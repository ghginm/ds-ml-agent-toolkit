---
name: compose-dsml-report
description: Compose stable DS/ML technical reports from normalized analysis state; do not perform the primary repository investigation or deep audit.
license: MIT
metadata:
  author: "ghgin, Hermes Agent"
  version: "0.6.2"
---

# Compose DS/ML Report

Turn consolidated evidence and a reviewed report plan into an editable technical
report and, when requested, a visually verified PDF. The technical-report
workflow owns request controls, profiles, iteration count, orchestration, and
completion. `analyze-dsml-project` owns evidence discovery. This skill owns
information design, composition, rendering, inspection, and targeted repair.

## Required inputs

Read [references/analysis-state.md](references/analysis-state.md). Require ready
normalized analysis state and a compact reviewed plan describing purpose,
audience, explicit focus, target length, independent analytical depth, proposed
major sections, focus/evidence mappings, visuals, appendix material, and
duplication risks. Reject a plan that silently drops significant inspected
evidence for a requested focus. Use
[assets/report-template.md](assets/report-template.md) as an adaptive scaffold,
not a table of contents.

## Information design and composition

- Give substantial reports a compact executive summary and enough context to
  understand the findings.
- Preserve the technical-report workflow's stable Executive Overview / Part I
  understanding / Part II immediate focus / Part III Research & Improvement Map
  / next investigations / appendix architecture. Adapt or omit unsupported
  subsections; never preserve discovery order or manufacture empty content.
- Keep each finding's full explanation in one canonical location. Elsewhere,
  point to it or state only the action that depends on it.
- Distinguish fact/evidence, inference, limitation, and recommendation where the
  distinction changes interpretation. Connect recommendations directly to
  evidence; omit generic future work.
- Keep the main body decision-dense. Move exhaustive provenance, commands,
  hyperparameters, file lists, and ancillary diagnostics to an appendix when
  useful.
- Treat target length as a presentation budget, never an investigation budget.
  Compress with tables/charts, combine related points, and move secondary detail
  to the appendix before discarding decision-useful evidence.
- Treat a page range as an information budget, not a layout target. If pages are
  underfilled, first recover supported mechanism, evidence interpretation,
  failure modes, interactions, and unresolved uncertainty. Never reach a page
  count through whitespace, decorative breaks, oversized tables, or one light
  section per page. A shorter evidence-complete report is better than filler.
- A requested focus needs explanation plus interpretation. Use model comparison,
  feature evidence, stability/cohort/bias diagnostics, routing/runtime/tuning
  behavior, or validity limits when the normalized state supports them.
- A major requested focus is not adequately covered when the reader knows what
  exists but cannot explain why it exists, when it should work, what could
  invalidate it, and how much project evidence supports it. An inventory table
  alone never satisfies this invariant.
- For material components, select the reasoning that matters from role,
  mechanism, applicability conditions, assumptions, failure modes,
  interactions/redundancy, empirical support, unknowns, and implication. Do not
  print a fixed template or force every component through every dimension.
- Keep verified project facts, technical rationale, and project-specific
  empirical support distinguishable in wording. A plausible design with no
  ablation or diagnostic remains plausible but unvalidated.
- Prefer compact analytical bullets with meaningful lead-ins and real reasoning
  steps. A useful section often uses a framing sentence, compact table,
  analytical bullets, and a short implication; vary the structure when another
  form scans better. Usually four to seven substantive bullets are easier to
  inspect than several dense paragraphs.
- For major risks and design conclusions, make mechanism → evidence →
  implication explicit, without requiring those words as headings.
- Keep supported low-hanging fruit in Part II and a compact, grouped Research &
  Improvement Map in Part III unless the report is explicitly descriptive.
- Use tables to compress repeated structure, diagrams for flows/relationships,
  and charts only for real quantitative questions. Avoid repetitive field-label
  cards when prose or a table is clearer.

Markdown or another chosen authoring source remains the semantic source of
truth. Include `<!-- dsml-report-state-revision: ... -->` and
`<!-- dsml-report-plan-revision: ... -->`; never substitute "see PDF."

## Review and targeted revision

Critique architecture separately from technical content. Iteration 2 must be a
content-depth review across every requested focus and must make a substantive
revision; formatting and visual QA do not consume it. Name specific defects,
affected sections, and intended repairs. Patch only affected material when the
architecture is sound; restructure when it is not. After late evidence, update
state and plan first, then recompose impacted sections. Do not append a
chronological catch-all.

For every requested focus in iteration 2, explicitly inspect descriptive-only
coverage, inventory without interpretation, missing mechanism or assumptions,
missing applicability or failure conditions, omitted interactions, absent
empirical-support status, theoretical claims phrased as project facts, omitted
state reasoning, evidence listed without interpretation, and conclusions whose
implication is left to the reader. Depth is semantic: tables, evidence IDs,
word count, or many implementation facts do not make a section deep.

Validate the source and review evidence:

    python3 -B .agents/skills/compose-dsml-report/scripts/validate_dsml_report.py \
      --state analysis-state.json --plan report-plan.json --report report.md \
      --review-log report-review.json

`--review-log` is required when the plan requests more than one iteration.
Resolve validation errors before rendering. The validator's shallow-coverage
and source-consistency warnings are iteration-2 triggers: revise them or record
a specific evidence-based acceptance reason.

## PDF rendering and visual inspection

For text-heavy technical reports, use the existing Markdown/CSS route when its
renderer is verified; choose DOCX or another supported pipeline only when it is
simpler and more stable for the report. Do not install dependencies silently.
Preserve one editable source in every route.

After rendering, run `qa_dsml_report_pdf.py prepare`, pass `--source-markdown`
for the persisted semantic source, and pass `--target-min-pages` /
`--target-max-pages` when the user supplied a range.
Inspect its page images,
and record review defects with `record`. Fix source/layout, rerender into a fresh
QA directory, and use `verify` to confirm each prior defect is resolved or
explicitly accepted. Review page balance, whitespace, stranded headings/blocks,
tables and wrapping, chart size, captions, hierarchy, density, clipping, and
zoom requirements, and useful information density. A report within the page
range can still fail as underfilled when multiple pages are sparse. Geometry
checks are preflight only; opening pages is not a quality result.

## Completion

Complete only when source validation passes, requested revision cycles have
actionable evidence, no material semantic/visual defect remains unaddressed,
final consistency checks numbers/headings/cross-references, and the latest PDF
page images were visually reviewed. Deliver primarily the final PDF and, when
useful or requested, its semantic source. Keep internal plans, critique logs,
normalized state, contact sheets, and temporary renders out of normal delivery.
