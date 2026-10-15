"""Build a versioned exchange bundle. No pickle and no Blender imports."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import SCHEMA_VERSION, __version__
from .catalogs import align_catalog
from .errors import InconsistentWCS, InvalidInput, UnsupportedDataModel
from .image_display import (
    choose_downsample,
    crop_image,
    downsample_mean,
    render_display,
    write_png_rgb,
)
from .io_fits import LoadedImage, load_fits, load_npz
from .io_roman import load_roman
from .mesh_sampling import axis_segments, build_mesh, sky_grid
from .projection import build_basis
from .provenance import runtime_versions, sha256_bytes, sha256_file, utc_now
from .uncertainty import propagate_source
from .wcs_adapter import (
    default_samples,
    describe_distortion,
    local_pixel_scale,
    pixel_to_sky,
    reference_pixel,
    require_celestial_wcs,
    roundtrip_samples,
)


@dataclass
class PrepareConfig:
    hdu: str | int | None = None
    catalog: str | None = None
    projection: str = "tan"
    arcsec_per_bu: float = 1.0
    pixel_preview: bool = False
    fmt: str = "auto"
    coord_authority: str = "auto"
    coord_tolerance_arcsec: float = 0.05
    pixel_origin: int = 0
    mesh_cells: int = 32
    residual_budget_arcsec: float | None = None
    fail_on_residual: bool = True
    flat_rectangle: bool = False
    stretch: str = "asinh"
    percentiles: tuple[float, float] = (1.0, 99.0)
    colormap: str = "gray"
    max_display_pixels: int = 2048
    downsample: int | None = None
    crop: tuple[int, int, int, int] | None = None
    east_left: bool = False
    pixel_uncertainty: bool = False
    sky_uncertainty_convention: str | None = None
    highlight_source_id: str | None = None
    tangent_lon_deg: float | None = None
    tangent_lat_deg: float | None = None
    command: list[str] | None = None


@dataclass
class PrepareResult:
    out_dir: Path
    manifest_path: Path
    exit_code: int
    validation_status: str
    warnings: list[dict[str, str]] = field(default_factory=list)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, np.floating):
        number = float(value)
        return None if not np.isfinite(number) else number
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_stable_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    buffer.seek(0)
    with zipfile.ZipFile(buffer, "r") as source, zipfile.ZipFile(path, "w") as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            target.writestr(info, source.read(name))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(to_jsonable(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_image(path: str | Path, config: PrepareConfig) -> LoadedImage:
    source = Path(path)
    suffix = source.suffix.lower()
    fmt = config.fmt
    if fmt not in {"auto", "fits", "roman", "npz"}:
        raise InvalidInput("--format must be auto, fits, roman, or npz")
    if fmt == "roman" or (fmt == "auto" and suffix == ".asdf"):
        return load_roman(source)
    if fmt == "npz" or (fmt == "auto" and suffix == ".npz"):
        return load_npz(source)
    if fmt == "fits" or suffix in {".fits", ".fit", ".fts"}:
        return load_fits(source, config.hdu)
    raise UnsupportedDataModel(
        f"UNSUPPORTED_DATA_MODEL: cannot prepare {source.name}. "
        "Use FITS, a no-WCS NPZ with --pixel-preview, or Roman ASDF."
    )


def _synthetic_banner(image: LoadedImage) -> bool:
    origin = str(image.header_meta.get("ORIGIN", "")).lower()
    return "synthetic" in origin or image.header_meta.get("PRODTYPE") == "SYNTHETIC_2D"


def _pixel_preview_mesh(
    nx: int, ny: int, crop: tuple[int, int, int, int] | None
) -> dict[str, np.ndarray]:
    if crop is None:
        xmin, xmax, ymin, ymax = 0, nx - 1, 0, ny - 1
    else:
        xmin, xmax, ymin, ymax = crop
    corners = np.array(
        [
            [xmin - 0.5, ymin - 0.5],
            [xmax + 0.5, ymin - 0.5],
            [xmax + 0.5, ymax + 0.5],
            [xmin - 0.5, ymax + 0.5],
        ],
        dtype=float,
    )
    origin = np.array([(nx - 1) / 2.0, (ny - 1) / 2.0])
    xyz = np.column_stack((corners - origin, np.zeros(4)))
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float)
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
    return {"xyz": xyz, "uv": uv, "pixel_xy": corners, "faces": faces}


def _qa_markdown(manifest: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    lines = [
        "# WCSScene QA report",
        "",
        "Synthetic or third-party inputs are not certified by this report. "
        "Numerical agreement is with the supplied WCS only.",
        "",
        f"- Mode: `{manifest['mode']}`",
        f"- Celestial accuracy: `{manifest['celestial_accuracy']}`",
        f"- Distance interpretation: `{manifest['distance_interpretation']}`",
    ]
    roundtrip = manifest.get("roundtrip")
    if roundtrip:
        lines.extend(
            [
                f"- World/pixel round-trip max error: `{roundtrip['max_pixel_error']}` pixel",
                f"- World/pixel round-trip max angular error: `{roundtrip['max_angular_error_arcsec']}` arcsec",
                f"- Round-trip failures: `{roundtrip['n_failed']}`",
                f"- Round-trip tolerance: `{roundtrip['tolerance_pixel']}` pixel",
            ]
        )
    residual = manifest["mesh"]["residual"]
    lines.extend(
        [
            f"- Mesh approximation: `{manifest['mesh']['approximation']}`",
            f"- Mesh interpolation max residual: `{residual.get('max_arcsec')}` arcsec",
            f"- Mesh interpolation RMS residual: `{residual.get('rms_arcsec')}` arcsec",
            f"- Mesh residual budget: `{residual.get('budget_arcsec')}` arcsec",
            f"- Mesh residual status: `{residual.get('status')}`",
            "",
        ]
    )
    highlight = manifest.get("highlight_source_id")
    chosen = next((row for row in sources if row["source_id"] == highlight), None)
    if chosen is None and sources:
        chosen = next((row for row in sources if row["placed"]), sources[0])
    if chosen is not None:
        lines.extend(
            [
                f"## Cross-highlight `{chosen['source_id']}`",
                "",
                f"- Catalogue row (0-based): `{chosen['catalog_row']}`",
                f"- Pixel centre (x, y): `{chosen['pixel_xy_input']}`",
                f"- Catalogue sky (deg): `{chosen['sky_input_deg']}`",
                f"- Sky from pixel (deg): `{chosen['sky_from_pixel_deg']}`",
                f"- Scene XYZ (Blender units): `{chosen['scene_xyz']}`",
                f"- Placed: `{chosen['placed']}` ({chosen['placement_reason']})",
                f"- Distance: `{chosen['distance_status']}`",
                f"- Uncertainty: `{chosen['uncertainty_status']}`",
                f"- SNR: `{chosen['snr']}`",
                f"- Anomaly score / percentile: `{chosen['anomaly_score']}` / `{chosen['anomaly_percentile']}`",
                f"- Known / reference id: `{chosen['known']}` / `{chosen['reference_id']}`",
                "",
                "The Blender marker with this source id is the same row. "
                "Z = 0 is the presentation plane, not a distance.",
                "",
            ]
        )
    return "\n".join(lines)


def prepare(path: str | Path, out: str | Path, config: PrepareConfig | None = None) -> PrepareResult:
    config = config or PrepareConfig()
    if config.projection != "tan" and not config.pixel_preview:
        raise InvalidInput("v0.1 supports only --projection tan")
    image = load_image(path, config)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, str]] = []
    ny, nx = image.data.shape
    if config.pixel_preview and image.wcs is not None:
        warnings.append(
            {
                "code": "WCS_IGNORED",
                "severity": "warning",
                "message": "A WCS was present and was not used because --pixel-preview was explicit.",
            }
        )
    if not config.pixel_preview and image.wcs is None:
        raise InconsistentWCS(
            "MISSING_WCS: scientific placement was refused. "
            "Pass --pixel-preview for a labelled pixel-space view with no sky accuracy."
        )

    catalog_table = None
    catalog_hash = None
    if config.catalog:
        from .catalogs import read_catalog_table

        catalog_table = read_catalog_table(config.catalog)
        catalog_hash = sha256_file(config.catalog)
    elif image.embedded_catalog is not None:
        catalog_table = image.embedded_catalog

    working = image.data
    mask = image.mask
    crop = config.crop
    if crop is not None:
        working, mask = crop_image(working, mask, crop)

    presentation: dict[str, Any]
    mesh_meta: dict[str, Any]
    geometry: dict[str, np.ndarray]
    roundtrip = None
    wcs_block: dict[str, Any] | None = None
    basis = None
    arcsec = None

    if config.pixel_preview:
        presentation = {
            "projection": None,
            "blender_unit": "pixel",
            "arcsec_per_blender_unit": None,
            "origin": "image_center",
            "blender_x": "increasing_pixel_x",
            "blender_y": "increasing_pixel_y",
            "blender_z": "presentation_normal",
            "celestial_axes": False,
            "display_flip_east_left": False,
            "handedness": "right",
            "note": "Pixel preview has no celestial coordinates and no astrometric accuracy.",
        }
        geometry = _pixel_preview_mesh(nx, ny, crop)
        mesh_meta = {
            "approximation": "pixel_preview_rectangle",
            "cells": [1, 1],
            "vertex_count": int(geometry["xyz"].shape[0]),
            "face_count": int(geometry["faces"].shape[0]),
            "uv_convention": {
                "description": "UV 0..1 spans the preview image. This is not a WCS mesh.",
                "crop_inclusive_pixel_index": crop,
            },
            "residual": {
                "method": "not_applicable",
                "max_arcsec": None,
                "rms_arcsec": None,
                "budget_arcsec": None,
                "n_cells": 0,
                "status": "not_applicable",
                "worst": None,
                "budget_note": "Pixel preview makes no interpolation or astrometric claim.",
            },
        }
        overlays = {
            "axes": None,
            "sky_grid": [],
            "grid_meaning": "pixel grid, not celestial",
            "pixel_outline": geometry["xyz"].tolist(),
        }
    else:
        wcs = image.wcs
        require_celestial_wcs(wcs)
        ref_x, ref_y, ref_source = reference_pixel(wcs, (ny, nx))
        if config.tangent_lon_deg is not None or config.tangent_lat_deg is not None:
            if config.tangent_lon_deg is None or config.tangent_lat_deg is None:
                raise InvalidInput("Set both tangent longitude and latitude, or neither.")
            from astropy import units as u
            from astropy.coordinates import SkyCoord

            sample = pixel_to_sky(wcs, ref_x, ref_y)
            tangent = SkyCoord(
                config.tangent_lon_deg * u.deg,
                config.tangent_lat_deg * u.deg,
                frame=sample.frame,
            )
            ref_source = "user_tangent"
        else:
            tangent = pixel_to_sky(wcs, ref_x, ref_y)
        basis = build_basis(tangent)
        scale = local_pixel_scale(wcs, ref_x, ref_y)
        if scale["anisotropy"] > 1.01:
            warnings.append(
                {
                    "code": "ANISOTROPIC_PIXEL_SCALE",
                    "severity": "info",
                    "message": (
                        "Local pixel steps differ: "
                        f"{scale['x_arcsec']:.6g} by {scale['y_arcsec']:.6g} arcsec."
                    ),
                }
            )
        distortion = describe_distortion(wcs)
        if distortion["present"]:
            warnings.append(
                {
                    "code": "DISTORTION_PRESENT",
                    "severity": "info",
                    "message": f"Nonlinear WCS model ({distortion['kind']}) is sampled on the mesh.",
                }
            )
        if config.flat_rectangle:
            warnings.append(
                {
                    "code": "FLAT_RECTANGLE",
                    "severity": "warning",
                    "message": "Flat rectangle approximation is labelled and is not a distortion solution.",
                }
            )
        samples = default_samples(nx, ny)
        roundtrip = roundtrip_samples(wcs, samples)
        if roundtrip["n_failed"] or (
            roundtrip["max_pixel_error"] is not None
            and roundtrip["max_pixel_error"] > roundtrip["tolerance_pixel"]
        ):
            warnings.append(
                {
                    "code": "ROUNDTRIP_FAILED",
                    "severity": "error",
                    "message": "World/pixel round-trip exceeded the numerical tolerance or did not converge.",
                }
            )
        arcsec = float(config.arcsec_per_bu)
        built = build_mesh(
            wcs,
            basis,
            nx=nx,
            ny=ny,
            crop=crop,
            arcsec_per_bu=arcsec,
            flip_east_left=config.east_left,
            mesh_cells=config.mesh_cells,
            flat=config.flat_rectangle,
            pixel_scale_arcsec=float(scale["geometric_mean_arcsec"]),
            budget_arcsec=config.residual_budget_arcsec,
        )
        geometry = {
            "xyz": built["xyz"],
            "uv": built["uv"],
            "pixel_xy": built["pixel_xy"],
            "faces": built["faces"],
        }
        mesh_meta = {
            "approximation": built["approximation"],
            "cells": built["cells"],
            "vertex_count": int(built["xyz"].shape[0]),
            "face_count": int(built["faces"].shape[0]),
            "uv_convention": built["uv_convention"],
            "residual": built["residual"],
        }
        if built["residual"]["status"] == "fail":
            warnings.append(
                {
                    "code": "MESH_RESIDUAL",
                    "severity": "error" if config.fail_on_residual else "warning",
                    "message": (
                        "Mesh interpolation residual "
                        f"{built['residual']['max_arcsec']} arcsec exceeds budget "
                        f"{built['residual']['budget_arcsec']} arcsec."
                    ),
                }
            )
        info = basis.as_dict()
        presentation = {
            "projection": "gnomonic_tan",
            "blender_unit": "arcsec / arcsec_per_blender_unit",
            "arcsec_per_blender_unit": arcsec,
            "tangent_point": info,
            "reference_pixel_xy": [ref_x, ref_y],
            "reference_pixel_source": ref_source,
            "local_pixel_scale_arcsec": scale,
            "pixel_scale_note": (
                "Local angular step of one pixel at the reference pixel. "
                "Not a global plate scale when distortion is present."
            ),
            "blender_x": info["x_axis"] if not config.east_left else f"{info['x_axis']}_flipped",
            "blender_y": info["y_axis"],
            "blender_z": "radial_toward_sky_before_display_flip",
            "display_flip_east_left": bool(config.east_left),
            "handedness": "left" if config.east_left else "right",
            "camera": "located on +Z, looking toward -Z; screen right is +X and screen up is +Y",
            "plane_z": 0.0,
            "distance_meaning": "Blender distance from the plane is not astronomical distance.",
        }
        field = float(scale["geometric_mean_arcsec"]) * max(nx, ny)
        overlays = {
            "axes": axis_segments(field, arcsec, config.east_left),
            "sky_grid": sky_grid(
                wcs,
                basis,
                nx=nx,
                ny=ny,
                arcsec_per_bu=arcsec,
                flip_east_left=config.east_left,
            ),
            "grid_meaning": "constant spherical coordinates sampled through the tangent plane",
        }
        wcs_block = {
            "kind": image.wcs_kind,
            "frame": info["frame"],
            "frame_key": info["frame_key"],
            "equinox": info["equinox"],
            "pixel_convention": "zero_based_pixel_centers_xy",
            "array_convention": "data[row, column] = data[y, x]",
            "fits_crpix_convention": "1-based; high-level pixels use CRPIX-1",
            "distortion": distortion,
            "keywords": image.wcs_keywords,
            "fits_wcs_fabricated": False,
            "fidelity": (
                "Agreement is with the supplied WCS transform only. "
                "It is not absolute accuracy on the sky, and frame/epoch limits "
                "of the input calibration still apply."
            ),
        }

    sources, summary = align_catalog(
        catalog_table,
        wcs=None if config.pixel_preview else image.wcs,
        basis=basis,
        shape=(ny, nx),
        arcsec_per_bu=arcsec,
        flip_east_left=config.east_left,
        pixel_origin=config.pixel_origin,
        authority=config.coord_authority,
        tolerance_arcsec=config.coord_tolerance_arcsec,
        pixel_preview=config.pixel_preview,
        image=image.data,
        mask=image.mask,
    )
    summary["sha256"] = catalog_hash
    summary["path"] = None if not config.catalog else str(config.catalog)
    for record in sources:
        propagate_source(
            record,
            wcs=image.wcs,
            basis=basis,
            arcsec_per_bu=arcsec,
            flip_east_left=config.east_left,
            pixel_uncertainty=config.pixel_uncertainty,
            sky_uncertainty_convention=config.sky_uncertainty_convention,
            pixel_preview=config.pixel_preview,
        )
    if summary.get("warnings"):
        for item in summary["warnings"]:
            warnings.append(
                {"code": item["code"], "severity": "warning", "message": item["message"]}
            )
    unknown = any(record["uncertainty_status"] == "UNKNOWN" for record in sources)
    if sources and unknown:
        warnings.append(
            {
                "code": "UNCERTAINTY_UNKNOWN",
                "severity": "info",
                "message": "Sources without a declared error convention are UNKNOWN, not zero error.",
            }
        )

    factor = choose_downsample(working.shape, config.max_display_pixels, config.downsample)
    display_data, display_mask = downsample_mean(working, mask, factor)
    if factor > 1:
        warnings.append(
            {
                "code": "DOWNSAMPLED_DISPLAY",
                "severity": "warning",
                "message": (
                    f"Display image was block-averaged by {factor}. "
                    "science.npy keeps the sampled scientific array."
                ),
            }
        )
    rgb, display_meta = render_display(
        display_data,
        display_mask,
        stretch=config.stretch,
        percentiles=config.percentiles,
        colormap=config.colormap,
    )
    invalid_fraction = float(np.mean(image.mask == 0))
    if invalid_fraction:
        warnings.append(
            {
                "code": "INVALID_PIXELS",
                "severity": "info",
                "message": f"{invalid_fraction:.6g} of pixels are masked invalid and were not interpolated.",
            }
        )

    placed = [record for record in sources if record["placed"] and record["scene_xyz"] is not None]
    marker_xyz = (
        np.array([record["scene_xyz"] for record in placed], dtype=np.float64)
        if placed
        else np.zeros((0, 3), dtype=np.float64)
    )
    geometry["marker_xyz"] = marker_xyz

    banners = ["2.5D presentation layer — distance_unknown"]
    if config.pixel_preview:
        banners = ["PIXEL PREVIEW — no celestial coordinates and no astrometric accuracy"]
    if _synthetic_banner(image):
        banners.append("Synthetic fixture — not a telescope observation")
    if image.roman is not None:
        banners.append(
            "Roman meta.wcs placement — flight data and instrument distortion are not verified"
        )

    science_path = out_dir / "science.npy"
    mask_path = out_dir / "mask.npy"
    png_path = out_dir / "display.png"
    npz_path = out_dir / "geometry.npz"
    sources_path = out_dir / "sources.json"
    np.save(science_path, np.ascontiguousarray(working, dtype=np.float64))
    np.save(mask_path, np.ascontiguousarray(mask, dtype=np.uint8))
    write_png_rgb(png_path, rgb)
    write_stable_npz(npz_path, geometry)
    _write_json(sources_path, sources)

    files = {
        "display_png": {"name": "display.png", "sha256": sha256_file(png_path)},
        "science_npy": {"name": "science.npy", "sha256": sha256_file(science_path)},
        "mask_npy": {"name": "mask.npy", "sha256": sha256_file(mask_path)},
        "geometry_npz": {"name": "geometry.npz", "sha256": sha256_file(npz_path)},
        "sources_json": {"name": "sources.json", "sha256": sha256_file(sources_path)},
    }
    inputs = [
        {"path": str(image.path), "sha256": sha256_file(image.path), "role": "image"}
    ]
    if config.catalog:
        inputs.append({"path": str(config.catalog), "sha256": catalog_hash, "role": "catalog"})

    image_block = {
        "shape_yx": [int(ny), int(nx)],
        "sampled_shape_yx": [int(working.shape[0]), int(working.shape[1])],
        "display_shape_yx": [int(display_data.shape[0]), int(display_data.shape[1])],
        "hdu_index": image.hdu_index,
        "hdu_name": image.hdu_name,
        "available_hdus": image.hdu_descriptions,
        "units": image.units,
        "units_note": image.product_note,
        "header_meta": image.header_meta,
        "roman": image.roman,
        "crop_inclusive_pixel_index": list(crop) if crop else None,
        "downsample_factor": factor,
        "downsample_method": "valid_pixel_block_mean" if factor > 1 else "none",
        "invalid_fraction": invalid_fraction,
        "display": display_meta,
        "banners": banners,
    }
    core = {
        "schema_version": SCHEMA_VERSION,
        "wcsscene_version": __version__,
        "mode": "pixel_preview" if config.pixel_preview else "scientific_wcs",
        "celestial_accuracy": "none" if config.pixel_preview else "relative_to_supplied_wcs",
        "distance_interpretation": "distance_unknown",
        "banners": banners,
        "presentation": presentation,
        "image": image_block,
        "wcs": wcs_block,
        "mesh": mesh_meta,
        "catalog": summary,
        "overlays": overlays,
        "roundtrip": roundtrip,
        "files": files,
        "inputs": inputs,
        "highlight_source_id": config.highlight_source_id,
        "warnings": warnings,
        "provenance": {
            "versions": runtime_versions(),
            "generator": "wcsscene.prepare",
            "config": _config_dict(config),
            "command": config.command,
        },
    }
    digest = sha256_bytes(canonical_json(core).encode("utf-8"))
    manifest = dict(core)
    manifest["content_id"] = digest
    manifest["provenance"] = dict(core["provenance"])
    manifest["provenance"]["created_utc"] = utc_now()
    manifest_path = out_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    qa = _qa_markdown(manifest, sources)
    (out_dir / "qa_report.md").write_text(qa, encoding="utf-8")
    _write_json(out_dir / "qa_report.json", {"content_id": digest, "warnings": warnings, "roundtrip": roundtrip, "mesh": mesh_meta})

    exit_code = 0
    status = "pass"
    if any(item["severity"] == "error" for item in warnings):
        exit_code = 4
        status = "fail"
    return PrepareResult(out_dir, manifest_path, exit_code, status, warnings)


def _config_dict(config: PrepareConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload.pop("command", None)
    payload["percentiles"] = list(config.percentiles)
    if config.crop is not None:
        payload["crop"] = list(config.crop)
    return payload
