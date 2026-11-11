# Correction safeguards and integrations

## Answer enforcement

Fresh installs set `"answer_policy": "require-fresh"` in `KB/kb.json`. Existing instances without the key retain `warn`; set the key explicitly to opt in. Neither mode changes case status or rewrites existing cases. Invalid policy values are errors.

- `warn`: missing or stale answer judgments are UNCHECKED. They never count as passes. Fresh failed judgments and deterministic failures still block.
- `require-fresh`: every active answer case needs a fresh passing judgment. A changed corpus, case or tool invalidates it. This conservative whole-corpus gate avoids pretending page references capture every dependency; it costs more replay work.

Before landing a proposal when active answer cases exist:

```bash
bin/kb correct replay-all --proposal AGENT/YYYY-MM-DD-slug --fresh
```

The command emits blind replay packets against a temporary copy containing exact proposed postimages. An external agent writes `replay-r-NNNN.md` answers and `judge-r-NNNN.json` judgments into `KB/inbox/_corrections/_replay-all/results/`, following the existing correction tutorial. Use separate contexts for answering and judging. Judgments require `verdict` and a verbatim `evidence` span; include per-point `points` judgments. The replay packet specifies the ranker and k. Never supply the answer key to the answering context.

Rerun the same command without `--fresh` to check completed results, then review and approve through the usual owner command. A different land, changed proposal, changed tool or changed page can invalidate those results; regenerate them. A failed postcheck restores prior bytes. `unland` deliberately remains available even if regressions fail.

After a correction adds a new answer case, run `bin/kb correct replay-all --fresh` against the landed corpus before `make verify`. The newly appended case is not retroactively included in the earlier land postcheck. Dormant cases can be replayed but do not gate lands. CLI evaluation can explicitly select warning mode for diagnosis; the land gate always uses instance configuration.

These checks verify workflow and freshness, not judge honesty or model quality. Shell access still bypasses local workflow controls.

## Short facts and changes over time

Use the existing proposal command with `--kind article --type fact`. A fact has a title and non-empty `## Core Claim`, at most 200 body words, a source reference and confidence. The linter warns above 80 words. Other page types retain their existing land minimum.

```markdown
# Meeting day

## Core Claim
The preferred meeting day is Tuesday, effective 2026-11-09.
```

To replace it, propose a new complete fact body with `--supersedes wiki:meeting-day`. The existing writer captures the base hash, refuses stale replacements and retains exact prior bytes for owner `unland`. The current page is the retrieval surface; history lives in the ledger and object store. Record effective dates and evidence in the claim. There is no automatic contradiction resolution, expiry or deletion guarantee.

## Local MCP

Start `python3 /absolute/path/to/SOTASECONDBRAIN/tools/kb-mcp.py --root /absolute/path/to/instance` as a stdio server in your MCP client. Standard client configuration:

```json
{"mcpServers":{"second-brain":{"command":"python3","args":["/absolute/path/to/SOTASECONDBRAIN/tools/kb-mcp.py","--root","/absolute/path/to/instance"]}}}
```

Five tools: `kb_search`, `kb_read`, `kb_status`, `kb_correction_next`, `kb_propose`. Proposals require an explicitly registered agent, category, source reference and confidence. Reads resolve within `KB/wiki`; symlink escapes are rejected. Page content is untrusted data, never an instruction source. Owner land/unland, arbitrary commands and remote transports are not exposed. The adapter implements the [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), initialization and tools subset. Tested with protocol fixtures; individual client integrations still require a smoke test.

## Matched retrieval benchmark

Use an isolated instance with a frozen corpus and a question file in the existing `{"questions":[{"id":"q1","q":"...","gold":["page-stem"]}]}` shape. Lock gold before running either system; exclude answer-revealing filenames. Rebuild indexes first.

```bash
bin/kb benchmark run --cases questions.json > sota-hybrid.json
bin/kb benchmark run --cases questions.json --ranker kb-query > sota-keyword.json
bin/kb benchmark compare sota-keyword.json sota-hybrid.json
```

Each run includes corpus and case hashes, tool version, ranker, k, ranked hits and per-query wall time. Comparison rejects mismatched corpus/cases/k and missing results. Latency includes local load/index construction inside retrieval; report hardware, warmup and repetition separately. A tiny demo is a smoke test, not competitive evidence.

For GBrain, import the exact same Markdown bytes into an isolated source, record the actual GBrain commit and full search configuration, and export the same JSON result schema. Keep `cases`, `case_hash`, `corpus_hash` and `k`; replace `system`, `version`, `configuration`, and all `results` with that system's measured output. Each result needs `id`, ordered `hits` mapped back to the original page stems, and `latency_ms`. The copied corpus hash is an assertion: independently verify the imported source bytes. Do not relabel SOTA results. Compare keyless modes first; run optional semantic modes separately with model and cost disclosure. This package does not install or invoke GBrain.

For answer quality, use the same frozen reader, prompt, context budget and blind judge across systems. Collect current-fact errors, abstentions and correction recurrence separately from retrieval recall. Publish all questions, settings and failures permitted by source privacy. No answer benchmark has been run by this upgrade.

## Real correction pilot

Start with three real mistakes, then evaluate ten consecutive attempts including failures and abandoned attempts. Keep private observations outside the public repo. For each attempt record: correction id, question, date, model/version, outcome, before/after answer, review minutes, total owner minutes, model cost, recurrence at a fixed follow-up date, and why any attempt stopped. Missing follow-up stays unknown, never zero recurrence. Compare owner time against manually editing a note. Publish only redacted observations with owner approval; never substitute fixture corrections for user outcomes.

## Withdrawals and competing claims

A fact's ID is its wiki path. Replacing its Core Claim records the prior and new text on the land ledger row. Matching uses the extracted Core Claim with whitespace collapsed. Case, wording and punctuation matter. Another fact may use identical wording independently.

To explicitly withdraw a landed fact, use the existing undo operation with an owner reason:

    bin/kb write unland ID --withdraw-fact --reason "Source retracted" --endorsed-by OWNER --confirm

This restores the previous page or removes a newly created page. Plain unland reverses the land without creating a new withdrawal. Earlier ledger history stays accessible. Existing historical rows without fact metadata are not backfilled.

Use `bin/kb write list --diff` to review competing fact proposals or an open contradictory gap targeting the same stem. The review shows the current claim, proposed claims, dates, submitters, source references, opening excerpts of available RAW files and the previous decision. Confidence is the submitter's assessment. The owner can reject proposals, land one replacement, or leave the disagreement open. A stale replacement must be proposed again against the current page.

Reimport checks the filename stem within the selected category. For a renamed source, pass `--select FILE --fact-id STEM` to `adopt-folder`. A withdrawn match is reported and skipped even with `--apply`. To intentionally reinstate it, submit a fact proposal and land it with `--reinstate "reason"`. Include the same reason in a signed dry run. The ledger records the reason and earlier decision.

## Answer, ask or abstain

Use `correct open --expected-action ask` alongside the usual question, owner correction and points file. Other actions are `answer` and `abstain`. This selects answer replay even if the question retrieved the right page. Use a separate context for the judge. It supplies `observed_action` based on the actual reply plus the usual verdict and verbatim evidence span. The expected action stays out of replay packets and blind overlays. Existing cases keep their original judging contract.

Pair an ambiguous question with a specific version that has an answer. Add an unanswerable case when evidence is missing. An agent that always asks will fail the other cases.

## Session handoff

    bin/kb brief --since 12

The cursor excludes ledger row 12. Save the returned `through` value for the next session. Changes include correction lands and reversals. Current facts, withdrawn claims, pending proposals, competing decisions, failed cases and cases awaiting replay have distinct fields. The brief checks the wiki against its seal and ledger, refuses unfinished operations, and checks input stability across generation. This is a local consistency check. It does not verify real-world truth or authenticate claimed identities.
