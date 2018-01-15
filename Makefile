# Simple scripts for testing etc.

# Assume that ../kythe has been cloned from
# https://github.com/google/kythe and has been built with `bazel build
# //...` and that the latest Kythe tarball has been downloaded and
# installed in /opt/kythe.

KYTHE=../kythe
KYTHE_BIN=$(KYTHE)/bazel-bin
VERIFIER_EXE=$(KYTHE_BIN)/kythe/cxx/verifier/verifier
# VERIFIER_EXE=/opt/kythe/tools/verifier
ENTRYSTREAM_EXE=$(KYTHE_BIN)/kythe/go/platform/tools/entrystream/entrystream
# ENTRYSTREAM_EXE=/opt/kythe/tools/entrystream
WRITE_ENTRIES_EXE=$(KYTHE_BIN)/kythe/go/storage/tools/write_entries/write_entries
WRITE_TABLES_EXE=$(KYTHE_BIN)/kythe/go/serving/tools/write_tables/write_tables
# http_server built from source requires some additional post-processing,
#     so use the old http_server from Kythe v0.0.26
# HTTP_SERVER_EXE=$(KYTHE_BIN)/kythe/go/serving/tools/http_server/http_server
TRIPLES_EXE=$(KYTHE_BIN)/kythe/go/storage/tools/triples/triples
HTTP_SERVER_EXE=/opt/kythe/tools/http_server
KYTHE_EXE=$(KYTHE_BIN)/kythe/go/serving/tools/kythe/kythe
# assume that /opt/kythe has been set up from
# https://github.com/google/kythe/releases/download/v0.0.26/kythe-v0.0.26.tar.gz
HTTP_SERVER_RESOURCES=/opt/kythe/web/ui
TEST_GRAMMAR_FILE=py3_test_grammar
TEST_GRAMMAR_DIR=test_data
TESTOUTDIR=/tmp/pykythe_test
BROWSE_PORT=8002

test: tests/test_pykythe.py \
		pykythe/ast_raw.py \
		pykythe/kythe.py \
		pykythe/pod.py
	python3.6 -B tests/test_pykythe.py

# Test that all syntactic forms are processed:
test_grammar: verify

# Reformat all the source code (uses .style.yapf)
pyformat:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | xargs yapf -i

pylint:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | \
		grep -v snippets.py | xargs -L1 pylint --disable=missing-docstring

pyflakes:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | \
		grep -v snippets.py | xargs -L1 pyflakes

# pytype doesn't work on this source, but if it did:
pytype:
	pytype -V3.6 pykythe/__main__.py
	pytype -V3.6 tests/test_pykythe.py

mypy:
	mypy pykythe/__main__.py
	mypy tests/test_pykythe.py

lint: pylint

# Delete the files generated by test_grammar:
clean:
	$(RM) $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).* \
		$(TESTOUTDIR)/graphstore/* $(TESTOUTDIR)/tables/*
	find $(TESTOUTDIR) -type f

$(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).json: $(TEST_GRAMMAR_DIR)/$(TEST_GRAMMAR_FILE).py pykythe/__main__.py \
		pykythe/ast_cooked.py \
		pykythe/ast_raw.py \
		pykythe/kythe.py \
		pykythe/pod.py
	mkdir -p $(TESTOUTDIR)
	python3.6 -B -m pykythe \
		--corpus='test-corpus' \
		--root='test-root' \
		$(TEST_GRAMMAR_DIR)/$(TEST_GRAMMAR_FILE).py >"$@"
	python3.6 -B pykythe/decode_json.py <"$@" >"$@-decoded"

$(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).entries: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).json
	mkdir -p $(TESTOUTDIR)
	$(ENTRYSTREAM_EXE) --read_json <"$<" >"$@"

verify: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).entries
	$(VERIFIER_EXE) -check_for_singletons -goal_prefix='#-' "$(TEST_GRAMMAR_DIR)/$(TEST_GRAMMAR_FILE).py" <"$<"

prep_server: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz

$(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).entries
	rm -rf $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	$(WRITE_ENTRIES_EXE) -graphstore $(TESTOUTDIR)/graphstore \
		<$(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).entries
	mkdir -p $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	$(WRITE_TABLES_EXE) -graphstore=$(TESTOUTDIR)/graphstore -out=$(TESTOUTDIR)/tables
	$(TRIPLES_EXE) $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).entries | \
		gzip >$(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz
	# 	$(TRIPLES_EXE) -graphstore $(TESTOUTDIR)/graphstore


run_server: prep_server
	$(HTTP_SERVER_EXE) -serving_table=$(TESTOUTDIR)/tables \
	  -public_resources=$(HTTP_SERVER_RESOURCES) \
	  -listen=localhost:$(BROWSE_PORT)

snapshot:
	rm -rf __pycache__
	git gc
	cd .. && tar --create --exclude=.cayley_history --gzip --file \
		$(HOME)/Downloads/pykythe_$$(date +%Y-%m-%d-%H-%M).tgz pykythe
	ls -lh $(HOME)/Downloads/pykythe_*.tgz

ls_uris:
	$(KYTHE_EXE) -api $(TESTOUTDIR)/tables ls -uris

ls_decor:
	$(KYTHE_EXE) -api $(TESTOUTDIR)/tables decor kythe://test-corpus?path=$(TEST_GRAMMAR_DIR)/$(TEST_GRAMMAR_FILE).py

push_to_github:
	mkdir -p /tmp/test-github
	rm -rf /tmp/test-github/pykythe
	cd /tmp/test-github && git clone https://github.com/kamahen/pykythe.git
	-# git remote add origin https://github.com/kamahen/pykythe.git
	rsync -aAHX --exclude .git --exclude snippets.py ./ /tmp/test-github/pykythe/
	rsync -aAHX ../kythe /tmp/test-github/
	-cd /tmp/test-github/pykythe && git status
	-cd /tmp/test-github/pykythe && git difftool --no-prompt --tool=tkdiff
	@echo '# cd /tmp/test-github && git commit -mCOMMIT-MSG'
	@echo '# cd /tmp/test-github && git push -u origin master'

triples: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz
