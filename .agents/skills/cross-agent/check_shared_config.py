#!/usr/bin/env python3
"""Assert the shared agent config actually loads. Broken config fails silently, so check it.

    python3 .agents/skills/cross-agent/check_shared_config.py [repo]   # default: cwd
"""
import re
import sys
from pathlib import Path


def imports_agents_md(claude_md: str) -> bool:
    # Parse like Claude's importer: it skips fenced blocks and code spans.
    body = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", claude_md, flags=re.S))
    return re.search(r"^@AGENTS\.md\s*$", body, flags=re.M) is not None


def problems(repo: Path) -> list[str]:
    found = []
    if not (repo / "AGENTS.md").is_file():
        found.append("AGENTS.md missing")
    claude_md = repo / "CLAUDE.md"
    if claude_md.is_file() and not imports_agents_md(claude_md.read_text()):
        found.append("CLAUDE.md exists but does not import @AGENTS.md, so Claude ignores AGENTS.md")
    # Claude does not expand @-imports in SKILL.md, so a shared skill must be the same file.
    for canonical in sorted((repo / ".agents/skills").glob("*/SKILL.md")):
        adapter = repo / ".claude/skills" / canonical.parent.name / "SKILL.md"
        if not adapter.exists() or not adapter.samefile(canonical):
            found.append(f"{adapter.relative_to(repo)} is not {canonical.relative_to(repo)} (symlink it)")
    return found


if __name__ == "__main__":
    assert imports_agents_md("@AGENTS.md\n")
    assert not imports_agents_md("```\n@AGENTS.md\n```\n")
    assert not imports_agents_md("`@AGENTS.md`\n")

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    found = problems(repo)
    for p in found:
        print(f"FAIL {p}", file=sys.stderr)
    if found:
        sys.exit(1)
    print("shared config OK")
