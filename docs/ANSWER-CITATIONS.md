# Check previously delivered answers

Use a private folder for receipts. They contain the full question, answer, wiki paths and quoted text. The CLI writes JSON to stdout. The shell redirections below save files only where you choose.

1. **Capture** a reply with one or more cited wiki passages. Page paths are relative to `KB/wiki`. Line numbers are one-based and inclusive. The cited bytes must match the wiki seal or ledger.
2. **Check** a receipt after changes. Unchanged pages pass. If the exact quotation persists on a revised page, review its new context. Missing, repeated, removed or directly edited passages require citation review.
3. **Audit** a folder. The command checks top-level `*.answer.json` files in name order, reports each result and counts malformed receipts separately.
4. **Queue** the review work. Results are grouped by affected page and sorted by number of affected receipt files. Each entry names the question, receipt file and finding. Invalid receipts and changed histories have no trustworthy page assignment.

Example using an existing sealed instance and a private directory:

    bin/kb answers capture --question "When is the meeting?" --answer-file reply.md \
      --cite operations/meeting.md 12 13 > private/meeting.answer.json
    bin/kb answers check private/meeting.answer.json
    bin/kb answers audit private
    bin/kb answers queue private

Repeat `--cite PAGE FIRST LAST` for another passage. Use `bin/kb answers --root /path/to/instance COMMAND ...` for another brain. Use an absolute answer-file or receipt directory when launching from outside the repository, since the bin wrapper changes to the repository directory.

Receipts carry a checksum over the question, answer, citations and history reference. Verification checks the original seal and ledger prefix, allowing later ledger entries. A changed seal, shortened ledger or changed prefix yields `history_changed`. Identical copies of an instance share history. Checksums detect accidental edits and provide no signer identity. A current citation confirms the captured text remains on a matching approved page. A human or external judge must assess whether it supports the answer. Following RAW source changes is a separate [evidence review](EVIDENCE-REVIEW.md).

Exit codes: 0 for successful capture or an all-current review, 1 when review is needed, 2 for a command error, including an empty collection or malformed individual receipt.
