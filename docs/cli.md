# Command line

`wcsscene --help` from version 0.1.0:

```
usage: wcsscene [-h] [--version] {demo,inspect,prepare,validate,doctor} ...

Build a scientifically traceable 2.5D Blender exchange bundle from an
astronomical image and its WCS. Blender units are an angular presentation
scale, not distance.

positional arguments:
  {demo,inspect,prepare,validate,doctor}
    demo                Write a synthetic TAN field and its exchange bundle
    inspect             Describe a FITS HDU and its WCS
    prepare             Write an exchange bundle
    validate            Check an exchange manifest
    doctor              Report installed scientific and Blender capabilities

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## demo

```
usage: wcsscene demo [-h] --out OUT
```

Writes `reference.fits`, `reference_sources.ecsv`, and a scientific bundle into `--out`. The highlight source is `SRC-B`. The field is synthetic.

## inspect

```
usage: wcsscene inspect [-h] [--hdu HDU] [--json] path
```

`--hdu` is a name or a zero-based index. A missing name exits 2 and lists the HDUs.

## prepare

```
usage: wcsscene prepare [-h] [--hdu HDU] [--catalog CATALOG]
                        [--format {auto,fits,roman,npz}]
                        [--projection PROJECTION]
                        [--arcsec-per-bu ARCSEC_PER_BU] [--pixel-preview]
                        [--coord-authority {auto,pixel,sky}]
                        [--coord-tolerance-arcsec COORD_TOLERANCE_ARCSEC]
                        [--pixel-origin {0,1}] [--mesh-cells MESH_CELLS]
                        [--residual-budget-arcsec RESIDUAL_BUDGET_ARCSEC]
                        [--allow-residual] [--flat-rectangle]
                        [--stretch {linear,asinh,log}]
                        [--percentiles PERCENTILES PERCENTILES]
                        [--colormap {gray,heat,slate}]
                        [--max-display-pixels MAX_DISPLAY_PIXELS]
                        [--downsample DOWNSAMPLE] [--crop XMIN XMAX YMIN YMAX]
                        [--east-left] [--pixel-uncertainty]
                        [--sky-uncertainty-convention SKY_UNCERTAINTY_CONVENTION]
                        [--highlight HIGHLIGHT] --out OUT
                        path
```

`--arcsec-per-bu` is the number of arcseconds represented by one Blender unit. `--projection` accepts `tan` only. `--pixel-preview` is the only way to import an image that has no celestial WCS.

## validate

```
usage: wcsscene validate [-h] --report REPORT manifest
```

Exit 0 when the bundle's recorded checks and, when the input file is still present, a recomputed round-trip agree. Exit 4 when they do not.

## doctor

```
usage: wcsscene doctor [-h]
```

Prints package versions and whether `blender` is on `PATH` or at `~/blender/blender`. Exit 0 even when optional pieces are missing. It always reports that flight Roman products are not verified.

## Exit statuses

| Code | Name | When |
| --- | --- | --- |
| 0 | success | Bundle written and checks passed, or doctor finished. |
| 2 | `INVALID_INPUT` | Missing file, unknown HDU, or rejected arguments. |
| 3 | `INCONSISTENT_WCS` / `UNSUPPORTED_WCS` / `TANGENT_POINT_AT_POLE` / `INCONSISTENT_COORDINATES` | Missing or unusable WCS, or pixel and sky columns disagree under `auto`. |
| 4 | `VALIDATION_FAILED` | Round-trip or enforced mesh residual failed. |
| 5 | `MISSING_OPTIONAL_DEPENDENCY` | Roman datamodels are not installed. |
| 6 | `UNSUPPORTED_DATA_MODEL` | The file opened but is not a supported 2D image. |
| 7 | Blender import failure | Returned by `scripts/import_bundle.py` when Blender is started with `--python-exit-code 7`. |
