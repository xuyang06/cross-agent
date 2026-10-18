# cross-agent

A skill for running **Claude Code and Codex together** on one repo: shared instructions and
skills, three handoff patterns, and the failure modes that actually bite.

Two agents are worth the trouble for one reason: **an agent reviewing work it did not write
has no stake in it.** Everything else is logistics around protecting that property.

## How it works

Neither agent reads the other's config. Claude Code reads `CLAUDE.md`, `~/.claude/rules` and
`.claude/skills`; Codex reads `AGENTS.md`, `~/.codex/AGENTS.md` and `.agents/skills`. Where
they meet, it goes wrong without an error:

- Claude Code reads `AGENTS.md` only when there is no `CLAUDE.md`, so in most repos it never does.
- Claude expands `@` imports in `CLAUDE.md` but not inside a skill's `SKILL.md`.
- Codex never reads `CLAUDE.md` or your Claude rules.

So everything has one canonical copy, where Codex looks, and Claude gets a thin adapter that
points at it:

| What | Canonical (Codex reads it) | Claude Code adapter |
|---|---|---|
| Project instructions | `AGENTS.md` | `CLAUDE.md`: `@AGENTS.md`, then Claude-only content |
| Project skills | `.agents/skills/<name>/` | `.claude/skills/<name>` → symlink |
| Project MCP servers | `.codex/config.toml` `[mcp_servers]` | `.mcp.json`, same names |
| User skills | `~/.agents/skills/<name>/` | `~/.claude/skills/<name>` → symlink |
| User rules | `~/.codex/AGENTS.md`, generated | `~/.claude/rules/` is the source |

This repo is laid out the same way, so it demonstrates what it documents.

Four pieces do the work:

1. **`install.py <repo>` migrates a project once.** It splits `CLAUDE.md` by audience. Shared
   sections move word for word to `AGENTS.md`. Skill routing stays in `CLAUDE.md`, and so do
   the sections gstack parses there by heading (Testing, Deploy Configuration, Health Stack);
   `AGENTS.md` lists those so Codex knows to read them. `CLAUDE.md` then starts with
   `@AGENTS.md`. Claude-only skills move to `.agents/skills/` (with `git mv`) and are symlinked
   back. It never deletes a line and never rewrites a repo that is already wired.
2. **`install.py --system` sets up the machine once.** It installs the skill for both agents,
   writes a short rule to `~/.claude/rules/` telling both agents where things go, and generates
   `~/.codex/AGENTS.md` from your `~/.claude/rules`.
3. **A session-start hook in both agents** regenerates `~/.codex/AGENTS.md` when your rules
   change and runs the checker. In a project whose wiring has broken, it tells the agent what
   is wrong and which command fixes it. Elsewhere it is silent (about 0.2 s).
4. **`check_shared_config.py` catches what loads without error but is still wrong:** a missing
   import, an `AGENTS.override.md` that shadows the real file, a skill only Claude can see, an
   ignored or oversized `AGENTS.md`, mismatched MCP servers, an untrusted `.codex/`. With
   `--live` it asks the real `claude` and `codex` CLIs what they loaded.

## What you need

- macOS (Linux should work but is untested), `git`, and Python 3.10 or newer. No other
  dependencies.
- Claude Code and the Codex CLI, both signed in. Codex needs hook support for the
  session-start check (tested on `codex-cli` 0.154).
- About five minutes. After setup there is nothing to remember: new projects only need an
  `AGENTS.md`, and both agents are told that by the global rule.

## Install

```bash
git clone https://github.com/xuyang06/cross-agent.git && cd cross-agent
I=.agents/skills/cross-agent/install.py

python3 $I --system                         # 1. once per machine
python3 $I ~/code/repo-a ~/code/repo-b      # 2. each existing repo that has a CLAUDE.md
python3 $I --local ~/code/upstream-clone    #    someone else's repo: untracked files only
```

Then:

3. **Review and commit** each migrated repo (`git diff`, `git status`). Nothing is committed
   for you.
4. **Approve the hook in Codex** the first time it asks. Codex makes you review a new hook once
   before running it.
5. **Check it took:**
   `python3 ~/.agents/skills/cross-agent/check_shared_config.py --live ~/code/repo-a`
   prints `ok ... (live: claude + codex)` when both agents load the same config.

Options: `--vendor` also commits a copy of the skill into the repo for teammates who have not
installed it. `--local` writes only an untracked `CLAUDE.local.md` (excluded through
`.git/info/exclude`), for repos you should not change. Every settings file the installer edits
gets a `.cross-agent.bak` backup first.

## Day to day

- **Write project knowledge in `AGENTS.md`.** Keep `CLAUDE.md` to `@AGENTS.md` plus skill
  routing.
- **Put new project skills in `.agents/skills/<name>/`**, then
  `ln -s ../../.agents/skills/<name> .claude/skills/<name>`.
- **Keep editing `~/.claude/rules/`.** Codex gets the change at its next session start.
- **Log decisions in `DECISIONS.md`**, not in either agent's memory.
- **If a session opens with a cross-agent warning,** run the command it prints and review the
  diff.

Check any repo, or run this repo's tests:

```bash
python3 ~/.agents/skills/cross-agent/check_shared_config.py ~/code/*/   # static, offline
python3 ~/.agents/skills/cross-agent/check_shared_config.py --live .    # asks claude and codex
python3 -m unittest discover tests                                      # LIVE=1 adds the live test
```

## Uninstall

Remove the `cross-agent` entries from the `SessionStart` hooks in `~/.claude/settings.json` and
`~/.codex/hooks.json`, then delete `~/.agents/skills/cross-agent`,
`~/.claude/skills/cross-agent` and `~/.claude/rules/cross-agent.md`. Migrated repos keep
working without it: they are plain `AGENTS.md`, `CLAUDE.md` and symlinks.

## Two rules

**1. The reviewer must not be able to write.**

```bash
codex exec --sandbox read-only "$(cat review-brief.md)" < /dev/null
```

A reviewer that can edit will quietly fix things instead of telling you about them, and you
lose the finding. The sandbox flag is what makes a review a review.

**2. If a rule matters, write the test, not the instruction.**

Instructions to an agent are advisory, and the other agent starts every run cold — asking it
to *remember* a rule fails by construction. A test binds both agents and you. Decisions worth
keeping become assertions:

| Decision | Enforced as |
|---|---|
| This package stays framework-free | a test that imports it and fails on the dependency |
| The public page serves X, never Y | a test asserting the served content |
| The shared instructions are actually loaded | `check_shared_config.py`, shipped with the skill |

## What is actually in here

The two source articles cover the setup and the patterns well. What this adds:

**A correction to the simple advice.** Claude Code reads `AGENTS.md` natively *only when no
`CLAUDE.md` exists* in the working directory or above. Most repos have one, so `AGENTS.md` is
silently ignored unless that file imports it — and if the import breaks, Claude loads nothing
and nothing errors. Split by audience too: moving a token `AGENTS.md` into place while the
real knowledge stays in `CLAUDE.md` gives the other agent nothing.

**The half nobody documents: shared state.** Claude accumulates memory across sessions; Codex's
memory is off by default, so it starts cold; neither can read the other's. A decision in one agent's
store is one the other will relitigate. Keep a `DECISIONS.md` in the repo — in the project
these notes come from, 20 logged decisions sat where the second agent could not see them,
including a memory file about *how to work with Codex*.

**Eight failure modes with numbers attached**, from six adversarial review rounds on a real
project:

- Two agents in one directory produce **phantom findings** — a reviewer reading a file
  mid-write reported a defect that was already fixed
- Reviewer findings are claims: **4 of 43 did not survive a source check**
- The spec is the bug surface — an agent given a bad URL implemented it correctly and the
  result was broken
- **5 of 6 rounds** corrected a claim in one file and left it standing in a sibling
- Truncated grep output hid the exact defect being hunted
- A guard that passes is not a guard that works — three attempts to mutation-test one check,
  two of which would have permitted a false "verified"
- A broken config fails silently — no error, no output change, just work that ignores a rule
  you thought was in force
- Patching does not always converge: six rounds, roughly one new defect per round of repairs

Full detail with fixes in [`.agents/skills/cross-agent/SKILL.md`](.agents/skills/cross-agent/SKILL.md).

## Credits

Built on two articles, and worth reading in full:

- Rafferty Uy — [Claude Code, Copilot and Codex cross-compatibility](https://raffertyuy.com/raztype/claude-copilot-codex-cross-compatibility/) — the shared-file layout
- Nimbalyst — [Orchestrating Claude Code and Codex together](https://nimbalyst.com/blog/orchestrating-claude-code-and-codex-together/) — the handoff patterns and the read-only-reviewer rule

The failure modes are mine, learned the expensive way.

## Licence

MIT
