#!/usr/bin/env bash
# Throwaway playground: copy this package to a temp folder, set up the demo there, run every check.
# Your real folder is never touched. Delete the sandbox any time with: rm -rf <printed path>
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$(mktemp -d "${TMPDIR:-/tmp}/kb-sandbox.XXXXXX")}"
git clone -q "$SRC" "$DEST/repo" 2>/dev/null || cp -R "$SRC" "$DEST/repo"
cd "$DEST/repo"
rm -rf KB evals agents
./bootstrap.sh --owner sandbox --demo >/dev/null
echo "== verify";  make -s verify | tail -1
echo "== tests";   make -s test | grep -c '^PASS' | xargs -I{} echo "{} suites PASS"
cat <<MSG

Sandbox ready: $DEST/repo
  cd "$DEST/repo"
  Then follow QUICKSTART.md from step 4 (owner id is "sandbox").
  Throw it away:  rm -rf "$DEST"
MSG
