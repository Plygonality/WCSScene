"""Downsample and marker storage stay bounded on a larger synthetic field."""

import time
import tracemalloc

import numpy as np
from astropy.io import fits
from astropy.table import Table

from wcsscene.exchange import PrepareConfig, prepare
from wcsscene.synthetic import make_tan_wcs


def test_downsampled_field_keeps_a_single_marker_array(tmp_path):
    ny, nx = 900, 1100
    rng = np.random.default_rng(5)
    image = rng.normal(10.0, 1.0, size=(ny, nx)).astype(np.float32)
    wcs = make_tan_wcs(nx, ny, scale_arcsec=0.2, rotation_deg=12.0)
    path = tmp_path / "wide.fits"
    hdu = fits.PrimaryHDU(image)
    hdu.header.update(wcs.to_header())
    hdu.header["BUNIT"] = "adu"
    hdu.header["ORIGIN"] = "WCSScene synthetic scale fixture; not a telescope observation"
    hdu.writeto(path)
    n_sources = 2000
    xs = rng.uniform(0, nx - 1, n_sources)
    ys = rng.uniform(0, ny - 1, n_sources)
    catalog = tmp_path / "sources.csv"
    Table({"label": [f"S{i:04d}" for i in range(n_sources)], "x_centroid": xs, "y_centroid": ys}).write(
        catalog, format="ascii.csv", overwrite=True
    )
    tracemalloc.start()
    started = time.perf_counter()
    result = prepare(
        path,
        tmp_path / "out",
        PrepareConfig(
            catalog=str(catalog),
            max_display_pixels=256,
            mesh_cells=24,
            arcsec_per_bu=1.0,
        ),
    )
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.exit_code == 0
    import json

    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert max(manifest["image"]["display_shape_yx"]) <= 256
    assert manifest["image"]["downsample_factor"] > 1
    with np.load(tmp_path / "out" / "geometry.npz") as archive:
        assert archive["marker_xyz"].shape == (n_sources, 3)
        assert archive["xyz"].shape[0] < 2000
    # Bounds are sanity limits against accidental per-source mesh explosion.
    assert elapsed < 90.0
    assert peak < 800_000_000
    print(
        f"SCALE elapsed_s={elapsed:.3f} tracemalloc_peak_bytes={peak} "
        f"display={manifest['image']['display_shape_yx']} "
        f"mesh_vertices={manifest['mesh']['vertex_count']}"
    )
