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
попадают в модель, дробление только по лимитам формата.

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compile", action="store_true", help="не запускать studiomdl")
    ap.add_argument("--texsize", type=int, default=TEX_SIZE)
    args = ap.parse_args()

    smd_dir = os.path.join(OUT, "smd")
    tex_dir = os.path.join(OUT, "textures")
    mdl_dir = os.path.join(OUT, "mdl")
    for d in (smd_dir, tex_dir, mdl_dir):
        os.makedirs(d, exist_ok=True)

    log("[1/6] читаю PSK")
    mesh = load_psk(PSK)
    log(f"      {len(mesh.points)} вершин, {len(mesh.faces)} треугольников, "
        f"{len(mesh.materials)} материала, {len(mesh.bones)} костей")

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
            fname = f"wesker_{mat_name}_{pi}.smd"
            smd.write_reference_smd(os.path.join(smd_dir, fname), bones,
                                    pos_local, rot_local, [chunk], mesh, bone_map)
            body_lines.append('$bodygroup "{}_{}" {{\n    studio "{}"\n}}'.format(
                mat_name, pi, fname[:-4]))

    _write_seq(os.path.join(smd_dir, "wesker_ref.smd"), bones, pos_local, rot_local, bone_map)

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

    qc_path = os.path.join(smd_dir, "wesker.qc")
    bbox = (min(mesh.points[i][0] for i in range(len(mesh.points))),
            min(mesh.points[i][1] for i in range(len(mesh.points))),
            0.0,
            max(mesh.points[i][0] for i in range(len(mesh.points))),
            max(mesh.points[i][1] for i in range(len(mesh.points))),
            height)
    ctx = dict(
        name="Вексер (K29)",
        bones=len(needed),
        tris=len(mesh.faces),
        verts=len({mesh.wedge_point[w] for tri in mesh.faces for w in tri}),
        modelname=MODEL_NAME,
        cd=".",
        cdtexture="../textures",
        bbox=f"-16 -16 0 16 16 {height:.2f}",
        cbox=f"-16 -16 0 16 16 72",
        eye=height - 6,
        textures="// имена BMP совпадают с именами материалов в SMD:\n// " + ", ".join(tex_names),
        body="\n".join(body_lines),
        attachments="\n".join(attachments),
        sequence='$sequence "ref" {\n    "wesker_ref"\n    fps 1\n}',
    )
    smd.write_qc(qc_path, ctx)
    log(f"      QC: {qc_path}")

    if args.no_compile:
        log("[6/6] компиляция пропущена (--no-compile)")
        return 0

    log("[6/6] компилирую studiomdl")
    exe = os.environ.get("STUDIOMDL", os.path.join(HERE, "build", "studiomdl"))
    if not os.path.exists(exe):
        log("      нет компилятора, собираю: bash Tools/goldsrc/build_studiomdl.sh")
        subprocess.run(["bash", os.path.join(HERE, "build_studiomdl.sh")], check=True)
    res = subprocess.run([exe, "-i", "wesker.qc"], cwd=smd_dir,
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
