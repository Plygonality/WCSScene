# Scientific limitations

WCSScene presents a calibrated image and its catalogue on a 2.5D plane. It is not a reconstruction of three-dimensional structure.

## What a single exposure provides

A 2D image plus a WCS gives a direction on the sky for each valid pixel. It does not give a distance. Every source is labelled `distance_unknown`. Blender Z is the presentation normal. Marker and label offsets along Z are annotation lifts so symbols clear the image; they are stored as `annotation_z` and are not parallax, redshift, or size.

No later mode in v0.1 accepts parallax or distance. Invented galaxy thickness, radial extrusion, and depth-from-anomaly are out of scope.

## Agreement is not absolute accuracy

Round-trip and mesh residuals measure whether the scene matches the WCS that was supplied. They do not measure:

- the astrometric calibration error of that WCS
- unmodelled distortion
- frame or epoch differences
- proper motion
- catalogue mismatches below the configured tolerance

The local pixel scale is the angular step of one pixel at the reference pixel. It is not a global plate scale when distortion is present.

## Display is not photometry

`science.npy` keeps the sampled array, including NaNs, in the units declared by the input. The PNG and the Blender emission material are a visual stretch (linear, asinh, or log) between percentiles, with a named colormap. Log is refused when the display range is negative or zero. Invalid pixels are painted magenta `(180, 0, 140)` and saturated pixels are tinted. Those colours are flags, not calibrated values.

Do not measure flux, surface brightness, or a detection limit from a Blender render or a screenshot. Display-normalised pixel values are not physical flux. A Roman rate image is not converted with `conversion_megajanskys`.

## Uncertainty

If the input has no error columns, or the requested convention was not enabled, the status is `UNKNOWN` and the ellipse is null. A missing error is not stored as zero.

Pixel covariance is used only with `--pixel-uncertainty`. Sky covariance is used only with `--sky-uncertainty-convention ra_cosdec_arcsec`, meaning σ(α cos δ) and σ(δ) in arcseconds. The Jacobian is numerical, with a pixel step of 0.01 and a sky step of 0.01 arcsecond, and a half-step stability check. Correlations are kept. The tangent point at a pole, and sky errors where `|cos δ|` is under `1e-4`, are rejected as singular rather than plotted.

## Masks

NaNs and data-quality flags are not interpolated into a source that looks credible. WCSScene's own `DQCONV=WCSSCENE_012` convention is 0 good, 1 invalid, 2 saturated. Any other FITS DQ image treats a non-zero flag as invalid. Roman DQ uses `DO_NOT_USE`, `NON_SCIENCE`, `DEAD`, and `DROPOUT` as invalid, and `SATURATED` as the saturated flag when it is not also invalid.

## Catalogue scores

Anomaly score and percentile from an NGRST-style table stay inside that table's scoring definition. They are not a detection significance and not a classification. `known` and `reference_id` record a catalogue match, not a physical type.

## What this package does not do

It does not detect sources, fit photometry, calibrate Roman data, replace DS9, Aladin, or Glue, or generate a procedural star field. A visually clear Blender scene is a presentation of the supplied products.
