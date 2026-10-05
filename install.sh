#!/bin/bash
# Manual install: links skills/colosseum into ~/.claude/skills/colosseum.
#
#   ./install.sh               install the checked-out version
#   ./install.sh --ref v3.2.0  check out a tag or commit first (the working tree must be clean)
#
# Never overwrites anything it did not create. A regular file, a directory, a link to
# another place, or a broken link at the destination stops the install with a message.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills/colosseum"
DEST="${COLOSSEUM_INSTALL_DEST:-$HOME/.claude/skills/colosseum}"
REF=""

while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?--ref needs a tag or commit}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

conflict() {
  echo "conflict: $DEST $1" >&2
  echo "Nothing was changed. Move it away (for example: mv \"$DEST\" \"$DEST.bak\") and run install.sh again." >&2
  exit 1
}

if [ -n "$REF" ]; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain)" ]; then
    echo "the working tree has local changes; commit or stash them before --ref" >&2
    exit 1
  fi
  git -C "$REPO_DIR" checkout --quiet --detach "$REF"
fi

if [ ! -f "$SRC/SKILL.md" ]; then
  echo "SKILL.md not found under $SRC" >&2
  exit 1
fi

if [ -L "$DEST" ]; then
  target="$(readlink "$DEST")"
  if [ "$target" = "$SRC" ]; then
    echo "already installed"
  elif [ ! -e "$DEST" ]; then
    conflict "is a broken link to $target"
  else
    conflict "is a link to $target, not to this checkout"
  fi
elif [ -d "$DEST" ]; then
  # Earlier versions installed a real directory holding only a SKILL.md link into this repo.
  entries="$(find "$DEST" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
  if [ "$entries" = "1" ] && [ -L "$DEST/SKILL.md" ] && [ "$(readlink "$DEST/SKILL.md")" = "$SRC/SKILL.md" ]; then
    rm "$DEST/SKILL.md"
    rmdir "$DEST"
    ln -s "$SRC" "$DEST"
    echo "replaced the SKILL.md-only install from an earlier version"
  else
    conflict "is a directory that this installer did not create"
  fi
elif [ -e "$DEST" ]; then
  conflict "is a file"
else
  mkdir -p "$(dirname "$DEST")"
  ln -s "$SRC" "$DEST"
fi

version="$(git -C "$REPO_DIR" describe --tags --always --dirty 2>/dev/null || echo unknown)"
commit="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "colosseum installed: $DEST -> $SRC"
echo "version: $version ($commit)"
echo "Roll back: ./install.sh --ref <earlier tag or commit>"
echo "Note: hooks and the colosseum:participant and colosseum:cli-proxy agents load only with the plugin install."
