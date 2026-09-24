# Orientation mode

Use this mode for fast onboarding, a bounded project question, or a living project-map refresh.

## Kit onboarding pass

Treat “Set up the DS/ML Agent Kit” or “Onboard this repository for the DS/ML
Agent Kit” as a full setup request. Treat “Recheck DS/ML Agent Kit setup” or the
older “Recheck DS/ML Agent Kit onboarding” as a cheap state-verification request.

For first onboarding:

1. Confirm the requested repository root contains the already-copied `.agent-system/manifest.json` and `.agents/skills/`. If it does not, stop without sourcing or copying toolkit files from another repository.
2. Inspect policy, repository instructions, `.agent-system/` runtime files, manifests, CI, tests, source paths, existing maps, and project docs before asking questions.
3. Use `.agent-system/project.template.yaml` to create a missing `.agent-system/project.yaml`; preserve explicit existing values and fill only evidence-backed unknowns.
4. Determine the effective capability state. A missing active override means the shipped conservative template remains effective; never infer authorization from installed technology or credentials.
5. Inspect harness instruction targets before writing. Create a missing target only when the merge is safe; preserve an existing target and report one explicit manual merge when it is not.
6. Create or reuse the project map when it adds navigation value. Do not duplicate an authoritative map or rewrite a current one during recheck.
7. Run `python3 -B .agent-system/tooling/validate-kit.py --installed-project .`, record the exact result, and create `.agent-system/onboarding-status.md`.
8. Return one answer-first verdict: `READY`, `READY_WITH_WARNINGS`, or `ACTION_REQUIRED`; collect every human requirement under `Manual action required`.

The shipped helper `python3 -B <repository-root>/.agent-system/tooling/onboard-project.py --installed-project <repository-root> --harness <harness>` performs conservative structured inference, merge-safe instruction handling, validation, and status generation. Review its inferred cache against authoritative evidence. Use `--recheck` after a manual fix and `--activation-verified` only when required harness activation was actually observed.

If execution is unavailable, write `Validation: NOT RUN`, a specific reason, and the exact manual command. Unknown optional systems may remain `null` and do not alone require `ACTION_REQUIRED`.

## Evidence pass

1. Read active policy and repository/path instructions.
2. Prefer authoritative entry points over broad file reading: manifests, configuration, orchestration definitions, CLI modules, notebooks named by current docs, tests, and evaluation code.
3. Follow symbols and configuration values to their definitions and consumers.
4. Build a compact evidence table while tracing:

| Claim | Status | Evidence | Freshness or gap |
| --- | --- | --- | --- |
| One material project-specific statement | `Verified`, `Inferred`, or `Unknown` | Repository path, configuration key, command result, or artifact reference | Revision/date or missing check |

5. Stop exploring a branch when it cannot change the central answer, risk register, or next action.

## Data-to-decision trace

Resolve, where relevant:

- source identities, grain, keys, time semantics, and bounded transformations;
- target definition, label timing, unit of observation, and prediction horizon;
- feature construction and point-in-time availability;
- split logic, baseline, metric implementation, and threshold selection;
- training and inference entry points plus produced artifact versions;
- consumer of the score/prediction/alert and operational constraints;
- external `distributed_compute`, `experiment_tracker`, `scheduler`, `model_registry`, and `git_provider` bindings as discovered facts, not core assumptions.

## Project map decision

Create or refresh `PROJECT_MAP.md` only for real onboarding/navigation work. Start from `.agent-system/templates/PROJECT_MAP.template.md`. If an equivalent current document exists, improve or link it rather than creating a competitor.

The map is answer-first and compact. Link to authoritative definitions instead of copying code, schema, or long operational instructions. Record the repository revision and date of evidence. Separate current behavior from proposals.

## Completion check

The result must answer the user's central question, show the critical flow and entry points, identify the highest-value unknowns, and cite enough repository evidence for another practitioner to verify the claims.