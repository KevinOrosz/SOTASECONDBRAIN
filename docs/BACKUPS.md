# Back up and recover an instance

The backup commands package the local instance data in `KB/`, `evals/`, and `agents/` when present, plus the standard `skills/REGISTRY.md` and `config/router.json` files used to validate page consumers. They preserve regular-file bytes and empty directories, including the wiki, RAW archive, config, proposal ledger, correction records and stored undo preimages. Use absolute archive and destination paths since `bin/kb` runs from the repository root.

    bin/kb backup create /private/path/brain.zip
    bin/kb backup inspect /private/path/brain.zip
    bin/kb backup verify /private/path/brain.zip
    bin/kb backup restore /private/path/brain.zip /private/path/recovered

**Create** builds a private ZIP beside the requested output, verifies it, and rechecks source file hashes and inventory before publishing. Choose a new filename outside the archived directories. Pause external editors and agents while creating a backup. The command rejects an active write lock, pending transaction journal, symlink or special file. Independent file reads do not provide filesystem snapshot isolation.

**Inspect** lists paths, sizes, and manifest hashes without reading the payload. **Verify** streams every file and compares its SHA-256 with the manifest. A corrupt or incomplete archive exits nonzero. The archive is unencrypted and the manifest is unsigned. Keep it in private storage and use a separately trusted digest or authenticated storage when authenticity matters.

**Restore** creates a new directory, checks each file while writing, and cleans up the destination on handled failures. It refuses existing destinations, including empty ones. A power loss can leave a partial directory; use a fresh destination on retry. Restore limits are 100,000 entries, 64 GiB of uncompressed data, and a 32 MiB manifest. File ownership, timestamps and original permission bits are outside this data format.

Use trusted archives. For a quick check with a compatible package checkout:

    python3 tools/kb-graph-query.py search "your question" --root /private/path/recovered --json

Keep the matching package revision separately. Also back up any custom souls, program files, config targets or answer receipts outside the three directories. Git history for legacy undo and signing keys are separate. In-progress external replay work can reference absolute paths to temporary overlays. Finish or discard that work before migration and start a fresh replay after moving machines. A byte-valid archive can preserve an unhealthy brain; run instance verification as well as archive verification.
