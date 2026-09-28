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

## The one rule

**The reviewer must not be able to write.**

```bash
codex exec --sandbox read-only "$(cat review-brief.md)" < /dev/null
```

A reviewer that can edit will quietly fix things instead of telling you about them, and you
lose the finding. The sandbox flag is what makes a review a review.

## What is actually in here

The two source articles cover the setup and the patterns well. What this adds is **seven
failure modes with numbers attached**, from running the setup through six adversarial review
rounds on a real project:

- Two agents in one directory produce **phantom findings** — a reviewer reading a file
  mid-write reported a defect that was already fixed
- Reviewer findings are claims: **4 of 43 did not survive a source check**
- The spec is the bug surface — an agent given a bad URL implemented it correctly and the
  result was broken
- **5 of 6 rounds** corrected a claim in one file and left it standing in a sibling
- Truncated grep output hid the exact defect being hunted
- A guard that passes is not a guard that works — three attempts to mutation-test one check,
  two of which would have permitted a false "verified"
- Patching does not always converge: six rounds, roughly one new defect per round of repairs

Full detail with fixes in [`.agents/skills/cross-agent/SKILL.md`](.agents/skills/cross-agent/SKILL.md).

## Credits

Built on two articles, and worth reading in full:

- Rafferty Uy — [Claude Code, Copilot and Codex cross-compatibility](https://raffertyuy.com/raztype/claude-copilot-codex-cross-compatibility/) — the shared-file layout
- Nimbalyst — [Orchestrating Claude Code and Codex together](https://nimbalyst.com/blog/orchestrating-claude-code-and-codex-together/) — the handoff patterns and the read-only-reviewer rule

The failure modes are mine, learned the expensive way.

## Licence

MIT
