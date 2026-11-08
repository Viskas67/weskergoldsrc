#!/usr/bin/env python3
"""Сборка модели Вескера для CS 1.6 / GoldSrc из исходников в репозитории.

Что делает:

1. читает ``Models/Bodies/SKM_K29_Body01.psk`` (12 382 вершины, 13 683 три);
2. восстанавливает скелет по весам (поза скелета в файле не совпадает с позой
   меша, поэтому суставы считаются по группам весов);
3. конвертирует UE-оси в GoldSrc (X вперёд, Y влево, Z вверх), ставит ступни
   на Z = 0, масштаб 1:1 (рост 170 юнитов, как у стандартного игрока HL);
4. пишет reference SMD, нарезанный под лимиты (2048 вершин / 4080 три на SMD),
   QC и 8-битные BMP из PNG-текстур;
5. вызывает studiomdl и получает готовый .mdl.

Модель делается играбельной моделью игрока CS 1.6: рост приводится к 72
юнитам (как у стандартных моделей, иначе персонаж вдвое выше хитбокса),
origin ставится в середину коробки, считаются хитбоксы с группами попаданий
(голова/грудь/живот/руки/ноги) и 111 анимационных последовательностей в том
же порядке, что и у стандартных моделей — см. anim.py.

Никакого decimation: все 13 683 треугольника и 12 382 вершины исходника
попадают в модель, дробление только по лимитам формата. Если нужно меньше
треугольников — это делает retopo.py (QEM), он вызывает этот же конвейер:

    python3 Tools/goldsrc/build.py --level 1   # ретопология до 5000 три
    python3 Tools/goldsrc/build.py --tris 7000 # свой предел

Использование::

    python3 Tools/goldsrc/build.py            # полная сборка
    python3 Tools/goldsrc/build.py --no-compile   # только SMD/QC/BMP
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import anim                     # noqa: E402
import rig                      # noqa: E402
import smd                      # noqa: E402
import textures                 # noqa: E402
from meshbuild import Skeleton, dominant_bone_map, split_mesh   # noqa: E402
from psk import load_psk        # noqa: E402

PSK = os.path.join(ROOT, "Models", "Bodies", "SKM_K29_Body01.psk")
TEXDIR = os.path.join(ROOT, "Textures", "Outfit01")
OUT = os.path.join(ROOT, "Build", "goldsrc")
MODEL_NAME = "wesker.mdl"   # без путей: studiomdl пишет по относительному пути
TEX_SIZE = 512          # GoldSrc: 512x512 безопасный максимум для 1.6
PLAYER_HEIGHT = 72.0    # рост стандартной модели игрока GoldSrc/CS 1.6
PLAYER_HULL = 16.0      # половина основания коробки игрока (32x32)
LEVEL_TRIS = (5000, 10000, 20000, 40000, 50000)   # уровни 1-5 (см. retopo.py)
REPORT = {}             # статистика ретопологии для report.txt

TEXTURES = {
    "MI_K29Torso01": "T_K29Torso01_BC.png",
    "MI_K29Arms01": "T_K29Arms01_BC.png",
    "MI_K29Legs01": "T_K29Legs01_BC.png",
}

# --------------------------------------------------------------- утилиты


def log(msg=""):
    print(msg, flush=True)


def clean():
    if os.path.isdir(os.path.join(ROOT, "Build")):
        shutil.rmtree(os.path.join(ROOT, "Build"))


# ------------------------------------------------------------------ main


def write_report(out_root, level=None, target=None):
    """Короткий отчёт о сборке: Build/goldsrc/level<N>/report.txt."""
    st = REPORT.get("rstats")
    lines = ["Ретопология модели игрока для CS 1.6 / GoldSrc", ""]
    if level:
        lines.append(f"Уровень: {level} ({target} треугольников)")
    elif target:
        lines.append(f"Предел: {target} треугольников")
    else:
        lines.append("Ретопология: выключена (сборка без уменьшения)")
    lines.append("")
    if st:
        lines += [
            f"Исходник:      {st['src_tris']} треугольников, {st['src_verts']} вершин",
            f"Результат:     {st['tris']} треугольников, {st['verts']} вершин",
            f"UV-островов:   {st['charts']}",
            f"Способ:        {st['mode']}",
        ]
        if st.get("deviation"):
            mean, worst = st["deviation"]
            lines.append(f"Отклонение от исходной поверхности: "
                         f"среднее {mean:.3f}, макс {worst:.3f} юнита")
    lines += [
        "",
        "Как поставить в игру:",
        f"  models/player/<имя>/<файл>.mdl",
        "  имя папки задаётся в .res/коде; стандартный вариант — cstrike/models/player/",
        "",
    ]
    if REPORT.get("qc"):
        lines.append(f"QC: {REPORT['qc']}")
    path = os.path.join(out_root, "report.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compile", action="store_true", help="не запускать studiomdl")
    ap.add_argument("--texsize", type=int, default=TEX_SIZE)
    ap.add_argument("--psk", default=PSK, help="исходный .psk")
    ap.add_argument("--level", type=int, choices=(1, 2, 3, 4, 5),
                    help="уровень ретопологии 1-5 (5000...50000 треугольников)")
    ap.add_argument("--tris", type=int, help="свой предел числа треугольников")
    ap.add_argument("--no-bone-cross", action="store_true",
                    help="не схлопывать рёбра через суставы")
    ap.add_argument("--no-seam-cross", action="store_true",
                    help="не схлопывать рёбра через UV-швы")
    ap.add_argument("--no-check", action="store_true",
                    help="не мерить отклонение от исходной поверхности")
    args = ap.parse_args(argv)

    target = args.tris
    if target is None and args.level:
        target = LEVEL_TRIS[args.level - 1]

    # уровень/свой предел пишем в отдельную папку, чтобы не затирать
    # полную сборку без децимации
    if target:
        tag = f"level{args.level}" if args.level else f"tris{target}"
        out_root = os.path.join(OUT, tag)
    else:
        out_root = OUT
    # имя .mdl всегда одно: уровень виден по папке, а в игру модель кладут
    # как models/player/<папка>/wesker.mdl
    model_name = MODEL_NAME[:-4]

    smd_dir = os.path.join(out_root, "smd")
    tex_dir = os.path.join(out_root, "textures")
    mdl_dir = os.path.join(out_root, "mdl")
    for d in (smd_dir, tex_dir, mdl_dir):
        os.makedirs(d, exist_ok=True)

    log("[1/6] читаю PSK")
    mesh = load_psk(args.psk)
    log(f"      {len(mesh.points)} вершин, {len(mesh.faces)} треугольников, "
        f"{len(mesh.materials)} материала, {len(mesh.bones)} костей")

    if target:
        import retopo
        if args.level:
            log(f"[1/6] уровень {args.level}: {retopo.describe(args.level)}")
        mesh, rstats = retopo.retopologize(
            mesh, target, report=log,
            allow_seam=not args.no_seam_cross,
            allow_bone=not args.no_bone_cross,
            check=not args.no_check)
        log(f"      результат: {rstats['tris']} треугольников, "
            f"{rstats['verts']} вершин")
        REPORT["rstats"] = rstats

    log("[2/6] строю скелет по весам")
    sk = Skeleton(mesh.bones)
    dom = dominant_bone_map(mesh, sk)
    used = sorted({infs[0][0] for infs in dom.values()})
    needed = set(used)
    for b in used:                       # добавляем предков
        cur = mesh.bones[b].parent
        while cur >= 0:
            needed.add(cur)
            cur = mesh.bones[cur].parent
    needed = sorted(needed)
    log(f"      костей в модели: {len(needed)} (из 529)")

    # ---- позиции/ориентации
    pos_gold, rot_local_abs, rot_world, pw = rig.solve_skeleton(mesh, needed)
    bone_map = {b: i for i, b in enumerate(needed)}
    bones = [mesh.bones[b] for b in needed]

    pos_local = {}
    for i, b in enumerate(needed):
        if mesh.bones[b].parent < 0:
            pos_local[i] = pos_gold[b]
        else:
            p = mesh.bones[b].parent
            d = [pos_gold[b][k] - pos_gold[p][k] for k in range(3)]
            pm = rot_world[p]
            pos_local[i] = (
                pm[0][0] * d[0] + pm[1][0] * d[1] + pm[2][0] * d[2],
                pm[0][1] * d[0] + pm[1][1] * d[1] + pm[2][1] * d[2],
                pm[0][2] * d[0] + pm[1][2] * d[1] + pm[2][2] * d[2],
            )
    rot_local = [rot_local_abs[b] for b in needed]

    # ---- высота и масштаб ------------------------------------------------
    # Игрок GoldSrc — это коробка 32x32x72 юнита с origin в СЕРЕДИНЕ (ноги на
    # -36, макушка на +36). Если оставить рост 170, модель будет вдвое выше
    # хитбокса и упрётся головой в потолки, поэтому рост приводим к 72.
    zs = [mesh.points[i][2] for i in range(len(mesh.points))]
    raw_height = max(zs) - min(zs)
    scale = PLAYER_HEIGHT / raw_height
    bottom_raw = min(zs)
    log(f"      рост исходника {raw_height:.1f} юнитов -> масштаб {scale:.4f} "
        f"(цель {PLAYER_HEIGHT:.0f})")
    # origin по вертикали: центр коробки игрока
    origin_z = -PLAYER_HEIGHT / 2.0

    log("[3/6] нарезаю меш под лимиты GoldSrc")
    chunks = split_mesh(mesh, dom)
    for c in chunks:
        log(f"      {mesh.materials[c['material']]:16} {len(c['tris']):5} три, "
            f"{len(c['wedges']):5} вершин")

    log("[4/6] пишу SMD и анимации")
    groups = {}
    for c in chunks:
        groups.setdefault(mesh.materials[c["material"]], []).append(c)

    # веса точек: {(точка, кость): вес} — нужны, чтобы вершины остались
    # привязанными к тем же суставам, что и в PSK (а не к одной кости).
    point_weights = {}
    for w, point, bone in mesh.weights:
        if w > 0 and bone in bone_map:
            point_weights[(point, bone)] = point_weights.get((point, bone), 0.0) + w

    # Rig — единый источник позы привязки для reference SMD и анимаций.
    anim_rig = anim.Rig(bones, pos_local, rot_local, bone_map, scale=scale,
                        origin_z=origin_z)
    bind_pose = anim_rig.solve(anim.Pose())

    body_lines = []
    # Каждый чанк — отдельный $bodygroup с единственной моделью: тогда движок
    # всегда рисует его. Если положить 2 модели в один bodygroup, GoldSrc
    # покажет только model 0 и половина геометрии пропадёт.
    for mat_name, mat_chunks in sorted(groups.items()):
        for pi, chunk in enumerate(mat_chunks, start=1):
            fname = f"{model_name}_{mat_name}_{pi}.smd"
            smd.write_reference_smd(os.path.join(smd_dir, fname), bones,
                                    pos_local, rot_local, [chunk], mesh, bone_map,
                                    weights=point_weights, scale=scale,
                                    origin=(0.0, 0.0, origin_z),
                                    bone_pose=bind_pose)
            body_lines.append('$bodygroup "{}_{}" {{\n    studio "{}"\n}}'.format(
                mat_name, pi, fname[:-4]))

    # --- анимации ---------------------------------------------------------
    seq_qc, seq_smd = _write_sequences(anim, anim_rig, smd_dir, model_name, log)
    REPORT["sequences"] = len(seq_qc)

    log("[5/6] конвертирую текстуры в 8-бит BMP")
    tex_names = []
    for mat_name, png in TEXTURES.items():
        src = os.path.join(TEXDIR, png)
        if not os.path.exists(src):
            raise SystemExit(f"нет текстуры {src}")
        bmp_name = mat_name + ".bmp"   # имя BMP = имя материала в SMD
        textures.png_to_bmp8(src, os.path.join(tex_dir, bmp_name), size=args.texsize, report=log)
        tex_names.append(bmp_name)

    # --- привязки ---------------------------------------------------------
    # Движок берёт оружие из этих точек: 0 — правая кисть, 1 — левая.
    # Голову (2) и «грудь» (3) добавляем отдельно — их используют плагины и
    # сторонние моды; стандартным моделям хватает первых двух.
    bone_names = {mesh.bones[b].name for b in needed}
    attach_candidates = [
        (0, "joint_HandRT_01", "joint_ElbowRT_01"),
        (1, "joint_HandLT_01", "joint_ElbowLT_01"),
        (2, "joint_Head_01", "joint_NeckA_01"),
        (3, "joint_TorsoC_01", "joint_TorsoB_01"),
    ]
    attachments = []
    for idx, want, fallback in attach_candidates:
        for name in (want, fallback):
            if name in bone_names:
                attachments.append(_attachment(idx, name, anim_rig, scale, origin_z))
                break
    log("      привязки: " + ", ".join(a.split('"')[1] for a in attachments))

    # --- контроллеры (движок крутит ими корпус) ---------------------------
    controllers = _controllers(bone_names)

    # --- хитбоксы ---------------------------------------------------------
    # Считаем по вершинам позы привязки и переводим в локальные оси кости,
    # как это делает сам studiomdl, когда $hbox в QC не задан. Группы попаданий
    # (1 голова, 2 грудь, 3 живот, 4/5 руки, 6/7 ноги) — как у CS 1.6.
    hitboxes = _hitboxes(anim_rig, mesh, point_weights, bone_map, scale, origin_z)
    log(f"      хитбоксы: {len(hitboxes)} шт., группы попаданий CS 1.6")
    REPORT["hitboxes"] = len(hitboxes)

    # --- bbox / cbox / глаз ------------------------------------------------
    half_x = max(abs(p[0]) for p in mesh.points) * scale
    half_y = max(abs(p[1]) for p in mesh.points) * scale
    eye_z = origin_z + PLAYER_HEIGHT * 0.90
    bbox = (f"-{PLAYER_HULL:.0f} -{PLAYER_HULL:.0f} {-PLAYER_HEIGHT / 2:.1f} "
            f"{PLAYER_HULL:.0f} {PLAYER_HULL:.0f} {PLAYER_HEIGHT / 2:.1f}")
    cbox = bbox
    if max(half_x, half_y) > PLAYER_HULL:
        log(f"      внимание: модель шире коробки игрока "
            f"({max(half_x, half_y):.1f} > {PLAYER_HULL:.0f}) — руки/оружие могут "
            f"выходить за хитбокс, это нормально")

    qc_path = os.path.join(smd_dir, model_name + ".qc")
    ctx = dict(
        name="Вексер (K29)" + (f", уровень {args.level}" if args.level else ""),
        bones=len(needed),
        tris=len(mesh.faces),
        verts=len({mesh.wedge_point[w] for tri in mesh.faces for w in tri}),
        sequences=len(seq_qc),
        modelname=model_name + ".mdl",
        cd=".",
        cdtexture="../textures",
        origin_z=f"{origin_z:.1f}",
        bbox=bbox,
        cbox=cbox,
        eye=f"0 0 {eye_z:.1f}",
        textures="// имена BMP совпадают с именами материалов в SMD:\n// " + ", ".join(tex_names),
        body="\n".join(body_lines),
        controllers="\n".join(controllers),
        attachments="\n".join(attachments),
        hitboxes="\n".join(hitboxes),
        sequences_qc="\n".join(seq_qc),
    )
    smd.write_qc(qc_path, ctx)
    log(f"      QC: {qc_path}")

    if args.no_compile:
        log("[6/6] компиляция пропущена (--no-compile)")
        REPORT["qc"] = qc_path
        return 0

    log("[6/6] компилирую studiomdl")
    exe = os.environ.get("STUDIOMDL", os.path.join(HERE, "build", "studiomdl"))
    if not os.path.exists(exe):
        log("      нет компилятора, собираю: bash Tools/goldsrc/build_studiomdl.sh")
        subprocess.run(["bash", os.path.join(HERE, "build_studiomdl.sh")], check=True)
    res = subprocess.run([exe, "-i", model_name + ".qc"], cwd=smd_dir,
                         capture_output=True, text=True)
    tail = (res.stdout + res.stderr).strip().splitlines()[-25:]
    for line in tail:
        log("      " + line)
    if res.returncode != 0:
        log("      компиляция не удалась")
        return res.returncode

    produced = [f for f in os.listdir(smd_dir) if f.endswith(".mdl")]
    for f in produced:
        shutil.copy(os.path.join(smd_dir, f), os.path.join(mdl_dir, f))
        log(f"      готово: {os.path.join(mdl_dir, f)} ({os.path.getsize(os.path.join(mdl_dir, f))} байт)")
    log(f"      отчёт: {write_report(out_root, args.level, target)}")
    return 0


def _write_sequences(anim, rig, smd_dir, model_name, log):
    """Пишет SMD всех 111 анимаций и возвращает строки $sequence для QC.

    Каждая последовательность — один или несколько SMD (для оружия движок
    смешивает 9 вариантов по горизонтали через ``blend XR``). Заглушки
    (``I_am_a_stupid_placeholder`` и т.п.) пишутся одной позой: так движку
    есть что проигрывать, а место в списке сохраняется.
    """
    table = anim.sequence_table()
    seq_lines = []
    enemies = {}
    total_smd = 0
    for entry in table:
        name = entry["name"]
        clip = entry["factory"]()
        variants = anim.blend_variants(clip, entry["blends"] or 1)
        files = []
        for v, variant in enumerate(variants, start=1):
            fname = f"anim_{model_name}_{name}_{v}.smd"
            anim.write_animation_smd(os.path.join(smd_dir, fname), rig, variant)
            files.append(fname[:-4])
            total_smd += 1
        enemies[name] = clip
        body = "\n".join(f'    "{f}"' for f in files)
        parts = [f'$sequence "{name}" {{', body]
        if entry["blends"]:
            parts.append(f"    blend XR -90 90")
        if entry["act"]:
            parts.append(f"    {entry['act']} {entry['weight']}")
        for ev, frame, opt in entry["events"]:
            parts.append(f'    {{ event {ev} {frame} "{opt}" }}')
        parts.append(f"    fps {entry['fps']}")
        if entry["loop"]:
            parts.append("    loop")
        parts.append("}")
        seq_lines.append("\n".join(parts))
    log(f"      анимаций: {len(table)} последовательностей, {total_smd} SMD")
    return seq_lines, total_smd


def _attachment(index, bone, rig, scale, origin_z):
    """$attachment вида «в кисти».

    Смещение задаётся в локальных осях кости — берём позицию «чуть вперёд по
    оружию», чтобы ствол смотрел туда же, куда и кисть. Для головы/корпуса
    смещение нулевое (это просто маркер).
    """
    if index == 0:
        org = (4.0, 0.0, 0.0)      # правая кисть: чуть вперёд по хвату
    elif index == 1:
        org = (4.0, 0.0, 0.0)
    else:
        org = (0.0, 0.0, 0.0)
    return f'$attachment {index} "{bone}" {org[0]:.3f} {org[1]:.3f} {org[2]:.3f}'


def _controllers(bone_names):
    """$controller: движок анимирует ими наклоны корпуса (bone controllers).

    Индекс контроллера — это индекс в списке, а не в скелете; стандартные
    модели игроков держат контроллеры на позвоночнике и шее, чтобы клиент
    мог наклонять модель по виду игрока. Ставим те, чьи кости есть.
    """
    wanted = [("joint_Spine", "XR", -30, 30), ("joint_Spine1", "XR", -30, 30),
              ("joint_Spine2", "XR", -30, 30), ("joint_Spine3", "XR", -30, 30)]
    # у нашего рига нет Bip01 Spine*, поэтому контроллеры ставим на реальные
    # кости корпуса — движок всё равно ищет их по имени из QC.
    wanted = [("joint_TorsoA_01", "XR", -30.0, 30.0),
              ("joint_TorsoB_01", "XR", -30.0, 30.0),
              ("joint_TorsoC_01", "XR", -30.0, 30.0),
              ("joint_NeckA_01", "XR", -30.0, 30.0)]
    out = []
    idx = 0
    for name, kind, lo, hi in wanted:
        if name in bone_names:
            out.append(f'$controller {idx} "{name}" {kind} {lo:.0f} {hi:.0f}')
            idx += 1
    return out


def _hitboxes(rig, mesh, point_weights, bone_map, scale, origin_z):
    """$hbox по вершинам позы привязки, в локальных осях каждой кости."""
    # точка -> кость с наибольшим весом
    dom = {}
    for (point, bone), w in point_weights.items():
        if point not in dom or w > dom[point][1]:
            dom[point] = (bone, w)
    # мировые трансформации позы привязки
    pos, rot = rig.bind_world()
    box = {}
    for point, (bone, _w) in dom.items():
        si = bone_map.get(bone)
        if si is None:
            continue
        # мировая позиция точки (масштаб + origin, как в SMD)
        p = (mesh.points[point][0] * scale, mesh.points[point][1] * scale,
             mesh.points[point][2] * scale + origin_z)
        # в локальные оси кости
        d = tuple(p[k] - pos[si][k] for k in range(3))
        local = [sum(rot[si][k][i] * d[k] for k in range(3)) for i in range(3)]
        b = box.setdefault(si, [list(local), list(local)])
        for i in range(3):
            b[0][i] = min(b[0][i], local[i])
            b[1][i] = max(b[1][i], local[i])

    out = []
    for si, (lo, hi) in sorted(box.items()):
        name = rig.bones[si].name
        group = anim.hitgroup_of(name)
        if group is None:
            continue
        # вырожденные коробки (кость без собственных вершин) не пишем
        if all(hi[i] - lo[i] < 1.0 for i in range(3)):
            continue
        # небольшой запас, чтобы хитбокс не был «в обрез»
        pad = 0.5
        out.append('$hbox {} "{}" {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f}'.format(
            group, name, lo[0] - pad, lo[1] - pad, lo[2] - pad,
            hi[0] + pad, hi[1] + pad, hi[2] + pad))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
