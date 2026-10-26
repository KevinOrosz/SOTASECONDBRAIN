# Skill: kb-correct

**Use when:** the owner says a brain answer was wrong. **Tool:** `tools/kb-correct.py` (zero LLM calls). **Doctrine:** `KB/SYSTEM.md` § Correction Protocol (the only home of the rules; this file is the recipe).

The tool never calls a model. It writes one packet per model step under `KB/inbox/_corrections/C-NNNN/packets/`, a harness gives each packet to a fresh model context, and the answer goes back through `record`. Pass **pointers only**: the packet path in, the result file path out. Never paste packet contents, the owner's words, or earlier results into another step's prompt.

## Packet → tier

| Step | Packet | Tier | Fresh context | Result file shape |
|---|---|---|---|---|
| split | none (the owner's verbatim + the question) | low | yes | `{"points":[],"forbidden":[],"named_stems":[],"terms":[]}`; the owner sees the split |
| conflict | `packets/conflict.json` | mid | yes | `{"conflict":bool,"primary":[{"path","line"}],"reason"}` |
| compile | `packets/compile.json` | mid; attempt 2 high | yes | `{"files":{"KB/wiki/...md":"<whole post-image>"}}` |
| review | `packets/review.json` (diff + target only) | mid | yes, never the compiler's context | `{"verdict":"APPROVE|REJECT","findings":[{"severity","line","claim"}]}` |
| replay | `packets/replay-RUN.json` (q + overlay path) | mid | yes, one context per run | markdown answer |
| judge | `packets/judge-RUN.json` (points + answer) | mid | yes | `{"points":[{"point","met","quote"}],"verdict":"PASS|FAIL"}` |

A replay context reads only the overlay it is pointed at. A judge never sees the diff or the owner's words.

## Loop

```
open       --q Q --owner-says "…verbatim…" --points-file split.json
diagnose   C-NNNN                          # exit 0: packet written; stage flagged = stop, gap filed
record     C-NNNN conflict|compile|review --result F
validate   C-NNNN                          # retrieval label: done. Answer label: replay packets
record     C-NNNN replay|judge --run RUN --result F      # every run in the packet list
validate   C-NNNN                          # verdict: validated | failed
land       C-NNNN                          # files the proposal (kb-write put); the wiki is untouched
```

Then the owner reads the proposal and runs `kb-write land ID --endorsed-by OWNER`. The land hook calls `landed`, which appends the regression case. Run `kb-correct.py replay-all` before closing a loop to replay dormant answer cases.

## Stop rules

- Exit 1 (gate): read the printed reason; a minimality miss re-emits `compile.json` once, then the correction is killed. Do not edit around the gate.
- Exit 2 (usage, stage, drift): fix the call; on drift, `kill` and reopen.
- Exit 3 (P2 absent): stop and report.
- `flagged`, `failed` and `killed` each print one run-log row. Hand it to the owner; do not retry silently.
