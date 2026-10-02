from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ONBOARD_MODULE_PATH = ROOT / "tooling" / "onboard-project.py"
ONBOARD_SPEC = importlib.util.spec_from_file_location("onboard_project", ONBOARD_MODULE_PATH)
assert ONBOARD_SPEC and ONBOARD_SPEC.loader
onboard_project = importlib.util.module_from_spec(ONBOARD_SPEC)
ONBOARD_SPEC.loader.exec_module(onboard_project)


class OnboardingTests(unittest.TestCase):
    def build_overlay(self, output: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "tooling/build-overlay.py", "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_clean_setup_reports_transient_detection_and_ready_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            overlay = base / "overlay"
            target = base / "synthetic-repository"
            self.build_overlay(overlay)
            shutil.copytree(overlay, target)
            (target / "src" / "training").mkdir(parents=True)
            (target / "src" / "inference").mkdir(parents=True)
            (target / "tests").mkdir()
            (target / "pyproject.toml").write_text(
                '[project]\nname = "synthetic-churn"\ndependencies = ["pytest"]\n\n'
                '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
                encoding="utf-8",
            )
            agents_text = (
                "# Existing project instructions\n\nPreserve this synthetic project rule.\n\n"
                + (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8")
            )
            (target / "AGENTS.md").write_text(agents_text, encoding="utf-8")
            extra_skill = target / ".agents" / "skills" / "entity-resolution" / "SKILL.md"
            extra_skill.parent.mkdir(parents=True)
            extra_skill.write_text(
                "---\nname: entity-resolution\n"
                "description: Resolve synthetic entities for this project.\n---\n"
                "# Entity resolution\n\nUse for project entity-resolution work.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(result.stdout.startswith("READY\n"))
            for expected in (
                "- project: Python project",
                "- tests: pytest",
                "- training: src/training",
                "- inference: src/inference",
                "Available workflows",
                "- Technical report",
                "- Autoresearch",
                "- Independent validation",
                "Validation: PASS",
                "Controls: `.agent-system/CONTROL.md`",
            ):
                self.assertIn(expected, result.stdout)

            project = json.loads(
                (target / ".agent-system" / "project.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual("0.2", project["schema_version"])
            self.assertEqual("unknown", project["data"]["default_classification"])
            self.assertNotIn("project", project)
            self.assertNotIn("commands", project)
            self.assertNotIn("paths", project)
            self.assertTrue(extra_skill.is_file())
            self.assertEqual(agents_text, (target / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertTrue((target / "PROJECT_MAP.md").is_file())

            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Status: READY", status)
            self.assertIn("Validation: PASS", status)
            self.assertIn("## Detected", status)
            self.assertIn("## Available workflows", status)
            self.assertIn("Manual action required\n\nNone.", status)
            self.assertIn("Project-specific skills: `entity-resolution`", status)
            self.assertIn("Controls: `.agent-system/CONTROL.md`", status)


    def test_existing_configuration_and_instructions_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            overlay = base / "overlay"
            target = base / "existing-project"
            self.build_overlay(overlay)
            shutil.copytree(overlay, target)
            (target / "tests").mkdir()
            (target / "pyproject.toml").write_text(
                '[project]\nname = "repository-name"\ndependencies = ["pytest"]\n',
                encoding="utf-8",
            )
            project_path = target / ".agent-system" / "project.yaml"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "project": {"name": "human-name"},
                        "commands": {"tests": None, "lint": "make lint", "typecheck": None},
                        "paths": {
                            "training": "private/training-entrypoint",
                            "inference": None,
                            "tests": None,
                        },
                        "data": {"default_classification": "internal"},
                        "compute": {"local_training": "bounded local only", "distributed_training": None},
                        "systems": {
                            "distributed_compute": "private-cluster-alias",
                            "experiment_tracker": "human-entered tracker",
                            "scheduler": None,
                            "model_registry": None,
                            "git_provider": None,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            agents_path = target / "AGENTS.md"
            agents_text = "# Existing instructions\n\nKeep this exact project rule.\n"
            agents_path.write_text(agents_text, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("ACTION_REQUIRED", result.stdout)
            self.assertEqual(agents_text, agents_path.read_text(encoding="utf-8"))
            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual("human-name", project["project"]["name"])
            self.assertEqual("make lint", project["commands"]["lint"])
            self.assertEqual("internal", project["data"]["default_classification"])
            self.assertEqual("bounded local only", project["compute"]["local_training"])
            self.assertEqual("human-entered tracker", project["systems"]["experiment_tracker"])
            self.assertEqual("private-cluster-alias", project["systems"]["distributed_compute"])
            self.assertEqual("private/training-entrypoint", project["paths"]["training"])
            self.assertIsNone(project["commands"]["tests"])
            self.assertIsNone(project["paths"]["tests"])
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Merge `AGENTS.dsml.template.md`", status)
            self.assertIn("The existing file was preserved unchanged.", status)
            self.assertIn("Validation: PASS", status)
            self.assertNotIn("private-cluster-alias", status)
            self.assertNotIn(
                "private/training-entrypoint",
                (target / "PROJECT_MAP.md").read_text(encoding="utf-8"),
            )

    def test_missing_core_skill_is_named_in_action_required_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "broken-project"
            self.build_overlay(target)
            shutil.rmtree(target / ".agents" / "skills" / "analyze-dsml-project")

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Status: ACTION_REQUIRED", status)
            self.assertIn("Validation: FAIL", status)
            self.assertIn("analyze-dsml-project", status)
            self.assertIn("Resolve the installed-project validation failure", status)

    def test_repair_runtime_restores_only_manifest_owned_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "clean-overlay"
            target = base / "installed-project"
            self.build_overlay(source)
            shutil.copytree(source, target)
            project_owned = target / ".agent-system" / "custom-project-note.txt"
            project_text = "preserve-me\n"
            project_owned.write_text(project_text, encoding="utf-8")
            missing = target / ".agent-system" / "CONTROL.md"
            missing.unlink()

            repaired = onboard_project.repair_runtime(target, source)

            self.assertIn(".agent-system/CONTROL.md", repaired)
            self.assertEqual(
                (source / ".agent-system" / "CONTROL.md").read_bytes(),
                missing.read_bytes(),
            )
            self.assertEqual(
                project_text,
                project_owned.read_text(encoding="utf-8"),
            )
            validation = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(target / ".agent-system" / "tooling" / "validate-kit.py"),
                    "--installed-project",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

    def test_detected_distributed_compute_does_not_infer_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "spark-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "spark-project"\ndependencies = ["pyspark"]\n',
                encoding="utf-8",
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            verdict, summary = onboard_project.onboard_repository(
                target, "codex", validation_runner=lambda _: ("PASS", "synthetic pass")
            )

            self.assertEqual("READY_WITH_WARNINGS", verdict)
            self.assertIn("- distributed compute: Apache Spark", summary)
            project = json.loads(
                (target / ".agent-system" / "project.yaml").read_text(encoding="utf-8")
            )
            self.assertIsNone(project["systems"]["distributed_compute"])
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Full/distributed training (`costly_compute`): `approval_required`", status)
            self.assertIn("Manual action required\n\nNone.", status)


    def test_recheck_clears_fixed_instruction_action_without_rewriting_project_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "recheck-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "recheck-project"\n', encoding="utf-8"
            )
            agents = target / "AGENTS.md"
            agents.write_text("# Existing instructions\n", encoding="utf-8")
            command = [
                sys.executable,
                "-B",
                ".agent-system/tooling/onboard-project.py",
                "--installed-project",
                ".",
                "--harness",
                "codex",
            ]

            first = subprocess.run(
                command,
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(1, first.returncode, first.stdout + first.stderr)
            self.assertIn("ACTION_REQUIRED", first.stdout)
            project_before = (target / ".agent-system" / "project.yaml").read_text(
                encoding="utf-8"
            )
            project_map = target / "PROJECT_MAP.md"
            project_map.write_text(
                project_map.read_text(encoding="utf-8") + "\nHuman-maintained note.\n",
                encoding="utf-8",
            )
            map_before = project_map.read_text(encoding="utf-8")
            agents.write_text(
                agents.read_text(encoding="utf-8")
                + "\n"
                + (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            second = subprocess.run(
                command + ["--recheck"],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertIn("READY", second.stdout)
            self.assertEqual(
                project_before,
                (target / ".agent-system" / "project.yaml").read_text(encoding="utf-8"),
            )
            self.assertEqual(map_before, project_map.read_text(encoding="utf-8"))
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Status: READY", status)
            self.assertIn("Manual action required\n\nNone.", status)

    def test_validation_unavailable_is_never_reported_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "no-python-project"
            self.build_overlay(target)

            def unavailable(_: Path) -> tuple[str, str]:
                return "NOT RUN", "Python execution is unavailable in this synthetic runtime."

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=unavailable,
            )

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Validation: NOT RUN", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Validation: NOT RUN", status)
            self.assertIn(
                "Run `",
                status,
            )
            self.assertIn(".agent-system/tooling/validate-kit.py --installed-project .", status)
            self.assertIn("from the repository root, then recheck onboarding.", status)
            self.assertNotIn("Validation: PASS", status)

    def test_validation_timeout_is_reported_as_an_attempted_failure(self) -> None:
        with mock.patch.object(
            onboard_project.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["python3", "validate-kit.py"], 60),
        ):
            result, detail = onboard_project._run_validation(ROOT)

        self.assertEqual("FAIL", result)
        self.assertIn("started", detail)
        self.assertIn("timed out", detail)

    def test_deployed_workflow_routes_setup_and_recheck(self) -> None:
        skill = (ROOT / ".agents" / "skills" / "analyze-dsml-project" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        orientation = (
            ROOT / ".agents" / "skills" / "analyze-dsml-project" / "references" / "orientation.md"
        ).read_text(encoding="utf-8")
        instructions = (
            ROOT / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        control = (ROOT / ".agent-system" / "CONTROL.md").read_text(encoding="utf-8")

        for text in (skill, orientation):
            self.assertIn("Set up the DS/ML Agent Kit", text)
            self.assertIn("Recheck DS/ML Agent Kit", text)
        for path in (
            ".agent-system/CONTROL.md",
            ".agent-system/SYSTEM.md",
            ".agent-system/workflows/",
        ):
            self.assertIn(path, instructions)
        self.assertIn("## Setup in three steps", control)
        self.assertIn("READY_WITH_WARNINGS", control)
        self.assertIn(".agent-system/tooling/validate-kit.py --installed-project .", control)
        self.assertIn("Need more detail? See [`SYSTEM.md`](SYSTEM.md).", control)
        self.assertFalse((ROOT / ".agent-system" / "docs" / "DSML_AGENT_KIT.md").exists())
        self.assertFalse((ROOT / ".agent-system" / "docs" / "HOW_TO_USE_DSML_AGENT.md").exists())


    def test_invalid_existing_project_config_still_creates_action_required_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "invalid-config-project"
            self.build_overlay(target)
            (target / ".agent-system" / "project.yaml").write_text(
                "{ definitely not valid JSON-compatible YAML }\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("ACTION_REQUIRED", result.stdout)
            status_path = target / ".agent-system" / "onboarding-status.md"
            self.assertTrue(status_path.is_file())
            status = status_path.read_text(encoding="utf-8")
            self.assertIn("Status: ACTION_REQUIRED", status)
            self.assertIn("Validation: NOT RUN", status)
            self.assertIn("Fix `.agent-system/project.yaml`", status)

    def test_onboarding_refuses_a_root_without_an_installed_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "wrong-repository"
            target.mkdir()

            with self.assertRaisesRegex(ValueError, "installed overlay markers are missing"):
                onboard_project.onboard_repository(target, "codex")

            self.assertEqual([], list(target.iterdir()))

    def test_onboarding_rejects_symlinked_installed_overlay_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "symlinked-overlay"
            self.build_overlay(target)
            external = base / "external-project-template.json"
            external.write_text("{}\n", encoding="utf-8")
            template = target / ".agent-system" / "project.template.yaml"
            template.unlink()
            try:
                template.symlink_to(external)
            except (NotImplementedError, OSError):
                self.skipTest("symbolic links are not supported in this runtime")

            with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
                onboard_project.onboard_repository(target, "codex")

            self.assertFalse((target / ".agent-system" / "project.yaml").exists())
            self.assertFalse((target / ".agent-system" / "onboarding-status.md").exists())

    def test_broken_symlink_to_capability_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "broken-policy-link"
            self.build_overlay(target)
            external = base / "missing-target.yaml"
            active = target / ".agent-system" / "policy" / "capability-policy.yaml"
            try:
                active.symlink_to(external)
            except (NotImplementedError, OSError):
                self.skipTest("symbolic links are not supported in this runtime")

            verdict, summary = onboard_project.onboard_repository(target, "codex")

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Capability policy: invalid active policy", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("approved active project policy", status)

    def test_onboarding_rejects_symlinked_skill_directory_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "symlinked-skills"
            self.build_overlay(target)
            external_skills = base / "external-skills"
            shutil.copytree(target / ".agents" / "skills", external_skills)
            shutil.rmtree(target / ".agents" / "skills")
            try:
                (target / ".agents" / "skills").symlink_to(
                    external_skills, target_is_directory=True
                )
            except (NotImplementedError, OSError):
                self.skipTest("symbolic links are not supported in this runtime")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                onboard_project.onboard_repository(target, "codex")

            self.assertFalse((target / ".agent-system" / "project.yaml").exists())

    def test_onboarding_requires_version_marker_before_writing_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing-version"
            self.build_overlay(target)
            (target / ".agent-system" / "VERSION").unlink()

            with self.assertRaisesRegex(ValueError, "installed overlay markers are missing.*VERSION"):
                onboard_project.onboard_repository(target, "codex")

            self.assertFalse((target / ".agent-system" / "project.yaml").exists())
            self.assertFalse((target / ".agent-system" / "onboarding-status.md").exists())

    def test_onboarding_rejects_symlinked_project_owned_write_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            scenarios = ("project", "project-map", "status", "instruction-parent")
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    target = base / scenario / "repository"
                    self.build_overlay(target)
                    (target / "pyproject.toml").write_text(
                        '[project]\nname = "safe-write-test"\n', encoding="utf-8"
                    )
                    (target / "AGENTS.md").write_text(
                        (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    victim = base / scenario / "victim.txt"
                    victim.parent.mkdir(parents=True, exist_ok=True)
                    victim.write_text("outside repository\n", encoding="utf-8")
                    harness = "codex"

                    if scenario == "project":
                        destination = target / ".agent-system" / "project.yaml"
                        destination.symlink_to(victim)
                    elif scenario == "project-map":
                        destination = target / "PROJECT_MAP.md"
                        destination.symlink_to(victim)
                    elif scenario == "status":
                        destination = target / ".agent-system" / "onboarding-status.md"
                        destination.symlink_to(victim)
                    else:
                        shutil.rmtree(target / ".github", ignore_errors=True)
                        external_parent = base / scenario / "external-github"
                        external_parent.mkdir()
                        (target / ".github").symlink_to(external_parent, target_is_directory=True)
                        destination = external_parent / "copilot-instructions.md"
                        harness = "copilot"

                    with self.assertRaisesRegex(ValueError, "symbolic link"):
                        onboard_project.onboard_repository(
                            target,
                            harness,
                            validation_runner=lambda _: ("PASS", "synthetic pass"),
                        )

                    self.assertEqual("outside repository\n", victim.read_text(encoding="utf-8"))
                    if scenario == "instruction-parent":
                        self.assertFalse(destination.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX permission semantics required")
    def test_safe_write_preserves_restrictive_existing_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / ".agent-system" / "project.yaml"
            destination.parent.mkdir()
            destination.write_text("old\n", encoding="utf-8")
            destination.chmod(0o600)

            onboard_project._safe_write(root, destination, "new\n")

            self.assertEqual("new\n", destination.read_text(encoding="utf-8"))
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)

    def test_setup_error_status_does_not_follow_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "invalid-project"
            self.build_overlay(target)
            (target / ".agent-system" / "project.yaml").write_text(
                "{ definitely not valid JSON-compatible YAML }\n", encoding="utf-8"
            )
            victim = base / "victim.txt"
            victim.write_text("outside repository\n", encoding="utf-8")
            status = target / ".agent-system" / "onboarding-status.md"
            status.symlink_to(victim)

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertEqual("outside repository\n", victim.read_text(encoding="utf-8"))
            self.assertIn("Onboarding status was not written safely", result.stdout)

    def test_setup_error_status_does_not_read_symlinked_version_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "symlinked-version"
            self.build_overlay(target)
            external = base / "external-version.txt"
            external.write_text("synthetic-sensitive-marker\n", encoding="utf-8")
            version = target / ".agent-system" / "VERSION"
            version.unlink()
            version.symlink_to(external)

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Toolkit version: unknown", status)
            self.assertNotIn("synthetic-sensitive-marker", status)

    def test_onboarding_rejects_symlinked_harness_instruction_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "symlinked-instruction-source"
            self.build_overlay(target)
            source = target / "adapters" / "copilot" / "copilot-instructions.fragment.md"
            external = base / "external-instructions.md"
            external.write_text("Synthetic external instructions.\n", encoding="utf-8")
            source.unlink()
            source.symlink_to(external)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                onboard_project.onboard_repository(target, "copilot")

            self.assertFalse((target / ".github" / "copilot-instructions.md").exists())

    def test_post_config_setup_error_does_not_blame_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing-instruction-source"
            self.build_overlay(target)
            (target / "AGENTS.dsml.template.md").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    ".agent-system/tooling/onboard-project.py",
                    "--installed-project",
                    ".",
                    "--harness",
                    "codex",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Restore the missing or invalid toolkit runtime file", status)
            self.assertNotIn("Fix `.agent-system/project.yaml`", status)

    def test_recheck_does_not_persist_rediscoverable_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "recheck-values"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "repository-name"\ndependencies = ["pytest"]\n',
                encoding="utf-8",
            )
            (target / "tests").mkdir()
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            project_path = target / ".agent-system" / "project.yaml"
            project_path.write_text(
                (target / ".agent-system" / "project.template.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            before = project_path.read_text(encoding="utf-8")

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                recheck=True,
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY", verdict)
            self.assertEqual(before, project_path.read_text(encoding="utf-8"))
            self.assertIn("- project: Python project", summary)
            self.assertIn("- tests: pytest", summary)
            project = json.loads(before)
            self.assertNotIn("project", project)
            self.assertNotIn("commands", project)
            self.assertNotIn("paths", project)


    def test_recheck_preserves_explicit_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "recheck-preserve"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "repository-name"\ndependencies = ["pytest"]\n',
                encoding="utf-8",
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            project_path = target / ".agent-system" / "project.yaml"
            explicit = {
                "schema_version": "0.2",
                "project": {"name": "human-name"},
                "commands": {"tests": "make test"},
                "data": {"default_classification": "internal"},
            }
            project_path.write_text(json.dumps(explicit), encoding="utf-8")

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                recheck=True,
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY_WITH_WARNINGS", verdict)
            self.assertEqual(explicit, json.loads(project_path.read_text(encoding="utf-8")))
            self.assertIn("Configuration conflict: project.name", summary)
            self.assertIn("Configuration conflict: commands.tests", summary)


    def test_recheck_is_idempotent_when_nothing_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "recheck-idempotent"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            onboard_project.onboard_repository(
                target, "codex", validation_runner=lambda _: ("PASS", "synthetic pass")
            )
            project_path = target / ".agent-system" / "project.yaml"
            before = project_path.read_text(encoding="utf-8")

            verdict, _ = onboard_project.onboard_repository(
                target,
                "codex",
                recheck=True,
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY", verdict)
            self.assertEqual(before, project_path.read_text(encoding="utf-8"))
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Project config: preserved unchanged (recheck)", status)


    def test_common_authoritative_architecture_map_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "mapped-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "mapped-project"\n', encoding="utf-8"
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            architecture = target / "docs" / "system-architecture.md"
            architecture.parent.mkdir()
            architecture.write_text("# Authoritative architecture\n", encoding="utf-8")

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY", verdict)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("reused `docs/system-architecture.md`", status)
            self.assertFalse((target / "PROJECT_MAP.md").exists())

    def test_partial_instruction_markers_do_not_count_as_complete_integration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            scenarios = ("codex", "copilot")
            for harness in scenarios:
                with self.subTest(harness=harness):
                    target = base / harness
                    self.build_overlay(target)
                    if harness == "codex":
                        instruction_path = target / "AGENTS.md"
                        original = "# DS/ML project runtime invariants\n"
                    else:
                        instruction_path = target / ".github" / "copilot-instructions.md"
                        instruction_path.parent.mkdir()
                        original = (target / "AGENTS.dsml.template.md").read_text(
                            encoding="utf-8"
                        )
                    instruction_path.write_text(original, encoding="utf-8")

                    verdict, _ = onboard_project.onboard_repository(
                        target,
                        harness,
                        validation_runner=lambda _: ("PASS", "synthetic pass"),
                    )

                    self.assertEqual("ACTION_REQUIRED", verdict)
                    self.assertEqual(original, instruction_path.read_text(encoding="utf-8"))
                    status = (target / ".agent-system" / "onboarding-status.md").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("merge required", status)
                    self.assertIn("The existing file was preserved unchanged.", status)

    def test_instructions_inside_a_code_fence_do_not_count_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "fenced-instructions"
            self.build_overlay(target)
            template = (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8")
            agents = target / "AGENTS.md"
            original = "# Existing instructions\n\n```markdown\n" + template + "\n```\n"
            agents.write_text(original, encoding="utf-8")

            verdict, _ = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertEqual(original, agents.read_text(encoding="utf-8"))
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("merge required", status)

    def test_active_policy_decision_bucket_controls_capability_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for decision in ("allowed", "forbidden"):
                with self.subTest(decision=decision):
                    target = base / decision
                    self.build_overlay(target)
                    (target / "pyproject.toml").write_text(
                        '[project]\nname = "policy-test"\ndependencies = ["pyspark"]\n',
                        encoding="utf-8",
                    )
                    (target / "AGENTS.md").write_text(
                        (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    template = target / ".agent-system" / "policy" / "capability-policy.template.yaml"
                    policy = json.loads(template.read_text(encoding="utf-8"))
                    policy["policy_status"] = "approved_project_policy"
                    policy["approval"] = {
                        "authority": "synthetic project owner",
                        "evidence_ref": "approval:synthetic-policy",
                    }
                    action = next(
                        item
                        for item in policy["actions"]["approval_required"]
                        if item["id"] == "costly_compute"
                    )
                    policy["actions"]["approval_required"].remove(action)
                    policy["actions"][decision].append(action)
                    (template.parent / "capability-policy.yaml").write_text(
                        json.dumps(policy), encoding="utf-8"
                    )

                    result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            ".agent-system/tooling/onboard-project.py",
                            "--installed-project",
                            ".",
                            "--harness",
                            "codex",
                        ],
                        cwd=target,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertIn("READY", result.stdout)
                    status = (target / ".agent-system" / "onboarding-status.md").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("Configured: approved active project policy", status)
                    self.assertIn(
                        f"Full/distributed training (`costly_compute`): `{decision}`", status
                    )
                    self.assertNotIn("conservative defaults active", status)
                    self.assertNotIn("authorization was not inferred", result.stdout.lower())

    def test_invalid_active_policy_is_not_described_as_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "invalid-active-policy"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            policy_dir = target / ".agent-system" / "policy"
            policy = json.loads(
                (policy_dir / "capability-policy.template.yaml").read_text(encoding="utf-8")
            )
            policy["policy_status"] = "approved_project_policy"
            policy["approval"] = {
                "authority": "synthetic project owner",
                "evidence_ref": "approval:invalid-policy",
            }
            policy["actions"]["approval_required"] = [
                item
                for item in policy["actions"]["approval_required"]
                if item["id"] != "costly_compute"
            ]
            (policy_dir / "capability-policy.yaml").write_text(
                json.dumps(policy), encoding="utf-8"
            )

            verdict, summary = onboard_project.onboard_repository(target, "codex")

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Capability policy: invalid active policy", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("approved active project policy", status)
            self.assertIn("could not be validated", status)

    def test_structurally_invalid_active_policy_makes_all_decisions_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unsafe-active-policy"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            policy_dir = target / ".agent-system" / "policy"
            policy = json.loads(
                (policy_dir / "capability-policy.template.yaml").read_text(encoding="utf-8")
            )
            policy["policy_status"] = "approved_project_policy"
            policy["approval"] = {
                "authority": "synthetic project owner",
                "evidence_ref": "approval:unsafe-policy",
            }
            production_mutation = next(
                item
                for item in policy["actions"]["forbidden"]
                if item["id"] == "production_data_mutation"
            )
            policy["actions"]["forbidden"].remove(production_mutation)
            policy["actions"]["allowed"].append(production_mutation)
            (policy_dir / "capability-policy.yaml").write_text(
                json.dumps(policy), encoding="utf-8"
            )

            verdict, summary = onboard_project.onboard_repository(target, "codex")

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Capability policy: invalid active policy", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("approved active project policy", status)
            for _, capability in onboard_project.STATUS_CAPABILITIES:
                self.assertIn(f"(`{capability}`): `unknown`", status)

    def test_chat_summary_lists_every_manual_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "summary-target"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text("# existing\n", encoding="utf-8")
            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("NOT RUN", "synthetic unavailable"),
            )
            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Manual action required:\n1. ", summary)
            self.assertIn(".agent-system/tooling/validate-kit.py --installed-project .", summary)
            self.assertIn("from the repository root, then recheck onboarding.", summary)

    def test_status_lists_transient_detected_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "values-target"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "values-target"\ndependencies = ["pytest"]\n',
                encoding="utf-8",
            )
            (target / "tests").mkdir()
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            onboard_project.onboard_repository(
                target, "codex", validation_runner=lambda _: ("PASS", "synthetic pass")
            )
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Detected", status)
            self.assertIn("- Project: `Python project`", status)
            self.assertIn("- Tests: `pytest`", status)
            project = json.loads(
                (target / ".agent-system" / "project.yaml").read_text(encoding="utf-8")
            )
            self.assertNotIn("project", project)
            self.assertNotIn("commands", project)
            self.assertNotIn("paths", project)


    def test_mlflow_artifact_does_not_prove_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "mlflow-model-artifact"
            self.build_overlay(target)
            (target / "MLmodel").write_text("flavor: python_function\n", encoding="utf-8")
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            onboard_project.onboard_repository(
                target, "codex", validation_runner=lambda _: ("PASS", "synthetic pass")
            )
            project = json.loads(
                (target / ".agent-system" / "project.yaml").read_text(encoding="utf-8")
            )
            self.assertIsNone(project["systems"]["model_registry"])

    def test_hermes_target_honours_agents_override_md(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hermes-override"
            self.build_overlay(target)
            (target / "AGENTS.override.md").write_text(
                "# Hermes-only runtime overrides\n", encoding="utf-8"
            )
            verdict, _ = onboard_project.onboard_repository(
                target,
                "hermes",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )
            self.assertEqual("ACTION_REQUIRED", verdict)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("merge required in `AGENTS.override.md`", status)
            self.assertFalse((target / "AGENTS.md").exists())

    def test_material_conflict_between_existing_and_inferred_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "conflict-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "repository-name"\ndependencies = ["pytest"]\n',
                encoding="utf-8",
            )
            (target / "tests").mkdir()
            project_path = target / ".agent-system" / "project.yaml"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "project": {"name": "human-name"},
                        "commands": {"tests": "make test", "lint": None, "typecheck": None},
                        "paths": {"training": None, "inference": None, "tests": None},
                        "data": {"default_classification": "unknown"},
                        "compute": {"local_training": None, "distributed_training": None},
                        "systems": {
                            "distributed_compute": None,
                            "experiment_tracker": None,
                            "scheduler": None,
                            "model_registry": None,
                            "git_provider": None,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY_WITH_WARNINGS", verdict)
            self.assertIn("Configuration conflict:", summary)
            self.assertIn("project.name", summary)
            self.assertIn("commands.tests", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Configuration conflict: project.name", status)
            self.assertIn("Configuration conflict: commands.tests", status)
            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual("human-name", project["project"]["name"])
            self.assertEqual("make test", project["commands"]["tests"])

    def test_inferred_path_conflict_is_surfaced_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "path-conflict-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "path-conflict"\n', encoding="utf-8"
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (target / "src" / "training").mkdir(parents=True)
            project_path = target / ".agent-system" / "project.yaml"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "project": {"name": "path-conflict"},
                        "commands": {"tests": None, "lint": None, "typecheck": None},
                        "paths": {
                            "training": "private/training-entrypoint",
                            "inference": None,
                            "tests": None,
                        },
                        "data": {"default_classification": "unknown"},
                        "compute": {
                            "local_training": None,
                            "distributed_training": None,
                        },
                        "systems": {
                            "distributed_compute": None,
                            "experiment_tracker": None,
                            "scheduler": None,
                            "model_registry": None,
                            "git_provider": None,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY_WITH_WARNINGS", verdict)
            self.assertIn("Configuration conflict: paths.training", summary)
            self.assertIn("private/training-entrypoint", summary)
            self.assertIn("src/training", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Configuration conflict: paths.training", status)
            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual("private/training-entrypoint", project["paths"]["training"])

    def test_inferred_system_conflict_is_surfaced_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system-conflict-project"
            self.build_overlay(target)
            (target / "pyproject.toml").write_text(
                '[project]\nname = "system-conflict"\ndependencies = ["pyspark"]\n',
                encoding="utf-8",
            )
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            project_path = target / ".agent-system" / "project.yaml"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.2",
                        "project": {"name": "system-conflict"},
                        "commands": {"tests": None, "lint": None, "typecheck": None},
                        "paths": {
                            "training": None,
                            "inference": None,
                            "tests": None,
                        },
                        "data": {"default_classification": "unknown"},
                        "compute": {
                            "local_training": None,
                            "distributed_training": None,
                        },
                        "systems": {
                            "distributed_compute": "private-cluster-alias",
                            "experiment_tracker": None,
                            "scheduler": None,
                            "model_registry": None,
                            "git_provider": None,
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            verdict, summary = onboard_project.onboard_repository(
                target,
                "codex",
                validation_runner=lambda _: ("PASS", "synthetic pass"),
            )

            self.assertEqual("READY_WITH_WARNINGS", verdict)
            self.assertIn(
                "Configuration conflict: systems.distributed_compute", summary
            )
            self.assertIn("private-cluster-alias", summary)
            self.assertIn("Apache Spark", summary)
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "Configuration conflict: systems.distributed_compute", status
            )
            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "private-cluster-alias", project["systems"]["distributed_compute"]
            )

    def test_invalid_capability_policy_template_manual_action_points_to_template(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "broken-template-project"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            template = target / ".agent-system" / "policy" / "capability-policy.template.yaml"
            template.write_text("{ definitely not valid JSON-compatible YAML }\n", encoding="utf-8")

            verdict, summary = onboard_project.onboard_repository(target, "codex")

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn(
                "Capability policy: invalid capability policy template", summary
            )
            self.assertIn(
                "Restore or repair `.agent-system/policy/capability-policy.template.yaml`",
                summary,
            )
            self.assertNotIn(
                "Repair `.agent-system/policy/capability-policy.yaml`", summary
            )
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Capability-policy template is invalid", status)
            self.assertIn(
                "Restore or repair `.agent-system/policy/capability-policy.template.yaml`",
                status,
            )

    def test_invalid_active_policy_manual_action_points_to_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "broken-active-policy-project"
            self.build_overlay(target)
            (target / "AGENTS.md").write_text(
                (target / "AGENTS.dsml.template.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            policy_dir = target / ".agent-system" / "policy"
            template = policy_dir / "capability-policy.template.yaml"
            policy = json.loads(template.read_text(encoding="utf-8"))
            policy["policy_status"] = "approved_project_policy"
            policy["approval"] = {
                "authority": "synthetic project owner",
                "evidence_ref": "approval:invalid-active",
            }
            policy["actions"]["approval_required"] = [
                item
                for item in policy["actions"]["approval_required"]
                if item["id"] != "costly_compute"
            ]
            (policy_dir / "capability-policy.yaml").write_text(
                json.dumps(policy), encoding="utf-8"
            )

            verdict, summary = onboard_project.onboard_repository(target, "codex")

            self.assertEqual("ACTION_REQUIRED", verdict)
            self.assertIn("Capability policy: invalid active policy", summary)
            self.assertIn(
                "Repair `.agent-system/policy/capability-policy.yaml`", summary
            )
            self.assertNotIn(
                "Restore or repair `.agent-system/policy/capability-policy.template.yaml`",
                summary,
            )
            status = (target / ".agent-system" / "onboarding-status.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Repair `.agent-system/policy/capability-policy.yaml`", status)
            self.assertNotIn(
                "Restore or repair `.agent-system/policy/capability-policy.template.yaml`",
                status,
            )

    def test_safe_write_non_posix_branch_writes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "non-posix-root"
            root.mkdir()
            destination = root / "nested" / "subdir" / "policy.yaml"
            original = (
                "policy_status: conservative_default\n"
                "actions:\n  allowed: []\n  approval_required: []\n  forbidden: []\n"
            )
            relative = Path("nested") / "subdir" / "policy.yaml"

            onboard_project._safe_write_non_posix(root, destination, original, relative)

            self.assertEqual(original, destination.read_text(encoding="utf-8"))
            self.assertTrue(destination.is_file())
            self.assertFalse(destination.is_symlink())
            leftover = list(destination.parent.glob(f".{destination.name}.*.tmp"))
            self.assertEqual([], leftover)
            self.assertFalse(
                (destination.parent / f".{destination.name}.tmp").exists()
            )

    def test_safe_write_non_posix_branch_rejects_symlinked_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "non-posix-symlinked-root"
            root.mkdir()
            victim = base / "victim.txt"
            victim.write_text("outside repository\n", encoding="utf-8")
            destination = root / "policy.yaml"
            try:
                destination.symlink_to(victim)
            except (NotImplementedError, OSError):
                self.skipTest("symbolic links are not supported in this runtime")

            relative = Path("policy.yaml")
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                onboard_project._safe_write_non_posix(
                    root, destination, "new\n", relative
                )

            self.assertEqual("outside repository\n", victim.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
