---
HANDOFF
agent: GURU
mission: Turn the agentic second-brain research into one build-ready CODA spec: typed pages, gated write-back, correction compiler, incubation.
date: 2026-10-23
type: build spec
score: n/a
key_findings:
  - The loop only closes if P3 regression cases gate P2 lands. All four drafts missed this. The land post-check now runs `kb-eval --regressions`. [high]
  - Header keys, ledger events, kb-lint ownership, verify numbering and Confidence/Last-Verified semantics had drifted across the drafts. Each now has exactly one home, in §1. [high]
  - Lean path is 8 CODA sessions. P1-S3, P2-S3 and P4 wait until 3 real corrections land. Skipping them breaks nothing. [moderate]
suggested_use: CODA session plan. Hand CODA one §0 row, plus §1, plus that phase's section. Nothing else.
---

> **Package note (2026-10-26).** This spec was written inside a reference instance. "Verify block N" means one numbered section of that instance's verify script; in this package every such check lives in `scripts/verify.sh`, which runs all `tests/test-kb-*.py` automatically. Paths are rewritten to this package's layout; instance paths are `KB/kb.json` keys (see `docs/HANDOFF.md` §3).

# Second-Brain Loop — Build Spec

**Status:** DRAFT until the owner reviews.
**Portability:** model, harness and founder agnostic. Instance identity (owner id, agent ids) lives only in `KB/kb.json`; see `docs/HANDOFF.md` §3. Model tiers low / mid / high mean any vendor's small / medium / large model. Agents (MAGI, GURU, CODA, CLERIC, SIGNAL, PRISM) are the reference swarm; see `docs/SWARM.md`.
**Research basis:** `docs/RESEARCH.md`. Not restated here.

**TL;DR**
1. P1: every wiki file states its `**Type:**`. `kb-lint.py` checks the contract with zero LLM calls. No YAML.
2. P2: agents write only to `KB/inbox/`. Only `kb-write.py land`, endorsed by the owner, touches `KB/wiki`, and every land is hashed into an append-only ledger.
3. P3: a the owner correction becomes one gated one-page diff plus one permanent regression case. Every later land must pass that case.
4. P4: brain-dream emits at most 2 gated proposals a week. Deferred until the loop proves itself.
5. The E2E test is the proof. Unland the fix and the new case must FAIL.
6. Six the owner rulings, batched before session 1. No LLM call inside any `tools/*.py`.

---

## 0. Build sequence + end-to-end acceptance

**Precondition.** Before session 1, the owner settles the six §6 rulings in one MAGI chat. That includes a single `KB/SYSTEM.md` edit approval covering P1, P2 and P3. MAGI logs it as one run-log row, so no later session blocks on it again.

**Sessions.** One CODA mission each.

| # | Session | Model | Scope | Depends on |
|---|---|---|---|---|
| 1 | P1-S1 | high | `kb-lint.py` core: `RULES`, `read_meta`, `CONTRACT`. Plus `kb_testkit.py`, `kb-index.py --root`, verify renumber, run log rotation. No wiki writes. | clean commit + pre-SHA |
| 2 | P1-S2 | mid | 13-batch migration, rebuild per batch, baseline, verify block 16 | 1 |
| 3 | P2-S1 | high | put/link/withdraw/list, allowlist, seal, adopt/reseal, WP1 (WARN) + WP2, block 17 | 2 |
| 4 | P2-S2 | high | land, unland, reject, resolve, land hook, fault seam, dry-run | 3 |
| 5 | P3-S1 | mid | `kb-eval --regressions`, seeds, block 18, skill-test count, regressions in land post-check | build: 1; wiring: 4 |
| 6 | P3-S2 | high | `kb-correct.py` core | 5 |
| 7 | P3-S3 | mid | land/landed, skill, row 55, Correction Protocol, one live correction | 4, 6 |
| 8 | LOOP-E2E | high | `tests/test-kb-loop-e2e.py`, block 20 | 7 |
| 9 | P1-S3 | mid | enforce Type, SYSTEM template | 2 |
| 10 | P2-S3 | mid | brain-think 4b, kb-ingest rewrite, REGISTRY, Write-Back Protocol, WP1 to FAIL | 4, 9 |
| 11 | P4-S1 | high | brain-dream seam on real P2, staleness, block 19, E2E P4 variant | 8, 10 |
| 12 | P4-S2 | mid | skill, row 52, eval, guardrail, one supervised fire | 11 |
| 13 | P4-S3 | mid (MAGI) | 4-fire pilot, fresh judge, LIVE or revert | 12 |

**Critical path:** sessions 1–8. Lean path (D6): stop at 8. Open 9–13 only after 3 real corrections land discriminating cases.

**If a phase is skipped:**
- **P1:** P2 creates kb-lint with WP rules only, and P4 loses age-check.
- **P2:** P3 stops at `validated` (exit 3). The loop never closes.
- **P3:** lands have no regression gate.
- **P4:** nothing breaks.

**Every session must:**
- end with the repo's close step
- write one run-log row (traceability)
- show verify 0 FAIL
- stop and report on any blocker, never route around it

**E2E acceptance: `tests/test-kb-loop-e2e.py`.** Runs on `kb_testkit.fixture(tmp, regressions=True)`. Fixture JSON replaces every LLM step, so there are zero LLM calls.

1. `kb-correct open → diagnose → record → validate` reaches `validated`.
2. `kb-correct land → kb-write put → kb-write land --endorsed-by OWNER`. The land hook calls `kb-correct landed`. `regressions.jsonl` gains exactly 1 row.
3. Checks, all must pass:
   - `kb-eval --regressions` exits 0
   - `kb-lint --rule all` reports 0 FAIL
   - ledger hash equals disk hash
   - the page has Type, Confidence and exactly one Provenance line
4. `kb-write unland`, then `kb-eval --regressions` **must exit 1**.

Step 4 is the discrimination proof. If it fails, P3's yield metric is measuring itself. Stop P3.

Session 11 adds a P4 variant: `plan → emit → land → gate --report --pilot` with landed=1. Runs as verify block 20, last.

---

## 1. Shared contracts (defined once; phases point here)

### 1.1 Canonical homes (single source of truth)

Each contract has one home. Every other phase imports it and never redefines it.

| Contract | Home |
|---|---|
| Wiki header keys, order, enums, budgets, META set | `kb-lint.py` `CONTRACT` (printed by `--contract`) |
| Header parsing | `kb-lint.read_meta(path) → {type, depends_on, consumers, confidence, last_verified, updated, provenance, header_end}` |
| Lint rules | `kb-lint.RULES` (phases append, additive) |
| Inbox schema, verb set, ledger enum, write allowlist | `kb-write.py` docstring + constants |
| Case schema + invariants | `kb-eval.py` `CASE_SCHEMA` |
| Test fixture | `tools/kb_testkit.py` `fixture()` + `tree_digest()`. Every suite imports it. `test-kb-graph.py` keeps its own. |
| Ratchets and tunables | `evals/kb-health-baseline.json` |
| Fixed values | `--contract` |
| Reviewer tier | `KB/kb.json` key `reviewer_tier` (default mid), diff-only |
| Doctrine | `KB/SYSTEM.md` § Write-Back Protocol, § Correction Protocol. Skills point, never copy. |

### 1.2 Wiki header contract v2 (bold-line)

**Header block.**
- Starts at the first non-blank line, which must be `^# `. Two live files open with a blank line. No H1 → FAIL `header-missing-h1`.
- Continues through contiguous blank lines and lines matching `^\*\*[A-Za-z0-9][A-Za-z0-9 -]*:\*\*`.

**v2 run.** One contiguous run after the legacy `**Updated:**`. If there is no Updated line, after the last legacy key. In this order:
```
**Type:** article                          # required after P1-S3
**Depends-On:** stem-a, stem-b             # plain stems, not [[links]]
**Consumers:** skill:brain-think, agent:GURU
**Confidence:** high|moderate|low          # absent = unrated
**Last-Verified:** 2026-10-23              # ISO ≤ today; absent = None (unverified)
**Provenance:** inbox GURU/2026-10-24-x · proposed GURU · endorsed OWNER 2026-10-24 · ledger 14
```

**Key rules.**
- **Last-Verified.** Absent means unverified, never fresh. `read_meta` returns `last_verified=None` plus `updated`, and the caller labels which one it used. 501/602 Updated lines are 2026-05 compile stamps, so falling back to Updated would forge verification. [high]
- **Confidence.** This header is its only home. Land converts the inbox `confidence` into this line, and Provenance carries no confidence token.
- **Provenance.** Land replaces the line, never appends a second one. History lives in `_ledger.jsonl`. `P2_MANAGED = {Confidence, Provenance}`.

**Header severities.**
- Duplicate v2 key → FAIL.
- Duplicate legacy key → WARN `header-legacy-duplicate`. Live case: `human-design-kjo-channels.md` has two Sources lines.
- Keys out of order → WARN `header-order`.

**Body words.** META = {Category, Sources, Tags, Updated, Articles, Scope, Status, System} plus the v2 keys. Body words = words after the H1, minus META lines. `**Core Claim:**`-style lines count as body.

**Types.**

| Type | Path default | Soft budget (words, ratchets) | Hard budget (words) |
|---|---|---|---|
| routing | `KB/wiki/_index.md` | — | 6000 |
| taxonomy | `<cat>/_index.md` | — | 6000 (≈100 articles; split the category) |
| article | `<cat>/<stem>.md` | 400 | 2000 |
| source | 5 overrides | — | 15000 |
| position | — | 400 | 800 |
| gateway | — | 150 | 300 |

**Type and id rules.**
- An `_index.md` must be routing or taxonomy. Nothing else may be.
- Article id = stem. Unique case-insensitively, and never equal to a category folder name.

**kb-lint exit codes.** Unified across all rules: 0 PASS, 1 FAIL/FATAL, 2 WARN. Bare `kb-lint.py` runs the contract rules. `--rule WP1|WP2|all` selects.

**Banned words.** No tool text quotes the instance's banned-word list. Cite the list by name instead. Case r-0001 enforces this.

### 1.3 Inbox, frontmatter, ledger

```
KB/inbox/_seal.json   KB/inbox/_ledger.jsonl (append-only, never git-reverted)   KB/inbox/.lock
KB/inbox/_corrections/C-0001/{record.json, packets/, results/, after.md, diff.patch}
KB/inbox/{AGENT}/{YYYY-MM-DD}-{slug}.md      # AGENT = a registered agent id (KB/kb.json), or the owner id
```

**Layout rules.**
- P2 declares the `_` exemption. WP2's stray-file check skips exactly the reserved names in `kb-write.py` (`RESERVED_FILES`, `RESERVED_DIRS`: `_seal.json`, `_ledger.jsonl`, `.lock`, `_corrections/`, `_objects/`, `_ops/`).
- Slug matches `^[a-z0-9]+(-[a-z0-9]+)*$`, max 60 chars. On collision, append `-2`.
- Frontmatter is a flat YAML subset. An unknown key is a WP2 violation.

**Keys on every kind:**
- `id` (derived)
- `kind`: article | gap | link
- `state`: open | landed | withdrawn | rejected | resolved
- `proposed_by`, `proposed_at`
- `source_refs`: at least one of `raw:`, `wiki:`, `output:`, `owner:<date>`. `query:<sha12>` is allowed only on missing-gaps.
- `confidence`
- `origin`: `skill:brain-think`, `correction:C-0001` or `brain-dream:{date}:{tension}:{move}`
- `dedupe_key`: `sha256(kind|gap_kind|target|norm(title))[:12]`

**Keys by kind:**
- **Article:** `type` (P1 enum, default article), `category` (a dir under `<root>/KB/wiki`), `stem`, `supersedes` (at most one `wiki:<stem>`), `base_hash`, `resolves`.
- **Gap:** `gap_kind` (stale | thin | contradictory | missing | skill), `target`, `query`.
- **Link:** `link_from`, `link_to`, `link_type` (must be in `kb-graph.json["type_vocabulary"]`, else `{RELATES_TO}`), `prose` (≥3 chars).
- **Tool-set only:** `endorsed_by`, `decided_at`, `landed_path`, `reason`.

**Ledger events.** One canonical enum, `LEDGER_EVENTS` in `kb-write.py` (today `put|withdraw|reject|land|unland|resolve|adopt|reseal|recover`). Row shape:
```json
{"seq":14,"ts":"2026-10-24T09:12:03","event":"land","id":"GURU/2026-10-24-x","actor":"owner","origin":"correction:C-0001",
 "files":{"KB/wiki/topic/x.md":"<sha256>"},"prior":{"KB/wiki/topic/x.md":null},"resolved":[],"reason":""}
```

**Source hashes (provenance).** A `land` row also carries `"sources": {"<raw name>": "<sha256>"}`: every `raw:` ref of the proposal plus every `[[RAW/...]]` link on the landed page's `**Sources:**` lines, hashed from `KB/RAW` at land time. A named raw file that is absent refuses the land (exit 2). `kb-provenance --check` FAILs when a source recorded on a live land (one not later unlanded) is missing or its bytes drifted, and WARNs on a landed page whose land row predates `sources`.

**Expected hash and tracing.**
- A wiki path's expected hash is its last ledger `files` entry. If it has none, the seal entry.
- The ledger `put` row is an inbox file's provenance trace.
- A session writes one run-log row (`ledger seq a–b`). Tools never write per-call rows.

### 1.4 Regression case shape

`evals/regressions.jsonl`. Append-only. Retire a case with `status:"retired"` plus `retired_reason`. Never delete a row.
```json
{"id":"r-0004","kind":"answer|retrieval|artifact","q":"","expected":[],"forbidden":[],"origin":"rule:banned-words|correction:C-0001",
 "landed":"2026-10-24","status":"active|dormant|retired","gold_source":"owner-verbatim|rules|evidence-scan",
 "gold_locked":"","evidence_stems":[],"named_stems":[],"retrieval_at":"","pages":[],"targets":[],
 "ranker":"kb-query","k":10,"failing_version":"seed|<sha256>","landed_version":"<ledger sha256>","ledger_seq":14}
```

**Case kinds.**
- **answer:** the owner's points are judged one by one. Forbidden literals are pre-checked deterministically. `--regressions` counts an active answer case only from a fresh `replay-all` verdict (§1.4 Evaluation honesty); with none it is reported `UNCHECKED`, never as a pass.
- **retrieval:** every gold stem is in kb-query's top-k, and no forbidden stem is.
- **artifact:** each expected regex matches at least one targets file, and no forbidden regex matches any.

**Invariants.** A violation exits 1.
- **I-1:** ids are unique and monotonic.
- **I-2:** keys are present and typed.
- **I-3 (gold independent of the ranker):** gold ⊆ `evidence_stems ∪ named_stems`, and `gold_locked < retrieval_at`. Checkable from the row alone.
- **I-4:** an artifact case with empty expected needs forbidden.
- **I-5:** at most one case per rule origin.

**Evaluation honesty.**
- **Blind replay.** A replay packet holds `q` and an overlay path only: never the gold points, forbidden literals, `owner_says` or any prior verdict. The overlay's copy of the cases strips answer gold (`expected`, `forbidden`). The judge packet is separate.
- **Strict judging.** A judge result is `{"verdict": "pass|fail|unclear", "evidence": "<span quoted verbatim from the answer>", "points": [{point, met, quote}]}`. Only a `pass` whose evidence span appears in the answer, with every point met and no forbidden literal, passes. Malformed JSON, another verdict string (`PASS` included), `unclear` or a missing or unquoted span is recorded and counts as FAIL.
- **Freshness.** Every verdict is bound to `{corpus, case, tools}`: the sha256 seal of `KB/wiki/**/*.md` (without generated `_index.md` pages; validate also leaves out the target page, which its own before/after hashes guard), the case's judged keys (`kind q expected forbidden targets ranker k`), and the `tools/*.py` source. A result whose binding moved is stale: validate restarts, `land` exits 1, `landed` exits 1 (the kb-write land rolls back), `replay-all` exits 2 until `--fresh`, and `--regressions` reports the case `UNCHECKED`.

**Retrieval method.** Results record what produced them. `kb-query --json` carries `retrieval: {ranker, tool, version, k, index_inputs_hash}`; `kb-eval` carries `retrieval.old` / `retrieval.new` and `--regressions` carries `retrieval_method`, each `{ranker, tool, version (tool sha256[:12]), tools_hash, k}`. The text reports print the same line.

**Derived-output integrity.** `kb-index.json`, `content-seeds.json`, the dashboard (`<!-- inputs_hash: ... -->`) and `kb-graph.json` store `inputs_hash`: sha256 over `(path, sha256)` of every non-`_index.md` wiki page they were built from. `kb-provenance --check` (0 PASS / 2 WARN / 1 FAIL): unreadable or self-inconsistent index or graph = FAIL; absent, legacy or another wiki's hash = WARN; a stale seed file or dashboard, or a `[[RAW/...]]` Sources link naming no file = WARN. Every non-PASS line names its fix command (`bin/kb index` for derived outputs). Trust boundaries: `docs/TRUST.md`.

### 1.5 verify.sh blocks

**Renumber first.** P1-S1 fixes the live duplicate 12: 11 Git shield, 12 PRISM, 13 Brain health, 14 Voice, 15 KB graph.

**New blocks.** Each goes before `summary`, uses `mktemp` and stays bash 3.2.

| Block | Phase | Runs |
|---|---|---|
| 16 | P1 | `kb-lint.py` + `test-kb-lint.py`. First, because WP1 trusts headers to parse. |
| 17 | P2 | `--rule WP1`, `--rule WP2`, `test-kb-write.py` |
| 18 | P3 | `kb-eval.py --regressions evals/regressions.jsonl` + `test-kb-correct.py` |
| 19 | P4 | `test-brain-dream.py` |
| 1b | PR3 | `kb-provenance.py --check` (sources, index/graph inputs_hash, cache freshness) + `test-kb-provenance.py` |
| 20 | E2E | runs last |

**Every suite asserts:**
- `grep -nE '(import|from) (requests|urllib|http\.client|socket|httpx|aiohttp)\b|subprocess.*(curl|wget|llm)|https?://'` on its tool returns nothing.
- The live `KB/output/kb-search.html` mtime is unchanged.

---

## P1 — Frontmatter contract v2 + deterministic linter

**1 Goal / Non-goals.**

- **Goal:** all 602 wiki files carry `**Type:**`. kb-lint checks for dangling Depends-On, orphan Consumers, budgets, duplicate ids and cycles.
- **Type set:** Meta-style structural types, not Cornelius maturity layers. Path plus 5 overrides classify all 602 files with no judgment calls. Cornelius would need 589. [high]
- **Counter:** 584/602 files are `article`, so at launch the field carries little information. [high] It still buys budgets, a typed slot for P2 `put --type`, and pages that describe themselves.
- **Non-goals:**
  - no graph schema change
  - no Confidence or Last-Verified backfill
  - no position/gateway pages (no placeholders)
  - no body edits
  - no fix for the 20 category mismatches

**2 Dependencies.** None on P0. Reads:
- `KB/wiki/**`
- REGISTRY skill column (status ≠ RETIRED)
- router `registered_names`
- baseline

**3 Files touched.**

Create:
- `tools/kb-lint.py`
- `tools/kb_testkit.py` (first consumer is test-kb-lint, so not a placeholder)
- `tests/test-kb-lint.py`

Modify:
- `tools/kb-index.py`: `--root R` re-roots WIKI, OUT and DASH together.
- `verify.sh`: renumber, then add block 16.
- the run log + archive: rotate under the 30,720 B cap (today: 33,717).
- 602 wiki files: one line each.
- Baseline: add the `lint` key, preserving unknown keys.
- `KB/SYSTEM.md` (S3, D3): add Type to the template; point length rules to `--contract`.

Regenerate: `KB/output/{kb-index,kb-graph,content-seeds}.json`, `kb-search.html`.

Do not touch `kb-ingest.md`. P2-S3 rewrites it once.

**4 Data contracts.** See §1.2.

`source` overrides:
- `spirituality-philosophy/aphorisms-and-power-quotes`
- `clients/testimonials`
- `clients/client-pricing-structures`
- `spirituality-philosophy/terence-mckenna-quotes-archive`
- `business-marketing/post-ideas-swipe-file`

`--json` keys: `file_count`, `typed_explicit`, `by_type`, `counts{fail,warn,over_soft_budget,cycles}`, `baseline`, `findings[{path,id,check,severity,detail}]`.

Check enum: `header-missing-h1`, `header-duplicate-key`, `header-legacy-duplicate`, `header-order`, `type-missing`, `type-invalid`, `type-path-conflict`, `confidence-invalid`, `date-invalid`, `dangling-depends-on`, `self-dependency`, `orphan-consumer`, `duplicate-id`, `cycle`, `budget-hard`, `budget-soft`.

Baseline: `"lint":{"captured":date,"over_soft_budget":<captured>}`. Capture the value; never assert it. A refuter counted 284 against the draft's 288.

**5 CLI.**
```
kb-lint.py [--root] [--json] [--category NAME|_root] [--rule …] [--contract] [--capture-baseline] [--migrate dry-run|write|revert]
```
- `--migrate` requires `--category`.
- `revert` removes the Type line only, and refuses if any other v2 key is present.

**6 Algorithm.** All steps are DETERMINISTIC.
1. Enumerate files, sorted. Global checks always see the full set.
2. Run `read_meta`.
3. Validate enums, dates ≤ today, and type↔path.
4. Ids: case-folded collisions and category-name collisions.
5. Resolve Depends-On against ids. Resolve Consumers against REGISTRY and the router.
6. Iterative DFS for cycles. Report each once, rotated to its smallest node.
7. Budgets: hard → FAIL. Soft count vs baseline → WARN on growth.
8. `migrate write`: insert the type (override, else path default) at its canonical position. Assert that removing the line reproduces the original bytes.

**7 Integration hooks.**
- Block 16: rc 0 PASS, 2 WARN (indented output), 1 FAIL.
- Session scripts and skill registry: unchanged.
- Loop-log row:
  ```
  2026-10-2X | CODA | command | P1 contract v2 migration | kb-lint | n/a | 13 | KEEP | typed {t}/{n}; 0 FAIL; soft baseline {captured}; recall@6 {before}={after}; pre-SHA {sha}; verify 0 FAIL
  ```

**8 Tests.** `test-kb-lint.py`, under 5 s.
1. Clean fixture → 0.
2. Path defaults.
3. FAIL: dangling Depends-On.
4. FAIL: orphan consumer (unknown, RETIRED, or unregistered).
5. Cycle reported once.
6. FAIL: duplicate id, case-insensitive.
7. Hard budget FAILs; soft budget ratchets.
8. FAIL: bad enum, bad date, future date.
9. Migrate inserts one line, body identical, revert round-trips.
10. Lint never mutates.
11. Exit codes 0/1/2.
12. Both leading-blank-line shapes.
13. Duplicate legacy Sources → WARN.
14. Core Claim line counts as body.
15. capture-baseline preserves `graph` and `staleness_days`.
16. `kb-index --root` leaves the live dashboard untouched.

**9 Migration / rollback.**

Step 0:
- `git status --porcelain KB/wiki KB/output/kb-index.json KB/output/kb-graph.json evals/kb-health-baseline.json` must be empty.
- Log `git rev-parse HEAD` as pre-SHA before the first write.

Per batch (`_root` plus 12 categories):
1. dry-run
2. write
3. `kb-index.py && kb-graph.py`
4. full verify, 0 FAIL

The rebuild in step 3 is mandatory. Skip it and brain-doctor hash drift raises real FAILs, and CODA stalls. [high]

After the last batch:
- `kb-eval --json` `new.combined` must be equal before and after. If not, revert and don't tune. [moderate]: kb-index counts raw words.
- Run `--capture-baseline`.
- All of this must happen before the P2 seal.

Rollback:
```
git checkout <pre-SHA> -- KB/wiki KB/output/{kb-index,kb-graph,content-seeds}.json evals/kb-health-baseline.json
```
Then drop block 16. If the seal already exists, also run `seal --reseal`.

**10 Target / Batch / Metric.**
- **Target:** `KB/wiki/**/*.md` + `tools/kb-lint.py`
- **Batch:** 1 category
- **Metric:** `typed_explicit/file_count = 1.0`

Acceptance:
- [ ] 0 FAIL. `by_type` logged, not asserted.
- [ ] `git diff --numstat <pre-SHA> -- KB/wiki` shows only `1\t0` rows.
- [ ] `git diff <pre-SHA> -- KB/wiki | grep '^[-+][^-+]' | grep -v '^+\*\*Type:\*\* '` is empty.
- [ ] recall@6 unchanged.
- [ ] 16/16 tests, verify 0 FAIL.

Zero cycles and zero dangling deps are trivial at launch; the fixtures prove the checks fire. Report them as checks only (no overclaiming).

**11 Decisions:** §6 D1, D5.

**12 Sessions.**
- **S1 (high tier):** everything in §3 except the wiki and SYSTEM writes.
  - Done when: 16/16 tests pass, the live dry-run shows 602 `type-missing` WARN, and the run log is under its cap.
- **S2 (mid tier):** run §9.
  - Done when: metric = 1.0 and block 16 PASS.
- **S3 (mid-tier, deferred):** set `TYPE_REQUIRED=True` and delete the overrides dict.
  - Done when: a missing Type FAILs in the fixture.

---

## P2 — Inbox write-back with provenance + one endorsement gate

**1 Goal / Non-goals.**
- **Goal.** Agents propose into `KB/inbox/`. Only `land` writes `KB/wiki`, and only with the owner's endorsement. The first producer is brain-think's gap block, which today dies in chat. [high]
- **Objection:** the inbox becomes a graveyard. Answer:
  - dedupe
  - ≤4 proposals per run
  - inbox count shown at session open
  - one global weekly gate budget (D2), which CLERIC measures from the ledger
- **Non-goals:**
  - no auto-landing
  - no LLM calls in the tools
  - no wiki deletes or renames
  - no multi-page supersede
  - no Provenance backfill (it would be invented)
  - no authorship proof. WP1 sees changes, not authors. [high]

**2 Dependencies.**
- **P1-S2 must finish first.** Sealing before it trips WP1 on all 602 files.
- From P1: `RULES`, `read_meta`, `kb-index --root`. Land's header writes go through a single function, P1's extension point.
- Also uses: `kb-autolink` (`_known_targets`, `_classify`, `scan`), `kb-graph --root/--check`, `kb-eval --check`.

**3 Files touched.**

Create:
- `tools/kb-write.py`
- `tests/test-kb-write.py`
- `KB/inbox/_seal.json` and `_ledger.jsonl`, written by the tool

Modify:
- `kb-lint.py`: add WP1 and WP2.
- `verify.sh`: block 17.
- the repo's open step: one line, `ok    inbox: N open (a/g/l)`. Never blocks.
- `brain-think.md`: step 4b.
- `kb-ingest.md`: **one rewrite.** Declare Type, put + land, one `link` proposal per backlink, fix the stale "502 tracked".
- `REGISTRY.md`: rows 51 and 22.
- `KB/SYSTEM.md` (D3): the vault line, plus `## Write-Back Protocol` (rules only; the schema stays in the docstring).
- `protocols.md`: one pointer and the reviewer tier.

Runtime writes by `land`:
- the article and its category `_index.md`
- master `_index.md`: Status, category row, Updated, Recent Updates
- `KB/CATALOG.md`
- `KB/output/{kb-edge-types,kb-index,kb-graph,content-seeds}.json`
- `kb-search.html`

**4 Data contracts.** See §1.3. Land writes Type (from the proposal) and Confidence, and replaces Provenance, all through P1's header-run function.

Allowlist: one `_write(path, bytes, verb)`.

| Verbs | May write |
|---|---|
| put, link, withdraw, reject, resolve | `KB/inbox/**` |
| land, unland | `KB/wiki/**` plus the runtime files above |
| adopt, reseal | ledger only |

JSON output:
- success: `{"ok":true,"verb","id","path","ledger_seq"}`
- error: `{"error","detail"}`
- `list` items carry `origin` and `proposed_at`

**5 CLI.** `kb-write.py VERB [--root] [--json]`:
- `put --agent --kind article|gap --slug --confidence --source-ref… --body-file [--type --category --supersedes --resolves --gap-kind --target --query --origin]`
- `link --agent --from --to --type --prose --source-ref… --confidence [--origin]`
- `withdraw ID --reason --by A`: the agent pulls its own proposal.
- `reject ID --reason --by OWNER`: the owner's decision, stamps `decided_at`.
- `land ID… --endorsed-by OWNER [--dry-run]`. Dry-run prints a unified diff per staged file plus one JSON summary, and writes nothing.
- `unland ID --reason --endorsed-by OWNER`
- `land --adopt PATH… --reason --endorsed-by OWNER`
- `seal --reseal --reason --endorsed-by OWNER`
- `list [--state] [--origin PREFIX] [--since DATE]`

Exit codes:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | usage or IO |
| 2 | contract violation |
| 3 | post-check failed, rolled back |
| 4 | conflict: duplicate, existing stem, or stale `base_hash` |
| 5 | lock held |

**6 Algorithm.** DETERMINISTIC unless tagged.

**put / link**
1. Validate agent, slug, enums and flags.
2. Resolve every source ref:
   - `raw:` → `KB/RAW`
   - `wiki:` → `_known_targets`
   - `output:` → `output/` or `KB/output/`
   - `owner:` → a valid date
   - `query:` → missing-gaps only

   **The source rule** requires at least one `raw:` or `owner:` ref, but only for new stems. A supersede inherits the base page's Sources. Any miss → exit 2.
3. Dedupe against open proposals. A hit → exit 4, printing the existing id.
4. Take the lock (`O_CREAT|O_EXCL`), write via `_write` (tmp file + `os.replace`), append the ledger row.

**withdraw / reject**

5. State must be `open` and a reason is required. Set the state, stamp `decided_at` on reject, append the row.

**land**

6. Take the lock. Require `--endorsed-by OWNER`, after the owner has read the proposal.
7. Preflight. Exit 2 unless all hold:
   - state is `open` and kind is not gap
   - WP1 is clean on the targets
   - `read_meta` parses the page
   - body ≥100 words (outside 200–400 → WARN only)
   - every `[[link]]` resolves

   Exit 4 on a stale `base_hash` or an existing stem.
8. Stage in memory:
   - the article with its header run
   - the category index row `| [[stem]] | claim≤300 |`, sorted, with Articles +1 and Updated set
   - master index: Status +1, category row +1, Updated, Recent Updates
   - CATALOG +1
   - Supersedes skip all count bumps.
   - A link appends `- [[to]] — prose` under `## Connections`. If that heading is missing, use `## Related`. If both are missing, create Connections before Open Questions. Then append the edge row with `hash = sha256(prose.strip())[:16]`, exactly as kb-graph computes it.
9. Capture prior bytes of every runtime file, then write.
10. Post-check. All must pass:
    - rebuild with `kb-index --root` and `kb-graph --root`
    - `kb-graph --check` returns 0
    - autolink unresolved count ≤ the preflight count
    - `kb-eval --check` returns 0
    - **`kb-eval --regressions` returns 0** on deterministic cases, if the jsonl exists
    - kb-lint reports 0 FAIL

    On failure: restore every captured file, delete new files, exit 3. The test seam is env `KB_WRITE_FAULT=postcheck`; `KB_WRITE_FAULT=<point>` (`FAULT_POINTS`) simulates a crash at that boundary. Both are documented in the kb-write docstring (Recovery).
11. Commit:
    - append a `land` row with post-write hashes and `resolved:[ids]`
    - append one `resolve` row per gap
    - set the proposal to `landed`
    - unlock
12. If origin is `correction:CID`, call `kb-correct.py landed CID --ledger-seq N`. The hook runs inside the land's journaled op: if it fails, the whole land rolls back (exit 3), so a correction never enters the wiki without its regression case.

**unland, adopt, reseal**
- **unland:** restore prior bytes from the preimage store `KB/inbox/_objects/<sha256>` (git history only as the fallback for older instances), or delete the file if prior was null. Reverse the count bumps and the edge row, rebuild, append `unland`, and reopen the proposal.
- **adopt / reseal:** hash the given paths and append one event with the reason.

**Producer**

13. **LLM:mid.** brain-think writes its gap block.
14. Step 4b: one `put --kind gap --origin skill:brain-think` per gap, at most 4. Exit 4 counts as `dup`.
15. **LLM:mid.** Upgrading a gap: draft the article, then `put --resolves ID`.

**Lint rules**

16. **WP1.** Every wiki file is checked against its expected hash. New, edited and deleted files are reported, each with an `--adopt` hint.
17. **WP2.** Every inbox file must parse, its enums must be valid, and its state must match its last ledger event. For a gap, a land row's `resolved` list counts as that event. Any non-`_` stray file is flagged.

**7 Integration hooks.**
- **Block 17.** WP1 is WARN through P2-S2 and FAIL from P2-S3 (D4). It asserts seal/ledger match, not authorship (no overclaiming).
- **Row 51 Trigger:** `; gap items → KB/inbox/GURU/ via tools/kb-write.py put`.
- **Row 51 Status:** `; P2 gap sink (requalify next run)`.
- **Row 22 Trigger:** `New canon → KB/inbox via kb-write.py put, landed on the owner endorsement`.
- **Logs.** brain-think note: `inbox +{n} ({d} dup)`. Session row: `landed N (ledger seq a–b)`.

**8 Tests.** Runs with `--root tmp`, under 30 s.
1. put writes the inbox only.
2. **FAIL case:** unresolved ref → exit 2, nothing written.
3. **FAIL case:** duplicate gap → exit 4.
4. withdraw keeps the file. A missing reason → exit 2.
5. land: counts bump; Type/Confidence/Provenance present; ledger = disk; WP1 clean.
6. **FAIL case:** fault seam → exit 3, all digests identical, no land row.
7. Stale `base_hash` → exit 4.
8. Landing a gap → exit 2.
9. A landed link is a typed edge with the stripped-prose hash.
10. A direct wiki write flags WP1, and adopt clears it.
11. Lock held → exit 5.
12. A crafted slug or category cannot escape the inbox.
13. `--resolves` leaves WP2 clean.
14. A missing-gap with `query:` is accepted.
15. unland restores the page and reopens the proposal.
16. Re-landing a supersede leaves exactly one Provenance line.
17. dry-run writes nothing.
18. reject stamps `decided_at`.

**9 Migration / rollback.**

Rollout:
1. S1: seal on a clean commit with verify green, after P1-S2.
2. S2: fixture lands, plus one real dry-run.
3. S3: the first real land, on the owner's go.

Rollback:
- **One land:** `unland`.
- **The phase:**
  - Drop block 17 and the session line.
  - Revert the skill, REGISTRY, SYSTEM and protocols edits.
  - **Never git-revert the ledger.** Append `reseal --reason "phase rollback P2"` instead.
  - Landed pages stay valid, since the parsers ignore Provenance.

**10 Target / Batch / Metric.**
- **Target:** `tools/kb-write.py` + `KB/inbox/`
- **Batch:** one brain-think run, at most 4 puts
- **Metric:** WP1 unlanded-change count on the live corpus = 0 at every verify

Acceptance:
- [ ] 18/18 tests
- [ ] seal count = P1 `file_count`
- [ ] 100% of landed pages have ledger hash = disk hash and exactly one Provenance line
- [ ] one live run produces ≥3 gaps
- [ ] skill-test 0 FAIL

Secondary signal: `list --origin skill:brain-think --since` shows ≥3 a week.

Global falsifier: after 4 weeks, ≥12 puts across all origins with 0 landed or resolved means the problem is attention, not tooling. CLERIC takes it, and the per-run cap drops to 2.

**11 Decisions:** §6 D2, D3, D4.

**12 Sessions.**
- **S1 (high tier):** put/link/withdraw/list, allowlist, seal, adopt, reseal, WP1 (WARN) + WP2, block 17. Done when tests 1–4, 10–12 and 14 pass.
- **S2 (high tier):** land, unland, reject, resolve, hook, fault seam, dry-run. Done when 18/18 pass and a real dry-run writes nothing.
- **S3 (mid-tier, deferred):** producer, doctrine, WP1 to FAIL. Done when one live run yields ≥3 gaps.

---

## P3 — Correction compiler + regression suite

**1 Goal / Non-goals.**

- **Goal.** When the owner says an answer is wrong, the correction becomes:
  - one gated wiki diff
  - one permanent regression case that every later land must pass

  [high]
- **Non-goals.**
  - No LLM inside the tools. LLM steps run in fresh subagents, fed packets the tool writes.
  - No direct writes to wiki or skills.
  - No backfill, no embeddings, no LLM cases in verify.
- **v1 scope.** Wiki targets only. A skill defect becomes a `gap_kind: skill` proposal.
- **Reopen trigger.** At ≥3 skill flags, add `kind: skill-patch` to P2: allowlist `skills/*.md` and run skill-test in the post-check.

**2 Dependencies.**
- **P2:** hard for `land`. Without it, land exits 3; every stage through `validate` still works.
- **P1:** `read_meta` and kb-lint.
- **Live code:**
  - `kb-eval` (`load`, `run`, `--root`)
  - `kb-query` (`rank`, `tokenize`, `STOPWORDS`; `ROOT` re-roots in a copied `tools/`)
  - `kb-index --root`, `kb-graph --root`
  - the retrieval step's file list, read at runtime

**3 Files touched.**
- **Create:**
  - `tools/kb-correct.py`
  - `tests/test-kb-correct.py`
  - `evals/regressions.jsonl` (3 seeds)
  - `skills/kb-correct.md`: which packet goes to which tier, fresh context, pointers only
- **Modify:**
  - `kb-eval.py`: `--regressions`, `CASE_SCHEMA`, I-1..I-5
  - `kb-write.py`: post-check runs regressions
  - `skill-test.sh`: expected count = REGISTRY max ID
  - `KB/SYSTEM.md` (D3): `## Correction Protocol`, ≤25 lines. The only doctrine home.
  - `brain-think.md`: one Checks line, "the owner says wrong → `SKILL: kb-correct`"
  - REGISTRY: row 55
  - `verify.sh`: block 18

**4 Data contracts.** Case shape: §1.4. Working dir: §1.3. `open` creates `_corrections/` with `parents=True`.

`record.json` keys:
- `cid`
- `stage`: open, diagnosed, compiled, reviewed, validated, proposed, landed, killed, flagged, failed
- `q`, `owner_says` (verbatim), `points`, `forbidden`, `named_stems`, `terms`
- `gold_sha256`, `gold_locked`, `evidence_stems`, `retrieval_at`, `topk`
- `diagnosis{label,evidence}`
- `compile{target,before_sha256,after_sha256,changed_lines,attempt}`
- `review{verdict,findings}`
- `validate{base,patched,affected,det_rc,verdict}`
- `land{proposal,ledger_seq,case_id}`

LLM result shapes:
- conflict: `{conflict, primary[{path,line}], reason}`
- review: `{verdict APPROVE|REJECT, findings[{severity,line,claim}]}`
- replay: markdown
- judge: `{verdict pass|fail|unclear, evidence, points[{point,met,quote}]}`; anything else counts as FAIL

**5 CLI.**

`kb-correct.py {open|diagnose|packet|record|validate|land|landed|kill|status|replay-all} [CID] [--root] [--json]`

Exit codes:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | gate failed |
| 2 | usage, stage, schema, or drift |
| 3 | P2 absent |

P2 exit codes map in: P2 3 or 4 → 1; P2 2 → 2.

`kb-eval.py --regressions PATH [--check]`:
- On its own, it skips `run()`.
- With `--check`, it prints `{retrieval, regressions:{cases,checked,passed,failed,answer_passed,unchecked,unchecked_ids,dormant,invalid}}` and the exit code is the OR of both.

**6 Algorithm.**

1. **LLM:low.** Split the owner's verbatim correction into points. The owner sees the split.
2. **DET `open`.** Hash the gold and stamp `gold_locked`. Refuse while an earlier cid has no terminal run-log row.
3. **DET evidence scan.**
   - Grep `KB/wiki` and `KB/RAW` for the terms (fallback: `tokenize(points) − STOPWORDS`). A hit is a paragraph with ≥2 terms.
   - **Gold stems = wiki hits ∪ named stems.** Lock them into `gold_sha256` before any ranking runs.
   - Then rank at k=10 and stamp `retrieval_at`.
4. **DET label.** No LLM here.
   - 0 hits → `unreachable`
   - RAW-only hits → `raw-only`
   - gold ∩ top-k = ∅ → `reachable-unretrieved`, which yields a retrieval case
   - gold ⊆ top-k → `reachable-retrieved`. That is a skill defect, so v1 puts a gap and sets the stage to `flagged`.
5. **LLM:mid conflict check.** It sees the evidence paragraphs and the points. **It never sees ranker output (gold independent of the ranker).**
6. **DET.** On conflict, `kb-write put --kind gap --gap-kind contradictory` and set the stage to `flagged`.
7. **LLM:mid compile.** Produce one post-image. After a REJECT, attempt 2 runs on a high-tier model. Max 2 attempts, then `kill`.
8. **DET minimality gate.**
   - exactly one `KB/wiki/**.md` target
   - ≤40 changed lines
   - `read_meta` valid, Updated bumped, Core Claim kept
   - kb-lint 0 FAIL
9. **LLM:mid review.** The reviewer gets only `diff.patch` and the target path.
10. **DET overlays.** Build base and patched copies in `$TMPDIR`, then rebuild the index and graph in each.
    - **Copied:** `KB/wiki`, `tools/`, `skills/`, every file the retrieval step reads, and read-only `KB/output/{retrieval-eval,kb-edge-types,kb-gazetteer}.json`.
    - **Symlinked:** `KB/RAW`.
    - **Excluded:** `KB/inbox`.
    - **Redacted:** the origin lines of every active case.
11. **DET.** On the patched overlay, `kb-eval --root OV --regressions <repo jsonl> --check` must return 0.
12. **LLM:mid blind replay.** The packet holds q and the overlay path only (no gold, `owner_says` or verdict).
    - Runs: ×1 on base, ×3 on patched, ×1 per affected answer case.
    - Affected = `pages ∩ target`. Cap at 25. Above that, stop and report.
13. **DET + LLM:mid judge.** A forbidden-literal pre-check runs first. The judge never sees the diff or `owner_says`. Strict judging and freshness per §1.4.
14. **DET verdict.** All must hold:
    - base judged FAIL
    - patched passes ≥2 of 3
    - every affected case passes
    - step 11 returned 0
    - review is APPROVE

    Retrieval cases skip steps 12–13 and flip via `rank`. Every terminal transition (KILL, FLAG, FAIL, validated) prints a run-log row.
15. **DET `land`.** `kb-write put --kind article --supersedes wiki:<stem> --base-hash <before_sha256> --origin correction:CID --source-ref owner:<date>`. The owner's verbatim stays in `record.json`, and `KB/RAW` is untouched.
16. **DET `landed`.**
    - Read ledger row N. The disk hash must equal the ledger hash.
    - Strip `P2_MANAGED` lines from both the post-image and the disk file; the two must then match.
    - Append the case with the I-3 fields, `landed_version` and `ledger_seq`. Idempotent.

**Cost.** 12 + 2×affected mid-tier-class calls per correction. [moderate]

**Blindness.** Packet whitelists are enforced in code. Fresh context is enforced by the skill. [moderate]

**7 Integration hooks.**
- **Block 18** prints `regressions: N deterministic green, P answer fresh pass, U answer UNCHECKED, D dormant`; U > 0 adds a WARN.
- **Row 55:**
  ```
  | 55 | `kb-correct` | knowledge | A | The owner flags a wrong brain answer → deterministic diagnose, one-page diff, blind replay, inbox proposal + regression case. Seam: `tools/kb-correct.py` | mid | GURU | DRAFT — P3; first discriminating correction flips LIVE |
  ```
- **Loop-log row.** The score column is binary: 1 = discriminating.
  ```
  2026-10-24 | GURU | skill:kb-correct | C-0001 example correction | correction | 1 | 1 | KEEP | diag:raw-only; KB/wiki/x.md +12/-2; review APPROVE; base FAIL→patched 3/3; det green
  ```

**8 Tests.** Fixture LLM JSON, under 10 s.
1. Gold is locked before retrieval.
2. diagnose before open → exit 2.
3. Zero evidence → `unreachable`, with no LLM call.
4. Gold taken only from the ranker → I-3 invalid, judged from the row alone.
5. Two-file or oversize diff → exit 1.
6. Review packet contains the diff only.
7. Replay overlay is blind.
8. A case that already passes on base → rejected.
9. Land with P2 absent → exit 3, nothing written.
10. Ledger hash mismatch → exit 2, no append.
11. landed is idempotent.
12. Eval covers all three kinds plus forbidden.
13. Full flow leaves wiki and RAW unmutated.
14. Step-11 command on a fixture overlay → exit 0.
15. Every retrieval-step file is present in the overlay.
16. All active origins are redacted.
17. kill, flag and fail each write a terminal row. open refuses while one is missing.
18. Works when `KB/inbox` is absent.
19. The diagnose packet contains no top-k stems.

**9 Migration / rollback.**

Seeds (D5). Confidence is [moderate], because most standing rules are behaviour rules, not answers.

| Lesson | Seed |
|---|---|
| 11 | `r-0001` artifact, active, green today. Targets `tools/kb-*.py` and `tools/brain-doctor.py`, forbids both banned phrases. |
| 8 | `r-0002` answer, dormant: "lean, literal, direct, no stacked metaphor" |
| 10 | `r-0003` answer, dormant: "a lexical pass is only a pre-filter" |
| 3, 12 | Dropped. verify 6 and I-3 already enforce them. |
| 1, 2, 4–7, 9 | Dropped. Process rules. |

Dormant cases run only through `replay-all`, manually, before a loop closes.

Rollback:
- Revert the commits.
- Set row 55 to `RETIRED — Canonical home: KB/SYSTEM.md § Correction Protocol`.
- The jsonl stays in git history.
- `_corrections/` may be deleted, because the I-3 fields live on the case rows.

**10 Target / Batch / Metric.**
- **Target:** `evals/regressions.jsonl`.
- **Batch:** 1 correction.
- **Metric, per run:** discriminating = 1, else 0, scored at `validated`, the last stage P3 owns. Discriminating means base FAIL plus patched ≥2/3, or the deterministic retrieval flip.
- **Cumulative yield:** grep `skill:kb-correct` rows. It must reach ≥7 of the first 10 non-conflict corrections. Below that, the diagnose step is theater: revert to manual rule notes.

Acceptance:
- [ ] 3 seeds; block 18 PASS.
- [ ] 19/19 tests.
- [ ] skill-test 0 FAIL.
- [ ] No-LLM guard passes.
- [ ] One real correction reaches `validated`.
- [ ] E2E falsifier is green.

**11 Decisions.** See §6 D2 and D5. Reviewer tier is mid-tier, set once in protocols.md; low-tier is weak at adversarial review.

**12 Sessions.**
- **S1 (mid tier).** Build `--regressions`, the seeds, block 18, skill-test count, and the post-check wiring. Done when the run prints `1 deterministic green, 0 answer deferred, 2 dormant`.
- **S2 (high tier).** Build the core and tests 1–8 and 13–19. Done when a fixture correction reaches `validated`.
- **S3 (mid tier).** Build land/landed, the skill, row 55, the protocol, the pointer, tests 9–11, and run one live correction. Done when that correction reaches `proposed`. If P2 is absent, stop at exit 3.

---

## P4 — Incubation: brain-dream emits gated proposals (deferred under lean path)

**1 Goal / Non-goals.**
- **Goal.** One move over one spine tension per weekly fire. ≤2 proposals go into `KB/inbox/MAGI/` via P2. brain-doctor gains a staleness INFO line. CLERIC measures gate time.
- **Counter.** Two fires ran, both with 0 link candidates, and the schedule is gone. [moderate] Answer: the metric counts landed proposals, and missing it reverts P4. [high]
- **Non-goals:**
  - writes to wiki or RAW
  - a new cron
  - tension resolution
  - backfill
  - `dream-loop` changes (brain-dream step 6 forbids them) [high]

**2 Dependencies.**
- **P2 (hard):** put, link, land, reject, `decided_at`, `--origin`, `list --origin`. Without P2, `emit` and `gate` exit 2.
- **P1 `read_meta`:** if absent, age-check is skipped and `move_skipped` is recorded.
- **P3:** the regressions jsonl, used by emit's dry-run.
- **P0:** optional.

**3 Files touched.**

Create:
- `tools/brain-dream.py` (plan, emit, gate)
- `tools/test-brain-dream.py`
- `logs/loops/brain-dream-gate.jsonl` (at the first real gate)

Modify:
- `brain-doctor.py` + its test: staleness via `read_meta`, +2 cases
- baseline: `staleness_days`
- `verify.sh`: block 19; doctor rc-2 message becomes `brain-doctor: WARN (see lines above)`
- `brain-dream.md`: tool calls only, ≤2,250 B
- row 52
- `eval-brain-dream.md`: inbox writes become legal; the wiki/RAW digest stays a hard gate
- mission guardrail (D6)
- progress columns

Per fire, the run writes `output/brain-dream/{date}_{plan,draft,review}.json` and the brief. Each traces to that fire's run-log row (traceability).

**4 Data contracts.**

*Tensions.* Slugs come from `KB/spine.md`: lowercase both poles, spaces to `-`, joined by `-`. That gives 5 slugs. Legacy `x↔y` progress cells are normalized the same way.

*Moves:* contradict, generalize, find-missing-link, age-check.

*Plan:* tension, move, poles (with `last_verified`, `updated`, `age_days`), candidates, doctor, digests, `move_skipped`.

*Draft* (LLM-written):

| Move | Fields |
|---|---|
| link | `s`, `o`, `type` ∈ `type_vocabulary`, `prose` |
| generalize | `title`, `body_md`; ≥3 cites across ≥2 categories; ≥1 `raw:` ref, else it is demoted to a gap |
| contradict | `bullet_md` only |
| age-check | cites only |

- Every proposal carries `cites[stem#ordinal]` and `confidence` (default low).
- Supersede bodies are built deterministically:
  - contradict = original bytes plus the bullet under `## Open Questions`, creating the heading if absent.
  - age-check sets only Last-Verified.
  - `body_md` on either → exit 1.

*Other contracts:*
- **Review file**, written separately by the reviewer: `[{proposal_index, sha256, verdict, killed_claims}]`.
- **Origin:** `brain-dream:{date}:{tension}:{move}`.
- **Progress columns:** `Run | Tension | Move | Pages read | Proposals | Landed | Gate min | KB digest held | Verify | Result`.
- **Gate ledger:** `{week, events[{ts, kind opened|decided, inbox}], owner_min, measured}`.
- **Staleness:** `{threshold_days, articles, verified, unverified, stale, oldest[5]}`.

**5 CLI.**
```
plan [--root] [--date] [--tension] [--move] [--json]
emit DRAFT --review REVIEW [--root] [--dry-run]
gate [--root] [--report] [--pilot] [--week]
```

| Exit | Meaning |
|---|---|
| 0 | ok |
| 1 | validation failed, nothing written |
| 2 | blocked: P2 absent, digest drift, or a fire still open |

Over-budget is a JSON field, `over_budget`. It is not an exit code.

**6 Algorithm.**
1. **DET plan.** Pick the least-recent tension and, independently, the least-recent move. Run `verb_search` per pole (k=8). Record the digests.
2. **DET candidates.**
   - contradict: A∖B × B∖A, ≤3
   - generalize: triples across ≥2 categories, ≤3
   - missing-link: no edge and hops ≥3 or none, ≤5
   - age-check: by Last-Verified, else Updated labeled unverified, ≤5
3. **DET.** `brain-doctor --json`.
4. **LLM:mid.** Read ≥2 pages, one per pole. Draft ≤2 cited proposals. Never reconcile the tension.
5. **LLM:mid reviewer** (tier per instance config). Sees only each proposal and its cited sections. Writes `_review.json`.
6. **DET emit.** Checks:
   - plan matches
   - ≤2 proposals
   - cites ⊆ graph sections ∩ candidates
   - every proposal hash has a `pass` review row
   - digests unchanged
   - overlay `kb-eval --regressions` returns 0, so a case-breaking proposal is never put

   Then `kb-write put|link --origin brain-dream:…`.
7. **LLM:low.** hygiene-loop, unchanged.
8. **LLM:mid.** Write a ≤1-page brief.
9. **DET close.** Re-hash, run autolink, verify. Write the progress row and the run-log row.
10. **DET gate.**
    - Refuses while a plan has no progress row, so nothing is gated mid-fire.
    - Shows a unified diff against the superseded page and logs `opened`. The owner decides via P2 land or reject.
    - `owner_min` sums the gaps between consecutive events, each gap capped at 5 idle minutes. It is a capped upper bound.
    - A landed proposal with no `opened` event → `measured:false`, never a pass.
    - `--pilot` prints `{fires, proposals, landed, landed_per_fire}` from P2 land rows with this origin, counting only `decided_at` ≤7 days after the fire.
11. **LLM:low CLERIC.** Log a burden row. If the week is over the global budget, hand off with the fix order: batch first, then default.

**7 Integration hooks.**
- Verify: block 19, plus the doctor message change.
- Row 52 Status: `DRAFT — P4 proposal-emitting; requalify per eval-brain-dream.md`.
- Loop-log row per fire:
  ```
  2026-11-01 | MAGI+GURU | skill:brain-dream | weekly-brain-dream | brief+proposals | n/a | 1 | DRAFT | tension:armor-opening; move:find-missing-link; proposals:2; landed:1; owner_min:3.5 (capped); digest held; verify 0 FAIL
  ```

**8 Tests.** Fixture: `kb_testkit` plus 5 articles, the spine, a progress table with a legacy row, and the **real** P2 in tmp.
1. The live spine yields 5 slugs.
2. Rotation works, legacy rows included.
3. Plan output is byte-deterministic.
4. Missing-link candidates have no edge.
5. Age-check fallback is labeled unverified.
6. Emit writes only to the inbox.
7. **FAIL:** unknown cite → exit 1.
8. **FAIL:** 3 proposals or a move mismatch → exit 1.
9. **FAIL:** wiki drift → exit 2.
10. **FAIL:** review hash mismatch → exit 1.
11. **FAIL:** `body_md` on a supersede → exit 1.
12. **FAIL:** a regression-breaking proposal → exit 1.
13. P1 absent → age-check skipped.
14. An overnight gap is capped.
15. An unmeasured week is flagged.
16. `--pilot` respects the 7-day window.

Doctor, +2 cases:
- Staleness never changes status.
- Staleness is N/A without a threshold.

**9 Migration / rollback.**

No backfill. Unverified starts near 589 and falls only as age-checks land.

Rollout:
- S1: fixture only.
- S2: one supervised fire.
- S3: re-arm the existing mission via `SKILL: mission-schedule`.

Rollback:
- Revert the commits.
- Run `withdraw --reason "P4 rollback"` on every pending proposal.
- Delete the schedule.
- Landed proposals stay, because the owner approved them. Reverse one via P2 `supersedes` or `unland`.

**10 Target / Batch / Metric.**
- **Target:** `skills/brain-dream.md` + `tools/brain-dream.py`
- **Batch:** 1 tension × 1 move × ≤2 proposals per fire; 4-fire pilot.
- **Metric:** `landed_per_fire` from `gate --report --pilot`. **≥1.0 → LIVE candidate. Anything lower → revert.**

Acceptance:
- [ ] 16/16 tests plus doctor tests
- [ ] verify and skill-test: 0 FAIL
- [ ] skill file ≤2,250 B
- [ ] digest unchanged on every fire
- [ ] ≥2 cites per proposal
- [ ] `owner_min` measured every week, and within P4's slice
- [ ] a fresh independent judge scores it before LIVE; the CODA never self-qualifies

**11 Decisions:** §6 D2, D6.

**12 Sessions.**
- **S1 (high tier):** seam, staleness, block 19, E2E P4 variant. Done when live `plan --json` is valid and the digest is unchanged.
- **S2 (mid tier):** skill, row 52, eval, mission, one supervised fire, first gate line.
- **S3 (mid-tier, MAGI):** pilot, judge, then LIVE or revert, logged.

---

## 5. Risk register + cross-phase rollback

| Risk | Rating | Mitigation |
|---|---|---|
| Cases don't discriminate | [high] | E2E step 4; if it fails on the fixture, stop P3 |
| P1 batch FAILs stall CODA or teach it to ignore FAIL | [high] | Rebuild plus full verify 0 FAIL after every batch |
| P2, P3 and P4 all feed one the owner gate with no shared cap | [high] | One global weekly budget (D2); CLERIC measures it from the ledger; global falsifier |
| 13 sessions before one corrected answer lands | [high] | Lean 8-session path (D6) |
| Header layout drift breaks byte and hash checks | [moderate] | One order in `CONTRACT`; `header-order` WARN; Provenance replaced, not appended; P3 strips `P2_MANAGED` |
| Replay cost scales with the suite | [moderate] | Cap of 25; no skill targets in v1 |
| WP1 FAIL fires on Obsidian hand edits | [moderate] | WARN until P2-S3; CLERIC counts adopts (D4) |
| Hardcoded counts go stale after the first land | [moderate] | Capture and log, never assert; skill-test reads REGISTRY |
| recall@6 shifts after migration | [moderate] | Measured gate; revert on change, no tuning |
| Loop-log over cap causes boot DRIFT | [moderate] | Rotate in P1-S1; one row per session |
| Fresh-context blindness rests on the skill, not code | [moderate] | Whitelists plus test 19; residual risk accepted |
| The 2-idle guardrail kills the pilot | [low] | Amend before P4-S3 (D6) |

**Cross-phase rollback:**
- Roll back strictly in order: P4 → P3 → P2 → P1.
- Never git-revert `_ledger.jsonl`. Append `unland`, `withdraw` or `reseal` with reason `phase rollback Pn` instead.
- P1 after the seal: `seal --reseal`.
- P2: landed pages stay valid, and P3 `landed_version` hashes stay checkable.
- P3: cases stay in history, and the REGISTRY row is retired, not deleted.

---

## 6. Open decisions for the owner (one MAGI chat, before session 1)

1. **Header syntax: bold-line or YAML?** Default: **bold-line.** One parser convention, zero dependencies, and 4 tools already read it.
2. **Who lands, and how much time does it get?** Default: **The owner lands everything** (P2, P3, P4), with MAGI pre-screening in chat.
   - Global gate budget: ≤10 min/week. [low] This is a starting number, not evidence.
   - Brain-dream's share of that: ≤5 min.
   - Revisit if CLERIC shows a breach: after 10 corrections (MAGI could land P3), and after the pilot (MAGI could land age-checks).
3. **`KB/SYSTEM.md` edits.** P1 adds a template pointer. P2 adds the vault line and Write-Back Protocol. P3 adds the Correction Protocol. The file says "Read only by LLM." Default: **yes, one approval now.** the owner sees each exact diff in its session. Without this, the doctrine has no home.
4. **Obsidian hand edits under WP1.** Default: **WARN through P2-S2, FAIL from P2-S3.** verify prints the exact `land --adopt` line. Revert to WARN if CLERIC counts more than 2 adopts a week.
5. **Seeds and budgets.** Default: **accept all three.**
   - The 5 `source` overrides, `client-pricing-structures` included.
   - Ratchet the soft 400-word budget at its captured value. No rewrite campaign, even though 49% of articles exceed SYSTEM.md's 200–400 today.
   - P3's seed table: 1 active, 2 dormant, 9 dropped.
6. **Scope.** Default: **the lean path.** Run sessions 1–8. Run 9–13 only after 3 real corrections land discriminating cases. When P4 opens:
   - staleness threshold: 180 days
   - re-arm the existing mission for 4 fires, Sunday 18:00 America/Chicago
   - "idle" means 0 proposals emitted
   - the pilot overrides the 2-idle kill

---

## 7. Not building + reopen triggers

**Not building:**
- embeddings
- reranker
- pgvector
- graph DB
- LLM entity extraction
- federation/OAuth
- P5 skill optimization, until this loop proves itself

Lexical plus graph retrieval is enough at this corpus size. GBrain's own default agrees: PGLite, ≤50K pages, no pgvector. [high]

**Reopen when any of these happens:**
- the corpus passes 5,000 articles
- recall@6 falls below 0.70 after P0–P1
- a second human needs scoped access

**Falsifier for the whole spec.** After P2 and P3, if the weekly count of corrections that land as wiki edits is still 0, tooling was never the gap. Attention was. CLERIC owns the next move, not CODA.

## Feedback upgrade amendment (2026-11-04)

The owner authorized onboarding and maintenance upgrades independently of deferred phases 9–13. Current contracts: `bin/kb query` uses hybrid search; internal correction ranking and `--keyword` stay unchanged. Fresh installs seed one neutral dormant case; the historical three-rule table above is reference-instance history, available in `examples/reference-regressions.jsonl`. Existing cases and config are never rewritten by bootstrap. `souls/` holds shipped roles; legacy instance globs remain valid. See UPGRADING and TRUST for guided corrections, read-only review/status, source-preserving imports and optional signed lands. New helper commands reuse the canonical write and correction schemas rather than bypassing them.
