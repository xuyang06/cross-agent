"""install.py + check_shared_config.py across the repo shapes a user actually has.

    python3 -m unittest discover tests            # offline, fake $HOME, a few seconds
    LIVE=1 python3 -m unittest discover tests     # also asks the real claude + codex CLIs
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / ".agents/skills/cross-agent"
INSTALL, CHECK = SKILL / "install.py", SKILL / "check_shared_config.py"
ROUTING = "## Skill routing\n\n- Bugs → invoke /investigate\n"
TESTING = "## Testing\n\nRun `npm test`.\n"
ARCH = "## Architecture\n\nOne service, one database.\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.repo = root / "home", root / "repo"
        self.home.mkdir()
        self.repo.mkdir()
        self.git("init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, script, *args, cwd=None, home=True):
        env = {**os.environ, "HOME": str(self.home)} if home else None
        env and env.pop("CODEX_HOME", None)
        return subprocess.run(["python3", str(script), *args], cwd=cwd, env=env, capture_output=True, text=True)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True)

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")

    def install(self, *args):
        return self.run_py(INSTALL, *args, str(self.repo))

    def check(self, repo=None, *args):
        return self.run_py(CHECK, *args, str(repo or self.repo))

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def read(self, rel):
        return (self.repo / rel).read_text()

    def assert_ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def assert_fails(self, r, fragment):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(fragment, r.stdout + r.stderr)


class NewProject(Base):
    def test_empty_repo_gets_both_files(self):
        self.assert_ok(self.install())
        self.assertTrue(self.read("AGENTS.md").startswith("# Agent instructions"))
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n")

    def test_rerun_changes_nothing(self):
        self.install()
        self.write("AGENTS.md", "# Mine\n")
        self.assert_ok(self.install())
        self.assertEqual(self.read("AGENTS.md"), "# Mine\n")
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n")

    def test_vendor_copies_skill_and_links_it(self):
        self.assert_ok(self.install("--vendor"))
        link = self.repo / ".claude/skills/cross-agent"
        self.assertEqual(os.readlink(link), "../../.agents/skills/cross-agent")
        self.assertTrue((self.repo / ".agents/skills/cross-agent/install.py").is_file())

    def test_clone_keeps_layout(self):
        self.install("--vendor")
        self.commit()
        clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(clone)], check=True)
        self.assert_ok(self.check(clone))


class ExistingProject(Base):
    def test_claude_only_repo_splits_by_audience(self):
        self.write("CLAUDE.md", ROUTING + "\n" + ARCH)
        self.commit()
        self.assert_ok(self.install())
        self.assertIn("One service, one database.", self.read("AGENTS.md"))
        self.assertNotIn("Skill routing", self.read("AGENTS.md"))
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n\n" + ROUTING.strip() + "\n")

    def test_tool_parsed_sections_stay_and_are_listed(self):
        deploy = "## Deploy Configuration (configured by /setup-deploy)\n\n- Platform: Railway\n"
        self.write("CLAUDE.md", ROUTING + "\n" + TESTING + "\n" + deploy + "\n" + ARCH)
        self.assert_ok(self.install())
        claude, agents = self.read("CLAUDE.md"), self.read("AGENTS.md")
        for kept in ("Run `npm test`.", "- Platform: Railway", "Skill routing"):
            self.assertIn(kept, claude)
        self.assertIn("One service, one database.", agents)
        self.assertNotIn("Run `npm test`.", agents)
        self.assertIn("## Kept in CLAUDE.md", agents)
        self.assertIn("- Deploy Configuration (configured by /setup-deploy)", agents)

    def test_split_file_left_byte_identical(self):
        self.write("AGENTS.md", "# P\n\nShared.\n")
        text = "# Adapter notes\n\nWhy this file exists.\n\n@AGENTS.md\n\n" + ROUTING
        self.write("CLAUDE.md", text)
        self.assert_ok(self.install())
        self.assertEqual(self.read("CLAUDE.md"), text)
        self.assertEqual(self.read("AGENTS.md"), "# P\n\nShared.\n")

    def test_both_files_without_import(self):
        self.write("AGENTS.md", "# Project\n\nShared.\n")
        self.write("CLAUDE.md", "```\n@AGENTS.md\n```\n" + ARCH)
        self.assert_ok(self.install())
        self.assertIn("One service, one database.", self.read("AGENTS.md"))
        self.assertTrue(self.read("CLAUDE.md").startswith("@AGENTS.md\n"))

    def test_claude_md_symlinked_to_agents_md_left_alone(self):
        self.write("AGENTS.md", "# Project\n")
        (self.repo / "CLAUDE.md").symlink_to("AGENTS.md")
        self.assert_ok(self.install())
        self.assertTrue((self.repo / "CLAUDE.md").is_symlink())

    def test_local_mode_touches_only_untracked_files(self):
        self.write("AGENTS.md", "# Upstream\n")
        self.write("CLAUDE.md", "Read AGENTS.md first.\n")
        self.commit()
        self.assert_ok(self.install("--local"))
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.read("CLAUDE.local.md"), "@AGENTS.md\n")

    def test_claude_only_skill_moves_with_history(self):
        self.write("AGENTS.md", "# P\n")
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.write(".claude/skills/deploy/SKILL.md", "---\nname: deploy\n---\nbody\n")
        self.commit()
        self.assert_ok(self.install())
        self.assertEqual(self.read(".agents/skills/deploy/SKILL.md"), "---\nname: deploy\n---\nbody\n")
        self.assertTrue((self.repo / ".claude/skills/deploy").is_symlink())
        self.assertIn("R  .claude/skills/deploy/SKILL.md -> .agents/skills/deploy/SKILL.md",
                      self.git("status", "--porcelain").stdout)

    def test_old_stub_replaced(self):
        self.install("--vendor")
        link = self.repo / ".claude/skills/cross-agent"
        link.unlink()
        self.write(".claude/skills/cross-agent/SKILL.md", "@../../../.agents/skills/cross-agent/SKILL.md\n")
        self.assert_ok(self.install())
        self.assertTrue(link.is_symlink())

    def test_whole_skills_dir_symlink_accepted(self):
        self.install()
        self.write(".agents/skills/a/SKILL.md", "x")
        (self.repo / ".claude").mkdir(exist_ok=True)
        (self.repo / ".claude/skills").symlink_to("../.agents/skills")
        self.assert_ok(self.check())


class SilentBreakage(Base):
    """Each of these loads fine and is wrong. The check must say so."""

    def setUp(self):
        super().setUp()
        self.install("--vendor")

    def test_missing_import(self):
        self.write("CLAUDE.md", "# Unrelated\n")
        self.assert_fails(self.check(), "imports @AGENTS.md")

    def test_agents_override(self):
        self.write("AGENTS.override.md", "# Other\n")
        self.assert_fails(self.check(), "AGENTS.override.md")

    def test_oversized_agents_md(self):
        self.write("AGENTS.md", "# Big\n" + "x" * 33000)
        self.assert_fails(self.check(), "over Codex's 32768")

    def test_absolute_symlink(self):
        link = self.repo / ".claude/skills/cross-agent"
        link.unlink()
        link.symlink_to(self.repo / ".agents/skills/cross-agent")
        self.assert_fails(self.check(), "absolute symlink")

    def test_gitignored_adapter(self):
        self.write(".gitignore", ".claude/\n")
        self.assert_fails(self.check(), "gitignored")

    def test_claude_only_skill(self):
        self.write(".claude/skills/solo/SKILL.md", "x")
        self.assert_fails(self.check(), "Codex cannot see skill solo")

    def test_nested_claude_md_without_import(self):
        self.write("pkg/AGENTS.md", "# Pkg\n")
        self.write("pkg/CLAUDE.md", "# Pkg notes\n")
        self.commit()
        self.assert_fails(self.check(), "pkg/CLAUDE.md does not import")

    def test_mcp_servers_differ(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"db": {}, "web": {}}}))
        self.write(".codex/config.toml", "[mcp_servers.db]\ncommand = 'x'\n")
        self.assert_fails(self.check(), "Codex lacks MCP servers ['web']")
        self.write(".codex/config.toml", "[mcp_servers.db]\ncommand = 'x'\n[mcp_servers.web]\ncommand = 'y'\n")
        self.assert_ok(self.check())

    def test_untrusted_codex_project(self):
        self.write(".codex/config.toml", "model = 'x'\n")
        (self.home / ".codex").mkdir()
        (self.home / ".codex/config.toml").write_text('[projects."/elsewhere"]\ntrust_level = "trusted"\n')
        self.assert_fails(self.check(), "until you trust the project")
        (self.home / ".codex/config.toml").write_text(f'[projects."{self.repo.resolve()}"]\ntrust_level = "trusted"\n')
        self.assert_ok(self.check())


class Hook(Base):
    def hook(self, cwd):
        r = self.run_py(CHECK, "--hook", cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_silent_without_instructions(self):
        self.assertEqual(self.hook(self.repo), "")

    def test_silent_when_shared(self):
        self.install()
        self.assertEqual(self.hook(self.repo), "")

    def test_silent_in_home_directory(self):
        (self.home / ".claude/skills/solo").mkdir(parents=True)
        (self.home / ".claude/skills/solo/SKILL.md").write_text("x")
        self.assertEqual(self.hook(self.home), "")

    def test_reports_from_subdirectory(self):
        self.write("CLAUDE.md", TESTING)
        (self.repo / "src").mkdir()
        out = self.hook(self.repo / "src")
        self.assertIn("AGENTS.md missing", out)
        self.assertIn("install.py", out)


class System(Base):
    def setUp(self):
        super().setUp()
        rules = self.home / ".claude/rules"
        (rules / "common").mkdir(parents=True)
        (rules / "common/testing.md").write_text("# Testing\n\nCover 80%.\n")
        (rules / "common/hooks.md").write_text("# Hooks\n\nClaude-only.\n")
        (rules / "ts").mkdir()
        (rules / "ts/style.md").write_text('---\npaths:\n  - "**/*.ts"\n---\n# TS style\n')
        self.settings = self.home / ".claude/settings.json"
        self.settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": []}]}}))

    def system(self):
        return self.run_py(INSTALL, "--system")

    def test_installs_for_both_agents(self):
        self.assert_ok(self.system())
        self.assertTrue((self.home / ".agents/skills/cross-agent/SKILL.md").is_file())
        self.assertEqual(os.readlink(self.home / ".claude/skills/cross-agent"), "../../.agents/skills/cross-agent")
        codex = (self.home / ".codex/AGENTS.md").read_text()
        for expected in ("Cover 80%.", "# Shared agent setup", "> Applies only to files matching: **/*.ts"):
            self.assertIn(expected, codex)
        self.assertNotIn("Claude-only.", codex)

    def test_hooks_added_once_and_settings_kept(self):
        self.system()
        self.assert_ok(self.system())
        claude = json.loads(self.settings.read_text())
        self.assertEqual(claude["model"], "x")
        self.assertIn("Stop", claude["hooks"])
        self.assertEqual(len(claude["hooks"]["SessionStart"]), 1)
        codex = json.loads((self.home / ".codex/hooks.json").read_text())
        self.assertEqual(len(codex["hooks"]["SessionStart"]), 1)

    def test_sync_check_catches_stale_and_shadowed(self):
        self.system()
        self.assert_ok(self.run_py(INSTALL, "--sync-global", "--check"))
        (self.home / ".claude/rules/common/testing.md").write_text("# Testing\n\nCover 90%.\n")
        self.assert_fails(self.run_py(INSTALL, "--sync-global", "--check"), "stale")
        self.run_py(INSTALL, "--sync-global")
        (self.home / ".codex/AGENTS.override.md").write_text("x")
        self.assert_fails(self.run_py(INSTALL, "--sync-global", "--check"), "shadows")

    def test_rerun_from_installed_copy(self):
        self.system()
        self.assert_ok(self.run_py(self.home / ".agents/skills/cross-agent/install.py", "--system"))

    def test_refuses_hand_written_codex_agents_md(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("# Mine\n")
        self.assert_fails(self.run_py(INSTALL, "--sync-global"), "refusing to overwrite")
        self.assertEqual((self.home / ".codex/AGENTS.md").read_text(), "# Mine\n")


class SecondReview(Base):
    """Regressions for the second Codex review round."""

    def test_r1_fence_inside_section_closes(self):
        self.write("CLAUDE.md", "## Skill routing\n\n```\n/qa\n```\n\n" + ARCH)
        self.assert_ok(self.install())
        self.assertIn("One service, one database.", self.read("AGENTS.md"))
        self.assertNotIn("One service", self.read("CLAUDE.md"))

    def test_r2_customised_stub_kept(self):
        self.install("--vendor")
        link = self.repo / ".claude/skills/cross-agent"
        for custom in ("---\nname: cross-agent\nallowed-tools: Bash\n---\n" + "@../../../.agents/skills/cross-agent/SKILL.md\n",
                       "<!-- my local note -->\n@../../../.agents/skills/cross-agent/SKILL.md\n"):
            if link.is_symlink():
                link.unlink()
            self.write(".claude/skills/cross-agent/SKILL.md", custom)
            self.install()
            self.assertEqual(self.read(".claude/skills/cross-agent/SKILL.md"), custom)

    def test_r2_real_old_stub_still_replaced(self):
        self.install("--vendor")
        (self.repo / ".claude/skills/cross-agent").unlink()
        stub = ("---\nname: cross-agent\ndescription: x\n---\n\n<!-- Adapter only. The canonical skill lives in "
                ".agents/skills/ so Codex and Copilot read\n     the same file Claude Code does. Edit that one; this "
                "stub exists to point at it. -->\n\n@../../../.agents/skills/cross-agent/SKILL.md\n")
        self.write(".claude/skills/cross-agent/SKILL.md", stub)
        self.assert_ok(self.install())
        self.assertTrue((self.repo / ".claude/skills/cross-agent").is_symlink())

    def test_r3_code_span_import_rejected(self):
        self.write("AGENTS.md", "# P\n")
        self.write("CLAUDE.md", "`` @AGENTS.md ``\n")
        self.assert_fails(self.check(), "imports @AGENTS.md")

    def test_r4_legacy_sync_script_kept(self):
        (self.home / ".claude/rules").mkdir(parents=True)
        (self.home / ".codex").mkdir()
        legacy = self.home / ".codex/sync-claude-rules.sh"
        legacy.write_text("# <!-- generated by ~/.codex/sync-claude-rules.sh -->\n")
        self.assert_ok(self.run_py(INSTALL, "--system"))
        self.assertTrue(legacy.exists())


class ThirdReview(Base):
    """Regressions for the third Codex review round, after cutting the in-place rewrite."""

    def test_r1_r2_imported_repo_never_rewritten(self):
        agents = "# P\n\n## Kept in CLAUDE.md\n\n- Testing\n\nApproval required.\n\n# Release policy\n\nShip Fridays.\n"
        claude = "## Shared instructions\n@AGENTS.md\n\n## Testing\nRun tests.\n\n## Health Stack\n- ruff\n"
        self.write("AGENTS.md", agents)
        self.write("CLAUDE.md", claude)
        self.assert_ok(self.install())
        self.assertEqual((self.read("AGENTS.md"), self.read("CLAUDE.md")), (agents, claude))

    def test_r3_incidental_title_text_still_gets_pointer(self):
        self.write("AGENTS.md", "# P\n\nTesting is important.\n")
        self.write("CLAUDE.md", TESTING)
        self.assert_ok(self.install())
        self.assertIn("## Kept in CLAUDE.md\n\nTools parse", self.read("AGENTS.md"))
        self.assertIn("- Testing\n", self.read("AGENTS.md"))

    def test_r4_claude_specific_heading_in_imported_file_ok(self):
        self.write("AGENTS.md", "# P\n")
        self.write("CLAUDE.md", "@AGENTS.md\n\n## Claude-specific subagents\n\nUse the planner.\n")
        self.assert_ok(self.install())
        self.assertIn("Claude-specific subagents", self.read("CLAUDE.md"))
        self.assertNotIn("planner", self.read("AGENTS.md"))

    def test_r5_partial_overlap_not_duplicated(self):
        self.write("AGENTS.md", "# P\n\n" + ARCH)
        self.write("CLAUDE.md", ARCH + "\n## Style\n\nTabs.\n")
        self.assert_ok(self.install())
        self.assertEqual(self.read("AGENTS.md").count("One service, one database."), 1)
        self.assertIn("Tabs.", self.read("AGENTS.md"))

    def test_r6_multiline_code_span_kept_verbatim(self):
        self.write("CLAUDE.md", "## Notes\n\nUse `this\n@AGENTS.md\nspan` literally.\n")
        self.assert_ok(self.install())
        self.assertIn("Use `this\n@AGENTS.md\nspan` literally.", self.read("AGENTS.md"))


class ReviewFindings(Base):
    """Regressions for the Codex review of the first install.py. Numbers match that review."""

    def test_1_stub_with_user_notes_is_not_deleted(self):
        self.install("--vendor")
        (self.repo / ".claude/skills/cross-agent").unlink()
        self.write(".claude/skills/cross-agent/SKILL.md", "@../../../.agents/skills/cross-agent/SKILL.md\nmy notes\n")
        self.install()
        self.assertIn("my notes", self.read(".claude/skills/cross-agent/SKILL.md"))

    def test_1_stub_beside_user_file_is_not_deleted(self):
        self.install("--vendor")
        (self.repo / ".claude/skills/cross-agent").unlink()
        self.write(".claude/skills/cross-agent/SKILL.md", "@../../../.agents/skills/cross-agent/SKILL.md\n")
        self.write(".claude/skills/cross-agent/notes.md", "mine\n")
        self.install()
        self.assertTrue((self.repo / ".claude/skills/cross-agent/notes.md").exists(), "user file deleted")
        self.assertEqual(self.read(".claude/skills/cross-agent/notes.md"), "mine\n")

    def test_2_vendored_edits_survive_plain_install(self):
        self.install("--vendor")
        self.write(".agents/skills/cross-agent/SKILL.md", "local edit\n")
        out = self.install().stdout
        self.assertEqual(self.read(".agents/skills/cross-agent/SKILL.md"), "local edit\n")
        self.assertIn("--vendor replaces it", out)

    def test_3_hand_written_global_rule_kept(self):
        rule = self.home / ".claude/rules/cross-agent.md"
        rule.parent.mkdir(parents=True)
        rule.write_text("# Mine\n")
        self.assert_fails(self.run_py(INSTALL, "--system"), "not written by cross-agent")
        self.assertEqual(rule.read_text(), "# Mine\n")
        self.assertFalse((self.home / ".agents/skills/cross-agent").exists())

    def test_3_other_tools_generated_codex_file_kept(self):
        (self.home / ".claude/rules").mkdir(parents=True)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("<!-- generated by another tool -->\n# Theirs\n")
        self.assert_fails(self.run_py(INSTALL, "--sync-global"), "refusing to overwrite")
        self.assertIn("# Theirs", (self.home / ".codex/AGENTS.md").read_text())

    def test_4_users_tmp_file_untouched(self):
        (self.home / ".claude/rules").mkdir(parents=True)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md.tmp").write_text("mine\n")
        self.run_py(INSTALL, "--sync-global")
        self.assertTrue((self.home / ".codex/AGENTS.md.tmp").exists(), "user's .tmp file consumed")
        self.assertEqual((self.home / ".codex/AGENTS.md.tmp").read_text(), "mine\n")

    def test_4_concurrent_syncs_all_succeed(self):
        (self.home / ".claude/rules").mkdir(parents=True)
        (self.home / ".claude/rules/a.md").write_text("# A\n" + "x" * 200000)
        env = {**os.environ, "HOME": str(self.home)}
        procs = [subprocess.Popen(["python3", str(INSTALL), "--sync-global", "--quiet"], env=env,
                                  stderr=subprocess.PIPE, text=True) for _ in range(8)]
        for proc in procs:
            self.assertEqual(proc.wait(), 0, proc.stderr.read())
        self.assert_ok(self.run_py(INSTALL, "--sync-global", "--check"))
        self.assertEqual([p.name for p in (self.home / ".codex").iterdir()], ["AGENTS.md"])

    def test_5_local_leaves_tracked_claude_local_md(self):
        self.write("AGENTS.md", "# Up\n")
        self.write("CLAUDE.local.md", "tracked notes\n")
        self.write(".agents/skills/s/SKILL.md", "x")
        self.commit()
        self.install("--local")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_6_exclude_without_trailing_newline(self):
        self.write("AGENTS.md", "# Up\n")
        self.commit()
        (self.repo / ".git/info").mkdir(exist_ok=True)
        (self.repo / ".git/info/exclude").write_text("private.env")
        self.assert_ok(self.install("--local"))
        self.assertEqual((self.repo / ".git/info/exclude").read_text(), "private.env\nCLAUDE.local.md\n")

    def test_6_exclude_in_worktree(self):
        self.write("AGENTS.md", "# Up\n")
        self.commit()
        wt = Path(self.tmp.name) / "wt"
        self.git("worktree", "add", "-q", str(wt))
        self.assert_ok(self.run_py(INSTALL, "--local", str(wt)))
        self.assertEqual(self.git("status", "--porcelain", cwd=wt).stdout, "")

    def test_7_split_keeps_literal_content(self):
        body = ("## Notes\n\n```\n@AGENTS.md\n## Skill routing\n```\n\n@AGENTS.md.extra\n\n"
                "Policy after the fence.\n")
        self.write("CLAUDE.md", body)
        self.install()
        agents = self.read("AGENTS.md")
        for kept in ("```\n@AGENTS.md\n## Skill routing\n```", "@AGENTS.md.extra", "Policy after the fence."):
            self.assertIn(kept, agents)
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n")

    def test_9_inline_import_accepted_tilde_fence_rejected(self):
        self.write("AGENTS.md", "# P\n")
        self.write("CLAUDE.md", "See @AGENTS.md for the rules.\n")
        self.assert_ok(self.check())
        self.write("CLAUDE.md", "~~~\n@AGENTS.md\n~~~\n")
        self.assert_fails(self.check(), "imports @AGENTS.md")

    def test_10_skills_dir_linked_elsewhere(self):
        self.install()
        self.write("elsewhere/solo/SKILL.md", "x")
        (self.repo / ".claude").mkdir(exist_ok=True)
        (self.repo / ".claude/skills").symlink_to("../elsewhere")
        self.assert_fails(self.check(), "Codex cannot see skill solo")

    def test_11_untracked_nested_override(self):
        self.install()
        self.write("pkg/AGENTS.override.md", "# Other\n")
        self.assert_fails(self.check(), "pkg/AGENTS.override.md")

    def test_12_combined_size_and_configured_limit(self):
        self.install()
        self.write("AGENTS.md", "# P\n" + "x" * 20000)
        self.write("pkg/AGENTS.md", "# Q\n" + "y" * 20000)
        self.assert_fails(self.check(), "pkg/AGENTS.md and its parents total")
        (self.home / ".codex").mkdir()
        (self.home / ".codex/config.toml").write_text("project_doc_max_bytes = 65536\n")
        self.assert_ok(self.check())

    def test_13_ignored_claude_md(self):
        self.install()
        self.write(".gitignore", "CLAUDE.md\n")
        self.assert_fails(self.check(), "CLAUDE.md is gitignored")

    def test_14_refused_sync_installs_no_hooks(self):
        (self.home / ".claude/rules").mkdir(parents=True)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/AGENTS.md").write_text("# Mine\n")
        self.assert_fails(self.run_py(INSTALL, "--system"), "not written by cross-agent")
        self.assertFalse((self.home / ".codex/hooks.json").exists())
        self.assertFalse((self.home / ".claude/settings.json").exists())


@unittest.skipUnless(os.environ.get("LIVE"), "set LIVE=1 to ask the real claude and codex CLIs")
class Live(Base):
    def test_both_agents_load_it(self):
        self.write("CLAUDE.md", ROUTING + "\n" + TESTING)
        self.install()
        self.assert_ok(self.run_py(CHECK, "--live", str(self.repo), home=False))


if __name__ == "__main__":
    unittest.main()
