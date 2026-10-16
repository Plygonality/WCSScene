"""Local gnomonic (TAN) tangent plane.

The plane is built in the declared spherical frame. For ICRS/FK5/FK4,
+X is celestial east and +Y is celestial north. +Z of the right-handed
scene, before any display flip, points along the frame radial (toward the
sky). The inverse is the direction of the plane point, so this is a
gnomonic projection rather than ``RA difference * cos(Dec)``.

Points on the opposite hemisphere (``s · r <= 0``) are undefined. The exact
celestial pole is rejected: the local east/north basis vanishes there.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

from .errors import TangentAtPole
from .frames import describe_frame, frame_key

ARCSEC_PER_RADIAN = float((1.0 * u.rad).to_value(u.arcsec))
_HORIZON = 1e-8
_POLE_BASIS = 1e-10


@dataclass(frozen=True)
class TangentBasis:
    sky: SkyCoord
    frame_name: str
    frame_key: str
    radial: np.ndarray
    east: np.ndarray
    north: np.ndarray

    def as_dict(self) -> dict:
        info = describe_frame(self.sky)
        return {
            "frame": info.name,
            "frame_key": info.key,
            "equinox": info.equinox,
            "celestial_east_north": info.celestial_east_north,
            "x_axis": info.x_axis,
            "y_axis": info.y_axis,
            "lon_deg": float(self.sky.spherical.lon.deg),
            "lat_deg": float(self.sky.spherical.lat.deg),
            "radial": [float(v) for v in self.radial],
            "east": [float(v) for v in self.east],
            "north": [float(v) for v in self.north],
            "handedness": "right",
            "projection": "gnomonic_tan",
        }


def _vecs(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    cos_lat = np.cos(lat)
    return np.stack(
        (cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)),
        axis=-1,
    )


def build_basis(sky: SkyCoord) -> TangentBasis:
    """Orthonormal east/north/radial basis at a scalar sky position."""
    if not isinstance(sky, SkyCoord) or not sky.isscalar:
        raise TypeError("tangent point must be a scalar SkyCoord")
    describe_frame(sky)
    lon = float(sky.spherical.lon.radian)
    lat = float(sky.spherical.lat.radian)
    radial = _vecs(np.array(lon), np.array(lat))
    radial = np.asarray(radial, dtype=float)
    pole = np.array([0.0, 0.0, 1.0])
    east = np.cross(pole, radial)
    enorm = float(np.linalg.norm(east))
    if enorm < _POLE_BASIS:
        raise TangentAtPole(
            "Tangent point is at a celestial pole, where celestial east/north "
            "is undefined. Choose another tangent point."
        )
    east = east / enorm
    north = np.cross(radial, east)
    north = north / np.linalg.norm(north)
    return TangentBasis(
        sky=sky,
        frame_name=sky.frame.name,
        frame_key=frame_key(sky),
        radial=radial,
        east=east,
        north=north,
    )


def sky_to_tangent(
    sky: SkyCoord, basis: TangentBasis
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return east/north gnomonic offsets in radians and a validity mask.

    ``valid`` is False where the direction is non-finite or does not intersect
    the tangent plane on the near hemisphere.
    """
    if sky.frame.name != basis.frame_name:
        raise ValueError(
            f"Sky frame {sky.frame.name!r} does not match tangent frame "
            f"{basis.frame_name!r}. WCSScene does not convert frames implicitly."
        )
    lon = np.atleast_1d(np.asarray(sky.spherical.lon.radian, dtype=float))
    lat = np.atleast_1d(np.asarray(sky.spherical.lat.radian, dtype=float))
    vec = _vecs(lon, lat)
    denom = vec @ basis.radial
    valid = np.isfinite(denom) & (denom > _HORIZON) & np.isfinite(lon) & np.isfinite(lat)
    east = np.full(lon.shape, np.nan, dtype=float)
    north = np.full(lon.shape, np.nan, dtype=float)
    if np.any(valid):
        east[valid] = (vec[valid] @ basis.east) / denom[valid]
        north[valid] = (vec[valid] @ basis.north) / denom[valid]
    return east, north, valid


def tangent_to_sky(east_rad: np.ndarray, north_rad: np.ndarray, basis: TangentBasis) -> SkyCoord:
    """Inverse gnomonic map. ``east_rad`` and ``north_rad`` are tangent offsets."""
    east_rad = np.atleast_1d(np.asarray(east_rad, dtype=float))
    north_rad = np.atleast_1d(np.asarray(north_rad, dtype=float))
    point = (
        basis.radial
        + east_rad[..., None] * basis.east
        + north_rad[..., None] * basis.north
    )
    norm = np.linalg.norm(point, axis=-1, keepdims=True)
    direction = point / norm
    lat = np.arcsin(np.clip(direction[..., 2], -1.0, 1.0))
    lon = np.arctan2(direction[..., 1], direction[..., 0])
    sky = SkyCoord(lon * u.rad, lat * u.rad, frame=basis.sky.frame)
    if sky.size == 1:
        return sky.reshape(())
    return sky


def tangent_to_scene(
    east_rad: np.ndarray,
    north_rad: np.ndarray,
    arcsec_per_bu: float,
    *,
    flip_east_left: bool = False,
) -> np.ndarray:
    """Map tangent-plane radians to Blender units. Z is the presentation plane."""
    if not np.isfinite(arcsec_per_bu) or arcsec_per_bu <= 0:
        raise ValueError("arcsec_per_bu must be a positive finite scale")
    factor = ARCSEC_PER_RADIAN / float(arcsec_per_bu)
    x = np.asarray(east_rad, dtype=float) * factor
    if flip_east_left:
        x = -x
    y = np.asarray(north_rad, dtype=float) * factor
    z = np.zeros(np.broadcast(x, y).shape, dtype=float)
    return np.stack(np.broadcast_arrays(x, y, z), axis=-1)


def scene_to_tangent(
    xyz: np.ndarray, arcsec_per_bu: float, *, flip_east_left: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    xyz = np.asarray(xyz, dtype=float)
    factor = ARCSEC_PER_RADIAN / float(arcsec_per_bu)
    x = xyz[..., 0]
    if flip_east_left:
        x = -x
    return x / factor, xyz[..., 1] / factor


def sky_to_scene(
    sky: SkyCoord,
    basis: TangentBasis,
    arcsec_per_bu: float,
    *,
    flip_east_left: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    east, north, valid = sky_to_tangent(sky, basis)
    scene = tangent_to_scene(
        east, north, arcsec_per_bu, flip_east_left=flip_east_left
    )
    scene = scene.astype(float, copy=False)
    scene[~valid] = np.nan
    return scene, valid
