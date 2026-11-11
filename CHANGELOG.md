# Changelog

## Unreleased

### Instance backups

- Add `bin/kb backup create|inspect|verify|restore` for local instance-data archives. Include undo preimages, empty directories and regression cases. Refuse destination collisions, unsafe archive paths and unfinished writer transactions.
- Add round-trip recovery tests for retrieval and supersession undo, plus corruption and failure-cleanup checks. See [backup scope and recovery instructions](docs/BACKUPS.md).

### Answer citations

- Add `bin/kb answers capture` and `check` for answer receipts bound to approved wiki passages and ledger history.
- Add `audit` for collection coverage and `queue` for review grouped by affected page. See [commands and limits](docs/ANSWER-CITATIONS.md).

### Evidence review

- Compare two RAW revisions with byte fingerprints and line edits.
- Trace a source through explicit page dependencies to registered regression cases.
- Pin an exact quotation and locate it after revision, reporting missing and ambiguous matches.
- Rehearse a proposal against a specific query using rebuilt base and candidate search indexes. Proposal replay shares the staged overlay builder. See [commands and limits](docs/EVIDENCE-REVIEW.md).

### Fact decisions and session handoffs

- Track exact withdrawn claims per fact. Surface prior decisions on import and review, require a reason to reinstate, and bind that reason to signed approvals.
- Compare competing proposals and contradictory gaps with the current claim, source excerpts, submitter and prior decision in the review diff.
- Add optional answer/ask/abstain regression cases with blind replay and independent action classification.
- Add read-only `bin/kb brief --since SEQ` with source-linked changes and outstanding decisions. See [usage and compatibility](docs/CORRECTION-FIRST.md#withdrawals-and-competing-claims).

### Correction-first upgrade (2026-11-09)

- New corrections use the same hybrid ranker as the default query command, record its source version, and tell replay agents which method and k to use. Existing records and cases retain their legacy ranker; explicit `open --ranker kb-query` remains available. Hybrid regression evaluation refuses degraded retrieval.
- Add `answer_policy: require-fresh`: unchecked active answers fail evaluation, verification and land postchecks. Fresh installs enable it; existing instances default to `warn`. `correct replay-all --proposal ID --fresh` prepares exact staged postimages for external replay before approval. Stale results block the land and restore prior bytes. Unland remains available for recovery.
- Add short `fact` pages using existing source references, reviewed proposals, hash-checked supersession and undo. Require a Core Claim, at most 200 body words; article minimum remains 100.
- Add a dependency-free local stdio MCP adapter with five tools: search, read, status, correction-next and propose. No owner operations or arbitrary shell tool.
- Add versioned retrieval benchmark run/compare commands; reject changed corpus/cases/k, stale indexes, malformed or incomplete results. Document external GBrain result import and a blind answer/correction pilot, without claiming unrun results.
- Add integration coverage for strict rollback/replay, hybrid versus legacy behavior, MCP transport/path boundaries and benchmark comparability. See `docs/CORRECTION-FIRST.md` for setup, migration and limits.

### Feedback upgrade (2026-11-04)

- Default CLI search now shares hybrid retrieval with Porter stemming; `query --keyword` preserves the legacy interface. FTS failures report the actual fallback; the demo eval includes `compost`.
- Add state-derived `correct next CID`, safe unfilled response templates, next replay/judge selection and stale-validation guidance without skipping gates.
- Add read-only batch diffs with overlap/blocker reporting, status summaries, successful-verification checkpoints and undo-object health checks.
- Add preview-first Markdown folder import, explicit category/confidence, immutable source snapshots, duplicate detection, path/symlink refusals and per-file failure reporting. Imports only propose.
- Make approval targets prompt interactively; retain an explicit script mode and record approval mode. Add optional SSH-signed proposal lands bound to exact input/output hashes; stale and reused signatures fail. Retained receipts are rechecked during verification.
- Fresh installs now seed one neutral dormant example and discover shipped WIZARD/GURU souls. Preserve existing config and regression history; keep reference rules as opt-in examples.
- Correct undo/git, private-instance, approval, word-count, release-status and benchmark claims. Document backup completeness, migration, CLI compatibility and signing boundaries in `docs/UPGRADING.md`.
- Pin CI actions to official immutable commits, disable persisted checkout credentials and show failed test output.
- Add regression coverage for read-only review, imports, signature drift/reuse, checkpoint mismatch, stemming fallback and correction guidance. Preserve recovery and end-to-end discrimination tests.

**Compatibility:** default `query` JSON uses the hybrid schema; put `--keyword` first for the previous schema. Make approval commands require a TTY unless `APPROVAL=--non-interactive` is explicit. Existing notes, config and case files are not migrated automatically. Version remains 0.2.1 until a maintainer publishes a release.


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

Hardening PR2: evaluation honesty.

- Blind replay. Replay packets carry only the question and an overlay path; tests check the packet bytes
  hold no gold point, forbidden literal, owner text or verdict. The overlay's case copy drops answer gold.
- Strict judging. A judge result must be `{"verdict": "pass|fail|unclear", "evidence": "<span>"}` with the
  span quoted verbatim from the answer. Malformed, `unclear`, uppercase `PASS` or uncited results are
  recorded and count as FAIL, never as pass. **Breaking for judge fixtures:** `PASS`/`FAIL` become `pass`/`fail`
  plus `evidence`.
- Fresh evaluations. Validate and replay-all verdicts are bound to sha256 of the wiki corpus, the case and
  the tool source. Stale verdicts restart `validate`, fail `land` and the `landed` hook (exit 1, the land
  rolls back) and make `replay-all` ask for `--fresh`.
- `kb-eval --regressions` replaces "answer deferred" with "answer fresh pass" and "answer UNCHECKED": an
  active answer case counts only from a fresh replay-all verdict. `make verify` WARNs on UNCHECKED > 0.
  JSON keys `answer_passed`, `unchecked`, `unchecked_ids` replace `deferred_answer`.
- Same-day corrections. A second correction to a page on the day of the first no longer fails the
  minimality gate on `Updated`; tested with two corrections opened and landed in one day.

Hardening PR3: provenance and verification.

- Source preservation. `land` hashes every raw source (the proposal's `raw:` refs and the page's
  `**Sources:** [[RAW/...]]` links) into the ledger land row as `sources`, and refuses a land whose raw
  file is absent (exit 2). New `tools/kb-provenance.py --check` FAILs on a missing or drifted landed
  source and WARNs on lands made before this release.
- Retrieval method recorded. `kb-query --json`, `kb-eval` and `kb-eval --regressions` report ranker,
  tool version hash, tools hash and k, so a result can be reproduced.
- Index integrity. `kb-index.json`, `content-seeds.json`, the dashboard and `kb-graph.json` store the
  `inputs_hash` of the wiki they were built from. Stale = WARN with `bin/kb index`; corrupt = FAIL.
- `make verify` runs the provenance gate (block 1b) and flags dangling `[[RAW/...]]` Sources links.
- `docs/TRUST.md`: what is deterministic, what is model judgment, what the owner gate covers, and the
  threat model for inbox inputs.
- Migration: run `bin/kb index` once to stamp `inputs_hash`; older land rows only WARN.

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
