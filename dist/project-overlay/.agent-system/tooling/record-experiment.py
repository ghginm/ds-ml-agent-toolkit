#!/usr/bin/env python3
"""Append one content-addressed autoresearch experiment journal entry, reserve
protected-evaluation exposure, or execute a protected evaluation behind that
reservation.

Three mutually exclusive operations:

* ``--row-json`` appends one novel or duplicate experiment to the journal.
  A stage-``final`` evaluated result is accepted only when this run already
  has a committed exposure event for its stable protected-split identity AND
  the row mechanically re-evaluates the previously promoted frozen candidate
  (identical ``candidate_identity`` and unchanged immutable provenance), so the
  ledger must be burned BEFORE the protected population is evaluated and
  observed, never after. Repeating a candidate in the same evaluation context
  remains a duplicate; the protected role change is the only legitimate reuse.
* ``--reserve-final-exposure`` appends the exposure event to
  ``.agent-system/evaluation-ledger.jsonl`` without touching the journal.
  It is idempotent: retrying the same reservation never duplicates the event,
  and the reservation establishes exposure at its append-only commit position.
  The full read/check/append transaction runs under an exclusive ledger lock
  and the event is fsynced before the command reports success, so concurrent
  reservations never overwrite each other's events and no acknowledged
  exposure can be silently lost.
* ``--run-protected-evaluation --row-json HANDOFF -- COMMAND...`` preflights
  the protected lifecycle, commits the reservation durably, and only then
  executes the opaque command, which must write its experiment row to the path
  exported as ``$DSML_PROTECTED_ROW_JSON``; the row is recorded through the
  same stage-final invariants.

A run whose ``lifecycle.evidence_status`` is ``finalized`` is immutable to
all three operations: final evidence can be validated and read, never mutated
by normal toolkit commands.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

try:  # POSIX: whole-file advisory locks serialize the ledger transaction.
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt inside the lock helper.
    fcntl = None  # type: ignore[assignment]

SCRIPT_PATH = Path(__file__).resolve()
VALIDATOR_PATH = SCRIPT_PATH.parent / "validate-kit.py"
SPEC = importlib.util.spec_from_file_location("dsml_validate_kit", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load validator: {VALIDATOR_PATH}")
validate_kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_kit)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


LEDGER_LOCKFILE = "evaluation-ledger.lock"


@contextlib.contextmanager
def _ledger_transaction(root: Path) -> Any:
    """Hold the exclusive ledger lock across the whole read/check/append transaction.

    Atomic file replacement prevents torn files, not stale-state races: a
    reservation that reads the ledger outside this lock could decide
    "untouched, append" from state another writer has already superseded, and
    the last rewrite would silently drop the other writer's committed event.
    Every decision that depends on ledger state — committed reservation,
    idempotent retry, cross-run exposure ordering — and the append that commits
    the event therefore happen while this lock is held, so concurrent
    reservations serialize and cannot lose ledger events.
    """
    lock_path = root / ".agent-system" / LEDGER_LOCKFILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows fallback
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows fallback
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]


def _fsync_directory(path: Path) -> None:
    """Flush a directory entry so a newly created ledger file is durable."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        directory_fd = os.open(str(path), flags)
    except OSError:  # pragma: no cover - platforms without directory fds
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _append_exposure_event(ledger_path: Path, event: dict[str, Any]) -> None:
    """Commit one exposure event append-only, durably, before any success is claimed.

    The ledger never gets rewritten here: events already committed by other
    transactions stay untouched, and this call returns only after the event
    bytes reach stable storage. A persistence error propagates so the
    reservation command fails instead of acknowledging an exposure the ledger
    does not contain.
    """
    newly_created = not ledger_path.exists()
    line = json.dumps(event, sort_keys=True) + "\n"
    with open(ledger_path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    if newly_created:
        _fsync_directory(ledger_path.parent)


def _load_summary(run_path: Path, root: Path) -> dict[str, Any] | None:
    if not run_path.is_file() or run_path.is_symlink():
        return None
    run = validate_kit.load_json(run_path, root)
    if not isinstance(run, dict):
        return None
    results = run.get("results")
    summary = results.get("experiment_summary") if isinstance(results, dict) else None
    if isinstance(summary, dict) and summary.get("format_version") == "0.2":
        return summary
    return None


def _reject_finalized(summary: dict[str, Any] | None, run_id: str) -> None:
    """Finalized evidence is terminal; normal commands must not reopen it."""
    if summary is None:
        return
    lifecycle = summary.get("lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("evidence_status") == "finalized":
        raise ValueError(
            f"run {run_id} evidence is finalized: finalized evidence is immutable to "
            "journal, counter, exposure, and selection mutation; reopen requires a "
            "separate explicit workflow, which this toolkit does not provide"
        )


def _final_split_contract(evaluation: dict[str, Any]) -> dict[str, Any]:
    contract = evaluation.get("evaluation")
    contract = contract if isinstance(contract, dict) else {}
    identity = contract.get("final_split_identity")
    return identity if isinstance(identity, dict) else {}


def _check_cross_run_exposure(
    root: Path, run_id: str, identity: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return this run+split's committed exposure event, or validate a new reservation.

    Reservation ordering is event order in the append-only ledger: this run's
    own committed reservation establishes its exposure status at commit time,
    so events appended by other runs AFTER it cannot retroactively invalidate
    this run's already-authorized one-shot evaluation. Before any own event
    exists, every other run's final exposure of the same split is a prior
    exposure, and an untouched claim over it is refused.
    """
    split_key = validate_kit._final_split_key(identity)
    if split_key is None:
        return []
    ledger_records, ledger_errors = validate_kit.load_evaluation_ledger(root)
    if ledger_errors:
        raise ValueError("; ".join(ledger_errors))
    exposure = validate_kit.final_exposure_event(run_id, identity)
    assert exposure is not None
    committed = [
        record for record in ledger_records if record.get("event_id") == exposure["event_id"]
    ]
    if committed:
        return committed
    prior_final = [
        record
        for record in ledger_records
        if record.get("role") == "final"
        and record.get("run_id") != run_id
        and validate_kit._final_split_key(record) == split_key
    ]
    if prior_final and identity.get("exposure_status") == "untouched":
        raise ValueError(
            "final split was previously exposed by "
            f"{prior_final[0].get('run_id')} and cannot be recorded as untouched reuse"
        )
    return []


def _load_ledger_records_locked(root: Path) -> list[dict[str, Any]]:
    """Load the current ledger records under the caller-held transaction lock.

    Distinct from a free-floating ``load_evaluation_ledger`` call: when the
    managed protected-evaluation wrapper holds the advisory lock, this read is
    guaranteed to see every committed event from earlier transactions because
    no concurrent reservation writer can interleave a stale-state overwrite.
    A loaded ledger that contains schema/parse errors fails closed so the
    wrapper never silently launches an evaluator on a corrupt exposure ledger.
    """
    records, errors = validate_kit.load_evaluation_ledger(root)
    if errors:
        raise ValueError("; ".join(errors))
    return records


def _execution_already_consumed(
    ledger_records: list[dict[str, Any]], run_id: str, identity: dict[str, Any]
) -> bool:
    """True iff the managed execution-consumed event for this run+split is already committed.

    The event ID is deterministic per (run, split), so a retried managed
    attempt finds its own prior commit. The consumed event is appended only
    by ``--run-protected-evaluation`` AFTER the reservation is durable and
    BEFORE the evaluator subprocess starts, so a True answer means a prior
    managed attempt has begun for this run and the evaluator must not be
    launched again regardless of how the prior attempt ended.
    """
    consumed = validate_kit.execution_consumed_event(run_id, identity)
    if consumed is None:
        return False
    return any(record.get("event_id") == consumed["event_id"] for record in ledger_records)


def reserve_final_exposure(root: Path, run_id: str) -> bool:
    """Commit protected-split exposure to the ledger before any result can exist.

    Must be invoked before executing or observing the protected final
    evaluation. A crash after this commit and before result recording still
    leaves the split burned, which is the scientifically honest state. The
    operation is idempotent per stable (run, split) event identity. The
    ledger is reread, checked for the committed/idempotent/prior-exposure
    states, and appended to exclusively while the ledger lock is held — the
    decision and the commit share one transaction, so a concurrent writer can
    never interleave a stale-state overwrite between them — and success is
    reported only after the event is fsynced to stable storage.
    """
    root = root.expanduser().resolve(strict=True)
    run_dir = root / ".agent-system" / "runs" / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError(f"run does not exist as a canonical directory: {run_id}")
    _reject_finalized(_load_summary(run_dir / "run.yaml", root), run_id)
    evaluation = validate_kit.load_json(run_dir / "evaluation.yaml", root)
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation.yaml must contain an object")
    identity = _final_split_contract(evaluation)
    if validate_kit._final_split_key(identity) is None:
        raise ValueError(
            "cannot reserve protected-evaluation exposure: final_split_identity has no "
            "stable split_hash and dataset_hash"
        )
    with _ledger_transaction(root):
        committed = _check_cross_run_exposure(root, run_id, identity)
        if committed:
            return False
        exposure = validate_kit.final_exposure_event(run_id, identity)
        assert exposure is not None
        _append_exposure_event(
            root / ".agent-system" / "evaluation-ledger.jsonl", exposure
        )
    return True


def _candidate_identity(row: dict[str, str]) -> str:
    material = {
        field: row.get(field, "").strip()
        for field in (
            "code_revision",
            "config_hash",
            "runner_hash",
            "input_manifest_hash",
        )
        if row.get(field, "").strip()
    }
    if not material:
        raise ValueError(
            "candidate_identity is missing and no immutable candidate fields are available"
        )
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _serialize(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=validate_kit.EXPERIMENT_JOURNAL_FIELDS,
        delimiter="\t",
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def record_experiment(
    root: Path, run_id: str, candidate: dict[str, Any]
) -> tuple[str | None, bool, bool]:
    """Append one journal entry after immutability, identity, budget, and exposure checks.

    Returns ``(duplicate_reason, plateau_recommended, budget_exhausted)``.
    Canonical accounting (shared with plateau stopping, run counters, and
    finalization validation): the baseline establishes the reference and does
    not consume the novel experiment budget; a valid novel candidate consumes
    one unit; duplicates never consume budget; crashed/invalid rows never
    consume budget; and the protected final evaluation of the already-counted
    promoted candidate never consumes budget again. Duplicate detection
    reasons over experimental identity — candidate identity plus evaluation
    context — so the legitimate lifecycle transition
    ``selection/promoted_to_holdout -> final/<outcome>`` for the SAME
    frozen candidate on the reserved protected population is not a duplicate,
    while repeating the candidate in the same context still is. Authorization
    of that reuse is decided purely by mechanics — reserved protected-final
    role, committed exposure, identical ``candidate_identity``, unchanged
    values for every immutable provenance field the promoted row declares, and
    one-shot rules — never by whether the final outcome is positive: a
    ``rejected`` protected evaluation of the promoted candidate keeps its real
    negative status instead of being rewritten to ``duplicate``. A
    stage-``final`` evaluation of a candidate that was never promoted is
    rejected outright, so the protected stage can never become a fresh
    adaptive search loop. A stage-``final`` evaluated result is rejected
    unless this run already committed its protected-split exposure
    reservation, and at most one evaluated stage-``final`` experiment may
    exist per run, so a protected population can never be queried repeatedly
    while still claiming one-shot final evidence. A finalized run rejects
    every mutation attempt.
    """
    root = root.expanduser().resolve(strict=True)
    run_dir = root / ".agent-system" / "runs" / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError(f"run does not exist as a canonical directory: {run_id}")
    journal_path = run_dir / "experiments.tsv"
    evaluation_path = run_dir / "evaluation.yaml"
    run_path = run_dir / "run.yaml"
    _reject_finalized(_load_summary(run_path, root), run_id)
    rows, read_errors = validate_kit.read_experiment_journal(journal_path, root)
    if read_errors:
        raise ValueError("; ".join(read_errors))
    evaluation = validate_kit.load_json(evaluation_path, root)
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation.yaml must contain an object")

    # The exposure ledger must already be burned whenever this submission
    # touches the protected stage at all: reserve-before-evaluate is the
    # enforced order. A stage-'final' submission requires the reservation even
    # when the row would be coerced to 'duplicate' or reports a crash, because
    # starting the protected pipeline can already have exposed the population.
    row_stage_final = str(candidate.get("stage") or "").strip() == "final"
    if row_stage_final:
        identity = _final_split_contract(evaluation)
        if validate_kit._final_split_key(identity) is not None:
            with _ledger_transaction(root):
                committed = _check_cross_run_exposure(root, run_id, identity)
            if not committed:
                raise ValueError(
                    "protected final evaluation has no committed exposure reservation; "
                    "run record-experiment.py --reserve-final-exposure for this run "
                    "BEFORE executing or observing the protected evaluation"
                )

    unknown = sorted(set(candidate) - set(validate_kit.EXPERIMENT_JOURNAL_FIELDS))
    if unknown:
        raise ValueError("unknown experiment fields: " + ", ".join(unknown))
    row = {
        field: "" if candidate.get(field) is None else str(candidate.get(field, ""))
        for field in validate_kit.EXPERIMENT_JOURNAL_FIELDS
    }
    if not row["experiment_id"].strip():
        raise ValueError("experiment_id is mandatory")
    if any(existing.get("experiment_id") == row["experiment_id"] for existing in rows):
        raise ValueError(f"experiment_id already exists: {row['experiment_id']}")
    if not row["candidate_identity"].strip():
        row["candidate_identity"] = _candidate_identity(row)
    duplicate = validate_kit.duplicate_reason(rows, row)
    if duplicate is not None:
        row["status"] = "duplicate"
        if not row["guardrail_status"]:
            row["guardrail_status"] = "not_applicable"
        note = f"duplicate {duplicate}"
        row["result_summary"] = (
            f"{row['result_summary']}; {note}" if row["result_summary"] else note
        )
        row["meaningful_improvement"] = "false"
        row["materially_new_evidence"] = "false"
    elif row["status"] not in validate_kit.EVALUATED_STATUSES | {"invalid", "crashed"}:
        raise ValueError(
            f"novel experiment status {row['status']!r} must be one of "
            + ", ".join(sorted(validate_kit.EVALUATED_STATUSES | {"invalid", "crashed"}))
        )

    # The stage-'final' role is reserved for the protected re-evaluation of the
    # promoted frozen candidate. A novel-identity final row is never a new
    # scientific candidate: without a mechanical identity tie to a promoted
    # row it is rejected, so stage relabeling cannot smuggle adaptive search
    # onto the protected population.
    if row_stage_final and duplicate is None:
        if validate_kit.promoted_frozen_anchor(rows, row) is None:
            raise ValueError(
                "protected final evaluation must re-evaluate the previously promoted "
                "frozen candidate: no earlier promoted_to_holdout experiment carries "
                "this candidate_identity with its immutable provenance unchanged"
            )

    summary = _load_summary(run_path, root)
    budget = summary.get("budget") if summary is not None else None
    budget = budget if isinstance(budget, int) and not isinstance(budget, bool) else None
    consumed = validate_kit.novel_experiment_count(rows)
    novel_valid = (
        duplicate is None
        and row["status"] in validate_kit.NOVEL_EXPERIMENT_STATUSES
        and not validate_kit.is_protected_final_evaluation(row)
    )
    if novel_valid and budget is not None and consumed >= budget:
        raise ValueError(
            f"experiment budget exhausted ({consumed} of {budget} novel experiments consumed); "
            "the hard ceiling rejects another budget-consuming novel candidate"
        )

    rows.append(row)
    errors = validate_kit.experiment_journal_errors(rows, evaluation, None)
    if errors:
        raise ValueError("; ".join(errors))
    _atomic_write(journal_path, _serialize(rows))

    budget_exhausted = (
        novel_valid and budget is not None and validate_kit.novel_experiment_count(rows) >= budget
    )
    if summary is not None:
        summary["experiments_run"] = validate_kit.novel_experiment_count(rows)
        events = summary.get("candidate_learning_events")
        events = events if isinstance(events, list) else []
        if duplicate is not None:
            event = (
                "duplicate_predictions"
                if duplicate == "prediction_hash"
                else "duplicate_config"
            )
            if event not in events:
                events.append(event)
        summary["candidate_learning_events"] = sorted(set(events))
        run = validate_kit.load_json(run_path, root)
        if isinstance(run, dict) and isinstance(run.get("results"), dict):
            run["results"]["experiment_summary"] = summary
            _atomic_write(run_path, json.dumps(run, indent=2) + "\n")
    return duplicate, validate_kit.plateau_stop_recommended(rows, evaluation), budget_exhausted


PROTECTED_ROW_HANDOFF_ENV = "DSML_PROTECTED_ROW_JSON"


def run_protected_evaluation(
    root: Path, run_id: str, row_path: Path, command: list[str]
) -> tuple[str | None, bool, bool]:
    """Execute an opaque protected evaluation mechanically gated behind its exposure commit.

    The managed boundary this closes: the evaluator command starts only after
    the protected-split exposure event AND the execution-consumed event are
    both durable in the ledger, so the workflow can no longer reveal a
    protected result before either commit exists. Two related transitions
    are kept distinct so a later retry can tell them apart:

        RESERVED                 -- the protected population may have been observed
        RESERVED+CONSUMED        -- this run's managed evaluator launch has begun

    Once ``CONSUMED`` is durable, no further managed launch for the same
    protected population is permitted for this run, even if the prior attempt
    crashed, exited non-zero, lost the result handoff, or never recorded a
    final row. The wrapper stays domain-agnostic — it knows only
    journal/ledger semantics and one opaque handoff: the command must write
    its final experiment row as JSON to the path exported in
    ``DSML_PROTECTED_ROW_JSON``. Preflight runs before any burn so a
    misconfigured invocation never wastes the protected population. The
    reservation ordering, promoted-candidate anchoring, one-shot, duplicate,
    budget, and immutability invariants are then enforced again inside
    ``record_experiment`` — the wrapper adds execution ordering, never
    relaxes evidence validation.
    """
    root = root.expanduser().resolve(strict=True)
    run_dir = root / ".agent-system" / "runs" / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError(f"run does not exist as a canonical directory: {run_id}")
    _reject_finalized(_load_summary(run_dir / "run.yaml", root), run_id)
    evaluation = validate_kit.load_json(run_dir / "evaluation.yaml", root)
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation.yaml must contain an object")
    identity = _final_split_contract(evaluation)
    if validate_kit._final_split_key(identity) is None:
        raise ValueError(
            "cannot execute protected evaluation: final_split_identity has no stable "
            "split_hash and dataset_hash"
        )
    rows, read_errors = validate_kit.read_experiment_journal(run_dir / "experiments.tsv", root)
    if read_errors:
        raise ValueError("; ".join(read_errors))
    if not any(
        row.get("status") == "promoted_to_holdout" and row.get("stage", "").strip() != "final"
        for row in rows
    ):
        raise ValueError(
            "no promoted frozen candidate exists yet; promote a candidate from the "
            "development/selection context before executing a protected final evaluation"
        )
    if any(
        row.get("stage") == "final" and row.get("status") in validate_kit.EVALUATED_STATUSES
        for row in rows
    ):
        raise ValueError(
            "the protected population is already consumed: this run has recorded its "
            "one-shot evaluated stage-final experiment"
        )
    row_path = row_path.expanduser().resolve()
    if not row_path.is_relative_to(root.resolve()):
        raise ValueError("protected evaluation handoff path must stay inside the project root")
    if row_path.exists():
        raise ValueError(
            f"protected evaluation handoff path already exists: {row_path}; refusing to "
            "mistake stale output for the protected result (checked before any exposure burn)"
        )

    # Atomic RESERVED+CONSUMED transition. The check that grants execution
    # permission and the durable commits that consume it share ONE lock hold,
    # so two concurrent invocations serialize on the ledger lock and the
    # second invocation deterministically sees the prior committed consumed
    # event. The reservation itself is committed inside the same transaction
    # when the run never reserved, so the workflow's only free-floating
    # preflight side effect is the journal/handoff/projected-candidate checks
    # above — no unprotected evaluation can run.
    ledger_path = root / ".agent-system" / "evaluation-ledger.jsonl"
    reserved_now = False
    with _ledger_transaction(root):
        committed_reservation = _check_cross_run_exposure(root, run_id, identity)
        if committed_reservation:
            reserved_now = False
        else:
            exposure = validate_kit.final_exposure_event(run_id, identity)
            assert exposure is not None
            _append_exposure_event(ledger_path, exposure)
            reserved_now = True
        ledger_records = _load_ledger_records_locked(root)
        if _execution_already_consumed(ledger_records, run_id, identity):
            raise ValueError(
                f"protected final evaluation execution attempt for run {run_id} is "
                f"already consumed: this run's managed evaluator launch has begun "
                f"before. The protected population was exposed by the earlier "
                f"managed attempt and no valid untouched final estimate remains "
                f"for this run; use a new untouched final population if another "
                f"genuinely untouched final estimate is required. The managed "
                f"evaluator will not be launched again."
            )
        consumed_event = validate_kit.execution_consumed_event(run_id, identity)
        assert consumed_event is not None
        _append_exposure_event(ledger_path, consumed_event)
    print(
        "RESERVED: protected final evaluation exposure committed"
        if reserved_now
        else "ALREADY_RESERVED: exposure event already committed; nothing duplicated",
        flush=True,
    )
    print(
        "EXECUTING: protected evaluation command runs only after the durable "
        "execution-consumed transition",
        flush=True,
    )
    completed = subprocess.run(
        command, env=os.environ | {PROTECTED_ROW_HANDOFF_ENV: str(row_path)}, cwd=str(root)
    )
    if completed.returncode != 0:
        raise ValueError(
            f"protected evaluation command exited with {completed.returncode}; the split "
            "stays exposed and no result was recorded"
        )
    if not row_path.is_file():
        raise ValueError(
            "protected evaluation command succeeded but wrote no result row to "
            f"${PROTECTED_ROW_HANDOFF_ENV}; the split stays exposed"
        )
    candidate = json.loads(row_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict):
        raise ValueError(
            "protected evaluation handoff must contain a single experiment row object"
        )
    if str(candidate.get("stage") or "").strip() != "final":
        raise ValueError(
            "protected evaluation handoff row must use stage='final' to be recorded "
            "as protected evidence"
        )
    return record_experiment(root, run_id, candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--row-json",
        type=Path,
        help=(
            "experiment row object to append, or — with --run-protected-evaluation — "
            "the handoff path where the protected command must write the final row"
        ),
    )
    parser.add_argument(
        "--reserve-final-exposure",
        action="store_true",
        help=(
            "commit this run's protected-split exposure event to the ledger and write "
            "no journal row; run this before executing or observing the protected "
            "final evaluation so an interrupted attempt still burns the split"
        ),
    )
    parser.add_argument(
        "--run-protected-evaluation",
        action="store_true",
        help=(
            "execute the opaque frozen evaluation command given after a '--' separator, "
            "but only after this run's protected exposure commit is durable; the command "
            "receives the required handoff path in $DSML_PROTECTED_ROW_JSON and its row "
            "is recorded through the same stage-final invariants"
        ),
    )
    argv = sys.argv[1:]
    command: list[str] = []
    if "--" in argv:
        separator = argv.index("--")
        argv, command = argv[:separator], argv[separator + 1 :]
    args = parser.parse_args(argv)
    if command and not args.run_protected_evaluation:
        parser.error("a '--' command is only accepted with --run-protected-evaluation")
    modes = [
        args.reserve_final_exposure,
        args.run_protected_evaluation,
        args.row_json is not None and not args.run_protected_evaluation,
    ]
    if sum(1 for mode in modes if mode) != 1:
        parser.error(
            "provide exactly one of --row-json, --reserve-final-exposure, "
            "or --run-protected-evaluation (with --row-json as the handoff path and "
            "the evaluation command after '--')"
        )
    if args.run_protected_evaluation and (args.row_json is None or not command):
        parser.error(
            "--run-protected-evaluation requires --row-json as the handoff path and "
            "the evaluation command after '--'"
        )
    protected = args.run_protected_evaluation
    try:
        if args.reserve_final_exposure:
            created = reserve_final_exposure(args.project_root, args.run_id)
            if created:
                print(
                    "RESERVED: protected final evaluation exposure committed; the split is "
                    "now burned even if this run never records a result"
                )
            else:
                print(
                    "ALREADY_RESERVED: exposure event already committed; nothing duplicated"
                )
            return 0
        row_json = args.row_json
        if row_json is None:
            raise ValueError("--row-json is required for this operation")
        if protected:
            candidate = {"stage": "final"}
            duplicate, plateau, budget_exhausted = run_protected_evaluation(
                args.project_root, args.run_id, row_json, command
            )
        else:
            candidate = json.loads(row_json.read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                raise ValueError("--row-json must contain an object")
            duplicate, plateau, budget_exhausted = record_experiment(
                args.project_root, args.run_id, candidate
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}")
        return 1
    if duplicate is not None:
        print(f"RECORDED: duplicate experiment ({duplicate}); valid experiment budget unchanged")
    elif str(candidate.get("stage") or "").strip() == "final":
        print(
            "RECORDED: protected final evaluation of the promoted frozen candidate; "
            "novel experiment budget unchanged"
        )
    else:
        print("RECORDED: novel experiment")
    if budget_exhausted:
        print("BUDGET_EXHAUSTED: hard experiment ceiling reached; no further novel candidates accepted")
    if plateau:
        print("STOP_RECOMMENDED: conservative plateau window reached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
