from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE_RUN = ROOT / "tooling" / "create-run.py"


class CreateRunStorageTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )

    def _repository(self, base: Path, name: str = "project") -> Path:
        root = base / name
        root.mkdir()
        self._git(root, "init", "-q")
        self._git(root, "config", "user.email", "synthetic@example.invalid")
        self._git(root, "config", "user.name", "Synthetic Test")
        (root / ".agent-system").mkdir()
        (root / "model.py").write_text("VALUE = 'baseline'\n", encoding="utf-8")
        (root / ".agent-system" / "project.yaml").write_text("{}\n", encoding="utf-8")
        self._git(root, "add", ".")
        self._git(root, "commit", "-qm", "synthetic baseline")
        return root

    def _create(self, project_root: Path, cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(CREATE_RUN),
                "--project-root",
                str(project_root),
                "--autoresearch",
                "--id",
                run_id,
                "--goal",
                "Improve the synthetic metric.",
                "--acceptance",
                "Canonical evidence survives worktree cleanup.",
                "--request-kind",
                "optimization",
                "--skill",
                "autoresearch",
                "--mode",
                "autoresearch",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _assert_authoritative_evidence(self, project_root: Path, run_id: str) -> Path:
        run_dir = project_root / ".agent-system" / "runs" / run_id
        self.assertTrue((run_dir / "run.yaml").is_file())
        self.assertTrue((run_dir / "learning.yaml").is_file())
        self.assertTrue((run_dir / "experiments.tsv").is_file())
        self.assertTrue((run_dir / "evaluation.yaml").is_file())
        learning = json.loads((run_dir / "learning.yaml").read_text(encoding="utf-8"))
        self.assertEqual(f".agent-system/runs/{run_id}/run.yaml", learning["run_ref"])
        self.assertEqual("0.4", learning["schema_version"])
        self.assertIn("no_reusable_signal_reason", learning)
        journal_header = (run_dir / "experiments.tsv").read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("experiment_id", journal_header)
        self.assertIn("config_hash", journal_header)
        self.assertIn("prediction_hash", journal_header)
        return run_dir

    def test_clean_repository_stores_autoresearch_evidence_in_canonical_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._repository(Path(directory))
            result = self._create(project, project, "clean-run")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._assert_authoritative_evidence(project, "clean-run")

    def test_dirty_active_worktree_keeps_candidate_mutations_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._repository(base)
            (project / "user-notes.txt").write_text("uncommitted user work\n", encoding="utf-8")
            worktree = base / "experiment"
            self._git(project, "worktree", "add", "-q", "-b", "autoresearch/dirty-run", str(worktree), "HEAD")
            (worktree / "model.py").write_text("VALUE = 'candidate'\n", encoding="utf-8")

            result = self._create(project, worktree, "dirty-run")

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._assert_authoritative_evidence(project, "dirty-run")
            self.assertEqual("VALUE = 'baseline'\n", (project / "model.py").read_text(encoding="utf-8"))
            self.assertEqual("uncommitted user work\n", (project / "user-notes.txt").read_text(encoding="utf-8"))
            self.assertFalse((worktree / ".agent-system" / "runs" / "dirty-run").exists())

    def test_toolkit_may_be_loaded_from_outside_target_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._repository(base)
            unrelated_cwd = base / "unrelated"
            unrelated_cwd.mkdir()

            result = self._create(project, unrelated_cwd, "external-toolkit")

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._assert_authoritative_evidence(project, "external-toolkit")
            self.assertFalse((ROOT / ".agent-system" / "runs" / "external-toolkit").exists())

    def test_cwd_in_isolated_worktree_does_not_change_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._repository(base)
            worktree = base / "experiment"
            self._git(project, "worktree", "add", "-q", "-b", "autoresearch/cwd-run", str(worktree), "HEAD")

            result = self._create(project, worktree, "cwd-run")

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._assert_authoritative_evidence(project, "cwd-run")
            self.assertFalse((worktree / ".agent-system" / "runs" / "cwd-run").exists())

    def test_evidence_survives_isolated_worktree_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._repository(base)
            worktree = base / "experiment"
            self._git(project, "worktree", "add", "-q", "-b", "autoresearch/cleanup-run", str(worktree), "HEAD")
            result = self._create(project, worktree, "cleanup-run")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self._git(project, "worktree", "remove", "--force", str(worktree))

            self.assertFalse(worktree.exists())
            self._assert_authoritative_evidence(project, "cleanup-run")

    def test_project_root_is_required_and_never_defaults_to_toolkit_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CREATE_RUN),
                "--id",
                "missing-project-root",
                "--goal",
                "Do not guess the evidence root.",
                "--acceptance",
                "Fail clearly.",
                "--request-kind",
                "optimization",
                "--skill",
                "autoresearch",
                "--mode",
                "autoresearch",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--project-root", result.stderr)
        self.assertFalse((ROOT / ".agent-system" / "runs" / "missing-project-root").exists())


if __name__ == "__main__":
    unittest.main()
