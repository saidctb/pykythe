# Test of pykythe through 3 iterations:
#   1st one: clean
#   2nd one: using the "batch" results
#   3rd one: same as 2nd -- shouldn't re-do anything
set -e -x
MAKEFILE_DIR="$(realpath $(dirname $0)/..)"
TEST_DATA_DIR="$(realpath $(dirname $0)/../test_data)"
BATCH_ID=BBB
TARGET0=t0
# TARGET0=circular_bases
# TARGET0=t2
# TARGET0=simple
TARGET=/tmp/pykythe_test/KYTHE/tmp/pykythe_test/SUBST${TEST_DATA_DIR}/${TARGET0}.verifier

time make -C ${MAKEFILE_DIR} BATCH_ID=${BATCH_ID} clean_lite      ${TARGET}
find /tmp/pykythe_test/KYTHE -name ${TARGET0}'*' -delete
time make -C ${MAKEFILE_DIR} BATCH_ID=${BATCH_ID} touch-fixed-src ${TARGET}
time make -C ${MAKEFILE_DIR} BATCH_ID=${BATCH_ID} touch-fixed-src ${TARGET}
make -C ${MAKEFILE_DIR} BATCH_ID=${BATCH_ID} json-decoded-all
