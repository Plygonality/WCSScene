"""Exchange arrays can be read without the scientific stack or Blender."""

import importlib.util
from pathlib import Path

import numpy as np


def _load(name: str):
    root = Path(__file__).resolve().parents[1] / "blender_addon" / "wcsscene" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"addon_{name}", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_npy_and_npz_roundtrip(tmp_path):
    npy_io = _load("npy_io")
    xyz = np.array([[0.0, 1.0, 0.0], [2.5, -3.0, 0.0]], dtype=np.float64)
    faces = np.array([[0, 1, 2]], dtype=np.int32)
    mask = np.array([[0, 1], [2, 1]], dtype=np.uint8)
    np.save(tmp_path / "xyz.npy", xyz)
    np.savez(tmp_path / "geometry.npz", xyz=xyz, faces=faces, mask=mask)
    loaded = npy_io.load_npy(tmp_path / "xyz.npy")
    assert loaded.shape == (2, 3)
    assert loaded.as_tuples()[1] == (2.5, -3.0, 0.0)
    archive = npy_io.load_npz(tmp_path / "geometry.npz")
    assert archive["faces"].as_tuples() == [(0, 1, 2)]
    assert list(archive["mask"].values) == [0, 1, 2, 1]


def test_display_stretch_matches_exchange_writer(tmp_path):
    display_math = _load("display_math")
    npy_io = _load("npy_io")
    from wcsscene.image_display import render_display

    data = np.array([[1.0, 5.0], [np.nan, 9.0]], dtype=np.float64)
    mask = np.array([[1, 2], [0, 1]], dtype=np.uint8)
    rgb, _meta = render_display(data, mask, stretch="asinh", percentiles=(0, 100), colormap="heat")
    np.save(tmp_path / "data.npy", data)
    np.save(tmp_path / "mask.npy", mask)
    got, _ = display_math.render_rgb(
        npy_io.load_npy(tmp_path / "data.npy"),
        npy_io.load_npy(tmp_path / "mask.npy"),
        stretch="asinh",
        percentiles=(0, 100),
        colormap="heat",
        show_mask=True,
    )
    assert got[2] == tuple(int(v) for v in rgb[1, 0])
    assert got[1][0] > got[1][2]
