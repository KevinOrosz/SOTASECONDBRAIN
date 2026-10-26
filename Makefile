# Thin wrappers. Every target is one command you can also run by hand.
.PHONY: help init demo verify test lint status land unland
help:
	@echo "make init | demo | verify | test | lint | status | land ID=... [OWNER=...] | unland ID=... REASON=..."
init:
	./bootstrap.sh
demo:
	./bootstrap.sh --demo
verify:
	bash scripts/verify.sh
test:
	bin/kb test
lint:
	bin/kb lint
status:
	bin/kb write list
	bin/kb doctor || true
OWNER ?= $(shell python3 -c 'import sys; sys.path.insert(0, "tools"); import kb_config; print(kb_config.load(".")["owner"])')
land:
	@test -n "$(ID)" || (echo "usage: make land ID=AGENT/YYYY-MM-DD-slug" && exit 1)
	bin/kb write land $(ID) --endorsed-by $(OWNER)
unland:
	@test -n "$(ID)" -a -n "$(REASON)" || (echo "usage: make unland ID=... REASON='why'" && exit 1)
	bin/kb write unland $(ID) --reason "$(REASON)" --endorsed-by $(OWNER)
