"""
fix_ww3_caching.py -- removes the stale forcing-cache bug in
scripts/aws_ww3_runner.py.

THE BUG: forcing_prefix is keyed by (run_date, region) only -- not run_id
or forecast_hours. The runner only regenerates wind forcing if wind.nc is
NOT already present at that S3 path. This meant a short canary run and a
later full-length run sharing the same run_date silently reused the
canary's short forcing data, producing a false "SUCCEEDED" status on a run
that actually simulated only a fraction of the requested forecast length.

THE FIX: always regenerate forcing fresh. Generation only takes a few
seconds, so there's no real performance cost to removing the cache -- it
was optimizing something cheap at the cost of correctness.

Run this from the ROOT of your predsea-system repo:

    python3 fix_ww3_caching.py

Review with `git diff scripts/aws_ww3_runner.py` before committing.
"""
from pathlib import Path

path = Path("scripts/aws_ww3_runner.py")
if not path.exists():
    raise SystemExit(
        "ERROR: scripts/aws_ww3_runner.py not found. Run this from the "
        "root of your predsea-system repo."
    )

text = path.read_text()

old = '''    run(["aws", "s3", "sync", grid_prefix, str(work), "--only-show-errors"])
    run(["aws", "s3", "sync", forcing_prefix, str(work), "--only-show-errors"])
    if not (work / "wind.nc").is_file():
        wrf_dir = Path("/workspace/inputs/wrf")
        generated = Path("/workspace/inputs/ww3")
        run(["aws", "s3", "sync", wrf_prefix, str(wrf_dir), "--exclude", "*", "--include", "wrfout_d02_*", "--only-show-errors"])
        run(["python3", "/app/scripts/prepare_ww3_wind_from_wrf.py", "--wrf-dir", str(wrf_dir), "--output-base-dir", str(generated), "--regions", args.region])
        region_forcing = generated / args.region
        run(["aws", "s3", "sync", str(region_forcing), forcing_prefix, "--only-show-errors"])
        run(["cp", "-r", f"{region_forcing}/.", str(work)])'''

new = '''    run(["aws", "s3", "sync", grid_prefix, str(work), "--only-show-errors"])
    # NOTE: forcing is ALWAYS regenerated fresh, never reused from a prior
    # run's cache. forcing_prefix is keyed by (run_date, region) only, not
    # run_id or forecast_hours -- caching by wind.nc-exists here previously
    # caused a real bug: a short canary run and a later full-length run on
    # the same run_date silently reused the canary's short forcing, giving
    # a false "SUCCEEDED" on a run that actually simulated a fraction of
    # the requested forecast length. Regeneration is cheap (~seconds), so
    # there's no real cost to always doing it fresh.
    wrf_dir = Path("/workspace/inputs/wrf")
    generated = Path("/workspace/inputs/ww3")
    run(["aws", "s3", "sync", wrf_prefix, str(wrf_dir), "--exclude", "*", "--include", "wrfout_d02_*", "--only-show-errors"])
    run(["python3", "/app/scripts/prepare_ww3_wind_from_wrf.py", "--wrf-dir", str(wrf_dir), "--output-base-dir", str(generated), "--regions", args.region])
    region_forcing = generated / args.region
    run(["aws", "s3", "sync", str(region_forcing), forcing_prefix, "--only-show-errors"])
    run(["cp", "-r", f"{region_forcing}/.", str(work)])'''

if old not in text:
    raise SystemExit(
        "ERROR: exact block not found in scripts/aws_ww3_runner.py.\n"
        "The file may have changed since this script was written.\n"
        "Run: sed -n '35,44p' scripts/aws_ww3_runner.py\n"
        "and share the output so the fix can be adjusted."
    )

text = text.replace(old, new)
path.write_text(text)
print("Fixed: scripts/aws_ww3_runner.py no longer reuses stale forcing.")
print("Now run: git diff scripts/aws_ww3_runner.py")
