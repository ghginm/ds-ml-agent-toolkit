# Learning loop design

Each tracked run keeps two records:

- `run.yaml` is the detailed, authoritative evidence trail for that task. It references report or experiment sections instead of duplicating large domain outputs and keeps concrete metrics only when needed to justify a criterion, decision, or comparison.
- `learning.yaml` is the compact cross-project input: the run date, toolkit version, request classification, actual routing, execution/user outcome, and zero to three meaningful project- or kit-scoped signals. Signals point to a section of their sibling `run_ref` via `evidence_ref`; detailed evidence stays in `run.yaml`.

```text
normal run
   ↓
run.yaml (detailed evidence)
   ↓
small learning.yaml (request, routing, sparse signals)
   ↓
periodic cross-run review
   ↓
potential toolkit improvement
```

`learning.yaml` does not summarize the project or copy model metrics. Empty `signals` is normal, but lightweight request metadata is always recorded so recurring needs can be discovered across runs. Use `scope: project` only for a fact or defect in the analyzed project/domain. Use `scope: kit` only when the run exposes a reusable weakness, missing capability, routing issue, workflow inefficiency, validation gap, or output-quality problem in the agent/toolkit. One run may contain both scopes.

`outcome.execution` records whether the mechanics ran to completion; `outcome.user_outcome` independently records `accepted`, `rework_required`, `rejected`, or `unknown`. Technical completion must not imply acceptance. Add a few stable `reason_tags` only when they help aggregation.

At finalization, inspect the original request, selected and corrected route, acceptance criteria, execution and validation results, final artifact, explicit user feedback, later corrections, and meaningful detours available in the run evidence. Ask whether the run revealed a reusable toolkit limitation or quality gap. Emit only the smallest set of actionable signals that could plausibly influence a skill, shared instruction, schema, validator, tool, or template:

- keep project findings `scope: project`;
- use `scope: kit` only for cross-project relevance, meaningful rework, a systematic quality gap, a recurring pattern established across records, or a missing/misleading capability;
- require each new signal to state the learning, a proportionate `suggested_change`, and an `evidence_ref` into the sibling `run.yaml`;
- prefer zero to three strong signals; a warning, failed command, or project defect is not automatically a toolkit learning.

`timestamp` and `toolkit_version` let later analysis group signals by release so a problem that stopped occurring after a toolkit release becomes visible.

When filling `kind`, `topics`, and `deliverable`, prefer stable, reusable, broad labels and reuse an existing label when one already captures the meaning semantically. Keep task-specific wording and details in `run.yaml` rather than inventing new classification fields. Semantically similar tasks should converge on the same label so cross-run aggregation stays useful.

In `routing`, `skill` and `mode` are the final route used. For an unchanged route, keep `initial_skill` and `initial_mode` as `null` and set `corrected: false`. When routing changes, set `corrected: true` and record whichever initial fields are relevant; one field may remain `null`. Do not store a full routing trace.

## Run record details

Under `run.yaml.execution.commands`, use `type: command` with the actual executable `command` when a meaningful reproducible command exists. For an ad-hoc step that is not practically reproducible, use `type: operation` with a concise `description` and `exit_code: null`. Omission of `type` remains compatible with older command records. Do not store every shell interaction or giant inline scripts; persist a script only when future reproduction has material value.

Use `results.decision: not_applicable` when an analysis or report has no accept/reject model or implementation decision. Reserve `not_verified` for a relevant verification that could not be completed or lacked sufficient evidence.

The intended future workflow is:

```text
project A learning.yaml
project B learning.yaml
project C learning.yaml
          ↓
   learning collection
          ↓
  clustering/deduplication
          ↓
  candidate improvements
          ↓
AGENTS / SKILL.md / tooling / templates
          ↓
         evals
          ↓
    accept / reject
```

The future analyzer should use `learning.yaml` as its primary input and read a referenced `run.yaml` only when a signal needs drill-down evidence or context. A single run must not claim that a request is recurring; recurrence comes from later aggregation of request metadata. Architecture changes must be supported by one or more concrete learning records, assigned to the narrowest responsible project or kit layer, and validated with evals before human acceptance. This design does not implement collection, clustering, an improvement agent, or automatic modification of instructions, skills, tooling, or templates.