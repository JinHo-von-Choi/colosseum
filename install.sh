#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/colosseum"

mkdir -p "$SKILL_DIR"
ln -sf "$REPO_DIR/skills/colosseum/SKILL.md" "$SKILL_DIR/SKILL.md"

echo "colosseum installed → $SKILL_DIR"
echo "Update: git pull (symlink reflects changes immediately)"
