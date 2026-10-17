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

# 1. The canonical skill, with its config check.
mkdir -p "$TARGET/.agents/skills/cross-agent"
cp "$SRC/.agents/skills/cross-agent/"{SKILL.md,check_shared_config.py} "$TARGET/.agents/skills/cross-agent/"
say "installed .agents/skills/cross-agent/"

# 2. The Claude Code adapter: a symlink. Claude does not expand @ imports in
#    SKILL.md, and a copied file is the drift bug the skill warns about.
LINK="$TARGET/.claude/skills/cross-agent"
if [ -L "$LINK" ]; then
  say ".claude/skills/cross-agent already a symlink, left alone"
elif [ -e "$LINK" ]; then
  say ".claude/skills/cross-agent exists and is not a symlink, left alone —"
  say "      replace it: ln -s ../../.agents/skills/cross-agent .claude/skills/cross-agent"
else
  mkdir -p "$TARGET/.claude/skills"
  ln -s ../../.agents/skills/cross-agent "$LINK"
  say "linked .claude/skills/cross-agent -> .agents/skills/cross-agent"
fi

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

Before committing, run `python3 .agents/skills/cross-agent/check_shared_config.py`.
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

# 6. Prove it loads. A grep for @AGENTS.md above also matches one inside a code
#    fence, which Claude skips; the check parses like the importer.
echo
if python3 "$TARGET/.agents/skills/cross-agent/check_shared_config.py" "$TARGET"; then
  say "done. Next: read .agents/skills/cross-agent/SKILL.md before dispatching anything."
else
  say "installed, but the shared config will not load as-is — fix the FAIL lines above"
  exit 1
fi
