# Thin wrappers. Every target is one command you can also run by hand.
.PHONY: help init demo verify test lint status land unland sandbox
help:
	@echo "SOTASECONDBRAIN $$(cat VERSION). Easiest start: open this folder in an AI agent tool and type WIZARD."
	@echo ""
	@echo "  make sandbox                    try everything in a throwaway copy"
	@echo "  make init                       set up your brain (asks your owner name)"
	@echo "  make demo                       set up with sample pages"
	@echo "  make status                     what's waiting + health check"
	@echo "  make verify                     full check (want: 0 fail(s))"
	@echo "  make test                       run every test suite"
	@echo "  make lint                       check page headers"
	@echo "  make land ID=...                approve a proposal into the wiki"
	@echo "  make unland ID=... REASON=...   undo an approval"
	@echo ""
	@echo "  bin/kb help                     every tool command"
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
sandbox:
	scripts/sandbox.sh

status:
	bin/kb status
# Preserve command-line values verbatim. Recipes never expand approval data into shell source.
override MAKEOVERRIDES :=
override ID := $(value ID)
override REASON := $(value REASON)
override OWNER := $(value OWNER)
override APPROVAL := $(value APPROVAL)
export ID REASON OWNER APPROVAL
land unland:
	@python3 tools/kb-write.py --make-approval $@
