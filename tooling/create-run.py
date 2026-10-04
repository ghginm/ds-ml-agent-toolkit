#!/usr/bin/env python3
"""Initialize a tracked run with task evidence and compact learning metadata."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
TOOLING_DIR = SCRIPT_PATH.parent
if str(TOOLING_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLING_DIR))
import git_preflight

TOOLKIT_ROOT = (
    SCRIPT_PATH.parents[2]
    if SCRIPT_PATH.parent.parent.name == ".agent-system"
    else SCRIPT_PATH.parents[1]
)
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
EXPERIMENT_JOURNAL_HEADER = (
    "experiment_id\tparent_experiment_id\tstage\tcandidate_identity\tcode_revision\t"
    "config_hash\trunner_hash\tinput_manifest_hash\tprediction_hash\tselection_metric\t"
    "selection_value\tmetrics_json\tguardrail_status\tstatus\thypothesis\texpected_mechanism\t"
    "change_summary\tresult_summary\tnext_hypothesis_rationale\tmeaningful_improvement\t"
    "materially_new_evidence\tartifact_ref\n"
)


def _load_template(name: str) -> dict[str, Any]:
    path = TOOLKIT_ROOT / ".agent-system" / "templates" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"template must contain an object: {path}")
    return value


def _toolkit_version() -> str:
    """Read the canonical release version in source or installed layout."""
    candidates = (
        TOOLKIT_ROOT / "VERSION",
        TOOLKIT_ROOT / ".agent-system" / "VERSION",
    )
    version_path = next((path for path in candidates if path.is_file()), None)
    if version_path is None:
        raise ValueError("toolkit VERSION file is missing")
    version = version_path.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError(f"invalid toolkit version in {version_path}")
    return version


def resolve_project_root(value: Path) -> Path:
    """Resolve the explicit project root without requiring Git."""
    try:
        project_root = value.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"project root cannot be resolved: {value}") from exc
    if not project_root.is_dir():
        raise ValueError(f"project root is not a directory: {project_root}")
    agent_system = project_root / ".agent-system"
    if agent_system.is_symlink() or not agent_system.is_dir():
        raise ValueError(
            f"project root must contain a non-symlink .agent-system directory: {project_root}"
        )
    return project_root


def create_run(
    project_root: Path,
    run_id: str,
    goal: str,
    acceptance: list[str],
    request_kind: str,
    skill: str,
    mode: str,
    topics: list[str] | None = None,
    deliverable: str | None = None,
    initial_skill: str | None = None,
    initial_mode: str | None = None,
    autoresearch: bool = False,
    experiment_mode: str = "adaptive",
    max_experiments: int = 10,
) -> tuple[Path, Path]:
    """Create a new run directory and both records without overwriting."""
    project_root = resolve_project_root(project_root)
    git_state = git_preflight.preflight(
        project_root,
        git_mode="required" if autoresearch else "auto-detect",
    )
    if autoresearch:
        git_errors = git_preflight.git_requirement_errors(git_state, project_root)
        if git_errors:
            raise ValueError("; ".join(git_errors))
    if re.fullmatch(RUN_ID_PATTERN, run_id) is None:
        raise ValueError(
            "run ID must start with an alphanumeric and contain only letters, "
            "digits, ., _, or -"
        )
    if re.fullmatch(SLUG_PATTERN, request_kind) is None:
        raise ValueError("request kind must be a lowercase semantic slug")
    topic_values = topics or []
    if any(re.fullmatch(SLUG_PATTERN, topic) is None for topic in topic_values):
        raise ValueError("each topic must be a lowercase semantic slug")
    if len(topic_values) != len(set(topic_values)):
        raise ValueError("topics must not contain duplicates")
    if deliverable is not None and re.fullmatch(SLUG_PATTERN, deliverable) is None:
        raise ValueError("deliverable must be a lowercase semantic slug")
    if not goal.strip() or not acceptance or any(not item.strip() for item in acceptance):
        raise ValueError("goal and every acceptance criterion must be non-blank")
    if not skill.strip() or not mode.strip() or (
        (initial_skill is not None and not initial_skill.strip())
        or (initial_mode is not None and not initial_mode.strip())
    ):
        raise ValueError(
            "skill, mode, and initial skill/mode when present must be non-blank"
        )
    corrected = initial_skill is not None or initial_mode is not None
    if corrected and all(
        initial is None or initial == final
        for initial, final in ((initial_skill, skill), (initial_mode, mode))
    ):
        raise ValueError("corrected routing must differ from the initial routing")

    agent_system = project_root / ".agent-system"
    runs_root = agent_system / "runs"
    if agent_system.is_symlink() or runs_root.is_symlink():
        raise ValueError("run records must not be created through symlinked directories")
    runs_root.mkdir(exist_ok=True)
    run_dir = runs_root / run_id
    run_dir.resolve().relative_to(runs_root.resolve())
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")

    run = _load_template("run.template.yaml")
    learning = _load_template("learning.template.yaml")
    evaluation = _load_template("evaluation.template.yaml") if autoresearch else None
    run["task"]["id"] = run_id
    run["task"]["goal"] = goal
    run["task"]["acceptance"] = acceptance
    if git_state["status"] == "repository":
        run["provenance"]["repository"]["revision"] = git_state["head"]
        run["provenance"]["repository"]["working_tree"] = git_state["worktree"]
        run["provenance"]["repository"]["diff_ref"] = git_state["upstream"]
    else:
        run["provenance"]["repository"]["working_tree"] = "not_applicable"
    active_policy = project_root / ".agent-system" / "policy" / "capability-policy.yaml"
    if active_policy.is_file():
        run["policy"]["policy_ref"] = ".agent-system/policy/capability-policy.yaml"

    learning["timestamp"] = date.today().isoformat()
    learning["toolkit_version"] = _toolkit_version()
    learning["schema_version"] = "0.4"
    learning["no_reusable_signal_reason"] = "Not assessed until run finalization."
    learning["run_ref"] = f".agent-system/runs/{run_id}/run.yaml"
    learning["request"] = {
        "kind": request_kind,
        "topics": topic_values,
        "deliverable": deliverable,
    }
    learning["routing"] = {
        "skill": skill,
        "mode": mode,
        "initial_skill": initial_skill,
        "initial_mode": initial_mode,
        "corrected": corrected,
    }
    learning["outcome"] = {
        "execution": "not_run",
        "user_outcome": "unknown",
        "reason_tags": [],
    }
    if autoresearch:
        if experiment_mode not in {"benchmark", "adaptive"}:
            raise ValueError("experiment mode must be benchmark or adaptive")
        if max_experiments < 1:
            raise ValueError("max experiments must be positive")
        run["schema_version"] = "0.2"
        run["results"]["experiment_summary"] = {
            "format_version": "0.2",
            "budget": max_experiments,
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
        assert evaluation is not None
        evaluation["experiment_mode"] = experiment_mode
        evaluation["candidate_plan"] = (
            "predeclared" if experiment_mode == "benchmark" else "sequential"
        )
        evaluation["adaptive_evolution"] = (
            "not_applicable" if experiment_mode == "benchmark" else "observed"
        )

    run_dir.mkdir()
    run_path = run_dir / "run.yaml"
    learning_path = run_dir / "learning.yaml"
    journal_path = run_dir / "experiments.tsv"
    evaluation_path = run_dir / "evaluation.yaml"
    try:
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        learning_path.write_text(
            json.dumps(learning, indent=2) + "\n", encoding="utf-8"
        )
        if autoresearch:
            journal_path.write_text(EXPERIMENT_JOURNAL_HEADER, encoding="utf-8")
            assert evaluation is not None
            evaluation_path.write_text(
                json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
            )
    except Exception:
        shutil.rmtree(run_dir)
        raise
    return run_path, learning_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        required=True,
        type=Path,
        help="canonical user repository root that owns durable run evidence",
    )
    parser.add_argument(
        "--autoresearch",
        action="store_true",
        help="initialize the canonical experiments.tsv journal",
    )
    parser.add_argument(
        "--experiment-mode",
        choices=("benchmark", "adaptive"),
        default="adaptive",
    )
    parser.add_argument("--max-experiments", type=int, default=10)
    parser.add_argument("--id", required=True, dest="run_id")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--acceptance", required=True, action="append")
    parser.add_argument("--request-kind", required=True)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--deliverable")
    parser.add_argument("--initial-skill")
    parser.add_argument("--initial-mode")
    args = parser.parse_args()
    run_path, learning_path = create_run(
        project_root=args.project_root,
        run_id=args.run_id,
        goal=args.goal,
        acceptance=args.acceptance,
        request_kind=args.request_kind,
        skill=args.skill,
        mode=args.mode,
        topics=args.topic,
        deliverable=args.deliverable,
        initial_skill=args.initial_skill,
        initial_mode=args.initial_mode,
        autoresearch=args.autoresearch,
        experiment_mode=args.experiment_mode,
        max_experiments=args.max_experiments,
    )
    project_root = args.project_root.expanduser().resolve(strict=True)
    print(f"Created {run_path.relative_to(project_root)}")
    print(f"Created {learning_path.relative_to(project_root)}")
    if args.autoresearch:
        print(f"Created {(run_path.parent / 'experiments.tsv').relative_to(project_root)}")
        print(f"Created {(run_path.parent / 'evaluation.yaml').relative_to(project_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
