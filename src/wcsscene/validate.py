"""Validate an exchange bundle without Blender."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .errors import InvalidInput
from .exchange import PrepareConfig, canonical_json, load_image
from .provenance import sha256_file
from .wcs_adapter import roundtrip_samples


def _check(checks: list[dict[str, Any]], name: str, passed: bool, severity: str, **detail: Any) -> None:
    checks.append({"name": name, "passed": passed, "severity": severity, **detail})


def validate_bundle(manifest_path: str | Path, *, recompute: bool = True) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_file():
        raise InvalidInput(f"Manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    checks: list[dict[str, Any]] = []
    version = str(manifest.get("schema_version", ""))
    major = version.split(".")[0] if version else ""
    _check(
        checks,
        "schema_major",
        major == "1",
        "error",
        detail=f"schema {version}; this reader accepts 1.x",
    )
    digest = manifest.get("content_id")
    created = None
    provenance = manifest.get("provenance") or {}
    if isinstance(provenance, dict):
        created = provenance.get("created_utc")
    core = json.loads(json.dumps(manifest))
    core.pop("content_id", None)
    if isinstance(core.get("provenance"), dict):
        core["provenance"].pop("created_utc", None)
        core["provenance"].pop("elapsed_s", None)
    recomputed = None
    try:
        recomputed = canonical_json(core)
        content_ok = digest == hashlib.sha256(recomputed.encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        content_ok = False
        recomputed = str(exc)
    _check(checks, "content_id", bool(content_ok), "error", created_utc=created)

    files = manifest.get("files") or {}
    for role, info in files.items():
        name = info.get("name")
        file_path = root / name
        if not file_path.is_file():
            _check(checks, f"file:{role}", False, "error", detail="missing")
            continue
        digest_ok = sha256_file(file_path) == info.get("sha256")
        _check(checks, f"file:{role}", digest_ok, "error")

    mode = manifest.get("mode")
    accuracy = manifest.get("celestial_accuracy")
    if mode == "pixel_preview":
        _check(checks, "pixel_preview_claims", accuracy == "none", "error")
        preview_scale = (manifest.get("presentation") or {}).get("arcsec_per_blender_unit")
        _check(checks, "pixel_preview_no_angular_scale", preview_scale is None, "error")
    elif mode == "scientific_wcs":
        scale = (manifest.get("presentation") or {}).get("arcsec_per_blender_unit")
        _check(
            checks,
            "scientific_claims",
            accuracy == "relative_to_supplied_wcs" and isinstance(scale, (int, float)) and scale > 0,
            "error",
        )
        _check(
            checks,
            "distance_unknown",
            manifest.get("distance_interpretation") == "distance_unknown",
            "error",
        )
    else:
        _check(checks, "mode", False, "error", detail=str(mode))

    sources_path = root / (files.get("sources_json") or {}).get("name", "sources.json")
    sources: list[dict[str, Any]] = []
    if sources_path.is_file():
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
    placed = [row for row in sources if row.get("placed")]
    unplaced_ok = all(row.get("scene_xyz") is None for row in sources if not row.get("placed"))
    _check(checks, "unplaced_not_at_origin", unplaced_ok, "error")
    placed_finite = all(
        row.get("scene_xyz") is not None and all(np.isfinite(row["scene_xyz"])) for row in placed
    )
    _check(checks, "placed_finite", placed_finite, "error")
    if len(placed) >= 2:
        xs = [row["scene_xyz"][0] for row in placed]
        ys = [row["scene_xyz"][1] for row in placed]
        spread = (max(xs) - min(xs)) > 0 or (max(ys) - min(ys)) > 0
        _check(checks, "markers_not_collapsed", spread, "error")
    distance_ok = all(row.get("distance_status") == "distance_unknown" for row in sources)
    _check(checks, "distance_status", distance_ok, "error")
    uncertainty_ok = all(
        not (
            row.get("uncertainty_status") == "UNKNOWN"
            and row.get("uncertainty") not in (None, {})
        )
        for row in sources
    )
    _check(checks, "unknown_uncertainty_not_numeric", uncertainty_ok, "error")
    if mode == "pixel_preview":
        sky_unused = all(not row.get("sky_used_for_placement") for row in sources)
        _check(checks, "preview_sky_unused", sky_unused, "error")

    geometry_name = (files.get("geometry_npz") or {}).get("name", "geometry.npz")
    geometry_path = root / geometry_name
    if geometry_path.is_file() and placed:
        with np.load(geometry_path) as archive:
            markers = np.array(archive["marker_xyz"], dtype=float) if "marker_xyz" in archive else None
        if markers is None or markers.shape != (len(placed), 3):
            _check(checks, "marker_array", False, "error", detail="marker_xyz shape")
        else:
            expected = np.array([row["scene_xyz"] for row in placed], dtype=float)
            delta = float(np.max(np.abs(markers - expected))) if len(placed) else 0.0
            _check(checks, "marker_array", delta <= 1e-9, "error", max_abs=delta)

    roundtrip = manifest.get("roundtrip")
    if mode == "scientific_wcs" and isinstance(roundtrip, dict):
        max_error = roundtrip.get("max_pixel_error")
        tolerance = roundtrip.get("tolerance_pixel")
        failed = roundtrip.get("n_failed") or 0
        passed = (
            failed == 0
            and max_error is not None
            and tolerance is not None
            and max_error <= tolerance
        )
        _check(
            checks,
            "roundtrip_recorded",
            bool(passed),
            "error",
            max_pixel_error=max_error,
            tolerance_pixel=tolerance,
        )
        residual = (manifest.get("mesh") or {}).get("residual") or {}
        if residual.get("status") == "fail":
            enforced = any(
                item.get("code") == "MESH_RESIDUAL" and item.get("severity") == "error"
                for item in manifest.get("warnings") or []
            )
            _check(
                checks,
                "mesh_residual",
                False,
                "error" if enforced else "warning",
                max_arcsec=residual.get("max_arcsec"),
                budget_arcsec=residual.get("budget_arcsec"),
            )
        else:
            _check(
                checks,
                "mesh_residual",
                residual.get("status") in {"pass", "not_applicable"},
                "error",
                status=residual.get("status"),
            )

    if recompute and mode == "scientific_wcs":
        _recompute(manifest, checks)

    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    return {
        "status": "pass" if not errors else "fail",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
        "manifest": str(path),
    }


def _recompute(manifest: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    inputs = manifest.get("inputs") or []
    image_input = next((item for item in inputs if item.get("role") == "image"), None)
    if image_input is None:
        _check(checks, "recompute_roundtrip", False, "warning", detail="no image input recorded")
        return
    image_path = Path(image_input["path"])
    if not image_path.is_file():
        _check(checks, "recompute_roundtrip", True, "info", detail="source file not present; skipped")
        return
    digest = sha256_file(image_path)
    if digest != image_input.get("sha256"):
        _check(checks, "input_hash", False, "error", detail="image bytes changed since prepare")
        return
    _check(checks, "input_hash", True, "info")
    image_block = manifest.get("image") or {}
    config = PrepareConfig(
        hdu=image_block.get("hdu_name") if image_block.get("hdu_name") not in {None, "ImageModel", "MosaicModel"} else image_block.get("hdu_index"),
        fmt="roman" if (manifest.get("wcs") or {}).get("kind") == "gwcs" else "auto",
    )
    if image_path.suffix.lower() == ".asdf":
        config.fmt = "roman"
    try:
        loaded = load_image(image_path, config)
    except Exception as exc:  # noqa: BLE001 - validation should report, not crash
        _check(checks, "recompute_roundtrip", False, "warning", detail=str(exc))
        return
    if loaded.wcs is None:
        _check(checks, "recompute_roundtrip", False, "error", detail="reloaded image has no WCS")
        return
    samples = [
        (float(row["x"]), float(row["y"]), str(row["kind"]))
        for row in (manifest.get("roundtrip") or {}).get("samples") or []
        if row.get("failure") is None
    ]
    if not samples:
        _check(checks, "recompute_roundtrip", False, "warning", detail="no samples stored")
        return
    fresh = roundtrip_samples(loaded.wcs, samples)
    recorded = (manifest.get("roundtrip") or {}).get("max_pixel_error")
    fresh_max = fresh.get("max_pixel_error")
    close = (
        fresh["n_failed"] == 0
        and fresh_max is not None
        and recorded is not None
        and abs(fresh_max - recorded) <= 1e-6
    )
    _check(
        checks,
        "recompute_roundtrip",
        bool(close),
        "error",
        fresh_max_pixel_error=fresh_max,
        recorded_max_pixel_error=recorded,
    )
