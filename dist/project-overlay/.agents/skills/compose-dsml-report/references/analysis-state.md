# Normalized analysis state

Use one structured object as the handoff between project analysis and report
planning/composition. It is evidence state, not a reader-facing outline:

    {
      "schema_version": "0.3",
      "state_revision": "1",
      "project_map": {
        "objective": "...",
        "target": "...",
        "prediction_grain": "...",
        "data_sources": [],
        "feature_groups": [{
          "name": "...", "examples": [], "construction": "...",
          "expected_signal": "...", "inference_availability": "...",
          "applicability_conditions": [], "interactions": [],
          "empirical_evidence": [], "risks": [], "open_questions": []
        }],
        "model_components": [{
          "name": "...", "role": "...", "training_logic": "...",
          "design_rationale": "...", "applicability_conditions": [],
          "key_parameters": [], "interaction_with_other_components": "...",
          "empirical_behavior": [], "strengths": [], "limitations": [],
          "evidence_refs": []
        }],
        "evaluation": {
          "split_structure": "...", "tuning_window": "...",
          "model_selection_window": "...", "outer_holdout": "...",
          "metrics": [], "baselines": [], "dimensions_analyzed": [],
          "empirical_results": [], "stability_evidence": [],
          "bias_evidence": [], "cohort_evidence": [],
          "known_validity_issues": []
        },
        "current_results": [],
        "known_constraints": [],
        "important_unknowns": []
      },
      "findings": [{
        "id": "EVAL-01",
        "topic": "evaluation",
        "title": "...",
        "claim_status": "Verified",
        "mechanism": "...",
        "evidence": "...",
        "consequence": "...",
        "affected_scope": "...",
        "recommended_action": "...",
        "confidence": "High"
      }],
      "opportunities": [{
        "id": "MODEL-01",
        "topic": "modeling",
        "title": "...",
        "basis": "...",
        "next_step": "...",
        "decision_enabled": "...",
        "dependency": "EVAL-01",
        "effort": "Medium",
        "confidence": "Medium"
      }],
      "evidence_surfaces": [{
        "id": "FEAT-IMP-01", "focus": "features",
        "kind": "feature_importance", "source": "artifacts/importance.csv",
        "availability": "available", "inspected": true,
        "significance": "high", "summary": "..."
      }],
      "focus_coverage": [{
        "focus": "features", "status": "sufficient",
        "questions": ["Which feature groups dominate, and is that plausible?"],
        "implementation_inspected": true,
        "evidence_ids": ["FEAT-IMP-01"],
        "interpretations": ["..."],
        "uninspected_relevant_surfaces": []
      }],
      "synthesis_gate": {
        "status": "ready",
        "project_map_consolidated": true,
        "findings_consolidated": true,
        "opportunities_consolidated": true,
        "material_unknowns_reviewed": true,
        "focus_coverage_reviewed": true,
        "existing_evidence_mined": true
      }
    }

Do not add empty project-map fields to imitate the example. The richer
`feature_groups`, `model_components`, and `evaluation` objects are optional and
replace—not duplicate—coarse scalar fields when their structure preserves
decision-useful evidence. `findings` and
`opportunities` are arrays and may be empty when evidence supports none. Claim
status is `Verified`, `Inferred`, `Unknown`, or `Recommendation`; confidence and
effort use `Low`, `Medium`, or `High` when known.

A finding may include issue, consequence, evidence, and action without forcing
four reader-facing labels. An opportunity must have an evidence basis and name
the decision its result enables. Avoid representing the same content as both a
finding and an opportunity unless the opportunity is a distinct next action
that references the canonical finding.

For each material component, use the smallest set of fields that preserves its
reasoning chain. `expected_signal` or `design_rationale` records technical
plausibility; it is not empirical support. `empirical_evidence` or
`empirical_behavior` records project observations and should identify an
evidence reference or an explicit absence. `risks`, `limitations`,
`applicability_conditions`, `interactions`, and `open_questions` preserve the
conditions and uncertainty needed for critical assessment. A component with an
implementation description but none of those analytical dimensions is not
ready for a standard or publication report.

`mechanism` and `affected_scope` are optional finding fields. Use them when the
causal path or blast radius is not obvious from `evidence` and `consequence`.
Their presence does not require matching reader-facing labels.

`evidence_surfaces` is a compact discovery ledger for requested focus areas,
not a repository inventory. Record meaningful available, unavailable, or
not-applicable surfaces. `focus_coverage` is the pre-composition gate. A weak
focus with relevant uninspected surfaces blocks composition; unavailable
coverage requires an explicit `evidence_gap`.

For compatibility with existing installed projects, schema versions `0.1` and
`0.2` remain valid input. Normalize `0.1` `issues` to `findings` in memory
before planning; do not preserve their register topology in the report. New
technical reports should use `0.3` when explicit focus coverage is required.

The semantic report source includes both revision markers:

    <!-- dsml-report-state-revision: 1 -->
    <!-- dsml-report-plan-revision: 1 -->
