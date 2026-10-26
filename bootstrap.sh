#!/usr/bin/env bash
# bootstrap.sh — create a second-brain instance in this folder. Safe to run again: it never
# overwrites a file that already exists.
#   ./bootstrap.sh                 asks for your owner id
#   ./bootstrap.sh --owner sam     no prompt
#   ./bootstrap.sh --demo          start from the example wiki instead of one welcome page
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
OWNER=""; DEMO=0; VERIFY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --owner) OWNER="${2:-}"; shift 2 ;;
    --owner=*) OWNER="${1#*=}"; shift ;;
    --demo) DEMO=1; shift ;;
    --no-verify) VERIFY=0; shift ;;
    -h|--help) sed -n 2,7p "$0"; exit 0 ;;
    *) echo "bootstrap: unknown option $1" >&2; exit 1 ;;
  esac
done

say() { printf '  %s\n' "$*"; }
echo "second-brain-loop bootstrap"

# 1. prerequisites
command -v python3 >/dev/null || { echo "need python3 (3.9 or newer)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "need python3 >= 3.9, found $(python3 -V 2>&1)" >&2; exit 1; }
command -v git >/dev/null || { echo "need git (unland reads earlier page versions from it)" >&2; exit 1; }
say "python3 $(python3 -c 'import platform; print(platform.python_version())') and git found"

# 2. owner id + config
if [ ! -f KB/kb.json ]; then
  if [ -z "$OWNER" ]; then
    if [ -t 0 ]; then read -r -p "  Your owner id (lowercase, e.g. sam): " OWNER; else OWNER="owner"; fi
  fi
  [[ "$OWNER" =~ ^[a-z][a-z0-9_-]{1,31}$ ]] || { echo "owner id must be lowercase letters/digits/-/_, 2-32 chars, start with a letter" >&2; exit 1; }
  mkdir -p KB
  python3 - "$OWNER" <<'PY'
import json, sys
cfg = json.load(open("kb.example.json"))
cfg["owner"] = sys.argv[1]
open("KB/kb.json", "w").write(json.dumps(cfg, indent=2) + "\n")
PY
  say "wrote KB/kb.json (owner: $OWNER)"
else
  say "KB/kb.json exists, kept"
fi

# 3. folders + seed content (copy only what is missing)
mkdir -p KB/wiki KB/RAW KB/inbox KB/output evals
if [ "$DEMO" -eq 1 ]; then WSRC=examples/demo-wiki; RSRC=examples/demo-raw; ESRC=examples/demo-retrieval-eval.json
else WSRC=templates/starter-wiki; RSRC=templates/starter-raw; ESRC=templates/starter-retrieval-eval.json; fi
if [ -z "$(ls -A KB/wiki)" ]; then
  cp -R "$WSRC"/. KB/wiki/; cp -R "$RSRC"/. KB/RAW/; cp "$ESRC" KB/output/retrieval-eval.json
  say "seeded KB/wiki from $WSRC"
else
  say "KB/wiki has pages, kept"
fi
[ -f KB/output/retrieval-eval.json ] || cp "$ESRC" KB/output/retrieval-eval.json
[ -f KB/SYSTEM.md ] || { cp templates/SYSTEM.md KB/SYSTEM.md; say "wrote KB/SYSTEM.md (doctrine)"; }
[ -f evals/regressions.jsonl ] || { cp templates/regressions.jsonl evals/regressions.jsonl; say "wrote evals/regressions.jsonl"; }

# 4. git (unland restores exact earlier bytes from git history)
if [ ! -d .git ]; then git init -q; say "git init"; fi
if ! git rev-parse -q --verify HEAD >/dev/null; then
  git add -A && git -c user.name="${GIT_AUTHOR_NAME:-bootstrap}" -c user.email="${GIT_AUTHOR_EMAIL:-bootstrap@localhost}" \
    commit -q -m "initial commit" && say "first commit"
fi

# 5. derived files + seal
python3 tools/kb-index.py >/dev/null && python3 tools/kb-graph.py >/dev/null && say "built search index + graph"
if [ ! -f KB/inbox/_seal.json ]; then
  python3 tools/kb-write.py seal >/dev/null && say "sealed KB/wiki (every page hash recorded)"
else
  say "seal exists, kept"
fi

# 6. verify
if [ "$VERIFY" -eq 1 ]; then echo; bash scripts/verify.sh; fi
