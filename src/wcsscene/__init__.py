"""WCSScene scientific core.

This package converts a celestial image and its WCS into a versioned exchange
bundle. It does not import Blender. A 2D exposure is placed on a 2.5D
presentation layer; Blender units are a configured angular scale, not distance.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "1.0.0"

__all__ = ["SCHEMA_VERSION", "__version__"]
