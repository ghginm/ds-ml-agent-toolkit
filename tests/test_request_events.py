from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tooling" / "request_events.py"
RECORD = ROOT / "tooling" / "record-request.py"
REVIEW = ROOT / "tooling" / "review-requests.py"


def load_module():
    spec = importlib.util.spec_from_file_location("request_events", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RequestEventTests(unittest.TestCase):
    def project(self, base: Path) -> Path:
        root = base / "project"
        (root / ".agent-system" / "local").mkdir(parents=True)
        shutil.copyfile(
            ROOT / ".agent-system" / "local" / ".gitignore",
            root / ".agent-system" / "local" / ".gitignore",
        )
        return root

    def record(
        self,
        root: Path,
        *,
        kind: str = "technical_report",
        topics: tuple[str, ...] = ("feature_design", "model_evaluation"),
        deliverable: str | None = "pdf",
        route: str = "technical-report",
        run_ref: str | None = None,
        outcome: str = "completed",
        rework: bool = False,
        corrected: bool = False,
        reason_tags: tuple[str, ...] = (),
        event_id: str | None = None,
        timestamp: str | None = None,
        review_every: int = 100,
        minimum_count: int = 3,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-B",
            str(RECORD),
            "--project-root",
            str(root),
            "--kind",
            kind,
            "--route",
            route,
            "--outcome",
            outcome,
            "--review-every",
            str(review_every),
            "--minimum-count",
            str(minimum_count),
        ]
        for topic in topics:
            command.extend(["--topic", topic])
        if deliverable is not None:
            command.extend(["--deliverable", deliverable])
        if run_ref is not None:
            command.extend(["--run-ref", run_ref])
        if rework:
            command.append("--rework")
        if corrected:
            command.append("--routing-corrected")
        for tag in reason_tags:
            command.extend(["--reason-tag", tag])
        if event_id is not None:
            command.extend(["--event-id", event_id])
        if timestamp is not None:
            command.extend(["--timestamp", timestamp])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_ordinary_request_records_sanitized_event_without_formal_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            result = self.record(
                root,
                topics=("model_evaluation", "feature_design", "model_evaluation"),
                event_id="event-ordinary",
                timestamp="2026-10-03T12:00:00Z",
            )
            events_path = root / ".agent-system" / "local" / "request-events.jsonl"
            event = json.loads(events_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse((root / ".agent-system" / "runs").exists())
        self.assertEqual(["feature_design", "model_evaluation"], event["topics"])
        self.assertEqual("technical-report", event["route"])
        self.assertIsNone(event["run_ref"])
        self.assertNotIn("prompt", event)
        self.assertNotIn("chain_of_thought", event)

    def test_request_can_link_to_formal_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            run_dir = root / ".agent-system" / "runs" / "report-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.yaml").write_text("{}\n", encoding="utf-8")
            result = self.record(
                root,
                run_ref=".agent-system/runs/report-1/run.yaml",
                event_id="event-linked",
                timestamp="2026-10-03T12:01:00Z",
            )
            event = json.loads(
                (root / ".agent-system" / "local" / "request-events.jsonl").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(".agent-system/runs/report-1/run.yaml", event["run_ref"])

    def test_thresholded_review_aggregates_frequency_recency_rework_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            first = self.record(
                root,
                event_id="event-1",
                timestamp="2026-10-01T12:00:00Z",
                review_every=3,
                minimum_count=3,
            )
            second = self.record(
                root,
                event_id="event-2",
                timestamp="2026-10-02T12:00:00Z",
                rework=True,
                corrected=True,
                reason_tags=("insufficient_depth",),
                review_every=3,
                minimum_count=3,
            )
            patterns_path = root / ".agent-system" / "local" / "request-patterns.yaml"
            before_threshold = patterns_path.exists()
            third = self.record(
                root,
                event_id="event-3",
                timestamp="2026-10-03T12:00:00Z",
                outcome="failed",
                reason_tags=("insufficient_depth",),
                review_every=3,
                minimum_count=3,
            )
            aggregate = json.loads(patterns_path.read_text(encoding="utf-8"))
            pattern = aggregate["patterns"][0]

        for result in (first, second, third):
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(before_threshold)
        self.assertEqual(3, aggregate["source_event_count"])
        self.assertEqual(3, pattern["count"])
        self.assertEqual("2026-10-03T12:00:00Z", pattern["last_seen"])
        self.assertAlmostEqual(1 / 3, pattern["friction"]["rework_rate"], places=6)
        self.assertEqual(1, pattern["friction"]["routing_corrections"])
        self.assertEqual(1, pattern["friction"]["failures"])
        self.assertEqual(2, pattern["friction"]["reason_tags"]["insufficient_depth"])
        self.assertEqual("improve_existing_skill", pattern["recommendation"]["type"])
        self.assertEqual("technical-report", pattern["recommendation"]["target"])

    def test_aggregate_orders_nullable_deliverables_deterministically(self) -> None:
        request_events = load_module()
        common = {
            "schema_version": "0.1",
            "kind": "technical_report",
            "topics": ["model_evaluation"],
            "route": "technical-report",
            "run_ref": None,
            "outcome": "completed",
            "rework": False,
            "routing_corrected": False,
            "reason_tags": [],
        }
        events = [
            {**common, "event_id": "event-none", "timestamp": "2026-10-01T12:00:00Z", "deliverable": None},
            {**common, "event_id": "event-pdf", "timestamp": "2026-10-02T12:00:00Z", "deliverable": "pdf"},
        ]

        first = request_events.aggregate(events, minimum_count=1)
        second = request_events.aggregate(list(reversed(events)), minimum_count=1)

        self.assertEqual(first, second)
        self.assertEqual([None, "pdf"], [item["deliverable"] for item in first["patterns"]])

    def test_three_identical_events_have_stable_trend(self) -> None:
        request_events = load_module()
        events = []
        for index in range(3):
            events.append(
                {
                    "schema_version": "0.1",
                    "event_id": f"event-{index}",
                    "timestamp": f"2026-10-0{index + 1}T12:00:00Z",
                    "kind": "technical_report",
                    "topics": ["model_evaluation"],
                    "deliverable": "pdf",
                    "route": "technical-report",
                    "run_ref": None,
                    "outcome": "completed",
                    "rework": False,
                    "routing_corrected": False,
                    "reason_tags": [],
                }
            )

        aggregate = request_events.aggregate(events, minimum_count=3)

        self.assertEqual("stable", aggregate["patterns"][0]["trend"])

    def test_review_age_uses_elapsed_utc_time_since_previous_review(self) -> None:
        request_events = load_module()
        current = {
            "source_event_count": 1,
            "reviewed_through": "2026-09-01T12:00:00Z",
        }
        events = [{"timestamp": "2026-09-01T12:00:00Z"}]

        due = request_events.review_due(
            events,
            current,
            review_every=10,
            max_age_days=30,
            now=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(due)

    def test_forced_review_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            for index in range(3):
                result = self.record(
                    root,
                    event_id=f"event-{index}",
                    timestamp=f"2026-10-0{index + 1}T12:00:00Z",
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            command = [
                sys.executable,
                "-B",
                str(REVIEW),
                "--project-root",
                str(root),
                "--force",
                "--minimum-count",
                "3",
            ]
            first = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
            patterns_path = root / ".agent-system" / "local" / "request-patterns.yaml"
            first_bytes = patterns_path.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
            second_bytes = patterns_path.read_bytes()

        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(first_bytes, second_bytes)

    def test_duplicate_event_id_is_rejected_without_rewriting_existing_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            first = self.record(
                root,
                event_id="duplicate-event",
                timestamp="2026-10-03T12:00:00Z",
            )
            events_path = root / ".agent-system" / "local" / "request-events.jsonl"
            before = events_path.read_bytes()
            second = self.record(
                root,
                event_id="duplicate-event",
                timestamp="2026-10-03T12:01:00Z",
            )
            after = events_path.read_bytes()

        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertNotEqual(0, second.returncode)
        self.assertIn("duplicate event_id", second.stderr)
        self.assertEqual(before, after)

    def test_concurrent_duplicate_event_id_appends_exactly_once(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            event = request_events.normalize_event(
                kind="technical_report",
                topics=["model_evaluation"],
                deliverable="pdf",
                route="technical-report",
                run_ref=None,
                outcome="completed",
                rework=False,
                routing_corrected=False,
                reason_tags=[],
                event_id="concurrent-duplicate",
                timestamp="2026-10-03T12:00:00Z",
            )
            original_load_events = request_events.load_events
            duplicate_check_barrier = threading.Barrier(8)

            def synchronized_load_events(project_root: Path):
                events = original_load_events(project_root)
                try:
                    duplicate_check_barrier.wait(timeout=0.5)
                except threading.BrokenBarrierError:
                    pass
                return events

            def append_same_event(_: int) -> str:
                try:
                    request_events.append_event(root, event)
                except ValueError as exc:
                    return str(exc)
                return "appended"

            with mock.patch.object(request_events, "load_events", synchronized_load_events):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(append_same_event, range(8)))
            events_path = root / ".agent-system" / "local" / "request-events.jsonl"
            events = events_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(1, results.count("appended"))
        self.assertEqual(7, sum("duplicate event_id" in result for result in results))
        self.assertEqual(1, len(events))

    def test_concurrent_distinct_appends_are_all_preserved(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            events = [
                request_events.normalize_event(
                    kind="technical_report",
                    topics=["model_evaluation"],
                    deliverable="pdf",
                    route="technical-report",
                    run_ref=None,
                    outcome="completed",
                    rework=False,
                    routing_corrected=False,
                    reason_tags=[],
                    event_id=f"distinct-event-{index}",
                    timestamp=f"2026-10-03T12:{index:02d}:00Z",
                )
                for index in range(6)
            ]
            original_load_events = request_events.load_events
            interleaving_barrier = threading.Barrier(6)

            def synchronized_load_events(project_root: Path):
                loaded = original_load_events(project_root)
                try:
                    interleaving_barrier.wait(timeout=0.5)
                except threading.BrokenBarrierError:
                    pass
                return loaded

            def append_distinct(event: dict) -> str:
                request_events.append_event(root, event)
                return event["event_id"]

            with mock.patch.object(request_events, "load_events", synchronized_load_events):
                with ThreadPoolExecutor(max_workers=6) as executor:
                    appended = list(executor.map(append_distinct, events))
            loaded = request_events.load_events(root)

        self.assertEqual(sorted(event["event_id"] for event in events), sorted(appended))
        self.assertEqual(len(events), len(loaded))

    def test_review_snapshot_holds_same_lock_as_appends(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            first = request_events.normalize_event(
                kind="technical_report",
                topics=["model_evaluation"],
                deliverable="pdf",
                route="technical-report",
                run_ref=None,
                outcome="completed",
                rework=False,
                routing_corrected=False,
                reason_tags=[],
                event_id="event-before-review",
                timestamp="2026-10-03T12:00:00Z",
            )
            second = {**first, "event_id": "event-during-review", "timestamp": "2026-10-03T12:01:00Z"}
            request_events.append_event(root, first)
            aggregate_entered = threading.Event()
            release_aggregate = threading.Event()
            append_started = threading.Event()
            append_completed = threading.Event()
            original_aggregate = request_events.aggregate

            def paused_aggregate(events, minimum_count=3):
                aggregate_entered.set()
                self.assertTrue(release_aggregate.wait(timeout=5))
                return original_aggregate(events, minimum_count=minimum_count)

            def append_during_review():
                append_started.set()
                try:
                    return request_events.append_event(root, second)
                finally:
                    append_completed.set()

            with mock.patch.object(request_events, "aggregate", paused_aggregate):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    review_future = executor.submit(request_events.write_patterns, root, 1)
                    self.assertTrue(aggregate_entered.wait(timeout=5))
                    append_future = executor.submit(append_during_review)
                    self.assertTrue(append_started.wait(timeout=5))
                    self.assertFalse(append_completed.wait(timeout=0.2))
                    release_aggregate.set()
                    review_future.result(timeout=5)
                    append_future.result(timeout=5)
            loaded = request_events.load_events(root)

        self.assertEqual(["event-before-review", "event-during-review"], [event["event_id"] for event in loaded])

    def test_partial_append_rolls_back_to_original_size(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            first = request_events.normalize_event(
                kind="technical_report",
                topics=["model_evaluation"],
                deliverable="pdf",
                route="technical-report",
                run_ref=None,
                outcome="completed",
                rework=False,
                routing_corrected=False,
                reason_tags=[],
                event_id="event-before-short-write",
                timestamp="2026-10-03T12:00:00Z",
            )
            second = {**first, "event_id": "event-short-write", "timestamp": "2026-10-03T12:01:00Z"}
            request_events.append_event(root, first)
            events_path = root / ".agent-system" / "local" / "request-events.jsonl"
            before = events_path.read_bytes()
            real_write = request_events.os.write

            def short_write(descriptor: int, data: bytes) -> int:
                partial = max(1, len(data) // 2)
                real_write(descriptor, data[:partial])
                return partial

            with mock.patch.object(request_events.os, "write", side_effect=short_write):
                with self.assertRaisesRegex(OSError, "short append"):
                    request_events.append_event(root, second)
            after = events_path.read_bytes()
            loaded = request_events.load_events(root)

        self.assertEqual(before, after)
        self.assertEqual([first], loaded)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "requires POSIX no-follow opens")
    def test_local_directory_symlink_swap_is_rejected(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self.project(base)
            event = request_events.normalize_event(
                kind="technical_report",
                topics=["model_evaluation"],
                deliverable="pdf",
                route="technical-report",
                run_ref=None,
                outcome="completed",
                rework=False,
                routing_corrected=False,
                reason_tags=[],
                event_id="event-after-swap",
                timestamp="2026-10-03T12:00:00Z",
            )
            local = root / ".agent-system" / "local"
            original_local = root / ".agent-system" / "local-original"
            external = base / "external"
            external.mkdir()
            external_events = external / "request-events.jsonl"
            external_events.write_text("", encoding="utf-8")
            original_load_events = request_events.load_events

            def swap_after_load(project_root: Path):
                events = original_load_events(project_root)
                local.rename(original_local)
                local.symlink_to(external, target_is_directory=True)
                return events

            with mock.patch.object(request_events, "load_events", swap_after_load):
                with self.assertRaises((OSError, ValueError)):
                    request_events.append_event(root, event)

            self.assertEqual(b"", external_events.read_bytes())
            self.assertFalse((original_local / "request-events.jsonl").exists())

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "requires POSIX no-follow opens")
    def test_ledger_file_symlink_swap_does_not_change_read_snapshot(self) -> None:
        request_events = load_module()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self.project(base)
            original = request_events.normalize_event(
                kind="technical_report",
                topics=["model_evaluation"],
                deliverable="pdf",
                route="technical-report",
                run_ref=None,
                outcome="completed",
                rework=False,
                routing_corrected=False,
                reason_tags=[],
                event_id="original-event",
                timestamp="2026-10-03T12:00:00Z",
            )
            external = {**original, "event_id": "external-event"}
            events_path = root / ".agent-system" / "local" / "request-events.jsonl"
            backup_path = events_path.with_name("request-events.original")
            external_path = base / "external-events.jsonl"
            events_path.write_text(json.dumps(original) + "\n", encoding="utf-8")
            external_path.write_text(json.dumps(external) + "\n", encoding="utf-8")
            original_is_file = Path.is_file

            def swap_after_file_check(path: Path) -> bool:
                result = original_is_file(path)
                if path == events_path and not backup_path.exists():
                    events_path.rename(backup_path)
                    events_path.symlink_to(external_path)
                return result

            with mock.patch.object(Path, "is_file", swap_after_file_check):
                loaded = request_events.load_events(root)

        self.assertEqual(["original-event"], [event["event_id"] for event in loaded])

    def test_generated_local_metadata_does_not_dirty_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
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
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, timeout=60)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "baseline"],
                check=True,
                timeout=60,
            )
            result = self.record(
                root,
                event_id="event-clean",
                timestamp="2026-10-03T12:00:00Z",
                review_every=1,
                minimum_count=1,
            )
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", status.stdout)

    def test_cli_rejects_non_normalized_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.project(Path(directory))
            result = self.record(
                root,
                route="write me a great report please",
                event_id="event-bad-route",
                timestamp="2026-10-03T12:00:00Z",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("route", result.stderr)
        self.assertFalse((root / ".agent-system" / "local" / "request-events.jsonl").exists())

    def test_runtime_validation_matches_event_schema_limits(self) -> None:
        request_events = load_module()
        base = {
            "schema_version": "0.1",
            "event_id": "validation-event",
            "timestamp": "2026-10-03T12:00:00Z",
            "kind": "technical_report",
            "topics": ["model_evaluation"],
            "deliverable": "pdf",
            "route": "technical-report",
            "run_ref": None,
            "outcome": "completed",
            "rework": False,
            "routing_corrected": False,
            "reason_tags": [],
        }
        invalid = {
            "fractional timestamp": (
                {**base, "timestamp": "2026-10-03T12:00:00.1Z"},
                "whole-second",
            ),
            "too many topics": (
                {**base, "topics": sorted(f"topic_{index}" for index in range(13))},
                "at most 12",
            ),
            "too many reason tags": (
                {**base, "reason_tags": sorted(f"reason_{index}" for index in range(9))},
                "at most 8",
            ),
            "overlong kind slug": ({**base, "kind": "a" * 65}, "kind"),
            "overlong topic slug": ({**base, "topics": ["a" * 65]}, "topics"),
            "overlong deliverable slug": ({**base, "deliverable": "a" * 65}, "deliverable"),
            "overlong reason slug": ({**base, "reason_tags": ["a" * 65]}, "reason_tags"),
            "route whitespace": ({**base, "route": "technical report"}, "route"),
            "route equals": ({**base, "route": "route=technical-report"}, "route"),
            "route prompt text": ({**base, "route": "please/write/a/report"}, "route"),
            "route overlong": ({**base, "route": "a" * 121}, "route"),
        }

        for label, (event, expected) in invalid.items():
            with self.subTest(label=label):
                self.assertTrue(
                    any(expected in error for error in request_events.event_errors(event)),
                    label,
                )
        for route in ("technical-report", "execute-dsml-task/diagnose"):
            with self.subTest(route=route):
                self.assertEqual([], request_events.event_errors({**base, "route": route}))

    def test_validator_rejects_forbidden_sensitive_fields(self) -> None:
        request_events = load_module()
        event = {
            "schema_version": "0.1",
            "event_id": "unsafe-event",
            "timestamp": "2026-10-03T12:00:00Z",
            "kind": "technical_report",
            "topics": [],
            "deliverable": None,
            "route": "technical-report",
            "run_ref": None,
            "outcome": "completed",
            "rework": False,
            "routing_corrected": False,
            "reason_tags": [],
            "chain_of_thought": "must never be stored",
        }
        errors = request_events.event_errors(event)
        self.assertTrue(any("forbidden" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
