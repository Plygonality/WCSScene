"""N-panel inspector. Readouts come from the imported bundle, not from a render."""

from __future__ import annotations

import bpy

from .properties import manifest_text, source_index


class WCSSCENE_PT_main(bpy.types.Panel):
    bl_label = "WCSScene"
    bl_idname = "WCSSCENE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "WCSScene"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.wcsscene
        manifest = manifest_text()
        image = manifest.get("image") or {}
        presentation = manifest.get("presentation") or {}
        wcs = manifest.get("wcs") or {}
        header = image.get("header_meta") or {}

        col = layout.column(align=True)
        col.operator("wcsscene.import_bundle", icon="IMPORT")
        col.operator("wcsscene.reimport_bundle", icon="FILE_REFRESH")
        col.operator("wcsscene.validate_scene", icon="CHECKMARK")
        if settings.status:
            col.label(text=f"Status: {settings.status}")

        box = layout.box()
        box.label(text="Image")
        filename = header.get("filename") or _input_name(manifest)
        box.label(text=f"File: {filename or '—'}")
        level = header.get("product_level") or (image.get("roman") or {}).get("product_level") or "—"
        box.label(text=f"Product / level: {level}")
        hdu = image.get("hdu_name")
        if hdu is None:
            hdu = image.get("hdu_index")
        box.label(text=f"HDU: {hdu}")
        shape = image.get("shape_yx")
        box.label(text=f"Shape (y, x): {shape}")
        box.label(text=f"Units: {image.get('units') or 'undeclared'}")
        if settings.mode == "pixel_preview":
            box.label(text="PIXEL PREVIEW — no sky accuracy")
        else:
            box.label(text=f"WCS: {wcs.get('kind') or 'missing'}")
            box.label(text=f"Frame: {wcs.get('frame_key') or wcs.get('frame') or '—'}")
            tangent = presentation.get("tangent_point") or {}
            box.label(text=f"Tangent deg: {_short(tangent.get('lon_deg'))}, {_short(tangent.get('lat_deg'))}")
            scale = presentation.get("local_pixel_scale_arcsec") or {}
            mean = scale.get("geometric_mean_arcsec") if isinstance(scale, dict) else None
            box.label(text=f"Local pixel scale: {_short(mean)} arcsec")
            box.label(text=f"Arcsec / Blender unit: {presentation.get('arcsec_per_blender_unit')}")
        approx = (manifest.get("mesh") or {}).get("approximation")
        if approx:
            box.label(text=f"Mesh: {approx}")

        layout.prop(settings, "show_image")
        layout.prop(settings, "show_markers")
        layout.prop(settings, "show_labels")
        layout.prop(settings, "show_grid")
        layout.prop(settings, "show_mask")
        layout.prop(settings, "show_warnings")
        layout.prop(settings, "show_sky")

        display = layout.box()
        display.label(text="Display (visual only)")
        display.prop(settings, "stretch")
        display.prop(settings, "colormap")
        display.prop(settings, "percentile_low")
        display.prop(settings, "percentile_high")
        display.operator("wcsscene.apply_display")

        src = layout.box()
        src.label(text="Source")
        src.prop(settings, "active_source_id")
        src.operator("wcsscene.focus_source")
        record = source_index(context).get(settings.active_source_id)
        if record is None:
            src.label(text="No source selected")
            return
        src.label(text=f"Catalogue row: {record.get('catalog_row')}")
        src.label(text=f"Pixel (x, y): {_short(record.get('pixel_xy_input'))}")
        if settings.show_sky and settings.mode != "pixel_preview":
            src.label(text=f"Sky deg: {_short(record.get('sky_input_deg') or record.get('sky_from_pixel_deg'))}")
        else:
            src.label(text="Sky readout off")
        src.label(text=f"Scene: {_short(record.get('scene_xyz'))}")
        src.label(text=f"Placed: {record.get('placed')} ({record.get('placement_reason')})")
        src.label(text=f"SNR: {record.get('snr')}")
        src.label(text=f"Anomaly score: {record.get('anomaly_score')}")
        src.label(text=f"Anomaly percentile: {record.get('anomaly_percentile')}")
        src.label(text="Anomaly is a within-image score")
        src.label(text=f"Known: {record.get('known')}")
        src.label(text=f"Reference id: {record.get('reference_id') or '—'}")
        src.label(text=f"Distance: {record.get('distance_status')}")
        src.label(text=f"Uncertainty: {record.get('uncertainty_status')}")
        catalog = (manifest.get("catalog") or {}).get("path")
        src.label(text=f"Catalogue: {catalog or 'embedded / none'}")

        warnings = manifest.get("warnings") or []
        if settings.show_warnings and warnings:
            warn = layout.box()
            warn.label(text="Warnings")
            for item in warnings[:8]:
                warn.label(text=f"{item.get('severity')}: {item.get('code')}")


def _input_name(manifest: dict) -> str:
    inputs = manifest.get("inputs") or []
    if not inputs:
        return ""
    path = str(inputs[0].get("path") or "")
    return path.rsplit("/", 1)[-1]


def _short(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, float):
                parts.append(f"{item:.6g}")
            else:
                parts.append(str(item))
        return "(" + ", ".join(parts) + ")"
    return str(value)


CLASSES = (WCSSCENE_PT_main,)
