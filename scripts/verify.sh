#!/usr/bin/env bash
# verify.sh — standalone health check for a second-brain instance. Exit = number of FAILs.
# WARN lines are reported but never fail the run. Zero network, zero model calls.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
FAILS=0; WARNS=0
pass() { echo "PASS  $*"; }
warn() { echo "WARN  $*"; WARNS=$((WARNS + 1)); }
fail() { echo "FAIL  $*"; FAILS=$((FAILS + 1)); }
indent() { sed 's/^/       /'; }
REG="$(python3 -c 'import sys; sys.path.insert(0, "tools"); import kb_config; print(kb_config.rel(".", "regressions"))')"

if [ ! -d KB/wiki ]; then fail "no instance: run ./bootstrap.sh first"; echo "RESULT: $FAILS fail(s), $WARNS warn(s)"; exit "$FAILS"; fi

START_STATE=$(python3 tools/kb-workflow.py state-hash) || { fail "cannot capture verification inputs"; exit 1; }

# 1. graph freshness + retrieval eval
OUT=$(python3 tools/kb-graph.py --check 2>&1); RC=$?
case $RC in 0) pass "kb-graph: matches wiki content hashes" ;; 2) echo "$OUT" | indent; warn "kb-graph stale: run bin/kb index" ;; *) echo "$OUT" | indent; fail "kb-graph unreadable" ;; esac
OUT=$(python3 tools/kb-eval.py --check 2>&1)
if [ $? -eq 0 ]; then pass "retrieval eval: $(echo "$OUT" | tail -1)"; else echo "$OUT" | indent; fail "retrieval eval regressed"; fi

# 1b. provenance: raw source hashes, index/graph built from this wiki, derived caches fresh
OUT=$(python3 tools/kb-provenance.py --check 2>&1); RC=$?
case $RC in
  0) pass "provenance: sources hashed + present, index/graph/caches built from the current wiki" ;;
  2) echo "$OUT" | grep -v '^PASS' | indent; warn "provenance: stale or legacy derived output (fix commands above)" ;;
  *) echo "$OUT" | grep -v '^PASS' | indent; fail "provenance: missing/drifted source or corrupt index" ;;
esac

# 2. header contract
OUT=$(python3 tools/kb-lint.py 2>&1); RC=$?
case $RC in 0) pass "kb-lint: header contract clean" ;; 2) pass "kb-lint: 0 FAIL, warnings: $(echo "$OUT" | grep -oE 'WARN [0-9]+' | head -1)" ;; *) echo "$OUT" | indent; fail "kb-lint: header contract" ;; esac

# 3. write-back provenance
OUT=$(python3 tools/kb-lint.py --rule WP1 2>&1); RC=$?
if [ $RC -eq 0 ]; then pass "WP1: every wiki hash matches its ledger or seal entry"
elif [ $RC -eq 2 ]; then echo "$OUT" | indent; warn "WP1: unrecorded wiki change (adopt it: bin/kb write land --adopt PATH --reason R --endorsed-by OWNER)"
else echo "$OUT" | indent; fail "WP1"; fi
OUT=$(python3 tools/kb-lint.py --rule WP2 2>&1)
if [ $? -eq 0 ]; then pass "WP2: inbox files parse, known keys, agent folders, state = ledger"; else echo "$OUT" | indent; fail "WP2: inbox contract"; fi

# 3b. retained undo preimages
OUT=$(python3 tools/kb-workflow.py undo-health 2>&1)
if [ $? -eq 0 ]; then pass "undo: required preimages available"; else echo "$OUT" | indent; fail "undo: missing or corrupt preimages"; fi

OUT=$(python3 tools/kb-workflow.py signature-health 2>&1)
if [ $? -eq 0 ]; then pass "signed approvals: retained receipts verify"; else echo "$OUT" | indent; fail "signed approval receipt mismatch"; fi

# 4. regressions
if [ -f "$REG" ]; then
  OUT=$(python3 tools/kb-eval.py --regressions "$REG" 2>&1)
  if [ $? -eq 0 ]; then pass "regressions: $(echo "$OUT" | tail -1 | sed 's/^PASS  //')"; else echo "$OUT" | indent; fail "regressions"; fi
  UNCHECKED=$(echo "$OUT" | tail -1 | grep -oE '[0-9]+ answer UNCHECKED' | grep -oE '^[0-9]+')
  if [ "${UNCHECKED:-0}" -gt 0 ]; then warn "regressions: $UNCHECKED answer case(s) UNCHECKED (no fresh verdict; run bin/kb correct replay-all)"; fi
else warn "regressions: $REG absent"; fi

# 5. test suites
for t in tests/test-kb-*.py; do
  case "$t" in *test-kb-loop-e2e.py) continue ;; esac
  OUT=$(python3 "$t" 2>&1)
  if [ $? -eq 0 ]; then pass "$(basename "$t"): $(echo "$OUT" | grep -E '^Ran [0-9]+ tests' | head -1)"
  else echo "$OUT" | tail -20 | indent; fail "$(basename "$t")"; fi
done

# 6. no network, no model calls in shipped tools
HITS=$(grep -lE '(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://' tools/*.py bin/kb 2>/dev/null)
if [ -z "$HITS" ]; then pass "no-network: tools import no network client and call no URL"; else echo "$HITS" | indent; fail "no-network"; fi

# 7. LOOP-E2E, last: the whole loop on a throwaway copy, plus the discrimination proof (spec §0, §1.5 block 20)
OUT=$(python3 tests/test-kb-loop-e2e.py 2>&1)
if [ $? -eq 0 ]; then pass "LOOP-E2E: correct -> land -> regressions green -> unland -> case FAILs ($(echo "$OUT" | grep -E '^Ran [0-9]+ tests' | head -1))"
else echo "$OUT" | tail -20 | indent; fail "LOOP-E2E: test-kb-loop-e2e.py"; fi

if [ "$FAILS" -eq 0 ]; then
  OUT=$(python3 tools/kb-workflow.py checkpoint --expected-state "$START_STATE" 2>&1)
  if [ $? -eq 0 ]; then pass "verification checkpoint saved (not human approval)"; else echo "$OUT" | indent; fail "verification inputs changed; checkpoint not saved"; fi
fi

echo "---"
echo "RESULT: $FAILS fail(s), $WARNS warn(s)"
exit "$FAILS"
