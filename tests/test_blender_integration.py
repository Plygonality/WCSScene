"""Real Blender session. Skips with a written reason when the binary is absent."""

import shutil
import subprocess
from pathlib import Path

import pytest

from wcsscene.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _blender() -> Path | None:
    found = shutil.which("blender")
    if found:
        return Path(found)
    candidate = Path.home() / "blender" / "blender"
    if candidate.is_file():
        return candidate
    return None


@pytest.mark.blender
def test_blender_imports_bundle_and_keeps_user_objects(tmp_path):
    blender = _blender()
    if blender is None:
        pytest.skip(
            "Blender executable not found on PATH or at ~/blender/blender. "
            "The scientific tests do not substitute a fake bpy module."
        )
    out = tmp_path / "demo"
    assert main(["demo", "--out", str(out)]) == 0
    blend = tmp_path / "scene.blend"
    png = tmp_path / "scene.png"
    script = ROOT / "scripts" / "blender_smoke.py"
    proc = subprocess.run(
        [
            str(blender),
            "--background",
            "--python-exit-code",
            "7",
            "--python",
            str(script),
            "--",
            str(out),
            str(blend),
            str(png),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "BLENDER_SMOKE status=pass" in proc.stdout
    assert blend.is_file()
    assert png.is_file() and png.stat().st_size > 1000
