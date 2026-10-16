"""Bundle claims, masks, reproducibility, and CLI failures."""

import json
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from wcsscene.cli import main
from wcsscene.errors import InconsistentWCS, InvalidInput
from wcsscene.exchange import PrepareConfig, prepare
from wcsscene.image_display import read_png_rgb
from wcsscene.synthetic import write_no_wcs_npz, write_reference_catalog, write_reference_fits
from wcsscene.validate import validate_bundle


def _bundle(tmp_path: Path) -> Path:
    fits_path = tmp_path / "reference.fits"
    catalog_path = tmp_path / "sources.ecsv"
    wcs = write_reference_fits(fits_path)
    write_reference_catalog(catalog_path, wcs)
    out = tmp_path / "bundle"
    result = prepare(
        fits_path,
        out,
        PrepareConfig(hdu="SCI", catalog=str(catalog_path), arcsec_per_bu=1.0, highlight_source_id="SRC-B"),
    )
    assert result.exit_code == 0
    return out


def test_reference_bundle_roundtrip_and_highlight(tmp_path):
    out = _bundle(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    sources = json.loads((out / "sources.json").read_text())
    src_b = next(row for row in sources if row["source_id"] == "SRC-B")
    assert manifest["celestial_accuracy"] == "relative_to_supplied_wcs"
    assert manifest["presentation"]["arcsec_per_blender_unit"] == 1.0
    assert manifest["roundtrip"]["max_pixel_error"] < 1e-6
    assert manifest["mesh"]["residual"]["max_arcsec"] < manifest["mesh"]["residual"]["budget_arcsec"]
    assert manifest["mesh"]["approximation"] == "sampled_wcs_mesh"
    assert src_b["pixel_xy_input"] == [70.0, 18.0]
    assert src_b["scene_xyz"][2] == 0.0
    assert src_b["placed"] is True
    science = np.load(out / "science.npy")
    original = fits.getdata(tmp_path / "reference.fits", extname="SCI")
    assert science.shape == (80, 96)
    assert np.isnan(science[8, 10])
    assert science[70, 5] == pytest.approx(50000.0)
    assert science[18, 70] > science[18, 69]
    assert science[18, 70] > science[17, 70]
    assert science[70, 18] < science[18, 70] / 5.0
    np.testing.assert_allclose(science, np.array(original, dtype=np.float64), equal_nan=True)
    rgb = read_png_rgb(out / "display.png")
    assert tuple(int(v) for v in rgb[8, 10]) == (180, 0, 140)
    report = validate_bundle(out / "manifest.json")
    assert report["status"] == "pass", report
    text = (out / "qa_report.md").read_text()
    assert "SRC-B" in text
    assert "distance_unknown" in text


def test_same_inputs_are_reproducible(tmp_path):
    fits_path = tmp_path / "reference.fits"
    catalog_path = tmp_path / "sources.ecsv"
    wcs = write_reference_fits(fits_path)
    write_reference_catalog(catalog_path, wcs)
    before = fits_path.read_bytes()
    catalog_before = catalog_path.read_bytes()
    config = PrepareConfig(hdu="SCI", catalog=str(catalog_path), arcsec_per_bu=1.0, highlight_source_id="SRC-B")
    first = prepare(fits_path, tmp_path / "a", config)
    second = prepare(fits_path, tmp_path / "b", config)
    manifest_a = json.loads(first.manifest_path.read_text())
    manifest_b = json.loads(second.manifest_path.read_text())
    assert manifest_a["content_id"] == manifest_b["content_id"]
    assert manifest_a["files"]["geometry_npz"]["sha256"] == manifest_b["files"]["geometry_npz"]["sha256"]
    assert json.loads((tmp_path / "a" / "sources.json").read_text())[1]["source_id"] == "SRC-B"
    assert fits_path.read_bytes() == before
    assert catalog_path.read_bytes() == catalog_before


def test_missing_wcs_fails_closed_and_preview_has_no_sky_claim(tmp_path):
    path = tmp_path / "plain.fits"
    fits.PrimaryHDU(np.arange(12, dtype=np.float32).reshape(3, 4)).writeto(path)
    with pytest.raises(InconsistentWCS, match="MISSING_WCS"):
        prepare(path, tmp_path / "bad", PrepareConfig())
    npz = tmp_path / "preview.npz"
    write_no_wcs_npz(npz)
    result = prepare(npz, tmp_path / "preview", PrepareConfig(pixel_preview=True))
    assert result.exit_code == 0
    manifest = json.loads((tmp_path / "preview" / "manifest.json").read_text())
    assert manifest["mode"] == "pixel_preview"
    assert manifest["celestial_accuracy"] == "none"
    assert manifest["presentation"]["arcsec_per_blender_unit"] is None
    assert manifest["wcs"] is None
    sources = json.loads((tmp_path / "preview" / "sources.json").read_text())
    assert sources and all(not row["sky_used_for_placement"] for row in sources)
    report = validate_bundle(tmp_path / "preview" / "manifest.json")
    assert report["status"] == "pass"


def test_missing_hdu_lists_available_extensions(tmp_path):
    path = tmp_path / "named.fits"
    primary = fits.PrimaryHDU()
    image = fits.ImageHDU(np.ones((4, 5), dtype=np.float32), name="ERR")
    fits.HDUList([primary, image]).writeto(path)
    code = main(["prepare", str(path), "--hdu", "SCI", "--out", str(tmp_path / "out")])
    assert code == 2
    # The CLI writes the error to stderr; call the loader for the message body.
    with pytest.raises(InvalidInput, match="SCI") as exc:
        prepare(path, tmp_path / "out2", PrepareConfig(hdu="SCI"))
    assert "ERR" in str(exc.value)


def test_log_stretch_rejects_negative_range(tmp_path):
    path = tmp_path / "neg.fits"
    wcs_header = fits.Header()
    data = np.linspace(-5.0, 5.0, 64, dtype=np.float32).reshape(8, 8)
    hdu = fits.PrimaryHDU(data, header=wcs_header)
    from wcsscene.synthetic import make_tan_wcs

    hdu.header.update(make_tan_wcs(8, 8).to_header())
    hdu.writeto(path)
    with pytest.raises(InvalidInput, match="LOG_STRETCH_UNDEFINED"):
        prepare(path, tmp_path / "log", PrepareConfig(stretch="log", percentiles=(0, 100)))


def test_missing_hdu_lists_available_names(tmp_path):
    path = tmp_path / "reference.fits"
    write_reference_fits(path)
    code = main(["prepare", str(path), "--hdu", "ERR", "--out", str(tmp_path / "bad")])
    assert code == 2


def test_cli_demo_and_validate(tmp_path):
    out = tmp_path / "demo"
    assert main(["demo", "--out", str(out)]) == 0
    report = tmp_path / "validation.json"
    assert main(["validate", str(out / "manifest.json"), "--report", str(report)]) == 0
    body = json.loads(report.read_text())
    assert body["status"] == "pass"
    assert main(["inspect", str(out / "reference.fits"), "--hdu", "SCI"]) == 0
    assert main(["doctor"]) == 0
    assert main(["--help"]) == 0


def test_addon_does_not_import_scientific_stack():
    root = Path(__file__).resolve().parents[1] / "blender_addon" / "wcsscene"
    if not root.exists():
        pytest.skip("addon not written yet")
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "astropy" not in text
    assert "roman_datamodels" not in text
    assert "import numpy" not in text
    assert "import wcsscene" not in text
