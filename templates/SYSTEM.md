# Instance doctrine

Read by the model that works this instance. Each rule lives here once; skills point to it.

## Correction Protocol

1. A correction starts only when the owner says an answer was wrong. Keep their words verbatim in the record; never paraphrase them into a gold set.
2. Open one correction at a time. A correction with no terminal run-log row blocks the next `open`.
3. Gold evidence is locked before any ranking runs. Gold never comes from the ranker's top-k.
4. Diagnosis is deterministic: unreachable, raw-only, reachable-unretrieved (retrieval case) or reachable-retrieved (a skill gap, flagged, no wiki diff).
5. A conflict in the evidence is flagged as a gap for the owner. It is never compiled over.
6. One wiki page, at most 40 changed lines, Type and Core Claim kept, Updated bumped, lint clean. Two attempts, then kill.
7. The reviewer sees the diff and the target path only. Replay and judge steps run in fresh contexts that never see the diff or the owner's words.
8. Validated means: the case fails on the base copy, passes on the patched copy (answer cases: at least 2 of 3 runs), every affected case still passes, the regression suite is green on the patched copy, and the review approved.
9. `land` files a proposal; it never writes the wiki. Only the owner's `kb-write land --endorsed-by OWNER` does.
10. `landed` runs from that land and appends exactly one regression case after checking the ledger hash against the disk. A land that fails any regression is rolled back.
11. Every terminal state (killed, flagged, failed, validated) yields one run-log row for the owner. A discriminating correction scores 1.
12. Recipe and packet-to-tier table: `skills/kb-correct.md`. Code: `tools/kb-correct.py`.
