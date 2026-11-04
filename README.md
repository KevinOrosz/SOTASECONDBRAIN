# SOTASECONDBRAIN

[![CI](https://github.com/KevinOrosz/SOTASECONDBRAIN/actions/workflows/ci.yml/badge.svg)](https://github.com/KevinOrosz/SOTASECONDBRAIN/actions/workflows/ci.yml)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![No network, no API keys](https://img.shields.io/badge/network-none-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> [!TIP]
> **Fastest start: let the WIZARD set it up for you.**
> 1. Clone this repo and open the folder in any AI agent tool (Claude Code, Codex, Cursor, or another).
> 2. Type one word: **`WIZARD`**
>
> It checks your computer, sets up your brain, runs the health check, and walks you through your first question and your first approved page. You just answer a few questions. ([What WIZARD does](souls/WIZARD/soul.md))
>
> No agent tool? Follow the [User guide](#user-guide) below. It's the same steps by hand.

**Start here.** This page is the user guide, for people and AI agents alike. Read it top to bottom once; everything else in the repo is reference.

**In one sentence:** a knowledge base made of plain Markdown files, where anyone (including AI agents) can *suggest* changes, only one person (the **owner**) can *approve* them, tool-mediated changes are logged with undo history, and corrections become tests for the mistakes they cover.

**Trust boundary:** owner approval is a workflow convention, not shell-level access control. A typed owner flag does not authenticate a human. Interactive confirmation prevents accidents; optional SSH-signed lands bind approval to exact bytes. See [Trust boundaries](docs/TRUST.md).

The project focuses on preserving corrections through reviewed edits and regression cases. The name is not a claim of benchmark superiority. Search uses local lexical and graph-based methods; no embedding service is required.

No accounts, no servers, no API keys, no AI calls inside the tools. Works with any AI model and any agent tool.

---

## User guide

### Step 0 · What you need

A Mac or Linux computer with **Python 3.9+**, **git** and **make** (most Macs already have all three). Check:

```bash
python3 --version && git --version && make --version | head -1
```

### Step 1 · Get the code

```bash
git clone https://github.com/KevinOrosz/SOTASECONDBRAIN.git
cd SOTASECONDBRAIN
```

This repository is public; cloning requires no invitation.

### Step 2 · Test drive in a sandbox (recommended)

```bash
make sandbox
```

This copies everything to a throwaway temp folder, loads a demo wiki, and runs every check. It prints the folder path. Go there and try Steps 5 to 8 safely. Your real folder is never touched. Delete the sandbox with the `rm -rf` line it prints.

### Step 3 · Set up your own brain

Pick a short lowercase name for yourself. That makes you the owner, the only one who can approve changes.

```bash
./bootstrap.sh --owner sam
```

Add `--demo` if you want sample pages to play with. Running it twice is safe.

### Step 4 · Check it's healthy

```bash
make verify
```

You want to see `RESULT: 0 fail(s)`.

### Step 5 · Add knowledge

- Put source material (notes, transcripts, articles) in `KB/RAW/`.
- Wiki pages live in `KB/wiki/<category>/<page>.md`. They are plain Markdown and can be read in Obsidian. Propose edits through the inbox; direct edits cause provenance drift. For existing notes, use the preview-first [folder importer](docs/UPGRADING.md#import-existing-notes).

### Step 6 · Ask it something

```bash
bin/kb query "your question"
```

It retrieves candidate pages using hybrid search with Porter stemming, so `compost` can find `composting`. Read the pages to answer. `bin/kb query --keyword "your question"` retains the legacy scorer and JSON format. The browser dashboard at `KB/output/kb-search.html` has its own search implementation; results can differ.

### Step 7 · Let agents suggest changes

An agent (or a person) writes a proposal into the inbox. It never edits the wiki directly.

First write the page as a Markdown file, for example `draft.md`: a `# Title` line, a `## Core Claim` section with one or two sentences, then `## Evidence`. It needs **at least 100 words** of body to be approved. Then propose it:

```bash
bin/kb write put --agent GURU --kind article --slug mulching --category gardening \
  --type article --confidence moderate --source-ref raw:soil-notes.md --body-file draft.md
```

To have an AI agent do this for you, open this folder in your agent tool (Claude Code, Codex, Cursor or any other). It loads `AGENTS.md` automatically, which sends it here first. Then say: *"Propose a page about X."*

### Step 8 · Review and approve

```bash
bin/kb write list --diff                           # review pending diffs and overlaps
make land ID=GURU/2026-10-26-mulching              # approve: it enters the wiki
make unland ID=GURU/2026-10-26-mulching REASON="not right"   # undo it
```

The make targets display a confirmation prompt. Use the real ID from `bin/kb write list`. Reject a proposal with `bin/kb write reject ID --reason "why" --by <you>`.

### Step 9 · Fix a wrong answer for good

When the brain answers something wrong, follow **`docs/CORRECTION-TUTORIAL.md`**. Use `bin/kb correct next C-0001` to see the next packet and command. The fix lands as a reviewed edit plus a regression test. Deterministic cases gate future lands; answer cases also need fresh external replay and judgment. Real correction time has not yet been measured.

### Step 10 · Stay healthy

```bash
make status    # what's waiting + health check
make verify    # full check
git pull       # get updates to the tools
```

### If something goes wrong

| You see | Do this |
|---|---|
| `RESULT: FAIL` from `make verify` | Read the `[FAIL]` line above it. It names the file and the fix. |
| `--endorsed-by ... is required` | Only the owner approves. Use the name you gave `bootstrap.sh`. |
| `agent ... is not a registered agent` | Add the agent's name to `agents` in `KB/kb.json`. |
| `land needs at least 100` body words | The page is too short. Add evidence to the draft and propose it again. |
| A land exits with code 3 | A safety check failed and the change was rolled back. Nothing broke. Read the message. |

---

## Contributing, security, support

- **Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md). Run `make test` and `make verify` before a pull request.
- **Security:** see [SECURITY.md](SECURITY.md). Report privately, not in a public issue.
- **Help:** type `WIZARD` in your agent tool, run `make help`, or open an issue with the bug template.
- **Changes:** see [CHANGELOG.md](CHANGELOG.md).

## Reference

### What's in the box

- **Your brain** (created by `bootstrap.sh`, never uploaded to git): `KB/wiki/` pages, `KB/RAW/` sources, `KB/inbox/` proposals plus the ledger, `KB/kb.json` settings, `evals/` regression tests.
- **The tools:** `bin/kb` (one command for everything), `make` shortcuts, `tools/` (plain Python, standard library only).
- **The docs:** `docs/AGENTS.md` (how agents work here), `docs/SWARM.md` (the multi-agent doctrine), `docs/ARCHITECTURE.md` (how the pieces connect), `docs/CORRECTION-TUTORIAL.md`, `docs/SPEC.md` (the full build spec), `docs/TRUST.md` (trust boundaries and threat model), `docs/HANDOFF.md` (build status).

### Concepts (one line each)

| Term | Meaning |
|---|---|
| **wiki** | `KB/wiki/` — the approved pages, one Markdown file each, grouped in category folders. |
| **raw source** | A file in `KB/RAW/` that pages are written from. Pages cite it in `**Sources:**`. |
| **header** | The `**Key:** value` lines under a page's title (Category, Sources, Updated, Type, ...). |
| **type** | What kind of page it is: `article`, `taxonomy` (a category index), `routing` (the top index), `source`, `position`, `gateway`. |
| **lint** | An automatic check that every page header follows the rules (`bin/kb lint`). |
| **owner** | The one person allowed to approve changes. Set once in `KB/kb.json`. |
| **agent** | Anyone allowed to propose: an AI assistant or a person, named in UPPERCASE (`GURU`). |
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

### Layout

```
bin/kb             one command for everything        tools/       the Python tools (stdlib only)
bootstrap.sh       create your instance              tests/       test suites (make test)
Makefile           short aliases                     scripts/     verify.sh health check
kb.example.json    every setting, with defaults      templates/   starter pages + seed regressions
examples/          a 12-page demo wiki               docs/        spec, architecture, agent guide
KB/  evals/        your instance (created by bootstrap; ignored by git)
```

Your instance (`KB/`, `evals/`) is listed in `.gitignore`, so updating the package never touches
your notes. Undo of new lands uses saved preimages, not git. Back up the whole instance, including `KB/inbox/` and `evals/`. Want your notes versioned? Keep `KB/` in its own git repo, or remove it from `.gitignore`.

### Settings

`KB/kb.json` (created from `kb.example.json`). Every key is optional:
`owner`, `agents`, `agents_glob`, `dashboard`, `regressions`, `baseline`, `catalog`, `registry`,
`router`, `spine`. See `docs/HANDOFF.md` §3 for what each does.

### Using it with AI agents

Any assistant that can run shell commands can propose pages with `bin/kb write put` and never touch
`KB/wiki` directly. See `docs/AGENTS.md` for how to give an agent its role and rules, and
`docs/ARCHITECTURE.md` for how the pieces connect.

### What you have now

After the quickstart you have a working, checked knowledge base:

- **A typed wiki** (`KB/wiki/`) whose every page header is linted, with a search page and a link graph.
- **A workflow gate.** Tool-mediated land and unland operations are fingerprinted in the ledger. Shell access can bypass this workflow.
- **A memory for mistakes.** Each correction you make becomes one small page fix plus a regression case,
  and every later land must keep passing it.
- **Proof the loop closes.** `tests/test-kb-loop-e2e.py` (last in `make test` and `make verify`) runs a
  correction end to end on a throwaway copy, then undoes the fix and checks that its case now fails.

### Next steps

1. **Make it yours.** Run `./bootstrap.sh --owner YOURID` without `--demo` in a fresh copy, or keep the demo
   and add pages. Drop your notes into `KB/RAW/`.
2. **Grow it through the gate.** Propose pages with `bin/kb write put`, land the good ones with `make land`.
3. **Correct it.** When an answer from the wiki is wrong, walk `docs/CORRECTION-TUTORIAL.md` once, then use
   `bin/kb correct` for real.
4. **Hand it to an agent.** Give an assistant `docs/AGENTS.md` and let it propose; you stay the only lander.
5. **Check it weekly.** `make verify` should stay at 0 fail(s).

### Status

Version 0.2.1; the [Unreleased upgrades](CHANGELOG.md#unreleased) are documented in [UPGRADING.md](docs/UPGRADING.md). The lean build path (sessions 1–8: typed pages, lint, gated write-back, regression suite,
correction compiler, end-to-end loop test) is complete. Further phases wait until three real corrections
have landed (`docs/HANDOFF.md` §5). MIT licensed.
