"""Deterministic synthetic fixtures. These are not telescope observations."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

REFERENCE_SEED = 20260315
REFERENCE_SHAPE = (80, 96)  # (ny, nx)
REFERENCE_CRVAL = (150.0, -20.0)
REFERENCE_SCALE_ARCSEC = 0.5
REFERENCE_ROTATION_DEG = 25.0

SOURCES = (
    {"id": "SRC-A", "x": 20.0, "y": 16.0, "amp": 80.0, "sigma": 1.6, "snr": 12.0,
     "anomaly_score": 0.10, "anomaly_percentile": 20.0, "known": False, "reference_id": None, "sky": True},
    {"id": "SRC-B", "x": 70.0, "y": 18.0, "amp": 140.0, "sigma": 1.8, "snr": 40.0,
     "anomaly_score": 0.15, "anomaly_percentile": 55.0, "known": True, "reference_id": "REF-SYN-B", "sky": True},
    {"id": "SRC-C", "x": 28.0, "y": 60.0, "amp": 55.0, "sigma": 2.2, "snr": 8.0,
     "anomaly_score": 0.95, "anomaly_percentile": 99.0, "known": None, "reference_id": None, "sky": True},
    {"id": "SRC-D", "x": 78.0, "y": 58.0, "amp": 100.0, "sigma": 1.4, "snr": 22.0,
     "anomaly_score": 0.40, "anomaly_percentile": 70.0, "known": False, "reference_id": None, "sky": True},
    {"id": "SRC-E", "x": 48.0, "y": 40.0, "amp": 36.0, "sigma": 1.2, "snr": 6.5,
     "anomaly_score": None, "anomaly_percentile": None, "known": False, "reference_id": None, "sky": True},
    {"id": "SRC-BLANK", "x": 40.0, "y": 30.0, "amp": 20.0, "sigma": 1.3, "snr": 5.0,
     "anomaly_score": None, "anomaly_percentile": None, "known": None, "reference_id": None, "sky": False},
    {"id": "SRC-OUT", "x": 140.0, "y": 10.0, "amp": 0.0, "sigma": 1.0, "snr": None,
     "anomaly_score": None, "anomaly_percentile": None, "known": False, "reference_id": None, "sky": True},
)


def make_tan_wcs(
    nx: int = 96,
    ny: int = 80,
    crval: tuple[float, float] = REFERENCE_CRVAL,
    scale_arcsec: float = REFERENCE_SCALE_ARCSEC,
    rotation_deg: float = REFERENCE_ROTATION_DEG,
    mirror: bool = False,
) -> WCS:
    """TAN WCS. +pixel y is tilted from north by ``rotation_deg``.

    The default CD has a negative RA term so increasing pixel x is mostly
    west, which is the usual astronomical image orientation. ``mirror=True``
    flips that axis. Callers must still test east/north in sky space.
    """
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.cunit = ["deg", "deg"]
    wcs.wcs.radesys = "ICRS"
    wcs.wcs.crpix = [(nx + 1) / 2.0, (ny + 1) / 2.0]
    wcs.wcs.crval = [float(crval[0]), float(crval[1])]
    scale = scale_arcsec / 3600.0
    theta = np.deg2rad(rotation_deg)
    sign = 1.0 if mirror else -1.0
    pc = np.array(
        [
            [sign * np.cos(theta), np.sin(theta)],
            [sign * np.sin(theta), np.cos(theta)],
        ],
        dtype=float,
    )
    wcs.wcs.pc = pc
    wcs.wcs.cdelt = [scale, scale]
    return wcs


def render_image(ny: int, nx: int, sources=SOURCES, seed: int = REFERENCE_SEED) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:ny, 0:nx]
    image = np.full((ny, nx), 8.0, dtype=np.float64)
    image += 0.01 * xx
    for source in sources:
        if source["amp"] <= 0 or not (0 <= source["x"] < nx and 0 <= source["y"] < ny):
            continue
        radius2 = (xx - source["x"]) ** 2 + (yy - source["y"]) ** 2
        image += source["amp"] * np.exp(-radius2 / (2.0 * source["sigma"] ** 2))
    image += rng.normal(0.0, 0.25, size=image.shape)
    dq = np.zeros(image.shape, dtype=np.int16)

    def _stamp(row: int, col: int, value: float | None, flag: int) -> None:
        if 0 <= row < ny and 0 <= col < nx:
            if value is not None:
                image[row, col] = value
            dq[row, col] = flag

    _stamp(8, 10, np.nan, 1)
    _stamp(min(70, ny - 1), 5, 50000.0, 2)
    _stamp(22, 12, None, 1)
    return image, dq


def catalog_table(wcs: WCS, sources=SOURCES) -> Table:
    rows = {key: [] for key in (
        "label", "x_centroid", "y_centroid", "ra", "dec", "snr",
        "anomaly_score", "anomaly_percentile", "known", "reference_id",
    )}
    for source in sources:
        rows["label"].append(source["id"])
        rows["x_centroid"].append(source["x"])
        rows["y_centroid"].append(source["y"])
        if source["sky"]:
            sky = wcs.pixel_to_world(source["x"], source["y"])
            rows["ra"].append(float(sky.ra.deg))
            rows["dec"].append(float(sky.dec.deg))
        else:
            rows["ra"].append(np.ma.masked)
            rows["dec"].append(np.ma.masked)
        for key in ("snr", "anomaly_score", "anomaly_percentile"):
            value = source[key]
            rows[key].append(np.ma.masked if value is None else value)
        known = source["known"]
        rows["known"].append(np.ma.masked if known is None else bool(known))
        ref = source["reference_id"]
        rows["reference_id"].append("" if ref is None else ref)
    table = Table(rows, masked=True)
    table.meta["comments"] = [
        "Synthetic WCSScene catalogue. Not a telescope observation.",
        "x_centroid and y_centroid are zero-based pixel centres.",
        "anomaly_score is a within-image score, not a discovery significance.",
        "known and reference_id are catalogue fields, not physical classes.",
        "No distances are provided; distance_status is distance_unknown.",
    ]
    return table


def write_reference_fits(path: str | Path) -> WCS:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ny, nx = REFERENCE_SHAPE
    wcs = make_tan_wcs(nx, ny)
    image, dq = render_image(ny, nx)
    primary = fits.PrimaryHDU()
    primary.header["COMMENT"] = "WCSScene synthetic MEF. Not a telescope observation."
    science = fits.ImageHDU(data=np.array(image, dtype=np.float32), name="SCI")
    science.header.update(wcs.to_header())
    science.header["BUNIT"] = ("adu", "declared image unit, not surface brightness")
    science.header["FILTER"] = "SYN-G"
    science.header["INSTRUME"] = "SYNTH"
    science.header["TELESCOP"] = "NONE"
    science.header["OBJECT"] = "WCSSCENE SYNTHETIC FIELD"
    science.header["ORIGIN"] = "WCSScene synthetic fixture; not a telescope observation"
    science.header["PRODTYPE"] = "SYNTHETIC_2D"
    science.header["DQCONV"] = "WCSSCENE_012"
    science.header["DATE"] = "2026-01-15T00:00:00"
    quality = fits.ImageHDU(data=dq, name="DQ")
    quality.header["COMMENT"] = "0 good, 1 invalid, 2 saturated display flag"
    fits.HDUList([primary, science, quality]).writeto(path, overwrite=True, checksum=False)
    return wcs


def write_reference_catalog(path: str | Path, wcs: WCS | None = None) -> None:
    path = Path(path)
    if wcs is None:
        ny, nx = REFERENCE_SHAPE
        wcs = make_tan_wcs(nx, ny)
    catalog_table(wcs).write(path, format="ascii.ecsv", overwrite=True)


def write_sip_fits(path: str | Path) -> None:
    """SIP fixture whose interior is not an affine image of the corners."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nx = ny = 64
    wcs = make_tan_wcs(nx, ny, crval=(20.0, 30.0), scale_arcsec=0.2, rotation_deg=0.0)
    header = wcs.to_header()
    header["CTYPE1"] = "RA---TAN-SIP"
    header["CTYPE2"] = "DEC--TAN-SIP"
    header["A_ORDER"] = 2
    header["A_2_0"] = 1.2e-3
    header["A_0_2"] = 0.0
    header["B_ORDER"] = 2
    header["B_2_0"] = 0.0
    header["B_0_2"] = -1.0e-3
    header["BUNIT"] = "adu"
    header["ORIGIN"] = "WCSScene synthetic SIP fixture; not a telescope observation"
    header["DQCONV"] = "WCSSCENE_012"
    image = np.zeros((ny, nx), dtype=np.float32)
    yy, xx = np.mgrid[0:ny, 0:nx]
    image += 20.0 * np.exp(-((xx - 16) ** 2 + (yy - 40) ** 2) / 8.0)
    image += 35.0 * np.exp(-((xx - 48) ** 2 + (yy - 18) ** 2) / 6.0)
    image += 18.0 * np.exp(-((xx - 40) ** 2 + (yy - 50) ** 2) / 10.0)
    image += 12.0 * np.exp(-((xx - 22) ** 2 + (yy - 12) ** 2) / 7.0)
    fits.PrimaryHDU(data=image, header=header).writeto(path, overwrite=True, checksum=False)


def write_no_wcs_npz(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ny, nx = REFERENCE_SHAPE
    image, _dq = render_image(ny, nx, sources=SOURCES[:4], seed=7)
    kept = [source for source in SOURCES[:4]]
    np.savez(
        path,
        image=image.astype(np.float32),
        source_x=np.array([source["x"] for source in kept], dtype=np.float64),
        source_y=np.array([source["y"] for source in kept], dtype=np.float64),
        source_label=np.array([source["id"] for source in kept]),
    )


def write_examples(root: str | Path) -> None:
    root = Path(root)
    examples = root / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    wcs = write_reference_fits(examples / "reference.fits")
    write_reference_catalog(examples / "reference_sources.ecsv", wcs)
    write_no_wcs_npz(examples / "synthetic_no_wcs.npz")
    write_sip_fits(examples / "sip_distorted.fits")
    catalog_table(wcs).write(examples / "ngrst_catalog.csv", format="ascii.csv", overwrite=True)
