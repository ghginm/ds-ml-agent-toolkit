# Technical-report mode

Use when the deliverable primarily explains a DS/ML project, model, data,
evaluation, results, or experiments. Markdown or PDF does not change the mode.
Project investigation remains here; final information architecture and prose
belong to [compose-dsml-report](../../compose-dsml-report/SKILL.md).

## Evidence objective

Trace the supported system: objective, target, grain, population, sources,
transformations, feature families, model architecture, training and selection,
evaluation design, inference, operational horizon, results, constraints, and
unknowns. Inspect permitted aggregate artifacts and outputs before turning code
observations into findings. Distinguish operational, validated, and
model-selection horizons; interpret metrics in comparison context; do not infer
feature contribution without importance or ablation evidence.

Treat every explicit user focus as an analytical obligation, not a heading.
Translate each focus into domain-adaptive questions before discovery. Use the
following bundles as prompts, not a mandatory forecasting schema:

- **Model design:** components and roles; fitting/training logic; interactions;
  design rationale and important parameters; empirical differences, strengths,
  failure modes, complexity, and unknowns.
- **Features:** families and concrete examples; construction and expected
  signal; point-in-time/inference availability and leakage risk; empirical
  contribution, redundancy, questionable complexity, and open questions.
- **Evaluation:** training, tuning, selection, and final-holdout boundaries;
  metric definitions, baselines, aggregation, performance dimensions,
  stability, bias, cohort effects, uncertainty, leakage, and trust limits.
- **Current issues:** mechanism, evidence, consequence, confidence, repair,
  dependencies, and which conclusions the issue weakens.

Adapt equivalent questions for classifiers, regressors, recommenders, ranking,
anomaly detection, NLP, graph, causal, vision, and hybrid systems. For important
components, borrow the deep-audit reasoning pattern WHAT → HOW → WHY → IMPORTANT
PARAMETERS → SO WHAT, without adopting audit framing or a defect-led structure.

For every material feature family, model component, evaluation choice, or issue,
collect enough evidence to explain more than implementation. Select only the
dimensions that change understanding: role, intended mechanism, applicability
conditions, assumptions, failure modes, interactions or redundancy,
project-specific empirical support, remaining uncertainty, and implication.
Do not populate a checklist mechanically. A concise component analysis is deep
enough only when an experienced reader can explain why it could work, what could
invalidate it, and whether this project demonstrates that it works.

Keep three claim types distinct in state:

- **Verified project fact:** code, configuration, data, or artifacts establish it.
- **Technical rationale:** statistical, ML, domain, or engineering reasoning makes
  the design plausible, but does not establish project benefit.
- **Project-specific empirical support:** an experiment or diagnostic measures the
  design's behavior or contribution in this project.

When rationale exists without empirical support, say so directly. Never upgrade
plausibility into observed benefit. For major findings, consolidate a compact
mechanism → evidence → implication chain; the evidence may be an explicit gap.

## Evidence-surface discovery

For each requested focus, deliberately search the repository and existing
outputs before concluding that only high-level evidence exists. Inspect, when
present:

- feature inventories, importance/SHAP/permutation outputs, grouped ablations,
  coefficients, contribution summaries, training logs, and model metadata;
- candidate comparisons, allocation/routing shares, margins, switching,
  regret, model-specific diagnostics, runtime, memory, and tuning history;
- fold/origin/horizon metrics, row-level predictions, segments/cohorts, bias,
  variance, calibration, coverage, holdout definitions, and baseline outputs;
- stage durations, profiles, repeated transforms, fit durations, convergence,
  trial distributions, parameter sensitivity, and diminishing returns.

Record each relevant surface as available/unavailable/not applicable, whether
it was inspected, its significance, and a compact interpretation. Existing
evidence is mined before proposing new measurement: analyze available
importance, stability, routing, runtime, or tuning artifacts rather than
recommending that the user generate them. Create a future MEASURE opportunity
only when evidence is absent or cannot safely be derived. Never treat gain
importance as causal evidence.

Do not draft reader-facing report sections while material findings are still
being discovered. Discovery order is not report structure.

## Normalized handoff

Create the normalized analysis state defined by
[analysis-state.md](../../compose-dsml-report/references/analysis-state.md).
Consolidate the project map, material findings, supported actions/opportunities,
and reviewed unknowns. Internal records may use fields such as issue,
consequence, evidence, and action, but the final report need not expose those
fields or registers as headings/cards.

Do not force empty categories, duplicate one fact as both an issue and an
opportunity, or add generic ideas unsupported by evidence. Set the synthesis
gate to ready only after the state is coherent and material unknowns are
reviewed.

Use the richer optional project-map structures for requested focuses when they
preserve evidence that a scalar summary would lose: `feature_groups`,
`model_components`, and structured `evaluation`. Add `evidence_surfaces` and
`focus_coverage` to state schema 0.3. For each focus, record its questions,
implementation inspection, evidence IDs, interpretations, remaining relevant
surfaces, and `sufficient` / `weak` / `unavailable` status. Do not mark a focus
sufficient without an interpretation beyond description. Do not compose while
coverage is weak because relevant existing artifacts remain uninspected; inspect
them first. Genuine absence becomes an explicit evidence gap.

For material feature groups, populate the existing `expected_signal`,
`inference_availability`, `empirical_evidence`, `risks`, and `open_questions`
with analytical statements, not inventory fragments. Add optional
`applicability_conditions` or `interactions` only when those relationships would
otherwise be lost. For material model components, use `role`, `training_logic`,
`interaction_with_other_components`, `empirical_behavior`, `strengths`, and
`limitations`; add optional `design_rationale` or `applicability_conditions`
only for a real gap. A finding may add `mechanism` and `affected_scope` when its
failure path would otherwise be implicit. Prefer these focused additions over a
larger universal schema.

Then hand the normalized state to the technical-report workflow. That workflow
creates and reviews the report plan before loading compose-dsml-report. If a
material finding appears later, update state, increment its revision, identify
affected plan sections, and recompose them. Never create an `Additional
Findings` or similar chronology section.

## Evidence and visuals

Classify material claims as Verified, Inferred, Unknown, or Recommendation when
status changes interpretation. Prefer WHAT / WHY / HOW explanations, feature
families, and representative examples. Supply chart/diagram candidates only
when they answer a project-specific question better than prose or a compact
table. Keep correctness blockers distinct from ordinary limitations.

Analysis is ready for composition when the critical flow is supported,
material claims are classified, normalized state is consolidated, and unknowns
are explicit. In addition, every requested focus has passed the coverage gate
and significant existing evidence has been mined. Target page length never
changes this investigation depth; it is a later presentation budget. Analysis
state is not complete report prose.
