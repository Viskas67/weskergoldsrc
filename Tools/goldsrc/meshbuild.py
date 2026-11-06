"""Скелет, веса и нарезка меша под лимиты GoldSrc. Только stdlib."""

from __future__ import annotations

import math

from goldsrc_math import to_gold, quat_to_matrix_xyzw, matrix_to_angles
from psk import Bone

# GoldSrc: 2048 вершин/нормалей и 4080 треугольников на один SMD.
MAX_VERTS_PER_SMD = 2048
MAX_NORMS_PER_SMD = 2048
MAX_TRIS_PER_SMD = 4080
MAX_BONES = 128


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def mat_transpose(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


class Skeleton:
    """Плоская иерархия костей из .psk + мировые трансформации."""

    def __init__(self, bones):
        self.bones = list(bones)
        self.local_rot = [quat_to_matrix_xyzw(b.quat) for b in self.bones]
        self.index_of = {b.name: b.index for b in self.bones}
        self._world = {}
        self._world_rot = {}

    def world(self, i):
        if i in self._world:
            return self._world[i], self._world_rot[i]
        b = self.bones[i]
        r = self.local_rot[i]
        if b.parent < 0:
            pos = mat_vec(r, b.pos)
            rot = r
        else:
            ppos, prot = self.world(b.parent)
            pos = tuple(ppos[k] + mat_vec(prot, b.pos)[k] for k in range(3))
            rot = mat_mul(prot, r)
        self._world[i], self._world_rot[i] = pos, rot
        return pos, rot


def dominant_bone_map(mesh, skeleton):
    """point -> [(bone, weight)], отсортировано по убыванию веса."""
    acc = {}
    for w, point, bone in mesh.weights:
        if w <= 0.0:
            continue
        acc.setdefault(point, {})
        acc[point][bone] = acc[point].get(bone, 0.0) + w
    return {p: sorted(d.items(), key=lambda kv: -kv[1]) for p, d in acc.items()}


def _avatar_pos(skeleton, bone_map, point):
    """Позиция точки в позе привязки (T-поза / A-поза модели)."""
    return point


def blend_bone_position(skeleton, influences, point):
    """Позиция кости как взвешенный центр привязки — так делают риггеры.

    В этой модели трансформации REFSKELT описывают позу отличную от позы
    меша, поэтому «центр» кости считаем по вершинам, которые на неё нагружены.
    Функция оставлена для документирования: фактический центр считается
    в :func:`bone_centers`.
    """
    raise NotImplementedError


def bone_centers(mesh, skeleton, dominant):
    """Центр каждой кости = среднее координат нагруженных на неё точек."""
    acc = {}
    for point, infs in dominant.items():
        bone, weight = infs[0]
        s = acc.setdefault(bone, [0.0, 0.0, 0.0, 0.0])
        x, y, z = mesh.points[point]
        s[0] += x * weight
        s[1] += y * weight
        s[2] += z * weight
        s[3] += weight
    return {b: (s[0] / s[3], s[1] / s[3], s[2] / s[3]) for b, s in acc.items()}


def build_bone_tree(skeleton, dominant, root_name="joint_Char"):
    """Оставляет только кости, на которые есть веса, плюс их предков."""
    needed = set()
    for infs in dominant.values():
        needed.add(infs[0][0])
    for bone in list(needed):
        cur = bone
        while cur >= 0 and cur not in needed:
            needed.add(cur)
            cur = skeleton.bones[cur].parent
        cur = bone
        while cur >= 0:
            p = skeleton.bones[cur].parent
            if p < 0:
                break
            needed.add(p)
            cur = p
    return needed


def split_mesh(mesh, dominant, materials_filter=None):
    """Делит треугольники по материалам и нарезает на SMD-пачки.

    Возвращает список словарей:
        {"material": имя, "part": номер, "tris": [(w0, w1, w2)], "wedges": set}
    """
    by_mat = {}
    for tri in mesh.faces:
        mat = mesh.wedge_material[tri[0]]
        by_mat.setdefault(mat, []).append(tri)

    chunks = []
    for mat, tris in sorted(by_mat.items()):
        chunk, used, tri_count = [], set(), 0
        for tri in tris:
            new_wedges = [w for w in tri if w not in used]
            if (len(used) + len(new_wedges) > MAX_VERTS_PER_SMD
                    or tri_count + 1 > MAX_TRIS_PER_SMD):
                chunks.append({"material": mat, "tris": chunk, "wedges": set(used)})
                chunk, used, tri_count = [], set(), 0
                new_wedges = [w for w in tri if w not in used]
            chunk.append(tri)
            used.update(new_wedges)
            tri_count += 1
        if chunk:
            chunks.append({"material": mat, "tris": chunk, "wedges": set(used)})
    for i, c in enumerate(chunks):
        c["id"] = i
    return chunks
