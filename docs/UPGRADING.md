# Feedback upgrade: migration and operating notes

Status: Released in 0.3.0 (2026-11-11). Builds on 0.2.1 and the recovery, evaluation and provenance hardening already on main. No hosted service, model API, embedding dependency or scheduled job is introduced.

## What changes

| Surface | Before | Now |
|---|---|---|
| `bin/kb query` | Exact keyword scorer | Existing hybrid search with Porter stemming; `--keyword` preserves old output |
| Correction guidance | Manually choose packets and commands | `correct next CID` derives the next action from recorded state |
| New instance regression seeds | Three reference rules, one active | One neutral dormant example; old examples retained separately |
| Fresh role config | Six example IDs; `agents/` glob | GURU plus discovery under shipped `souls/`; WIZARD and GURU supplied |
| `make land`, `make unland` | Implicit owner string only | Interactive confirmation by default; explicit script override |
| Proposal land signatures | Unavailable | Optional OpenSSH verification over exact input/output hashes |
| `make status` | Proposal list and doctor | Read-only review summary, verification checkpoint, undo and regression health |
| Batch review | One manual dry-run at a time | `write list --diff`, with blocked proposals and overlapping paths |
| Existing notes | Manual proposal creation | Preview-first folder importer with source snapshots and resumable deduplication |
| CI | Mutable action tags; suppressed test failure output | Immutable action pins, no persisted checkout credential, visible test failures |

Existing instance configuration and regression files are **not rewritten**. Bootstrap retains them. To adopt neutral defaults in an existing brain, inspect your cases and deliberately retire only rules you do not want, with a reason. Do not copy the fresh seed file over your history. Optional reference rules are in `examples/reference-regressions.jsonl`; importing them requires unique IDs and deliberate policy review.

## Search compatibility

`bin/kb query "compost"` uses the same ranker as `bin/kb search "compost"`. JSON changes from keyword score fields to the hybrid result schema. Consumers needing the old schema must use `bin/kb query --keyword "compost"` (put `--keyword` first), or invoke `tools/kb-query.py` directly.

SQLite FTS5 is part of most Python SQLite builds. When absent, search reports a keyword fallback without stemming. The demo retrieval evaluation includes the single-word query `compost`; inspect both methods with `bin/kb eval --json`. Retrieval regression cases and the correction compiler keep their existing keyword ranker. This release does not reinterpret old case gold against a new method. The browser dashboard remains a separate implementation.

## Guided corrections

```bash
bin/kb correct next C-0001
bin/kb correct next C-0001 --write-template
```

`next` does not advance state. It prints the next packet, an unfilled result shape and a record command. Only `--write-template` creates a file; existing templates are never overwritten. Invalid verdict placeholders must be filled by the worker, not accepted as approval. For replay and judge steps, give a fresh worker only the packet. The helper checks stale validation and directs you back to validation when needed. All existing conflict, review, discrimination and freshness gates remain.

## Review and approval

```bash
bin/kb write list --state open --diff
make land ID=AGENT/YYYY-MM-DD-slug
make unland ID=AGENT/YYYY-MM-DD-slug REASON="reason"
```

The make targets require a terminal and the word `approve`. A land shows its diff under the write lock before prompting. Batch review is a preview of each proposal against the current base, not a promise that all can land together; later lands revalidate. Review refuses unfinished journals rather than recovering while claiming to be read-only. The legacy `write list` and `correct status` commands still trigger crash recovery; `bin/kb status` and `correct next` do not.

For an explicitly authorized script, use `APPROVAL=--non-interactive`. This remains a claimed identity, not authentication. Direct CLI flags remain backward compatible. Ledger approval modes distinguish interactive confirmation, claimed-owner mode and signed proposal lands. See TRUST for the limits.

### Optional signed proposal lands

Requires OpenSSH with `ssh-keygen -Y` support. The owner provisions an allowed-signers file containing `owner-id ssh-ed25519 PUBLIC_KEY`, held outside the agent's write access. Set `allowed_signers` to that absolute path in `KB/kb.json`, and `require_signed_lands` to `true` if every proposal land must carry a signature. The tool does not generate keys, change permissions or enable this policy automatically.

Prepare an exact review packet:

```bash
bin/kb write land AGENT/YYYY-MM-DD-slug --endorsed-by sam --dry-run --json > review.json
python3 -c 'import json; from pathlib import Path; d=json.loads(Path("review.json").read_text()); Path("approval.json").write_text(d["approval_payload"])'
```

The owner reviews the diff and payload, then signs on a trusted machine/account:

```bash
ssh-keygen -Y sign -f /owner-controlled/key -n kb-land approval.json
```

Return only the signature and land:

```bash
bin/kb write land AGENT/YYYY-MM-DD-slug --endorsed-by sam --signature approval.json.sig
```

Signatures bind the proposal, staged bytes, wiki, raw sources, tools, regression file, config, seal and ledger. Any changed binding requires a new review and signature. Sign promptly: managed dates can change the planned postimage at midnight. Only one proposal can use a signature. Successful use changes the ledger, preventing reuse after undo. This policy covers proposal lands, not direct edits, unland, adopt or reseal. Same-user filesystem access still defeats a local verifier; use account/permission isolation when that matters.

## Import existing notes

Choose an existing category and a confidence value after reading the notes. Preview a small batch first:

```bash
bin/kb adopt-folder /path/to/notes --agent GURU --category gardening --confidence moderate --limit 2
```

Review the preview, then repeat with `--apply`. Use repeated `--select relative/path.md` options for exact file selection. After the small batch is satisfactory, increase the limit or select the remaining files.

Apply preserves original files, writes content-addressed copies into `KB/RAW/imports/`, and proposes through the canonical inbox writer. It never lands pages or creates wiki categories. Equal source bytes already proposed are skipped, including rejected or withdrawn proposals: revisit those proposals deliberately instead of duplicating them. An interrupted batch is resumable; it may leave an unreferenced source snapshot if proposal creation failed. Failures are reported per file and return a nonzero exit status.

Only UTF-8 `.md` files are imported. Symlinks, path escapes, empty notes and YAML-frontmatter notes are refused with a reason; convert unsupported note formats separately. Missing titles are inferred from filenames and flagged. Core claims, short bodies and unresolved links are flagged for review; the importer does not invent evidence, rewrite links, approve confidence or pad content to pass checks. All land gates still apply.

## Status, verification and backup

`make status` / `bin/kb status --json` shows open work, recent mutations and claimed actors, unchecked answers, undo preimage availability and retrieval recall. A successful `make verify` records `KB/output/last-verify.json` with ledger-prefix and measurement bindings. Verification refuses to save a checkpoint if relevant instance inputs changed during the run. Status reports all mutations if that ledger prefix no longer matches.

Recall deltas are available only when corpus, eval set and method bindings match. Otherwise status says “no comparable baseline.” This is a comparison with the last successful verification, not a fabricated weekly trend. Weekly counts cover the preceding seven days. Verification and actor strings are not evidence of human approval.

New lands already use `_objects/` for undo, including pages that existed before the land. Keep `.gitignore` as shipped. Old lands may still need git history; do not remove the fallback or prune the object store casually. Undo diagnostics report missing/corrupt required wiki preimages and legacy dependencies. Back up `KB/` and `evals/` together, including raw sources, config, ledger, seal, objects, journals and correction records. Undo can refuse when the page has changed since the land; backups remain necessary.

## Maintainer checks

Run `make test`, `make verify`, and `make sandbox` from the candidate commit. CI repeats the checks on Linux and macOS with Python 3.9 and 3.12. Pin action updates to verified official commits and review them; this follows [GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).

This source change does not alter branch protection, enable automatic dependency-update jobs, publish a release, or claim a comparative performance benchmark. Maintainers should require green CI and review before merging.

Signed land receipts retain the signed payload and signature in the ledger. Verification checks the signature, ledger position, actor and staged postimage hashes against the currently configured allowed-signers file. Retain historical public keys in that trusted file when rotating keys if old receipts must continue to verify. The ledger grows with signed state manifests; signing is optional. Removing receipts or rewriting local policy remains possible for a same-user attacker.

## Implementation record

| Date | Mode | Topic | New artifacts | Disposition |
|---|---|---|---|---|
| 2026-11-04 | build and verification | Coworker feedback upgrade | `tools/kb-workflow.py`, `tests/test-kb-workflow.py`, `souls/GURU/soul.md`, `examples/reference-regressions.jsonl`, `docs/UPGRADING.md` | Candidate implementation; release remains Unreleased |
