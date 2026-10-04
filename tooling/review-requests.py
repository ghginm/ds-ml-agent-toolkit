#!/usr/bin/env python3
"""Deterministically aggregate sanitized request events into compact local patterns."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import request_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--minimum-count", type=int, default=3)
    parser.add_argument("--review-every", type=int, default=10)
    parser.add_argument("--max-review-age-days", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        root, _, patterns_path = request_events.local_paths(args.project_root)
        if args.force:
            reviewed = request_events.write_patterns(root, minimum_count=args.minimum_count)
        else:
            reviewed = request_events.maybe_review(
                root,
                review_every=args.review_every,
                max_age_days=args.max_review_age_days,
                minimum_count=args.minimum_count,
            )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    if reviewed is None:
        print("Request review is not due")
    else:
        print(f"Reviewed {patterns_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
