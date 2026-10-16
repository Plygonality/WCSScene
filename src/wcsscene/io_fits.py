"""FITS image loading and the no-WCS NPZ preview container.

The selected HDU's array is ``data[row, column]`` = ``data[y, x]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from .errors import InvalidInput, UnsupportedDataModel

WCS_KEYWORDS = (
    "WCSAXES",
    "RADESYS",
    "EQUINOX",
    "LONPOLE",
    "LATPOLE",
    "WCSNAME",
)
_WCS_PREFIXES = ("CTYPE", "CUNIT", "CRPIX", "CRVAL", "CDELT", "CD", "PC", "PV", "CROTA")
_SIP_PREFIXES = ("A_", "B_", "AP_", "BP_")


@dataclass
class LoadedImage:
    data: np.ndarray
    mask: np.ndarray
    path: Path
    hdu_index: int | None
    hdu_name: str | None
    hdu_descriptions: list[str]
    wcs: Any | None
    wcs_kind: str
    header_meta: dict[str, Any] = field(default_factory=dict)
    wcs_keywords: dict[str, Any] = field(default_factory=dict)
    embedded_catalog: Table | None = None
    product_note: str = ""
    units: str = "undeclared"
    roman: dict[str, Any] | None = None


def hdu_descriptions(hdul: fits.HDUList) -> list[str]:
    rows = []
    for index, hdu in enumerate(hdul):
        name = hdu.name or "UNNAMED"
        naxis = int(hdu.header.get("NAXIS", 0))
        kind = type(hdu).__name__
        rows.append(f"{index}:{name} ({kind}, NAXIS={naxis})")
    return rows


def resolve_hdu(hdul: fits.HDUList, hdu: str | int | None) -> int:
    descriptions = hdu_descriptions(hdul)
    if hdu is None:
        for index, item in enumerate(hdul):
            data = item.data
            if data is not None and getattr(data, "ndim", 0) == 2 and item.is_image:
                return index
        raise InvalidInput(
            "No 2D image HDU found. Available HDUs: " + ", ".join(descriptions)
        )
    text = str(hdu)
    if text.lstrip("-").isdigit():
        index = int(text)
        if index < 0 or index >= len(hdul):
            raise InvalidInput(
                f"HDU index {index} is outside 0..{len(hdul) - 1}. "
                f"Available HDUs: {', '.join(descriptions)}"
            )
        return index
    exact = [i for i, item in enumerate(hdul) if item.name == text]
    if exact:
        return exact[0]
    folded = [i for i, item in enumerate(hdul) if item.name.lower() == text.lower()]
    if folded:
        return folded[0]
    raise InvalidInput(
        f"HDU {text!r} not found. Available HDUs: {', '.join(descriptions)}"
    )


def _header_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return str(value)


def _wcs_keyword_dump(header: fits.Header) -> dict[str, Any]:
    dumped: dict[str, Any] = {}
    for key in header:
        upper = key.upper()
        if upper in WCS_KEYWORDS or upper.startswith(_WCS_PREFIXES + _SIP_PREFIXES):
            dumped[key] = _header_value(header[key])
    return dumped


def _meta_from_header(header: fits.Header) -> dict[str, Any]:
    keys = (
        "BUNIT",
        "FILTER",
        "INSTRUME",
        "TELESCOP",
        "DETECTOR",
        "OBJECT",
        "DATE-OBS",
        "EXPTIME",
        "PRODTYPE",
        "ORIGIN",
        "RADESYS",
        "EQUINOX",
        "DQCONV",
    )
    meta = {}
    for key in keys:
        if key in header:
            meta[key] = _header_value(header[key])
    return meta


def _apply_dq(data: np.ndarray, dq: np.ndarray | None, convention: str) -> np.ndarray:
    mask = np.ones(data.shape, dtype=np.uint8)
    mask[~np.isfinite(data)] = 0
    if dq is None:
        return mask
    dq_arr = np.asarray(dq)
    if dq_arr.shape != data.shape:
        raise InvalidInput(
            f"DQ array shape {dq_arr.shape} does not match image shape {data.shape}."
        )
    if convention == "WCSSCENE_012":
        mask[dq_arr == 1] = 0
        saturated = dq_arr == 2
        mask[saturated & (mask != 0)] = 2
        mask[dq_arr > 2] = 0
    else:
        mask[dq_arr != 0] = 0
    return mask


def _read_wcs(header: fits.Header) -> Any | None:
    has_ctype = any(key.upper().startswith("CTYPE") for key in header)
    if not has_ctype and "WCSAXES" not in header:
        return None
    try:
        return WCS(header)
    except Exception as exc:
        raise InvalidInput(f"FITS header has CTYPE/WCSAXES but WCS() failed: {exc}") from exc


def load_fits(path: str | Path, hdu: str | int | None = None) -> LoadedImage:
    fits_path = Path(path)
    if not fits_path.is_file():
        raise InvalidInput(f"File not found: {fits_path}")
    with fits.open(fits_path, memmap=False) as hdul:
        descriptions = hdu_descriptions(hdul)
        index = resolve_hdu(hdul, hdu)
        selected = hdul[index]
        if selected.data is None or not selected.is_image:
            raise InvalidInput(
                f"HDU {index}:{selected.name or 'UNNAMED'} has no image data. "
                f"Available HDUs: {', '.join(descriptions)}"
            )
        if selected.data.ndim != 2:
            raise UnsupportedDataModel(
                f"HDU {index}:{selected.name or 'UNNAMED'} has ndim={selected.data.ndim}. "
                "Only 2D images are supported; extra axes are not dropped."
            )
        data = np.array(selected.data, dtype=np.float64, copy=True)
        header = selected.header.copy()
        dq = None
        for extra in hdul:
            if extra.name.upper() == "DQ" and extra.data is not None and extra.is_image:
                dq = np.array(extra.data, copy=True)
                break
    convention = str(header.get("DQCONV", "GENERIC_NONZERO"))
    mask = _apply_dq(data, dq, convention)
    units = str(header.get("BUNIT", "undeclared"))
    return LoadedImage(
        data=data,
        mask=mask,
        path=fits_path,
        hdu_index=index,
        hdu_name=selected.name or "UNNAMED",
        hdu_descriptions=descriptions,
        wcs=_read_wcs(header),
        wcs_kind="fits-wcs" if _read_wcs(header) is not None else "none",
        header_meta=_meta_from_header(header),
        wcs_keywords=_wcs_keyword_dump(header),
        units=units,
        product_note=(
            "Declared FITS BUNIT is preserved. Display stretches are not physical "
            "flux or surface brightness."
        ),
    )


def load_npz(path: str | Path) -> LoadedImage:
    """Load a synthetic array container that has no celestial WCS."""
    npz_path = Path(path)
    if not npz_path.is_file():
        raise InvalidInput(f"File not found: {npz_path}")
    with np.load(npz_path, allow_pickle=False) as archive:
        if "image" not in archive:
            raise InvalidInput("NPZ preview files must contain an 'image' array.")
        data = np.array(archive["image"], dtype=np.float64, copy=True)
        dq = np.array(archive["dq"], copy=True) if "dq" in archive else None
        catalog = None
        if "source_x" in archive or "source_y" in archive:
            if "source_x" not in archive or "source_y" not in archive:
                raise InvalidInput("NPZ sources require both source_x and source_y.")
            columns = {
                "x_centroid": np.array(archive["source_x"], dtype=float),
                "y_centroid": np.array(archive["source_y"], dtype=float),
            }
            if "source_label" in archive:
                columns["label"] = np.array(archive["source_label"]).astype(str)
            catalog = Table(columns)
    if data.ndim != 2:
        raise UnsupportedDataModel(
            f"NPZ image ndim={data.ndim}. Only 2D arrays are supported."
        )
    mask = _apply_dq(data, dq, "WCSSCENE_012" if dq is not None else "GENERIC_NONZERO")
    return LoadedImage(
        data=data,
        mask=mask,
        path=npz_path,
        hdu_index=None,
        hdu_name=None,
        hdu_descriptions=["npz:image"],
        wcs=None,
        wcs_kind="none",
        embedded_catalog=catalog,
        units="undeclared",
        header_meta={"ORIGIN": "NPZ array without a celestial WCS"},
        product_note="Pixel-preview container. No celestial coordinate system is stored.",
    )
