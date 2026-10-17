"""install.sh + check_shared_config.py across the repo shapes a user actually has.

    python3 -m unittest discover tests            # offline, a few seconds
    LIVE=1 python3 -m unittest discover tests     # also asks the real claude + codex CLIs
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
CHECK = SRC / ".agents/skills/cross-agent/check_shared_config.py"


def run(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        return run(str(SRC / "install.sh"), str(self.repo))

    def check(self, repo=None, *extra):
        return run("python3", str(CHECK), *extra, str(repo or self.repo))

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_fails(self, result, fragment):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(fragment, result.stderr)

    # New project: nothing there yet.
    def test_fresh_repo(self):
        self.assert_ok(self.install())
        link = self.repo / ".claude/skills/cross-agent"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "../../.agents/skills/cross-agent")

    def test_rerun_is_idempotent(self):
        self.install()
        (self.repo / "AGENTS.md").write_text("# Mine\n")
        self.assert_ok(self.install())
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "# Mine\n")
        self.assertEqual((self.repo / "CLAUDE.md").read_text().count("@AGENTS.md"), 1)

    # Existing project with its own CLAUDE.md: keep it, add the import.
    def test_existing_claude_md_kept_and_imports(self):
        (self.repo / "CLAUDE.md").write_text("# Project\n\nReal knowledge.\n")
        self.assert_ok(self.install())
        text = (self.repo / "CLAUDE.md").read_text()
        self.assertIn("Real knowledge.", text)
        self.assertIn("\n@AGENTS.md\n", text)

    def test_existing_claude_local_md_only(self):
        (self.repo / "CLAUDE.local.md").write_text("mine\n")
        self.assert_ok(self.install())

    # The silent failures. Each must fail loudly.
    def test_fenced_import_fails(self):
        (self.repo / "CLAUDE.md").write_text("```\n@AGENTS.md\n```\n")
        self.assert_fails(self.install(), "does not import @AGENTS.md")

    def test_old_stub_adapter_fails(self):
        stub = self.repo / ".claude/skills/cross-agent"
        stub.mkdir(parents=True)
        (stub / "SKILL.md").write_text("@../../../.agents/skills/cross-agent/SKILL.md\n")
        self.assert_fails(self.install(), "(symlink it)")

    def test_deleted_claude_md_fails(self):
        self.install()
        (self.repo / "CLAUDE.md").unlink()
        self.assert_fails(self.check(), "CLAUDE.md missing")

    def test_agents_override_fails(self):
        self.install()
        (self.repo / "AGENTS.override.md").write_text("# Other\n")
        self.assert_fails(self.check(), "AGENTS.override.md")

    def test_oversized_agents_md_fails(self):
        self.install()
        (self.repo / "AGENTS.md").write_text("# Big\n" + "x" * 33000)
        self.assert_fails(self.check(), "over 32 KiB")

    def test_absolute_symlink_fails(self):
        self.install()
        link = self.repo / ".claude/skills/cross-agent"
        link.unlink()
        link.symlink_to(self.repo / ".agents/skills/cross-agent")
        self.assert_fails(self.check(), "absolute symlink")

    def test_gitignored_adapter_fails(self):
        (self.repo / ".gitignore").write_text(".claude/\n")
        self.assert_fails(self.install(), "gitignored")

    # A teammate's clone must get the same layout, symlink included.
    def test_clone_keeps_layout(self):
        self.install()
        run("git", "add", "-A", cwd=self.repo)
        run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=self.repo)
        clone = Path(self.tmp.name) / "clone"
        run("git", "clone", "-q", str(self.repo), str(clone))
        self.assert_ok(self.check(clone))

    @unittest.skipUnless(os.environ.get("LIVE"), "set LIVE=1 to ask the real claude and codex CLIs")
    def test_live_both_agents_load_it(self):
        self.install()
        self.assert_ok(self.check(None, "--live"))


if __name__ == "__main__":
    unittest.main()
