"""Pixel convention, round trip, frames, and SIP distortion."""

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from wcsscene.errors import UnsupportedWCS
from wcsscene.exchange import PrepareConfig, prepare
from wcsscene.projection import build_basis, sky_to_scene
from wcsscene.synthetic import make_tan_wcs, write_sip_fits
from wcsscene.wcs_adapter import (
    describe_distortion,
    reference_pixel,
    require_celestial_wcs,
    roundtrip_samples,
)


def _tan(**kwargs) -> WCS:
    wcs = make_tan_wcs(**kwargs)
    require_celestial_wcs(wcs)
    return wcs


def test_crpix_is_one_based_and_pixel_api_is_zero_based():
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.cunit = ["deg", "deg"]
    wcs.wcs.radesys = "ICRS"
    wcs.wcs.crpix = [1.0, 1.0]
    wcs.wcs.crval = [10.0, 20.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    sky = wcs.pixel_to_world(0.0, 0.0)
    assert sky.ra.deg == pytest.approx(10.0, abs=1e-10)
    assert sky.dec.deg == pytest.approx(20.0, abs=1e-10)
    mistaken = wcs.pixel_to_world(1.0, 1.0)
    assert mistaken.separation(sky).arcsec > 0.5
    x_ref, y_ref, source = reference_pixel(wcs, (8, 8))
    assert (x_ref, y_ref, source) == (0.0, 0.0, "fits_crpix_minus_one")


def test_roundtrip_samples_on_rotated_tan():
    wcs = _tan(nx=96, ny=80, rotation_deg=25.0)
    samples = [(0, 0, "corner"), (95, 0, "corner"), (47.5, 39.5, "center"), (10.2, 70.4, "random")]
    report = roundtrip_samples(wcs, samples)
    assert report["n_failed"] == 0
    assert report["max_pixel_error"] < 1e-6
    assert report["max_angular_error_arcsec"] < 1e-6


def test_pixel_axis_direction_does_not_define_east():
    wcs = _tan(nx=32, ny=32, crval=(0.0, 0.0), rotation_deg=0.0, mirror=False, scale_arcsec=1.0)
    ref = 15.5
    basis = build_basis(wcs.pixel_to_world(ref, ref))
    toward_east = wcs.pixel_to_world(ref - 1, ref)
    toward_west = wcs.pixel_to_world(ref + 1, ref)
    toward_north = wcs.pixel_to_world(ref, ref + 1)
    scene_e, _ = sky_to_scene(toward_east, basis, 1.0)
    scene_w, _ = sky_to_scene(toward_west, basis, 1.0)
    scene_n, _ = sky_to_scene(toward_north, basis, 1.0)
    assert scene_e[0, 0] > 0 > scene_w[0, 0]
    assert scene_n[0, 1] > 0
    assert abs(float(scene_e[0, 1])) < abs(float(scene_e[0, 0])) * 1e-6


def test_mirrored_cd_still_puts_east_on_positive_x():
    wcs = _tan(nx=32, ny=32, crval=(40.0, 10.0), rotation_deg=15.0, mirror=True, scale_arcsec=1.0)
    ref_x, ref_y, _ = reference_pixel(wcs, (32, 32))
    basis = build_basis(wcs.pixel_to_world(ref_x, ref_y))
    from astropy import units as u

    east = basis.sky.directional_offset_by(90 * u.deg, 2 * u.arcsec)
    scene, valid = sky_to_scene(east, basis, 1.0)
    assert bool(valid[0])
    assert scene[0, 0] > 0


def test_galactic_frame_is_not_labelled_celestial_east():
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
    wcs.wcs.cunit = ["deg", "deg"]
    wcs.wcs.crpix = [5.0, 6.0]
    wcs.wcs.crval = [30.0, 10.0]
    wcs.wcs.cdelt = [-0.01, 0.01]
    sky = require_celestial_wcs(wcs)
    assert sky.frame.name == "galactic"
    info = build_basis(wcs.pixel_to_world(4.0, 5.0)).as_dict()
    assert info["celestial_east_north"] is False
    assert info["x_axis"] == "galactic_longitude_increasing"


def test_fk5_is_not_relabelled_icrs():
    wcs = _tan(nx=16, ny=16, crval=(10.0, -5.0), rotation_deg=0.0)
    wcs.wcs.radesys = "FK5"
    wcs.wcs.equinox = 2000.0
    sky = wcs.pixel_to_world(*reference_pixel(wcs, (16, 16))[:2])
    assert sky.frame.name == "fk5"


def test_multidimensional_wcs_is_rejected():
    header = fits.Header()
    header["WCSAXES"] = 3
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CTYPE3"] = "FREQ"
    header["CRPIX1"] = 1
    header["CRPIX2"] = 1
    header["CRPIX3"] = 1
    header["CRVAL1"] = 10
    header["CRVAL2"] = 20
    header["CRVAL3"] = 1e9
    header["CDELT1"] = -0.001
    header["CDELT2"] = 0.001
    header["CDELT3"] = 1e6
    header["CUNIT1"] = "deg"
    header["CUNIT2"] = "deg"
    header["CUNIT3"] = "Hz"
    wcs = WCS(header)
    with pytest.raises(UnsupportedWCS, match="dropping axes"):
        require_celestial_wcs(wcs)


def test_sip_changes_the_interior_and_undersampled_mesh_fails(tmp_path):
    path = tmp_path / "sip.fits"
    write_sip_fits(path)
    with fits.open(path) as hdul:
        distorted = WCS(hdul[0].header)
        plain_header = hdul[0].header.copy()
    assert describe_distortion(distorted)["present"] is True
    for key in list(plain_header):
        if key.startswith(("A_", "B_", "AP_", "BP_")):
            del plain_header[key]
    plain_header["CTYPE1"] = "RA---TAN"
    plain_header["CTYPE2"] = "DEC--TAN"
    plain = WCS(plain_header)
    separation = distorted.pixel_to_world(8, 32).separation(plain.pixel_to_world(8, 32)).arcsec
    assert separation > 0.05
    coarse = prepare(path, tmp_path / "coarse", PrepareConfig(mesh_cells=1, hdu=0))
    assert coarse.exit_code == 4
    assert any(item["code"] == "MESH_RESIDUAL" for item in coarse.warnings)
    fine = prepare(path, tmp_path / "fine", PrepareConfig(mesh_cells=48, hdu=0))
    assert fine.exit_code == 0
    import json

    coarse_manifest = json.loads((tmp_path / "coarse" / "manifest.json").read_text())
    fine_manifest = json.loads((tmp_path / "fine" / "manifest.json").read_text())
    assert coarse_manifest["mesh"]["approximation"] == "sampled_wcs_mesh"
    assert coarse_manifest["mesh"]["residual"]["max_arcsec"] > fine_manifest["mesh"]["residual"]["max_arcsec"] * 5
    assert fine_manifest["mesh"]["residual"]["status"] == "pass"
    assert not np.allclose(
        coarse_manifest["presentation"]["local_pixel_scale_arcsec"]["geometric_mean_arcsec"],
        0.0,
    )
