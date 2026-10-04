#!/usr/bin/env python3
"""Create and verify project-owned DS/ML Agent Kit onboarding state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TOOLING_DIR = Path(__file__).resolve().parent
if str(TOOLING_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLING_DIR))
import git_preflight

CORE_SKILLS = {
    "analyze-dsml-project",
    "execute-dsml-task",
    "validate-dsml-result",
}
BUNDLED_SPECIALIZED_SKILLS = {"autoresearch", "compose-dsml-report"}
VALID_HARNESSES = {"codex", "copilot", "hermes", "unknown"}
VALIDATION_COMMAND = "python3 -B .agent-system/tooling/validate-kit.py --installed-project ."
STATUS_CAPABILITIES = (
    ("Ordinary repository read", "authorized_repository_read"),
    ("Safe local validation", "safe_local_validation"),
    ("Full/distributed training", "costly_compute"),
    ("Remote ML-system writes", "remote_ml_system_write"),
    ("Production data mutation", "production_data_mutation"),
)


def _relative_project_path(root: Path, path: Path) -> Path:
    root = root.resolve()
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"write destination is outside repository root: {path}") from exc
    if relative == Path(".") or not relative.name:
        raise ValueError(f"write destination must be a file inside repository root: {path}")
    return relative


def _reject_symlink_components(root: Path, path: Path) -> Path:
    relative = _relative_project_path(root, path)
    current = root.resolve()
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                f"project-owned path must not be a symbolic link or contain one: {relative}"
            )
        if not current.exists():
            break
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"project-owned path resolves outside repository root: {relative}") from exc
    return relative


def _safe_write_non_posix(root: Path, path: Path, content: str, relative: Path) -> None:
    """Write a repository-owned file outside POSIX semantics. The caller has
    already verified the destination through ``_reject_symlink_components``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        temporary.write_text(content, encoding="utf-8")
        if path.is_symlink():
            raise ValueError(
                f"project-owned path must not be a symbolic link: {relative}"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_write(root: Path, path: Path, content: str) -> None:
    """Atomically write a repository-owned file without following symlinks."""
    root = root.resolve()
    relative = _reject_symlink_components(root, path)

    if os.name != "posix":
        _safe_write_non_posix(root, path, content, relative)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(root, flags)
    try:
        for part in relative.parent.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=directory_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags | nofollow, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd

        try:
            destination_stat = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and not stat.S_ISREG(destination_stat.st_mode):
            kind = "symbolic link" if stat.S_ISLNK(destination_stat.st_mode) else "non-file"
            raise ValueError(f"project-owned path must not be a {kind}: {relative}")

        temporary_name = f".{relative.name}.{secrets.token_hex(8)}.tmp"
        destination_mode = (
            stat.S_IMODE(destination_stat.st_mode) if destination_stat is not None else 0o644
        )
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            destination_mode,
            dir_fd=directory_fd,
        )
        try:
            os.fchmod(descriptor, destination_mode)
            stream = os.fdopen(descriptor, "w", encoding="utf-8")
            descriptor = -1
            with stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                destination_stat = os.stat(
                    relative.name, dir_fd=directory_fd, follow_symlinks=False
                )
            except FileNotFoundError:
                destination_stat = None
            if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
                raise ValueError(
                    f"project-owned path must not be a symbolic link: {relative}"
                )
            os.replace(
                temporary_name,
                relative.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def repair_runtime(root: Path, clean_overlay: Path) -> list[str]:
    """Restore only manifest-owned runtime files from a trusted same-version overlay."""
    root = root.expanduser().resolve(strict=True)
    clean_overlay = clean_overlay.expanduser().resolve(strict=True)
    source_manifest_path = clean_overlay / ".agent-system" / "manifest.json"
    source_manifest = _read_json(source_manifest_path)
    if source_manifest.get("schema_version") != "0.2":
        raise ValueError("repair source manifest must use schema_version '0.2'")
    files = source_manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("repair source manifest must contain runtime files")
    source_version = source_manifest.get("toolkit_version")
    if not isinstance(source_version, str) or not source_version.strip():
        raise ValueError("repair source manifest toolkit_version is invalid")
    installed_version_path = root / ".agent-system" / "VERSION"
    if installed_version_path.exists():
        _reject_symlink_components(root, installed_version_path)
        installed_version = installed_version_path.read_text(encoding="utf-8").strip()
        if installed_version != source_version:
            raise ValueError(
                "repair source version does not match the installed toolkit version"
            )

    repaired: list[str] = []
    for relative, expected_hash in sorted(files.items()):
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"repair source manifest has unsafe path {relative!r}")
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise ValueError(f"repair source manifest has invalid hash for {relative}")
        source = clean_overlay / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"repair source runtime file is missing or unsafe: {relative}")
        content = source.read_text(encoding="utf-8")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != expected_hash:
            raise ValueError(f"repair source runtime hash mismatch: {relative}")
        target = root / relative
        _reject_symlink_components(root, target)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current is None or hashlib.sha256(current.encode("utf-8")).hexdigest() != expected_hash:
            _safe_write(root, target, content)
            repaired.append(relative)

    source_manifest_text = source_manifest_path.read_text(encoding="utf-8")
    target_manifest_path = root / ".agent-system" / "manifest.json"
    _reject_symlink_components(root, target_manifest_path)
    target_manifest_text = (
        target_manifest_path.read_text(encoding="utf-8")
        if target_manifest_path.is_file()
        else None
    )
    if target_manifest_text != source_manifest_text:
        _safe_write(root, target_manifest_path, source_manifest_text)
        repaired.append(".agent-system/manifest.json")
    return repaired


def _active_markdown_lines(text: str) -> list[str]:
    active: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[0]
            length = len(stripped) - len(stripped.lstrip(marker))
            if fence is None:
                fence = (marker, length)
            elif marker == fence[0] and length >= fence[1]:
                fence = None
            continue
        if fence is None:
            active.append(line)
    return active


def _normalized_instruction_lines(path: Path) -> set[str]:
    return {
        " ".join(line.split())
        for line in _active_markdown_lines(path.read_text(encoding="utf-8"))
        if line.lstrip().startswith("- ")
    }


def _instructions_are_complete(target_text: str, sources: tuple[Path, ...]) -> bool:
    target_lines = {" ".join(line.split()) for line in _active_markdown_lines(target_text)}
    required_lines = set().union(*(_normalized_instruction_lines(source) for source in sources))
    return bool(required_lines) and required_lines.issubset(target_lines)


def _policy_action_buckets(policy: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    actions = policy.get("actions")
    expected = {"allowed", "approval_required", "forbidden"}
    if not isinstance(actions, dict) or set(actions) != expected:
        return None
    buckets: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for decision in expected:
        entries = actions.get(decision)
        if not isinstance(entries, list) or not entries:
            return None
        bucket: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            capability = entry.get("id")
            scope = entry.get("scope")
            if (
                not isinstance(capability, str)
                or not capability.strip()
                or not isinstance(scope, str)
                or not scope.strip()
                or capability in seen
            ):
                return None
            seen.add(capability)
            bucket[capability] = scope
        buckets[decision] = bucket
    return buckets


def _active_policy_is_valid(
    policy: dict[str, Any], template: dict[str, Any]
) -> tuple[bool, dict[str, str]]:
    approval = policy.get("approval")
    if not (
        policy.get("policy_status") == "approved_project_policy"
        and isinstance(approval, dict)
        and isinstance(approval.get("authority"), str)
        and bool(approval["authority"].strip())
        and isinstance(approval.get("evidence_ref"), str)
        and bool(approval["evidence_ref"].strip())
    ):
        return False, {}
    immutable_sections = (
        "schema_version",
        "instruction_precedence",
        "decision_rule",
        "default_decisions",
        "fallback_when_capability_absent",
        "artifact_data_rules",
    )
    if any(policy.get(key) != template.get(key) for key in immutable_sections):
        return False, {}
    template_buckets = _policy_action_buckets(template)
    active_buckets = _policy_action_buckets(policy)
    if template_buckets is None or active_buckets is None:
        return False, {}
    template_entries = {
        capability: scope
        for bucket in template_buckets.values()
        for capability, scope in bucket.items()
    }
    active_entries = {
        capability: scope
        for bucket in active_buckets.values()
        for capability, scope in bucket.items()
    }
    if active_entries != template_entries:
        return False, {}
    for fixed_bucket in ("allowed", "forbidden"):
        if not set(template_buckets[fixed_bucket]).issubset(active_buckets[fixed_bucket]):
            return False, {}
    decisions = {
        capability: decision
        for decision, entries in active_buckets.items()
        for capability in entries
    }
    return True, decisions


def _effective_capability_decisions(root: Path) -> tuple[str, dict[str, str]]:
    policy_dir = root / ".agent-system" / "policy"
    active = policy_dir / "capability-policy.yaml"
    active_present = active.exists() or active.is_symlink() or active.is_file()
    template_path = policy_dir / "capability-policy.template.yaml"
    try:
        template = _read_json(template_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return "invalid capability policy template", {
            capability: "unknown" for _, capability in STATUS_CAPABILITIES
        }
    if active_present:
        try:
            _reject_symlink_components(root, active)
        except ValueError:
            return "invalid active policy", {
                capability: "unknown" for _, capability in STATUS_CAPABILITIES
            }
        path = active
        source = "active project policy"
    else:
        path = template_path
        source = "conservative template defaults"
    try:
        policy = _read_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        invalid_source = "invalid active policy" if active_present else "invalid capability policy template"
        return invalid_source, {
            capability: "unknown" for _, capability in STATUS_CAPABILITIES
        }
    if active_present:
        valid, decisions = _active_policy_is_valid(policy, template)
        if not valid:
            return "invalid active policy", {
                capability: "unknown" for _, capability in STATUS_CAPABILITIES
            }
    else:
        buckets = _policy_action_buckets(policy)
        if buckets is None:
            return "invalid capability policy template", {
                capability: "unknown" for _, capability in STATUS_CAPABILITIES
            }
        decisions = {
            capability: decision
            for decision, entries in buckets.items()
            for capability in entries
        }
    effective = {
        capability: decisions.get(capability, "unknown")
        for _, capability in STATUS_CAPABILITIES
    }
    if "unknown" in effective.values():
        source = "invalid active policy" if active_present else "invalid capability policy template"
        effective = {capability: "unknown" for _, capability in STATUS_CAPABILITIES}
    return source, effective


def _overlay_mapping(base: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in explicit.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _overlay_mapping(result[key], value)
        else:
            result[key] = value
    return result


def _set_if_unknown(document: dict[str, Any], section: str, key: str, value: str | None) -> bool:
    if value is None:
        return False
    values = document.setdefault(section, {})
    if not isinstance(values, dict) or values.get(key) is not None:
        return False
    values[key] = value
    return True


def _load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _dependency_names(pyproject: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    project = pyproject.get("project")
    if isinstance(project, dict):
        dependencies = project.get("dependencies")
        if isinstance(dependencies, list):
            values.extend(dependencies)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    values.extend(group)
    names = set()
    for value in values:
        if not isinstance(value, str):
            continue
        match = re.match(r"[A-Za-z0-9_.-]+", value.strip())
        if match:
            names.add(match.group(0).lower().replace("_", "-"))
    return names


def _first_path(root: Path, candidates: tuple[str, ...]) -> str | None:
    for relative in candidates:
        path = root / relative
        if path.exists() and not path.is_symlink():
            return relative
    return None


def discover_repository_context(root: Path) -> dict[str, str]:
    """Return cheap repository facts for status output without persisting them."""
    pyproject = _load_pyproject(root)
    dependencies = _dependency_names(pyproject)
    tool = pyproject.get("tool")
    tool = tool if isinstance(tool, dict) else {}
    detected: dict[str, str] = {}
    source_roots = ("src", "app", "models", "pipelines", "notebooks")
    is_python = bool(pyproject) or (root / "requirements.txt").is_file() or any(
        path.is_file()
        for source_root in source_roots
        if (root / source_root).is_dir()
        for path in (root / source_root).rglob("*.py")
    )
    if is_python:
        detected["project_type"] = "Python project"
    if "pytest" in tool or "pytest" in dependencies or (root / "pytest.ini").is_file():
        detected["tests"] = "pytest"
    elif (root / "tests").is_dir():
        detected["tests"] = "tests directory"
    training = _first_path(
        root,
        (
            "src/train.py",
            "src/training",
            "src/train",
            "training",
            "train.py",
            "train",
        ),
    )
    inference = _first_path(
        root,
        (
            "src/predict.py",
            "src/inference",
            "src/infer",
            "inference",
            "predict.py",
            "serve",
        ),
    )
    if training:
        detected["training"] = training
    if inference:
        detected["inference"] = inference

    evidence_names = dependencies | {path.name.lower() for path in root.iterdir()}
    if bool({"pyspark", "spark"} & evidence_names) or any(
        (root / value).exists()
        for value in ("spark", "conf/spark", "spark-submit.conf")
    ):
        detected["distributed_compute"] = "Apache Spark"
    if "mlflow" in evidence_names or (root / "mlruns").is_dir():
        detected["experiment_tracker"] = "MLflow"
    if "apache-airflow" in evidence_names or (root / "dags").is_dir():
        detected["scheduler"] = "Airflow"
    if (root / "models" / "registered").is_dir():
        detected["model_registry"] = "MLflow Model Registry"
    return detected


def infer_project_context(
    root: Path, document: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Preserve only stable project-owned facts; rediscoverable facts stay transient."""
    discover_repository_context(root)
    return document, [], []


def update_project_config(root: Path) -> tuple[dict[str, Any], list[str], list[str], list[str], str]:
    template_path = root / ".agent-system" / "project.template.yaml"
    project_path = root / ".agent-system" / "project.yaml"
    _reject_symlink_components(root, project_path)
    template = _read_json(template_path)
    action = "created"
    existing = _read_json(project_path) if project_path.exists() else None
    if existing is not None:
        document = _overlay_mapping(template, existing)
        action = "preserved and updated"
    else:
        document = template
    inferred_explicit_before = _flatten_project_document(existing) if existing is not None else {}
    pyproject = _load_pyproject(root)
    dependencies = _dependency_names(pyproject)
    pyproject_path_exists = (root / "pyproject.toml").is_file()
    document, inferred, inferred_values = infer_project_context(root, document)
    conflicts = _find_material_conflicts(
        existing,
        inferred_explicit_before,
        document,
        inferred,
        pyproject=pyproject,
        dependencies=dependencies,
        pyproject_path_exists=pyproject_path_exists,
        root=root,
    )
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"
    previous = project_path.read_text(encoding="utf-8") if project_path.is_file() else None
    if previous != rendered:
        _safe_write(root, project_path, rendered)
    elif action != "created":
        action = "preserved unchanged"
    return document, inferred, inferred_values, conflicts, action


def project_config_for_recheck(
    root: Path,
) -> tuple[dict[str, Any], list[str], list[str], list[str], str]:
    """Recheck path: populate null fields from new repository evidence while
    preserving explicit project-owned values, and surface any conflicts.
    """
    project_path = root / ".agent-system" / "project.yaml"
    _reject_symlink_components(root, project_path)
    if not project_path.is_file():
        return update_project_config(root)
    document = _read_json(project_path)
    existing_flat = _flatten_project_document(document)
    pyproject = _load_pyproject(root)
    dependencies = _dependency_names(pyproject)
    pyproject_path_exists = (root / "pyproject.toml").is_file()
    document, inferred, inferred_values = infer_project_context(root, document)
    conflicts = _find_material_conflicts(
        document,
        existing_flat,
        document,
        inferred,
        pyproject=pyproject,
        dependencies=dependencies,
        pyproject_path_exists=pyproject_path_exists,
        root=root,
    )
    rendered = json.dumps(document, indent=2, sort_keys=False) + "\n"
    previous = project_path.read_text(encoding="utf-8")
    if previous != rendered:
        _safe_write(root, project_path, rendered)
        action = "preserved and updated (recheck)"
    else:
        action = "preserved unchanged (recheck)"
    return document, inferred, inferred_values, conflicts, action


def _flatten_project_document(document: dict[str, Any] | None) -> dict[str, Any]:
    """Return the dotted section.key → value map from a project document."""
    if not isinstance(document, dict):
        return {}
    flat: dict[str, Any] = {}
    for section, values in document.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            flat[f"{section}.{key}"] = value
    return flat


def _find_material_conflicts(
    existing: dict[str, Any] | None,
    existing_flat: dict[str, Any],
    document: dict[str, Any],
    inferred: list[str],
    pyproject: dict[str, Any] | None = None,
    dependencies: set[str] | None = None,
    pyproject_path_exists: bool = False,
    root: Path | None = None,
) -> list[str]:
    """Return a list of human-readable material conflicts between the explicit
    existing configuration and the inferred values that would have been filled
    in from repository evidence."""
    if not existing:
        return []
    document_flat = _flatten_project_document(document)
    conflicts: list[str] = []
    for field, inferred_value in _candidate_inferred_values(
        existing_flat,
        document_flat,
        inferred,
        pyproject,
        dependencies,
        pyproject_path_exists,
        root,
    ):
        explicit = existing_flat.get(field)
        if explicit is None:
            continue
        if explicit == inferred_value:
            continue
        conflicts.append(
            f"{field}: existing=`{explicit}` vs inferred=`{inferred_value}`; explicit preserved"
        )
    return conflicts


def _candidate_inferred_values(
    existing_flat: dict[str, Any],
    document_flat: dict[str, Any],
    inferred: list[str],
    pyproject: dict[str, Any] | None,
    dependencies: set[str] | None,
    pyproject_path_exists: bool,
    root: Path | None = None,
) -> list[tuple[str, Any]]:
    """Reconstruct the inferred values that would be set, regardless of whether
    the inference was skipped because an explicit value was already present."""
    candidates: list[tuple[str, Any]] = []
    project = (pyproject or {}).get("project") if isinstance(pyproject, dict) else None
    project_name = project.get("name") if isinstance(project, dict) else None
    if isinstance(project_name, str) and project_name.strip() and pyproject_path_exists:
        candidates.append(("project.name", project_name.strip()))
    tool = pyproject.get("tool") if isinstance(pyproject, dict) else None
    tool = tool if isinstance(tool, dict) else {}
    has_dep = lambda name: bool(dependencies and name in dependencies)
    if "pytest" in tool or has_dep("pytest"):
        candidates.append(("commands.tests", "python3 -B -m pytest"))
    if "ruff" in tool or has_dep("ruff"):
        candidates.append(("commands.lint", "ruff check ."))
    if "mypy" in tool or has_dep("mypy"):
        candidates.append(("commands.typecheck", "mypy ."))
    elif "pyright" in tool or has_dep("pyright"):
        candidates.append(("commands.typecheck", "pyright"))
    if root is not None:
        path_candidates = {
            "training": ("src/training", "src/train", "training", "train"),
            "inference": ("src/inference", "src/infer", "inference", "serve"),
            "tests": ("tests", "test"),
        }
        for key, candidates_list in path_candidates.items():
            value = _first_path(root, candidates_list)
            if value is not None:
                candidates.append((f"paths.{key}", value))
        evidence_names = dependencies | {
            path.name.lower() for path in root.iterdir()
        }
        if bool({"pyspark", "spark"} & evidence_names) or any(
            (root / value).exists()
            for value in ("spark", "conf/spark", "spark-submit.conf")
        ):
            candidates.append(("systems.distributed_compute", "Apache Spark"))
        if "mlflow" in evidence_names or (root / "mlruns").is_dir():
            candidates.append(("systems.experiment_tracker", "MLflow"))
        if "apache-airflow" in evidence_names or (root / "dags").is_dir():
            candidates.append(("systems.scheduler", "Airflow"))
        if (root / "models" / "registered").is_dir():
            candidates.append(("systems.model_registry", "MLflow Model Registry"))
        if (root / ".github" / "workflows").is_dir():
            candidates.append(("systems.git_provider", "GitHub"))
    return candidates


def _instruction_target(root: Path, harness: str) -> tuple[Path | None, Path | None]:
    if harness == "copilot":
        return (
            root / ".github" / "copilot-instructions.md",
            root / "adapters" / "copilot" / "copilot-instructions.fragment.md",
        )
    if harness in {"codex", "hermes"}:
        hermes_context = next(
            (root / name for name in (".hermes.md", "HERMES.md") if (root / name).is_file()),
            None,
        )
        if harness == "hermes":
            override = root / "AGENTS.override.md"
            agents = root / "AGENTS.md"
            if override.is_file() and not agents.is_file():
                return override, root / "AGENTS.dsml.template.md"
            if hermes_context is not None:
                return hermes_context, root / "AGENTS.dsml.template.md"
            if override.is_file():
                return agents, root / "AGENTS.dsml.template.md"
            return agents, root / "AGENTS.dsml.template.md"
        return root / "AGENTS.md", root / "AGENTS.dsml.template.md"
    return None, None


def ensure_harness_instructions(root: Path, harness: str) -> tuple[str, list[str], list[str]]:
    target, source = _instruction_target(root, harness)
    if target is None or source is None:
        return "unverified", [], ["Active harness is unknown; project instruction integration was not verified."]
    _reject_symlink_components(root, target)
    _reject_symlink_components(root, source)
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        instruction_sources = (root / "AGENTS.dsml.template.md",)
        if harness == "copilot":
            instruction_sources += (source,)
        if _instructions_are_complete(text, instruction_sources):
            return f"ready in `{target.relative_to(root)}`", [], []
        if harness == "copilot":
            action = (
                "Merge `AGENTS.dsml.template.md` and "
                f"`{source.relative_to(root)}` into the existing `{target.relative_to(root)}`. "
                "The existing file was preserved unchanged."
            )
        else:
            action = (
                f"Merge `{source.relative_to(root)}` into the existing "
                f"`{target.relative_to(root)}`. The existing file was preserved unchanged."
            )
        return f"merge required in `{target.relative_to(root)}`", [], [action]
    source_text = source.read_text(encoding="utf-8")
    if harness == "copilot":
        runtime_text = (root / "AGENTS.dsml.template.md").read_text(encoding="utf-8")
        source_text = runtime_text + "\n\n" + source_text
    _safe_write(root, target, source_text)
    return f"created `{target.relative_to(root)}`", [str(target.relative_to(root))], []


def _project_map_alternative(root: Path) -> Path | None:
    candidates = (
        "docs/system-overview.md",
        "docs/system-architecture.md",
        "docs/architecture-overview.md",
        "docs/architecture.md",
        "docs/project-map.md",
        "SYSTEM_OVERVIEW.md",
        "ARCHITECTURE.md",
    )
    return next((root / value for value in candidates if (root / value).is_file()), None)


def ensure_project_map(
    root: Path, project: dict[str, Any], inferred: list[str]
) -> tuple[str, list[str]]:
    path = root / "PROJECT_MAP.md"
    _reject_symlink_components(root, path)
    if path.is_file():
        return "preserved existing `PROJECT_MAP.md`", []
    alternative = _project_map_alternative(root)
    if alternative is not None:
        return f"reused `{alternative.relative_to(root)}`; no duplicate created", []

    detected = discover_repository_context(root)
    meaningful = any(
        key in detected for key in ("project_type", "training", "inference", "tests")
    )
    if not meaningful:
        return "not created; repository evidence was too small to add value", []

    lines = [
        "# Project map",
        "",
        f"> Generated during DS/ML Agent Kit setup for `{root.name}`. Verify against repository evidence.",
        "",
        "## System in one paragraph",
        "",
        "`Inferred` — repository structure indicates a DS/ML project. Product purpose and score consumer remain `Unknown` unless documented elsewhere.",
        "",
        "## Key entry points and commands",
        "",
        "| Purpose | Evidence-backed path or command | Status |",
        "| --- | --- | --- |",
        f"| Training | `{detected['training']}` | Inferred |"
        if "training" in detected
        else "| Training | Unknown | Unknown |",
        f"| Inference | `{detected['inference']}` | Inferred |"
        if "inference" in detected
        else "| Inference | Unknown | Unknown |",
        f"| Tests | `{detected['tests']}` | Inferred |"
        if "tests" in detected
        else "| Tests | Unknown | Unknown |",
        "",
        "## Operational dependencies",
        "",
    ]
    systems = [
        f"- {key}: {detected[key]}"
        for key in (
            "distributed_compute",
            "experiment_tracker",
            "scheduler",
            "model_registry",
        )
        if key in detected
    ]
    lines.extend(systems or ["- None detected from repository evidence."])
    lines.extend(
        [
            "- Technical detection does not imply authorization.",
            "",
            "## Known risks and unknowns",
            "",
            "- Product purpose, data contract, evaluation contract, and operational consumer require repository-specific evidence.",
            "",
            "## Evidence and freshness",
            "",
            "- Evidence: authoritative repository files and discovered entry points.",
            "- Refresh only when architecture or toolkit configuration changes materially.",
            "",
        ]
    )
    _safe_write(root, path, "\n".join(lines))
    return "created `PROJECT_MAP.md`", ["PROJECT_MAP.md"]


def _run_validation(root: Path) -> tuple[str, str]:
    command = _validation_command(root)
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        return "FAIL", f"Validation started but timed out after {exc.timeout} seconds."
    except OSError as exc:
        return "NOT RUN", str(exc)
    output = (result.stdout + result.stderr).strip()
    return ("PASS" if result.returncode == 0 else "FAIL"), output


def _validation_command(root: Path) -> list[str]:
    return [
        sys.executable,
        "-B",
        str((root / ".agent-system" / "tooling" / "validate-kit.py").resolve()),
        "--installed-project",
        ".",
    ]


def _format_validation_command(root: Path) -> str:
    return shlex_join_safe(_validation_command(root))


def shlex_join_safe(command: list[str]) -> str:
    try:
        import shlex
        return shlex.join(command)
    except ImportError:
        return " ".join(command)


def _repository_revision(root: Path) -> str:
    try:
        state = git_preflight.preflight(root)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "unavailable"
    head = state.get("head")
    return head[:12] if isinstance(head, str) and head else "unavailable"


def _additional_skills(root: Path) -> list[str]:
    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        return []
    toolkit_skills = CORE_SKILLS | BUNDLED_SPECIALIZED_SKILLS
    return sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and path.name not in toolkit_skills
    )


def _unknown_project_fields(project: dict[str, Any]) -> list[str]:
    """Optional unknowns are intentionally silent during low-ceremony setup."""
    return []


def _require_installed_overlay(root: Path) -> None:
    required = (
        ".agent-system/VERSION",
        ".agent-system/manifest.json",
        ".agent-system/project.template.yaml",
        ".agents/skills",
        "AGENTS.dsml.template.md",
    )
    missing = [relative for relative in required if not (root / relative).exists()]
    if missing:
        raise ValueError(f"installed overlay markers are missing: {', '.join(missing)}")
    for relative in required:
        _reject_symlink_components(root, root / relative)


def _render_status(
    root: Path,
    project: dict[str, Any],
    verdict: str,
    created: list[str],
    inferred: list[str],
    inferred_values: list[str],
    project_action: str,
    map_status: str,
    instruction_status: str,
    validation_result: str,
    validation_detail: str,
    validation_command: str,
    manual_actions: list[str],
    warnings: list[str],
    harness: str,
    policy_source: str,
    capability_decisions: dict[str, str],
) -> str:
    version = (root / ".agent-system" / "VERSION").read_text(encoding="utf-8").strip()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    detected = discover_repository_context(root)
    additional = _additional_skills(root)
    created_items = list(dict.fromkeys(created + [".agent-system/onboarding-status.md"]))
    lines = [
        "# DS/ML Agent Kit Setup Status",
        "",
        f"Status: {verdict}",
        f"Toolkit version: {version}",
        f"Repository revision: {_repository_revision(root)}",
        f"Generated at: {generated_at}",
        "",
        "## Detected",
        "",
    ]
    labels = {
        "project_type": "Project",
        "tests": "Tests",
        "training": "Training",
        "inference": "Inference",
        "distributed_compute": "Distributed compute",
        "experiment_tracker": "Experiment tracker",
        "scheduler": "Scheduler",
        "model_registry": "Model registry",
    }
    if detected:
        lines.extend(f"- {labels[key]}: `{value}`" for key, value in detected.items())
    else:
        lines.append("- No high-confidence DS/ML entry points detected.")
    lines.extend(
        [
            "",
            "## Available workflows",
            "",
            "- Technical report",
            "- Autoresearch",
            "- Independent validation",
            "",
            "## Setup state",
            "",
            f"- Project config: {project_action}",
            f"- Project map: {map_status}",
            f"- Harness: `{harness}`; instructions {instruction_status}",
            f"- Capability policy: {policy_source}",
            f"- Validation: {validation_result}",
            f"- Command: `{validation_command}`",
            "- Core skills: "
            + ", ".join(
                f"`{skill}`"
                for skill in sorted(
                    skill
                    for skill in CORE_SKILLS
                    if (root / ".agents" / "skills" / skill / "SKILL.md").is_file()
                )
            ),
        ]
    )
    if policy_source == "active project policy":
        lines.append("- Configured: approved active project policy present; higher-level policy still wins.")
    elif policy_source == "invalid active policy":
        lines.append("- Active capability policy could not be validated.")
    elif policy_source == "invalid capability policy template":
        lines.append("- Capability-policy template is invalid.")
    else:
        lines.append("- Conservative defaults active; ordinary local/read-only work can proceed.")
    lines.extend(
        f"- {label} (`{capability}`): `{capability_decisions[capability]}`"
        for label, capability in STATUS_CAPABILITIES
    )
    if detected.get("distributed_compute") and policy_source == "active project policy":
        lines.append(
            "- Distributed compute authorization follows the exact approved "
            f"`costly_compute` scope: `{capability_decisions['costly_compute']}`."
        )
    if additional:
        lines.append("- Project-specific skills: " + ", ".join(f"`{item}`" for item in additional))
    if validation_detail and validation_result == "FAIL":
        detail_lines = validation_detail.splitlines()
        lines.append(f"- Validation summary: {detail_lines[0]}")
        lines.extend(f"  {item}" for item in detail_lines[1:9])
    lines.extend(["", "## Manual action required", ""])
    if manual_actions:
        lines.extend(f"{index}. {item}" for index, item in enumerate(manual_actions, start=1))
    else:
        lines.append("None.")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    lines.extend(["", "## Created / updated", ""])
    lines.extend(f"- `{item}`" for item in created_items)
    lines.extend(["", "Controls: `.agent-system/CONTROL.md`", ""])
    return "\n".join(lines)


def onboard_repository(
    root: Path,
    harness: str,
    *,
    activation_verified: bool = False,
    recheck: bool = False,
    validation_runner: Callable[[Path], tuple[str, str]] = _run_validation,
) -> tuple[str, str]:
    root = root.resolve()
    if harness not in VALID_HARNESSES:
        raise ValueError(f"unsupported harness {harness!r}")
    _require_installed_overlay(root)
    if recheck:
        project, inferred, inferred_values, conflicts, project_action = project_config_for_recheck(root)
    else:
        project, inferred, inferred_values, conflicts, project_action = update_project_config(root)
    created = (
        [".agent-system/project.yaml"]
        if project_action in {"created", "preserved and updated"}
        else []
    )
    instruction_status, instruction_created, manual_actions = ensure_harness_instructions(root, harness)
    created.extend(instruction_created)
    warnings: list[str] = []
    if harness == "unknown":
        warnings.append("Harness-specific activation remains unverified.")
    if harness == "hermes" and not activation_verified:
        manual_actions.append(
            "Run `hermes skills trust` from the repository root, start a new session, and recheck onboarding."
        )
        instruction_status += "; project-skill trust not verified"
    for conflict in conflicts:
        warnings.append(f"Configuration conflict: {conflict}")
    map_status, map_created = ensure_project_map(root, project, inferred)
    created.extend(map_created)
    policy_source, capability_decisions = _effective_capability_decisions(root)
    validation_result, validation_detail = validation_runner(root)
    if validation_result == "FAIL":
        manual_actions.append("Resolve the installed-project validation failure, then recheck onboarding.")
    elif validation_result == "NOT RUN":
        manual_actions.append(f"Run `{_format_validation_command(root)}` from the repository root, then recheck onboarding.")
    if policy_source == "invalid active policy":
        manual_actions.append(
            "Repair `.agent-system/policy/capability-policy.yaml` so it is a valid approved project policy, then recheck onboarding."
        )
    elif policy_source == "invalid capability policy template":
        manual_actions.append(
            "Restore or repair `.agent-system/policy/capability-policy.template.yaml` so the conservative default policy is parseable, then recheck onboarding."
        )
    distributed = discover_repository_context(root).get("distributed_compute")
    if distributed and capability_decisions["costly_compute"] == "approval_required":
        warnings.append(
            "Distributed training technology was detected, but authorization was not inferred; approval remains required per run."
        )
    if manual_actions:
        verdict = "ACTION_REQUIRED"
    elif warnings:
        verdict = "READY_WITH_WARNINGS"
    else:
        verdict = "READY"
    status = _render_status(
        root,
        project,
        verdict,
        created,
        inferred,
        inferred_values,
        project_action,
        map_status,
        instruction_status,
        validation_result,
        validation_detail,
        _format_validation_command(root),
        manual_actions,
        warnings,
        harness,
        policy_source,
        capability_decisions,
    )
    status_path = root / ".agent-system" / "onboarding-status.md"
    created_items = list(dict.fromkeys(created + [str(status_path.relative_to(root))]))
    _safe_write(root, status_path, status)
    detected = discover_repository_context(root)
    summary = [verdict, "", "Detected"]
    labels = {
        "project_type": "project",
        "tests": "tests",
        "training": "training",
        "inference": "inference",
        "distributed_compute": "distributed compute",
        "experiment_tracker": "experiment tracker",
        "scheduler": "scheduler",
        "model_registry": "model registry",
    }
    if detected:
        summary.extend(f"- {labels[key]}: {value}" for key, value in detected.items())
    else:
        summary.append("- no high-confidence DS/ML entry points")
    summary.extend(
        [
            "",
            "Available workflows",
            "- Technical report",
            "- Autoresearch",
            "- Independent validation",
            "",
            f"Validation: {validation_result}",
        ]
    )
    if manual_actions:
        summary.append("Manual action required:")
        summary.extend(
            f"{index}. {item}" for index, item in enumerate(manual_actions, start=1)
        )
    if warnings:
        summary.append("Warnings:")
        summary.extend(f"- {item}" for item in warnings)
    if policy_source.startswith("invalid"):
        summary.append(f"Capability policy: {policy_source}")
    summary.extend(
        [
            "",
            "Controls: `.agent-system/CONTROL.md`",
            "Details: `.agent-system/onboarding-status.md`",
        ]
    )
    return verdict, "\n".join(summary) + "\n"


def _write_setup_error_status(root: Path, harness: str, error: Exception) -> None:
    system = root / ".agent-system"
    if not system.is_dir():
        return
    version_path = system / "VERSION"
    version = "unknown"
    try:
        _reject_symlink_components(root, version_path)
    except ValueError:
        pass
    else:
        if version_path.is_file():
            version = version_path.read_text(encoding="utf-8").strip()
    project_path = system / "project.yaml"
    project_invalid = False
    if project_path.is_file() and not project_path.is_symlink():
        try:
            _read_json(project_path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            project_invalid = True
    if project_invalid:
        action = "Fix `.agent-system/project.yaml` so it is valid JSON-compatible YAML, then recheck onboarding."
    else:
        action = "Restore the missing or invalid toolkit runtime file, then recheck onboarding."
    status = (
        "# DS/ML Agent Kit Setup Status\n\n"
        "Status: ACTION_REQUIRED\n"
        f"Toolkit version: {version}\n\n"
        f"Harness: `{harness}`\n\n"
        "## Validation\n\n"
        f"Command: `{_format_validation_command(root)}`\n"
        "Validation: NOT RUN\n"
        f"Reason: setup failed before validation ({type(error).__name__}).\n\n"
        "## Manual action required\n\n"
        f"1. {action}\n\n"
        "## Remaining unknowns\n\n"
        "Not assessed because setup input was invalid.\n"
    )
    _safe_write(root, system / "onboarding-status.md", status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-project", type=Path, default=Path("."))
    parser.add_argument("--harness", choices=sorted(VALID_HARNESSES), default="unknown")
    parser.add_argument(
        "--activation-verified",
        action="store_true",
        help="record that required harness activation/trust was observed",
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="refresh validation/status while preserving existing project-owned files",
    )
    parser.add_argument(
        "--repair-runtime",
        type=Path,
        metavar="CLEAN_OVERLAY",
        help="restore manifest-owned files from a trusted same-version clean overlay",
    )
    args = parser.parse_args()
    try:
        repaired: list[str] = []
        if args.repair_runtime is not None:
            repaired = repair_runtime(args.installed_project, args.repair_runtime)
        verdict, summary = onboard_repository(
            args.installed_project,
            args.harness,
            activation_verified=args.activation_verified,
            recheck=args.recheck,
        )
        if args.repair_runtime is not None:
            summary = (
                f"Runtime integrity: repaired {len(repaired)} manifest-owned file(s); validation completed.\n"
                + summary
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        status_error: Exception | None = None
        try:
            _write_setup_error_status(args.installed_project.resolve(), args.harness, exc)
        except (OSError, UnicodeError, ValueError) as write_exc:
            status_error = write_exc
        message = f"DS/ML Agent Kit onboarding: ACTION_REQUIRED\n\nSetup error: {exc}"
        if status_error is not None:
            message += f"\nOnboarding status was not written safely: {status_error}"
        print(message)
        return 2
    print(summary, end="")
    return 0 if verdict in {"READY", "READY_WITH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
