---
name: cross-agent
description: Run Claude Code and Codex together on one repo — shared instructions, a shared decision log, the three handoff patterns (cross-agent review, sequential plan→implement, parallel race), and eight failure modes with fixes. Covers why agent memory is private and asymmetric, and why anything that must hold belongs in a test rather than an instruction. Use when setting up two agents on a project, dispatching work to a second agent, or reviewing a diff a different agent wrote.
---

# Working with a second agent

Two agents are worth the trouble for exactly one reason: **an agent reviewing work it did not
write has no stake in it.** Everything else here is logistics around protecting that property.

Two rules carry most of the value:

1. **The reviewer must not be able to write.** A reviewer that can edit will quietly fix
   things instead of telling you about them, and you lose the finding.
2. **If a rule matters, write the test, not the instruction.** Instructions are advisory and
   the other agent starts every run cold. A test binds both agents and you.

---

## 1. Share the context, once

Keep every piece of human-authored instruction in exactly one place. Vendor directories hold
thin adapters, nothing else.

| What | Canonical | Adapter |
|---|---|---|
| Instructions | `AGENTS.md` (repo root) | `CLAUDE.md` containing one line: `@AGENTS.md` |
| Skills | `.agents/skills/<name>/` | `.claude/skills/<name>` — a symlink to `../../.agents/skills/<name>` |
| MCP servers | `.mcp.json` (repo root) | `.codex/config.toml` `[mcp_servers]` mirror |

Codex and Copilot read `AGENTS.md` and `.agents/skills/` natively. Claude Code reads
`CLAUDE.md` and `.claude/skills/`. The adapters make one source serve all three.

### The import is not optional, and its failure is silent

Claude Code *can* read `AGENTS.md` directly, but **only when no `CLAUDE.md` exists in the
working directory or above it.** If the repo has a `CLAUDE.md` — most do — then `AGENTS.md`
is ignored unless that file imports it. Direct reading also needs a recent version; the
import works regardless, which is why it is the layout above.

**The failure mode is the dangerous part.** If the import line is deleted, renamed, or
wrapped in backticks, Claude loads `CLAUDE.md` alone and quietly loses every shared
instruction. Nothing errors. No output changes. You find out weeks later from a session that
behaves oddly.

So do not leave it to inspection. Assert it, and parse the way the importer does — it skips
fenced blocks and code spans, so a naive substring check passes on an import that never
loads:

```python
body = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))
assert re.search(r"^@AGENTS\.md\s*$", body, flags=re.M)
```

`check_shared_config.py` next to this file runs that assertion plus the other silent
breakages: a skill stub instead of a symlink, an absolute symlink, an `AGENTS.override.md`
(Codex reads it instead of `AGENTS.md`; Claude does not), an `AGENTS.md` over Codex's 32 KiB
read limit, and shared files that `.gitignore` keeps out of clones. Run it from the repo root,
in CI or a test. Add `--live` to ask the real `claude` and `codex` what they actually loaded.

### A skill stub does not import

`@path` expands in `CLAUDE.md` and `AGENTS.md`, **not in `SKILL.md`**. A Claude skill stub
whose body is `@../../../.agents/skills/<name>/SKILL.md` loads as that literal line: Claude
gets the frontmatter and a path, and has to decide on its own to open it. Its description is
also a second copy that drifts from the canonical one. Symlink the skill directory instead;
Claude Code follows symlinked project skills, and there is one file to edit. On Windows,
clone with `core.symlinks` enabled or the link checks out as a one-line text file.

**Split by audience, not by convenience.** If your `CLAUDE.md` already holds real project
knowledge, moving a token file into `AGENTS.md` and leaving the content behind gives the
other agent nothing. Shared knowledge goes in `AGENTS.md`; only what has no counterpart in
the other tool — slash-command routing, Claude-specific subagents — stays in the adapter.

**Stays tool-specific and cannot be shared:** subagent definitions, hooks, path-scoped rules,
permission settings. Do not fight this — reference the shared instructions from inside them.

`install.sh` in this repo writes the adapters into a target repo without clobbering existing
content.

---

## 1b. Shared state: agent memory is private and asymmetric

Sharing instructions is the easy half. **Decisions are the half that rots.**

Claude Code accumulates durable state across sessions — auto memory, and whatever your
tooling logs. Codex's `memories` feature is off by default, so a typical `codex exec` starts
cold with only the files in the repo. Turned on or not, neither can read the other's store. So a decision recorded in one agent's memory is one the
other will unknowingly relitigate or contradict.

In the project these notes come from, **20 logged decisions sat outside the repo** where the
second agent could not see them. The sharpest example was a memory file recording *how to
work with Codex* — which Codex could not read.

**Keep a `DECISIONS.md` in the repo.** Newest first, append-only, never edited — supersede an
entry and say what it replaces. Record durable calls only: architecture, scope, a tool or
vendor choice, a reversal, or a rule that binds future work.

The test for whether something belongs: *would an agent six weeks from now waste an hour, or
do the wrong thing, for not knowing this?*

`git log` is the other shared channel and is underrated — both agents can read it, and a
detailed commit message is a decision record that costs nothing extra.

---

## 1c. Instructions are advisory. Enforcement lives in the repo.

Everything above is a request an agent can skip, and nothing notices when it does. Asking the
other agent to *remember* a rule fails by construction: it starts every run cold.

**If a rule matters, write the test.** Both agents run the suite, so a test binds both of them
and you. Decisions worth keeping become assertions:

| Decision | Enforced as |
|---|---|
| This package stays framework-free | a test that imports it and fails on the dependency |
| The public page serves X, never Y | a test asserting the served content |
| Colour lives in tokens, not literals | a test scanning for raw hex outside the token block |
| The shared instructions are actually loaded | the import test above |

A hook can enforce more for one vendor, but a test is the only mechanism that binds every
agent and every human without configuration on either side.

---

## 2. Three patterns, in order of value

### Cross-agent review — the reason to run two vendors

One agent implements. The other reviews the diff **with no prior context and no write
access**.

```bash
# Codex reviewing, read-only. It physically cannot edit.
codex exec --sandbox read-only "$(cat review-brief.md)" < /dev/null
```

Give the reviewer a brief that names what to attack, not "review this". A brief that says
"check whether X is sound" gets a real answer; "any thoughts?" gets agreement.

### Sequential: one plans, the other implements

The planning agent writes a plan you actually read. The implementing agent gets that plan as
its brief. The value is the artifact in the middle — if you would not read the plan, this
pattern is just latency.

### Parallel race

Both agents attempt a genuinely uncertain task on **separate worktrees**, keep the better
result. Only worth it when you cannot predict which approach works.

```bash
git worktree add ../proj-codex -b attempt/codex
```

**Do not skip the worktree.** Two agents in one working directory collide, and the collision
is silent — see failure mode 1.

---

## 3. Failure modes

These are observed, not hypothetical. The numbers come from a single project that ran this
setup through six adversarial review rounds.

### 1. Two agents in one directory produce phantom findings

A reviewer read a file while the implementer was mid-write and reported a defect that had
already been fixed. It looked exactly like a real finding.

**Fix:** one agent per worktree, or run them strictly in sequence. If you must overlap, the
reviewer gets `--sandbox read-only` and you treat any finding about a file the other agent
touched as suspect until re-checked.

### 2. Reviewer findings are claims, not facts

Roughly **4 of 43 findings across six rounds did not survive a source check.** Some were
confidently worded and wrong.

**Fix:** verify before recording. For claims about external sources, **re-fetch the page** —
do not reason about what it probably says. A finding you cannot ground is worse than no
finding, because it enters your notes with the authority of review.

### 3. The spec is the bug surface

An implementing agent was given a URL that silently returned only half the expected data. It
implemented exactly what was specified, correctly, and the result was broken.

**Fix:** verify the facts in your brief before you send it. When the output is wrong, check
the brief before blaming the agent. It usually did what you asked.

### 4. Fixing the passage is not fixing the document

In **5 of 6 rounds**, a claim was corrected in one file and left standing in a sibling. Twice
in the same file being edited.

**Fix:** when you withdraw or change something, grep for what it *named* — the nouns, the
quoted phrase, the number — across the whole repo, then fix every hit in the same commit.
Fixing the instance in front of you is the single most common way this goes wrong.

### 5. Truncated output lies

`grep ... | cut -c1-165` hid the exact defect being hunted; the line looked like an unrelated
match. Separately, a summarising fetch returned only each item's first sentence, which made
two accurate quotations look fabricated and nearly produced a false accusation.

**Fix:** inventory greps print untruncated, or match on the specific fragment. When a tool
summarises, read the source before acting on the summary.

### 6. A guard that passes is not a guard that works

Three attempts were needed to mutation-test one check. The first mutation targeted a property
the code did not reference and the script reported success anyway; the second produced a
compile error. **Both would have let a "verified" claim be made on no evidence.**

**Fix:** after mutating, confirm the mutation *applied* and that the failure is an assertion
failure, not a build error. Then restore and confirm green.

### 7. A broken config fails silently, not loudly

An import that stops resolving, a skill stub whose `@` import was never expanded, a rule that only ever
lived in one agent's private memory — none of these raise an error. The agent simply proceeds
without the context, competently and wrongly, and the first symptom is work that ignores a
rule you thought was in force.

**Fix:** every piece of shared config gets an assertion. If you cannot see it fail, you cannot
tell it is working. See 1c.

### 8. Patching does not always converge

Six review rounds on one document: 7 findings, then 6, then 10, then 1, then 8, then 6 —
with roughly one new defect introduced per round of repairs. The count of claims fell 21 → 16
as unsupportable ones were removed.

**Fix:** if round N+1 keeps finding defects introduced in round N, the problem is not the
individual claims. Something structural is wrong — usually scope or framing that the evidence
cannot carry. Cut the scope instead of patching again.

---

## 4. Practical notes

**Dispatch long runs in the background.** A foreground agent call that exceeds the tool
timeout is killed with nothing committed.

```bash
codex exec --sandbox workspace-write "$(cat brief.md)" < /dev/null > run.log 2>&1 &
```

`< /dev/null` matters — without stdin closed, the agent may wait for input that never comes.

**Sandbox flags set the role.**

| Role | Flag |
|---|---|
| Reviewer | `--sandbox read-only` |
| Implementer | `--sandbox workspace-write` |
| Implementer, inside a container or VM you already isolate | `--dangerously-bypass-approvals-and-sandbox` |

The reviewer flag is not a formality. It is what makes the review a review. The bypass flag
is the opposite: Codex's own help reserves it for externally sandboxed environments.

**Ask for disagreement explicitly.** Briefs should say: *if this is fine, say so plainly; do
not manufacture findings to appear rigorous, and do not soften to be agreeable.* Without it
you get both failure modes, sometimes in the same response.

**Do not hard-code which model is better at what.** Both vendors ship updates faster than
anyone republishes a comparison. Route on properties you can observe today — who has the
context, who has write access — not on a remembered benchmark.

---

## Credits

The file-sharing layout follows Rafferty Uy, *Claude Code, Copilot and Codex
cross-compatibility*. The three handoff patterns and the read-only-reviewer rule follow
Nimbalyst, *Orchestrating Claude Code and Codex together*. The failure modes are from
running the setup in anger.
