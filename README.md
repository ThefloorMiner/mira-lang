# Mira

**Un langage à deux régimes : on écrit en brouillon, on livre sous scellé.**

> **EN — TL;DR.** Mira is a language design optimised for code written by LLMs. Its metric is not source
> length but *expected tokens to a verified-correct program* — error loops included. It borrows Python's
> layout, Rust's ownership semantics and C's execution model, and carries a per-module marker selecting
> one of two regimes: `draft` (interpreted, refcounted, nothing proved) or `seal` (AOT-compiled, fully
> proved, tests mandatory). **No compiler exists yet — this repository is a specification.**

---

## Statut

⚠️ **Il n'existe aucun compilateur.** Ce dépôt contient une spécification, un guide et des programmes
d'exemple qui décrivent le comportement *spécifié*. Rien n'est exécutable aujourd'hui. La phase 0
(§12 de la spec) construit le banc de mesure qui validera — ou enterrera — la thèse.

| | |
|---|---|
| **Spécification** | [`SPEC.md`](SPEC.md) — le *pourquoi*, 12 sections |
| **Guide** | [`GUIDE.md`](GUIDE.md) — le *comment*, trois programmes complets |
| **Exemples** | [`examples/`](examples/) — bonjour, wordcount, deps |

---

## La thèse en un paragraphe

L'intuition courante — « raccourcissons les mots-clés pour économiser des tokens » — est le plus petit
levier possible, et il peut se retourner contre vous. `else`, `return`, `fn`, `let` sont déjà des tokens
uniques dans les vocabulaires BPE : écrire `el` ne gagne rien. Un glyphe rare se décompose en plusieurs
tokens d'octets. Pendant ce temps, **un seul aller-retour de diagnostic coûte 300 à 800 tokens**.

La quantité à minimiser est donc :

```
E[T] = T_écriture + Σᵢ P(échec à l'itération i) · (T_diagnostic + T_correction)
```

D'où le principe directeur : **minimiser l'entropie, pas les caractères.** Le meilleur token est celui
que le modèle aurait prédit de toute façon. Les gains réels viennent d'ailleurs — les diagnostics, la
compression de contexte, et la suppression des constructions où les modèles échouent.

### Les leviers, par ordre d'impact réel

| Levier | Mécanisme | Statut |
|---|---|---|
| Format de diagnostic | une ligne par erreur, cascades supprimées, budget plafonné | hypothèse forte |
| Digest d'API | `mi api` : la surface publique au lieu du source | hypothèse forte |
| Zéro durée de vie | modes de paramètre + régions | hypothèse forte |
| Zéro import | bibliothèque ambiante | mesurable |
| Forme canonique unique | le formateur *est* la syntaxe | à mesurer |
| Mots-clés courts | sous contrainte « un seul token » | **quasi nul** |

Aucun de ces chiffres n'est mesuré à ce jour.

---

## Hello world

```mira
fn main() + io:
  io.print("hello, monde")
```

Pas d'`import`, pas de `#include`, pas de point-virgule, pas d'accolade. Mais **une chose en plus** :
`+ io`. Sans cette déclaration d'effet, `io.print` est refusé à la compilation. Une fonction Mira ne peut
pas toucher au monde extérieur en cachette — et c'est ce qui rend le bac à sable possible.

## Les deux régimes

```mira
draft mod wordcount              seal mod wordcount

pub fn top(text, n):             pub fn top(text: str, n: u32) -> Vec[(str, u32)]:
  counts = {}                      var counts: Map[str, u32] = {}
  for w in text.split():           for w in text.split():
    counts[w] = …                    counts.upsert(w, 0, c -> c + 1)
```

| | `draft` | `seal` |
|---|---|---|
| Exécution | VM à registres, < 10 ms | natif AOT |
| Mémoire | comptage de références + cycles | propriété statique |
| Emprunts | vérifiés à l'exécution | prouvés à la compilation |
| Tests | facultatifs | obligatoires sur tout `pub` |

**Loi de cohérence** — pour tout programme qui scelle, `mi run` et `mi build` ont un comportement
observable identique. Le brouillon ne rejette jamais ce que le scellé accepte ; le scellé rejette ce
que le brouillon accepte, et l'écart est **toujours** restitué comme une liste finie d'obligations :

```
$ mi seal
O301 wordcount.mi:3:12  type-inconnu   text       fix:annotate str
O204 wordcount.mi:5:5   index-dyn      counts[w]  fix:upsert | get_or
O410 wordcount.mi:3:1   pub-non-teste  top        fix:add-test
3 obligations · 0 erreurs · sealed=no
```

Une obligation n'est pas une erreur : le programme tourne pendant tout ce temps. C'est ce qui rend la
boucle « brouillon → scellé » **bornée** au lieu d'être une négociation.

## Mémoire : aucune annotation de durée de vie, jamais

Trois modes de paramètre, des mots anglais, et le cas majoritaire ne s'écrit pas :

```mira
fn len(v: Vec[i32]) -> u32          # emprunt partagé — le défaut, zéro sigle
fn push(var v: Vec[i32], x: i32)    # emprunt exclusif
fn eat(own v: Vec[i32]) -> u32      # déplacement
```

Le caractère `&` n'existe pas dans le langage. Pour les graphes et les cycles — là où la propriété
linéaire fait le plus souffrir — on ouvre une région :

```mira
region g:
  var nodes = mods.map(m -> g.new Node{name: m.name, out: []})
  …                                  # les noeuds se pointent librement, cycles compris
  err Cycle(g.out(path))             # g.out : promouvoir hors de la région
```

Sans `g.out`, le vérificateur refuse en une ligne :

```
E211 deps.mi:24:18  echappement-region  path (alloue dans g:16)  fix:g.out | own
```

## Compression de contexte

Le poste que personne n'optimise : **lire** le dépôt coûte dix fois plus que l'écrire.

```
$ mi api deps
mod deps + fs
  Mod{name: str, uses: Vec[str]}  derive Eq Json
  err Deps = IoErr | Cycle(Vec[str])
  pub fn scan(root: Path) -> Vec[Mod]!Deps + fs
  pub fn check(mods: Vec[Mod]) -> Unit!Deps
# 4 items · 58 tokens · sha b71c04
```

58 tokens pour un module de 200 lignes. Et `check` n'affiche aucun effet : on sait, sans lire une ligne
de corps, qu'il ne touche ni au disque ni au réseau.

---

## Plan

| Phase | Contenu | Sortie |
|---|---|---|
| **0** | Banc de mesure : coût en tokens par lexème, suite de 100 tâches, métrique *tokens-jusqu'au-vert*, lignes de base Python et Rust | la thèse devient réfutable |
| **1** | Régime brouillon : parseur, VM à registres, tas RC + collecteur de cycles, `mi run/test/fmt/api` | premier gain testable |
| **2** | Régime scellé : vérificateur de propriété et de régions, dorsale Cranelift, `mi seal` | loi de cohérence testée |
| **3** | `mi fix`, `mi explain`, `mi ctx`, LSP, bac à sable, WASM | surface d'outillage |

### Critère d'abandon

Si, à la fin de la phase 2, Mira ne bat pas Python sur *tokens-jusqu'au-vert* à fiabilité égale, **la
thèse est fausse et le projet s'arrête.** Ce qui reste de valeur — le format de diagnostic, le digest
d'API, la porte de scellement — se rétro-porte sur un langage existant, et c'est un meilleur résultat
qu'un langage de plus.

## Le risque principal

Un langage neuf a **zéro donnée d'entraînement**. Un modèle écrit du Python correct parce qu'il en a lu
des milliards de lignes ; aucune élégance de design ne compense ça à court terme. Trois atténuations,
par ordre d'efficacité : la surface est à ~90 % l'intersection Rust ∩ Python déjà connue ; la spec
entière tient sous 12 000 tokens, donc elle rentre dans le contexte ; les obligations et les `fix:`
transforment l'apprentissage en boucle fermée plutôt qu'en devinette.

Si ça ne suffit pas, la conclusion honnête est que la bonne cible n'est pas un langage neuf mais un
**dialecte** : un sous-ensemble canonique de Rust doté de `mi api`, du format de diagnostic et de la
porte de scellement.

## Expériences

- [`experiments/ts-api-digest/`](experiments/ts-api-digest/) — l'idée de §7 mesurée sur le code de
  DeepSeek Harness. À taille pratiquement égale (12,4 % contre 11,4 % des caractères), un digest de
  surface publique conserve **100 % des symboles exportés** là où la troncature par caractères en perd
  69 %.

## Performance : le contrat C

Le régime scellé vise la parité C, et la spec ([§10](SPEC.md#10--performance--le-contrat-c)) énonce les
clauses plutôt que le slogan : aucun runtime, aucun déroulement de pile, disposition mémoire identique au
C, monomorphisation, et **zéro vérification implicite** — une indexation non prouvée n'est pas compilée
avec un garde, elle devient une obligation de scellement :

```
$ mi seal
O220 img.mi:14:11  index-non-prouve  px[i]  fix:for-in | get | assert-range
```

Trois endroits où Mira peut *dépasser* le C : `noalias` gratuit sur chaque emprunt exclusif (le C doit
supposer que deux pointeurs se recouvrent), les régions qui allouent par déplacement de pointeur au lieu
de `malloc`, et la pureté lisible dans la signature qui ouvre l'évaluation à la compilation et la
vectorisation sans analyse d'alias.

**Le seuil, écrit à l'avance :** ±5 % de `clang -O2` sur au moins 10 des 12 micro-bancs du panier, jamais
plus de +20 % sur aucun. Tant qu'il n'est pas atteint, la phrase « aussi rapide que le C » ne s'écrit pas
ici — on écrit le chiffre mesuré à la place.

## Licence

MIT — voir [`LICENSE`](LICENSE).
