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


def write_reference_smd(path, bones, pos_local, rot_local, chunks, mesh, bone_map):
    """Пишет reference SMD (меш + скелет) в GoldSrc-пространстве.

    * ``bones``       — список Bone (индексы .psk);
    * ``pos_local``   — локальные смещения костей в порядке SMD;
    * ``rot_local``   — локальные углы (рад) в порядке SMD;
    * ``chunks``      — пачки треугольников из meshbuild.split_mesh;
    * ``bone_map``    — индекс .psk -> индекс SMD.
    """
    lines = ["version 1", "nodes"]
    for smd_index, bone in enumerate(bones):
        parent = bone_map.get(bone.parent, -1)
        lines.append(f'{smd_index:3d} "{bone.name}" {parent}')
    lines.append(dummy_node(len(bones)))
    lines.append("end")
    lines.append("skeleton")
    lines.append("time 0")
    for smd_index in range(len(bones)):
        p = pos_local[smd_index]
        r = rot_local[smd_index]
        # формат SMD: "<индекс кости> px py pz rx ry rz" — без индекса
        # studiomdl парсит строку sscanf'ом и молча теряет её.
        lines.append(f"{smd_index:3d} " + " ".join(_fmt(v) for v in (*p, *r)))
    lines.append("end")
    lines.append("triangles")
    for chunk in chunks:
        # имя материала в SMD = имя BMP-файла (studiomdl ищет текстуру по нему)
        mat_name = mesh.materials[chunk["material"]] + ".bmp"
        for tri in chunk["tris"]:
            lines.append(mat_name)
            for w in tri:
                pt = mesh.points[mesh.wedge_point[w]]
                nx, ny, nz = (0.0, 0.0, 0.0)
                if mesh.normals and mesh.wedge_point[w] < len(mesh.normals):
                    nx, ny, nz = mesh.normals[mesh.wedge_point[w]]
                x, y, z = pt
                # Координаты уже в системе SMD: X вбок, Y глубина, Z вверх
                # (см. to_gold). Поворот лица в +X делает $rotate при компиляции.
                gx, gy, gz = x, y, z
                onx, ony, onz = nx, ny, nz
                u, v = mesh.wedge_uv[w]
                bone = bone_map[_dominant_bone(mesh, mesh.wedge_point[w])]
                lines.append(
                    f"{bone} {_fmt(gx)} {_fmt(gy)} {_fmt(gz)} "
                    f"{_fmt(onx)} {_fmt(ony)} {_fmt(onz)} {_fmt(u)} {_fmt(1.0 - v)}"
                )
    lines.append("end")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


_DOM_CACHE = {}


def _dominant_bone(mesh, point):
    key = id(mesh)
    cache = _DOM_CACHE.get(key)
    if cache is None:
        acc = {}
        for w, pt, bone in mesh.weights:
            if w <= 0:
                continue
            acc.setdefault(pt, {})
            acc[pt][bone] = acc[pt].get(bone, 0.0) + w
        cache = {p: max(d.items(), key=lambda kv: kv[1])[0] for p, d in acc.items()}
        _DOM_CACHE[key] = cache
    return cache[point]


def dominant_map(mesh):
    acc = {}
    for w, pt, bone in mesh.weights:
        if w <= 0:
            continue
        acc.setdefault(pt, {})
        acc[pt][bone] = acc[pt].get(bone, 0.0) + w
    return {p: max(d.items(), key=lambda kv: kv[1])[0] for p, d in acc.items()}


# ------------------------------------------------------------------- QC


TEMPLATE = """// ---------------------------------------------------------------------------
// QC-скрипт для {name}
// Сгенерирован Tools/goldsrc/build.py — править лучше генератор, а не этот файл.
//
// Скелет: {bones} костей (исходный риг Unreal, 529 костей, обрезан до весов)
// Геометрия: {tris} треугольников, {verts} уникальных позиций, без decimation
// ---------------------------------------------------------------------------

$modelname "{modelname}"
$cd "{cd}"
$cdtexture "{cdtexture}"

// Оси: PSK (UE) -> GoldSrc. Поворот уже применён к вершинам и костям,
// поэтому studiomdl не должен крутить модель сам (по умолчанию +90).
$scale 1.0
$cliptotextures

$bbox {bbox}
$cbox {cbox}

$eyeposition 0 0 {eye}

// --- текстуры --------------------------------------------------------------
{textures}
// --- меш -------------------------------------------------------------------
{body}
// --- привязка --------------------------------------------------------------
{attachments}
// --- поза (пока без анимаций: один кадр-референс) ---------------------------
{sequence}
"""


def write_qc(path, ctx):
    ctx = dict(ctx)
    ctx["modelname"] = ctx["modelname"].replace("\\", "/")
    text = TEMPLATE.format(**ctx)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_single_frame_sequence(path, nodes, bone_names, pos_local, rot_local, bone_map):
    """Однокадровая sequence.smd (нужна studiomdl для $sequence)."""
    lines = ["version 1", "nodes"]
    for smd_index, bone in enumerate(bone_names):
        parent = -1 if bone.parent < 0 else bone_map[bone.parent]
        lines.append(f'{smd_index:3d} "{bone.name}" {parent}')
    lines.append("end")
    lines.append("skeleton")
    lines.append("time 0")
    for smd_index in range(len(bone_names)):
        lines.append(" ".join(_fmt(v) for v in (*pos_local[smd_index], *rot_local[smd_index])))
    lines.append("end")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def bone_rpy_degrees(rot_local, index):
    """Локальные углы SMD (уже в радианах)."""
    return tuple(rot_local[index])
