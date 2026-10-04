#!/usr/bin/env python3
"""Transactionally finalize a DS/ML Agent Kit autoresearch run."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
TOOLING_DIR = SCRIPT_PATH.parent
if str(TOOLING_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLING_DIR))
import git_preflight

VALIDATOR_PATH = TOOLING_DIR / "validate-kit.py"
SPEC = importlib.util.spec_from_file_location("dsml_validate_kit", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load validator: {VALIDATOR_PATH}")
validate_kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_kit)


def _load_object(path: Path, root: Path) -> dict[str, Any]:
    value = validate_kit.load_json(path, root)
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(root)} must contain an object")
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _git_errors(root: Path) -> list[str]:
    try:
        state = git_preflight.preflight(root, git_mode="required")
    except (OSError, ValueError) as exc:
        return [f"cannot inspect Git repository state: {exc}"]
    return git_preflight.git_requirement_errors(state, root)


def _final_split_identity(evaluation: dict[str, Any]) -> dict[str, Any]:
    contract = evaluation.get("evaluation")
    contract = contract if isinstance(contract, dict) else {}
    identity = contract.get("final_split_identity")
    return identity if isinstance(identity, dict) else {}


def _candidate_events(
    evaluation_errors: list[str],
    rows: list[dict[str, str]],
) -> list[str]:
    events: set[str] = set()
    combined = "\n".join(evaluation_errors).lower()
    if "point-in-time" in combined or "label_available_at" in combined:
        events.add("point_in_time_violation")
    if "previously exposed" in combined:
        events.add("holdout_reuse")
    if "selection_metric" in combined and "objective" in combined:
        events.add("metric_disagreement")
    if "disagrees with metrics_json" in combined:
        events.add("metric_disagreement")
    if "selected experiment" in combined and (
        "mismatch" in combined or "resolve to exactly one" in combined
    ):
        events.add("selected_experiment_mismatch")
    if "guardrail" in combined:
        events.add("guardrail_failure")
    if "untracked evidence" in combined or "missing canonical" in combined:
        events.add("untracked_evidence")
    if any(row.get("status") == "duplicate" and row.get("config_hash") for row in rows):
        events.add("duplicate_config")
    if any(row.get("status") == "duplicate" and row.get("prediction_hash") for row in rows):
        events.add("duplicate_predictions")
    # Artifact-agnostic provenance contract: enough immutable material to
    # uniquely identify what candidate was evaluated. A Git revision is one
    # sufficient artifact among several (config/runner/input-manifest/prediction
    # hashes or an explicit candidate_identity), never a mandatory one —
    # config-only candidates are legitimate across DS/ML projects.
    immutable_artifacts = (
        "code_revision",
        "config_hash",
        "runner_hash",
        "input_manifest_hash",
        "prediction_hash",
    )
    if any(
        not row.get("candidate_identity", "").strip()
        or not any(row.get(field, "").strip() for field in immutable_artifacts)
        for row in rows
    ):
        events.add("missing_provenance")
    return sorted(events)


def _merged_candidate_events(
    summary: dict[str, Any],
    derived: list[str],
    explicit: tuple[str, ...],
) -> list[str]:
    stored = summary.get("candidate_learning_events")
    stored = [item for item in stored if isinstance(item, str)] if isinstance(stored, list) else []
    return sorted(set(stored) | set(derived) | set(explicit))


def finalize_run(
    root: Path,
    run_id: str,
    explicit_events: tuple[str, ...] = (),
) -> list[str]:
    """Validate current state, then finalize (or succeed idempotently).

    An already-finalized run is still fully validated: validation is never
    skipped because ``evidence_status`` claims completion. Invalid evidence
    fails even when manually marked finalized. Valid re-finalization repeats
    nothing: a finalized record is terminal and immutable, so finalization
    performs zero writes once ``evidence_status`` is ``finalized`` — it neither
    rewrites ``run.yaml`` nor appends ledger events. Diagnostic event
    persistence applies only while a run is still open.
    """
    root = root.expanduser().resolve(strict=True)
    run_dir = root / ".agent-system" / "runs" / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        return [f"run does not exist as a canonical directory: {run_id}"]
    paths = {
        "run": run_dir / "run.yaml",
        "evaluation": run_dir / "evaluation.yaml",
        "learning": run_dir / "learning.yaml",
        "journal": run_dir / "experiments.tsv",
    }
    errors = _git_errors(root)
    for label, path in paths.items():
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing canonical {label} artifact: {path.relative_to(root)}")
    if errors:
        return errors

    run = _load_object(paths["run"], root)
    evaluation = _load_object(paths["evaluation"], root)
    learning = _load_object(paths["learning"], root)
    run_schema = _load_object(root / ".agent-system" / "schemas" / "run.schema.json", root)
    evaluation_schema = _load_object(
        root / ".agent-system" / "schemas" / "evaluation.schema.json", root
    )
    learning_schema = _load_object(
        root / ".agent-system" / "schemas" / "learning.schema.json", root
    )
    errors.extend(f"run.yaml: {item}" for item in validate_kit.schema_errors(run, run_schema))
    errors.extend(
        f"evaluation.yaml: {item}"
        for item in validate_kit.schema_errors(evaluation, evaluation_schema)
    )
    errors.extend(
        f"learning.yaml: {item}"
        for item in validate_kit.schema_errors(learning, learning_schema)
    )

    ledger_records, ledger_errors = validate_kit.load_evaluation_ledger(root)
    errors.extend(ledger_errors)
    # Pass the complete ledger: the untouched-claim check is order-aware and
    # must see this run's own reservation position to judge exposure as of its
    # commit time instead of conflating it with later cross-run exposure.
    evaluation_errors = validate_kit.evaluation_semantic_errors(
        evaluation,
        paths["evaluation"],
        root,
        ledger_records=ledger_records,
    )
    errors.extend(evaluation_errors)
    errors.extend(validate_kit.learning_semantic_errors(learning, paths["learning"], root))
    rows, journal_read_errors = validate_kit.read_experiment_journal(paths["journal"], root)
    errors.extend(journal_read_errors)

    results = run.get("results")
    results = results if isinstance(results, dict) else {}
    summary = results.get("experiment_summary")
    summary = summary if isinstance(summary, dict) else {}
    lifecycle = summary.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    already_finalized = lifecycle.get("evidence_status") == "finalized"
    selected = summary.get("selected_experiment")
    journal_errors = validate_kit.experiment_journal_errors(
        rows, evaluation, selected if isinstance(selected, dict) else None
    )
    errors.extend(journal_errors)
    errors.extend(validate_kit.run_semantic_errors(run, paths["run"], root))

    for row in rows:
        artifact_ref = row.get("artifact_ref", "").strip()
        if not artifact_ref or "://" in artifact_ref:
            continue
        artifact_path = (run_dir / artifact_ref).resolve(strict=False)
        try:
            artifact_path.relative_to(root)
        except ValueError:
            errors.append(
                f"untracked evidence for {row.get('experiment_id')}: artifact_ref escapes project root"
            )
            continue
        if artifact_path.is_symlink() or not artifact_path.is_file():
            errors.append(
                f"untracked evidence for {row.get('experiment_id')}: missing artifact {artifact_ref}"
            )
            continue
        prediction_hash = row.get("prediction_hash", "").strip()
        if prediction_hash:
            actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if actual_hash != prediction_hash:
                errors.append(
                    f"missing provenance for {row.get('experiment_id')}: prediction_hash does not match {artifact_ref}"
                )

    if summary.get("format_version") != "0.2":
        errors.append("run is not opted into transactional autoresearch finalization")
    if lifecycle.get("evidence_status") not in {"open", "finalized"}:
        errors.append("evidence_status must be open or finalized before finalization")
    if lifecycle.get("research_decision") not in {"accept", "reject"}:
        errors.append("research_decision must be accept or reject before finalization")
    if summary.get("stopping_reason") in {None, "not_started"}:
        errors.append("stopping_reason must describe why research stopped")
    if learning.get("no_reusable_signal_reason") == "Not assessed until run finalization.":
        errors.append("learning record must be reviewed before finalization")
    novel_count = validate_kit.novel_experiment_count(rows)
    if summary.get("experiments_run") != novel_count:
        errors.append(
            "experiments_run must equal valid novel journal experiments "
            "(baseline, duplicate, invalid, and crashed rows excluded)"
        )
    budget = summary.get("budget")
    if isinstance(budget, int) and not isinstance(budget, bool) and novel_count > budget:
        errors.append(
            f"budget_consumed {novel_count} exceeds the hard experiment budget {budget}"
        )

    derived = _candidate_events(errors, rows)
    unknown_events = sorted(set(explicit_events) - validate_kit.CANDIDATE_EVENT_TYPES)
    if unknown_events:
        errors.append("unknown candidate events: " + ", ".join(unknown_events))
    known_explicit = tuple(
        item for item in explicit_events if item in validate_kit.CANDIDATE_EVENT_TYPES
    )
    merged_events = _merged_candidate_events(summary, derived, known_explicit)

    # The exposure event must already be committed: record-experiment.py
    # requires a reservation before a stage-final result may be recorded, so a
    # final journal row without a ledger event can only mean the ledger was
    # bypassed or edited. Finalization verifies exposure and never creates or
    # repairs it — a completion step must not be the first creator of the
    # scientific record.
    identity = _final_split_identity(evaluation)
    split_key = validate_kit._final_split_key(identity)
    final_evaluated = any(
        row.get("stage") == "final" and row.get("status") in validate_kit.EVALUATED_STATUSES
        for row in rows
    )
    exposure_event = (
        validate_kit.final_exposure_event(run_id, identity)
        if split_key is not None and final_evaluated
        else None
    )
    ledger_has_exposure = exposure_event is not None and any(
        record.get("event_id") == exposure_event["event_id"] for record in ledger_records
    )
    if exposure_event is not None and not ledger_has_exposure:
        errors.append(
            "protected final evaluation was recorded without a committed exposure "
            "reservation; run record-experiment.py --reserve-final-exposure before "
            "executing or observing the protected evaluation"
        )

    if errors:
        # Diagnostic candidate events are durable while the run is still open:
        # they are the evidence the learning loop needs precisely because the
        # run did not finalize. A finalized record is immutable: reporting
        # failures must not rewrite it. This write changes no lifecycle state
        # and never touches the ledger.
        if (
            not already_finalized
            and merged_events != summary.get("candidate_learning_events")
            and isinstance(results.get("experiment_summary"), dict)
        ):
            summary["candidate_learning_events"] = merged_events
            results["experiment_summary"] = summary
            run["results"] = results
            _atomic_write(paths["run"], json.dumps(run, indent=2) + "\n")
        return errors

    if already_finalized:
        if merged_events != summary.get("candidate_learning_events"):
            errors.append(
                "finalized evidence is immutable: explicit --candidate-event mutation "
                "is refused on a finalized run"
            )
            return errors
        # Valid and already finalized: succeed idempotently with zero writes —
        # no journal transitions, exposure records, learning events, or file
        # rewrites. Finalized evidence is terminal.
        return []

    if merged_events != summary.get("candidate_learning_events") and isinstance(
        results.get("experiment_summary"), dict
    ):
        summary["candidate_learning_events"] = merged_events
        results["experiment_summary"] = summary
        run["results"] = results

    lifecycle["evidence_status"] = "finalized"
    summary["lifecycle"] = lifecycle
    results["experiment_summary"] = summary
    run["results"] = results
    _atomic_write(paths["run"], json.dumps(run, indent=2) + "\n")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--candidate-event",
        action="append",
        default=[],
        choices=sorted(validate_kit.CANDIDATE_EVENT_TYPES),
        help=(
            "explicitly record a candidate learning event that generic evidence "
            "cannot infer (for example user_rejection); never auto-invented"
        ),
    )
    args = parser.parse_args()
    try:
        errors = finalize_run(
            args.project_root, args.run_id, tuple(args.candidate_event)
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    if errors:
        print(f"FAILED: run {args.run_id} was not finalized")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS: finalized .agent-system/runs/{args.run_id}/run.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
