# Develop mode

Use for a new model, model improvement, feature candidate, or material algorithmic change.

## Exploration before candidate evaluation

Use bounded exploration to investigate data, features, or model ideas before choosing a candidate. Hypotheses and exploratory metrics may evolve, but record which data was used, keep the final holdout untouched, and make no production improvement claim from exploration alone. Stop exploring when another iteration is unlikely to discriminate the remaining ideas.

Move to candidate evaluation only when a result will support an accept/reject or model-improvement claim. Do not relabel repeated final-holdout tuning as exploration.

## Freeze the candidate evaluation contract

Before inspecting candidate-evaluation results, derive authoritative definitions from repository evidence and record:

- baseline artifact and code/config version;
- target, unit of observation, label timing, and prediction horizon;
- point-in-time feature availability and exclusions;
- development split and untouched final holdout;
- evaluation population and metric implementation;
- primary metric and direction;
- guardrail metrics, calibration/threshold requirements, and segment/temporal checks;
- operational constraints such as latency, volume, capacity, interpretability, or cost;
- acceptance rule and compute/time budget.

Ask only when a material ambiguity remains. If the baseline cannot be reproduced, do not make a valid improvement claim; diagnose the mismatch or stop as `not_verified`.

## Candidate loop

1. Reproduce the baseline on the frozen contract and record versions, command, seed, environment, and results.
2. Audit target, split, joins, feature timing, and leakage before selection work.
3. State one testable hypothesis and the expected metric/operational effect.
4. Implement the smallest candidate that tests it.
5. Run baseline and candidate on identical populations with the same metric code.
6. Use an ablation when multiple changes prevent attribution.
7. Quantify run/seed uncertainty, temporal behavior, or segment stability when variability can change the decision.
8. Inspect calibration and threshold behavior when scores become actions.
9. Apply the predeclared acceptance rule: `accept` or `reject`.
10. Keep accepted code minimal; remove rejected code from the production path unless it is an intentionally isolated research artifact.

## Comparison table

| Contract item | Baseline | Candidate | Comparable? | Evidence |
| --- | --- | --- | --- | --- |
| Population, split, metric, seed policy, artifact | Recorded value | Recorded value | Yes or reason no | Run/artifact reference |

A negative result is complete when it discriminates the hypothesis and preserves the baseline.

## Completion check

The result includes the frozen contract, reproducible baseline status, candidate hypothesis/change, comparable metrics, attribution evidence where needed, stability/uncertainty appropriate to the decision, an explicit decision, and remaining uncertainty. Never promote, deploy, or write to a remote registry without separate authorization.