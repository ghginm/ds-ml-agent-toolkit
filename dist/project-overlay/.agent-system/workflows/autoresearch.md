# Autoresearch workflow

## Trigger and controls

Use when the user explicitly requests autoresearch or clearly authorizes repeated
autonomous experiments against a measurable objective. Do not use for an ordinary
bug fix, explanation, one-shot experiment, or vague request to improve a model.

| Parameter | Default |
| --- | --- |
| metric and direction | Infer only when unambiguous; otherwise ask |
| `max experiments` | 10 cheap local experiments |
| editable scope | Smallest repository-supported scope |
| guardrails | Existing tests plus relevant metric/resource constraints |
| final holdout | Never used as the repeated search objective |

## Contract

1. Use the `autoresearch` skill to reconstruct and show a compact preflight.
2. Obtain confirmation unless the initial request already supplies a complete,
   safe contract and explicitly authorizes immediate execution.
3. Isolate user work, reproduce the baseline, and freeze the evaluation contract.
4. Run the bounded hypothesis → edit → evaluate → decide loop without per-candidate
   approval; record all kept, discarded, crashed, and invalid experiments.
5. Stop at the budget, target, plateau, invalid evaluation, or capability gate.

Complete with baseline/best comparison, experiment counts, stopping reason,
guardrails, retained local revision, and uncertainty. Material improvement claims
go to independent validation.
