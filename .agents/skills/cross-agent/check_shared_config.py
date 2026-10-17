#!/usr/bin/env python3
"""Assert the shared agent config actually loads. Broken config fails silently, so check it.

    python3 .agents/skills/cross-agent/check_shared_config.py [--live] [repo ...]   # default: cwd

Static checks are instant and offline. --live also asks the real `claude` and `codex` CLIs
what they loaded (one model call each per repo).
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CODEX_PROJECT_DOC_MAX_BYTES = 32 * 1024  # Codex default; past it, it silently stops reading
# Codex layers ~/.codex/AGENTS.md above the project file; a separate GLOBAL slot stops it
# reporting the global heading as the project one.
PROBE = (
    "Do not use any tools. Reply with exactly three lines and nothing else:\n"
    "GLOBAL=<the first markdown heading of your user-level/global instructions, or NONE>\n"
    "PROJECT=<the first markdown heading of the instructions loaded from {agents_md}, or NONE>\n"
    "SKILL=<YES if a skill named cross-agent is in your available skills, else NO>"
)


def imports_agents_md(claude_md: str) -> bool:
    # Parse like Claude's importer: it skips fenced blocks and code spans.
    body = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", claude_md, flags=re.S))
    return re.search(r"^@AGENTS\.md\s*$", body, flags=re.M) is not None


def gitignored(repo: Path, rel: str) -> bool:
    if not (repo / ".git").exists():
        return False
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel]).returncode == 0


def instruction_problems(repo: Path) -> list[str]:
    agents_md, claude_md = repo / "AGENTS.md", repo / "CLAUDE.md"
    if not agents_md.is_file() or not agents_md.read_text().strip():
        return ["AGENTS.md missing or empty"]
    found = []
    if agents_md.stat().st_size > CODEX_PROJECT_DOC_MAX_BYTES:
        found.append("AGENTS.md is over 32 KiB; Codex truncates it (raise project_doc_max_bytes or split it)")
    if (repo / "AGENTS.override.md").exists():
        found.append("AGENTS.override.md exists; Codex reads it instead of AGENTS.md, Claude does not")
    # Claude reads AGENTS.md natively only with no CLAUDE.md/CLAUDE.local.md and a recent
    # version; the import works everywhere, so require it.
    if not claude_md.is_file() or not imports_agents_md(claude_md.read_text()):
        found.append("CLAUDE.md missing or does not import @AGENTS.md, so Claude may not load AGENTS.md")
    return found


def skill_problems(repo: Path) -> list[str]:
    found = []
    # Claude does not expand @-imports in SKILL.md, so a shared skill must be the same file.
    for canonical in sorted((repo / ".agents/skills").glob("*/SKILL.md")):
        link = repo / ".claude/skills" / canonical.parent.name
        adapter = link / "SKILL.md"
        if not adapter.exists() or not adapter.samefile(canonical):
            found.append(f"{adapter.relative_to(repo)} is not {canonical.relative_to(repo)} (symlink it)")
        elif link.is_symlink() and os.path.isabs(os.readlink(link)):
            found.append(f"{link.relative_to(repo)} is an absolute symlink; it breaks on every other clone")
    return found


def ignore_problems(repo: Path) -> list[str]:
    paths = ["AGENTS.md", "CLAUDE.md"]
    for canonical in sorted((repo / ".agents/skills").glob("*/SKILL.md")):
        name = canonical.parent.name
        paths += [f".agents/skills/{name}/SKILL.md", f".claude/skills/{name}"]
    return [f"{p} is gitignored; clones will not get it" for p in paths if gitignored(repo, p)]


def problems(repo: Path) -> list[str]:
    return instruction_problems(repo) + skill_problems(repo) + ignore_problems(repo)


def parse_probe(reply: str) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in reply.splitlines() if "=" in line)
    return {k.strip().upper(): v.strip().strip("`").lstrip("#").strip() for k, v in pairs}


def probe_problems(agent: str, reply: str, repo: Path) -> list[str]:
    heading = next((l for l in (repo / "AGENTS.md").read_text().splitlines() if l.startswith("# ")), None)
    if heading is None:
        return ["AGENTS.md has no '# ' heading for the live probe to ask about"]
    got = parse_probe(reply)
    found = []
    if got.get("PROJECT", "").casefold() != heading[2:].strip().casefold():
        found.append(f"{agent} did not load AGENTS.md (said PROJECT={got.get('PROJECT')!r})")
    if (repo / ".agents/skills/cross-agent").is_dir() and got.get("SKILL", "").upper() != "YES":
        found.append(f"{agent} does not list the cross-agent skill (said SKILL={got.get('SKILL')!r})")
    return found


def ask(cmd: list[str], repo: Path) -> str:
    try:
        r = subprocess.run(cmd, cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"ERROR {e}"
    return r.stdout


def live_problems(repo: Path) -> list[str]:
    probe = PROBE.format(agents_md=repo / "AGENTS.md")
    found = probe_problems("claude", ask(["claude", "-p", probe, "--max-turns", "1"], repo), repo)
    with tempfile.NamedTemporaryFile(suffix=".txt") as out:
        ask(["codex", "exec", "--sandbox", "read-only", "--ephemeral", "-o", out.name, probe], repo)
        found += probe_problems("codex", Path(out.name).read_text(), repo)
    return found


def self_test() -> None:
    assert imports_agents_md("@AGENTS.md\n")
    assert not imports_agents_md("```\n@AGENTS.md\n```\n")
    assert not imports_agents_md("`@AGENTS.md`\n")
    assert parse_probe("PROJECT=`# Agent instructions`\nSKILL=YES") == {"PROJECT": "Agent instructions", "SKILL": "YES"}


if __name__ == "__main__":
    self_test()
    args = sys.argv[1:]
    live = "--live" in args
    repos = [Path(a).resolve() for a in args if a != "--live"] or [Path(".").resolve()]
    failed = False
    for repo in repos:
        found = problems(repo)
        if live and not found:  # live probes only mean something once the static layout is right
            found = live_problems(repo)
        for p in found:
            print(f"FAIL {repo}: {p}", file=sys.stderr)
        if not found:
            print(f"ok   {repo}" + (" (live: claude + codex)" if live else ""))
        failed = failed or bool(found)
    sys.exit(1 if failed else 0)
