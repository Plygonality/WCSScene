"""Import, reimport, display, and scene-validation operators."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from .bundle import BundleError
from .display_math import DisplayError, downsample, render_rgb
from .geometry import apply_visibility, clear_owned, import_bundle, validate_scene
from .materials import replace_image


class WCSSCENE_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "wcsscene.import_bundle"
    bl_label = "Import Exchange Bundle"
    bl_description = "Import a validated WCSScene exchange bundle"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            _import_path(self.filepath, context)
        except BundleError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Imported WCSScene bundle")
        return {"FINISHED"}


class WCSSCENE_OT_reimport(bpy.types.Operator):
    bl_idname = "wcsscene.reimport_bundle"
    bl_label = "Reimport / Update"
    bl_description = "Replace only WCSScene collections, objects, and materials"

    def execute(self, context):
        path = context.scene.wcsscene.manifest_path
        if not path:
            self.report({"ERROR"}, "MISSING_MANIFEST: import a bundle first")
            return {"CANCELLED"}
        try:
            _import_path(path, context)
        except BundleError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Reimported WCSScene bundle")
        return {"FINISHED"}


class WCSSCENE_OT_validate(bpy.types.Operator):
    bl_idname = "wcsscene.validate_scene"
    bl_label = "Validate Scene"
    bl_description = "Check marker alignment, mesh residuals recorded in the bundle, and owned data"

    def execute(self, context):
        report = validate_scene()
        if report["status"] != "pass":
            codes = [row["code"] for row in report["checks"] if not row["ok"]]
            self.report({"ERROR"}, "VALIDATION_FAILED: " + ", ".join(codes))
            return {"CANCELLED"}
        self.report({"INFO"}, "Scene matches the exchange bundle")
        return {"FINISHED"}


class WCSSCENE_OT_display(bpy.types.Operator):
    bl_idname = "wcsscene.apply_display"
    bl_label = "Apply Display"
    bl_description = "Rebuild the visual image. Scientific samples in science.npy are not modified"

    def execute(self, context):
        try:
            refresh_display(context.scene.wcsscene)
        except DisplayError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except BundleError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Updated the visual display only")
        return {"FINISHED"}


class WCSSCENE_OT_focus_source(bpy.types.Operator):
    bl_idname = "wcsscene.focus_source"
    bl_label = "Show Source"
    bl_description = "Move the highlight marker to the named catalogue source"

    def execute(self, context):
        from .properties import source_index

        settings = context.scene.wcsscene
        rows = source_index(context)
        source = rows.get(settings.active_source_id)
        if source is None:
            self.report({"ERROR"}, "UNKNOWN_SOURCE: that source id is not in the bundle")
            return {"CANCELLED"}
        if not source.get("placed") or not source.get("scene_xyz"):
            self.report({"WARNING"}, "Source is not placed. It was not moved to the origin.")
            return {"CANCELLED"}
        obj = bpy.data.objects.get("WCSScene_Highlight")
        if obj is None:
            self.report({"ERROR"}, "MISSING_HIGHLIGHT")
            return {"CANCELLED"}
        xyz = source["scene_xyz"]
        lift = float(obj.get("annotation_z") or 0.0)
        obj.location = (float(xyz[0]), float(xyz[1]), float(xyz[2]) + lift)
        from .geometry import _copy_source_props

        _copy_source_props(obj, source)
        self.report({"INFO"}, f"Highlight is {source['source_id']}, catalogue row {source['catalog_row']}")
        return {"FINISHED"}


def _import_path(path: str, context) -> None:
    settings = context.scene.wcsscene
    settings.suspend = True
    try:
        import_bundle(path, replace=True)
        apply_visibility(context.scene.wcsscene)
    finally:
        context.scene.wcsscene.suspend = False


def refresh_display(settings) -> None:
    from .bundle import load_bundle, load_science

    if not settings.manifest_path:
        raise BundleError("MISSING_MANIFEST", "import a bundle before changing the display")
    bundle = load_bundle(settings.manifest_path)
    science, mask = load_science(bundle)
    pixels = int(science.shape[0]) * int(science.shape[1])
    if pixels > 1_500_000:
        raise DisplayError(
            "DISPLAY_TOO_LARGE",
            f"science array has {pixels} pixels. Refusing to rebuild it inside Blender. "
            "Re-run wcsscene prepare with a crop or downsample.",
        )
    factor = int((bundle["manifest"].get("image") or {}).get("downsample_factor") or 1)
    science, mask = downsample(science, mask, factor)
    rgb, _meta = render_rgb(
        science,
        mask,
        stretch=settings.stretch,
        percentiles=(settings.percentile_low, settings.percentile_high),
        colormap=settings.colormap,
        show_mask=settings.show_mask,
    )
    height, width = science.shape
    image = bpy.data.images.get("WCSScene_Display")
    if image is None or image.size[0] != width or image.size[1] != height:
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new("WCSScene_Display", width=width, height=height, alpha=True)
    flat = [0.0] * (width * height * 4)
    for index, pixel in enumerate(rgb):
        flat[index * 4] = pixel[0] / 255.0
        flat[index * 4 + 1] = pixel[1] / 255.0
        flat[index * 4 + 2] = pixel[2] / 255.0
        flat[index * 4 + 3] = 1.0
    image.pixels.foreach_set(flat)
    image.update()
    material = bpy.data.materials.get("WCSScene_Image")
    replace_image(material, image)


def clear_for_tests() -> None:
    clear_owned()


CLASSES = (
    WCSSCENE_OT_import,
    WCSSCENE_OT_reimport,
    WCSSCENE_OT_validate,
    WCSSCENE_OT_display,
    WCSSCENE_OT_focus_source,
)
