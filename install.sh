#!/usr/bin/env bash
# Install the cross-agent skill into a target repo, plus the adapters that let
# Claude Code, Codex and Copilot read one shared source.
#
#   ./install.sh /path/to/your/repo
#
# Idempotent and non-destructive: it never overwrites an existing AGENTS.md or
# CLAUDE.md, and says what it skipped.
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ] || [ ! -d "$TARGET" ]; then
  echo "usage: ./install.sh /path/to/repo" >&2
  exit 1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET="$(cd "$TARGET" && pwd)"

if [ "$SRC" = "$TARGET" ]; then
  echo "refusing to install into myself" >&2
  exit 1
fi

say() { printf '  %s\n' "$1"; }

# 1. The canonical skill.
mkdir -p "$TARGET/.agents/skills/cross-agent"
cp "$SRC/.agents/skills/cross-agent/SKILL.md" "$TARGET/.agents/skills/cross-agent/SKILL.md"
say "installed .agents/skills/cross-agent/SKILL.md"

# 2. The Claude Code adapter. Thin on purpose — a second copy of the content is
#    the drift bug the skill itself warns about.
mkdir -p "$TARGET/.claude/skills/cross-agent"
cp "$SRC/.claude/skills/cross-agent/SKILL.md" "$TARGET/.claude/skills/cross-agent/SKILL.md"
say "installed .claude/skills/cross-agent/SKILL.md (adapter)"

# 3. AGENTS.md — create only. Yours is yours.
if [ -e "$TARGET/AGENTS.md" ]; then
  say "AGENTS.md exists, left alone"
else
  cat > "$TARGET/AGENTS.md" <<'EOF'
# Agent instructions

Canonical instructions for every agent in this repo. `CLAUDE.md` imports this file; Codex
and Copilot read it directly. Edit here, never in the adapters.

## House rules

- **The reviewer does not write.** Reviews run `--sandbox read-only`.
- **Verify before recording.** A finding from another agent is a claim until checked against
  source. Re-fetch external pages rather than reasoning about them.
- **Fix the document, not the passage.** When something is withdrawn, grep for what it named
  across the repo and fix every hit in the same commit.

See `.agents/skills/cross-agent/SKILL.md` for the handoff patterns and failure modes.
EOF
  say "created AGENTS.md"
fi

# 4. CLAUDE.md — append the import if a file already exists, so we never clobber.
if [ -e "$TARGET/CLAUDE.md" ]; then
  if grep -q '^@AGENTS\.md' "$TARGET/CLAUDE.md"; then
    say "CLAUDE.md already imports AGENTS.md"
  else
    printf '\n@AGENTS.md\n' >> "$TARGET/CLAUDE.md"
    say "appended @AGENTS.md to existing CLAUDE.md"
  fi
else
  printf '@AGENTS.md\n' > "$TARGET/CLAUDE.md"
  say "created CLAUDE.md importing AGENTS.md"
fi

# 5. Codex MCP mirror, only if the repo actually uses MCP.
if [ -e "$TARGET/.mcp.json" ] && [ ! -e "$TARGET/.codex/config.toml" ]; then
  say "note: .mcp.json found but no .codex/config.toml —"
  say "      Codex needs the same servers mirrored under [mcp_servers] in TOML"
fi

echo
say "done. Next: read .agents/skills/cross-agent/SKILL.md before dispatching anything."
