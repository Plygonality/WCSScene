"""Catalogue alignment.

NGRST-Discovery-Toolkit columns are accepted when present. Blank fields stay
blank. Pixel and sky positions are cross-checked with ``SkyCoord.separation``
and are never quietly substituted. Distances and uncertainties are not invented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from .errors import InconsistentCoordinates, InvalidInput
from .projection import TangentBasis, sky_to_scene
from .wcs_adapter import pixel_to_sky, sky_to_pixel

# Priority order is the NGRST exporter contract, then common aliases.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "source_id": ("label", "source_id", "id", "name", "object"),
    "pixel_x": ("x_centroid", "x", "x_0", "xcen", "x_pix", "x_image", "xcentroid"),
    "pixel_y": ("y_centroid", "y", "y_0", "ycen", "y_pix", "y_image", "ycentroid"),
    "ra": ("ra", "ra_deg", "alpha_j2000", "ra_icrs"),
    "dec": ("dec", "dec_deg", "delta_j2000", "dec_icrs"),
    "glon": ("glon", "l", "lon"),
    "glat": ("glat", "b", "lat"),
    "snr": ("snr",),
    "anomaly_score": ("anomaly_score",),
    "anomaly_percentile": ("anomaly_percentile",),
    "known": ("known",),
    "reference_id": ("reference_id",),
    "x_err": ("x_err", "x_centroid_err"),
    "y_err": ("y_err", "y_centroid_err"),
    "xy_corr": ("xy_corr", "xy_correlation"),
    "ra_err": ("ra_err", "ra_err_arcsec"),
    "dec_err": ("dec_err", "dec_err_arcsec"),
    "ra_dec_corr": ("ra_dec_corr", "radec_corr"),
}

ANOMALY_SEMANTICS = (
    "Within-image anomaly score or percentile. Not a discovery significance "
    "and not a physical classification."
)
REFERENCE_SEMANTICS = (
    "Catalogue match identifier supplied by the input table. Not a physical class."
)


def read_catalog_table(path: str | Path) -> Table:
    catalog_path = Path(path)
    if not catalog_path.is_file():
        raise InvalidInput(f"Catalogue not found: {catalog_path}")
    suffix = catalog_path.suffix.lower()
    try:
        if suffix == ".ecsv":
            return Table.read(catalog_path, format="ascii.ecsv")
        if suffix == ".csv":
            return Table.read(catalog_path, format="ascii.csv")
        if suffix in {".fits", ".fit", ".fts"}:
            return Table.read(catalog_path, format="fits")
        return Table.read(catalog_path)
    except Exception as exc:
        raise InvalidInput(f"Could not read catalogue {catalog_path.name}: {exc}") from exc


def _find_column(table: Table, aliases: tuple[str, ...]) -> str | None:
    lookup = {name.lower(): name for name in table.colnames}
    for alias in aliases:
        found = lookup.get(alias.lower())
        if found is not None:
            return found
    return None


def column_map(table: Table) -> dict[str, str]:
    mapping = {}
    for role, aliases in COLUMN_ALIASES.items():
        found = _find_column(table, aliases)
        if found is not None:
            mapping[role] = found
    return mapping


def _masked(value: Any) -> bool:
    if value is None:
        return True
    try:
        if np.ma.is_masked(value):
            return True
    except (TypeError, ValueError):
        pass
    return False


def optional_float(value: Any) -> float | None:
    if _masked(value):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text.lower() in {"nan", "none", "null"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if np.isfinite(number) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def optional_bool(value: Any) -> tuple[bool | None, str | None]:
    if _masked(value):
        return None, None
    if isinstance(value, (bool, np.bool_)):
        return bool(value), None
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(int(value)), None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None, None
    folded = text.lower()
    if folded in {"1", "true", "t", "yes", "y"}:
        return True, None
    if folded in {"0", "false", "f", "no", "n"}:
        return False, None
    return None, text


def optional_text(value: Any) -> str | None:
    if _masked(value):
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _column_value(table: Table, name: str | None, row: int) -> Any:
    if name is None:
        return None
    return table[name][row]


def _inside(x: float, y: float, nx: int, ny: int) -> bool:
    return (-0.5 <= x < nx - 0.5) and (-0.5 <= y < ny - 0.5)


def _unique_id(raw: str | None, index: int, used: dict[str, int]) -> str:
    base = raw if raw else f"src-{index:06d}"
    count = used.get(base, 0) + 1
    used[base] = count
    if count == 1:
        return base
    return f"{base}~{count}"


def align_catalog(
    table: Table | None,
    *,
    wcs: Any,
    basis: TangentBasis | None,
    shape: tuple[int, int],
    arcsec_per_bu: float | None,
    flip_east_left: bool,
    pixel_origin: int,
    authority: str,
    tolerance_arcsec: float,
    pixel_preview: bool,
    image: np.ndarray,
    mask: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return source records and a catalogue summary.

    ``authority='auto'`` fails when both coordinate pairs exist and disagree.
    An explicit authority still reports the residual.
    """
    if authority not in {"auto", "pixel", "sky"}:
        raise InvalidInput("coord authority must be auto, pixel, or sky")
    if pixel_origin not in {0, 1}:
        raise InvalidInput("pixel origin must be 0 (pixel centres) or 1 (FITS)")
    ny, nx = shape
    if table is None or len(table) == 0:
        return [], {
            "present": False,
            "row_count": 0,
            "placed_count": 0,
            "column_map": {},
            "pixel_origin": pixel_origin,
            "authority_policy": authority,
            "distance_status": "distance_unknown",
        }

    mapping = column_map(table)
    frame_name = None if basis is None else basis.frame_name
    equatorial = frame_name in {None, "icrs", "fk5", "fk4"}
    if not pixel_preview and not equatorial and "ra" in mapping and "glon" not in mapping:
        raise InvalidInput(
            "Catalogue has equatorial ra/dec columns but the WCS frame is "
            f"{frame_name}. Refusing to treat RA/Dec as galactic coordinates."
        )

    used_ids: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    disagreements: list[str] = []
    warnings: list[dict[str, str]] = []

    for index in range(len(table)):
        source_id = _unique_id(
            optional_text(_column_value(table, mapping.get("source_id"), index)),
            index,
            used_ids,
        )
        x_raw = optional_float(_column_value(table, mapping.get("pixel_x"), index))
        y_raw = optional_float(_column_value(table, mapping.get("pixel_y"), index))
        pixel_xy = None
        if x_raw is not None and y_raw is not None:
            pixel_xy = [x_raw - pixel_origin, y_raw - pixel_origin]
        if equatorial or pixel_preview:
            lon = optional_float(_column_value(table, mapping.get("ra"), index))
            lat = optional_float(_column_value(table, mapping.get("dec"), index))
        else:
            lon = optional_float(_column_value(table, mapping.get("glon"), index))
            lat = optional_float(_column_value(table, mapping.get("glat"), index))
        sky_input = [lon, lat] if lon is not None and lat is not None else None
        known, known_raw = optional_bool(_column_value(table, mapping.get("known"), index))
        if known_raw is not None:
            warnings.append(
                {
                    "code": "UNPARSED_KNOWN",
                    "message": f"{source_id} known value {known_raw!r} was left null.",
                }
            )
        record: dict[str, Any] = {
            "source_id": source_id,
            "catalog_row": index,
            "pixel_xy_input": pixel_xy,
            "pixel_xy_from_sky": None,
            "sky_input_deg": None if pixel_preview else sky_input,
            "sky_from_pixel_deg": None,
            "separation_arcsec": None,
            "authoritative": None,
            "scene_xyz": None,
            "placed": False,
            "placement_reason": "missing_coordinates",
            "outside_image": False,
            "sky_used_for_placement": False,
            "snr": optional_float(_column_value(table, mapping.get("snr"), index)),
            "anomaly_score": optional_float(
                _column_value(table, mapping.get("anomaly_score"), index)
            ),
            "anomaly_percentile": optional_float(
                _column_value(table, mapping.get("anomaly_percentile"), index)
            ),
            "known": known,
            "reference_id": optional_text(
                _column_value(table, mapping.get("reference_id"), index)
            ),
            "distance_status": "distance_unknown",
            "uncertainty_status": "UNKNOWN",
            "uncertainty": None,
            "pixel_value": None,
            "pixel_quality": None,
            "errors": {
                "x_err": optional_float(_column_value(table, mapping.get("x_err"), index)),
                "y_err": optional_float(_column_value(table, mapping.get("y_err"), index)),
                "xy_corr": optional_float(_column_value(table, mapping.get("xy_corr"), index)),
                "ra_err": optional_float(_column_value(table, mapping.get("ra_err"), index)),
                "dec_err": optional_float(_column_value(table, mapping.get("dec_err"), index)),
                "ra_dec_corr": optional_float(
                    _column_value(table, mapping.get("ra_dec_corr"), index)
                ),
            },
        }
        if pixel_preview and sky_input is not None:
            warnings.append(
                {
                    "code": "SKY_IGNORED_IN_PIXEL_PREVIEW",
                    "message": f"{source_id} sky columns were not used for placement.",
                }
            )
        records.append(record)
        if pixel_preview:
            _place_pixel_preview(record, nx, ny, image, mask)
            continue
        disagreements.extend(
            _place_scientific(
                record,
                wcs=wcs,
                basis=basis,
                nx=nx,
                ny=ny,
                arcsec_per_bu=float(arcsec_per_bu),
                flip_east_left=flip_east_left,
                authority=authority,
                tolerance_arcsec=tolerance_arcsec,
                image=image,
                mask=mask,
            )
        )

    if disagreements and authority == "auto":
        preview = "; ".join(disagreements[:8])
        raise InconsistentCoordinates(
            f"{len(disagreements)} catalogue rows exceed {tolerance_arcsec} arcsec "
            "between WCS(pixel) and catalogue sky coordinates. "
            f"Examples: {preview}. Pass --coord-authority pixel or "
            "--coord-authority sky to choose one explicitly; the residual stays in the record."
        )

    placed = sum(1 for record in records if record["placed"])
    summary = {
        "present": True,
        "row_count": len(records),
        "placed_count": placed,
        "unplaced_count": len(records) - placed,
        "column_map": mapping,
        "pixel_origin": pixel_origin,
        "pixel_convention_after_origin": "zero_based_pixel_centers",
        "authority_policy": authority,
        "coord_tolerance_arcsec": tolerance_arcsec,
        "separation_method": "SkyCoord.separation",
        "distance_status": "distance_unknown",
        "anomaly_semantics": ANOMALY_SEMANTICS if _has_anomaly(mapping) else None,
        "reference_semantics": REFERENCE_SEMANTICS if "reference_id" in mapping else None,
        "ngrst_fields": [
            "label",
            "x_centroid",
            "y_centroid",
            "ra",
            "dec",
            "snr",
            "anomaly_score",
            "anomaly_percentile",
            "known",
            "reference_id",
        ],
        "warnings": warnings,
        "disagreement_count": len(disagreements),
    }
    return records, summary


def _has_anomaly(mapping: dict[str, str]) -> bool:
    return "anomaly_score" in mapping or "anomaly_percentile" in mapping


def _sample_pixel(record: dict[str, Any], image: np.ndarray, mask: np.ndarray) -> None:
    pixel = record["pixel_xy_input"] if record["authoritative"] == "pixel" else None
    if pixel is None:
        pixel = record["pixel_xy_from_sky"] or record["pixel_xy_input"]
    if pixel is None:
        return
    x = int(np.rint(pixel[0]))
    y = int(np.rint(pixel[1]))
    ny, nx = image.shape
    if not (0 <= x < nx and 0 <= y < ny):
        return
    value = float(image[y, x])
    record["pixel_value"] = value if np.isfinite(value) else None
    code = int(mask[y, x])
    record["pixel_quality"] = {0: "invalid", 1: "ok", 2: "saturated"}.get(code, "flagged")


def _place_pixel_preview(
    record: dict[str, Any], nx: int, ny: int, image: np.ndarray, mask: np.ndarray
) -> None:
    pixel = record["pixel_xy_input"]
    record["authoritative"] = "pixel" if pixel is not None else None
    record["sky_used_for_placement"] = False
    if pixel is None:
        record["placement_reason"] = "missing_coordinates"
        return
    x, y = pixel
    if not _inside(x, y, nx, ny):
        record["outside_image"] = True
        record["placement_reason"] = "outside_image"
        return
    # Centre the array on the origin. One pixel is one Blender unit, not an angle.
    record["scene_xyz"] = [x - (nx - 1) / 2.0, y - (ny - 1) / 2.0, 0.0]
    record["placed"] = True
    record["placement_reason"] = "pixel_preview"
    _sample_pixel(record, image, mask)


def _place_scientific(
    record: dict[str, Any],
    *,
    wcs: Any,
    basis: TangentBasis | None,
    nx: int,
    ny: int,
    arcsec_per_bu: float,
    flip_east_left: bool,
    authority: str,
    tolerance_arcsec: float,
    image: np.ndarray,
    mask: np.ndarray,
) -> list[str]:
    assert basis is not None
    disagreements: list[str] = []
    pixel = record["pixel_xy_input"]
    sky_input = record["sky_input_deg"]
    sky_from_pixel = None
    pixel_from_sky = None
    if pixel is not None:
        sky = pixel_to_sky(wcs, pixel[0], pixel[1])
        if np.isfinite(float(sky.spherical.lon.deg)) and np.isfinite(float(sky.spherical.lat.deg)):
            sky_from_pixel = [float(sky.spherical.lon.deg), float(sky.spherical.lat.deg)]
            record["sky_from_pixel_deg"] = sky_from_pixel
    if sky_input is not None:
        catalog_sky = SkyCoord(
            sky_input[0] * u.deg, sky_input[1] * u.deg, frame=basis.sky.frame
        )
        x2, y2, failure = sky_to_pixel(wcs, catalog_sky)
        if failure is None:
            pixel_from_sky = [float(np.asarray(x2)), float(np.asarray(y2))]
            record["pixel_xy_from_sky"] = pixel_from_sky
        else:
            record["pixel_xy_from_sky_failure"] = failure
    if sky_from_pixel is not None and sky_input is not None:
        derived = SkyCoord(
            sky_from_pixel[0] * u.deg,
            sky_from_pixel[1] * u.deg,
            frame=basis.sky.frame,
        )
        given = SkyCoord(sky_input[0] * u.deg, sky_input[1] * u.deg, frame=basis.sky.frame)
        separation = float(derived.separation(given).arcsec)
        record["separation_arcsec"] = separation
        if separation > tolerance_arcsec:
            disagreements.append(
                f"{record['source_id']} row {record['catalog_row']} "
                f"separation {separation:.6g} arcsec"
            )
    chosen = _choose_authority(authority, pixel is not None, sky_input is not None)
    record["authoritative"] = chosen
    if chosen is None:
        record["placement_reason"] = "missing_coordinates"
        return disagreements
    if chosen == "sky":
        record["sky_used_for_placement"] = True
        if record.get("pixel_xy_from_sky_failure"):
            record["placement_reason"] = "outside_wcs_footprint"
            return disagreements
        if pixel_from_sky is None:
            record["placement_reason"] = "outside_wcs_footprint"
            return disagreements
        if not _inside(pixel_from_sky[0], pixel_from_sky[1], nx, ny):
            record["outside_image"] = True
            record["placement_reason"] = "outside_image"
            return disagreements
        catalog_sky = SkyCoord(
            sky_input[0] * u.deg, sky_input[1] * u.deg, frame=basis.sky.frame
        )
        scene, valid = sky_to_scene(
            catalog_sky, basis, arcsec_per_bu, flip_east_left=flip_east_left
        )
        if not bool(np.asarray(valid).reshape(-1)[0]) or not np.all(np.isfinite(scene)):
            record["placement_reason"] = "projection_undefined"
            return disagreements
        record["scene_xyz"] = [float(v) for v in np.asarray(scene).reshape(-1)[:3]]
    else:
        if pixel is None or not _inside(pixel[0], pixel[1], nx, ny):
            record["outside_image"] = pixel is not None
            record["placement_reason"] = "outside_image" if pixel is not None else "missing_coordinates"
            return disagreements
        if sky_from_pixel is None:
            record["placement_reason"] = "outside_wcs_footprint"
            return disagreements
        derived = SkyCoord(
            sky_from_pixel[0] * u.deg,
            sky_from_pixel[1] * u.deg,
            frame=basis.sky.frame,
        )
        scene, valid = sky_to_scene(
            derived, basis, arcsec_per_bu, flip_east_left=flip_east_left
        )
        if not bool(np.asarray(valid).reshape(-1)[0]) or not np.all(np.isfinite(scene)):
            record["placement_reason"] = "projection_undefined"
            return disagreements
        record["scene_xyz"] = [float(v) for v in np.asarray(scene).reshape(-1)[:3]]
    record["placed"] = True
    record["placement_reason"] = "ok" if not disagreements else "mismatch_reported"
    if record["separation_arcsec"] is not None and record["separation_arcsec"] > tolerance_arcsec:
        record["placement_reason"] = "mismatch_reported"
    _sample_pixel(record, image, mask)
    return disagreements


def _choose_authority(policy: str, has_pixel: bool, has_sky: bool) -> str | None:
    if policy == "pixel":
        return "pixel" if has_pixel else None
    if policy == "sky":
        return "sky" if has_sky else None
    if has_sky:
        return "sky"
    if has_pixel:
        return "pixel"
    return None
