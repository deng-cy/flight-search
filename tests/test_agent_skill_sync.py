from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = WORKSPACE_ROOT / "scripts/sync_agent_skills.py"


class AgentSkillSyncTests(unittest.TestCase):
    def test_sync_round_trip_from_claude_to_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "agent_skills/setup"
            (source / "scripts").mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\n"
                "name: setup\n"
                "description: Test setup skill.\n"
                "---\n"
                "\n"
                "# Setup\n"
                "\n"
                "Initial content.\n",
                encoding="utf-8",
            )
            (source / "scripts/setup_repo.py").write_text("print('setup')\n", encoding="utf-8")

            self.run_sync(root, "--to-tools")
            claude_skill = root / ".claude/skills/setup/SKILL.md"
            claude_skill.write_text(claude_skill.read_text(encoding="utf-8") + "\nClaude trial change.\n", encoding="utf-8")

            self.run_sync(root, "--from", "claude", "setup")
            self.run_sync(root, "--to-tools")
            self.run_sync(root, "--check")

            canonical_text = (root / "agent_skills/setup/SKILL.md").read_text(encoding="utf-8")
            codex_text = (root / ".codex/skills/setup/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Claude trial change.", canonical_text)
            self.assertEqual(canonical_text, codex_text)

    def run_sync(self, root: Path, *args: str) -> None:
        result = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), "--root", str(root), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
