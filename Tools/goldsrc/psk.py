"""Минимальный читатель Unreal-мешей .psk (ActorX). Только stdlib.

Заголовок файла — последовательность чанков:
    name[20], type int32, datasize int32, count int32, затем count записей.

Читаются чанки:
    PNTS0000    точки       (x, y, z)                 float32
    VTXW0000    веджи       (point, u, v, material)   см. _parse_wedges
    FACE0000    треугольники (w0, w1, mat, aux, w2, aux)
    MATT0000    материалы   (name[64], texture[24])
    VTXNORMS    нормали     (x, y, z)                 float32
    RAWWEIGHTS  веса        (weight, point, bone)
    REFSKELT    кости       (name[64], flags, numchildren, parent,
                             quat xyzw, pos xyz, length, size)
"""

from __future__ import annotations

import struct

CHUNK_HEADER = 32


class Bone:
    __slots__ = ("index", "name", "parent", "quat", "pos")

    def __init__(self, index, name, parent, quat, pos):
        self.index = index
        self.name = name
        self.parent = parent
        self.quat = quat
        self.pos = pos

    def __repr__(self):
        return f"Bone({self.index}, {self.name!r}, parent={self.parent})"


class PskMesh:
    def __init__(self):
        self.points = []        # [(x, y, z)]
        self.normals = []       # [(x, y, z)]
        self.wedge_point = []   # индекс точки
        self.wedge_uv = []      # [(u, v)], v отсчитывается сверху
        self.wedge_material = []
        self.faces = []         # [(w0, w1, w2)], индексы веджей
        self.materials = []     # имена материалов
        self.bones = []         # [Bone]
        self.weights = []       # [(w, point, bone)]

    def __repr__(self):
        return (f"PskMesh(points={len(self.points)}, faces={len(self.faces)}, "
                f"materials={self.materials}, bones={len(self.bones)})")


def _read_chunks(data: bytes) -> dict:
    chunks = {}
    off = 0
    while off + CHUNK_HEADER <= len(data):
        name = data[off:off + 20].split(b"\x00")[0].decode("latin1")
        typ, size, count = struct.unpack_from("<iii", data, off + 20)
        start = off + CHUNK_HEADER
        end = start + size * count
        if size < 0 or count < 0 or end > len(data):
            raise ValueError(f"битый чанк {name!r} по смещению {off}")
        chunks[name] = (start, size, count)
        off = end
    return chunks


def _parse_wedges(start: int, count: int, data: bytes):
    """Декодирует 16-байтные веджи.

    Раскладка полей в этом файле (отличается от публичной документации ActorX,
    где сначала идут u/v):

        +0   int32   индекс точки
        +4   float32 u
        +8   float32 v
        +12  int32   индекс материала
    """
    points, uvs, mats = [], [], []
    unpack = struct.unpack_from
    for i in range(count):
        off = start + i * 16
        p = unpack("<i", data, off)[0]
        u, v = unpack("<2f", data, off + 4)
        m = unpack("<i", data, off + 12)[0]
        points.append(p)
        uvs.append((u, v))
        mats.append(m)
    return points, uvs, mats


def load_psk(path: str) -> PskMesh:
    with open(path, "rb") as fh:
        data = fh.read()
    ch = _read_chunks(data)
    mesh = PskMesh()

    if "PNTS0000" in ch:
        start, size, count = ch["PNTS0000"]
        flat = struct.unpack_from(f"<{count * 3}f", data, start)
        mesh.points = [tuple(flat[i * 3:i * 3 + 3]) for i in range(count)]

    if "VTXNORMS" in ch:
        start, size, count = ch["VTXNORMS"]
        flat = struct.unpack_from(f"<{count * 3}f", data, start)
        mesh.normals = [tuple(flat[i * 3:i * 3 + 3]) for i in range(count)]

    if "VTXW0000" in ch:
        start, size, count = ch["VTXW0000"]
        mesh.wedge_point, mesh.wedge_uv, mesh.wedge_material = _parse_wedges(start, count, data)

    if "FACE0000" in ch:
        start, size, count = ch["FACE0000"]
        flat = struct.unpack_from(f"<{count * 6}H", data, start)
        # Поля записи FACE0000: (w0, w1, w2, material, aux, aux).
        # Индексы веджей лежат подряд — 0, 1, 2. Раньше здесь читались
        # смещения 0, 2, 4 (это схема другой версии формата), из-за чего
        # каждый треугольник склеивался из вершин разных частей тела:
        # медиана ребра выходила 47 юнитов вместо 2.
        mesh.faces = [(flat[i * 6], flat[i * 6 + 1], flat[i * 6 + 2]) for i in range(count)]

    if "MATT0000" in ch:
        start, size, count = ch["MATT0000"]
        mesh.materials = [
            data[start + i * size:start + i * size + 64].split(b"\x00")[0].decode("latin1")
            for i in range(count)
        ]

    if "RAWWEIGHTS" in ch:
        start, size, count = ch["RAWWEIGHTS"]
        mesh.weights = []
        unpack = struct.unpack_from
        for i in range(count):
            off = start + i * 12
            w = unpack("<f", data, off)[0]
            pt, bone = unpack("<2i", data, off + 4)
            mesh.weights.append((w, pt, bone))

    if "REFSKELT" in ch:
        start, size, count = ch["REFSKELT"]
        for i in range(count):
            off = start + i * size
            name = data[off:off + 64].split(b"\x00")[0].decode("utf-8", "replace")
            _flags, _numchildren, parent = struct.unpack_from("<3i", data, off + 64)
            quat = struct.unpack_from("<4f", data, off + 76)
            pos = struct.unpack_from("<3f", data, off + 92)
            mesh.bones.append(Bone(i, name, parent, quat, pos))

    return mesh
