# Security

## Reporting a problem

Please report security issues privately to the repository owner (GitHub profile, or the contact you were given with access), not in a public issue. Include steps to reproduce and the output of `make verify`. You'll get an acknowledgement within 7 days. If this repo is ever made public, GitHub's private vulnerability reporting (Security tab) will be turned on and becomes the preferred channel.

## What this project does and doesn't do

- **No network.** The tools make no network calls and import no network libraries. CI and the test suites check this.
- **No model calls, no keys.** The tools never call an AI model and need no API keys or tokens.
- **Your data stays local.** Your knowledge base (`KB/`, `evals/`, `agents/`) is in `.gitignore`, so it is never committed to this repo.
- **Tamper evidence.** Every approved change is hashed into an append-only ledger (`KB/inbox/_ledger.jsonl`). `make verify` flags any wiki file whose bytes don't match the ledger. It detects changes; it can't prove who made them. Raw sources are hashed when a page lands, and `make verify` fails if one goes missing or changes. See `docs/TRUST.md` for the full trust boundaries and the threat model for inbox inputs.

## Agents

Agents you run against this repo act with your shell's permissions. Read `AGENTS.md`: agents may only propose into `KB/inbox/`; landing requires the owner.
