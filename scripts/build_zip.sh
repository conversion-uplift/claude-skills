#!/usr/bin/env bash
# Builds dist/chrome-tracking-check.zip for upload in Claude
# (Customize -> Skills -> + -> Create skill -> Upload a skill).
# The ZIP holds one folder whose name matches the skill name.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=plugins/chrome-tracking-check/skills/chrome-tracking-check
mkdir -p dist
rm -f dist/chrome-tracking-check.zip
find "$SRC" -name __pycache__ -type d -prune -exec rm -rf {} +
(cd "$(dirname "$SRC")" && zip -qr -X "$OLDPWD/dist/chrome-tracking-check.zip" chrome-tracking-check \
  -x "*/__pycache__/*" "*.pyc" "*/.DS_Store")
echo "Built dist/chrome-tracking-check.zip"
unzip -l dist/chrome-tracking-check.zip | tail -1
