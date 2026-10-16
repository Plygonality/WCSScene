"""Build WCSScene-owned geometry from an exchange bundle.

Blender coordinates are the presentation transform stored in the bundle.
Marker Z offsets used to lift annotations off the image are not distances.
"""

from __future__ import annotations

import json
import math

import bpy

from .bundle import BundleError
from .materials import (
    east_material,
    ellipse_material,
    grid_material,
    highlight_material,
    image_material,
    label_material,
    marker_material,
    north_material,
)

PREFIX = "WCSScene"
_LABEL_LIMIT = 48


def clear_owned() -> None:
    """Remove datablocks this add-on created. User objects are left in place."""
    for obj in list(bpy.data.objects):
        if obj.name.startswith(PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.name.startswith(PREFIX):
            bpy.data.collections.remove(collection)
    for material in list(bpy.data.materials):
        if material.name.startswith(PREFIX):
            bpy.data.materials.remove(material)
    for image in list(bpy.data.images):
        if image.name.startswith(PREFIX):
            bpy.data.images.remove(image)
    for group in list(bpy.data.node_groups):
        if group.name.startswith(PREFIX):
            bpy.data.node_groups.remove(group)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(PREFIX) and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for curve in list(bpy.data.curves):
        if curve.name.startswith(PREFIX) and curve.users == 0:
            bpy.data.curves.remove(curve)
    for text in list(bpy.data.texts):
        if text.name.startswith(PREFIX):
            bpy.data.texts.remove(text)


def import_bundle(path: str, *, replace: bool = True) -> dict:
    from .bundle import load_bundle

    bundle = load_bundle(path)
    if replace:
        clear_owned()
    scene = bpy.context.scene
    root = bpy.data.collections.new(PREFIX)
    scene.collection.children.link(root)
    labels = bpy.data.collections.new(f"{PREFIX}_Labels")
    root.children.link(labels)

    manifest = bundle["manifest"]
    span = _span(bundle["geometry"]["xyz"])
    annotation_z = max(span * 0.004, 1e-4)
    text_size = max(span * 0.035, 0.15)

    image_obj = _image_surface(bundle, root)
    _marker_cloud(bundle, root, span)
    highlight = _highlight(bundle, root, span, annotation_z)
    _axes(manifest, root, labels, annotation_z, text_size)
    _grid(manifest, root, annotation_z * 0.5)
    _labels(bundle, labels, annotation_z, text_size)
    _ellipses(bundle, root, annotation_z)
    _banner(manifest, root, span, annotation_z, text_size)
    camera = _camera(span)
    root.objects.link(camera)
    if scene.camera is None or scene.camera.name in {"Camera"}:
        scene.camera = camera

    _store_text(f"{PREFIX}_manifest.json", json.dumps(manifest))
    _store_text(f"{PREFIX}_sources.json", json.dumps(bundle["sources"]))
    settings = scene.wcsscene
    settings.bundle_dir = str(bundle["root"])
    settings.manifest_path = str(bundle["manifest_path"])
    settings.content_id = str(manifest.get("content_id") or "")
    settings.mode = str(manifest.get("mode") or "")
    display = ((manifest.get("image") or {}).get("display") or {})
    settings.stretch = str(display.get("stretch") or "asinh")
    settings.colormap = str(display.get("colormap") or "gray")
    percentiles = display.get("percentiles") or [1.0, 99.0]
    settings.percentile_low = float(percentiles[0])
    settings.percentile_high = float(percentiles[1])
    settings.show_mask = bool(display.get("show_mask", True))
    highlight_id = manifest.get("highlight_source_id") or ""
    if not highlight_id and highlight is not None:
        highlight_id = highlight.get("source_id", "")
    settings.active_source_id = str(highlight_id or "")
    settings.status = "imported"
    settings.last_report = ""
    image_obj["annotation_z"] = 0.0
    return bundle


def _span(xyz) -> float:
    rows = xyz.as_tuples()
    if not rows:
        return 1.0
    xs = [row[0] for row in rows]
    ys = [row[1] for row in rows]
    return max(max(xs) - min(xs), max(ys) - min(ys), 1.0)


def _image_surface(bundle: dict, collection):
    geometry = bundle["geometry"]
    vertices = [tuple(row) for row in geometry["xyz"].as_tuples()]
    faces = [tuple(int(v) for v in row) for row in geometry["faces"].as_tuples()]
    uvs = geometry["uv"].as_tuples()
    mesh = bpy.data.meshes.new(f"{PREFIX}_ImageMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uvs[vertex]
    image = bpy.data.images.load(str(bundle["paths"]["display_png"]), check_existing=False)
    image.name = f"{PREFIX}_Display"
    try:
        image.colorspace_settings.name = "sRGB"
    except TypeError:
        pass
    material = image_material(image)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"{PREFIX}_Image", mesh)
    obj["wcsscene_role"] = "image"
    obj["wcsscene_note"] = "Sampled presentation surface. Not a distance map."
    collection.objects.link(obj)
    return obj


def _marker_cloud(bundle: dict, collection, span: float):
    placed = [row for row in bundle["sources"] if row.get("placed") and row.get("scene_xyz")]
    vertices = [tuple(row["scene_xyz"]) for row in placed]
    mesh = bpy.data.meshes.new(f"{PREFIX}_MarkerPointsMesh")
    mesh.from_pydata(vertices, [], [])
    mesh.update()
    if vertices:
        # Blender 4.5 string attributes are not stable beside other attributes.
        # The catalogue row is the stable point attribute; source ids live in sources.json.
        rows = mesh.attributes.new("catalog_row", "INT", "POINT")
        for index, source in enumerate(placed):
            rows.data[index].value = int(source["catalog_row"])
    obj = bpy.data.objects.new(f"{PREFIX}_Markers", mesh)
    obj["wcsscene_role"] = "markers"
    obj["wcsscene_count"] = len(vertices)
    radius = max(span * 0.012, 0.05)
    material = marker_material()
    mesh.materials.append(material)
    collection.objects.link(obj)
    group = _marker_nodes(radius)
    if group is not None:
        modifier = obj.modifiers.new(f"{PREFIX}_Instances", "NODES")
        modifier.node_group = group
    else:
        _marker_glyphs(vertices, radius, material, collection)
    return obj


def _marker_glyphs(vertices, radius: float, material, collection):
    """One combined mesh used only if geometry nodes cannot be built."""
    if not vertices:
        return None
    all_verts = []
    all_faces = []
    faces = _octa_faces()
    for origin in vertices:
        start = len(all_verts)
        for corner in _octahedron(radius):
            all_verts.append((origin[0] + corner[0], origin[1] + corner[1], origin[2] + corner[2]))
        all_faces.extend(tuple(start + index for index in face) for face in faces)
    mesh = bpy.data.meshes.new(f"{PREFIX}_MarkerGlyphMesh")
    mesh.from_pydata(all_verts, [], all_faces)
    mesh.update()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"{PREFIX}_MarkerGlyphs", mesh)
    obj["wcsscene_role"] = "markers"
    collection.objects.link(obj)
    return obj


def _marker_nodes(radius: float):
    try:
        group = bpy.data.node_groups.new(f"{PREFIX}_MarkerNodes", "GeometryNodeTree")
        group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        nodes = group.nodes
        links = group.links
        node_in = nodes.new("NodeGroupInput")
        node_out = nodes.new("NodeGroupOutput")
        points = nodes.new("GeometryNodeMeshToPoints")
        ico = nodes.new("GeometryNodeMeshIcoSphere")
        ico.inputs["Radius"].default_value = float(radius)
        ico.inputs["Subdivisions"].default_value = 1
        inst = nodes.new("GeometryNodeInstanceOnPoints")
        links.new(node_in.outputs[0], points.inputs["Mesh"])
        links.new(points.outputs["Points"], inst.inputs["Points"])
        links.new(ico.outputs["Mesh"], inst.inputs["Instance"])
        links.new(inst.outputs["Instances"], node_out.inputs[0])
        return group
    except Exception:
        return None


def _highlight(bundle: dict, collection, span: float, annotation_z: float):
    manifest = bundle["manifest"]
    wanted = manifest.get("highlight_source_id")
    chosen = None
    for source in bundle["sources"]:
        if source.get("source_id") == wanted and source.get("placed"):
            chosen = source
            break
    if chosen is None:
        chosen = next((row for row in bundle["sources"] if row.get("placed")), None)
    if chosen is None:
        return None
    radius = max(span * 0.02, 0.08)
    mesh = bpy.data.meshes.new(f"{PREFIX}_HighlightMesh")
    mesh.from_pydata(_octahedron(radius), [], _octa_faces())
    mesh.update()
    mesh.materials.append(highlight_material())
    obj = bpy.data.objects.new(f"{PREFIX}_Highlight", mesh)
    xyz = chosen["scene_xyz"]
    obj.location = (float(xyz[0]), float(xyz[1]), float(xyz[2]) + annotation_z)
    obj["annotation_z"] = annotation_z
    obj["wcsscene_role"] = "highlight"
    obj["distance_note"] = "Z offset is an annotation lift, not astronomical distance."
    _copy_source_props(obj, chosen)
    collection.objects.link(obj)
    return chosen


def _axes(manifest: dict, collection, labels, annotation_z: float, text_size: float):
    overlays = manifest.get("overlays") or {}
    axes = overlays.get("axes")
    if not axes:
        return
    east = axes["east"]
    north = axes["north"]
    east_pts = [_lift(east["p0"], annotation_z), _lift(east["p1"], annotation_z)]
    north_pts = [_lift(north["p0"], annotation_z), _lift(north["p1"], annotation_z)]
    east_mat = east_material()
    north_mat = north_material()
    _axis_object(f"{PREFIX}_East", east_pts, east_mat, collection, annotation_z)
    _axis_object(f"{PREFIX}_North", north_pts, north_mat, collection, annotation_z)
    _font(
        f"{PREFIX}_Label_E",
        str(east.get("label") or "E"),
        east_pts[1],
        labels,
        text_size,
        east_mat,
    )
    _font(
        f"{PREFIX}_Label_N",
        str(north.get("label") or "N"),
        north_pts[1],
        labels,
        text_size,
        north_mat,
    )


def _lift(point, annotation_z: float) -> tuple[float, float, float]:
    return (float(point[0]), float(point[1]), float(point[2]) + annotation_z)


def _axis_object(name: str, points, material, collection, annotation_z: float):
    length = math.dist(points[0], points[1])
    obj = _curve_object(name, [points], material, collection, "axes", max(length * 0.02, 0.04))
    obj["annotation_z"] = annotation_z
    return obj


def _grid(manifest: dict, collection, annotation_z: float):
    overlays = manifest.get("overlays") or {}
    lines = overlays.get("sky_grid") or []
    polylines = []
    for line in lines:
        points = line.get("xyz") or []
        if len(points) < 2:
            continue
        polylines.append([_lift(point, annotation_z) for point in points])
    bevel = 0.03
    if polylines:
        span = max(abs(point[0]) for line in polylines for point in line)
        bevel = max(span * 0.004, 0.02)
    obj = _curve_object(f"{PREFIX}_Grid", polylines, grid_material(), collection, "grid", bevel)
    obj["annotation_z"] = annotation_z


def _labels(bundle: dict, collection, annotation_z: float, text_size: float):
    placed = [row for row in bundle["sources"] if row.get("placed") and row.get("scene_xyz")]
    if len(placed) > _LABEL_LIMIT:
        placed = [
            row
            for row in placed
            if row.get("source_id") == (bundle["manifest"].get("highlight_source_id"))
        ]
    material = label_material()
    for source in placed:
        xyz = source["scene_xyz"]
        location = (float(xyz[0]), float(xyz[1]) + text_size * 0.8, float(xyz[2]) + annotation_z)
        obj = _font(
            f"{PREFIX}_Label_{_safe(source['source_id'])}",
            str(source["source_id"]),
            location,
            collection,
            text_size * 0.55,
            material,
        )
        obj["wcsscene_role"] = "label"
        obj["source_id"] = str(source["source_id"])


def _ellipses(bundle: dict, collection, annotation_z: float):
    loops = []
    for source in bundle["sources"]:
        uncertainty = source.get("uncertainty") or {}
        if source.get("uncertainty_status") != "PROPAGATED":
            continue
        if not source.get("scene_xyz"):
            continue
        major = float(uncertainty.get("semi_major_bu") or 0.0)
        minor = float(uncertainty.get("semi_minor_bu") or 0.0)
        if major <= 0.0 or minor <= 0.0:
            continue
        angle = float(uncertainty.get("position_angle_rad_from_east_toward_north") or 0.0)
        origin = source["scene_xyz"]
        ring = []
        for step in range(32):
            theta = 2.0 * math.pi * step / 32.0
            ex = major * math.cos(theta)
            ny = minor * math.sin(theta)
            rx = ex * math.cos(angle) - ny * math.sin(angle)
            ry = ex * math.sin(angle) + ny * math.cos(angle)
            ring.append(
                (
                    float(origin[0]) + rx,
                    float(origin[1]) + ry,
                    float(origin[2]) + annotation_z,
                )
            )
        loops.append(ring)
    if not loops:
        return
    vertices = []
    edges = []
    for ring in loops:
        start = len(vertices)
        vertices.extend(ring)
        for index in range(len(ring)):
            edges.append((start + index, start + (index + 1) % len(ring)))
    mesh = bpy.data.meshes.new(f"{PREFIX}_EllipseMesh")
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    mesh.materials.append(ellipse_material())
    obj = bpy.data.objects.new(f"{PREFIX}_Ellipses", mesh)
    obj["wcsscene_role"] = "ellipses"
    obj["annotation_z"] = annotation_z
    obj["distance_note"] = "Ellipse axes are scene-plane uncertainty, not distance."
    collection.objects.link(obj)


def _banner(manifest: dict, collection, span: float, annotation_z: float, text_size: float):
    banners = manifest.get("banners") or []
    if not banners:
        return
    rows = bundle_vertices_top(span)
    obj = _font(
        f"{PREFIX}_Banner",
        " | ".join(str(line) for line in banners),
        (-span * 0.45, rows, annotation_z),
        collection,
        text_size * 0.45,
        label_material(),
    )
    obj["wcsscene_role"] = "banner"


def bundle_vertices_top(span: float) -> float:
    return span * 0.55


def _camera(span: float):
    data = bpy.data.cameras.new(f"{PREFIX}_Camera")
    data.type = "ORTHO"
    data.ortho_scale = span * 1.35
    data.clip_start = 0.01
    data.clip_end = max(span * 10.0, 100.0)
    obj = bpy.data.objects.new(f"{PREFIX}_Camera", data)
    obj.location = (0.0, 0.0, max(span, 1.0))
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj["wcsscene_role"] = "camera"
    obj["view_note"] = "Looks toward -Z. Screen right is +X and screen up is +Y."
    return obj


def _curve_object(name: str, polylines, material, collection, role: str, bevel: float):
    curve = bpy.data.curves.new(name + "Curve", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = float(bevel)
    curve.bevel_resolution = 2
    if material is not None:
        curve.materials.append(material)
    for points in polylines:
        if len(points) < 2:
            continue
        spline = curve.splines.new("POLY")
        spline.points.add(len(points) - 1)
        for index, point in enumerate(points):
            spline.points[index].co = (float(point[0]), float(point[1]), float(point[2]), 1.0)
    obj = bpy.data.objects.new(name, curve)
    obj["wcsscene_role"] = role
    collection.objects.link(obj)
    return obj


def _font(name: str, body: str, location, collection, size: float, material):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = size
    if material.name not in curve.materials:
        curve.materials.append(material)
    obj = bpy.data.objects.new(name, curve)
    obj.location = location
    collection.objects.link(obj)
    return obj


def _store_text(name: str, body: str) -> None:
    text = bpy.data.texts.new(name)
    text.write(body)
    text["wcsscene_role"] = name


def _copy_source_props(obj, source: dict) -> None:
    sky = source.get("sky_input_deg") or source.get("sky_from_pixel_deg")
    pixel = source.get("pixel_xy_input")
    obj["source_id"] = str(source.get("source_id") or "")
    obj["catalog_row"] = int(source.get("catalog_row") or 0)
    obj["pixel_x"] = "" if not pixel else float(pixel[0])
    obj["pixel_y"] = "" if not pixel else float(pixel[1])
    obj["sky_lon_deg"] = "" if not sky else float(sky[0])
    obj["sky_lat_deg"] = "" if not sky else float(sky[1])
    obj["sky_used_for_placement"] = bool(source.get("sky_used_for_placement"))
    obj["snr"] = _num(source.get("snr"))
    obj["anomaly_score"] = _num(source.get("anomaly_score"))
    obj["anomaly_percentile"] = _num(source.get("anomaly_percentile"))
    obj["anomaly_note"] = "Within-image score, not a discovery significance."
    known = source.get("known")
    obj["known"] = "" if known is None else bool(known)
    obj["reference_id"] = str(source.get("reference_id") or "")
    obj["distance_status"] = str(source.get("distance_status") or "distance_unknown")
    obj["uncertainty_status"] = str(source.get("uncertainty_status") or "UNKNOWN")
    obj["placement_reason"] = str(source.get("placement_reason") or "")
    obj["authoritative"] = str(source.get("authoritative") or "")


def _num(value):
    if value is None:
        return ""
    return float(value)


def _safe(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text))
    return cleaned[:48] or "source"


def _octahedron(radius: float) -> list[tuple[float, float, float]]:
    r = float(radius)
    return [
        (r, 0.0, 0.0),
        (-r, 0.0, 0.0),
        (0.0, r, 0.0),
        (0.0, -r, 0.0),
        (0.0, 0.0, r),
        (0.0, 0.0, -r),
    ]


def _octa_faces():
    return [
        (4, 0, 2),
        (4, 2, 1),
        (4, 1, 3),
        (4, 3, 0),
        (5, 2, 0),
        (5, 1, 2),
        (5, 3, 1),
        (5, 0, 3),
    ]


def apply_visibility(settings) -> None:
    roles = {
        "image": settings.show_image,
        "markers": settings.show_markers,
        "highlight": settings.show_markers,
        "label": settings.show_labels,
        "banner": settings.show_warnings,
        "grid": settings.show_grid,
        "axes": settings.show_grid,
        "ellipses": settings.show_markers,
    }
    for obj in bpy.data.objects:
        if not obj.name.startswith(PREFIX):
            continue
        role = obj.get("wcsscene_role")
        if role == "camera":
            continue
        if role in {"label"} or obj.name.startswith(f"{PREFIX}_Label"):
            visible = settings.show_labels
        elif role == "banner":
            visible = settings.show_warnings
        elif role in roles:
            visible = roles[role]
        else:
            continue
        obj.hide_viewport = not visible
        obj.hide_render = not visible
        if role == "axes":
            obj.hide_viewport = not settings.show_grid
            obj.hide_render = not settings.show_grid


def validate_scene() -> dict:
    """Compare owned geometry with the bundle arrays. Returns a report dict."""
    from .bundle import load_bundle

    checks = []
    scene = bpy.context.scene
    settings = scene.wcsscene

    def add(code: str, ok: bool, message: str, severity: str = "error") -> None:
        checks.append(
            {
                "code": code,
                "ok": ok,
                "severity": "info" if ok else severity,
                "message": message,
            }
        )

    root = bpy.data.collections.get(PREFIX)
    add("MISSING_COLLECTION", root is not None, "WCSScene collection is present")
    manifest_path = settings.manifest_path
    if not manifest_path:
        add("MISSING_MANIFEST", False, "No bundle path is stored on the scene")
        return _finish(checks)
    try:
        bundle = load_bundle(manifest_path)
    except BundleError as exc:
        add(exc.code, False, str(exc))
        return _finish(checks)

    image = bpy.data.objects.get(f"{PREFIX}_Image")
    expected = bundle["geometry"]["xyz"].as_tuples()
    if image is None:
        add("MESH_MISMATCH", False, "WCSScene_Image is missing")
    else:
        got = [tuple(vertex.co) for vertex in image.data.vertices]
        add(
            "MESH_MISMATCH",
            _coords_close(got, expected, 1e-5),
            f"image mesh vertices {len(got)} vs bundle {len(expected)}",
        )
    markers = bpy.data.objects.get(f"{PREFIX}_Markers")
    expected_markers = bundle["geometry"]["marker_xyz"].as_tuples()
    if markers is None:
        add("MARKER_MISMATCH", False, "WCSScene_Markers is missing")
    else:
        got = [tuple(vertex.co) for vertex in markers.data.vertices]
        add(
            "MARKER_MISMATCH",
            _coords_close(got, expected_markers, 1e-5),
            f"marker vertices {len(got)} vs bundle {len(expected_markers)}",
        )
        add(
            "OBJECT_COUNT",
            True,
            f"markers are one object with {len(got)} points, not one object per source",
            "info",
        )
    highlight = bpy.data.objects.get(f"{PREFIX}_Highlight")
    wanted = bundle["manifest"].get("highlight_source_id")
    source = next((row for row in bundle["sources"] if row.get("source_id") == wanted), None)
    if source is None:
        source = next((row for row in bundle["sources"] if row.get("placed")), None)
    if source and source.get("scene_xyz"):
        if highlight is None:
            add("HIGHLIGHT_MISMATCH", False, "highlight object is missing")
        else:
            xyz = source["scene_xyz"]
            lift = float(highlight.get("annotation_z") or 0.0)
            dx = abs(highlight.location.x - float(xyz[0]))
            dy = abs(highlight.location.y - float(xyz[1]))
            dz = abs(highlight.location.z - float(xyz[2]) - lift)
            add(
                "HIGHLIGHT_MISMATCH",
                dx < 1e-5 and dy < 1e-5 and dz < 1e-5,
                f"highlight delta xy=({dx:.3g},{dy:.3g}) z={dz:.3g}",
            )
    mode = bundle["manifest"].get("mode")
    if mode == "pixel_preview":
        accuracy = bundle["manifest"].get("celestial_accuracy")
        add(
            "PIXEL_PREVIEW_CLAIM",
            accuracy == "none",
            "pixel preview carries no celestial accuracy claim",
        )
    user_kept = bpy.data.objects.get("KeepMe")
    if user_kept is not None:
        add("USER_OBJECT", True, "KeepMe is still in the file", "info")
    return _finish(checks)


def _coords_close(got, expected, tol: float) -> bool:
    if len(got) != len(expected):
        return False
    for left, right in zip(got, expected, strict=True):
        if len(left) != len(right):
            return False
        for a, b in zip(left, right, strict=True):
            if abs(float(a) - float(b)) > tol:
                return False
    return True


def _finish(checks: list[dict]) -> dict:
    errors = [row for row in checks if not row["ok"] and row["severity"] == "error"]
    report = {
        "status": "fail" if errors else "pass",
        "error_count": len(errors),
        "checks": checks,
    }
    body = json.dumps(report, indent=2)
    existing = bpy.data.texts.get(f"{PREFIX}_validation.json")
    if existing is not None:
        bpy.data.texts.remove(existing)
    text = bpy.data.texts.new(f"{PREFIX}_validation.json")
    text.write(body)
    bpy.context.scene.wcsscene.last_report = report["status"]
    bpy.context.scene.wcsscene.status = report["status"]
    return report
