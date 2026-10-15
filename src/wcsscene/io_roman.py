"""Roman WFI datamodel adapter.

Scientific placement uses ``meta.wcs`` only. A FITS WCS header is never
invented from GWCS. Schema-factory coordinates are not treated as a verified
instrument distortion solution, and this module does not claim flight-data
acceptance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .errors import InconsistentWCS, InvalidInput, MissingOptionalDependency, UnsupportedDataModel
from .io_fits import LoadedImage

_LEVEL = {
    "ImageModel": "L2",
    "MosaicModel": "L3",
}
_SUPPORTED = frozenset({"ImageModel", "MosaicModel"})
_INVALID_DQ = ("DO_NOT_USE", "NON_SCIENCE", "DEAD", "DROPOUT")


def _import_roman():
    try:
        import roman_datamodels as rdm
    except ImportError as exc:
        raise MissingOptionalDependency(
            "roman_datamodels is not installed. Roman ASDF input requires the "
            "'roman' extra. No FITS-equivalent WCS was fabricated."
        ) from exc
    return rdm


def _is_sentinel(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() in {"", "?", "N/A", "None"}
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return (not np.isfinite(number)) or abs(number) == 999999.0 or number == -999999.0
    return False


def _plain(value: Any) -> Any:
    if value is None or _is_sentinel(value):
        return None
    if hasattr(value, "isot"):
        return str(value.isot)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    text = str(value)
    if len(text) > 200:
        return text[:200]
    return text


def _meta_value(model: Any, dotted: str) -> tuple[Any, bool]:
    current = model
    for part in dotted.split("."):
        if not hasattr(current, part):
            return None, False
        current = getattr(current, part)
    present = True
    usable = not _is_sentinel(current)
    return _plain(current) if usable else None, present and not usable


def _roman_mask(dq: np.ndarray) -> np.ndarray:
    from roman_datamodels.dqflags import pixel as flags

    dq_arr = np.asarray(dq)
    invalid = 0
    for name in _INVALID_DQ:
        invalid |= int(getattr(flags, name))
    saturated = int(flags.SATURATED)
    mask = np.ones(dq_arr.shape, dtype=np.uint8)
    mask[(dq_arr & np.uint32(invalid)) != 0] = 0
    sat = (dq_arr & np.uint32(saturated)) != 0
    mask[sat & (mask != 0)] = 2
    return mask


def roman_metadata(model: Any) -> dict[str, Any]:
    model_name = type(model).__name__
    fields = [
        "meta.instrument.name",
        "meta.instrument.detector",
        "meta.instrument.optical_element",
        "meta.exposure.type",
        "meta.exposure.start_time",
        "meta.exposure.exposure_time",
        "meta.exposure.effective_exposure_time",
        "meta.observation.program",
        "meta.observation.observation_id",
        "meta.wcsinfo.aperture_name",
        "meta.wcsinfo.ra_ref",
        "meta.wcsinfo.dec_ref",
        "meta.wcsinfo.roll_ref",
        "meta.photometry.conversion_megajanskys",
        "meta.photometry.pixel_area",
        "meta.filename",
        "meta.calibration_software_name",
        "meta.crds_context_used",
        "meta.origin",
    ]
    usable: dict[str, Any] = {}
    sentinels: list[str] = []
    for field in fields:
        value, was_sentinel = _meta_value(model, field)
        key = field.removeprefix("meta.")
        if was_sentinel:
            sentinels.append(key)
        elif value is not None:
            usable[key] = value
    level = _LEVEL.get(model_name, "undeclared")
    unit_note = (
        "Undeclared on the array. "
        if level == "undeclared"
        else (
            f"Roman {level} {model_name} rate/mosaic products are defined by the "
            "Roman data handbook in instrumental units (L2 rate images: DN/s). "
        )
    )
    unit_note += (
        "No per-array unit override was applied. conversion_megajanskys is not "
        "applied, and sentinel fill values are not measurements."
    )
    return {
        "model_type": model_name,
        "product_level": level,
        "adapter": "roman_datamodels",
        "wcs_attribute": "meta.wcs",
        "fits_wcs_fabricated": False,
        "instrument_distortion_verified": False,
        "flight_data_verified": False,
        "units_note": unit_note,
        "metadata": usable,
        "sentinel_fields": sentinels,
        "acceptance": (
            "meta.wcs is evaluated as provided by roman_datamodels. "
            "This does not certify a CRDS distortion reference file or a flight product."
        ),
    }


def load_roman(path: str | Path) -> LoadedImage:
    asdf_path = Path(path)
    if not asdf_path.is_file():
        raise InvalidInput(f"File not found: {asdf_path}")
    try:
        rdm = _import_roman()
    except ImportError as exc:
        raise MissingOptionalDependency(
            "MISSING_OPTIONAL_DEPENDENCY: roman_datamodels could not be imported. "
            "No FITS-equivalent WCS was fabricated."
        ) from exc
    try:
        model = rdm.open(asdf_path)
    except MissingOptionalDependency:
        raise
    except Exception as exc:
        raise UnsupportedDataModel(
            f"UNSUPPORTED_DATA_MODEL: {asdf_path.name} is not a roman_datamodels "
            f"imaging product ({type(exc).__name__}: {exc})."
        ) from exc
    model_name = type(model).__name__
    if model_name not in _SUPPORTED:
        raise UnsupportedDataModel(
            f"UNSUPPORTED_DATA_MODEL: {model_name} is not a supported 2D Roman "
            f"imaging model ({', '.join(sorted(_SUPPORTED))})."
        )
    if not hasattr(model, "data"):
        raise UnsupportedDataModel(f"{model_name} has no data array.")
    data = np.array(model.data, dtype=np.float64, copy=True)
    if data.ndim != 2:
        raise UnsupportedDataModel(
            f"{model_name} data ndim={data.ndim}. Refusing to drop axes."
        )
    wcs = getattr(getattr(model, "meta", None), "wcs", None)
    if wcs is None:
        raise InconsistentWCS(
            f"{model_name} has no meta.wcs. Scientific placement is refused. "
            "WCSScene does not fabricate a FITS WCS."
        )
    dq = getattr(model, "dq", None)
    if dq is None:
        mask = np.ones(data.shape, dtype=np.uint8)
        mask[~np.isfinite(data)] = 0
    else:
        mask = _roman_mask(np.array(dq, copy=True))
        mask[~np.isfinite(data)] = 0
    info = roman_metadata(model)
    return LoadedImage(
        data=data,
        mask=mask,
        path=asdf_path,
        hdu_index=None,
        hdu_name=model_name,
        hdu_descriptions=[f"roman:{model_name}"],
        wcs=wcs,
        wcs_kind="gwcs",
        units="DN/s" if info["product_level"] == "L2" else "declared-by-product-level",
        header_meta=info["metadata"],
        product_note=info["units_note"],
        roman=info,
    )
