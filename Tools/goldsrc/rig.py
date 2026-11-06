"""Сборка рига GoldSrc из меша+весов: позиции суставов и ориентации костей.

Почему не берём transform'ы из .psk напрямую: в этом файле иерархия REFSKELT
описывает позу, не совпадающую с позой меша (руки/ноги уезжают на 100+ юнитов,
порядок кватернионов/осей не соответствует ни одному публичному варианту
ActorX). Поэтому поза восстанавливается по мешу: центр сустава = центр
вершин, которые на него нагружены, с уточнением по «шву» с родительской
костью.  Это даёт корректную привязку (bind pose) в GoldSrc независимо от
того, что записано в .psk.
"""

from __future__ import annotations

import math

from goldsrc_math import to_gold, matrix_to_angles, normalize

MAX_BONES = 128


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(a):
    return math.sqrt(_dot(a, a))


def point_weights(mesh):
    """point -> {bone: weight}"""
    acc = {}
    for w, point, bone in mesh.weights:
        if w <= 0.0:
            continue
        acc.setdefault(point, {})
        acc[point][bone] = acc[point].get(bone, 0.0) + w
    return acc


def joint_positions(mesh, pw, bones):
    """Центр каждой кости в пространстве меша (до перевода в GoldSrc)."""
    # средневзвешенный центр по всем вершинам группы
    acc = {}
    for point, infs in pw.items():
        pt = mesh.points[point]
        for bone, w in infs.items():
            s = acc.setdefault(bone, [0.0, 0.0, 0.0, 0.0])
            s[0] += pt[0] * w
            s[1] += pt[1] * w
            s[2] += pt[2] * w
            s[3] += w
    centroid = {b: (s[0] / s[3], s[1] / s[3], s[2] / s[3]) for b, s in acc.items()}

    # уточнение: сустав лежит на границе между костью и её родителем
    seam = {}
    for point, infs in pw.items():
        if len(infs) < 2:
            continue
        bs = sorted(infs, key=lambda b: -infs[b])
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                b1, b2 = bs[i], bs[j]
                if bones[b1].parent == b2:
                    key = b1
                elif bones[b2].parent == b1:
                    key = b2
                else:
                    continue
                w = min(infs[b1], infs[b2])
                s = seam.setdefault(key, [0.0, 0.0, 0.0, 0.0])
                pt = mesh.points[point]
                s[0] += pt[0] * w
                s[1] += pt[1] * w
                s[2] += pt[2] * w
                s[3] += w

    positions = {}
    for bone, c in centroid.items():
        s = seam.get(bone)
        if s and s[3] > 1e-6:
            positions[bone] = (s[0] / s[3], s[1] / s[3], s[2] / s[3])
        else:
            positions[bone] = c
    return positions, centroid


def build_orientations(bones, positions, children):
    """Ориентация кости: ось X смотрит в сторону дочерних суставов.

    Так устроены стандартные GoldSrc-скелеты (Bip01): X — вдоль кости.
    Возвращает {bone: R (3x3, столбцы — оси X, Y, Z)}.
    """
    order = _topological(bones)
    rot = {}
    for bone in order:
        if bone not in positions:
            continue
        parent = bones[bone].parent
        pos = positions[bone]
        kids = [c for c in children.get(bone, []) if c in positions]
        if kids:
            direction = [0.0, 0.0, 0.0]
            for c in kids:
                d = normalize(_sub(positions[c], pos))
                direction = _add(direction, d)
            if _length(direction) < 1e-6:     # дети в той же точке — пропускаем
                direction = None
            else:
                direction = normalize(direction)
                if _length(direction) < 0.5:  # дочерние в разные стороны
                    direction = normalize(_sub(positions[kids[0]], pos))
        else:
            direction = None

        up_ref = (0.0, 0.0, 1.0) if parent is None or parent not in rot else (rot[parent][0][2],
                                                                             rot[parent][1][2],
                                                                             rot[parent][2][2])
        if direction is None:
            if parent is not None and parent in rot:
                rot[bone] = rot[parent]
                continue
            direction = up_ref

        x = normalize(direction)
        z = _sub(up_ref, _mul(x, _dot(up_ref, x)))
        if _length(z) < 1e-4:
            alt = (1.0, 0.0, 0.0) if abs(x[0]) < 0.9 else (0.0, 1.0, 0.0)
            z = _sub(alt, _mul(x, _dot(alt, x)))
        z = normalize(z)
        # правая тройка: Y = Z x X, чтобы матрица была собственным поворотом
        # (иначе определитель = -1 и matrix_to_angles() выдаёт мусор)
        y = normalize(_cross(z, x))
        # столбцы: X, Y, Z
        rot[bone] = [[x[0], y[0], z[0]],
                     [x[1], y[1], z[1]],
                     [x[2], y[2], z[2]]]
    return rot


def _topological(bones):
    order, seen = [], set()

    def visit(i):
        if i in seen:
            return
        p = bones[i].parent
        if p >= 0:
            visit(p)
        seen.add(i)
        order.append(i)

    for i in range(len(bones)):
        visit(i)
    return order


def build_children(bones):
    children = {}
    for b in bones:
        if b.parent >= 0:
            children.setdefault(b.parent, []).append(b.index)
    return children


def solve_skeleton(mesh, needed, scale=1.0, z_shift=0.0):
    """Возвращает (bones, pos_gold, rot_local, rot_world) для нужных костей.

    * ``pos_gold`` — абсолютные позиции суставов в системе GoldSrc
      (X вперёд, Y влево, Z вверх), уже с масштабом и сдвигом по Z;
    * ``rot_local`` — локальные углы SMD (pitch, yaw, roll) в РАДИАНАХ,
      как их и ждёт SMD/studiomdl;
    * ``rot_world`` — абсолютные матрицы ориентации (для отладочных картинок).
    """
    bones = mesh.bones
    children = build_children(bones)
    pw = point_weights(mesh)
    positions_ue, _ = joint_positions(mesh, pw, bones)

    # переводим в GoldSrc, масштабируем и ставим ступни на Z=0
    pos_gold = {}
    for bone, p in positions_ue.items():
        g = to_gold(p)
        pos_gold[bone] = (g[0] * scale, g[1] * scale, (g[2] + z_shift) * scale)

    # Кости без весов (корень joint_Char, промежуточные) — ставим в среднее
    # положение их детей: иначе они слипаются с родителем, длина «кости» = 0
    # и ориентация вырождается.
    pending = [b for b in needed if b not in pos_gold]
    for _ in range(len(pending) + 1):
        still = []
        for bone in pending:
            kids = [c for c in children.get(bone, []) if c in pos_gold]
            if kids:
                pos_gold[bone] = tuple(sum(pos_gold[c][k] for c in kids) / len(kids)
                                       for k in range(3))
            else:
                still.append(bone)
        pending = still
        if not pending:
            break
    for bone in pending:                       # совсем без потомков — к родителю
        parent = bones[bone].parent
        pos_gold[bone] = pos_gold.get(parent, (0.0, 0.0, 0.0))

    # ориентации считаем в GoldSrc-пространстве
    rot_world = build_orientations(bones, pos_gold, children)

    # Кость, у которой нет весов, но есть дети, в build_orientations()
    # пропускается (её нет в positions) — тогда её локальный поворот берём
    # нулевым: мировая ориентация унаследуется от родителя.
    for bone in needed:
        if bone not in rot_world:
            parent = bones[bone].parent
            rot_world[bone] = rot_world.get(parent, [[1.0, 0.0, 0.0],
                                                     [0.0, 1.0, 0.0],
                                                     [0.0, 0.0, 1.0]])

    rot_local = {}
    for bone in _topological(bones):
        if bone not in rot_world:
            continue
        parent = bones[bone].parent
        if parent is None or parent < 0 or parent not in rot_world:
            rl = rot_world[bone]
        else:
            pm = rot_world[parent]
            rm = rot_world[bone]
            # local = parent^T * world
            rl = [[sum(pm[k][i] * rm[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        rot_local[bone] = matrix_to_angles(rl)

    return pos_gold, rot_local, rot_world, pw


def local_translations(bones, pos_gold, rot_world):
    """Локальные смещения костей (SMD): parent^T * (pos - parent_pos)."""
    out = {}
    for b in bones:
        i = b.index
        p = b.parent
        if p < 0:
            out[i] = pos_gold[i]
            continue
        d = _sub(pos_gold[i], pos_gold[p])
        pm = rot_world[p]
        # parent^T * d
        out[i] = (sum(pm[k][0] * d[k] for k in range(3)),
                  sum(pm[k][1] * d[k] for k in range(3)),
                  sum(pm[k][2] * d[k] for k in range(3)))
    return out
