#!/usr/bin/env python3
"""Проверка собранного .mdl теми же формулами, что использует движок GoldSrc.

Скрипт ничего не рендерит и не доверяет нашим же хелперам: он заново
реализует ``AngleMatrix``/``R_ConcatTransforms``/``VectorTransform`` из
``utils/common/mathlib.c`` (Valve SDK) и применяет их к ``mstudiobone_t.value``
и ``mstudiobone_t.vertindex``. Полученные мировые вершины сверяются с
мировыми вершинами reference-SMD — если расхождение < 0.05 юнита, модель
в игре встанет ровно так, как задумано.

Запуск::

    python3 Tools/goldsrc/verify_mdl.py Build/goldsrc/smd/wesker.mdl Build/goldsrc/smd
"""

from __future__ import annotations

import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import inspect_mdl as im  # noqa: E402


def angle_matrix(angles):
    """AngleMatrix из Valve SDK; углы в радианах (так их хранит .mdl)."""
    sy, cy = math.sin(angles[2]), math.cos(angles[2])
    sp, cp = math.sin(angles[1]), math.cos(angles[1])
    sr, cr = math.sin(angles[0]), math.cos(angles[0])
    return [
        [cp * cy, sr * sp * cy + cr * -sy, cr * sp * cy + -sr * -sy, 0.0],
        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy + -sr * cy, 0.0],
        [-sp, sr * cp, cr * cp, 0.0],
    ]


def concat(a, b):
    """R_ConcatTransforms."""
    out = [[0.0] * 4 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            out[r][c] = sum(a[r][k] * b[k][c] for k in range(3))
        out[r][3] = sum(a[r][k] * b[k][3] for k in range(3)) + a[r][3]
    return out


def bone_frames(mdl):
    """(матрица поворота, мировое начало) каждой кости, как в движке."""
    bones = mdl["bones"]
    mats, origin = {}, {}

    def build(i):
        if i in mats:
            return
        b = bones[i]
        local = angle_matrix(b["value"][3:])
        if b["parent"] < 0:
            mats[i] = local
            origin[i] = list(b["value"][:3])
            return
        build(b["parent"])
        parent = mats[b["parent"]]
        mats[i] = concat(parent, local)
        move = [sum(b["value"][k] * parent[r][k] for k in range(3)) + parent[r][3]
                for r in range(3)]
        origin[i] = [move[k] + origin[b["parent"]][k] for k in range(3)]

    for i in range(len(bones)):
        build(i)
    return mats, origin


def world_vertex(v, i, mats, origin):
    m = mats[i]
    o = origin[i]
    return [sum(v[k] * m[r][k] for k in range(3)) + o[r] for r in range(3)]


def smd_points(path):
    """Мировые вершины одного reference-SMD, сгруппированные по имени кости."""
    section = None
    nodes = {}
    per_bone = collections.defaultdict(set)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s in ("nodes", "skeleton", "triangles"):
                section = s
                continue
            if s == "end":
                section = None
                continue
            if section == "nodes":
                parts = s.split('"')
                nodes[int(parts[0])] = parts[1]
            elif section == "triangles":
                parts = s.split()
                if len(parts) == 9:
                    per_bone[nodes[int(parts[0])]].add(
                        tuple(round(float(x), 2) for x in parts[1:4]))
    return per_bone


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mdl_path, smd_dir = sys.argv[1], sys.argv[2]
    mdl = im.read_mdl(mdl_path)
    mats, origin = bone_frames(mdl)
    names = [b["name"] for b in mdl["bones"]]

    total = worst = bad = 0
    print("сверка .mdl (формулы движка) с reference-SMD:")
    for bp in mdl["bodyparts"]:
        path = os.path.join(smd_dir, "wesker_%s.smd" % bp["name"])
        if not os.path.exists(path):
            continue
        ref = smd_points(path)
        for model in bp["models"]:
            by_bone = collections.defaultdict(list)
            for vi, v in enumerate(model["verts"]):
                bi = model["vertbone"][vi]
                by_bone[bi].append(world_vertex(v, bi, mats, origin))
            local_worst = 0.0
            for bi, pts in by_bone.items():
                ref_pts = ref.get(names[bi])
                if not ref_pts:
                    continue
                for p in pts:
                    d = min(math.dist(p, r) for r in ref_pts)
                    local_worst = max(local_worst, d)
                    total += 1
                    if d > 0.05:
                        bad += 1
            worst = max(worst, local_worst)
            print("  %-18s вершин %5d  maxΔ=%.3f"
                  % (bp["name"], len(model["verts"]), local_worst))

    lo = [9e9] * 3
    hi = [-9e9] * 3
    for bp in mdl["bodyparts"]:
        for model in bp["models"]:
            for vi, v in enumerate(model["verts"]):
                w = world_vertex(v, model["vertbone"][vi], mats, origin)
                for k in range(3):
                    lo[k] = min(lo[k], w[k])
                    hi[k] = max(hi[k], w[k])
    print("вершин сверено: %d, макс. отклонение: %.3f, плохих (>0.05): %d"
          % (total, worst, bad))
    print("габариты в системе движка: [%.1f %.1f %.1f] … [%.1f %.1f %.1f]"
          % (*lo, *hi))
    print("габариты из заголовка .mdl: [%.1f %.1f %.1f] … [%.1f %.1f %.1f]"
          % (*mdl["bbox"][0], *mdl["bbox"][1]))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
