"""Covariance propagation through a numerical Jacobian.

Missing errors stay ``UNKNOWN``. They are not stored as zero. Sky errors are
propagated only when the caller names a convention. ``ra_cosdec_arcsec`` means
the RA term is already :math:`\\sigma(\\alpha \\cos\\delta)` in arcseconds.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

from .projection import TangentBasis, sky_to_scene

_PIXEL_STEP = 1e-2
_SKY_STEP_ARCSEC = 1e-2
_STABILITY = 1e-2


def propagate_source(
    record: dict[str, Any],
    *,
    wcs: Any,
    basis: TangentBasis | None,
    arcsec_per_bu: float | None,
    flip_east_left: bool,
    pixel_uncertainty: bool,
    sky_uncertainty_convention: str | None,
    pixel_preview: bool,
) -> None:
    errors = record.get("errors") or {}
    has_pixel = errors.get("x_err") is not None and errors.get("y_err") is not None
    has_sky = errors.get("ra_err") is not None and errors.get("dec_err") is not None
    if pixel_preview:
        record["uncertainty_status"] = "UNKNOWN"
        record["uncertainty"] = None
        return
    if not has_pixel and not has_sky:
        record["uncertainty_status"] = "UNKNOWN"
        record["uncertainty"] = None
        return
    if has_pixel and not pixel_uncertainty and not (has_sky and sky_uncertainty_convention):
        record["uncertainty_status"] = "AMBIGUOUS_CONVENTION"
        record["uncertainty"] = {
            "reason": "pixel error columns exist but --pixel-uncertainty was not set"
        }
        return
    if has_sky and not has_pixel and sky_uncertainty_convention is None:
        record["uncertainty_status"] = "AMBIGUOUS_CONVENTION"
        record["uncertainty"] = {
            "reason": "RA/Dec error columns exist without --sky-uncertainty-convention"
        }
        return
    if not record.get("placed") or basis is None or arcsec_per_bu is None:
        record["uncertainty_status"] = "NOT_PLACED"
        record["uncertainty"] = None
        return
    if has_pixel and pixel_uncertainty:
        _propagate_pixel(record, wcs, basis, arcsec_per_bu, flip_east_left)
        return
    if has_sky and sky_uncertainty_convention:
        _propagate_sky(
            record, basis, arcsec_per_bu, flip_east_left, sky_uncertainty_convention
        )
        return
    record["uncertainty_status"] = "UNKNOWN"
    record["uncertainty"] = None


def _covariance(sx: float, sy: float, corr: float | None) -> np.ndarray | None:
    if sx < 0 or sy < 0 or not np.isfinite(sx) or not np.isfinite(sy):
        return None
    rho = 0.0 if corr is None else float(corr)
    if not np.isfinite(rho) or abs(rho) > 1:
        return None
    return np.array([[sx * sx, rho * sx * sy], [rho * sx * sy, sy * sy]], dtype=float)


def _ellipse(cov: np.ndarray, arcsec_per_bu: float) -> dict[str, float] | None:
    values, vectors = np.linalg.eigh(cov)
    if np.any(values < -1e-12):
        return None
    values = np.clip(values, 0.0, None)
    order = int(np.argmax(values))
    major_vec = vectors[:, order]
    angle = float(np.arctan2(major_vec[1], major_vec[0]))
    return {
        "semi_major_bu": float(np.sqrt(values[order])),
        "semi_minor_bu": float(np.sqrt(values[1 - order])),
        "semi_major_arcsec": float(np.sqrt(values[order]) * arcsec_per_bu),
        "semi_minor_arcsec": float(np.sqrt(values[1 - order]) * arcsec_per_bu),
        "position_angle_rad_from_east_toward_north": angle,
        "covariance_scene": [float(v) for v in cov.reshape(-1)],
    }


def _stable_jacobian(jac: np.ndarray, jac_half: np.ndarray) -> bool:
    scale = max(1e-12, float(np.max(np.abs(jac))))
    return float(np.max(np.abs(jac - jac_half))) / scale < _STABILITY


def _scene_xy(
    sky: SkyCoord, basis: TangentBasis, arcsec_per_bu: float, flip_east_left: bool
) -> np.ndarray | None:
    scene, valid = sky_to_scene(sky, basis, arcsec_per_bu, flip_east_left=flip_east_left)
    if not bool(np.asarray(valid).reshape(-1)[0]):
        return None
    flat = np.asarray(scene, dtype=float).reshape(-1)
    if not np.all(np.isfinite(flat[:2])):
        return None
    return flat[:2]


def _propagate_pixel(
    record: dict[str, Any],
    wcs: Any,
    basis: TangentBasis,
    arcsec_per_bu: float,
    flip_east_left: bool,
) -> None:
    errors = record["errors"]
    pixel = record["pixel_xy_input"] or record["pixel_xy_from_sky"]
    cov = _covariance(float(errors["x_err"]), float(errors["y_err"]), errors.get("xy_corr"))
    if pixel is None or cov is None:
        record["uncertainty_status"] = "INVALID_COVARIANCE"
        record["uncertainty"] = None
        return

    def project(x: float, y: float) -> np.ndarray | None:
        sky = wcs.pixel_to_world(x, y)
        return _scene_xy(sky, basis, arcsec_per_bu, flip_east_left)

    jac = _pixel_jacobian(project, pixel[0], pixel[1], _PIXEL_STEP)
    jac_half = _pixel_jacobian(project, pixel[0], pixel[1], _PIXEL_STEP / 2)
    if jac is None or jac_half is None or not _stable_jacobian(jac, jac_half):
        record["uncertainty_status"] = "UNSTABLE"
        record["uncertainty"] = {"step_pixel": _PIXEL_STEP}
        return
    scene_cov = jac @ cov @ jac.T
    ellipse = _ellipse(scene_cov, arcsec_per_bu)
    if ellipse is None:
        record["uncertainty_status"] = "UNSTABLE"
        record["uncertainty"] = None
        return
    ellipse["convention"] = "pixel_cov_xy"
    ellipse["jacobian_scene_per_pixel"] = [float(v) for v in jac.reshape(-1)]
    ellipse["step_pixel"] = _PIXEL_STEP
    record["uncertainty_status"] = "PROPAGATED"
    record["uncertainty"] = ellipse


def _pixel_jacobian(project, x: float, y: float, step: float) -> np.ndarray | None:
    samples = [
        project(x + step, y),
        project(x - step, y),
        project(x, y + step),
        project(x, y - step),
    ]
    if any(sample is None for sample in samples):
        return None
    xp, xm, yp, ym = samples
    return np.array(
        [
            [(xp[0] - xm[0]) / (2 * step), (yp[0] - ym[0]) / (2 * step)],
            [(xp[1] - xm[1]) / (2 * step), (yp[1] - ym[1]) / (2 * step)],
        ],
        dtype=float,
    )


def _propagate_sky(
    record: dict[str, Any],
    basis: TangentBasis,
    arcsec_per_bu: float,
    flip_east_left: bool,
    convention: str,
) -> None:
    if convention != "ra_cosdec_arcsec":
        record["uncertainty_status"] = "AMBIGUOUS_CONVENTION"
        record["uncertainty"] = {"reason": f"unsupported convention {convention}"}
        return
    sky_deg = record["sky_input_deg"] or record["sky_from_pixel_deg"]
    if sky_deg is None:
        record["uncertainty_status"] = "UNKNOWN"
        record["uncertainty"] = None
        return
    dec = float(sky_deg[1])
    cos_dec = float(np.cos(np.deg2rad(dec)))
    if abs(cos_dec) < 1e-4:
        record["uncertainty_status"] = "SINGULAR"
        record["uncertainty"] = {"reason": "RA*cos(Dec) is singular near the pole"}
        return
    errors = record["errors"]
    cov = _covariance(
        float(errors["ra_err"]), float(errors["dec_err"]), errors.get("ra_dec_corr")
    )
    if cov is None:
        record["uncertainty_status"] = "INVALID_COVARIANCE"
        record["uncertainty"] = None
        return
    base = SkyCoord(sky_deg[0] * u.deg, sky_deg[1] * u.deg, frame=basis.sky.frame)

    def project(east_arcsec: float, north_arcsec: float) -> np.ndarray | None:
        ra = base.ra.deg + (east_arcsec / 3600.0) / cos_dec
        dec2 = base.dec.deg + north_arcsec / 3600.0
        sky = SkyCoord(ra * u.deg, dec2 * u.deg, frame=base.frame)
        return _scene_xy(sky, basis, arcsec_per_bu, flip_east_left)

    jac = _pixel_jacobian(project, 0.0, 0.0, _SKY_STEP_ARCSEC)
    jac_half = _pixel_jacobian(project, 0.0, 0.0, _SKY_STEP_ARCSEC / 2)
    if jac is None or jac_half is None or not _stable_jacobian(jac, jac_half):
        record["uncertainty_status"] = "UNSTABLE"
        record["uncertainty"] = {"step_arcsec": _SKY_STEP_ARCSEC}
        return
    scene_cov = jac @ cov @ jac.T
    ellipse = _ellipse(scene_cov, arcsec_per_bu)
    if ellipse is None:
        record["uncertainty_status"] = "UNSTABLE"
        record["uncertainty"] = None
        return
    ellipse["convention"] = convention
    ellipse["jacobian_scene_per_arcsec"] = [float(v) for v in jac.reshape(-1)]
    ellipse["step_arcsec"] = _SKY_STEP_ARCSEC
    record["uncertainty_status"] = "PROPAGATED"
    record["uncertainty"] = ellipse
