# Contributing

Thanks for helping. This repo is small on purpose, and it stays that way through a few firm rules.

## Set up

```bash
./bootstrap.sh --owner dev --demo
make test && make verify
```

Or open the repo in any AI agent tool and type `WIZARD`.

## Ground rules

1. **Standard library only.** `tools/` uses Python 3.9+ and nothing from pip. No model calls and no network calls inside the tools: model work happens in the agent, tools only check and record.
2. **Agents propose, the owner approves.** Never add a code path that writes `KB/wiki/` outside `kb-write land`.
3. **One home per contract.** Schemas, header keys and ledger events are defined once (see `docs/SPEC.md` §1). Import them, don't redefine them.
4. **Tests come with changes.** Every behavior change gets a test in `tests/`, built on `tools/kb_testkit.py`, including at least one failure case.
5. **No personal or vendor names** in code, tests or docs. Instance identity lives in `KB/kb.json`.

## Before you open a pull request

```bash
make test       # all suites PASS
make verify     # RESULT: 0 fail(s)
```

Update `CHANGELOG.md` under an "Unreleased" heading, and the docs if behavior changed. The PR template has the checklist.

## Where things are

`docs/ARCHITECTURE.md` explains how the pieces connect, `docs/SPEC.md` is the canonical spec, and `docs/HANDOFF.md` shows build status and what's next.
