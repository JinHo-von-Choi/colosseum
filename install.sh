#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/colosseum"

if [ ! -f "$REPO_DIR/skills/colosseum/SKILL.md" ]; then
  echo "SKILL.md not found under $REPO_DIR/skills/colosseum" >&2
  exit 1
fi

mkdir -p "$SKILL_DIR"
ln -sf "$REPO_DIR/skills/colosseum/SKILL.md" "$SKILL_DIR/SKILL.md"

echo "colosseum installed → $SKILL_DIR"
echo "Update: git pull (symlink reflects changes immediately)"
