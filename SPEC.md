# Mira — spécification v0.1

*Brouillon de travail. Aucun compilateur n'existe. Les estimations de §0 sont des hypothèses non mesurées.*

---

## §0 — Le modèle de coût

Avant toute décision de syntaxe, il faut dire ce qu'on minimise. La quantité n'est pas la longueur du
source, c'est l'espérance de tokens jusqu'au vert :

```
E[T] = T_écriture + Σᵢ P(échec à l'itération i) · (T_diagnostic + T_correction)
```

Deux conséquences désagréables pour l'intuition « mots-clés courts = moins de tokens » :

- **Les tokenizers BPE ont déjà fait le travail.** `else`, `return`, `fn`, `let`, `def` sont des tokens
  uniques dans les vocabulaires usuels. Écrire `el` ne gagne rien et peut coûter plus si la forme
  abrégée n'est pas dans le vocabulaire. Un glyphe rare (style APL) se décompose en plusieurs tokens
  d'octets : c'est un piège, pas une optimisation.
- **Une erreur coûte 10 à 100 fois un mot-clé.** Un diagnostic Rust illustré et son correctif, c'est
  300 à 800 tokens. Sur un programme de 40 lignes, trois allers-retours d'emprunt coûtent plus cher que
  l'intégralité du source.

> **Principe directeur — minimiser l'entropie, pas les caractères.**
> Le meilleur token est celui que le modèle aurait prédit de toute façon. Là où une forme familière et
> une forme courte s'opposent, Mira choisit la familière, et va chercher les tokens dans l'élision
> structurelle (§3.4), les diagnostics (§6) et la compression de contexte (§7).

### Leviers par ordre d'impact réel

| Levier | Mécanisme | Où va l'économie | Statut |
|---|---|---|---|
| Format de diagnostic | une ligne/erreur, cascades supprimées, budget plafonné (§6) | boucle d'erreur | hypothèse forte |
| Digest d'API | `mi api` : surface publique au lieu du source (§7) | lecture du dépôt | hypothèse forte |
| Zéro durée de vie | modes de paramètre + régions (§2) | P(échec) | hypothèse forte |
| Zéro import | bibliothèque ambiante (§3.5) | écriture + P(échec) | mesurable |
| Forme canonique unique | le formateur *est* la syntaxe (§3.6) | P(échec) | à mesurer |
| Inférence & élision | types locaux, `return` implicite, `case` supprimé | écriture | à mesurer |
| Mots-clés courts | sous contrainte « un seul token » | marginale | quasi nul |

---

## §1 — Les deux régimes

| | `draft` | `seal` |
|---|---|---|
| Exécution | VM à registres, démarrage < 10 ms | natif AOT (Cranelift / LLVM) |
| Types | inférés, `any` toléré | totalement statiques, `any` interdit |
| Mémoire | comptage de références + collecteur de cycles | propriété statique, libération déterministe |
| Emprunts | vérifiés à l'exécution | prouvés à la compilation |
| Effets | déduits, non exigés | déclarés dans la signature |
| Tests | facultatifs | obligatoires sur tout `pub` |
| Usage | explorer, prototyper, instrumenter | livrer |

> **Loi de cohérence.** Pour tout programme P qui scelle, `mi run P` et `mi build P` ont un comportement
> observable identique — au temps et à la mémoire près.

Le brouillon ne rejette jamais ce que le scellé accepte. Le scellé rejette ce que le brouillon accepte,
et l'écart est toujours restitué comme une liste finie d'*obligations*. La sémantique n'est jamais
négociée par le régime : seul le moment de la vérification change. Quand le brouillon rattrape à
l'exécution une faute que le scellé aurait vue statiquement, il la signale avec **le même code d'erreur**.

### Portée des marqueurs

```mira
seal mod payments        # tout le module est scellé

draft fn probe(x):       # exception locale, autorisée en build dev
  io.print(x.shape())    # rejetée par `mi seal`
```

Aux frontières mixtes (build dev seulement) l'appel traverse un *shim* contrôlé qui valide types et
propriété à l'entrée et à la sortie ; le blâme désigne le côté brouillon. En release, un item scellé ne
peut pas appeler un item brouillon : erreur `E401`.

---

## §2 — Mémoire

Rust est le langage où les LLM échouent le plus, et la cause est presque toujours la même : les
annotations de durée de vie et le choix `&`/`&mut`/move à chaque signature. Mira supprime les deux.

### 2.1 Modes de paramètre, pas de sigles

```mira
fn len(v: Vec[i32]) -> u32          # emprunt partagé — le défaut, zéro sigle
fn push(var v: Vec[i32], x: i32)    # emprunt exclusif
fn eat(own v: Vec[i32]) -> u32      # déplacement : v meurt ici
```

Trois modes, aucun symbole, et le mode majoritaire ne s'écrit pas. Le caractère `&` n'existe pas.

**Le mode d'une liaison de boucle est hérité, jamais écrit.** `for x in xs:` donne un `x` exclusif si
`xs` est `var`, partagé sinon. Quand la collection est une expression composée — `a.zip(b)`, un résultat
d'appel — le mode n'est pas conclu : le vérificateur s'abstient plutôt que de se tromper. C'est un faux
négatif assumé, et c'est le bon sens du compromis : un outil qui signale du code correct se fait
désactiver.

### 2.2 Aucune syntaxe de durée de vie

Les durées de vie sont inférées et **ne sont jamais écrites**. Quand l'inférence échoue, le compilateur
n'exige pas une annotation : il propose les trois réparations canoniques — `own`, `clone`, ou une région.
Choix assumé : certains motifs zéro-copie exprimables en Rust ne le sont pas directement (§14).

### 2.3 Régions

Une région est une arène : une seule durée de vie pour tout ce qu'elle contient, libérée d'un bloc à la
sortie. À l'intérieur, les valeurs se référencent librement — y compris en cycles.

```mira
seal fn eval(src: str) -> f64!:
  region a:
    let ast = parse_into(a, src)?  # les noeuds se pointent librement
    walk(ast)                      # f64 sort ; aucun emprunt ne s'échappe
```

Règle d'échappement : une valeur allouée dans `a` ne survit pas à `a`. Pour la faire sortir, `a.out(x)`
la recopie dans le propriétaire appelant — coût explicite, visible à la lecture.

### 2.4 La bascule de régime *est* la bascule mémoire

En `draft`, tout vit sur un tas compté par références avec collecteur de cycles : on écrit comme en
Python. Sceller remplace ce tas par la propriété statique et les régions — coût d'exécution nul, pas de
GC dans le binaire. Les obligations de scellement sont précisément la liste des endroits où le comptage
de références servait de béquille.

| Forme | Sémantique | Coût | Régime |
|---|---|---|---|
| `T` | possédé, unique, détruit en fin de portée | nul | les deux |
| `var T` / défaut | emprunt exclusif / partagé, prouvé | nul | les deux |
| `region` | arène, cycles permis, libération en bloc | un pointeur de bump | les deux |
| `rc T` | partage compté, mono-thread | incr/décr | les deux |
| `arc T` | partage compté atomique | atomiques | les deux |
| `raw` | pointeurs bruts, FFI | nul | `seal` + justification |

Un bloc `raw` sans ligne `safety:` ne scelle pas. La justification est du texte libre, non vérifiée —
mais son absence est une erreur, et sa présence rend l'audit humain possible sur du code écrit par une
machine.

### 2.5 Concurrence

Structurée et sans annotation : `Send`/`Sync` se déduisent de la propriété, jamais déclarés. Un emprunt
exclusif ne peut pas traverser une frontière parallèle ; la course de données est impossible en `seal`
et détectée à l'exécution en `draft`.

```mira
seal fn total(paths: Vec[Path]) -> u64! + fs:
  paths.par_map(p -> fs.read(p)?.len() as u64)?.sum()
```

---

## §3 — Syntaxe & lexique

Mise en page significative (prior Python), vocabulaire d'items (prior Rust), sémantique d'exécution
(prior C). ~90 % de la surface est l'intersection de ce que les modèles connaissent déjà.

### 3.1 Grammaire du noyau

```ebnf
item    = mode? ("fn" | "type" | "trait" | "impl" | "mod" | "err") …
mode    = "seal" | "draft"
fn      = mode? "fn" IDENT "(" params ")" ("->" type)? effects? ":" block
params  = [ param {"," param} ]
param   = pmode? IDENT ":" type          ; ":" type facultatif en draft
pmode   = "var" | "own"                  ; défaut = emprunt partagé
effects = "+" EFFECT { EFFECT }
type    = IDENT [ "[" type {"," type} "]" ] [ "?" ] [ "!" [type] ]
block   = INDENT { stmt } DEDENT | stmt          ; corps en ligne apres ':'
if_st   = "if" expr ":" block [ "else" ":" block ]  ; instruction : `else` facultatif
if_ex   = "if" expr ":" expr "else" ":" expr        ; expression : `else` obligatoire
postfix = primary { "." IDENT | call | index | "?" | "as" type
                  | "." "new" postfix }             ; allocation en region, §2.3
```

Ces trois productions viennent de l'amorce : écrire l'analyseur a révélé qu'elles manquaient. Le détail
et les deux corrections sémantiques qui ont suivi sont dans [`bootstrap/README.md`](bootstrap/README.md).

### 3.2 Règle de lexique

**Un mot-clé doit être un token unique dans les vocabulaires cibles, et un mot dont le modèle a un prior
fort.** On ne raccourcit jamais en dessous du token unique.

| Retenu | Rejeté | Raison |
|---|---|---|
| `fn` | `f`, `def` | un token ; prior Rust ; `def` évoque le dynamique |
| `else` | `el` | déjà un token — abréger ne gagne rien, perd le prior |
| `return` | `ret` | idem ; et l'usage est rare (§3.4) |
| `seal` / `draft` | `!` / `~` | mots repérables au grep, et libèrent les sigles |
| `var` / `own` | `&mut` / move implicite | mots courants, suppriment un sigle du langage |
| `->` | type nu à la Go | coûte un token, le rend en lisibilité — arbitrage assumé |
| `[T]` | `<T>` | pas d'ambiguïté avec la comparaison ; prior Python 3.12 |

### 3.3 Sigles, au complet

| Sigle | Position | Sens |
|---|---|---|
| `?` | suffixe de type | optionnel : `str?` |
| `?` | suffixe d'expression | propage l'erreur ou le `none` |
| `!` | suffixe de type | faillible : `u32!`, `u32!IoErr` |
| `+` | après le type de retour | liste d'effets |
| `#` | début de ligne | commentaire |
| `->` | signature / lambda | retour, et `x -> expr` |

Six sigles. Pas de `&`, pas de `*`, pas de `'a`, pas d'accolades de bloc (elles ne servent qu'aux
littéraux d'enregistrement et de table), pas de point-virgule, pas de `@`.

### 3.4 Élisions

- **La dernière expression est la valeur** ; `return` ne sert qu'aux sorties anticipées.
- **Pas de `case`** dans `match` : le motif seul ouvre le bloc.
- **Types locaux inférés** ; annotation exigée aux frontières `pub` seulement.
- **Champs abrégés** : `User{id, mail}` quand les noms coïncident.
- **Effets vides implicites** : pas de `+` ⇒ fonction pure.

### 3.5 Zéro ligne d'import

La bibliothèque standard est ambiante, qualifiée par module : `str.split`, `fs.read`, `json.parse`,
`io.print`. Les dépendances externes sont déclarées une fois dans `mi.toml` et deviennent ambiantes sous
leur nom de paquet. **Aucun fichier Mira ne contient de ligne d'import.** Cela supprime 30 à 80 tokens
par fichier et la première cause d'erreur des LLM : le chemin d'import halluciné.

*Contrepartie :* des noms ambiants nuisent à la lisibilité quand ils prolifèrent. Mitigation : la
qualification est obligatoire hors d'un prélude de ~40 noms, et `mi api` donne la surface exacte.

### 3.6 La forme canonique est la syntaxe

`mi fmt` n'est pas un outil de style. Il n'existe qu'une seule écriture valide de chaque programme : pas
de parenthèses facultatives, pas de choix de virgule finale, pas d'alignement discrétionnaire. Un fichier
non canonique est réécrit à la compilation, sans erreur. Moins de variantes ⇒ moins d'entropie ⇒ moins de
tokens *et* moins d'erreurs.

---

## §4 — Types, erreurs, effets

Pas d'exceptions, pas d'héritage, pas de conversion implicite. Les erreurs sont des valeurs, les effets
sont dans la signature.

```mira
type User = {id: u64, mail: str?}
err Db = Missing | Corrupt(str)

fn find(id: u64) -> User!Db + fs:
  let row = db.get(id)?           # propage l'erreur
  let mail = row.mail or "—"      # valeur par défaut sur none
  User{id, mail}

match find(7):
  ok u:            io.print(u.mail)
  err Missing:     io.print("inconnu")
  err Corrupt(m):  log.warn(m)
```

### 4.1 Effets

Ensemble clos et court : `io`, `fs`, `net`, `clock`, `rand`, `env`, `proc`, `task` (§11), `gpu` (§12), `ffi`. Une fonction sans `+`
est pure : déterministe, parallélisable, testable par propriété gratuitement.

```mira
fn parse(s: str) -> Json!          # pure
fn fetch(u: Url) -> Bytes! + net   # effet déclaré
fn log(m: str) + io
```

Deux bénéfices qui comptent quand le code est écrit par une machine : le bac à sable applique exactement
les effets déclarés, et la revue humaine se réduit à lire les signatures.

### 4.2 Traits

Conformité nominale, `trait` / `impl X for T`. Pas de conformité structurelle : le diagnostic « ce type
n'implémente pas `X` » est plus court et plus actionnable. Les macros arbitraires n'existent pas ; seules
des dérivations fermées (`derive Eq Hash Json`) sont admises — une macro qui invente de la syntaxe
détruit les priors du modèle *et* la fiabilité de `mi api`.

---

## §5 — Tests & porte de scellement

```mira
fn norm(s: str) -> str:
  s.trim().lower()

test norm:
  norm(" Hi ") == "hi"                     # expression nue = assertion
  prop s: str -> norm(norm(s)) == norm(s)  # idempotence, fuzzée, graine fixe
```

Une expression nue dans un bloc `test` est une assertion. `prop` déclare une propriété ; les entrées sont
générées, la graine enregistrée, un contre-exemple automatiquement réduit et réécrit dans le bloc comme
cas de régression.

### 5.1 Ce que `mi seal` exige

1. Aucun item `draft` atteignable.
2. Tous les types résolus ; aucun `any`.
3. Propriété, emprunts et échappement de région prouvés.
4. Effets déclarés exacts (ni manquants, ni en trop).
5. Tous les tests au vert, graines comprises.
6. Tout item `pub` couvert par au moins un test, ou par une dérogation explicite
   `test f: "raison"` — un bloc `test` dont le corps est une seule chaîne littérale.
7. Tout bloc `raw` muni d'une ligne `safety:`.

### 5.2 Exemple d'obligations

```
$ mi seal src/wc.mi
O301 wc.mi:3:8   type-inconnu   text       fix:annotate str
O204 wc.mi:6:5   index-dyn      counts[w]  fix:upsert | get_or
O410 wc.mi:3:1   pub-non-teste  top        fix:add-test | waive
3 obligations · 0 erreurs · sealed=no
```

Une obligation n'est pas une erreur : le programme tourne. C'est une liste de travail finie, ordonnée,
directement consommable — c'est elle qui rend la boucle « brouillon → scellé » bornée.

---

## §6 — Diagnostics comme API

La sortie du compilateur retourne dans le contexte du modèle. Elle fait donc partie du budget de tokens
du langage — et c'est le poste le plus lourd.

```
$ mi build --diag=llm --budget=2k
E204 src/pay.mi:31:9  valeur-deplacee v (deplacee 28:5)  fix:own | clone | region
E512 src/pay.mi:44:3  effet net non declare sur charge   fix:+net
2 erreurs · 3 cascades supprimees · mi explain E204
```

### 6.1 Règles du format `llm`

- **Une ligne par erreur**, jamais de rappel du source : le modèle a déjà le fichier.
- **Codes stables** et versionnés : un code ne change jamais de sens.
- **Réparations nommées** dans `fix:` — vocabulaire fermé, pas de prose.
- **Racine d'abord** : les cascades sont supprimées et seulement comptées.
- **Budget plafonné** (2 000 tokens par défaut).
- **Explication en tirage** : `mi explain E204` donne la version longue à la demande.

### 6.2 Familles de codes

| Plage | Famille | Réparations canoniques |
|---|---|---|
| `E1xx` | lexique, mise en page, forme canonique | `fmt` |
| `E2xx` | propriété, emprunts, échappement de région | `own` · `clone` · `region` · `rc` |
| `E3xx` | types, motifs non exhaustifs | `annotate` · `arm` · `as` |
| `E4xx` | régimes et obligations de scellement | `add-test` · `seal` · `test none` |
| `E5xx` | effets et capacités | `+effet` · `pure` |
| `O***` | obligations (non bloquantes en draft) | idem, mêmes codes |

`mi fix E204@31` applique la réparation quand elle est unique et mécanique. Sinon il refuse plutôt que de
deviner — un correctif faux coûte deux itérations, pas zéro.

---

## §7 — Compression de contexte

Écrire du code coûte des tokens. *Lire le dépôt* en coûte dix fois plus. C'est le poste que personne
n'optimise.

```
$ mi api payments
mod payments + net
  Card{num: str, exp: Date}
  TxId = u64
  err Pay = Declined | Network | Invalid
  fn charge(c: Card, cents: u32) -> TxId!Pay + net
  fn refund(t: TxId) -> Unit!Pay + net
# 5 items · 71 tokens · sha 9f2c1b
```

| Commande | Rend | Usage |
|---|---|---|
| `mi api MOD` | surface publique d'un module | appeler du code existant |
| `mi api --deps` | surface transitive du projet | amorcer une session |
| `mi ctx SYM` | définition + appelants + tests, budgété | modifier un symbole |
| `mi why SYM` | chaîne d'appels et d'effets jusqu'à la racine | comprendre un effet inattendu |
| `mi diff --api` | ce qui a changé *dans la surface* | revue, compatibilité |

Le `sha` rend le digest citable : un agent peut affirmer « écrit contre l'API `9f2c1b` » ; si la surface
a bougé, `mi diff --api` dit exactement quoi.

C'est la conséquence directe de §4.1 : parce que les effets sont dans la signature et que les macros
n'inventent pas de syntaxe, le digest est **fidèle**.

---

## §8 — Chaîne d'outils

| Commande | Effet |
|---|---|
| `mi new N` | crée `mi.toml` + `src/main.mi` ; aucune autre question posée |
| `mi run F` | exécute sur la VM (draft), démarrage < 10 ms |
| `mi test` | tests + propriétés, graines rejouables, sortie budgétée |
| `mi seal` | liste les obligations ; ne produit rien tant qu'il en reste |
| `mi build` | binaire natif ; refuse si `mi seal` n'est pas vert |
| `mi fmt` | réécrit en forme canonique (implicite à chaque build) |
| `mi api` · `mi ctx` · `mi why` | compression de contexte (§7) |
| `mi fix CODE@LIG` | applique la réparation canonique, ou refuse |
| `mi explain CODE` | version longue d'un diagnostic, à la demande |
| `mi bind h.h` | génère les déclarations FFI depuis un en-tête C |

Le bac à sable est branché sur les effets : `mi run --allow fs` refuse au démarrage tout module déclarant
`net`. Faire tourner du code fraîchement généré devient une décision explicite et vérifiable.

---

## §9 — Interop & cibles

- **C** — ABI C dans les deux sens, effet `ffi` obligatoire, déclarations générées par `mi bind`.
- **Python** — `mi py` expose un module scellé comme extension CPython. Dans l'autre sens, `py.call`
  existe en `draft` uniquement : un module qui l'utilise ne scelle pas.
- **Cibles** — natif (Cranelift en dev, LLVM en release), WASM, et la VM de brouillon comme cible portable.
- **Sans runtime** — un binaire scellé n'embarque ni GC ni comptage de références, sauf `rc`/`arc` explicites.

---

## §10 — Performance : le contrat C

« Aussi rapide que le C » n'est pas une phrase qu'on écrit dans un README, c'est un contrat qui s'arrache
clause par clause. Voici les clauses, et le seuil qui donne le droit d'écrire la phrase.

### 10.1 Ce que le binaire scellé n'embarque pas

- **Aucun ramasse-miettes**, aucun compteur de références — sauf `rc`/`arc` écrits explicitement.
- **Aucun déroulement de pile.** Les erreurs sont des valeurs (§4) : pas de tables d'exception, pas de
  *landing pad*, aucun coût sur le chemin heureux. Avantage déjà acquis sur C++ et sur Rust `panic=unwind`.
- **Aucune initialisation de runtime.** Le point d'entrée est `main`, pas un préambule qui monte un tas managé.
- **Aucun code de test.** Les blocs `test` et `prop` sont retirés en release.

### 10.2 Représentation mémoire prévisible

| Type Mira | Représentation | Équivalent C |
|---|---|---|
| `type P = {x: f64, y: f64}` | disposition déclarée, sans en-tête, sans réordonnancement | `struct P { double x, y; }` |
| `Vec[T]` | trois mots : pointeur, longueur, capacité | `T*` + deux `size_t` |
| `str` | deux mots : pointeur, longueur — UTF-8, *non* terminé par zéro | `char*` + `size_t` |
| `T?` | niche quand il en existe une, sinon un mot de discriminant | `T*` nullable |
| `fn f[T](…)` | monomorphisé par instanciation | macro ou code dupliqué |
| `dyn Trait` | pointeur gras — **seulement si écrit** | pointeur + table de fonctions |

La répartition dynamique n'arrive jamais par accident : un `trait` employé génériquement est monomorphisé,
il faut écrire `dyn` pour payer une table de fonctions. Une signature dit son coût, et `mi api` le montre.

### 10.3 Zéro vérification implicite — obtenu par la porte de scellement

Clause la plus difficile, résolue par un mécanisme que le langage a déjà. Rust paie un contrôle de bornes
sur `v[i]` et vous ne le voyez jamais passer. Mira n'en paie aucun — parce qu'en régime scellé, **une
indexation non prouvée n'est pas compilée avec un garde : elle est une obligation.**

```
$ mi seal
O220 img.mi:14:11  index-non-prouve  px[i]    fix:for-in | get | assert-range
O221 img.mi:21:5   arith-non-prouve  a * b    fix:wrap | sat | try
O222 img.mi:28:9   div-non-prouve    n / d    fix:assert | try
3 obligations · 0 erreurs · sealed=no
```

| Issue | Ce qu'on écrit | Coût |
|---|---|---|
| L'analyse de plages le prouve | rien | nul — le garde n'est jamais émis |
| Parcourir au lieu d'indexer | `for x in v:`, `v.windows(3)` | nul, par construction |
| Rendre l'accès total | `v.get(i)` qui rend `T?` | un test que vous avez écrit, et que vous voyez |
| Affirmer une fois pour un bloc | `assert i < v.len()` en tête de boucle | un test, hors de la boucle chaude |

**La différence avec Rust n'est pas la vitesse du code généré, c'est la visibilité.** Dans les deux
langages le code final peut être identique ; en Rust, savoir si le garde a survécu demande de lire
l'assembleur. En Mira, le garde n'existe pas : soit c'est prouvé, soit c'est une ligne dans la liste
d'obligations. La performance devient une propriété qu'on lit dans la sortie de `mi seal`.

### 10.4 Arithmétique, sans violer la loi de cohérence

C enroule en silence, et c'est pour ça qu'il est rapide. Mira enroule aussi : `+`, `-`, `*` sur les
entiers compilent vers l'instruction machine nue, sans contrôle de débordement. Les variantes explicites
existent — `a.sat_add(b)`, `a.try_add(b) -> u32!`.

Comment attraper un débordement en développement sans casser la loi de cohérence de §1 ? **Le régime
brouillon instrumente, il ne change jamais les résultats.** `mi run` détecte le débordement, l'enregistre,
le signale à la sortie — et produit exactement la même valeur enroulée que le binaire scellé. Le
comportement observable est identique ; seul s'ajoute un canal d'observation.

```
$ mi run
resultat: 42
3 debordements observes · u32 mul · hash.mi:21  (valeurs inchangees)
```

### 10.5 Là où Mira peut dépasser le C

Trois endroits, conséquences directes de §2 :

- **Non-aliasing gratuit.** Un `var` est un emprunt exclusif prouvé : le compilateur émet `noalias` sur
  chaque paramètre mutable, partout, sans que personne n'écrive `restrict`. En C, deux pointeurs peuvent
  toujours se recouvrir et l'optimiseur doit supposer le pire.
- **Les régions battent `malloc`.** Une `region` alloue par déplacement d'un pointeur et libère en un seul
  geste. Sur un parseur ou un graphe (§2.3), c'est structurellement plus rapide qu'une suite de
  `malloc`/`free`, et ça élimine la fragmentation.
- **La pureté ouvre des portes fermées au C.** Une fonction sans `+` est déterministe : évaluable à la
  compilation, mise en cache, vectorisable ou parallélisable sans analyse d'alias. Un compilateur C doit
  *prouver* l'absence d'effets ; Mira la lit dans la signature.

### 10.6 Les échappatoires

Quand la preuve coûte plus cher que le risque, `raw` donne les pointeurs bruts, l'arithmétique de
pointeurs et les intrinsèques SIMD — en régime scellé uniquement, et toujours avec une ligne `safety:`
sans laquelle le module ne scelle pas (§2.4). `ffi` appelle du C existant à coût nul : même ABI, même
disposition, aucune conversion.

> **Le contrat, mesurable.** Un binaire scellé doit tenir dans ±5 % de `clang -O2` sur au moins 10 des 12
> micro-bancs du panier, et ne jamais dépasser +20 % sur aucun. Panier : `binary-trees`, `n-body`,
> `mandelbrot`, `fasta`, `regex-redux`, `json-parse`, `memcpy-loop`, `hashmap-churn`, `sort-1e7`,
> `matmul-512`, `tcp-echo`, `terminal-io`. Tant que ce seuil n'est pas atteint, la phrase « aussi rapide
> que le C » ne s'écrit ni dans le README, ni dans cette spec — on écrit le chiffre mesuré à la place.
> Même discipline que le critère d'abandon de §15 : une affirmation de performance sans banc est une
> affirmation fausse.

---

## §11 — Concurrence

La décision la plus lourde de cette section est une soustraction : **Mira n'a ni `async` ni `await`.**
La coloration de fonctions est la première cause d'erreur des modèles en Rust et en JavaScript, et elle
contamine chaque signature qu'elle touche.

### 11.1 Deux choses distinctes, et une seule est un effet

```mira
fn total(paths: Vec[Path]) -> u64! + fs:          # parallèle, et pourtant sans effet `task`
  paths.par_map(p -> fs.read(p)?.len() as u64)?.sum()

fn serve(port: u16) -> Unit! + net task:          # concurrent : l'ordonnancement est observable
  par:
    for conn in net.listen(port)?:
      spawn handle(conn)
```

`par_map` sur une fermeture pure rend le même résultat quel que soit l'ordonnancement : c'est une
optimisation, pas un effet, et la signature n'en porte aucune trace. `spawn`, les canaux et les verrous
rendent l'ordre observable : c'est l'effet **`task`**, neuvième de l'ensemble clos de §4.1.

*Conséquence pratique :* une fonction pure reste parallélisable gratuitement, et `mi api` montre d'un
coup d'œil quels modules introduisent du non-déterminisme. Sur du code écrit par une machine, c'est la
différence entre un test rejouable et un test qui échoue un jour sur cent.

### 11.2 Portées structurées : aucune tâche détachée

`par:` ouvre une portée. Toute tâche lancée dedans est jointe — ou annulée — au dédentage, sans
exception. Il n'existe aucune façon de détacher une tâche, donc aucune façon d'en oublier une.

```mira
let (tx, rx) = chan[Job](64)     # la capacité est obligatoire : pas de canal non borné

par:
  spawn produce(tx)              # une erreur dans une tâche annule ses soeurs
  for j in rx:                   # et remonte au dédentage
    handle(j)?
```

Un canal non borné est une fuite mémoire qui attend son jour de charge ; exiger la capacité coûte trois
caractères et supprime une classe entière d'incidents.

### 11.3 L'état partagé appartient à son verrou

Par défaut rien n'est partagé : on déplace les données dans la tâche avec `own`. Quand il faut vraiment
partager, le verrou *possède* la donnée — il n'existe aucun chemin d'accès qui ne passe pas par lui.

```mira
let hits = mutex(0)

with hits as var n:              # verrou tenu pour le bloc, relâché au dédentage
  n += 1                         # aucune façon d'atteindre n sans ce `with`
```

`arc T` pour le partage immuable, `atom[u64]` pour les compteurs. `Send` et `Sync` ne s'écrivent jamais :
ils se déduisent de la propriété (§2.5).

### 11.4 L'ordre des verrous, vérifié

L'absence d'interblocage est indécidable en général. Une approximation conservatrice ne l'est pas :
chaque verrou reçoit un rang statique de son site de déclaration, et prendre un rang inférieur alors
qu'on en tient un supérieur devient une obligation de scellement.

```
$ mi seal
O230 srv.mi:44:5  ordre-de-verrous  cache(2) pris sous db(5)  fix:reorder | merge | rank
1 obligation · 0 erreurs · sealed=no
```

C'est la discipline des noyaux, rarement offerte dans un langage applicatif. Elle rejette des programmes
corrects — d'où les trois réparations, dont `rank` qui déclare un ordre explicite.

### 11.5 Fils verts, et la réconciliation avec §10

Les tâches sont des fils verts multiplexés M:N. Une opération d'E/S bloque la tâche, jamais le fil
système : on écrit du code séquentiel, il s'exécute de façon concurrente, et aucune signature n'est
colorée.

> **Cela contredit-il « aucune initialisation de runtime » (§10.1) ? Non, et le détail compte.**
> L'ordonnanceur est une bibliothèque, pas un runtime de langage : un programme dont aucune fonction ne
> déclare `task` ne le lie pas, et son binaire est exactement aussi nu qu'un binaire C. Un programme
> concurrent lie l'ordonnanceur comme un programme C lie `pthreads`. Le système d'effets rend cette
> propriété vérifiable plutôt que promise.

**Le prix, énoncé :** un appel FFI bloquant ne peut pas être suspendu par l'ordonnanceur. La tâche est
alors épinglée à un fil système le temps de l'appel, ce qui consomme un fil du pool. C'est le coût réel
du choix « pas de coloration », et il se paie sur les frontières C, pas dans le code Mira.

---

## §12 — Graphique

Une spec v0.1 n'a pas à inventer une boîte à outils d'interface. Ce qu'elle doit trancher, c'est le
modèle mémoire de part et d'autre de la frontière CPU–GPU — parce que c'est là que la propriété a
quelque chose à dire, et que personne d'autre ne le dit.

### 12.1 Un tampon GPU est une région

Une région, c'est « une seule durée de vie, libérée en bloc » (§2.3). Un tampon GPU, c'est exactement ça,
avec un autre allocateur. Le concept se réutilise tel quel au lieu d'en inventer un deuxième.

```mira
fn frame(var w: Window, t: f32) -> Unit! + gpu:
  region f on gpu:                    # arène de trame, en mémoire périphérique
    let verts = f.new Mesh(scene(t))  # même règle d'échappement qu'en §2.3
    w.draw(verts, tint, 0.8)          # libérée entièrement au dédentage
```

Conséquence directe pour le temps réel : l'arène de trame se libère d'un seul geste à chaque image. Pas
de ramasse-miettes, pas de pauses, pas de fragmentation — la discipline que les moteurs de jeu
appliquent à la main, ici portée par le langage.

### 12.2 La mémoire projetée est un emprunt exclusif

Écrire depuis le CPU dans un tampon que le GPU est en train de lire est une classe de bug entière,
silencieuse et pénible à reproduire. C'est aussi, littéralement, un emprunt exclusif violé — donc le
vérificateur de §2 l'attrape sans rien apprendre de nouveau.

```mira
with buf.map() as var bytes:     # emprunt exclusif du tampon, borné au bloc
  bytes.fill(0)                  # le GPU ne peut pas y toucher pendant ce temps
```

```
$ mi seal
E240 draw.mi:12:3  tampon-en-vol  buf (soumis 9:5)  fix:with-map | double-buffer
1 erreur · sealed=no
```

### 12.3 Les nuanceurs s'écrivent en Mira

Un troisième marqueur de régime, après `draft` et `seal` : `gpu`. La fonction est compilée vers SPIR-V et
restreinte à un sous-ensemble pur — aucune allocation, aucun effet, aucune récursion, aucune boucle non
bornée. Les violations sortent en obligations, comme le reste.

```mira
gpu fn tint(px: vec4, k: f32) -> vec4:
  px * k
```

Le bénéfice est celui de tout le langage : **une seule syntaxe**. Pas de WGSL en chaîne de caractères,
pas de second jeu de priors à acquérir pour le modèle, et `mi api` couvre les nuanceurs comme le reste.

### 12.4 Ce qui est dans le langage et ce qui ne l'est pas

| Couche | Où elle vit | Effet |
|---|---|---|
| Régions GPU, projection, `gpu fn` | dans le langage | `gpu` |
| `gpu` — sémantique WebGPU sur Vulkan, Metal, D3D12, WASM | bibliothèque de base | `gpu` |
| `win` — fenêtres, entrées, écrans | paquet | `gpu io` |
| `ui` — widgets, mise en page, texte | paquet, **hors v0.1** | `gpu io` |

Le choix de WebGPU n'est pas esthétique : c'est la seule abstraction portable qui couvre les trois API
natives *et* la cible WASM déjà présente en §9. Un même binaire de rendu vise le bureau et le navigateur.

---

## §13 — Bibliothèque de base

Comme il n'y a pas d'imports (§3.5), la bibliothèque est ambiante — donc sa carte n'est pas de la
documentation, c'est la surface du langage.

### 13.1 Noyau pur : aucun effet, toujours disponible

| Module | Contenu |
|---|---|
| `str` | découpage, recherche, casse, normalisation Unicode, greffons |
| `vec` `map` `set` `deque` | collections ; `Map` et `Set` ordonnés par insertion |
| `iter` | paresseux : `map` `filter` `fold` `zip` `windows` `chunks` `par_map` |
| `sort` `cmp` | tri stable, ordres, `min_by` / `max_by` |
| `num` `math` `bit` | entiers et flottants, saturation, trigonométrie, opérations binaires |
| `bytes` `enc` `hash` | tampons, base64, hexadécimal, SHA-2, BLAKE3, hachage non cryptographique |
| `fmt` | formatage ; le moteur derrière `"{x:>5}"` |
| `json` `csv` `toml` | analyse et sérialisation, via `derive Json` |
| `re` | expressions régulières, automate fini — pas de retour arrière, temps linéaire garanti |
| `time` | durées, instants, calendrier — *pure* ; lire l'heure est un effet (`clock`) |
| `vec2` `vec4` `mat4` | algèbre linéaire courte, partagée avec `gpu fn` (§12.3) |

### 13.2 Modules à effet

| Module | Contenu | Effet |
|---|---|---|
| `io` | entrée et sortie standard, terminal | `io` |
| `log` | journalisation structurée, niveaux | `io` |
| `fs` | fichiers, répertoires, `glob`, surveillance | `fs` |
| `net` `http` | TCP, UDP, TLS ; client et serveur HTTP | `net` |
| `clock` | heure courante, minuteries, sommeil | `clock` |
| `rand` | aléatoire cryptographique et ensemencé | `rand` |
| `env` | arguments, variables d'environnement | `env` |
| `proc` | sous-processus, signaux, code de retour | `proc` |
| `chan` `mutex` `atom` | concurrence (§11) | `task` |
| `gpu` | rendu, sémantique WebGPU (§12) | `gpu` |
| `ffi` | appel de C, pointeurs bruts | `ffi` |

> **Dix effets, et c'est fermé :** `io fs net clock rand env proc task gpu ffi`. Un module de base ne peut
> pas en introduire un onzième — sinon `mi run --allow` (§8) cesserait d'être une garantie et redeviendrait
> une convention.

### 13.3 Ce qui n'est pas dans la base

Paquets, déclarés dans `mi.toml`, ambiants sous leur nom : bases de données, gRPC, images, audio, `win`,
`ui`. La règle de partage est simple — **la base contient ce dont le compilateur, les tests et `mi api`
ont besoin pour fonctionner**, plus ce qu'on ne peut pas raisonnablement demander à chacun de réécrire.

La bibliothèque de base est elle-même écrite en Mira et scellée. Deux conséquences : `mi api` fonctionne
dessus comme sur n'importe quel module, et elle constitue le premier corpus de référence — celui sur
lequel se mesure la phase 1 de §15.

---

## §14 — Ce qu'on abandonne volontairement

Une spec qui ne liste pas ses renoncements n'est pas une spec, c'est une brochure.

- **Des motifs zéro-copie exprimables en Rust sont inaccessibles.** Sans syntaxe de durée de vie,
  certaines structures empruntées à travers des frontières complexes exigent une région ou une copie.
  C'est le prix direct de §2.2, et le renoncement le plus coûteux.
- **Pas d'exceptions, pas d'héritage, pas de surcharge d'opérateurs** hors d'un jeu fixe, pas de
  conversion implicite.
- **Pas de macros arbitraires** — elles détruisent les priors du modèle et rendent `mi api` menteur.
- **Une seule forme d'écriture** : pas de DSL interne, pas d'expressivité stylistique.
- **Modèle mémoire mixte à assumer** : régions + `rc` + propriété, trois disciplines à tenir.

**Le vrai risque, qui domine tous les autres : un langage neuf a zéro donnée d'entraînement.** Un modèle
écrit du Python correct parce qu'il en a lu des milliards de lignes. Atténuations : (1) la surface est à
~90 % l'intersection Rust ∩ Python déjà connue ; (2) la spec entière pèse ≈ 11 500 tokens, donc elle rentre dans le contexte — mais le budget est presque épuisé, et toute section ajoutée devra en retirer une autre ; (3) les
obligations et les `fix:` transforment l'apprentissage en boucle fermée.

Si la phase 0 montre que ça ne suffit pas, la bonne cible n'est pas un langage neuf mais un **dialecte** :
un sous-ensemble canonique de Rust doté de `mi api`, du format de diagnostic et de la porte de scellement.

---

## §15 — Plan & falsifiabilité

**Phase 0 — le banc, avant le langage.** Un harness qui mesure le coût en tokens de chaque lexème candidat
sur les vocabulaires cibles, et une suite de 100 tâches avec la métrique *tokens-jusqu'au-vert*, mesurée
d'abord sur Python et Rust pour fixer les lignes de base. Deux semaines. C'est ce qui rend tout le reste
réfutable.

**Phase 1 — régime brouillon seul.** Parseur, VM à registres, tas RC + collecteur de cycles, écrits en
Rust. Livre `mi run`, `mi test`, `mi fmt` et — dès le premier jour — `mi api`.

**Phase 2 — régime scellé.** Vérificateur de propriété et de régions, inférence des durées de vie, dorsale
Cranelift, `mi seal` et la liste d'obligations. La loi de cohérence (§1) devient une suite de tests
différentiels.

**Phase 3 — surface d'outillage.** `mi fix`, `mi explain`, `mi ctx`, LSP, bac à sable d'effets, WASM, `mi bind`.

> **Critère d'abandon.** Si, à la fin de la phase 2, Mira ne bat pas Python sur *tokens-jusqu'au-vert* à
> fiabilité égale, la thèse est fausse et le projet s'arrête. Pas « on ajuste la syntaxe » : ce qui reste
> de valeur se rétro-porte sur un langage existant, et c'est un meilleur résultat qu'un langage de plus.
