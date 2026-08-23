#!/usr/bin/env python3
"""Render a bounded, internally-consistent CROCO regional namelist."""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path


def render(template: str, *, start_date: str, forecast_hours: int, work_dir: Path,
           timestep_seconds: int = 60, ndtfast: int = 30) -> str:
    if forecast_hours < 1 or forecast_hours > 120:
        raise ValueError("forecast_hours must be between 1 and 120")
    if timestep_seconds <= 0 or 3600 % timestep_seconds:
        raise ValueError("timestep_seconds must be a positive divisor of one hour")
    if ndtfast <= 0:
        raise ValueError("ndtfast must be a positive integer")
    start = dt.datetime.strptime(start_date, "%Y-%m-%d")
    end = start + dt.timedelta(hours=forecast_hours)
    ntimes = forecast_hours * 3600 // timestep_seconds
    steps_per_hour = 3600 // timestep_seconds
    text = template
    text = re.sub(
        r"(time_stepping: NTIMES\s+dt\[sec\]\s+NDTFAST\s+NINFO\s*\n)\s*\d+\s+\d+\s+\d+\s+\d+",
        rf"\g<1>                {ntimes}      {timestep_seconds}      {ndtfast}      10",
        text,
    )
    text = re.sub(r"(start_date:\s*\n).*", rf"\g<1>{start:%Y-%m-%d %H:%M:%S}", text)
    text = re.sub(r"(end_date:\s*\n).*", rf"\g<1>{end:%Y-%m-%d %H:%M:%S}", text)
    replacements = {
        r"(?m)^(grid:[ \t]+filename[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_grid.nc",
        r"(?m)^(forcing:[ \t]+filename[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_frc.nc",
        r"(?m)^(bulk_forcing:[ \t]+filename[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_blk.nc",
        r"(?m)^(climatology:[ \t]+filename[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_clm.nc",
        r"(?m)^(boundary:[ \t]+filename[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_bry.nc",
        r"(?m)^(initial:[ \t]+NRREC / filename[ \t]*\n[ \t]*1[ \t]*\n)[ \t]*.*$": rf"\g<1>    {work_dir}/croco_ini.nc",
        r"(?m)^(restart:[ \t]+NRST, NRPFRST / filename[ \t]*\n)[ \t]*\d+[ \t]+-1[ \t]*\n[ \t]*.*$": rf"\g<1>                   {ntimes}    -1\n    {work_dir}/croco_rst.nc",
        r"(?m)^(history:[ \t]+LDEFHIS, NWRT, NRPFHIS / filename[ \t]*\n)[ \t]*T[ \t]+\d+[ \t]+0[ \t]*\n[ \t]*.*$": rf"\g<1>            T      {steps_per_hour}     0\n    {work_dir}/croco_his.nc",
        r"(?m)^(averages:[ \t]+NTSAVG, NAVG, NRPFAVG / filename[ \t]*\n)[ \t]*1[ \t]+\d+[ \t]+0[ \t]*\n[ \t]*.*$": rf"\g<1>            1      {ntimes}     0\n    {work_dir}/croco_avg.nc",
        r"(?m)^(sponge:[ \t]+X_SPONGE \[m\],[ \t]+V_SPONGE \[m\^2/sec\][ \t]*\n)[ \t]*.*$": rf"\g<1>                    50000.           100.",
    }
    for pattern, replacement in replacements.items():
        text, count = re.subn(pattern, replacement, text)
        if count != 1:
            raise ValueError(f"CROCO template field did not match exactly once: {pattern}")
    if str(ntimes) not in text or f"{end:%Y-%m-%d %H:%M:%S}" not in text:
        raise ValueError("rendered CROCO namelist failed duration consistency check")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    parser.add_argument("--timestep-seconds", type=int, default=60)
    parser.add_argument("--ndtfast", type=int, default=30)
    args = parser.parse_args()
    rendered = render(
        args.template.read_text(),
        start_date=args.start_date,
        forecast_hours=args.forecast_hours,
        work_dir=args.work_dir,
        timestep_seconds=args.timestep_seconds,
        ndtfast=args.ndtfast,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)
    print(f"Rendered CROCO namelist: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
