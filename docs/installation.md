# Installation

Tested on Python 3.12.3 with the versions in `requirements-tested.txt`, and on Blender 4.5.14 LTS (build hash `62c1db4208e8`, built 2026-09-15). The package requires Python 3.11 or newer. The add-on manifest allows Blender 4.2 or newer; only 4.5.14 was executed.

## Scientific package

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[roman,dev]"
wcsscene doctor
```

`roman` installs `asdf`, `gwcs`, and `roman-datamodels`. Omit it and Roman files fail with `MISSING_OPTIONAL_DEPENDENCY` (exit 5). Core FITS preparation needs only NumPy and Astropy. SciPy is not required for v0.1.

The package does not phone home, download survey data, or need a network connection after installation.

## Blender extension

The add-on is `blender_addon/wcsscene`. It does not import Astropy, NumPy, or the scientific package. Build a zip with the Blender that will load it:

```bash
blender --command extension build \
  --source-dir blender_addon/wcsscene \
  --output-filepath dist/wcsscene-0.1.0.zip
blender --command extension validate dist/wcsscene-0.1.0.zip
```

Install that zip from Blender's extension preferences, or run the background importer against a bundle directory:

```bash
blender --background --python-exit-code 7 \
  --python scripts/import_bundle.py -- build/reference
```

`--python-exit-code 7` is required. Without it, Blender can return 0 even when the script fails. Exit 7 means the import or the scene validation failed.

Save and render in the same process with:

```bash
blender --background --python-exit-code 7 \
  --python scripts/import_bundle.py -- build/demo \
  --save build/demo_scene.blend --render build/demo_scene.png
```

The interactive panel is the 3D Viewport sidebar, category **WCSScene**. Import selects `manifest.json`. Reimport deletes only datablocks whose names start with `WCSScene`. Validate Scene compares the image mesh and marker vertices with `geometry.npz`.

## Offline examples

```bash
python scripts/generate_examples.py
```

The files under `examples/` are synthetic. Do not label them as telescope observations.
