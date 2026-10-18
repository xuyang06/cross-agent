# Decisions

Newest first. Append only: to reverse one, add an entry that says what it supersedes.

## 2026-10-17 — The session-start hook wires broken projects itself

Supersedes "the hook only reports" below. Users want the setup to run without them, so
reporting a fix and waiting for someone to run it was the gap. The hook now runs the
per-repo install when it finds a problem the install can fix. Three guards keep that safe:

- **It never commits.** Every change shows up in `git status` and can be reviewed or reverted.
- **It skips files with uncommitted edits**, so its changes never mix with work in progress.
- **In a repo you have never committed to, it uses `--local`**, which changes only untracked
  files. A repo with no commits counts as yours.

It holds a lock in `.git` so Claude and Codex starting together do not both run it. It says
"wired" only when a problem actually went away. Keeping later `CLAUDE.md` edits in sync stays
manual: rewriting migrated repos in place was the feature cut after review round 3.

## 2026-10-17 — The system install adds a session-start hook, not a background job

New projects need no install step: a global rule tells both agents where instructions go,
and a hook in both agents flags any project whose shared config is broken, naming the fix.
The hook only reports; it never edits a repo on its own. It also regenerates
`~/.codex/AGENTS.md`, so editing `~/.claude/rules` reaches Codex without a manual step.

## 2026-10-17 — `~/.codex/AGENTS.md` is generated from `~/.claude/rules`

Codex has no import syntax, so a copy is unavoidable. A generated copy with one source does
not drift; a hand-kept one does. The generator skips Claude-only rules (`agents.md`,
`hooks.md`, `performance.md`) and refuses to overwrite a file it did not write.

## 2026-10-17 — Migration splits `CLAUDE.md` by audience, section by section

Shared `## ` sections move to `AGENTS.md` verbatim. Claude-only sections (skill routing, GBrain
guidance) stay. So do sections a Claude-side tool parses in `CLAUDE.md` by heading — gstack
greps it for Testing, Deploy Configuration and Health Stack — because moving them breaks the
tool; `AGENTS.md` lists them under `## Kept in CLAUDE.md` rather than copying them, since a
copy drifts. Upstream clones use `--local` and keep tracked files untouched.

## 2026-10-17 — Two Codex review rounds before touching real repos

The first round found 14 defects, several of which would have deleted user content; the
second found 4, one introduced by the fixes; the third found 6, all in a new feature that
rewrote already-migrated repos in place. That is failure mode 8, so the feature was cut, not
patched: migration now runs once, appends only, and never deletes a line. Each finding has a
regression test in `tests/test_install.py`, mutation-checked to fail on an assertion.

## 2026-10-17 — Skill adapters are symlinks, not `@` stubs

Claude Code does not expand `@` imports inside `SKILL.md`; the stub loaded as a bare path.
Verified by invoking it. Both agents follow symlinked skill folders.
