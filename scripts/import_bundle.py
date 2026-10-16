"""Import an exchange bundle in background Blender.

Example, from the repository root, with the tested Blender 4.5 binary::

    blender --background --python-exit-code 7 --python scripts/import_bundle.py -- build/reference

``--python-exit-code 7`` makes a failed script return exit status 7.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_addon"))

import wcsscene  # noqa: E402


def _args() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def main() -> None:
    args = _args()
    if not args:
        print("usage: blender --background --python scripts/import_bundle.py -- BUNDLE [--save FILE] [--render FILE]")
        raise SystemExit(7)
    bundle = args[0]
    save = None
    render = None
    index = 1
    while index < len(args):
        if args[index] == "--save" and index + 1 < len(args):
            save = args[index + 1]
            index += 2
        elif args[index] == "--render" and index + 1 < len(args):
            render = args[index + 1]
            index += 2
        else:
            print(f"unknown argument {args[index]}")
            raise SystemExit(7)
    wcsscene.register()
    try:
        wcsscene.import_bundle(bundle)
        report = wcsscene.geometry.validate_scene()
    except Exception as exc:
        print(f"BLENDER_IMPORT_FAIL {exc}")
        raise SystemExit(7) from exc
    print(f"BLENDER_IMPORT status={report['status']} errors={report['error_count']}")
    if report["status"] != "pass":
        print(report)
        raise SystemExit(7)
    if save:
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(save).resolve()))
        print(f"BLENDER_SAVED {save}")
    if render:
        _render(render)
        print(f"BLENDER_RENDERED {render}")


def _render(path: str) -> None:
    scene = bpy.context.scene
    camera = bpy.data.objects.get("WCSScene_Camera")
    if camera is not None:
        scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(path).resolve())
    world = scene.world
    if world and world.use_nodes:
        background = world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.015, 0.016, 0.02, 1.0)
            background.inputs["Strength"].default_value = 1.0
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
