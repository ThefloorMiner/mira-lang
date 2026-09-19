# Expérience — `mi api` pour TypeScript

**Question :** l'idée de [§7](../../SPEC.md#7--compression-de-contexte) — donner à un agent la *surface
publique* d'un module plutôt que son source — tient-elle sur du vrai code ?

**Terrain :** [`deepseek-ai/deepseek-harness`](https://github.com/deepseek-ai/deepseek-harness),
six fichiers de `packages/core/`, 272 564 caractères.

**Point de comparaison :** leur propre
[`dsh-compaction-tool-result-pruner`](https://github.com/deepseek-ai/deepseek-harness/tree/main/packages/compaction/compaction-tool-result-pruner),
qui tronque tout résultat d'outil dépassant 8 192 caractères en gardant les 4 096 premiers, un marqueur,
et les 1 024 derniers.

## Résultat

```
fichier                    source head/tail  digest    +doc  sym  h/t  dig
--------------------------------------------------------------------------
agent-loop/agent.ts        25,001     5,159     869     929    1    1    1
agent-loop/index.ts        40,149     5,159   2,215   3,415    9    2    9
agent/index.ts             31,075     5,159   7,774  10,555    7    4    7
session/index.ts           59,815     5,159   3,466   5,426    7    4    7
session/surface.ts         27,707     5,159   3,790   7,594   14    5   14
tools/index.ts             88,817     5,159  15,804  21,033   30    5   30
--------------------------------------------------------------------------
TOTAL                     272,564    30,954  33,918  48,952   68   21   68

head/tail   :  11.4 % des caractères ·  30.9 % des symboles publics
digest      :  12.4 % des caractères · 100.0 % des symboles publics
digest +doc :  18.0 % des caractères · 100.0 % des symboles publics
```

**À taille pratiquement égale — 12,4 % contre 11,4 % — le digest conserve la totalité de la surface
publique là où la troncature en perd 69 %.**

## Pourquoi, et ce que ça ne dit pas

La troncature head/tail est une stratégie *générique*, et c'est un choix raisonnable : elle doit traiter
des sorties de commandes, des résultats de recherche, des logs. Elle est simplement **aveugle au
contenu**, et le code source est le cas où ça coûte le plus cher : les 4 096 premiers caractères d'un
fichier TypeScript, ce sont les imports et une ou deux déclarations ; les 1 024 derniers, la fin
arbitraire du fichier. Tout ce qui est au milieu — l'essentiel des signatures — disparaît.

Ce n'est donc pas un défaut de leur *architecture*, c'est un vide de leur *catalogue de plugins* : la
famille `compaction/` est explicitement conçue pour qu'on y ajoute des stratégies. Un pruner conscient du
code s'y branche à côté de l'existant, sans le remplacer.

**Ce qui n'est pas mesuré ici :** l'argument complet est qu'un fichier amputé de 69 % de ses symboles
n'est pas exploitable, donc l'agent relit le fichier entier, et le coût réel de la troncature devient
11,4 % + 100 %. C'est plausible ; ce n'est pas prouvé. Le test suivant est le banc
[`conversation-fold`](https://github.com/deepseek-ai/deepseek-harness/tree/main/benchmarks/conversation-fold)
de dsh.

## Ce que le digest produit

Surface publique complète, corps de fonctions et de méthodes jetés, membres `private` retirés, types
internes conservés s'ils sont atteignables depuis une signature exportée, imports réduits à une ligne.
La sortie est un `.d.ts` lisible — extrait réel de `packages/core/agent-loop/src/agent.ts`, 25 001
caractères ramenés à 869 :

```ts
// imports: assistant-stream.ts, cordis, dsh-agent, dsh-llm, dsh-scope, dsh-session, …

export class ReactLoopAgent implements Agent {
  readonly inbox: ReactLoopInbox
  readonly scope: Scope
  readonly ctx: Context
  constructor(
    private loopCtx: Context,
    public readonly id: SessionId,
    public readonly options: AgentOptions,
    public readonly session: Session,
  )
  get status(): AgentStatus
  send(message: UserMessage, target: InboxTarget, wakeup: boolean): void
  followup(input: UserMessage): void
  steer(input: UserMessage): void
  inject(input: UserMessage): void
  cancel(cause: AgentCancelCause, options: CancelOptions = {}): void
  runMaintenance<T>(job: (signal: AbortSignal) => Promise<T>): Promise<T>
  async whenIdle(): Promise<void>
}
```

## Implémentation

`digest.mjs` marche sur l'AST du compilateur TypeScript — pas de regex, pas de comptage d'accolades.
Une première version par expressions régulières donnait 32,5 % au lieu de 12,4 % et tronquait les
signatures multi-lignes ; elle a été jetée. Les accolades dans les chaînes, les gabarits et le JSX sont
exactement le genre de choses qu'un parseur gère et qu'une regex n'attrapera jamais.

| Fichier | Rôle |
|---|---|
| `digest.mjs` | `apiDigest(src, {keepDoc})` et `publicSymbols(src)` |
| `measure.mjs` | comparaison head/tail vs digest sur un dossier |
| `inspect.mjs` | affiche le digest d'un fichier |

## Reproduire

```sh
npm install
mkdir corpus
# récupérer quelques fichiers, par exemple :
gh api -H "Accept: application/vnd.github.raw" \
  repos/deepseek-ai/deepseek-harness/contents/packages/core/session/src/index.ts \
  > corpus/session_index.ts

npm run measure
node inspect.mjs corpus/session_index.ts
```

## Limites

- **Caractères, pas tokens.** L'unité de budget de dsh est le point de code Unicode, donc la comparaison
  est juste — mais le rapport en tokens diffère un peu.
- **Six fichiers, un seul dépôt.** L'échantillon est petit et tous les fichiers viennent de `core/`.
- Le gain dépend du fichier : 3 à 6 % sur du code d'implémentation, jusqu'à 25 % sur des fichiers
  majoritairement typés, qui sont déjà presque de la surface.
- Rien de tout ceci ne teste l'hypothèse centrale : qu'un digest évite une relecture.
