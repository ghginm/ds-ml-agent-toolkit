---
name: validate-dsml-result
description: Independently challenge DS/ML/AML analyses, changes, experiments, and model claims with read-only adversarial review; not implementation or routine developer checks.
license: MIT
metadata:
  author: "ghgin, Hermes Agent"
  version: "0.6.2"
---

# Validate DS/ML Result

Independently challenge an analysis, change, experiment, or model claim against the original task and raw evidence. Keep review read-only with respect to product code; normal developer checks remain the responsibility of the executor.

## When to use

Use for explicit validation/audit/critique, review-ready deep reports, model improvement claims, material changes to target/split/metric/feature timing/grain, AML or other high-impact decisions, release/governance preparation, or material residual uncertainty.

Do not trigger the full adversarial workflow for a simple explanation, trivial lookup, formatting-only change, routine non-semantic refactor, or early exploration that supports no decision.

## Inputs and scope

Prefer the original request and acceptance criteria, repository revision and diff, commands and raw results, tests, versions of data/query/features/model/artifacts, metrics, and stated assumptions. Read `.agent-system/project.yaml` when present for environment facts, but treat repository evidence and higher-level policy as authoritative. In tracked work evidence should be referenced by `run.yaml`; missing evidence is a review result, not a form-filling request.

Read [references/review-surfaces.md](references/review-surfaces.md) and load only the surfaces relevant to the central claims. For an actual AML context, additionally read [references/aml.md](references/aml.md).

## Workflow

1. Reconstruct the original task, acceptance criteria, and decision being supported; do not inherit the author's persuasive framing as fact.
2. Identify the few central claims whose failure changes that decision.
3. Verify provenance: what actually ran, on which code/input/artifact versions, and which claimed checks lack raw evidence.
4. Select relevant review surfaces and the highest-value counterexample or alternative explanation for each central claim.
5. Run only safe, permitted falsification checks. Do not alter product code; isolated scratch calculations or synthetic fixtures must remain outside the product path.
6. Record findings with severity, claim, evidence, failure mechanism, impact, required action, and verification status.
7. Issue one verdict and the smallest set of required actions. Distinguish unavailable checks from passed checks.

When structural agent independence is unavailable, start a fresh sequential pass from the original task and raw artifacts rather than the author's narrative. State that the review was logically separated but not independently executed.

## Finding severities and verdicts

- `BLOCKER`: central conclusion invalid or action unsafe.
- `HIGH`: likely to change the decision or system correctness.
- `MEDIUM`: material limitation or incomplete coverage.
- `LOW`: useful, non-blocking improvement.

Verdicts:

- `PASS`: acceptance is supported and no material finding remains.
- `PASS_WITH_UNCERTAINTY`: no known blocker for an explicitly limited use, but material checks remain unavailable; never production approval.
- `REQUIRES_CHANGES`: concrete fixable issues prevent acceptance.
- `NOT_VERIFIED`: the central claim lacks sufficient evidence.
- `BLOCKED`: required access, artifacts, or permission prevent meaningful or safe validation.

When concrete fixable findings already invalidate acceptance, use `REQUIRES_CHANGES` even if additional evidence is also missing. Reserve `NOT_VERIFIED` for an unsupported central claim when the available evidence does not establish a specific required correction.

## Outputs and handoff

Return an answer-first verdict, central claims tested, material findings using `.agent-system/templates/finding-report.template.md`, checks actually run, unavailable checks, and required actions. Do not flood the report with style preferences or generic best practices.

Hand fixes back to `execute-dsml-task`. After correction, revalidate affected claims and surfaces rather than mechanically repeating the entire review.

When the review is tracked, use `.agent-system/tooling/create-run.py` to initialize sibling records. At finalization, set execution and user outcome independently; use `unknown` without explicit acceptance, rejection, or rework evidence. Inspect the request, route/corrections, acceptance criteria, validation, final result, user feedback, rework, and material detours. Keep project/domain findings `scope: project`; add `scope: kit` only for a reusable toolkit weakness, meaningful rework, systematic quality gap, recurring pattern supported across records, or missing/misleading capability. Emit zero to three actionable signals with `suggested_change` and sibling-run `evidence_ref`; a correctly rejected candidate and a clean successful review may need none. Detailed evidence remains in `run.yaml`. A failed learning-record write is auxiliary and learning evidence may not trigger automatic edits to released toolkit content.

## Stopping conditions

Stop when central claims received a meaningful falsification attempt, decision-relevant surfaces are covered, unavailable checks are explicit, and the verdict follows from the findings. Stop as `NOT_VERIFIED` or `BLOCKED` rather than manufacturing evidence.

## Pitfalls

- Test success alone does not validate a model or analytical conclusion.
- An improvement is not comparable when population, split, metric implementation, or baseline artifact changed.
- Absence of an artifact is not evidence a command failed; it is missing provenance.
- Validation may conclude the existing implementation and no-change decision are correct.

## Verification

Every verdict must trace to findings and actual evidence. Each material acceptance claim must have either a falsification result or an explicit unavailable check with impact. The reviewer must not implement the required fixes.
