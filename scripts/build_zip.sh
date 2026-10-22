#!/usr/bin/env bash
# Builds dist/<skill>.zip for upload in Claude
# (Customize -> Skills -> + -> Create skill -> Upload a skill).
# Each ZIP holds one folder whose name matches the skill name.
# Usage: scripts/build_zip.sh [skill-name ...]   (no arguments builds every skill)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
if [ "$#" -eq 0 ]; then
  set -- $(ls plugins)
fi
for NAME in "$@"; do
  SRC="plugins/$NAME/skills/$NAME"
  if [ ! -f "$SRC/SKILL.md" ]; then
    echo "No skill found at $SRC" >&2
    exit 1
  fi
  rm -f "dist/$NAME.zip"
  find "$SRC" -name __pycache__ -type d -prune -exec rm -rf {} +
  (cd "$(dirname "$SRC")" && zip -qr -X "$OLDPWD/dist/$NAME.zip" "$NAME" \
    -x "*/__pycache__/*" "*.pyc" "*/.DS_Store")
  echo "Built dist/$NAME.zip"
  unzip -l "dist/$NAME.zip" | tail -1
done
