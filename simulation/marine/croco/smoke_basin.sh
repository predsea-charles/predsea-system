#!/bin/sh
set -eu

dump_logs() {
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "CROCO BASIN smoke test failed with status ${status}" >&2
        if [ -f /work/croco.stdout.log ]; then
            echo "--- croco.stdout.log ---" >&2
            tail -n 120 /work/croco.stdout.log >&2
        fi
        if [ -f /work/croco.stderr.log ]; then
            echo "--- croco.stderr.log ---" >&2
            tail -n 120 /work/croco.stderr.log >&2
        fi
        echo "--- /work files ---" >&2
        ls -lah /work >&2
    fi
    exit "$status"
}
trap dump_logs EXIT

cp /opt/croco/croco.in.Basin /work/croco.in
# Two short steps are sufficient to prove the executable can initialize,
# integrate, and write NetCDF without turning a container smoke test into a
# scientific benchmark.
sed -i 's/^[[:space:]]*3240[[:space:]]*9600[[:space:]]*65[[:space:]]*1/                2       60      10      1/' /work/croco.in
sed -i 's/^[[:space:]]*T[[:space:]]*90[[:space:]]*0/            T      1       0/' /work/croco.in

cd /work
/usr/local/bin/croco croco.in > croco.stdout.log 2> croco.stderr.log
test -s basin_his.nc
grep -q "MAIN: DONE" croco.stdout.log

trap - EXIT
echo "CROCO BASIN smoke test passed"
