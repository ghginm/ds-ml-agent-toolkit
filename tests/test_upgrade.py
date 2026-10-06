"""Cross-version toolkit install/repair/upgrade/downgrade behavior (audit states A-K)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONBOARD_MODULE_PATH = ROOT / "tooling" / "onboard-project.py"
ONBOARD_SPEC = importlib.util.spec_from_file_location("onboard_project_upgrade", ONBOARD_MODULE_PATH)
assert ONBOARD_SPEC and ONBOARD_SPEC.loader
onboard_project = importlib.util.module_from_spec(ONBOARD_SPEC)
ONBOARD_SPEC.loader.exec_module(onboard_project)

CURRENT_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
MARKER_START = onboard_project.MANAGED_BLOCK_START
MARKER_END = onboard_project.MANAGED_BLOCK_END
LEGACY_OWNED = ".agent-system/tooling/legacy-merge.py"
LEGACY_MODIFIED = ".agent-system/tooling/legacy-modified.py"


def restamp_manifest(overlay: Path, version: str) -> None:
    """Rewrite VERSION and regenerate manifest.json for a mutated overlay copy."""
    (overlay / ".agent-system" / "VERSION").write_text(version + "\n", encoding="utf-8")
    files = {
        str(path.relative_to(overlay)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(overlay.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {"schema_version": "0.2", "toolkit_version": version, "files": files}
    (overlay / ".agent-system" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def stamp_overlay(
    source: Path,
    destination: Path,
    version: str,
    *,
    strip_template_markers: bool = False,
    add_files: dict[str, str] | None = None,
) -> Path:
    """Copy a built overlay, rewrite its version/template, and regenerate its manifest."""
    shutil.copytree(source, destination)
    template = destination / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
    if strip_template_markers:
        text = onboard_project._strip_managed_markers(template.read_text(encoding="utf-8"))
        template.write_text(text + "\n", encoding="utf-8")
    for relative, content in (add_files or {}).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    restamp_manifest(destination, version)
    return destination


class ToolkitUpgradeTests(unittest.TestCase):
    base: Path
    current: Path

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.current = self.base / "current-overlay"
        self.build_current(self.current)

    def build_current(self, output: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "tooling/build-overlay.py", "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def run_cli(
        self,
        project: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tooling" / "onboard-project.py"),
                "--installed-project",
                str(project),
                "--harness",
                "codex",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def seed_repository(self, target: Path) -> None:
        (target / "src" / "training").mkdir(parents=True)
        (target / "src" / "inference").mkdir(parents=True)
        (target / "tests").mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "synthetic-upgrade"\ndependencies = ["pytest"]\n',
            encoding="utf-8",
        )

    def install_kit(self, project: Path) -> None:
        self.seed_repository(project)
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def validate(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(project / ".agent-system" / "tooling" / "validate-kit.py"),
                "--installed-project",
                str(project),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def make_old_project(self) -> Path:
        """Install a stamped 0.12.0 overlay plus typical user-owned state."""
        old = stamp_overlay(
            self.current,
            self.base / "old-overlay",
            "0.12.0",
            strip_template_markers=True,
            add_files={
                LEGACY_OWNED: "print('legacy toolkit script')\n",
                LEGACY_MODIFIED: "print('legacy toolkit script')\n",
            },
        )
        project = self.base / "project"
        shutil.copytree(old, project)
        self.seed_repository(project)
        old_template = (
            project / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn(MARKER_START, old_template)
        (project / "AGENTS.md").write_text(
            "# Custom project rules\n\nPreserve this project rule.\n\n"
            + old_template
            + "\nPreserve this trailing project note.\n",
            encoding="utf-8",
        )
        (project / "PROJECT_MAP.md").write_text(
            "# Project map\n\nHand-maintained; keep this exact file.\n", encoding="utf-8"
        )
        skill = project / ".agents" / "skills" / "sku-lookup" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            "---\nname: sku-lookup\ndescription: Resolve synthetic SKUs for this project.\n---\n"
            "# SKU lookup\n\nProject-owned content.\n",
            encoding="utf-8",
        )
        local_state = project / ".agent-system" / "local" / "request-events.jsonl"
        local_state.parent.mkdir(parents=True, exist_ok=True)
        self.local_event_line = (
            '{"schema_version": "0.1", "event_id": "upgrade-probe-1", '
            '"timestamp": "2026-10-06T03:30:00Z", "kind": "implementation", '
            '"topics": ["tooling"], "deliverable": "policy_and_behavioral_evals", '
            '"route": "execute-dsml-task/develop", "run_ref": null, '
            '"outcome": "completed", "rework": false, "routing_corrected": false, '
            '"reason_tags": []}\n'
        )
        local_state.write_text(self.local_event_line, encoding="utf-8")
        (project / ".agent-system" / "tooling" / "legacy-merge-notes.md").write_text(
            "Unknown user file with a similar name.\n", encoding="utf-8"
        )
        (project / LEGACY_MODIFIED).write_text(
            "user changed this obsolete toolkit file\n", encoding="utf-8"
        )
        return project

    # A. No kit installed -> fresh install through the same CLI works.
    def test_fresh_install_via_upgrade_from(self) -> None:
        project = self.base / "empty-project"
        project.mkdir()
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("installed version " + CURRENT_VERSION, result.stdout)
        self.assertIn("(no previous kit detected)", result.stdout)
        self.assertEqual(
            CURRENT_VERSION,
            (project / ".agent-system" / "VERSION").read_text(encoding="utf-8").strip(),
        )
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(MARKER_START, agents)
        self.assertEqual(1, agents.count(MARKER_START))
        validation = self.validate(project)
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

    # B + E(migration) + F + G + H + I: real cross-version upgrade.
    def test_upgrade_older_to_current_preserves_and_cleans(self) -> None:
        project = self.make_old_project()
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("upgrade 0.12.0 -> " + CURRENT_VERSION, result.stdout)
        self.assertIn("obsolete toolkit file(s) removed", result.stdout)
        self.assertIn("converted to a managed block", result.stdout)
        self.assertEqual(
            CURRENT_VERSION,
            (project / ".agent-system" / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertFalse((project / LEGACY_OWNED).exists())
        self.assertTrue((project / LEGACY_MODIFIED).exists())
        self.assertIn("Preserved `" + LEGACY_MODIFIED, result.stdout)
        self.assertTrue(
            (project / ".agent-system" / "tooling" / "legacy-merge-notes.md").is_file()
        )
        self.assertEqual(
            "# Project map\n\nHand-maintained; keep this exact file.\n",
            (project / "PROJECT_MAP.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            self.local_event_line,
            (project / ".agent-system" / "local" / "request-events.jsonl").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn(
            "Project-owned content.",
            (project / ".agents" / "skills" / "sku-lookup" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
        )
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(1, agents.count(MARKER_START))
        self.assertEqual(1, agents.count(MARKER_END))
        self.assertIn("Preserve this project rule.", agents)
        self.assertIn("Preserve this trailing project note.", agents)
        self.assertIn("temporary execution and review isolation", agents)
        runtime_tool = project / ".agent-system" / "tooling" / "onboard-project.py"
        self.assertIn("--upgrade-from", runtime_tool.read_text(encoding="utf-8"))
        validation = self.validate(project)
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

        # J. second run: repair, no changes, no duplicate content.
        second = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertIn("same-version repair", second.stdout)
        self.assertIn("0 file(s) restored or updated", second.stdout)
        self.assertEqual(agents, (project / "AGENTS.md").read_text(encoding="utf-8"))

    # E. customized managed AGENTS.md updates exactly once and keeps user content.
    def test_managed_block_upgrade_refreshes_once(self) -> None:
        old = stamp_overlay(
            self.current, self.base / "managed-old-overlay", "0.12.1"
        )
        template_path = old / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        old_template = template_path.read_text(encoding="utf-8")
        stale_block = old_template.replace(
            "## Agent system\n",
            "## Agent system\n- Obsolete toolkit guidance line that must be replaced.\n",
            1,
        )
        template_path.write_text(stale_block, encoding="utf-8")
        restamp_manifest(old, "0.12.1")
        project = self.base / "managed-project"
        shutil.copytree(old, project)
        self.seed_repository(project)
        (project / "AGENTS.md").write_text(
            "# Project handbook\n\n"
            + stale_block
            + "\nKeep this project-owned section.\n",
            encoding="utf-8",
        )

        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("refreshed in place", result.stdout)
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(1, agents.count(MARKER_START))
        self.assertEqual(1, agents.count(MARKER_END))
        self.assertNotIn("Obsolete toolkit guidance line", agents)
        self.assertIn("# Project handbook", agents)
        self.assertIn("Keep this project-owned section.", agents)
        self.assertIn("temporary execution and review isolation", agents)
        validation = self.validate(project)
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

    # C. same installed/source version keeps repair semantics.
    def test_same_version_upgrade_from_repairs_without_touching_agents(self) -> None:
        project = self.base / "same-version-project"
        project.mkdir()
        self.install_kit(project)
        before = (project / "AGENTS.md").read_text(encoding="utf-8")
        (project / ".agent-system" / "SYSTEM.md").unlink()
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("same-version repair", result.stdout)
        self.assertIn("1 file(s) restored or updated", result.stdout)
        self.assertTrue((project / ".agent-system" / "SYSTEM.md").is_file())
        self.assertEqual(before, (project / "AGENTS.md").read_text(encoding="utf-8"))

    # D. newer installed kit + older distribution -> refusal, then explicit downgrade.
    def test_downgrade_requires_explicit_intent(self) -> None:
        project = self.base / "downgrade-project"
        project.mkdir()
        self.install_kit(project)
        (project / ".agent-system" / "VERSION").write_text("0.99.0\n", encoding="utf-8")
        manifest_path = project / ".agent-system" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["toolkit_version"] = "0.99.0"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        before_agents = (project / "AGENTS.md").read_text(encoding="utf-8")

        refused = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(2, refused.returncode, refused.stdout + refused.stderr)
        self.assertIn("refusing to downgrade", refused.stdout)
        self.assertIn("No changes were made", refused.stdout)
        self.assertEqual(
            "0.99.0",
            (project / ".agent-system" / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertEqual(before_agents, (project / "AGENTS.md").read_text(encoding="utf-8"))

        forced = self.run_cli(
            project, "--upgrade-from", str(self.current), "--allow-downgrade"
        )
        self.assertEqual(0, forced.returncode, forced.stdout + forced.stderr)
        self.assertIn("downgrade 0.99.0 -> " + CURRENT_VERSION, forced.stdout)
        self.assertEqual(
            CURRENT_VERSION,
            (project / ".agent-system" / "VERSION").read_text(encoding="utf-8").strip(),
        )

    # K. a failing distribution stops before any project change.
    def test_corrupt_distribution_applies_nothing(self) -> None:
        project = self.make_old_project()
        before_agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        before_version = (project / ".agent-system" / "VERSION").read_text(encoding="utf-8")
        broken = self.base / "broken-overlay"
        shutil.copytree(self.current, broken)
        (broken / ".agent-system" / "CONTROL.md").write_text(
            "tampered content does not match the manifest\n", encoding="utf-8"
        )
        result = self.run_cli(project, "--upgrade-from", str(broken))
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("No changes were made", result.stdout)
        self.assertIn("hash mismatch", result.stdout)
        self.assertEqual(before_agents, (project / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(
            before_version,
            (project / ".agent-system" / "VERSION").read_text(encoding="utf-8"),
        )
        self.assertTrue((project / LEGACY_OWNED).exists())

    # Unit coverage of the version state machine.
    def test_version_relation_states_and_safety(self) -> None:
        relation = onboard_project._version_relation
        self.assertEqual("fresh", relation(None, "0.14.0"))
        self.assertEqual("repair", relation("0.14.0", "0.14.0"))
        self.assertEqual("upgrade", relation("0.12.0", "0.14.0"))
        self.assertEqual("downgrade", relation("0.14.0", "0.9.0"))
        self.assertEqual("upgrade", relation("0.13", "0.13.1"))
        with self.assertRaises(ValueError):
            relation("0.14.0rc1", "0.14.0")

    def test_marker_spans_pair_and_flag_strays(self) -> None:
        lines = [MARKER_START, "a", MARKER_END, "b", MARKER_START, "c"]
        pairs, strays = onboard_project._managed_marker_spans(lines)
        self.assertEqual([(0, 2)], pairs)
        self.assertEqual([4], strays)
        duplicate = [MARKER_START, "x", MARKER_END, "keep", MARKER_START, "y", MARKER_END]
        pairs, strays = onboard_project._managed_marker_spans(duplicate)
        self.assertEqual([(0, 2), (4, 6)], pairs)
        self.assertEqual([], strays)

    def test_pre_managed_intertwined_content_is_preserved_not_duplicated(self) -> None:
        """Unmanaged toolkit lines woven into custom text: preserved unchanged,
        no second block is appended, and the safe fallback reports the ambiguity."""
        project = self.base / "intertwined-project"
        project.mkdir()
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        template = (
            project / ".agent-system" / "templates" / "AGENTS.dsml.template.md"
        ).read_text(encoding="utf-8")
        unmanaged = onboard_project._strip_managed_markers(template)
        lines = unmanaged.splitlines()
        middle = len(lines) // 2
        custom_agents = (
            "\n".join(lines[:middle])
            + "\n\nCustom project rule inserted inside the toolkit text.\n\n"
            + "\n".join(lines[middle:])
            + "\n"
        )
        agents_path = project / "AGENTS.md"
        agents_path.write_text(custom_agents, encoding="utf-8")

        (project / ".agent-system" / "VERSION").write_text("0.12.0\n", encoding="utf-8")
        manifest_path = project / ".agent-system" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["toolkit_version"] = "0.12.0"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result = self.run_cli(project, "--upgrade-from", str(self.current))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not be located as one exact section", result.stdout)
        self.assertEqual(agents_path.read_text(encoding="utf-8"), custom_agents)
        self.assertEqual(0, agents_path.read_text(encoding="utf-8").count(MARKER_START))


if __name__ == "__main__":
    unittest.main()
