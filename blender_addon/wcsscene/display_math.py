"""Visual-only stretch used by the add-on when the user changes the display.

This does not alter science.npy. Log is refused when the display range is not
positive. Invalid pixels use the same magenta mark as the exchange writer.
"""

from __future__ import annotations

import math
from array import array

INVALID_RGB = (180, 0, 140)


class DisplayError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def finite_percentiles(data, mask, low: float, high: float) -> tuple[float, float]:
    ny, nx = data.shape
    valid: list[float] = []
    values = data.values
    flags = mask.values
    for index in range(ny * nx):
        if int(flags[index]) != 1:
            continue
        value = float(values[index])
        if math.isfinite(value):
            valid.append(value)
    if not valid:
        return 0.0, 1.0
    return _percentile(valid, low), _percentile(valid, high)


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percent / 100.0)
    lo = int(math.floor(rank))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def stretch_value(value: float, vmin: float, vmax: float, stretch: str) -> float:
    span = vmax - vmin
    if not math.isfinite(span) or span == 0.0:
        return 0.0
    if stretch == "log":
        if vmin < 0.0 or vmax <= 0.0:
            raise DisplayError(
                "LOG_STRETCH_UNDEFINED",
                f"log stretch requires a non-negative display range, got vmin={vmin}, vmax={vmax}",
            )
        floor = math.log10(vmin + 1.0)
        scale = math.log10(vmax + 1.0) - floor
        clipped = min(max(value, vmin), vmax)
        if scale == 0.0:
            return 0.0
        return (math.log10(clipped + 1.0) - floor) / scale
    normalised = min(max((value - vmin) / span, 0.0), 1.0)
    if stretch == "linear":
        return normalised
    if stretch == "asinh":
        soft = 0.1
        return math.asinh(normalised / soft) / math.asinh(1.0 / soft)
    raise DisplayError("UNKNOWN_STRETCH", f"unknown stretch {stretch}")


def colorize(normalised: float, colormap: str) -> tuple[int, int, int]:
    value = min(max(normalised, 0.0), 1.0)
    if colormap == "gray":
        channel = int(round(value * 255.0))
        return channel, channel, channel
    if colormap == "heat":
        red = min(max(value * 3.0, 0.0), 1.0)
        green = min(max(value * 3.0 - 1.0, 0.0), 1.0)
        blue = min(max(value * 3.0 - 2.0, 0.0), 1.0)
    elif colormap == "slate":
        red = 0.05 + 0.90 * value
        green = 0.08 + 0.85 * (value**1.2)
        blue = 0.18 + 0.75 * value
    else:
        raise DisplayError("UNKNOWN_COLORMAP", f"unknown colormap {colormap}")
    return (
        int(round(min(max(red, 0.0), 1.0) * 255.0)),
        int(round(min(max(green, 0.0), 1.0) * 255.0)),
        int(round(min(max(blue, 0.0), 1.0) * 255.0)),
    )


def render_rgb(
    data,
    mask,
    *,
    stretch: str,
    percentiles: tuple[float, float],
    colormap: str,
    show_mask: bool,
) -> tuple[list[tuple[int, int, int]], dict]:
    vmin, vmax = finite_percentiles(data, mask, percentiles[0], percentiles[1])
    ny, nx = data.shape
    rgb: list[tuple[int, int, int]] = []
    for index in range(ny * nx):
        sample = float(data.values[index])
        if not math.isfinite(sample):
            sample = vmin
        tone = stretch_value(sample, vmin, vmax, stretch)
        pixel = colorize(tone, colormap)
        flag = int(mask.values[index])
        if show_mask and flag == 0:
            pixel = INVALID_RGB
        elif show_mask and flag == 2:
            pixel = (
                min(255, int(pixel[0] * 0.45 + 200)),
                min(255, int(pixel[1] * 0.45 + 140)),
                int(pixel[2] * 0.35),
            )
        rgb.append(pixel)
    meta = {
        "stretch": stretch,
        "percentiles": [percentiles[0], percentiles[1]],
        "vmin": vmin,
        "vmax": vmax,
        "colormap": colormap,
        "show_mask": show_mask,
        "visual_only": True,
        "shape_yx": [ny, nx],
    }
    return rgb, meta


def downsample(data, mask, factor: int):
    if factor <= 1:
        return data, mask
    ny, nx = data.shape
    ny2 = ny // factor
    nx2 = nx // factor
    if ny2 < 1 or nx2 < 1:
        raise DisplayError("DISPLAY_TOO_LARGE", f"downsample factor {factor} exceeds the image")
    out = array("d", [float("nan")] * (ny2 * nx2))
    out_mask = array("B", [0] * (ny2 * nx2))
    for y in range(ny2):
        for x in range(nx2):
            total = 0.0
            count = 0
            saturated = False
            for dy in range(factor):
                for dx in range(factor):
                    src = (y * factor + dy) * nx + (x * factor + dx)
                    flag = int(mask.values[src])
                    if flag == 2:
                        saturated = True
                    if flag != 1:
                        continue
                    sample = float(data.values[src])
                    if math.isfinite(sample):
                        total += sample
                        count += 1
            dest = y * nx2 + x
            if count:
                out[dest] = total / count
                out_mask[dest] = 2 if saturated else 1
    from .npy_io import NpyArray

    return NpyArray((ny2, nx2), "d", out), NpyArray((ny2, nx2), "B", out_mask)
