from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BalearicDomain:
    start_date: str = "2026-05-04_00:00:00"
    end_date: str = "2026-05-05_00:00:00"
    interval_seconds: int = 10800
    geog_data_path: str = "/opt/WPS_GEOG"
    ref_lat: float = 40.0
    ref_lon: float = 5.0
    d01_dx_m: int = 9000
    d01_dy_m: int = 9000
    # d01 grew from 160x120 to 210x140 (2026-08-05) to actually reach
    # alboran_1km's western edge (lon -6.0) -- the old 160x120 grid only
    # reached -3.96, missing ~40% of alboran's bbox including the whole
    # boundary-point edge at x=1. Growth is symmetric about ref_lat/ref_lon
    # (WRF's standard mother-domain behavior), so d02's i/j_parent_start below
    # were shifted by half the added columns/rows (+25/+10) to keep d02
    # anchored at its original absolute position over balearic/gulf_of_lion.
    d01_e_we: int = 210
    d01_e_sn: int = 140
    # Expanded Domain 2 (d02 @ 3km resolution): Covers entire Western Mediterranean
    # from Gibraltar (-6.0°W) to Messina (+16.0°E) and North Africa (35°N) to S. France (45°N)
    d02_e_we: int = 571
    d02_e_sn: int = 361
    # Emergency operational profile: retain all regional footprints at the
    # d02 resolution.  Each dimension preserves the corresponding 1 km nest
    # extent: (fine_dimension - 1) / 3 + 1.
    regional_dx_m: int = 3000
    d03_e_we: int = 51
    d03_e_sn: int = 51
    d04_e_we: int = 101
    d04_e_sn: int = 34
    d05_e_we: int = 51
    d05_e_sn: int = 134
    d06_e_we: int = 51
    d06_e_sn: int = 68
    d07_e_we: int = 85
    d07_e_sn: int = 101

    d02_i_parent_start: int = 10
    d02_j_parent_start: int = 10
    d03_i_parent_start: int = 34
    d03_j_parent_start: int = 35
    d04_i_parent_start: int = 10
    d04_j_parent_start: int = 180
    d05_i_parent_start: int = 110
    d05_j_parent_start: int = 60
    d06_i_parent_start: int = 160
    d06_j_parent_start: int = 180
    d07_i_parent_start: int = 160
    d07_j_parent_start: int = 10

    forcing_prefix: str = "ECMWF"
    max_dom: int = 2

    @classmethod
    def ultra_1km(cls, **kwargs) -> "BalearicDomain":
        """Return the preserved seven-domain 1 km regional configuration."""
        return cls(
            max_dom=7,
            regional_dx_m=1000,
            d03_e_we=151,
            d03_e_sn=151,
            d04_e_we=301,
            d04_e_sn=100,
            d05_e_we=151,
            d05_e_sn=400,
            d06_e_we=151,
            d06_e_sn=202,
            d07_e_we=253,
            d07_e_sn=301,
            **kwargs,
        )

    @property
    def regional_parent_ratio(self) -> int:
        d02_dx_m = self.d01_dx_m // 3
        if d02_dx_m % self.regional_dx_m:
            raise ValueError("regional resolution must divide the d02 resolution exactly")
        ratio = d02_dx_m // self.regional_dx_m
        if ratio < 1:
            raise ValueError("regional resolution cannot be coarser than d02")
        return ratio

    @property
    def mpi_layout(self) -> tuple[int, int]:
        """Return a safe decomposition for the active domain topology."""
        override_x = os.environ.get("MPI_NPROC_X")
        override_y = os.environ.get("MPI_NPROC_Y")
        if override_x or override_y:
            if not (override_x and override_y):
                raise ValueError("MPI_NPROC_X and MPI_NPROC_Y must be configured together")
            return int(override_x), int(override_y)
        return (8, 8) if self.max_dom == 2 else (4, 3)

    @property
    def grids(self) -> tuple[tuple[int, int], ...]:
        grids = (
            (self.d01_e_we, self.d01_e_sn),
            (self.d02_e_we, self.d02_e_sn),
            (self.d03_e_we, self.d03_e_sn),
            (self.d04_e_we, self.d04_e_sn),
            (self.d05_e_we, self.d05_e_sn),
            (self.d06_e_we, self.d06_e_sn),
            (self.d07_e_we, self.d07_e_sn),
        )
        return grids[: self.max_dom]

    @property
    def parent_grid_ratios(self) -> tuple[int, ...]:
        ratios = (1, 3) + (self.regional_parent_ratio,) * 5
        return ratios[: self.max_dom]


def validate_domain_topology(domain: BalearicDomain) -> None:
    """Reject degenerate WRF nests before geogrid or real.exe can run."""
    if domain.max_dom < 1 or domain.max_dom > 7:
        raise ValueError(f"max_dom must be between 1 and 7, got {domain.max_dom}")
    invalid = [
        f"d{domain_id:02d}={ratio}"
        for domain_id, ratio in enumerate(domain.parent_grid_ratios[1:], start=2)
        if ratio < 3
    ]
    if invalid:
        raise ValueError(
            "Invalid WRF nesting topology; every active child domain must have "
            f"parent_grid_ratio >= 3: {', '.join(invalid)}"
        )


def _values(values: tuple[object, ...]) -> str:
    return ", ".join(str(value) for value in values)


def render_namelist(domain: BalearicDomain) -> str:
    validate_domain_topology(domain)
    count = domain.max_dom
    dates_start = tuple(f"'{domain.start_date}'" for _ in range(count))
    dates_end = tuple(f"'{domain.end_date}'" for _ in range(count))
    parent_ids = (1, 1, 2, 2, 2, 2, 2)[:count]
    starts_i = (1, domain.d02_i_parent_start, domain.d03_i_parent_start, domain.d04_i_parent_start, domain.d05_i_parent_start, domain.d06_i_parent_start, domain.d07_i_parent_start)[:count]
    starts_j = (1, domain.d02_j_parent_start, domain.d03_j_parent_start, domain.d04_j_parent_start, domain.d05_j_parent_start, domain.d06_j_parent_start, domain.d07_j_parent_start)[:count]
    e_we = tuple(grid[0] for grid in domain.grids)
    e_sn = tuple(grid[1] for grid in domain.grids)
    geog_res = tuple("'modis_landuse_20class_30s_with_lakes+default'" for _ in range(count))
    return f"""&share
 wrf_core = 'ARW',
 max_dom = {count},
 start_date = {_values(dates_start)},
 end_date = {_values(dates_end)},
 interval_seconds = {domain.interval_seconds},
 io_form_geogrid = 2,
 opt_output_from_geogrid_path = './geo_em',
 debug_level = 0,
/

&geogrid
 parent_id = {_values(parent_ids)},
 parent_grid_ratio = {_values(domain.parent_grid_ratios)},
 i_parent_start = {_values(starts_i)},
 j_parent_start = {_values(starts_j)},
 e_we = {_values(e_we)},
 e_sn = {_values(e_sn)},
 geog_data_res = {_values(geog_res)},
 dx = {domain.d01_dx_m},
 dy = {domain.d01_dy_m},
 map_proj = 'lambert',
 ref_lat = {domain.ref_lat:.4f},
 ref_lon = {domain.ref_lon:.4f},
 truelat1 = 37.0,
 truelat2 = 43.0,
 stand_lon = {domain.ref_lon:.4f},
 geog_data_path = '{domain.geog_data_path}',
/

&ungrib
 out_format = 'WPS',
 ordered_by_date = .true.,
 prefix = '{domain.forcing_prefix}',
/

&metgrid
 fg_name = '{domain.forcing_prefix}',
 io_form_metgrid = 2,
 opt_output_from_metgrid_path = './met_em',
/
"""


def write_namelist(path: Path, domain: BalearicDomain) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_namelist(domain))
    return path


def validate_mpi_decomposition(
    domain: BalearicDomain,
    nproc_x: int = 4,
    nproc_y: int = 3,
    minimum_patch_cells: int = 10,
) -> None:
    invalid = []
    for domain_id, (e_we, e_sn) in enumerate(domain.grids, start=1):
        patch_x = e_we // nproc_x
        patch_y = e_sn // nproc_y
        if patch_x < minimum_patch_cells or patch_y < minimum_patch_cells:
            invalid.append(f"d{domain_id:02d}={e_we}x{e_sn} -> {patch_x}x{patch_y} cells")
    if invalid:
        raise ValueError(
            f"Invalid WRF MPI decomposition {nproc_x}x{nproc_y}; "
            f"minimum patch dimension is {minimum_patch_cells}: {'; '.join(invalid)}"
        )


def patch_namelist_input(path: Path, start_date_str: str, end_date_str: str, domain: BalearicDomain) -> None:
    validate_domain_topology(domain)
    nproc_x, nproc_y = domain.mpi_layout
    validate_mpi_decomposition(domain, nproc_x=nproc_x, nproc_y=nproc_y)
    try:
        from datetime import datetime

        start_datetime = datetime.strptime(start_date_str, "%Y-%m-%d_%H:%M:%S")
        end_datetime = datetime.strptime(end_date_str, "%Y-%m-%d_%H:%M:%S")
        duration_seconds = int((end_datetime - start_datetime).total_seconds())
        if duration_seconds <= 0:
            raise ValueError("end date must be later than start date")

        run_hours, remainder = divmod(duration_seconds, 60 * 60)
        run_minutes, run_seconds = divmod(remainder, 60)

        parts_start = start_date_str.split("_")
        date_start = parts_start[0].split("-")
        time_start = parts_start[1].split(":")
        
        parts_end = end_date_str.split("_")
        date_end = parts_end[0].split("-")
        time_end = parts_end[1].split(":")
        
        s_yr, s_mo, s_dy = date_start[0], date_start[1], date_start[2]
        s_hr = time_start[0]
        
        e_yr, e_mo, e_dy = date_end[0], date_end[1], date_end[2]
        e_hr = time_end[0]
    except Exception as e:
        print(f"Error parsing dates for namelist.input patch: {e}")
        return

    if not path.exists():
        print(f"Warning: {path} does not exist. Cannot patch.")
        return
        
    content = path.read_text()
    
    import re
    count = domain.max_dom

    def repeated(value: object) -> str:
        return ", ".join(str(value) for _ in range(count))

    e_we = ", ".join(str(grid[0]) for grid in domain.grids)
    e_sn = ", ".join(str(grid[1]) for grid in domain.grids)
    dx = (domain.d01_dx_m, domain.d01_dx_m // 3) + (domain.regional_dx_m,) * 5
    dy = (domain.d01_dy_m, domain.d01_dy_m // 3) + (domain.regional_dx_m,) * 5
    parent_ids = (0, 1, 2, 2, 2, 2, 2)[:count]
    starts_i = (1, domain.d02_i_parent_start, domain.d03_i_parent_start, domain.d04_i_parent_start, domain.d05_i_parent_start, domain.d06_i_parent_start, domain.d07_i_parent_start)[:count]
    starts_j = (1, domain.d02_j_parent_start, domain.d03_j_parent_start, domain.d04_j_parent_start, domain.d05_j_parent_start, domain.d06_j_parent_start, domain.d07_j_parent_start)[:count]
    replacements = {
        # Time control
        # Derive the WRF duration from the same start/end timestamps used by
        # WPS. This removes the possibility of a stale template run_hours
        # extending WRF beyond the boundary-condition coverage.
        r"(\brun_days\s*=)[^!\n/]+": f"\\1 0,",
        r"(\brun_hours\s*=)[^!\n/]+": f"\\1 {run_hours},",
        r"(\brun_minutes\s*=)[^!\n/]+": f"\\1 {run_minutes},",
        r"(\brun_seconds\s*=)[^!\n/]+": f"\\1 {run_seconds},",
        r"(\bstart_year\s*=)[^!\n/]+": f"\\1 {repeated(s_yr)},",
        r"(\bstart_month\s*=)[^!\n/]+": f"\\1 {repeated(s_mo)},",
        r"(\bstart_day\s*=)[^!\n/]+": f"\\1 {repeated(s_dy)},",
        r"(\bstart_hour\s*=)[^!\n/]+": f"\\1 {repeated(s_hr)},",
        r"(\bend_year\s*=)[^!\n/]+": f"\\1 {repeated(e_yr)},",
        r"(\bend_month\s*=)[^!\n/]+": f"\\1 {repeated(e_mo)},",
        r"(\bend_day\s*=)[^!\n/]+": f"\\1 {repeated(e_dy)},",
        r"(\bend_hour\s*=)[^!\n/]+": f"\\1 {repeated(e_hr)},",
        r"(\bhistory_interval\s*=)[^!\n/]+": f"\\1 {repeated(60)},",
        r"(\bframes_per_outfile\s*=)[^!\n/]+": f"\\1 {repeated(1)},",
        r"(\binput_from_file\s*=)[^!\n/]+": f"\\1 {repeated('.true.')},",
        # WRF recommends no more than roughly 6 seconds per kilometre for the
        # parent domain. 45 seconds leaves margin for the 9 km grid and divides
        # cleanly through the 3:1 nested-domain time-step ratios.
        r"(\btime_step\s*=)[^!\n/]+": f"\\1 45,",
        r"(\btime_step_fract_num\s*=)[^!\n/]+": f"\\1 0,",
        r"(\btime_step_fract_den\s*=)[^!\n/]+": f"\\1 1,",
        
        # Domains
        r"(\bmax_dom\s*=)[^!\n/]+": f"\\1 {count},",
        r"(\be_we\s*=)[^!\n/]+": f"\\1 {e_we},",
        r"(\be_sn\s*=)[^!\n/]+": f"\\1 {e_sn},",
        r"(\be_vert\s*=)[^!\n/]+": f"\\1 {repeated(45)},",
        r"(\bnum_metgrid_levels\s*=)[^!\n/]+": f"\\1 13,",
        r"(\bnum_metgrid_soil_levels\s*=)[^!\n/]+": f"\\1 4,",
        r"(\bdx\s*=)[^!\n/]+": f"\\1 {_values(dx[:count])},",
        r"(\bdy\s*=)[^!\n/]+": f"\\1 {_values(dy[:count])},",
        r"(\bgrid_id\s*=)[^!\n/]+": f"\\1 {_values(tuple(range(1, count + 1)))},",
        r"(\bparent_id\s*=)[^!\n/]+": f"\\1 {_values(parent_ids)},",
        r"(\bi_parent_start\s*=)[^!\n/]+": f"\\1 {_values(starts_i)},",
        r"(\bj_parent_start\s*=)[^!\n/]+": f"\\1 {_values(starts_j)},",
        r"(\bparent_grid_ratio\s*=)[^!\n/]+": f"\\1 {_values(domain.parent_grid_ratios)},",
        r"(\bparent_time_step_ratio\s*=)[^!\n/]+": f"\\1 {_values(domain.parent_grid_ratios)},",
        r"(\bnproc_x\s*=)[^!\n/]+": f"\\1 {nproc_x},",
        r"(\bnproc_y\s*=)[^!\n/]+": f"\\1 {nproc_y},",
        
        # Physics arrays
        r"(\bmp_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bcu_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bra_lw_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bra_sw_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bbl_pbl_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bsf_sfclay_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bsf_surface_physics\s*=)[^!\n/]+": f"\\1 {repeated(-1)},",
        r"(\bradt\s*=)[^!\n/]+": f"\\1 {repeated(15)},",
        r"(\bbldt\s*=)[^!\n/]+": f"\\1 {repeated(0)},",
        r"(\bcudt\s*=)[^!\n/]+": f"\\1 {repeated(0)},",
        r"(\bsf_urban_physics\s*=)[^!\n/]+": f"\\1 {repeated(0)},",
        
        # Dynamics arrays
        r"(\bzdamp\s*=)[^!\n/]+": f"\\1 {repeated('5000.')},",
        r"(\bdampcoef\s*=)[^!\n/]+": f"\\1 {repeated(0.2)},",
        r"(\bkhdif\s*=)[^!\n/]+": f"\\1 {repeated(0)},",
        r"(\bkvdif\s*=)[^!\n/]+": f"\\1 {repeated(0)},",
        r"(\bnon_hydrostatic\s*=)[^!\n/]+": f"\\1 {repeated('.true.')},",
        r"(\bmoist_adv_opt\s*=)[^!\n/]+": f"\\1 {repeated(1)},",
        r"(\bscalar_adv_opt\s*=)[^!\n/]+": f"\\1 {repeated(1)},",
        r"(\bgwd_opt\s*=)[^!\n/]+": f"\\1 1{', 0' * (count - 1)},",
    }
    
    new_content = content
    for pattern, replacement in replacements.items():
        new_content = re.sub(pattern, replacement, new_content, flags=re.IGNORECASE)

    domains_match = re.search(r"(?ms)^\s*&domains\b.*?^\s*/", new_content)
    if domains_match:
        domains_block = domains_match.group(0)
        additions = []
        if not re.search(r"(?m)^\s*max_dom\s*=", domains_block):
            additions.append(f" max_dom = {count},")
        if not re.search(r"(?m)^\s*nproc_x\s*=", domains_block):
            additions.append(f" nproc_x = {nproc_x},")
        if not re.search(r"(?m)^\s*nproc_y\s*=", domains_block):
            additions.append(f" nproc_y = {nproc_y},")
        if additions:
            patched_block = domains_block.rsplit("/", 1)[0] + "\n" + "\n".join(additions) + "\n/"
            new_content = new_content[:domains_match.start()] + patched_block + new_content[domains_match.end():]
        
    path.write_text(new_content)
    print(f"Successfully patched {path} for domain starting {start_date_str}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a WPS namelist for the Balearic Sea nest.")
    parser.add_argument("--output", type=Path, default=Path("simulation/namelist.wps"))
    parser.add_argument("--start-date", default=BalearicDomain.start_date)
    parser.add_argument("--end-date", default=BalearicDomain.end_date)
    parser.add_argument("--geog-data-path", default=BalearicDomain.geog_data_path)
    parser.add_argument("--forcing-prefix", default=BalearicDomain.forcing_prefix)
    parser.add_argument(
        "--resolution-profile",
        choices=("operational-3km", "ultra-1km"),
        default="operational-3km",
        help="Regional nest resolution profile (default: fast operational 3 km).",
    )
    parser.add_argument("--patch-namelist-input", type=Path, help="Path to namelist.input to dynamically patch run dates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    domain_factory = BalearicDomain.ultra_1km if args.resolution_profile == "ultra-1km" else BalearicDomain
    domain = domain_factory(
        start_date=args.start_date,
        end_date=args.end_date,
        geog_data_path=args.geog_data_path,
        forcing_prefix=args.forcing_prefix,
    )
    output = write_namelist(args.output, domain)
    print(output)
    if args.patch_namelist_input:
        patch_namelist_input(args.patch_namelist_input, args.start_date, args.end_date, domain)


if __name__ == "__main__":
    main()
