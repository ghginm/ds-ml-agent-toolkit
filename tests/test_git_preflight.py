from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tooling" / "git_preflight.py"
CLI_PATH = MODULE_PATH


def load_module():
    spec = importlib.util.spec_from_file_location("git_preflight", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitPreflightTests(unittest.TestCase):
    def git(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=60,
        )

    def init_repository(self, root: Path) -> None:
        root.mkdir()
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "synthetic@example.invalid")
        self.git(root, "config", "user.name", "Synthetic Test")
        (root / "model.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(root, "add", "model.py")
        self.git(root, "commit", "-qm", "baseline")

    def init_remote_pair(self, base: Path) -> tuple[Path, Path, Path]:
        remote = base / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True, timeout=60)
        project = base / "project"
        self.init_repository(project)
        self.git(project, "branch", "-M", "main")
        self.git(project, "remote", "add", "origin", str(remote))
        self.git(project, "push", "-qu", "origin", "main")
        self.git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        peer = base / "peer"
        subprocess.run(["git", "clone", "-q", str(remote), str(peer)], check=True, timeout=60)
        self.git(peer, "config", "user.email", "peer@example.invalid")
        self.git(peer, "config", "user.name", "Synthetic Peer")
        return project, peer, remote

    def test_non_git_project_is_optional_but_required_mode_reports_blocker(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            optional = git_preflight.preflight(root, git_mode="auto-detect")
            required = git_preflight.preflight(root, git_mode="required")

        self.assertEqual("not_repository", optional["status"])
        self.assertFalse(optional["git_required"])
        self.assertEqual([], optional["issues"])
        self.assertEqual("not_repository", required["status"])
        self.assertTrue(required["git_required"])
        self.assertIn("workflow requires Git", required["issues"][0])

    def test_unborn_repository_fails_required_git_mode(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            self.git(root, "init", "-q")

            state = git_preflight.preflight(root, git_mode="required")
            errors = git_preflight.git_requirement_errors(state, root)

        self.assertEqual("repository", state["status"])
        self.assertIsNone(state["head"])
        self.assertTrue(any("HEAD revision" in issue for issue in state["issues"]))
        self.assertTrue(any("HEAD revision" in error for error in errors))

    def test_clean_repository_reports_branch_head_cleanliness_and_remote_state(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.init_repository(root)
            state = git_preflight.preflight(root)

        self.assertEqual("repository", state["status"])
        self.assertEqual(str(root.resolve()), state["repo_root"])
        self.assertTrue(state["branch"])
        self.assertRegex(state["head"], r"^[0-9a-f]{40}$")
        self.assertTrue(state["clean"])
        self.assertFalse(state["remote_available"])
        self.assertEqual("no_upstream", state["relation"])

    def test_dirty_repository_is_detected_without_modifying_user_work(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.init_repository(root)
            changed = root / "model.py"
            changed.write_text("VALUE = 2\n", encoding="utf-8")
            before = changed.read_bytes()
            state = git_preflight.preflight(root)
            after = changed.read_bytes()

        self.assertFalse(state["clean"])
        self.assertEqual(before, after)
        self.assertEqual("dirty", state["worktree"])

    def test_fetch_check_reports_clean_up_to_date_repository(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            project, _, _ = self.init_remote_pair(Path(directory))

            state = git_preflight.preflight(project, sync_mode="fetch-check")

        self.assertTrue(state["clean"])
        self.assertEqual("current", state["relation"])
        self.assertEqual("fetched", state["sync_result"])

    def test_fetch_check_detects_behind_and_fast_forward_only_updates_clean_branch(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            project, peer, _ = self.init_remote_pair(Path(directory))
            (peer / "peer.txt").write_text("remote change\n", encoding="utf-8")
            self.git(peer, "add", "peer.txt")
            self.git(peer, "commit", "-qm", "remote change")
            self.git(peer, "push", "-q", "origin", "main")

            before = self.git(project, "rev-parse", "HEAD").stdout.strip()
            checked = git_preflight.preflight(project, sync_mode="fetch-check")
            updated = git_preflight.preflight(project, sync_mode="fast-forward-only")
            after = self.git(project, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual("behind", checked["relation"])
        self.assertEqual(0, checked["ahead"])
        self.assertEqual(1, checked["behind"])
        self.assertEqual("fetched", checked["sync_result"])
        self.assertNotEqual(before, after)
        self.assertEqual("fast_forwarded", updated["sync_result"])
        self.assertEqual("current", updated["relation"])

    def test_diverged_branch_is_reported_and_never_merged_or_rebased(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            project, peer, _ = self.init_remote_pair(Path(directory))
            (peer / "remote.txt").write_text("remote\n", encoding="utf-8")
            self.git(peer, "add", "remote.txt")
            self.git(peer, "commit", "-qm", "remote")
            self.git(peer, "push", "-q", "origin", "main")
            (project / "local.txt").write_text("local\n", encoding="utf-8")
            self.git(project, "add", "local.txt")
            self.git(project, "commit", "-qm", "local")
            before = self.git(project, "rev-parse", "HEAD").stdout.strip()

            state = git_preflight.preflight(project, sync_mode="fast-forward-only")
            after = self.git(project, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual("diverged", state["relation"])
        self.assertEqual("blocked_diverged", state["sync_result"])
        self.assertEqual(before, after)
        self.assertTrue(any("diverged" in issue for issue in state["issues"]))

    def test_dirty_behind_branch_is_not_fast_forwarded(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            project, peer, _ = self.init_remote_pair(Path(directory))
            (peer / "remote.txt").write_text("remote\n", encoding="utf-8")
            self.git(peer, "add", "remote.txt")
            self.git(peer, "commit", "-qm", "remote")
            self.git(peer, "push", "-q", "origin", "main")
            (project / "model.py").write_text("dirty user work\n", encoding="utf-8")
            before = self.git(project, "rev-parse", "HEAD").stdout.strip()

            state = git_preflight.preflight(project, sync_mode="fast-forward-only")
            after = self.git(project, "rev-parse", "HEAD").stdout.strip()
            user_work = (project / "model.py").read_text(encoding="utf-8")

        self.assertEqual("blocked_dirty", state["sync_result"])
        self.assertEqual(before, after)
        self.assertEqual("dirty user work\n", user_work)

    def test_fetch_prunes_only_the_current_upstream_ref(self) -> None:
        git_preflight = load_module()
        with tempfile.TemporaryDirectory() as directory:
            project, peer, remote = self.init_remote_pair(Path(directory))
            self.git(project, "push", "-q", "origin", "HEAD:refs/heads/other")
            self.git(
                project, "fetch", "-q", "origin",
                "refs/heads/other:refs/remotes/origin/other",
            )
            self.git(remote, "update-ref", "-d", "refs/heads/other")
            (peer / "remote.txt").write_text("remote\n", encoding="utf-8")
            self.git(peer, "add", "remote.txt")
            self.git(peer, "commit", "-qm", "remote change")
            self.git(peer, "push", "-q", "origin", "main")

            state = git_preflight.preflight(project, sync_mode="fetch-check")
            tracking_refs = self.git(
                project, "for-each-ref", "--format=%(refname)", "refs/remotes/origin"
            ).stdout

        self.assertEqual("fetched", state["sync_result"])
        self.assertIn("refs/remotes/origin/other", tracking_refs)

    def test_state_change_between_fetch_and_fast_forward_blocks_merge(self) -> None:
        git_preflight = load_module()
        original_fetch = git_preflight._fetch
        with tempfile.TemporaryDirectory() as directory:
            project, peer, _ = self.init_remote_pair(Path(directory))
            (peer / "remote.txt").write_text("remote\n", encoding="utf-8")
            self.git(peer, "add", "remote.txt")
            self.git(peer, "commit", "-qm", "remote change")
            self.git(peer, "push", "-q", "origin", "main")
            before = self.git(project, "rev-parse", "HEAD").stdout.strip()

            def fetch_then_change(state: dict) -> None:
                original_fetch(state)
                (project / "racing.txt").write_text("changed after inspection\n", encoding="utf-8")

            with mock.patch.object(git_preflight, "_fetch", fetch_then_change):
                state = git_preflight.preflight(project, sync_mode="fast-forward-only")
            after = self.git(project, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual("blocked_state_changed", state["sync_result"])
        self.assertEqual(before, after)
        self.assertTrue(any("no merge, reset, stash, or rebase" in issue for issue in state["issues"]))

    def test_auth_failure_reports_remote_and_sanitized_agent_fingerprints(self) -> None:
        git_preflight = load_module()
        original_run_git = git_preflight._run_git
        with tempfile.TemporaryDirectory() as directory:
            project, _, _ = self.init_remote_pair(Path(directory))
            self.git(project, "remote", "set-url", "origin", "git@example.invalid:team/project.git")

            def fail_fetch(root: Path, *args: str, timeout: int = 30):
                if args and args[0] == "fetch":
                    return subprocess.CompletedProcess(
                        ["git", "fetch"],
                        128,
                        stdout="",
                        stderr="git@example.invalid: Permission denied (publickey).\n",
                    )
                return original_run_git(root, *args, timeout=timeout)

            with mock.patch.object(git_preflight, "_run_git", side_effect=fail_fetch), mock.patch.object(
                git_preflight,
                "_ssh_agent_fingerprints",
                return_value=[
                    {"bits": 256, "fingerprint": "SHA256:synthetic", "key_type": "ED25519"}
                ],
            ):
                state = git_preflight.preflight(project, sync_mode="fetch-check")

        self.assertEqual("fetch_failed", state["sync_result"])
        diagnostics = state["auth_diagnostics"]
        self.assertTrue(diagnostics["authentication_failure"])
        self.assertEqual("origin", diagnostics["remote"])
        self.assertEqual("git@example.invalid:team/project.git", diagnostics["remote_url"])
        self.assertEqual("normal_ssh_resolution", diagnostics["identity_resolution"])
        self.assertEqual("SHA256:synthetic", diagnostics["ssh_agent_identities"][0]["fingerprint"])
        self.assertNotIn("private", json.dumps(diagnostics).lower())

    def test_auth_failure_redacts_https_credentials_from_all_output(self) -> None:
        git_preflight = load_module()
        original_run_git = git_preflight._run_git
        secret_url = "https://synthetic-user:synthetic-token@example.invalid/team/project.git"
        with tempfile.TemporaryDirectory() as directory:
            project, _, _ = self.init_remote_pair(Path(directory))
            self.git(project, "remote", "set-url", "origin", secret_url)

            def fail_fetch(root: Path, *args: str, timeout: int = 30):
                if args and args[0] == "fetch":
                    return subprocess.CompletedProcess(
                        ["git", "fetch"],
                        128,
                        stdout="",
                        stderr=f"fatal: Authentication failed for '{secret_url}'\n",
                    )
                return original_run_git(root, *args, timeout=timeout)

            with mock.patch.object(git_preflight, "_run_git", side_effect=fail_fetch):
                state = git_preflight.preflight(project, sync_mode="fetch-check")

        serialized = json.dumps(state)
        self.assertNotIn("synthetic-user", serialized)
        self.assertNotIn("synthetic-token", serialized)
        self.assertIn("https://***@example.invalid/team/project.git", serialized)

    def test_cli_continues_when_auto_detect_has_no_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            self.init_repository(root)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CLI_PATH),
                    "--project-root",
                    str(root),
                    "--sync-mode",
                    "fetch-check",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(0, result.returncode)
        state = json.loads(result.stdout)
        self.assertEqual("skipped_no_upstream", state["sync_result"])

    def test_cli_continues_for_non_git_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CLI_PATH),
                    "--project-root",
                    directory,
                    "--sync-mode",
                    "fetch-check",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(0, result.returncode)
        state = json.loads(result.stdout)
        self.assertEqual("not_repository", state["status"])

    def test_main_keeps_best_effort_sync_warnings_nonblocking(self) -> None:
        git_preflight = load_module()
        for sync_result in (
            "skipped_no_upstream",
            "fetch_failed",
            "blocked_dirty",
            "blocked_diverged",
        ):
            state = git_preflight._empty_state(Path("."), "auto-detect", "fetch-check")
            state["status"] = "repository"
            state["sync_result"] = sync_result
            state["issues"] = ["synthetic warning"]
            with self.subTest(sync_result=sync_result), mock.patch.object(
                git_preflight, "preflight", return_value=state
            ), mock.patch.object(sys, "argv", [str(CLI_PATH), "--project-root", "."]):
                output = StringIO()
                with redirect_stdout(output):
                    returncode = git_preflight.main()
            self.assertEqual(0, returncode, output.getvalue())

    def test_cli_returns_nonzero_when_required_git_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CLI_PATH),
                    "--project-root",
                    directory,
                    "--git-mode",
                    "required",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(2, result.returncode)
        state = json.loads(result.stdout)
        self.assertEqual("not_repository", state["status"])
        self.assertTrue(state["issues"])


if __name__ == "__main__":
    unittest.main()
