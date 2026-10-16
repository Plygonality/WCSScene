"""Sample the WCS onto a presentation mesh.

Vertices are original pixel coordinates, including edges at ±0.5, mapped
through the full high-level WCS and the gnomonic plane. UVs address the
unaltered cropped pixel grid. Bilinear residuals are measured at cell
centres, which are not mesh vertices.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

from .projection import TangentBasis, sky_to_scene
from .wcs_adapter import pixel_to_sky


def default_residual_budget(pixel_scale_arcsec: float) -> float:
    """Interpolation budget, not an absolute astrometric floor.

    Five percent of the local pixel scale, and never a claim tighter than
    0.01 arcsec from the mesh itself. Exact WCS round-trips use a separate
    pixel tolerance.
    """
    return float(max(0.01, 0.05 * pixel_scale_arcsec))


def cell_counts(nx: int, ny: int, mesh_cells: int, flat: bool) -> tuple[int, int]:
    if flat or mesh_cells <= 1 or max(nx, ny) <= 1:
        return 1, 1
    longest = max(nx, ny)
    cells_x = max(1, int(round(mesh_cells * nx / longest)))
    cells_y = max(1, int(round(mesh_cells * ny / longest)))
    return cells_x, cells_y


def build_mesh(
    wcs: Any,
    basis: TangentBasis,
    *,
    nx: int,
    ny: int,
    crop: tuple[int, int, int, int] | None,
    arcsec_per_bu: float,
    flip_east_left: bool,
    mesh_cells: int,
    flat: bool,
    pixel_scale_arcsec: float,
    budget_arcsec: float | None,
) -> dict[str, Any]:
    xmin, xmax, ymin, ymax = (0, nx - 1, 0, ny - 1) if crop is None else crop
    x0 = xmin - 0.5
    x1 = xmax + 0.5
    y0 = ymin - 0.5
    y1 = ymax + 0.5
    cells_x, cells_y = cell_counts(xmax - xmin + 1, ymax - ymin + 1, mesh_cells, flat)
    xs = np.linspace(x0, x1, cells_x + 1)
    ys = np.linspace(y0, y1, cells_y + 1)
    grid_x, grid_y = np.meshgrid(xs, ys, indexing="xy")
    sky = pixel_to_sky(wcs, grid_x.ravel(), grid_y.ravel())
    scene, valid = sky_to_scene(sky, basis, arcsec_per_bu, flip_east_left=flip_east_left)
    scene = np.asarray(scene, dtype=float).reshape(-1, 3)
    valid = np.asarray(valid, dtype=bool).reshape(-1)
    width = float(xmax - xmin + 1)
    height = float(ymax - ymin + 1)
    uv = np.column_stack(
        (
            (grid_x.ravel() - x0) / width,
            (grid_y.ravel() - y0) / height,
        )
    )
    pixel_xy = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    faces = []
    residual_rows = []
    stride = cells_x + 1
    for j in range(cells_y):
        for i in range(cells_x):
            corners = [
                j * stride + i,
                j * stride + i + 1,
                (j + 1) * stride + i + 1,
                (j + 1) * stride + i,
            ]
            if not all(valid[index] for index in corners):
                continue
            faces.append((corners[0], corners[1], corners[2]))
            faces.append((corners[0], corners[2], corners[3]))
            midpoint = np.array(
                [0.5 * (xs[i] + xs[i + 1]), 0.5 * (ys[j] + ys[j + 1])],
                dtype=float,
            )
            true_sky = pixel_to_sky(wcs, midpoint[0], midpoint[1])
            true_scene, true_valid = sky_to_scene(
                true_sky, basis, arcsec_per_bu, flip_east_left=flip_east_left
            )
            if not bool(np.asarray(true_valid).reshape(-1)[0]):
                continue
            bilinear = scene[corners].mean(axis=0)
            true_xyz = np.asarray(true_scene, dtype=float).reshape(-1)
            delta_bu = float(np.hypot(true_xyz[0] - bilinear[0], true_xyz[1] - bilinear[1]))
            residual_rows.append(
                {
                    "pixel_xy": [float(midpoint[0]), float(midpoint[1])],
                    "residual_arcsec": delta_bu * arcsec_per_bu,
                }
            )
    if faces:
        used = np.zeros(scene.shape[0], dtype=bool)
        face_arr = np.array(faces, dtype=np.int32)
        used[face_arr.reshape(-1)] = True
        remap = -np.ones(scene.shape[0], dtype=np.int32)
        remap[used] = np.arange(int(used.sum()), dtype=np.int32)
        face_arr = remap[face_arr]
        scene = scene[used]
        uv = uv[used]
        pixel_xy = pixel_xy[used]
    else:
        face_arr = np.zeros((0, 3), dtype=np.int32)
        scene = np.zeros((0, 3), dtype=float)
        uv = np.zeros((0, 2), dtype=float)
        pixel_xy = np.zeros((0, 2), dtype=float)
    residuals = [row["residual_arcsec"] for row in residual_rows]
    max_residual = float(max(residuals)) if residuals else None
    rms = float(np.sqrt(np.mean(np.square(residuals)))) if residuals else None
    budget = (
        float(budget_arcsec)
        if budget_arcsec is not None
        else default_residual_budget(pixel_scale_arcsec)
    )
    if max_residual is None:
        status = "fail"
    elif max_residual <= budget:
        status = "pass"
    else:
        status = "fail"
    return {
        "xyz": scene,
        "uv": uv,
        "pixel_xy": pixel_xy,
        "faces": face_arr,
        "cells": [cells_x, cells_y],
        "approximation": (
            "flat_rectangle_labeled_approximation" if flat else "sampled_wcs_mesh"
        ),
        "uv_convention": {
            "description": "UV 0..1 spans the cropped pixel rectangle, not a distorted mesh.",
            "crop_inclusive_pixel_index": [xmin, xmax, ymin, ymax],
            "formula_original_x": "(xmin - 0.5) + u * (xmax - xmin + 1)",
            "formula_original_y": "(ymin - 0.5) + v * (ymax - ymin + 1)",
        },
        "residual": {
            "method": "bilinear_withheld_cell_centers",
            "max_arcsec": max_residual,
            "rms_arcsec": rms,
            "budget_arcsec": budget,
            "n_cells": len(residuals),
            "status": status,
            "worst": max(residual_rows, key=lambda row: row["residual_arcsec"])
            if residual_rows
            else None,
            "budget_note": (
                "Mesh residual is interpolation error against the supplied WCS. "
                "It is not a statement of absolute astrometric accuracy."
            ),
        },
    }


def nice_length(target: float) -> float:
    for step in (1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 1800, 3600):
        if step >= target:
            return float(step)
    return float(target)


def sky_grid(
    wcs: Any,
    basis: TangentBasis,
    *,
    nx: int,
    ny: int,
    arcsec_per_bu: float,
    flip_east_left: bool,
    lines: int = 5,
    samples: int = 24,
) -> list[dict[str, Any]]:
    corners = []
    for x, y in ((0, 0), (nx - 1, 0), (0, ny - 1), (nx - 1, ny - 1)):
        sky = pixel_to_sky(wcs, x, y)
        corners.append(sky)
    origin = float(basis.sky.spherical.lon.deg)
    lons = []
    lats = []
    for sky in corners:
        lon = float(sky.spherical.lon.deg)
        lons.append(origin + ((lon - origin + 180.0) % 360.0) - 180.0)
        lats.append(float(sky.spherical.lat.deg))
    lon_values = np.linspace(min(lons), max(lons), lines)
    lat_values = np.linspace(min(lats), max(lats), lines)
    polylines = []
    for lon in lon_values:
        polylines.append(
            _sample_line(
                basis,
                np.full(samples, lon),
                np.linspace(min(lats), max(lats), samples),
                arcsec_per_bu,
                flip_east_left,
                "constant_lon",
                float(lon),
            )
        )
    for lat in lat_values:
        polylines.append(
            _sample_line(
                basis,
                np.linspace(min(lons), max(lons), samples),
                np.full(samples, lat),
                arcsec_per_bu,
                flip_east_left,
                "constant_lat",
                float(lat),
            )
        )
    return [line for line in polylines if line["xyz"]]


def _sample_line(
    basis: TangentBasis,
    lons: np.ndarray,
    lats: np.ndarray,
    arcsec_per_bu: float,
    flip_east_left: bool,
    kind: str,
    value: float,
) -> dict[str, Any]:
    sky = SkyCoord(lons * u.deg, lats * u.deg, frame=basis.sky.frame)
    scene, valid = sky_to_scene(sky, basis, arcsec_per_bu, flip_east_left=flip_east_left)
    scene = np.asarray(scene, dtype=float).reshape(-1, 3)
    valid = np.asarray(valid, dtype=bool).reshape(-1)
    xyz = [
        [float(point[0]), float(point[1]), float(point[2])]
        for point, ok in zip(scene, valid, strict=True)
        if ok and np.all(np.isfinite(point))
    ]
    return {
        "kind": kind,
        "value_deg": value,
        "frame": basis.frame_name,
        "xyz": xyz,
        "meaning": "constant spherical coordinate sampled into the tangent plane",
    }


def axis_segments(field_arcsec: float, arcsec_per_bu: float, flip_east_left: bool) -> dict[str, Any]:
    target = max(field_arcsec * 0.22, arcsec_per_bu)
    length = nice_length(target)
    if length > field_arcsec * 0.45:
        length = max(field_arcsec * 0.2, arcsec_per_bu)
    bu = length / arcsec_per_bu
    sign = -1.0 if flip_east_left else 1.0
    return {
        "east": {
            "p0": [0.0, 0.0, 0.0],
            "p1": [sign * bu, 0.0, 0.0],
            "length_arcsec": length,
            "label": "E",
        },
        "north": {
            "p0": [0.0, 0.0, 0.0],
            "p1": [0.0, bu, 0.0],
            "length_arcsec": length,
            "label": "N",
        },
    }
