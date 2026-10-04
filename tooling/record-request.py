#!/usr/bin/env python3
"""Append one sanitized local request event and review only when thresholds are due."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import request_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--deliverable")
    parser.add_argument("--route", required=True)
    parser.add_argument("--run-ref")
    parser.add_argument(
        "--outcome",
        choices=("completed", "partial", "blocked", "failed", "unknown"),
        default="unknown",
    )
    parser.add_argument("--rework", action="store_true")
    parser.add_argument("--routing-corrected", action="store_true")
    parser.add_argument("--reason-tag", action="append", default=[])
    parser.add_argument("--event-id")
    parser.add_argument("--timestamp")
    parser.add_argument("--review-every", type=int, default=10)
    parser.add_argument("--max-review-age-days", type=int, default=30)
    parser.add_argument("--minimum-count", type=int, default=3)
    args = parser.parse_args()
    try:
        event = request_events.normalize_event(
            kind=args.kind,
            topics=args.topic,
            deliverable=args.deliverable,
            route=args.route,
            run_ref=args.run_ref,
            outcome=args.outcome,
            rework=args.rework,
            routing_corrected=args.routing_corrected,
            reason_tags=args.reason_tag,
            event_id=args.event_id,
            timestamp=args.timestamp,
        )
        path = request_events.append_event(args.project_root, event)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Recorded {path.relative_to(args.project_root.resolve())}")
    try:
        reviewed = request_events.maybe_review(
            args.project_root,
            review_every=args.review_every,
            max_age_days=args.max_review_age_days,
            minimum_count=args.minimum_count,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"WARNING: request event was recorded but review was skipped: {exc}", file=sys.stderr)
        return 0
    if reviewed is not None:
        print(f"Reviewed {reviewed.relative_to(args.project_root.resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
