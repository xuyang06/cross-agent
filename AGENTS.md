# Agent instructions

Canonical instructions for every agent working in this repo. `CLAUDE.md` imports this file;
Codex and Copilot read it directly. **Edit here, never in the adapters.**

## What this repo is

A single skill, `cross-agent`, for running Claude Code and Codex together on one codebase:
shared context, three handoff patterns, and the failure modes that actually bite.

The repo also demonstrates the layout it documents — canonical content in `.agents/`, thin
adapters in `.claude/`. If you change the skill, change `.agents/skills/cross-agent/SKILL.md`.
The `.claude/` copy is a pointer and should stay one.

## House rules

- **The reviewer does not write.** Any review dispatched from here runs `--sandbox read-only`.
- **Verify before recording.** A finding from another agent is a claim. Check it against
  source — re-fetch external pages rather than reasoning about them.
- **Fix the document, not the passage.** When something is withdrawn or corrected, grep for
  what it named across the whole repo and fix every hit in the same commit.
- **Print greps untruncated** when hunting. Truncation hides the thing you are looking for.
- **Credit stays.** The two blog posts this is built on are named in the skill; keep them.
