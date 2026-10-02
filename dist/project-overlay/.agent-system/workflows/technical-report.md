# Technical report workflow

At a glance: iteration 1 investigates the project, builds normalized evidence,
plans, and writes V1. Iteration 2 reads V1 plus that persisted state, scans for
only material depth gaps, and patches affected sections; it reopens project
evidence only for a specific unresolved question. Then validators run, PDF
rendering occurs, and visual/layout QA is handled separately.

## Trigger and controls

Use for an explicit technical report or technical PDF report. A request for an
audit remains an audit even when its output is PDF. Natural-language controls
are accepted; no exact syntax is required.

| Control | Default |
| --- | --- |
| `profile=quick/standard/publication` | `standard` |
| `iterations=N` | Profile default: quick 1, standard 2, publication 3 |
| `focus=...` | The purpose and evidence named in the request |
| `target length=...` | Fit the evidence; do not pad |
| `analytical depth=...` | Substantial for broad multi-focus reports; independent of page length |
| `audience=...` | Experienced DS/ML practitioners unless context says otherwise |
| `detail=compact/normal/deep` | Profile default: quick compact, standard normal, publication deep |

Explicit controls override profile defaults. Target length is a presentation
budget controlling compression, layout, section allocation, appendix use, and
chart/table density. It never authorizes inspecting fewer artifacts or omitting
material diagnostics. `iterations=1` is one-shot: one planned composition
followed by required preflight/final checks. Version 2 is always a content-depth
review; visual QA occurs after content iterations and does not consume one. For
`N > 2`, later cycles improve synthesis, clarity, redundancy, information
density, and section balance. Do not regenerate the whole report blindly.

Profile depth differs deliberately. Quick may remain a high-level overview.
Standard normally explains the mechanism, applicability conditions,
assumptions, failure modes, empirical-support status, and implications for the
requested technical focus without needing a separate request for theory.
Publication may add alternatives, deeper theory, uncertainty, sensitivity, and
methodological discussion. None of these profiles may present technical
plausibility as project-specific empirical support.

## Contract

1. Interpret purpose, audience, focus, length, analytical depth, detail, format,
   profile, and iteration count. Use `analyze-dsml-project` in technical-report
   mode to gather evidence and consolidate normalized analysis state.
2. Before long-form prose, pass the normalized state's focus-coverage gate.
   Every explicit focus must be sufficient or genuinely unavailable. Weak
   coverage caused by an uninspected relevant artifact returns to analysis.
3. Create a compact report plan containing proposed major sections,
   evidence/visuals, appendix material, duplication risks, `analytical_depth`,
   and a focus-to-section/evidence/question/claim mapping. Map every significant
   inspected artifact relevant to a requested focus. Review the plan against the
   request and set its status to `reviewed`.
4. Use `compose-dsml-report` to compose an editable semantic source. The plan,
   not discovery order or internal registers, controls the table of contents.
5. Iteration 2 is a surgical depth-revision pass, not a second analysis and not
   a second composition. Start from V1, normalized state, the reviewed plan,
   prior validator/review results, and already extracted evidence. Run a compact
   semantic depth-gap scan across every requested focus, record only material
   gaps, select the high-value repairs, and patch only their affected sections.
   A substantive review is mandatory; rewriting is not. `revision_scope: none`
   is valid when the gap list is empty and a concise `pass_reason` explains why.
6. Check mechanism, empirical-support status, evidence interpretation, and
   implication wherever analytical claims exist. Check assumptions,
   applicability, failure modes, interactions, claim-type separation, and
   omitted-state reasoning only when relevant. Use descriptive-only and
   inventory-without-interpretation as defect detectors, not mandatory fields.
7. Do not repeat broad repository discovery, data-flow tracing, spreadsheet
   inspection, artifact enumeration, metric extraction, or source analysis in
   iteration 2. If a specific material gap cannot be resolved from normalized
   state, state the exact missing question, inspect the narrowest relevant
   source, update state when needed, and patch only the affected section.
8. Preserve sections that pass. Do not regenerate tables or figures, rewrite
   for stylistic variation, or restructure merely because a cleaner layout
   exists. `revision_scope: restructure` is exceptional and requires the
   information architecture itself to prevent adequate coverage.
9. Record actionable defects, affected sections/pages, resolution, and
   verification. For later versions, critique architecture, technical content,
   synthesis/clarity, redundancy, and section balance.
10. Run structural/semantic validation. For PDF, render to page images, run
   automated preflight, visually inspect every page, repair defects, rerender,
   and verify repairs. Pass the persisted Markdown source and requested page
   bounds to PDF QA. A source/PDF semantic mismatch blocks completion. Multiple
   sparse or low-information pages while total count is in range mean the report is underfilled: integrate
   useful evidence or diagnostics, improve tables/charts, merge weak sections,
   or reduce whitespace—never add filler. Automated geometry is not visual
   approval.

## Stable information architecture

Preserve the established skeleton unless the request is explicitly purely
descriptive or evidence makes a subsection irrelevant:

1. Executive Overview.
2. Part I — Understand the Project: system/scope/architecture, data and target,
   features, models, and evaluation/observed evidence.
3. Part II — Immediate Focus: blockers, important issues, and supported
   low-hanging fruit.
4. Part III — Research & Improvement Map.
5. Suggested Next Investigations.
6. Appendix.

The compact Research & Improvement Map groups only supported opportunities
(for example Metrics & Evaluation, Features & Data, Models & Architecture,
Efficiency, Robustness/Operations) and retains why, evidence, next step,
decision enabled, dependency, type, effort, and confidence. Omit it only for an
explicitly descriptive report or when no useful future-work evidence exists.
Keep low-hanging fruit distinct: low effort plus high information value, not a
large research initiative.

Complete only when every explicit focus has analytical coverage, significant
available evidence is mapped and used, existing artifacts were mined before
recommending new measurement, material claims are traceable, the stable
architecture answers the request, unsupported generic content and duplicate
findings are absent, the Research & Improvement Map and low-hanging fruit appear
when supported, iteration 2 completes a substantive depth review and repairs or
dispositions every material gap, aggregate metrics are contextualized when
deeper evidence exists, final consistency passes, and a delivered PDF has a
final defect-free or explicitly accepted page-image review.
Expose the final report and optionally its semantic source; keep internal state,
plans, review logs, and temporary renders out of normal delivery.
