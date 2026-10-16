"""Catalogue authority, blanks, and the NGRST column contract."""

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from wcsscene.catalogs import align_catalog
from wcsscene.errors import InconsistentCoordinates
from wcsscene.projection import build_basis
from wcsscene.synthetic import SOURCES, catalog_table, make_tan_wcs


def _wcs():
    return make_tan_wcs()


def test_clean_catalog_agrees_and_blank_sky_uses_pixel(tmp_path):
    wcs = _wcs()
    table = catalog_table(wcs)
    basis = build_basis(wcs.pixel_to_world(47.5, 39.5))
    image = np.zeros((80, 96))
    mask = np.ones_like(image, dtype=np.uint8)
    records, summary = align_catalog(
        table,
        wcs=wcs,
        basis=basis,
        shape=image.shape,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_origin=0,
        authority="auto",
        tolerance_arcsec=0.05,
        pixel_preview=False,
        image=image,
        mask=mask,
    )
    by_id = {row["source_id"]: row for row in records}
    assert summary["column_map"]["pixel_x"] == "x_centroid"
    assert summary["column_map"]["source_id"] == "label"
    src_b = by_id["SRC-B"]
    assert src_b["placed"] is True
    assert src_b["authoritative"] == "sky"
    assert src_b["separation_arcsec"] < 1e-4
    assert src_b["known"] is True
    assert src_b["reference_id"] == "REF-SYN-B"
    assert src_b["distance_status"] == "distance_unknown"
    assert by_id["SRC-A"]["known"] is False
    assert by_id["SRC-C"]["known"] is None
    blank = by_id["SRC-BLANK"]
    assert blank["sky_input_deg"] is None
    assert blank["placed"] is True
    assert blank["authoritative"] == "pixel"
    assert blank["sky_from_pixel_deg"] is not None
    outside = by_id["SRC-OUT"]
    assert outside["placed"] is False
    assert outside["scene_xyz"] is None
    assert outside["placement_reason"] == "outside_image"
    assert "anomaly" in (summary["anomaly_semantics"] or "").lower()
    assert SOURCES[1]["id"] == "SRC-B"


def test_disagreement_fails_closed_until_authority_is_explicit():
    wcs = _wcs()
    table = catalog_table(wcs)
    row = np.where(table["label"] == "SRC-A")[0][0]
    table["dec"][row] = float(table["dec"][row]) + 1.0 / 3600.0
    basis = build_basis(wcs.pixel_to_world(47.5, 39.5))
    image = np.zeros((80, 96))
    mask = np.ones_like(image, dtype=np.uint8)
    kwargs = dict(
        wcs=wcs,
        basis=basis,
        shape=image.shape,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_origin=0,
        tolerance_arcsec=0.05,
        pixel_preview=False,
        image=image,
        mask=mask,
    )
    with pytest.raises(InconsistentCoordinates):
        align_catalog(table, authority="auto", **kwargs)
    records, _summary = align_catalog(table, authority="sky", **kwargs)
    src = next(row for row in records if row["source_id"] == "SRC-A")
    assert src["placed"] is True
    assert src["separation_arcsec"] > 0.5
    assert src["placement_reason"] == "mismatch_reported"
    assert src["pixel_xy_input"] == [20.0, 16.0]


def test_pixel_origin_one_matches_zero_based_centroids():
    wcs = _wcs()
    table = Table(
        {
            "label": ["SRC-A"],
            "x_centroid": [21.0],
            "y_centroid": [17.0],
            "ra": [np.nan],
            "dec": [np.nan],
        }
    )
    basis = build_basis(wcs.pixel_to_world(47.5, 39.5))
    image = np.zeros((80, 96))
    mask = np.ones_like(image, dtype=np.uint8)
    records, _summary = align_catalog(
        table,
        wcs=wcs,
        basis=basis,
        shape=image.shape,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_origin=1,
        authority="pixel",
        tolerance_arcsec=0.05,
        pixel_preview=False,
        image=image,
        mask=mask,
    )
    assert records[0]["pixel_xy_input"] == [20.0, 16.0]
    sky = wcs.pixel_to_world(20.0, 16.0)
    got = SkyCoord(*records[0]["sky_from_pixel_deg"], unit=u.deg)
    assert float(sky.separation(got).arcsec) < 1e-6


def test_ngrst_column_names_map_without_inventing_distance():
    wcs = _wcs()
    sky = wcs.pixel_to_world(70.0, 18.0)
    table = Table(
        {
            "label": ["SRC-B", "SRC-C"],
            "x_centroid": [70.0, 28.0],
            "y_centroid": [18.0, 60.0],
            "ra": [float(sky.ra.deg), ""],
            "dec": [float(sky.dec.deg), ""],
            "snr": [40.0, ""],
            "anomaly_score": [0.15, 0.95],
            "anomaly_percentile": [55.0, 99.0],
            "known": ["true", ""],
            "reference_id": ["REF-SYN-B", ""],
        }
    )
    basis = build_basis(wcs.pixel_to_world(47.5, 39.5))
    image = np.zeros((80, 96))
    mask = np.ones_like(image, dtype=np.uint8)
    records, summary = align_catalog(
        table,
        wcs=wcs,
        basis=basis,
        shape=image.shape,
        arcsec_per_bu=1.0,
        flip_east_left=False,
        pixel_origin=0,
        authority="auto",
        tolerance_arcsec=0.05,
        pixel_preview=False,
        image=image,
        mask=mask,
    )
    assert "distance" not in summary["column_map"]
    assert all(row["distance_status"] == "distance_unknown" for row in records)
    assert records[0]["anomaly_score"] == pytest.approx(0.15)
    assert records[1]["sky_input_deg"] is None
    assert records[1]["uncertainty_status"] == "UNKNOWN"
