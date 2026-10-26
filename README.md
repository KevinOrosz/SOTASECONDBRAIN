# second-brain-loop

A personal knowledge base you can trust to grow. It is a folder of Markdown pages plus a few small
Python tools that check every page, let helpers (people or AI agents) *propose* changes, and let one
person — you, the **owner** — approve each change. Every approved change is recorded and can be undone.

No accounts, no servers, no network, no AI calls inside the tools. Python 3.9+ and git are all you need.

## 5-minute quickstart

```bash
git clone <this repo> second-brain-loop && cd second-brain-loop
./bootstrap.sh --owner sam --demo     # use your own lowercase id instead of "sam"
make verify                           # should end with: RESULT: 0 fail(s)
bin/kb query "compost"                # search the demo wiki
open KB/output/kb-search.html         # or open the file in any browser
```

Leave out `--demo` to start with a single welcome page instead of the example wiki.
`bootstrap.sh` is safe to run again; it never overwrites a file that exists.

## Daily use

1. **Collect.** Drop source material (notes, clippings, transcripts) into `KB/RAW/` as `.md` files.
2. **Propose.** Write a draft page and put it in the inbox:
   ```bash
   bin/kb write put --agent RESEARCHER --kind article --slug mulching --category gardening \
     --type article --confidence moderate --source-ref raw:soil-notes.md --body-file draft.md
   ```
   The draft needs a `# Title`, a `## Core Claim` section and at least 100 words.
3. **Review.** `bin/kb write list` shows open proposals. Read the file under `KB/inbox/`.
4. **Approve (land)** or decline:
   ```bash
   make land ID=RESEARCHER/2026-10-26-mulching
   bin/kb write reject RESEARCHER/2026-10-26-mulching --reason "too thin" --by sam
   ```
   Landing writes the page, updates the indexes, rebuilds search, and re-runs every check. If any
   check fails, everything is put back exactly as it was.
5. **Undo** a land: `make unland ID=... REASON="why"`.
6. **Check health** any time: `make verify`.

Run `bin/kb help` for every command.

## Concepts (one line each)

| Term | Meaning |
|---|---|
| **wiki** | `KB/wiki/` — the approved pages, one Markdown file each, grouped in category folders. |
| **raw source** | A file in `KB/RAW/` that pages are written from. Pages cite it in `**Sources:**`. |
| **header** | The `**Key:** value` lines under a page's title (Category, Sources, Updated, Type, ...). |
| **type** | What kind of page it is: `article`, `taxonomy` (a category index), `routing` (the top index), `source`, `position`, `gateway`. |
| **lint** | An automatic check that every page header follows the rules (`bin/kb lint`). |
| **owner** | The one person allowed to approve changes. Set once in `KB/kb.json`. |
| **agent** | Anyone allowed to propose: an AI assistant or a person, named in UPPERCASE (`RESEARCHER`). |
| **inbox** | `KB/inbox/` — proposals waiting for the owner. Agents only ever write here. |
| **land** | Approve a proposal: the only way a page enters the wiki. |
| **unland** | Undo one land and put the proposal back in the inbox. |
| **ledger** | `KB/inbox/_ledger.jsonl` — an append-only log; every change gets one row with file fingerprints. |
| **hash** | A fingerprint of a file's exact bytes (SHA-256). Any edit changes it. |
| **seal** | The first snapshot of every page's hash. Later edits must match the ledger or the seal. |
| **WP1 / WP2** | Two lint rules: WP1 = no unrecorded wiki edits; WP2 = inbox files are well-formed. |
| **regression case** | A saved test (in `evals/regressions.jsonl`) that a past mistake never comes back. Every land must pass them all. |
| **retrieval eval** | A small hand-written question set checking that search still finds the right pages. |
| **correction** | An owner's "that answer was wrong", compiled into one gated page diff plus one regression case (`bin/kb correct`). |
| **graph** | `KB/output/kb-graph.json` — pages, links and sources as a network, for `bin/kb ask`. |

## Layout

```
bin/kb             one command for everything        tools/       the Python tools (stdlib only)
bootstrap.sh       create your instance              tests/       test suites (make test)
Makefile           short aliases                     scripts/     verify.sh health check
kb.example.json    every setting, with defaults      templates/   starter pages + seed regressions
examples/          a 12-page demo wiki               docs/        spec, architecture, agent guide
KB/  evals/        your instance (created by bootstrap; ignored by git)
```

Your instance (`KB/`, `evals/`) is listed in `.gitignore`, so updating the package never touches
your notes. Want your notes versioned? Keep `KB/` in its own git repo, or remove it from `.gitignore`.

## Settings

`KB/kb.json` (created from `kb.example.json`). Every key is optional:
`owner`, `agents`, `agents_glob`, `dashboard`, `regressions`, `baseline`, `catalog`, `registry`,
`router`, `spine`. See `docs/HANDOFF.md` §3 for what each does.

## Using it with AI agents

Any assistant that can run shell commands can propose pages with `bin/kb write put` and never touch
`KB/wiki` directly. See `docs/AGENTS.md` for how to give an agent its role and rules, and
`docs/ARCHITECTURE.md` for how the pieces connect.

## Status

Sessions 1–7 of an 8-session build are done (typed pages, lint, gated write-back, regression suite,
correction compiler). Try it: `docs/CORRECTION-TUTORIAL.md`. Next: the end-to-end loop test
(`docs/HANDOFF.md` §5). MIT licensed.
