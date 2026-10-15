"""File hashes and library versions recorded in the exchange manifest."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import __version__


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def runtime_versions() -> dict[str, str | None]:
    import sys

    import astropy
    import numpy

    return {
        "python": sys.version.split()[0],
        "wcsscene": __version__,
        "numpy": numpy.__version__,
        "astropy": astropy.__version__,
        "scipy": package_version("scipy"),
        "asdf": package_version("asdf"),
        "gwcs": package_version("gwcs"),
        "roman_datamodels": package_version("roman-datamodels"),
    }


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
