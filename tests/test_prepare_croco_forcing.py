from __future__ import annotations

import numpy as np
from pathlib import Path

from scripts.prepare_croco_forcing import (
    croco_climatology_times,
    croco_depths,
    croco_s_coordinates,
    depth_average_velocity,
    verify_transport_consistency,
)


def test_verify_transport_consistency_passes_matching_and_fails_mismatch():
    u_3d = np.array([[[1.0]], [[3.0]]])
    v_3d = np.array([[[2.0]], [[4.0]]])
    z_w = np.array([[[-10.0]], [[-9.0]], [[0.0]]])

    ubar = depth_average_velocity(u_3d, z_w)
    vbar = depth_average_velocity(v_3d, z_w)

    # Should pass when ubar/vbar match
    verify_transport_consistency(u_3d, v_3d, ubar, vbar, z_w, z_w, tolerance=1e-4)

    # Should fail when ubar is modified beyond tolerance
    bad_ubar = ubar + 0.01
    try:
        verify_transport_consistency(u_3d, v_3d, bad_ubar, vbar, z_w, z_w, tolerance=1e-4)
    except ValueError as exc:
        assert "Barotropic transport mismatch" in str(exc)
    else:
        raise AssertionError("Inconsistent transport must raise ValueError")



def test_new_s_coordinate_matches_pinned_croco_213_reference_values():
    s_rho, s_w, cs_r, cs_w = croco_s_coordinates(30, theta_s=6.0, theta_b=0.0)

    np.testing.assert_allclose(s_rho[[0, -1]], [-29.5 / 30.0, -0.5 / 30.0])
    np.testing.assert_allclose(s_w[[0, -1]], [-1.0, 0.0])
    np.testing.assert_allclose(cs_w[[0, -1]], [-1.0, 0.0])
    expected_cs_r = (1.0 - np.cosh(6.0 * s_rho)) / (np.cosh(6.0) - 1.0)
    np.testing.assert_allclose(cs_r, expected_cs_r)


def test_new_s_coordinate_depths_are_stretched_and_bound_the_water_column():
    s_rho, s_w, cs_r, cs_w = croco_s_coordinates(30, 6.0, 0.0)
    h = np.array([[1000.0]])
    zeta = np.array([[0.25]])

    z_rho = croco_depths(h, zeta, s_rho, cs_r, hc_m=10.0)
    z_w = croco_depths(h, zeta, s_w, cs_w, hc_m=10.0)

    np.testing.assert_allclose(z_w[0, 0, 0], -1000.0)
    np.testing.assert_allclose(z_w[-1, 0, 0], 0.25)
    assert np.all(np.diff(z_w[:, 0, 0]) > 0.0)
    assert not np.allclose(z_rho[:, 0, 0], s_rho * h.item())


def test_new_s_coordinate_depths_match_shallow_water_runtime_formula():
    s_rho, s_w, cs_r, cs_w = croco_s_coordinates(30, 6.0, 0.0)
    h = np.array([[10.0]])
    zeta = np.array([[0.2]])

    z_w = croco_depths(h, zeta, s_w, cs_w, hc_m=10.0)
    k = 1
    z0 = 10.0 * s_w[k] + cs_w[k] * h.item()
    expected = z0 * h.item() / 20.0 + zeta.item() * (1.0 + z0 / 20.0)

    np.testing.assert_allclose(z_w[k, 0, 0], expected)
    assert np.all(np.diff(z_w[:, 0, 0]) > 0.0)


def test_barotropic_velocity_is_thickness_weighted_not_level_mean():
    velocity = np.array([[[1.0]], [[3.0]]])
    z_w = np.array([[[-10.0]], [[-9.0]], [[0.0]]])

    result = depth_average_velocity(velocity, z_w)

    np.testing.assert_allclose(result, [[2.8]])
    assert result.item() != velocity.mean()


def test_forcing_generator_uses_staggered_bathymetry_and_no_unweighted_mean():
    source = Path("scripts/prepare_croco_forcing.py").read_text()

    assert "h_u = 0.5 * (h[:, :-1] + h[:, 1:])" in source
    assert "h_v = 0.5 * (h[:-1, :] + h[1:, :])" in source
    assert "u_clm.mean(axis=1)" not in source
    assert "v_clm.mean(axis=1)" not in source
    assert 'default=4' in source
    assert "min(args.workers, multiprocessing.cpu_count())" in source


def test_climatology_uses_croco_ssh_variable_contract():
    source = Path("scripts/prepare_croco_forcing.py").read_text()

    assert '"SSH": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm_pad)' in source
    assert '"zeta": (("ssh_time", "eta_rho", "xi_rho"), zeta_clm_pad)' not in source


def test_writes_all_explicit_open_boundary_fields():
    source = Path("scripts/prepare_croco_forcing.py").read_text()

    for side in ("west", "east", "south", "north"):
        for field in ("zeta", "ubar", "vbar", "u", "v", "temp", "salt"):
            assert f'f"{field}_{{side}}"' in source
    assert 'args.output_dir / "croco_bry.nc"' in source


def test_binary_and_namelist_enable_explicit_boundary_forcing():
    patcher = Path("simulation/marine/croco/patch_croco_source.py").read_text()
    namelist = Path("simulation/marine/croco/croco.in.balearic").read_text()

    for define in ("FRC_BRY", "Z_FRC_BRY", "M2_FRC_BRY", "M3_FRC_BRY", "T_FRC_BRY"):
        assert f"# define {define}" in patcher
    assert "croco_bry.nc" in namelist


def test_builds_named_elapsed_day_axes_required_by_croco():
    source = np.array(
        ["2026-07-16T00:00:00", "2026-07-16T01:00:00", "2026-07-16T06:00:00"],
        dtype="datetime64[s]",
    )

    axes = croco_climatology_times(source)

    assert set(axes) == {"ssh_time", "uclm_time", "tclm_time", "sclm_time"}
    for name, (dimension, values) in axes.items():
        assert dimension == name
        np.testing.assert_allclose(values, [0.0, 1.0 / 24.0, 0.25])


def test_rejects_non_increasing_climatology_time():
    source = np.array(
        ["2026-07-16T00:00:00", "2026-07-16T00:00:00"], dtype="datetime64[s]"
    )

    try:
        croco_climatology_times(source)
    except ValueError as exc:
        assert "increasing" in str(exc)
    else:
        raise AssertionError("duplicate CROCO forcing timestamps must be rejected")


def test_padding_preserves_3d_rank_for_barotropic_velocities():
    source = Path("scripts/prepare_croco_forcing.py").read_text()

    assert 'ubar_clm_pad = np.pad(ubar_clm, ((0, 1), (0, 0), (0, 0)), mode="edge")' in source
    assert 'vbar_clm_pad = np.pad(vbar_clm, ((0, 1), (0, 0), (0, 0)), mode="edge")' in source

