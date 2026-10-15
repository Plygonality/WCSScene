# Coordinate contract

WCSScene maps a 2D image onto a Blender presentation plane. The mapping is reversible for valid samples and is tested in stages. Blender units are an angular presentation scale. Distance from the plane is not an astronomical distance.

## Stages

```
image array (row, column) = data[y, x]
        ↕
zero-based pixel centres (x, y)
        ↕
celestial WCS, high-level pixel_to_world / world_to_pixel
        ↕
SkyCoord in the frame the WCS returns
        ↕
local gnomonic (TAN) tangent plane
        ↕
Blender scene coordinates
```

## Pixel convention

The high-level shared WCS API is authoritative. `pixel_to_world(x, y)` and `world_to_pixel` use zero-based pixel centres, with `x` along the first pixel axis and `y` along the second. Array indices stay `(row, column) = (y, x)`.

FITS `CRPIX` is 1-based. The reference pixel passed to the high-level API is `CRPIX - 1`. A fixture with `CRPIX = (1, 1)` must map pixel `(0, 0)` to `CRVAL`, and pixel `(1, 1)` must not.

Catalogue pixel columns follow the same zero-based centres unless `--pixel-origin 1` is set, in which case 1 is subtracted before use. The input table is not rewritten.

## Celestial frame

Supported frames are ICRS, FK5, FK4, and Galactic. The frame is whatever `pixel_to_world` returns. WCSScene does not convert between frames. Galactic axes are galactic longitude and latitude, not celestial east and north. A WCS with `pixel_n_dim` or `world_n_dim` other than 2 is rejected. Axes are not dropped.

## Tangent plane

The tangent point is `pixel_to_world` of the reference pixel, unless both tangent longitude and latitude are set in `PrepareConfig`. The basis is Cartesian, not `ΔRA cos Dec`:

- radial `r` points from the observer toward the tangent sky position
- east is the normalisation of celestial-pole × `r`
- north is `r` × east

So east × north points toward the sky. Scene coordinates before a display flip are

```
X = east component, in arcseconds, divided by --arcsec-per-bu
Y = north component, in the same units
Z = 0
```

`--arcsec-per-bu 1` means one Blender unit is one arcsecond on this tangent plane. The gnomonic scale is `tan(theta)`, not `theta`, so a large offset is not a raw angular difference. That difference is tested.

The exact pole, where east cannot be defined, raises `TANGENT_POINT_AT_POLE`. The opposite hemisphere is undefined and is not placed at the origin. RA values on either side of 0° are ordinary Cartesian directions, so the 359.999° / 0.001° seam is not a special case in the plane.

`--east-left` multiplies scene X by −1 and records a left-handed presentation. The default is east to the right when a camera on +Z looks toward −Z, with +Y up. That matches north-up, east-right.

## Image mesh

Vertices sit on pixel edges from −0.5 to `n − 0.5` and are projected through the full WCS, including SIP or a GWCS forward model. UV coordinates span the cropped pixel rectangle of the unaltered image:

```
original_x = (xmin - 0.5) + u * (xmax - xmin + 1)
original_y = (ymin - 0.5) + v * (ymax - ymin + 1)
```

A uniform grid is used. `--mesh-cells` is the count along the long side. Residuals are measured at withheld cell centres: the true WCS position minus the bilinear average of the four corners, converted to arcseconds with `arcsec_per_blender_unit`. The default budget is `max(0.01, 0.05 * local_pixel_scale)` arcseconds. This is interpolation error against the supplied WCS, not absolute accuracy on the sky.

`--flat-rectangle` forces one cell and is labelled `flat_rectangle_labeled_approximation`. `--allow-residual` records an over-budget mesh as a warning and exits 0. Otherwise `prepare` exits 4.

## Catalogue authority

If both pixel and sky columns are present, both are transformed and compared with `SkyCoord.separation`. The default tolerance is 0.05 arcseconds.

| Situation | Result |
| --- | --- |
| Both agree within tolerance, `--coord-authority auto` | Sky is authoritative and the residual is reported. |
| They disagree and authority is `auto` | `INCONSISTENT_COORDINATES`, exit 3. Nothing is quietly swapped. |
| Authority is explicitly `pixel` or `sky` | The chosen columns place the source and the mismatch is reported. |
| Sky is blank and pixel is inside the image | Pixel is authoritative and sky is derived. |
| The position is outside the image | `placed` is false and `scene_xyz` is null. It is not drawn at the origin. |

NGRST-Discovery-Toolkit names are the first alias in each family. Blank fields stay blank. `known` that cannot be parsed stays null rather than becoming false.

| Bundle field | Accepted input names, in order |
| --- | --- |
| source id | `label`, `source_id`, `id`, `name`, `object` |
| pixel x, y | `x_centroid`, `y_centroid`, then `x` / `y` and common centroid aliases |
| equatorial sky | `ra`, `dec`, then `ra_deg` / `dec_deg` |
| galactic sky | `glon`, `glat`, then `l` / `b` |
| snr | `snr` |
| anomaly | `anomaly_score`, `anomaly_percentile` |
| match | `known`, `reference_id` |

`anomaly_score` is a within-image score, not a discovery significance. `reference_id` is a catalogue match identifier, not a physical class. No distance column is interpreted. Uncertainty columns are ignored unless `--pixel-uncertainty` or `--sky-uncertainty-convention ra_cosdec_arcsec` is set. Otherwise the status is `UNKNOWN`, not zero.

## Round-trip tolerance

Exact WCS round-trips use a tolerance of `1e-3` pixel so a SIP inverse is allowed to iterate. A pure TAN fixture is expected far below `1e-6` pixel. Mesh interpolation has the separate arcsecond budget above. Passing either check means numerical agreement with the supplied WCS. It does not certify the calibration, the frame, the epoch, or residual distortion that the WCS itself does not model.

## Pixel preview

`--pixel-preview` places the image in pixel units centred on the array. One pixel is one Blender unit. Celestial axes, sky readouts, and astrometric claims are omitted. A WCS validation failure never falls through into this mode.

## Exchange schema

Schema `1.0.0`. Readers accept major version 1 and ignore unknown keys. A different major version is `SCHEMA_UNSUPPORTED`. The manifest `content_id` is a SHA-256 of the canonical JSON excluding `content_id`, `provenance.created_utc`, and elapsed time. Geometry NPZ timestamps are fixed so the same inputs and configuration reproduce the same file bytes. Nothing is pickled.
