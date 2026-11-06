"""Проверка собранного .mdl и рендер превью без движка. Только stdlib.

* разбирает заголовок/кости/меши/текстуры;
* пишет PNG-превью (три ракурса) простым софтверным растеризатором
  с z-буфером, чтобы глазами проверить, что модель действительно целая.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from goldsrc_math import angle_matrix  # noqa: E402

# ------------------------------------------------------------------ MDL


def read_mdl(path):
    data = open(path, "rb").read()
    (ident, version) = struct.unpack_from("<4si", data, 0)[0], struct.unpack_from("<i", data, 4)[0]
    name = data[8:72].split(b"\x00")[0].decode("latin1")
    length = struct.unpack_from("<i", data, 72)[0]
    eye = struct.unpack_from("<3f", data, 76)
    bmin = struct.unpack_from("<3f", data, 88)
    bmax = struct.unpack_from("<3f", data, 100)
    bbmin = struct.unpack_from("<3f", data, 112)
    bbmax = struct.unpack_from("<3f", data, 124)
    (numbones, boneindex, numbonesctrl, bcindex, numhitboxes, hitboxindex,
     numseq, seqindex, numseqgroups, seqgroupindex, numtextures, textureindex,
     texturedataindex, numskinref, numskinfamilies, skinindex,
     numbodyparts, bodypartindex, numattachments, attachmentindex) = struct.unpack_from("<20i", data, 140)

    bones = []
    for i in range(numbones):
        off = boneindex + i * 112
        bname = data[off:off + 32].split(b"\x00")[0].decode("latin1")
        parent = struct.unpack_from("<i", data, off + 32)[0]
        value = struct.unpack_from("<6f", data, off + 64)
        bones.append(dict(name=bname, parent=parent, value=value))

    textures = []
    for i in range(numtextures):
        off = textureindex + i * 80
        tname = data[off:off + 64].split(b"\x00")[0].decode("latin1")
        flags, w, h, index = struct.unpack_from("<4i", data, off + 64)
        textures.append(dict(name=tname, flags=flags, width=w, height=h, index=index))

    bodyparts = []
    for i in range(numbodyparts):
        off = bodypartindex + i * 76
        bpname = data[off:off + 64].split(b"\x00")[0].decode("latin1")
        nummodels, base, modelindex = struct.unpack_from("<3i", data, off + 64)
        models = []
        for j in range(nummodels):
            moff = modelindex + j * 112
            mname = data[moff:moff + 64].split(b"\x00")[0].decode("latin1")
            (unused, unused2, nummesh, meshindex, numverts, vertinfoindex,
             vertindex, numnorms, norminfoindex, normindex,
             bvindex, bnindex) = struct.unpack_from("<i f 10i", data, moff + 64)
            meshes = []
            for k in range(nummesh):
                eoff = meshindex + k * 20
                numtris, triindex, skinref, nummesh_norms, unusedm = struct.unpack_from("<5i", data, eoff)
                meshes.append(dict(numtris=numtris, triindex=triindex, skinref=skinref))
            verts = [struct.unpack_from("<3f", data, vertindex + v * 12) for v in range(numverts)]
            vertbone = data[vertinfoindex:vertinfoindex + numverts]
            models.append(dict(name=mname, meshes=meshes, verts=verts, vertbone=vertbone))
        bodyparts.append(dict(name=bpname, models=models))

    return dict(_data=data, ident=ident, version=version, name=name, length=length, eye=eye,
                bbox=(bmin, bmax), cbox=(bbmin, bbmax), bones=bones,
                textures=textures, bodyparts=bodyparts, skulls=(numskinref, numskinfamilies),
                numseq=numseq, numattachments=numattachments,
                numhitboxes=numhitboxes, size=len(data))


# ---------------------------------------------------------------- render


def png_write(path, w, h, rgb):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgb[y * w * 3:(y + 1) * w * 3]

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    open(path, "wb").write(out)


def bone_matrices(mdl):
    """Матрицы привязки (bone -> world), как их строит движок GoldSrc.

    ``value[0:3]`` — локальное смещение, ``value[3:6]`` — (pitch, yaw, roll)
    в радианах. Мировое положение родителя умножается слева, как в
    ``Build_Reference()`` из studiomdl / ``R_StudioSetupBones()`` в движке.
    """
    bones = mdl["bones"]
    world = {}

    def build(i):
        if i in world:
            return world[i]
        b = bones[i]
        px, py, pz, rx, ry, rz = b["value"]
        m = [row[:] + [0.0] for row in angle_matrix(rx, ry, rz)]
        if b["parent"] < 0:
            world[i] = (m, [px, py, pz])
        else:
            pm, pp = build(b["parent"])
            off = [pm[r_][0] * px + pm[r_][1] * py + pm[r_][2] * pz for r_ in range(3)]
            world[i] = (_mat_mul(pm, m), [pp[k] + off[k] for k in range(3)])
        return world[i]

    for i in range(len(bones)):
        build(i)
    return world


def _mat_mul(a, b):
    """R_ConcatTransforms для матриц 3x4 (как в mathlib движка)."""
    out = [[0.0] * 4 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            out[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j]
        out[i][3] = (a[i][0] * b[0][3] + a[i][1] * b[1][3] + a[i][2] * b[2][3] + a[i][3])
    return out


def bind_pose(mdl):
    """Треугольники модели в мировых координатах позы привязки."""
    mats = bone_matrices(mdl)
    verts, tris = [], []
    for bp in mdl["bodyparts"]:
        for mo in bp["models"]:
            base = len(verts)
            bones = mo["vertbone"]
            for vi, v in enumerate(mo["verts"]):
                m, off = mats[bones[vi]]
                verts.append(tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + off[r]
                                   for r in range(3)))
            for mesh in mo["meshes"]:
                for f in _read_tris(mdl, mesh):
                    tris.append((base + f[0], base + f[1], base + f[2]))
    return verts, tris


def render_views(mdl, outdir, size=420):
    """Три ракурса: спереди, сбоку, три четверти. Z-буфер, плоское освещение."""
    # собираем все треугольники в мировых координатах bind-позы
    tris = []
    for bp in mdl["bodyparts"]:
        for model in bp["models"]:
            verts = model["verts"]
            for mesh in model["meshes"]:
                base = mesh["triindex"]
                for t in range(mesh["numtris"]):
                    idx = []
                    off = base
                    # трисовые команды: short count, затем count вершин по 4 шорта
                    # (numtris > 0 => strip; для простоты читаем их отдельно)
                    idx = None
                    break
                if idx is None:
                    pass
    return tris


def rasterize(mdl, path, yaw_deg=0.0, pitch_deg=8.0, size=420):
    """Растеризует модель из bind-позы с z-буфером. Возвращает число треугольников."""
    verts_all = []
    tris = []
    for bp in mdl["bodyparts"]:
        for model in bp["models"]:
            faces = []
            base_vert = len(verts_all)
            verts_all.extend(model["verts"])
            for mesh in model["meshes"]:
                faces.extend(_read_tris(mdl, mesh))
            for f in faces:
                tris.append((base_vert + f[0], base_vert + f[1], base_vert + f[2]))
    return _draw(verts_all, tris, path, yaw_deg, pitch_deg, size)


def _read_tris(mdl, mesh):
    """Читает трисовые команды меша: (short count, count x (v, n, s, t)) ... 0.

    count < 0 => triangle fan, count > 0 => strip.
    Возвращает список треугольников как кортежи индексов вершин.
    """
    data = mdl["_data"]
    off = mesh["triindex"]
    out = []
    while True:
        count = struct.unpack_from("<h", data, off)[0]
        off += 2
        if count == 0:
            break
        strip = []
        for _ in range(abs(count)):
            v, n, s, t = struct.unpack_from("<4h", data, off)
            off += 8
            strip.append(v)
        for i in range(len(strip) - 2):
            if count < 0:
                tri = (strip[0], strip[i + 1], strip[i + 2])
            else:
                tri = (strip[i], strip[i + 1], strip[i + 2])
            out.append(tri)
    return out


def rasterize_strip(path, verts, tris, yaw_deg=0.0, pitch_deg=8.0, size=420, color=(200, 190, 180)):
    return _draw(verts, tris, path, yaw_deg, pitch_deg, size, color)


def _draw(verts, tris, path, yaw_deg, pitch_deg, size, color=(200, 190, 180)):
    if not verts:
        return 0
    ys = [v[2] for v in verts]
    zmin, zmax = min(ys), max(ys)
    cy = (zmin + zmax) * 0.5
    scale = size / (max(zmax - zmin, 1.0) * 1.25)

    cy_, sy_ = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))

    pts = []
    for x, y, z in verts:
        x0, y0, z0 = x, y, z - cy
        xr = x0 * cy_ + y0 * sy_
        yr = -x0 * sy_ + y0 * cy_
        yp = yr * cp - z0 * sp
        zp = yr * sp + z0 * cp
        pts.append((size * 0.5 + xr * scale, size * 0.5 - zp * scale, yp))

    zbuf = [-1e30] * (size * size)
    buf = bytearray(b"\x14\x16\x1a" * (size * size))
    light = (0.35, 0.5, 0.8)
    ln = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ln for c in light)
    drawn = 0
    for ia, ib, ic in tris:
        a, b, c = pts[ia], pts[ib], pts[ic]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(area) < 1e-9:
            continue
        # нормаль для освещения
        ux, uy, uz = (verts[ib][0] - verts[ia][0], verts[ib][1] - verts[ia][1], verts[ib][2] - verts[ia][2])
        vx, vy, vz = (verts[ic][0] - verts[ia][0], verts[ic][1] - verts[ia][1], verts[ic][2] - verts[ia][2])
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        shade = abs(nx / nl * light[0] + ny / nl * light[1] + nz / nl * light[2])
        col = tuple(min(255, int(c_ * (0.35 + 0.65 * shade))) for c_ in color)

        minx = max(0, int(min(a[0], b[0], c[0])))
        maxx = min(size - 1, int(max(a[0], b[0], c[0])) + 1)
        miny = max(0, int(min(a[1], b[1], c[1])))
        maxy = min(size - 1, int(max(a[1], b[1], c[1])) + 1)
        for py in range(miny, maxy + 1):
            for px in range(minx, maxx + 1):
                w0 = ((b[0] - a[0]) * (py + 0.5 - a[1]) - (b[1] - a[1]) * (px + 0.5 - a[0])) / area
                w1 = ((c[0] - b[0]) * (py + 0.5 - b[1]) - (c[1] - b[1]) * (px + 0.5 - b[0])) / area
                w2 = ((a[0] - c[0]) * (py + 0.5 - c[1]) - (a[1] - c[1]) * (px + 0.5 - c[0])) / area
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                depth = w2 * a[2] + w0 * b[2] + w1 * c[2]
                di = py * size + px
                if depth > zbuf[di]:
                    zbuf[di] = depth
                    buf[di * 3:di * 3 + 3] = bytes(col)
                    drawn += 1
    png_write(path, size, size, bytes(buf))
    return drawn


if __name__ == "__main__":
    mdl_path = sys.argv[1] if len(sys.argv) > 1 else "Build/goldsrc/mdl/wesker.mdl"
    info = read_mdl(mdl_path)
    print(f"ident={info['ident']!r} version={info['version']} size={info['size']}")
    print(f"name={info['name']!r}")
    print(f"bones={len(info['bones'])} textures={len(info['textures'])} "
          f"bodyparts={len(info['bodyparts'])} sequences={info['numseq']} "
          f"attachments={info['numattachments']} hitboxes={info['numhitboxes']}")
    print(f"bbox={info['bbox']} eye={info['eye']}")
    total_tris = sum(m['numtris'] for bp in info['bodyparts'] for mo in bp['models'] for m in mo['meshes'])
    print(f"triangles={total_tris}")
    if len(sys.argv) > 2:
        import inspect_mdl as im
        info2 = im.read_mdl(mdl_path)
        verts, tris = im.bind_pose(info2)
        os.makedirs(sys.argv[2], exist_ok=True)
        for label, yaw in (("front", 0), ("side", 90), ("q34", 35)):
            out = os.path.join(sys.argv[2], f"wesker_{label}.png")
            n = im._draw(verts, tris, out, yaw_deg=yaw, pitch_deg=8, size=480)
            print(f"  {out}: {n} пикселей, {len(tris)} треугольников")
    for bp in info["bodyparts"]:
        for mo in bp["models"]:
            print(f"  {bp['name']:16} {mo['name']:6} verts={len(mo['verts']):5} "
                  f"meshes={len(mo['meshes'])} tris={sum(m['numtris'] for m in mo['meshes'])}")
    for t in info["textures"]:
        print(f"  texture {t['name']:20} {t['width']}x{t['height']} flags={t['flags']}")
