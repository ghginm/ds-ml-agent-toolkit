# Project map

> Living navigation document. Keep it concise, link authoritative definitions, and distinguish current behavior from recommendations.

## System in one paragraph

State what the system does, which decision it supports, who or what consumes the output, and the most important limitation. Label material claims `Verified`, `Inferred`, or `Unknown`.

## Data-to-decision flow

```text
source → transformations → features → target → split
→ model → evaluation → artifact → operational decision
```

Annotate project-specific grain, keys, time semantics, and evidence references at material boundaries.

## Components and ownership

| Component | Responsibility | Path or system binding | Owner/source | Status |
| --- | --- | --- | --- | --- |
| Material component | Current responsibility | Repository path or neutral external binding | Authoritative owner/source | Verified, Inferred, or Unknown |

## Key entry points and commands

| Purpose | Entry point | Approved command or invocation | Evidence |
| --- | --- | --- | --- |
| Build, train, evaluate, infer, test, or schedule | Path/symbol/config | Exact command when verified | Source or run reference |

## Data, target, and feature contract

Record source grain and keys, target construction, label timing, unit of observation, prediction horizon, feature availability, and material joins/filters. Link schemas and queries rather than copying them.

## Model and evaluation contract

Record baseline/artifact identity, objective, split, evaluation population, primary and guardrail metrics, calibration/threshold logic, final-holdout boundary, and operational acceptance constraints.

## Training and inference paths

Describe how training and inference are invoked, how artifacts/configuration move between them, and any known skew or unreproducible step.

## Operational dependencies

| Neutral capability | Project binding | Read/write behavior | Authorization or unknown |
| --- | --- | --- | --- |
| `distributed_compute`, `experiment_tracker`, `scheduler`, `model_registry`, or `git_provider` | Discovered product/service/config | Current effect | Approved boundary or unresolved question |

## Known risks and unknowns

Prioritize only items that can change correctness, safety, reproducibility, or the supported decision. For each, state impact and the next discriminating check.

## Evidence and freshness

| Item | Value |
| --- | --- |
| Repository revision | Inspected revision or why unavailable |
| Evidence date/window | Relevant dates and freshness |
| Project-map owner | Responsible role or unknown |
| Last verified commands | `run.yaml` or sanitized command references |
| Material inaccessible systems | Scope, reason, and authorized next check |
