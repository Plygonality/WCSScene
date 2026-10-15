"""Headless acceptance check for one real Blender session.

Creates an unrelated object, imports a bundle, checks the highlighted source,
saves a .blend, reimports, and confirms the unrelated object is still there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_addon"))

import wcsscene  # noqa: E402


def _args() -> list[str]:
    if "--" not in sys.argv:
        raise SystemExit("missing bundle argument after --")
    return sys.argv[sys.argv.index("--") + 1 :]


def main() -> None:
    bundle_dir, blend_path, render_path = _args()
    bundle = Path(bundle_dir)
    sources = json.loads((bundle / "sources.json").read_text(encoding="utf-8"))
    src_b = next(row for row in sources if row["source_id"] == "SRC-B")

    keep_mesh = bpy.data.meshes.new("KeepMeMesh")
    keep_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    keep = bpy.data.objects.new("KeepMe", keep_mesh)
    keep.location = (5000.0, 5000.0, 5000.0)
    bpy.context.scene.collection.objects.link(keep)
    user_cam_data = bpy.data.cameras.new("UserCam")
    user_cam = bpy.data.objects.new("UserCam", user_cam_data)
    user_cam.location = (80.0, -80.0, 40.0)
    bpy.context.scene.collection.objects.link(user_cam)
    bpy.context.scene.camera = user_cam

    wcsscene.register()
    wcsscene.import_bundle(str(bundle))
    if bpy.context.scene.camera != user_cam:
        raise SystemExit("import replaced the user camera")
    _assert_src_b(src_b)
    first = wcsscene.geometry.validate_scene()
    if first["status"] != "pass":
        raise SystemExit(f"validate failed after import: {first}")

    Path(blend_path).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_path).resolve()))

    before = {obj.name for obj in bpy.data.objects if not obj.name.startswith("WCSScene")}
    bpy.ops.wcsscene.reimport_bundle()
    after = {obj.name for obj in bpy.data.objects if not obj.name.startswith("WCSScene")}
    if "KeepMe" not in after or "UserCam" not in after:
        raise SystemExit(f"reimport removed user objects: {sorted(before - after)}")
    if bpy.data.objects["KeepMe"].location.x != 5000.0:
        raise SystemExit("KeepMe was moved")
    _assert_src_b(src_b)
    second = wcsscene.geometry.validate_scene()
    if second["status"] != "pass":
        raise SystemExit(f"validate failed after reimport: {second}")

    owned = [obj.name for obj in bpy.data.objects if obj.name.startswith("WCSScene")]
    marker = bpy.data.objects["WCSScene_Markers"]
    if len(marker.data.vertices) != len([row for row in sources if row.get("placed")]):
        raise SystemExit("marker vertex count does not match placed sources")
    if any(name.startswith("WCSScene_Marker_") for name in owned):
        raise SystemExit("per-source marker objects were created")

    scene = bpy.context.scene
    scene.camera = bpy.data.objects["WCSScene_Camera"]
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(render_path).resolve())
    world = scene.world
    if world and world.use_nodes:
        background = world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = (0.015, 0.016, 0.02, 1.0)
            background.inputs["Strength"].default_value = 1.0
    for name in ("Cube", "Light"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_render = True
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_path).resolve()))
    xyz = src_b["scene_xyz"]
    print(
        "BLENDER_SMOKE status=pass "
        f"src_b_xyz={xyz[0]:.6f},{xyz[1]:.6f},{xyz[2]:.6f} "
        f"markers={len(marker.data.vertices)} "
        f"owned={len(owned)} blend={blend_path}"
    )


def _assert_src_b(source: dict) -> None:
    mesh = bpy.data.objects["WCSScene_Markers"].data
    rows = mesh.attributes["catalog_row"]
    found = None
    for index, vertex in enumerate(mesh.vertices):
        if int(rows.data[index].value) == int(source["catalog_row"]):
            found = vertex.co
            break
    if found is None:
        raise SystemExit("SRC-B marker vertex is missing")
    xyz = source["scene_xyz"]
    if abs(found.x - xyz[0]) > 1e-5 or abs(found.y - xyz[1]) > 1e-5 or abs(found.z - xyz[2]) > 1e-5:
        raise SystemExit(f"SRC-B mismatch mesh={tuple(found)} bundle={xyz}")
    highlight = bpy.data.objects["WCSScene_Highlight"]
    if highlight.get("source_id") != "SRC-B":
        raise SystemExit(f"highlight source is {highlight.get('source_id')}")
    if abs(float(highlight["pixel_x"]) - 70.0) > 1e-6 or abs(float(highlight["pixel_y"]) - 18.0) > 1e-6:
        raise SystemExit("highlight pixel coordinate is not (70, 18)")
    lift = float(highlight.get("annotation_z") or 0.0)
    if abs(highlight.location.x - xyz[0]) > 1e-5 or abs(highlight.location.y - xyz[1]) > 1e-5:
        raise SystemExit("highlight XY is not the catalogue scene position")
    if abs(highlight.location.z - xyz[2] - lift) > 1e-5:
        raise SystemExit("highlight Z is not the presentation plane plus the annotation lift")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"BLENDER_SMOKE status=fail error={exc}")
        raise SystemExit(7) from exc
