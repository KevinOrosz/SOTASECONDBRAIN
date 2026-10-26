# Architecture

```
            propose (agents)                       approve (owner)
 KB/RAW ──► bin/kb write put ──► KB/inbox/AGENT/*.md ──► bin/kb write land ──┐
  sources       │                     │                                       │
                └──── ledger row ─────┴──► KB/inbox/_ledger.jsonl ◄───────────┤ (land / unland rows,
                                                                              │  file hashes before/after)
                                                                              ▼
                                         stage page + category index + master index (+ catalog)
                                                                              │
                                                                              ▼
                     post-check: kb-index + kb-graph rebuild ─► kb-graph --check ─► autolink
                                 ─► kb-eval --check ─► kb-eval --regressions ─► kb-lint 0 FAIL
                                                                              │
                                         any miss ─► restore every byte, exit 3
                                         all pass ─► KB/wiki updated, ledger row, proposal = landed
                                                                              │
                                                                              ▼
       KB/output/kb-index.json · kb-graph.json · content-seeds.json · kb-search.html (dashboard)
                                                                              │
                                     read by  bin/kb query · search · ask · doctor · eval
```

## Data flow

1. **Sources** land in `KB/RAW/` by hand. Nothing reads the network.
2. **Proposals** are written only by `kb-write put|link` into `KB/inbox/{AGENT}/`. Each gets a ledger row.
3. **Land** is the single path into `KB/wiki/`. It stages every edit, writes it, rebuilds the derived
   files, then runs the post-check. A failure restores the exact prior bytes. Every land/unland stores its preimages in
   `KB/inbox/_objects/` and journals itself in `KB/inbox/_ops/`, so a crash is finished or rolled back
   on the next run.
4. **Derived files** in `KB/output/` are always rebuildable from `KB/wiki/` + `KB/RAW/` (`bin/kb index`).
5. **Checks**: `kb-lint` (header contract, WP1 hashes, WP2 inbox), `kb-graph --check` (freshness),
   `kb-eval` (hand-labeled retrieval recall@6 and regression cases), `brain-doctor` (structure).
6. **Config**: `KB/kb.json`, read only through `tools/kb_config.py`.

## Tools

| Tool | Writes | Role |
|---|---|---|
| `kb-lint.py` | nothing (except `--migrate`, `--capture-baseline`) | header contract, WP1, WP2 |
| `kb-write.py` | `KB/inbox`, and `KB/wiki` + derived files on land/unland | the only write path |
| `kb-index.py` | `KB/output/*.json`, dashboard | parse pages into the search index |
| `kb-graph.py` | `KB/output/kb-graph.json` | pages, sections, links, sources as a graph |
| `kb-query.py` | nothing | field-weighted keyword ranker |
| `kb-graph-query.py` | nothing | hybrid search (BM25 over bodies) + graph verbs |
| `kb-correct.py` | `KB/inbox/_corrections/`, `evals/regressions.jsonl` (via `landed`) | owner correction → packets, gated diff, proposal, regression case |
| `kb-eval.py` | nothing | retrieval eval + regression suite |
| `kb-autolink.py` | nothing | reports unlinked mentions |
| `brain-doctor.py` | nothing | structural health report |
| `kb_config.py`, `kb_testkit.py` | — | shared config reader; shared test fixture |
