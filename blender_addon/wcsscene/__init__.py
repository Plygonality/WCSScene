"""WCSScene Blender extension.

The scientific package is not imported here. This add-on reads the exchange
bundle only.
"""

from __future__ import annotations

import bpy

from .operators import CLASSES as OPERATOR_CLASSES
from .properties import WCSSceneSettings
from .ui import CLASSES as UI_CLASSES

bl_info = {
    "name": "WCSScene",
    "author": "Plygonality",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > WCSScene",
    "description": "Import a WCS-traced astronomical image plane",
    "category": "Import-Export",
}

CLASSES = (WCSSceneSettings, *OPERATOR_CLASSES, *UI_CLASSES)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.wcsscene = bpy.props.PointerProperty(type=WCSSceneSettings)


def unregister() -> None:
    del bpy.types.Scene.wcsscene
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


def import_bundle(path: str) -> dict:
    """Headless entry point used by scripts/import_bundle.py."""
    from .geometry import import_bundle as _import

    register_if_needed()
    return _import(path, replace=True)


def register_if_needed() -> None:
    if not hasattr(bpy.types.Scene, "wcsscene"):
        register()
