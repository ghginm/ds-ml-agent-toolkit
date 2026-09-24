#!/usr/bin/env python3
"""Initialize a tracked run with task evidence and compact learning metadata."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import date
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
ROOT = (
    SCRIPT_PATH.parents[2]
    if SCRIPT_PATH.parent.parent.name == ".agent-system"
    else SCRIPT_PATH.parents[1]
)
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"


def _load_template(name: str) -> dict[str, object]:
    path = ROOT / ".agent-system" / "templates" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"template must contain an object: {path}")
    return value


def _toolkit_version() -> str:
    """Read the canonical release version in source or installed layout."""
    candidates = (ROOT / "VERSION", ROOT / ".agent-system" / "VERSION")
    version_path = next((path for path in candidates if path.is_file()), None)
    if version_path is None:
        raise ValueError("toolkit VERSION file is missing")
    version = version_path.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError(f"invalid toolkit version in {version_path}")
    return version


def create_run(
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
) -> tuple[Path, Path]:
    """Create a new run directory and both records without overwriting."""
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

    agent_system = ROOT / ".agent-system"
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
    run["task"]["id"] = run_id
    run["task"]["goal"] = goal
    run["task"]["acceptance"] = acceptance
    active_policy = ROOT / ".agent-system" / "policy" / "capability-policy.yaml"
    if active_policy.is_file():
        run["policy"]["policy_ref"] = ".agent-system/policy/capability-policy.yaml"

    learning["timestamp"] = date.today().isoformat()
    learning["toolkit_version"] = _toolkit_version()
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

    run_dir.mkdir()
    run_path = run_dir / "run.yaml"
    learning_path = run_dir / "learning.yaml"
    try:
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        learning_path.write_text(
            json.dumps(learning, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(run_dir)
        raise
    return run_path, learning_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    )
    print(f"Created {run_path.relative_to(ROOT)}")
    print(f"Created {learning_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
