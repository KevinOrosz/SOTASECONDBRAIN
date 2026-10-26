# Changelog

## 0.1.0 — 2026-10-26

- Extracted from a private reference instance (build sessions 1–5): typed wiki pages + `kb-lint`,
  gated write-back with hash ledger (`kb-write`), retrieval eval + regression suite (`kb-eval`),
  search index, knowledge graph, hybrid search, doctor, autolink report.
- New: `tools/kb_config.py` reads every instance path from `KB/kb.json` (`dashboard`, `regressions`,
  `agents_glob`, `baseline`, `catalog`, `registry`, `router`, `spine`) with defaults.
- New: `bootstrap.sh`, `bin/kb`, `Makefile`, `scripts/verify.sh`, 12-page demo wiki, starter template.
- The catalog page is optional; `land` skips its count bump while the file is absent.
