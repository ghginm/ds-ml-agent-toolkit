# DS/ML Agent Kit — Control

## Start here

| I want to... | What to say | Useful controls | Default behavior |
| --- | --- | --- | --- |
| Work normally | Ask normally | none | Regular agent work; no workflow ceremony |
| Set up this repo | `Set up the DS/ML Agent Kit` | usually none | Inspect, configure only stable facts, validate, report readiness |
| Understand a project | `Analyze this project` | `depth=quick/deep`, `focus=...` | Evidence-based, bounded analysis |
| Technical report | `Create a technical PDF report` | `iterations=N`, `profile=...`, `focus=...`, `target length=...` | Prompt-adaptive plan, revision, and visual QA |
| Run model search | `Run autoresearch` | `metric=...`, `max experiments=N`, constraints | Confirmed, bounded experiment loop |
| Validate a result | `Independently validate this result` | `focus=...` | Read-only adversarial review |

Ordinary requests stay ordinary. `Fix this bug`, `Explain how this model works`,
and `Investigate why validation performance dropped` need no toolkit syntax.

## Setup in three steps

1. Copy the contents of `dist/project-overlay/` into the target repository root
   without overwriting project-owned files.
2. Start the agent in that repository and say `Set up the DS/ML Agent Kit`.
3. Read the `READY`, `READY_WITH_WARNINGS`, or `ACTION_REQUIRED` result. After a
   required fix, say `Recheck DS/ML Agent Kit setup`.

Health check:

```text
python3 -B .agent-system/tooling/validate-kit.py --installed-project .
```

## Workflow controls

| Workflow | Controls worth using | Defaults |
| --- | --- | --- |
| Technical report | `profile=quick/standard/publication`, `iterations=N`, `focus`, `target length`, `audience`, `detail` | Standard includes one meaningful revision; PDF only when rendered and visually verified |
| Autoresearch | `metric`, direction, `max experiments`, editable scope, guardrails, holdout rule | Finite local search; usually 10 cheap experiments; final holdout protected |
| Independent validation | `focus`, claims to test, unavailable evidence | Read-only falsification of decision-relevant claims |

Parameters are plain language, not a required form. Explicit values override
workflow defaults; missing values are inferred when safe.

## Copy/paste examples

```text
Analyze this project. depth=quick
```

```text
Create a technical PDF report on model design, features, evaluation and current issues.
iterations=3
target length=6-8 pages
```

```text
Create the same report with iterations=3 and target length=8 pages.
```

```text
Run autoresearch.
metric=PR-AUC
max experiments=15
do not use the final holdout
```

```text
Independently validate the claimed lift. focus=split integrity and metric comparability
```

```text
Fix this data preprocessing bug and add a regression test.
```

Need more detail? See [`SYSTEM.md`](SYSTEM.md).
