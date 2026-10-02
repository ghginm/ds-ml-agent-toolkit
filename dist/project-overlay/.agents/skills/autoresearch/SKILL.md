---
name: autoresearch
description: Run bounded autonomous repeated experiments against a measurable objective; use for explicit autoresearch requests or clear multi-candidate optimization, not ordinary one-shot model development.
license: MIT
compatibility: Requires local Git, terminal command execution, and a reproducible experiment evaluation command.
metadata:
  author: "Luis Cantero (upstream), adapted by ghgin and Hermes Agent"
  version: "0.8.0"
  inspired-by: "https://github.com/karpathy/autoresearch"
---

# Autoresearch

Run a bounded autonomous hypothesis → edit → evaluate → decide loop while protecting user work and DS/ML evaluation validity. This adaptation is based on Luis Cantero's MIT-licensed `autoresearch` skill and Karpathy's autoresearch concept.

## Routing

Use this skill when the user explicitly says `autoresearch`, asks for an autonomous experiment loop, asks for a stated number of automatic experiments, or asks to keep iterating and measuring without confirmation after each candidate.

A natural-language request also selects this skill only when all three are clear:

1. repeated or autonomous experimentation;
2. a measurable objective;
3. permission to try multiple candidate changes.

For example, “Automatically try feature and model changes and keep only changes that improve PR-AUC” selects autoresearch.

Do not select autoresearch for “improve this model,” one feature experiment, one model comparison, one-shot fixes, routine bugs or edits, explanations, code review, or work without a measurable outcome. Route normal bounded candidate work to `execute-dsml-task` develop mode. Project-specific skills remain preferred when their narrower domain workflow is the main request.

## Startup: infer, preflight, confirm

Before any candidate mutation, inspect the request and authoritative repository evidence. Reconstruct the executable `evaluation.yaml` contract; the user does not need to write it. Infer what is already clear instead of asking the user to restate it, then show only a compact **Autoresearch preflight** in this shape, omitting irrelevant lines:

```text
Goal: ...
Mode: benchmark | adaptive
Selection: <metric> ↑|↓
Secondary: ...
Evaluation: ...
Final holdout: untouched | previously exposed | unavailable
Point-in-time checks: enabled | unverified | not applicable
Budget: max N
Guardrails: ...
```

Freeze the exact evaluation command/pipeline and extraction method, editable/protected scope, meaningful delta, dataset/population, target, development/final splits, timing, and compute limits in the internal contract and run evidence. Do not dump the full contract into chat unless requested.

Generic runtime validation treats metric names as opaque identifiers whose semantics are declared, never inferred from the name. Bounded parsing in `.agent-system/tooling/reconstruct-contract.py` extracts the metric phrase, any explicit direction and role, and evaluation qualifiers: out-of-sample/OOS/holdout/CV/rolling/temporal wording is evaluation-design context, so “out-of-sample RMSE” reconstructs to metric `RMSE` plus evaluation context, exactly as “holdout F1” is `F1` plus evaluation context. Preserve a direction the user stated explicitly; use project/repository evidence for metrics that repository defines; when direction cannot be established safely, surface the unresolved metric in the preflight instead of inventing one. Optimization wording determines the selection objective; a metric mentioned for reporting does not silently become the search target. In the forecasting example, `metric=FA` plus `optimization via OOS RMSE` reconstructs as selection `RMSE` with the repository-declared minimizing direction and `FA` as a maximizing reporting/business metric. Ask only when optimization directives genuinely conflict, no reproducible evaluation exists, scope cannot be bounded, or a capability gate is unresolved. When timing metadata cannot prove feature or label availability, record explicit assumptions as `unverified` and surface that state instead of claiming point-in-time safety; for non-temporal projects leave point-in-time checks disabled (`not_applicable`) rather than inventing cutoffs.

Respect an explicit experiment count as a hard ceiling. Otherwise propose and show a conservative finite budget—normally 10 cheap local experiments—so the user can change it. Canonical budget accounting is one shared rule across `record-experiment.py`, plateau stopping, `run.yaml` counters, and `finalize-run.py`: the baseline establishes the reference measurement and does not consume the novel experiment budget; each valid novel candidate consumes one unit; duplicates, crashed, and invalid candidates never consume budget. `record-experiment.py` rejects another budget-consuming novel candidate once the ceiling is reached. Unlimited operation requires an explicit request and still cannot cross capability or compute gates.

Ask the user to confirm or correct the complete preflight before establishing the baseline or making candidate changes. Normal responses such as “yes,” “go ahead,” or corrections to one field are sufficient; ritual wording is not required. A request may skip the extra confirmation round only when it already supplies a sufficiently complete contract, explicitly authorizes immediate execution without another question, and leaves no safety or capability ambiguity. Even then, record or briefly show the reconstructed preflight before proceeding. A bare `Run autoresearch` is never pre-authorization.

## Establish safe local Git isolation

Before the baseline:

1. From the user's initial working directory, before creating or entering any isolated worktree, resolve `canonical_project_root` with `git rev-parse --show-toplevel` and record the starting revision. Retain that absolute root for the entire run; never recompute it from a later current working directory.
2. Inspect the working tree. A dirty active worktree does not block autoresearch when safe isolation is available. Never discard, reset, stash, clean, include, or commit pre-existing user changes.
3. Treat `canonical_project_root`, the new `experiment_worktree_root`, and the `toolkit_root` from which tooling/templates are loaded as three separate paths. They are not interchangeable.
4. Prefer a separate local Git worktree on a dedicated `autoresearch/<run-id>` branch rooted at the recorded revision. Keep the user's active worktree exactly untouched and exclude its uncommitted changes from every experiment.
5. Confirm experiment edits and rollback are confined to `experiment_worktree_root`. Proceed there even when the active worktree is dirty; if safe isolation cannot be established, stop before experimentation.
6. Candidate source edits, experiment commits, checkout, and destructive rollback belong only in the isolated worktree. Writing toolkit-owned evidence below the canonical root does not authorize source-code changes in the active worktree.
7. Do not initialize Git unless repository-level mutation is already authorized.

Task-authorized local branch/worktree creation, local experiment commits, checkout, and rollback inside the isolated workspace are local versioning operations. They do not authorize remote effects. Never push, create a remote branch or repository, open a pull request, or change remote configuration unless that exact remote action is separately authorized. A configured remote is not permission to use it.

Destructive rollback is permitted only against experiment commits created in the dedicated isolated worktree. Never run destructive reset where it can affect pre-existing or unrelated work.

## Create run evidence and freeze evaluation

Autoresearch may execute in an isolated worktree, but durable run evidence belongs to the canonical user project root from which the run was initiated. Never use the isolated worktree or toolkit installation as the sole evidence location. Every relative `.agent-system/runs/...` reference is relative to `canonical_project_root`, not the current execution directory.

Invoke the available `create-run.py` with `--project-root <canonical_project_root> --autoresearch --experiment-mode benchmark|adaptive --max-experiments N` to initialize `run.yaml`, `learning.yaml`, `evaluation.yaml`, and `experiments.tsv` under `<canonical_project_root>/.agent-system/runs/<run-id>/`. The script location supplies templates and toolkit version only; it never selects the evidence destination. If the canonical root cannot be resolved safely, stop instead of guessing or defaulting to the toolkit installation. After creation, retain the absolute `run_dir` and use concrete paths below it for every evidence update even while the process CWD is `experiment_worktree_root`.

`evaluation.yaml` separates the selection objective, reporting metrics, mandatory guardrails, split identity/exposure, point-in-time verification, and conservative stopping rule. Before calling a final split untouched, compute or recover stable split and dataset hashes and check `.agent-system/evaluation-ledger.jsonl`. A prior final exposure means it is now selection/validation data, a new outer holdout is required, or the report must say that no untouched final estimate remains. Exposure is committed before the protected evaluation can run: `record-experiment.py --reserve-final-exposure` appends the stable-identity event idempotently first, so an interrupted run cannot leave a protected holdout looking pristine; any stage-`final` submission is mechanically refused until that reservation exists (including duplicate-coerced or crashed rows, because starting the protected pipeline may already have exposed the population), a run may record at most one evaluated stage-`final` experiment (a repeated protected query is downgraded to a duplicate, never fresh one-shot evidence), and a stage-`final` evaluation of a split another run already exposed is refused while the contract claims it untouched. Ledger order is what each reservation sees: the event fixes its own run's exposure state at commit time, so a later reservation by another run cannot retroactively invalidate an earlier authorized one-shot final evaluation, while a run without its own reservation sees the prior exposure. Prefer `record-experiment.py --run-protected-evaluation <run> --row-json HANDOFF -- COMMAND`: it preflights the lifecycle, commits the reservation durably, and only then executes the opaque evaluation command, which must write its experiment row to the path exported as `$DSML_PROTECTED_ROW_JSON`. Outside that wrapper the toolkit cannot sequence an evaluator's actual execution against the ledger — reserve first, always. Finalization verifies exposure state instead of first creating it.

The canonical journal records `experiment_id`, parent/stage, code/config/runner/input/prediction identity, selection outcome, guardrail status, lifecycle status, adaptive rationale, evidence novelty, and artifact reference. Use `record-experiment.py` so duplicate config/candidate identity is detected before normal budget use and duplicate predictions are detected after execution. Duplicate detection reasons over experimental identity — candidate identity plus evaluation context: repeating a candidate within the same context is a duplicate that consumes no budget, while the reserved protected re-evaluation of the promoted frozen candidate is a new scientific evaluation role, not a duplicate. That reuse is mechanically anchored, never claimed by a stage label: the stage-`final` row must repeat the promoted row's `candidate_identity` with identical values for every immutable provenance field the promoted row declares, and no other row may already carry those identities or the final row's prediction hash; an unanchored or mutated `final` row is rejected or downgraded, and the protected evaluation of the already-counted candidate never consumes the novel experiment budget. Git revision alone is never candidate identity, and its absence is never a provenance gap: `missing_provenance` is derived from the actual immutable-provenance contract — a candidate needs enough immutable identity to be uniquely resolvable (`candidate_identity` plus at least one content-addressed artifact such as a config, runner, input-manifest, prediction hash, or code revision), so a legitimately config-only candidate with no Git state is complete evidence.

An ephemeral local `run.log` may retain bounded diagnostic output. Large candidate outputs, caches, temporary predictions, and logs may remain disposable inside `experiment_worktree_root`. Copy any final artifact needed to understand or reproduce the selected result into `run_dir`, or reference a deliberately persistent location; never leave the final result available only in a disposable worktree. Do not persist secrets, raw customer rows, complete sensitive terminal output, or hidden reasoning.

Only after the preflight is accepted or validly pre-authorized, create the isolated workspace and run evidence. Before candidate edits, reproduce and record the baseline. If it cannot be reproduced, stop as blocked or unresolved. Freeze the candidate-comparison contract:

- dataset/population, target, split, time window, and feature timing;
- selection metric implementation and direction, separate reporting metrics, and mandatory guardrails;
- baseline and candidate commands;
- point-in-time feature and actual label availability, or explicit unverified assumptions;
- development evaluation versus protected final holdout;
- resource limits and acceptance conditions.

Iterate on the approved development/validation evaluation. Never turn a final holdout into the repeated fitness function. Baseline and candidates must remain like-for-like; reject gains caused by leakage, changed rows/splits/preprocessing/metric code, target availability, or inference assumptions.

## Autonomous experiment loop

After the baseline, continue without asking “should I continue?” until a stopping condition applies.

In `benchmark` mode, evaluate a mostly predeclared candidate set independently. In `adaptive` mode, each post-baseline novel experiment records its parent, falsifiable hypothesis, expected mechanism, focused change, result, and next-hypothesis rationale; later candidates must use prior evidence. Lineage is causally ordered and mechanically checked: an experiment can never parent itself, a parent must appear earlier in the ordered journal than its child, and future-parent or cycle claims are rejected. The baseline establishes the reference and needs no adaptive parent. A fully predeclared independent sweep is benchmark mode, or must explicitly record that no adaptive evolution occurred. Config-only candidates are valid when immutable identity changes; a source diff is not required.

For each experiment:

1. **THINK** — form one focused, falsifiable hypothesis using previous results. Prefer low-cost/high-information and simple changes; diversify after a plateau and combine winners only when attribution remains understandable. Only after incremental and low-cost directions are exhausted, consider larger or more architectural hypotheses when they remain within the confirmed scope, budget, capability policy, and frozen evaluation contract. Do not use this as justification for unnecessary large rewrites.
2. **EDIT** — make one focused in-scope change. Avoid unrelated churn.
3. **RECORD LOCAL REVISION** — create a local experiment commit for evidence and rollback in the isolated branch.
4. **RUN** — execute the frozen evaluation and relevant guardrails. Protected
   final evaluation is one-shot at the managed evaluation boundary. Before
   executing or observing any protected stage-`final` evaluation, first commit
   its exposure with `record-experiment.py --reserve-final-exposure`, or run
   it through `record-experiment.py --run-protected-evaluation <run-id>
   --row-json HANDOFF -- EVALUATOR_COMMAND`, which commits the reservation
   durably, then commits a second `kind: execution_consumed` ledger event,
   and only then executes the opaque command; a promoted candidate evaluated
   on the reserved protected population is the protected final evaluation of
   that same frozen candidate, never a new research experiment. Once the
   managed execution has begun, no later managed invocation for the same
   run + protected population will launch the evaluator again — a crash,
   non-zero exit, lost handoff, or process-spawn failure leaves the run
   with no valid untouched final estimate for that population; the run must
   use a new untouched final population if another genuinely untouched
   estimate is required. Keep verbose output out of context while retaining
   enough bounded diagnostics for failures.
5. **MEASURE** — extract the selection objective, reporting metrics, guardrail results, execution status, and contracted resource measures.
6. **DECIDE** — assign one explicit lifecycle status: `baseline`, `promoted_to_holdout`, `final_selected`, `rejected`, `duplicate`, `invalid`, or `crashed`. Promotion for further evaluation is not final selection. A better selection objective is insufficient when a mandatory guardrail fails materially. Guardrail semantics come only from the declared contract (`metric`, `direction`, `max_degradation`, `role=guardrail`) and are metric-agnostic: when the contract declares no guardrails, `guardrail_status=not_applicable` is the valid honest value and no fake `pass` is forced; when guardrails are declared, `pass` requires baseline reference plus candidate metric evidence, a mechanically detectable violation can never be overridden by a manually supplied `pass`, and missing comparison evidence cannot silently become `pass`.
7. **LOG** — append every result, including rejected, crashed, and invalid experiments, to the canonical `run_dir/experiments.tsv`; update canonical `run_dir/run.yaml` at `results.experiment_summary`. Never write through a CWD-relative `.agent-system/runs/...` path.
8. Revert rejected experiment changes only within the isolated worktree, then continue from the best retained local revision.

If an experiment crashes because of an obvious implementation error introduced by that experiment—for example a typo, import error, or small configuration mistake—make up to two bounded repair attempts without changing the experiment hypothesis. Keep the repair attempts inside the same isolated experiment and record their outcome. If repair would require a different hypothesis, broader work, a new dependency, or crossing a capability gate, record the experiment as `crash`, revert its changes within the isolated worktree, and continue from the best retained revision.

Treat noise-level deltas as inconclusive. Use existing repeated seeds, paired evaluation, variance, confidence intervals, acceptance tolerance, or minimum meaningful delta when appropriate and affordable; do not invent unnecessary statistical machinery. When the primary metric depends on model-output weighting, normalization, or denominator behavior, normally include at least one conventional output-independent error/calibration/stability/fairness/resource secondary metric. Periodically try simplification because complexity is a cost.

## Capability and stopping gates

Stop before an action that requires unavailable or unrecorded authorization, including restricted data, expensive/full/distributed training, dependency changes, remote systems, or remote Git writes. Preserve completed evidence and report the exact gate; do not silently broaden scope.

Also stop when the budget or acceptance target is reached, evaluation becomes invalid or irreproducible, repeated crashes require non-small work, the next idea violates scope, the user interrupts, or further search would tune against the final holdout. By default, after at least six valid novel experiments, recommend stopping when the last four introduce neither a meaningful improvement nor materially new evidence, including repeated duplicate configs/predictions. `max experiments=N` is a ceiling, not a requirement to consume N. Do not generate meaningless permutations merely to consume the budget.

## Records and completion

Keep canonical `run_dir/run.yaml` authoritative. The current `results.experiment_summary` records the budget, valid novel experiment count, stopping reason, journal/evaluation references, structurally selected experiment, candidate learning events, and separate lifecycle dimensions. `selected_experiment` contains the `experiment_id` plus the journal `candidate_identity` — mandatory because it is the invariant that connects the selection to recorded evidence — along with whichever code/config/prediction identities meaningfully exist for the project; it must resolve to exactly one journal row. A research decision does not imply independent validation, branch integration, or production readiness. Normal and historical runs remain readable without the current format marker.

Finalize canonical `run_dir/learning.yaml` with `skill: autoresearch` and `mode: autoresearch`. Set execution from the run and user outcome independently from explicit acceptance, rejection, or rework evidence; otherwise use `unknown`. Emit zero to three actionable signals; when empty, record a concrete `no_reusable_signal_reason`. Finalization derives normalized candidate events such as `point_in_time_violation`, `holdout_reuse`, `metric_disagreement`, `duplicate_config`, `duplicate_predictions`, `missing_provenance`, `untracked_evidence`, `selected_experiment_mismatch`, and `guardrail_failure`, and it persists them durably even when validation fails and the run stays open (deterministically and deduplicated), because failed runs are precisely when reusable evidence matters most; this diagnostic persistence applies only while evidence is open — a record already marked `finalized` is never rewritten. `evaluation_repaired`, `repeated_fallback`, `user_rejection`, and `major_rework` have no reliable generic evidence source: they are recorded explicitly with `--candidate-event` and are never mechanically inferred. Curate only genuinely reusable events into durable signals.

Complete runs only through `python3 -B .agent-system/tooling/finalize-run.py <run-id> --project-root <canonical_project_root>`. It validates schemas, evaluation semantics, journal/selection identity, learning, artifacts/provenance, exposure state, guardrails, canonical evidence, Git state, and recorded target/repository checks — including for runs already marked `finalized`; a manually finalized run never bypasses validation, and finalization never creates an exposure record — it only verifies the reservation committed at evaluation time. When evidence is valid and already finalized it succeeds idempotently with zero writes: no duplicated exposure records, learning events, journal transitions, or byte changes; when valid and open it atomically transitions `evidence_status` to `finalized`. A finalized run is immutable to normal toolkit commands: `record-experiment.py` refuses to append, count, or reserve anything into it, and there is no reopen operation. Do not report completion when finalization fails or the isolated worktree contains the only copy.

Report:

- baseline, best result, and meaningful selection-objective delta;
- novel/duplicate/rejected/crashed/invalid experiment counts;
- stopping reason and guardrails;
- protected-evaluation execution discipline: state honestly whether the
  protected final evaluation ran inside `--run-protected-evaluation`
  (reservation mechanically precedes execution) or was invoked manually after
  `--reserve-final-exposure` (execution order then rests on agent discipline,
  which the journal cannot re-verify);
- useful retained changes;
- local autoresearch branch and selected revision;
- remaining uncertainty and recommended next step.
- `Run evidence: .agent-system/runs/<run-id>/`

State that branches and commits remain local. Hand a material improvement claim to `validate-dsml-result` for independent review, especially when target, split, metric, feature timing, or consequential decisions are involved.
