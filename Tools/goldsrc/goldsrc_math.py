"""Общие математические хелперы. Только stdlib (без numpy).

PSK приходит из Unreal: X — вправо, Y — вперёд (лицо смотрит в -Y), Z — вверх.
GoldSrc/SMD ждёт X — вперёд, Y — влево, Z — вверх.

Замена базиса::

    (x, y, z)_gold = (x, z, -y)_ue

это чистый поворот (det = +1), то есть «развернуть модель на 90 градусов».
Именно так studiomdl и поступает по умолчанию (defaultzrotation = +90 градусов),
поэтому в QC мы явно ставим ``$rotate 0``.
"""

from __future__ import annotations

import math


def to_gold(vec):
    """Система координат SMD: X — вбок, Y — глубина (лицо в -Y), Z — вверх.

    Это та же система, в которой авторизованы штатные модели Half-Life
    (в player_template_biped_barney.smd высота лежит в Z, носки смотрят в -Y).
    Исходный PSK уже в ней: рост по Z (0…170), ширина по X (±59), глубина по Y
    (±19), носки в -Y. Поэтому пересчёт координат не нужен — только поворот
    ``$rotate`` на +90° при компиляции развернёт персонажа лицом в +X, как
    требует GoldSrc.

    (Раньше здесь было ``(x, z, -y)`` — это переводило рост в ось Y и валило
    модель на бок.)
    """
    return (vec[0], vec[1], vec[2])


def quat_to_matrix_xyzw(q):
    """Кватернион (x, y, z, w) -> матрица 3x3."""
    x, y, z, w = (float(v) for v in q)
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    s = 2.0 / n
    return [
        [1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
        [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
        [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)],
    ]


def matrix_to_quat_xyzw(m):
    """Матрица 3x3 -> кватернион (x, y, z, w) с w >= 0 (Шеппард)."""
    m00, m01, m02 = m[0]
    m10, m11, m12 = m[1]
    m20, m21, m22 = m[2]
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    if w < 0.0:
        x, y, z, w = -x, -y, -z, -w
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / n, y / n, z / n, w / n)


def angle_matrix(pitch, yaw, roll):
    """AngleMatrix() из mathlib Valve/движка GoldSrc — но в РАДИАНАХ.

    В mathlib.c studiomdl угол сначала переводится в градусы
    (``angle * (Q_PI*2/360)``), а SMD хранит радианы, поэтому итоговые синусы
    берутся от самих значений в радианах.

    Порядок элементов массива: [0] = pitch, [1] = yaw, [2] = roll
    (так же, как PITCH/YAW/ROLL в studiomdl.h и в движке).

    Матрица = Rz(roll) * Ry(yaw) * Rx(pitch); элементы [r][c] — строка r,
    столбец c (как float[3][4] из SDK), столбцы = оси forward/left/up.
    """
    sy, cy = math.sin(roll), math.cos(roll)      # angles[2]
    sp, cp = math.sin(yaw), math.cos(yaw)        # angles[1]
    sr, cr = math.sin(pitch), math.cos(pitch)    # angles[0]
    return [
        [cp * cy, sr * sp * cy + cr * -sy, cr * sp * cy + -sr * -sy],
        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy + -sr * cy],
        [-sp, sr * cp, cr * cp],
    ]


def matrix_to_angles(m):
    """Обратное к :func:`angle_matrix`. Возвращает (pitch, yaw, roll) в рад.

    В матрице AngleMatrix (строка r, столбец c)::

        m[2][0] = -sin(yaw)
        m[2][1] =  sin(pitch) * cos(yaw)
        m[2][2] =  cos(pitch) * cos(yaw)
        m[1][0] =  cos(yaw) * sin(roll)
        m[0][0] =  cos(yaw) * cos(roll)

    ``asin`` возвращает yaw в [-90°, 90°], поэтому cos(yaw) >= 0 и делить
    на него не нужно. При cos(yaw) == 0 (gimbal lock) две первые строки
    обнуляются: углы читаем из столбца 1, положив roll = 0.
    """
    sy = max(-1.0, min(1.0, -m[2][0]))
    yaw = math.asin(sy)
    cy = math.cos(yaw)
    if cy > 1e-5:
        pitch = math.atan2(m[2][1], m[2][2])
        roll = math.atan2(m[1][0], m[0][0])
    else:
        # m[0][1] = sin(pitch) * sin(yaw), m[1][1] = cos(pitch)  (roll = 0)
        pitch = math.atan2(m[0][1] / sy, m[1][1])
        roll = 0.0
    return (pitch, yaw, roll)


def normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(c / n for c in v)
