"""Command line for preparing and checking WCSScene bundles."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .errors import InvalidInput, WCSSceneError
from .exchange import PrepareConfig, prepare
from .io_fits import hdu_descriptions, load_fits, resolve_hdu
from .provenance import package_version, runtime_versions
from .validate import validate_bundle
from .wcs_adapter import (
    describe_distortion,
    local_pixel_scale,
    reference_pixel,
    require_celestial_wcs,
)

EXIT_BLENDER = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wcsscene",
        description=(
            "Build a scientifically traceable 2.5D Blender exchange bundle from an "
            "astronomical image and its WCS. Blender units are an angular presentation "
            "scale, not distance."
        ),
    )
    parser.add_argument("--version", action="version", version=f"wcsscene {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Write a synthetic TAN field and its exchange bundle")
    demo.add_argument("--out", required=True, help="Output directory")
    demo.set_defaults(func=cmd_demo)

    inspect = sub.add_parser("inspect", help="Describe a FITS HDU and its WCS")
    inspect.add_argument("path")
    inspect.add_argument("--hdu", default=None, help="HDU name or index")
    inspect.add_argument("--json", action="store_true")
    inspect.set_defaults(func=cmd_inspect)

    prepare_parser = sub.add_parser("prepare", help="Write an exchange bundle")
    prepare_parser.add_argument("path")
    prepare_parser.add_argument("--hdu", default=None)
    prepare_parser.add_argument("--catalog", default=None)
    prepare_parser.add_argument("--format", default="auto", choices=["auto", "fits", "roman", "npz"])
    prepare_parser.add_argument("--projection", default="tan")
    prepare_parser.add_argument(
        "--arcsec-per-bu",
        type=float,
        default=1.0,
        help="Arcseconds represented by one Blender unit in scientific mode",
    )
    prepare_parser.add_argument("--pixel-preview", action="store_true")
    prepare_parser.add_argument("--coord-authority", default="auto", choices=["auto", "pixel", "sky"])
    prepare_parser.add_argument("--coord-tolerance-arcsec", type=float, default=0.05)
    prepare_parser.add_argument("--pixel-origin", type=int, default=0, choices=[0, 1])
    prepare_parser.add_argument("--mesh-cells", type=int, default=32)
    prepare_parser.add_argument("--residual-budget-arcsec", type=float, default=None)
    prepare_parser.add_argument("--allow-residual", action="store_true")
    prepare_parser.add_argument("--flat-rectangle", action="store_true")
    prepare_parser.add_argument("--stretch", default="asinh", choices=["linear", "asinh", "log"])
    prepare_parser.add_argument("--percentiles", type=float, nargs=2, default=(1.0, 99.0))
    prepare_parser.add_argument("--colormap", default="gray", choices=["gray", "heat", "slate"])
    prepare_parser.add_argument("--max-display-pixels", type=int, default=2048)
    prepare_parser.add_argument("--downsample", type=int, default=None)
    prepare_parser.add_argument("--crop", type=int, nargs=4, default=None, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    prepare_parser.add_argument("--east-left", action="store_true")
    prepare_parser.add_argument("--pixel-uncertainty", action="store_true")
    prepare_parser.add_argument("--sky-uncertainty-convention", default=None)
    prepare_parser.add_argument("--highlight", default=None)
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.set_defaults(func=cmd_prepare)

    validate_parser = sub.add_parser("validate", help="Check an exchange manifest")
    validate_parser.add_argument("manifest")
    validate_parser.add_argument("--report", required=True)
    validate_parser.set_defaults(func=cmd_validate)

    doctor = sub.add_parser("doctor", help="Report installed scientific and Blender capabilities")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if code is not None else 0
    try:
        return int(args.func(args))
    except WCSSceneError as exc:
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return exc.exit_code


def cmd_demo(args: argparse.Namespace) -> int:
    from .synthetic import write_reference_catalog, write_reference_fits

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fits_path = out / "reference.fits"
    catalog_path = out / "reference_sources.ecsv"
    wcs = write_reference_fits(fits_path)
    write_reference_catalog(catalog_path, wcs)
    result = prepare(
        fits_path,
        out,
        PrepareConfig(
            hdu="SCI",
            catalog=str(catalog_path),
            arcsec_per_bu=1.0,
            highlight_source_id="SRC-B",
            command=["wcsscene", "demo", "--out", str(out)],
        ),
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    residual = manifest["mesh"]["residual"]
    roundtrip = manifest["roundtrip"]
    print(f"bundle: {result.out_dir}")
    print(f"content_id: {manifest['content_id']}")
    print(f"round-trip max pixel error: {roundtrip['max_pixel_error']}")
    print(f"mesh max residual arcsec: {residual['max_arcsec']}")
    print("highlight: SRC-B (see qa_report.md)")
    print("note: synthetic fixture, not a telescope observation")
    print(f"status: {result.validation_status}")
    return result.exit_code


def cmd_inspect(args: argparse.Namespace) -> int:
    from astropy.io import fits

    fits_path = Path(args.path)
    if not fits_path.is_file():
        raise InvalidInput(f"File not found: {fits_path}")
    if fits_path.suffix.lower() not in {".fits", ".fit", ".fts"}:
        raise InvalidInput(f"{fits_path.name} is not a FITS file")
    with fits.open(fits_path) as hdul:
        descriptions = hdu_descriptions(hdul)
        index = resolve_hdu(hdul, args.hdu)
    loaded = load_fits(fits_path, index)
    report: dict = {
        "path": str(fits_path),
        "hdus": descriptions,
        "selected_index": loaded.hdu_index,
        "selected_name": loaded.hdu_name,
        "shape_yx": list(loaded.data.shape),
        "units": loaded.units,
        "units_note": loaded.product_note,
        "header_meta": loaded.header_meta,
    }
    if loaded.wcs is None:
        report["wcs_status"] = "missing"
        report["scientific_placement"] = "refused without --pixel-preview"
    else:
        try:
            require_celestial_wcs(loaded.wcs)
            ref_x, ref_y, ref_source = reference_pixel(loaded.wcs, loaded.data.shape)
            scale = local_pixel_scale(loaded.wcs, ref_x, ref_y)
            report["wcs_status"] = "valid"
            report["wcs_kind"] = loaded.wcs_kind
            report["frame"] = loaded.wcs.pixel_to_world(ref_x, ref_y).frame.name
            report["reference_pixel_xy"] = [ref_x, ref_y]
            report["reference_pixel_source"] = ref_source
            report["local_pixel_scale_arcsec"] = scale
            report["distortion"] = describe_distortion(loaded.wcs)
        except WCSSceneError as exc:
            report["wcs_status"] = exc.code
            report["wcs_error"] = str(exc)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(f"path: {report['path']}")
        print("hdus:")
        for row in descriptions:
            print(f"  {row}")
        print(f"selected: {loaded.hdu_index}:{loaded.hdu_name} shape_yx={tuple(loaded.data.shape)}")
        print(f"units: {loaded.units}")
        print(f"wcs: {report['wcs_status']}")
        if report.get("frame"):
            print(f"frame: {report['frame']}")
            print(f"reference pixel (x, y): {report['reference_pixel_xy']} ({report['reference_pixel_source']})")
            scale = report["local_pixel_scale_arcsec"]
            print(
                "local pixel scale arcsec: "
                f"x={scale['x_arcsec']:.6g} y={scale['y_arcsec']:.6g} "
                "(local linear step, not a distorted global plate scale)"
            )
            print(f"distortion: {report['distortion']['kind']}")
        if report.get("wcs_error"):
            print(f"wcs error: {report['wcs_error']}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    config = PrepareConfig(
        hdu=args.hdu,
        catalog=args.catalog,
        projection=args.projection,
        arcsec_per_bu=args.arcsec_per_bu,
        pixel_preview=args.pixel_preview,
        fmt=args.format,
        coord_authority=args.coord_authority,
        coord_tolerance_arcsec=args.coord_tolerance_arcsec,
        pixel_origin=args.pixel_origin,
        mesh_cells=args.mesh_cells,
        residual_budget_arcsec=args.residual_budget_arcsec,
        fail_on_residual=not args.allow_residual,
        flat_rectangle=args.flat_rectangle,
        stretch=args.stretch,
        percentiles=(args.percentiles[0], args.percentiles[1]),
        colormap=args.colormap,
        max_display_pixels=args.max_display_pixels,
        downsample=args.downsample,
        crop=tuple(args.crop) if args.crop else None,
        east_left=args.east_left,
        pixel_uncertainty=args.pixel_uncertainty,
        sky_uncertainty_convention=args.sky_uncertainty_convention,
        highlight_source_id=args.highlight,
        command=sys.argv[1:],
    )
    result = prepare(args.path, args.out, config)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    print(f"wrote {result.manifest_path}")
    print(f"mode: {manifest['mode']}")
    print(f"content_id: {manifest['content_id']}")
    print(f"status: {result.validation_status}")
    for item in result.warnings:
        if item["severity"] in {"warning", "error"}:
            print(f"{item['severity']} [{item['code']}]: {item['message']}")
    return result.exit_code


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_bundle(args.manifest)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status: {report['status']}")
    print(f"errors: {report['error_count']} warnings: {report['warning_count']}")
    print(f"report: {report_path}")
    return 0 if report["status"] == "pass" else 4


def cmd_doctor(_args: argparse.Namespace) -> int:
    versions = runtime_versions()
    blender = shutil.which("blender")
    home_blender = Path.home() / "blender" / "blender"
    if blender is None and home_blender.is_file():
        blender = str(home_blender)
    print(f"wcsscene {__version__}")
    for name, value in versions.items():
        print(f"{name}: {value if value is not None else 'not installed'}")
    print(f"roman_datamodels: {package_version('roman-datamodels') or 'not installed'}")
    print(f"blender: {blender or 'not found'}")
    print("network: not required")
    print("flight Roman products verified: no")
    if package_version("roman-datamodels") is None:
        print("roman prepare will return MISSING_OPTIONAL_DEPENDENCY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
