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
python3 -c "print('# Mulching\n\n## Core Claim\nMulch keeps soil moist and cool.\n\n## Evidence\n' + 'Mulch slows evaporation and smothers weeds in summer beds. ' * 12)" > draft.md
```

```bash
bin/kb write put --agent GURU --kind article --slug mulching --category gardening --type article --confidence moderate --source-ref raw:soil-notes.md --body-file draft.md
```

```bash
bin/kb write list
```

```bash
make land ID=GURU/YYYY-MM-DD-mulching
```

```bash
make unland ID=GURU/YYYY-MM-DD-mulching REASON="undo test"
```

```bash
make status
```
