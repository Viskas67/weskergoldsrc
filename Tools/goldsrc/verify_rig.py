#!/usr/bin/env python3
"""Сквозная проверка рига без движка.

Повторяет ровно то, что делает studiomdl: из nodes/skeleton reference-SMD
строит мировые матрицы костей (AngleMatrix + конкатенация), переводит вершины
в «объектное» пространство кости и проверяет, что после обратного преобразования
в мир получается исходный меш.

Печатает максимальное и среднее отклонение. Если < 0.01 юнита — привязка верна
и модель не развалится в игре.

Запуск: python3 Tools/goldsrc/verify_rig.py
"""

from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

from goldsrc_math import angle_matrix, to_gold               # noqa: E402
from meshbuild import Skeleton, dominant_bone_map           # noqa: E402
from psk import load_psk                                    # noqa: E402
import rig                                                  # noqa: E402

PSK = os.path.join(ROOT, "Models", "Bodies", "SKM_K29_Body01.psk")


def smd_world(bones, pos_local, rot_local):
    """Мировые матрицы костей так, как их строит Build_Reference()."""
    world = {}
    order = []

    def visit(i):
        if i in world:
            return
        if bones[i].parent >= 0:
            visit(bones[i].parent)
        m = angle_matrix(*rot_local[i])
        if bones[i].parent < 0:
            world[i] = (m, list(pos_local[i]))
        else:
            pm, pp = world[bones[i].parent]
            off = [sum(pm[r][k] * pos_local[i][k] for k in range(3)) for r in range(3)]
            world[i] = ([[sum(pm[r][k] * m[k][c] for k in range(3)) for c in range(3)] for r in range(3)],
                        [pp[k] + off[k] for k in range(3)])
        order.append(i)

    for i in range(len(bones)):
        visit(i)
    return world


def main():
    mesh = load_psk(PSK)
    sk = Skeleton(mesh.bones)
    dom = dominant_bone_map(mesh, sk)
    needed = set(infs[0][0] for infs in dom.values())
    for b in list(needed):                      # предки всех используемых костей
        cur = mesh.bones[b].parent
        while cur >= 0:
            needed.add(cur)
            cur = mesh.bones[cur].parent
    needed = sorted(needed)
    bone_map = {b: i for i, b in enumerate(needed)}
    bones = [mesh.bones[b] for b in needed]

    pos_gold, rot_local_abs, rot_world, pw = rig.solve_skeleton(mesh, needed)
    pos_local = {}
    for i, b in enumerate(needed):
        if mesh.bones[b].parent < 0:
            pos_local[i] = pos_gold[b]
        else:
            p = mesh.bones[b].parent
            d = [pos_gold[b][k] - pos_gold[p][k] for k in range(3)]
            pm = rot_world[p]
            pos_local[i] = tuple(sum(pm[k][c] * d[k] for k in range(3)) for c in range(3))
    rot_local = [rot_local_abs[b] for b in needed]

    world = smd_world(bones, pos_local, rot_local)
    print("проверка мировых позиций суставов:")
    worst = 0.0
    for i, b in enumerate(needed):
        if mesh.bones[b].index not in pos_gold:
            continue
        got = world[i][1]
        want = pos_gold[mesh.bones[b].index]
        d = math.dist(got, want)
        worst = max(worst, d)
    print(f"  макс. отклонение сустава: {worst:.4f} юнита")

    # вершины: мир -> кость -> мир
    dom_of = {p: infs[0][0] for p, infs in dom.items()}
    errors = []
    for p in range(0, len(mesh.points), 53):
        bone = dom_of[p]
        i = bone_map[bone]
        m, off = world[i]
        x, y, z = mesh.points[p]
        world_pos = to_gold((x, y, z))  # координаты SMD (см. goldsrc_math)
        local = [sum(m[r][k] * (world_pos[k] - off[k]) for k in range(3)) for r in range(3)]
        back = [sum(m[k][r] * local[k] for k in range(3)) + off[r] for r in range(3)]
        errors.append(math.dist(back, world_pos))
    errors.sort()
    print(f"вершины (n={len(errors)}): медиана {errors[len(errors)//2]:.6f}, "
          f"максимум {errors[-1]:.6f}")

    # модель в bind-позе должна стоять вертикально
    zs = [(mesh.points[p][2]) for p in range(len(mesh.points))]
    print(f"рост: {max(zs) - min(zs):.1f} юнитов, низ на Z={min(zs):.2f}")
    print("углы первой кости (рад):", tuple(round(a, 2) for a in rot_local[0]))
    return 0 if max(errors) < 0.01 and worst < 0.01 else 1


if __name__ == "__main__":
    raise SystemExit(main())
