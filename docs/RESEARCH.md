---
MAGI HANDOFF
agent: GURU (via MAGI)
mission: Upgrade "agentic second brain SOTA" paste to build-ready spec, grounded in the reference instance's live KB
date: 2026-10-23
type: build-ready spec (research brief + structured data + CODA phases)
score: 8.6/10 (Accuracy 9, Actionability 9, Completeness 8, Conciseness 8, Clarity 9)
key_findings:
  - Paste is directionally right, factually loose: 4 of 8 named claims corrected below. Cornelius has no "canon", 114 stars, and needs Trinity for autonomy; GBrain's reranker, source-tier boost, and its own OAuth leak caveat were omitted.
  - the reference instance already has 5 of 7 SOTA layers (Markdown truth, graph, synthesis+gaps, skills, governance). The two real gaps are agent WRITE-BACK with provenance and a CORRECTION COMPILER with a regression suite (Meta's loop). Everything else is scale theater at 589 articles.
  - Hybrid/embeddings/rerank stay REJECTED on existing evidence until corpus >5k articles or recall@6 <0.70. Memory-benchmark numbers (LoCoMo/LongMemEval) are vendor-reported and mutually contradictory; none applies to a 3.3MB wiki.
suggested_use: CODA builds P0–P3 in order (gazetteer → frontmatter contract + linter → inbox write-back → correction compiler). MAGI owns the endorsement gate. The owner reviews before any commit.
---

# Agentic Second Brain — SOTA Spec v2 (the reference instance delta)

**Status:** DRAFT. Nothing here is final until the owner reviews.
**Scope:** (1) fact-check the paste, (2) state the verified SOTA pattern, (3) gap it against the reference instance's live KB, (4) hand CODA a phased build with Target/Batch/Metric per phase. Out of scope: multi-user federation, external sync, any hosted product.

## 0. Counterargument first

The paste's thesis: "value is in connections + procedural memory; systems that get smarter every night win." Lead counter: **at the reference instance's scale, the bottleneck is not retrieval, graph, or overnight enrichment. It is that corrections die in chat.** `[high]` the owner fixes an agent, the fix goes to a 12-line the standing-rules file, and the KB page that caused the error is untouched. Meta's result (zero regressions across cycles, days→minutes) came from compiling corrections into reviewed file edits plus a regression test, not from a better vector index ([Meta Engineering, 2026-09-02](https://engineering.fb.com/2026/09/02/ml-applications/organizational-second-brain-ai-learns-from-experts/)). GBrain's own eval says the same thing in reverse: its graph lift (R@5 0.98 vs 0.69) is measured on a corpus orders of magnitude larger than ours ([garrytan/gbrain](https://github.com/garrytan/gbrain)). Build the loop, not the lake.

Second counter: the paste treats three systems as peers. They are not. GBrain is 31.1k stars, 10k commits, MIT. Cornelius is 114 stars, MIT, and "meant to be run on Trinity" for anything autonomous ([Abilityai/cornelius](https://github.com/Abilityai/cornelius)). Meta's is a blog post with no code. Steal patterns, not stacks.

## 1. Fact-check ledger (paste → verified)

| # | Paste claim | Verified | Δ |
|---|---|---|---|
| 1 | GBrain ~30k+ stars | 31.1k stars, 4.7k forks, 10,189 commits, MIT | ✔ |
| 2 | GBrain = pgvector/HNSW + tsvector hybrid | Default store is **PGLite** (Postgres 17 via WASM, "up to ~50K pages"); pgvector only for shared/large. Scoring = vector + keyword + RRF + **source-tier boost** + **reranker** (Voyage `rerank-3-lite` default; local Qwen3-Reranker via llama.cpp). tsvector not named. | partial |
| 3 | GBrain autopilot / overnight | `gbrain autopilot` cron loop; 66 jobs in Tan's deployment (his figure, unaudited). "Dream cycle" described, not specified. | ✔ caveat |
| 4 | GBrain federation + OAuth scoping | OAuth 2.1 scopes `read/write/admin/agent`. README itself warns sources don't isolate local-file or shared-DB callers and auth tests "cover specific paths," not no-leak guarantees. Paste omitted. | caveat |
| 5 | Cornelius: atomic notes, lenses, endorsement gate, canon, skills library | Atomic notes ✔ ("one idea per note"). **Canon: absent.** "Lens" = layer 5 of a 7-layer Brain Dependency Graph (signal→impression→insight→framework→lens→synthesis→index). One human endorsement gate ✔. 60 skills, FAISS local search, Obsidian `Brain/00-Inbox…05-Meta`. | 2 of 5 wrong |
| 6 | Cornelius "dozens of agents around one brain" | README lists 10 sub-agents + `/brain-merge` across instances. Trinity adds agent-to-agent delegation. "Dozens" unsupported. | overstated |
| 7 | Meta: structured knowledge + recipes + feedback→PRs + regression | ✔ and under-specified: 200+ files in four kinds (position, taxonomy/vocab, routing index, gateway); YAML frontmatter declares `dependencies` and `consumers` → bidirectional dependency graph; deterministic linter; adversarial reviewer in fresh context sees only diffs; blind-judge replay; recipe staging cut tokens/turn ~80%; 3 sprints / 6 weeks; zero regressions. Compliance domain. | ✔ + detail |
| 8 | (implicit) memory frameworks are a benchmarked field | Vendor numbers contradict: Mem0 claims LongMemEval 94.4 ([mem0 blog](https://mem0.ai/blog/state-of-ai-agent-memory-2026)); Atlan reports Mem0 49.0 vs Zep 63.8 ([Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)). Different harnesses. Treat as marketing. `[moderate]` | noise |

## 2. SOTA pattern, verified (seven layers)

1. **Markdown truth, Git-backed, soft-delete** — GBrain, Meta, Cornelius all converge. `[high]`
2. **Typed pages with declared dependencies** — GBrain schema pack: 15 types (person, company, atom, concept, source, project…), path-prefix→type mapping, `extractable:` and `expert_routing:` flags. Meta: `dependencies`/`consumers` in frontmatter → linter catches dangling refs, size budgets, id collisions, cycles. `[high]`
3. **Retrieval = lexical + graph first; vectors when scale demands** — GBrain hybrid+rerank is tuned for 50K-page brains. The owner's own head-to-head put GraphRAG last of 4 and rejected embeddings at ~2000× below payoff scale (run log 2026-08-12). `[high]`
4. **Synthesis with citations + explicit gap analysis** — `gbrain think` = ranked pages + cited answer + gaps. the reference instance's `brain-think` already does this (mandatory stale/thin/contradictory/missing). `[high]`
5. **Agents write back, through a gate** — GBrain: `put_page`/`add_link` with provenance, corrections, withdrawal; `visibility: private`; capture off by default. Cornelius: inbox → one human endorsement gate. Meta: diffs land as reviewed PRs. `[high]`
6. **Procedural memory as progressively-loaded Markdown skills** — GBrain `skills/` + `gbrain skillopt` (optimize SKILL.md against a benchmark, keep only higher-scoring edits). Meta recipes: imperative, zero domain facts, staged → ~80% token cut. Vendor agent-skill docs: name+description at boot, body on match, resources on demand. `[high]`
7. **Self-improvement loop with regression suite** — Meta diagnose→compile→validate→land; every landed fix becomes a regression case. Cornelius incubation loop (rotating analytical moves over open topics, cron) + `/coherence-sweep`. GBrain autopilot. `[high]` on pattern, `[moderate]` on anyone's claimed outcomes.

## 3. the reference instance vs SOTA — gap table

| Layer | the reference instance now | Verdict |
|---|---|---|
| 1 Markdown truth | `KB/wiki` 589 articles (3.3MB), `KB/RAW` 1,575 sources (13MB, 78% cited), local-only shield commits, `verify.sh` 0 FAIL | **HAVE** |
| 2 Typed pages + deps | Categories + `KB/spine.md`; no `type:`/`depends_on:`/`consumers:` contract; **entity gazetteer missing** (MENTIONS edges inert, per `KB/CATALOG.md`) | **GAP** |
| 3 Retrieval | `kb-query.py` lexical, `kb-graph.py` 3,500 edges, recall@6 0.755, `connect/provenance/themes/gaps` verbs | **HAVE** (no source-tier boost) |
| 4 Synthesis + gaps | `brain-think` LIVE | **HAVE** |
| 5 Agent write-back | `kb-ingest` DRAFT unproven; `kb-autolink.py` exists; no provenance-carrying write path; agents effectively read-only | **GAP — largest** |
| 6 Skills | 54 skills, the skill registry, two-layer resolver, skill-test harness 54/54 | **HAVE** (no benchmark-driven skill optimization) |
| 7 Correction loop | the standing-rules file (manual, capped 1KB), `kb-eval.py`, `evals/`, `brain-dream` DRAFT report-only, `dream-loop` weekly | **GAP** — corrections never become KB edits + tests |
| Governance | Single owner, draft-until-reviewed, run log, no egress | **HAVE** (solo-adequate; federation out of scope) |

## 4. Build spec — CODA phases (Target / Batch / Metric)

> Build-ready detail (contracts, CLI, tests, 13-session plan, E2E acceptance) lives in `docs/SPEC.md`. This section is the summary; that file is canonical for CODA.

**P0 — Entity gazetteer** (already specced in `KB/CATALOG.md`; just do it)
Target `output/kb-gazetteer.json`. Batch: one file, 60–150 entities, 4+ file threshold, no common-word aliases. Metric: MENTIONS edges > 0 and recall@6 ≥ 0.755 held.

**P1 — Frontmatter contract v2 + deterministic linter** (Meta pattern)
Target: `kb-graph.py` (+ `tools/kb-lint.py`), every `KB/wiki/**/*.md`. Add:
```yaml
type: position | taxonomy | routing | gateway | article | source
depends_on: [wiki/path, ...]
consumers:  [wiki/path, skill:brain-think, agent:GURU]
confidence: high | moderate | low
last_verified: 2026-10-23
```
Linter checks (all deterministic, zero LLM): dangling `depends_on`, orphan `consumers`, size budget per type, duplicate ids, dependency cycles. Batch: migrate by category (13 `_index.md` groups). Metric: 589/589 lint-clean, 0 cycles, `verify.sh` gains one check.
Why `type:` matters: Meta's "position files" = the owner's operating systems (`os-audit` output); "gateway files" = threshold tests before an agent enters a domain (voice-guard already is one, unlabeled).

**P2 — Inbox write-back with provenance + one endorsement gate** (GBrain verbs, Cornelius gate)
Target: `tools/kb-write.py` with verbs `put --type --source --provenance`, `link`, `withdraw`. Agents write **only** to `KB/inbox/{agent}/{date}-{slug}.md`; frontmatter carries `proposed_by`, `source_refs`, `confidence`, `supersedes`. MAGI runs the gate; `land` moves to wiki, runs autolink, appends a run-log row; `withdraw` soft-deletes with reason. Batch: wire GURU + brain-think gap findings first (they already emit "missing/thin" items with no sink). Metric: 100% of landed pages carry provenance; 0 direct agent writes to `KB/wiki` (linter enforces); gap-analysis items converted to inbox proposals per week ≥ 3.

**P3 — Correction compiler + regression suite** (Meta loop, the 200% move)
Target: `tools/kb-correct.py`, `evals/regressions.jsonl`. Flow per correction:
1. **Diagnose** — was the right answer reachable from `KB/RAW` + wiki? Yes → recipe/skill defect; no → knowledge gap; the owner and source disagree → ambiguity, flag.
2. **Compile** — minimal diff (one page or one skill). Adversarial review in a **fresh context that sees only the diff**. Linter from P1.
3. **Validate** — blind replay: re-run the failing question through `brain-think` with the diff applied, judge without showing the expected fix; then run `regressions.jsonl` (Q&A pairs) via `kb-eval.py`.
4. **Land** — write to `KB/inbox/` for the gate; on land, append `{q, expected, failing_version, landed_version, date}` to regressions.
Regression case shape:
```json
{"id":"r-0001","q":"...","expected":"...","forbidden":["..."],"origin":"rule:<id>","landed":"2026-10-23"}
```
Batch: seed from the 12 rules in the standing-rules file (each becomes a case or dies). Metric: zero regressions across cycles; every correction yields +1 case; standing-rules growth → 0 (rules become tests). Falsifier: if 10 corrections produce <7 reachable-vs-gap diagnoses that CODA agrees with, the diagnose step is theater, revert to manual.

**P4 — Incubation on existing dream-loop** (Cornelius pattern, writes gated)
Target: `brain-dream` skill → from report-only to proposal-emitting. Rotating moves over the one weekly tension it already surfaces: {contradict, generalize, find-missing-link, age-check}. Output goes to `KB/inbox/MAGI/`. Coherence sweep = `brain-doctor.py` + `last_verified` staleness. Batch: 1 tension/week. Metric: 1 inbox proposal/week; stale-page count trending down; the owner gate time ≤ 5 min/week (CLERIC measures).

**P5 — Skill optimization loop** (GBrain `skillopt`, optional)
Target: one skill at a time against its eval in `evals/`. Keep edit only if score rises (GURU loop mode already encodes this; apply it to `SKILL.md` files). Metric: ≥ +0.5 on the skill's metric or revert.

**NOT building (data says so):** embeddings, reranker, pgvector, graph DB, LLM entity extraction, federation/OAuth. Re-open trigger: corpus > 5,000 articles **or** recall@6 < 0.70 after P0–P1 **or** a second human needs scoped access. GBrain's own default (PGLite, ≤50K pages, no pgvector) agrees. `[high]`

## 5. Code finds worth lifting verbatim (patterns, not deps)

- **Single contract → CLI + MCP**: GBrain generates both from one `BrainEngine` interface (`src/core/engine.ts`, 140+ methods). the reference instance equivalent: one `kb_api.py` module; `kb-*.py` CLIs and any future MCP server import it. Kills drift between tools.
- **Path-prefix → type** (`gbrain-base-v2`, 15 types, `extractable:`/`expert_routing:` flags). Map `KB/wiki/<category>/` → `type:` default, override in frontmatter.
- **Auto-link without LLM** on trusted local writes (`[[people/alice]]` pattern match) — the reference instance's `kb-autolink.py` already matches; add it as a P2 `land` hook.
- **Edges are evidence, not proof** (GBrain README wording). Adopt as `kb-graph-query.py` output footer.
- **Seven-layer BDG** (Cornelius): signal → impression → insight → framework → lens → synthesis → index. Use as the `type:` ladder for P1 if the four Meta kinds feel too compliance-shaped. Pick one; don't run both.
- **Recipe = imperative workflow, zero domain facts** (Meta). Audit `skills/*.md` for embedded facts; move facts to wiki pages, leave the skill as pointers (already the reference instance doctrine: "skills point to doctrine, never copy it").
- **Adversarial reviewer sees only the diff** (Meta). Cheap to implement as a low-tier pass in P3; matches adversarial-by-default review.

## 6. Open questions / falsifiers

- `[unknown]` Does the owner want MAGI or himself at the endorsement gate? Meta uses SMEs; Cornelius uses one human. Default proposed: MAGI gates, the owner spot-checks weekly via CLERIC burden report.
- `[moderate]` P3 assumes `brain-think` is deterministic enough for blind replay. If answer variance > judge tolerance, replay needs 3 runs + majority.
- `[low]` Meta's ~80% token cut came from replacing one flat instruction file with staged recipes. the reference instance already stages via two-layer skill resolver; expect far less than 80%. Measure before claiming.
- Falsifier for the whole spec: if after P2+P3 the weekly count of corrections that reach the KB as landed edits is still 0, the gap was never tooling. It was attention. Then CLERIC, not CODA, owns the next move.

## Sources
GBrain README (31.1k★, PGLite/pgvector, RRF+reranker, OAuth 2.1 caveats, BrainBench P@5/R@5, `skillopt`) — https://github.com/garrytan/gbrain `[high]` · Cornelius README (7-layer BDG, 60 skills, endorsement gate, incubation loop, 114★, Trinity requirement) — https://github.com/Abilityai/cornelius `[high]` · Meta Engineering, "Organizational Second Brain" 2026-09-02 (four layers, 200+ files, frontmatter dependency graph, diagnose→compile→validate→land, ~80% tokens, zero regressions) — https://engineering.fb.com/2026/09/02/ml-applications/organizational-second-brain-ai-learns-from-experts/ `[high]` · Cornelius incubation changelog 2026-05-17 — https://docs.ability.ai/announcements/2026-05-17-142114 `[moderate]` · Vyborov on background connection scanning — https://www.ability.ai/blog/autonomous-second-brain-connections `[moderate]` · Mem0 "State of AI Agent Memory 2026" (vendor) — https://mem0.ai/blog/state-of-ai-agent-memory-2026 `[low]` · Atlan memory framework comparison (conflicting numbers) — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/ `[low]` · Vendor agent-skill docs on context management and progressive disclosure `[moderate]` · Local: the run log 2026-08-12 (GraphRAG last 4/4, embeddings rejected), `KB/CATALOG.md` 2026-08-15, the skill registry, `tools/session.sh open` 2026-10-23 `[high]`
