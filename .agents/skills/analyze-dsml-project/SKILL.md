---
name: analyze-dsml-project
description: Inspect an existing DS/ML/AML project for onboarding, data-to-decision tracing, technical reporting, or explicit audit; use for analysis, not implementation or independent validation.
license: MIT
metadata:
  author: "ghgin, Hermes Agent"
  version: "0.8.0"
---

# Analyze DS/ML Project

Inspect an existing project to answer a bounded question, build a navigable system map, or produce an evidence-backed technical report or audit. Do not implement product fixes or independently certify the result.

## When to use

Use for onboarding—including “Onboard this repository for the DS/ML Agent Kit” and “Recheck DS/ML Agent Kit onboarding”—project explanation, data-to-decision tracing, handover, `PROJECT_MAP.md` creation or refresh, a technical project report, an explicitly requested deep audit, and a bounded review of DS/ML Agent Kit learning signals.

Do not use as the primary workflow for a concrete regression, implementation, candidate experiment, independent validation, generic ML explanation, or trivial lookup. For “understand and fix,” establish only the context needed, then hand off to `execute-dsml-task`.

## Minimum input and mode

An accessible repository and a natural-language objective are normally enough. Read `.agent-system/project.yaml` when present, but infer authoritative facts from repository evidence and leave unknown values unknown rather than requiring the user to complete a form. Ask only when the repository or subsystem is unresolved, multi-repository scope changes the result, restricted evidence is essential, or deliverable depth cannot reasonably be inferred.

Read this routing contract before selecting or announcing an analysis mode, then choose the least expensive sufficient mode:

- **orientation** — onboarding or a bounded repository investigation or explanation when no formal research deliverable is requested; read [references/orientation.md](references/orientation.md).
- **technical-report** — a formal explanation or report whose primary purpose is to document the problem, data, target, modelling, evaluation, results, experiments, limitations, and next work; read [references/technical-report.md](references/technical-report.md).
- **deep-audit** — an explicit audit, correctness or leakage investigation, production-readiness assessment, failure/risk review, reliability/governance assessment, or request to determine whether the system can be trusted; read [references/deep-audit.md](references/deep-audit.md).

Choose the mode from the user's analytical intent, not the presentation format. Markdown and PDF are output formats and never select `deep-audit` by themselves. A generic request to create a detailed technical report or PDF selects `technical-report`; an explicit audit request selects `deep-audit` even when its output is also a PDF. Do not announce a mode until this contract has been loaded.

Use light rigor for ordinary work; it does not require a run record. Create
schema-conforming `run.yaml` and `learning.yaml` siblings for a formal report,
audit, or other explicitly tracked/controlled work, and record approvals and
provenance when they matter.

## Repository onboarding

For “Set up the DS/ML Agent Kit” or “Onboard this repository for the DS/ML
Agent Kit,” use orientation mode and complete all safe inference before asking a
question:

1. Resolve and confirm the requested repository root before any write. Require its existing `.agent-system/manifest.json` and `.agents/skills/`; if the overlay is absent or the resolved root differs from the requested project, stop without copying toolkit files and report `ACTION_REQUIRED`.
2. Read higher-level policy, repository/path instructions, installed runtime files, existing project configuration/maps, and authoritative manifests, CI, tests, source, and docs.
3. Identify the active harness. Inspect existing instruction files before changing them; never overwrite or guess a merge into an existing file.
4. Run `python3 -B <repository-root>/.agent-system/tooling/onboard-project.py --installed-project <repository-root> --harness <codex|copilot|hermes|unknown>`. Add `--activation-verified` only when required harness activation or Hermes project-skill trust was actually observed.
5. Review the generated `.agent-system/project.yaml` against repository evidence. Preserve explicit project values, fill only supported unknowns, and never convert technical availability into authorization.
6. Create or refresh `PROJECT_MAP.md` when useful for real onboarding, or point to the equivalent authoritative map. Preserve a current existing map.
7. Ensure installed-project validation actually ran. If Python execution is unavailable, record `NOT RUN`, the reason, and the exact manual command; never report `PASS`.
8. Refresh `.agent-system/onboarding-status.md` with exactly one verdict: `READY`, `READY_WITH_WARNINGS`, or `ACTION_REQUIRED`. Put every required human step in its single manual-action section.
9. Return the same compact status in chat; do not narrate the repository inventory.

For “Recheck DS/ML Agent Kit onboarding,” rerun the helper with `--recheck`, reassess only current configuration/runtime/instruction/activation state, and refresh the status. Do not regenerate a sound project map or replace deliberate project values without material evidence.

For an explicit runtime-integrity repair, run the helper from a trusted clean overlay with the same toolkit version and pass `--repair-runtime <clean-overlay> --recheck`. Restore only manifest-owned files; never use repair to overwrite project configuration, runs, maps, instruction merges, or project-specific skills.

If the helper is unavailable, perform the same steps directly from the shipped templates and run `python3 -B .agent-system/tooling/validate-kit.py --installed-project .`. Optional `null` values do not block safe work; ask only about a material security, cost, data, or recurring-authorization boundary that repository evidence cannot resolve.

## Learning-signal review

For “Review this project's DS/ML Agent Kit learning signals,” use orientation mode. Read `.agent-system/runs/*/learning.yaml` as the primary input. Use request metadata to identify repeated needs, cluster concise signals, and open a referenced `run.yaml` only when a signal needs drill-down evidence or context. Report only important themes; do not produce a broad project analytics report.

Do not infer recurrence from a single record or copy detailed project metrics into the review. Recommend the narrowest responsible layer: project-local instructions or map/config for project facts and workflows; an existing skill reference for detailed reusable procedures; `SKILL.md` only for routing/core invariants; shared instructions for universal behavior; an adapter, capability policy, or tooling layer when it owns the issue; a new skill only for a genuinely distinct workflow. Never apply maintenance changes to released toolkit content automatically.

## Workflow

1. Fix the central question and evidence standard before broad exploration.
2. Read organization/repository/path instructions, optional project configuration, existing maps, architecture docs, and approved commands. Higher-level policy wins over project configuration.
3. Locate the smallest set of source, SQL, notebook, feature, training, evaluation, inference, test, and orchestration entry points needed for the question.
4. Trace the critical path: source → transformations → features → target → split → model → evaluation → artifact → operational decision.
5. Verify material claims against code, query text, configuration, tests, artifacts, or permitted execution. For technical-report mode, consolidate normalized state and pass its synthesis gate before loading compose-dsml-report.
6. Label material statements `Verified`, `Inferred`, `Unknown`, or `Recommendation`; never turn an inference into a fact through confident prose.
7. Surface contradictions, high-impact risks, missing evidence, freshness, and the next discriminating checks.
8. Produce the requested answer or artifact without inventorying the repository indiscriminately.

## Outputs and handoff

- Bounded question: answer-first response with repository evidence pointers.
- Orientation: concise answer and, only when useful, a project map based on `.agent-system/templates/PROJECT_MAP.template.md`; kit onboarding additionally produces `.agent-system/onboarding-status.md`.
- Technical report: consolidate normalized analysis state, then load compose-dsml-report; its validator gates rendering and its Markdown remains the source of truth.
- Deep audit: source Markdown with strong correctness, risk, traceability, and remediation emphasis; derive a PDF only when a verified renderer is available.
- Large source sets may justify an evidence index; small reports should use inline evidence pointers.

If a defect needs implementation, hand off the verified mechanism and affected scope to `execute-dsml-task`. If a report will support a material decision, hand off the original request and raw evidence to `validate-dsml-result`.

At tracked-run finalization, set `outcome.execution` from the run result and set `outcome.user_outcome` independently from explicit acceptance, rejection, or rework evidence; otherwise use `unknown`. Inspect the request, route and corrections, acceptance criteria, validation, final result, user feedback, rework, and material detours. Keep project/domain findings `scope: project`. Add `scope: kit` only for a reusable toolkit weakness, meaningful rework, systematic quality gap, recurring pattern supported across records, or missing/misleading capability. Emit zero to three strong signals, each with a proportionate `suggested_change` and sibling-run `evidence_ref`; empty `signals` is normal. Never copy task evidence into `learning.yaml`, infer recurrence from one run, or rewrite released toolkit content from runtime evidence.

## Stopping conditions

Stop successfully when the central question is supported, the critical flow is traced as far as available evidence permits, material claims are classified, and unknowns are explicit. Stop with a bounded result when further work requires forbidden or unavailable access; provide the exact authorized next check. Do not modify product code.

## Pitfalls

- Existing project maps may be stale; record repository revision and evidence freshness.
- A data-flow diagram is not evidence unless its nodes and edges point to sources.
- Generic DS/ML or AML knowledge is context, not proof about this project.
- Do not create a PDF, project map, run record, or evidence index merely because a template exists.

## Verification

A successful orientation lets an experienced practitioner find the important entry points and explain the critical flow. A successful technical report lets a DS/ML reader understand the model and its evidence without reading the source code. A successful deep audit lets an independent reviewer determine which assumptions make the result valid, where it may fail, and how to reproduce and remediate material findings.
