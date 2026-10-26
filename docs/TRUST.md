# Trust boundaries

What the tools guarantee, what depends on a model's judgment, and what the owner's approval covers. Read this
before you let an agent propose to your brain or before you rely on a verify result.

## 1. Deterministic guarantees (tools, stdlib Python, no network, no model)

Each line holds whatever an agent does, as long as the files are only changed through the tools:

- **One write gate.** `kb-write` writes proposals only into `KB/inbox/`. Only `land` and `unland` write
  `KB/wiki/`, and both need `--endorsed-by <owner>`.
- **Append-only ledger.** Every put, land, unland, adopt, reseal and recover adds a row with the sha256 of
  every file it touched (`KB/inbox/_ledger.jsonl`). WP1 flags a wiki file whose bytes match no ledger or
  seal entry.
- **Reversible lands.** Prior bytes are stored by hash in `KB/inbox/_objects/`. An interrupted operation is
  finished or rolled back from `KB/inbox/_ops/` on the next tool call.
- **Postcheck rollback.** A land whose rebuilt index, graph, lint, retrieval recall or regressions get worse is
  rolled back byte for byte (exit 3).
- **Source preservation.** A land hashes every raw source it cites. Verify FAILs if a cited raw file is
  later removed or edited.
- **Derived-output integrity.** The index, graph, seeds and dashboard record the hash of the wiki they were
  built from. Verify says when they are stale (WARN) or corrupt (FAIL), and gives the rebuild command.
- **Reproducible retrieval.** Query and eval results record the ranker, the tool version hash and k.
- **Fresh verdicts.** An answer verdict is bound to the corpus, the case and the tool source hashes. A stale
  verdict never counts as a pass.

What these do **not** do: they detect changes, they don't prevent them. Anyone with shell access can edit
files, rewrite the ledger or delete `_objects/`. The ledger is tamper-evident only against edits that skip
the tools, and only while the ledger file itself is intact. Keep backups or Git history of `KB/`.

## 2. Model judgment (outside the tools)

These are only as good as the agent and model that produce them. The tools check their shape, not their truth:

- whether a proposed article is accurate, well-sourced or worth having;
- whether a cited raw source actually supports the claim (the tools check the file exists and keep its hash;
  they don't read it for meaning);
- the replay answers and judge verdicts in a correction (the tools enforce blindness, strict verdict shape,
  a verbatim evidence span and freshness, but whether the answer is right is the judge's call);
- link types, gap kinds, confidence levels and categories chosen by an agent.

## 3. What the owner gate covers

`make land ID=...` is the owner saying "this belongs in my wiki". Before landing, read the proposal and the
`--dry-run` diff. The gate guarantees that nothing reaches `KB/wiki/` without that act, and that every land
is recorded and reversible. It does not check content for you: an approved falsehood is still a falsehood,
and it now carries your endorsement. Agents must never pass the owner id themselves (`AGENTS.md`).

## 4. Threat model for inbox inputs

Treat every proposal, raw file and agent output as untrusted text.

| Threat | What stops it | What remains |
|---|---|---|
| Agent writes into the wiki directly | WP1 flags unrecorded bytes; `make verify` WARNs with the adopt or restore command | Detection only; review and restore |
| Agent impersonates the owner | Land needs `--endorsed-by <owner>`; rule in `AGENTS.md` | An agent with your shell can still type it; watch the ledger `actor` |
| Proposal path escape (`../`) or unknown frontmatter keys | Slug and ref validation; WP2 rejects unknown keys and stray files | none known |
| Source ref to a missing or outside file | `raw:` and `output:` refs must resolve under their base; land refuses absent raw files | none known |
| Raw source swapped after land | Hash on the land row; verify FAILs | Detection only |
| Prompt injection inside a raw file or proposal body | Nothing in the tools runs or interprets the text; the owner reads it before landing | A model reading the wiki later can still be misled by text the owner approved |
| Malformed or flattering judge output | Strict verdict shape; malformed counts as FAIL | A wrong but well-formed verdict |
| Stale index hides or invents results | `inputs_hash` checks in verify | Between rebuilds, query notes the drift |
| Ledger or `_objects/` deleted | Verify reports the loss | No recovery without backups |

Report anything that breaks a line in section 1 as a security issue (`SECURITY.md`).
