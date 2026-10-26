# Changelog

## Unreleased

- New: `kb-correct.py land` (validated correction -> `kb-write put --supersedes ... --origin correction:CID`,
  stage `proposed`), `landed` (the kb-write land hook: checks the ledger row and disk hash, appends exactly
  one regression case with `landed_version` and `ledger_seq`, idempotent) and `replay-all` (replay/judge
  packets for every answer case, dormant included; exit 0/1/2).
- New: `skills/kb-correct.md` (packet-to-tier recipe), `templates/SYSTEM.md` with the Correction Protocol
  (bootstrap copies it to `KB/SYSTEM.md`), `bin/kb correct`, `docs/CORRECTION-TUTORIAL.md` and fixtures in
  `examples/correction-walkthrough/`. `tests/test-kb-correct.py` now has 30 tests. No skill registry
  ships in this package, so there is no registry row.

- New: `tools/kb-correct.py` correction compiler core (build session 6, P3-S2): `open`, `diagnose`,
  `packet`, `record`, `validate`, `kill`, `status` under `KB/inbox/_corrections/C-NNNN/`. Writes packets
  for every LLM step and reads filled results; whitelisted packet keys; deterministic evidence scan,
  gold lock before ranking, four diagnosis labels; minimality gate on `kb-lint.read_meta` + lint;
  base/patched overlays with redacted origins; `kb-eval --regressions --check` on the patched overlay;
  blind replay + judge with a forbidden-literal pre-check. `land`/`landed`/`replay-all` follow in P3-S3.
- New: `tests/test-kb-correct.py` (22 tests). `test-kb-write.py` covers the hook both absent and failing.

## 0.1.0 — 2026-10-26

- Dashboard title comes from `title` in kb.json (default "Knowledge Base"); no name is hard-coded.

- Extracted from a private reference instance (build sessions 1–5): typed wiki pages + `kb-lint`,
  gated write-back with hash ledger (`kb-write`), retrieval eval + regression suite (`kb-eval`),
  search index, knowledge graph, hybrid search, doctor, autolink report.
- New: `tools/kb_config.py` reads every instance path from `KB/kb.json` (`dashboard`, `regressions`,
  `agents_glob`, `baseline`, `catalog`, `registry`, `router`, `spine`) with defaults.
- New: `bootstrap.sh`, `bin/kb`, `Makefile`, `scripts/verify.sh`, 12-page demo wiki, starter template.
- The catalog page is optional; `land` skips its count bump while the file is absent.
