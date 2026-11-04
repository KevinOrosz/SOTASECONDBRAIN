# Running agents against this package

Any harness that can read files and run shell commands can drive the loop. The tools never call a
model; agents call the tools. Roles come from `docs/SWARM.md`; this page is the minimum wiring.

## 1. Register agents

Agent ids are UPPERCASE (`^[A-Z][A-Z0-9_]{1,31}$`). Either list them in `KB/kb.json`:

```json
{ "owner": "sam", "agents": ["GURU", "CODA"] }
```

or give each one a folder matching `agents_glob`. Fresh installs use `souls/*/soul.md`; omitted settings retain the legacy `agents/*/soul.md` fallback:

```
souls/GURU/soul.md     identity, lane, inputs, outputs, boundaries, done condition
```

## 2. Boot an agent

Give the agent, in order: its `soul.md`, `docs/SWARM.md` §1–3, and the rules below. One mission per
session. A fresh session reads files, not chat history.

## 3. Rules every agent follows

- Write only through `bin/kb write put|link|withdraw`. Never edit `KB/wiki/` or `KB/output/` directly.
- Cite sources: `--source-ref raw:FILE` (in `KB/RAW/`), `wiki:STEM`, or `owner:YYYY-MM-DD`.
- Only the owner runs `land`, `unland`, `reject`, `resolve`, `seal --reseal`.
- Answer questions with `bin/kb query` / `bin/kb search`, then read the pages. If they fall short,
  propose a gap: `bin/kb write put --kind gap --gap-kind missing --target TOPIC ...`.
- Before reporting done, run `make verify` and quote the RESULT line.

## 4. Suggested roles

| Role | Does with this package |
|---|---|
| MAGI | routes a request, pre-screens inbox proposals for the owner |
| GURU | reads `KB/RAW`, proposes articles and links, files gaps |
| CODA | changes `tools/` and `tests/`, keeps `make test` and `make verify` green |
| CLERIC | measures owner review time per land, proposes ways to cut it |

Rename freely; the tools only check the id format and the `agents` / `agents_glob` settings.
