# Toolkit development contract

- Preserve a harness-neutral core. Product bindings belong only in `adapters/` or target-project context.
- Apply organization policy before repository, path, skill, task, or runtime instructions.
- Inspect consumers and neighboring conventions before editing; make the smallest coherent change.
- Never apply changes to protected policy or released skills automatically. Use an explicit maintenance workflow and human review.
- Preserve unrelated user work and avoid destructive Git operations.
- Do not add empty directories, placeholders, unused scripts, speculative abstractions, or duplicate instructions.
- Use only synthetic, non-sensitive eval data. Never store secrets, raw customer rows, or hidden reasoning traces.
- Run `python3 -B tooling/validate-kit.py` and `python3 -B -m unittest discover -s tests -v` after substantive changes; `-B` prevents validation itself from creating release-forbidden bytecode caches.
- Report only commands and checks actually run; distinguish verified facts, assumptions, and remaining uncertainty.
- Open a run record under `.agent-system/runs/<run-id>/` for **any major rework**
  in this repository, not only the predefined workflow contracts. Treat the
  following as a trigger — when in doubt, log it; false positives are cheap,
  lost rework signal is not:
  - explicit user request for an audit, review, or "fix the project";
  - a deep-audit verdict such as `REQUIRES_CHANGES` (or equivalent);
  - a multi-phase plan that touches core correctness — target leakage,
    evaluation/holdouts, model/artifact contracts, scheduling/freshness,
    inference, or repository hygiene;
  - ≥ 2 of those phase categories in a single session;
  - a dedicated feature branch was created for the change;
  - the user describes the work as "significant", "rework", "harden",
    "productionise", or "redesign".
  Decide first, log second: open the record as soon as the rework is
  recognised, before doing meaningful work.
- Each major-rework record is the sibling pair
  `.agent-system/runs/<run-id>/run.yaml` and
  `.agent-system/runs/<run-id>/learning.yaml`, conformant to the schemas
  documented in `.agent-system/SYSTEM.md` (see the `Run evidence and
  learning` section and `.agent-system/schemas/run.schema.json` /
  `learning.schema.json`). Reuse `tooling/create-run.py` to scaffold;
  populate `task.goal`, `task.acceptance`, `provenance.repository.*`,
  and `learning.request.*` before meaningful work, then update
  `results.*`, `outcome.execution`, and `outcome.user_outcome` at
  finalisation. `<run-id>` follows the pattern `YYYY-MM-DD_HHMMSS-<slug>`
  and is reused for both files and any sibling artefact referenced from
  them. The run record's `outcome.user_outcome` is set independently
  from explicit user feedback; the `outcome.execution` reflects the run
  result.
- Never copy secrets, connection strings, full SQL queries, or large
  payloads into run records. A failed run-record write is auxiliary and
  must not block, downgrade, or hide the primary result. Edit kit-owned
  files such as `.agent-system/SYSTEM.md` and `.agent-system/CONTROL.md`
  only through the kit's explicit maintenance workflow — do not change
  them from this project-local rule.