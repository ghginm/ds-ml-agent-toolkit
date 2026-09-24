#!/usr/bin/env python3
"""Validate the portable DS/ML agent toolkit with stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2] if SCRIPT_PATH.parent.parent.name == ".agent-system" else SCRIPT_PATH.parents[1]
CORE_SKILLS = {
    "analyze-dsml-project",
    "execute-dsml-task",
    "validate-dsml-result",
}
BUNDLED_SPECIALIZED_SKILLS = {"autoresearch", "compose-dsml-report"}
SHIPPED_SKILLS = CORE_SKILLS | BUNDLED_SPECIALIZED_SKILLS
EXPECTED_SKILLS = CORE_SKILLS
EXPECTED_CATEGORIES = {"positive", "negative-trigger", "pathological", "no-change-correct"}
REQUIRED_COVERAGE = {
    "analyze_orientation",
    "analyze_technical_report",
    "analyze_deep_audit",
    "execute_diagnose",
    "execute_develop",
    "ordinary_task_no_workflow",
    "workflow_parameter_override",
    "explicit_validation",
    "generic_ml_negative",
    "trivial_task_negative",
    "target_leakage",
    "entity_leakage",
    "row_exploding_join",
    "metric_population_change",
    "training_inference_skew",
    "unreproducible_baseline",
    "aml_delayed_labels_capacity",
    "full_training_approval",
    "restricted_data_approval",
    "forbidden_production_mutation",
    "forbidden_exfiltration",
    "static_fallback",
    "failed_experiment_preserve_baseline",
    "nonreproducible_bug_no_edit",
    "correct_no_change",
    "unrun_claim_detected",
    "project_specific_skill",
    "routing_correction_signal",
    "valid_rejection_empty_signals",
    "authorized_dev_training",
    "organization_policy_conflict",
    "exploration_before_candidate_evaluation",
    "onboarding_trigger",
    "onboarding_low_ceremony",
    "onboarding_optional_unknowns",
    "onboarding_permission_ambiguity",
    "onboarding_no_self_modification",
    "onboarding_recheck",
    "empty_learning_signals",
    "recurring_request_metadata",
    "scope_separation",
    "learning_metric_separation",
    "learning_signal_sanitization",
    "learning_signal_review",
    "learning_outcome_separation",
    "mixed_learning_scopes",
    "semantic_validation_gap",
    "auxiliary_learning_write_isolation",
    "natural_language_pdf_research",
    "natural_language_bounded_understanding",
    "natural_language_diagnosis",
    "natural_language_development",
    "natural_language_validation",
    "autoresearch_bare_preflight",
    "autoresearch_partial_preflight",
    "autoresearch_explicit",
    "autoresearch_explicit_proceed",
    "autoresearch_ambiguous_metric",
    "autoresearch_implicit",
    "autoresearch_negative_ordinary",
    "autoresearch_negative_bounded",
    "autoresearch_holdout_protection",
    "autoresearch_user_work_protection",
    "autoresearch_remote_git_separation",
    "autoresearch_guardrail_rejection",
    "autoresearch_noise_plateau",
    "autoresearch_bounded_crash_repair",
    "autoresearch_larger_hypothesis",
    "autoresearch_capability_gate",
}
REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "user_request",
    "fixture_ids",
    "raw_evidence_refs",
    "expected",
    "required_invariants",
    "forbidden_actions",
    "rubric_ids",
    "coverage_tags",
}
REQUIRED_ADAPTERS = {
    "adapters/codex/AGENTS.fragment.md",
    "adapters/copilot/copilot-instructions.fragment.md",
    "adapters/hermes/hermes-project.fragment.md",
}
FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
UNFINISHED_MARKERS = (
    "TO" + "DO",
    "T" + "BD",
    "FIX" + "ME",
    "REPLACE" + "_ME",
)
PLACEHOLDER_RE = re.compile(
    r"\b(?:" + "|".join(UNFINISHED_MARKERS[:3]) + r")\b|"
    + re.escape(UNFINISHED_MARKERS[3])
    + r"|lorem\s+ipsum",
    re.IGNORECASE,
)
BANNED_CORE_PRODUCTS = re.compile(
    r"\b(?:databricks|mlflow|airflow|azure\s+data\s+factory|github\s+actions)\b",
    re.IGNORECASE,
)
SUPPORTED_SCHEMA_KEYS = {
    "$schema",
    "$id",
    "title",
    "type",
    "additionalProperties",
    "required",
    "properties",
    "enum",
    "minLength",
    "maxLength",
    "pattern",
    "items",
    "minItems",
    "maxItems",
    "minimum",
}
ALLOWED_SKILL_FRONTMATTER = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
CORE_DESCRIPTION_SIGNALS = {
    "analyze-dsml-project": (
        r"\b(?:inspect|understand|map|trace)\b",
        r"\b(?:project|repository)\b",
        r"\b(?:onboarding|orientation|audit|analysis)\b",
        r"\bnot\b.*\b(?:implementation|validation)\b",
    ),
    "execute-dsml-task": (
        r"\b(?:diagnose|implement|evaluate|develop)\b",
        r"\b(?:regressions?|fix(?:es)?|changes?|experiments?)\b",
        r"\bnot\b.*\b(?:orientation|validation)\b",
    ),
    "validate-dsml-result": (
        r"\bindependent(?:ly)?\b",
        r"\b(?:challenge|validate|review)\b",
        r"\bread-only\b",
        r"\bnot\b.*\b(?:implementation|developer)\b",
    ),
}
REQUIRED_POLICY_STATUS = "template_requires_organization_review"
REQUIRED_ACTIVE_POLICY_STATUS = "approved_project_policy"
REQUIRED_INSTRUCTION_PRECEDENCE = [
    "organization_policy",
    "repository_contract",
    "path_specific_instructions",
    "selected_skill",
    "task_state",
    "runtime_evidence",
]
REQUIRED_POLICY_DEFAULTS = {
    "production_mutation": "forbidden",
    "unknown_behavior": "forbidden",
    "sensitive_data_access": "unknown",
    "external_transmission": "unknown",
    "remote_mutation": "unknown",
}
REQUIRED_POLICY_FORBIDDEN_ACTIONS = {
    "production_data_mutation",
    "protected_branch_push",
    "secret_access_or_disclosure",
    "unapproved_sensitive_transmission",
    "silent_policy_or_skill_change",
    "fabricated_execution_claim",
}
REQUIRED_POLICY_APPROVAL_ACTIONS = {
    "internal_data_query",
    "dependency_change",
    "costly_compute",
    "git_remote_change",
    "remote_ml_system_write",
    "confidential_data_processing",
}
REQUIRED_POLICY_ALLOWED_ACTIONS = {"task_scoped_local_git"}
REQUIRED_ARTIFACT_FORBIDDEN = {"secrets", "raw customer rows", "hidden chain-of-thought"}
UNSAFE_FIXTURE_PATH_RE = re.compile(r"(^|[\\/])\.\.($|[\\/])|^[A-Za-z]:|^[/\\]")
TEMPLATE_REQUIRED_SECTIONS = {
    ".agent-system/CONTROL.md": [
        "# DS/ML Agent Kit — Control",
        "## Start here",
        "## Setup in three steps",
        "## Workflow controls",
        "Need more detail? See [`SYSTEM.md`](SYSTEM.md).",
    ],
    ".agent-system/SYSTEM.md": [
        "# DS/ML Agent Kit — System",
        "## 5-minute architecture",
        "## Routing precedence",
        "Ordinary work does not require them.",
    ],
    ".agent-system/workflows/technical-report.md": [
        "## Trigger and controls",
        "## Contract",
        "analyze-dsml-project",
        "compose-dsml-report",
    ],
    ".agent-system/workflows/autoresearch.md": [
        "## Trigger and controls",
        "## Contract",
        "max experiments",
        "final holdout",
    ],
    ".agent-system/workflows/independent-validation.md": [
        "## Trigger and controls",
        "## Contract",
        "Read-only",
        "validate-dsml-result",
    ],
    ".agent-system/templates/AGENTS.dsml.template.md": [
        "## Agent system",
        "Project-specific guidance is defined in this file.",
        ".agent-system/CONTROL.md",
        ".agent-system/SYSTEM.md",
        ".agent-system/workflows/",
    ],
    ".agent-system/templates/PROJECT_MAP.template.md": [
        "# Project map",
        "## System in one paragraph",
        "## Data-to-decision flow",
        "## Known risks and unknowns",
        "## Evidence and freshness",
        "Label material claims",
    ],
    ".agent-system/templates/finding-report.template.md": [
        "PASS_WITH_UNCERTAINTY",
        "BLOCKER",
        "verification_status",
        "## Checks actually run",
        "Review provenance",
    ],
    ".agent-system/templates/improvement-candidate.template.md": [
        "not released instruction or policy",
        "Observed signal",
        "Responsible layer",
        "never apply automatically",
        "Review and release record",
    ],
}
VALID_CASE_VERDICTS = {
    "PASS",
    "PASS_WITH_UNCERTAINTY",
    "REQUIRES_CHANGES",
    "NOT_VERIFIED",
    "BLOCKED",
    "accept",
    "reject",
    "blocked",
    "not_verified",
    "unresolved",
    "not_applicable",
    "READY",
    "READY_WITH_WARNINGS",
    "ACTION_REQUIRED",
}
VALID_CASE_MODES = {"orientation", "technical-report", "deep-audit", "diagnose", "develop", "review", "review+aml", "autoresearch", "specialized", "none"}
VALID_ARTIFACT_CLASSES = {
    "project_map",
    "report",
    "run_record",
    "finding_report",
    "response_only",
    "minimal_diff",
    "diagnosis",
    "approval_request",
    "learning_record",
    "refusal",
    "onboarding_status",
}
EXPECTED_RUBRICS = {
    "routing",
    "evidence_traceability",
    "capability_gate",
    "dsml_contract",
    "falsification",
    "truthfulness",
    "minimal_scope",
    "no_change_outcome",
    "artifact_discipline",
}
COVERAGE_CASE_IDS = {
    "analyze_orientation": "positive-analyze-orientation",
    "analyze_technical_report": "routing-natural-language-pdf-research",
    "analyze_deep_audit": "positive-analyze-deep-audit",
    "execute_diagnose": "positive-execute-diagnose",
    "execute_develop": "positive-execute-develop",
    "ordinary_task_no_workflow": "ordinary-preprocessing-bug",
    "workflow_parameter_override": "technical-report-iterations-override",
    "explicit_validation": "positive-explicit-validation",
    "generic_ml_negative": "negative-generic-ml-question",
    "trivial_task_negative": "negative-trivial-documentation",
    "target_leakage": "pathological-target-leakage",
    "entity_leakage": "pathological-entity-leakage",
    "row_exploding_join": "pathological-row-exploding-join",
    "metric_population_change": "pathological-metric-population-change",
    "training_inference_skew": "pathological-training-inference-skew",
    "unreproducible_baseline": "pathological-unreproducible-baseline",
    "aml_delayed_labels_capacity": "pathological-aml-delayed-labels-capacity",
    "full_training_approval": "pathological-full-training-approval",
    "restricted_data_approval": "pathological-restricted-data-approval",
    "forbidden_production_mutation": "pathological-forbidden-production-mutation",
    "forbidden_exfiltration": "pathological-forbidden-exfiltration",
    "static_fallback": "pathological-static-fallback",
    "failed_experiment_preserve_baseline": "no-change-failed-experiment",
    "nonreproducible_bug_no_edit": "no-change-unreproduced-bug",
    "correct_no_change": "no-change-correct-join",
    "unrun_claim_detected": "pathological-unrun-claim",
    "project_specific_skill": "positive-project-specific-forecasting",
    "routing_correction_signal": "pathological-feedback-after-routing-correction",
    "valid_rejection_empty_signals": "no-change-failed-experiment",
    "authorized_dev_training": "positive-authorized-dev-training",
    "organization_policy_conflict": "pathological-organization-policy-conflict",
    "exploration_before_candidate_evaluation": "positive-exploration-before-evaluation",
    "onboarding_trigger": "positive-natural-language-onboarding",
    "onboarding_low_ceremony": "positive-natural-language-onboarding",
    "onboarding_optional_unknowns": "positive-natural-language-onboarding",
    "onboarding_permission_ambiguity": "pathological-onboarding-permission-ambiguity",
    "onboarding_no_self_modification": "pathological-onboarding-permission-ambiguity",
    "onboarding_recheck": "positive-onboarding-recheck",
    "empty_learning_signals": "positive-one-off-success-no-learning-signal",
    "recurring_request_metadata": "positive-learning-signal-review",
    "scope_separation": "pathological-feedback-after-routing-correction",
    "learning_metric_separation": "pathological-feedback-after-routing-correction",
    "learning_signal_sanitization": "positive-learning-signal-review",
    "learning_signal_review": "positive-learning-signal-review",
    "learning_outcome_separation": "pathological-technical-report-rework-learning",
    "mixed_learning_scopes": "pathological-technical-report-rework-learning",
    "semantic_validation_gap": "pathological-technical-report-rework-learning",
    "auxiliary_learning_write_isolation": "pathological-auxiliary-learning-write-failure",
    "natural_language_pdf_research": "routing-natural-language-pdf-research",
    "natural_language_bounded_understanding": "routing-natural-language-bounded-understanding",
    "natural_language_diagnosis": "routing-natural-language-diagnosis",
    "natural_language_development": "routing-natural-language-development",
    "natural_language_validation": "routing-natural-language-validation",
    "autoresearch_bare_preflight": "autoresearch-bare-preflight",
    "autoresearch_partial_preflight": "autoresearch-partial-preflight",
    "autoresearch_explicit": "autoresearch-explicit-trigger",
    "autoresearch_explicit_proceed": "autoresearch-explicit-proceed-authorization",
    "autoresearch_ambiguous_metric": "autoresearch-ambiguous-primary-metric",
    "autoresearch_implicit": "autoresearch-implicit-trigger",
    "autoresearch_negative_ordinary": "autoresearch-negative-ordinary-development",
    "autoresearch_negative_bounded": "autoresearch-negative-bounded-candidate",
    "autoresearch_holdout_protection": "autoresearch-final-holdout-protection",
    "autoresearch_user_work_protection": "autoresearch-dirty-worktree-safe-isolation",
    "autoresearch_remote_git_separation": "autoresearch-remote-git-separation",
    "autoresearch_guardrail_rejection": "autoresearch-guardrail-rejection",
    "autoresearch_noise_plateau": "autoresearch-noise-plateau",
    "autoresearch_bounded_crash_repair": "autoresearch-bounded-crash-repair",
    "autoresearch_larger_hypothesis": "autoresearch-larger-hypothesis-after-incremental-search",
    "autoresearch_capability_gate": "autoresearch-capability-gate",
}
MAX_MAINTAINED_FILE_BYTES = 2_000_000
IGNORED_DIRECTORY_NAMES = {".git", ".pytest_cache", "_prompts", "node_modules", ".venv", "venv"}
FORBIDDEN_LEARNING_ARTIFACT_KEYS = {
    "chain_of_thought",
    "credentials",
    "customer_records",
    "raw_customer_rows",
    "raw_query_output",
    "secrets",
    "terminal_transcript",
}


def relative_name(path: Path, root: Path = ROOT) -> str:
    """Return a stable repository-relative name when possible."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


def read_text_checked(path: Path, root: Path | None = None) -> str:
    """Read a bounded regular file without following repository symlinks."""
    if path.is_symlink():
        raise ValueError(f"symlinked file is not allowed: {path}")
    resolved = path.resolve(strict=True)
    if root is not None:
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"file escapes repository: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {path}")
    if resolved.stat().st_size > MAX_MAINTAINED_FILE_BYTES:
        raise ValueError(f"maintained file exceeds {MAX_MAINTAINED_FILE_BYTES} bytes: {path}")
    return resolved.read_text(encoding="utf-8")


def load_json(path: Path, root: Path | None = None) -> Any:
    """Load JSON, including JSON-compatible YAML files."""
    return json.loads(
        read_text_checked(path, root),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_json_constant,
    )


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def schema_errors(instance: Any, schema: dict[str, Any], location: str = "$") -> list[str]:
    """Validate the JSON Schema subset used by maintained toolkit schemas."""
    errors: list[str] = []
    expected_types = schema.get("type")
    if expected_types is not None:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(_matches_type(instance, item) for item in expected_types):
            return [f"{location}: expected type {expected_types}, got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{location}: {instance!r} is not in {schema['enum']!r}")

    if isinstance(instance, str) and len(instance) < schema.get("minLength", 0):
        errors.append(f"{location}: string is shorter than minLength")
    max_length = schema.get("maxLength")
    if isinstance(instance, str) and isinstance(max_length, int) and len(instance) > max_length:
        errors.append(f"{location}: string is longer than maxLength {max_length}")
    minimum = schema.get("minimum")
    if (
        isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and instance < minimum
    ):
        errors.append(f"{location}: number is less than minimum {minimum}")
    pattern = schema.get("pattern")
    if isinstance(instance, str) and isinstance(pattern, str) and re.search(pattern, instance) is None:
        errors.append(f"{location}: string does not match required pattern")

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{location}: array is shorter than minItems")
        max_items = schema.get("maxItems")
        if (
            isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and len(instance) > max_items
        ):
            errors.append(f"{location}: array is longer than maxItems {max_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(schema_errors(item, item_schema, f"{location}[{index}]"))

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{location}: missing required property {key!r}")

        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(schema_errors(value, properties[key], f"{location}.{key}"))
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                errors.append(f"{location}: unexpected property {key!r}")
            elif isinstance(additional, dict):
                errors.extend(schema_errors(value, additional, f"{location}.{key}"))

    return errors


def schema_definition_errors(schema: dict[str, Any], location: str = "$") -> list[str]:
    """Reject schema keywords that the stdlib validator would ignore."""
    errors = [
        f"{location}: unsupported JSON Schema keyword {key!r}"
        for key in schema
        if key not in SUPPORTED_SCHEMA_KEYS
    ]
    errors.extend(_validate_supported_keyword_values(schema, location))
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, child in properties.items():
            if isinstance(child, dict):
                errors.extend(schema_definition_errors(child, f"{location}.properties.{key}"))
    items = schema.get("items")
    if isinstance(items, dict):
        errors.extend(schema_definition_errors(items, f"{location}.items"))
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        errors.extend(schema_definition_errors(additional, f"{location}.additionalProperties"))
    return errors


def _validate_supported_keyword_values(schema: dict[str, Any], location: str) -> list[str]:
    """Reject supported keywords whose values would silently disable their constraint."""
    errors: list[str] = []
    expected_types = schema.get("type")
    allowed_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
    type_values = [expected_types] if isinstance(expected_types, str) else expected_types
    if expected_types is not None and not (
        isinstance(type_values, list)
        and type_values
        and all(isinstance(item, str) and item in allowed_types for item in type_values)
    ):
        errors.append(f"{location}: 'type' must contain only supported JSON types")
    required = schema.get("required")
    if required is not None and not (
        isinstance(required, list)
        and required
        and len(required) == len(set(required))
        and all(isinstance(item, str) and item for item in required)
    ):
        errors.append(f"{location}: 'required' must be a non-empty unique string list")
    enum = schema.get("enum")
    if enum is not None and not (isinstance(enum, list) and enum):
        errors.append(f"{location}: 'enum' must be a non-empty list")
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        errors.append(f"{location}: 'properties' must be a mapping")
    elif isinstance(properties, dict) and any(not isinstance(child, dict) for child in properties.values()):
        errors.append(f"{location}: every property value must be a mapping schema")
    additional = schema.get("additionalProperties")
    if additional is not None and not (
        isinstance(additional, bool) or isinstance(additional, dict)
    ):
        errors.append(f"{location}: 'additionalProperties' must be boolean or a mapping")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        value = schema.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            errors.append(f"{location}: {key!r} must be a non-negative integer")
    minimum = schema.get("minimum")
    if minimum is not None and (
        not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
    ):
        errors.append(f"{location}: 'minimum' must be a number")
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append(f"{location}: 'pattern' must be a string")
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"{location}: invalid regular-expression pattern: {exc}")
    items = schema.get("items")
    if items is not None and not isinstance(items, dict):
        errors.append(f"{location}: 'items' must be a mapping schema")
    return errors


def parse_frontmatter(path: Path, root: Path = ROOT) -> tuple[dict[str, Any], list[str]]:
    """Parse the constrained top-level frontmatter fields used by this kit."""
    text = read_text_checked(path, root if path.is_relative_to(root) else None)
    errors: list[str] = []
    if not text.startswith("---\n"):
        return {}, [f"{relative_name(path, root)}: frontmatter must start at byte zero"]
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, [f"{relative_name(path, root)}: missing frontmatter terminator"]
    if not text[end + 5 :].strip():
        errors.append(f"{relative_name(path, root)}: skill body is empty")

    block = text[4:end]
    if "\t" in block:
        errors.append(f"{relative_name(path, root)}: tabs are not valid in constrained frontmatter")
    values: dict[str, Any] = {}
    nested_key: str | None = None
    block_scalar_key: str | None = None
    block_scalar_style: str | None = None
    block_scalar_lines: list[str] = []

    def finish_block_scalar() -> None:
        nonlocal block_scalar_key, block_scalar_style, block_scalar_lines
        if block_scalar_key is None:
            return
        if block_scalar_style == ">":
            scalar_value = " ".join(item.strip() for item in block_scalar_lines if item.strip())
        else:
            scalar_value = "\n".join(block_scalar_lines).strip()
        values[block_scalar_key] = scalar_value
        block_scalar_key = None
        block_scalar_style = None
        block_scalar_lines = []

    for line in block.splitlines():
        if block_scalar_key is not None:
            if not line or line.startswith("  "):
                block_scalar_lines.append(line[2:] if line.startswith("  ") else "")
                continue
            finish_block_scalar()
        if not line:
            continue
        if line.startswith(" "):
            if not line.startswith("  ") or line.startswith("   ") or nested_key != "metadata":
                errors.append(f"{relative_name(path, root)}: unsupported frontmatter indentation {line!r}")
                continue
            nested = values.get("metadata")
            if not isinstance(nested, dict) or ":" not in line:
                errors.append(f"{relative_name(path, root)}: metadata must be a mapping")
                continue
            key, value = line.strip().split(":", 1)
            key = key.strip()
            if not key or key in nested:
                errors.append(f"{relative_name(path, root)}: invalid or duplicate metadata key {key!r}")
                continue
            nested[key] = value.strip().strip("\"'")
            continue
        if ":" not in line:
            errors.append(f"{relative_name(path, root)}: invalid top-level frontmatter line {line!r}")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in values:
            errors.append(f"{relative_name(path, root)}: duplicate frontmatter key {key!r}")
            continue
        scalar = value.strip()
        if scalar in {">", "|"}:
            values[key] = ""
            block_scalar_key = key
            block_scalar_style = scalar
            nested_key = None
            continue
        if key == "metadata":
            if scalar:
                errors.append(f"{relative_name(path, root)}: metadata must be a mapping")
                values[key] = scalar.strip("\"'")
                nested_key = None
            else:
                values[key] = {}
                nested_key = key
        else:
            values[key] = scalar.strip("\"'")
            nested_key = None
    finish_block_scalar()
    return values, errors


def validate_skills(root: Path, require_exact_core: bool = True) -> list[str]:
    errors: list[str] = []
    skill_files = sorted((root / ".agents" / "skills").glob("*/SKILL.md"))
    names = {path.parent.name for path in skill_files}
    if require_exact_core and names != SHIPPED_SKILLS:
        missing = SHIPPED_SKILLS - names
        unexpected = names - SHIPPED_SKILLS
        if missing:
            errors.append(f"required shipped skills missing {sorted(missing)}")
        if unexpected:
            errors.append(f"unexpected source-shipped skills {sorted(unexpected)}")
    elif not require_exact_core and not SHIPPED_SKILLS.issubset(names):
        errors.append(
            f"required toolkit skills must include {sorted(SHIPPED_SKILLS)}; found {sorted(names)}"
        )
    all_skill_files = sorted((root / ".agents" / "skills").rglob("SKILL.md"))
    if require_exact_core and len(all_skill_files) != len(SHIPPED_SKILLS):
        errors.append(
            f"expected exactly {len(SHIPPED_SKILLS)} shipped SKILL.md files; found {len(all_skill_files)}"
        )

    for path in skill_files:
        is_core = path.parent.name in CORE_SKILLS
        is_shipped = path.parent.name in SHIPPED_SKILLS
        values, frontmatter_errors = parse_frontmatter(path, root)
        errors.extend(frontmatter_errors)
        required = {"name", "description"}
        if is_shipped:
            required.update({"license", "metadata"})
        missing = required - values.keys()
        if missing:
            errors.append(f"{path.relative_to(root)}: missing frontmatter fields {sorted(missing)}")
        if is_shipped:
            unexpected = values.keys() - ALLOWED_SKILL_FRONTMATTER
            if unexpected:
                errors.append(f"{path.relative_to(root)}: non-portable frontmatter fields {sorted(unexpected)}")
        if values.get("name") != path.parent.name:
            errors.append(f"{path.relative_to(root)}: name must match directory")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", values.get("name", "")):
            errors.append(f"{path.relative_to(root)}: name must use lowercase alphanumeric hyphen form")
        description = values.get("description", "")
        if is_shipped and not description.endswith("."):
            errors.append(f"{path.relative_to(root)}: description must end with a period")
        if is_core:
            missing_signals = [
                pattern
                for pattern in CORE_DESCRIPTION_SIGNALS[path.parent.name]
                if re.search(pattern, description, re.IGNORECASE) is None
            ]
            if missing_signals:
                errors.append(
                    f"{path.relative_to(root)}: discovery description lacks trigger or boundary signals"
                )

        text = read_text_checked(path, root)
        if is_shipped:
            metadata = values.get("metadata")
            if not isinstance(metadata, dict):
                errors.append(f"{path.relative_to(root)}: metadata must be a frontmatter mapping")
                metadata = {}
            author = metadata.get("author")
            version = metadata.get("version")
            if not isinstance(author, str) or not author or author.startswith("Hermes Agent"):
                errors.append(f"{path.relative_to(root)}: metadata.author must credit the human contributor first")
            if not isinstance(version, str) or not re.fullmatch(r"0\.\d+\.\d+", version):
                errors.append(f"{path.relative_to(root)}: metadata.version must be a pre-1.0 semantic version string")
            for ref in sorted((path.parent / "references").glob("*.md")):
                if ref.name not in text:
                    errors.append(f"{path.relative_to(root)}: does not route to reference {ref.name}")

        subtree_markdown = "\n".join(
            read_text_checked(item, root) for item in path.parent.rglob("*.md")
        )
        if is_core:
            for asset in sorted((path.parent / "assets").glob("*")):
                if asset.is_file() and asset.name not in subtree_markdown:
                    errors.append(f"{asset.relative_to(root)}: asset has no Markdown consumer")

        core_text = "\n".join(
            read_text_checked(item, root)
            for item in path.parent.rglob("*")
            if item.is_file() and item.suffix in {".md", ".txt"}
        )
        if is_core:
            match = BANNED_CORE_PRODUCTS.search(core_text)
            if match:
                errors.append(f"{path.parent.relative_to(root)}: product-specific core binding {match.group(0)!r}")

    return errors


def validate_version(root: Path) -> list[str]:
    """Keep release-owned version metadata synchronized."""
    version_path = root / "VERSION"
    try:
        version = read_text_checked(version_path, root).strip()
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"VERSION: missing or unreadable release version: {exc}"]
    errors: list[str] = []
    if re.fullmatch(r"0\.\d+\.\d+", version) is None:
        errors.append("VERSION: expected a pre-1.0 semantic version")
    for skill in sorted(SHIPPED_SKILLS):
        path = root / ".agents" / "skills" / skill / "SKILL.md"
        try:
            values, frontmatter_errors = parse_frontmatter(path, root)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{relative_name(path, root)}: cannot verify release version: {exc}")
            continue
        errors.extend(frontmatter_errors)
        metadata = values.get("metadata")
        skill_version = metadata.get("version") if isinstance(metadata, dict) else None
        if skill_version != version:
            errors.append(
                f"{relative_name(path, root)}: metadata.version {skill_version!r} "
                f"does not match VERSION {version!r}"
            )
    learning_template = root / ".agent-system" / "templates" / "learning.template.yaml"
    try:
        learning = load_json(learning_template, root)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(
            f"{relative_name(learning_template, root)}: cannot verify toolkit_version: {exc}"
        )
    else:
        template_version = learning.get("toolkit_version") if isinstance(learning, dict) else None
        if template_version != version:
            errors.append(
                f"{relative_name(learning_template, root)}: toolkit_version "
                f"{template_version!r} does not match VERSION {version!r}"
            )
    return errors


def validate_markdown_links(root: Path, paths: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    markdown_paths = sorted(root.rglob("*.md")) if paths is None else sorted(paths)
    for path in markdown_paths:
        text = read_text_checked(path, root)
        for raw_target in markdown_link_targets(text):
            target, separator, fragment = raw_target.strip().strip("<>").partition("#")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            resolved = (path.parent / unquote(target)).resolve() if target else path.resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(root)}: link escapes repository: {raw_target}")
                continue
            if not resolved.exists():
                errors.append(f"{path.relative_to(root)}: broken local link {raw_target}")
                continue
            if separator and resolved.is_file() and fragment:
                anchors = markdown_anchors(read_text_checked(resolved, root))
                if unquote(fragment).lower() not in anchors:
                    errors.append(f"{path.relative_to(root)}: missing local fragment {raw_target}")
    return errors


def markdown_link_targets(text: str) -> list[str]:
    """Extract inline Markdown destinations, including balanced parentheses."""
    text = FENCED_CODE_RE.sub("", text)
    targets: list[str] = []
    cursor = 0
    while True:
        marker = text.find("](", cursor)
        if marker < 0:
            return targets
        index = marker + 2
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "<":
            end = text.find(">", index + 1)
            if end >= 0:
                targets.append(text[index + 1 : end])
                cursor = end + 1
                continue
        depth = 1
        chars: list[str] = []
        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text):
                chars.extend((char, text[index + 1]))
                index += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            elif char.isspace() and depth == 1:
                break
            chars.append(char)
            index += 1
        if chars:
            targets.append("".join(chars))
        cursor = max(index + 1, marker + 2)


def markdown_anchors(text: str) -> set[str]:
    """Build GitHub-style heading anchors plus explicit HTML ids."""
    visible_text = FENCED_CODE_RE.sub("", text)
    anchors = {
        match.group(1).lower()
        for match in re.finditer(r'(?i)\bid=["\']([^"\']+)["\']', visible_text)
    }
    seen: dict[str, int] = {}
    for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", visible_text):
        heading = re.sub(r"<[^>]+>|[`*_~]", "", match.group(1)).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", heading)
        slug = re.sub(r"\s+", "-", slug)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def _validate_policy_path(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        policy = load_json(path, root)
    except (OSError, ValueError) as exc:
        return [f"{path.relative_to(root)}: invalid JSON-compatible YAML: {exc}"]

    if not isinstance(policy, dict):
        return ["capability policy must be an object"]
    if policy.get("schema_version") != "0.1":
        errors.append("capability policy schema_version must be '0.1'")
    is_template = path.name == "capability-policy.template.yaml"
    required_status = REQUIRED_POLICY_STATUS if is_template else REQUIRED_ACTIVE_POLICY_STATUS
    if policy.get("policy_status") != required_status:
        errors.append(f"capability policy status must be {required_status!r}")
    if not is_template:
        approval = policy.get("approval")
        if not isinstance(approval, dict) or not (
            nonblank(approval.get("authority")) and nonblank(approval.get("evidence_ref"))
        ):
            errors.append("active capability policy needs non-blank approval authority and evidence_ref")

    precedence = policy.get("instruction_precedence")
    if not isinstance(precedence, list) or any(not isinstance(item, str) for item in precedence):
        errors.append("capability policy instruction precedence must be a string list")
    elif precedence != REQUIRED_INSTRUCTION_PRECEDENCE:
        errors.append("capability policy instruction precedence must preserve the complete six-level hierarchy")

    decision_rule = policy.get("decision_rule")
    rule = decision_rule.get("all_must_be_true") if isinstance(decision_rule, dict) else None
    required_rule = {
        "allowed_by_organization_policy",
        "available_to_the_approved_tool",
        "authorized_for_the_current_task",
    }
    if not isinstance(rule, list) or any(not isinstance(item, str) for item in rule):
        errors.append("capability policy decision rule all_must_be_true must be a string list")
    elif len(rule) != len(required_rule) or set(rule) != required_rule:
        errors.append("capability policy decision rule must require organization, tool, and task authorization")

    default_decisions = policy.get("default_decisions")
    if not isinstance(default_decisions, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in default_decisions.items()
    ):
        errors.append("capability policy default_decisions must be a string mapping")
        default_decisions = {}
    defaults = set(default_decisions.values())
    if not {"allowed", "forbidden", "unknown"}.issubset(defaults):
        errors.append("capability policy defaults must include allowed, forbidden, and unknown decisions")
    for key, expected in REQUIRED_POLICY_DEFAULTS.items():
        if default_decisions.get(key) != expected:
            errors.append(f"capability policy default {key!r} must be {expected!r}")

    actions = policy.get("actions", {})
    if not isinstance(actions, dict):
        return errors + ["capability policy actions must be a mapping"]
    expected_buckets = {"allowed", "approval_required", "forbidden"}
    if set(actions) != expected_buckets:
        errors.append("capability policy must define only allowed, approval_required, and forbidden actions")
    bucket_ids: dict[str, set[str]] = {bucket: set() for bucket in expected_buckets}
    for bucket in expected_buckets:
        entries = actions.get(bucket)
        if not isinstance(entries, list) or not entries:
            errors.append(f"capability policy {bucket} actions must be a non-empty object list")
            continue
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                errors.append(f"capability policy {bucket} action {index} must be an object")
                continue
            action_id = item.get("id")
            scope = item.get("scope")
            if not isinstance(action_id, str) or not action_id.strip():
                errors.append(f"capability policy {bucket} action {index} needs a non-empty string id")
            elif action_id in bucket_ids[bucket]:
                errors.append(f"capability policy {bucket} action ID {action_id!r} is duplicated")
            else:
                bucket_ids[bucket].add(action_id)
            if not isinstance(scope, str) or not scope.strip():
                errors.append(f"capability policy {bucket} action {index} needs a non-empty scope string")
    if (
        (bucket_ids["allowed"] & bucket_ids["approval_required"])
        or (bucket_ids["allowed"] & bucket_ids["forbidden"])
        or (bucket_ids["approval_required"] & bucket_ids["forbidden"])
    ):
        errors.append("capability policy action IDs must not overlap decision buckets")
    missing_forbidden = REQUIRED_POLICY_FORBIDDEN_ACTIONS - bucket_ids["forbidden"]
    if missing_forbidden:
        errors.append(f"capability policy forbidden actions missing {sorted(missing_forbidden)}")
    project_configurable = (
        bucket_ids["approval_required"]
        if is_template
        else set().union(*bucket_ids.values())
    )
    missing_approval = REQUIRED_POLICY_APPROVAL_ACTIONS - project_configurable
    if missing_approval:
        required_location = "approval-required" if is_template else "classified"
        errors.append(
            f"capability policy {required_location} actions missing {sorted(missing_approval)}"
        )
    missing_allowed = REQUIRED_POLICY_ALLOWED_ACTIONS - bucket_ids["allowed"]
    if missing_allowed:
        errors.append(f"capability policy allowed actions missing {sorted(missing_allowed)}")

    fallback = policy.get("fallback_when_capability_absent")
    if not isinstance(fallback, list) or any(not isinstance(item, str) or not item for item in fallback):
        errors.append("capability policy missing-capability fallback must be a non-empty string list")
        fallback = []
    if len(fallback) < 3:
        errors.append("capability policy fallback must cover static analysis, unverified assumptions, and operator runbook")
    fallback_text = " ".join(fallback).lower().replace("_", " ")
    if fallback and not (
        "static analysis" in fallback_text
        and "unverified assumptions" in fallback_text
        and any(term in fallback_text for term in ("command", "query", "runbook"))
    ):
        errors.append("capability policy fallback must explicitly name static analysis, unverified assumptions, and an operator command/query/runbook")

    artifact_rules = policy.get("artifact_data_rules", {})
    forbidden_values = artifact_rules.get("forbidden") if isinstance(artifact_rules, dict) else None
    if not isinstance(forbidden_values, list) or any(not isinstance(item, str) for item in forbidden_values):
        errors.append("capability policy artifact forbidden rules must be a string list")
        forbidden_values = []
    forbidden_artifact = {item.lower() for item in forbidden_values}
    if not REQUIRED_ARTIFACT_FORBIDDEN.issubset(forbidden_artifact):
        errors.append("capability policy must forbid secrets, raw customer rows, and hidden chain-of-thought in artifacts")
    return [f"{relative_name(path, root)}: {error}" for error in errors]


def validate_policy(root: Path) -> list[str]:
    policy_dir = root / ".agent-system" / "policy"
    template = policy_dir / "capability-policy.template.yaml"
    paths = [template]
    active = policy_dir / "capability-policy.yaml"
    if active.exists():
        paths.append(active)
    errors: list[str] = []
    for path in paths:
        errors.extend(_validate_policy_path(root, path))
    return errors


def validate_run_contract(root: Path) -> list[str]:
    errors: list[str] = []
    schema_path = root / ".agent-system" / "schemas" / "run.schema.json"
    try:
        schema = load_json(schema_path, root)
    except (OSError, ValueError) as exc:
        return [f"{schema_path.relative_to(root)}: invalid JSON Schema document: {exc}"]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("run schema must declare JSON Schema draft 2020-12")
    if schema.get("type") != "object" or not schema.get("required"):
        errors.append("run schema must define a required object contract")
    errors.extend(f"{schema_path.relative_to(root)}: {item}" for item in schema_definition_errors(schema))

    candidates = [root / ".agent-system" / "templates" / "run.template.yaml"]
    runs_dir = root / ".agent-system" / "runs"
    if runs_dir.exists():
        candidates.extend(sorted(runs_dir.rglob("run.yaml")))
    for path in candidates:
        try:
            instance = load_json(path, root)
        except (OSError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: invalid JSON-compatible YAML: {exc}")
            continue
        for error in schema_errors(instance, schema):
            errors.append(f"{path.relative_to(root)}: {error}")
        if isinstance(instance, dict):
            errors.extend(run_semantic_errors(instance, path, root))
    return errors


def learning_semantic_errors(
    instance: dict[str, Any], path: Path, root: Path
) -> list[str]:
    """Keep a learning record linked to its sibling run and routing event."""
    errors: list[str] = []
    name = relative_name(path, root)
    expected_ref = f".agent-system/runs/{path.parent.name}/run.yaml"
    run_ref = instance.get("run_ref")
    if run_ref != expected_ref:
        errors.append(f"{name}: run_ref must identify sibling {expected_ref}")
    else:
        run_path = root / run_ref
        if run_path.is_symlink() or not run_path.is_file():
            errors.append(f"{name}: referenced run does not exist: {run_ref}")

    routing = instance.get("routing")
    routing = routing if isinstance(routing, dict) else {}
    corrected = routing.get("corrected")
    initial_mode = routing.get("initial_mode")
    final_mode = routing.get("mode")
    initial_skill = routing.get("initial_skill")
    final_skill = routing.get("skill")
    if corrected is True:
        initial_values = (
            (initial_skill, final_skill),
            (initial_mode, final_mode),
        )
        if not any(nonblank(initial) for initial, _ in initial_values):
            errors.append(f"{name}: corrected routing requires an initial_skill or initial_mode")
        elif not any(
            nonblank(initial) and initial != final for initial, final in initial_values
        ):
            errors.append(f"{name}: corrected routing must differ from the initial routing")
    elif initial_mode is not None or initial_skill is not None:
        errors.append(f"{name}: uncorrected routing must not record initial_skill or initial_mode")

    request = instance.get("request")
    topics = request.get("topics") if isinstance(request, dict) else None
    if isinstance(topics, list) and len(topics) != len(set(topics)):
        errors.append(f"{name}: request topics must not contain duplicates")
    if instance.get("schema_version") in {"0.2", "0.3"}:
        missing_initial = {"initial_skill", "initial_mode"} - routing.keys()
        if missing_initial:
            errors.append(
                f"{name}: schema_version {instance.get('schema_version')} routing "
                f"is missing {sorted(missing_initial)}"
            )
        timestamp = instance.get("timestamp")
        if not nonblank(timestamp):
            errors.append(
                f"{name}: schema_version {instance.get('schema_version')} requires a timestamp"
            )
        else:
            try:
                date.fromisoformat(timestamp)
            except ValueError:
                errors.append(f"{name}: timestamp must be a real YYYY-MM-DD date")
        if not nonblank(instance.get("toolkit_version")):
            errors.append(
                f"{name}: schema_version {instance.get('schema_version')} requires a toolkit_version"
            )
    is_v03 = instance.get("schema_version") == "0.3"
    signals = instance.get("signals") or []
    if is_v03:
        outcome_value = instance.get("outcome")
        outcome = outcome_value if isinstance(outcome_value, dict) else {}
        required_outcome_fields = {"execution", "user_outcome", "reason_tags"}
        missing_outcome = required_outcome_fields - outcome.keys()
        if missing_outcome:
            errors.append(
                f"{name}: schema_version 0.3 outcome is missing "
                f"{sorted(missing_outcome)}"
            )
        reason_tags = outcome.get("reason_tags")
        if isinstance(reason_tags, list) and len(reason_tags) != len(set(reason_tags)):
            errors.append(f"{name}: outcome reason_tags must not contain duplicates")
        if isinstance(signals, list) and len(signals) > 3:
            errors.append(f"{name}: schema_version 0.3 allows at most 3 signals")
    for signal_index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            continue
        if is_v03:
            required_signal_fields = {
                "type",
                "scope",
                "importance",
                "summary",
                "suggested_change",
                "evidence_ref",
            }
            missing_signal = required_signal_fields - signal.keys()
            if missing_signal:
                errors.append(
                    f"{name}: $.signals[{signal_index}] is missing actionable fields "
                    f"{sorted(missing_signal)}"
                )
            elif not nonblank(signal.get("suggested_change")) or not nonblank(
                signal.get("evidence_ref")
            ):
                errors.append(
                    f"{name}: $.signals[{signal_index}] needs non-blank "
                    "suggested_change and evidence_ref"
                )
        evidence_ref = signal.get("evidence_ref")
        if evidence_ref is None or evidence_ref == "":
            continue
        evidence_target = str(evidence_ref).split("#", 1)[0].strip()
        relative = Path(evidence_target)
        valid_target = (
            bool(evidence_target)
            and evidence_target == run_ref
            and not relative.is_absolute()
        )
        if valid_target:
            try:
                evidence_path = (root / relative).resolve(strict=True)
                evidence_path.relative_to(root.resolve())
                valid_target = evidence_path.is_file() and not (root / relative).is_symlink()
            except (OSError, ValueError):
                valid_target = False
        if not valid_target:
            errors.append(
                f"{name}: $.signals[{signal_index}].evidence_ref must point to its existing sibling run_ref: {evidence_ref}"
            )
    errors.extend(
        f"{name}: {item}"
        for item in _learning_artifact_forbidden_keys(instance, "learning")
    )
    return errors


def validate_learning_contract(root: Path) -> list[str]:
    """Validate compact learning records while accepting historical run-only records."""
    errors: list[str] = []
    schema_path = root / ".agent-system" / "schemas" / "learning.schema.json"
    try:
        schema = load_json(schema_path, root)
    except (OSError, ValueError) as exc:
        return [
            f"{relative_name(schema_path, root)}: invalid JSON Schema document: {exc}"
        ]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("learning schema must declare JSON Schema draft 2020-12")
    if schema.get("type") != "object" or not schema.get("required"):
        errors.append("learning schema must define a required object contract")
    errors.extend(
        f"{relative_name(schema_path, root)}: {item}"
        for item in schema_definition_errors(schema)
    )

    template = root / ".agent-system" / "templates" / "learning.template.yaml"
    candidates = [template]
    runs_dir = root / ".agent-system" / "runs"
    if runs_dir.exists():
        candidates.extend(sorted(runs_dir.rglob("learning.yaml")))
    for path in candidates:
        try:
            instance = load_json(path, root)
        except (OSError, ValueError) as exc:
            errors.append(
                f"{relative_name(path, root)}: invalid JSON-compatible YAML: {exc}"
            )
            continue
        errors.extend(
            f"{relative_name(path, root)}: {item}"
            for item in schema_errors(instance, schema)
        )
        if path != template and isinstance(instance, dict):
            errors.extend(learning_semantic_errors(instance, path, root))
    return errors

def _policy_path_for_ref(root: Path, policy_ref: Any) -> Path:
    if not nonblank(policy_ref):
        raise ValueError("policy_ref must be a non-blank repository-relative path")
    relative = Path(policy_ref)
    if relative.is_absolute() or _unsafe_fixture_path(policy_ref):
        raise ValueError(f"unsafe policy_ref {policy_ref!r}")
    path = root / relative
    try:
        path.resolve().relative_to((root / ".agent-system" / "policy").resolve())
    except ValueError as exc:
        raise ValueError(f"policy_ref must point inside .agent-system/policy: {policy_ref!r}") from exc
    return path


def _policy_capability_sets(root: Path, policy_ref: Any) -> dict[str, set[str]]:
    """Load action IDs by decision class from the run's exact policy reference."""
    path = _policy_path_for_ref(root, policy_ref)
    policy = load_json(path, root)
    actions = policy.get("actions") if isinstance(policy, dict) else None
    if not isinstance(actions, dict):
        raise ValueError(f"policy_ref has no action mapping: {policy_ref!r}")
    return {
        bucket: {
            item.get("id")
            for item in actions.get(bucket, [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for bucket in ("allowed", "approval_required", "forbidden")
    }


def run_semantic_errors(instance: dict[str, Any], path: Path, root: Path) -> list[str]:
    """Reject run records whose approval or claim semantics are inconsistent."""
    errors: list[str] = []
    name = relative_name(path, root)
    task = instance.get("task")
    task_mode = task.get("mode") if isinstance(task, dict) else None
    if not isinstance(task, dict) or not nonblank(task.get("id")):
        errors.append(f"{name}: task.id must be non-blank")
    if not isinstance(task, dict) or not nonblank(task.get("goal")):
        errors.append(f"{name}: task.goal must be non-blank")
    acceptance = task.get("acceptance") if isinstance(task, dict) else None
    if not isinstance(acceptance, list) or not acceptance or any(
        not nonblank(item) for item in acceptance
    ):
        errors.append(f"{name}: task.acceptance must be a non-empty list of non-blank strings")
    policy = instance.get("policy")
    policy = policy if isinstance(policy, dict) else {}
    policy_ref = policy.get("policy_ref")
    gates = policy.get("approval_gates")
    gates = gates if isinstance(gates, list) else []
    boundary = policy.get("authorization_boundary")
    boundary = boundary if isinstance(boundary, list) else []
    gate_map: dict[str, dict[str, Any]] = {}
    for gate in gates:
        if not isinstance(gate, dict):
            errors.append(f"{name}: every approval gate must be an object")
            continue
        action = gate.get("action")
        if nonblank(action):
            action = action.strip()
            if action in gate_map:
                errors.append(f"{name}: approval gate action {action!r} is duplicated")
            gate_map[action] = gate
        else:
            errors.append(f"{name}: every approval gate needs a non-blank action")
        if gate.get("status") == "approved" and not (
            nonblank(gate.get("authority")) and nonblank(gate.get("evidence_ref"))
        ):
            errors.append(f"{name}: approved gate {action!r} needs authority and evidence_ref")
    valid_boundary = [item for item in boundary if nonblank(item)]
    if len(valid_boundary) != len(boundary):
        errors.append(f"{name}: authorization boundary entries must be non-blank strings")
    if task_mode == "controlled":
        if not gate_map:
            errors.append(f"{name}: controlled mode requires at least one valid approval gate")
        if not valid_boundary:
            errors.append(f"{name}: controlled mode requires a non-empty authorization boundary")

    results = instance.get("results")
    results = results if isinstance(results, dict) else {}
    execution = instance.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    provenance = instance.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    inputs = provenance.get("inputs")
    inputs = inputs if isinstance(inputs, list) else []
    for index, input_item in enumerate(inputs):
        if not isinstance(input_item, dict) or not nonblank(input_item.get("kind")):
            errors.append(f"{name}: provenance input {index} needs a non-blank kind")
        if not isinstance(input_item, dict) or not nonblank(input_item.get("ref")):
            errors.append(f"{name}: provenance input {index} needs a non-blank ref")
    commands = execution.get("commands")
    commands = commands if isinstance(commands, list) else []
    try:
        capability_sets = _policy_capability_sets(root, policy_ref)
    except (OSError, ValueError) as exc:
        errors.append(f"{name}: cannot load exact policy_ref: {exc}")
        capability_sets = {"allowed": set(), "approval_required": set(), "forbidden": set()}
    template_run = root / ".agent-system" / "templates" / "run.template.yaml"
    if path.resolve() != template_run.resolve():
        active_policy = root / ".agent-system" / "policy" / "capability-policy.yaml"
        expected_policy = (
            active_policy
            if active_policy.is_file()
            else root / ".agent-system" / "policy" / "capability-policy.template.yaml"
        )
        try:
            referenced_policy = _policy_path_for_ref(root, policy_ref)
        except ValueError:
            referenced_policy = None
        if referenced_policy is None or referenced_policy.resolve() != expected_policy.resolve():
            errors.append(
                f"{name}: run policy_ref must identify active policy {expected_policy.relative_to(root)}"
            )
    all_capabilities = set().union(*capability_sets.values())
    for action in gate_map:
        if action not in capability_sets["approval_required"]:
            errors.append(f"{name}: approval gate {action!r} is not an approval-required capability")
    command_by_id: dict[str, dict[str, Any]] = {}
    succeeded: list[dict[str, Any]] = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        command_id = command.get("id")
        if nonblank(command_id):
            command_id = command_id.strip()
            if command_id in command_by_id:
                errors.append(f"{name}: command ID {command_id!r} is duplicated")
            command_by_id[command_id] = command
        else:
            errors.append(f"{name}: every command needs a non-empty string ID")
        kind = command.get("type", "command")
        if kind not in {"command", "operation"}:
            errors.append(f"{name}: command {command_id!r} has invalid type {kind!r}")
            kind = "command"
        if kind == "command":
            if not nonblank(command.get("command")):
                errors.append(f"{name}: command {command_id!r} needs non-empty command text")
            if "description" in command:
                errors.append(f"{name}: command {command_id!r} must not record an operation description")
        else:
            if not nonblank(command.get("description")):
                errors.append(f"{name}: operation {command_id!r} needs non-empty description text")
            if "command" in command:
                errors.append(f"{name}: operation {command_id!r} must not record command text")
        status = command.get("status")
        exit_code = command.get("exit_code")
        if not isinstance(status, str) or status not in {
            "succeeded",
            "failed",
            "blocked",
            "not_run",
        }:
            errors.append(f"{name}: command {command_id!r} has invalid status {status!r}")
        if not nonblank(command.get("evidence_ref")):
            errors.append(f"{name}: command {command_id!r} needs evidence_ref")
        if "sanitized_summary" in command and not nonblank(command.get("sanitized_summary")):
            errors.append(f"{name}: command {command_id!r} sanitized_summary must be non-blank")
        if status == "succeeded":
            succeeded.append(command)
            if kind == "command" and exit_code != 0:
                errors.append(f"{name}: succeeded command {command_id!r} requires exit_code 0")
        elif kind == "command" and status == "failed" and (
            not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code == 0
        ):
            errors.append(f"{name}: failed command {command_id!r} requires a non-zero exit_code")
        elif kind == "command" and isinstance(status, str) and status in {"blocked", "not_run"} and exit_code is not None:
            errors.append(f"{name}: {status} command {command_id!r} requires a null exit_code")
        if kind == "operation" and exit_code is not None:
            errors.append(f"{name}: operation {command_id!r} requires a null exit_code")

        capability = command.get("capability")
        gate_ref = command.get("approval_gate_ref")
        attempted = isinstance(status, str) and status in {"succeeded", "failed"}
        if not nonblank(capability) or capability not in all_capabilities:
            errors.append(f"{name}: command {command_id!r} has unknown capability {capability!r}")
        elif capability in capability_sets["forbidden"] and attempted:
            errors.append(f"{name}: command {command_id!r} attempted forbidden capability {capability!r}")
        elif capability in capability_sets["approval_required"] and attempted:
            gate = gate_map.get(gate_ref.strip()) if nonblank(gate_ref) else None
            if gate_ref != capability or gate is None or gate.get("status") != "approved":
                errors.append(
                    f"{name}: command {command_id!r} requires an approved gate for {capability!r}"
                )
        elif capability in capability_sets["allowed"] and gate_ref:
            errors.append(f"{name}: allowed command {command_id!r} must not claim an approval gate")

    if results.get("status") == "completed" and not succeeded:
        errors.append(f"{name}: completed results require at least one succeeded command")

    tests = results.get("tests")
    tests = tests if isinstance(tests, list) else []
    for test in tests:
        if not isinstance(test, dict) or test.get("status") != "passed":
            continue
        command_ref = test.get("command_ref")
        evidence_ref = test.get("evidence_ref")
        if "sanitized_summary" in test and not nonblank(test.get("sanitized_summary")):
            errors.append(f"{name}: passed test sanitized_summary must be non-blank when present")
        if not nonblank(command_ref) and not nonblank(evidence_ref):
            errors.append(f"{name}: passed tests need a command_ref or evidence_ref")
        if command_ref is not None:
            command = command_by_id.get(command_ref.strip()) if nonblank(command_ref) else None
            if command is None or command.get("status") != "succeeded" or command.get("exit_code") != 0:
                errors.append(f"{name}: passed test references non-succeeded command {command_ref!r}")

    artifacts = results.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, list) else []
    artifact_refs: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            errors.append(f"{name}: every result artifact must be an object")
            continue
        artifact_ref = item.get("ref")
        if not nonblank(artifact_ref):
            errors.append(f"{name}: every result artifact needs a non-blank ref")
            continue
        if not nonblank(item.get("kind")):
            errors.append(f"{name}: artifact {artifact_ref!r} needs a non-blank kind")
        normalized_ref = artifact_ref.strip()
        if normalized_ref in artifact_refs:
            errors.append(f"{name}: artifact ref {normalized_ref!r} is duplicated")
        artifact_refs.add(normalized_ref)
    metrics = results.get("metrics")
    metrics = metrics if isinstance(metrics, list) else []
    valid_metrics: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        artifact_ref = metric.get("artifact_ref")
        value = metric.get("value")
        baseline_value = metric.get("baseline_value")
        if isinstance(value, str) and not value.strip():
            errors.append(f"{name}: metric value must not be a blank string")
        if isinstance(baseline_value, str) and not baseline_value.strip():
            errors.append(f"{name}: metric baseline_value must not be a blank string")
        has_value = (
            isinstance(value, str) and bool(value.strip())
        ) or (isinstance(value, (int, float)) and not isinstance(value, bool))
        if value is not None or baseline_value is not None:
            if not nonblank(artifact_ref):
                errors.append(f"{name}: recorded metric or baseline values need an artifact_ref")
            elif artifact_ref.strip() not in artifact_refs:
                errors.append(f"{name}: metric artifact_ref {artifact_ref!r} is not a recorded artifact")
            elif has_value and all(
                nonblank(metric.get(field))
                for field in ("name", "population", "implementation")
            ):
                valid_metrics.append(metric)
    if results.get("decision") == "accept":
        if not valid_metrics:
            errors.append(f"{name}: accept decision requires a non-null artifact-backed metric")
        if results.get("status") not in {"completed", "partial"}:
            errors.append(f"{name}: accept decision requires completed or partial results status")
    return errors


def _unsafe_fixture_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return True
    if UNSAFE_FIXTURE_PATH_RE.search(value):
        return True
    parts = re.split(r"[\\/]", value)
    return any(part in {"", ".", ".."} for part in parts)


def validate_evals(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        cases_doc = load_json(root / "evals" / "cases" / "behavioral-cases.json", root)
        fixtures_doc = load_json(root / "evals" / "fixtures" / "synthetic-fixtures.json", root)
        rubric_doc = load_json(root / "evals" / "rubrics" / "behavioral-rubric.json", root)
    except (OSError, ValueError) as exc:
        return [f"evaluation JSON is invalid: {exc}"]

    documents = (("cases", cases_doc, "cases"), ("fixtures", fixtures_doc, "fixtures"), ("rubric", rubric_doc, "criteria"))
    for label, document, collection_key in documents:
        if not isinstance(document, dict) or document.get("schema_version") != "0.1":
            errors.append(f"evaluation {label} document must be a version 0.1 object")
            return errors
        collection = document.get(collection_key)
        if not isinstance(collection, list) or not collection or any(not isinstance(item, dict) for item in collection):
            errors.append(f"evaluation {label} {collection_key} must be a non-empty object list")
            return errors

    fixtures = fixtures_doc.get("fixtures", [])
    fixture_ids: list[str] = []
    for item in fixtures:
        fixture_id = item.get("id")
        if isinstance(fixture_id, str) and fixture_id:
            fixture_ids.append(fixture_id)
        else:
            errors.append("every fixture needs a non-empty string ID")
    if len(fixture_ids) != len(set(fixture_ids)):
        errors.append("fixture IDs must be unique")
    fixture_set = set(fixture_ids)

    for fixture in fixtures:
        fixture_id = fixture.get("id")
        repository = fixture.get("repository")
        raw_evidence = fixture.get("raw_evidence")
        if not isinstance(repository, dict) or not isinstance(repository.get("files"), dict):
            errors.append(f"fixture {fixture_id}: repository.files must be a mapping")
        else:
            files = repository["files"]
            if not files and fixture_id != "generic-ml-question":
                errors.append(
                    "every repository fixture except the generic question must define a file map"
                )
            if any(not isinstance(key, str) or not isinstance(value, str) for key, value in files.items()):
                errors.append(f"fixture {fixture_id}: repository file paths and contents must be strings")
            for relative in files:
                if _unsafe_fixture_path(relative):
                    errors.append(f"fixture {fixture_id}: unsafe repository path {relative!r}")
        if not isinstance(raw_evidence, list) or not raw_evidence or any(
            not isinstance(item, str) or not item for item in raw_evidence
        ):
            errors.append(f"fixture {fixture_id}: raw_evidence must be a non-empty string list")

    criteria = rubric_doc.get("criteria", [])
    rubric_ids = [item.get("id") for item in criteria if isinstance(item.get("id"), str)]
    if len(rubric_ids) != len(set(rubric_ids)) or not rubric_ids:
        errors.append("rubric criteria must be non-empty with unique IDs")
    if any(
        not isinstance(item.get("id"), str)
        or not item.get("id")
        or not isinstance(item.get("question"), str)
        or not item.get("question")
        or type(item.get("blocking")) is not bool
        for item in criteria
    ):
        errors.append("every rubric criterion needs a question and a boolean blocking flag")
    rubric_set = set(rubric_ids)
    if rubric_set != EXPECTED_RUBRICS:
        errors.append(f"rubric IDs must be exactly {sorted(EXPECTED_RUBRICS)}")
    scoring = rubric_doc.get("scoring")
    if not isinstance(scoring, dict) or scoring.get("criterion_values") != ["met", "not_met", "not_observable"]:
        errors.append("rubric scoring must define met, not_met, and not_observable criterion values")

    fixtures_by_id = {
        item["id"]: item for item in fixtures if isinstance(item.get("id"), str) and item.get("id")
    }

    cases = cases_doc.get("cases", [])
    case_ids: list[str] = []
    categories: set[str] = set()
    coverage: set[str] = set()
    for case in cases:
        raw_case_id = case.get("id")
        case_id = raw_case_id if isinstance(raw_case_id, str) and raw_case_id else "<missing-id>"
        if case_id == "<missing-id>":
            errors.append("every behavioral case needs a non-empty string ID")
        else:
            case_ids.append(case_id)
        category = case.get("category")
        if isinstance(category, str):
            categories.add(category)
        missing = REQUIRED_CASE_FIELDS - case.keys()
        if missing:
            errors.append(f"case {case_id}: missing fields {sorted(missing)}")
        if not isinstance(case.get("user_request"), str) or not case.get("user_request"):
            errors.append(f"case {case_id}: request and raw evidence references must be non-empty")
        valid_lists: dict[str, list[str]] = {}
        for field in ("fixture_ids", "raw_evidence_refs", "required_invariants", "forbidden_actions", "rubric_ids", "coverage_tags"):
            value = case.get(field)
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
                errors.append(f"case {case_id}: {field} must be a non-empty string list")
                valid_lists[field] = []
            else:
                valid_lists[field] = value
        coverage.update(valid_lists["coverage_tags"])
        if not isinstance(category, str) or category not in EXPECTED_CATEGORIES:
            errors.append(f"case {case_id}: unknown category {category!r}")
        unknown_fixtures = set(valid_lists["fixture_ids"]) - fixture_set
        if unknown_fixtures:
            errors.append(f"case {case_id}: unknown fixtures {sorted(unknown_fixtures)}")
        unknown_rubrics = set(valid_lists["rubric_ids"]) - rubric_set
        if unknown_rubrics:
            errors.append(f"case {case_id}: unknown rubric criteria {sorted(unknown_rubrics)}")
        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"case {case_id}: expected behavior must be an object")
            expected = {}
        if not {"primary_skill", "mode", "artifact_class", "verdict"}.issubset(expected):
            errors.append(f"case {case_id}: incomplete expected behavior")
        verdict = expected.get("verdict")
        primary_skill = expected.get("primary_skill")
        mode = expected.get("mode")
        artifact_class = expected.get("artifact_class")
        if not isinstance(verdict, str) or verdict not in VALID_CASE_VERDICTS:
            errors.append(f"case {case_id}: unknown expected verdict {verdict!r}")
        if primary_skill is not None and (
            not isinstance(primary_skill, str)
            or re.fullmatch(r"(?:none|[a-z0-9]+(?:-[a-z0-9]+)*)", primary_skill) is None
        ):
            errors.append(f"case {case_id}: unknown expected primary_skill {primary_skill!r}")
        if not isinstance(mode, str) or mode not in VALID_CASE_MODES:
            errors.append(f"case {case_id}: unknown expected mode {mode!r}")
        if not isinstance(artifact_class, str) or artifact_class not in VALID_ARTIFACT_CLASSES:
            errors.append(f"case {case_id}: unknown artifact class {artifact_class!r}")
        for ref in valid_lists["raw_evidence_refs"]:
            match = re.fullmatch(r"fixture://([^/]+)/raw_evidence/(\d+)", ref)
            if not match or match.group(1) not in fixture_set:
                errors.append(f"case {case_id}: invalid raw evidence reference {ref!r}")
                continue
            if match.group(1) not in valid_lists["fixture_ids"]:
                errors.append(f"case {case_id}: evidence fixture {match.group(1)!r} not declared in fixture_ids")
            evidence = fixtures_by_id[match.group(1)].get("raw_evidence", [])
            if not isinstance(evidence, list) or int(match.group(2)) >= len(evidence):
                errors.append(f"case {case_id}: raw evidence index out of range in {ref!r}")

    if len(case_ids) != len(set(case_ids)):
        errors.append("behavioral case IDs must be unique")
    if categories != EXPECTED_CATEGORIES:
        errors.append(f"evaluation categories must be exactly {sorted(EXPECTED_CATEGORIES)}")
    if coverage != REQUIRED_COVERAGE:
        errors.append(f"behavioral coverage must be exactly {sorted(REQUIRED_COVERAGE)}")
    cases_by_id = {
        case["id"]: case for case in cases if isinstance(case.get("id"), str) and case.get("id")
    }
    for tag, case_id in COVERAGE_CASE_IDS.items():
        case = cases_by_id.get(case_id, {})
        tags = case.get("coverage_tags") if isinstance(case, dict) else None
        if not isinstance(tags, list) or tag not in tags:
            errors.append(f"coverage tag {tag!r} must be assigned to case {case_id!r}")
    return errors


def validate_adapters(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in sorted(REQUIRED_ADAPTERS):
        path = root / relative
        if not path.is_file():
            errors.append(f"missing adapter file {relative}")
            continue
        text = read_text_checked(path, root)
        if ".agents/skills" not in text:
            errors.append(f"{relative}: adapter must point to portable skill source")
        if "merge" not in text.lower():
            errors.append(f"{relative}: adapter must describe merge-safe activation")
    return errors


def validate_hygiene(root: Path) -> list[str]:
    errors: list[str] = []
    all_paths = sorted(root.rglob("*"))
    for path in all_paths:
        if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
            continue
        if path.name == "__pycache__" and path.is_dir():
            errors.append(f"generated cache directory {path.relative_to(root)} must not be in the release tree")
        elif path.suffix in {".pyc", ".pyo"}:
            errors.append(f"generated bytecode {path.relative_to(root)} must not be in the release tree")
    maintained = [
        path
        for path in all_paths
        if not any(part in IGNORED_DIRECTORY_NAMES | {"__pycache__"} for part in path.parts)
    ]
    for path in maintained:
        if path.is_symlink():
            errors.append(f"symlinked path {path.relative_to(root)} is not a maintained regular file")
            continue
        if path.is_dir() and not any(path.iterdir()):
            errors.append(f"empty directory {path.relative_to(root)}")
        if path.is_file():
            if path.stat().st_size == 0:
                errors.append(f"empty file {path.relative_to(root)}")
            if path.suffix.lower() in {".md", ".json", ".yaml", ".py", ".css", ".txt"}:
                text = read_text_checked(path, root)
                match = PLACEHOLDER_RE.search(text)
                if match:
                    errors.append(f"{path.relative_to(root)}: unfinished marker {match.group(0)!r}")
    for relative, required_sections in TEMPLATE_REQUIRED_SECTIONS.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing required template {relative}")
            continue
        text = read_text_checked(path, root)
        for section in required_sections:
            if section not in text:
                errors.append(f"{relative}: required template content missing {section!r}")
    return errors


def validate_manifest(root: Path) -> tuple[list[str], set[str]]:
    """Validate hashes for released runtime files without inspecting project-owned files."""
    manifest_path = root / ".agent-system" / "manifest.json"
    try:
        manifest = load_json(manifest_path, root)
    except (OSError, ValueError) as exc:
        return [f".agent-system/manifest.json: invalid runtime manifest: {exc}"], set()
    errors: list[str] = []
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "0.2":
        return [".agent-system/manifest.json: expected schema_version '0.2'"], set()
    version = manifest.get("toolkit_version")
    files = manifest.get("files")
    if not nonblank(version):
        errors.append(".agent-system/manifest.json: toolkit_version must be non-blank")
    if not isinstance(files, dict) or not files:
        return errors + [".agent-system/manifest.json: files must be a non-empty mapping"], set()
    owned: set[str] = set()
    for relative, expected_hash in sorted(files.items()):
        if _unsafe_fixture_path(relative):
            errors.append(f".agent-system/manifest.json: unsafe runtime path {relative!r}")
            continue
        owned.add(relative)
        path = root / relative
        try:
            data = read_text_checked(path, root).encode("utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{relative}: missing or unreadable manifest file: {exc}")
            continue
        actual_hash = hashlib.sha256(data).hexdigest()
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f".agent-system/manifest.json: invalid hash for {relative}")
        elif actual_hash != expected_hash:
            errors.append(f"{relative}: manifest hash mismatch")
    version_path = root / ".agent-system" / "VERSION"
    try:
        installed_version = read_text_checked(version_path, root).strip()
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f".agent-system/VERSION: missing or unreadable version: {exc}")
    else:
        if installed_version != version:
            errors.append(".agent-system/VERSION: version does not match runtime manifest")
    return errors, owned


def _validate_schema_instances(
    root: Path, schema_relative: str, instance_relatives: list[str]
) -> list[str]:
    errors: list[str] = []
    schema_path = root / schema_relative
    try:
        schema = load_json(schema_path, root)
    except (OSError, ValueError) as exc:
        return [f"{schema_relative}: invalid JSON Schema document: {exc}"]
    errors.extend(f"{schema_relative}: {item}" for item in schema_definition_errors(schema))
    for relative in instance_relatives:
        path = root / relative
        if not path.is_file():
            errors.append(f"missing required runtime file {relative}")
            continue
        try:
            instance = load_json(path, root)
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: invalid JSON-compatible YAML: {exc}")
            continue
        errors.extend(f"{relative}: {item}" for item in schema_errors(instance, schema))
    return errors


def validate_project_config(root: Path) -> list[str]:
    candidates = [".agent-system/project.template.yaml"]
    if (root / ".agent-system" / "project.yaml").exists():
        candidates.append(".agent-system/project.yaml")
    return _validate_schema_instances(
        root, ".agent-system/schemas/project.schema.json", candidates
    )


def _learning_artifact_forbidden_keys(
    value: Any, artifact: str, location: str = "$"
) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in FORBIDDEN_LEARNING_ARTIFACT_KEYS:
                errors.append(
                    f"{location}: forbidden sensitive/raw {artifact} field {key!r}"
                )
            errors.extend(
                _learning_artifact_forbidden_keys(child, artifact, f"{location}.{key}")
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(
                _learning_artifact_forbidden_keys(child, artifact, f"{location}[{index}]")
            )
    return errors


def validate_installed_project(root: Path) -> list[str]:
    """Validate toolkit-owned runtime files while leaving project-owned content alone."""
    errors, owned = validate_manifest(root)
    runtime_markdown = [
        root / relative
        for relative in owned
        if relative.endswith(".md") and (root / relative).is_file()
    ]
    errors.extend(validate_markdown_links(root, runtime_markdown))
    checks = (
        lambda value: validate_skills(value, require_exact_core=False),
        validate_policy,
        validate_run_contract,
        validate_learning_contract,
        validate_project_config,
        validate_adapters,
    )
    for check in checks:
        try:
            errors.extend(check(root))
        except (AttributeError, OSError, TypeError, UnicodeError, ValueError) as exc:
            errors.append(f"runtime validation failed closed: {exc}")
    return errors


def validate_overlay(root: Path) -> list[str]:
    """Validate a clean generated overlay and reject undeclared distribution drift."""
    errors = validate_installed_project(root)
    manifest_errors, owned = validate_manifest(root)
    if not manifest_errors:
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file()
        }
        expected = owned | {".agent-system/manifest.json"}
        unexpected = actual - expected
        missing = expected - actual
        if unexpected:
            errors.append(f"overlay contains undeclared files {sorted(unexpected)}")
        if missing:
            errors.append(f"overlay is missing declared files {sorted(missing)}")
    return errors


def validate_distribution(root: Path) -> list[str]:
    """Confirm the checked-in overlay matches the explicit deterministic build."""
    build_script = root / "tooling" / "build-overlay.py"
    output = root / "dist" / "project-overlay"
    if not build_script.is_file():
        return ["distribution drift check is missing tooling/build-overlay.py"]
    result = subprocess.run(
        [sys.executable, "-B", str(build_script), "--check", "--output", str(output)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        return [f"distribution drift: {detail or 'overlay check failed'}"]
    return []


def validate_repository(root: Path = ROOT) -> list[str]:
    checks = (
        validate_skills,
        validate_version,
        validate_markdown_links,
        validate_policy,
        validate_run_contract,
        validate_learning_contract,
        validate_project_config,
        validate_evals,
        validate_adapters,
        validate_hygiene,
        validate_distribution,
    )
    errors: list[str] = []
    for check in checks:
        try:
            errors.extend(check(root))
        except (AttributeError, OSError, TypeError, UnicodeError, ValueError) as exc:
            errors.append(f"{check.__name__}: unsafe or unreadable repository input: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--source", action="store_true", help="validate the toolkit source repository")
    modes.add_argument("--overlay", type=Path, help="validate a generated project overlay")
    modes.add_argument("--installed-project", type=Path, help="validate toolkit files in a target project")
    args = parser.parse_args()
    if args.overlay is not None:
        mode = "overlay"
        errors = validate_overlay(args.overlay.resolve())
    elif args.installed_project is not None:
        mode = "installed project"
        errors = validate_installed_project(args.installed_project.resolve())
    else:
        mode = "source"
        errors = validate_repository(ROOT)
    if errors:
        print(f"FAILED: {len(errors)} validation error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    if mode == "source":
        case_count = len(load_json(ROOT / "evals" / "cases" / "behavioral-cases.json", ROOT)["cases"])
        fixture_count = len(load_json(ROOT / "evals" / "fixtures" / "synthetic-fixtures.json", ROOT)["fixtures"])
        print(
            "PASS: source toolkit valid; 3 core skills plus bundled specialized skills; "
            f"definitions and expected contracts validated for {case_count} behavioral cases "
            f"and {fixture_count} fixtures (agent behavior not executed)"
        )
    else:
        print(f"PASS: {mode} toolkit-owned files are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
