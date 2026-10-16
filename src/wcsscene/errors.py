"""Stable error codes and process exit statuses."""


class WCSSceneError(Exception):
    """Base class for errors the CLI maps to a documented exit status."""

    code = "ERROR"
    exit_code = 1


class InvalidInput(WCSSceneError):
    """Missing files, unknown HDUs, or malformed arguments."""

    code = "INVALID_INPUT"
    exit_code = 2


class InconsistentWCS(WCSSceneError):
    """The WCS is missing, non-celestial, or not internally consistent."""

    code = "INCONSISTENT_WCS"
    exit_code = 3


class UnsupportedWCS(InconsistentWCS):
    """Dimensionality or frame the high-level WCS path will not silently reduce."""

    code = "UNSUPPORTED_WCS"


class TangentAtPole(InconsistentWCS):
    """The requested tangent point is at a celestial pole, so east/north is undefined."""

    code = "TANGENT_POINT_AT_POLE"


class InconsistentCoordinates(WCSSceneError):
    """Pixel and sky catalogue columns disagree beyond the configured tolerance."""

    code = "INCONSISTENT_COORDINATES"
    exit_code = 3


class ValidationFailed(WCSSceneError):
    """A written bundle failed a coordinate or residual check."""

    code = "VALIDATION_FAILED"
    exit_code = 4


class MissingOptionalDependency(WCSSceneError):
    """An optional extra (Roman datamodels, or Blender) is not installed."""

    code = "MISSING_OPTIONAL_DEPENDENCY"
    exit_code = 5


class UnsupportedDataModel(WCSSceneError):
    """The file opened, but it is not a supported 2D imaging product."""

    code = "UNSUPPORTED_DATA_MODEL"
    exit_code = 6
