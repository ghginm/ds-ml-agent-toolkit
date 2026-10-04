#!/usr/bin/env python3
"""Build the deployable DS/ML project overlay deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "project-overlay"

COPY_TREES = {
    ".agents/skills": ".agents/skills",
    "adapters": "adapters",
}
COPY_FILES = {
    "VERSION": ".agent-system/VERSION",
    ".agent-system/CONTROL.md": ".agent-system/CONTROL.md",
    ".agent-system/SYSTEM.md": ".agent-system/SYSTEM.md",
    ".agent-system/docs/LEARNING_LOOP.md": ".agent-system/docs/LEARNING_LOOP.md",
    ".agent-system/workflows/autoresearch.md": ".agent-system/workflows/autoresearch.md",
    ".agent-system/workflows/independent-validation.md": ".agent-system/workflows/independent-validation.md",
    ".agent-system/workflows/technical-report.md": ".agent-system/workflows/technical-report.md",
    ".agent-system/policy/capability-policy.template.yaml": ".agent-system/policy/capability-policy.template.yaml",
    ".agent-system/project.template.yaml": ".agent-system/project.template.yaml",
    ".agent-system/local/.gitignore": ".agent-system/local/.gitignore",
    ".agent-system/schemas/learning.schema.json": ".agent-system/schemas/learning.schema.json",
    ".agent-system/schemas/request-event.schema.json": ".agent-system/schemas/request-event.schema.json",
    ".agent-system/schemas/request-patterns.schema.json": ".agent-system/schemas/request-patterns.schema.json",
    ".agent-system/schemas/evaluation.schema.json": ".agent-system/schemas/evaluation.schema.json",
    ".agent-system/schemas/project.schema.json": ".agent-system/schemas/project.schema.json",
    ".agent-system/schemas/run.schema.json": ".agent-system/schemas/run.schema.json",
    ".agent-system/templates/PROJECT_MAP.template.md": ".agent-system/templates/PROJECT_MAP.template.md",
    ".agent-system/templates/finding-report.template.md": ".agent-system/templates/finding-report.template.md",
    ".agent-system/templates/learning.template.yaml": ".agent-system/templates/learning.template.yaml",
    ".agent-system/templates/evaluation.template.yaml": ".agent-system/templates/evaluation.template.yaml",
    ".agent-system/templates/run.template.yaml": ".agent-system/templates/run.template.yaml",
    ".agent-system/templates/AGENTS.dsml.template.md": "AGENTS.dsml.template.md",
    "tooling/create-run.py": ".agent-system/tooling/create-run.py",
    "tooling/finalize-run.py": ".agent-system/tooling/finalize-run.py",
    "tooling/git_preflight.py": ".agent-system/tooling/git_preflight.py",
    "tooling/onboard-project.py": ".agent-system/tooling/onboard-project.py",
    "tooling/record-request.py": ".agent-system/tooling/record-request.py",
    "tooling/reconstruct-contract.py": ".agent-system/tooling/reconstruct-contract.py",
    "tooling/record-experiment.py": ".agent-system/tooling/record-experiment.py",
    "tooling/request_events.py": ".agent-system/tooling/request_events.py",
    "tooling/review-requests.py": ".agent-system/tooling/review-requests.py",
    "tooling/validate-kit.py": ".agent-system/tooling/validate-kit.py",
}


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"runtime source must be a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def populate_overlay(destination: Path) -> None:
    """Populate an empty destination from the explicit runtime manifest."""
    destination.mkdir(parents=True, exist_ok=False)
    for source_name, destination_name in sorted(COPY_TREES.items()):
        source_root = ROOT / source_name
        for source in sorted(source_root.rglob("*")):
            if source.is_symlink():
                raise ValueError(f"runtime source must not contain symlinks: {source}")
            if source.is_file():
                relative = source.relative_to(source_root)
                _copy_file(source, destination / destination_name / relative)
    for source_name, destination_name in sorted(COPY_FILES.items()):
        _copy_file(ROOT / source_name, destination / destination_name)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    files = {
        str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    manifest = {
        "schema_version": "0.2",
        "toolkit_version": version,
        "files": files,
    }
    manifest_path = destination / ".agent-system" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_snapshot(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def build_overlay(output: Path, check: bool = False) -> bool:
    """Build atomically, or return whether an existing output is current."""
    output = output.resolve()
    if output == ROOT or output in ROOT.parents:
        raise ValueError("overlay output must not replace the source repository")
    if output.is_relative_to(ROOT) and "dist" not in output.relative_to(ROOT).parts:
        raise ValueError(
            "overlay output inside the source repository is only allowed under dist/"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".project-overlay-", dir=output.parent) as directory:
        staged = Path(directory) / "overlay"
        populate_overlay(staged)
        if check:
            return _file_snapshot(staged) == _file_snapshot(output)

        backup = Path(directory) / "previous"
        if output.exists():
            output.rename(backup)
        try:
            staged.rename(output)
        except Exception:
            if backup.exists() and not output.exists():
                backup.rename(output)
            raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail when output differs")
    args = parser.parse_args()
    current = build_overlay(args.output, check=args.check)
    if args.check and not current:
        print(f"FAILED: overlay drift detected at {args.output}")
        return 1
    action = "current" if args.check else "built"
    print(f"PASS: project overlay {action} at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
