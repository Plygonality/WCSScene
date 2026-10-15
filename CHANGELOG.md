# Changelog

## 0.1.0

First usable release of the FITS WCS to Blender path.

- Scientific package prepares a versioned exchange bundle from a 2D FITS image, its celestial WCS, and an optional CSV, ECSV, or FITS catalogue.
- Local gnomonic tangent plane, sampled image mesh, source markers, uncertainty propagation when a convention is declared, and a no-WCS pixel preview that makes no sky claim.
- Blender 4.5 extension imports the bundle without Astropy, validates marker positions, and reimports without deleting unrelated objects.
- Roman ASDF support loads `ImageModel` and `MosaicModel` through `meta.wcs` when `roman_datamodels` is installed. Schema-factory WCS is not treated as flight data or as a verified instrument distortion.
- Synthetic fixtures only. No mission data are included.

## Not in 0.1.0

- A real Roman L2 product with a CRDS detector-distortion WCS has not been accepted.
- No scientific distance mode. Every source is `distance_unknown`.
- No adaptive mesh. A uniform grid is sampled and checked against a residual budget.
- NGRST-Discovery-Toolkit was not readable from this environment, so the catalogue adapter follows the documented column names and has not been run on a live export.
