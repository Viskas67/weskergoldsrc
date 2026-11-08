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

    # ---- высота/центрирование
    zs = [mesh.points[i][2] for i in range(len(mesh.points))]
    height = max(zs) - min(zs)
    log(f"      рост меша: {height:.1f} юнитов, ступни на Z={min(zs):.2f}")

    log("[3/6] нарезаю меш под лимиты GoldSrc")
    chunks = split_mesh(mesh, dom)
    for c in chunks:
        log(f"      {mesh.materials[c['material']]:16} {len(c['tris']):5} три, "
            f"{len(c['wedges']):5} вершин")

    log("[4/6] пишу SMD")
    groups = {}
    for c in chunks:
        groups.setdefault(mesh.materials[c["material"]], []).append(c)

    body_lines = []
    # Каждый чанк — отдельный $bodygroup с единственной моделью: тогда движок
    # всегда рисует его. Если положить 2 модели в один bodygroup, GoldSrc
    # покажет только model 0 и половина геометрии пропадёт.
    for mat_name, mat_chunks in sorted(groups.items()):
        for pi, chunk in enumerate(mat_chunks, start=1):
            fname = f"{model_name}_{mat_name}_{pi}.smd"
            smd.write_reference_smd(os.path.join(smd_dir, fname), bones,
                                    pos_local, rot_local, [chunk], mesh, bone_map)
            body_lines.append('$bodygroup "{}_{}" {{\n    studio "{}"\n}}'.format(
                mat_name, pi, fname[:-4]))

    _write_seq(os.path.join(smd_dir, model_name + "_ref.smd"), bones,
               pos_local, rot_local, bone_map)

    log("[5/6] конвертирую текстуры в 8-бит BMP")
    tex_names = []
    for mat_name, png in TEXTURES.items():
        src = os.path.join(TEXDIR, png)
        if not os.path.exists(src):
            raise SystemExit(f"нет текстуры {src}")
        bmp_name = mat_name + ".bmp"   # имя BMP = имя материала в SMD
        textures.png_to_bmp8(src, os.path.join(tex_dir, bmp_name), size=args.texsize, report=log)
        tex_names.append(bmp_name)

    # $attachment можно вешать только на кости, которые реально есть в модели:
    # studiomdl собирает bonetable по вершинам, поэтому кость без собственных
    # вершин (например joint_Head_01) в таблицу не попадает.
    attach_candidates = [
        (0, "joint_Head_01", "joint_NeckA_01"),
        (1, "joint_HandRT_01", "joint_ElbowRT_01"),
        (2, "joint_HandLT_01", "joint_ElbowLT_01"),
    ]
    attachments = []
    for idx, want, fallback in attach_candidates:
        for name in (want, fallback):
            if name in {mesh.bones[b].name for b in needed}:
                attachments.append(f'$attachment {idx} "{name}" 0 0 0')
                break
    log("      привязки: " + ", ".join(a.split('"')[1] for a in attachments))

    qc_path = os.path.join(smd_dir, model_name + ".qc")
    bbox = (min(mesh.points[i][0] for i in range(len(mesh.points))),
            min(mesh.points[i][1] for i in range(len(mesh.points))),
            0.0,
            max(mesh.points[i][0] for i in range(len(mesh.points))),
            max(mesh.points[i][1] for i in range(len(mesh.points))),
            height)
    ctx = dict(
        name="Вексер (K29)" + (f", уровень {args.level}" if args.level else ""),
        bones=len(needed),
        tris=len(mesh.faces),
        verts=len({mesh.wedge_point[w] for tri in mesh.faces for w in tri}),
        modelname=model_name + ".mdl",
        cd=".",
        cdtexture="../textures",
        bbox=f"-16 -16 0 16 16 {height:.2f}",
        cbox=f"-16 -16 0 16 16 72",
        eye=height - 6,
        textures="// имена BMP совпадают с именами материалов в SMD:\n// " + ", ".join(tex_names),
        body="\n".join(body_lines),
        attachments="\n".join(attachments),
        sequence='$sequence "ref" {\n    "%s_ref"\n    fps 1\n}' % model_name,
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


def _write_seq(path, bones, pos_local, rot_local, bone_map):
    lines = ["version 1", "nodes"]
    for i, b in enumerate(bones):
        parent = -1 if b.parent < 0 else bone_map[b.parent]
        lines.append(f'{i:3d} "{b.name}" {parent}')
    lines.append(smd.dummy_node(len(bones)))
    lines += ["end", "skeleton", "time 0"]
    for i in range(len(bones)):
        p, r = pos_local[i], rot_local[i]
        lines.append(f"{i:3d} " + " ".join(f"{v:.6f}" for v in (*p, *r)))
    lines.append("end")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
