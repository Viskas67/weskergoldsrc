#!/usr/bin/env python3
"""Ретопология (прореживание) модели игрока под CS 1.6 / GoldSrc. Только stdlib.

Что делает
----------
Строит из тяжёлого меша облегчённый — с заданным пределом треугольников — и
собирает из него готовый ``.mdl`` тем же конвейером, что и ``build.py``.

Алгоритм — QEM (quadric error metrics, Garland & Heckbert 1997): рёбра сетки
схлопываются в порядке возрастания «ошибки формы», поэтому первыми уходят
плоские участки, а лицо, кисти и стыки деталей держатся дольше всего.
Без ограничений такой алгоритм ломает модель в игре, поэтому добавлено:

* **материалы** — вершины разных атласов не сливаются никогда (треугольник не
  получит UV чужой текстуры);
* **UV-швы** — вершины разных UV-островов сливаются только на втором этапе,
  когда иначе до цели не добраться; на выходе вершина раздваивается по числу
  островов (в SMD у вершины может быть только один UV);
* **границы** (открытые края, разрезы, стыки материалов) — к ним добавляются
  «штрафные» квадратики, чтобы силуэт не поплыл;
* **кости** — сначала схлопываются только рёбра внутри одной кости, поэтому
  веса и поза скелета остаются жёсткими; переход через сустав разрешается
  только на последнем этапе (``--no-bone-cross`` выключает и его).

Уровни детализации (число треугольников; в GoldSrc «полигон» = треугольник):

===  ==============  =====================================================
1    5 000           лёгкий, как стандартные модели игроков CS 1.6
2    10 000          средний, компромисс детализации и веса
3    20 000          высокий, нужен только для тяжёлых исходников
4    40 000          очень высокий, движку GoldSrc обычно не нужен
5    50 000          максимум; лёгкий исходник останется без изменений
===  ==============  =====================================================

Число в уровне — это **предел**: если исходник легче, ретопология не делается
(растягивать сетку вверх бессмысленно: файл только вырастет).

Запуск
------
    python3 Tools/goldsrc/retopo.py               # меню 1-5, затем сборка .mdl
    python3 Tools/goldsrc/retopo.py --level 1     # без вопросов
    python3 Tools/goldsrc/retopo.py --level 1 --no-compile
    python3 Tools/goldsrc/retopo.py --tris 7000   # свой предел
    python3 Tools/goldsrc/retopo.py --psk Models/Bodies/Other.psk --level 2

Результат — в ``Build/goldsrc/level<N>/``: ``mdl/``, ``smd/``, ``textures/``,
``preview/`` (три PNG-ракурса без движка, см. ``inspect_mdl.py``) и
``report.txt`` со статистикой.
"""

from __future__ import annotations

import argparse
import heapq
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# --------------------------------------------------------------- уровни

LEVELS = (
    (1, 5000, "лёгкий        — как стандартные модели игроков CS 1.6"),
    (2, 10000, "средний       — компромисс детализации и веса файла"),
    (3, 20000, "высокий       — нужен только для тяжёлых исходников"),
    (4, 40000, "очень высокий — движку GoldSrc обычно не нужен"),
    (5, 50000, "максимум      — потолок; лёгкий исходник останется как есть"),
)

LEVEL_TRIS = {lv: tris for lv, tris, _ in LEVELS}

#: сколько треугольников минимум должно остаться в каждом UV-острове
MIN_CHART_TRIS = 4
MIN_CHART_SHARE = 0.12
#: какую долю исходной площади UV-острова нужно сохранить
MIN_CHART_AREA = 0.55


def describe(level: int) -> str:
    for lv, tris, text in LEVELS:
        if lv == level:
            return f"{level} = {tris} треугольников ({text})"
    raise ValueError(f"нет уровня {level}")


def print_menu(source_tris=None, stream=sys.stdout):
    print("Ретопология модели игрока для CS 1.6 / GoldSrc", file=stream)
    print("Уровень детализации (предел числа треугольников):", file=stream)
    for lv, tris, text in LEVELS:
        print(f"  {lv})  {tris:>5}  {text}", file=stream)
    if source_tris:
        print("", file=stream)
        print(f"Исходный меш: {source_tris} треугольников.", file=stream)
        levels = [lv for lv, tris, _ in LEVELS if tris < source_tris]
        if not levels:
            print("  Он легче любого уровня — ретопология ничего не изменит.",
                  file=stream)
        else:
            print("  Реально уменьшат модель уровни: " +
                  ", ".join(f"{lv} (<{LEVEL_TRIS[lv]})" for lv in levels),
                  file=stream)
            rest = [lv for lv, tris, _ in LEVELS if tris >= source_tris]
            if rest:
                print("  Уровни " + ", ".join(map(str, rest)) +
                      " выше исходника — модель останется как есть.",
                      file=stream)
    print("", file=stream)


def ask_level(source_tris=None) -> int:
    """Спрашивает уровень 1-5 в консоли. Без ввода — уровень 1."""
    print_menu(source_tris)
    while True:
        try:
            answer = input("Введите номер уровня [1-5]: ").strip()
        except EOFError:
            print("\nнет ответа — беру уровень 1")
            return 1
        if not answer:
            continue
        if answer.lower() in ("q", "quit", "exit", "0"):
            raise SystemExit("отменено")
        if not answer.isdigit() or int(answer) not in LEVEL_TRIS:
            print("  нужно число от 1 до 5 (или q для выхода)")
            continue
        return int(answer)


# ------------------------------------------------------------ геометрия

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _face_area_normal(p0, p1, p2):
    """Площадь и единичная нормаль треугольника (для квадратиков QEM)."""
    n = _cross(_sub(p1, p0), _sub(p2, p0))
    ln = math.sqrt(_dot(n, n))
    if ln < 1e-12:
        return 0.0, (0.0, 0.0, 0.0)
    return 0.5 * ln, (n[0] / ln, n[1] / ln, n[2] / ln)


def _quadric(nx, ny, nz, d, w):
    """Квадратик плоскости (n, d) с весом w — 10 значимых элементов 4x4."""
    return [w * nx * nx, w * nx * ny, w * nx * nz, w * nx * d,
            w * ny * ny, w * ny * nz, w * ny * d,
            w * nz * nz, w * nz * d,
            w * d * d]


def _quadric_err(q, p):
    x, y, z = p
    return (q[0] * x * x + 2.0 * q[1] * x * y + 2.0 * q[2] * x * z
            + 2.0 * q[3] * x + q[4] * y * y + 2.0 * q[5] * y * z
            + 2.0 * q[6] * y + q[7] * z * z + 2.0 * q[8] * z + q[9])


def _solve3(r0, r1, r2, b):
    """Решение 3x3 методом Крамера; None, если матрица вырождена."""
    def det3(c0, c1, c2):
        return (c0[0] * (c1[1] * c2[2] - c1[2] * c2[1])
                - c0[1] * (c1[0] * c2[2] - c1[2] * c2[0])
                + c0[2] * (c1[0] * c2[1] - c1[1] * c2[0]))

    det = det3(r0, r1, r2)
    if abs(det) < 1e-14:
        return None
    x = det3((b[0], r0[1], r0[2]), (b[1], r1[1], r1[2]), (b[2], r2[1], r2[2])) / det
    y = det3((r0[0], b[0], r0[2]), (r1[0], b[1], r1[2]), (r2[0], b[2], r2[2])) / det
    z = det3((r0[0], r0[1], b[0]), (r1[0], r1[1], b[1]), (r2[0], r2[1], b[2])) / det
    return (x, y, z)


# ------------------------------------------------------------ сварка меша

class _UnionFind:
    __slots__ = ("parent",)

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, a):
        p = self.parent
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


class Welded:
    """Меш PSK, склеенный по (позиция, материал), с UV-островами.

    * ``pos``/``vmat`` — позиция и материал сварной вершины;
    * ``vbone`` — доминирующая кость вершины;
    * ``vchart`` — главный UV-остров; ``vcharts`` — {остров: [u, v, вес]};
    * ``faces``/``fmat``/``fchart`` — треугольники и их принадлежность;
    * ``skipped`` — сколько треугольников выродилось при сварке.
    """

    __slots__ = ("pos", "vmat", "vbone", "vchart", "vcharts",
                 "faces", "fmat", "fchart", "ncharts", "skipped")

    def seam_count(self):
        n = 0
        for f, c in zip(self.faces, self.fchart):
            for x, y in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                if self.vchart[x] != self.vchart[y]:
                    n += 1
        return n


def _weld(mesh) -> Welded:
    """Склеивает веджи PSK в вершины и считает UV-острова.

    В PSK (ActorX) UV хранится на ведже, а не на точке, поэтому вершина
    однозначна только вместе с материалом; UV-остров определяется связностью
    треугольников с совпадающими UV вдоль общих рёбер.
    """
    w = Welded()
    nwedge = len(mesh.wedge_point)

    # --- вершины по (позиция, материал)
    key = {}
    wedge2v = [0] * nwedge
    pos_of, mat_of = [], []
    for i, pt in enumerate(mesh.wedge_point):
        p = mesh.points[pt]
        k = (round(p[0], 3), round(p[1], 3), round(p[2], 3), mesh.wedge_material[i])
        v = key.get(k)
        if v is None:
            v = len(pos_of)
            key[k] = v
            pos_of.append((p[0], p[1], p[2]))
            mat_of.append(mesh.wedge_material[i])
        wedge2v[i] = v

    # --- UV-острова: union-find по веджам
    uf = _UnionFind(nwedge)
    for f in mesh.faces:                        # внутри треугольника всё связно
        uf.union(f[0], f[1])
        uf.union(f[1], f[2])

    posid = {}
    pid_of = [0] * nwedge
    for i, pt in enumerate(mesh.wedge_point):
        p = mesh.points[pt]
        k = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
        pid_of[i] = posid.setdefault(k, len(posid))

    edges = {}
    for f in mesh.faces:
        mat = mesh.wedge_material[f[0]]
        a, b, c = f
        for (x, y) in ((a, b), (b, c), (c, a)):
            kx, ky = pid_of[x], pid_of[y]
            if kx == ky:                        # сварка уже свела их в одну точку
                continue
            if kx > ky:
                kx, ky, x, y = ky, kx, y, x
            edges.setdefault((kx, ky, mat), []).append((x, y))

    for lst in edges.values():
        if len(lst) < 2:
            continue
        x0, y0 = lst[0]
        u0, v0 = mesh.wedge_uv[x0], mesh.wedge_uv[y0]
        for x1, y1 in lst[1:]:
            u1, v1 = mesh.wedge_uv[x1], mesh.wedge_uv[y1]
            if (abs(u0[0] - u1[0]) < 1e-4 and abs(u0[1] - u1[1]) < 1e-4
                    and abs(v0[0] - v1[0]) < 1e-4 and abs(v0[1] - v1[1]) < 1e-4):
                uf.union(x0, x1)
                uf.union(y0, y1)

    chart_of = [0] * nwedge
    remap = {}
    for i in range(nwedge):
        chart_of[i] = remap.setdefault(uf.find(i), len(remap))

    # --- UV по (вершина, остров)
    nv = len(pos_of)
    acc = [{} for _ in range(nv)]               # chart -> [u, v, count]
    for i in range(nwedge):
        d = acc[wedge2v[i]]
        c = chart_of[i]
        u, v = mesh.wedge_uv[i]
        t = d.get(c)
        if t is None:
            d[c] = [u, v, 1]
        else:
            t[0] += u
            t[1] += v
            t[2] += 1

    vchart, vcharts = [], []
    for d in acc:
        vchart.append(max(d.items(), key=lambda kv: kv[1][2])[0])
        vcharts.append(d)

    # --- кость вершины: сумма весов всех веджей, попавших в неё
    pw = {}
    for weight, pt, bone in mesh.weights:
        if weight <= 0.0:
            continue
        d = pw.setdefault(pt, {})
        d[bone] = d.get(bone, 0.0) + weight
    vw = [dict() for _ in range(nv)]
    for i, pt in enumerate(mesh.wedge_point):
        d = vw[wedge2v[i]]
        for bone, weight in pw.get(pt, {}).items():
            d[bone] = d.get(bone, 0.0) + weight
    vbone = []
    for d in vw:
        vbone.append(max(d.items(), key=lambda kv: kv[1])[0] if d else 0)

    # --- треугольники
    faces, fmat, fchart = [], [], []
    skipped = 0
    for f in mesh.faces:
        a, b, c = wedge2v[f[0]], wedge2v[f[1]], wedge2v[f[2]]
        if a == b or b == c or a == c:
            skipped += 1
            continue
        faces.append((a, b, c))
        fmat.append(mesh.wedge_material[f[0]])
        fchart.append(chart_of[f[0]])

    w.pos, w.vmat, w.vbone = pos_of, mat_of, vbone
    w.vchart, w.vcharts, w.ncharts = vchart, vcharts, len(remap)
    w.faces, w.fmat, w.fchart = faces, fmat, fchart
    w.skipped = skipped
    return w


# --------------------------------------------------------- схлопывание

class Collapser:
    """QEM-схлопывание рёбер с ограничениями (материалы/швы/кости)."""

    #: этапы: жёсткий, +UV-швы, +суставы, +послабление UV-плотности
    #: ``uv_keep`` — какую долю UV-площади треугольника можно потерять при
    #: перевешивании вершины, ``texel`` — во сколько раз может измениться
    #: плотность текселей (3D-площадь / UV-площадь) у соседних треугольников.
    #: ``uv_keep`` — какую долю UV-площади треугольника можно потерять при
    #: перевешивании вершины, ``texel`` — во сколько раз может измениться
    #: плотность текселей (площадь 3D / площадь UV) у соседних треугольников,
    #: ``grow`` — во сколько раз может вырасти 3D-площадь треугольника
    #: относительно исходной (иначе маленький треугольник растянет текстуру).
    texture_texels = 512.0   # размер атласа, в текселях

    MODES = (
        ("жёсткий (внутри кости и UV-острова)",
         dict(seam=False, bone=False, texel=4.0, grow=8.0, normal=True)),
        ("с UV-швами",
         dict(seam=True, bone=False, texel=4.0, grow=8.0, normal=True)),
        ("с суставами",
         dict(seam=True, bone=True, texel=4.0, grow=8.0, normal=True)),
        ("с послаблением UV-плотности",
         dict(seam=True, bone=True, texel=16.0, grow=20.0, normal=True)),
    )

    def __init__(self, w: Welded, allow_seam=True, allow_bone=True,
                 lock_bones=(), modes=None):
        self.pos = [list(p) for p in w.pos]
        self.vmat = list(w.vmat)
        self.vbone = list(w.vbone)
        self.vchart = list(w.vchart)
        self.vcharts = [dict((c, list(t)) for c, t in d.items())
                        for d in w.vcharts]
        self.faces = [list(f) for f in w.faces]
        self.fmat = list(w.fmat)
        self.fchart = list(w.fchart)
        self.nv = len(self.pos)
        self.bw = [{w.vbone[v]: 1.0} for v in range(self.nv)]

        self.falive = bytearray([1]) * len(self.faces)
        self.dead = bytearray([0]) * self.nv
        self.ver = [0] * self.nv
        self.vf = [set() for _ in range(self.nv)]
        for fi, f in enumerate(self.faces):
            for v in f:
                self.vf[v].add(fi)
        self.face_count = len(self.faces)

        self.lock_bones = set(lock_bones or ())
        if not allow_seam:
            modes = Collapser.MODES[:1]
        elif not allow_bone:
            modes = Collapser.MODES[:2]
        self.modes = list(modes or Collapser.MODES)

        # треугольник мельче одного тексела атласа в UV уже вырожден: такие
        # есть в исходнике (тонкие слайверы), охранять их площадь бессмысленно
        self.min_texel_area = 1.0 / max(self.texture_texels ** 2, 1.0)

        self._init_face_measures()
        self._analyze_charts(w.ncharts)
        self._init_quadrics()
        self._init_penalties()
        self.heap = []

    def _init_face_measures(self):
        """Площади треугольников: UV (не меняются) и 3D (меняются)."""
        self.uv_area = [0.0] * len(self.faces)
        self.a3d0 = [0.0] * len(self.faces)
        for fi, f in enumerate(self.faces):
            (u0, v0), (u1, v1), (u2, v2) = self._face_uv(f, self.fchart[fi])
            self.uv_area[fi] = abs((u1 - u0) * (v2 - v0)
                                   - (u2 - u0) * (v1 - v0)) * 0.5
            self.a3d0[fi] = _face_area_normal(self.pos[f[0]], self.pos[f[1]],
                                              self.pos[f[2]])[0]

    def _analyze_charts(self, ncharts):
        """Статистика UV-островов: рамки, площади, «гармошки», защита.

        Некоторые острова (ремень, кант, воротник) состоят из нескольких
        полос внутри одной UV-рамки. Если их схлопывать, полосы сходятся
        друг с другом и остров исчезает целиком — на модели появляется
        дырка. Такие острова помечаем защищёнными и не трогаем.
        """
        self.chart_area0, self.chart_tris0 = {}, {}
        for fi, c in enumerate(self.fchart):
            self.chart_area0[c] = self.chart_area0.get(c, 0.0) + self.a3d0[fi]
            self.chart_tris0[c] = self.chart_tris0.get(c, 0) + 1
        self.chart_alive = dict(self.chart_tris0)
        self.chart_area_live = dict(self.chart_area0)

        self.uv_bbox = [None] * ncharts
        for ci in range(ncharts):
            xs, ys = [], []
            for d in self.vcharts:
                t = d.get(ci)
                if t:
                    xs.append(t[0] / t[2])
                    ys.append(t[1] / t[2])
            if xs:
                self.uv_bbox[ci] = (min(xs), min(ys), max(xs), max(ys))

        # медианы по островам — точка отсчёта для «аномальных» островов
        dens, tri_dens = [], []
        for ci, box in enumerate(self.uv_bbox):
            if box is None:
                continue
            a_uv = (box[2] - box[0]) * (box[3] - box[1])
            if a_uv <= 1e-9:
                continue
            dens.append(self.chart_area0[ci] / a_uv)
            tri_dens.append(self.chart_tris0[ci] / a_uv)
        dens.sort()
        tri_dens.sort()
        self._median_density_cache = dens[len(dens) // 2] if dens else 1.0
        med_tri = tri_dens[len(tri_dens) // 2] if tri_dens else 1.0

        self.protected_charts = set()
        for ci, box in enumerate(self.uv_bbox):
            if box is None or self.chart_tris0.get(ci, 0) < 4:
                continue
            a_uv = (box[2] - box[0]) * (box[3] - box[1])
            if a_uv <= 1e-9:
                continue
            # мало 3D-площади на единицу UV (полоса, обёрнутая вокруг тела)
            # или аномально плотная сетка (несколько полос в одной рамке)
            if (self.chart_area0[ci] / a_uv < 0.45 * self._median_density()
                    or self.chart_tris0[ci] / a_uv > 2.5 * med_tri):
                self.protected_charts.add(ci)

    # ------------------------------------------------------------ квадратики

    def _median_density(self):
        """Типичная плотность: 3D-площадь на единицу площади UV-рамки."""
        return self._median_density_cache

    def _init_quadrics(self):
        nv = self.nv
        self.q = [[0.0] * 10 for _ in range(nv)]
        for f in self.faces:
            p0, p1, p2 = self.pos[f[0]], self.pos[f[1]], self.pos[f[2]]
            area, nrm = _face_area_normal(p0, p1, p2)
            if area <= 1e-12:
                continue
            d = -_dot(nrm, p0)
            q = _quadric(nrm[0], nrm[1], nrm[2], d, area)
            for v in f:
                qv = self.q[v]
                for i in range(10):
                    qv[i] += q[i]

        # границы: рёбра, встречающиеся один раз -> «стенка» вдоль ребра
        ecount = {}
        for f in self.faces:
            for x, y in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                k = (x, y) if x < y else (y, x)
                ecount[k] = ecount.get(k, 0) + 1
        for (x, y), cnt in ecount.items():
            if cnt != 1:
                continue
            fi = None
            for cand in self.vf[x]:
                if y in self.faces[cand]:
                    fi = cand
                    break
            if fi is None:
                continue
            p0, p1 = self.pos[x], self.pos[y]
            third = next((v for v in self.faces[fi] if v != x and v != y), None)
            if third is None:
                continue
            area, nrm = _face_area_normal(p0, p1, self.pos[third])
            if area <= 1e-12:
                continue
            ed = _norm(_sub(p1, p0))
            m = _norm(_cross(nrm, ed))
            if _dot(m, m) < 0.5:
                continue
            d = -_dot(m, p0)
            length = math.sqrt(_dot(_sub(p1, p0), _sub(p1, p0)))
            q = _quadric(m[0], m[1], m[2], d, 4.0 * length * max(area, 1e-6))
            for v in (x, y):
                qv = self.q[v]
                for i in range(10):
                    qv[i] += q[i]

    def _init_penalties(self):
        """Штрафы за шов/сустав — в масштабе типичной стоимости ребра."""
        costs = []
        for f in self.faces:
            for x, y in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                if x > y:
                    continue
                q = [self.q[x][i] + self.q[y][i] for i in range(10)]
                costs.append(_quadric_err(q, self.pos[x]))
        costs.sort()
        scale = costs[len(costs) // 2] if costs else 1.0
        if scale <= 0.0:
            scale = max(1e-6, sum(costs) / len(costs) if costs else 1.0)
        self.pen_seam = 8.0 * scale
        self.pen_bone = 40.0 * scale

    # ------------------------------------------------------------- утилиты

    def _uv_of(self, v, chart):
        d = self.vcharts[v]
        t = d.get(chart)
        if t is None:
            t = d.get(self.vchart[v])
            if t is None:
                return (0.0, 0.0)
        return (t[0] / t[2], t[1] / t[2])

    def _face_uv(self, f, chart):
        return (self._uv_of(f[0], chart), self._uv_of(f[1], chart),
                self._uv_of(f[2], chart))

    def _nbrs(self, v):
        out = set()
        for fi in self.vf[v]:
            for x in self.faces[fi]:
                if x != v:
                    out.add(x)
        return out

    def _edge_faces(self, u, v):
        return sum(1 for fi in self.vf[u] if v in self.faces[fi])

    def _edge_cost(self, survivor, removed, mode):
        """Стоимость схлопывания removed -> survivor (вершина не двигается).

        Позиция вершины не меняется — это ключ к аккуратной текстуре: UV и
        нормали остаются там, где их разложил художник, а «оптимальная» точка
        QEM уводила бы вершину с шва и размазывала текстуру.
        """
        pen = self._penalty(survivor, removed, mode)
        if pen is None:
            return None
        q = [self.q[survivor][i] + self.q[removed][i] for i in range(10)]
        p = self.pos[survivor]
        return _quadric_err(q, p) + pen, (p[0], p[1], p[2])

    def _penalty(self, u, v, mode):
        """None — ребро запрещено на этом этапе, иначе штраф к стоимости."""
        if self.vmat[u] != self.vmat[v]:
            return None
        # острова-«гармошки» не трогаем: они складываются и исчезают целиком
        if (self.vchart[u] == self.vchart[v]
                and self.vchart[u] in self.protected_charts):
            return None

        # ни один UV-остров не должен «съесть» себя целиком: тонкие полосы
        # (ремень, кант, боковые вставки) при этом превращаются в дырки
        if self._chart_starved(u, v) or self._chart_thin(u, v):
            return None
        pen = 0.0
        if self.vchart[u] != self.vchart[v]:
            if not mode["seam"]:
                return None
            pen += self.pen_seam
        if self.vbone[u] != self.vbone[v]:
            if not mode["bone"]:
                return None
            if self.vbone[u] in self.lock_bones or self.vbone[v] in self.lock_bones:
                return None
            pen += self.pen_bone
        return pen

    def _chart_thin(self, u, v):
        """Остров стал слишком «тонким»: на единицу площади много треугольников.

        Так выглядит лоскут, который соседи съедают по краям: он сплющивается
        и в кадре превращается в дырку. Поэтому такие острова не трогаем,
        когда плотность превысила исходную в 2.5 раза.
        """
        for c in {self.fchart[fi] for fi in self.vf[v]}:
            a0, n0 = self.chart_area0.get(c, 0.0), self.chart_tris0.get(c, 0)
            if a0 <= 1e-9 or n0 < 8:
                continue
            alive = self.chart_alive.get(c, 0)
            area = self.chart_area_live.get(c, 0.0)
            if alive <= 0 or area <= 1e-9:
                continue
            if (alive / area) > 2.5 * (n0 / a0):
                return True
        return False

    def _chart_starved(self, u, v):
        """True, если схлопывание оголит UV-остров (дырка в модели).

        Следим за двумя вещами: число треугольников острова не падает ниже
        минимума, а его площадь в 3D не уменьшается больше допустимого —
        иначе лоскут «съедается» соседями и на модели появляется провал.
        """
        dying_n = {}
        dying_area = {}
        for fi in self.vf[v]:
            c = self.fchart[fi]
            if u in self.faces[fi]:
                dying_n[c] = dying_n.get(c, 0) + 1
                dying_area[c] = dying_area.get(c, 0.0) + self.a3d0[fi]
            else:
                # треугольник переедет: его площадь тоже изменится
                a_new = self._area_after(fi, u, v)
                dying_area[c] = dying_area.get(c, 0.0) + (self.a3d0[fi] - a_new)
        for c, n in dying_n.items():
            keep = max(MIN_CHART_TRIS, int(round(self.chart_tris0.get(c, 0) * MIN_CHART_SHARE)))
            if self.chart_alive.get(c, 0) - n < keep:
                return True
        for c, d in dying_area.items():
            if d <= 0.0:
                continue
            floor = self.chart_area0.get(c, 0.0) * MIN_CHART_AREA
            if self.chart_area_live.get(c, 0.0) - d < floor:
                return True
        return False

    def _cost(self, u, v, mode):
        """Стоимость ребра; возвращает (цена, куда встанет вершина)."""
        return self._edge_cost(u, v, mode)

    # -------------------------------------------------------------- очередь

    def _rebuild_heap(self, mode):
        self.heap = []
        seen = set()
        for f in self.faces:
            for x, y in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                k = (x, y) if x < y else (y, x)
                if k in seen:
                    continue
                seen.add(k)
                self._push(k[0], k[1], mode)
                self._push(k[1], k[0], mode)

    def _push(self, u, v, mode):
        """Кладёт в кучу схлопывание v -> u (u остаётся на месте)."""
        if self.dead[u] or self.dead[v]:
            return
        r = self._cost(u, v, mode)
        if r is None:
            return
        heapq.heappush(self.heap, (r[0], u, v, self.ver[u], self.ver[v]))

    # -------------------------------------------------------------- проверки

    def _link_ok(self, u, v):
        """Условие Дейка: схлопывание не рвёт топологию (нет «бутылок»)."""
        common = self._nbrs(u) & self._nbrs(v)
        need = 1 if self._edge_faces(u, v) == 1 else 2
        return len(common) == need

    def _area_after(self, fi, u, v):
        """3D-площадь треугольника fi после замены вершины v на u."""
        f = self.faces[fi]
        pts = [self.pos[u] if x == v else self.pos[x] for x in f]
        return _face_area_normal(pts[0], pts[1], pts[2])[0]

    def _uv_areas_after(self, u, v):
        """UV-площади треугольников вокруг v до/после замены v на u.

        Возвращает (индекс, площадь до, площадь после, есть_ли_UV): последний
        флаг — есть ли у вершины u UV в острове этого треугольника. Подменять
        UV чужим островом нельзя: угол уедет на другую часть атласа.
        """
        out = []
        for fi in self.vf[v]:
            f = self.faces[fi]
            chart = self.fchart[fi]
            uv = self._face_uv(f, chart)
            a_old = abs((uv[1][0] - uv[0][0]) * (uv[2][1] - uv[0][1])
                        - (uv[2][0] - uv[0][0]) * (uv[1][1] - uv[0][1])) * 0.5
            if chart not in self.vcharts[u]:
                out.append((fi, a_old, 0.0, False))
                continue
            uu, uv_ = self._uv_of(u, chart)
            pts = [(self._uv_of(x, chart) if x != v else (uu, uv_)) for x in f]
            a_new = abs((pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1])
                        - (pts[2][0] - pts[0][0]) * (pts[1][1] - pts[0][1])) * 0.5
            out.append((fi, a_old, a_new, True))
        return out

    def _flip_ok(self, u, v, mode):
        """Проверки формы и текстуры перед схлопыванием v -> u.

        Вершина u остаётся на месте, поэтому меняются только треугольники
        вокруг v; их и проверяем:

        * не выворачиваются и не вырождаются в линию;
        * их площадь не растёт в разы (иначе мелкий треугольник растянет UV);
        * плотность текселей (площадь 3D / площадь UV) не уезжает больше чем
          в ``texel`` раз от исходной — это и есть «текстура не поехала»;
        * у u есть UV в острове каждого такого треугольника.
        """
        texel = mode["texel"]
        check_normals = mode.get("normal", True)
        self.last_reject = None

        for fi in self.vf[v]:
            f = self.faces[fi]
            if u in f:
                continue                        # треугольник схлопывается
            a, b, c = f
            pa = self.pos[u] if a == v else self.pos[a]
            pb = self.pos[u] if b == v else self.pos[b]
            pc = self.pos[u] if c == v else self.pos[c]
            n_old = _cross(_sub(self.pos[b], self.pos[a]),
                           _sub(self.pos[c], self.pos[a]))
            n_new = _cross(_sub(pb, pa), _sub(pc, pa))
            lo, ln = _dot(n_old, n_old), _dot(n_new, n_new)
            if lo < 1e-12:
                continue                        # вырожден ещё в исходнике
            if ln < 1e-12:
                if check_normals:
                    self.last_reject = ("degen", fi)
                    return False
                continue
            if check_normals and _dot(n_old, n_new) < 0.35 * math.sqrt(lo * ln):
                self.last_reject = ("flip", fi)
                return False                    # выворот

            # раздувание площади — всегда, даже на самом мягком этапе:
            # иначе треугольники вытягиваются в длинные шипы
            a0 = self.a3d0[fi]
            if a0 > 1e-12 and ln > (a0 * 2.0 * mode["grow"]) ** 2:
                self.last_reject = ("grow", fi)
                return False

            uv_a = self.uv_area[fi]
            a0 = self.a3d0[fi]
            if uv_a <= 1e-12 or a0 <= 1e-12:
                continue
            if uv_a < self.min_texel_area:
                continue                        # субтексельный слайвер
            r0 = math.sqrt(a0 * 0.5 / uv_a)
            r_new = math.sqrt(ln * 0.5 / uv_a)
            if r_new > r0 * texel or r_new * texel * 4.0 < r0:
                self.last_reject = ("texel", fi)
                return False

        # защищённый остров не должен потерять все треугольники вокруг v
        if self.vchart[v] in self.protected_charts and self.vchart[u] == self.vchart[v]:
            alive = sum(1 for fi in self.vf[v] if self.fchart[fi] == self.vchart[v])
            if alive <= 1:
                return False

        # текстура: UV-площадь и плотность после замены v на u
        for fi, a_old, a_new, has_uv in self._uv_areas_after(u, v):
            # Слайвер-треугольники (UV-площадь меньше ~одного тексела) не
            # охраняем по площади: на текстуре они занимают меньше пикселя и
            # видны только как случайный шум. Но не даём им «проснуться»
            # большими — это проверяется ниже по росту 3D-площади.
            if a_old < self.min_texel_area:
                f = self.faces[fi]
                a3_now = _face_area_normal(*[self.pos[x] for x in f])[0]
                if a3_now > 1e-12:
                    a3_new = self._area_after(fi, u, v)
                    if a3_new > a3_now * mode["grow"]:
                        return False
                continue
            if not has_uv:
                return False                    # у u нет UV этого острова
            f = self.faces[fi]
            a3_now = _face_area_normal(self.pos[f[0]], self.pos[f[1]],
                                       self.pos[f[2]])[0]
            a3_new = self._area_after(fi, u, v)
            if a3_now <= 1e-12:
                continue
            if a_new <= 1e-12:
                # UV-треугольник выродился в линию: допустимо только если и
                # 3D-треугольник схлопнулся (а не стал видимой полосой)
                if a3_new > self.a3d0[fi] * 1e-3:
                    self.last_reject = ("uv_line", fi)
                    return False
                continue
            r0 = self.a3d0[fi] / a_old
            r_new = max(a3_new, 1e-9) / a_new
            if r_new > r0 * texel or r_new * texel * 4.0 < r0:
                self.last_reject = ("uv_texel", fi)
                return False
        return True

    # ------------------------------------------------------------- коллапс

    def _collapse(self, u, v, p):
        # u остаётся на месте (схлопывание «в существующую вершину»):
        # p — это ровно позиция u, менять её нельзя, иначе UV/нормали поедут
        for i in range(10):
            self.q[u][i] += self.q[v][i]

        bu = self.bw[u]
        for b, wt in self.bw[v].items():
            bu[b] = bu.get(b, 0.0) + wt
        self.vbone[u] = max(bu.items(), key=lambda kv: kv[1])[0]

        for c, t in self.vcharts[v].items():
            if c not in self.vcharts[u]:
                self.vcharts[u][c] = list(t)

        for fi in list(self.vf[v]):
            f = self.faces[fi]
            self.vf[v].discard(fi)
            if u in f:                          # треугольник схлопнулся
                self.falive[fi] = 0
                self.face_count -= 1
                c = self.fchart[fi]
                self.chart_alive[c] = self.chart_alive.get(c, 1) - 1
                self.chart_area_live[c] = (self.chart_area_live.get(c, 0.0)
                                          - self.a3d0[fi])
                for x in f:
                    self.vf[x].discard(fi)
            else:                               # перевешиваем на u
                self.faces[fi] = [u if x == v else x for x in f]
                self.vf[u].add(fi)

        self.dead[v] = 1
        self.ver[u] += 1
        self.ver[v] += 1

    def run(self, target, report=print):
        """Схлопывает рёбра до ``target`` треугольников (или до упора)."""
        for label, mode in self.modes:
            start = self.face_count
            self._rebuild_heap(mode)
            while self.face_count > target and self.heap:
                cost, u, v, tu, tv = heapq.heappop(self.heap)
                if self.dead[u] or self.dead[v]:
                    continue
                if self.ver[u] != tu or self.ver[v] != tv:
                    continue
                r = self._cost(u, v, mode)
                if r is None:
                    continue
                c, p = r
                if c > cost + 1e-12:            # сосед сдвинулся — пересчёт
                    heapq.heappush(self.heap, (c, u, v, self.ver[u],
                                               self.ver[v]))
                    continue
                if not self._link_ok(u, v):
                    continue
                if not self._flip_ok(u, v, mode):
                    continue
                self._collapse(u, v, p)
                for w in self._nbrs(u):
                    self._push(u, w, mode)
                    self._push(w, u, mode)
            report(f"      этап «{label}»: {start} -> {self.face_count}")
            if self.face_count <= target:
                return self.face_count
        return self.face_count


# ------------------------------------------------------------- сборка выхода

def _uv_for(coll, v, chart, miss=None):
    """UV вершины v в острове chart; если остров потерян — главный UV."""
    d = coll.vcharts[v]
    t = d.get(chart)
    if t is None:
        if miss is not None:
            miss[0] += 1
        t = d.get(coll.vchart[v])
        if t is None:
            return (0.0, 0.0)
    return (t[0] / t[2], t[1] / t[2])


def _make_mesh(mesh, coll):
    """Собирает объект, совместимый с PskMesh, из схлопнутого меша.

    Вершина раздваивается по UV-островам: в SMD у вершины один UV, поэтому
    треугольники из разных островов получают каждый свою копию.
    """
    from psk import PskMesh

    out = PskMesh()
    out.materials = mesh.materials
    out.bones = mesh.bones
    key = {}
    pts, uvs, mats, bones = [], [], [], []
    seen_face = set()
    faces, fmat = [], []
    dup = 0
    miss = [0]
    for fi, f in enumerate(coll.faces):
        if not coll.falive[fi]:
            continue
        a, b, c = f
        sig = tuple(sorted((a, b, c)))
        if sig in seen_face:                    # совпал после схлопывания
            dup += 1
            continue
        seen_face.add(sig)
        chart = coll.fchart[fi]
        tri = []
        for x in (a, b, c):
            k = (x, chart)
            idx = key.get(k)
            if idx is None:
                idx = len(pts)
                key[k] = idx
                pts.append(tuple(coll.pos[x]))
                uvs.append(_uv_for(coll, x, chart, miss))
                mats.append(coll.vmat[x])
                bones.append(coll.vbone[x])
            tri.append(idx)
        faces.append(tuple(tri))
        fmat.append(coll.fmat[fi])

    out.points = pts
    out.faces = faces
    out.wedge_point = list(range(len(pts)))
    out.wedge_uv = uvs
    out.wedge_material = mats
    out.weights = [(1.0, i, bones[i]) for i in range(len(pts))]

    # --- нормали: по итоговым треугольникам
    acc = [[0.0, 0.0, 0.0] for _ in pts]
    for (a, b, c) in faces:
        pa, pb, pc = pts[a], pts[b], pts[c]
        n = _cross(_sub(pb, pa), _sub(pc, pa))
        for i in (a, b, c):
            acc[i][0] += n[0]
            acc[i][1] += n[1]
            acc[i][2] += n[2]
    out.normals = [_norm(tuple(t)) for t in acc]
    # позиция в формате .mdl (доли юнита): удобно сверять и не тратить место
    out.pos_scale = 100.0
    return out, dup, miss[0]


# --------------------------------------------------- отклонение от исходника

def _dist_point_tri(p, a, b, c):
    """Кратчайшее расстояние от точки до треугольника (Ericson)."""
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return math.sqrt(_dot(ap, ap))
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return math.sqrt(_dot(bp, bp))
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 <= d1 and d3 <= 0.0:
        t = d1 / (d1 - d3)
        q = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
        d = _sub(p, q)
        return math.sqrt(_dot(d, d))
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return math.sqrt(_dot(cp, cp))
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 <= d2 and d6 <= 0.0:
        t = d2 / (d2 - d6)
        q = (a[0] + t * ac[0], a[1] + t * ac[1], a[2] + t * ac[2])
        d = _sub(p, q)
        return math.sqrt(_dot(d, d))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        q = (b[0] + t * (c[0] - b[0]), b[1] + t * (c[1] - b[1]),
             b[2] + t * (c[2] - b[2]))
        d = _sub(p, q)
        return math.sqrt(_dot(d, d))
    denom = 1.0 / (va + vb + vc)
    v, ww = vb * denom, vc * denom
    q = (a[0] + ab[0] * v + ac[0] * ww,
         a[1] + ab[1] * v + ac[1] * ww,
         a[2] + ab[2] * v + ac[2] * ww)
    d = _sub(p, q)
    return math.sqrt(_dot(d, d))


def surface_deviation(mesh, points, cell=8.0, limit=4000):
    """Среднее и максимальное отклонение новых вершин от исходной поверхности."""
    tris = []
    for f in mesh.faces:
        tris.append((mesh.points[mesh.wedge_point[f[0]]],
                     mesh.points[mesh.wedge_point[f[1]]],
                     mesh.points[mesh.wedge_point[f[2]]]))
    if not tris or not points:
        return (0.0, 0.0)

    grid = {}
    for ti, (a, b, c) in enumerate(tris):
        lo = [min(a[k], b[k], c[k]) for k in range(3)]
        hi = [max(a[k], b[k], c[k]) for k in range(3)]
        for ix in range(int(math.floor(lo[0] / cell)), int(math.floor(hi[0] / cell)) + 1):
            for iy in range(int(math.floor(lo[1] / cell)), int(math.floor(hi[1] / cell)) + 1):
                for iz in range(int(math.floor(lo[2] / cell)), int(math.floor(hi[2] / cell)) + 1):
                    grid.setdefault((ix, iy, iz), []).append(ti)

    sample = points
    if len(sample) > limit:
        step = len(sample) / float(limit)
        sample = [points[int(i * step)] for i in range(limit)]

    worst = 0.0
    total = 0.0
    for p in sample:
        c0 = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)),
              int(math.floor(p[2] / cell)))
        best = None
        for r in range(0, 4):
            cand = []
            for ix in range(c0[0] - r, c0[0] + r + 1):
                for iy in range(c0[1] - r, c0[1] + r + 1):
                    for iz in range(c0[2] - r, c0[2] + r + 1):
                        lst = grid.get((ix, iy, iz))
                        if lst:
                            cand.extend(lst)
            if cand:
                best = min(_dist_point_tri(p, *tris[ti]) for ti in cand)
                if best <= r * cell:
                    break
        if best is None:
            best = min(_dist_point_tri(p, *t) for t in tris[::4] or tris)
        total += best
        if best > worst:
            worst = best
    return total / len(sample), worst


# ----------------------------------------------------------- публичный API

def retopologize(mesh, target_tris, report=print, allow_seam=True,
                 allow_bone=True, lock_bones=(), check=True):
    """Возвращает (новый_меш, статистика).

    ``mesh`` — объект PskMesh. При ``target_tris >= len(mesh.faces)``
    возвращается исходный меш без изменений: растягивать сетку вверх
    бессмысленно, движку GoldSrc это ничего не даёт.
    """
    src_tris = len(mesh.faces)
    src_verts = len(mesh.points)
    stats = dict(src_tris=src_tris, src_verts=src_verts, target=target_tris,
                 tris=src_tris, verts=src_verts, mode="без изменений",
                 charts=0, deviation=None, dup=0)

    if target_tris <= 0:
        raise SystemExit("цель по треугольникам должна быть > 0")
    if src_tris <= target_tris:
        report(f"      исходник {src_tris} <= цели {target_tris}: "
               f"модель остаётся как есть")
        return mesh, stats

    report(f"      цель: {target_tris} треугольников "
           f"(из {src_tris}, это {100.0 * target_tris / src_tris:.0f}%)")

    w = _weld(mesh)
    report(f"      сварено вершин: {len(mesh.points)} -> {len(w.pos)}, "
           f"UV-островов: {w.ncharts}")
    if w.skipped:
        report(f"      вырожденных треугольников при сварке: {w.skipped}")

    coll = Collapser(w, allow_seam=allow_seam, allow_bone=allow_bone,
                     lock_bones=lock_bones)
    result = coll.run(target_tris, report=report)
    if result > target_tris:
        report(f"      до цели не добраться (жёсткие ограничения): "
               f"получилось {result}")

    out, dup, miss = _make_mesh(mesh, coll)
    if dup:
        report(f"      убрано совпавших треугольников: {dup}")
    if miss:
        report(f"      UV взяты из главного острова (потерян остров): {miss}")

    stats.update(tris=len(out.faces), verts=len(out.points), mode="QEM",
                 charts=w.ncharts, dup=dup, uv_miss=miss)
    if check:
        mean, worst = surface_deviation(mesh, out.points)
        stats["deviation"] = (mean, worst)
        report(f"      отклонение от исходной поверхности: "
               f"среднее {mean:.3f}, макс {worst:.3f} юнита")
    return out, stats


# ------------------------------------------------------------------- запуск

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="retopo.py",
        description="Ретопология модели игрока под CS 1.6 (уровни 1-5).",
    )
    ap.add_argument("--level", type=int, choices=[lv for lv, _, _ in LEVELS],
                    help="1=5000, 2=10000, 3=20000, 4=40000, 5=50000 треугольников")
    ap.add_argument("--tris", type=int, help="свой предел треугольников")
    ap.add_argument("--psk", help="исходный .psk (по умолчанию из репозитория)")
    ap.add_argument("--name", help="имя .mdl без расширения")
    ap.add_argument("--no-compile", action="store_true", help="не вызывать studiomdl")
    ap.add_argument("--texsize", type=int, help="размер BMP-текстур (512 по умолчанию)")
    ap.add_argument("--no-bone-cross", action="store_true",
                    help="не схлопывать через суставы (жёсткий скелет)")
    ap.add_argument("--no-seam-cross", action="store_true",
                    help="не схлопывать через UV-швы")
    ap.add_argument("--no-check", action="store_true",
                    help="не мерить отклонение (быстрее)")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="не спрашивать уровень, взять 1")
    args = ap.parse_args(argv)

    level = args.level
    if level is None and not args.tris:
        if args.yes:
            level = 1
        else:
            level = ask_level()

    forward = []
    if level:
        forward += ["--level", str(level)]
    if args.tris:
        forward += ["--tris", str(args.tris)]
    if args.psk:
        forward += ["--psk", args.psk]
    if args.name:
        forward += ["--name", args.name]
    if args.no_compile:
        forward += ["--no-compile"]
    if args.texsize:
        forward += ["--texsize", str(args.texsize)]
    if args.no_bone_cross:
        forward += ["--no-bone-cross"]
    if args.no_seam_cross:
        forward += ["--no-seam-cross"]
    if args.no_check:
        forward += ["--no-check"]

    import build
    return build.main(forward)


if __name__ == "__main__":
    raise SystemExit(main())
