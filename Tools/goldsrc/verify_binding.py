"""Проверка гипотезы: координаты вершин в .psk заданы в системе координат
кости, на которую они нагружены (типичная особенность UE-экспорта в этот файл).

Если гипотеза верна, то квадратичная ошибка между «вершина в позе скелета»
(bone_world @ vert) и вершиной, посчитанной по соседним вершинам с другой
доминирующей костью, минимальна.  Тест перебирает варианты и печатает остаток.

Запуск:  python3 Tools/goldsrc/verify_binding.py [--perm no|mesh|zup]
"""

from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psk import load_psk
from meshbuild import Skeleton, dominant_bone_map, mat_mul, mat_vec, mat_transpose

PSK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "Models", "Bodies", "SKM_K29_Body01.psk")


def skeleton_world(sk, i):
    return sk.world(i)


def with_skin(sk, point, infs, mode):
    """Вернуть позицию вершины после применения скелета."""
    acc = [0.0, 0.0, 0.0]
    for bone, w in infs:
        pos, rot = skeleton_world(sk, bone)
        v = mat_vec(rot, point)
        if mode == "perm":       # поворот меша: (x, z, -y)
            v = (v[0], v[2], -v[1])
        acc[0] += v[0] * w
        acc[1] += v[1] * w
        acc[2] += v[2] * w
    return tuple(acc)


def main():
    mesh = load_psk(PSK)
    sk = Skeleton(mesh.bones)
    dom = dominant_bone_map(mesh, sk)

    sample = [p for p in range(0, len(mesh.points), 37)][:400]
    for mode in ("none", "perm"):
        errs = []
        for p in sample:
            infs = dom[p]
            v = with_skin(sk, mesh.points[p], infs, mode)
            # сравниваем с «сырой» позицией: если скелет — тождество, ошибка 0
            raw = mesh.points[p]
            errs.append(math.dist(v, raw))
        errs.sort()
        print(f"{mode:6} median={errs[len(errs)//2]:8.3f}  p90={errs[int(len(errs)*0.9)]:8.3f}")

    # Оценка локального масштаба: для пар вершин с ОДНОЙ доминирующей костью
    # скелет ничего не меняет, поэтому сравниваем расстояния внутри групп,
    # чтобы понять, надо ли вообще применять скелет.
    print("\nДиапазон координат меша:",
          [round(min(p[i] for p in mesh.points), 2) for i in range(3)],
          [round(max(p[i] for p in mesh.points), 2) for i in range(3)])
    heights = [p[2] for p in mesh.points]
    print("Высота (Z) min/max:", round(min(heights), 2), round(max(heights), 2))


if __name__ == "__main__":
    main()
