---
name: execute-dsml-task
description: Diagnose, implement, or evaluate DS/ML/AML changes for concrete regressions, fixes, and model experiments; not broad project orientation or independent validation.
license: MIT
metadata:
  author: "ghgin, Hermes Agent"
  version: "0.14.0"
---

# Execute DS/ML Task

Diagnose a concrete model, data, metric, or pipeline problem; implement an authorized fix; or evaluate a model candidate under a defensible contract. Do not use this workflow for broad project orientation or independent review.

## When to use

Use for model degradation, metric discrepancies, data/pipeline bugs, requested root-cause fixes, feature/model behavior changes, new models, model improvement, and comparative experiments.

Do not use primarily for an architecture map, descriptive handover, generic ML explanation, independent validation, a routine edit with no DS/ML semantics, or an explicit autonomous repeated measurable search that routes to `autoresearch`.

## Minimum input and mode

A natural-language goal and accessible repository are normally enough. Read `.agent-system/project.yaml` when present, but infer authoritative baselines, commands, splits, and metrics from repository evidence. Ask only when multiple baselines are plausible, success criteria materially conflict, restricted data/full training is necessary, requested mutation is not authorized, or an operational constraint defining success is genuinely unknown.

Select one mode and load only its reference:

- **diagnose** for a symptom, regression, discrepancy, or suspected bug: [references/diagnose.md](references/diagnose.md).
- **develop** for a new model, model improvement, feature candidate, or material algorithmic experiment: [references/develop.md](references/develop.md).
- For either mode in an actual AML context, additionally load [references/aml.md](references/aml.md).

Ordinary diagnosis, fixes, and bounded developer checks need no run record. Use
`.agent-system/tooling/create-run.py` for formal model experiments or explicitly
tracked/controlled work. Sensitive data, costly compute, remote writes, or release
actions remain controlled unless their exact scope is already authorized.

## Shared workflow

1. Reconstruct the goal, bounded scope, constraints, data classification, action gates, evaluation, and acceptance from the request and repository evidence.
2. Read organization/repository/path instructions and the relevant project map or entry points.
3. Establish the baseline behavior and evidence before changing the candidate path.
4. Verify target, grain, keys, joins, feature timing, split, metric population/implementation, and training-inference boundary only where relevant to the task.
5. State a falsifiable hypothesis or failure mechanism; choose the smallest change or check that discriminates it.
6. Execute only allowed actions. When a run record is warranted, record commands actually run, versions, sanitized results, changes, assumptions, and uncertainty. Reference detailed report or experiment sections instead of copying their domain output; retain concrete metrics only when they justify a criterion, decision, or comparison.
7. Perform normal developer validation; compare like with like and add a regression check for a demonstrated bug.
8. Accept, reject, or leave unresolved according to predeclared evidence—not the attractiveness of the result.

## Outputs and handoff

Diagnosis-only returns the mechanism, evidence, confidence (`confirmed`, `strongly_supported`, `plausible`, or `unresolved`), affected scope, next check/fix, and unverified assumptions.

Diagnosis plus fix returns a minimal diff, regression check, before/after evidence, and limitations. Exploration returns bounded hypotheses and exploratory evidence without a final improvement claim. Candidate evaluation returns the frozen evaluation contract, minimal candidate, run record, comparable baseline table, ablation where attribution needs it, and an explicit `accept` or `reject` decision.

Use `validate-dsml-result` when the result supports a material decision, changes target/split/metric/feature timing/grain, makes an improvement claim, or retains material uncertainty.

At completion, set `learning.yaml` outcome fields independently: execution comes from the run result, while user outcome is `accepted`, `rework_required`, or `rejected` only with explicit evidence and is otherwise `unknown`. Inspect the request, actual/corrected route, acceptance criteria, validation, final result, user feedback, rework, and material detours. Keep project/domain findings `scope: project`; add `scope: kit` only for a reusable toolkit weakness, meaningful rework, systematic quality gap, recurring pattern supported across records, or missing/misleading capability. Emit zero to three strong signals, each with a proportionate `suggested_change` and sibling-run `evidence_ref`; empty `signals` is normal. Do not duplicate run evidence or infer recurrence from one run. A failed learning-record write is auxiliary: report it without downgrading the primary result or claiming persistence. Never rewrite released toolkit content automatically.

## Stopping conditions

Stop when the root cause is sufficiently supported, acceptance is met, the candidate should be rejected, the evaluation is invalid, the baseline cannot be reproduced, the next action is gated, budget is exhausted, or another iteration is unlikely to discriminate hypotheses. A correct result may be no production change.

Commits, pushes, pull requests, deployments, registry writes, and remote configuration changes must be authorized for their exact scope. Do not re-request authorization already recorded by approved policy; never infer broader authorization from a narrower one.

## Pitfalls

- Do not make several speculative edits and infer causality from a disappearing symptom.
- Do not change the primary metric, population, or acceptance rule after seeing candidate results without an explicit evidence-based reason.
- Do not repeatedly tune against the final holdout or compare runs with different populations/metric code.
- Remove rejected candidate code from the production path unless it remains an explicitly isolated research artifact.

## Verification

The final claim must be traceable to commands and artifacts actually produced. A fix needs a regression check; a model decision needs comparable baseline evidence under the frozen contract; unavailable evidence must yield `unresolved` or `not_verified`, never a fabricated success.
