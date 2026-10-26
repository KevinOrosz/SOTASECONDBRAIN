# Quickstart

```bash
./bootstrap.sh --owner sam --demo
```

```bash
make verify
```

```bash
make test
```

```bash
bin/kb query "spaced repetition"
```

```bash
bin/kb write put --agent RESEARCHER --kind article --slug mulching --category gardening --type article --confidence moderate --source-ref raw:soil-notes.md --body-file draft.md
```

```bash
bin/kb write list
```

```bash
make land ID=RESEARCHER/YYYY-MM-DD-mulching
```

```bash
make unland ID=RESEARCHER/YYYY-MM-DD-mulching REASON="undo test"
```

```bash
make status
```
