from pathlib import Path

from simulation.setup_domain import (
    BalearicDomain,
    patch_namelist_input,
    render_namelist,
    validate_domain_topology,
    validate_mpi_decomposition,
)


def test_render_namelist_defaults_to_two_domain_operational_profile():
    namelist = render_namelist(BalearicDomain())

    assert "max_dom = 2" in namelist
    assert "parent_id = 1, 1" in namelist
    assert "parent_grid_ratio = 1, 3" in namelist
    assert "dx = 9000" in namelist
    assert "dy = 9000" in namelist
    assert "ref_lat = 40.0000" in namelist
    assert "ref_lon = 5.0000" in namelist
    assert "stand_lon = 5.0000" in namelist
    assert "geog_data_res = 'modis_landuse_20class_30s_with_lakes+default', 'modis_landuse_20class_30s_with_lakes+default'" in namelist
    assert "i_parent_start = 1, 65" in namelist
    assert "j_parent_start = 1, 30" in namelist
    assert "e_we = 210, 277" in namelist
    assert "e_sn = 140, 271" in namelist
    assert "ordered_by_date = .true." in namelist


def test_render_namelist_preserves_selectable_one_km_profile():
    namelist = render_namelist(BalearicDomain.ultra_1km())

    assert "parent_grid_ratio = 1, 3, 3, 3, 3, 3, 3" in namelist
    assert "max_dom = 7" in namelist
    assert "e_we = 210, 277, 151, 301, 151, 151, 253" in namelist
    assert "e_sn = 140, 271, 151, 100, 400, 202, 301" in namelist



def test_render_namelist_allows_dates_and_geog_path_override():
    namelist = render_namelist(
        BalearicDomain(
            start_date="2026-05-04_00:00:00",
            end_date="2026-05-05_00:00:00",
            geog_data_path="/opt/wps_geog",
        )
    )

    assert (
        "start_date = '2026-05-04_00:00:00', '2026-05-04_00:00:00'"
        in namelist
    )
    assert (
        "end_date = '2026-05-05_00:00:00', '2026-05-05_00:00:00'"
        in namelist
    )
    assert "geog_data_path = '/opt/wps_geog'" in namelist


def test_patch_namelist_input_uses_stable_nested_time_step(tmp_path):
    namelist_input = tmp_path / "namelist.input"
    namelist_input.write_text(
        """&time_control
 run_days = 0,
 run_hours = 36,
 run_minutes = 15,
 run_seconds = 30,
 start_year = 2000,
/
&domains
 time_step = 90,
 time_step_fract_num = 1,
 time_step_fract_den = 2,
 dx = 9000,
 parent_time_step_ratio = 1,
/
"""
    )

    patch_namelist_input(
        namelist_input,
        "2026-07-15_00:00:00",
        "2026-07-16_00:00:00",
        BalearicDomain(),
    )

    patched = namelist_input.read_text()
    assert "run_days = 0," in patched
    assert "run_hours = 24," in patched
    assert "run_minutes = 0," in patched
    assert "run_seconds = 0," in patched
    assert "time_step = 45," in patched
    assert "time_step_fract_num = 0," in patched
    assert "time_step_fract_den = 1," in patched
    assert "max_dom = 2," in patched
    assert "parent_time_step_ratio = 1, 3," in patched
    assert "dx = 9000, 3000," in patched
    assert "nproc_x = 8," in patched
    assert "nproc_y = 8," in patched


def test_patch_namelist_input_derives_non_day_duration_from_dates(tmp_path):
    namelist_input = tmp_path / "namelist.input"
    namelist_input.write_text(
        """&time_control
 run_days = 5,
 run_hours = 0,
 run_minutes = 0,
 run_seconds = 0,
/
&domains
/
"""
    )

    patch_namelist_input(
        namelist_input,
        "2026-07-15_00:00:00",
        "2026-07-16_06:30:15",
        BalearicDomain(),
    )

    patched = namelist_input.read_text()
    assert "run_days = 0," in patched
    assert "run_hours = 30," in patched
    assert "run_minutes = 30," in patched
    assert "run_seconds = 15," in patched


def test_operational_profile_accepts_sixty_four_rank_decomposition():
    validate_mpi_decomposition(BalearicDomain(), nproc_x=8, nproc_y=8)


def test_ultra_profile_accepts_its_twelve_rank_decomposition():
    validate_mpi_decomposition(BalearicDomain.ultra_1km(), nproc_x=4, nproc_y=3)


def test_preflight_rejects_same_resolution_child_domains():
    import pytest

    with pytest.raises(ValueError, match="parent_grid_ratio >= 3"):
        validate_domain_topology(BalearicDomain(max_dom=3))


def test_phase2_files_capture_wrf_wps_pipeline_contract():
    dockerfile = Path("simulation/Dockerfile").read_text()
    pipeline = Path("simulation/run_pipeline.sh").read_text()

    assert "FROM debian:bullseye AS wrf-builder" in dockerfile
    assert "FROM debian:bullseye-slim AS wrf-runtime" in dockerfile
    assert "WRF_VERSION=4.5" in dockerfile
    assert "WPS_VERSION=4.5" in dockerfile
    assert "gfortran" in dockerfile
    assert "libnetcdf-dev" in dockerfile
    assert "libnetcdff-dev" in dockerfile
    assert "libnetcdf15" not in dockerfile
    assert "netcdf-bin" in dockerfile
    assert "libeccodes-tools" in dockerfile
    assert "libjasper-dev" not in dockerfile
    assert "jasper-software/jasper" in dockerfile
    assert "CMAKE_INSTALL_PREFIX=/usr/local" in dockerfile
    assert "linux/amd64" in dockerfile
    assert "mpirun" in dockerfile
    assert "test -x run/wrf.exe" in dockerfile
    assert "test -x geogrid.exe" in dockerfile
    assert "COPY --from=wrf-builder /opt/WRF/run/wrf.exe" in dockerfile
    assert "COPY --from=wrf-builder /opt/WPS/geogrid.exe" in dockerfile

    assert "link_grib.csh" in pipeline
    assert "run_wps_stage ungrib" in pipeline
    assert "run_wps_stage metgrid" in pipeline
    assert 'cat "${GRIB_DIR}"/ecmwf_*.grib2 > "${COMBINED_GRIB}"' in pipeline
    assert 'ecmwf_[validityDate]_[validityTime].grib2' in pipeline
    assert "sort -zV" in pipeline
    assert './link_grib.csh "${WPS_GRIB_FILES[@]}"' in pipeline
    assert "one hdate from the first message in each GRIBFILE" in pipeline
    assert "timeout --signal=TERM --kill-after=30s" in pipeline
    assert "ungrib created the complete WPS intermediate time sequence" in pipeline
    assert 'date -u -d "@${expected_epoch}"' in pipeline
    assert "expected_epoch=$((expected_epoch + 3 * 60 * 60))" in pipeline
    assert ' ${expected_time:11:8} +3 hours' not in pipeline
    assert pipeline.index("run_wps_stage ungrib") < pipeline.index("missing_intermediate_times=()")
    assert pipeline.index("missing_intermediate_times=()") < pipeline.index("run_wps_stage metgrid")
    assert '"${exe}" > "${stdout_log}" 2>&1' in pipeline
    assert 'PREDSEA_BIN="${PREDSEA_BIN:-/opt/predsea/bin}"' in pipeline
    assert '"${PREDSEA_BIN}/real.exe"' in pipeline
    assert '"${PREDSEA_BIN}/wrf.exe"' in pipeline
    assert 'MPI_PROCS="${MPI_PROCS:-64}"' in pipeline
    assert 'MPI_NPROC_X="${MPI_NPROC_X:-8}"' in pipeline
    assert 'MPI_NPROC_Y="${MPI_NPROC_Y:-8}"' in pipeline
    assert "OMP_NUM_THREADS=1" in pipeline

    startup = Path("scripts/vm_startup.sh").read_text()
    assert 'MPI_PROCS="${PREDSEA_WRF_MPI_PROCS:-64}"' in startup
    assert 'MPI_NPROC_X="${PREDSEA_WRF_MPI_NPROC_X:-8}"' in startup
    assert 'MPI_NPROC_Y="${PREDSEA_WRF_MPI_NPROC_Y:-8}"' in startup
