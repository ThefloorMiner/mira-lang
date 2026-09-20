# Mira par l'exemple

*Compagnon de [`SPEC.md`](SPEC.md). La spec dit **pourquoi** ; ce guide dit **comment on écrit**.*

*Aucun compilateur n'existe : tout ce qui suit décrit le comportement spécifié.*

---

## 00 — Mise en route

```console
$ mi new bonjour
$ cd bonjour
```

```
bonjour/
  mi.toml
  src/
    main.mi        # module `main` — contient fn main, le point d'entrée
```

`mi.toml`, en entier :

```toml
name = "bonjour"
mode = "draft"          # régime par défaut du projet

[deps]
http = "1.2"            # devient ambiant sous `http.` — aucune ligne d'import
```

Pas de fichier de build, pas de choix de linter, pas de configuration de formateur. Un fichier `.mi` est
un module nommé d'après le fichier : `src/wordcount.mi` est le module `wordcount`, utilisable partout
sous le préfixe `wordcount.` sans rien écrire en haut du fichier.

---

## 01 — Hello world

```mira
fn main() + io:
  io.print("hello, monde")
```

```console
$ mi run
hello, monde
```

Pas d'`import`, pas de `#include`, pas de `public static void`, pas de point-virgule, pas d'accolade.
Mais **une chose en plus** : `+ io`. Sans cette déclaration d'effet, `io.print` est refusé à la
compilation.

Une version avec argument, valeur par défaut et test :

```mira
fn greet(name: str) -> str:
  "hello, {name}"

fn main() + io env:
  let who = env.args.get(1) or "monde"
  io.print(greet(who))

test greet:
  greet("Nico") == "hello, Nico"
  greet("") == "hello, "
```

```console
$ mi run -- Nico
hello, Nico

$ mi test
✓ greet · 2 assertions
1/1 · 4 ms

$ mi seal
0 obligations · sealed=ok

$ mi build
→ target/bonjour · 318 Ko · 0 dependance runtime
```

---

## 02 — Anatomie

Neuf éléments, et vous savez lire n'importe quel programme Mira.

| Élément | Ce que c'est |
|---|---|
| `fn greet(…)` | **Déclare une fonction.** Privée au module par défaut ; `pub fn` pour l'exposer. |
| `name: str` | **Mode par défaut : emprunt partagé.** Pour muter : `var name`. Pour posséder : `own name`. `&` n'existe pas. |
| `-> str` | **Type de retour.** Facultatif en `draft`, obligatoire sur tout `pub` ou scellé. Les locaux sont toujours inférés. |
| `:` + indentation | **Ouvre un bloc.** Une ligne commençant par `.` et plus indentée continue l'expression précédente. |
| `"hello, {name}"` | **Interpolation**, format optionnel : `"{n:>5}"`. Pas de `format!`, pas de `+`. |
| dernière ligne du bloc | **C'est la valeur de retour.** `return` ne sert qu'aux sorties anticipées. |
| `+ io env` | **Les effets.** Liste close : `io fs net clock rand env proc task gpu ffi`. Pas de `+` ⇒ fonction pure. |
| `.get(1) or "monde"` | **Optionnels sans panique.** `or` donne le défaut, `?` propage. Pas d'`unwrap`, pas de `null`. |
| `test greet:` | **Le test est attaché à l'item.** Une expression nue est une assertion. Retiré du binaire en release. |

---

## 03 — La boucle

| Commande | Question | Durée |
|---|---|---|
| `mi run` | Ça tourne ? Types inférés, mémoire comptée par références, aucune preuve exigée. | secondes |
| `mi test` | Ça fait ce qu'il faut ? Assertions et propriétés, graines rejouables. | secondes |
| `mi seal` | Qu'est-ce qui manque ? Une liste finie d'obligations, une ligne chacune. | liste bornée |
| `mi build` | Livré. Natif, propriété statique, zéro runtime. | final |

La différence avec un typage graduel classique : **le passage n'est jamais deviné**. `mi seal` ne dit pas
« ça ne compile pas », il énumère les points où le brouillon servait de béquille, avec la réparation
canonique en face. Une obligation n'est pas une erreur — le programme tourne pendant tout ce temps.

---

## 04 — Exemple simple : les dix mots les plus fréquents

→ code complet dans [`examples/wordcount/`](examples/wordcount/)

### 4.1 La version brouillon

`src/wordcount.mi`

```mira
draft mod wordcount

pub fn top(text, n):
  counts = {}
  for w in text.lower().split():
    counts[w] = (counts[w] or 0) + 1
  counts.pairs()
    .sort_by(p -> -p.1)
    .take(n)
```

`src/main.mi`

```mira
fn main() -> Unit! + io fs env:
  let path = env.args.get(1) or "README.md"
  let text = fs.read_str(path)?
  for w, n in wordcount.top(text, 10):
    io.print("{n:>5}  {w}")
```

`wordcount.` est disponible sans rien déclarer : le fichier *est* le module. Le `?` sur `fs.read_str`
propage l'erreur, ce qui oblige `main` à être faillible — d'où le `-> Unit!`. Une erreur non gérée sort
en code de retour non nul, sans exception ni déroulement de pile.

### 4.2 La porte

```console
$ mi seal
O301 wordcount.mi:3:12  type-inconnu   text       fix:annotate str
O301 wordcount.mi:3:18  type-inconnu   n          fix:annotate u32
O204 wordcount.mi:5:5   index-dyn      counts[w]  fix:upsert | get_or
O410 wordcount.mi:3:1   pub-non-teste  top        fix:add-test | test none:<raison>
4 obligations · 0 erreurs · sealed=no
```

Quatre lignes, quatre réparations nommées. Aucune prose, aucun ASCII art, aucun rappel du source.
Version longue à la demande seulement : `mi explain O204`.

### 4.3 La version scellée

```mira
seal mod wordcount

pub fn top(text: str, n: u32) -> Vec[(str, u32)]:
  var counts: Map[str, u32] = {}
  for w in text.lower().split():
    counts.upsert(w, 0, c -> c + 1)
  counts.drain()
        .sort_by(p -> -(p.1 as i64))
        .take(n)

test top:
  top("a b a", 1) == [("a", 2)]
  top("", 5) == []
  prop t: str -> top(t, 0).len() == 0
```

| Obligation | Ce qu'on écrit | Pourquoi |
|---|---|---|
| `O301` ×2 | `text: str`, `n: u32`, `-> Vec[(str, u32)]` | Frontière `pub` : les types deviennent obligatoires. C'est aussi ce que lira `mi api`. |
| `O204` | `counts.upsert(w, 0, c -> c + 1)` | `counts[w]` peut échouer ; `upsert` est total. Pas d'opération partielle silencieuse. |
| — | `counts.drain().sort_by(…)` | `drain` prend possession des paires ; `sort_by` rend une nouvelle liste plutôt que de muter. |
| `O410` | le bloc `test top:` | Tout `pub` est couvert, ou porte un `test none:` justifié. |

```console
$ mi seal
0 obligations · sealed=ok

$ mi api wordcount
mod wordcount
  pub fn top(text: str, n: u32) -> Vec[(str, u32)]
# 1 item · 23 tokens · sha 4d10ae
```

23 tokens : c'est ce qu'un agent relit pour appeler ce module, au lieu des ~400 tokens du source.

---

## 05 — Exemple avancé : détecter les dépendances circulaires

→ code complet dans [`examples/deps/`](examples/deps/)

C'est le programme que Rust rend pénible — un graphe avec cycles — et c'est exactement pour ça que les
régions existent. Le découpage est celui de tous les programmes Mira sérieux : **les effets au bord, le
cœur pur au milieu, la mémoire en région là où le graphe vit.**

### 5.1 Le bord

```mira
seal mod deps

err Deps = IoErr | Cycle(Vec[str])

pub type Mod = {name: str, uses: Vec[str]}
  derive Eq Json

pub fn scan(root: Path) -> Vec[Mod]!Deps + fs:
  fs.glob(root, "src/**/*.mi")
    .par_map(p -> Mod{name: p.stem(), uses: refs(fs.read_str(p)?)})
    .collect()?
```

- `par_map` lit tous les fichiers en parallèle sans une ligne de plus. `Send`/`Sync` ne sont jamais
  écrits : ils se déduisent de la propriété. Une fermeture capturant un emprunt exclusif serait refusée
  à la compilation.
- Le `?` produit un `IoErr` qui remonte tel quel dans `Deps` — parce que `IoErr` *est* une variante de
  l'union. Pas d'`impl From`, pas de `map_err`, pas de `Box<dyn Error>`.
- Une dépendance Mira, c'est une référence qualifiée (`wordcount.`) : comme il n'y a pas d'imports, le
  graphe se lit dans le code lui-même.

### 5.2 Le graphe vit dans une région

```mira
type Node = {name: str, out: Vec[Node]}   # références mutuelles permises

pub fn check(mods: Vec[Mod]) -> Unit!Deps:
  region g:
    var nodes = mods.map(m -> g.new Node{name: m.name, out: []})
    let by: Map[str, Node] = nodes.map(n -> (n.name, n)).to_map()
    for m, n in mods.zip(nodes):
      for u in m.uses:
        match by.get(u):
          some t: n.out.push(t)      # arête ; t et n peuvent se pointer
          none: pass
    match find_cycle(nodes):
      some path: err Cycle(path)     # ← le vérificateur va refuser ceci
      none: ok
```

```console
$ mi seal
E211 deps.mi:24:18  echappement-region  path (alloue dans g:16)  fix:g.out | own
1 erreur · sealed=no
```

**C'est le moment intéressant.** `path` est un `Vec[str]` dont les chaînes viennent de `n.name` — elles
vivent dans `g`, et `g` meurt à la fin du bloc. Le retourner serait un *use-after-free*. En C, ça passe
et ça plante trois semaines plus tard ; en Rust, c'est un message de durée de vie que personne ne lit
jusqu'au bout. Ici, c'est une ligne, avec la réparation en face :

```mira
    match find_cycle(nodes):
      some path: err Cycle(g.out(path))   # recopie hors de la région
      none: ok
```

`g.out(x)` promeut une valeur hors de la région en la recopiant chez l'appelant. Le coût est explicite et
visible. Et notez ce qu'on n'a *pas* écrit : aucune annotation de durée de vie, aucun `Rc<RefCell<…>>`,
aucun index entier en guise de faux pointeur.

### 5.3 Le cœur pur

```mira
type Mark = New | Open | Done

fn find_cycle(nodes: Vec[Node]) -> Vec[str]?:
  var mark: Map[str, Mark] = {}
  var stack: Vec[str] = []
  for n in nodes:
    match walk(n, mark, stack):
      some c: return some c
      none: pass
  none

fn walk(n: Node, var mark: Map[str, Mark], var stack: Vec[str]) -> Vec[str]?:
  match mark.get(n.name) or New:
    Open: return some stack.from(stack.find(n.name) or 0)
    Done: return none
    New: pass
  mark.set(n.name, Open)
  stack.push(n.name)
  for t in n.out:
    match walk(t, mark, stack):
      some c: return some c
      none: pass
  stack.pop()
  mark.set(n.name, Done)
  none
```

> **Le site d'appel ne répète pas le mode :** on écrit `walk(n, mark, stack)`, pas
> `walk(n, var mark, var stack)`. C'est la signature qui fait foi, et `mi api` l'affiche. On gagne des
> tokens et une source d'erreur ; on perd la visibilité de la mutation à la lecture. **C'est la décision
> la plus contestable de ce guide**, à trancher au banc de la phase 0.

### 5.4 Les tests écrivent les cas limites eux-mêmes

```mira
fn id(i: u32) -> str:
  "m{i}"

fn chain(n: u32) -> Vec[Mod]:          # m0→m1→m2… : jamais de cycle
  (0..n).map(i -> Mod{name: id(i), uses: if i + 1 < n: [id(i + 1)] else: []})
        .collect()

fn ring(n: u32) -> Vec[Mod]:           # m0→m1→m2→m0 : toujours un cycle
  (0..n).map(i -> Mod{name: id(i), uses: [id((i + 1) % n)]}).collect()

test check:
  check([]) == ok
  check(chain(3)) == ok
  check(ring(3)) == err Cycle(["m0", "m1", "m2"])
  prop n: u32 -> check(chain(n.clamp(0, 200))) == ok
  prop n: u32 -> check(ring(n.clamp(2, 200))) != ok
```

Les deux dernières lignes valent cinq cents cas écrits à la main. Une chaîne n'a jamais de cycle, un
anneau en a toujours un : la propriété est vraie par construction, donc tout contre-exemple trouvé est un
vrai bug — réduit automatiquement et réécrit dans le bloc comme assertion de régression.

### 5.5 Le programme

```mira
seal mod main

fn main() -> Unit! + io fs env proc:
  let root = env.args.get(1) or "."
  match deps.check(deps.scan(root)?):
    ok:
      io.print("✓ aucun cycle")
    err Cycle(p):
      let chain = p.join(" → ")
      io.eprint("✗ cycle : {chain}")
      proc.exit(1)
    err e:
      io.eprint("✗ {e}")
      proc.exit(2)
```

```console
$ mi test
✓ check · 3 assertions · 2 proprietes · 400 cas · graine 8821
✓ refs  · 4 assertions
2/2 · 61 ms

$ mi run -- .
✗ cycle : parser → ast → parser

$ mi run --allow fs -- .
E520 module main declare io env proc, non autorises  fix:--allow io env proc
```

La dernière ligne est la raison d'être des effets. Exécuter du code qu'on vient de générer devient une
décision explicite : ce programme *ne peut pas* ouvrir une socket, parce que sa signature ne le déclare
pas et que le bac à sable applique la signature.

### 5.6 Ce que l'agent relit, lui

```console
$ mi api deps
mod deps + fs
  Mod{name: str, uses: Vec[str]}  derive Eq Json
  err Deps = IoErr | Cycle(Vec[str])
  pub fn scan(root: Path) -> Vec[Mod]!Deps + fs
  pub fn check(mods: Vec[Mod]) -> Unit!Deps
# 4 items · 58 tokens · sha b71c04

$ mi why deps.check
main → deps.check → find_cycle → walk     [pur]
```

58 tokens pour un module de 200 lignes. Et `check` n'affiche aucun effet : on sait, sans lire une ligne
de corps, qu'il ne touche ni au disque ni au réseau.

---

## 06 — Antisèche

| Python | Rust | Mira |
|---|---|---|
| `def f(x):` | `fn f(x: T) {}` | `fn f(x: T):` |
| — | `&x` | rien — c'est le défaut |
| — | `&mut x` | `var x` |
| — | `x` (move) | `own x` |
| — | `'a` | n'existe pas |
| — | `Rc<RefCell<T>>` | `region` ou `rc T` |
| `x = 1` | `let mut x = 1;` | `var x = 1` |
| — | `let x = 1;` | `let x = 1` |
| `f"{x}"` | `format!("{x}")` | `"{x}"` |
| `List[int]` | `Vec<i32>` | `Vec[i32]` |
| `Optional[T]` | `Option<T>` | `T?` |
| `raise` / `try` | `Result<T, E>` | `T!E` |
| `x or d` | `x.unwrap_or(d)` | `x or d` |
| — | `x?` | `x?` |
| — | `impl From<E1> for E2` | union : `err E2 = E1 \| …` |
| `match x: case p:` | `match x { p => }` | `match x:` puis `p:` |
| `lambda x: e` | `\|x\| e` | `x -> e` |
| `import m` | `use m;` | rien — ambiant |
| `@dataclass` | `#[derive(..)]` | `derive Eq Json` |
| `pytest`, fichier à part | `#[test] mod tests` | `test f:` sous l'item |
| `hypothesis` | `proptest!` | `prop x: T -> …` |
| `ThreadPool.map` | `par_iter().map()` | `.par_map(…)` |
| — | `unsafe {}` | `raw:` + `safety:` |
| invisible | invisible | `+ io fs net` dans la signature |

---

## 07 — Ajouts à la spec v0.1

Écrire des programmes réels a forcé sept décisions que la spec laissait ouvertes. À reverser dans §3 et §4.

| Ajout | Décision | Motif |
|---|---|---|
| Point d'entrée | `fn main()` dans le module racine ; `-> Unit!` s'il propage | Erreur non gérée = code de retour, sans exception ni déroulement de pile. |
| Interpolation | `"{expr}"`, format optionnel `"{n:>5}"` | Prior Python très fort ; supprime `format!` et la concaténation. |
| Unions d'erreurs | `?` élargit automatiquement si le type source est une variante | Remplace `impl From` et `map_err`, première source de bruit en Rust. |
| Régions | `g.new T{…}` pour allouer, `g.out(x)` pour promouvoir | Deux verbes, coût de la copie explicite. |
| Continuation | une ligne débutant par `.` et plus indentée continue l'expression | Chaînage lisible sans parenthèses de groupe. |
| `if` en expression | `if c: a else: b` sur une ligne | Évite un bloc de quatre lignes pour un défaut. |
| Divers | `pass`, joker `_`, `derive` en ligne indentée, `self` en premier paramètre d'`impl` | Priors Python et Rust, aucun coût. |

**Et une décision qui reste ouverte :** les sites d'appel ne répètent pas le mode de paramètre (§5.3).
Cohérent avec la philosophie — le cas par défaut ne s'écrit pas — mais la mutation devient invisible à la
lecture, ce qui est un vrai coût pour la revue humaine d'un code écrit par une machine. À trancher au
banc, pas à l'intuition.
