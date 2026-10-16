"""Scene settings for the WCSScene sidebar."""

from __future__ import annotations

import bpy


def _visibility(self, context):
    if getattr(self, "suspend", False):
        return
    from .geometry import apply_visibility

    apply_visibility(self)


class WCSSceneSettings(bpy.types.PropertyGroup):
    bundle_dir: bpy.props.StringProperty(name="Bundle directory", default="")
    manifest_path: bpy.props.StringProperty(name="Manifest", default="")
    content_id: bpy.props.StringProperty(name="Content id", default="")
    mode: bpy.props.StringProperty(name="Mode", default="")
    status: bpy.props.StringProperty(name="Status", default="")
    last_report: bpy.props.StringProperty(name="Validation", default="")
    active_source_id: bpy.props.StringProperty(name="Source", default="")
    suspend: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    show_image: bpy.props.BoolProperty(name="Image surface", default=True, update=_visibility)
    show_markers: bpy.props.BoolProperty(name="Source markers", default=True, update=_visibility)
    show_labels: bpy.props.BoolProperty(name="Labels", default=True, update=_visibility)
    show_grid: bpy.props.BoolProperty(name="Reference grid and axes", default=True, update=_visibility)
    show_mask: bpy.props.BoolProperty(name="Valid-pixel mask", default=True)
    show_warnings: bpy.props.BoolProperty(name="Quality warnings", default=True, update=_visibility)
    show_sky: bpy.props.BoolProperty(name="Sky coordinate readout", default=True)

    stretch: bpy.props.EnumProperty(
        name="Stretch",
        items=(
            ("linear", "Linear", "Linear display stretch"),
            ("asinh", "Asinh", "Inverse hyperbolic sine stretch"),
            ("log", "Log", "Log stretch, refused when the range is negative"),
        ),
        default="asinh",
    )
    colormap: bpy.props.EnumProperty(
        name="Colormap",
        items=(
            ("gray", "Gray", "Neutral gray"),
            ("heat", "Heat", "Black-red-white"),
            ("slate", "Slate", "Muted blue-gray"),
        ),
        default="gray",
    )
    percentile_low: bpy.props.FloatProperty(name="Low percentile", default=1.0, min=0.0, max=100.0)
    percentile_high: bpy.props.FloatProperty(name="High percentile", default=99.0, min=0.0, max=100.0)


def source_index(context) -> dict[str, dict]:
    text = bpy.data.texts.get("WCSScene_sources.json")
    if text is None:
        return {}
    import json

    try:
        rows = json.loads(text.as_string())
    except json.JSONDecodeError:
        return {}
    return {str(row.get("source_id")): row for row in rows}


def manifest_text() -> dict:
    text = bpy.data.texts.get("WCSScene_manifest.json")
    if text is None:
        return {}
    import json

    try:
        return json.loads(text.as_string())
    except json.JSONDecodeError:
        return {}
