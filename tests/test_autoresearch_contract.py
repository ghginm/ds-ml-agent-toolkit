from __future__ import annotations

import concurrent.futures
import importlib.util
import csv
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tooling" / "validate-kit.py"
SPEC = importlib.util.spec_from_file_location("validate_kit_autoresearch", MODULE_PATH)
assert SPEC and SPEC.loader
validate_kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_kit)

RECONSTRUCT_PATH = ROOT / "tooling" / "reconstruct-contract.py"
RECONSTRUCT_SPEC = importlib.util.spec_from_file_location(
    "reconstruct_contract", RECONSTRUCT_PATH
)
assert RECONSTRUCT_SPEC and RECONSTRUCT_SPEC.loader
reconstruct_contract = importlib.util.module_from_spec(RECONSTRUCT_SPEC)
RECONSTRUCT_SPEC.loader.exec_module(reconstruct_contract)

FINALIZE_PATH = ROOT / "tooling" / "finalize-run.py"
FINALIZE_SPEC = importlib.util.spec_from_file_location("finalize_run", FINALIZE_PATH)
assert FINALIZE_SPEC and FINALIZE_SPEC.loader
finalize_run_module = importlib.util.module_from_spec(FINALIZE_SPEC)
FINALIZE_SPEC.loader.exec_module(finalize_run_module)

RECORD_PATH = ROOT / "tooling" / "record-experiment.py"
RECORD_SPEC = importlib.util.spec_from_file_location("record_experiment", RECORD_PATH)
assert RECORD_SPEC and RECORD_SPEC.loader
record_experiment_module = importlib.util.module_from_spec(RECORD_SPEC)
RECORD_SPEC.loader.exec_module(record_experiment_module)


def journal_row(**overrides: str) -> dict[str, str]:
    row = {field: "" for field in validate_kit.EXPERIMENT_JOURNAL_FIELDS}
    row.update(
        {
            "stage": "development",
            "code_revision": "abc123",
            "meaningful_improvement": "false",
            "materially_new_evidence": "true",
        }
    )
    row.update(overrides)
    return row


class AutoresearchContractTests(unittest.TestCase):
    def evaluation_template(self) -> dict[str, Any]:
        return json.loads(
            (ROOT / ".agent-system" / "templates" / "evaluation.template.yaml").read_text(
                encoding="utf-8"
            )
        )

    # ------------------------------------------------------------------
    # Generic metric semantics: identity is syntactic, semantics declared
    # ------------------------------------------------------------------

    def test_metric_canonicalization_is_syntactic_only(self) -> None:
        self.assertEqual(validate_kit._canonical_metric_name(" RMSE "), "rmse")
        self.assertEqual(validate_kit._canonical_metric_name("RMSE"), "rmse")
        self.assertEqual(validate_kit._canonical_metric_name("custom_metric"), "custommetric")
        self.assertEqual(validate_kit._canonical_metric_name("CUSTOM_METRIC"), "custommetric")
        # No forecasting ontology: the same function is used for arbitrary names.
        self.assertEqual(validate_kit._canonical_metric_name("my_project_metric"), "myprojectmetric")
        self.assertFalse(hasattr(validate_kit, "MINIMIZED_METRICS"))
        self.assertFalse(hasattr(validate_kit, "MAXIMIZED_METRICS"))
        self.assertFalse(hasattr(validate_kit, "infer_evaluation_contract"))

    def test_journal_selection_metric_matches_case_variant_of_objective(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": " RMSE ",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        row = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            selection_metric="rmse",
            selection_value="9.5",
            guardrail_status="not_applicable",
            status="baseline",
        )
        self.assertEqual([], validate_kit.experiment_journal_errors([row], evaluation, None))

    def test_canonical_metric_collision_is_ambiguous_evidence(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "RMSE",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        row = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            selection_metric="RMSE",
            selection_value="10.0",
            metrics_json=json.dumps({"RMSE": 10.0, "rmse": 11.0}),
            guardrail_status="not_applicable",
            status="baseline",
        )
        errors = validate_kit.experiment_journal_errors([row], evaluation, None)
        self.assertTrue(
            any("collide on one canonical metric identity" in error for error in errors),
            errors,
        )

    def test_selection_value_disagrees_with_metrics_json(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "auroc",
            "direction": "maximize",
            "minimum_meaningful_delta": None,
        }
        row = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            selection_metric="AUROC",
            selection_value="0.91",
            metrics_json=json.dumps({"auroc": 0.72}),
            guardrail_status="not_applicable",
            status="baseline",
        )
        errors = validate_kit.experiment_journal_errors([row], evaluation, None)
        self.assertTrue(any("disagrees with metrics_json" in error for error in errors), errors)

    def test_secondary_metric_colliding_with_objective_is_rejected(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "RMSE",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        evaluation["secondary_metrics"] = [
            {"metric": "rmse", "role": "reporting", "direction": "minimize", "max_degradation": None}
        ]
        errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("runs/r1/evaluation.yaml"), ROOT, ledger_records=[]
        )
        self.assertTrue(any("collides with the selection objective" in error for error in errors), errors)

    # ------------------------------------------------------------------
    # Cross-domain contracts validated by the same generic machinery
    # ------------------------------------------------------------------

    def test_cross_domain_contracts_use_identical_generic_logic(self) -> None:
        cases = (
            # (metric, direction, strategy, guardrail metric, guardrail direction)
            ("rmse", "minimize", "rolling_origin", "wape", "minimize"),
            ("auroc", "maximize", "temporal_or_grouped_cv", "inference_latency_ms", "minimize"),
            ("custom_loss", "minimize", "grouped_cv", None, None),
            ("ndcg_at_10", "maximize", "stratified_group_cv", None, None),
            ("my_project_metric", "maximize", "single_holdout", "latency_ms", "minimize"),
        )
        for metric, direction, strategy, guardrail, guardrail_direction in cases:
            with self.subTest(metric=metric):
                evaluation = self.evaluation_template()
                evaluation["experiment_mode"] = "benchmark"
                evaluation["candidate_plan"] = "predeclared"
                evaluation["adaptive_evolution"] = "not_applicable"
                evaluation["selection_objective"] = {
                    "metric": metric,
                    "direction": direction,
                    "minimum_meaningful_delta": None,
                }
                evaluation["evaluation"]["strategy"] = strategy
                metrics_row = {metric: 1.0}
                if guardrail is not None:
                    evaluation["secondary_metrics"] = [
                        {
                            "metric": guardrail,
                            "role": "guardrail",
                            "direction": guardrail_direction,
                            "max_degradation": 0.1,
                        }
                    ]
                    metrics_row[guardrail] = 50.0
                self.assertEqual(
                    [],
                    validate_kit.evaluation_semantic_errors(
                        evaluation, Path("runs/r1/evaluation.yaml"), ROOT, ledger_records=[]
                    ),
                )
                rows = [
                    journal_row(
                        experiment_id="exp_01",
                        candidate_identity="1" * 64,
                        selection_metric=metric,
                        selection_value="1.0",
                        metrics_json=json.dumps({metric: 1.0, **(
                            {guardrail: 50.0} if guardrail else {}
                        )}),
                        guardrail_status="pass" if guardrail else "not_applicable",
                        status="baseline",
                    ),
                    journal_row(
                        experiment_id="exp_02",
                        parent_experiment_id="exp_01",
                        candidate_identity="2" * 64,
                        selection_metric=metric,
                        selection_value="1.05" if direction == "maximize" else "0.95",
                        metrics_json=json.dumps({
                            metric: 1.05 if direction == "maximize" else 0.95,
                            **({guardrail: 50.0} if guardrail else {}),
                        }),
                        guardrail_status="pass" if guardrail else "not_applicable",
                        status="rejected",
                    ),
                ]
                self.assertEqual(
                    [],
                    validate_kit.experiment_journal_errors(rows, evaluation, None),
                    msg=f"{metric}: unexpected journal errors",
                )

    # ------------------------------------------------------------------
    # Guardrail governance is mechanical and domain-independent
    # ------------------------------------------------------------------

    def guardrail_evaluation(self, metric: str, direction: str, allowed: float) -> dict[str, Any]:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "primary_score",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        evaluation["secondary_metrics"] = [
            {
                "metric": metric,
                "role": "guardrail",
                "direction": direction,
                "max_degradation": allowed,
            }
        ]
        return evaluation

    def test_manual_guardrail_pass_cannot_override_violation(self) -> None:
        # Contract: latency_ms minimize, max_degradation 5. Same machinery as any
        # domain metric; primary metric is even *worse* here, which previously
        # skipped guardrail checks entirely.
        evaluation = self.guardrail_evaluation("latency_ms", "minimize", 5)
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="primary_score",
                selection_value="100.0",
                metrics_json=json.dumps({"primary_score": 100.0, "latency_ms": 100.0}),
                guardrail_status="pass",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_01",
                candidate_identity="2" * 64,
                selection_metric="primary_score",
                selection_value="101.0",
                metrics_json=json.dumps({"primary_score": 101.0, "latency_ms": 120.0}),
                guardrail_status="pass",
                status="rejected",
                hypothesis="candidate",
                expected_mechanism="candidate",
                change_summary="candidate",
                result_summary="measured",
                next_hypothesis_rationale="continue",
            ),
        ]
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(
            any("latencyms degraded by 20, exceeding 5" in error for error in errors),
            errors,
        )
        rows[1]["guardrail_status"] = "fail"
        self.assertEqual([], validate_kit.experiment_journal_errors(rows, evaluation, None))

    def test_maximize_guardrail_direction_is_declared_not_inferred(self) -> None:
        evaluation = self.guardrail_evaluation("recall_at_100", "maximize", 0.01)
        violations, missing = validate_kit.guardrail_findings(
            evaluation,
            {"recall_at_100": 0.90},
            {"recall_at_100": 0.80},
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual([], missing)
        violations, missing = validate_kit.guardrail_findings(
            evaluation,
            {"recall_at_100": 0.90},
            {"recall_at_100": 0.895},
        )
        self.assertEqual([], violations)

    def test_pass_claim_without_guardrail_evidence_is_rejected(self) -> None:
        evaluation = self.guardrail_evaluation("wape", "minimize", 0.01)
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="primary_score",
                selection_value="10.0",
                metrics_json=json.dumps({"primary_score": 10.0, "wape": 0.20}),
                guardrail_status="pass",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_01",
                candidate_identity="2" * 64,
                selection_metric="primary_score",
                selection_value="9.0",
                metrics_json=json.dumps({"primary_score": 9.0}),
                guardrail_status="pass",
                status="promoted_to_holdout",
                hypothesis="candidate",
                expected_mechanism="candidate",
                change_summary="candidate",
                result_summary="measured",
                next_hypothesis_rationale="continue",
            ),
        ]
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(
            any("claims measured evidence" in error for error in errors), errors
        )
        rows[1]["guardrail_status"] = "unverified"
        self.assertEqual([], validate_kit.experiment_journal_errors(rows, evaluation, None))

    # ------------------------------------------------------------------
    # Point-in-time logic stays conditional and domain-general
    # ------------------------------------------------------------------

    def test_point_in_time_rejects_label_not_available_by_training_cutoff(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["point_in_time"] = {
            "enabled": True,
            "verification_status": "verified",
            "prediction_cutoff": "2026-01-08T00:00:00Z",
            "training_cutoff": "2026-01-08T00:00:00Z",
            "feature_available_at": "2026-01-07T23:00:00Z",
            "label_available_at": "2026-01-10T00:00:00Z",
            "assumptions": [],
        }

        errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
        )

        self.assertTrue(any("label_available_at" in error for error in errors), errors)
        evaluation["point_in_time"]["label_available_at"] = "2026-01-08T00:00:00Z"
        self.assertEqual(
            [],
            validate_kit.evaluation_semantic_errors(
                evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
            ),
        )

    def test_point_in_time_rejects_training_cutoff_after_prediction_cutoff(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["point_in_time"] = {
            "enabled": True,
            "verification_status": "verified",
            "prediction_cutoff": "2026-01-08T00:00:00Z",
            "training_cutoff": "2026-02-08T00:00:00Z",
            "feature_available_at": "2026-01-07T23:00:00Z",
            "label_available_at": "2026-01-07T23:00:00Z",
            "assumptions": [],
        }
        errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
        )
        self.assertTrue(any("training_cutoff" in error for error in errors), errors)

    def test_non_temporal_contract_does_not_require_point_in_time_fields(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "auroc",
            "direction": "maximize",
            "minimum_meaningful_delta": None,
        }
        evaluation["evaluation"]["strategy"] = "grouped_cv"
        evaluation["point_in_time"] = {
            "enabled": False,
            "verification_status": "not_applicable",
            "prediction_cutoff": None,
            "training_cutoff": None,
            "feature_available_at": None,
            "label_available_at": None,
            "assumptions": [],
        }
        self.assertEqual(
            [],
            validate_kit.evaluation_semantic_errors(
                evaluation, Path("runs/r1/evaluation.yaml"), ROOT, ledger_records=[]
            ),
        )

    def test_unverified_point_in_time_requires_assumptions(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["point_in_time"].update(
            {"enabled": True, "verification_status": "unverified", "assumptions": []}
        )
        errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
        )
        self.assertTrue(any("assumptions" in error for error in errors), errors)
        evaluation["point_in_time"]["assumptions"] = [
            "Fraud labels arrive up to 30 days late; training uses labels available at extract time."
        ]
        errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
        )
        self.assertEqual(
            [error for error in errors if "assumptions" in error], [], errors
        )

    # ------------------------------------------------------------------
    # Exposure ledger and the untouched-claim invariant
    # ------------------------------------------------------------------

    def test_previously_exposed_final_split_cannot_remain_untouched(self) -> None:
        evaluation = self.evaluation_template()
        identity = evaluation["evaluation"]["final_split_identity"]
        identity.update(
            {
                "split_id": "outer-2026-q1",
                "split_hash": "a" * 64,
                "dataset_hash": "b" * 64,
                "population_hash": "c" * 64,
                "exposure_status": "untouched",
            }
        )
        record = {
            "run_id": "earlier-run",
            "split_id": "outer-2026-q1",
            "split_hash": "a" * 64,
            "dataset_hash": "b" * 64,
            "population_hash": "c" * 64,
            "role": "final",
            "first_exposed_at": "2026-09-30T00:00:00Z",
            "exposure_count": 1,
        }

        first_errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[]
        )
        second_errors = validate_kit.evaluation_semantic_errors(
            evaluation, Path("evaluation.yaml"), ROOT, ledger_records=[record]
        )

        self.assertEqual([], first_errors)
        self.assertTrue(any("previously exposed" in error for error in second_errors), second_errors)

    def test_ledger_rejects_duplicate_event_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            record = {
                "event_id": "e" * 64,
                "run_id": "run-a",
                "split_hash": "a" * 64,
                "dataset_hash": "b" * 64,
                "population_hash": None,
                "role": "final",
                "first_exposed_at": "2026-09-30T00:00:00Z",
                "exposure_count": 1,
            }
            ledger.write_text(
                json.dumps(record, sort_keys=True) + "\n" + json.dumps(record, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            records, errors = validate_kit.load_evaluation_ledger(root)
            self.assertTrue(any("duplicate exposure event_id" in error for error in errors), errors)

    # ------------------------------------------------------------------
    # Experiment journal identity and adaptive semantics
    # ------------------------------------------------------------------

    def test_selected_experiment_resolves_by_identity_not_revision_alone(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"]["metric"] = "RMSE"
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                runner_hash="c" * 64,
                input_manifest_hash="d" * 64,
                prediction_hash="e" * 64,
                selection_metric="RMSE",
                selection_value="9.0",
                guardrail_status="pass",
                status="baseline",
                hypothesis="baseline",
                expected_mechanism="baseline",
                change_summary="baseline",
                result_summary="baseline",
                next_hypothesis_rationale="try another config",
                artifact_ref="predictions-exp-01.csv",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_01",
                candidate_identity="2" * 64,
                config_hash="b" * 64,
                runner_hash="c" * 64,
                input_manifest_hash="d" * 64,
                prediction_hash="f" * 64,
                selection_metric="RMSE",
                selection_value="8.0",
                guardrail_status="pass",
                status="final_selected",
                hypothesis="regularization improves generalization",
                expected_mechanism="reduce variance",
                change_summary="changed regularization config",
                result_summary="meaningful RMSE improvement",
                next_hypothesis_rationale="selected",
                artifact_ref="predictions-exp-02.csv",
            ),
        ]
        selected = {
            "experiment_id": "exp_02",
            "candidate_identity": "2" * 64,
            "code_revision": "abc123",
            "config_hash": "b" * 64,
            "prediction_hash": "f" * 64,
        }

        self.assertEqual(
            [], validate_kit.experiment_journal_errors(rows, evaluation, selected)
        )
        selected["config_hash"] = "a" * 64
        errors = validate_kit.experiment_journal_errors(rows, evaluation, selected)
        self.assertTrue(any("config_hash mismatch" in error for error in errors), errors)
        selected["config_hash"] = "b" * 64
        selected["candidate_identity"] = "9" * 64
        errors = validate_kit.experiment_journal_errors(rows, evaluation, selected)
        self.assertTrue(any("candidate_identity mismatch" in error for error in errors), errors)

    def test_selected_experiment_requires_candidate_identity(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"]["metric"] = "RMSE"
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="RMSE",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="final_selected",
            )
        ]
        selected = {"experiment_id": "exp_01", "candidate_identity": None}
        errors = validate_kit.experiment_journal_errors(rows, evaluation, selected)
        self.assertTrue(
            any("candidate_identity is required" in error for error in errors), errors
        )

    def test_journal_stage_vocabulary_is_enforced(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "rmse",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        row = journal_row(
            experiment_id="exp_01",
            stage="final_holdout",
            candidate_identity="1" * 64,
            selection_metric="rmse",
            guardrail_status="not_applicable",
            status="baseline",
        )
        errors = validate_kit.experiment_journal_errors([row], evaluation, None)
        self.assertTrue(any("stage" in error for error in errors), errors)

    def test_journal_selection_metric_must_match_evaluation_objective(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["selection_objective"]["metric"] = "RMSE"
        row = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            selection_metric="FA",
            guardrail_status="pass",
            status="baseline",
            hypothesis="baseline",
            expected_mechanism="baseline",
            change_summary="baseline",
            result_summary="baseline",
            next_hypothesis_rationale="continue",
        )

        errors = validate_kit.experiment_journal_errors([row], evaluation, None)

        self.assertTrue(any("selection_metric" in error for error in errors), errors)

    def test_benchmark_sweep_does_not_require_adaptive_lineage(self) -> None:
        evaluation = self.evaluation_template()
        evaluation.update(
            {
                "experiment_mode": "benchmark",
                "candidate_plan": "predeclared",
                "adaptive_evolution": "not_applicable",
            }
        )
        evaluation["selection_objective"]["metric"] = "RMSE"
        rows = [
            journal_row(
                experiment_id=f"exp_0{index + 1}",
                candidate_identity=str(index + 1) * 64,
                config_hash=chr(ord("a") + index) * 64,
                selection_metric="RMSE",
                selection_value=str(10 - index),
                guardrail_status="pass",
                status="baseline" if index == 0 else "rejected",
            )
            for index in range(2)
        ]

        self.assertEqual([], validate_kit.experiment_journal_errors(rows, evaluation, None))
        evaluation.update(
            {
                "experiment_mode": "adaptive",
                "candidate_plan": "sequential",
                "adaptive_evolution": "observed",
            }
        )
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(any("parent_experiment_id" in error for error in errors), errors)
        self.assertTrue(any("hypothesis" in error for error in errors), errors)

    def test_adaptive_lineage_content_is_project_independent(self) -> None:
        # A fraud-flavoured adaptive journal: the generic validator requires the
        # lineage fields to exist without prescribing their content vocabulary.
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "auroc",
            "direction": "maximize",
            "minimum_meaningful_delta": None,
        }
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="auroc",
                selection_value="0.81",
                guardrail_status="not_applicable",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_01",
                candidate_identity="2" * 64,
                selection_metric="auroc",
                selection_value="0.83",
                guardrail_status="not_applicable",
                status="rejected",
                hypothesis="card-present routing features add lift",
                expected_mechanism="richer authorization context separates cohorts",
                change_summary="added merchant category aggregation",
                result_summary="+0.02 AUROC on grouped CV",
                next_hypothesis_rationale="test velocity windows next",
            ),
        ]
        self.assertEqual([], validate_kit.experiment_journal_errors(rows, evaluation, None))

    def test_identity_can_be_minimal_immutable_evidence(self) -> None:
        # A pipeline-oriented project: config + runner identity, no predictions.
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "custom_loss",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        row = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            config_hash="a" * 64,
            runner_hash="b" * 64,
            selection_metric="custom_loss",
            selection_value="0.42",
            guardrail_status="not_applicable",
            status="baseline",
        )
        self.assertEqual([], validate_kit.experiment_journal_errors([row], evaluation, None))

    def test_duplicate_detection_uses_content_identity_not_git_revision(self) -> None:
        rows = [
            {
                "experiment_id": "exp_01",
                "candidate_identity": "1" * 64,
                "code_revision": "abc123",
                "config_hash": "a" * 64,
                "prediction_hash": "b" * 64,
            }
        ]

        same_revision_new_config = {
            "candidate_identity": "2" * 64,
            "code_revision": "abc123",
            "config_hash": "c" * 64,
        }
        same_config = {
            "candidate_identity": "3" * 64,
            "code_revision": "def456",
            "config_hash": "a" * 64,
        }

        self.assertIsNone(validate_kit.duplicate_reason(rows, same_revision_new_config))
        self.assertEqual("config_hash", validate_kit.duplicate_reason(rows, same_config))

    def test_plateau_stopping_is_conservative_and_duplicate_aware(self) -> None:
        evaluation = self.evaluation_template()
        rows = [
            {
                "experiment_id": f"exp_{index:02d}",
                "status": "baseline" if index == 1 else "rejected",
                "meaningful_improvement": "true" if index == 2 else "false",
                "materially_new_evidence": "true" if index <= 2 else "false",
            }
            for index in range(1, 8)
        ]

        # Six valid NOVEL experiments (the baseline never counts toward the
        # minimum) are required before the conservative plateau rule applies.
        self.assertTrue(validate_kit.plateau_stop_recommended(rows, evaluation))
        self.assertFalse(validate_kit.plateau_stop_recommended(rows[:6], evaluation))

    def test_plateau_and_budget_exclude_the_baseline(self) -> None:
        evaluation = self.evaluation_template()
        rows = [
            {"experiment_id": "exp_01", "status": "baseline"},
            {"experiment_id": "exp_02", "status": "duplicate"},
            {"experiment_id": "exp_03", "status": "crashed"},
            {"experiment_id": "exp_04", "status": "invalid"},
            {"experiment_id": "exp_05", "status": "rejected"},
            {"experiment_id": "exp_06", "status": "promoted_to_holdout"},
            {"experiment_id": "exp_07", "status": "final_selected"},
        ]
        self.assertEqual(3, validate_kit.novel_experiment_count(rows))
        self.assertEqual(7, len(rows))
        # A plateau over the last four journal entries still contains a valid
        # novel experiment, so no stop is recommended.
        self.assertFalse(validate_kit.plateau_stop_recommended(rows, evaluation))

    # ------------------------------------------------------------------
    # Request -> contract reconstruction (bounded parsing layer)
    # ------------------------------------------------------------------

    def test_reconstruction_of_documented_selection_forms(self) -> None:
        for request in (
            "Selection metric: out-of-sample RMSE, minimize.",
            "Selection metric: OOS RMSE, minimize.",
        ):
            with self.subTest(request=request):
                draft = reconstruct_contract.reconstruct(request)
                self.assertEqual("rmse", draft["selection_objective"]["metric"])
                self.assertEqual("minimize", draft["selection_objective"]["direction"])
                self.assertEqual([], draft["unresolved_directions"])
                self.assertEqual([], draft["secondary_metrics"])

    def test_reconstruction_separates_qualifier_from_metric_identity(self) -> None:
        for request in (
            "Optimization: out-of-sample RMSE.",
            "Optimization should be done via out of sample RMSE.",
        ):
            with self.subTest(request=request):
                draft = reconstruct_contract.reconstruct(request)
                self.assertEqual("rmse", draft["selection_objective"]["metric"])
                self.assertIn("out of sample", draft["evaluation_qualifiers"])

    def test_reconstruction_without_explicit_direction_stays_unresolved(self) -> None:
        # "Optimization: cross-validated AUROC" — the generic helper may not
        # invent a direction for an unknown metric; it surfaces the gap.
        draft = reconstruct_contract.reconstruct(
            "Optimization: cross-validated AUROC."
        )
        self.assertEqual("auroc", draft["selection_objective"]["metric"])
        self.assertEqual("", draft["selection_objective"]["direction"])
        self.assertEqual(["auroc"], draft["unresolved_directions"])

    def test_reconstruction_uses_repository_metric_evidence(self) -> None:
        semantics = {
            "rmse": {"direction": "minimize"},
            "fa": {"direction": "maximize", "role": "reporting"},
        }
        draft = reconstruct_contract.reconstruct(
            "Run autoresearch. metric=FA with optimization via OOS RMSE.",
            semantics,
        )
        self.assertEqual("rmse", draft["selection_objective"]["metric"])
        self.assertEqual("minimize", draft["selection_objective"]["direction"])
        self.assertEqual(
            [
                {
                    "metric": "fa",
                    "role": "reporting",
                    "direction": "maximize",
                    "max_degradation": None,
                }
            ],
            draft["secondary_metrics"],
        )

    def test_reconstruction_handles_unpunctuated_metric_clause(self) -> None:
        draft = reconstruct_contract.reconstruct(
            "Run autoresearch.\nmetric=FA\noptimization should be done via out-of-sample RMSE, minimize.\n",
            {"fa": {"direction": "maximize"}},
        )
        self.assertEqual("rmse", draft["selection_objective"]["metric"])
        self.assertEqual("minimize", draft["selection_objective"]["direction"])
        self.assertEqual([{"metric": "fa", "role": "reporting", "direction": "maximize", "max_degradation": None}], draft["secondary_metrics"])

    def test_reconstruction_detects_conflicting_selection_directives(self) -> None:
        with self.assertRaises(ValueError):
            reconstruct_contract.reconstruct(
                "Selection metric: FA. Optimization should be done via RMSE."
            )

    def test_reconstruction_keeps_ambiguous_weak_mentions_unresolved(self) -> None:
        with self.assertRaises(ValueError):
            reconstruct_contract.reconstruct(
                "Run autoresearch.\nmetric=FA\nmetric=NDCG@10\n"
            )

    # ------------------------------------------------------------------
    # Subprocess-backed tooling: budgets, exposure, finalization
    # ------------------------------------------------------------------

    def build_project(self, root: Path) -> None:
        build = subprocess.run(
            [sys.executable, "-B", "tooling/build-overlay.py", "--output", str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, build.returncode, build.stdout + build.stderr)
        subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "synthetic@example.invalid"],
            check=True,
            timeout=60,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Synthetic Test"],
            check=True,
            timeout=60,
        )
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, timeout=60)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", "baseline"], check=True, timeout=60
        )

    def create_run(
        self, root: Path, run_id: str, max_experiments: int = 10, experiment_mode: str = "adaptive"
    ) -> None:
        create = subprocess.run(
            [
                sys.executable,
                "-B",
                str(root / ".agent-system" / "tooling" / "create-run.py"),
                "--project-root",
                str(root),
                "--autoresearch",
                "--id",
                run_id,
                "--goal",
                "Synthetic goal",
                "--acceptance",
                "Synthetic acceptance",
                "--request-kind",
                "optimization",
                "--skill",
                "autoresearch",
                "--mode",
                "autoresearch",
                "--experiment-mode",
                experiment_mode,
                "--max-experiments",
                str(max_experiments),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, create.returncode, create.stdout + create.stderr)

    def finalize(self, root: Path, run_id: str, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(root / ".agent-system" / "tooling" / "finalize-run.py"),
                run_id,
                "--project-root",
                str(root),
            ]
            + (extra or []),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def record(self, root: Path, run_id: str, candidate: dict[str, str]) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(candidate, handle)
            row_path = handle.name
        try:
            return subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tooling" / "record-experiment.py"),
                    run_id,
                    "--project-root",
                    str(root),
                    "--row-json",
                    row_path,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            Path(row_path).unlink(missing_ok=True)

    def reserve(self, root: Path, run_id: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tooling" / "record-experiment.py"),
                run_id,
                "--project-root",
                str(root),
                "--reserve-final-exposure",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def configure_finalizable_contract(
        self, root: Path, run_id: str, *, metric: str = "rmse", exposure: dict[str, Any] | None = None
    ) -> None:
        evaluation_path = root / ".agent-system" / "runs" / run_id / "evaluation.yaml"
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        evaluation["selection_objective"] = {
            "metric": metric,
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        evaluation["evaluation"]["final_split"] = "outer holdout"
        evaluation["evaluation"]["final_split_identity"] = exposure or {
            "split_id": "outer-1",
            "split_hash": "a" * 64,
            "dataset_hash": "b" * 64,
            "population_hash": "c" * 64,
            "exposure_status": "untouched",
        }
        evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")

    def prepare_finalizable_run(
        self, root: Path, run_id: str, *, stage: str = "development", metric: str = "rmse",
        research_decision: str = "reject",
    ) -> Path:
        run_dir = root / ".agent-system" / "runs" / run_id
        self.configure_finalizable_contract(run_dir.parent.parent.parent, run_id, metric=metric)
        if stage == "final":
            # The real protected lifecycle: baseline -> promoted frozen candidate ->
            # reserved exposure -> one final evaluation of that same candidate.
            self.assertEqual("accept", research_decision)
            reserved = self.reserve(root, run_id)
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            adaptive = {
                "hypothesis": "candidate",
                "expected_mechanism": "candidate",
                "change_summary": "candidate",
                "result_summary": "measured",
                "next_hypothesis_rationale": "continue",
            }
            rows = [
                journal_row(
                    experiment_id="exp_01",
                    candidate_identity="0" * 64,
                    config_hash="a" * 64,
                    selection_metric=metric,
                    selection_value="9.0",
                    guardrail_status="pass",
                    status="baseline",
                    hypothesis="baseline",
                    expected_mechanism="baseline",
                    change_summary="baseline",
                    result_summary="baseline measured",
                    next_hypothesis_rationale="continue",
                ),
                journal_row(
                    experiment_id="exp_02",
                    parent_experiment_id="exp_01",
                    stage="selection",
                    candidate_identity="1" * 64,
                    config_hash="d" * 64,
                    selection_metric=metric,
                    selection_value="8.0",
                    guardrail_status="pass",
                    status="promoted_to_holdout",
                    **adaptive,
                ),
                journal_row(
                    experiment_id="exp_03",
                    parent_experiment_id="exp_02",
                    stage="final",
                    candidate_identity="1" * 64,
                    config_hash="d" * 64,
                    prediction_hash="e" * 64,
                    selection_metric=metric,
                    selection_value="8.4",
                    guardrail_status="pass",
                    status="final_selected",
                    **{**adaptive, "next_hypothesis_rationale": "done"},
                ),
            ]
        else:
            rows = [
                journal_row(
                    experiment_id="exp_01",
                    stage=stage,
                    candidate_identity="1" * 64,
                    config_hash="d" * 64,
                    selection_metric=metric,
                    selection_value="8.0",
                    guardrail_status="pass",
                    status="baseline",
                    hypothesis="baseline",
                    expected_mechanism="baseline",
                    change_summary="baseline",
                    result_summary="baseline measured",
                    next_hypothesis_rationale="stop",
                )
            ]
        journal_buffer = io.StringIO()
        writer = csv.DictWriter(
            journal_buffer,
            fieldnames=validate_kit.EXPERIMENT_JOURNAL_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        (run_dir / "experiments.tsv").write_text(journal_buffer.getvalue(), encoding="utf-8")
        run_path = run_dir / "run.yaml"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        summary = run["results"]["experiment_summary"]
        # Canonical accounting: the protected final evaluation of the promoted
        # frozen candidate never consumes the novel experiment budget, so the
        # final-lifecycle journal counts exactly one novel research experiment.
        summary["experiments_run"] = validate_kit.novel_experiment_count(rows)
        summary["stopping_reason"] = "plateau"
        summary["lifecycle"]["research_decision"] = research_decision
        if research_decision == "accept":
            summary["selected_experiment"] = {
                "experiment_id": rows[-1]["experiment_id"],
                "candidate_identity": rows[-1]["candidate_identity"],
            }
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        learning_path = run_dir / "learning.yaml"
        learning = json.loads(learning_path.read_text(encoding="utf-8"))
        learning["no_reusable_signal_reason"] = "No reusable signal from the synthetic run."
        learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
        return run_dir

    def test_record_experiment_marks_duplicate_config_before_budget_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / ".agent-system" / "runs" / "duplicate-run"
            run_dir.mkdir(parents=True)
            (run_dir / "evaluation.yaml").write_text(
                json.dumps(
                    {
                        **self.evaluation_template(),
                        "selection_objective": {
                            "metric": "RMSE",
                            "direction": "minimize",
                            "minimum_meaningful_delta": None,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "experiments.tsv").write_text(
                "\t".join(validate_kit.EXPERIMENT_JOURNAL_FIELDS) + "\n",
                encoding="utf-8",
            )
            base_row = journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                selection_metric="RMSE",
                guardrail_status="unverified",
                status="baseline",
                hypothesis="baseline",
                expected_mechanism="baseline",
                change_summary="baseline",
                result_summary="pending",
                next_hypothesis_rationale="continue",
            )
            rows = [base_row, {**base_row, "experiment_id": "exp_02", "candidate_identity": "2" * 64}]
            for index, row in enumerate(rows):
                row_path = root / f"row-{index}.json"
                row_path.write_text(json.dumps(row), encoding="utf-8")
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(ROOT / "tooling" / "record-experiment.py"),
                        "duplicate-run",
                        "--project-root",
                        str(root),
                        "--row-json",
                        str(row_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            recorded, errors = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("baseline", recorded[0]["status"])
            self.assertEqual("duplicate", recorded[1]["status"])

    def minimal_run_environment(self, root: Path, run_id: str, budget: int) -> Path:
        """Run directory with run.yaml/evaluation.yaml/journal but no full overlay."""
        run_dir = root / ".agent-system" / "runs" / run_id
        run_dir.mkdir(parents=True)
        evaluation = {
            **self.evaluation_template(),
            "selection_objective": {
                "metric": "rmse",
                "direction": "minimize",
                "minimum_meaningful_delta": None,
            },
        }
        (run_dir / "evaluation.yaml").write_text(
            json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
        )
        (run_dir / "experiments.tsv").write_text(
            "\t".join(validate_kit.EXPERIMENT_JOURNAL_FIELDS) + "\n", encoding="utf-8"
        )
        run = {
            "schema_version": "0.2",
            "results": {
                "experiment_summary": {
                    "format_version": "0.2",
                    "budget": budget,
                    "experiments_run": 0,
                    "stopping_reason": "not_started",
                    "journal_ref": "experiments.tsv",
                    "evaluation_ref": "evaluation.yaml",
                    "selected_experiment": None,
                    "candidate_learning_events": [],
                    "lifecycle": {
                        "research_decision": "pending",
                        "evidence_status": "open",
                        "independent_validation_status": "not_requested",
                        "candidate_branch_status": "local",
                        "production_integration_status": "not_started",
                    },
                }
            },
        }
        (run_dir / "run.yaml").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        return run_dir

    def test_experiment_budget_is_a_hard_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = self.minimal_run_environment(root, "budget-run", budget=1)
            baseline = journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="unverified",
                status="baseline",
                hypothesis="baseline",
                expected_mechanism="baseline",
                change_summary="baseline",
                result_summary="measured",
                next_hypothesis_rationale="continue",
            )
            # Canonical accounting: the baseline establishes the reference and
            # does NOT consume the novel experiment budget. budget=1 leaves
            # room for exactly one novel research experiment after it.
            baseline_result = self.record(root, "budget-run", baseline)
            self.assertEqual(0, baseline_result.returncode, baseline_result.stdout + baseline_result.stderr)
            self.assertNotIn("BUDGET_EXHAUSTED", baseline_result.stdout)
            run = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(0, run["results"]["experiment_summary"]["experiments_run"])

            novel_a = {
                **baseline,
                "experiment_id": "exp_02",
                "parent_experiment_id": "exp_01",
                "candidate_identity": "2" * 64,
                "config_hash": "b" * 64,
                "status": "rejected",
                "hypothesis": "novel A",
                "expected_mechanism": "novel A",
                "change_summary": "novel A",
                "result_summary": "novel A measured",
                "next_hypothesis_rationale": "continue",
            }
            novel_result = self.record(root, "budget-run", novel_a)
            self.assertEqual(0, novel_result.returncode, novel_result.stdout + novel_result.stderr)
            self.assertIn("BUDGET_EXHAUSTED", novel_result.stdout)
            run = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(1, run["results"]["experiment_summary"]["experiments_run"])

            novel_b = {
                **novel_a,
                "experiment_id": "exp_03",
                "parent_experiment_id": "exp_02",
                "candidate_identity": "3" * 64,
                "config_hash": "c" * 64,
            }
            rejected = self.record(root, "budget-run", novel_b)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("budget exhausted", rejected.stdout)
            rows, errors = validate_kit.read_experiment_journal(run_dir / "experiments.tsv", root)
            self.assertEqual([], errors)
            self.assertEqual(2, len(rows))
            run = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(1, run["results"]["experiment_summary"]["experiments_run"])

            duplicate_a = {**novel_a, "experiment_id": "exp_04", "candidate_identity": "4" * 64}
            dup_result = self.record(root, "budget-run", duplicate_a)
            self.assertEqual(0, dup_result.returncode, dup_result.stdout + dup_result.stderr)
            self.assertIn("budget unchanged", dup_result.stdout)
            rows, _ = validate_kit.read_experiment_journal(run_dir / "experiments.tsv", root)
            self.assertEqual("duplicate", rows[-1]["status"])
            run = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(1, run["results"]["experiment_summary"]["experiments_run"])

    def write_journal(self, run_dir: Path, rows: list[dict[str, str]]) -> None:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=validate_kit.EXPERIMENT_JOURNAL_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        (run_dir / "experiments.tsv").write_text(buffer.getvalue(), encoding="utf-8")

    def test_run_over_budget_fails_current_format_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / ".agent-system" / "runs" / "over-budget"
            run_dir.mkdir(parents=True)
            (run_dir / "learning.yaml").write_text("{}\n", encoding="utf-8")
            evaluation = self.evaluation_template()
            evaluation["experiment_mode"] = "benchmark"
            evaluation["candidate_plan"] = "predeclared"
            evaluation["adaptive_evolution"] = "not_applicable"
            evaluation["selection_objective"] = {
                "metric": "rmse",
                "direction": "minimize",
                "minimum_meaningful_delta": None,
            }
            (run_dir / "evaluation.yaml").write_text(
                json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
            )
            self.write_journal(
                run_dir,
                [
                    journal_row(
                        experiment_id="exp_01",
                        candidate_identity="1" * 64,
                        config_hash="a" * 64,
                        selection_metric="rmse",
                        selection_value="9.0",
                        guardrail_status="not_applicable",
                        status="baseline",
                    ),
                    journal_row(
                        experiment_id="exp_02",
                        candidate_identity="2" * 64,
                        config_hash="b" * 64,
                        selection_metric="rmse",
                        selection_value="8.0",
                        guardrail_status="not_applicable",
                        status="rejected",
                    ),
                    journal_row(
                        experiment_id="exp_03",
                        candidate_identity="3" * 64,
                        config_hash="c" * 64,
                        selection_metric="rmse",
                        selection_value="7.5",
                        guardrail_status="not_applicable",
                        status="promoted_to_holdout",
                    ),
                ],
            )
            errors = validate_kit.autoresearch_evidence_errors(
                {
                    "schema_version": "0.2",
                    "results": {
                        "experiment_summary": {
                            "format_version": "0.2",
                            "budget": 1,
                            "experiments_run": 2,
                            "stopping_reason": "plateau",
                            "journal_ref": "experiments.tsv",
                            "evaluation_ref": "evaluation.yaml",
                        }
                    },
                },
                run_dir / "run.yaml",
                root,
            )
            self.assertTrue(
                any("exceeds the hard experiment budget" in error for error in errors), errors
            )

    def test_run_schema_v02_requires_experiment_summary(self) -> None:
        errors = validate_kit.autoresearch_evidence_errors(
            {"schema_version": "0.2", "results": {}},
            Path("x"),
            Path("."),
        )
        self.assertTrue(any("requires results.experiment_summary" in error for error in errors), errors)

    def test_protected_exposure_is_reserved_before_final_result_can_be_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "exposed-run")
            self.configure_finalizable_contract(root, "exposed-run")
            baseline = journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="baseline",
                hypothesis="baseline",
                expected_mechanism="baseline",
                change_summary="baseline",
                result_summary="baseline measured",
                next_hypothesis_rationale="continue",
            )
            promoted = {
                **baseline,
                "experiment_id": "exp_02",
                "parent_experiment_id": "exp_01",
                "stage": "selection",
                "candidate_identity": "f" * 64,
                "config_hash": "d" * 64,
                "selection_value": "8.0",
                "status": "promoted_to_holdout",
                "result_summary": "promoted after selection",
                "next_hypothesis_rationale": "freeze for final",
            }
            final_row = {
                **promoted,
                "experiment_id": "exp_03",
                "parent_experiment_id": "exp_02",
                "stage": "final",
                "status": "final_selected",
                "prediction_hash": "e" * 64,
                "selection_value": "8.4",
                "result_summary": "final protected estimate",
                "next_hypothesis_rationale": "done",
            }
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"

            for row in (baseline, promoted):
                recorded = self.record(root, "exposed-run", row)
                self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)

            # Exposure-before-observation is mechanically enforced: a stage-final
            # result is refused until this run's reservation is committed.
            premature = self.record(root, "exposed-run", final_row)
            self.assertNotEqual(0, premature.returncode)
            self.assertIn("exposure reservation", premature.stdout)
            self.assertFalse(ledger.exists())

            reserved = self.reserve(root, "exposed-run")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            self.assertIn("RESERVED", reserved.stdout)
            self.assertTrue(ledger.is_file(), "exposure must be committed before any result")
            lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(lines))
            self.assertEqual("exposed-run", lines[0]["run_id"])
            self.assertEqual("final", lines[0]["role"])

            # Retrying the same reservation is idempotent: no duplicate event,
            # no false additional exposure count.
            retry_reserve = self.reserve(root, "exposed-run")
            self.assertEqual(0, retry_reserve.returncode, retry_reserve.stdout)
            self.assertIn("ALREADY_RESERVED", retry_reserve.stdout)
            lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(lines), "retried reservation must not duplicate the event")

            # The promoted frozen candidate is legitimately evaluated on the
            # reserved protected population: same candidate_identity and
            # config_hash as the promoted row, new population-specific
            # predictions — not a duplicate research experiment.
            recorded = self.record(root, "exposed-run", final_row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn("protected final evaluation of the promoted frozen candidate", recorded.stdout)
            self.assertNotIn("BUDGET_EXHAUSTED", recorded.stdout)
            rows, errors = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "exposed-run" / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("final_selected", rows[-1]["status"])
            self.assertEqual(rows[-1]["candidate_identity"], rows[1]["candidate_identity"])
            lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(lines), "recording the reserved result must not add events")
            summary = json.loads(
                (root / ".agent-system" / "runs" / "exposed-run" / "run.yaml").read_text(
                    encoding="utf-8"
                )
            )["results"]["experiment_summary"]
            self.assertEqual(1, summary["experiments_run"], "final evaluation consumed no budget")

            # A second query against the protected population with the SAME
            # frozen candidate is downgraded to a duplicate: the first final
            # evaluation already consumed that role, and it still spends no
            # research budget.
            second_final = {
                **final_row,
                "experiment_id": "exp_04",
                "result_summary": "repeated protected query",
                "next_hypothesis_rationale": "stop",
            }
            repeated = self.record(root, "exposed-run", second_final)
            self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
            self.assertIn("duplicate", repeated.stdout)
            rows, _ = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "exposed-run" / "experiments.tsv", root
            )
            self.assertEqual("duplicate", rows[-1]["status"])
            evaluated_final = [
                row
                for row in rows
                if row["stage"] == "final" and row["status"] in validate_kit.EVALUATED_STATUSES
            ]
            self.assertEqual(1, len(evaluated_final), "one-shot final evidence is preserved")

    def test_stage_final_duplicate_cannot_bypass_reservation(self) -> None:
        # A stage-'final' submission whose config duplicates an earlier
        # development row would be coerced to 'duplicate' and would add no
        # evaluated final evidence — but running it against the protected
        # split still exposes that split, so the reservation is required.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "dup-bypass")
            self.configure_finalizable_contract(root, "dup-bypass")
            baseline = journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="d" * 64,
                selection_metric="rmse",
                selection_value="8.0",
                guardrail_status="not_applicable",
                status="baseline",
            )
            recorded = self.record(root, "dup-bypass", baseline)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            bypass = self.record(
                root,
                "dup-bypass",
                {**baseline, "experiment_id": "exp_02", "candidate_identity": "2" * 64, "stage": "final"},
            )
            self.assertNotEqual(0, bypass.returncode)
            self.assertIn("exposure reservation", bypass.stdout)
            reserved = self.reserve(root, "dup-bypass")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            recorded = self.record(
                root,
                "dup-bypass",
                {**baseline, "experiment_id": "exp_02", "candidate_identity": "2" * 64, "stage": "final"},
            )
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn("duplicate", recorded.stdout)

    def test_interrupted_run_still_blocks_reuse_of_protected_population(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "run-a")
            self.configure_finalizable_contract(root, "run-a")
            reserved = self.reserve(root, "run-a")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            # Run A crashes after the reservation and before any result or
            # journal row exists. The split is already committed as burned.
            run_dir_a = root / ".agent-system" / "runs" / "run-a"
            self.assertEqual(
                0,
                len(validate_kit.read_experiment_journal(run_dir_a / "experiments.tsv", root)[0]),
            )
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            self.assertEqual(1, len(ledger.read_text(encoding="utf-8").strip().splitlines()))

            # Run B references the same protected split population.
            self.create_run(root, "run-b")
            self.configure_finalizable_contract(root, "run-b")
            reuse_reserve = self.reserve(root, "run-b")
            self.assertNotEqual(0, reuse_reserve.returncode)
            self.assertIn("previously exposed", reuse_reserve.stdout)
            final_row_b = journal_row(
                experiment_id="exp_01",
                stage="final",
                candidate_identity="1" * 64,
                config_hash="d" * 64,
                selection_metric="rmse",
                selection_value="8.0",
                guardrail_status="pass",
                status="baseline",
            )
            reuse = self.record(root, "run-b", final_row_b)
            self.assertNotEqual(0, reuse.returncode)
            self.assertIn("previously exposed", reuse.stdout)
            prepared = self.prepare_finalizable_run(root, "run-b", stage="development")
            finalize_b = self.finalize(root, "run-b")
            self.assertNotEqual(0, finalize_b.returncode, finalize_b.stdout)
            self.assertIn("previously exposed", finalize_b.stdout)
            run_b = json.loads((prepared / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                "open", run_b["results"]["experiment_summary"]["lifecycle"]["evidence_status"]
            )
            # Cross-run reuse stays visible in the ledger: the failing part is
            # the false untouched claim, never the record of the burn itself.
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(events))
            self.assertEqual("run-a", events[0]["run_id"])

    def test_development_run_does_not_fabricate_final_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "dev-only")
            self.prepare_finalizable_run(root, "dev-only", stage="development")
            finalize = self.finalize(root, "dev-only")
            self.assertEqual(0, finalize.returncode, finalize.stdout + finalize.stderr)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            self.assertFalse(
                ledger.exists() and ledger.read_text(encoding="utf-8").strip(),
                "finalize must not create a final-exposure event for an unexecuted final split",
            )

    # ------------------------------------------------------------------
    # Selection -> protected final lifecycle: identity is candidate + context
    # ------------------------------------------------------------------

    def lifecycle_rows(self, metric: str = "rmse") -> tuple[dict[str, str], ...]:
        baseline = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            config_hash="a" * 64,
            selection_metric=metric,
            selection_value="9.0",
            guardrail_status="not_applicable",
            status="baseline",
            hypothesis="baseline",
            expected_mechanism="baseline",
            change_summary="baseline",
            result_summary="baseline measured",
            next_hypothesis_rationale="continue",
        )
        first = {
            **baseline,
            "experiment_id": "exp_02",
            "parent_experiment_id": "exp_01",
            "candidate_identity": "2" * 64,
            "config_hash": "b" * 64,
            "selection_value": "8.5",
            "status": "rejected",
            "hypothesis": "novel A",
            "expected_mechanism": "mechanism A",
            "change_summary": "change A",
            "result_summary": "A measured",
            "next_hypothesis_rationale": "continue",
        }
        promoted = {
            **first,
            "experiment_id": "exp_03",
            "parent_experiment_id": "exp_02",
            "stage": "selection",
            "candidate_identity": "3" * 64,
            "config_hash": "c" * 64,
            "selection_value": "8.0",
            "status": "promoted_to_holdout",
            "hypothesis": "novel B",
            "expected_mechanism": "mechanism B",
            "change_summary": "change B",
            "result_summary": "B selected and promoted",
            "next_hypothesis_rationale": "freeze B for the reserved final evaluation",
        }
        final_row = {
            **promoted,
            "experiment_id": "exp_04",
            "parent_experiment_id": "exp_03",
            "stage": "final",
            "status": "final_selected",
            "prediction_hash": "e" * 64,
            "selection_value": "8.2",
            "result_summary": "final protected estimate of frozen candidate B",
            "next_hypothesis_rationale": "done",
        }
        return baseline, first, promoted, final_row

    def prepare_final_cli_run(self, root: Path, run_id: str, metric: str = "rmse") -> dict[str, str]:
        """Record baseline -> development -> promotion through the real CLI."""
        self.configure_finalizable_contract(root, run_id, metric=metric)
        rows = self.lifecycle_rows(metric)
        for row in rows[:3]:
            recorded = self.record(root, run_id, row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
        return rows[3]

    def test_duplicate_identity_is_candidate_plus_evaluation_context(self) -> None:
        # Same candidate in the same evaluation context: duplicate, always.
        _, first, promoted, final_row = self.lifecycle_rows()
        rows = [first, promoted]
        same_context_rerun = {**promoted, "experiment_id": "exp_09"}
        self.assertEqual(
            "candidate_identity", validate_kit.duplicate_reason(rows, same_context_rerun)
        )
        # Same frozen candidate promoted to the reserved protected final role:
        # a legitimate evaluation-context change, not a duplicate experiment.
        self.assertTrue(validate_kit.is_promoted_protected_final_reuse(rows, final_row))
        self.assertIsNone(validate_kit.duplicate_reason(rows, final_row))
        self.assertIsNotNone(validate_kit.promoted_frozen_anchor(rows, final_row))
        # The reuse exception is anchored, not a stage label escape hatch: an
        # unrelated candidate relabeled 'final' has no promoted anchor, so
        # record-experiment rejects it even though duplicate_reason stays quiet.
        smuggled = {**final_row, "candidate_identity": "7" * 64, "config_hash": "7" * 64}
        self.assertIsNone(validate_kit.duplicate_reason(rows, smuggled))
        self.assertIsNone(validate_kit.promoted_frozen_anchor(rows, smuggled))
        # A frozen candidate whose provenance mutated is never the promoted
        # candidate again.
        mutated = {**final_row, "config_hash": "9" * 64}
        self.assertIsNone(validate_kit.promoted_frozen_anchor(rows, mutated))
        # A second query is not a legitimate reuse: the first evaluated final
        # row already carries the repeated identity.
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(
                rows + [final_row], {**final_row, "experiment_id": "exp_10"}
            )
        )
        # Copied development predictions are evidence of a re-run, not a new
        # population evaluation.
        copied_predictions = {**final_row, "prediction_hash": first["prediction_hash"] or "0" * 64}
        with_pred = [{**first, "prediction_hash": "0" * 64}, promoted]
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(with_pred, copied_predictions)
        )
        # A mis-submitted repeat that was downgraded to `duplicate` or recorded
        # as `crashed`/`invalid` claimed no scientific evidence and therefore
        # does not consume the frozen candidate's protected-final role.
        for no_evidence_status in ("duplicate", "crashed", "invalid"):
            noise = [promoted, {**promoted, "experiment_id": f"exp_11_{no_evidence_status}",
                                "status": no_evidence_status}]
            self.assertTrue(
                validate_kit.is_promoted_protected_final_reuse(noise, final_row),
                no_evidence_status,
            )

    def test_final_reuse_authorization_is_independent_of_outcome(self) -> None:
        # Authorized protected-final reuse is decided by mechanics, never by
        # whether the final outcome is positive: any supported final outcome
        # status of the anchored frozen candidate keeps its real evidence role.
        _, first, promoted, final_row = self.lifecycle_rows()
        rows = [first, promoted]
        for outcome in validate_kit.PROTECTED_FINAL_OUTCOME_STATUSES:
            self.assertTrue(
                validate_kit.is_promoted_protected_final_reuse(
                    rows, {**final_row, "status": outcome}
                ),
                outcome,
            )
            self.assertIsNone(
                validate_kit.duplicate_reason(rows, {**final_row, "status": outcome}),
                outcome,
            )
        # Statuses that claim no final outcome never play the protected role.
        for claimed in ("duplicate", "baseline", "promoted_to_holdout", ""):
            self.assertFalse(
                validate_kit.is_promoted_protected_final_reuse(
                    rows, {**final_row, "status": claimed}
                ),
                claimed,
            )
        # A negative outcome is not an identity wildcard: mutated provenance,
        # an unanchored candidate, or a consumed protected-final role remain
        # duplicates under the same mechanics as a positive outcome.
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(
                rows, {**final_row, "status": "rejected", "config_hash": "9" * 64}
            )
        )
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(
                rows,
                {**final_row, "status": "rejected", "candidate_identity": "7" * 64,
                 "config_hash": "7" * 64},
            )
        )
        consumed = rows + [{**final_row, "status": "rejected"}]
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(
                consumed, {**final_row, "experiment_id": "exp_12", "status": "final_selected"}
            )
        )
        self.assertFalse(
            validate_kit.is_promoted_protected_final_reuse(
                rows + [final_row], {**final_row, "experiment_id": "exp_13", "status": "rejected"}
            )
        )
        # Ordinary repetition is untouched by the fix: same candidate in the
        # same context is a duplicate whatever the submitted status says.
        self.assertEqual(
            "candidate_identity",
            validate_kit.duplicate_reason(rows, {**promoted, "experiment_id": "exp_14"}),
        )
        self.assertEqual(
            "candidate_identity",
            validate_kit.duplicate_reason(
                rows, {**final_row, "status": "rejected", "stage": "development"}
            ),
        )

    def test_unanchored_final_evaluation_is_rejected(self) -> None:
        # Stage relabeling must not turn the protected population into a new
        # search loop: a final row without a promoted frozen candidate behind
        # it is refused mechanically, with or without a reservation.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "unanchored")
            self.configure_finalizable_contract(root, "unanchored")
            _, first, promoted, final_row = self.lifecycle_rows()
            smuggled = {**final_row, "candidate_identity": "7" * 64, "config_hash": "7" * 64}
            rejected = self.record(root, "unanchored", smuggled)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("exposure reservation", rejected.stdout)
            reserved = self.reserve(root, "unanchored")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            rejected = self.record(root, "unanchored", smuggled)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("must re-evaluate the previously promoted frozen candidate", rejected.stdout)
            # Even with the correct identity, promotion evidence must exist:
            rejected = self.record(root, "unanchored", final_row)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("must re-evaluate the previously promoted frozen candidate", rejected.stdout)

    def test_final_identity_mutated_after_promotion_never_becomes_final_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "mutated")
            final_row = self.prepare_final_cli_run(root, "mutated")
            reserved = self.reserve(root, "mutated")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            mutated = {**final_row, "config_hash": "9" * 64}
            result = self.record(root, "mutated", mutated)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("duplicate", result.stdout)
            rows, errors = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "mutated" / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("duplicate", rows[-1]["status"])
            evaluated_final = [
                row
                for row in rows
                if row["stage"] == "final" and row["status"] in validate_kit.EVALUATED_STATUSES
            ]
            self.assertEqual(0, len(evaluated_final))

    def test_final_evaluation_never_consumes_the_novel_experiment_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            run_dir = root / ".agent-system" / "runs" / "budget-final"
            self.create_run(root, "budget-final")
            final_row = self.prepare_final_cli_run(root, "budget-final")
            run_path = run_dir / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            # Two research candidates were novel (exp_02, exp_03): set the
            # ceiling exactly at exhaustion before the protected evaluation.
            run["results"]["experiment_summary"]["budget"] = 2
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            reserved = self.reserve(root, "budget-final")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            # Budget is exhausted by the promoted research candidate; the
            # protected final evaluation of that same candidate still records.
            recorded = self.record(root, "budget-final", final_row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn("novel experiment budget unchanged", recorded.stdout)
            summary = json.loads(run_path.read_text(encoding="utf-8"))["results"]["experiment_summary"]
            self.assertEqual(2, summary["experiments_run"], "the final evaluation added no consumption")
            # A budget-consuming research candidate remains rejected afterwards.
            novel = {
                **final_row,
                "experiment_id": "exp_05",
                "stage": "development",
                "candidate_identity": "8" * 64,
                "config_hash": "8" * 64,
                "prediction_hash": "",
                "status": "rejected",
                "result_summary": "late research idea",
            }
            rejected = self.record(root, "budget-final", novel)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("budget exhausted", rejected.stdout)

    def test_negative_final_outcome_is_preserved_protected_evidence(self) -> None:
        # The promoted frozen candidate evaluated on the reserved protected
        # population keeps its REAL negative outcome: it is authorized
        # protected-final reuse, not a duplicate of the selection row, and it
        # still consumes zero novel-experiment budget even with the ceiling
        # already reached.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "negfinal")
            run_dir = root / ".agent-system" / "runs" / "negfinal"
            run_path = run_dir / "run.yaml"
            final_row = self.prepare_final_cli_run(root, "negfinal")
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["results"]["experiment_summary"]["budget"] = 2
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            reserved = self.reserve(root, "negfinal")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)

            negative = {
                **final_row,
                "status": "rejected",
                "selection_value": "9.5",
                "result_summary": "protected evidence: candidate fails the acceptance bar",
            }
            recorded = self.record(root, "negfinal", negative)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn(
                "protected final evaluation of the promoted frozen candidate", recorded.stdout
            )
            self.assertNotIn("duplicate", recorded.stdout)
            self.assertNotIn("BUDGET_EXHAUSTED", recorded.stdout)
            rows, errors = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("rejected", rows[-1]["status"])
            self.assertEqual(rows[2]["candidate_identity"], rows[-1]["candidate_identity"])
            self.assertEqual(rows[2]["config_hash"], rows[-1]["config_hash"])
            summary = json.loads(run_path.read_text(encoding="utf-8"))["results"][
                "experiment_summary"
            ]
            self.assertEqual(2, summary["experiments_run"],
                             "negative final outcome consumed no novel budget")

            # One-shot semantics do not depend on the outcome being positive:
            # a second query against the consumed protected population is
            # still downgraded to a duplicate.
            second = {
                **negative,
                "experiment_id": "exp_05",
                "status": "final_selected",
                "result_summary": "retry hoping for a better number",
            }
            repeat = self.record(root, "negfinal", second)
            self.assertEqual(0, repeat.returncode, repeat.stdout + repeat.stderr)
            self.assertIn("duplicate", repeat.stdout)
            rows, _ = validate_kit.read_experiment_journal(run_dir / "experiments.tsv", root)
            self.assertEqual("duplicate", rows[-1]["status"])
            evaluated_final = [
                row
                for row in rows
                if row["stage"] == "final"
                and row["status"] in validate_kit.EVALUATED_STATUSES
            ]
            self.assertEqual(1, len(evaluated_final))

            # Budget-consuming research candidates remain rejected afterwards.
            novel = {
                **negative,
                "experiment_id": "exp_06",
                "stage": "development",
                "candidate_identity": "8" * 64,
                "config_hash": "8" * 64,
                "prediction_hash": "",
                "result_summary": "late research idea",
            }
            blocked = self.record(root, "negfinal", novel)
            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("budget exhausted", blocked.stdout)

    def test_guardrail_failed_final_outcome_is_preserved(self) -> None:
        # A mechanically detected guardrail violation on the protected final
        # evaluation is a supported negative final outcome: rejected +
        # guardrail_status='fail' must survive as final evidence, never be
        # rewritten to duplicate.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "guardrail-final")
            self.configure_finalizable_contract(root, "guardrail-final")
            evaluation_path = (
                root / ".agent-system" / "runs" / "guardrail-final" / "evaluation.yaml"
            )
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            evaluation["secondary_metrics"] = [
                {
                    "metric": "latency_ms",
                    "role": "guardrail",
                    "direction": "minimize",
                    "max_degradation": 5.0,
                }
            ]
            evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
            rationale = {
                "hypothesis": "candidate",
                "expected_mechanism": "candidate",
                "change_summary": "candidate",
                "result_summary": "measured",
                "next_hypothesis_rationale": "continue",
            }
            baseline = journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                metrics_json=json.dumps({"rmse": 9.0, "latency_ms": 100.0}),
                guardrail_status="pass",
                status="baseline",
                hypothesis="baseline",
                expected_mechanism="baseline",
                change_summary="baseline",
                result_summary="baseline measured",
                next_hypothesis_rationale="continue",
            )
            promoted = {
                **baseline,
                **rationale,
                "experiment_id": "exp_02",
                "parent_experiment_id": "exp_01",
                "stage": "selection",
                "candidate_identity": "3" * 64,
                "config_hash": "c" * 64,
                "selection_value": "8.0",
                "metrics_json": json.dumps({"rmse": 8.0, "latency_ms": 102.0}),
                "status": "promoted_to_holdout",
            }
            for row in (baseline, promoted):
                recorded = self.record(root, "guardrail-final", row)
                self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            reserved = self.reserve(root, "guardrail-final")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)

            final_row = {
                **promoted,
                "experiment_id": "exp_03",
                "parent_experiment_id": "exp_02",
                "stage": "final",
                "status": "rejected",
                "guardrail_status": "fail",
                "prediction_hash": "e" * 64,
                "selection_value": "8.1",
                "metrics_json": json.dumps({"rmse": 8.1, "latency_ms": 120.0}),
                "result_summary": "guardrail breaches the declared ceiling on the protected split",
                "next_hypothesis_rationale": "done",
            }
            recorded = self.record(root, "guardrail-final", final_row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn(
                "protected final evaluation of the promoted frozen candidate", recorded.stdout
            )
            self.assertNotIn("duplicate", recorded.stdout)
            rows, errors = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "guardrail-final" / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("rejected", rows[-1]["status"])
            self.assertEqual("fail", rows[-1]["guardrail_status"])
            summary = json.loads(
                (root / ".agent-system" / "runs" / "guardrail-final" / "run.yaml").read_text(
                    encoding="utf-8"
                )
            )["results"]["experiment_summary"]
            self.assertEqual(1, summary["experiments_run"])
            self.assertEqual([], summary["candidate_learning_events"])

    def test_journal_validation_rejects_final_row_without_promoted_anchor(self) -> None:
        # Defense in depth for hand-edited journals: finalize-level validation
        # requires the same mechanical anchor the CLI enforces at record time.
        evaluation = self.evaluation_template()
        evaluation["selection_objective"] = {
            "metric": "rmse",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        _, first, promoted, final_row = self.lifecycle_rows()
        evaluation["experiment_mode"] = "benchmark"
        evaluation["candidate_plan"] = "predeclared"
        evaluation["adaptive_evolution"] = "not_applicable"
        anchored = validate_kit.experiment_journal_errors(
            [{**first, "stage": "development"}, promoted, final_row], evaluation, None
        )
        self.assertEqual([], [error for error in anchored if "promoted frozen" in error], anchored)
        orphan = validate_kit.experiment_journal_errors(
            [{**first, "stage": "development"}, final_row], evaluation, None
        )
        self.assertTrue(
            any("promoted frozen candidate" in error for error in orphan), orphan
        )

    def test_ledger_ordering_authorizes_the_first_reservation(self) -> None:
        # Run A reserves the previously untouched split first. Run B may then
        # reuse it honestly as previously_exposed, but that later exposure
        # must not retroactively invalidate A's already-authorized one-shot
        # final evaluation — and A's finalize stays valid on the untouched
        # claim established at A's reservation position.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "run-a")
            self.configure_finalizable_contract(root, "run-a")
            first = self.reserve(root, "run-a")
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertIn("RESERVED", first.stdout)

            self.create_run(root, "run-b")
            self.configure_finalizable_contract(
                root,
                "run-b",
                exposure={
                    "split_id": "outer-1",
                    "split_hash": "a" * 64,
                    "dataset_hash": "b" * 64,
                    "population_hash": "c" * 64,
                    "exposure_status": "previously_exposed",
                },
            )
            second = self.reserve(root, "run-b")
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(["run-a", "run-b"], [event["run_id"] for event in events])

            # Retrying A's reservation stays idempotent after B's event.
            retry = self.reserve(root, "run-a")
            self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
            self.assertIn("ALREADY_RESERVED", retry.stdout)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events))

            # A records its legitimate lifecycle and authorized result.
            final_row = self.prepare_final_cli_run(root, "run-a")
            recorded = self.record(root, "run-a", final_row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertIn("final evaluation", recorded.stdout)

            # A second protected-final query by A is downgraded, never new evidence.
            repeat = {**final_row, "experiment_id": "exp_05", "result_summary": "again"}
            second_query = self.record(root, "run-a", repeat)
            self.assertEqual(0, second_query.returncode, second_query.stdout + second_query.stderr)
            self.assertIn("duplicate", second_query.stdout)

            # A finalizes: its untouched claim is judged against its own
            # reservation position, not against B's later event.
            run_path = root / ".agent-system" / "runs" / "run-a" / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            summary = run["results"]["experiment_summary"]
            summary["stopping_reason"] = "budget"
            summary["lifecycle"]["research_decision"] = "accept"
            summary["selected_experiment"] = {
                "experiment_id": "exp_04",
                "candidate_identity": "3" * 64,
            }
            rows, _ = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "run-a" / "experiments.tsv", root
            )
            self.assertEqual("exp_04", rows[3]["experiment_id"])
            self.assertEqual("final_selected", rows[3]["status"])
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            learning_path = root / ".agent-system" / "runs" / "run-a" / "learning.yaml"
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            learning["no_reusable_signal_reason"] = "Synthetic ordering scenario."
            learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
            finalized = self.finalize(root, "run-a")
            self.assertEqual(0, finalized.returncode, finalized.stdout + finalized.stderr)

    def test_run_without_own_reservation_still_sees_prior_exposure(self) -> None:
        # B never reserved first: any other run's committed exposure precedes
        # everything B could claim, so B cannot reserve or record untouched
        # one-shot evidence.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "run-first")
            self.configure_finalizable_contract(root, "run-first")
            self.assertEqual(0, self.reserve(root, "run-first").returncode)
            self.create_run(root, "run-late")
            self.configure_finalizable_contract(root, "run-late")
            late_reserve = self.reserve(root, "run-late")
            self.assertNotEqual(0, late_reserve.returncode)
            self.assertIn("previously exposed by run-first", late_reserve.stdout)

    # ------------------------------------------------------------------
    # Protected-exposure ledger: concurrency and durable commit
    # ------------------------------------------------------------------

    def overlay_reserve_command(self, root: Path, run_id: str) -> list[str]:
        """Reserve exposure through the BUILT overlay tooling, not the source copy."""
        return [
            sys.executable,
            "-B",
            str(root / ".agent-system" / "tooling" / "record-experiment.py"),
            run_id,
            "--project-root",
            str(root),
            "--reserve-final-exposure",
        ]

    def launch_overlay_reserves(
        self, root: Path, run_ids: list[str]
    ) -> list[tuple[str, int, str]]:
        """Launch every reservation concurrently, then collect each command's result."""
        handles = [
            subprocess.Popen(
                self.overlay_reserve_command(root, run_id),
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for run_id in run_ids
        ]
        results = []
        for run_id, handle in zip(run_ids, handles):
            stdout, stderr = handle.communicate(timeout=120)
            results.append((run_id, handle.returncode, stdout + stderr))
        return results

    def validated_ledger_events(self, root: Path) -> list[dict[str, Any]]:
        """Parse every ledger line and assert the append-only ledger invariants."""
        records, errors = validate_kit.load_evaluation_ledger(root)
        self.assertEqual([], errors, "every JSONL line must remain valid after concurrency")
        event_ids = [record.get("event_id") for record in records]
        self.assertEqual(len(event_ids), len(set(event_ids)),
                         "exposure event_ids must stay unique")
        return records

    def create_split_run(
        self, root: Path, run_id: str, split_hash: str, exposure_status: str = "untouched"
    ) -> None:
        self.create_run(root, run_id)
        self.configure_finalizable_contract(
            root,
            run_id,
            exposure={
                "split_id": f"outer-{run_id}",
                "split_hash": split_hash,
                "dataset_hash": "b" * 64,
                "population_hash": "c" * 64,
                "exposure_status": exposure_status,
            },
        )

    def test_concurrent_reservations_of_distinct_splits_lose_no_events(self) -> None:
        # Regression: the old read/check/atomic-rewrite transaction lost writes
        # under concurrency (28 successful commands, 26 ledger events). Every
        # successful reservation command must be durably represented.
        rounds = 3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            for round_index in range(rounds):
                run_ids = [f"storm-{round_index}-{i:02d}" for i in range(12)]
                for offset, run_id in enumerate(run_ids):
                    self.create_split_run(
                        root, run_id, f"{round_index * len(run_ids) + offset:064x}"
                    )
                results = self.launch_overlay_reserves(root, run_ids)
                successes = [item for item in results if item[1] == 0]
                self.assertEqual(len(run_ids), len(successes), str(results))
                events = self.validated_ledger_events(root)
                self.assertEqual(
                    (round_index + 1) * len(run_ids),
                    len(events),
                    "successful commands and durable events must stay equal every round",
                )
                self.assertEqual({event["run_id"] for event in events},
                                 {run_id for r in range(round_index + 1)
                                  for run_id in [f"storm-{r}-{i:02d}" for i in range(12)]})
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(36, len(lines))
            for line in lines:
                self.assertIsInstance(json.loads(line), dict)

    def test_concurrent_first_reservations_of_same_split_elect_one_owner(self) -> None:
        # Concurrent untouched claims over one population: exactly one
        # reservation may receive first-exposure semantics, the ledger must
        # record exactly that one event, honest later reservations must see the
        # prior exposure and commit their own events, and the first owner's
        # already-authorized position must never be retroactively invalidated.
        shared = "f" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            claimants = [f"claim-{i}" for i in range(8)]
            for run_id in claimants:
                self.create_split_run(root, run_id, shared)
            results = self.launch_overlay_reserves(root, claimants)
            winners = [item for item in results if item[1] == 0]
            self.assertEqual(1, len(winners), str(results))
            self.assertIn("RESERVED", winners[0][2])
            for _, code, output in results:
                if code != 0:
                    self.assertIn("previously exposed", output)
            events = self.validated_ledger_events(root)
            self.assertEqual(1, len(events), "exactly one first-exposure event is committed")

            late = ["late-a", "late-b"]
            for run_id in late:
                self.create_split_run(root, run_id, shared, exposure_status="previously_exposed")
            results = self.launch_overlay_reserves(root, late)
            self.assertEqual([0, 0], [item[1] for item in results], str(results))
            events = self.validated_ledger_events(root)
            self.assertEqual(3, len(events))
            self.assertEqual(winners[0][0], events[0]["run_id"],
                             "the first owner keeps its committed first position")

            # Concurrent retries of the FIRST owner's reservation are pure
            # idempotent replays: every command succeeds, no new event exists.
            results = self.launch_overlay_reserves(root, [winners[0][0]] * 6)
            self.assertEqual([0] * 6, [item[1] for item in results], str(results))
            events = self.validated_ledger_events(root)
            self.assertEqual(3, len(events), "retried reservations never duplicate events")

    def test_concurrent_identical_retry_commits_one_logical_reservation(self) -> None:
        # Six simultaneous retries of a reservation that does not exist yet:
        # the lock must make exactly one command the committing first run and
        # every other command must observe the committed event instead of
        # racing its own append.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_split_run(root, "retry-storm", "d" * 64)
            results = self.launch_overlay_reserves(root, ["retry-storm"] * 6)
            self.assertEqual([0] * 6, [item[1] for item in results], str(results))
            firsts = [item for item in results if "now burned" in item[2]]
            retries = [item for item in results if "nothing duplicated" in item[2]]
            self.assertEqual(1, len(firsts), str(results))
            self.assertEqual(5, len(retries), str(results))
            events = self.validated_ledger_events(root)
            self.assertEqual(1, len(events), "one logical reservation, one durable event")

    def test_reservation_without_durable_commit_never_reports_success(self) -> None:
        # A protected exposure is acknowledged only after durable persistence:
        # if the append/fsync fails, the reservation raises, the ledger stays
        # empty, and the retry path still commits honestly afterwards.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_split_run(root, "durable", "a" * 64)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"

            original = record_experiment_module._append_exposure_event

            def fail_persistence(ledger_path, event):
                raise OSError("simulated storage failure before durable commit")

            record_experiment_module._append_exposure_event = fail_persistence
            try:
                with self.assertRaises(OSError):
                    record_experiment_module.reserve_final_exposure(root, "durable")
            finally:
                record_experiment_module._append_exposure_event = original
            self.assertFalse(
                ledger.exists(),
                "a failed persistence must never leave an acknowledged exposure",
            )

            # After the transient failure the real commit path works: the
            # reservation is durable and the retry maps to the existing event.
            self.assertTrue(record_experiment_module.reserve_final_exposure(root, "durable"))
            events = self.validated_ledger_events(root)
            self.assertEqual(1, len(events))
            self.assertFalse(record_experiment_module.reserve_final_exposure(root, "durable"))
            self.assertEqual(1, len(self.validated_ledger_events(root)))

    # ------------------------------------------------------------------
    # Bounded protected-evaluation execution wrapper
    # ------------------------------------------------------------------

    def protected_eval(
        self, root: Path, run_id: str, handoff: Path, row: dict[str, str] | None = None,
        exit_code: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        script_lines = ["print('PROTECTED_EVAL_RAN')"]
        if exit_code == 0 and row is not None:
            script_lines += [
                "import json, os",
                f"row = {row!r}",
                "with open(os.environ['DSML_PROTECTED_ROW_JSON'], 'w', encoding='utf-8') as f:",
                "    f.write(json.dumps(row))",
            ]
        script_lines.append(f"raise SystemExit({exit_code})")
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tooling" / "record-experiment.py"),
                run_id,
                "--project-root",
                str(root),
                "--run-protected-evaluation",
                "--row-json",
                str(handoff),
                "--",
                sys.executable,
                "-c",
                "\n".join(script_lines),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_protected_evaluation_wrapper_gates_execution_behind_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "wrapped")
            final_row = self.prepare_final_cli_run(root, "wrapped")
            handoff = root / ".agent-system" / "runs" / "wrapped" / "protected-result.json"
            result = self.protected_eval(root, "wrapped", handoff, final_row)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            output = result.stdout
            self.assertLess(
                output.index("RESERVED"),
                output.index("PROTECTED_EVAL_RAN"),
                "the managed workflow must not reveal the protected result before the "
                "exposure commit is durable",
            )
            self.assertLess(
                output.index("PROTECTED_EVAL_RAN"), output.index("RECORDED")
            )
            self.assertIn("protected final evaluation of the promoted frozen candidate", output)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            # One exposure event + one execution-consumed event are both
            # durable before the evaluator starts; the journal remains the
            # single source of truth for the actual recorded outcome.
            self.assertEqual(2, len(events))
            self.assertEqual("wrapped", events[0]["run_id"])
            self.assertEqual("wrapped", events[1]["run_id"])
            self.assertNotIn("kind", events[0])
            self.assertEqual("execution_consumed", events[1].get("kind"))
            rows, errors = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "wrapped" / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("final_selected", rows[-1]["status"])

            # The one-shot property holds for the wrapper too: a second
            # protected query is refused before anything is revealed, and the
            # ledger gains no additional events of either kind.
            handoff2 = root / ".agent-system" / "runs" / "wrapped" / "protected-result-2.json"
            repeat = self.protected_eval(
                root, "wrapped", handoff2, {**final_row, "experiment_id": "exp_05"}
            )
            self.assertNotEqual(0, repeat.returncode)
            self.assertIn("already consumed", repeat.stdout)
            self.assertNotIn("PROTECTED_EVAL_RAN", repeat.stdout)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                2, len(events), "refused protected execution never re-burns or executes"
            )

    def test_protected_evaluation_wrapper_failure_and_misuse_stay_honest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "crashy")
            final_row = self.prepare_final_cli_run(root, "crashy")
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"

            # Missing promotion evidence: refused BEFORE any burn.
            self.create_run(root, "unpromoted")
            self.configure_finalizable_contract(root, "unpromoted")
            early = root / ".agent-system" / "runs" / "unpromoted" / "row.json"
            refused = self.protected_eval(root, "unpromoted", early, final_row)
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("no promoted frozen candidate", refused.stdout)
            self.assertFalse(ledger.exists(), "a refused preflight never burns the split")

            # Command crash after the durable reservation + consumed
            # transition: the split stays exposed and no result is recorded —
            # the honest scientific state. The crash happens after both the
            # reservation and the execution-consumed event are durable, so
            # the ledger carries two events for "crashy".
            handoff = root / ".agent-system" / "runs" / "crashy" / "row.json"
            failed = self.protected_eval(root, "crashy", handoff, exit_code=3)
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("PROTECTED_EVAL_RAN", failed.stdout)
            self.assertIn("stays exposed", failed.stdout)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events))
            self.assertEqual("crashy", events[0]["run_id"])
            self.assertEqual("crashy", events[1]["run_id"])
            self.assertNotIn("kind", events[0])
            self.assertEqual("execution_consumed", events[1].get("kind"))
            rows, _ = validate_kit.read_experiment_journal(
                root / ".agent-system" / "runs" / "crashy" / "experiments.tsv", root
            )
            self.assertEqual(3, len(rows))
            self.assertFalse(
                any(row["stage"] == "final" for row in rows),
                "a crashed protected evaluation records no final evidence",
            )

            # A stale handoff file is refused before burning, so a retry can
            # never mistake yesterday's output for the protected result.
            handoff.parent.mkdir(parents=True, exist_ok=True)
            stale = root / ".agent-system" / "runs" / "crashy" / "stale.json"
            stale.write_text("{}", encoding="utf-8")
            refused = self.protected_eval(root, "crashy", stale, final_row)
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("already exists", refused.stdout)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events), "stale-handoff refusal adds no new events")

    # ------------------------------------------------------------------
    # One-shot protected execution: crash, persistence, concurrency
    # ------------------------------------------------------------------

    def protected_eval_with_marker(
        self,
        root: Path,
        run_id: str,
        handoff: Path,
        marker: Path,
        row: dict[str, str] | None = None,
        exit_code: int = 0,
        spawn_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke ``--run-protected-evaluation`` with an evaluator script that
        increments ``marker`` every time it is launched.

        ``spawn_failure=True`` writes the command line so the evaluator cannot
        be spawned (``subprocess.run`` raises ``FileNotFoundError``).
        """
        script_lines = [
            f"with open({str(marker)!r}, 'r+') as f:",
            "    n = int(f.read().strip() or '0')",
            "    f.seek(0); f.write(str(n+1)); f.truncate()",
            "print('PROTECTED_EVAL_RAN', flush=True)",
        ]
        if exit_code == 0 and row is not None:
            script_lines += [
                "import json, os",
                f"row = {row!r}",
                "with open(os.environ['DSML_PROTECTED_ROW_JSON'], 'w', encoding='utf-8') as f:",
                "    f.write(json.dumps(row))",
            ]
        script_lines.append(f"raise SystemExit({exit_code})")
        if spawn_failure:
            command = ["/nonexistent-evaluator-binary", "--does-not-exist"]
        else:
            command = [sys.executable, "-c", "\n".join(script_lines)]
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tooling" / "record-experiment.py"),
                run_id,
                "--project-root",
                str(root),
                "--run-protected-evaluation",
                "--row-json",
                str(handoff),
                "--",
                *command,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_managed_protected_evaluator_launches_exactly_once_after_crash(self) -> None:
        # Mechanical crash-then-retry regression: a managed evaluator that
        # crashes must NOT be launched again, regardless of whether a final
        # row was recorded. The launch count is verified via a side-effect
        # marker incremented by the test evaluator, so the assertion is
        # independent of stdout inspection.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "crash-retry")
            self.prepare_final_cli_run(root, "crash-retry")
            run_dir = root / ".agent-system" / "runs" / "crash-retry"
            marker = Path(directory) / "launches.txt"
            marker.write_text("0\n", encoding="utf-8")

            handoff1 = run_dir / "row1.json"
            first = self.protected_eval_with_marker(
                root, "crash-retry", handoff1, marker, exit_code=7
            )
            self.assertNotEqual(0, first.returncode)
            self.assertIn("PROTECTED_EVAL_RAN", first.stdout)
            self.assertEqual("1", marker.read_text(encoding="utf-8").strip())

            handoff2 = run_dir / "row2.json"
            second = self.protected_eval_with_marker(
                root, "crash-retry", handoff2, marker, exit_code=0
            )
            self.assertNotEqual(0, second.returncode)
            self.assertIn("already consumed", second.stdout)
            self.assertNotIn("PROTECTED_EVAL_RAN", second.stdout)
            self.assertEqual(
                "1",
                marker.read_text(encoding="utf-8").strip(),
                "a second managed invocation must not launch the evaluator again",
            )

            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events))
            self.assertNotIn("kind", events[0])
            self.assertEqual("execution_consumed", events[1].get("kind"))
            rows, _ = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual(
                3,
                len(rows),
                "a crashed managed execution records no stage-final journal row",
            )
            self.assertFalse(
                any(row["stage"] == "final" for row in rows),
                "a crashed managed execution must not leave any final-stage row",
            )

    def test_invalid_final_outcome_keeps_one_shot_consumed(self) -> None:
        # The managed evaluator exits zero but records an invalid/crashed
        # status: that is a legitimate final outcome, the one-shot execution
        # is durably consumed, and a subsequent managed launch is refused.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "invalid-final")
            final_row = self.prepare_final_cli_run(root, "invalid-final")
            run_dir = root / ".agent-system" / "runs" / "invalid-final"
            marker = Path(directory) / "launches.txt"
            marker.write_text("0\n", encoding="utf-8")

            invalid = {**final_row, "status": "invalid", "result_summary": "evaluator could not score this candidate"}
            handoff1 = run_dir / "row1.json"
            first = self.protected_eval_with_marker(
                root, "invalid-final", handoff1, marker, row=invalid
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertEqual("1", marker.read_text(encoding="utf-8").strip())
            rows, _ = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual("invalid", rows[-1]["status"])
            self.assertEqual("final", rows[-1]["stage"])

            handoff2 = run_dir / "row2.json"
            retry = self.protected_eval_with_marker(
                root, "invalid-final", handoff2, marker, row={**invalid, "experiment_id": "exp_06"}
            )
            self.assertNotEqual(0, retry.returncode)
            self.assertIn("already consumed", retry.stdout)
            self.assertEqual(
                "1",
                marker.read_text(encoding="utf-8").strip(),
                "invalid/crashed final outcome still consumes the one-shot execution",
            )

    def test_reservation_only_without_execution_stays_idempotent(self) -> None:
        # The standalone --reserve-final-exposure operation must remain
        # idempotent regardless of how many times it is invoked before any
        # managed execution begins.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "reserve-only")
            self.prepare_final_cli_run(root, "reserve-only")
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"

            for _ in range(3):
                reserved = self.reserve(root, "reserve-only")
                self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                1,
                len(events),
                "repeated standalone reservation must not duplicate the exposure event",
            )
            self.assertNotIn("kind", events[0])

    def test_persistence_failure_before_execution_start_never_launches(self) -> None:
        # If the durable consumed-event commit fails, the wrapper must
        # raise BEFORE launching the subprocess. Calling the wrapper
        # function in-process lets us simulate a durability failure
        # deterministically; the launch-marker file is checked to prove
        # the subprocess was never spawned.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "persist-fail")
            self.prepare_final_cli_run(root, "persist-fail")
            run_dir = root / ".agent-system" / "runs" / "persist-fail"
            marker = Path(directory) / "launches.txt"
            marker.write_text("0\n", encoding="utf-8")
            handoff = run_dir / "row.json"

            real_append = record_experiment_module._append_exposure_event
            call_count = {"n": 0}

            def flaky(ledger_path: Path, event: dict[str, Any]) -> None:
                call_count["n"] += 1
                # The reservation commit (first call) must succeed; the
                # consumed commit (second call) must fail to simulate a
                # broken durability path between reservation and launch.
                if call_count["n"] >= 2:
                    raise OSError("simulated persistence failure on consumed commit")
                real_append(ledger_path, event)

            evaluator_command = [
                sys.executable,
                "-c",
                "\n".join([
                    f"with open({str(marker)!r}, 'r+') as f:",
                    "    n = int(f.read().strip() or '0')",
                    "    f.seek(0); f.write(str(n+1)); f.truncate()",
                    "print('PROTECTED_EVAL_RAN', flush=True)",
                ]),
            ]

            with patch.object(
                record_experiment_module, "_append_exposure_event", side_effect=flaky
            ):
                with self.assertRaises(OSError) as raised:
                    record_experiment_module.run_protected_evaluation(
                        root, "persist-fail", handoff, evaluator_command
                    )
            self.assertIn("simulated persistence failure", str(raised.exception))
            self.assertEqual(
                "0",
                marker.read_text(encoding="utf-8").strip(),
                "persistence failure before consumed commit must keep the evaluator unlaunched",
            )
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                1,
                len(events),
                "a failed consumed commit must not append a partial event",
            )
            self.assertNotIn(
                "kind",
                events[0],
                "the only event after a failure is the durable reservation",
            )

    def test_spawn_failure_after_consumed_commit_still_consumes_one_shot(self) -> None:
        # Persistence succeeds but the subprocess cannot be spawned (the
        # chosen binary does not exist). The conservative scientifically
        # valid behavior keeps the execution attempt consumed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "spawn-fail")
            self.prepare_final_cli_run(root, "spawn-fail")
            run_dir = root / ".agent-system" / "runs" / "spawn-fail"
            marker = Path(directory) / "launches.txt"
            marker.write_text("0\n", encoding="utf-8")
            handoff = run_dir / "row.json"

            first = self.protected_eval_with_marker(
                root, "spawn-fail", handoff, marker, spawn_failure=True
            )
            self.assertNotEqual(0, first.returncode)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events))
            self.assertEqual("execution_consumed", events[1].get("kind"))

            handoff2 = run_dir / "row2.json"
            retry = self.protected_eval_with_marker(
                root, "spawn-fail", handoff2, marker, exit_code=0
            )
            self.assertNotEqual(0, retry.returncode)
            self.assertIn("already consumed", retry.stdout)
            self.assertEqual(
                "0",
                marker.read_text(encoding="utf-8").strip(),
                "a spawn-failed attempt must not be retried by the managed wrapper",
            )

    def test_simultaneous_duplicate_managed_launch_starts_evaluator_once(self) -> None:
        # Two concurrent --run-protected-evaluation invocations on the same
        # run: the lock-protected check-and-transition must serialize them so
        # exactly one evaluator subprocess starts.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "race")
            final_row = self.prepare_final_cli_run(root, "race")
            run_dir = root / ".agent-system" / "runs" / "race"
            marker = Path(directory) / "launches.txt"
            marker.write_text("0\n", encoding="utf-8")

            script = (
                f"with open({str(marker)!r}, 'r+') as f:\n"
                "    n = int(f.read().strip() or '0')\n"
                "    f.seek(0); f.write(str(n+1)); f.truncate()\n"
                "import os, json\n"
                f"row = {final_row!r}\n"
                "with open(os.environ['DSML_PROTECTED_ROW_JSON'], 'w', encoding='utf-8') as f:\n"
                "    f.write(json.dumps(row))\n"
                "print('PROTECTED_EVAL_RAN', flush=True)\n"
            )
            command = [sys.executable, "-B"]
            run_command = [
                sys.executable,
                "-B",
                str(ROOT / "tooling" / "record-experiment.py"),
                "race",
                "--project-root",
                str(root),
                "--run-protected-evaluation",
                "--row-json",
                str(run_dir / "row-a.json"),
                "--",
                sys.executable,
                "-c",
                script,
            ]

            barrier = threading.Barrier(2)

            def worker(suffix: str) -> subprocess.CompletedProcess[str]:
                handoff = run_dir / f"row-{suffix}.json"
                command_args = list(run_command)
                idx = command_args.index("--row-json")
                command_args[idx + 1] = str(handoff)
                proc = subprocess.Popen(
                    command_args,
                    cwd=root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                barrier.wait(timeout=30)
                stdout, stderr = proc.communicate(timeout=120)
                return subprocess.CompletedProcess(
                    command_args, proc.returncode, stdout, stderr
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, "a"), pool.submit(worker, "b")]
                results = [f.result() for f in futures]

            launch_count = int(marker.read_text(encoding="utf-8").strip())
            self.assertEqual(
                1,
                launch_count,
                "concurrent managed launches must start exactly one evaluator",
            )
            successful = [result for result in results if result.returncode == 0]
            refused = [result for result in results if result.returncode != 0]
            self.assertEqual(1, len(successful))
            self.assertEqual(1, len(refused))
            self.assertIn("already consumed", refused[0].stdout)
            self.assertNotIn("PROTECTED_EVAL_RAN", refused[0].stdout)

            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(events))
            self.assertEqual("execution_consumed", events[1].get("kind"))

    # ------------------------------------------------------------------
    # Full realistic lifecycle: baseline to finalized evidence
    # ------------------------------------------------------------------

    def complete_lifecycle(self, root: Path, run_id: str, metric: str = "rmse") -> Path:
        final_row = self.prepare_final_cli_run(root, run_id, metric=metric)
        reserved = self.reserve(root, run_id)
        self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
        recorded = self.record(root, run_id, final_row)
        self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
        run_dir = root / ".agent-system" / "runs" / run_id
        run_path = run_dir / "run.yaml"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        summary = run["results"]["experiment_summary"]
        summary["stopping_reason"] = "budget"
        summary["lifecycle"]["research_decision"] = "accept"
        summary["selected_experiment"] = {
            "experiment_id": "exp_04",
            "candidate_identity": final_row["candidate_identity"],
            "config_hash": final_row["config_hash"],
        }
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        learning_path = run_dir / "learning.yaml"
        learning = json.loads(learning_path.read_text(encoding="utf-8"))
        learning["no_reusable_signal_reason"] = "Synthetic lifecycle run."
        learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
        return run_dir

    def test_end_to_end_selection_to_finalized_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "e2e", max_experiments=4)
            run_dir = self.complete_lifecycle(root, "e2e")

            rows, errors = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual(["baseline", "rejected", "promoted_to_holdout", "final_selected"],
                              [row["status"] for row in rows])
            # The final row IS the promoted frozen candidate.
            self.assertEqual(rows[2]["candidate_identity"], rows[3]["candidate_identity"])
            self.assertEqual(rows[2]["config_hash"], rows[3]["config_hash"])
            summary = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))[
                "results"
            ]["experiment_summary"]
            # Development budget consumed: baseline no, novel A yes, promotion
            # yes, protected final no.
            self.assertEqual(2, summary["experiments_run"])
            self.assertEqual(
                "exp_04",
                summary["selected_experiment"]["experiment_id"],
            )
            self.assertEqual("final_selected", rows[3]["status"])

            finalized = self.finalize(root, "e2e")
            self.assertEqual(0, finalized.returncode, finalized.stdout + finalized.stderr)
            finalized_bytes = (run_dir / "run.yaml").read_bytes()

            # Post-finalization mutation fails closed on every surface.
            late = {
                **rows[3],
                "experiment_id": "exp_05",
                "stage": "development",
                "candidate_identity": "8" * 64,
                "config_hash": "8" * 64,
                "status": "rejected",
            }
            mutation = self.record(root, "e2e", late)
            self.assertNotEqual(0, mutation.returncode)
            self.assertIn("immutable", mutation.stdout)
            reserve_again = self.reserve(root, "e2e")
            self.assertNotEqual(0, reserve_again.returncode)
            self.assertIn("finalized", reserve_again.stdout)

            # Repeated finalization remains an idempotent zero-write pass.
            again = self.finalize(root, "e2e")
            self.assertEqual(0, again.returncode, again.stdout + again.stderr)
            self.assertEqual(finalized_bytes, (run_dir / "run.yaml").read_bytes())

    def test_negative_final_outcome_lifecycle_finalizes_for_real_reasons(self) -> None:
        # The complete protected lifecycle through the execution wrapper with a
        # NEGATIVE final outcome: the rejected evaluation stays real evidence
        # (never a duplicate), the run finalizes because of its actual
        # outcome-dependent lifecycle state, and finalized immutability holds.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "neglife")
            run_dir = root / ".agent-system" / "runs" / "neglife"
            final_row = self.prepare_final_cli_run(root, "neglife")
            negative = {
                **final_row,
                "status": "rejected",
                "selection_value": "9.5",
                "result_summary": "protected evidence rejects the frozen candidate",
            }
            handoff = run_dir / "protected-result.json"
            result = self.protected_eval(root, "neglife", handoff, negative)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertLess(
                result.stdout.index("RESERVED"), result.stdout.index("PROTECTED_EVAL_RAN")
            )
            self.assertIn(
                "protected final evaluation of the promoted frozen candidate", result.stdout
            )
            rows, errors = validate_kit.read_experiment_journal(
                run_dir / "experiments.tsv", root
            )
            self.assertEqual([], errors)
            self.assertEqual("rejected", rows[-1]["status"])
            self.assertNotEqual("duplicate", rows[-1]["status"])

            # One-shot semantics are outcome-independent: a second protected
            # execution is refused before revealing anything, and no positive
            # status can be forced onto the consumed population.
            handoff2 = run_dir / "protected-result-2.json"
            again = self.protected_eval(
                root, "neglife", handoff2,
                {**negative, "experiment_id": "exp_05", "status": "final_selected"},
            )
            self.assertNotEqual(0, again.returncode)
            self.assertIn("already consumed", again.stdout)
            self.assertNotIn("PROTECTED_EVAL_RAN", again.stdout)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            # A successful managed execution leaves one exposure + one
            # consumed event; the refused retry adds nothing.
            self.assertEqual(
                2,
                len(ledger.read_text(encoding="utf-8").strip().splitlines()),
                "refused retry never adds new ledger events",
            )

            run_path = run_dir / "run.yaml"
            learning_path = run_dir / "learning.yaml"
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            learning["no_reusable_signal_reason"] = "Synthetic negative final lifecycle."
            learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
            run = json.loads(run_path.read_text(encoding="utf-8"))
            summary = run["results"]["experiment_summary"]
            summary["stopping_reason"] = "budget"

            # Claiming ACCEPT with the negative final as the selected
            # experiment must fail for the real lifecycle reason — the journal
            # status is 'rejected' — not because the final experiment was
            # rewritten to duplicate.
            summary["lifecycle"]["research_decision"] = "accept"
            summary["selected_experiment"] = {
                "experiment_id": "exp_04",
                "candidate_identity": negative["candidate_identity"],
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            accepted = self.finalize(root, "neglife")
            self.assertNotEqual(0, accepted.returncode)
            self.assertIn("journal status must be 'final_selected'", accepted.stdout)
            self.assertNotIn("duplicate", accepted.stdout)

            # The honest representation of the negative outcome finalizes:
            # research_decision reject, no selected experiment.
            summary["lifecycle"]["research_decision"] = "reject"
            summary["selected_experiment"] = None
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            finalized = self.finalize(root, "neglife")
            self.assertEqual(0, finalized.returncode, finalized.stdout + finalized.stderr)
            finalized_bytes = run_path.read_bytes()

            # Finalized evidence stays immutable and re-finalization stays an
            # idempotent zero-write pass.
            repeat = self.finalize(root, "neglife")
            self.assertEqual(0, repeat.returncode, repeat.stdout + repeat.stderr)
            self.assertEqual(finalized_bytes, run_path.read_bytes())
            mutation = self.record(
                root, "neglife",
                {**negative, "experiment_id": "exp_06", "stage": "development",
                 "candidate_identity": "8" * 64, "config_hash": "8" * 64,
                 "prediction_hash": ""},
            )
            self.assertNotEqual(0, mutation.returncode)
            self.assertIn("immutable", mutation.stdout)
            late_reserve = self.reserve(root, "neglife")
            self.assertNotEqual(0, late_reserve.returncode)
            self.assertIn("finalized", late_reserve.stdout)

    def test_non_forecasting_custom_metric_lifecycle(self) -> None:
        # The same lifecycle machinery with an AUROC objective, grouped CV
        # strategy, and an opaque latency guardrail: metric semantics stay in
        # the declared contract, and no metric-specific source path is needed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "fraud-e2e")
            evaluation_path = root / ".agent-system" / "runs" / "fraud-e2e" / "evaluation.yaml"
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            evaluation["selection_objective"] = {
                "metric": "custom_score",
                "direction": "maximize",
                "minimum_meaningful_delta": 0.01,
            }
            evaluation["secondary_metrics"] = [
                {
                    "metric": "latency_ms",
                    "role": "guardrail",
                    "direction": "minimize",
                    "max_degradation": 5.0,
                }
            ]
            evaluation["evaluation"]["strategy"] = "grouped_cv"
            evaluation["evaluation"]["final_split"] = "outer holdout"
            evaluation["evaluation"]["final_split_identity"] = {
                "split_id": "outer-fraud-1",
                "split_hash": "d" * 64,
                "dataset_hash": "e" * 64,
                "population_hash": "f" * 64,
                "exposure_status": "untouched",
            }
            evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")

            metric = "custom_score"
            scored = {
                "baseline": ("90.0", 90.0, 100.0),
                "candidate": ("95.0", 95.0, 102.0),
            }

            identities = {"baseline": ("1", "a"), "candidate": ("2", "b")}

            def row_for(experiment_id: str, phase: str, **overrides: str) -> dict[str, str]:
                value, objective, latency = scored[phase]
                identity, config = identities[phase]
                row = journal_row(
                    experiment_id=experiment_id,
                    candidate_identity=identity * 64,
                    config_hash=config * 64,
                    selection_metric=metric,
                    selection_value=value,
                    metrics_json=json.dumps({metric: objective, "latency_ms": latency}),
                    guardrail_status="pass",
                    hypothesis=phase,
                    expected_mechanism=phase,
                    change_summary=phase,
                    result_summary=phase,
                    next_hypothesis_rationale="continue",
                    **overrides,
                )
                return row

            baseline = row_for("exp_01", "baseline", status="baseline")
            promoted = row_for(
                "exp_02",
                "candidate",
                parent_experiment_id="exp_01",
                stage="selection",
                status="promoted_to_holdout",
            )
            for row in (baseline, promoted):
                recorded = self.record(root, "fraud-e2e", row)
                self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            reserved = self.reserve(root, "fraud-e2e")
            self.assertEqual(0, reserved.returncode, reserved.stdout + reserved.stderr)
            final_row = {
                **promoted,
                "experiment_id": "exp_03",
                "parent_experiment_id": "exp_02",
                "stage": "final",
                "status": "final_selected",
                "selection_value": "93.0",
                "metrics_json": json.dumps({metric: 93.0, "latency_ms": 104.0}),
                "prediction_hash": "9" * 64,
                "result_summary": "final protected custom_score",
                "next_hypothesis_rationale": "done",
            }
            recorded = self.record(root, "fraud-e2e", final_row)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            run_path = root / ".agent-system" / "runs" / "fraud-e2e" / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            summary = run["results"]["experiment_summary"]
            summary["stopping_reason"] = "target_reached"
            summary["lifecycle"]["research_decision"] = "accept"
            summary["selected_experiment"] = {
                "experiment_id": "exp_03",
                "candidate_identity": final_row["candidate_identity"],
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            learning_path = root / ".agent-system" / "runs" / "fraud-e2e" / "learning.yaml"
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            learning["no_reusable_signal_reason"] = "Synthetic non-forecasting lifecycle."
            learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
            finalized = self.finalize(root, "fraud-e2e")
            self.assertEqual(0, finalized.returncode, finalized.stdout + finalized.stderr)

    def test_invalid_manually_finalized_run_cannot_bypass_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "forged")
            run_path = root / ".agent-system" / "runs" / "forged" / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["results"]["experiment_summary"]["lifecycle"]["evidence_status"] = "finalized"
            del run["task"]["goal"]
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            finalize = self.finalize(root, "forged")
            self.assertNotEqual(0, finalize.returncode)
            self.assertIn("task.goal", finalize.stdout)

    def test_invalid_run_cannot_transition_to_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "invalid-finalization")
            run_path = root / ".agent-system" / "runs" / "invalid-finalization" / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            del run["task"]["goal"]
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            finalize = self.finalize(root, "invalid-finalization")

            self.assertNotEqual(0, finalize.returncode)
            unchanged = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "open",
                unchanged["results"]["experiment_summary"]["lifecycle"]["evidence_status"],
            )

    def test_valid_finalization_is_idempotent_without_duplicate_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "valid-finalization")
            run_dir = self.prepare_finalizable_run(
                root, "valid-finalization", stage="final", research_decision="accept"
            )
            run_path = run_dir / "run.yaml"

            first = self.finalize(root, "valid-finalization")
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            first_bytes = run_path.read_bytes()
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            first_ledger = ledger.read_text(encoding="utf-8")

            second = self.finalize(root, "valid-finalization")
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertEqual(first_bytes, run_path.read_bytes())
            self.assertEqual(first_ledger, ledger.read_text(encoding="utf-8"))
            self.assertEqual(1, len(first_ledger.strip().splitlines()))

    def test_failed_finalization_persists_candidate_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "mismatch-run")
            run_dir = self.prepare_finalizable_run(
                root, "mismatch-run", stage="final", research_decision="accept"
            )
            run_path = run_dir / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["results"]["experiment_summary"]["selected_experiment"] = {
                "experiment_id": "exp_01",
                "candidate_identity": "9" * 64,
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            first = self.finalize(root, "mismatch-run")
            self.assertNotEqual(0, first.returncode)
            self.assertIn("candidate_identity mismatch", first.stdout)
            persisted = json.loads(run_path.read_text(encoding="utf-8"))
            summary = persisted["results"]["experiment_summary"]
            self.assertEqual("open", summary["lifecycle"]["evidence_status"])
            self.assertIn("selected_experiment_mismatch", summary["candidate_learning_events"])

            second = self.finalize(root, "mismatch-run")
            self.assertNotEqual(0, second.returncode)
            repersisted = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                summary["candidate_learning_events"],
                repersisted["results"]["experiment_summary"]["candidate_learning_events"],
                "event persistence must be deterministic and deduplicated",
            )

    def test_explicit_candidate_event_recorded_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "explicit-event")
            run_path = root / ".agent-system" / "runs" / "explicit-event" / "run.yaml"
            finalize = self.finalize(
                root, "explicit-event", ["--candidate-event", "user_rejection"]
            )
            self.assertNotEqual(0, finalize.returncode)
            persisted = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertIn(
                "user_rejection",
                persisted["results"]["experiment_summary"]["candidate_learning_events"],
            )

    def test_empty_learning_signals_require_a_structured_reason_in_v04(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / ".agent-system" / "runs" / "no-signal"
            run_dir.mkdir(parents=True)
            (run_dir / "run.yaml").write_text("{}\n", encoding="utf-8")
            learning = json.loads(
                (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                    encoding="utf-8"
                )
            )
            learning["schema_version"] = "0.4"
            learning["run_ref"] = ".agent-system/runs/no-signal/run.yaml"
            learning["signals"] = []
            learning["no_reusable_signal_reason"] = "One-off clean result with no reusable toolkit lesson."
            path = run_dir / "learning.yaml"

            self.assertEqual(
                [], validate_kit.learning_semantic_errors(learning, path, root)
            )
            del learning["no_reusable_signal_reason"]
            errors = validate_kit.learning_semantic_errors(learning, path, root)
            self.assertTrue(any("no_reusable_signal_reason" in error for error in errors), errors)

    # ------------------------------------------------------------------
    # Finalized evidence is terminal (regression: post-finalization mutation)
    # ------------------------------------------------------------------

    def finalize_open_run(self, root: Path, run_id: str) -> Path:
        self.create_run(root, run_id)
        return self.prepare_finalizable_run(root, run_id, stage="development")

    def test_finalized_run_is_immutable_to_experiment_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            run_dir = self.finalize_open_run(root, "locked-run")
            finalized = self.finalize(root, "locked-run")
            self.assertEqual(0, finalized.returncode, finalized.stdout + finalized.stderr)
            run_bytes = (run_dir / "run.yaml").read_bytes()
            journal_bytes = (run_dir / "experiments.tsv").read_bytes()

            novel = journal_row(
                experiment_id="exp_02",
                candidate_identity="2" * 64,
                config_hash="e" * 64,
                selection_metric="rmse",
                selection_value="8.5",
                guardrail_status="not_applicable",
                status="rejected",
            )
            rejected = self.record(root, "locked-run", novel)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("finalized", rejected.stdout)
            self.assertIn("immutable", rejected.stdout)
            self.assertEqual(journal_bytes, (run_dir / "experiments.tsv").read_bytes())
            self.assertEqual(run_bytes, (run_dir / "run.yaml").read_bytes())
            summary = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))[
                "results"
            ]["experiment_summary"]
            self.assertEqual(0, summary["experiments_run"])
            self.assertEqual("finalized", summary["lifecycle"]["evidence_status"])

            # Exposure reservation is also mutation: refused on finalized runs.
            reserved = self.reserve(root, "locked-run")
            self.assertNotEqual(0, reserved.returncode)
            self.assertIn("finalized", reserved.stdout)
            ledger = root / ".agent-system" / "evaluation-ledger.jsonl"
            self.assertFalse(
                ledger.exists() and ledger.read_text(encoding="utf-8").strip(),
                "a finalized development run must not gain exposure events",
            )

            # Repeated finalization stays a validated, zero-write PASS.
            again = self.finalize(root, "locked-run")
            self.assertEqual(0, again.returncode, again.stdout + again.stderr)
            self.assertEqual(run_bytes, (run_dir / "run.yaml").read_bytes())

            # Even an explicit event argument is refused against finalized evidence.
            evented = self.finalize(root, "locked-run", ["--candidate-event", "user_rejection"])
            self.assertNotEqual(0, evented.returncode)
            self.assertIn("immutable", evented.stdout)
            self.assertEqual(run_bytes, (run_dir / "run.yaml").read_bytes())

    def test_finalize_reports_failures_without_rewriting_finalized_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            run_dir = self.finalize_open_run(root, "tampered")
            first = self.finalize(root, "tampered")
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            run_path = run_dir / "run.yaml"
            before = run_path.read_bytes()
            # Hand-edit the finalized record into an invalid state.
            run = json.loads(before.decode("utf-8"))
            run["results"]["experiment_summary"]["stopping_reason"] = "not_started"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            tampered = run_path.read_bytes()

            result = self.finalize(root, "tampered")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("stopping_reason", result.stdout)
            self.assertEqual(
                tampered,
                run_path.read_bytes(),
                "finalization must not rewrite (even diagnostically) a finalized record",
            )

    def test_hand_written_final_row_without_reservation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "bypass")
            self.configure_finalizable_contract(root, "bypass")
            run_dir = root / ".agent-system" / "runs" / "bypass"
            self.write_journal(
                run_dir,
                [
                    journal_row(
                        experiment_id="exp_01",
                        stage="final",
                        candidate_identity="1" * 64,
                        config_hash="d" * 64,
                        selection_metric="rmse",
                        selection_value="8.0",
                        guardrail_status="not_applicable",
                        status="baseline",
                    )
                ],
            )
            run_path = run_dir / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            summary = run["results"]["experiment_summary"]
            summary["experiments_run"] = 0
            summary["stopping_reason"] = "plateau"
            summary["lifecycle"]["research_decision"] = "reject"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            learning_path = run_dir / "learning.yaml"
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            learning["no_reusable_signal_reason"] = "Nothing reusable."
            learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")

            result = self.finalize(root, "bypass")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("exposure reservation", result.stdout)
            self.assertFalse((root / ".agent-system" / "evaluation-ledger.jsonl").exists())
            self.assertEqual(
                "open",
                json.loads(run_path.read_text(encoding="utf-8"))["results"][
                    "experiment_summary"
                ]["lifecycle"]["evidence_status"],
            )

    # ------------------------------------------------------------------
    # Guardrail semantics: declared contract decides what evidence is required
    # ------------------------------------------------------------------

    def test_no_guardrail_contract_accepts_not_applicable_selection(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["experiment_mode"] = "benchmark"
        evaluation["selection_objective"] = {
            "metric": "rmse",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                config_hash="a" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                candidate_identity="2" * 64,
                config_hash="b" * 64,
                selection_metric="rmse",
                selection_value="8.0",
                guardrail_status="not_applicable",
                status="final_selected",
            ),
        ]
        selected = {"experiment_id": "exp_02", "candidate_identity": "2" * 64}
        self.assertEqual(
            [], validate_kit.experiment_journal_errors(rows, evaluation, selected)
        )

    def test_declared_guardrails_reject_unverified_or_absent_selection_pass(self) -> None:
        evaluation = self.guardrail_evaluation("latency_ms", "minimize", 5)
        evaluation["experiment_mode"] = "benchmark"
        evaluation["selection_objective"] = {
            "metric": "primary",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="primary",
                selection_value="9.0",
                metrics_json=json.dumps({"primary": 9.0, "latency_ms": 100.0}),
                guardrail_status="pass",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                candidate_identity="2" * 64,
                selection_metric="primary",
                selection_value="8.0",
                metrics_json=json.dumps({"primary": 8.0, "latency_ms": 103.0}),
                guardrail_status="not_applicable",
                status="final_selected",
            ),
        ]
        selected = {"experiment_id": "exp_02", "candidate_identity": "2" * 64}
        errors = validate_kit.experiment_journal_errors(rows, evaluation, selected)
        self.assertTrue(
            any("mandatory guardrails must pass" in error for error in errors), errors
        )

    def test_guardrail_pass_without_reference_baseline_is_invalid(self) -> None:
        evaluation = self.guardrail_evaluation("latency_ms", "minimize", 5)
        evaluation["selection_objective"] = {
            "metric": "primary",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        candidate = journal_row(
            experiment_id="exp_01",
            stage="selection",
            candidate_identity="1" * 64,
            selection_metric="primary",
            selection_value="8.0",
            metrics_json=json.dumps({"primary": 8.0, "latency_ms": 120.0}),
            guardrail_status="pass",
            status="promoted_to_holdout",
        )
        errors = validate_kit.experiment_journal_errors([candidate], evaluation, None)
        self.assertTrue(
            any(
                "no baseline experiment provides reference metrics" in error
                for error in errors
            ),
            errors,
        )

    def test_guardrail_comparison_uses_canonical_metric_names(self) -> None:
        evaluation = self.guardrail_evaluation("latency-ms", "minimize", 5)
        evaluation["selection_objective"] = {
            "metric": "primary",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        within = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="primary",
                selection_value="9.0",
                metrics_json=json.dumps({"Primary Score": 9.0, "Latency_ms": 100.0}),
                guardrail_status="pass",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_01",
                candidate_identity="2" * 64,
                selection_metric="primary",
                selection_value="8.0",
                metrics_json=json.dumps({"Primary Score": 8.0, "Latency_ms": 103.0}),
                guardrail_status="pass",
                status="rejected",
                hypothesis="h",
                expected_mechanism="m",
                change_summary="c",
                result_summary="r",
                next_hypothesis_rationale="n",
            ),
        ]
        self.assertEqual(
            [], validate_kit.experiment_journal_errors(within, evaluation, None)
        )

    # ------------------------------------------------------------------
    # Adaptive lineage is causally ordered
    # ------------------------------------------------------------------

    def adaptive_rows(self, child_overrides: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
        evaluation = self.evaluation_template()
        evaluation["experiment_mode"] = "adaptive"
        evaluation["selection_objective"] = {
            "metric": "rmse",
            "direction": "minimize",
            "minimum_meaningful_delta": None,
        }
        base = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            selection_metric="rmse",
            selection_value="9.0",
            guardrail_status="not_applicable",
            status="baseline",
        )
        child = journal_row(
            experiment_id="exp_02",
            candidate_identity="2" * 64,
            selection_metric="rmse",
            selection_value="8.0",
            guardrail_status="not_applicable",
            status="rejected",
            hypothesis="h",
            expected_mechanism="m",
            change_summary="c",
            result_summary="r",
            next_hypothesis_rationale="n",
        )
        child.update(child_overrides)
        return evaluation, [base, child]

    def test_lineage_earlier_parent_is_valid(self) -> None:
        evaluation, rows = self.adaptive_rows({"parent_experiment_id": "exp_01"})
        self.assertEqual([], validate_kit.experiment_journal_errors(rows, evaluation, None))

    def test_lineage_self_parent_is_invalid(self) -> None:
        evaluation, rows = self.adaptive_rows({"parent_experiment_id": "exp_02"})
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(
            any("cannot reference the experiment itself" in error for error in errors), errors
        )

    def test_lineage_future_parent_is_invalid(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["experiment_mode"] = "adaptive"
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="baseline",
            ),
            journal_row(
                experiment_id="exp_02",
                parent_experiment_id="exp_03",
                candidate_identity="2" * 64,
                selection_metric="rmse",
                selection_value="8.0",
                guardrail_status="not_applicable",
                status="rejected",
                hypothesis="h",
                expected_mechanism="m",
                change_summary="c",
                result_summary="r",
                next_hypothesis_rationale="n",
            ),
            journal_row(
                experiment_id="exp_03",
                parent_experiment_id="exp_01",
                candidate_identity="3" * 64,
                selection_metric="rmse",
                selection_value="7.0",
                guardrail_status="not_applicable",
                status="rejected",
                hypothesis="h",
                expected_mechanism="m",
                change_summary="c",
                result_summary="r",
                next_hypothesis_rationale="n",
            ),
        ]
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(
            any(
                "exp_02" in error and "must appear earlier in the journal" in error
                for error in errors
            ),
            errors,
        )

    def test_lineage_missing_parent_is_invalid(self) -> None:
        evaluation, rows = self.adaptive_rows({"parent_experiment_id": ""})
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertTrue(
            any("requires parent_experiment_id" in error for error in errors), errors
        )

    def test_baseline_needs_no_adaptive_parent(self) -> None:
        evaluation = self.evaluation_template()
        evaluation["experiment_mode"] = "adaptive"
        rows = [
            journal_row(
                experiment_id="exp_01",
                candidate_identity="1" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="promoted_to_holdout",
            ),
            journal_row(
                experiment_id="exp_02",
                candidate_identity="2" * 64,
                selection_metric="rmse",
                selection_value="8.5",
                guardrail_status="not_applicable",
                status="baseline",
            ),
        ]
        errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
        self.assertFalse(
            any(
                "exp_02" in error and "parent_experiment_id" in error for error in errors
            ),
            errors,
        )

    # ------------------------------------------------------------------
    # Provenance is artifact-agnostic, never Git-specific
    # ------------------------------------------------------------------

    def test_missing_provenance_is_derived_from_immutable_identity(self) -> None:
        config_only = journal_row(
            experiment_id="exp_01",
            candidate_identity="1" * 64,
            config_hash="a" * 64,
            code_revision="",
            selection_metric="rmse",
            selection_value="9.0",
            guardrail_status="not_applicable",
            status="baseline",
        )
        self.assertNotIn(
            "missing_provenance", finalize_run_module._candidate_events([], [config_only])
        )
        runner_only = journal_row(
            experiment_id="exp_02",
            candidate_identity="2" * 64,
            runner_hash="b" * 64,
            code_revision="",
            config_hash="",
        )
        self.assertNotIn(
            "missing_provenance", finalize_run_module._candidate_events([], [runner_only])
        )
        empty = journal_row(
            experiment_id="exp_03",
            candidate_identity="",
            code_revision="",
            config_hash="",
            runner_hash="",
            input_manifest_hash="",
            prediction_hash="",
        )
        self.assertIn(
            "missing_provenance", finalize_run_module._candidate_events([], [empty])
        )

    def test_finalization_accepts_config_only_candidate_without_git_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.build_project(root)
            self.create_run(root, "config-only")
            self.configure_finalizable_contract(root, "config-only")
            run_dir = root / ".agent-system" / "runs" / "config-only"
            baseline = journal_row(
                experiment_id="exp_01",
                candidate_identity="",
                code_revision="",
                config_hash="f" * 64,
                selection_metric="rmse",
                selection_value="9.0",
                guardrail_status="not_applicable",
                status="baseline",
            )
            recorded = self.record(root, "config-only", baseline)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            rows, _ = validate_kit.read_experiment_journal(run_dir / "experiments.tsv", root)
            self.assertEqual(64, len(rows[0]["candidate_identity"]))
            self.assertEqual("", rows[0]["code_revision"])
            # Move to the finalization decision without rewriting the recorded
            # config-only journal row.
            run_path = run_dir / "run.yaml"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            summary = run["results"]["experiment_summary"]
            summary["stopping_reason"] = "plateau"
            summary["lifecycle"]["research_decision"] = "reject"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            learning_path = run_dir / "learning.yaml"
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            learning["no_reusable_signal_reason"] = "Nothing reusable."
            learning_path.write_text(json.dumps(learning, indent=2) + "\n", encoding="utf-8")
            finalize = self.finalize(root, "config-only")
            self.assertEqual(0, finalize.returncode, finalize.stdout + finalize.stderr)
            summary = json.loads((run_dir / "run.yaml").read_text(encoding="utf-8"))[
                "results"
            ]["experiment_summary"]
            self.assertNotIn("missing_provenance", summary["candidate_learning_events"])
            self.assertEqual("finalized", summary["lifecycle"]["evidence_status"])

    # ------------------------------------------------------------------
    # Reconstruction of every documented prompt family (no metric ontology)
    # ------------------------------------------------------------------

    def test_reconstruction_keeps_secondary_business_metric_from_lean_form(self) -> None:
        draft = reconstruct_contract.reconstruct(
            "Selection metric: out-of-sample RMSE, minimize.\n"
            "Report FA as a secondary business metric."
        )
        self.assertEqual("rmse", draft["selection_objective"]["metric"])
        self.assertEqual("minimize", draft["selection_objective"]["direction"])
        self.assertEqual(
            [{"metric": "fa", "role": "reporting", "direction": "", "max_degradation": None}],
            draft["secondary_metrics"],
        )
        self.assertIn("out of sample", draft["evaluation_qualifiers"])
        # FA is NOT invented as maximizing; only the user wording is recorded.
        self.assertIn("fa", draft["unresolved_directions"])

    def test_reconstruction_of_non_forecasting_optimize_prompt(self) -> None:
        draft = reconstruct_contract.reconstruct(
            "Optimize cross-validated AUROC; keep p99 inference latency roughly flat."
        )
        self.assertEqual("auroc", draft["selection_objective"]["metric"])
        self.assertIn("cross validated", draft["evaluation_qualifiers"])
        secondary = draft["secondary_metrics"]
        self.assertEqual(1, len(secondary))
        self.assertEqual("guardrail", secondary[0]["role"])
        self.assertEqual("p99inferencelatency", secondary[0]["metric"])
        self.assertIn("auroc", draft["unresolved_directions"])
        # No hard-coded AUROC or latency semantics: direction stays unresolved.
        self.assertEqual("", secondary[0]["direction"])

    def test_reconstruction_binds_explicit_role_phrases(self) -> None:
        draft = reconstruct_contract.reconstruct(
            "Selection objective: holdout AUROC, maximize. "
            "Use recall_at_100 as a guardrail. Keep p99 latency below 40ms. "
            "Report calibration_error as a secondary metric."
        )
        self.assertEqual("auroc", draft["selection_objective"]["metric"])
        self.assertEqual("maximize", draft["selection_objective"]["direction"])
        roles = {entry["metric"]: entry["role"] for entry in draft["secondary_metrics"]}
        self.assertEqual(
            {"recallat100": "guardrail", "p99latency": "guardrail", "calibrationerror": "reporting"},
            roles,
        )

    def test_reconstruction_trims_non_metric_clauses_from_optimize_phrase(self) -> None:
        draft = reconstruct_contract.reconstruct(
            "Optimize PR-AUC, max 15 experiments, and do not let recall_at_100 regress."
        )
        self.assertEqual("prauc", draft["selection_objective"]["metric"])
        self.assertEqual(["recallat100"], [e["metric"] for e in draft["secondary_metrics"]])
        self.assertEqual("guardrail", draft["secondary_metrics"][0]["role"])


if __name__ == "__main__":
    unittest.main()
