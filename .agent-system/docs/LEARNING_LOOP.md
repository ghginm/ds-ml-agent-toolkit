# Learning loop design

Each tracked run keeps two records:

- `run.yaml` is the detailed, authoritative evidence trail for that task. It references report or experiment sections instead of duplicating large domain outputs and keeps concrete metrics only when needed to justify a criterion, decision, or comparison.
- `learning.yaml` is the compact cross-project input: the run date, toolkit version, request classification, actual routing, execution/user outcome, and zero to three meaningful project- or kit-scoped signals. Signals point to a section of their sibling `run_ref` via `evidence_ref`; detailed evidence stays in `run.yaml`. A current record with zero signals includes `no_reusable_signal_reason` instead of inventing a lesson.

All relative `.agent-system/runs/...` references are relative to the canonical user project root, not the current execution directory or the toolkit location. Autoresearch may execute in an isolated worktree, but durable run evidence belongs to the canonical user project root from which the run was initiated. Never use the isolated worktree or toolkit installation as the sole evidence location. Capture that root before isolation, retain the concrete canonical `run_dir`, and use it for every later `run.yaml`, `learning.yaml`, and `experiments.tsv` write. Candidate caches and intermediate outputs may remain disposable, but any final artifact needed to understand or reproduce a selected result must be copied into the canonical run directory or referenced at a deliberately persistent location.

```text
ordinary meaningful request ──→ local/request-events.jsonl
tracked run ──→ run.yaml + learning.yaml
                         ↓
          thresholded deterministic review
                         ↓
             local/request-patterns.yaml
                         ↓
      semantic grouping + evidence drill-down
                         ↓
           candidate toolkit improvement
```

`learning.yaml` does not summarize the project or copy model metrics. Empty `signals` is normal, but lightweight request metadata is always recorded so recurring needs can be discovered across runs. Use `scope: project` only for a fact or defect in the analyzed project/domain. Use `scope: kit` only when the run exposes a reusable weakness, missing capability, routing issue, workflow inefficiency, validation gap, or output-quality problem in the agent/toolkit. One run may contain both scopes.

`outcome.execution` records whether the mechanics ran to completion; `outcome.user_outcome` independently records `accepted`, `rework_required`, `rejected`, or `unknown`. Technical completion must not imply acceptance. Add a few stable `reason_tags` only when they help aggregation.

At finalization, inspect the original request, selected and corrected route, acceptance criteria, execution and validation results, final artifact, explicit user feedback, later corrections, and meaningful detours available in the run evidence. Ask whether the run revealed a reusable toolkit limitation or quality gap. Emit only the smallest set of actionable signals that could plausibly influence a skill, shared instruction, schema, validator, tool, or template:

- keep project findings `scope: project`;
- use `scope: kit` only for cross-project relevance, meaningful rework, a systematic quality gap, a recurring pattern established across records, or a missing/misleading capability;
- require each new signal to state the learning, a proportionate `suggested_change`, and an `evidence_ref` into the sibling `run.yaml`;
- prefer zero to three strong signals; a warning, failed command, or project defect is not automatically a toolkit learning.

For autoresearch finalization, use `finalize-run.py` to cross-validate canonical `run.yaml`, `evaluation.yaml`, `learning.yaml`, and `experiments.tsv`; selected experiment identity; timing and exposure semantics; guardrails; provenance; and lifecycle state. Finalization runs the full validation even for evidence already marked finalized, then either fails or succeeds idempotently without duplicating append-only side effects. It generates normalized candidate reusable events from important scientific or operational failures and persists them durably while the run is still open even when finalization fails, so failed runs keep their diagnostic evidence — already-finalized records are never rewritten; events without reliable generic evidence (`evaluation_repaired`, `repeated_fallback`, `user_rejection`, `major_rework`) are recorded explicitly, never inferred. The agent still curates only zero to three genuinely reusable signals. Protected-population exposure is committed BEFORE the protected evaluation can be observed — `record-experiment.py --reserve-final-exposure` writes the stable-identity ledger event idempotently first, a stage-`final` result is refused without that reservation, a run records at most one evaluated stage-`final` experiment, and finalization only verifies the exposure record (it never creates one). Managed protected execution is one-shot at the wrapper boundary: `record-experiment.py --run-protected-evaluation ... -- COMMAND` commits a separate `kind: execution_consumed` event to the same append-only ledger AFTER the reservation and BEFORE the evaluator subprocess is spawned, so a managed execution attempt remains durably consumed even if the evaluator crashes, exits non-zero, fails the result handoff, or never records a row; a later managed invocation for the same run + protected population is rejected before launching. A crashed managed attempt leaves the run with no valid untouched final estimate for that population; the run must use a new untouched final population if another genuinely untouched estimate is required. The user-facing summary includes `Run evidence: .agent-system/runs/<run-id>/`.

`timestamp` and `toolkit_version` let later analysis group signals by release so a problem that stopped occurring after a toolkit release becomes visible.

When filling `kind`, `topics`, and `deliverable`, prefer stable, reusable, broad labels and reuse an existing label when one already captures the meaning semantically. Keep task-specific wording and details in `run.yaml` rather than inventing new classification fields. Semantically similar tasks should converge on the same label so cross-run aggregation stays useful.

In `routing`, `skill` and `mode` are the final route used. For an unchanged route, keep `initial_skill` and `initial_mode` as `null` and set `corrected: false`. When routing changes, set `corrected: true` and record whichever initial fields are relevant; one field may remain `null`. Do not store a full routing trace.

## Lightweight request events

`record-request.py` appends normalized metadata for meaningful ordinary requests
without creating a run. The ignored local event contains only timestamp, broad
request kind/topics/deliverable, final route, optional `run_ref`, outcome, rework,
routing-correction, and stable reason tags. The route is a normalized identifier
such as `technical-report` or `execute-dsml-task/diagnose`, never prompt text. It never stores full prompts, raw
project/customer data, secrets, terminal dumps, transcripts, or hidden reasoning.
Recording is best-effort auxiliary work and must not change the primary task result.

`review-requests.py` deterministically groups exact normalized request shapes. By
default recording triggers review after 10 new events or 30 days since the previous
review (measured against current UTC time, not event timestamps); only patterns with at least three events are emitted. The aggregate reports
frequency, first/last observation, trend, rework rate, routing corrections,
failures, and repeated reason tags. The agent may then semantically group closely
related patterns during an explicit review. Frequency alone yields monitoring;
friction or rework is the stronger improvement signal.

Both generated files live below `.agent-system/local/`, which is excluded by its
release-owned `.gitignore`. The deterministic aggregate is compact optional project
context, not evidence for automatic self-modification.

## Run record details

Under `run.yaml.execution.commands`, use `type: command` with the actual executable `command` when a meaningful reproducible command exists. For an ad-hoc step that is not practically reproducible, use `type: operation` with a concise `description` and `exit_code: null`. Omission of `type` remains compatible with older command records. Do not store every shell interaction or giant inline scripts; persist a script only when future reproduction has material value.

Use `results.decision: not_applicable` when an analysis or report has no accept/reject model or implementation decision. Reserve `not_verified` for a relevant verification that could not be completed or lacked sufficient evidence.

The maintenance workflow is:

```text
recurring request + friction/rework
          ↓
candidate improvement in the narrowest responsible layer
          ↓
explicit maintainer implementation
          ↓
regression/evaluation case
          ↓
human keep / reject decision
```

Review `request-patterns.yaml` first for recurrence and friction, then use
`learning.yaml` and referenced `run.yaml` records for evidence-backed drill-down.
A single event or run must not claim recurrence. Architecture changes remain
explicit, reviewable maintainer work validated with evals before human acceptance;
the toolkit does not fine-tune itself or automatically modify instructions, skills,
policy, tooling, or templates.