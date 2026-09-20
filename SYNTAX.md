# Syntaxe Mira — référence v0.1

*Toute forme du langage, une fois chacune. Compagnon de [`SPEC.md`](SPEC.md) (le pourquoi) et de
[`GUIDE.md`](GUIDE.md) (le démarrage).*

**Chaque extrait de ce fichier est passé au parseur de l'amorce** par
[`bootstrap/check_docs.py`](bootstrap/check_docs.py). Un document dont les exemples ne compilent pas est
un document faux.

Statut : ● exécuté par l'amorce · ◐ analysé, non exécuté ni vérifié · ○ spécifié seulement.

---

## 00 — Fichier & module

```mira
seal mod payments

pub fn charge(cents: u32) -> u32:
  cents
```
● `seal` ou `draft` fixe le régime. L'en-tête est facultatif. **Aucune ligne d'import** : les autres
modules sont ambiants sous leur nom (`payments.charge(…)`).

```mira
# commentaire jusqu'a la fin de ligne
fn f() -> u32:        # aussi en fin de ligne
  1
```
● Une seule forme, `#`. Pas de commentaire de bloc.

```mira
fn total(xs: Vec[u32]) -> u32:
  xs.filter(x -> x > 0)
    .sum()
```
● Indentation significative, `:` ouvre un bloc, une ligne commençant par `.` continue l'expression.
*Piège de lexeur : le `NEWLINE` est déjà émis quand on découvre le `.` — il faut le retirer.*

## 01 — Littéraux

```mira
fn nombres() -> f64:
  let a = 42
  let b = 1_000_000
  let c = 3.14
  c + (a + b) as f64
```
● `_` sépare les chiffres. `x.0` reste un accès de tuple.

```mira
fn salut(nom: str, n: u32) -> str:
  "bonjour {nom}, {n:>5} fois"
```
● `{expr}` interpole, `{expr:spec}` formate. Échappements `\n \t \\ \" \{`. Un guillemet à l'intérieur
d'un `{…}` appartient à l'expression : `"{f("x")}"` est valide.

```mira
fn collections() -> u32:
  let v = [1, 2, 3]
  let m = {"a": 1, "b": 2}
  let t = ("x", 7)
  v.len() + m.len() + t.1
```
● Les accolades servent aux littéraux de table et d'enregistrement, jamais aux blocs.

```mira
type User = {id: u64, name: str}

fn faire(id: u64) -> User:
  let name = "nico"
  User{id, name}
```
● `User{id, name}` abrège `User{id: id, name: name}`.

## 02 — Liaisons

```mira
fn compter() -> u32:
  let base = 10          # partagee
  var n: u32 = 0         # exclusive
  n += base
  n
```
● `let` lie en partagé, `var` en exclusif. Muter un `let` est `E205`.

```mira
fn paire() -> (str, u32):
  ("a", 2)

fn prendre() -> u32:
  let (nom, n) = paire()
  n + nom.len()
```
● Déstructuration de tuple. *Trouvée manquante par le vérificateur de documentation : la spec l'utilisait
en §11.2, le parseur ne la connaissait pas.*

## 03 — Types

```mira
fn formes(a: u32, b: f64, c: str, d: bool) -> u64:
  a as u64
```
◐ `i8…i64`, `u8…u64`, `f32 f64`, `bool`, `str`, `Unit`.

```mira
fn suffixes(a: str?, b: u32!, c: u32!IoErr, d: rc str) -> u32:
  0
```
◐ `T?` optionnel, `T!` faillible avec l'erreur du module, `T!E` avec `E`, `rc`/`arc` pour le partage
compté. Génériques en `[T]` et non `<T>` : pas d'ambiguïté avec la comparaison.

```mira
pub type Card = {num: str, exp: u32}
  derive Eq Json

type Mark = New | Open | Done

err Deps = IoErr | Cycle(Vec[str])
```
● Produit, somme, union d'erreurs. Une variante peut être un type d'erreur existant — `?` élargit alors
automatiquement, sans `impl From`. `derive` sur une ligne indentée, jeu fermé.

## 04 — Fonctions

```mira
fn len(v: Vec[u32]) -> u32
fn push(var v: Vec[u32], x: u32)
fn eat(own v: Vec[u32]) -> u32
```
● Défaut : emprunt partagé, et il ne s'écrit pas. `var` : exclusif. `own` : déplacement.
**`&` n'existe pas, aucune durée de vie ne s'écrit jamais.**

```mira
fn parse(s: str) -> u32:
  s.len()

fn fetch(u: str) -> str! + net:
  ok u

fn trace(m: str) + io fs:
  io.print(m)
```
● Pas de `+` ⇒ pure. Jeu fermé de dix : `io fs net clock rand env proc task gpu ffi`. Les effets sont
**inférés par point fixe** et confrontés à la déclaration (`E512` / `O513`).

```mira
fn trier(v: Vec[(str, u32)]) -> Vec[(str, u32)]:
  v.sort_by(p -> -(p.1 as i64))

fn combiner(a: u32, b: u32) -> u32:
  let f = (x, y) -> x + y
  f(a, b)
```
● Lambdas `x -> expr` ou `(a, b) -> expr`, corps d'une expression.

○ `trait` / `impl X for T` : spécifiés, **ni analysés ni exécutés**.

## 05 — Contrôle

```mira
fn signe(x: i64) -> str:
  if x > 0:
    "positif"
  else if x < 0:
    "negatif"
  else:
    "zero"

fn court(x: u32) -> u32:
  if x > 0: x else: 0
```
● **En instruction, `else` est facultatif ; en expression, il est obligatoire** — sans lui, l'expression
n'aurait pas de valeur. *La spec ne tranchait pas ; écrire l'analyseur a forcé la règle.*

```mira
fn somme(v: Vec[(str, u32)]) -> u32:
  var t = 0
  for nom, n in v:
    if nom == "": continue
    t += n
  for i in 0..3:
    t += i
  t
```
● Destructure les tuples, `0..n` borne haute exclue. **Le mode d'une liaison de boucle est hérité** de la
collection parcourue, jamais écrit.

```mira
fn descendre(n: u32) -> u32:
  var i = n
  while i > 0:
    if i == 3: break
    i -= 1
  i
```
● `while`, `break`, `continue`, `pass` pour le bloc vide.

## 06 — Motifs

Le motif seul ouvre le bloc : **pas de `case`**, un token économisé par branche.

```mira
type Mark = New | Open | Done

fn nommer(m: Mark) -> str:
  match m:
    Open: "ouvert"
    Done: "fini"
    _: "neuf"
```
● Nom capitalisé = variante, `_` = joker.

```mira
err Db = Missing | Corrupt(str)

fn lire(r: str!Db) -> str:
  match r:
    ok v: v
    err Missing: "absent"
    err Corrupt(m): m
```
● `ok v`, `err E`, `err Ctor(x)`.

```mira
fn couper(s: str) -> str:
  match s.split_once("."):
    some (tete, _): tete
    none: s
```
● `some x`, `some (a, b)`, `none`. Les littéraux sont des motifs.
**L'exhaustivité n'est pas vérifiée** : il faudrait les types.

## 07 — Erreurs & optionnels

```mira
fn lire(p: str) -> u32! + fs:
  let texte = fs.read_str(p)?
  ok texte.len()
```
● `?` rend la valeur si `ok`, sinon remonte. Sur un `T?`, remonte le `none`.

```mira
fn defaut(v: Vec[str]) -> str:
  v.get(3) or "absent"
```
● `or` rend la droite si la gauche est `none`, une erreur ou fausse. **Il n'y a pas d'`unwrap`.**

```mira
err E = Vide

fn construire(n: u32) -> u32!E:
  if n == 0:
    return err Vide
  ok n
```
● `ok x`, `err e`, `some x`, `none`. `ok` seul = succès sans valeur.

## 08 — Mémoire

```mira
type Node = {nom: str}

fn evaluer() -> str:
  region g:
    let n = g.new Node{nom: "x"}
    g.out(n.nom)
```
● `g.new T{…}` alloue dans l'arène, `g.out(x)` promeut hors d'elle. Sans `g.out`, c'est `E211`.
*La production `.new` manquait dans la grammaire.*

```mira
fn sur_gpu(t: f32) -> u32 + gpu:
  region f on gpu:
    let m = f.new Node{nom: "mesh"}
    m.nom.len()
```
◐ Arène de trame en mémoire périphérique. *`gpu` étant un mot-clé, le parseur refusait cette forme.*

## 09 — Concurrence

Pas d'`async`, pas d'`await`, aucune coloration de fonction.

```mira
fn total(ps: Vec[str]) -> u32 + fs:
  ps.par_map(p -> fs.read_str(p)?.len()).sum()
```
◐ `par_map` sur une fermeture pure : **optimisation, pas effet**. Aucun `task` dans la signature.

```mira
fn servir(n: u32) -> u32 + task:
  let (tx, rx) = chan[u32](64)
  par:
    spawn produire(tx)
    for j in rx:
      traiter(j)
  n
```
◐ `par:` joint ou annule toute tâche au dédentage. **Aucune tâche détachée n'existe.** Capacité de canal
obligatoire.

```mira
fn compter() -> u32 + task:
  let hits = mutex(0)
  with hits as var n:
    n += 1
  0
```
◐ Le verrou possède sa donnée. *`as` y est un lieur, pas une conversion — l'ambiguïté avec `x as i64` a
été trouvée par le vérificateur de documentation.*

## 10 — Tests

```mira
fn norm(s: str) -> str:
  s.trim().lower()

test norm:
  norm(" Hi ") == "hi"
  prop s: str -> norm(norm(s)) == norm(s)
```
● **Une expression nue est une assertion.** `prop` fuzz l'entrée, graine enregistrée.

```mira
pub fn scan(p: str) -> u32 + fs:
  p.len()

test scan: "lit le disque, couvert en integration"
```
● Un bloc `test` dont le corps est une seule chaîne est une dérogation motivée.
*La spec écrivait `test none: <raison>`, qui ne nommait pas l'item couvert.*

## 11 — Opérateurs

Du plus faible au plus fort, extraits de l'analyseur :

| # | Opérateurs | Note |
|---|---|---|
| 1 | `->` | lambda, détecté avant tout le reste |
| 2 | `or` | défaut sur `none`, erreur ou faux |
| 3 | `and` | |
| 4 | `not` | préfixe |
| 5 | `== != < <= > >=` | |
| 6 | `..` | intervalle, borne haute exclue |
| 7 | `+ -` | |
| 8 | `* / %` | |
| 9 | `-` | négation préfixe |
| 10 | `. () [] ? as {}` | accès, appel, index, propagation, conversion, enregistrement |
| 11 | littéraux, noms | |

**Six sigles au total :** `?` `!` `+` `#` `->`. Pas de `&`, pas de `*` de déréférencement, pas de `'a`,
pas de point-virgule, pas de `@`.

## 12 — Mots-clés

Quarante-deux, extraits du lexeur :

```
and  as  break  continue  derive  draft  else  err  false  fn  for  gpu
if  impl  in  let  match  mod  none  not  ok  or  own  par
pass  prop  pub  raw  region  return  seal  self  some  spawn  test  trait
true  type  use  var  while  with
```

Aucun n'est plus court que sa forme usuelle : `else` est déjà un token BPE, l'abréger ne gagnerait rien
et perdrait le prior. `impl` et `trait` sont réservés sans être analysés ; `use` est réservé sans emploi —
il n'y a pas d'imports en Mira, le mot reste pris pour qu'aucun identifiant ne s'en empare.
