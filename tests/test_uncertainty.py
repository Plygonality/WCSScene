"""Jacobian propagation and the refusal to invent zero errors."""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from wcsscene.projection import build_basis
from wcsscene.synthetic import make_tan_wcs
from wcsscene.uncertainty import propagate_source
from wcsscene.wcs_adapter import reference_pixel


def _record(**overrides):
    record = {
        "placed": True,
        "pixel_xy_input": [15.5, 15.5],
        "pixel_xy_from_sky": None,
        "sky_input_deg": [0.0, 0.0],
        "sky_from_pixel_deg": [0.0, 0.0],
        "scene_xyz": [0.0, 0.0, 0.0],
        "errors": {},
        "uncertainty_status": None,
        "uncertainty": None,
    }
    record.update(overrides)
    return record


def test_missing_errors_are_unknown_not_zero():
    record = _record()
    propagate_source(
        record,
        wcs=None,
        basis=None,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_uncertainty=False,
        sky_uncertainty_convention=None,
        pixel_preview=False,
    )
    assert record["uncertainty_status"] == "UNKNOWN"
    assert record["uncertainty"] is None


def test_sky_errors_without_convention_are_ambiguous():
    record = _record(errors={"ra_err": 1.0, "dec_err": 1.0, "ra_dec_corr": 0.0})
    propagate_source(
        record,
        wcs=None,
        basis=build_basis(SkyCoord(0 * u.deg, 0 * u.deg)),
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_uncertainty=False,
        sky_uncertainty_convention=None,
        pixel_preview=False,
    )
    assert record["uncertainty_status"] == "AMBIGUOUS_CONVENTION"
    assert record["uncertainty"]["reason"]


def test_ra_cosdec_jacobian_at_tangent_point():
    basis = build_basis(SkyCoord(0 * u.deg, 0 * u.deg, frame="icrs"))
    record = _record(
        errors={"ra_err": 2.0, "dec_err": 1.0, "ra_dec_corr": 0.5},
        sky_input_deg=[0.0, 0.0],
    )
    propagate_source(
        record,
        wcs=None,
        basis=basis,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_uncertainty=False,
        sky_uncertainty_convention="ra_cosdec_arcsec",
        pixel_preview=False,
    )
    assert record["uncertainty_status"] == "PROPAGATED"
    cov = np.array(record["uncertainty"]["covariance_scene"]).reshape(2, 2)
    expected = np.array([[4.0, 1.0], [1.0, 1.0]])
    assert cov == pytest.approx(expected, abs=1e-4)
    assert record["uncertainty"]["semi_major_arcsec"] > record["uncertainty"]["semi_minor_arcsec"]


def test_pixel_covariance_matches_linear_scale():
    wcs = make_tan_wcs(
        nx=32, ny=32, crval=(0.0, 0.0), scale_arcsec=2.0, rotation_deg=0.0, mirror=True
    )
    ref_x, ref_y, _ = reference_pixel(wcs, (32, 32))
    basis = build_basis(wcs.pixel_to_world(ref_x, ref_y))
    record = _record(
        pixel_xy_input=[ref_x, ref_y],
        errors={"x_err": 0.5, "y_err": 0.4, "xy_corr": 0.25},
    )
    propagate_source(
        record,
        wcs=wcs,
        basis=basis,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_uncertainty=True,
        sky_uncertainty_convention=None,
        pixel_preview=False,
    )
    assert record["uncertainty_status"] == "PROPAGATED"
    jac = np.array(record["uncertainty"]["jacobian_scene_per_pixel"]).reshape(2, 2)
    assert jac == pytest.approx(np.diag([2.0, 2.0]), abs=1e-5)
    cov_pixel = np.array([[0.25, 0.05], [0.05, 0.16]])
    cov_scene = jac @ cov_pixel @ jac.T
    got = np.array(record["uncertainty"]["covariance_scene"]).reshape(2, 2)
    assert got == pytest.approx(cov_scene, abs=1e-6)
