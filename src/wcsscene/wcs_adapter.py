"""High-level WCS access.

Pixel coordinates follow the shared WCS API: zero-based pixel centres in
``(x, y)`` order. Array indices remain ``(row, column)`` = ``(y, x)``.
FITS ``CRPIX`` stays 1-based and is converted only at the boundary where a
reference pixel is read from a FITS WCS object.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.wcs import NoConvergence

from .errors import InconsistentWCS, UnsupportedWCS
from .frames import SUPPORTED

_LINEAR_GWCS = {
    "Shift",
    "Scale",
    "Identity",
    "Mapping",
    "AffineTransformation2D",
}
_PROJECTION_GWCS = {
    "Pix2Sky_TAN",
    "Sky2Pix_TAN",
    "Pix2Sky_Gnomonic",
    "Sky2Pix_Gnomonic",
    "RotateNative2Celestial",
    "RotateCelestial2Native",
}


def _model_type_names(model: Any) -> list[str]:
    if model is None:
        return []
    if type(model).__name__ == "CompoundModel" and hasattr(model, "left"):
        return _model_type_names(model.left) + _model_type_names(model.right)
    return [type(model).__name__]


def describe_distortion(wcs: Any) -> dict[str, Any]:
    """Report whether the evaluated transform is more than a linear TAN plane.

    A GWCS pipeline made only of shifts, scales, and TAN is not called
    instrument distortion. SIP and any other model are.
    """
    sip = getattr(wcs, "sip", None)
    if sip is not None:
        return {
            "present": True,
            "kind": "sip",
            "steps": ["fits-sip"],
            "note": "FITS SIP is evaluated by pixel_to_world / world_to_pixel.",
        }
    pipeline = getattr(wcs, "pipeline", None)
    if pipeline:
        steps: list[str] = []
        nonlinear = False
        for step in pipeline:
            frame = getattr(step, "frame", None)
            transform = getattr(step, "transform", None)
            if frame is None and not hasattr(step, "transform"):
                frame, transform = step
            names = _model_type_names(transform)
            label = "+".join(names) if names else "none"
            frame_name = getattr(frame, "name", "?")
            steps.append(f"{frame_name}:{label}")
            for name in names:
                if name not in _LINEAR_GWCS and name not in _PROJECTION_GWCS:
                    nonlinear = True
        return {
            "present": nonlinear,
            "kind": "gwcs-nonlinear" if nonlinear else "gwcs-tan",
            "steps": steps,
            "note": (
                "The full GWCS forward model is sampled. "
                "A TAN-only pipeline is not an instrument distortion solution."
            ),
        }
    if getattr(wcs, "has_distortion", False):
        return {
            "present": True,
            "kind": "fits-distortion",
            "steps": ["wcs.has_distortion"],
            "note": "astropy.wcs reports distortion; the high-level API is used.",
        }
    return {
        "present": False,
        "kind": "none",
        "steps": [],
        "note": "No SIP or extra GWCS distortion model was detected.",
    }


def require_celestial_wcs(wcs: Any) -> SkyCoord:
    """Accept a 2D celestial WCS or raise. Extra axes are not discarded."""
    try:
        pixel_n = int(wcs.pixel_n_dim)
        world_n = int(wcs.world_n_dim)
    except Exception as exc:  # noqa: BLE001 - the object simply is not a WCS
        raise UnsupportedWCS(f"Object does not expose WCS dimensions: {exc}") from exc
    if pixel_n != 2 or world_n != 2:
        raise UnsupportedWCS(
            f"WCS pixel_n_dim={pixel_n}, world_n_dim={world_n}. "
            "Multi-dimensional WCS is rejected rather than dropping axes."
        )
    try:
        sample = wcs.pixel_to_world(0.0, 0.0)
    except Exception as exc:
        raise InconsistentWCS(f"pixel_to_world failed at pixel (0, 0): {exc}") from exc
    if not isinstance(sample, SkyCoord) or not sample.isscalar:
        raise UnsupportedWCS(
            "Celestial WCS must return a scalar SkyCoord from pixel_to_world. "
            f"Got {type(sample).__name__}."
        )
    if sample.frame.name not in SUPPORTED:
        supported = ", ".join(sorted(SUPPORTED))
        raise UnsupportedWCS(
            f"Frame {sample.frame.name!r} is not supported ({supported})."
        )
    lon = float(sample.spherical.lon.deg)
    lat = float(sample.spherical.lat.deg)
    if not np.isfinite(lon) or not np.isfinite(lat):
        raise InconsistentWCS("WCS sample at pixel (0, 0) is non-finite.")
    return sample


def reference_pixel(wcs: Any, shape: tuple[int, int]) -> tuple[float, float, str]:
    """Zero-based reference pixel.

    FITS ``CRPIX`` is 1-based, so the high-level pixel is ``CRPIX - 1``.
    GWCS has no CRPIX; the image centre is the default tangent sample.
    """
    ny, nx = shape
    crpix = getattr(getattr(wcs, "wcs", None), "crpix", None)
    if crpix is not None and len(crpix) >= 2 and np.all(np.isfinite(crpix[:2])):
        return float(crpix[0]) - 1.0, float(crpix[1]) - 1.0, "fits_crpix_minus_one"
    return (nx - 1) / 2.0, (ny - 1) / 2.0, "image_center"


def pixel_to_sky(wcs: Any, x: np.ndarray, y: np.ndarray) -> SkyCoord:
    return wcs.pixel_to_world(np.asarray(x, dtype=float), np.asarray(y, dtype=float))


def sky_to_pixel(wcs: Any, sky: SkyCoord) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Return ``(x, y, failure)``. ``failure`` is set instead of a guessed solution."""
    try:
        x, y = wcs.world_to_pixel(sky)
    except NoConvergence:
        return np.array(np.nan), np.array(np.nan), "NO_CONVERGENCE"
    except (ValueError, RuntimeError) as exc:
        return np.array(np.nan), np.array(np.nan), type(exc).__name__
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if not np.all(np.isfinite(x_arr)) or not np.all(np.isfinite(y_arr)):
        return x_arr, y_arr, "NON_FINITE"
    return x_arr, y_arr, None


def local_pixel_scale(wcs: Any, x: float, y: float) -> dict[str, float | None]:
    """Angular step of one pixel at ``(x, y)``, labelled as a local linear scale."""
    sky0 = pixel_to_sky(wcs, x, y)
    skyx = pixel_to_sky(wcs, x + 1.0, y)
    skyy = pixel_to_sky(wcs, x, y + 1.0)
    sx = float(sky0.separation(skyx).arcsec)
    sy = float(sky0.separation(skyy).arcsec)
    if sx <= 0 or sy <= 0 or not np.isfinite(sx) or not np.isfinite(sy):
        raise InconsistentWCS(
            f"Local pixel scale is not positive at ({x}, {y}): dx={sx}, dy={sy}."
        )
    return {
        "x_arcsec": sx,
        "y_arcsec": sy,
        "geometric_mean_arcsec": float(np.sqrt(sx * sy)),
        "anisotropy": float(max(sx, sy) / min(sx, sy)),
    }


def roundtrip_samples(
    wcs: Any, samples: list[tuple[float, float, str]]
) -> dict[str, Any]:
    """Pixel -> sky -> pixel errors for an explicit sample list."""
    rows = []
    pixel_errors = []
    angular_errors = []
    for x, y, kind in samples:
        sky = pixel_to_sky(wcs, x, y)
        x2, y2, failure = sky_to_pixel(wcs, sky)
        if failure:
            rows.append(
                {
                    "kind": kind,
                    "x": x,
                    "y": y,
                    "failure": failure,
                    "pixel_error": None,
                    "angular_error_arcsec": None,
                }
            )
            continue
        x2f = float(np.asarray(x2))
        y2f = float(np.asarray(y2))
        pixel_error = float(np.hypot(x2f - x, y2f - y))
        sky2 = pixel_to_sky(wcs, x2f, y2f)
        angular = float(sky.separation(sky2).arcsec)
        pixel_errors.append(pixel_error)
        angular_errors.append(angular)
        rows.append(
            {
                "kind": kind,
                "x": float(x),
                "y": float(y),
                "ra_or_lon_deg": float(sky.spherical.lon.deg),
                "dec_or_lat_deg": float(sky.spherical.lat.deg),
                "x_back": x2f,
                "y_back": y2f,
                "pixel_error": pixel_error,
                "angular_error_arcsec": angular,
                "failure": None,
            }
        )
    failed = [row for row in rows if row["failure"]]
    return {
        "pixel_convention": "zero_based_pixel_centers_xy",
        "samples": rows,
        "max_pixel_error": max(pixel_errors) if pixel_errors else None,
        "max_angular_error_arcsec": max(angular_errors) if angular_errors else None,
        "n_failed": len(failed),
        "tolerance_pixel": 1e-3,
        "tolerance_note": (
            "1e-3 pixel admits SIP iterative inversion. Distortion-free TAN "
            "on these fixtures is typically << 1e-6 pixel. This is numerical "
            "agreement with the supplied WCS, not absolute sky accuracy."
        ),
    }


def default_samples(nx: int, ny: int, seed: int = 12345) -> list[tuple[float, float, str]]:
    rng = np.random.default_rng(seed)
    x_mid = (nx - 1) / 2.0
    y_mid = (ny - 1) / 2.0
    samples = [
        (0.0, 0.0, "corner"),
        (float(nx - 1), 0.0, "corner"),
        (0.0, float(ny - 1), "corner"),
        (float(nx - 1), float(ny - 1), "corner"),
        (x_mid, y_mid, "center"),
        (x_mid, 0.0, "edge"),
        (0.0, y_mid, "edge"),
        (float(nx - 1), y_mid, "edge"),
        (x_mid, float(ny - 1), "edge"),
    ]
    for _ in range(8):
        samples.append(
            (float(rng.uniform(0.0, nx - 1)), float(rng.uniform(0.0, ny - 1)), "random")
        )
    return samples
