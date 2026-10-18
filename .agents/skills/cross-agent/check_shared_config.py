#!/usr/bin/env python3
"""Assert Claude Code and Codex load the same project config. Breakage is silent, so check it.

    check_shared_config.py [repo ...]          static, offline (default: cwd)
    check_shared_config.py --live [repo ...]   also ask the real claude and codex CLIs
    check_shared_config.py --hook              session-start hook: wire the project if safe, never fail
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

CODEX_DEFAULT_DOC_MAX_BYTES = 32 * 1024  # Codex stops adding instruction files past this
CLAUDE_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
FIX = "python3 ~/.agents/skills/cross-agent/install.py"
GIT_TIMEOUT = 10
# Problems install.py fixes, and the files it touches doing so (the hook needs them clean).
FIXABLE = ("AGENTS.md missing", "no CLAUDE.md or CLAUDE.local.md imports", "Claude cannot see skill",
           "Codex cannot see skill")
WIRED_PATHS = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", ".claude/skills", ".agents/skills")
# CLAUDE.md sections that stay there. Claude-only ones drive features Codex lacks. Tool-parsed
# ones are read or rewritten in CLAUDE.md by heading (gstack's /ship, /land-and-deploy,
# /health), so moving them breaks the tool; AGENTS.md points Codex at them instead.
CLAUDE_ONLY_HEADINGS = ("skill routing", "gbrain search guidance")
TOOL_PARSED_HEADINGS = ("testing", "deploy configuration", "health stack")
POINTER_HEADING = "## Kept in CLAUDE.md"
# Codex layers ~/.codex/AGENTS.md above the project file; a separate GLOBAL slot stops it
# reporting the global heading as the project one.
PROBE = (
    "Do not use any tools. Reply with exactly three lines and nothing else:\n"
    "GLOBAL=<the first markdown heading of your user-level/global instructions, or NONE>\n"
    "PROJECT=<the last markdown heading (any level) of the instructions loaded from {agents_md}, or NONE>\n"
    "SKILL=<YES if a skill named cross-agent is in your available skills, else NO>"
)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def global_skill() -> Path:
    return Path.home() / ".agents/skills/cross-agent"


def fence_mask(lines: list[str]) -> list[bool]:
    """True for each line inside (or delimiting) a ``` or ~~~ fenced block."""
    mask, fence = [], None
    for line in lines:
        m = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence is None and m:
            fence = m.group(1)
            mask.append(True)
        elif fence is not None:
            mask.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip().strip("`~"):
                fence = None
        else:
            mask.append(False)
    return mask


def prose(text: str) -> str:
    """Text as Claude's importer sees it: fenced blocks and code spans removed."""
    lines = text.splitlines()
    kept = (l for l, fenced in zip(lines, fence_mask(lines)) if not fenced)
    return re.sub(r"(`+)(?!`).+?(?<!`)\1(?!`)", "", "\n".join(kept), flags=re.S)  # spans of any width, multiline


def sections(text: str) -> list[tuple[str | None, str]]:
    """Split on `## ` headings outside fences: [(title, text)], title None for the preamble."""
    lines = text.splitlines(keepends=True)
    out: list[tuple[str | None, list[str]]] = [(None, [])]
    for line, fenced in zip(lines, fence_mask(lines)):
        m = None if fenced else re.match(r"## +(.+?)\s*$", line)
        if m:
            out.append((m.group(1), []))
        out[-1][1].append(line)
    return [(title, "".join(body)) for title, body in out if body]


def heading_kind(title: str) -> str:
    t = title.strip().casefold()
    return "claude" if t.startswith(CLAUDE_ONLY_HEADINGS) else "tool" if t.startswith(TOOL_PARSED_HEADINGS) else "shared"


def imports(text: str, target: str = "AGENTS.md") -> bool:
    # An import can sit anywhere in a line; it ends at whitespace.
    return re.search(rf"(?:^|\s)@(?:\./)?{re.escape(target)}(?=\s|$)", prose(text), flags=re.M) is not None


def same(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and a.samefile(b)


def claude_importer(d: Path) -> Path | None:
    """The Claude file in d that imports d/AGENTS.md or links to it, if any."""
    agents = d / "AGENTS.md"
    for name in CLAUDE_FILES:
        f = d / name
        target = "../AGENTS.md" if name.startswith(".claude/") else "AGENTS.md"
        if f.is_file() and (same(f, agents) or imports(f.read_text(errors="replace"), target)):
            return f
    return None


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "git timed out")


def files(repo: Path, pattern: str) -> list[Path]:
    """Tracked and untracked-but-not-ignored files: agents load both."""
    if not (repo / ".git").exists():
        return [p for p in [repo / pattern.split("/")[-1]] if p.exists() and not pattern.startswith("*/")]
    out = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "--", f":(glob){pattern}").stdout
    return sorted({repo / p for p in out.splitlines() if (repo / p).exists()})


def doc_max_bytes(repo: Path) -> int:
    limit = CODEX_DEFAULT_DOC_MAX_BYTES
    for config in (codex_home() / "config.toml", repo / ".codex/config.toml"):
        try:
            limit = tomllib.loads(config.read_text()).get("project_doc_max_bytes", limit) if config.is_file() else limit
        except ValueError:
            pass  # a broken config is reported by the MCP and trust checks; the default still applies
    return limit


def size_problems(repo: Path) -> list[str]:
    """Codex concatenates one file per directory from the root down, up to a byte budget."""
    per_dir = {}
    for f in files(repo, "**/AGENTS.md") + files(repo, "**/AGENTS.override.md"):
        if f.name == "AGENTS.override.md" or f.parent not in per_dir:
            per_dir[f.parent] = f.stat().st_size
    limit = doc_max_bytes(repo)
    for d in sorted(per_dir, key=lambda p: len(p.parts), reverse=True):
        total = sum(n for p, n in per_dir.items() if p == d or p in d.parents)
        if total > limit:
            where = "AGENTS.md" if d == repo else f"{d.relative_to(repo)}/AGENTS.md"
            return [f"{where} and its parents total {total} bytes, over Codex's {limit}; Codex drops the rest "
                    "(raise project_doc_max_bytes or trim)"]
    return []


def instruction_problems(repo: Path) -> list[str]:
    agents_md = repo / "AGENTS.md"
    if not agents_md.is_file() or not agents_md.read_text(errors="replace").strip():
        return ["AGENTS.md missing or empty, so Codex gets no project instructions"]
    found = size_problems(repo)
    # Claude reads AGENTS.md natively only with no Claude file and a recent version; an
    # import or link works in every session, so require one at the root.
    if claude_importer(repo) is None:
        found.append("no CLAUDE.md or CLAUDE.local.md imports @AGENTS.md, so Claude may not load it")
    for override in files(repo, "**/AGENTS.override.md"):
        found.append(f"{override.relative_to(repo)} exists; Codex reads it instead of AGENTS.md, Claude does not")
    # A subdirectory with its own Claude file makes Claude skip that directory's AGENTS.md.
    for nested in files(repo, "*/**/AGENTS.md"):
        d = nested.parent
        if any((d / n).exists() for n in CLAUDE_FILES) and claude_importer(d) is None:
            found.append(f"{d.relative_to(repo)}/CLAUDE.md does not import its AGENTS.md, so Claude skips it")
    return found


def skill_problems(repo: Path) -> list[str]:
    shared, claude = repo / ".agents/skills", repo / ".claude/skills"
    found = []
    # Claude does not expand @-imports in SKILL.md, so a shared skill must be the same file.
    for canonical in sorted(shared.glob("*/SKILL.md")):
        name = canonical.parent.name
        if not same(claude / name / "SKILL.md", canonical):
            found.append(f"Claude cannot see skill {name}: .claude/skills/{name} is not a symlink to .agents/skills/{name}")
        for link in (claude, claude / name):
            if link.is_symlink() and os.path.isabs(os.readlink(link)):
                found.append(f"{link.relative_to(repo)} is an absolute symlink; it breaks on every other clone")
    for skill in sorted(claude.glob("*/SKILL.md")):  # also through a whole-directory symlink
        name = skill.parent.name
        if not (shared / name).exists():
            found.append(f"Codex cannot see skill {name}: it is not in .agents/skills (move it there and symlink back)")
    return list(dict.fromkeys(found))


def mcp_problems(repo: Path) -> list[str]:
    claude_json, codex_toml = repo / ".mcp.json", repo / ".codex/config.toml"
    try:
        claude = set(json.loads(claude_json.read_text()).get("mcpServers", {})) if claude_json.is_file() else set()
        codex = set(tomllib.loads(codex_toml.read_text()).get("mcp_servers", {})) if codex_toml.is_file() else set()
    except (ValueError, AttributeError) as e:  # JSONDecodeError and TOMLDecodeError are ValueErrors
        return [f"cannot parse MCP config: {e}"]
    found = []
    if claude - codex:
        found.append(f"Codex lacks MCP servers {sorted(claude - codex)}: mirror them under [mcp_servers] in .codex/config.toml")
    if codex - claude:
        found.append(f"Claude lacks MCP servers {sorted(codex - claude)}: add them to .mcp.json")
    return found


def trust_problems(repo: Path) -> list[str]:
    """Codex ignores a project's .codex/ (config, MCP, hooks) unless the project is trusted."""
    config = codex_home() / "config.toml"
    if not (repo / ".codex").is_dir() or not config.is_file():
        return []  # nothing to load, or not this machine's concern (CI, a teammate)
    try:
        projects = tomllib.loads(config.read_text()).get("projects", {})
    except ValueError as e:
        return [f"cannot parse {config}: {e}"]
    trusted = [Path(p) for p, v in projects.items() if v.get("trust_level") == "trusted"]
    if any(repo == p or p in repo.parents for p in trusted):
        return []
    return [f"Codex ignores .codex/ here until you trust the project (accept the prompt in codex, or set trust_level in {config})"]


def ignore_problems(repo: Path) -> list[str]:
    if not (repo / ".git").exists():
        return []
    paths = ["AGENTS.md"]
    importer = claude_importer(repo)
    if importer is not None and importer.name != "CLAUDE.local.md":  # local imports are private by design
        paths.append(str(importer.relative_to(repo)))
    for canonical in sorted((repo / ".agents/skills").glob("*/SKILL.md")):
        name = canonical.parent.name
        link = ".claude/skills" if (repo / ".claude/skills").is_symlink() else f".claude/skills/{name}"
        paths += [f".agents/skills/{name}/SKILL.md", link]
    ignored = git(repo, "check-ignore", "--", *dict.fromkeys(paths)).stdout.splitlines()
    return [f"{p} is gitignored; clones will not get it" for p in ignored]


def problems(repo: Path) -> list[str]:
    return (instruction_problems(repo) + skill_problems(repo) + mcp_problems(repo)
            + trust_problems(repo) + ignore_problems(repo))


def parse_probe(reply: str) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in reply.splitlines() if "=" in line)
    return {k.strip().upper(): v.strip().strip("`").lstrip("#").strip() for k, v in pairs}


def probe_problems(agent: str, reply: str, repo: Path) -> list[str]:
    # The last heading, not the first: Codex appends the project file after the global one,
    # and asked for "the first heading" it reports the global file's.
    lines = (repo / "AGENTS.md").read_text().splitlines()
    heading = next((l for l, fenced in reversed(list(zip(lines, fence_mask(lines))))
                    if not fenced and re.match(r"#{1,6} ", l)), None)
    if heading is None:
        return ["AGENTS.md has no heading for the live probe to ask about"]
    got = parse_probe(reply)
    found = []
    if got.get("PROJECT", "").casefold() != heading.lstrip("#").strip().casefold():
        found.append(f"{agent} did not load AGENTS.md (said PROJECT={got.get('PROJECT')!r})")
    expect_skill = (repo / ".agents/skills/cross-agent").is_dir() or global_skill().is_dir()
    if expect_skill and got.get("SKILL", "").upper() != "YES":
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


def own_repo(repo: Path) -> bool:
    """A repo you never committed to is someone else's: only untracked files change there."""
    if git(repo, "rev-parse", "-q", "--verify", "HEAD").returncode != 0:
        return True  # no commits yet: a new project
    email = git(repo, "config", "user.email").stdout.strip()
    # ponytail: scans history for your email; a git timeout on a huge repo falls back to --local
    return bool(email) and bool(git(repo, "log", "-1", "--format=%H", "-F", f"--author=<{email}>").stdout.strip())


def wire(repo: Path) -> list[str]:
    """Run install.py on the project, unless that would mix with uncommitted edits. Returns what it did."""
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no", "--", *WIRED_PATHS).stdout.splitlines()
    if dirty:
        return [f"left alone: uncommitted changes in {', '.join(line[3:] for line in dirty)}"]
    cmd = [sys.executable, str(Path(__file__).with_name("install.py")), str(repo)]
    if not own_repo(repo):
        cmd.insert(2, "--local")
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.splitlines()[1:]
    return [line.strip() for line in out if not line.strip().startswith(("FAIL ", "ok:", "fix the FAIL"))]


def hook(cwd: Path) -> None:
    """Session start: wire a project whose shared config is broken, or say why not. Never fail."""
    top = git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
    repo = Path(top) if top else cwd
    if repo.resolve() == Path.home().resolve():
        return  # ~/.claude/skills is user-level, not a project
    markers = ("AGENTS.md", "CLAUDE.md", ".claude/skills", ".agents/skills", ".mcp.json")
    if not any((repo / m).exists() for m in markers):
        return  # no project instructions yet; the global ones cover both agents
    found, did, fixed = problems(repo), [], []
    if top and any(p.startswith(FIXABLE) for p in found):
        lock = Path(git(repo, "rev-parse", "--git-path", "cross-agent.lock").stdout.strip())
        with open(lock if lock.is_absolute() else repo / lock, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)  # Claude and Codex starting together run this twice
            found = problems(repo)
            if any(p.startswith(FIXABLE) for p in found):
                before, did = found, wire(repo)
                found = problems(repo)
                fixed = [p for p in before if p not in found]
    skipped = [line for line in did if line.startswith("left alone")]
    if fixed:
        print("cross-agent: wired this project so Claude Code and Codex share its config. "
              "Nothing is committed; review with `git status` and `git diff`:")
        print("\n".join(f"- {line}" for line in did))
    if found:
        print("cross-agent: Claude Code and Codex see different config in this project:")
        print("\n".join(f"- {p}" for p in found + skipped))
        print(f"Fix with `{FIX} {repo}` and review the diff (add --local for an upstream clone).")


def self_test() -> None:
    assert imports("@AGENTS.md\n") and imports("@./AGENTS.md\n") and imports("See @AGENTS.md for rules.\n")
    assert not imports("```\n@AGENTS.md\n```\n") and not imports("~~~\n@AGENTS.md\n~~~\n")
    assert not imports("`@AGENTS.md`\n") and not imports("@AGENTS.md.extra\n") and not imports("a@AGENTS.md\n")
    assert not imports("`` @AGENTS.md ``\n") and not imports("`see\n@AGENTS.md`\n")
    assert imports("```\nx\n```\t\n@AGENTS.md\n")
    assert imports("@../AGENTS.md\n", "../AGENTS.md")
    assert parse_probe("PROJECT=`# Agent instructions`\nSKILL=YES") == {"PROJECT": "Agent instructions", "SKILL": "YES"}


def main(args: list[str]) -> int:
    self_test()
    if args == ["--hook"]:
        try:
            hook(Path.cwd())
        except Exception as e:  # a broken check must not break the session
            print(f"cross-agent check failed: {e}", file=sys.stderr)
        return 0
    live = "--live" in args
    repos = [Path(a).resolve() for a in args if a != "--live"] or [Path.cwd()]
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
