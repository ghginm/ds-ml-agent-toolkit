# Decision-relevant review surfaces

Select only surfaces capable of changing the supported decision. For each central claim, seek the most plausible counterexample rather than grading presentation quality.

## Analysis or report

Check claim-to-source traceability, evidence freshness, contradictions, unsupported causality, selective omission, and correct use of `Verified`, `Inferred`, `Unknown`, and `Recommendation`.

## SQL and data pipeline

Check unit of observation, keys, expected join cardinality, row counts before/after joins, duplicate/null behavior, filters, temporal boundaries, source/query versions, and label integrity. A passing query is not proof of correct grain.

## Features

Check point-in-time availability, target/entity/time leakage, unstable proxies, training-inference definitions, online/offline defaults, and whether missing-value handling changes meaning.

## Model and experiment

Check baseline artifact and reproducibility, identical evaluation population/split/metric implementation, final-holdout isolation, seed/run uncertainty, candidate attribution or ablation, calibration, threshold selection, and rejection-rule consistency.

## Operational behavior

Check how scores become decisions, alert/action volume, capacity, latency, fallback, threshold drift, temporal and material segment stability, monitoring, and impact of failures.

## Reproducibility

Check repository revision/diff, sanitized input and dataset/query/feature/model versions, environment, seed policy, command, exit/result evidence, metric code, and artifact identity. A narrative claim that a test ran without command/result provenance remains `NOT_VERIFIED`.

## Falsification matrix

| Central claim | Plausible counterexample | Safe check | Result | Decision impact |
| --- | --- | --- | --- | --- |
| One acceptance-critical statement | Alternative mechanism or invalidating population | Exact permitted check or unavailable reason | Evidence reference | Verdict consequence |

## Finding quality

For each material finding provide:

- `severity`;
- `claim`;
- `evidence`;
- `failure_mechanism`;
- `impact`;
- `required_action`;
- `verification_status` (`verified`, `partially_verified`, `not_verified`, or `blocked`).

Do not convert missing evidence into a defect claim. State what cannot be verified and choose the verdict from its decision impact.