"""Roman datamodel adapter.

``ImageModel.create_fake_data`` builds a schema placeholder TAN GWCS. That is
enough to prove ``meta.wcs`` is used. It is not instrument-distortion or
flight-data acceptance.
"""

import pytest

from wcsscene.errors import InconsistentWCS, MissingOptionalDependency, UnsupportedDataModel
from wcsscene.exchange import PrepareConfig, prepare
from wcsscene.io_roman import load_roman

roman = pytest.importorskip("roman_datamodels")


def test_dependency_error_is_visible(monkeypatch, tmp_path):
    target = tmp_path / "anything.asdf"
    target.write_bytes(b"not-really")

    def boom():
        raise ImportError("simulated")

    monkeypatch.setattr("wcsscene.io_roman._import_roman", boom)
    with pytest.raises(MissingOptionalDependency, match="MISSING_OPTIONAL_DEPENDENCY|roman_datamodels"):
        load_roman(target)


def test_plain_asdf_is_unsupported(tmp_path):
    asdf = pytest.importorskip("asdf")
    path = tmp_path / "plain.asdf"
    with asdf.AsdfFile({"note": "not a roman datamodel"}) as handle:
        handle.write_to(path)
    with pytest.raises(UnsupportedDataModel, match="UNSUPPORTED_DATA_MODEL"):
        load_roman(path)


def test_library_image_model_uses_meta_wcs_and_does_not_claim_flight_data(tmp_path):
    from roman_datamodels.datamodels import ImageModel

    model = ImageModel.create_fake_data(shape=(24, 24))
    path = tmp_path / "roman_library_fixture.asdf"
    model.save(path)
    loaded = load_roman(path)
    assert loaded.wcs_kind == "gwcs"
    assert loaded.roman["fits_wcs_fabricated"] is False
    assert loaded.roman["instrument_distortion_verified"] is False
    assert loaded.roman["flight_data_verified"] is False
    assert loaded.roman["model_type"] == "ImageModel"
    assert loaded.roman["product_level"] == "L2"
    assert loaded.header_meta["instrument.detector"] == "WFI01"
    assert "exposure.exposure_time" in loaded.roman["sentinel_fields"]
    result = prepare(path, tmp_path / "bundle", PrepareConfig(fmt="roman"))
    assert result.exit_code == 0
    import json

    manifest = json.loads((tmp_path / "bundle" / "manifest.json").read_text())
    assert manifest["wcs"]["kind"] == "gwcs"
    assert manifest["wcs"]["fits_wcs_fabricated"] is False
    assert manifest["wcs"]["distortion"]["kind"] == "gwcs-tan"
    assert manifest["roundtrip"]["max_pixel_error"] < 1e-4
    assert manifest["presentation"]["tangent_point"]["lon_deg"] != pytest.approx(-999999)
    assert "flight" in " ".join(manifest["banners"]).lower() or "not verified" in " ".join(manifest["banners"])
    report_text = (tmp_path / "bundle" / "qa_report.md").read_text()
    assert "round-trip" in report_text.lower() or "round-trip" in report_text


def test_missing_meta_wcs_refuses_placement(tmp_path, monkeypatch):
    from roman_datamodels.datamodels import ImageModel

    model = ImageModel.create_fake_data(shape=(8, 8))

    class Wrapper:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

    # Opening a real file is the supported path. A model whose meta.wcs is
    # removed must not fall back to wcsinfo sentinels.
    model.meta.wcs = None
    path = tmp_path / "no_wcs.asdf"
    try:
        model.save(path)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"roman schema refused a null meta.wcs: {exc}")
    with pytest.raises(InconsistentWCS, match="meta.wcs"):
        load_roman(path)


def test_non_image_model_is_unsupported(tmp_path):
    from roman_datamodels.datamodels import ScienceRawModel

    try:
        model = ScienceRawModel.create_fake_data(shape=(2, 8, 8))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not build a raw ramp fixture: {exc}")
    path = tmp_path / "ramp.asdf"
    model.save(path)
    with pytest.raises(UnsupportedDataModel):
        load_roman(path)
