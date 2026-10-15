"""Celestial frame labels for the tangent-plane axes.

+X/+Y are celestial east/north only for equatorial frames. Galactic
longitude/latitude stay in the Galactic frame and are labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from astropy.coordinates import SkyCoord

EQUATORIAL = frozenset({"icrs", "fk5", "fk4"})
SUPPORTED = EQUATORIAL | frozenset({"galactic"})


@dataclass(frozen=True)
class FrameDescription:
    name: str
    key: str
    equinox: str | None
    x_axis: str
    y_axis: str
    celestial_east_north: bool


def frame_key(sky: SkyCoord) -> str:
    name = sky.frame.name
    equinox = getattr(sky.frame, "equinox", None)
    if equinox is not None:
        return f"{name}:{float(equinox.jyear):.5f}"
    return name


def describe_frame(sky: SkyCoord) -> FrameDescription:
    name = sky.frame.name
    if name not in SUPPORTED:
        supported = ", ".join(sorted(SUPPORTED))
        raise ValueError(
            f"Frame {name!r} is not supported. Supported frames: {supported}."
        )
    equinox = getattr(sky.frame, "equinox", None)
    equinox_text = None if equinox is None else f"J{float(equinox.jyear):.5f}"
    if name in EQUATORIAL:
        return FrameDescription(
            name=name,
            key=frame_key(sky),
            equinox=equinox_text,
            x_axis="celestial_east",
            y_axis="celestial_north",
            celestial_east_north=True,
        )
    return FrameDescription(
        name=name,
        key=frame_key(sky),
        equinox=None,
        x_axis="galactic_longitude_increasing",
        y_axis="galactic_latitude_increasing",
        celestial_east_north=False,
    )
