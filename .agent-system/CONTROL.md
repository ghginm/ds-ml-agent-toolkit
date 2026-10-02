# DS/ML Agent Kit — Control

## Start here

| I want to... | What to say | Useful controls | Default behavior |
| --- | --- | --- | --- |
| Work normally | Ask normally | none | Regular agent work; no workflow ceremony |
| Set up this repo | `Set up the DS/ML Agent Kit` | usually none | Inspect, configure only stable facts, validate, report readiness |
| Understand a project | `Analyze this project` | `depth=quick/deep`, `focus=...` | Evidence-based, bounded analysis |
| Technical report | `Create a technical PDF report` | `iterations=N`, `profile=...`, `focus=...`, `target length=...` | Prompt-adaptive plan, revision, and visual QA |
| Run model search | `Run autoresearch` | `metric=...`, `max experiments=N`, constraints | Confirmed, bounded experiment loop; final holdout is one-shot at the managed evaluation boundary |
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

If validation reports missing or inconsistent toolkit-owned runtime files, repair
from a trusted clean overlay with the same toolkit version. Project-owned files are
not overwritten:

```text
python3 -B /path/to/clean-overlay/.agent-system/tooling/onboard-project.py \
  --installed-project . --repair-runtime /path/to/clean-overlay --recheck
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

### Lean autoresearch example

The user normally supplies only the research objective and important
constraints. The agent reconstructs a project-appropriate evaluation contract
from the request and repository evidence, and generic runtime tooling then
validates that explicit contract. The forecasting prompts below demonstrate how
that reconstruction works; forecasting metrics and rolling-origin evaluation
methods are not hard-coded scientific semantics of the toolkit.

```text
Run autoresearch.

Goal: improve forecast reconsolidation.
Selection metric: out-of-sample RMSE, minimize.
Report FA as a secondary business metric.
Max experiments: 10.

Use a proper rolling-origin / time-aware CV loop and compare candidates like-for-like.
Do not repeatedly optimize against the final holdout.

Explore:
- the previous LightGBM implementation;
- the best Holt's model from prior runs;
- forecast reconsolidation approaches.

For reconsolidation, investigate graduality, low- vs high-volume SKUs,
long-term patterns such as yearly seasonality, and other evidence-supported approaches.

Use an adaptive research loop: later experiments should be informed by earlier results.
Prefer simpler solutions unless additional complexity produces a meaningful improvement.
```

The same architecture reconstructs a non-forecasting project from an equally
lean request — for example a fraud classifier — where the contract ends up with
a maximizing `AUROC` selection objective, a maximizing reporting metric, and a
minimizing latency guardrail, with no toolkit source change:

```text
Run autoresearch.
Goal: reduce fraudulent chargebacks without increasing review workload.
Optimize cross-validated AUROC; keep p99 inference latency roughly flat.
Max experiments: 8.
```

### Forecasting reconstruction example

```text
Run autoresearch.

Goal:
Find a better forecast-reconsolidation approach than the current baseline.

Experiment mode:
Adaptive autoresearch.

Selection objective:
Out-of-sample RMSE, minimize.

Secondary / business metric:
Forecast Accuracy (FA), maximize.
Do not accept an RMSE improvement if important business metrics or declared guardrails materially deteriorate.

Evaluation:
Use proper time-aware rolling-origin cross-validation.
Keep train, validation, and candidate comparisons like-for-like.
Respect point-in-time feature and label availability.
The final holdout must not be used as the repeated search objective.
If the supposed final holdout has already been exposed in previous research,
treat it as validation and report that no untouched estimate remains unless a new holdout exists.

Budget:
max experiments=10

Candidate space:
- existing baseline;
- previous LightGBM implementation;
- best previously successful Holt's implementation;
- forecast reconsolidation approaches.

Research directions:
- gradual versus immediate reconciliation;
- different treatment of low- and high-volume SKUs;
- long-term demand structure;
- yearly seasonality where supported by available history;
- segment-specific versus global reconciliation;
- combinations suggested by earlier experiment results.

Research behavior:
Start with cheap, high-information hypotheses.
Each adaptive experiment should have a mechanism/rationale and use prior evidence.
Detect duplicate configurations or predictions rather than spending experiment budget on them.
Prefer simpler candidates unless additional complexity yields a meaningful and robust gain.

Reconstruct the executable evaluation contract from this request and repository evidence.
Show a compact preflight before execution and flag material ambiguity rather than silently choosing different evaluation semantics.
```

```text
Independently validate the claimed lift. focus=split integrity and metric comparability
```

```text
Fix this data preprocessing bug and add a regression test.
```

Need more detail? See [`SYSTEM.md`](SYSTEM.md).
