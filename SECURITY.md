# Security

## Reporting a problem

Please report security issues privately to the repository owner via GitHub's private vulnerability reporting (Security tab, "Report a vulnerability"), not in a public issue. You'll get an acknowledgement within 7 days.

## What this project does and doesn't do

- **No network.** The tools make no network calls and import no network libraries. CI and the test suites check this.
- **No model calls, no keys.** The tools never call an AI model and need no API keys or tokens.
- **Your data stays local.** Your knowledge base (`KB/`, `evals/`, `agents/`) is in `.gitignore`, so it is never committed to this repo.
- **Tamper evidence.** Every approved change is hashed into an append-only ledger (`KB/inbox/_ledger.jsonl`). `make verify` flags any wiki file whose bytes don't match the ledger. It detects changes; it can't prove who made them.

## Agents

Agents you run against this repo act with your shell's permissions. Read `AGENTS.md`: agents may only propose into `KB/inbox/`; landing requires the owner.
