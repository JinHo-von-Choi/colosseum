#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills/colosseum"
DEST="$HOME/.claude/skills/colosseum"

if [ ! -f "$SRC/SKILL.md" ]; then
  echo "SKILL.md not found under $SRC" >&2
  exit 1
fi

# Earlier versions installed a real directory holding only a SKILL.md symlink.
if [ -d "$DEST" ] && [ ! -L "$DEST" ]; then
  if [ "$(find "$DEST" -mindepth 1 -maxdepth 1 | wc -l)" -eq 1 ] && [ -L "$DEST/SKILL.md" ]; then
    rm "$DEST/SKILL.md" && rmdir "$DEST"
  else
    echo "$DEST exists and is not a previous colosseum install; move it away first" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$DEST")"
ln -sfn "$SRC" "$DEST"

echo "colosseum installed → $DEST"
echo "Update: git pull (symlink reflects changes immediately)"
echo "Note: hooks and the colosseum:participant agent load only with the plugin install."
