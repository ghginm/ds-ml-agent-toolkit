---
name: autoresearch
description: Run bounded autonomous repeated experiments against a measurable objective; use for explicit autoresearch requests or clear multi-candidate optimization, not ordinary one-shot model development.
license: MIT
compatibility: Requires local Git, terminal command execution, and a reproducible experiment evaluation command.
metadata:
  author: "Luis Cantero (upstream), adapted by ghgin and Hermes Agent"
  version: "0.6.2"
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

Before any candidate mutation, inspect the request and authoritative repository evidence. Infer what is already clear instead of asking the user to restate it, then present a compact **Autoresearch preflight** containing:

- goal;
- primary metric, direction, exact evaluation command or pipeline, and metric extraction/evaluation method;
- editable scope and protected/out-of-scope files, data, evaluation code, and unrelated application areas;
- constraints, test and metric guardrails, and acceptance threshold or meaningful delta;
- experiment budget;
- simplicity policy: prefer simpler solutions unless added complexity is justified by a meaningful improvement.

For DS/ML work, also freeze relevant dataset/population, target, train/development/final-holdout split, time window, feature timing, and compute/resource constraints. Keep the visible preflight compact and omit irrelevant DS/ML fields, but retain them in the evaluation contract when they matter.

Ask only for missing or materially ambiguous fields after showing the inferred values. In particular, ask when multiple primary metrics are plausible, no reproducible evaluation exists, mutation scope cannot be bounded safely, or a capability gate is unresolved. Do not choose what “better” means from a vague objective. Do not turn setup into a field-by-field questionnaire when repository evidence answers the questions.

Respect an explicit experiment count. Otherwise propose and show a conservative finite budget—normally 10 cheap local experiments—so the user can change it. Unlimited operation requires an explicit request and still cannot cross capability or compute gates.

Ask the user to confirm or correct the complete preflight before establishing the baseline or making candidate changes. Normal responses such as “yes,” “go ahead,” or corrections to one field are sufficient; ritual wording is not required. A request may skip the extra confirmation round only when it already supplies a sufficiently complete contract, explicitly authorizes immediate execution without another question, and leaves no safety or capability ambiguity. Even then, record or briefly show the reconstructed preflight before proceeding. A bare `Run autoresearch` is never pre-authorization.

## Establish safe local Git isolation

Before the baseline:

1. Verify the project is a Git repository and record the starting revision.
2. Inspect the working tree. A dirty active worktree does not block autoresearch when safe isolation is available. Never discard, reset, stash, clean, include, or commit pre-existing user changes.
3. Prefer a separate local Git worktree on a dedicated `autoresearch/<run-id>` branch rooted at the recorded revision. Keep the user's active worktree exactly untouched and exclude its uncommitted changes from every experiment.
4. Confirm experiment edits and rollback are confined to that isolated worktree. Proceed there even when the active worktree is dirty; if safe isolation cannot be established, stop before experimentation.
5. Do not initialize Git unless repository-level mutation is already authorized.

Task-authorized local branch/worktree creation, local experiment commits, checkout, and rollback inside the isolated workspace are local versioning operations. They do not authorize remote effects. Never push, create a remote branch or repository, open a pull request, or change remote configuration unless that exact remote action is separately authorized. A configured remote is not permission to use it.

Destructive rollback is permitted only against experiment commits created in the dedicated isolated worktree. Never run destructive reset where it can affect pre-existing or unrelated work.

## Create run evidence and freeze evaluation

Use `.agent-system/tooling/create-run.py` to initialize `.agent-system/runs/<run-id>/run.yaml` and `learning.yaml`. An autoresearch run may add `.agent-system/runs/<run-id>/experiments.tsv` with compact columns:

```text
experiment	revision	primary_metric	guardrails	status	description
```

An ephemeral local `run.log` may retain bounded diagnostic output. Do not persist secrets, raw customer rows, complete sensitive terminal output, or hidden reasoning.

Only after the preflight is accepted or validly pre-authorized, create the isolated workspace and run evidence. Before candidate edits, reproduce and record the baseline. If it cannot be reproduced, stop as blocked or unresolved. Freeze the candidate-comparison contract:

- dataset/population, target, split, time window, and feature timing;
- metric implementation and direction;
- baseline and candidate commands;
- primary objective, guardrails, and meaningful-delta threshold;
- development evaluation versus protected final holdout;
- resource limits and acceptance conditions.

Iterate on the approved development/validation evaluation. Never turn a final holdout into the repeated fitness function. Baseline and candidates must remain like-for-like; reject gains caused by leakage, changed rows/splits/preprocessing/metric code, target availability, or inference assumptions.

## Autonomous experiment loop

After the baseline, continue without asking “should I continue?” until a stopping condition applies.

For each experiment:

1. **THINK** — form one focused, falsifiable hypothesis using previous results. Prefer low-cost/high-information and simple changes; diversify after a plateau and combine winners only when attribution remains understandable. Only after incremental and low-cost directions are exhausted, consider larger or more architectural hypotheses when they remain within the confirmed scope, budget, capability policy, and frozen evaluation contract. Do not use this as justification for unnecessary large rewrites.
2. **EDIT** — make one focused in-scope change. Avoid unrelated churn.
3. **RECORD LOCAL REVISION** — create a local experiment commit for evidence and rollback in the isolated branch.
4. **RUN** — execute the frozen evaluation and relevant guardrails. Keep verbose output out of context while retaining enough bounded diagnostics for failures.
5. **MEASURE** — extract the primary metric, guardrail results, execution status, and contracted resource measures.
6. **DECIDE** — assign `keep`, `discard`, `crash`, or `invalid`. Keep only evidence-supported improvements under the frozen contract. A better primary metric is insufficient when a guardrail fails.
7. **LOG** — append every result, including rejected, crashed, and invalid experiments, to `experiments.tsv`; update `run.yaml` at `results.experiment_summary`.
8. Revert rejected experiment changes only within the isolated worktree, then continue from the best retained local revision.

If an experiment crashes because of an obvious implementation error introduced by that experiment—for example a typo, import error, or small configuration mistake—make up to two bounded repair attempts without changing the experiment hypothesis. Keep the repair attempts inside the same isolated experiment and record their outcome. If repair would require a different hypothesis, broader work, a new dependency, or crossing a capability gate, record the experiment as `crash`, revert its changes within the isolated worktree, and continue from the best retained revision.

Treat noise-level deltas as inconclusive. Use existing repeated seeds, paired evaluation, variance, confidence intervals, acceptance tolerance, or minimum meaningful delta when appropriate and affordable; do not invent unnecessary statistical machinery. Periodically try simplification because complexity is a cost.

## Capability and stopping gates

Stop before an action that requires unavailable or unrecorded authorization, including restricted data, expensive/full/distributed training, dependency changes, remote systems, or remote Git writes. Preserve completed evidence and report the exact gate; do not silently broaden scope.

Also stop when the budget or acceptance target is reached, a plateau remains after a strategy change, evaluation becomes invalid or irreproducible, repeated crashes require non-small work, the next idea violates scope, the user interrupts, or further search would tune against the final holdout. Do not generate meaningless permutations merely to consume the budget.

## Records and completion

Keep `run.yaml` authoritative. Record the goal, routing, frozen evaluation contract, baseline, final decision, commands actually run, and evidence references in their existing fields. For an autoresearch run, add the optional `results.experiment_summary` object with `budget`, `experiments_run`, `kept`, `discarded`, `crashed`, `invalid`, `stopping_reason`, `selected_revision`, and `journal_ref`. The selected revision identifies the retained candidate; use `null` when none is retained. Keep detailed per-experiment rows in `experiments.tsv` and verbose output in the compact journal or ephemeral log rather than duplicating them in `run.yaml`. Normal runs omit `results.experiment_summary`.

Finalize `learning.yaml` with `skill: autoresearch` and `mode: autoresearch`. Set execution from the run and user outcome independently from explicit acceptance, rejection, or rework evidence; otherwise use `unknown`. Inspect the request, route, acceptance criteria, validation, selected result, feedback, rework, and material detours. Keep project/domain findings `scope: project`; add `scope: kit` only for a reusable toolkit weakness, meaningful rework, systematic quality gap, recurring pattern supported across records, or missing/misleading capability. Emit zero to three actionable signals with `suggested_change` and sibling-run `evidence_ref`; do not copy experiment metrics, infer recurrence from one run, or automatically modify released toolkit content.

Report:

- baseline, best result, and meaningful primary-metric delta;
- experiments run and kept/discarded/crashed/invalid counts;
- stopping reason and guardrails;
- useful retained changes;
- local autoresearch branch and selected revision;
- remaining uncertainty and recommended next step.

State that branches and commits remain local. Hand a material improvement claim to `validate-dsml-result` for independent review, especially when target, split, metric, feature timing, or consequential decisions are involved.
