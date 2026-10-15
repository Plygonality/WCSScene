"""Load a versioned exchange bundle. Schema 1.x is accepted; 1.0 is written."""

from __future__ import annotations

import json
from pathlib import Path

from .npy_io import NpyArray, load_npy, load_npz

SCHEMA_MAJOR = 1


class BundleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def resolve_bundle(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        manifest = candidate / "manifest.json"
    elif candidate.name == "manifest.json":
        manifest = candidate
    else:
        manifest = candidate
    if not manifest.is_file():
        raise BundleError("MISSING_MANIFEST", f"no manifest.json at {candidate}")
    return manifest


def load_bundle(path: str | Path) -> dict:
    manifest_path = resolve_bundle(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = str(manifest.get("schema_version", ""))
    major = schema.split(".", 1)[0]
    if major != str(SCHEMA_MAJOR):
        raise BundleError(
            "SCHEMA_UNSUPPORTED",
            f"schema {schema!r} is outside major version {SCHEMA_MAJOR}. "
            "v0.1 reads schema 1.x and does not migrate other majors.",
        )
    root = manifest_path.parent
    files = manifest.get("files") or {}
    required = ("display_png", "science_npy", "mask_npy", "geometry_npz", "sources_json")
    paths = {}
    for key in required:
        name = (files.get(key) or {}).get("name")
        if not name:
            raise BundleError("MISSING_FILE", f"manifest.files.{key} is absent")
        file_path = root / name
        if not file_path.is_file():
            raise BundleError("MISSING_FILE", f"missing bundle file {file_path.name}")
        paths[key] = file_path
    sources = json.loads(paths["sources_json"].read_text(encoding="utf-8"))
    geometry = load_npz(paths["geometry_npz"])
    for key in ("xyz", "uv", "faces", "marker_xyz"):
        if key not in geometry:
            raise BundleError("MISSING_FILE", f"geometry.npz has no {key} array")
    return {
        "manifest_path": manifest_path,
        "root": root,
        "manifest": manifest,
        "sources": sources,
        "geometry": geometry,
        "paths": paths,
    }


def load_science(bundle: dict) -> tuple[NpyArray, NpyArray]:
    return load_npy(bundle["paths"]["science_npy"]), load_npy(bundle["paths"]["mask_npy"])
