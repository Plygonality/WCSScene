"""Read the NumPy NPY/NPZ files written into an exchange bundle.

The Blender add-on does not import a scientific stack. Only little-endian
numeric arrays in C order are accepted, which is what the exchange writer emits.
"""

from __future__ import annotations

import ast
import struct
import sys
import zipfile
from array import array
from pathlib import Path

_TYPECODES = {
    "|b1": "b",
    "|i1": "b",
    "|u1": "B",
    "<i2": "h",
    "<u2": "H",
    "<i4": "i",
    "<u4": "I",
    "<i8": "q",
    "<u8": "Q",
    "<f4": "f",
    "<f8": "d",
}
_ITEMSIZE = {
    "b": 1,
    "B": 1,
    "h": 2,
    "H": 2,
    "i": 4,
    "I": 4,
    "q": 8,
    "Q": 8,
    "f": 4,
    "d": 8,
}


class NpyError(ValueError):
    """The array file is not a supported numeric NPY payload."""


class NpyArray:
    """A C-order numeric array backed by ``array.array``."""

    def __init__(self, shape: tuple[int, ...], typecode: str, values: array) -> None:
        self.shape = tuple(int(v) for v in shape)
        self.typecode = typecode
        self.values = values

    def __len__(self) -> int:
        return 0 if not self.shape else int(self.shape[0])

    def row(self, index: int) -> tuple[float, ...]:
        if len(self.shape) != 2:
            raise NpyError(f"row() needs a 2D array, got shape {self.shape}")
        width = int(self.shape[1])
        start = index * width
        return tuple(self.values[start : start + width])

    def as_tuples(self) -> list[tuple[float, ...]]:
        if len(self.shape) == 1:
            return [(value,) for value in self.values]
        if len(self.shape) != 2:
            raise NpyError(f"unsupported rank {len(self.shape)}")
        width = int(self.shape[1])
        count = int(self.shape[0])
        values = self.values
        return [tuple(values[i * width : (i + 1) * width]) for i in range(count)]


def load_npy(path: str | Path) -> NpyArray:
    blob = Path(path).read_bytes()
    return _parse_npy(blob)


def load_npz(path: str | Path) -> dict[str, NpyArray]:
    archive = zipfile.ZipFile(path)
    found: dict[str, NpyArray] = {}
    for name in archive.namelist():
        if not name.endswith(".npy"):
            continue
        key = Path(name).name[:-4]
        found[key] = _parse_npy(archive.read(name))
    return found


def _parse_npy(blob: bytes) -> NpyArray:
    if blob[:6] != b"\x93NUMPY":
        raise NpyError("missing NPY magic")
    major = blob[6]
    if major == 1:
        header_len = struct.unpack("<H", blob[8:10])[0]
        header_start = 10
    elif major in {2, 3}:
        header_len = struct.unpack("<I", blob[8:12])[0]
        header_start = 12
    else:
        raise NpyError(f"unsupported NPY version {major}")
    header = blob[header_start : header_start + header_len].decode("latin1").strip()
    meta = ast.literal_eval(header)
    if meta.get("fortran_order"):
        raise NpyError("Fortran-order arrays are not accepted")
    descr = str(meta["descr"])
    if descr not in _TYPECODES:
        raise NpyError(f"unsupported dtype {descr}")
    typecode = _TYPECODES[descr]
    shape = tuple(int(v) for v in meta["shape"])
    count = 1
    for dim in shape:
        count *= dim
    data_start = header_start + header_len
    expected = count * _ITEMSIZE[typecode]
    payload = blob[data_start : data_start + expected]
    if len(payload) != expected:
        raise NpyError(f"NPY payload is {len(payload)} bytes, expected {expected}")
    if descr[0] == ">" or (descr[0] == "=" and sys.byteorder == "little"):
        raise NpyError("big-endian arrays are not accepted")
    values = array(typecode)
    values.frombytes(payload)
    return NpyArray(shape, typecode, values)
