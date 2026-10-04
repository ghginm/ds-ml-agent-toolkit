#!/usr/bin/env python3
"""Sanitized local request-event storage and deterministic pattern aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None


SCHEMA_VERSION = "0.1"
MAX_SLUG_LENGTH = 64
MAX_TOPICS = 12
MAX_REASON_TAGS = 8
SLUG_PATTERN = re.compile(rf"^[a-z0-9][a-z0-9_-]{{0,{MAX_SLUG_LENGTH - 1}}}$")
ROUTE_SEGMENT_PATTERN = rf"[a-z0-9][a-z0-9_-]{{0,{MAX_SLUG_LENGTH - 1}}}"
ROUTE_PATTERN = re.compile(rf"^({ROUTE_SEGMENT_PATTERN})(?:/{ROUTE_SEGMENT_PATTERN})?$")
MAX_ROUTE_LENGTH = 120
TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RUN_REF_PATTERN = re.compile(
    r"^\.agent-system/runs/[A-Za-z0-9][A-Za-z0-9._-]*/run\.yaml$"
)
OUTCOMES = {"completed", "partial", "blocked", "failed", "unknown"}
FORBIDDEN_KEYS = {
    "chain_of_thought",
    "credentials",
    "customer_records",
    "full_prompt",
    "prompt",
    "raw_customer_rows",
    "raw_project_data",
    "raw_query_output",
    "secrets",
    "terminal_dump",
    "terminal_transcript",
    "transcript",
}
EVENT_KEYS = {
    "schema_version",
    "event_id",
    "timestamp",
    "kind",
    "topics",
    "deliverable",
    "route",
    "run_ref",
    "outcome",
    "rework",
    "routing_corrected",
    "reason_tags",
}


def _normalized_key(value: Any) -> str:
    return str(value).lower().replace("-", "_").replace(" ", "_")


def _forbidden_key_errors(value: Any, location: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if _normalized_key(key) in FORBIDDEN_KEYS:
                errors.append(f"{location}: forbidden request metadata field {key!r}")
            errors.extend(_forbidden_key_errors(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_forbidden_key_errors(child, f"{location}[{index}]"))
    return errors


def _timestamp(value: str) -> datetime:
    if TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError("timestamp must use whole-second UTC format YYYY-MM-DDTHH:MM:SSZ")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed


def event_errors(event: Any) -> list[str]:
    """Validate one normalized event without loading project schemas."""
    if not isinstance(event, dict):
        return ["event must be an object"]
    errors = _forbidden_key_errors(event)
    unexpected = sorted(set(event) - EVENT_KEYS)
    missing = sorted(EVENT_KEYS - set(event))
    if unexpected:
        errors.append(f"unexpected fields: {unexpected}")
    if missing:
        errors.append(f"missing fields: {missing}")
        return errors
    if event.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or EVENT_ID_PATTERN.fullmatch(event_id) is None:
        errors.append("event_id must be a stable identifier")
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        errors.append("timestamp must be a UTC string")
    else:
        try:
            _timestamp(timestamp)
        except ValueError as exc:
            errors.append(f"invalid timestamp: {exc}")
    for field in ("kind", "deliverable"):
        value = event.get(field)
        if field == "deliverable" and value is None:
            continue
        if not isinstance(value, str) or SLUG_PATTERN.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase semantic slug")
    topics = event.get("topics")
    if not isinstance(topics, list) or any(
        not isinstance(topic, str) or SLUG_PATTERN.fullmatch(topic) is None
        for topic in topics if isinstance(topics, list)
    ):
        errors.append("topics must be a list of lowercase semantic slugs")
    elif len(topics) > MAX_TOPICS:
        errors.append(f"topics must contain at most {MAX_TOPICS} items")
    elif topics != sorted(set(topics)):
        errors.append("topics must be sorted and unique")
    route = event.get("route")
    if (
        not isinstance(route, str)
        or len(route) > MAX_ROUTE_LENGTH
        or ROUTE_PATTERN.fullmatch(route) is None
    ):
        errors.append(
            f"route must be a normalized route identifier of at most {MAX_ROUTE_LENGTH} characters"
        )
    run_ref = event.get("run_ref")
    if run_ref is not None and (
        not isinstance(run_ref, str) or RUN_REF_PATTERN.fullmatch(run_ref) is None
    ):
        errors.append("run_ref must be null or a canonical run.yaml path")
    if event.get("outcome") not in OUTCOMES:
        errors.append(f"outcome must be one of {sorted(OUTCOMES)}")
    for field in ("rework", "routing_corrected"):
        if not isinstance(event.get(field), bool):
            errors.append(f"{field} must be boolean")
    reason_tags = event.get("reason_tags")
    if not isinstance(reason_tags, list) or any(
        not isinstance(tag, str) or SLUG_PATTERN.fullmatch(tag) is None
        for tag in reason_tags if isinstance(reason_tags, list)
    ):
        errors.append("reason_tags must be a list of lowercase semantic slugs")
    elif len(reason_tags) > MAX_REASON_TAGS:
        errors.append(f"reason_tags must contain at most {MAX_REASON_TAGS} items")
    elif reason_tags != sorted(set(reason_tags)):
        errors.append("reason_tags must be sorted and unique")
    return errors


def normalize_event(
    *,
    kind: str,
    topics: list[str] | tuple[str, ...],
    deliverable: str | None,
    route: str,
    run_ref: str | None,
    outcome: str,
    rework: bool,
    routing_corrected: bool,
    reason_tags: list[str] | tuple[str, ...],
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or str(uuid4()),
        "timestamp": timestamp
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "topics": sorted(set(topics)),
        "deliverable": deliverable,
        "route": route.strip(),
        "run_ref": run_ref,
        "outcome": outcome,
        "rework": rework,
        "routing_corrected": routing_corrected,
        "reason_tags": sorted(set(reason_tags)),
    }
    errors = event_errors(event)
    if errors:
        raise ValueError("; ".join(errors))
    return event


def local_paths(
    project_root: Path,
    *,
    create: bool = False,
) -> tuple[Path, Path, Path]:
    root = project_root.expanduser().resolve(strict=True)
    agent_system = root / ".agent-system"
    local = agent_system / "local"
    if agent_system.is_symlink() or not agent_system.is_dir():
        raise ValueError(f"project root must contain a non-symlink .agent-system directory: {root}")
    if local.is_symlink():
        raise ValueError(".agent-system/local must not be a symlink")
    if create:
        local.mkdir(exist_ok=True)
    elif local.exists() and not local.is_dir():
        raise ValueError(".agent-system/local must be a directory")
    return root, local / "request-events.jsonl", local / "request-patterns.yaml"


def _open_local_directory(local: Path) -> int | None:
    local_descriptor: int | None = None
    if (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
    ):
        local_descriptor = os.open(
            local,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        if not stat.S_ISDIR(os.fstat(local_descriptor).st_mode):
            os.close(local_descriptor)
            raise ValueError(".agent-system/local must be a non-symlink directory")
    return local_descriptor


@contextmanager
def _request_lock(local: Path):
    local_descriptor = _open_local_directory(local)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if local_descriptor is None:
        descriptor = os.open(local / "request-events.lock", flags, 0o600)
    else:
        descriptor = os.open(
            "request-events.lock",
            flags,
            0o600,
            dir_fd=local_descriptor,
        )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("request-events.lock must be a regular non-symlink file")
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - exercised on Windows
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            getattr(msvcrt, "locking")(descriptor, getattr(msvcrt, "LK_LOCK"), 1)
        yield local_descriptor
    finally:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - exercised on Windows
            os.lseek(descriptor, 0, os.SEEK_SET)
            getattr(msvcrt, "locking")(descriptor, getattr(msvcrt, "LK_UNLCK"), 1)
        os.close(descriptor)
        if local_descriptor is not None:
            os.close(local_descriptor)


def _verify_local_directory(local: Path, descriptor: int | None) -> None:
    if descriptor is None:
        if local.is_symlink() or not local.is_dir():
            raise ValueError(".agent-system/local must be a non-symlink directory")
        return
    current = os.stat(local, follow_symlinks=False)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(current.st_mode)
        or current.st_dev != opened.st_dev
        or current.st_ino != opened.st_ino
    ):
        raise ValueError(".agent-system/local changed while request metadata was locked")


def _open_local_file(
    local: Path,
    local_descriptor: int | None,
    name: str,
    flags: int,
    mode: int = 0o600,
) -> int:
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if local_descriptor is None:
        return os.open(local / name, flags, mode)
    return os.open(name, flags, mode, dir_fd=local_descriptor)


def _read_local_text(local: Path, name: str) -> str | None:
    local_descriptor = _open_local_directory(local)
    descriptor: int | None = None
    try:
        try:
            descriptor = _open_local_file(
                local,
                local_descriptor,
                name,
                os.O_RDONLY,
            )
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{name} must be a regular non-symlink file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            text = handle.read()
        descriptor = None
        _verify_local_directory(local, local_descriptor)
        return text
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if local_descriptor is not None:
            os.close(local_descriptor)


def load_events(project_root: Path) -> list[dict[str, Any]]:
    root, events_path, _ = local_paths(project_root)
    if not events_path.parent.exists():
        return []
    text = _read_local_text(events_path.parent, events_path.name)
    if text is None:
        return []
    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise ValueError(f"request-events.jsonl line {line_number} is blank")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"request-events.jsonl line {line_number}: invalid JSON: {exc}") from exc
        errors = event_errors(event)
        if errors:
            raise ValueError(
                f"request-events.jsonl line {line_number}: " + "; ".join(errors)
            )
        event_id = event["event_id"]
        if event_id in event_ids:
            raise ValueError(f"duplicate event_id {event_id!r}")
        event_ids.add(event_id)
        run_ref = event.get("run_ref")
        if run_ref is not None:
            path = root / run_ref
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    f"request-events.jsonl line {line_number}: run_ref does not exist: {run_ref}"
                )
        events.append(event)
    return events


def append_event(project_root: Path, event: dict[str, Any]) -> Path:
    root, events_path, _ = local_paths(project_root, create=True)
    errors = event_errors(event)
    if errors:
        raise ValueError("; ".join(errors))
    with _request_lock(events_path.parent) as local_descriptor:
        existing = load_events(root)
        if any(item["event_id"] == event["event_id"] for item in existing):
            raise ValueError(f"duplicate event_id {event['event_id']!r}")
        run_ref = event.get("run_ref")
        if run_ref is not None:
            path = root / run_ref
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"run_ref does not exist: {run_ref}")
        _verify_local_directory(events_path.parent, local_descriptor)
        line = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        descriptor = _open_local_file(
            events_path.parent,
            local_descriptor,
            events_path.name,
            flags,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("request-events.jsonl must be a regular non-symlink file")
        original_size = os.fstat(descriptor).st_size
        try:
            try:
                written = os.write(descriptor, line)
                if written != len(line):
                    raise OSError("short append to request-events.jsonl")
                os.fsync(descriptor)
            except BaseException:
                os.ftruncate(descriptor, original_size)
                os.fsync(descriptor)
                raise
        finally:
            os.close(descriptor)
    return events_path


def _pattern_key(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event["kind"],
        tuple(event["topics"]),
        event["deliverable"],
        event["route"],
    )


def aggregate(events: list[dict[str, Any]], minimum_count: int = 3) -> dict[str, Any]:
    if minimum_count < 1:
        raise ValueError("minimum_count must be positive")
    ordered = sorted(events, key=lambda event: (event["timestamp"], event["event_id"]))
    window_size = len(ordered) // 2
    older_keys = Counter(_pattern_key(event) for event in ordered[:window_size])
    recent_keys = Counter(
        _pattern_key(event) for event in ordered[len(ordered) - window_size :]
    ) if window_size else Counter()
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in ordered:
        groups[_pattern_key(event)].append(event)
    patterns: list[dict[str, Any]] = []
    for key, grouped in sorted(
        groups.items(),
        key=lambda item: (
            item[0][0],
            item[0][1],
            item[0][2] is not None,
            item[0][2] or "",
            item[0][3],
        ),
    ):
        if len(grouped) < minimum_count:
            continue
        kind, topics, deliverable, route = key
        canonical_key = json.dumps(key, separators=(",", ":"), ensure_ascii=True)
        pattern_id = f"request-{hashlib.sha256(canonical_key.encode('utf-8')).hexdigest()[:12]}"
        rework_count = sum(1 for event in grouped if event["rework"])
        corrections = sum(1 for event in grouped if event["routing_corrected"])
        failures = sum(1 for event in grouped if event["outcome"] in {"blocked", "failed"})
        reason_counts = Counter(
            tag for event in grouped for tag in event.get("reason_tags", [])
        )
        friction = rework_count > 0 or corrections > 0 or failures > 0 or any(
            count > 1 for count in reason_counts.values()
        )
        if recent_keys[key] > older_keys[key]:
            trend = "rising"
        elif recent_keys[key] < older_keys[key]:
            trend = "falling"
        else:
            trend = "stable"
        patterns.append(
            {
                "id": pattern_id,
                "kind": kind,
                "topics": list(topics),
                "deliverable": deliverable,
                "route": route,
                "count": len(grouped),
                "first_seen": grouped[0]["timestamp"],
                "last_seen": grouped[-1]["timestamp"],
                "trend": trend,
                "friction": {
                    "rework_rate": round(rework_count / len(grouped), 6),
                    "routing_corrections": corrections,
                    "failures": failures,
                    "reason_tags": dict(sorted(reason_counts.items())),
                },
                "recommendation": {
                    "type": "improve_existing_skill" if friction else "monitor",
                    "target": route if friction else None,
                },
            }
        )
    latest = ordered[-1]["timestamp"] if ordered else None
    return {
        "schema_version": SCHEMA_VERSION,
        "source_event_count": len(ordered),
        "reviewed_through": latest,
        "minimum_count": minimum_count,
        "patterns": patterns,
    }


def _load_patterns(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("request-patterns.yaml must be a regular non-symlink file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("request-patterns.yaml must contain an object")
    return value


def review_due(
    events: list[dict[str, Any]],
    current: dict[str, Any] | None,
    *,
    review_every: int = 10,
    max_age_days: int = 30,
    now: datetime | None = None,
) -> bool:
    if review_every < 1 or max_age_days < 1:
        raise ValueError("review thresholds must be positive")
    previous_count = current.get("source_event_count", 0) if current else 0
    if len(events) - previous_count >= review_every:
        return True
    if not events or current is None or current.get("reviewed_through") is None:
        return False
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current_time = current_time.astimezone(timezone.utc)
    reviewed = _timestamp(current["reviewed_through"])
    return current_time - reviewed >= timedelta(days=max_age_days)


def _write_patterns_locked(
    patterns_path: Path,
    value: dict[str, Any],
    local_descriptor: int | None,
) -> None:
    _verify_local_directory(patterns_path.parent, local_descriptor)
    temporary_name = f".{patterns_path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = _open_local_file(
        patterns_path.parent,
        local_descriptor,
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    )
    try:
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        if local_descriptor is None:
            os.replace(patterns_path.parent / temporary_name, patterns_path)
        else:
            os.replace(
                temporary_name,
                patterns_path.name,
                src_dir_fd=local_descriptor,
                dst_dir_fd=local_descriptor,
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if local_descriptor is None:
                (patterns_path.parent / temporary_name).unlink(missing_ok=True)
            else:
                os.unlink(temporary_name, dir_fd=local_descriptor)
        except FileNotFoundError:
            pass


def write_patterns(project_root: Path, minimum_count: int = 3) -> Path:
    root, _, patterns_path = local_paths(project_root, create=True)
    with _request_lock(patterns_path.parent) as local_descriptor:
        events = load_events(root)
        value = aggregate(events, minimum_count=minimum_count)
        _write_patterns_locked(patterns_path, value, local_descriptor)
    return patterns_path


def maybe_review(
    project_root: Path,
    *,
    review_every: int = 10,
    max_age_days: int = 30,
    minimum_count: int = 3,
) -> Path | None:
    root, _, patterns_path = local_paths(project_root, create=True)
    with _request_lock(patterns_path.parent) as local_descriptor:
        events = load_events(root)
        current = _load_patterns(patterns_path)
        if not review_due(
            events,
            current,
            review_every=review_every,
            max_age_days=max_age_days,
        ):
            return None
        value = aggregate(events, minimum_count=minimum_count)
        _write_patterns_locked(patterns_path, value, local_descriptor)
    return patterns_path
