# Expérience — `mi api` pour TypeScript

**Question :** l'idée de [§7](../../SPEC.md#7--compression-de-contexte) — donner à un agent la *surface
publique* d'un module au lieu de son source — tient-elle sur du vrai code ?

**Terrain :** [`deepseek-ai/deepseek-harness`](https://github.com/deepseek-ai/deepseek-harness), six
fichiers de `packages/core/`, 272 564 caractères.

**Comparaison :** leur propre stratégie de troncature,
[`dsh-compaction-tool-result-pruner`](https://github.com/deepseek-ai/deepseek-harness/tree/main/packages/compaction/compaction-tool-result-pruner)
— 4 096 premiers caractères + marqueur + 1 024 derniers, au-delà de 8 192.

## Résultat

```
fichier                    source head/tail  digest  sym  h/t  dig
------------------------------------------------------------------
agent-loop/agent.ts        25,001     5,159   3,807    1    1    1
agent-loop/index.ts        40,149     5,159   7,538    9    2    9
agent/index.ts             31,075     5,159  17,447    7    4    7
session/index.ts           59,815     5,159  21,940    7    4    7
session/surface.ts         27,707     5,159   4,902   14    5   14
tools/index.ts             88,817     5,159  33,016   30    5   30
------------------------------------------------------------------
TOTAL                     272,564    30,954  88,650   68   21   68

head/tail :  11.4 % des caractères ·  30.9 % des symboles publics
digest    :  32.5 % des caractères · 100.0 % des symboles publics
```

La troncature head/tail garde 11,4 % des caractères — et **perd 69 % des symboles exportés**. Elle
conserve les imports et la fin du fichier, et jette toutes les signatures du milieu. Le digest coûte
trois fois plus de caractères et conserve **la totalité** de la surface publique.

L'argument n'est donc pas « 11,4 % contre 32,5 % ». Il est : un fichier tronqué à 31 % de ses symboles
n'est pas exploitable, donc l'agent relit le fichier entier, et le coût réel devient 11,4 % + 100 %.
Le digest à 32,5 % se suffit à lui-même.

**Cette dernière proposition n'est pas mesurée.** Elle est plausible et c'est ce qu'il faut tester
ensuite, contre le banc `conversation-fold` de dsh.

## Ce que le digest garde

Surface publique complète, corps de fonctions jetés, types internes conservés s'ils sont atteignables
depuis une signature exportée, imports réduits à une ligne. La sortie ressemble à un `.d.ts` :

```ts
// imports: dsh-llm, known-event-types.ts, types.ts

export interface SessionMessageProjection<T extends SessionEventType = SessionEventType> {
  /** Event interpreted by this definition. */
  type: T
  project(event: SessionEvent<T>, context: SessionMessageProjectionContext): ReadonlyMap<SessionSeq, Message>
}

export function isSurfaceEligibleType(type: string): boolean
```

## Limites de ce prototype

- **Extraction par accolades et expressions régulières.** Les signatures sur plusieurs lignes sont
  tronquées (`export function deriveEventMessage(` sans ses paramètres), et les accolades dans les
  chaînes, les gabarits ou le JSX peuvent égarer le compteur. Une version réelle doit passer par l'API
  du compilateur TypeScript (émission de déclarations / `isolatedDeclarations`), qui est exacte et déjà
  présente dans ce monorepo.
- **Caractères, pas tokens.** L'unité de budget de dsh est le point de code Unicode, donc la comparaison
  est juste — mais le rapport en tokens diffère un peu.
- Le gain dépend du type de fichier : 18-20 % sur du code d'implémentation, 37-56 % sur des fichiers
  majoritairement typés, qui sont déjà presque de la surface.

## Reproduire

```sh
python3 digest.py    # attend les fichiers .ts dans dsh-sample/
```
