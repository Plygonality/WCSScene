"""Visual-only stretches. Scientific pixel values are not modified."""

from __future__ import annotations

import struct
import zlib
from typing import Any

import numpy as np

from .errors import InvalidInput

_INVALID_RGB = np.array([180, 0, 140], dtype=np.uint8)


def finite_percentiles(data: np.ndarray, mask: np.ndarray, percentiles: tuple[float, float]) -> tuple[float, float]:
    valid = data[mask == 1]
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(valid, list(percentiles))
    return float(low), float(high)


def stretch_array(
    data: np.ndarray,
    vmin: float,
    vmax: float,
    stretch: str,
    softening: float = 0.1,
) -> np.ndarray:
    if stretch not in {"linear", "asinh", "log"}:
        raise InvalidInput(f"Unknown stretch {stretch!r}. Use linear, asinh, or log.")
    span = float(vmax - vmin)
    if not np.isfinite(span) or span == 0:
        return np.zeros(data.shape, dtype=float)
    if stretch == "log":
        if vmin < 0 or vmax <= 0:
            raise InvalidInput(
                "LOG_STRETCH_UNDEFINED: log stretch requires a non-negative "
                f"display range, got vmin={vmin}, vmax={vmax}."
            )
        floor = np.log10(vmin + 1.0)
        scale = np.log10(vmax + 1.0) - floor
        clipped = np.clip(data, vmin, vmax)
        return (np.log10(clipped + 1.0) - floor) / scale
    normalised = np.clip((data - vmin) / span, 0.0, 1.0)
    if stretch == "linear":
        return normalised
    soft = float(softening)
    return np.arcsinh(normalised / soft) / np.arcsinh(1.0 / soft)


def colorize(normalised: np.ndarray, colormap: str) -> np.ndarray:
    if colormap not in {"gray", "heat", "slate"}:
        raise InvalidInput(f"Unknown colormap {colormap!r}. Use gray, heat, or slate.")
    value = np.clip(normalised, 0.0, 1.0)
    if colormap == "gray":
        channel = value
        rgb = np.stack([channel, channel, channel], axis=-1)
    elif colormap == "heat":
        rgb = _heat(value)
    else:
        rgb = _slate(value)
    return (np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)


def _heat(value: np.ndarray) -> np.ndarray:
    red = np.clip(value * 3.0, 0.0, 1.0)
    green = np.clip(value * 3.0 - 1.0, 0.0, 1.0)
    blue = np.clip(value * 3.0 - 2.0, 0.0, 1.0)
    return np.stack([red, green, blue], axis=-1)


def _slate(value: np.ndarray) -> np.ndarray:
    red = 0.05 + 0.90 * value
    green = 0.08 + 0.85 * value**1.2
    blue = 0.18 + 0.75 * value
    return np.stack([red, green, blue], axis=-1)


def render_display(
    data: np.ndarray,
    mask: np.ndarray,
    *,
    stretch: str,
    percentiles: tuple[float, float],
    colormap: str,
    show_mask: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return an RGB uint8 image. ``data`` is not written to."""
    vmin, vmax = finite_percentiles(data, mask, percentiles)
    flat = data.copy()
    flat[~np.isfinite(flat)] = vmin
    normalised = stretch_array(flat, vmin, vmax, stretch)
    rgb = colorize(normalised, colormap)
    if show_mask:
        rgb[mask == 0] = _INVALID_RGB
        saturated = mask == 2
        if np.any(saturated):
            tint = rgb[saturated].astype(float)
            tint[:, 0] = np.minimum(255.0, tint[:, 0] * 0.45 + 200.0)
            tint[:, 1] = np.minimum(255.0, tint[:, 1] * 0.45 + 140.0)
            tint[:, 2] = tint[:, 2] * 0.35
            rgb[saturated] = tint.astype(np.uint8)
    meta = {
        "stretch": stretch,
        "percentiles": [float(percentiles[0]), float(percentiles[1])],
        "vmin": vmin,
        "vmax": vmax,
        "colormap": colormap,
        "invalid_rgb": [int(v) for v in _INVALID_RGB],
        "show_mask": show_mask,
        "visual_only": True,
        "asinh_softening": 0.1 if stretch == "asinh" else None,
    }
    return rgb, meta


def downsample_mean(data: np.ndarray, mask: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    if factor <= 1:
        return data.copy(), mask.copy()
    ny, nx = data.shape
    ny2 = ny // factor
    nx2 = nx // factor
    if ny2 < 1 or nx2 < 1:
        raise InvalidInput(f"Downsample factor {factor} is larger than the image.")
    cropped = data[: ny2 * factor, : nx2 * factor]
    cropped_mask = mask[: ny2 * factor, : nx2 * factor]
    view = cropped.reshape(ny2, factor, nx2, factor)
    mask_view = cropped_mask.reshape(ny2, factor, nx2, factor)
    valid = mask_view == 1
    counts = valid.sum(axis=(1, 3))
    filled = np.where(valid, view, 0.0)
    totals = filled.sum(axis=(1, 3))
    out = np.full((ny2, nx2), np.nan, dtype=float)
    good = counts > 0
    out[good] = totals[good] / counts[good]
    out_mask = np.zeros((ny2, nx2), dtype=np.uint8)
    out_mask[good] = 1
    any_sat = (mask_view == 2).any(axis=(1, 3))
    out_mask[any_sat & good] = 2
    out_mask[counts == 0] = 0
    return out, out_mask


def choose_downsample(shape: tuple[int, int], max_pixels: int, requested: int | None) -> int:
    if requested is not None:
        if requested < 1:
            raise InvalidInput("downsample factor must be >= 1")
        return int(requested)
    ny, nx = shape
    longest = max(ny, nx)
    if longest <= max_pixels:
        return 1
    return int(np.ceil(longest / max_pixels))


def crop_image(
    data: np.ndarray, mask: np.ndarray, crop: tuple[int, int, int, int]
) -> tuple[np.ndarray, np.ndarray]:
    xmin, xmax, ymin, ymax = crop
    ny, nx = data.shape
    if not (0 <= xmin <= xmax < nx and 0 <= ymin <= ymax < ny):
        raise InvalidInput(
            f"Crop {crop} is outside image x=0..{nx - 1}, y=0..{ny - 1}."
        )
    return (
        data[ymin : ymax + 1, xmin : xmax + 1].copy(),
        mask[ymin : ymax + 1, xmin : xmax + 1].copy(),
    )


def write_png_rgb(path: str, rgb: np.ndarray) -> None:
    """Write an 8-bit RGB PNG. Row 0 of ``rgb`` is the bottom row (FITS y=0)."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("write_png_rgb expects uint8 RGB with shape (ny, nx, 3)")
    ny, nx, _ = rgb.shape
    # PNG stores the top row first. Flip so FITS y=0 stays at the bottom.
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(ny - 1, -1, -1))
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", nx, ny, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


def read_png_rgb(path: str) -> np.ndarray:
    """Decode the 8-bit non-interlaced RGB PNGs written by :func:`write_png_rgb`."""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    offset = 8
    width = height = None
    idat = b""
    while offset < len(blob):
        length = struct.unpack(">I", blob[offset : offset + 4])[0]
        tag = blob[offset + 4 : offset + 8]
        payload = blob[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, depth, color, comp, filt, inter = struct.unpack(">IIBBBBB", payload)
            if (depth, color, comp, filt, inter) != (8, 2, 0, 0, 0):
                raise ValueError("only 8-bit RGB PNG is supported")
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG missing IHDR")
    raw = zlib.decompress(idat)
    rows = []
    stride = 1 + width * 3
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        if row[0] != 0:
            raise ValueError("only filter 0 PNG rows are supported")
        rows.append(np.frombuffer(row[1:], dtype=np.uint8).reshape(width, 3))
    top_first = np.stack(rows, axis=0)
    return top_first[::-1].copy()
