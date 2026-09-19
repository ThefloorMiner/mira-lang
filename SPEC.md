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

### 2.2 Aucune syntaxe de durée de vie

Les durées de vie sont inférées et **ne sont jamais écrites**. Quand l'inférence échoue, le compilateur
n'exige pas une annotation : il propose les trois réparations canoniques — `own`, `clone`, ou une région.
Choix assumé : certains motifs zéro-copie exprimables en Rust ne le sont pas directement (§10).

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
block   = INDENT { stmt } DEDENT
```

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

Ensemble clos et court : `io`, `fs`, `net`, `clock`, `rand`, `env`, `proc`, `ffi`. Une fonction sans `+`
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
6. Tout item `pub` couvert par au moins un test, ou par un `test none: <raison>` explicite.
7. Tout bloc `raw` muni d'une ligne `safety:`.

### 5.2 Exemple d'obligations

```
$ mi seal src/wc.mi
O301 wc.mi:3:8   type-inconnu   text       fix:annotate str
O204 wc.mi:6:5   index-dyn      counts[w]  fix:upsert | get_or
O410 wc.mi:3:1   pub-non-teste  top        fix:add-test | test none:<raison>
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

## §10 — Ce qu'on abandonne volontairement

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
~90 % l'intersection Rust ∩ Python déjà connue ; (2) la spec entière tient sous 12 000 tokens ; (3) les
obligations et les `fix:` transforment l'apprentissage en boucle fermée.

Si la phase 0 montre que ça ne suffit pas, la bonne cible n'est pas un langage neuf mais un **dialecte** :
un sous-ensemble canonique de Rust doté de `mi api`, du format de diagnostic et de la porte de scellement.

---

## §11 — Plan & falsifiabilité

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
