from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tooling" / "validate-kit.py"
SPEC = importlib.util.spec_from_file_location("validate_kit", MODULE_PATH)
assert SPEC and SPEC.loader
validate_kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_kit)


class ValidateKitTests(unittest.TestCase):
    def make_symlink_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlinks unavailable in this environment: {exc}")

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

    def test_repository_contract_passes(self) -> None:
        self.assertEqual([], validate_kit.validate_repository(ROOT))

    def test_overlay_build_is_deterministic_and_excludes_development_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = base / "first"
            second = base / "second"
            self.build_overlay(first)
            self.build_overlay(second)

            first_files = {
                str(path.relative_to(first)): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                str(path.relative_to(second)): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }

        self.assertEqual(first_files, second_files)
        for skill in validate_kit.CORE_SKILLS | validate_kit.BUNDLED_SPECIALIZED_SKILLS:
            self.assertIn(f".agents/skills/{skill}/SKILL.md", first_files)
        self.assertIn(
            ".agents/skills/autoresearch/SKILL.md",
            json.loads(first_files[".agent-system/manifest.json"])["files"],
        )
        for required in (
            "DSML_AGENT_KIT.md",
            ".agent-system/VERSION",
            ".agent-system/manifest.json",
            ".agent-system/project.template.yaml",
            ".agent-system/schemas/learning.schema.json",
            ".agent-system/schemas/request-event.schema.json",
            ".agent-system/schemas/request-patterns.schema.json",
            ".agent-system/schemas/evaluation.schema.json",
            ".agent-system/schemas/project.schema.json",
            ".agent-system/schemas/run.schema.json",
            ".agent-system/templates/learning.template.yaml",
            ".agent-system/templates/evaluation.template.yaml",
            ".agent-system/tooling/create-run.py",
            ".agent-system/tooling/finalize-run.py",
            ".agent-system/tooling/git_preflight.py",
            ".agent-system/tooling/onboard-project.py",
            ".agent-system/tooling/record-request.py",
            ".agent-system/tooling/reconstruct-contract.py",
            ".agent-system/tooling/record-experiment.py",
            ".agent-system/tooling/request_events.py",
            ".agent-system/tooling/review-requests.py",
            ".agent-system/tooling/validate-kit.py",
            ".agent-system/local/.gitignore",
            ".agent-system/CONTROL.md",
            ".agent-system/SYSTEM.md",
            ".agent-system/docs/LEARNING_LOOP.md",
            ".agent-system/workflows/technical-report.md",
            ".agent-system/workflows/autoresearch.md",
            ".agent-system/workflows/independent-validation.md",
            ".agent-system/templates/AGENTS.dsml.template.md",
            ".agent-system/adapters/codex/AGENTS.fragment.md",
            ".agent-system/adapters/copilot/copilot-instructions.fragment.md",
            ".agent-system/adapters/hermes/hermes-project.fragment.md",
        ):
            self.assertIn(required, first_files)
        for root_document in ("AGENTS.dsml.template.md", "HOW_TO_USE_DSML_AGENT.md", "LEARNING_LOOP.md"):
            self.assertNotIn(root_document, first_files)
        self.assertFalse(any(path.startswith("adapters/") for path in first_files))
        self.assertNotIn("README.md", first_files)
        self.assertFalse(any(path.startswith("evals/") for path in first_files))
        self.assertFalse(any("/.agent-system/runs/" in f"/{path}" for path in first_files))
        self.assertNotIn(".agent-system/onboarding-status.md", first_files)
        self.assertNotIn(".agent-system/project.yaml", first_files)
        self.assertNotIn(".agent-system/policy/capability-policy.yaml", first_files)
        self.assertNotIn(".agent-system/local/request-events.jsonl", first_files)
        self.assertNotIn(".agent-system/local/request-patterns.yaml", first_files)

        visible_root_entries = sorted(
            {path.split("/", 1)[0] for path in first_files if not path.startswith(".")}
        )
        self.assertEqual(["DSML_AGENT_KIT.md"], visible_root_entries)
        guide = first_files["DSML_AGENT_KIT.md"].decode("utf-8")
        for required_text in (
            "# DS/ML Agent Kit",
            "## Quick setup",
            "Set up the DS/ML Agent Kit for this project.",
            "## Common usage",
            ".agent-system/CONTROL.md",
            "## Git",
            "## Advanced / internals",
            "Most users do not need to edit files inside `.agent-system`.",
        ):
            self.assertIn(required_text, guide)
        for absent_text in (
            "Analyze this project",
            "Implement this feature",
            "Investigate this model issue",
            "Create a technical PDF report",
            "Update the project map",
        ):
            self.assertNotIn(absent_text, guide)
        self.assertLessEqual(len(guide.splitlines()), 45)

    def test_installed_validation_does_not_create_missing_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            local = target / ".agent-system" / "local"
            shutil.rmtree(local)

            validate_kit.validate_installed_project(target)

            self.assertFalse(local.exists())

    def test_installed_validator_accepts_valid_aggregate_prefix_with_newer_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            record = ROOT / "tooling" / "record-request.py"
            for index in range(4):
                review_every = "3" if index < 3 else "100"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(record),
                        "--project-root",
                        str(target),
                        "--kind",
                        "technical_report",
                        "--topic",
                        "model_evaluation",
                        "--deliverable",
                        "pdf",
                        "--route",
                        "technical-report",
                        "--outcome",
                        "completed",
                        "--event-id",
                        f"prefix-event-{index}",
                        "--timestamp",
                        f"2026-10-0{index + 1}T12:00:00Z",
                        "--review-every",
                        review_every,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            errors = validate_kit.validate_installed_project(target)

        self.assertFalse(any("request-patterns.yaml is stale" in error for error in errors), errors)

    def test_installed_project_validates_deterministic_request_patterns_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            record = target / ".agent-system" / "tooling" / "record-request.py"
            for index in range(3):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(record),
                        "--project-root",
                        str(target),
                        "--kind",
                        "technical_report",
                        "--topic",
                        "model_evaluation",
                        "--deliverable",
                        "pdf",
                        "--route",
                        "technical-report",
                        "--outcome",
                        "completed",
                        "--event-id",
                        f"event-{index}",
                        "--timestamp",
                        f"2026-10-0{index + 1}T12:00:00Z",
                        "--review-every",
                        "3",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            self.assertEqual([], validate_kit.validate_installed_project(target))
            patterns_path = target / ".agent-system" / "local" / "request-patterns.yaml"
            patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
            patterns["source_event_count"] = 99
            patterns_path.write_text(json.dumps(patterns, indent=2) + "\n", encoding="utf-8")
            errors = validate_kit.validate_installed_project(target)

        self.assertTrue(
            any("exceeds the request-event ledger length" in error for error in errors),
            errors,
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            record = target / ".agent-system" / "tooling" / "record-request.py"
            review = target / ".agent-system" / "tooling" / "review-requests.py"
            for index in range(3):
                result = subprocess.run(
                    [
                        sys.executable, "-B", str(record),
                        "--project-root", str(target),
                        "--kind", "technical_report",
                        "--topic", "model_evaluation",
                        "--deliverable", "pdf",
                        "--route", "technical-report",
                        "--outcome", "completed",
                        "--event-id", f"event-{index}",
                        "--timestamp", f"2026-10-0{index + 1}T12:00:00Z",
                        "--review-every", "3",
                    ],
                    capture_output=True, text=True, check=False, timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            subprocess.run(
                [
                    sys.executable, "-B", str(record),
                    "--project-root", str(target),
                    "--kind", "technical_report",
                    "--topic", "model_evaluation",
                    "--deliverable", "pdf",
                    "--route", "technical-report",
                    "--outcome", "completed",
                    "--event-id", "event-3",
                    "--timestamp", "2026-10-04T12:00:00Z",
                    "--review-every", "100",
                ],
                capture_output=True, text=True, check=False, timeout=60,
            )
            force = subprocess.run(
                [sys.executable, "-B", str(review), "--project-root", str(target), "--force", "--minimum-count", "3"],
                capture_output=True, text=True, check=False, timeout=60,
            )
            self.assertEqual(0, force.returncode, force.stdout + force.stderr)
            patterns_path = target / ".agent-system" / "local" / "request-patterns.yaml"
            patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
            pattern = patterns["patterns"][0]
            pattern["count"] = pattern["count"] + 1
            patterns["source_event_count"] = 3
            patterns["reviewed_through"] = pattern["last_seen"]
            patterns_path.write_text(json.dumps(patterns, indent=2) + "\n", encoding="utf-8")
            errors = validate_kit.validate_installed_project(target)

        self.assertTrue(any("stale or tampered" in error for error in errors), errors)

    def test_installed_project_ignores_unrelated_files_and_allows_project_specific_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            overlay = base / "overlay"
            target = base / "target"
            self.build_overlay(overlay)
            shutil.copytree(overlay, target)
            (target / "src").mkdir()
            app = target / "src" / "app.py"
            app.write_text("# TO" + "DO belongs to the target project\n", encoding="utf-8")
            (target / "PROJECT_NOTES.md").write_text("Existing project docs.\n", encoding="utf-8")
            self.make_symlink_or_skip(target / "src" / "app-link.py", app)
            extension = target / ".agents" / "skills" / "forecasting" / "SKILL.md"
            extension.parent.mkdir(parents=True)
            extension.write_text(
                "---\n"
                "name: forecasting\n"
                "description: Forecast time series with project-specific backtesting.\n"
                "---\n"
                "# Forecasting\n\nUse for recurring project forecasting requests.\n",
                encoding="utf-8",
            )
            (target / ".agent-system" / "project.yaml").write_text(
                '{"schema_version":"0.2","project":{"name":null}}\n',
                encoding="utf-8",
            )
            runs_root = target / ".agent-system" / "runs"
            for run_id in ("20000102-forecast", "20000103-forecast"):
                run_dir = runs_root / run_id
                run_dir.mkdir(parents=True)
                shutil.copyfile(target / ".agent-system/templates/run.template.yaml", run_dir / "run.yaml")
                learning = json.loads((target / ".agent-system/templates/learning.template.yaml").read_text(encoding="utf-8"))
                learning["run_ref"] = f".agent-system/runs/{run_id}/run.yaml"
                (run_dir / "learning.yaml").write_text(json.dumps(learning) + "\n", encoding="utf-8")

            errors = validate_kit.validate_installed_project(target)

        self.assertEqual([], errors)

    def test_source_skill_validation_distinguishes_bundled_and_project_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            extra = root / ".agents" / "skills" / "unexpected-source-skill" / "SKILL.md"
            extra.parent.mkdir(parents=True)
            extra.write_text(
                "---\nname: unexpected-source-skill\n"
                "description: Unexpected source-shipped skill.\n---\n# Unexpected\n",
                encoding="utf-8",
            )

            source_errors = validate_kit.validate_skills(root)
            installed_errors = validate_kit.validate_skills(root, require_exact_core=False)

        self.assertTrue(any("unexpected source-shipped skills" in error for error in source_errors))
        self.assertEqual([], installed_errors)

    def test_autoresearch_mode_is_valid_for_behavioral_evals(self) -> None:
        self.assertIn("autoresearch", validate_kit.VALID_CASE_MODES)

    def test_policy_allows_task_scoped_local_git_but_gates_remote_git(self) -> None:
        for filename in ("capability-policy.yaml", "capability-policy.template.yaml"):
            policy = json.loads(
                (ROOT / ".agent-system" / "policy" / filename).read_text(encoding="utf-8")
            )
            allowed = {item["id"]: item["scope"] for item in policy["actions"]["allowed"]}
            gated = {
                item["id"]: item["scope"]
                for item in policy["actions"]["approval_required"]
            }
            self.assertIn("task_scoped_local_git", allowed)
            self.assertIn("local", allowed["task_scoped_local_git"].lower())
            self.assertIn("git_remote_change", gated)
            self.assertNotIn("commit", gated["git_remote_change"].lower())

    def test_installed_project_rejects_modified_core_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            skill = target / ".agents" / "skills" / "execute-dsml-task" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nmodified\n", encoding="utf-8")

            errors = validate_kit.validate_installed_project(target)

        self.assertTrue(any("manifest hash mismatch" in error for error in errors))

    def test_overlay_rejects_broken_runtime_link_with_consistent_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "overlay"
            self.build_overlay(target)
            relative = ".agents/skills/execute-dsml-task/SKILL.md"
            skill = target / relative
            skill.write_text(
                skill.read_text(encoding="utf-8")
                + "\n[Missing runtime reference](references/missing.md)\n",
                encoding="utf-8",
            )
            manifest_path = target / ".agent-system" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][relative] = hashlib.sha256(skill.read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            errors = validate_kit.validate_overlay(target)

        self.assertTrue(any("broken local link" in error for error in errors))

    def test_overlay_build_refuses_output_inside_source_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "kit"
            shutil.copytree(ROOT, copy)
            script = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tooling/build-overlay.py",
                    "--output",
                    str(copy / "deploy" / "overlay"),
                ],
                cwd=copy,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertNotEqual(0, script.returncode)

    def test_source_validation_checks_project_configuration_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "kit"
            shutil.copytree(ROOT, copy)
            path = copy / ".agent-system" / "project.template.yaml"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["duplicated_manifest_fact"] = "3.12"
            path.write_text(json.dumps(document), encoding="utf-8")

            errors = validate_kit.validate_repository(copy)

        self.assertTrue(any("unexpected property 'duplicated_manifest_fact'" in error for error in errors))

    def test_source_validation_detects_distribution_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "kit"
            shutil.copytree(ROOT, copy)
            skill = copy / ".agents" / "skills" / "execute-dsml-task" / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8") + "\nA maintained runtime clarification.\n",
                encoding="utf-8",
            )

            errors = validate_kit.validate_repository(copy)

        self.assertTrue(any("distribution drift" in error for error in errors))

    def test_run_schema_rejects_missing_required_sections(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        errors = validate_kit.schema_errors({"schema_version": "0.1"}, schema)
        self.assertTrue(any("missing required property 'task'" in item for item in errors))
        self.assertTrue(any("missing required property 'execution'" in item for item in errors))

    def test_run_schema_accepts_optional_autoresearch_experiment_summary(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["results"]["experiment_summary"] = {
            "budget": 12,
            "experiments_run": 10,
            "kept": 2,
            "discarded": 6,
            "crashed": 1,
            "invalid": 1,
            "stopping_reason": "plateau",
            "selected_revision": "abc123",
            "journal_ref": "experiments.tsv",
        }

        self.assertEqual([], validate_kit.schema_errors(instance, schema))

    def test_autoresearch_finalization_requires_canonical_sibling_evidence(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["results"]["experiment_summary"] = {
            "budget": 2,
            "experiments_run": 2,
            "kept": 1,
            "discarded": 1,
            "crashed": 0,
            "invalid": 0,
            "stopping_reason": "budget",
            "selected_revision": "abc123",
            "journal_ref": "experiments.tsv",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / ".agent-system" / "runs" / "canonical-run"
            run_dir.mkdir(parents=True)
            run_path = run_dir / "run.yaml"
            run_path.write_text(json.dumps(instance), encoding="utf-8")

            errors = validate_kit.autoresearch_evidence_errors(instance, run_path, root)
            self.assertTrue(any("learning.yaml" in error for error in errors), errors)
            self.assertTrue(any("experiments.tsv" in error for error in errors), errors)

            (run_dir / "learning.yaml").write_text("{}\n", encoding="utf-8")
            (run_dir / "experiments.tsv").write_text(
                "experiment\trevision\tprimary_metric\tguardrails\tstatus\tdescription\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [], validate_kit.autoresearch_evidence_errors(instance, run_path, root)
            )

            instance["results"]["experiment_summary"]["journal_ref"] = "other.tsv"
            errors = validate_kit.autoresearch_evidence_errors(instance, run_path, root)
            self.assertTrue(any("journal_ref must be 'experiments.tsv'" in error for error in errors))

    def test_normal_run_template_remains_valid_without_experiment_summary(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn("experiment_summary", instance["results"])
        self.assertEqual([], validate_kit.schema_errors(instance, schema))

    def test_run_schema_accepts_historical_working_tree_description(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["provenance"]["repository"]["working_tree"] = (
            "Record the inspected state when available."
        )

        self.assertEqual([], validate_kit.schema_errors(instance, schema))

    def test_learning_schema_accepts_sparse_and_scoped_signals(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], validate_kit.schema_errors(instance, schema))

        instance["request"] = {
            "kind": "project-analysis",
            "topics": ["architecture", "model-evaluation"],
            "deliverable": "technical-report",
        }
        instance["routing"] = {
            "skill": "analyze-dsml-project",
            "mode": "technical-report",
            "initial_skill": None,
            "initial_mode": "deep-audit",
            "corrected": True,
        }
        instance["signals"] = [
            {
                "type": "routing_failure",
                "scope": "kit",
                "importance": "high",
                "summary": "A generic PDF report was initially routed to deep-audit.",
                "suggested_change": "Load the skill contract before selecting the mode.",
            },
            {
                "type": "workflow_gap",
                "scope": "project",
                "importance": "low",
                "summary": "A project-local report handoff step was undocumented.",
            },
        ]
        self.assertEqual([], validate_kit.schema_errors(instance, schema))

    def test_observed_learning_examples_are_compact_and_schema_valid(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fixture_document = json.loads(
            (ROOT / "evals" / "fixtures" / "synthetic-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        fixtures = {item["id"]: item for item in fixture_document["fixtures"]}
        records = {}
        for fixture_id in (
            "learning-onboarding-zone-identifier",
            "learning-pdf-technical-report-routing",
            "learning-report-rework-outcome",
        ):
            files = fixtures[fixture_id]["repository"]["files"]
            content = next(
                value for path, value in files.items() if path.endswith("/learning.yaml")
            )
            record = json.loads(content)
            self.assertEqual([], validate_kit.schema_errors(record, schema))
            self.assertNotIn("metrics", record)
            records[fixture_id] = record

        onboarding = records["learning-onboarding-zone-identifier"]
        self.assertEqual("tooling_failure", onboarding["signals"][0]["type"])
        self.assertEqual("kit", onboarding["signals"][0]["scope"])
        pdf = records["learning-pdf-technical-report-routing"]
        self.assertEqual("deep-audit", pdf["routing"]["initial_mode"])
        self.assertEqual("technical-report", pdf["routing"]["mode"])
        self.assertTrue(pdf["routing"]["corrected"])
        rework = records["learning-report-rework-outcome"]
        self.assertEqual("completed", rework["outcome"]["execution"])
        self.assertEqual("rework_required", rework["outcome"]["user_outcome"])
        self.assertEqual(
            {"project", "kit"}, {signal["scope"] for signal in rework["signals"]}
        )

    def test_learning_v03_separates_execution_and_user_outcome_and_mixes_scopes(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["outcome"] = {
            "execution": "completed",
            "user_outcome": "rework_required",
            "reason_tags": ["report_structure", "synthesis_quality"],
        }
        instance["signals"] = [
            {
                "type": "evaluation_correctness",
                "scope": "project",
                "importance": "high",
                "summary": "The project forecast evaluation leaks future observations.",
                "suggested_change": "Correct the project evaluation split.",
                "evidence_ref": ".agent-system/runs/task-id/run.yaml#findings",
            },
            {
                "type": "validation_gap",
                "scope": "kit",
                "importance": "high",
                "summary": "Artifact checks passed without detecting weak report synthesis.",
                "suggested_change": "Add structural and semantic report acceptance checks.",
                "evidence_ref": ".agent-system/runs/task-id/run.yaml#user-feedback",
            },
        ]

        self.assertEqual([], validate_kit.schema_errors(instance, schema))
        self.assertEqual({"project", "kit"}, {signal["scope"] for signal in instance["signals"]})
        self.assertEqual("completed", instance["outcome"]["execution"])
        self.assertEqual("rework_required", instance["outcome"]["user_outcome"])

    def test_learning_v03_allows_project_only_and_clean_outcomes(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        template = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        project_only = json.loads(json.dumps(template))
        project_only["outcome"] = {
            "execution": "completed",
            "user_outcome": "accepted",
            "reason_tags": [],
        }
        project_only["signals"] = [
            {
                "type": "evaluation_correctness",
                "scope": "project",
                "importance": "high",
                "summary": "The project evaluation uses an invalid temporal split.",
                "suggested_change": "Correct the project evaluation split.",
                "evidence_ref": ".agent-system/runs/task-id/run.yaml#findings",
            }
        ]
        clean = json.loads(json.dumps(template))
        clean["outcome"] = {
            "execution": "completed",
            "user_outcome": "accepted",
            "reason_tags": [],
        }

        self.assertEqual([], validate_kit.schema_errors(project_only, schema))
        self.assertEqual(["project"], [signal["scope"] for signal in project_only["signals"]])
        self.assertEqual([], validate_kit.schema_errors(clean, schema))
        self.assertEqual([], clean["signals"])

    def test_learning_v03_limits_compact_actionable_signals(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        signal = {
            "type": "validation_gap",
            "scope": "kit",
            "importance": "high",
            "summary": "Validation missed a meaningful output-quality failure.",
            "suggested_change": "Add a semantic acceptance check.",
            "evidence_ref": ".agent-system/runs/task-id/run.yaml#validation",
        }
        instance["signals"] = [dict(signal) for _ in range(4)]
        errors = validate_kit.learning_semantic_errors(instance, ROOT / "learning.yaml", ROOT)
        self.assertTrue(any("at most 3" in item for item in errors), errors)

        instance["signals"] = [dict(signal)]
        del instance["signals"][0]["evidence_ref"]
        errors = validate_kit.learning_semantic_errors(instance, ROOT / "learning.yaml", ROOT)
        self.assertTrue(any("missing actionable fields" in item for item in errors), errors)

        instance["signals"] = []
        del instance["outcome"]
        errors = validate_kit.learning_semantic_errors(instance, ROOT / "learning.yaml", ROOT)
        self.assertTrue(any("outcome is missing" in item for item in errors), errors)

        self.assertNotIn("execution", instance)
        self.assertNotIn("results", instance)

    def test_learning_schema_rejects_project_metrics(self) -> None:
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "learning.schema.json").read_text(
                encoding="utf-8"
            )
        )
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["metrics"] = [{"name": "accuracy", "value": 0.9}]
        errors = validate_kit.schema_errors(instance, schema)
        self.assertTrue(any("unexpected property 'metrics'" in item for item in errors))

    def test_learning_validation_accepts_historical_run_without_learning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(
                ROOT / ".agent-system" / "schemas",
                root / ".agent-system" / "schemas",
            )
            shutil.copytree(
                ROOT / ".agent-system" / "templates",
                root / ".agent-system" / "templates",
            )
            historical = root / ".agent-system" / "runs" / "historical" / "run.yaml"
            historical.parent.mkdir(parents=True)
            shutil.copyfile(
                ROOT / ".agent-system" / "templates" / "run.template.yaml",
                historical,
            )

            errors = validate_kit.validate_learning_contract(root)

        self.assertEqual([], errors)

    def test_learning_signal_evidence_ref_is_optional_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agent-system" / "schemas", root / ".agent-system" / "schemas")
            shutil.copytree(ROOT / ".agent-system" / "templates", root / ".agent-system" / "templates")
            run_dir = root / ".agent-system" / "runs" / "evidence-pointer" / "run.yaml"
            run_dir.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / ".agent-system" / "templates" / "run.template.yaml", run_dir)
            learning = json.loads(
                (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                    encoding="utf-8"
                )
            )
            learning["schema_version"] = "0.2"
            learning["run_ref"] = ".agent-system/runs/evidence-pointer/run.yaml"
            learning["signals"] = [
                {
                    "type": "release_integrity_problem",
                    "scope": "kit",
                    "importance": "high",
                    "summary": "Overlay contents did not match the immutable manifest.",
                }
            ]
            learning_path = run_dir.parent / "learning.yaml"
            learning_path.write_text(json.dumps(learning) + "\n", encoding="utf-8")
            self.assertEqual([], validate_kit.validate_learning_contract(root))

            learning["signals"][0]["evidence_ref"] = (
                ".agent-system/runs/evidence-pointer/run.yaml#validation"
            )
            learning_path.write_text(json.dumps(learning) + "\n", encoding="utf-8")
            self.assertEqual([], validate_kit.validate_learning_contract(root))

            learning["signals"][0]["evidence_ref"] = ".agent-system/runs/missing/run.yaml"
            learning_path.write_text(json.dumps(learning) + "\n", encoding="utf-8")
            errors = validate_kit.validate_learning_contract(root)
            self.assertTrue(
                any("evidence_ref must point to its existing sibling run_ref" in error for error in errors)
            )

            learning["signals"][0]["evidence_ref"] = "/etc/passwd"
            learning_path.write_text(json.dumps(learning) + "\n", encoding="utf-8")
            errors = validate_kit.validate_learning_contract(root)
            self.assertTrue(
                any("evidence_ref must point to its existing sibling run_ref" in error for error in errors)
            )

            learning["signals"][0]["evidence_ref"] = ".agent-system/templates/run.template.yaml"
            learning_path.write_text(json.dumps(learning) + "\n", encoding="utf-8")
            errors = validate_kit.validate_learning_contract(root)
            self.assertTrue(
                any("evidence_ref must point to its existing sibling run_ref" in error for error in errors)
            )

    def test_learning_routing_accepts_skill_only_correction(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["routing"] = {
            "skill": "analyze-dsml-project",
            "mode": "orientation",
            "initial_skill": "execute-dsml-task",
            "initial_mode": None,
            "corrected": True,
        }
        errors = validate_kit.learning_semantic_errors(instance, ROOT / "learning.yaml", ROOT)
        self.assertFalse(any("routing" in error for error in errors), errors)

    def test_learning_rejects_impossible_timestamp(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "learning.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["timestamp"] = "2026-02-31"
        errors = validate_kit.learning_semantic_errors(instance, ROOT / "learning.yaml", ROOT)
        self.assertTrue(any("timestamp must be a real YYYY-MM-DD date" in error for error in errors))

    def test_run_record_admits_operation_type_for_non_reproducible_steps(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["execution"]["commands"] = [
            {
                "id": "ad-hoc-review",
                "type": "operation",
                "description": "Parsed aggregate CSV outputs to verify reported totals.",
                "capability": "safe_local_validation",
                "status": "succeeded",
                "exit_code": None,
                "evidence_ref": "terminal:ad-hoc-review",
            }
        ]
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], validate_kit.schema_errors(instance, schema))
        errors = [
            error
            for error in validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
            if "policy_ref" not in error
        ]
        self.assertEqual([], errors)

    def test_run_rejects_operation_type_without_description(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["execution"]["commands"] = [
            {
                "id": "bad-op",
                "type": "operation",
                "capability": "safe_local_validation",
                "status": "succeeded",
                "exit_code": 0,
                "evidence_ref": "terminal:bad-op",
            }
        ]
        errors = [
            error
            for error in validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
            if "policy_ref" not in error
        ]
        self.assertTrue(any("needs non-empty description text" in error for error in errors))

    def test_run_rejects_operation_with_synthetic_exit_code(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["execution"]["commands"] = [
            {
                "id": "bad-op-exit",
                "type": "operation",
                "description": "Reviewed the synthetic artifact.",
                "capability": "safe_local_validation",
                "status": "succeeded",
                "exit_code": 0,
                "evidence_ref": "artifact:review",
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("operation 'bad-op-exit' requires a null exit_code" in error for error in errors))

    def test_run_rejects_mixed_command_and_operation_fields(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["execution"]["commands"] = [
            {
                "id": "mixed-op",
                "type": "operation",
                "command": "pretend-review",
                "description": "Reviewed the synthetic artifact.",
                "capability": "safe_local_validation",
                "status": "succeeded",
                "exit_code": None,
                "evidence_ref": "artifact:review",
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("operation 'mixed-op' must not record command text" in error for error in errors))

    def test_run_decision_supports_not_applicable_for_analysis_tasks(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(
                encoding="utf-8"
            )
        )
        instance["results"]["decision"] = "not_applicable"
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], validate_kit.schema_errors(instance, schema))

    def test_create_run_initializes_run_and_learning_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self.build_overlay(target)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(target / ".agent-system" / "tooling" / "create-run.py"),
                    "--project-root",
                    str(target),
                    "--id",
                    "pdf-routing",
                    "--goal",
                    "Produce a synthetic technical audit.",
                    "--acceptance",
                    "Both records are initialized.",
                    "--request-kind",
                    "project_research",
                    "--skill",
                    "analyze-dsml-project",
                    "--mode",
                    "deep-audit",
                    "--initial-skill",
                    "execute-dsml-task",
                    "--initial-mode",
                    "orientation",
                    "--topic",
                    "model_evaluation",
                    "--deliverable",
                    "pdf",
                ],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            run_path = target / ".agent-system" / "runs" / "pdf-routing" / "run.yaml"
            learning_path = run_path.with_name("learning.yaml")
            learning = json.loads(learning_path.read_text(encoding="utf-8"))
            run_exists = run_path.is_file()
            learning_exists = learning_path.is_file()
            target_version = (
                target / ".agent-system" / "VERSION"
            ).read_text(encoding="utf-8").strip()

            errors = validate_kit.validate_installed_project(target)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(run_exists)
        self.assertTrue(learning_exists)
        self.assertEqual("analyze-dsml-project", learning["routing"]["skill"])
        self.assertEqual("execute-dsml-task", learning["routing"]["initial_skill"])
        self.assertEqual("deep-audit", learning["routing"]["mode"])
        self.assertEqual("orientation", learning["routing"]["initial_mode"])
        self.assertTrue(learning["routing"]["corrected"])
        self.assertEqual([], learning["signals"])
        self.assertEqual(
            {"execution": "not_run", "user_outcome": "unknown", "reason_tags": []},
            learning["outcome"],
        )
        self.assertEqual("0.4", learning["schema_version"])
        self.assertEqual(
            "Not assessed until run finalization.",
            learning["no_reusable_signal_reason"],
        )
        self.assertEqual(date.today().isoformat(), learning["timestamp"])
        self.assertEqual(target_version, learning["toolkit_version"])
        self.assertEqual([], errors)

    def test_broken_local_link_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("[missing](docs/missing.md)\n", encoding="utf-8")
            errors = validate_kit.validate_markdown_links(root)
        self.assertEqual(["README.md: broken local link docs/missing.md"], errors)

    def test_frontmatter_parser_preserves_full_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SKILL.md"
            path.write_text(
                "---\nname: sample\ndescription: " + "x" * 61 + ".\n---\n# Body\n",
                encoding="utf-8",
            )
            values, errors = validate_kit.parse_frontmatter(path)
        self.assertEqual([], errors)
        self.assertGreater(len(values["description"]), 60)

    def test_skill_validator_accepts_informative_description_over_sixty_chars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            path = root / ".agents" / "skills" / "analyze-dsml-project" / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "description: Map existing DS/ML/AML projects from repository evidence.",
                "description: Inspect existing DS/ML/AML projects for onboarding and analysis, not implementation or independent validation.",
            )
            path.write_text(text, encoding="utf-8")
            errors = validate_kit.validate_skills(root)
        self.assertEqual([], errors)

    def test_installed_skill_validation_allows_compatible_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            extension = root / ".agents" / "skills" / "forecasting" / "SKILL.md"
            extension.parent.mkdir(parents=True)
            extension.write_text(
                "---\n"
                "name: forecasting\n"
                "description: Forecast time series with project-specific backtesting.\n"
                "---\n"
                "# Forecasting\n\nUse only for project forecasting requests.\n",
                encoding="utf-8",
            )

            errors = validate_kit.validate_skills(root, require_exact_core=False)

        self.assertEqual([], errors)

    def test_installed_skill_accepts_folded_discovery_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            extension = root / ".agents" / "skills" / "forecasting" / "SKILL.md"
            extension.parent.mkdir(parents=True)
            extension.write_text(
                "---\n"
                "name: forecasting\n"
                "description: >\n"
                "  Forecast time series with project-specific rolling-origin\n"
                "  backtesting and evaluation.\n"
                "---\n"
                "# Forecasting\n\nUse for recurring project forecasting requests.\n",
                encoding="utf-8",
            )

            errors = validate_kit.validate_skills(root, require_exact_core=False)

        self.assertEqual([], errors)

    def test_installed_skill_allows_project_style_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            extension = root / ".agents" / "skills" / "vision-checker" / "SKILL.md"
            extension.parent.mkdir(parents=True)
            extension.write_text(
                "---\n"
                "name: vision-checker\n"
                "description: Verify synthetic vision outputs for this project's pipeline\n"
                "custom-harness-key: allowed-for-project-skills\n"
                "---\n"
                "# Vision checker\n\nProject-specific validation workflow.\n",
                encoding="utf-8",
            )

            errors = validate_kit.validate_skills(root, require_exact_core=False)

        self.assertEqual([], errors)

    def test_core_skill_validator_rejects_generic_discovery_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            path = root / ".agents" / "skills" / "validate-dsml-result" / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            text = re.sub(
                r"(?m)^description: .+$",
                "description: Help with data science and machine learning work when useful.",
                text,
                count=1,
            )
            path.write_text(text, encoding="utf-8")

            errors = validate_kit.validate_skills(root)

        self.assertTrue(any("discovery description lacks" in error for error in errors))

    def test_source_validation_rejects_core_version_mismatch(self) -> None:
        current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            shutil.copyfile(ROOT / "VERSION", root / "VERSION")
            path = root / ".agents" / "skills" / "execute-dsml-task" / "SKILL.md"
            text = path.read_text(encoding="utf-8").replace(
                f'version: "{current_version}"', 'version: "0.1.0"', 1
            )
            path.write_text(text, encoding="utf-8")

            errors = validate_kit.validate_version(root)

        self.assertTrue(any("does not match VERSION" in error for error in errors))

    def test_source_validation_rejects_learning_template_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            shutil.copytree(
                ROOT / ".agent-system" / "templates",
                root / ".agent-system" / "templates",
            )
            shutil.copyfile(ROOT / "VERSION", root / "VERSION")
            path = root / ".agent-system" / "templates" / "learning.template.yaml"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["toolkit_version"] = "0.1.0"
            path.write_text(json.dumps(document), encoding="utf-8")

            errors = validate_kit.validate_version(root)

        self.assertTrue(any("toolkit_version '0.1.0'" in error for error in errors))

    def test_schema_subset_rejects_silently_ignored_keyword(self) -> None:
        errors = validate_kit.schema_definition_errors(
            {"type": "string", "oneOf": [{"type": "string"}]}
        )
        self.assertEqual(["$: unsupported JSON Schema keyword 'oneOf'"], errors)

    def test_schema_subset_rejects_malformed_supported_keyword(self) -> None:
        errors = validate_kit.schema_definition_errors(
            {"type": "object", "additionalProperties": "false"}
        )
        self.assertEqual(["$: 'additionalProperties' must be boolean or a mapping"], errors)

    def test_json_loader_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"value": 1, "value": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                validate_kit.load_json(path)

    def test_required_behavioral_coverage_is_complete(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        actual = {tag for case in document["cases"] for tag in case["coverage_tags"]}
        self.assertTrue(validate_kit.REQUIRED_COVERAGE.issubset(actual))

    def test_v02_behavioral_coverage_is_present(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        actual = {tag for case in document["cases"] for tag in case["coverage_tags"]}
        expected = {
            "project_specific_skill",
            "routing_correction_signal",
            "valid_rejection_empty_signals",
            "authorized_dev_training",
            "organization_policy_conflict",
            "exploration_before_candidate_evaluation",
        }
        self.assertTrue(expected.issubset(actual), expected - actual)

    def test_v021_onboarding_behavioral_coverage_is_present(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        actual = {tag for case in document["cases"] for tag in case["coverage_tags"]}
        expected = {
            "onboarding_trigger",
            "onboarding_low_ceremony",
            "onboarding_optional_unknowns",
            "onboarding_permission_ambiguity",
            "onboarding_no_self_modification",
            "onboarding_recheck",
        }
        self.assertTrue(expected.issubset(actual), expected - actual)

    def test_v03_learning_signal_behavioral_coverage_is_present(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        actual = {tag for case in document["cases"] for tag in case["coverage_tags"]}
        expected = {
            "empty_learning_signals",
            "recurring_request_metadata",
            "scope_separation",
            "learning_metric_separation",
            "learning_signal_sanitization",
            "learning_signal_review",
            "auxiliary_learning_write_isolation",
        }
        self.assertTrue(expected.issubset(actual), expected - actual)

    def test_v03_learning_signal_cases_assert_named_behavior(self) -> None:
        cases_document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        cases = {case["id"]: case for case in cases_document["cases"]}
        fixtures_document = json.loads(
            (ROOT / "evals" / "fixtures" / "synthetic-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        fixtures = {fixture["id"]: fixture for fixture in fixtures_document["fixtures"]}

        rejection = json.dumps(cases["no-change-failed-experiment"]).lower()
        failure = json.dumps(cases["pathological-feedback-after-routing-correction"]).lower()
        recurring = json.dumps(cases["positive-learning-signal-review"]).lower()
        auxiliary = json.dumps(cases["pathological-auxiliary-learning-write-failure"]).lower()

        self.assertIn("signals empty", rejection)
        self.assertIn("routing_failure", failure)
        self.assertIn("learning.yaml", failure)
        self.assertIn("without writing", recurring)
        recurring_files = fixtures["recurring-regression-workflow"]["repository"]["files"]
        self.assertTrue(recurring_files)
        self.assertIn(".agent-system/local/request-patterns.yaml", recurring_files)
        self.assertEqual(
            3,
            sum(path.endswith("/learning.yaml") for path in recurring_files),
        )
        self.assertIn("primary", auxiliary)
        self.assertIn("downgrade", auxiliary)

    def test_natural_language_routing_contract_and_cases(self) -> None:
        runtime = (
            ROOT / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        control = (ROOT / ".agent-system" / "CONTROL.md").read_text(encoding="utf-8")
        system = (ROOT / ".agent-system" / "SYSTEM.md").read_text(encoding="utf-8")
        report_workflow = (
            ROOT / ".agent-system" / "workflows" / "technical-report.md"
        ).read_text(encoding="utf-8")
        analysis_skill = (
            ROOT / ".agents" / "skills" / "analyze-dsml-project" / "SKILL.md"
        ).read_text(encoding="utf-8")
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(
                encoding="utf-8"
            )
        )
        cases = {case["id"]: case for case in document["cases"]}

        self.assertIn(".agent-system/CONTROL.md", runtime)
        self.assertIn(".agent-system/SYSTEM.md", runtime)
        self.assertIn(".agent-system/workflows/", runtime)
        self.assertIn("every other request as normal agent work", runtime)
        self.assertIn("substantial work that depends on repository contents", runtime)
        self.assertIn("git_preflight.py", runtime)
        self.assertIn("--sync-mode", runtime)
        self.assertIn("Do not ask whether to use Git", runtime)
        self.assertIn("authentication", runtime)
        self.assertIn("Markdown and PDF are output formats", analysis_skill)
        self.assertIn("explicit audit request selects `deep-audit`", analysis_skill)

        self.assertLessEqual(len(control.splitlines()), 180)
        for heading in (
            "## Start here",
            "## Workflow controls",
            "## Copy/paste examples",
        ):
            self.assertIn(heading, control)
        for operation in (
            "Create a technical PDF report",
            "Run autoresearch",
            "Independently validate this result",
            "Fix this data preprocessing bug",
        ):
            self.assertIn(operation, control)
        self.assertNotIn("Set up this repo", control)
        self.assertNotIn("Set up the DS/ML Agent Kit", control)
        self.assertNotIn("## Repair and upgrade", control)
        self.assertNotIn("Upgrade the DS/ML Agent Kit", control)
        self.assertNotIn("--repair-runtime", control)
        self.assertNotIn("--upgrade-from", control)
        self.assertIn("### Independent validation example", control)
        self.assertIn("### Ordinary bug-fix example", control)
        self.assertNotIn("This is a separate follow-up", control)
        self.assertNotIn("This unrelated example", control)
        self.assertIn("Need more detail? See [`SYSTEM.md`](SYSTEM.md).", control)
        self.assertIn("## Routing precedence", system)
        self.assertIn("Everything else remains normal agent work", system)

        expected_routes = {
            "routing-natural-language-pdf-research": ("analyze-dsml-project", "technical-report"),
            "routing-natural-language-bounded-understanding": ("analyze-dsml-project", "orientation"),
            "routing-natural-language-diagnosis": ("execute-dsml-task", "diagnose"),
            "routing-natural-language-development": ("execute-dsml-task", "develop"),
            "routing-natural-language-validation": ("validate-dsml-result", "review"),
            "ordinary-preprocessing-bug": ("execute-dsml-task", "diagnose"),
            "technical-report-iterations-override": ("analyze-dsml-project", "technical-report"),
        }
        for case_id, (skill, mode) in expected_routes.items():
            case = cases[case_id]
            self.assertEqual(skill, case["expected"]["primary_skill"])
            self.assertEqual(mode, case["expected"]["mode"])

        ordinary = json.dumps(cases["ordinary-preprocessing-bug"]).lower()
        self.assertIn("or run record", ordinary)
        override = json.dumps(cases["technical-report-iterations-override"]).lower()
        self.assertIn("four report versions", override)
        self.assertIn("`iterations=N` | Profile default: quick 1, standard 2, publication 3", report_workflow)
        self.assertIn("Version 2 is always a content-depth", report_workflow)
        self.assertIn("visual QA occurs after content iterations", report_workflow)
        self.assertIn("Explicit controls override profile defaults", report_workflow)
        self.assertFalse((ROOT / ".agent-system" / "docs" / "DSML_AGENT_KIT.md").exists())
        self.assertFalse((ROOT / ".agent-system" / "docs" / "HOW_TO_USE_DSML_AGENT.md").exists())

    def test_git_commit_and_finalization_conventions(self) -> None:
        runtime = (
            ROOT / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        system = (ROOT / ".agent-system" / "SYSTEM.md").read_text(encoding="utf-8")
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(
                encoding="utf-8"
            )
        )
        fixtures_document = json.loads(
            (ROOT / "evals" / "fixtures" / "synthetic-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        cases = {case["id"]: case for case in document["cases"]}
        fixtures = {fixture["id"]: fixture for fixture in fixtures_document["fixtures"]}

        self.assertEqual("0.14.0", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        for text in (runtime, system):
            self.assertIn("Conventional Commits", text)
            self.assertIn("feat(scope):", text)
            self.assertIn("fix(scope):", text)
            self.assertIn("refactor(scope):", text)
            self.assertIn("test(scope):", text)
            self.assertIn("docs(scope):", text)
            self.assertIn("chore(scope):", text)
            self.assertIn("one logical change per commit", text)
            self.assertIn("actual logical change", text)
            self.assertIn("git_preflight.py", text)
            self.assertIn("generated, cache, or temporary files", text)
            self.assertIn("repository-required generated outputs", text)
            self.assertIn("Push only when", text)
            self.assertIn("unrelated user changes", text)

        expected = {
            "git-finalize-feature": ("feat(inference): add batch prediction support", "git_commit_feat"),
            "git-finalize-bug-fix": ("fix(features): prevent target leakage in lag features", "git_commit_fix"),
            "git-finalize-refactor": ("refactor(training): separate tuning from final fit", "git_commit_refactor"),
            "git-finalize-docs": ("docs: update project setup", "git_commit_docs"),
            "git-finalize-no-repository": ("continue normally without creating a repository", "git_no_repository"),
            "git-finalize-no-push-authorization": ("must not push", "git_no_push_authorization"),
            "git-finalize-dirty-unrelated-changes": ("exclude unrelated user changes", "git_dirty_worktree_protection"),
        }
        for case_id, (required_text, coverage_tag) in expected.items():
            case = cases[case_id]
            serialized = json.dumps(case).lower()
            self.assertIn(required_text.lower(), serialized)
            self.assertIn(coverage_tag, case["coverage_tags"])

        self.assertEqual(
            ["git-non-repository"],
            cases["git-finalize-no-repository"]["fixture_ids"],
        )
        self.assertIn(
            "fixture://git-non-repository/raw_evidence/0",
            cases["git-finalize-no-repository"]["raw_evidence_refs"],
        )
        self.assertIn(
            "push",
            json.dumps(cases["git-finalize-no-push-authorization"]["forbidden_actions"]).lower(),
        )
        self.assertIn(
            "git add -a",
            json.dumps(cases["git-finalize-dirty-unrelated-changes"]["forbidden_actions"]).lower(),
        )
        feature_case = json.dumps(cases["git-finalize-feature"]).lower()
        self.assertIn("incidental generated/cache/temp", feature_case)
        self.assertIn("repository-required generated outputs", feature_case)

        semantic_fixtures = {
            "git-finalize-feature": (
                "git-feature-missing-batch",
                "supports only one prediction record",
            ),
            "git-finalize-bug-fix": (
                "git-lag-leakage-bug",
                "shift(0)",
            ),
            "git-finalize-refactor": (
                "git-training-refactor",
                "tuning and final fit are coupled",
            ),
        }
        for case_id, (fixture_id, marker) in semantic_fixtures.items():
            self.assertEqual([fixture_id], cases[case_id]["fixture_ids"])
            self.assertIn(marker, json.dumps(fixtures[fixture_id]).lower())

    def test_structural_change_discipline_contract_and_cases(self) -> None:
        runtime = (
            ROOT / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        system = (ROOT / ".agent-system" / "SYSTEM.md").read_text(encoding="utf-8")
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(
                encoding="utf-8"
            )
        )
        fixtures_document = json.loads(
            (ROOT / "evals" / "fixtures" / "synthetic-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        cases = {case["id"]: case for case in document["cases"]}
        fixtures = {fixture["id"]: fixture for fixture in fixtures_document["fixtures"]}

        self.assertEqual("0.14.0", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        for text in (runtime, system):
            self.assertIn("Structural Change Discipline", text)
            self.assertIn("canonical new paths", text)
            self.assertIn("legacy paths", text)
            self.assertIn("compatibility", text)
            self.assertIn("behavioral parity", text)
            self.assertIn("Git worktree", text)
            self.assertIn("normal feature", text)
            self.assertIn("migrated and removed", text)
            self.assertIn("retained as canonical", text)
            self.assertIn("compatibility shim", text)
            self.assertIn("deprecated and documented", text)
            self.assertIn("non-Git", text)
            self.assertIn("only when isolation", text)
            self.assertIn("temporary execution and review isolation", text)
            self.assertIn("both appear canonical", text)

        self.assertIn("<!-- DS/ML Agent Kit:BEGIN managed -->", runtime)
        self.assertIn("<!-- DS/ML Agent Kit:END managed -->", runtime)

        refactor_case = cases["structural-refactor-clean-end-state"]
        self.assertEqual(["structural-script-heavy-project"], refactor_case["fixture_ids"])
        self.assertIn("structural_change_large_refactor", refactor_case["coverage_tags"])
        self.assertIn("structural_worktree_finalization", refactor_case["coverage_tags"])
        serialized_refactor = json.dumps(refactor_case).lower()
        for marker in (
            "intended end-state",
            "isolated git worktree",
            "duplicate test directories",
            "canonical execution path",
            "legacy paths",
            "parity",
            "repository-level completion pass",
            "project_map.md",
            "compatibility shim",
            ".gitignore",
            "name the branch",
            "temporary worktree",
            "canonical branch",
            "never silently merge or delete",
        ):
            self.assertIn(marker, serialized_refactor)
        fixture_text = json.dumps(fixtures["structural-script-heavy-project"]).lower()
        self.assertIn("training.py", fixture_text)
        self.assertIn("test/test_training.py", fixture_text)
        self.assertIn("git worktree is practical", fixture_text)
        self.assertIn("external scheduler", fixture_text)
        self.assertIn("__pycache__", fixture_text)
        self.assertIn("debug-forecast-output.json", fixture_text)
        self.assertIn("stale map", fixture_text)

        for text in (runtime, system):
            self.assertIn("repository-level", text)
            self.assertIn("duplicate concepts", text)
            self.assertIn("root-level", text)
            self.assertIn(".gitignore", text)
            self.assertIn("PROJECT_MAP.md", text)
            self.assertIn("major directories", text)
            self.assertIn("core entry points", text)
            self.assertIn("trivial edits", text)
            self.assertIn("AGENTS.md", text)
            self.assertIn("change log", text)

        small_case = cases["structural-discipline-normal-feature-negative"]
        self.assertEqual(["structural-normal-feature-project"], small_case["fixture_ids"])
        self.assertIn("structural_change_small_edit_negative", small_case["coverage_tags"])
        serialized_small = json.dumps(small_case).lower()
        self.assertIn("ordinary edit", serialized_small)
        self.assertIn("must not create a worktree", serialized_small)
        self.assertIn("staging directories", serialized_small)
        self.assertIn("do not churn project_map.md", serialized_small)
        self.assertIn("trivial edit", serialized_small)
        small_fixture = json.dumps(fixtures["structural-normal-feature-project"]).lower()
        self.assertIn("current map", small_fixture)
        self.assertIn("commands remain accurate", small_fixture)
        self.assertIn("durable project guidance remains unchanged", small_fixture)


    def test_autoresearch_preflight_confirmation_contract_and_cases(self) -> None:
        skill = (
            ROOT / ".agents" / "skills" / "autoresearch" / "SKILL.md"
        ).read_text(encoding="utf-8")
        guide = (ROOT / ".agent-system" / "workflows" / "autoresearch.md").read_text(
            encoding="utf-8"
        )
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(
                encoding="utf-8"
            )
        )
        cases = {case["id"]: case for case in document["cases"]}

        for contract_field in (
            "goal",
            "selection objective",
            "direction",
            "evaluation",
            "final holdout",
            "point-in-time",
            "guardrails",
            "budget",
        ):
            self.assertIn(contract_field, skill.lower())
        self.assertIn("confirm or correct", skill)
        self.assertIn("A bare `Run autoresearch` is never pre-authorization.", skill)
        self.assertIn("explicitly authorizes immediate execution", skill)
        self.assertIn("before establishing the baseline or making candidate changes", skill)
        self.assertIn("max experiments", guide)
        self.assertIn("final holdout", guide)

        expected_cases = {
            "autoresearch-bare-preflight": "response_only",
            "autoresearch-partial-preflight": "response_only",
            "autoresearch-explicit-trigger": "response_only",
            "autoresearch-explicit-proceed-authorization": "run_record",
            "autoresearch-ambiguous-primary-metric": "response_only",
            "autoresearch-metric-role-inference": "response_only",
        }
        for case_id, artifact_class in expected_cases.items():
            case = cases[case_id]
            self.assertEqual("autoresearch", case["expected"]["primary_skill"])
            self.assertEqual(artifact_class, case["expected"]["artifact_class"])

        bare = json.dumps(cases["autoresearch-bare-preflight"]).lower()
        specified = json.dumps(cases["autoresearch-explicit-trigger"]).lower()
        proceed = json.dumps(cases["autoresearch-explicit-proceed-authorization"]).lower()
        ambiguous = json.dumps(cases["autoresearch-ambiguous-primary-metric"]).lower()
        metric_roles = json.dumps(cases["autoresearch-metric-role-inference"]).lower()
        self.assertIn("ten-experiment default budget", bare)
        self.assertIn("confirmation", bare)
        self.assertIn("without re-asking", specified)
        self.assertIn("without a redundant question", proceed)
        self.assertIn("both plausible primary metrics", ambiguous)
        self.assertIn("silently choose", ambiguous)
        self.assertIn("rmse", metric_roles)
        self.assertIn("reporting or business metric", metric_roles)
        self.assertIn("metric=fa", skill.lower())

    def test_autoresearch_crash_repair_and_larger_hypothesis_contracts(self) -> None:
        skill = (
            ROOT / ".agents" / "skills" / "autoresearch" / "SKILL.md"
        ).read_text(encoding="utf-8")
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(
                encoding="utf-8"
            )
        )
        cases = {case["id"]: case for case in document["cases"]}

        self.assertIn("up to two bounded repair attempts", skill)
        self.assertIn("without changing the experiment hypothesis", skill)
        self.assertIn("record the experiment as `crash`", skill)
        self.assertIn("Only after incremental and low-cost directions are exhausted", skill)
        self.assertIn("Do not use this as justification for unnecessary large rewrites", skill)

        repair = json.dumps(cases["autoresearch-bounded-crash-repair"]).lower()
        larger = json.dumps(
            cases["autoresearch-larger-hypothesis-after-incremental-search"]
        ).lower()
        self.assertIn("at most two bounded repair attempts", repair)
        self.assertIn("preserving the experiment hypothesis", repair)
        self.assertIn("new dependency", repair)
        self.assertIn("after simpler directions are exhausted", larger)
        self.assertIn("confirmed scope", larger)
        self.assertIn("unnecessary architectural rewrite", larger)

    def test_project_specific_skill_fixture_is_compatible(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "fixtures" / "synthetic-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        fixture = next(
            item for item in document["fixtures"] if item["id"] == "project-specific-forecasting"
        )
        content = fixture["repository"]["files"][".agents/skills/forecasting/SKILL.md"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            path = root / ".agents" / "skills" / "forecasting" / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding="utf-8")

            errors = validate_kit.validate_skills(root, require_exact_core=False)

        self.assertEqual([], errors)

    def test_adapters_remain_thin_discovery_pointers(self) -> None:
        for relative in (
            "adapters/codex/AGENTS.fragment.md",
            "adapters/copilot/copilot-instructions.fragment.md",
            "adapters/hermes/hermes-project.fragment.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(".agent-system/CONTROL.md", text, relative)
            self.assertIn(".agent-system/SYSTEM.md", text, relative)
            self.assertIn(".agent-system/workflows/", text, relative)
            self.assertIn("ordinary requests ordinary", text, relative)
            self.assertIn("project-specific skills", text.lower(), relative)

    def test_dirty_worktree_autoresearch_contract_separates_safe_isolation_and_blocking(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        cases = {case["id"]: case for case in document["cases"]}
        safe = cases["autoresearch-dirty-worktree-safe-isolation"]
        blocked = cases["autoresearch-dirty-worktree-isolation-unavailable"]

        self.assertEqual("not_applicable", safe["expected"]["verdict"])
        self.assertEqual("run_record", safe["expected"]["artifact_class"])
        self.assertIn("isolated", json.dumps(safe).lower())
        self.assertIn("untouched", json.dumps(safe).lower())
        self.assertEqual("blocked", blocked["expected"]["verdict"])
        for case in (safe, blocked):
            forbidden = json.dumps(case["forbidden_actions"]).lower()
            for operation in ("stash", "reset", "commit", "clean", "discard"):
                self.assertIn(operation, forbidden)

    def test_autoresearch_contract_keeps_durable_evidence_at_canonical_root(self) -> None:
        paths = (
            ROOT / ".agents" / "skills" / "autoresearch" / "SKILL.md",
            ROOT / ".agent-system" / "workflows" / "autoresearch.md",
            ROOT / ".agent-system" / "SYSTEM.md",
            ROOT / ".agent-system" / "docs" / "LEARNING_LOOP.md",
        )
        documents = [path.read_text(encoding="utf-8") for path in paths]
        for path, text in zip(paths, documents):
            self.assertIn("canonical", text.lower(), path)
            self.assertIn("isolated worktree", text.lower(), path)
            self.assertIn("toolkit", text.lower(), path)
        skill, workflow, _, learning_loop = documents
        for text in (skill, workflow):
            self.assertIn("--project-root", text)
            self.assertIn("canonical_project_root", text)
            self.assertIn("experiment_worktree_root", text)
            self.assertIn("toolkit_root", text)
            self.assertIn("Run evidence: .agent-system/runs/<run-id>/", text)
            self.assertIn("experiments.tsv", text)
        self.assertIn("never recompute", skill)
        self.assertIn("journal_ref", workflow)
        self.assertIn("current execution directory", learning_loop)

    def test_remote_git_actions_remain_separately_gated_in_autoresearch_case(self) -> None:
        document = json.loads(
            (ROOT / "evals" / "cases" / "behavioral-cases.json").read_text(encoding="utf-8")
        )
        case = next(
            case for case in document["cases"] if case["id"] == "autoresearch-remote-git-separation"
        )
        self.assertIn("separately gated", json.dumps(case["required_invariants"]).lower())
        self.assertIn("push", json.dumps(case["forbidden_actions"]).lower())

    def test_evals_reject_cross_fixture_evidence_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evals", root / "evals")
            path = root / "evals" / "cases" / "behavioral-cases.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["cases"][0]["raw_evidence_refs"][0] = (
                "fixture://deep-audit-repository/raw_evidence/0"
            )
            path.write_text(json.dumps(document), encoding="utf-8")
            errors = validate_kit.validate_evals(root)
        self.assertTrue(any("not declared in fixture_ids" in error for error in errors))

    def test_evals_reject_fixture_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evals", root / "evals")
            path = root / "evals" / "fixtures" / "synthetic-fixtures.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["fixtures"][0]["repository"]["files"]["../../outside.txt"] = "unsafe"
            path.write_text(json.dumps(document), encoding="utf-8")
            errors = validate_kit.validate_evals(root)
        self.assertTrue(any("unsafe repository path" in error for error in errors))

    def test_policy_rejects_removed_secret_prohibition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agent-system" / "policy"
            target.mkdir(parents=True)
            source = ROOT / ".agent-system" / "policy" / "capability-policy.template.yaml"
            document = json.loads(source.read_text(encoding="utf-8"))
            document["actions"]["forbidden"] = [
                item
                for item in document["actions"]["forbidden"]
                if item["id"] != "secret_access_or_disclosure"
            ]
            (target / source.name).write_text(json.dumps(document), encoding="utf-8")
            errors = validate_kit.validate_policy(root)
        self.assertTrue(any("secret_access_or_disclosure" in error for error in errors))

    def test_policy_rejects_string_security_collections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agent-system" / "policy"
            target.mkdir(parents=True)
            source = ROOT / ".agent-system" / "policy" / "capability-policy.template.yaml"
            document = json.loads(source.read_text(encoding="utf-8"))
            document["decision_rule"]["all_must_be_true"] = (
                "allowed_by_organization_policy authorized_for_the_current_task"
            )
            document["fallback_when_capability_absent"] = "static analysis then runbook"
            (target / source.name).write_text(json.dumps(document), encoding="utf-8")
            errors = validate_kit.validate_policy(root)
        self.assertTrue(any("all_must_be_true must be a string list" in error for error in errors))
        self.assertTrue(any("fallback must be a non-empty string list" in error for error in errors))

    def test_approved_project_policy_can_pre_authorize_bounded_recurring_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agent-system" / "policy"
            target.mkdir(parents=True)
            source = ROOT / ".agent-system" / "policy" / "capability-policy.template.yaml"
            shutil.copyfile(source, target / source.name)
            policy = json.loads(source.read_text(encoding="utf-8"))
            policy["policy_status"] = "approved_project_policy"
            policy["approval"] = {
                "authority": "synthetic project owner",
                "evidence_ref": "approval:bounded-dev-training",
            }
            action = next(
                item
                for item in policy["actions"]["approval_required"]
                if item["id"] == "costly_compute"
            )
            policy["actions"]["approval_required"].remove(action)
            action["scope"] = "Bounded recurring development training only; production remains unauthorized."
            policy["actions"]["allowed"].append(action)
            (target / "capability-policy.yaml").write_text(
                json.dumps(policy), encoding="utf-8"
            )

            errors = validate_kit.validate_policy(root)

        self.assertEqual([], errors)

    def test_run_uses_exact_active_policy_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agent-system", root / ".agent-system")
            policy_path = root / ".agent-system" / "policy" / "capability-policy.yaml"
            template_path = root / ".agent-system" / "policy" / "capability-policy.template.yaml"
            policy = json.loads(template_path.read_text(encoding="utf-8"))
            policy["policy_status"] = "approved_project_policy"
            policy["approval"] = {"authority": "policy-owner", "evidence_ref": "approval:policy"}
            safe_action = next(
                item for item in policy["actions"]["allowed"] if item["id"] == "safe_local_validation"
            )
            policy["actions"]["allowed"].remove(safe_action)
            policy["actions"]["forbidden"].append(safe_action)
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            instance = json.loads(
                (root / ".agent-system" / "templates" / "run.template.yaml").read_text(
                    encoding="utf-8"
                )
            )
            instance["policy"]["policy_ref"] = ".agent-system/policy/capability-policy.yaml"
            instance["execution"]["commands"] = [
                {
                    "id": "check",
                    "command": "python3 -B tooling/validate-kit.py",
                    "capability": "safe_local_validation",
                    "status": "succeeded",
                    "exit_code": 0,
                    "evidence_ref": "terminal:check",
                }
            ]
            run_path = root / ".agent-system" / "runs" / "probe" / "run.yaml"
            run_path.parent.mkdir(parents=True)
            errors = validate_kit.run_semantic_errors(instance, run_path, root)
            self.assertTrue(any("forbidden capability" in error for error in errors))

            policy.pop("approval")
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            policy_errors = validate_kit.validate_policy(root)
            self.assertTrue(any("non-blank approval authority" in error for error in policy_errors))

    def test_controlled_run_requires_authorization_evidence(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["task"]["mode"] = "controlled"
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("approval gate" in error for error in errors))
        self.assertTrue(any("authorization boundary" in error for error in errors))

    def test_run_rejects_denied_gate_for_attempted_costly_command(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["task"]["mode"] = "controlled"
        instance["policy"]["authorization_boundary"] = ["Only approved costly compute."]
        instance["policy"]["approval_gates"] = [
            {"action": "costly_compute", "status": "denied"}
        ]
        instance["execution"]["commands"] = [
            {
                "id": "training",
                "command": "train --full",
                "capability": "costly_compute",
                "approval_gate_ref": "costly_compute",
                "status": "succeeded",
                "exit_code": 0,
                "evidence_ref": "terminal:training",
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("requires an approved gate" in error for error in errors))

    def test_run_rejects_succeeded_command_with_nonzero_exit(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["execution"]["commands"] = [
            {
                "id": "bad-status",
                "command": "false",
                "capability": "safe_local_validation",
                "status": "succeeded",
                "exit_code": 1,
                "evidence_ref": "terminal:bad-status",
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("requires exit_code 0" in error for error in errors))

    def test_run_rejects_accept_with_null_metric(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["results"]["status"] = "partial"
        instance["results"]["decision"] = "accept"
        instance["results"]["metrics"] = [
            {
                "name": "F1",
                "population": "holdout",
                "implementation": "v1",
                "value": None,
                "baseline_value": 0.61,
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("metric or baseline values need an artifact_ref" in error for error in errors))
        self.assertTrue(any("non-null artifact-backed metric" in error for error in errors))

    def test_run_accepts_approved_gate_and_artifact_backed_metric(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["policy"]["policy_ref"] = ".agent-system/policy/capability-policy.yaml"
        instance["task"]["mode"] = "controlled"
        instance["policy"]["authorization_boundary"] = ["One approved training run."]
        instance["policy"]["approval_gates"] = [
            {
                "action": "costly_compute",
                "status": "approved",
                "authority": "authorized-owner",
                "evidence_ref": "approval:1",
            }
        ]
        instance["execution"]["commands"] = [
            {
                "id": "training",
                "command": "train --full",
                "capability": "costly_compute",
                "approval_gate_ref": "costly_compute",
                "status": "succeeded",
                "exit_code": 0,
                "evidence_ref": "terminal:training",
            }
        ]
        instance["results"]["status"] = "completed"
        instance["results"]["decision"] = "accept"
        instance["results"]["artifacts"] = [
            {"kind": "metric table", "ref": "artifact:metrics"}
        ]
        instance["results"]["metrics"] = [
            {
                "name": "F1",
                "population": "frozen holdout",
                "implementation": "metric-v1",
                "value": 0.66,
                "baseline_value": 0.61,
                "artifact_ref": "artifact:metrics",
            }
        ]
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertEqual([], errors)

    def test_run_rejects_whitespace_only_evidence(self) -> None:
        instance = json.loads(
            (ROOT / ".agent-system" / "templates" / "run.template.yaml").read_text(encoding="utf-8")
        )
        instance["task"]["id"] = "   "
        instance["task"]["acceptance"] = ["   "]
        instance["task"]["mode"] = "controlled"
        instance["provenance"]["inputs"] = [
            {"kind": "   ", "ref": "   ", "classification": "synthetic"}
        ]
        instance["policy"]["authorization_boundary"] = ["   "]
        instance["policy"]["approval_gates"] = [
            {
                "action": "   ",
                "status": "approved",
                "authority": "   ",
                "evidence_ref": "   ",
            }
        ]
        instance["execution"]["commands"] = [
            {
                "id": "training",
                "command": "train --full",
                "capability": "costly_compute",
                "approval_gate_ref": "costly_compute",
                "status": "succeeded",
                "exit_code": 0,
                "evidence_ref": "   ",
                "sanitized_summary": "   ",
            }
        ]
        instance["results"]["tests"] = [
            {
                "name": "claimed",
                "status": "passed",
                "evidence_ref": "   ",
                "sanitized_summary": "   ",
            }
        ]
        instance["results"]["status"] = "partial"
        instance["results"]["decision"] = "accept"
        instance["results"]["artifacts"] = [{"kind": "metrics", "ref": "   "}]
        instance["results"]["metrics"] = [
            {
                "name": "F1",
                "population": "holdout",
                "implementation": "v1",
                "value": "   ",
                "baseline_value": "   ",
                "artifact_ref": "   ",
            }
        ]
        schema = json.loads(
            (ROOT / ".agent-system" / "schemas" / "run.schema.json").read_text(encoding="utf-8")
        )
        structural_errors = validate_kit.schema_errors(instance, schema)
        self.assertTrue(any("required pattern" in error for error in structural_errors))
        errors = validate_kit.run_semantic_errors(instance, ROOT / "run.yaml", ROOT)
        self.assertTrue(any("task.id must be non-blank" in error for error in errors))
        self.assertTrue(any("task.acceptance" in error for error in errors))
        self.assertTrue(any("provenance input 0 needs a non-blank kind" in error for error in errors))
        self.assertTrue(any("provenance input 0 needs a non-blank ref" in error for error in errors))
        self.assertTrue(any("valid approval gate" in error for error in errors))
        self.assertTrue(any("non-empty authorization boundary" in error for error in errors))
        self.assertTrue(any("needs authority and evidence_ref" in error for error in errors))
        self.assertTrue(any("command 'training' needs evidence_ref" in error for error in errors))
        self.assertTrue(any("command 'training' sanitized_summary" in error for error in errors))
        self.assertTrue(any("passed tests need" in error for error in errors))
        self.assertTrue(any("passed test sanitized_summary" in error for error in errors))
        self.assertTrue(any("result artifact needs a non-blank ref" in error for error in errors))
        self.assertTrue(any("metric value must not be a blank string" in error for error in errors))
        self.assertTrue(any("metric baseline_value must not be a blank string" in error for error in errors))
        self.assertTrue(any("recorded metric or baseline values need" in error for error in errors))
        self.assertTrue(any("non-null artifact-backed metric" in error for error in errors))

    def test_markdown_links_ignore_fences_and_validate_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.md").write_text("# Real heading\n", encoding="utf-8")
            (root / "README.md").write_text(
                "[ok](target.md#real-heading)\n```md\n[ignored](missing.md)\n```\n[bad](target.md#missing)\n",
                encoding="utf-8",
            )
            errors = validate_kit.validate_markdown_links(root)
        self.assertEqual(["README.md: missing local fragment target.md#missing"], errors)

    def test_markdown_links_allow_balanced_parentheses_and_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target(v1).md").write_text("# Target\n", encoding="utf-8")
            (root / "README.md").write_text(
                '[target](target(v1).md "optional title")\n', encoding="utf-8"
            )
            errors = validate_kit.validate_markdown_links(root)
        self.assertEqual([], errors)

    def test_markdown_fragment_ignores_fenced_html_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.md").write_text(
                '```html\n<span id="ghost"></span>\n```\n', encoding="utf-8"
            )
            (root / "README.md").write_text("[ghost](target.md#ghost)\n", encoding="utf-8")
            errors = validate_kit.validate_markdown_links(root)
        self.assertEqual(["README.md: missing local fragment target.md#ghost"], errors)

    def test_hygiene_rejects_generated_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "tooling" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "validator.pyc").write_bytes(b"synthetic")
            errors = validate_kit.validate_hygiene(root)
        self.assertTrue(any("generated cache directory" in error for error in errors))

    def test_checked_reader_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.txt"
            outside.write_text("synthetic", encoding="utf-8")
            link = root / "link.txt"
            self.make_symlink_or_skip(link, outside)
            with self.assertRaisesRegex(ValueError, "symlinked file"):
                validate_kit.read_text_checked(link, root)

    def test_repository_validator_fails_closed_on_symlinked_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            root.mkdir()
            outside = base / "outside-validator-test.md"
            outside.write_text("synthetic", encoding="utf-8")
            self.make_symlink_or_skip(root / "README.md", outside)
            errors = validate_kit.validate_repository(root)
        self.assertTrue(any("symlinked file is not allowed" in error for error in errors))

    def test_evals_reject_non_string_fixture_id_and_dot_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "evals", root / "evals")
            path = root / "evals" / "fixtures" / "synthetic-fixtures.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["fixtures"][0]["id"] = ["not", "hashable"]
            document["fixtures"][1]["repository"]["files"]["."] = "unsafe"
            path.write_text(json.dumps(document), encoding="utf-8")
            errors = validate_kit.validate_evals(root)
        self.assertTrue(any("non-empty string ID" in error for error in errors))
        self.assertTrue(any("unsafe repository path '.'" in error for error in errors))

    def test_skill_metadata_must_be_frontmatter_mapping(self) -> None:
        current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agents", root / ".agents")
            path = root / ".agents" / "skills" / "analyze-dsml-project" / "SKILL.md"
            text = path.read_text(encoding="utf-8").replace(
                f'metadata:\n  author: "ghgin, Hermes Agent"\n  version: "{current_version}"',
                "metadata: definitely-not-a-mapping",
            )
            text += f'\n  author: "ghgin, Hermes Agent"\n  version: "{current_version}"\n'
            path.write_text(text, encoding="utf-8")
            errors = validate_kit.validate_skills(root)
        self.assertTrue(any("metadata must be a frontmatter mapping" in error for error in errors))

    def test_schema_subset_rejects_malformed_minimum_keyword(self) -> None:
        errors = validate_kit.schema_definition_errors(
            {"type": "integer", "minimum": "2"}
        )
        self.assertTrue(any("'minimum' must be a number" in error for error in errors))

    def test_schema_subset_rejects_malformed_maxItems_keyword(self) -> None:
        errors = validate_kit.schema_definition_errors(
            {"type": "array", "maxItems": "3"}
        )
        self.assertTrue(any("'maxItems' must be a non-negative integer" in error for error in errors))

    def test_missing_required_template_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_kit.validate_hygiene(Path(directory))
        self.assertTrue(any("missing required template" in error for error in errors))

    def test_documented_commands_pass_in_clean_copy(self) -> None:
        if os.environ.get("DSML_KIT_E2E_CHILD") == "1":
            self.skipTest("avoid recursive end-to-end subprocess")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "kit"
            shutil.copytree(ROOT, copy)
            environment = os.environ.copy()
            environment["DSML_KIT_E2E_CHILD"] = "1"
            checks = [
                [sys.executable, "-B", "tooling/validate-kit.py"],
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
            ]
            for command in checks:
                result = subprocess.run(
                    command,
                    cwd=copy,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
