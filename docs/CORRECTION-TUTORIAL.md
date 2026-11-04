# Tutorial: one owner correction, end to end

You will fix a wrong answer on the demo wiki and watch the fix become a permanent regression case. Model steps are played by the fixture files in `examples/correction-walkthrough/`; in real use a model in a fresh context fills each packet (recipe: `skills/kb-correct.md`). The fixture requires no network. Real correction duration is not yet measured.

**Setup.** Keep the default `.gitignore`. New lands save undo preimages in `KB/inbox/_objects/`; no git tracking of notes is needed. In a fresh demo copy:

```bash
./bootstrap.sh --owner sam --demo --no-verify    # use your own owner id
```

**The wrong answer.** The legacy correction ranker (`bin/kb query --keyword "marigolds pests"`) finds nothing, yet `companion-planting` holds the fact in its body. The owner says so.

```bash
W=examples/correction-walkthrough
bin/kb correct open --q "marigolds pests" --points-file $W/split.json \
  --owner-says "You missed it: companion planting says marigolds draw pests away, and the answer left it out."
bin/kb correct diagnose C-0001                   # label reachable-unretrieved; writes packets/conflict.json
bin/kb correct record C-0001 conflict --result $W/conflict.json
bin/kb correct record C-0001 compile  --result $W/compile.json   # gate: one page, <= 40 lines, lint clean
bin/kb correct record C-0001 review   --result $W/review.json
bin/kb correct validate C-0001                   # base misses, patched flips; prints a run-log row; stage validated
bin/kb correct land C-0001                       # files ONE proposal with kb-write; the wiki is untouched
```

A retrieval correction needs no replay: the tool ranks the base and the patched copy and checks the flip itself. An answer correction adds `replay` and `judge` steps (`validate` lists the packets).

**The owner lands it.** Read `KB/inbox/sam/…-correction-c-0001.md`, then:

```bash
bin/kb write land sam/2026-10-26-correction-c-0001 --endorsed-by sam
```

The land rebuilds the index, runs every check, writes a ledger row, then calls `kb-correct landed`. That re-reads the ledger row, compares its hash with the page on disk, and appends exactly one row to `evals/regressions.jsonl` (`origin: correction:C-0001`, `landed_version`, `ledger_seq`).

```bash
bin/kb eval --regressions evals/regressions.jsonl   # PASS; counts depend on your instance (exit 0)
```

**The discrimination proof.** Take the fix away and the case must fail:

```bash
bin/kb write unland sam/2026-10-26-correction-c-0001 --reason "discrimination proof" --endorsed-by sam
bin/kb eval --regressions evals/regressions.jsonl
# FAIL  <case-id> (correction:C-0001): expected stem not in top-10: ['companion-planting']   (exit 1)
```

Exit 1 shows the case catches the mistake it was written for. `unland` leaves the case in the file, so every later land fails until the proposal is landed again or the case is retired (`status: retired` with a `retired_reason`).

Before closing a loop, `bin/kb correct replay-all` writes replay and judge packets for every answer case, dormant ones included. Fill them, rerun until no result is pending (exit 0 all pass, 1 a case fails, 2 still waiting).

Judging is strict. A judge result is `{"verdict": "pass", "evidence": "<a span copied verbatim from the answer>", "points": [...]}`; `fail` and `unclear` are the other verdicts. Anything malformed, `unclear`, or without a span found in the answer counts as FAIL. Every verdict is bound to the wiki, the case and the tool source: change any of them and the verdict goes stale. A stale `validate` restarts (run it again), `land` exits 1, and `replay-all` asks for `--fresh`. `bin/kb eval --regressions` reports an answer case with no fresh verdict as `UNCHECKED` and `make verify` warns about it. That is honest, not a failure: rerun `replay-all`.

Two corrections to the same page on the same day work: the second post-image keeps today's `Updated` date.

## Guided execution

Run `bin/kb correct next C-0001` after each step. It reads state without advancing it, shows only the next packet, and prints the record command. `--write-template` creates an unfilled response file and refuses to overwrite it. A fresh worker receives only its packet; do not send the full guidance or earlier answers to a blind replay worker. No checks are skipped. Existing correction cases continue using their recorded legacy keyword method; the default user-facing hybrid query does not silently migrate them.
