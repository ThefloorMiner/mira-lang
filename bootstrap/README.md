# `mi` — amorce

Un interpréteur Mira du régime `draft`, en Python, sans dépendance.

**Ce n'est pas la VM de la phase 1.** C'est l'implémentation de référence dont le seul travail est de
répondre à une question : *la grammaire de [§3.1](../SPEC.md#31-grammaire-du-noyau) est-elle analysable
sans ambiguïté, et la sémantique tient-elle debout ?* Elle est lente, elle ne scelle rien, et elle
n'applique ni la propriété ni les effets au-delà du bac à sable.

## Utiliser

```sh
python3 bootstrap/mi.py run  examples/bonjour/src/main.mi -- Nico
python3 bootstrap/mi.py test examples/deps/src/deps.mi
python3 bootstrap/mi.py api  examples/deps/src/deps.mi
python3 bootstrap/mi.py lex  examples/bonjour/src/main.mi     # jetons, pour l'indentation
```

## Ce qui tourne

Les trois exemples du dépôt, en entier :

```
$ mi run src/main.mi -- Nico
hello, Nico

$ mi test src/deps.mi
✓ check · 3 assertions · 2 proprietes · 200 cas · graine 8821
1/1 · graine 8821

$ mi api src/deps.mi
mod deps + fs
  Mod{name: str, uses: Vec[str]}  derive Eq Json
  pub fn scan(root: Path) -> Vec[Mod]!Deps + fs
  pub fn check(mods: Vec[Mod]) -> Unit!Deps
  err Deps = IoErr | Cycle(Vec[str])
# 4 items · 66 tokens · sha dd3024

$ mi run src/main.mi --allow fs -- .
E520 main.mi  module declare env io proc, non autorises  fix:--allow env io proc
```

La dernière ligne est le bac à sable de [§8](../SPEC.md#8--chaîne-doutils) : les effets déclarés sont
confrontés à `--allow` au démarrage, et le diagnostic sort au format `llm` de
[§6](../SPEC.md#6--diagnostics-comme-api).

Couvert : indentation significative, continuation de ligne, interpolation, `fn`/`let`/`var`, `if`/`for`/
`while`, `match` et ses motifs, `test` et `prop`, optionnels et `or`, résultats et `?`, lambdas,
enregistrements, types sommes, régions, modules ambiants sans import, et `mi api`.

## Ce que l'écriture de l'analyseur a trouvé

C'est la raison d'être de cette amorce. **Trois trous de grammaire**, invisibles tant qu'on écrit la spec
à la main :

1. **La continuation de ligne était impossible à implémenter telle qu'écrite.** §3.4 dit qu'une ligne
   commençant par `.` continue l'expression précédente — mais le lexeur a déjà émis le `NEWLINE` quand il
   le découvre. Il faut le retirer rétroactivement. C'est une règle de lexeur, pas de grammaire.
2. **`if c: a` contre `if c: a else: b`.** La spec ne tranchait pas. Règle retenue : en position
   d'instruction, `if` n'exige pas de `else` ; en position d'expression, il en exige un, puisque sans lui
   il n'a pas de valeur. Et un corps d'une seule instruction est autorisé sur la même ligne après `:`,
   pour `if`, `for`, `while` et les bras de `match`.
3. **`g.new T{…}` n'avait aucune production.** Cette forme est écrite en §2.3 et §12.1 et n'existait nulle
   part dans la grammaire. Ajoutée : `postfix = … | postfix '.' 'new' postfix`.

Et **deux découvertes sémantiques** :

4. **`sort_by` rendait un résultat dans un exemple et mutait dans l'autre.** Les deux ne pouvaient pas
   être vrais. Retenu : il rend une nouvelle liste, comme `map`, `filter` et `take` ; les exemples du
   dépôt ont été corrigés.
5. **`mi api` doit inclure les types non-`pub` atteignables depuis une signature publique.** Sans ça,
   `err Deps` disparaissait du digest alors que `scan` rend `Vec[Mod]!Deps` — on ne peut pas traiter une
   erreur dont on ignore les variantes. C'est exactement la règle trouvée dans
   [`experiments/ts-api-digest`](../experiments/ts-api-digest/).

## Ce qui n'est pas fait

- **Aucun scellement.** Pas de vérificateur de propriété, d'emprunts, de régions ni d'effets. `seal mod`
  est analysé et ignoré ; `mi seal` n'existe pas. C'est la phase 2.
- **Optionnels approximés.** `some v` est représenté par `v` lui-même et `none` par un singleton, donc
  `some none` n'est pas distinguable. La VM de la phase 1 les distinguera.
- **`par` et `spawn` sont séquentiels**, les régions ne libèrent rien, `g.out(x)` rend `x`.
- **Le compteur de tokens de `mi api` est un regex**, pas un tokenizer BPE : il donne 66 là où la spec
  annonçait 58. Les deux sont des approximations ; seule la phase 0 tranchera.
- **Plafond de récursion.** Un parcours d'arbre consomme ~15 trames Python par appel Mira ; l'amorce
  s'exécute dans un fil à grande pile pour compenser. La VM à registres n'aura pas cette contrainte.

## Ensuite

Phase 1 telle que décrite en [§15](../SPEC.md#15--plan--falsifiabilité) : reprendre cette grammaire —
maintenant qu'elle est validée — dans un lexeur, un analyseur et une VM à registres en Rust, avec un tas
compté par références et un collecteur de cycles.

---

## `mi seal` — la porte

[`seal.py`](seal.py) applique [§5.1](../SPEC.md#51-ce-que-mi-seal-exige) sur l'AST. Huit contrôles,
tous avec une suite de cas dans [`tests/`](tests/) :

| Code | Contrôle | §  |
|---|---|---|
| `E401` | item `draft` atteignable depuis `seal` | 1.3 |
| `E512` / `O513` | effets manquants ou déclarés en trop, inférés par point fixe sur le graphe d'appel | 4.1 |
| `O301` | frontière `pub` sans annotation | 5.1 |
| `O204` / `O220` | indexation partielle d'une table, indexation non prouvée d'une séquence | 10.3 |
| `E211` | échappement de région | 2.3 |
| `E204` | usage après déplacement dans un paramètre `own` | 2.1 |
| `O410` | item `pub` non testé | 5.1 |
| `E420` | tests rouges | 5.1 |
| `E205` | mutation d'une liaison partagée (`let`, paramètre sans mode) | 2.1 |
| `E207` | passage d'une liaison partagée à un paramètre `var` | 2.1 |
| `E206` | même variable empruntée deux fois en exclusif dans un appel | 2.1 |
| `E208` | variable lue pendant son emprunt exclusif | 2.1 |

La sortie est au format `llm` de §6 : une ligne par constat, racines d'abord, budget plafonné.

```
$ mi seal src/deps.mi
0 obligations · 0 erreurs · sealed=ok

$ mi seal src/deps.mi            # apres avoir retire g.out(path)
E211 deps.mi:36  echappement-region  valeur de region g:28 rendue par la fonction  fix:g.out | own
0 obligations · 1 erreurs · sealed=no
```

```
$ python3 bootstrap/run_tests.py
  ✓ alias_exclusive.mi     E208
  ✓ assign_to_let.mi       E205
  ✓ borrow_ok.mi           sealed
  ✓ double_exclusive.mi    E206
  …
17/17 cas
```

### Angles morts, déclarés

`mi blind` les imprime, et ils sont dans le code à côté des contrôles. **Un vérificateur qui tait ses
angles morts est pire qu'aucun vérificateur : il fait croire à une preuve qu'il n'a pas faite.**

```
$ mi blind
  · Emprunts : verifies seulement quand la racine de l'acces est un nom simple.
  · Arithmetique : O221/O222 demandent une analyse de plages, absente.
  · Types : aucune inference ni verification.
  · Verrous : O230 demande un graphe de rangs, absent.
  · GPU : E240 n'est pas implemente.
  · Regions : le suivi de contamination est conservateur mais pas sain.
```

### Ce que l'écriture du vérificateur a trouvé

6. **`test none: <raison>` n'était pas analysable.** La forme de la spec ne nomme pas l'item qu'elle
   couvre. Remplacée par `test f: "raison"` — un bloc `test` dont le corps est une seule chaîne
   littérale, ce qui ne demande aucune syntaxe nouvelle et ne peut pas se confondre avec une assertion.
7. **`scan` n'avait aucun test.** Le vérificateur l'a signalé sur mon propre code ; la fonction porte
   maintenant une dérogation explicite.
8. **Un bug qui rendait le vérificateur muet.** Lancé comme script, `mi.py` est le module `__main__`,
   mais `seal.py` importe `mi` — deux classes `N` distinctes dans le processus, donc tous les
   `isinstance` échouaient et le parcours d'arbre ne voyait rien. Le vérificateur *passait* sur tout.
   Corrigé en repassant par le module, et le parcours utilise maintenant du typage canard.

### Emprunts (§2.1)

Quatre contrôles, sans une seule annotation de durée de vie dans le langage :

```mira
pub fn build() -> u32:
  let xs = [1, 2]
  xs.push(3)            # E205 mutation-sans-var  fix:var | own

fn grow(var v: Vec[u32], n: u32): …
  grow(xs, xs.len())    # E208 alias-pendant-exclusif  fix:clone | reorder
  swap2(xs, xs)         # E206 exclusif-double         fix:clone | split
```

**Faux négatifs assumés, faux positifs interdits.** On ne conclut que lorsque la racine d'un accès est un
nom simple connu de la portée. À travers une expression composée — `a.b[i]`, un résultat d'appel — rien
n'est signalé. C'est un choix : un vérificateur qui crie au loup sur du code correct se fait désactiver
en trois jours, et il ne reste alors aucune vérification du tout.

### Ce que l'écriture du vérificateur d'emprunts a trouvé

9. **Le mode d'une liaison de boucle n'était pas spécifié.** `for x in xs:` — `x` est-il exclusif ou
   partagé ? Règle adoptée, cohérente avec §2.1 : hérité de la collection parcourue, jamais écrit ; et
   non conclu quand la collection est une expression composée. Sans cette règle, `deps.check` — qui fait
   `for m, n in mods.zip(nodes)` puis `n.out.push(t)` — aurait été rejeté à tort.
10. **`E206` et `E208` se déclenchaient ensemble** sur `swap2(xs, xs)` : une cause, deux lignes. §6.1
    exige racines d'abord et cascades supprimées. La cascade est maintenant supprimée.
