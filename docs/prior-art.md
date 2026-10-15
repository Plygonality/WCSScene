# Prior art

WCSScene is a traceable WCS-to-Blender exchange. The tools below already visualise astronomical images or put sky data into a 3D application. Licences below were checked against the project's own documentation during this build, except where a row says the licence was not re-verified.

| Project | Role | Licence | How WCSScene differs |
| --- | --- | --- | --- |
| [SAOImage DS9](https://sites.google.com/cfa.harvard.edu/saoimageds9) | Image and catalogue display, WCS readout | GPL-3.0 | DS9 is the interactive standard. WCSScene exports an editable Blender scene with a recorded tangent plane, mesh residual, and source provenance. |
| [Aladin Desktop](https://aladin.cds.unistra.fr/) | Sky atlas, image, and catalogue client | GPL-3.0 | Aladin browses surveys and catalogues. WCSScene does not query archives and does not claim survey calibration. |
| [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) | In-browser HiPS viewer | LGPL-3.0-or-later | A web viewer of hierarchical surveys, not a Blender exchange. |
| [Glue](https://glueviz.org/) | Linked statistical views of tabular and image data | BSD-3-Clause (project README) | Glue links selections across views. WCSScene's product is a scene file with an explicit presentation transform. |
| [Ginga](https://ginga.readthedocs.io/) | FITS viewer toolkit | BSD (project licence) | Ginga displays and plugins around FITS. It does not build a sampled WCS mesh for Blender. |
| [APLpy](https://aplpy.github.io/) | Publication figures from FITS and WCS | MIT | APLpy draws static figures. WCSScene keeps the scientific array separate from the visual stretch and round-trips into a DCC. |
| [Jdaviz](https://jdaviz.readthedocs.io/) | Jupyter viewers for spectra and images | BSD-3-Clause | Analysis widgets for JWST-style products. Not a Blender importer, and not used as a Roman calibrator here. |
| [CARTA](https://cartavis.org/) | Remote image viewer aimed at large cubes | GPL-3.0 | CARTA visualises cubes in a browser or desktop client. WCSScene refuses extra WCS axes instead of displaying a cube. |
| [TOPCAT](https://www.star.bris.ac.uk/mbt/topcat/) | Table and catalogue tool | GPL (application; some libraries are LGPL) | TOPCAT edits and matches tables. WCSScene consumes a table and checks it against the image WCS. |
| [FitsMap](https://github.com/ryanhausen/fitsmap) | FITS to a web slippy map | MIT | FitsMap publishes a tiled web map. WCSScene publishes a Blender bundle with a residual report. |
| [OpenSpace](https://www.openspaceproject.com/) | Planetarium-scale universe visualisation | MIT | OpenSpace presents contextual 3D tours. WCSScene keeps one exposure on a labelled 2.5D plane unless a separate distance is supplied and validated. |
| FRELLED, AstroBlend | Earlier Blender links for FITS or volumetric astronomy | Not re-verified in this build | Cited only as prior Blender experiments. Their licences were not copied into this table without a current project page. |

## Nearby Plygonality repositories

These are optional ecosystem links. They are not runtime dependencies, and this repository does not modify them.

| Repository | Relationship |
| --- | --- |
| NGRST-Discovery-Toolkit | When its object-catalogue export is available, the column names `label`, `x_centroid`, `y_centroid`, `ra`, `dec`, `snr`, `anomaly_score`, `anomaly_percentile`, `known`, and `reference_id` are accepted. The private repository was not readable from the account used for this build, so no live export was tested. Fields may be blank. Distances and uncertainties are not invented from it. |
| NodeBridge | A DCC graph translator. Not used. |
| Plygon-mcp | A local MCP bridge. Not used. WCSScene does not require a running MCP connection. |
| RomanRecoverer | No repository was visible to this account. The FITS and Roman paths do not depend on it. |

WCSScene's licence is MIT. Blender itself is GPL-2.0-or-later, so using the add-on inside Blender is constrained by Blender's licence. The scientific package does not import Blender.
