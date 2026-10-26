# Changelog

## Unreleased

Hardening PR1: recovery.

- Undo works without Git. Every `land` and `unland` stores each touched file's prior bytes, write-once
  and hash-verified, at `KB/inbox/_objects/<sha256>`; `unland` restores from there first. A page changed
  since its land is refused (exit 4) with the hashes in the message.
- Atomic correction landing. A failing `kb-correct landed` hook now rolls the whole land back (exit 3)
  instead of warning and letting the land stand, so no correction enters the wiki without its case.
- Operation journal `KB/inbox/_ops/<op>.json` (planned files with pre/post hashes, step markers). Every
  `kb-write` and `kb-correct` invocation first finishes or rolls back an unfinished op and logs one new
  `recover` ledger event. `_objects/` and `_ops/` are reserved inbox names (WP2).
- `KB_WRITE_FAULT` gains named crash points: `after-page`, `after-derived`, `after-ledger`,
  `after-proposal`, `after-case` (exit 9, test seam). Each is tested to end in full success or
  byte-identical restored state, and a rerun converges.
- Migration: none needed. Instances without `_objects/` keep working; `unland` of a land made before
  this release falls back to Git history as before.

## 0.2.1 — 2026-10-26

- WIZARD setup agent: open the repo in any AI agent tool and type `WIZARD` (`souls/WIZARD/soul.md`).
- README opens with the user guide and the WIZARD tip; root `AGENTS.md` and `CLAUDE.md` route agents to it.
- GitHub CI: tests, verify and sandbox on Ubuntu and macOS, Python 3.9 and 3.12.
- Community files: CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue and PR templates, CODEOWNERS.
- Quality of life: grouped `make help`, `bin/kb version`, `.editorconfig`, `.gitattributes`, README badges.

## 0.2.0 — 2026-10-26

- `make status` no longer reports FAIL on a fresh install: the doctor records its link baseline on first run.

Lean path complete (build sessions 6–8).

- New: `tests/test-kb-loop-e2e.py` (LOOP-E2E, session 8). On a throwaway fixture, driving every tool as a
  CLI with fixture JSON for each model step: correct → validated → land → owner land (hook appends exactly
  one case) → regressions green, lint 0 FAIL, ledger hash = disk hash, one Type/Confidence/Provenance line
  → unland → regressions exit 1 (discrimination proof). Runs last in `scripts/verify.sh` and `make test`.
- README: quickstart query now matches the demo (`composting`), a copy-paste `draft.md`, owner-id rule
  stated, "What you have now" and "Next steps" sections. QUICKSTART gains the draft step.

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
