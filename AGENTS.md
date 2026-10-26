# AGENTS.md — read this first if you are an AI agent

1. **Read `README.md` top to bottom before doing anything.** It is the user guide and the source of truth for how this repo is used.
2. Then read `docs/AGENTS.md` (how agents register, boot and propose) and `docs/SWARM.md` (roles: MAGI orchestrates, GURU researches and specs, CODA builds, CLERIC audits owner time, SIGNAL senses, PRISM repurposes).
3. If you are building or changing the tools, read `docs/HANDOFF.md` (status, next step) and `docs/SPEC.md` (canonical spec) next.

## Hard rules

- **Propose, never publish.** Write knowledge only through `bin/kb write put` / `link` into `KB/inbox/`. Never edit `KB/wiki/` directly. Only the owner lands changes (`make land ID=... `).
- **Never act as the owner.** Do not pass `--endorsed-by` or `--by` with the owner's id unless the human owner told you to in this conversation.
- **No model calls inside `tools/`.** Tools stay standard-library Python. Model work happens in you, the agent.
- **Verify before you say done.** Run `make verify` (want `0 fail(s)`) and `make test` after any change to tools or docs.
- **Ask when the request is vague.** Never guess a category, owner or agent id.
