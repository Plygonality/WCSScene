# Roman ASDF and GWCS

Roman WFI science products are ASDF. The exposure-level pipeline stores an instrument-aware WCS on `meta.wcs`, usually a GWCS model that can include detector distortion. A FITS header is not assumed to be a lossless copy of that model. WCSScene never fabricates FITS WCS keywords from a GWCS.

## What v0.1 loads

With the `roman` extra (`asdf`, `gwcs`, `roman_datamodels`), `wcsscene prepare --format roman` opens the file with `roman_datamodels.open` and accepts a 2D `ImageModel` (level L2) or `MosaicModel` (level L3). Placement uses `meta.wcs` through the same high-level `pixel_to_world` / `world_to_pixel` API as FITS. If `meta.wcs` is missing, scientific placement is refused. Ramps and other arrays that are not 2D are refused rather than sliced.

The adapter copies non-sentinel instrument, exposure, observation, and photometry metadata. Sentinel strings (`?`, empty) and fill values at `±999999` are listed as sentinels and are not used as measurements. `wcsinfo.ra_ref` is not substituted for `meta.wcs`. The handbook unit context for an L2 rate image (DN/s) is recorded as a note. `conversion_megajanskys` is not applied.

Roman DQ flags mark unusable pixels. The manifest records:

- `fits_wcs_fabricated: false`
- `instrument_distortion_verified: false`
- `flight_data_verified: false`

A GWCS made only of shifts, scales, and a gnomonic TAN (`Pix2Sky_TAN` or `Pix2Sky_Gnomonic`) is labelled `gwcs-tan`. Any other forward model is labelled `gwcs-nonlinear` and is sampled on the mesh. Neither label certifies a CRDS distortion reference file.

## What was actually tested

`roman_datamodels` 1.2.0 is installed in the environment that produced this release. `ImageModel.create_fake_data` builds a schema placeholder whose `make_wcs` is a TAN GWCS: shifts of −500, a scale of 0.1 arcsec/pixel, and `RotateNative2Celestial`. Tests round-trip that WCS and check that the manifest does not claim flight data or a fabricated FITS header. A missing import is reported as `MISSING_OPTIONAL_DEPENDENCY` (exit 5). A file that is not an imaging datamodel is `UNSUPPORTED_DATA_MODEL` (exit 6).

That is library-fixture acceptance. It is not acceptance of a Roman calibration product. `examples/roman_calibrated.asdf` is not in the repository. Preparing that path returns `INVALID_INPUT` because the file is absent:

```
wcsscene prepare examples/roman_calibrated.asdf --format roman \
  --catalog examples/ngrst_catalog.csv --out build/roman
```

To exercise the adapter offline, write a throwaway library model under `build/` and prepare that path. Do not rename it as if it were an observation:

```python
from roman_datamodels.datamodels import ImageModel

model = ImageModel.create_fake_data(shape=(24, 24))
model.save("build/roman_library_fixture.asdf")
```

```
wcsscene prepare build/roman_library_fixture.asdf --format roman --out build/roman
```

The resulting banner states that flight data and instrument distortion are not verified.

## Not supported yet

- A delivered L2 `_cal.asdf` with the observatory's distortion solution has not been run.
- `ScienceRawModel` ramps are rejected because they are not 2D images.
- No mosaic tiler beyond a single 2D `MosaicModel` array.
- No conversion of GWCS into a SIP or TAN FITS header.
