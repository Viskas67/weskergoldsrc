"""Генерация SMD и QC для GoldSrc. Только stdlib."""

from __future__ import annotations

import math
import os

from goldsrc_math import angle_matrix, matrix_to_angles


def _fmt(v):
    return f"{v:.6f}"


# В форке studiomdl (fnky/studiomdl) Grab_Nodes() возвращает индекс последней
# кости вместо их количества, из-за чего у последней кости остаётся мусорный
# parent и компилятор падает в segfault. В эталонных моделях Valve последняя
# кость всегда пустая (см. modelsrc/models/player/*.smd) — повторяем приём:
# добавляем в конец узлов неиспользуемую кость-заглушку.
def dummy_node(count):
    """Строка-заглушка: индекс = count (сразу за последней реальной костью).

    Трансформацию для неё писать нельзя — Grab_Skeleton() читает строки подряд
    и пишет по индексу, поэтому лишняя строка уехала бы в чужой слот.
    """
    return f'  {count} "__unused" 0'


# ------------------------------------------------------------------ SMD


def write_reference_smd(path, bones, pos_local, rot_local, chunks, mesh, bone_map,
                       weights=None, scale=1.0, origin=(0.0, 0.0, 0.0),
                       bone_pose=None):
    """Пишет reference SMD: меш + скелет в позе привязки.

    * ``bones``     — список ``Bone`` в порядке SMD;
    * ``pos_local`` — {индекс SMD: (x, y, z)} локальные смещения костей;
    * ``rot_local`` — {индекс SMD: (pitch, yaw, roll)} в радианах;
    * ``chunks``    — пачки треугольников из :func:`meshbuild.split_mesh`;
    * ``bone_map``  — индекс PSK -> индекс SMD;
    * ``weights``   — {(точка, кость_psk): вес} — для сварки вершин по весам;
    * ``scale``     — общий масштаб (рост модели приводят к 72 юнитам);
    * ``origin``    — сдвиг в координатах GoldSrc (центр по вертикали);
    * ``bone_pose`` — (rot_local, pos_local) из :meth:`anim.Rig.solve` для позы
      привязки: если задано, скелет пишется как есть, без scale/origin.
    """
    lines = ["version 1", "nodes"]
    for smd_index, bone in enumerate(bones):
        parent = bone_map.get(bone.parent, -1)
        lines.append(f'{smd_index:3d} "{bone.name}" {parent}')
    lines.append(dummy_node(len(bones)))
    lines.append("end")
    lines.append("skeleton")
    lines.append("time 0")
    # Позу привязки лучше брать из того же Rig, что и анимации (build.py
    # передаёт её в bone_pose) — тогда reference и кадры гарантированно в
    # одной системе координат. Иначе масштаб/origin легко применить дважды
    # или не применить вовсе, и скелет «складывается» при проигрывании.
    if bone_pose is not None:
        for smd_index in range(len(bones)):
            pose_local_rot, pose_local_pos = bone_pose
            p = pose_local_pos[smd_index]
            r = pose_local_rot[smd_index]
            lines.append(f"{smd_index:3d} " + " ".join(_fmt(v) for v in (*p, *r)))
    else:
        for smd_index in range(len(bones)):
            p = pos_local[smd_index]
            r = rot_local[smd_index]
            shift = origin if bone_map.get(bones[smd_index].parent, -1) < 0 else (0.0, 0.0, 0.0)
            lines.append(f"{smd_index:3d} " + " ".join(
                _fmt(v) for v in (*_shift(_scale3(p, scale), shift), *r)))
    lines.append("end")
    lines.append("triangles")

    key_of = {}
    if weights:
        for (point, bone), w in weights.items():
            key_of.setdefault(point, {})[bone] = w
    for chunk in chunks:
        # имя материала в SMD = имя BMP-файла (studiomdl ищет текстуру по нему)
        mat_name = mesh.materials[chunk["material"]] + ".bmp"
        for tri in chunk["tris"]:
            lines.append(mat_name)
            for w in tri:
                point = mesh.wedge_point[w]
                pt = mesh.points[point]
                nx, ny, nz = (0.0, 0.0, 0.0)
                if mesh.normals and point < len(mesh.normals):
                    nx, ny, nz = mesh.normals[point]
                u, v = mesh.wedge_uv[w]
                gx, gy, gz = (pt[0] * scale + origin[0], pt[1] * scale + origin[1],
                              pt[2] * scale + origin[2])
                # SMD описывает одну вершину одной строкой: кость + 8 чисел.
                # Мультивес («вес остатка» в 9-м поле) этот форк studiomdl не
                # читает, поэтому берём доминирующую кость — так же, как это
                # делали штатные модели GoldSrc.
                infs = _top_weights(key_of.get(point), bone_map, limit=1)
                lines.append(
                    f"{infs[0][0]} {_fmt(gx)} {_fmt(gy)} {_fmt(gz)} "
                    f"{_fmt(nx)} {_fmt(ny)} {_fmt(nz)} {_fmt(u)} {_fmt(1.0 - v)}")
    lines.append("end")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _scale3(p, s):
    return (p[0] * s, p[1] * s, p[2] * s)


def _shift(p, origin):
    return (p[0] + origin[0], p[1] + origin[1], p[2] + origin[2])


def _top_weights(weights, bone_map, limit=3):
    """До 3 влияний точки -> [(индекс SMD, вес)]. Первое — всегда 1.0.

    Формат SMD: у вершины первая строка задаёт кость с неявным весом 1.0,
    следующие (необязательные) — вес ОСТАТКА. Движок нормирует: при весах
    (1.0, w2) реальная доля второй кости = w2 / (1 + w2). Поэтому веса
    пересчитываем так, чтобы доли совпали с исходными из PSK.
    """
    if not weights:
        return [(-1, 1.0)]
    pairs = sorted(((b, w) for b, w in weights.items() if b in bone_map),
                   key=lambda bw: -bw[1])[:limit]
    if not pairs:
        return [(-1, 1.0)]
    total = sum(w for _, w in pairs) or 1.0
    share = [w / total for _, w in pairs]
    # первая кость = 1.0, остальные — их доля ОТ первой (движок нормирует)
    out = [(bone_map[pairs[0][0]], 1.0)]
    for k in range(1, len(pairs)):
        if share[k] >= 0.02:
            out.append((bone_map[pairs[k][0]], share[k] / share[0]))
    return out


# ------------------------------------------------------------------- QC


TEMPLATE = """// ---------------------------------------------------------------------------
// QC-скрипт модели игрока CS 1.6: {name}
// Сгенерирован Tools/goldsrc/build.py — править лучше генератор, а не этот файл.
//
// Скелет: {bones} костей (риг Unreal K29, обрезан до нагруженных весов)
// Геометрия: {tris} треугольников, {verts} уникальных позиций
// Анимации: {sequences} последовательностей в порядке CS 1.6 (см. anim.py)
// ---------------------------------------------------------------------------

$modelname "{modelname}"
$cd "{cd}"
$cdtexture "{cdtexture}"

$scale 1.0
$cliptotextures

// Ось модели. В SMD лицо смотрит в -Y, Z — вверх; движок ждёт, что персонаж
// смотрит в +X, поэтому studiomdl крутит модель на +90° сам (значение по
// умолчанию). Дополнительный поворот не задаём: $rotate 0 сломал бы это.
$origin 0 0 {origin_z}

// Игровой bbox: 32x32 в основании, рост 72 юнита, центр по вертикали в
// середине коробки (движок ставит модель origin'ом в центр игрока).
$bbox {bbox}
$cbox {cbox}
$eyeposition {eye}

// --- текстуры --------------------------------------------------------------
{textures}
// --- меш -------------------------------------------------------------------
{body}
// --- кости для анимации (верхняя часть скелета) -----------------------------
{controllers}
// --- привязки (оружие в руках) ---------------------------------------------
{attachments}
// --- хитбоксы (группы попаданий CS 1.6) ------------------------------------
{hitboxes}
// --- 111 последовательностей в порядке движка -------------------------------
{sequences_qc}
"""



def write_qc(path, ctx):
    ctx = dict(ctx)
    ctx["modelname"] = ctx["modelname"].replace("\\", "/")
    text = TEMPLATE.format(**ctx)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


