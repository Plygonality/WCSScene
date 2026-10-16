"""Gnomonic east/north plane, including wrap and the pole."""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from wcsscene.errors import TangentAtPole
from wcsscene.projection import (
    ARCSEC_PER_RADIAN,
    build_basis,
    scene_to_tangent,
    sky_to_scene,
    tangent_to_sky,
)


def test_equator_basis_is_right_handed():
    basis = build_basis(SkyCoord(0 * u.deg, 0 * u.deg))
    assert np.allclose(basis.radial, [1, 0, 0])
    assert np.allclose(basis.east, [0, 1, 0])
    assert np.allclose(basis.north, [0, 0, 1])
    assert np.allclose(np.cross(basis.east, basis.north), basis.radial)


def test_gnomonic_east_is_not_the_small_angle_ra_difference():
    basis = build_basis(SkyCoord(0 * u.deg, 0 * u.deg))
    point = SkyCoord(30 * u.deg, 0 * u.deg)
    scene, valid = sky_to_scene(point, basis, 1.0)
    expected = np.tan(np.deg2rad(30.0)) * ARCSEC_PER_RADIAN
    assert bool(valid[0])
    assert scene[0, 0] == pytest.approx(expected, abs=1e-6)
    assert scene[0, 1] == pytest.approx(0.0, abs=1e-6)
    assert abs(expected - 30.0 * 3600.0) > 1000.0


def test_directional_offsets_match_east_north():
    origin = SkyCoord(150 * u.deg, -20 * u.deg)
    basis = build_basis(origin)
    east = origin.directional_offset_by(90 * u.deg, 30 * u.arcsec)
    north = origin.directional_offset_by(0 * u.deg, 30 * u.arcsec)
    scene_e, _ = sky_to_scene(east, basis, 1.0)
    scene_n, _ = sky_to_scene(north, basis, 1.0)
    assert scene_e[0, 0] == pytest.approx(30.0, abs=1e-4)
    assert scene_e[0, 1] == pytest.approx(0.0, abs=1e-3)
    assert scene_n[0, 1] == pytest.approx(30.0, abs=1e-4)
    assert scene_n[0, 0] == pytest.approx(0.0, abs=1e-3)


def test_inverse_and_ra_seam():
    basis = build_basis(SkyCoord(0 * u.deg, 5 * u.deg))
    west = SkyCoord(359.999 * u.deg, 5 * u.deg)
    east = SkyCoord(0.001 * u.deg, 5 * u.deg)
    scene_w, valid_w = sky_to_scene(west, basis, 1.0)
    scene_e, valid_e = sky_to_scene(east, basis, 1.0)
    assert bool(valid_w[0] and valid_e[0])
    assert scene_w[0, 0] < 0 < scene_e[0, 0]
    separation = scene_e[0, 0] - scene_w[0, 0]
    expected = 0.002 * np.cos(np.deg2rad(5.0)) * 3600.0
    assert separation == pytest.approx(expected, rel=1e-4)
    east_rad, north_rad = scene_to_tangent(scene_e, 1.0)
    recovered = tangent_to_sky(east_rad, north_rad, basis)
    assert float(east.separation(recovered).arcsec) < 1e-6


def test_pole_is_rejected_and_near_pole_is_finite():
    with pytest.raises(TangentAtPole):
        build_basis(SkyCoord(0 * u.deg, 90 * u.deg))
    basis = build_basis(SkyCoord(12 * u.deg, 89.5 * u.deg))
    nearby = SkyCoord(12.01 * u.deg, 89.5 * u.deg)
    scene, valid = sky_to_scene(nearby, basis, 1.0)
    assert bool(valid[0])
    assert np.all(np.isfinite(scene))


def test_opposite_hemisphere_is_undefined():
    basis = build_basis(SkyCoord(10 * u.deg, 0 * u.deg))
    opposite = SkyCoord(190 * u.deg, 0 * u.deg)
    scene, valid = sky_to_scene(opposite, basis, 1.0)
    assert not bool(valid[0])
    assert not np.isfinite(scene[0, 0])


def test_east_left_flip_is_explicit():
    basis = build_basis(SkyCoord(0 * u.deg, 0 * u.deg))
    point = SkyCoord(0.01 * u.deg, 0 * u.deg)
    plain, _ = sky_to_scene(point, basis, 1.0, flip_east_left=False)
    flipped, _ = sky_to_scene(point, basis, 1.0, flip_east_left=True)
    assert plain[0, 0] > 0
    assert flipped[0, 0] == pytest.approx(-plain[0, 0])
