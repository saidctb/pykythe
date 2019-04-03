# Simple scripts for testing etc.

# To build the indexes for the pyythe source and display
# it with the Kythe browser:
# - download the latest Kythe build from https://github.com/kythe/kythe/releases
# - unpack it and link it into ~/kythe (e.g., so that ~/kythe/tools/http_server exists)
# - make -C ~/src/pykythe add-index-pykythe run-server
#   (if you use Emacs, you can't do "make run-server" in the *compilation*
#    window because Emacs will kill the process; instead, run it in a shell)
# Because of some pre-processing, $HOME/src/pykythe/* files show in
# /tmp/pykythe_test/SUBST/$HOME/src/pykythe/pykythe/ast_raw.py
# e.g.:
# http://localhost:8888/#/tmp/pykythe_test/SUBST/home/peter/src/pykythe/pykythe/ast_raw.py?root=test-root&corpus=test-corpus&signature

# make -C ~/src/pykythe clean etags test
# make -C ~/src/pykythe clean_lite etags test
# You should be able to run with --jobs parameter and get the same
# results each time (the outputs should be idempotent), but the order
# of running will vary.  If you use --jobs, you should specify
# --output-sync=target (this seems to be the default).

# To see how to run this for a single source, see target
# test_pykythe_pykythe which also outputs *.kythe.entries files for
# all the imported files.
# Also scripts/test3a.sh (and test3.sh)
# ALso target test_pykythe_pykythe_all

# ("clean" shouldn't be necessary, but the dependencies are fairly
# complicated, so it's possible that "make test" doesn't run
# everything.  In particular, pykythe doesn't check its "version" when
# reusing an import.

# Assume that ../kythe has been cloned from
# https://github.com/google/kythe and has been built with `bazel build
# //... //kythe/web/ui` and that the latest Kythe tarball has been
# downloaded and installed in /opt/kythe.

TESTOUTDIR=/tmp/pykythe_test
SHELL:=/bin/bash
PYTHON3_EXE:=$(shell type -p python3.7)  # /usr/bin/python3.7
FIND_EXE:=$(shell type -p find)          # /usr/bin/find
SWIPL_EXE:=$(shell type -p swipl)        # /usr/bin/swipl
# SWIPL_EXE:=$(realpath ../swipl-devel/build/src/swipl)  # From github
COVERAGE:=$(shell type -p coverage)      # /usr/local/bin/coverage

# stuff for running tests (see https://kythe.io/docs/kythe-verifier.html)
KYTHE:=../kythe
KYTHE_BIN:=$(KYTHE)/bazel-bin
KYTHE_GENFILES:=$(KYTHE)/bazel-genfiles

BROWSE_PORT_PYKYTHE:=8888
BROWSE_PORT_PYTYPE:=8889
VERIFIER_EXE:=/opt/kythe/tools/verifier
ENTRYSTREAM_EXE:=/opt/kythe/tools/entrystream
WRITE_ENTRIES_EXE=/opt/kythe/tools/write_entries
WRITE_TABLES_EXE=/opt/kythe/tools/write_tables
HTTP_SERVER_EXE:=/opt/kythe/tools/http_server
HTTP_SERVER_RESOURCES:=/opt/kythe/web/ui

# If Kythe built from source:
# VERIFIER_EXE:=$(KYTHE_BIN)/kythe/cxx/verifier/verifier
# ENTRYSTREAM_EXE:=$(KYTHE_BIN)/kythe/go/platform/tools/entrystream/entrystream
# WRITE_ENTRIES_EXE:=$(KYTHE_BIN)/kythe/go/storage/tools/write_entries/write_entries
# WRITE_TABLES_EXE:=$(KYTHE_BIN)/kythe/go/serving/tools/write_tables/write_tables
# HTTP_SERVER_EXE:=$(KYTHE_BIN)/kythe/go/serving/tools/http_server/http_server

# TRIPLES_EXE:=$(KYTHE_BIN)/kythe/go/storage/tools/triples/triples
# KYTHE_EXE:=$(KYTHE_BIN)/kythe/go/serving/tools/kythe/kythe

# WARNING: web_ui modifies $(HTTP_SERVER_RESOURCES)
# TODO: fix this for where the build_kythe target puts the resources
#       (e.g. ../kythe/bazel-genfiles/kythe/web/ui/resources/public)
# HTTP_SERVER_RESOURCES:=/tmp/kythe_resources

PYKYTHE_SRCS:=$(shell ls pykythe/*.{py,pl} | sort)
# TODO: see also https://docs.python.org/3/library/uuid.html
VERSION:=$(shell ($(SWIPL_EXE) --version; $(PYTHON3_EXE) --version; head -999999 $(PYKYTHE_SRCS)) | sha1sum | cut -f1 -d' ')
# To add a random piece: $$RANDOM
# or with more randomness:
# -$(shell $(PYTHON3_EXE) -c 'import os, base64; print(base64.urlsafe_b64encode(os.urandom(9)).decode("ascii"))')
BATCH_ID:=$(shell date --utc --iso-8601=ns | sed -e 's/\+00:00//' -e 's/,/./')

PYKYTHE_EXE=$(TESTOUTDIR)/pykythe.qlf

TEST_GRAMMAR_DIR:=test_data
TESTGITHUB:=$(HOME)/tmp/test-github
PARSECMD_OPT:=--parsecmd="$(PYTHON3_EXE) -m pykythe"
# ENTRIESCMD_OPT:=--entriescmd=$(realpath ../kythe/bazel-bin/kythe/go/platform/tools/entrystream/entrystream)
ENTRIESCMD_OPT:=--entriescmd=$(ENTRYSTREAM_EXE)
# PYTHONPATH starts at .., so "absolute" paths in test_data should be
#            of the form "pykythe.test_data.___"
#            (see also fix_for_verifier.py and ${ROOT_DIR} etc. substitutions
PWD_REAL:=$(realpath .)
TYPESHED_REAL:=$(realpath ../typeshed)
SUBSTDIR:=$(TESTOUTDIR)/SUBST
KYTHEOUTDIR:=$(TESTOUTDIR)/KYTHE
BUILTINS_SYMTAB_FILE:=$(TESTOUTDIR)/KYTHE/builtins_symtab.pl
TESTOUT_PYKYTHEDIR=$(KYTHEOUTDIR)/pykythe
SUBSTDIR_PWD_REAL:=$(shell echo $(SUBSTDIR) | sed "s:$$:$(PWD_REAL):")
KYTHEOUTDIR_PWD_REAL:=$(shell echo $(KYTHEOUTDIR) | sed "s:$$:$(PWD_REAL):")
# Warning: do *not* replace the following "$(shell realpath .." with "$(realpath ..".
PYTHONPATH_DOT:=$(shell realpath .. | sed 's!^/!$(SUBSTDIR)/!')
TESTOUT_SRCS:=$(shell $(FIND_EXE) $(TEST_GRAMMAR_DIR) -name '*.py'  | sort | \
    sed -e 's!^!$(SUBSTDIR_PWD_REAL)/!')
TESTOUT_TARGETS:=$(shell $(FIND_EXE) $(TEST_GRAMMAR_DIR) -name '*.py' | sort | \
    sed -e 's!^!$(KYTHEOUTDIR)$(SUBSTDIR_PWD_REAL)/!' -e 's!\.py$$!.kythe.verifier!')
TESTOUT_TYPESHED:=$(KYTHEOUTDIR)$(TYPESHED_REAL)
KYTHE_CORPUS_ROOT_OPT:=--kythe_corpus='test-corpus' --kythe_root='test-root'
VERSION_OPT:=--version='$(VERSION)'
PYKYTHEOUT_OPT:=--kytheout='$(KYTHEOUTDIR)'
ifeq ($(BATCH_ID),)
    BATCH_OPT:=--batch_suffix=
else
    BATCH_OPT:=--batch_suffix='-batch-$(BATCH_ID)'
endif
# TODO: parameterize following for python3.6, etc.:
PYTHONPATH_OPT:=--pythonpath='$(PYTHONPATH_DOT):../typeshed/stdlib/3.7:../typeshed/stdlib/3:../typeshed/stdlib/2and3:/usr/lib/python3.7'
PYTHONPATH_OPT_NO_SUBST:=--pythonpath='$(PYTHONPATH_DOT):../typeshed/stdlib/3.7:../typeshed/stdlib/3:../typeshed/stdlib/2and3:/usr/lib/python3.7'
PYKYTHE_OPTS0=$(VERSION_OPT) $(BATCH_OPT) \
	--builtins_symtab=$(BUILTINS_SYMTAB_FILE) \
	$(PYKYTHEOUT_OPT) $(PARSECMD_OPT) $(ENTRIESCMD_OPT) $(KYTHE_CORPUS_ROOT_OPT)
PYKYTHE_OPTS=$(PYKYTHE_OPTS0)  $(PYTHONPATH_OPT)
TIME:=time

# .PRECIOUS: %.kythe.entries %.json-decoded %.json
.SECONDARY:  # Do not delete any intermediate files

# $(PYKYTHE_SRCS) is a dependency because it's used to compute $(VERSION)
$(SUBSTDIR_PWD_REAL)/pykythe/bootstrap_builtins_symtab.pl: $(PYKYTHE_SRCS)

$(SUBSTDIR_PWD_REAL)/%: % scripts/fix_for_verifier.py
	@# FROM_DIR TO_DIR TYPESHED_DIR FROM_FILE TO_FILE
	@echo "fix >$@"
	@mkdir -p "$(dir $@)"
	@$(PYTHON3_EXE) scripts/fix_for_verifier.py "${VERSION}" "$(TEST_GRAMMAR_DIR)" "$(SUBSTDIR)$(realpath $(TEST_GRAMMAR_DIR))" "$(realpath ../typeshed)" "$(realpath $<)" "$@"

########
# TODO: the following have an extra stutter in the files
########

# $(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1.py: \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i3.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1_sub/i4.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1_sub/i4a.py

# $(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1_sub/i4.py: \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1_sub/i4a.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i5.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i8/i9.py

# $(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/imports1.py: \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i1_sub/i4.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_file1 \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i6.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i7.py \
# 	$(SUBSTDIR_PWD_REAL)/test_data/imports_dir1/i8/__init__.py

.PHONY: testout_srcs
testout_srcs: $(TESTOUT_SRCS)

.PHONY: importlab
importlab:
	../importlab/bin/importlab --tree --trim -P.. .

$(PYKYTHE_EXE): pykythe/*.pl
	$(SWIPL_EXE) --stand_alone=true --foreign=save --undefined=error --verbose=true \
	    -o $@ -c pykythe/pykythe.pl

# TODO: this rule requires all the SUBST files ($(TESTOUT_SRCS))
#       because it isn't easy to write more specific Make fules (and
#       what about circular imports?):
#  $(SUBSTDIR_PWD_REAL)/%.py
# NOTE: the 1st argument is important (used by "$<")
$(KYTHEOUTDIR)%.kythe.json \
$(KYTHEOUTDIR)%.kythe.entries: \
		%.py \
		$(TESTOUT_SRCS) \
		$(PYKYTHE_SRCS) \
		$(BUILTINS_SYMTAB_FILE) \
	 	$(PYKYTHE_EXE) \
		pykythe/pykythe.pl $(wildcard pykythe/*.pl) \
		pykythe/__main__.py $(wildcard pykythe/*.py)
	@# TODO: make this into a script (with a saved state - qsave_program/2 stand_alone).
	@#       maybe?: set_prolog_flag(generate_debug_info, false)
	@# Note that -O changes the order of some directives (see the comment in
	@# pykythe/pykythe.pl with the last `set_prolog_flag(autoload, false)`.
	$(TIME) $(PYKYTHE_EXE) \
	    $(PYKYTHE_OPTS) \
	    "$<"

# WARNING -- this doesn't play nicely with --jobs because $(BUILTINS_SYMTAB_FILE
#            is output twice

# TODO: This uses /tmp/pykythe_test/SUBST/home/peter/src/pykythe/pykythe/bootstrap_builtins.py
#       This is the same as make $(mumble)/src/typeshed/stdlib/2and3/builtins.kythe.json
#       followed by gen_builtins_symtab.
# $(PYKYTHE_SRCS) is a dependency because it's used to compute $(VERSION)
$(BUILTINS_SYMTAB_FILE) \
$(KYTHEOUTDIR)$(TYPESHED_REAL)/stdlib/2and3/builtins.kythe.json \
$(KYTHEOUTDIR)$(TYPESHED_REAL)/stdlib/2and3/builtins.kythe.entries: \
		$(SUBSTDIR_PWD_REAL)/pykythe/bootstrap_builtins.py \
		$(SUBSTDIR_PWD_REAL)/pykythe/bootstrap_builtins_symtab.pl \
		$(PYKYTHE_SRCS) \
	 	$(PYKYTHE_EXE) \
		pykythe/gen_builtins_symtab.pl \
		pykythe/pykythe.pl $(wildcard pykythe/*.pl) \
		pykythe/__main__.py $(wildcard pykythe/*.py)
	@mkdir -p "$(dir $@)"
	cat $(SUBSTDIR_PWD_REAL)/pykythe/bootstrap_builtins_symtab.pl >"$@"
	$(TIME) $(PYKYTHE_EXE) \
	    $(PYKYTHE_OPTS) \
	    "$<"
	$(SWIPL_EXE) pykythe/gen_builtins_symtab.pl \
	    -- $(VERSION_OPT) $(PYTHONPATH_OPT) \
	    "$(KYTHEOUTDIR)$(TYPESHED_REAL)/stdlib/2and3/builtins.kythe.json" \
	    "$(BUILTINS_SYMTAB_FILE)"

%.json-decoded: %.json scripts/decode_json.py
	$(PYTHON3_EXE) scripts/decode_json.py <"$<" >"$@"

.PHONY: json-decoded-all
json-decoded-all:
	for i in $$(find $(KYTHEOUTDIR) -type f -name '*.kythe.json'); do \
	    $(PYTHON3_EXE) scripts/decode_json.py <$$i >$$i-decoded; \
	done

# %.kythe.entries: %.kythe.json %.kythe.json-decoded
# 	@# We leave /pykythe/symtab unencoded, so need to strip it:
# 	egrep -v '^{"fact_name":"/pykythe/symtab"' <"$<" | \
# 	    $(ENTRYSTREAM_EXE) --read_format=json >"$@"

$(KYTHEOUTDIR)/%.kythe.verifier: $(KYTHEOUTDIR)/%.kythe.entries
	@# TODO: --ignore_dups
	set -o pipefail; $(VERIFIER_EXE) -check_for_singletons -goal_prefix='#-' \
		"/$*.py" \
		<"$<" | tee "$@" || (rm "$@" ; exit 1)

.PHONY: verify-%
# TODO: make the following work:
verify-%: $(KYTHEOUTDIR_PWD_REAL)/$(TEST_GRAMMAR_DIR)/%.kythe.verifier

.PHONY: etags
etags: pykythe/TAGS

pykythe/TAGS: pykythe/TAGS-py pykythe/TAGS-pl
	cat pykythe/TAGS-pl pykythe/TAGS-py >$@

pykythe/TAGS-pl: pykythe/*.pl
	cd pykythe ; etags -l prolog -o ../$@ *.pl

pykythe/TAGS-py: pykythe/*.py
	cd pykythe ; etags -l python -o ../$@ *.py

.PHONY: test
test: all_tests

.PHONY: all_tests
all_tests: etags unit_tests test_imports1 test_grammar test_pykythe_pykythe # json-decoded-all  # pykythe_http_server

.PHONY: unit_tests
unit_tests: tests/test_pykythe.py \
		pykythe/ast_raw.py \
		pykythe/pod.py
	$(PYTHON3_EXE) tests/test_pykythe.py

.PHONY: test_imports1
test_imports1:  # run imports code, to ensure that it behaves as expected
	cd .. && PYTHONPATH=. $(PYTHON3_EXE) -B pykythe/test_data/imports1.py
	cd test_data && PYTHONPATH=../.. $(PYTHON3_EXE) -B imports1.py

test_c3_a:  # run c3_a, to ensure it behaves as expected
	$(PYTHON3_EXE) -B test_data/c3_a.py

.PHONY: test_grammar
test_grammar: $(TESTOUT_TARGETS) # TODO: test_grammar2

# TODO: The following needs something like this added to TESTOUT_SRCS:
#        realpath ../typeshed/stdlib/3/builtins.pyi

.PHONY: test_grammar2
test_grammar2: $(TESTOUT_TYPESHED)/stdlib/3/builtins.kythe.json

.PHONY: test_pykythe_pykythe
# This is an example of how to generate outputs for a single source
# (it also generates *.kythe.entries for all the imported files). ===
test_pykythe_pykythe: $(KYTHEOUTDIR)$(PWD_REAL)/pykythe/__main__.kythe.entries

.PHONY: test_pykythe_pykythe_all test_pykythe_pykythe_all0
# This is an example of running on multiple sources
test_pykythe_pykythe_all: $(BUILTINS_SYMTAB_FILE) $(PYKYTHE_EXE) test_pykythe_pykythe_all0

test_pykythe_pykythe_all0:
	@# specify the order of the *.py files, to allow verifying that the cache is used:
	$(TIME) $(PYKYTHE_EXE) $(PYKYTHE_OPTS0) $(PYTHONPATH_OPT_NO_SUBST) __main__.py pykythe/*.py

# Reformat all the source code (uses .style.yapf)
.PHONY: pyformat
pyformat:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | xargs yapf -i

.PHONY: yapf
yapf: pyformat

.PHONY: pylint
pylint:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | \
		grep -v snippets.py | xargs -L1 pylint --disable=missing-docstring

.PHONY: pyflakes
pyflakes:
	find . -type f -name '*.py' | grep -v $(TEST_GRAMMAR_DIR) | \
		grep -v snippets.py | xargs -L1 pyflakes

PYTYPE_DIR=/tmp/pykythe_pytype
# TODO: PYTYPE_V=3.7 when it's supported:
PYTYPE_V=3.6
# Can't do the following because need to compile
# things like parser_ext:
#   PYTYPE=PYTHONPATH=$$(pwd)/../pytype ../pytype/scripts/pytype
# and PYTHONPATH seems to confuse other things in:N
#   PYTYPE=PYTHONPATH=$$(pwd)/../pytype/build/lib.linux-x86_64-2.7 ../pytype/scripts/pytype
# The following requires having done an install from ../pytype:
# PYTYPE=/usr/local/bin/pytype
PYTYPE=$(shell type -p pytype)
# TODO: in the following, it would be nice if we could remove the
#       "cd pykythe" and instead using the file name "pykythe/...py"
#       but that seems to upset pytype's imnport mechanism.

# TODO: --python-version=3.6  # conflict if python3.6 is not default python3
#       maybe --no-site-packages ?
# Anyway, mypy doesn't yet have a plugin for dataclasses. :(
MYPY=$(PYTHON3_EXE) $$(which mypy) --python-version=3.7 --strict-optional --check-untyped-defs --warn-incomplete-stub --warn-no-return --no-incremental --disallow-any-unimported --show-error-context --implicit-optional --strict --disallow-incomplete-defs
# TODO: --disallow-incomplete-defs  https://github.com/python/mypy/issues/4603
# TODO: --disallow-any-generics

.PHONY: mypy
mypy:
	$(MYPY) pykythe/__main__.py
	$(MYPY) tests/test_pykythe.py

.PHONY: lint
lint: pylint

.PHONY: clean
clean:
	$(RM) -r $(TESTOUTDIR) pykythe/TAGS*

.PHONY: clean-lite clean_lite
clean-lite clean_lite:
	$(RM) -r $(KYTHEOUTDIR)

.PHONY: touch-fixed-src touch_fixed_src
touch-fixed-src touch_fixed_src:  # For doing a rerun with cache preserved
	-find $(SUBSTDIR) -type f -print0 | xargs -0 touch

.PHONY: clean-cache clean_cache
clean-batch clean_batch:
	@# leaves the BATCH cache intact
	find $(KYTHEOUTDIR) -name '*.kythe.json' -o -name '*.kythe.json-decoded' -o -name '*.kythe.entries' -o -name '*.kythe.verifier' -delete

PHONY: clean-batch clean_batch
	find $(KYTHEOUTDIR) -name '*.kythe.json-batch-*' -delete

.PHONY: clean-testout-srcs clean_testout_srcs
clean-testout-srcs clean_testout_srcs:
	find $(SUBSTDIR) -name '*.py' -delete

clean-batch clean_batch:

.PHONY: tkdiff
tkdiff:
	git difftool --no-prompt --tool=tkdiff

# .nq.gz files are for Cayley

#@#@# prep_server: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz

%.nq.gz: %.entries
	$(RM) -r $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	@mkdir -p $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	$(WRITE_ENTRIES_EXE) -graphstore $(TESTOUTDIR)/graphstore <"$<"
	$(WRITE_TABLES_EXE) -graphstore=$(TESTOUTDIR)/graphstore -out=$(TESTOUTDIR)/tables
	$(TRIPLES_EXE) "$<" | gzip >"$@"
	$(TRIPLES_EXE) -graphstore $(TESTOUTDIR)/graphstore

FFF:=$(shell find pykythe test_data -name '*.py')
zzz:
	@# for i in $(foreach file,$(wildcard pykythe/*.py) $(wildcard test_data/**.py),$(basename $(KYTHEOUTDIR)$(SUBSTDIR)$(realpath $(file))).kythe.entries);do echo $$i; done
	@echo $(foreach file,$(FFF),$(basename $(KYTHEOUTDIR)$(SUBSTDIR)$(realpath $(file))).kythe.entries)


.PHONY: add-index-pykythe
# $(wildcard test_data/**.py) doesn't work, so do it this way:
TEST_FILES:=$(shell find pykythe test_data -name '*.py')
add-index-pykythe: \
		$(foreach file,$(TEST_FILES),$(basename $(KYTHEOUTDIR)$(SUBSTDIR)$(realpath $(file))).kythe.entries)
	$(RM) -r $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	mkdir -p $(TESTOUTDIR)/graphstore $(TESTOUTDIR)/tables
	@# cat $(basename $(KYTHEOUTDIR)$(SUBSTDIR)$(realpath pykythe))/*.kythe.json
	set -o pipefail; \
	    cat $$(find $(KYTHEOUTDIR) -name '*.kythe.json') | \
	    egrep -v '^{"fact_name":"/pykythe/symtab"' | \
	    $(ENTRYSTREAM_EXE) --read_format=json | \
	    $(WRITE_ENTRIES_EXE) -graphstore $(TESTOUTDIR)/graphstore
	$(WRITE_TABLES_EXE) -graphstore=$(TESTOUTDIR)/graphstore -out=$(TESTOUTDIR)/tables

# TODO: pre-req:  prep_server
.PHONY: run_server run-server
run_server run-server: # web_ui  # TODO: uncomment web_ui
	$(HTTP_SERVER_EXE) -serving_table=$(TESTOUTDIR)/tables \
	  -public_resources=$(HTTP_SERVER_RESOURCES) \
	  -listen=localhost:$(BROWSE_PORT_PYKYTHE)

.PHONY: build_kythe build-kythe
build_kythe build-kythe:
	cd ../kythe && git remote show origin && git pull --recurse-submodules
	-# cd ../kythe && git pull --recurse-submodules
	cd ../kythe && nice bazel build --jobs=3 @local_config_cc//:toolchain;
	cd ../kythe && nice bazel build --jobs=3 //...
	cd ../kythe && nice bazel test -k --jobs=3 //...
	cd ../kythe && LEIN_JAVA_CMD=/usr/lib/jvm/java-8-openjdk-amd64/bin/java nice bazel build //kythe/web/ui
	cd ../kythe && bazel shutdown

.PHONY: web_ui
web_ui:
	@# assumes that build_kythe has been done
	$(RM) -rf $(HTTP_SERVER_RESOURCES)
	@mkdir -p $(HTTP_SERVER_RESOURCES)
	cp -pR $(KYTHE)/kythe/web/ui/resources/public/{css,js,index.html} $(HTTP_SERVER_RESOURCES)
	cp -p  $(KYTHE_GENFILES)/kythe/web/ui/resources/public/js/main.js $(HTTP_SERVER_RESOURCES)/js/
# .PHONY: triples
# triples: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).nq.gz

.PHONY: gc
gc:
	du -hsc .
	git gc
	git repack -a -d -f --depth=250 --window=250
	git gc
	du -hsc .

.PHONY: snapshot
snapshot:
	find . -name __pycache__ -type d | xargs rm -rf
	git gc
	cd .. && tar --create --exclude=.cayley_history --exclude=.mypy_cache --exclude=__pycache__ --gzip --file \
		$(HOME)/Downloads/pykythe_$$(date +%Y-%m-%d-%H-%M).tgz pykythe
	@# ls -lh $(HOME)/Downloads/pykythe_*.tgz

#@#@# PHONY: ls_uris
#@#@# ls_uris:
#@#@# 	$(KYTHE_EXE) -api $(TESTOUTDIR)/tables ls -uris

#@#@# PHONY: ls_decor
#@#@# ls_decor:
#@#@# 	$(KYTHE_EXE) -api $(TESTOUTDIR)/tables decor kythe://test-corpus?path=$(TEST_GRAMMAR_DIR)/$(TEST_GRAMMAR_FILE).py

.PHONY: push_to_github
push_to_github:
	@# TODO: remove ../typeshed from following:
	grep SUBMIT $$(find tests pykythe scripts ../typeshed $(TEST_GRAMMAR_DIR) tests -type f); if [ $$? -eq 0 ]; then exit 1; fi
	@# The following are for the initial setup only:
	@#   @mkdir -p $(TESTGITHUB)
	@#   rm -rf $(TESTGITHUB)/pykythe
	@#   cd $(TESTGITHUB) && git clone https://github.com/kamahen/pykythe.git
	@# The following is not needed ("git clone" sets this up):
	@#   git remote add origin https://github.com/kamahen/pykythe.git
	cd $(TESTGITHUB)/pykythe && git pull
	rsync -aAHX --delete --exclude .git \
		--exclude .coverage --exclude htmlcov --exclude __pykythe__ \
		--exclude snippets.py \
		./ $(TESTGITHUB)/pykythe/
	rsync -aAHX --delete ../kythe ../typeshed $(TESTGITHUB)/
	-cd $(TESTGITHUB)/pykythe && git status
	-cd $(TESTGITHUB)/pykythe && git difftool --no-prompt --tool=tkdiff
	@echo '# pushd $(TESTGITHUB)/pykythe && git commit -mCOMMIT-MSG' -a
	@echo '# pushd $(TESTGITHUB)/pykythe && git push -u origin master'


# Not yet implemented
#@#@# PHONY: pykythe_http_server
#@#@# pykythe_http_server: $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).kythe.json scripts/pykythe_http_server.pl FORCE
#@#@# 	scripts/pykythe_http_server.pl \
#@#@# 		--port 8008 \
#@#@# 		--kythe $(TESTOUTDIR)/$(TEST_GRAMMAR_FILE).kythe.json

FORCE:
.PHONY: FORCE


#@#@# PHONY: coverage
#@#@# coverage:
#@#@# 	-# file:///home/peter/src/pykythe/htmlcov/index.html
#@#@# 	-# TODO: use the variables in the rule for $(TESTOUTDIR)/%.kythe.json
#@#@# 	-# TODO: run test_pykythe.py and add to coverage results
#@#@# 	$(PYTHON3_EXE) $(COVERAGE) run --branch -m pykythe \
#@#@# 		$(KYTHE_CORPUS_ROOT_OPT) \
#@#@# 		--src="$(TEST_GRAMMAR_DIR)/py3_test_grammar.py" \
#@#@# 		--out_kythe=/dev/null --out_fqn_expr=/dev/null
#@#@# 	-# $(PYTHON3_EXE) $(COVERAGE) run --branch tests/test_pykythe.py
#@#@# 	$(COVERAGE) html
#@#@# 	rm -r pykythe/__pycache__


pytype:
	@# TODO: ast_cooked.py needs "from __future__" removed to make pytype happy
	-$(RM) -r .pytype
	-time pytype -k --exclude=pykythe/bootstrap_builtins.py pykythe
	for i in $$(ls pykythe/*.py | fgrep -v bootstrap_builtins.py); do \
	    echo $$i \
	        .pytype/imports/pykythe.$$(basename $$i .py).imports \
		/tmp/$$(basename $$i .py).pyxref.json; \
	    time pyxref --debug --python_version=3.6 --imports_info=.pytype/imports/pykythe.$$(basename $$i .py).imports $$i >/tmp/$$(basename $$i .py).pyxref.json;  \
	done
	$(RM) -r /tmp/pytype-graphstore /tmp/pytype-tables
	mkdir -p $/tmp/pytype-graphstore /tmp/pytype-tables
	set -o pipefail; \
	    cat /tmp/*.pyxref.json | \
	    $(ENTRYSTREAM_EXE) --read_format=json | \
	    $(WRITE_ENTRIES_EXE) -graphstore /tmp/pytype-graphstore
	$(WRITE_TABLES_EXE) -graphstore=/tmp/pytype-graphstore -out=/tmp/pytype-tables

run-pytype-server:
	$(HTTP_SERVER_EXE) -serving_table=/tmp/pytype-tables \
	  -public_resources=$(HTTP_SERVER_RESOURCES) \
	  -listen=localhost:$(BROWSE_PORT_PYTYPE)

# $(PYTYPE_DIR)/%.pyi: %.py
# 	@mkdir -p $(dir $@)
# 	-$(PYTYPE) -V$(PYTYPE_V) -P $(PYTYPE_DIR) $< -o $@

# $(PYTYPE_DIR)/pykythe/ast.pyi: $(addprefix $(PYTYPE_DIR)/pykythe/,\
# 	pod.pyi)
# $(PYTYPE_DIR)/pykythe/ast_cooked.pyi: $(addprefix $(PYTYPE_DIR)/pykythe/,\
# 	pod.pyi typing_debug.pyi ast.pyi)
# $(PYTYPE_DIR)/pykythe/ast_raw.pyi: $(addprefix $(PYTYPE_DIR)/pykythe/,\
# 	pod.pyi typing_debug.pyi ast_cooked.pyi)
# $(PYTYPE_DIR)/pykythe/__main__.pyi: $(addprefix $(PYTYPE_DIR)/pykythe/,\
# 	pod.pyi typing_debug.pyi ast_raw.pyi ast_cooked.pyi ast.pyi)
