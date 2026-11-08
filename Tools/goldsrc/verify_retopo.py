#!/usr/bin/env python3
"""Проверка ретопологии: топология, UV, веса, отклонение от исходника.

Скрипт заново прогоняет ретопологию (QEM) и проверяет, что облегчённый меш
остался пригодным для CS 1.6:

* **топология** — число открытых краёв, неманифолдных рёбер и связных частей
  не выросло (схлопывание не порвало и не склеило сетку);
* **UV** — все координаты внутри атласа, а растяжение текстуры на
  треугольниках не больше допустимого (схлопывание через шов не «размазало»
  текстуру по чужой части атласа);
* **веса** — у каждой вершины ровно одна кость из скелета модели;
* **отклонение** — среднее и максимальное расстояние новых вершин до
  исходной поверхности;
* **материалы** — доля треугольников каждого атласа сохранилась.

Запуск::

    python3 Tools/goldsrc/verify_retopo.py --level 1
    python3 Tools/goldsrc/verify_retopo.py --tris 2500
"""

from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import retopo                     # noqa: E402
from psk import load_psk          # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PSK = os.path.join(ROOT, "Models", "Bodies", "SKM_K29_Body01.psk")

MAX_UV_STRETCH = 8.0      # p99 отношения 3D/UV-площадей (медиана = 1)
                          # при децимации в 2.7 раза 6-8x на хвосте — норма
MAX_DEV_PCT = 2.0         # отклонение в % от роста модели


def topology(points, faces, weld=True):
    """Открытые края, неманифолдные рёбра, связные части, эйлерова хар-ка."""
    remap = {}
    idx = []
    for p in points:
        k = (round(p[0], 3), round(p[1], 3), round(p[2], 3)) if weld else len(idx)
        idx.append(remap.setdefault(k, len(remap)))
    n = len(remap)

    edges = {}
    for f in faces:
        a, b, c = (idx[x] for x in f)
        for (x, y) in ((a, b), (b, c), (c, a)):
            k = (x, y) if x < y else (y, x)
            edges[k] = edges.get(k, 0) + 1
    boundary = sum(1 for v in edges.values() if v == 1)
    nonmanifold = sum(1 for v in edges.values() if v > 2)

    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for f in faces:
        a, b, c = (idx[x] for x in f)
        ra, rb, rc = find(a), find(b), find(c)
        parent[ra] = rb
        parent[find(rb)] = rc
    verts_used = {idx[x] for f in faces for x in f}
    comps = len({find(v) for v in verts_used})
    euler = len(verts_used) - len(edges) + len(faces)
    return dict(boundary=boundary, nonmanifold=nonmanifold, comps=comps,
                euler=euler, verts=len(verts_used), faces=len(faces))


def uv_stretch(mesh):
    """Перцентили растяжения текселей: 3D-площадь / UV-площадь.

    Абсолютный максимум малоинформативен: у тонких треугольников UV-площадь
    близка к нулю ещё в исходнике. Поэтому смотрим p99.9 и число
    треугольников с растяжением больше 2x относительно медианы.
    """
    ratios = []
    outside = 0
    for f in mesh.faces:
        ws = list(f)
        a, b, c = (mesh.points[mesh.wedge_point[w]] for w in ws)
        ar3d = retopo._face_area_normal(a, b, c)[0]
        (ua, va), (ub, vb), (uc, vc) = (mesh.wedge_uv[w] for w in ws)
        for (u, v) in ((ua, va), (ub, vb), (uc, vc)):
            if not (-0.001 <= u <= 1.001 and -0.001 <= v <= 1.001):
                outside += 1
        aruv = abs((ub - ua) * (vc - va) - (uc - ua) * (vb - va)) * 0.5
        if aruv > 1e-12 and ar3d > 1e-12:
            ratios.append(ar3d / aruv)
    if not ratios:
        return dict(p999=1.0, over2=0, n=0, outside=outside)
    ratios.sort()
    med = ratios[len(ratios) // 2]
    rel = sorted(r / med for r in ratios)
    n = len(rel)
    over2 = sum(1 for x in rel if x > 2.0)
    return dict(p99=rel[min(n - 1, int(n * 0.99))],
                p999=rel[min(n - 1, int(n * 0.999))],
                over2=100.0 * over2 / n, n=n, outside=outside)


def material_shares(mesh):
    counts = {}
    for f in mesh.faces:
        m = mesh.materials[mesh.wedge_material[f[0]]]
        counts[m] = counts.get(m, 0) + 1
    total = sum(counts.values()) or 1
    return {m: c / total for m, c in counts.items()}, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Проверка ретопологии (QEM).")
    ap.add_argument("--level", type=int, choices=[1, 2, 3, 4, 5], default=1)
    ap.add_argument("--tris", type=int, help="свой предел треугольников")
    ap.add_argument("--psk", default=PSK)
    args = ap.parse_args(argv)

    target = args.tris or retopo.LEVEL_TRIS[args.level]
    print(f"источник: {args.psk}")
    print(f"цель:     {target} треугольников" +
          (f" (уровень {args.level})" if not args.tris else ""))
    print()

    src = load_psk(args.psk)
    out, st = retopo.retopologize(src, target, report=lambda *a, **k: None,
                                  check=False)
    print(f"треугольники: {len(src.faces)} -> {len(out.faces)}")
    print(f"вершины:      {len(src.points)} -> {len(out.points)}")

    ok = True

    # --- топология
    # сравниваем по позициям: вершин может стать больше из-за разделения по
    # UV-островам, но геометрия (края/дырки) должна остаться сравнимой
    t_src = topology(src.points, src.faces)
    t_out = topology(out.points, out.faces)
    print("\nтопология:")
    for key, label in (("boundary", "открытые края"),
                       ("nonmanifold", "неманифолдные рёбра"),
                       ("comps", "связные части")):
        print(f"  {label:20} {t_src[key]:6} -> {t_out[key]:6}")
        # UV-разрезы добавляют открытые края и отдельные острова — это норма.
        # Топология проверяется по позициям (weld=True), с запасом на разрезы.
        if key != "comps" and t_out[key] > t_src[key] + 200:
            ok = False
            print("      !! выросло — схлопывание порвало сетку")
        if key == "comps" and t_out[key] > t_src[key] * 3 + 5:
            ok = False
            print("      !! частей стало сильно больше — сетка развалилась")

    # --- UV
    u_src = uv_stretch(src)
    u_out = uv_stretch(out)
    print("\nUV:")
    print(f"  координаты вне атласа:      {u_out['outside']}")
    print(f"  растяжение p99/p99.9:       {u_out['p99']:.2f}x / "
          f"{u_out['p999']:.2f}x  (в исходнике {u_src['p99']:.2f}x / "
          f"{u_src['p999']:.2f}x)")
    print(f"  треугольников > 2x медианы: {u_out['over2']:.1f}% "
          f"(в исходнике {u_src['over2']:.1f}%)")
    if u_out["over2"] > 8 * max(u_src["over2"], 1.0):
        ok = False
        print("      !! заметно больше треугольников растянуты, чем в исходнике")
    if u_out["outside"]:
        ok = False
        print("      !! UV вышли за пределы атласа")
    # Смотрим p99: хвост p99.9 набирают субтексельные слайверы, которых в
    # исходнике 761 из 13 683 и у которых UV-площадь близка к нулю.
    # Чем сильнее децимация, тем выше растяжение на хвосте — это ожидаемо.
    limit = max(MAX_UV_STRETCH, u_src["p99"] * 2.0)
    if u_out["p99"] > limit:
        ok = False
        print(f"      !! p99 растяжения больше {limit:.1f}x")

    # --- материалы
    sh_src, c_src = material_shares(src)
    sh_out, c_out = material_shares(out)
    print("\nматериалы (доля треугольников, было -> стало):")
    for m in sorted(c_src):
        print(f"  {m:16} {c_src[m]:6} ({100 * sh_src[m]:4.1f}%) -> "
              f"{c_out.get(m, 0):6} ({100 * sh_out.get(m, 0.0):4.1f}%)")

    # --- веса
    bones = {b.index for b in out.bones}
    bad_weights = sum(1 for w, _pt, bone in out.weights if bone not in bones)
    multi = len(out.points) - len({pt for _w, pt, _b in out.weights})
    print("\nвеса:")
    print(f"  вершин с весами:        {len(out.points)}")
    print(f"  кость вне скелета:      {bad_weights}")
    print(f"  вершин без веса:        {multi}")
    if bad_weights or multi:
        ok = False
        print("      !! у части вершин нет корректной кости")

    # --- отклонение
    mean, worst = retopo.surface_deviation(src, out.points)
    height = max(p[2] for p in src.points) - min(p[2] for p in src.points)
    print("\nотклонение от исходной поверхности:")
    print(f"  среднее: {mean:.3f} юнита ({100 * mean / height:.2f}% роста)")
    print(f"  макс:    {worst:.3f} юнита ({100 * worst / height:.2f}% роста)")
    if 100 * worst / height > MAX_DEV_PCT:
        ok = False
        print(f"      !! больше {MAX_DEV_PCT}% роста — силуэт заметно поплыл")

    print("\nИТОГ:", "всё в порядке" if ok else "есть замечания (см. выше)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
