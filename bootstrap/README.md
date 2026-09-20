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
