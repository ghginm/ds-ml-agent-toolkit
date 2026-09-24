# Deep-audit mode

Use only when the user's intent is explicitly audit-oriented: correctness,
leakage, production readiness, failure/risk assessment, code/model review,
reliability, governance, controls, or whether the system can be trusted. PDF or
Markdown alone never selects this mode. Reuse the system, data, model,
evaluation, and results analysis described in
the required analysis surfaces and synthesis rules below, organizing the deliverable around audit questions, evidence traceability, failure surfaces, and prioritized remediation. Use [the shared stylesheet](../../compose-dsml-report/assets/report-style.css)
only for a verified HTML/PDF toolchain.

## Goal of the report

Produce a technically grounded audit rather than a source-code evidence dump.
Correctness, leakage, evaluation validity, failure surfaces, operational risk,
governance, traceability, and prioritized remediation may lead the document,
but the reader still needs enough system and model context to evaluate those
findings. An experienced reviewer should be able to determine:

1. the problem being solved;
2. the data that enters the system;
3. the target and prediction unit;
4. how preprocessing works;
5. what models and components exist and **why** each exists;
6. what features are used, with concrete names, groups, and parameters;
7. how training, validation, testing, model selection, and inference work;
8. the important numerical results;
9. the main technical or modelling weaknesses;
10. what should be fixed or investigated next.

Do not reduce technical depth. Improve organization, explanation, and
information density.

## Scope before depth

Record the decision the report supports, audience, repository revision,
accessible evidence, material exclusions, data classification, and
authorization boundaries. A deep report is tracked work: initialize sibling
`run.yaml` and `learning.yaml` records, keeping intent and execution
evidence in `run.yaml` and only compact request/routing metadata plus
meaningful agent signals in `learning.yaml`.

## Required analysis surfaces

Cover each surface that can change the decision and mark irrelevant surfaces
with a short reason. These are the *topics* the report must investigate;
the *order and framing* of how they appear in the report is governed by the
content contract, not by this list.

1. **System and lineage:** source grain / keys / time → transformations →
   features / target → split → model → evaluation → artifact → operational
   action.
2. **Target contract:** label source, construction, delay / noise, unit of
   observation, horizon, censoring, and leakage opportunities.
3. **Feature contract:** lineage, point-in-time availability,
   training-inference consistency, null / default behaviour, and unstable
   proxies.
4. **Model contract:** architecture, objective / loss, class weighting or
   sampling, calibration, thresholds, and artifact selection.
5. **Evaluation contract:** population, temporal / entity split, baseline,
   metric implementation, uncertainty, subgroup / temporal stability, and
   final-holdout usage.
6. **Operational contract:** consumer, decision rule, capacity, latency,
   fallback, monitoring, retraining trigger, and failure impact.
7. **Reproducibility and governance:** code / data / query / feature / model
   versions, seeds, environment, approvals, limitations, and ownership.

Use concise formulas only when they clarify a project-specific
transformation, loss, or metric. Prefer diagrams that expose real lineage,
boundaries, joins, or failure surfaces; omit decorative visuals.

## Evidence discipline (preserve, do not weaken)

- Classify material statements as `Verified`, `Inferred`, `Unknown`, or
  `Recommendation`.
- Cite repository paths with symbols or line ranges, sanitized command
  results, query identifiers, or artifact versions.
- Seek contradictory evidence and stale documentation.
- Separate inability to observe from absence of a behaviour.
- Never invent feature importance, business requirements, model behaviour,
  architecture components, metrics, or causal explanations when the
  repository does not support them. If the artefact is not present, say so
  explicitly — for example:
  `Feature importance: not available in inspected artifacts.`

Evidence-status prefixes should not interrupt every paragraph. Where the
status is unambiguous from context (because the sentence cites a specific
file and line), keep the prose readable and rely on the labels only where
they change interpretation.

## Synthesis rules

Follow these rules when writing the audit. They govern *how* the investigation
becomes a readable explanation; the required analysis surfaces above govern
*what* must be covered.

1. **Lead with the system, not the audit.** The first section explains the
   whole system end to end in roughly five minutes of reading. Provenance,
   file inventories, hashes, and authorization boundaries belong later or in
   the appendix.
2. **Avoid repetitive summaries.** Use one strong executive summary. Later
   sections may open with a single finding sentence when useful, followed by
   evidence; do not require repeated **Key takeaways** blocks.
3. **One concrete walkthrough.** Include an end-to-end walkthrough that
   follows one observation through the real pipeline (raw data →
   preprocessing → target → features → model → selection / routing →
   prediction → post-processing → output → consumer). Adapt the steps to
   the actual project.
4. **Component-level reasoning structure.** For important components, prefer
   WHAT → HOW → WHY → IMPORTANT NUMBERS / PARAMETERS → SO WHAT. Example
   shape: which lag features are used, how they are constructed (recursive
   or direct), why short lags capture persistence and ~52-week lags capture
   annual structure, the exact lags and windows, and the implications
   (recursive error, leakage risk, inference-time availability).
5. **Practical data and target section.** Target definition should be
   visually prominent (formula, callout). Cover observation unit, joins,
   inclusion / exclusion, missing-value treatment, leakage-sensitive
   fields, freshness, and the gap between raw business quantity and
   modelled target.
6. **Feature section is a structured table, not a paragraph.** Use a table
   with concrete columns (Feature family / Concrete features / Source and
   construction / Lookback / Why it may help / Available at inference? /
   Risks). Include concrete examples and exact parameters. If importance
   artifacts exist, summarize and visualize; if not, state explicitly.
7. **Combine model description and model assessment.** For each important
   model or component, keep purpose, input, mechanics, parameters,
   training, inference, performance evidence, strengths, and weaknesses in
   one place. Avoid describing a model in one section and repeating its
   risks several pages later.
8. **Make train / validation / test easy to understand.** When relevant,
   include a simple timeline or rolling-origin schematic. Explain ranges,
   fold count, horizon, overlap, early stopping, hyperparameter tuning,
   transformations fitted before versus inside each fold, the final
   holdout, and whether evaluation data is reused for selection. Visualize
   the split when prose would otherwise force the reader to reconstruct it.
9. **Conditional figures, not a fixed chart count.** Generate a figure
   when it materially reduces cognitive load or exposes a real comparison
   or trend. Every chart must answer a concrete question; no decorative
   plots. Typical candidates: architecture or data-flow diagram,
   train / validation / test timeline, model comparison across horizons,
   stability across time or cohorts, feature importance, routing
   distribution, error distribution, subgroup performance, runtime
   comparison. If the data is not available, do not fabricate it.
10. **Interpretation with every results table.** Keep exact numbers; add
    interpretation. Explain which model wins where, the size of the
    improvement, whether differences are small or large, bias direction,
    horizon degradation, temporal instability, and whether comparisons are
    valid (identical populations, fixed cohorts, leakage-free). When
    comparing a few models across a few horizons, a line chart usually
    beats a table alone.
11. **ONE canonical findings table.** Maintain a single prioritized
    findings table (Severity / Problem / Mechanism / Impact / Evidence /
    Suggested fix). Separate correctness bugs, modelling and evaluation
    weaknesses, operational and reproducibility issues, and unknowns when
    this distinction improves clarity. Findings may be briefly referenced
    elsewhere, but do not re-explain the entire issue repeatedly.
12. **Recommendations form a dependency-aware roadmap.** Typical stages:
    correctness first → rebuild credible evaluation → reassess modelling
    decisions → production and reproducibility hardening. Explain
    dependencies (e.g. fix leakage → rerun evaluation → assess router →
    only then change architecture). Do not recommend large architecture
    changes on the basis of metrics that are not trustworthy.
13. **Provenance and evidence detail move toward the end.** Keep them in
    the appendix or the final evidence index unless one is directly
    relevant to a major finding in the body.
14. **Higher information density, not shallower depth.** Prefer
    `mechanism + concrete example + exact number + interpretation` over
    paragraphs repeating the same conclusion. Remove redundant prose;
    avoid boilerplate DS/ML explanations for an experienced audience.

## Markdown and rendering compatibility

Markdown is the source of truth. Do not install a renderer silently. If an
approved `pandoc` is already available, an operator may run:

```text
pandoc report.md --standalone --css report-style.css --output report.html
pandoc report.md --pdf-engine=<approved-engine> --output report.pdf
```

Record the exact command and result in `run.yaml`. If no verified renderer
exists, deliver Markdown and this runbook; do not claim a PDF exists.

Prefer simple robust visualization generation. If Mermaid is not reliably
supported by the verified rendering path, use whatever compatible approach
already exists in the project (rendered SVG / PNG / Graphviz) rather than
introducing a new dependency.

## Completion check

An experienced reviewer must be able to:

- explain the data-to-decision path end to end from the report;
- identify where the decision comes from, which assumptions make it valid,
  and where it may fail;
- reproduce the important results from referenced versions and commands;
- prioritize the unresolved risks;
- locate the exact features and important model parameters quickly.

A report that satisfies these criteria is complete regardless of whether it
uses every section of the template.
