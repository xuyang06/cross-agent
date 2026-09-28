# cross-agent

A skill for running **Claude Code and Codex together** on one repo: shared instructions and
skills, three handoff patterns, and the failure modes that actually bite.

Two agents are worth the trouble for one reason: **an agent reviewing work it did not write
has no stake in it.** Everything else is logistics around protecting that property.

## Install

```bash
git clone https://github.com/xuyang06/cross-agent.git
cd cross-agent && ./install.sh /path/to/your/repo
```

Idempotent and non-destructive — it never overwrites an existing `AGENTS.md` or `CLAUDE.md`,
and tells you what it skipped.

## What it sets up

One canonical source, thin vendor adapters:

| What | Canonical | Adapter |
|---|---|---|
| Instructions | `AGENTS.md` | `CLAUDE.md` → one line, `@AGENTS.md` |
| Skills | `.agents/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` → pointer |
| MCP servers | `.mcp.json` | `.codex/config.toml` `[mcp_servers]` |

Codex and Copilot read `AGENTS.md` and `.agents/` natively; Claude Code reads `CLAUDE.md` and
`.claude/`. Human-authored content lives in exactly one place.

This repo is laid out the same way, so it demonstrates what it documents.

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
| The shared instructions are actually loaded | an import test that parses like the importer |

## What is actually in here

The two source articles cover the setup and the patterns well. What this adds:

**A correction to the simple advice.** Claude Code reads `AGENTS.md` natively *only when no
`CLAUDE.md` exists* in the working directory or above. Most repos have one, so `AGENTS.md` is
silently ignored unless that file imports it — and if the import breaks, Claude loads nothing
and nothing errors. Split by audience too: moving a token `AGENTS.md` into place while the
real knowledge stays in `CLAUDE.md` gives the other agent nothing.

**The half nobody documents: shared state.** Claude accumulates memory across sessions; Codex
has none and starts every run cold; neither can read the other's. A decision in one agent's
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
