# Second-Brain Loop — Continuation Handoff

> For any builder: a coding agent in any harness, any model, or a human engineer.
>
> **Development continues in this package** (`second-brain-loop/`). Sessions 1–5 were built inside a private reference instance and extracted here on 2026-10-26; commit ids in §4 belong to that instance's history, not this repo's. From session 6 on, build, test and commit here.
> Updated 2026-11-09. Implementation status: lean path complete; release and owner acceptance are separate from test results. See CHANGELOG Unreleased and UPGRADING for the feedback upgrade. **Lean path complete: sessions 1–8 done (0.2.0).**

## 1. What this is

A Git-backed Markdown knowledge base (`KB/wiki`) with deterministic, stdlib-only Python tools in `tools/`. The build turns it into a **second-brain loop**:

- **Typed pages.** Every wiki page declares a `**Type:**` header. `tools/kb-lint.py` checks the contract with zero LLM calls.
- **Gated write-back.** Agents write only to `KB/inbox/`. One human owner endorses each land. Every write is hashed into an append-only ledger.
- **Correction compiler.** Each owner correction becomes one gated diff plus a permanent regression case. Deterministic cases gate later lands; answer freshness follows the configured policy.

Nothing in the tools names a person, a model, a vendor or a harness. Instance identity lives in one file (§3).

**Read in this order:**
1. `docs/SPEC.md` — **the build spec, canonical.** §0 session plan and E2E acceptance, §1 shared contracts (defined once), P1–P4 per-phase detail, §6 rulings.
2. `docs/SWARM.md` — the multi-agent doctrine the build runs inside (MAGI orchestrates, GURU specs, CODA builds, CLERIC audits owner time).
3. This file — where the build stands.
4. `docs/RESEARCH.md` — why (SOTA survey, gap analysis). Optional.

## 2. Rulings (accepted 2026-10-23; do not re-ask)

1. Bold-line `**Key:**` headers in the wiki. No YAML.
2. The owner lands everything (`--endorsed-by OWNER`). MAGI pre-screens. Gate budget ≤10 min/week.
3. `KB/SYSTEM.md` edits approved once; the exact diff is shown in the session that makes it.
4. WP1 (wiki hash vs ledger/seal) is WARN through P2-S2, FAIL from P2-S3.
5. Five `source` type overrides; the 400-word soft article budget ratchets at its captured value; the P3 seed table is accepted.
6. **Lean path: sessions 1–8.** Sessions 9–13 open only after 3 real corrections land discriminating cases.

## 3. Instance config — `KB/kb.json`

| Key | Meaning | Default |
|---|---|---|
| `owner` | The one human id that endorses lands, rejects and resolves. Lowercase `^[a-z][a-z0-9_-]{1,31}$`. Also accepted as an alias of the `owner:` source-ref prefix, so pre-config history stays valid. | `owner` |
| `title` | Name shown in the search dashboard header. | `Knowledge Base` |
| `agents` | Extra agent ids allowed to write to the inbox. Uppercase. | `[]` |
| `agents_glob` | Pattern whose matches' parent folder names are agent ids. Set `""` to disable. | `agents/*/soul.md` |
| `dashboard` | Where `kb-index` writes the search page. | `KB/output/kb-search.html` |
| `regressions` | Regression cases; `land` gates on them while the file exists. | `evals/regressions.jsonl` |
| `baseline` | Lint and doctor baselines. | `evals/kb-health-baseline.json` |
| `catalog` | Optional page whose `**Articles:**` count `land` bumps. | `KB/CATALOG.md` |
| `registry` / `router` | Optional skill table / `{"registered_names": [...]}` checked for `Consumers:` headers. | `skills/REGISTRY.md` / `config/router.json` |
| `spine` | Optional hand-written theme map for `bin/kb ask themes`. | `KB/spine.md` |

Every key is read through `tools/kb_config.py`. `kb.example.json` lists them all. No code changes to adopt elsewhere.

## 4. Progress (lean path)

| # | Session | Tier | State | Commit |
|---|---|---|---|---|
| 1 | P1-S1 kb-lint core, testkit, `kb-index --root`, verify renumber | high | DONE | `fc27975` |
| 2 | P1-S2 Type migration (602 files), baseline, verify block 16 | mid | DONE | `3f96271` |
| 3 | P2-S1 kb-write put/link/withdraw/list, seal, WP1/WP2, block 17 | high | DONE | `e08ad86` |
| 4 | P2-S2 land/unland/reject/resolve, dry-run, fault seam, correction hook | high | DONE | `03f2094` |
| 4b | Agnostic pass: `KB/kb.json` owner/agents config, neutral tests and docs | high | DONE | see `git log` |
| 5 | P3-S1 `kb-eval --regressions`, seeds, block 18, regressions gate on land | mid | DONE | `7ef0302` |
| 5b | Standalone package: `kb_config.py` path keys, `bootstrap.sh`, `bin/kb`, demo wiki, `scripts/verify.sh` | mid | DONE | this repo's first commit |
| 6 | P3-S2 `kb-correct.py` core: open/diagnose/packet/record/validate/kill/status, packets, gate, overlays | high | DONE | see `git log` |
| 7 | P3-S3 land/landed/replay-all, `skills/kb-correct.md`, Correction Protocol, one live correction | mid | DONE | see `git log` |
| 8 | LOOP-E2E `tests/test-kb-loop-e2e.py`, E2E last in verify and `make test`, 0.2.0 release pass | high | DONE | see `git log` |
| 9–13 | P1-S3, P2-S3, P4-S1..S3 | — | DEFERRED until 3 real corrections land discriminating cases (ruling 6) | |

Tiers are provider-neutral: low / mid / high = any vendor's small / medium / large model.

**Verified state (reference instance, at extraction):**
- All 602 wiki files typed: 584 article, 12 taxonomy, 1 routing, 5 source.
- `kb-lint --rule all`: 0 FAIL, 1 known WARN (one page carries two Sources lines).
- Seal covers 602 hashes. Ledger rows 1–6 hold two put→withdraw probes and one full put→land→unland→withdraw round-trip, which left the wiki byte-identical with recall@6 held at 0.745.
- `test-kb-write.py` 22/22, `test-kb-lint.py` 18/18, `test-kb-eval.py` 11/11, `verify.sh` 0 FAIL (block 18 included).

**Verified state (this package):** `./bootstrap.sh --owner test --demo` then `make verify` → 0 FAIL, 0 WARN; `make test` 8/8 suites green with `test-kb-loop-e2e.py` last (`test-kb-correct.py` 30, `test-kb-write.py` 23, E2E 2); `make verify` ends with the LOOP-E2E line; README quickstart and daily-use steps re-run verbatim on a fresh clone.

## 5. RESUME HERE — lean path complete; wait for 3 real corrections

Session 8 shipped `tests/test-kb-loop-e2e.py`: on `kb_testkit.fixture(..., regressions=True, git=True)` it drives `kb-correct` and `kb-write` as CLIs with fixture JSON for every model step. `open → diagnose → record → validate` reaches `validated`; `kb-correct land` → owner `kb-write land` → hook `landed` appends exactly 1 case; `kb-eval --regressions` exits 0, `kb-lint --rule all` 0 FAIL, ledger hash = disk hash, one Type/Confidence/Provenance line; `kb-write unland` → `kb-eval --regressions` exits 1 (discrimination proof). It runs last in `scripts/verify.sh` (section 7, spec block 20) and in `bin/kb test`.

**Next.** Advanced phases 9–13 still wait for 3 real discriminating corrections. The owner-authorized feedback upgrade addresses maintenance and onboarding independently; it does not establish that milestone.

**Carried notes.** (a) `unland` of a correction leaves its case active, so later lands fail until the fix is relanded or the case retired. (b) New lands store exact preimages in `_objects/`; supersede undo works with `KB/` ignored. Git is retained as a fallback for older lands. (c) No `skills/REGISTRY.md`, `brain-think` or Write-Back Protocol ships; spec P3 row 55 waits for session 10. (d) External replay remains manual; `answer_policy=require-fresh` gates lands on fresh results, with proposal replay before approval. (e) `docs/RESEARCH.md` line 31 names third-party tools. (f) Default queries and new corrections use hybrid search. Existing cases and records keep their recorded legacy method.

## 6. Rules for every session

- Zero LLM calls inside any `tools/*.py`. Stdlib only. Each suite greps its tool for network imports and model CLIs.
- Agents write only to `KB/inbox/`. Only `kb-write land` touches `KB/wiki`.
- One canonical home per contract (spec §1.1). Import it, never redefine it.
- Every new file traces to a run-log row. No placeholder files.
- The reference instance used a local-only publication rule. For this public package, follow CONTRIBUTING and the current owner's authorization for branches, pushes and releases.
- Stop and report on any consequential blocker. Never route around it.
- Verify against disk before claiming done. A builder's report is a claim, not proof.

## 7. Session brief template (used 4×)

Give each CODA session (any harness, any model at the listed tier): its spec §0 row, spec §1, its phase section, the pre-SHA, and its done-checklist. Use the tier from §4. One mission per session. End with the repo's close step. MAGI verifies the commit against disk before starting the next session.
