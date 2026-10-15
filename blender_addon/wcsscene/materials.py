"""Emission materials. Display colour is visual-only and double-sided."""

from __future__ import annotations

import bpy

PREFIX = "WCSScene"


def _emission(name: str, color: tuple[float, float, float, float], strength: float = 1.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.use_backface_culling = False
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = strength
    emission.location = (-200, 0)
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def image_material(image: bpy.types.Image):
    material = _emission(f"{PREFIX}_Image", (1, 1, 1, 1), 1.0)
    tree = material.node_tree
    emission = next(node for node in tree.nodes if node.type == "EMISSION")
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    texture.location = (-480, 0)
    tree.links.new(texture.outputs["Color"], emission.inputs["Color"])
    material["wcsscene_role"] = "image"
    return material


def marker_material():
    return _emission(f"{PREFIX}_Marker", (0.95, 0.82, 0.45, 1.0), 2.0)


def highlight_material():
    return _emission(f"{PREFIX}_Highlight", (1.0, 0.35, 0.12, 1.0), 3.0)


def east_material():
    return _emission(f"{PREFIX}_East", (0.85, 0.25, 0.22, 1.0), 2.0)


def north_material():
    return _emission(f"{PREFIX}_North", (0.25, 0.45, 0.95, 1.0), 2.0)


def grid_material():
    return _emission(f"{PREFIX}_Grid", (0.55, 0.62, 0.58, 1.0), 1.2)


def label_material():
    return _emission(f"{PREFIX}_Label", (0.93, 0.93, 0.9, 1.0), 1.5)


def ellipse_material():
    return _emission(f"{PREFIX}_Ellipse", (0.95, 0.75, 0.3, 1.0), 1.5)


def replace_image(material: bpy.types.Material, image: bpy.types.Image) -> None:
    if material is None or material.node_tree is None:
        return
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            node.image = image
