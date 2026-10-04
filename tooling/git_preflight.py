#!/usr/bin/env python3
"""Inspect optional Git state and perform only explicitly requested safe synchronization."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


GIT_MODES = ("disabled", "auto-detect", "required")
SYNC_MODES = ("no-sync", "fetch-check", "fast-forward-only")
def _run_git(
    root: Path,
    *args: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _output(root: Path, *args: str) -> str | None:
    result = _run_git(root, *args)
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _empty_state(root: Path, git_mode: str, sync_mode: str) -> dict[str, Any]:
    return {
        "git_mode": git_mode,
        "sync_mode": sync_mode,
        "git_required": git_mode == "required",
        "git_available": shutil.which("git") is not None,
        "status": "disabled" if git_mode == "disabled" else "not_repository",
        "requested_root": str(root),
        "repo_root": None,
        "branch": None,
        "detached": False,
        "head": None,
        "upstream": None,
        "clean": None,
        "worktree": "unavailable",
        "ahead": None,
        "behind": None,
        "relation": "unavailable",
        "remote_available": False,
        "remotes": [],
        "sync_result": "not_requested",
        "auth_diagnostics": None,
        "issues": [],
    }


def _relation(ahead: int | None, behind: int | None, upstream: str | None) -> str:
    if upstream is None:
        return "no_upstream"
    if ahead is None or behind is None:
        return "unknown"
    if ahead == 0 and behind == 0:
        return "current"
    if ahead == 0:
        return "behind"
    if behind == 0:
        return "ahead"
    return "diverged"


def _inspect_repository(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    top_level = _output(root, "rev-parse", "--show-toplevel")
    if top_level is None:
        if state["git_required"]:
            state["issues"].append(
                "workflow requires Git, but the project root is not inside a Git repository"
            )
        return state

    repo_root = Path(top_level).resolve()
    state["status"] = "repository"
    state["repo_root"] = str(repo_root)
    state["head"] = _output(repo_root, "rev-parse", "--verify", "HEAD")
    if state["git_required"] and state["head"] is None:
        issue = "workflow requires Git with an existing HEAD revision; the repository is unborn"
        if issue not in state["issues"]:
            state["issues"].append(issue)
    state["branch"] = _output(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    state["detached"] = state["head"] is not None and state["branch"] is None
    porcelain = _run_git(repo_root, "status", "--porcelain", "--untracked-files=normal")
    if porcelain.returncode == 0:
        state["clean"] = not bool(porcelain.stdout)
        state["worktree"] = "clean" if state["clean"] else "dirty"
    state["remotes"] = sorted(
        line for line in (_output(repo_root, "remote") or "").splitlines() if line
    )
    state["remote_available"] = bool(state["remotes"])
    state["upstream"] = _output(
        repo_root,
        "for-each-ref",
        "--format=%(upstream:short)",
        f"refs/heads/{state['branch']}",
    ) if state["branch"] else None
    if state["upstream"]:
        counts = _output(repo_root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if counts:
            pieces = counts.split()
            if len(pieces) == 2 and all(piece.isdigit() for piece in pieces):
                state["ahead"], state["behind"] = (int(piece) for piece in pieces)
    state["relation"] = _relation(state["ahead"], state["behind"], state["upstream"])
    return state


def _upstream_refs(repo_root: Path, branch: str | None) -> tuple[str, str, str] | None:
    """Return (remote name, remote branch ref, local tracking ref) for the current upstream."""
    if branch is None:
        return None
    details = _output(
        repo_root,
        "for-each-ref",
        "--format=%(upstream:remotename)\t%(upstream:remoteref)\t%(upstream)",
        f"refs/heads/{branch}",
    )
    if not details:
        return None
    pieces = details.split("\t")
    if len(pieces) != 3 or not all(pieces):
        return None
    return (pieces[0], pieces[1], pieces[2])


def _repository_snapshot(repo_root: Path) -> dict[str, Any]:
    snapshot = _empty_state(repo_root, "auto-detect", "no-sync")
    return _inspect_repository(repo_root, snapshot)


def _ssh_agent_fingerprints() -> list[dict[str, Any]]:
    """Return public identity fingerprints without exposing key paths or comments."""
    if shutil.which("ssh-add") is None:
        return []
    result = subprocess.run(
        ["ssh-add", "-l"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    identities: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        pieces = line.split()
        if len(pieces) < 2 or not pieces[0].isdigit():
            continue
        key_type = pieces[-1].strip("()") if pieces[-1].startswith("(") else "unknown"
        identities.append(
            {
                "bits": int(pieces[0]),
                "fingerprint": pieces[1],
                "key_type": key_type,
            }
        )
    return identities


def _authentication_failure(detail: str) -> bool:
    normalized = detail.lower()
    return any(
        marker in normalized
        for marker in (
            "authentication failed",
            "could not read username",
            "permission denied (publickey)",
            "permission denied, please try again",
            "terminal prompts disabled",
        )
    )


def _sanitize_git_text(value: str | None) -> str | None:
    """Redact URL userinfo while preserving enough remote context to diagnose failures."""
    if value is None:
        return None
    return re.sub(
        r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/'\"]+@",
        r"\1***@",
        value,
    )


def _auth_diagnostics(repo_root: Path, remote: str, detail: str) -> dict[str, Any]:
    remote_url = _output(repo_root, "remote", "get-url", remote)
    authentication_failure = _authentication_failure(detail)
    ssh_remote = bool(
        remote_url
        and (remote_url.startswith("ssh://") or (":" in remote_url and "://" not in remote_url))
    )
    identities = _ssh_agent_fingerprints() if authentication_failure and ssh_remote else []
    if not authentication_failure:
        resolution = "not_applicable"
        action = None
    elif not ssh_remote:
        resolution = "credential_configuration_required"
        action = "Verify the configured remote credentials, then retry the fetch."
    elif len(identities) == 1:
        resolution = "normal_ssh_resolution"
        action = "Normal SSH identity resolution was used; verify that the configured remote accepts this fingerprint."
    elif len(identities) > 1:
        resolution = "ambiguous_ssh_identities"
        action = "Use normal SSH configuration first; select an identity only if the retry remains ambiguous."
    else:
        resolution = "no_ssh_agent_identity"
        action = "Load or configure the intended SSH identity, then retry the fetch."
    return {
        "authentication_failure": authentication_failure,
        "remote": remote,
        "remote_url": _sanitize_git_text(remote_url),
        "ssh_agent_identities": identities,
        "identity_resolution": resolution,
        "action": action,
    }


def _fetch(state: dict[str, Any]) -> None:
    repo_root = Path(state["repo_root"])
    refs = _upstream_refs(repo_root, state["branch"])
    if not refs:
        state["sync_result"] = "skipped_no_upstream"
        state["issues"].append("cannot fetch because the current branch has no upstream remote")
        return
    remote, remote_ref, tracking_ref = refs
    result = _run_git(
        repo_root,
        "fetch",
        "--prune",
        remote,
        f"{remote_ref}:{tracking_ref}",
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        safe_detail = _sanitize_git_text(detail)
        state["sync_result"] = "fetch_failed"
        state["issues"].append(
            f"Git fetch failed for remote {remote}: {safe_detail or 'unknown error'}"
        )
        state["auth_diagnostics"] = _auth_diagnostics(repo_root, remote, detail)
        action = state["auth_diagnostics"].get("action")
        if state["auth_diagnostics"]["authentication_failure"] and action:
            state["issues"].append(action)
        return
    state["sync_result"] = "fetched"
    _inspect_repository(repo_root, state)


def _fast_forward(state: dict[str, Any]) -> None:
    if state["sync_result"] == "fetch_failed":
        return
    if state["upstream"] is None:
        state["sync_result"] = "skipped_no_upstream"
        return
    if state["relation"] == "current":
        state["sync_result"] = "already_current"
        return
    if state["relation"] == "ahead":
        state["sync_result"] = "skipped_ahead"
        return
    if state["relation"] == "diverged":
        state["sync_result"] = "blocked_diverged"
        state["issues"].append(
            "local and upstream branches have diverged; choose merge, rebase, or another resolution explicitly"
        )
        return
    if state["relation"] != "behind":
        state["sync_result"] = "blocked_unknown_state"
        state["issues"].append("cannot prove that a fast-forward-only update is safe")
        return
    if state["clean"] is not True:
        state["sync_result"] = "blocked_dirty"
        state["issues"].append(
            "worktree is dirty; no stash, reset, clean, or update was performed"
        )
        return
    repo_root = Path(state["repo_root"])
    expected = {
        "branch": state["branch"],
        "head": state["head"],
        "upstream": state["upstream"],
        "relation": state["relation"],
        "clean": state["clean"],
    }
    snapshot = _repository_snapshot(repo_root)
    current = {key: snapshot.get(key) for key in expected}
    if snapshot["status"] != "repository" or current != expected:
        state["sync_result"] = "blocked_state_changed"
        state["issues"].append(
            "repository state changed after inspection; no merge, reset, stash, or rebase was performed"
        )
        return
    target_commit = _output(repo_root, "rev-parse", "--verify", state["upstream"])
    if target_commit is None:
        state["sync_result"] = "blocked_unknown_state"
        state["issues"].append("cannot resolve the upstream commit before fast-forward; nothing was merged")
        return
    result = _run_git(repo_root, "merge", "--ff-only", target_commit, timeout=120)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        state["sync_result"] = "fast_forward_failed"
        state["issues"].append(
            f"fast-forward-only update failed: {_sanitize_git_text(detail) or 'unknown error'}"
        )
        return
    state["sync_result"] = "fast_forwarded"
    _inspect_repository(repo_root, state)


def preflight(
    project_root: Path,
    *,
    git_mode: str = "auto-detect",
    sync_mode: str = "no-sync",
) -> dict[str, Any]:
    """Return normalized Git state; mutate only for an explicit synchronization mode."""
    if git_mode not in GIT_MODES:
        raise ValueError(f"unsupported Git mode: {git_mode}")
    if sync_mode not in SYNC_MODES:
        raise ValueError(f"unsupported Git sync mode: {sync_mode}")
    root = project_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"project root is not a directory: {root}")
    state = _empty_state(root, git_mode, sync_mode)
    if git_mode == "disabled":
        return state
    if not state["git_available"]:
        state["status"] = "git_unavailable"
        if state["git_required"]:
            state["issues"].append("workflow requires Git, but the git executable is unavailable")
        return state
    _inspect_repository(root, state)
    if state["status"] != "repository" or sync_mode == "no-sync":
        return state
    _fetch(state)
    if sync_mode == "fast-forward-only":
        _fast_forward(state)
    return state


def git_requirement_errors(state: dict[str, Any], project_root: Path) -> list[str]:
    """Return workflow-local Git blockers, including canonical-root mismatch."""
    errors = list(state.get("issues", []))
    repo_root = state.get("repo_root")
    if state.get("status") == "repository" and repo_root != str(project_root.resolve()):
        errors.append(
            f"workflow requires --project-root to identify the canonical Git repository root ({repo_root})"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--git-mode", choices=GIT_MODES, default="auto-detect")
    parser.add_argument("--sync-mode", choices=SYNC_MODES, default="no-sync")
    args = parser.parse_args()
    try:
        state = preflight(
            args.project_root,
            git_mode=args.git_mode,
            sync_mode=args.sync_mode,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "error", "issues": [str(exc)]}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(state, indent=2, sort_keys=True))
    if state["git_required"] and state["issues"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
