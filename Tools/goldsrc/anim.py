"""Анимации, хитбоксы и привязки для играбельной модели игрока CS 1.6.

GoldSrc выбирает позу игрока **по номеру последовательности**: в
``mstudioseqdesc_t`` лежат только имена, а движок (``CBasePlayer::GetSequence``
в game dll) обращается к ним по индексу. Поэтому у модели игрока должен быть
ровно тот же список из 111 последовательностей в том же порядке, что и у
стандартных моделей CS 1.6, иначе персонаж замирает в первой позе.

Порядок и параметры (fps, loop, ACT_*, события 5001/2001) здесь взяты из
официального ``player.qc`` Valve (Half-Life SDK / CS 1.6), а позы считаются
процедурно из нашего скелета: готовых анимаций для рига K29 взять негде, но
играбельной модель делает именно наличие всех последовательностей.

## Система координат

SMD (до ``$rotate +90`` при компиляции): **X** — влево персонажа, **Y** — назад
(лицо смотрит в −Y), **Z** — вверх. Углы ниже — в градусах по правилу правой
руки в этих осях:

* **X** — наклон вперёд (+) / назад (−);
* **Y** — наклон влево (+) / вправо (−);
* **Z** — поворот влево (+) / вправо (−).

## Как считается поза

Кость получает поворот ``D`` в мировых осях, который применяется поверх
родителя: ``W = W_parent * D``. Мировая ориентация ``R = W * R_bind``,
локальный угол для SMD ``L = R_parent^T * R``. Это обычный FK: «опустить
плечо на 70°» — один и тот же угол независимо от того, что делает корпус.
"""

from __future__ import annotations

import math

import smd
from goldsrc_math import angle_matrix, matrix_to_angles

# ---------------------------------------------------------------- скелет

#: Роли костей нашего рига (K29). Слева — роль, справа — имя кости в PSK.
ROLES = {
    "hips": "joint_HipMaster_01",
    "waist": "joint_TorsoA_01",
    "spine": "joint_TorsoB_01",
    "chest": "joint_TorsoC_01",
    "neck": "joint_NeckA_01",
    "head": "joint_Head_01",
    "jaw": "joint_Jaw_01",
    "clav_l": "joint_ClavicleLT_01",
    "clav_r": "joint_ClavicleRT_01",
    "arm_l": "joint_ShoulderLT_01",
    "arm_r": "joint_ShoulderRT_01",
    "fore_l": "joint_ElbowLT_01",
    "fore_r": "joint_ElbowRT_01",
    "hand_l": "joint_HandLT_01",
    "hand_r": "joint_HandRT_01",
    "thigh_l": "joint_HipLT_01",
    "thigh_r": "joint_HipRT_01",
    "calf_l": "joint_KneeLT_01",
    "calf_r": "joint_KneeRT_01",
    "foot_l": "joint_FootLT_01",
    "foot_r": "joint_FootRT_01",
    "toe_l": "joint_ToeLT_01",
    "toe_r": "joint_ToeRT_01",
}

FINGERS_R = [
    ["joint_ThumbART_01", "joint_ThumbBRT_01", "joint_ThumbCRT_01"],
    ["joint_IndexART_01", "joint_IndexBRT_01", "joint_IndexCRT_01", "joint_IndexDRT_01"],
    ["joint_FingerART_01", "joint_FingerBRT_01", "joint_FingerCRT_01", "joint_FingerDRT_01"],
    ["joint_RingART_01", "joint_RingBRT_01", "joint_RingCRT_01", "joint_RingDRT_01"],
    ["joint_PinkyART_01", "joint_PinkyBRT_01", "joint_PinkyCRT_01", "joint_PinkyDRT_01"],
]
FINGERS_L = [
    ["joint_ThumbALT_01", "joint_ThumbBLT_01", "joint_ThumbCLT_01"],
    ["joint_IndexALT_01", "joint_IndexBLT_01", "joint_IndexCLT_01", "joint_IndexDLT_01"],
    ["joint_FingerALT_01", "joint_FingerBLT_01", "joint_FingerCLT_01", "joint_FingerDLT_01"],
    ["joint_RingALT_01", "joint_RingBLT_01", "joint_RingCLT_01", "joint_RingDLT_01"],
    ["joint_PinkyALT_01", "joint_PinkyBLT_01", "joint_PinkyCLT_01", "joint_PinkyDLT_01"],
]

#: Группы попаданий CS 1.6 (те же, что у стандартных моделей игроков).
HITGROUP_HEAD = 1
HITGROUP_CHEST = 2
HITGROUP_STOMACH = 3
HITGROUP_ARM_L = 4
HITGROUP_ARM_R = 5
HITGROUP_LEG_L = 6
HITGROUP_LEG_R = 7


def hitgroup_of(name):
    """Группа хитбокса по имени кости. None — кость не может быть хитбоксом."""
    if name.startswith(("joint_Head", "joint_Jaw")):
        return HITGROUP_HEAD
    if name.startswith(("joint_Neck", "joint_TorsoB", "joint_TorsoC", "joint_Clavicle")):
        return HITGROUP_CHEST
    if name.startswith(("joint_TorsoA", "joint_HipMaster")):
        return HITGROUP_STOMACH
    if name.startswith(("joint_Shoulder", "joint_Elbow", "joint_Hand", "joint_TwistHand")):
        return HITGROUP_ARM_R if "RT" in name else HITGROUP_ARM_L
    if name.startswith(("joint_Hip", "joint_Knee", "joint_Foot", "joint_Toe")):
        return HITGROUP_LEG_R if "RT" in name else HITGROUP_LEG_L
    return None


# ------------------------------------------------------------- математика


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mulv(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def transpose(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def world_delta(rx=0.0, ry=0.0, rz=0.0):
    """Поворот в мировых осях SMD по углам в градусах (сначала Z, потом Y, X)."""
    if not (rx or ry or rz):
        return IDENTITY
    return mul(rot_x(math.radians(rx)),
               mul(rot_y(math.radians(ry)), rot_z(math.radians(rz))))




# ------------------------------------------------------------- векторная
def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross3(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def length3(a):
    return math.sqrt(dot3(a, a))


def normalize3(a):
    n = length3(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-9 else (0.0, 0.0, 0.0)


def _wrap(a):
    """Угол в (−pi, pi]."""
    while a <= -math.pi:
        a += 2 * math.pi
    while a > math.pi:
        a -= 2 * math.pi
    return a


def _ang_close(a, b):
    return sum(abs(_wrap(a[k] - b[k])) for k in range(3))


def _rot_angle(R):
    """Угол поворота матрицы 3x3 (0..pi)."""
    tr = R[0][0] + R[1][1] + R[2][2]
    return math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))


def _rot_axis(R):
    """Ось поворота матрицы 3x3 (единичная)."""
    a = (R[2][1] - R[1][2], R[0][2] - R[2][0], R[1][0] - R[0][1])
    n = length3(a)
    if n < 1e-9:
        return (0.0, 0.0, 1.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _rot_between(a, b):
    """Матрица минимального поворота, переводящая вектор a в b."""
    axis = cross3(a, b)
    if length3(axis) < 1e-9:
        if dot3(a, b) > 0:
            return IDENTITY
        # противоположные векторы: крутим вокруг любой перпендикулярной оси
        axis = cross3(a, (1.0, 0.0, 0.0))
        if length3(axis) < 1e-6:
            axis = cross3(a, (0.0, 1.0, 0.0))
        return rot_axis_angle(normalize3(axis), math.pi)
    dot = max(-1.0, min(1.0, dot3(a, b)))
    return rot_axis_angle(normalize3(axis), math.acos(dot))


def rot_axis_angle(axis, ang):
    """Матрица поворота 3x3 вокруг единичной оси (правая тройка)."""
    x, y, z = normalize3(axis)
    c, s = math.cos(ang), math.sin(ang)
    t = 1.0 - c
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def axis_angle_to_ypr(axis, ang):
    """Ось+угол -> (rx, ry, rz) в градусах для world_delta (Z, Y, X)."""
    x, y, z = normalize3(axis)
    c, s = math.cos(ang), math.sin(ang)
    t = 1.0 - c
    m = [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
         [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
         [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]
    return tuple(math.degrees(v) for v in matrix_to_angles(m))


# ------------------------------------------------------------------ поза


class Pose:
    """Поза: {кость: (rx, ry, rz)} в градусах мировых осей + сдвиг корня."""

    __slots__ = ("angles", "root")

    def __init__(self, angles=None, root=(0.0, 0.0, 0.0)):
        self.angles = dict(angles or {})
        self.root = tuple(root)

    # --- заполнение ---------------------------------------------------
    def set_role(self, role, rx=0.0, ry=0.0, rz=0.0):
        name = ROLES.get(role)
        if name:
            self.angles[name] = (rx, ry, rz)
        return self

    def add_role(self, role, rx=0.0, ry=0.0, rz=0.0):
        name = ROLES.get(role)
        if name:
            rx0, ry0, rz0 = self.angles.get(name, (0.0, 0.0, 0.0))
            self.angles[name] = (rx0 + rx, ry0 + ry, rz0 + rz)
        return self

    def add(self, bone, rx=0.0, ry=0.0, rz=0.0):
        rx0, ry0, rz0 = self.angles.get(bone, (0.0, 0.0, 0.0))
        self.angles[bone] = (rx0 + rx, ry0 + ry, rz0 + rz)
        return self

    def copy(self):
        return Pose(self.angles, self.root)

    def move(self, dx=0.0, dy=0.0, dz=0.0):
        self.root = (self.root[0] + dx, self.root[1] + dy, self.root[2] + dz)
        return self

    # --- смешивание ---------------------------------------------------
    @staticmethod
    def blend(a, b, t):
        out = {}
        for bone in set(a.angles) | set(b.angles):
            pa = a.angles.get(bone, (0.0, 0.0, 0.0))
            pb = b.angles.get(bone, (0.0, 0.0, 0.0))
            out[bone] = tuple(pa[k] + (pb[k] - pa[k]) * t for k in range(3))
        root = tuple(a.root[k] + (b.root[k] - a.root[k]) * t for k in range(3))
        return Pose(out, root)

    def fingers(self, side, curl=0.0, spread=0.0):
        """Сжать пальцы в кулак: curl — угол первой фаланги в градусах.

        Сгиб идёт вокруг Z (пальцы заворачиваются к ладони), разброс — вокруг X.
        """
        chains = FINGERS_R if side == "r" else FINGERS_L
        sign = -1.0 if side == "r" else 1.0
        for chain in chains:
            for depth, bone in enumerate(chain):
                k = 1.0 if depth == 0 else 0.7
                self.add(bone, rz=sign * curl * k,
                         rx=spread * sign * (1.0 if depth == 0 else 0.0))
        return self


class Clip:
    """Анимация: кадры-позы, fps, зацикленность."""

    def __init__(self, name, frames, fps=30, loop=True):
        self.name = name
        self.frames = frames
        self.fps = fps
        self.loop = loop

    def __len__(self):
        return len(self.frames)


# ------------------------------------------------------------ скелет: FK


class Rig:
    """Скелет в позе привязки + расчёт кадров.

    * ``bones``        — список ``Bone`` в порядке SMD;
    * ``pos_local``    — {индекс SMD: (x, y, z)} локальные смещения;
    * ``rot_local``    — {индекс SMD: (pitch, yaw, roll)} в радианах;
    * ``bone_map``     — индекс PSK -> индекс SMD.
    """

    def __init__(self, bones, pos_local, rot_local, bone_map, scale=1.0, origin_z=0.0):
        self.bones = list(bones)
        self.parent = []
        for b in self.bones:
            p = bone_map.get(b.parent, -1) if b.parent >= 0 else -1
            self.parent.append(p)
        self.index_of = {b.name: i for i, b in enumerate(self.bones)}
        self.scale = scale
        self.origin_z = origin_z
        # локальные смещения/углы с учётом масштаба и сдвига origin
        self.pos_local = {i: (pos_local[i][0] * scale, pos_local[i][1] * scale,
                              pos_local[i][2] * scale + (origin_z if self.parent[i] < 0 else 0.0))
                          for i in range(len(self.bones))}
        self.rot_local = rot_local
        # мировые матрицы позы привязки (как Build_Reference в studiomdl)
        self.bind_rot = []
        for i, par in enumerate(self.parent):
            local = angle_matrix(*rot_local[i])
            self.bind_rot.append(local if par < 0 else mul(self.bind_rot[par], local))

    # --- FK -----------------------------------------------------------
    def solve(self, pose):
        """Локальные углы/смещения SMD для одной позы."""
        world = [None] * len(self.bones)
        rot = [None] * len(self.bones)
        out_rot = [None] * len(self.bones)
        out_pos = [None] * len(self.bones)
        for i, par in enumerate(self.parent):
            delta = pose.angles.get(self.bones[i].name)
            d = world_delta(*delta) if delta else IDENTITY
            if par < 0:
                world[i] = d
                out_pos[i] = tuple(self.pos_local[i][k] + pose.root[k] * self.scale
                                   for k in range(3))
            else:
                world[i] = mul(world[par], d)
                out_pos[i] = self.pos_local[i]
            rot[i] = mul(world[i], self.bind_rot[i])
            local = rot[i] if par < 0 else mul(transpose(rot[par]), rot[i])
            out_rot[i] = matrix_to_angles(local)
        return out_rot, out_pos

    def world(self, pose):
        """Мировые (позиция, матрица) костей — для скиннинга и отладки."""
        pos, rot, _ = self._fk(pose)
        return pos, rot

    # --- IK ------------------------------------------------------------
    def _fk(self, pose):
        """Прямая кинематика: мировые позиции, полные ориентации и дельты.

        Возвращает ``(pos, rot, wdelta)``:

        * ``pos[i]``    — мировая позиция сустава;
        * ``rot[i]``    — полная мировая ориентация (дельта * поза привязки);
        * ``wdelta[i]`` — только накопленная дельта ``W[i]`` (``W = W_par * D``).

        Позиции детей считаются по ПОЛНОЙ ориентации родителя — без
        ``bind_rot`` точки уезжают на длину кости, и IK «видит» не тот скелет.
        """
        n = len(self.bones)
        pos = [None] * n
        rot = [None] * n
        wdelta = [None] * n
        for i, par in enumerate(self.parent):
            delta = pose.angles.get(self.bones[i].name)
            d = world_delta(*delta) if delta else IDENTITY
            if par < 0:
                wdelta[i] = d
                pos[i] = tuple(self.pos_local[i][k] + pose.root[k] * self.scale
                               for k in range(3))
            else:
                wdelta[i] = mul(wdelta[par], d)
                # позиция ребёнка = позиция родителя + ПОЛНАЯ ориентация
                # родителя на локальное смещение (иначе поза не влияет на точки)
                off = mulv(mul(wdelta[par], self.bind_rot[par]), self.pos_local[i])
                pos[i] = tuple(pos[par][k] + off[k] for k in range(3))
            rot[i] = mul(wdelta[i], self.bind_rot[i])
        return pos, rot, wdelta

    def _set_world_delta(self, pose, bone_i, R, max_step=120.0):
        """Домножает мирровую дельту кости на R слева: W_new = R * W.

        Локальная (SMD) дельта при этом ``D' = W_par^T * R * W_par * D`` —
        сопряжение именно дельтой родителя, а не полной ориентацией.
        """
        pos, rot, wdelta = self._fk(pose)
        par = self.parent[bone_i]
        P = wdelta[par] if par >= 0 else IDENTITY
        name = self.bones[bone_i].name
        prev = pose.angles.get(name, (0.0, 0.0, 0.0))
        D = world_delta(*prev) if name in pose.angles else IDENTITY
        if math.degrees(_rot_angle(R)) > max_step:
            R = rot_axis_angle(_rot_axis(R), math.radians(max_step))
        D_new = mul(transpose(P), mul(R, mul(P, D)))
        raw = matrix_to_angles(D_new)
        # выбираем эквивалент, ближайший к прежнему углу (иначе кадры прыгают)
        cur = tuple(math.radians(v) for v in prev)
        best = raw
        for cand in (raw,
                     (math.pi - raw[0], raw[1] + math.pi, raw[2] + math.pi),
                     (-math.pi - raw[0], raw[1] - math.pi, raw[2] - math.pi)):
            wrapped = tuple(_wrap(cand[k]) for k in range(3))
            if _ang_close(cur, wrapped) < _ang_close(cur, best):
                best = wrapped
        pose.angles[name] = tuple(math.degrees(v) for v in best)

    def reach(self, pose, chain, target, pole=None, iters=6, tol=0.6):
        """Аналитический IK двузвенной цепочки (плечо–локоть, бедро–колено).

        ``chain`` — роли ``(ближняя, дальняя)``; кончик — ребёнок дальней.
        ``pole`` — куда выгибать сустав (локоть/колено).
        """
        roles = [ROLES[r] for r in chain if r in ROLES]
        if len(roles) < 2 or target is None:
            return pose
        near_i = self.index_of.get(roles[0])
        far_i = self.index_of.get(roles[1])
        if near_i is None or far_i is None:
            return pose
        kids = [i for i, par in enumerate(self.parent) if par == far_i]
        if not kids:
            return pose
        tip_i = kids[0]

        for _ in range(iters):
            pos, _rot, _wd = self._fk(pose)
            if math.dist(pos[tip_i], target) < tol:
                break
            A, B, T = pos[near_i], pos[far_i], pos[tip_i]
            L1, L2 = math.dist(A, B), math.dist(B, T)
            if L1 < 1e-6 or L2 < 1e-6:
                return pose
            v = [target[k] - A[k] for k in range(3)]
            d = length3(v)
            if d < 1e-6:
                return pose
            d = max(abs(L1 - L2) + 1e-3, min(L1 + L2 - 1e-3, d))
            w = [x / d for x in v]
            cos_a = (L1 * L1 + d * d - L2 * L2) / (2.0 * L1 * d)
            alpha = math.acos(max(-1.0, min(1.0, cos_a)))
            # плоскость сгиба: pole, иначе текущий сустав
            ref = pole if pole is not None else B
            pv = [ref[k] - A[k] for k in range(3)]
            pv = [pv[k] - w[k] * dot3(pv, w) for k in range(3)]
            if length3(pv) < 1e-4:
                pv = [B[k] - A[k] for k in range(3)]
                pv = [pv[k] - w[k] * dot3(pv, w) for k in range(3)]
            if length3(pv) < 1e-4:
                pv = cross3(w, (0.0, 0.0, 1.0))
                if length3(pv) < 1e-4:
                    pv = cross3(w, (1.0, 0.0, 0.0))
            pv = normalize3(pv)
            want = [w[k] * math.cos(alpha) + pv[k] * math.sin(alpha) for k in range(3)]
            cur = normalize3([B[k] - A[k] for k in range(3)])
            self._set_world_delta(pose, near_i, _rot_between(cur, want))
            pos, _rot, _wd = self._fk(pose)
            B, T = pos[far_i], pos[tip_i]
            a2 = [T[k] - B[k] for k in range(3)]
            b2 = [target[k] - B[k] for k in range(3)]
            if length3(a2) < 1e-6 or length3(b2) < 1e-6:
                return pose
            self._set_world_delta(pose, far_i,
                                  _rot_between(normalize3(a2), normalize3(b2)))
        return pose

    def bind_world(self):
        """Мировые позиции и матрицы костей в позе привязки."""
        pos = [None] * len(self.bones)
        rot = [None] * len(self.bones)
        for i, par in enumerate(self.parent):
            if par < 0:
                pos[i] = self.pos_local[i]
            else:
                off = mulv(rot[par], self.pos_local[i])
                pos[i] = tuple(pos[par][k] + off[k] for k in range(3))
            rot[i] = self.bind_rot[i]
        return pos, rot


# --------------------------------------------------------------- шаблоны


def base_pose():
    """Нейтральная поза: руки опущены вдоль тела (риг в T-позе)."""
    p = Pose()
    p.set_role("clav_l", rz=-3.0).set_role("clav_r", rz=3.0)
    p.set_role("arm_l", ry=74.0, rx=-3.0)
    p.set_role("arm_r", ry=-74.0, rx=-3.0)
    p.set_role("fore_l", ry=10.0, rx=-12.0)
    p.set_role("fore_r", ry=-10.0, rx=-12.0)
    p.set_role("hand_l", rx=-4.0).set_role("hand_r", rx=-4.0)
    p.fingers("l", curl=8.0).fingers("r", curl=8.0)
    return p


#: Хват оружия: (плечо_вниз, плечо_вперёд, локоть_сгиб, локоть_внутрь) для
#: правой и левой руки, наклон корпуса и доворот. Углы в градусах.
GRIPS = {
    #              r_down r_fwd r_bend r_in   l_down l_fwd l_bend l_in  lean turn
    "rifle":  dict(r=(-52.0, 34.0, 74.0, 12.0), l=(-58.0, 42.0, 84.0, 16.0), lean=7.0, turn=-5.0),
    "mp5":    dict(r=(-54.0, 36.0, 76.0, 12.0), l=(-60.0, 44.0, 86.0, 16.0), lean=7.0, turn=-5.0),
    "m249":   dict(r=(-48.0, 34.0, 78.0, 14.0), l=(-54.0, 42.0, 88.0, 18.0), lean=8.0, turn=-6.0),
    "pistol": dict(r=(-46.0, 44.0, 62.0, 10.0), l=(-70.0, 26.0, 58.0, 8.0), lean=5.0, turn=-8.0),
    "dual":   dict(r=(-46.0, 44.0, 62.0, 10.0), l=(-46.0, 44.0, 62.0, 10.0), lean=5.0, turn=0.0),
    "knife":  dict(r=(-56.0, 30.0, 66.0, 8.0), l=(-62.0, 34.0, 70.0, 10.0), lean=6.0, turn=-10.0),
    "grenade": dict(r=(-58.0, 26.0, 60.0, 6.0), l=(-64.0, 30.0, 64.0, 8.0), lean=5.0, turn=-6.0),
    "c4":     dict(r=(-60.0, 34.0, 72.0, 10.0), l=(-62.0, 36.0, 74.0, 10.0), lean=9.0, turn=-4.0),
    "shield": dict(r=(-50.0, 36.0, 78.0, 14.0), l=(-56.0, 44.0, 86.0, 18.0), lean=7.0, turn=-5.0),
}

CROUCH = dict(thigh=-52.0, calf=78.0, foot=-26.0, drop=-17.0)


def hold_pose(kind="rifle", crouch=False, aim=0.0):
    """Поза «держит оружие». aim — доворот корпуса под цель (−90…+90)."""
    g = GRIPS.get(kind, GRIPS["rifle"])
    r_down, r_fwd, r_bend, r_in = g["r"]
    l_down, l_fwd, l_bend, l_in = g["l"]
    lean, turn = g["lean"], g["turn"]
    yaw = aim + turn

    p = Pose()
    # корпус наклоняется вперёд и доворачивается на цель
    p.set_role("waist", rx=lean * 0.30, rz=yaw * 0.20)
    p.set_role("spine", rx=lean * 0.35, rz=yaw * 0.30)
    p.set_role("chest", rx=lean * 0.35, rz=yaw * 0.35)
    p.set_role("neck", rx=-lean * 0.30, rz=-yaw * 0.25)
    p.set_role("head", rx=-lean * 0.40, rz=-yaw * 0.30)
    # руки
    # Знаки: у ПРАВОЙ руки отрицательный ry опускает кисть вниз, у ЛЕВОЙ —
    # положительный; rx отрицательный уводит руку вперёд (лицо смотрит в −Y).
    p.set_role("clav_r", rz=2.0).set_role("clav_l", rz=-2.0)
    p.set_role("arm_r", ry=r_down, rx=-r_fwd)
    p.set_role("fore_r", ry=r_in, rx=-r_bend)
    p.set_role("arm_l", ry=-l_down, rx=-l_fwd)
    p.set_role("fore_l", ry=-l_in, rx=-l_bend)
    p.set_role("hand_r", rz=8.0, rx=-8.0)
    p.set_role("hand_l", rz=-16.0, rx=-4.0)
    p.fingers("r", curl=52.0).fingers("l", curl=48.0)
    # ноги
    if crouch:
        for side in ("l", "r"):
            p.set_role("thigh_" + side, rx=CROUCH["thigh"], ry=6.0 if side == "l" else -6.0)
            p.set_role("calf_" + side, rx=CROUCH["calf"])
            p.set_role("foot_" + side, rx=CROUCH["foot"])
        p.move(dz=CROUCH["drop"])
    else:
        p.set_role("thigh_l", ry=3.0, rx=-3.0).set_role("thigh_r", ry=-3.0, rx=1.0)
        p.set_role("calf_l", rx=5.0).set_role("calf_r", rx=3.0)
        p.set_role("foot_l", rx=-2.0).set_role("foot_r", rx=-2.0)
    return p


#: Куда ставим кисти относительно корпуса (в юнитах SMD, рост 72).
#: X — влево, Y — назад (лицо в −Y), Z — вверх.
GRIP_POINTS = {
    # kind: (правая кисть, левая кисть) в юнитах SMD (рост 72):
    # X — влево, Y — назад (лицо в −Y), Z — вверх.
    # Обе цели лежат в пределах досягаемости (плечо -> кисть ≤ 22 юнитов),
    # иначе IK вытягивает руку в струну и кисть уезжает мимо.
    "rifle":  ((-2.0, -6.5, 15.0), (5.0, -10.0, 15.5)),
    "mp5":    ((-2.0, -6.5, 15.5), (4.5, -9.5, 16.0)),
    "m249":   ((-2.5, -7.0, 14.0), (5.5, -10.5, 14.5)),
    "pistol": ((-1.5, -8.0, 15.5), (-4.0, -4.5, 12.0)),
    "dual":   ((-2.0, -8.5, 15.5), (2.0, -8.5, 15.5)),
    "knife":  ((-1.5, -7.0, 14.0), (2.0, -8.0, 14.5)),
    "grenade": ((-1.0, -6.0, 13.5), (2.0, -7.5, 14.5)),
    "c4":     ((-1.0, -5.5, 12.5), (2.0, -7.0, 13.5)),
    "shield": ((-2.5, -6.0, 15.0), (5.5, -10.5, 16.0)),
}


def grip_kind(name):
    """Определяет тип оружия по имени последовательности CS 1.6."""
    n = name.lower()
    for key in ("m249", "mp5", "ak47", "carbine", "rifle", "shotgun",
                "dualpistols", "pistol", "knife", "grenade", "c4", "shield"):
        if key in n:
            return {"ak47": "rifle", "carbine": "rifle", "shotgun": "rifle"}.get(key, key)
    if "onehanded" in n:
        return "pistol"
    return "rifle"


#: Цели IK для ступней (не зависят от оружия): стоим и присели.
STANCE = {
    False: ((-5.0, -1.0, -31.0), (5.0, -1.0, -31.0)),   # (правая, левая)
    True:  ((-6.0, 3.0, -31.0), (6.0, 3.0, -31.0)),
}


def apply_ik(rig, pose, kind="rifle", crouch=False, aim=0.0, rounds=14,
             feet=False):
    """Ставит кисти (и по желанию ступни) IK поверх любой позы.

    Углы в ``GRIPS`` подобраны «на глаз» и для этого рига неверны, поэтому
    руки доводим до конкретных точек у корпуса, а не подбором градусов.
    Решаем в несколько проходов: поворот плеча сдвигает цель, одной
    итерации мало.
    """
    right, left = GRIP_POINTS.get(kind, GRIP_POINTS["rifle"])
    lean = 14.0 if crouch else 8.0
    dy, dz = -lean * 0.10, -lean * 0.05
    targets = {
        "l": (left[0], left[1] + dy, left[2] + dz),
        "r": (right[0], right[1] + dy, right[2] + dz),
    }
    # локоть наружу-вниз: так рука не выворачивается через корпус
    poles = {
        "l": (targets["l"][0] + 6.0, targets["l"][1] + 6.0, targets["l"][2] - 5.0),
        "r": (targets["r"][0] - 6.0, targets["r"][1] + 6.0, targets["r"][2] - 5.0),
    }
    for side in ("l", "r"):
        rig.reach(pose, ("arm_" + side, "fore_" + side), targets[side],
                  pole=poles[side], iters=4, tol=0.7)
    for _ in range(rounds):
        worst = 0.0
        for side in ("l", "r"):
            rig.reach(pose, ("arm_" + side, "fore_" + side), targets[side],
                      pole=poles[side], iters=1, tol=0.4)
            pos = rig._fk(pose)[0]
            hand = rig.index_of.get(ROLES["hand_" + side])
            if hand is not None:
                worst = max(worst, math.dist(pos[hand], targets[side]))
        if worst < 0.8:
            break
    if feet:
        ft = STANCE[bool(crouch)]
        for side, tgt in (("r", ft[0]), ("l", ft[1])):
            for _ in range(6):
                rig.reach(pose, ("thigh_" + side, "calf_" + side), tgt,
                          pole=(tgt[0], tgt[1] + 12.0, tgt[2] + 12.0), iters=2)
                pos = rig._fk(pose)[0]
                foot = rig.index_of.get(ROLES["foot_" + side])
                if foot is None or math.dist(pos[foot], tgt) < 1.2:
                    break
    return pose


def relax_pose(crouch=False):
    """Поза без оружия (заглушка dummy)."""
    p = base_pose()
    if crouch:
        for side in ("l", "r"):
            p.set_role("thigh_" + side, rx=CROUCH["thigh"], ry=6.0 if side == "l" else -6.0)
            p.set_role("calf_" + side, rx=CROUCH["calf"])
            p.set_role("foot_" + side, rx=CROUCH["foot"])
        p.add_role("waist", rx=12.0)
        p.move(dz=CROUCH["drop"])
    return p


# ------------------------------------------------------------------ позы


def _ease(t):
    return (1.0 - math.cos(math.pi * max(0.0, min(1.0, t)))) / 2.0


def idle_clip(crouch=False, frames=20, fps=15):
    out = []
    for i in range(frames):
        s = math.sin(2 * math.pi * i / frames)
        p = hold_pose("rifle", crouch=crouch)
        p.add_role("chest", rx=-1.4 * s)
        p.add_role("neck", rx=0.9 * s)
        p.add_role("head", rx=-0.7 * s)
        p.add_role("arm_r", rx=1.2 * s)
        p.add_role("arm_l", rx=1.0 * s)
        p.move(dz=0.5 * s)
        out.append(p)
    return Clip("idle", out, fps=fps, loop=True)


def locomotion_clip(name, crouch=False, frames=20, fps=30, stride=24.0,
                    knee=40.0, bob=1.4, swing=9.0):
    """Шаг: ноги в противофазе, корпус качается, руки держат оружие."""
    out = []
    for i in range(frames):
        ph = 2 * math.pi * i / frames
        p = hold_pose("rifle", crouch=crouch)
        for side, sign in (("l", 0.0), ("r", math.pi)):
            s = math.sin(ph + sign)
            c = max(0.0, math.sin(ph + sign - 0.7))
            if crouch:
                p.add_role("thigh_" + side, rx=-stride * 0.5 * s)
                p.add_role("calf_" + side, rx=knee * 0.45 + knee * 0.4 * c)
                p.add_role("foot_" + side, rx=-12.0 - 8.0 * c)
            else:
                p.add_role("thigh_" + side, rx=-stride * 0.5 * s)
                p.add_role("calf_" + side, rx=knee * 0.6 * c)
                p.add_role("foot_" + side, rx=-6.0 * c + 4.0 * s)
                p.add_role("toe_" + side, rx=8.0 * max(0.0, s))
        p.move(dz=bob * math.cos(2 * ph))
        p.add_role("waist", rz=2.0 * math.sin(ph))
        p.add_role("chest", rz=-1.6 * math.sin(ph))
        p.add_role("head", rz=0.8 * math.sin(ph))
        p.add_role("arm_r", rx=swing * math.sin(ph))
        p.add_role("arm_l", rx=-swing * math.sin(ph))
        out.append(p)
    return Clip(name, out, fps=fps, loop=True)


def jump_clip():
    """Прыжок: подсед, толчок, полёт, приземление."""
    out = []
    n = 10
    for i in range(n):
        t = i / (n - 1)
        p = hold_pose("rifle")
        if t < 0.25:                       # подсед
            k = _ease(t / 0.25)
            p.add_role("thigh_l", rx=-34 * k).add_role("thigh_r", rx=-32 * k)
            p.add_role("calf_l", rx=52 * k).add_role("calf_r", rx=50 * k)
            p.add_role("foot_l", rx=-18 * k).add_role("foot_r", rx=-18 * k)
            p.add_role("waist", rx=10 * k)
            p.move(dz=-11 * k)
        elif t < 0.5:                      # толчок, тело вытягивается
            k = _ease((t - 0.25) / 0.25)
            p.add_role("thigh_l", rx=-34 + 40 * k).add_role("thigh_r", rx=-32 + 38 * k)
            p.add_role("calf_l", rx=52 - 48 * k).add_role("calf_r", rx=50 - 46 * k)
            p.add_role("foot_l", rx=-18 + 22 * k).add_role("foot_r", rx=-18 + 22 * k)
            p.add_role("waist", rx=10 - 16 * k)
            p.move(dz=-11 + 16 * k)
        else:                              # полёт и приземление
            k = (t - 0.5) / 0.5
            s = math.sin(k * math.pi)
            p.add_role("thigh_l", rx=-4 - 22 * s).add_role("thigh_r", rx=-2 - 18 * s)
            p.add_role("calf_l", rx=8 + 40 * s).add_role("calf_r", rx=6 + 34 * s)
            p.add_role("foot_l", rx=4 - 10 * s).add_role("foot_r", rx=4 - 10 * s)
            p.move(dz=5 - 9 * k)
            p.add_role("waist", rx=-4 * s)
        out.append(p)
    return Clip("jump", out, fps=30, loop=False)


def longjump_clip():
    out = []
    n = 10
    for i in range(n):
        t = i / (n - 1)
        s = math.sin(t * math.pi)
        p = hold_pose("rifle")
        p.add_role("waist", rx=-10 + 30 * _ease(t * 1.5))
        p.add_role("spine", rx=-4 + 14 * _ease(t * 1.5))
        p.add_role("thigh_l", rx=-18 - 34 * s).add_role("thigh_r", rx=-12 - 30 * s)
        p.add_role("calf_l", rx=26 + 46 * s).add_role("calf_r", rx=22 + 40 * s)
        p.add_role("foot_l", rx=-6 + 12 * s).add_role("foot_r", rx=-6 + 12 * s)
        p.move(dz=4 - 10 * t)
        out.append(p)
    return Clip("longjump", out, fps=30, loop=False)


def swim_clip():
    out = []
    frames = 20
    for i in range(frames):
        ph = 2 * math.pi * i / frames
        p = Pose()
        p.set_role("waist", rx=74.0)
        p.set_role("spine", rx=6.0)
        p.set_role("neck", rx=-34.0)
        p.set_role("head", rx=-26.0)
        for side, off in (("l", 0.0), ("r", math.pi)):
            s = math.sin(ph + off)
            c = math.cos(ph + off)
            sign = 1.0 if side == "l" else -1.0
            p.set_role("arm_" + side, ry=sign * (64.0 + 30.0 * s), rx=18.0 * c)
            p.set_role("fore_" + side, rx=26.0 + 16.0 * c)
            p.set_role("thigh_" + side, rx=-14.0 * s)
            p.set_role("calf_" + side, rx=22.0 + 14.0 * c)
        p.move(dz=12.0)
        out.append(p)
    return Clip("swim", out, fps=30, loop=True)


def treadwater_clip():
    out = []
    frames = 20
    for i in range(frames):
        ph = 2 * math.pi * i / frames
        p = Pose()
        p.set_role("waist", rx=10.0)
        p.set_role("neck", rx=-8.0)
        for side, off in (("l", 0.0), ("r", math.pi)):
            s = math.sin(ph + off)
            c = math.cos(ph + off)
            sign = 1.0 if side == "l" else -1.0
            p.set_role("arm_" + side, ry=sign * 54.0, rx=-20.0 + 18.0 * s)
            p.set_role("fore_" + side, rx=64.0 + 22.0 * c)
            p.set_role("thigh_" + side, rx=-26.0 + 14.0 * s)
            p.set_role("calf_" + side, rx=36.0 + 16.0 * c)
        out.append(p)
    return Clip("treadwater", out, fps=24, loop=True)


def shoot_clip(kind="rifle", crouch=False, frames=5, fps=30):
    base = hold_pose(kind, crouch=crouch)
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        k = math.sin(min(1.0, t * 1.7) * math.pi) ** 0.55
        p = base.copy()
        p.add_role("waist", rx=-3.5 * k)
        p.add_role("chest", rx=-4.5 * k, rz=1.5 * k)
        p.add_role("neck", rx=2.5 * k)
        p.add_role("arm_r", rx=-8.0 * k, ry=-4.0 * k)
        p.add_role("arm_l", rx=-6.0 * k)
        p.add_role("fore_r", rx=7.0 * k)
        p.add_role("fore_l", rx=-5.0 * k)
        p.move(dy=1.2 * k, dz=0.6 * k)
        out.append(p)
    return Clip("shoot", out, fps=fps, loop=False)


def shoot2_clip(kind="dual", crouch=False, frames=5, fps=30):
    base = hold_pose(kind, crouch=crouch)
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        k = math.sin(min(1.0, t * 1.7) * math.pi) ** 0.55
        p = base.copy()
        p.add_role("waist", rx=-2.0 * k, rz=-1.5 * k)
        p.add_role("chest", rz=-3.0 * k)
        p.add_role("arm_l", rx=-9.0 * k, ry=4.0 * k)
        p.add_role("fore_l", rx=-6.0 * k)
        p.move(dy=0.9 * k)
        out.append(p)
    return Clip("shoot2", out, fps=fps, loop=False)


def reload_clip(kind="rifle", crouch=False, frames=12, fps=30):
    base = hold_pose(kind, crouch=crouch)
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        k = math.sin(t * math.pi) ** 0.7
        p = base.copy()
        p.add_role("waist", rx=5.0 * k)
        p.add_role("chest", rx=3.0 * k, rz=-6.0 * k)
        p.add_role("neck", rx=5.0 * k)
        p.add_role("head", rx=7.0 * k, rz=-5.0 * k)
        p.add_role("arm_l", rx=-22.0 * k, ry=12.0 * k)
        p.add_role("fore_l", rx=26.0 * k)
        p.add_role("hand_l", rz=-18.0 * k)
        p.add_role("arm_r", rx=7.0 * k, ry=5.0 * k)
        p.add_role("fore_r", rx=-7.0 * k)
        p.move(dz=-1.0 * k)
        out.append(p)
    return Clip("reload", out, fps=fps, loop=False)


def flinch_clip(part="gut", frames=6, fps=30):
    base = hold_pose("rifle")
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        k = math.sin(t * math.pi) ** 0.65
        p = base.copy()
        if part == "gut":
            p.add_role("waist", rx=17.0 * k)
            p.add_role("spine", rx=9.0 * k)
            p.add_role("chest", rx=6.0 * k)
            p.add_role("neck", rx=9.0 * k)
            p.add_role("head", rx=7.0 * k)
            p.add_role("arm_l", rx=-8.0 * k)
            p.add_role("arm_r", rx=-6.0 * k)
            p.move(dy=2.0 * k, dz=-1.4 * k)
        else:
            p.add_role("head", rx=-18.0 * k, rz=9.0 * k)
            p.add_role("neck", rx=-11.0 * k, rz=6.0 * k)
            p.add_role("chest", rx=2.0 * k)
            p.move(dy=1.2 * k)
        out.append(p)
    return Clip("flinch_" + part, out, fps=fps, loop=False)


#: Как падает каждая смерть: (наклон корпуса, заваливание в сторону, подгиб
#: ног, опускание корпуса, наклон головы). Углы в градусах, drop в юнитах.
DEATH_STYLES = {
    "death1": dict(lean=58.0, side=6.0, knee=36.0, drop=-16.0, head=16.0),
    "death2": dict(lean=84.0, side=-10.0, knee=14.0, drop=-26.0, head=12.0),
    "death3": dict(lean=-66.0, side=8.0, knee=28.0, drop=-24.0, head=-14.0),
    "head": dict(lean=-44.0, side=16.0, knee=32.0, drop=-28.0, head=-28.0),
    "gutshot": dict(lean=70.0, side=-6.0, knee=52.0, drop=-32.0, head=20.0),
    "left": dict(lean=46.0, side=54.0, knee=32.0, drop=-32.0, head=10.0),
    "back": dict(lean=-78.0, side=-6.0, knee=20.0, drop=-28.0, head=-18.0),
    "right": dict(lean=48.0, side=-50.0, knee=34.0, drop=-32.0, head=10.0),
    "forward": dict(lean=92.0, side=4.0, knee=58.0, drop=-38.0, head=22.0),
    "crouch_die": dict(lean=74.0, side=-8.0, knee=80.0, drop=-42.0, head=16.0),
}


def death_clip(name, frames=14, fps=30):
    """Падение: тело заваливается ВСЕМ корпусом и оседает на землю.

    Раньше наклон размазывался по waist/spine/chest — суммарно около 60°, и
    персонаж просто сгибался. Здесь наклоняется корень (класс ``hips``), т.е.
    падает всё тело, а ноги подгибаются под него.
    """
    st = DEATH_STYLES[name]
    base = hold_pose("rifle")
    out = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        k = _ease(min(1.0, t * 1.15))
        p = base.copy()
        # заваливание всего тела вокруг опоры
        p.add_role("hips", rx=st["lean"] * k, rz=st["side"] * k)
        # остаточный изгиб корпуса, чтобы силуэт не был «доской»
        p.add_role("waist", rx=st["lean"] * 0.10 * k, rz=st["side"] * 0.10 * k)
        p.add_role("chest", rx=st["lean"] * 0.08 * k, rz=st["side"] * 0.12 * k)
        p.add_role("neck", rx=st["head"] * 0.40 * k)
        p.add_role("head", rx=st["head"] * 0.60 * k)
        for side in ("l", "r"):
            p.add_role("thigh_" + side, rx=-st["knee"] * 0.55 * k)
            p.add_role("calf_" + side, rx=st["knee"] * 0.95 * k)
            p.add_role("foot_" + side, rx=-st["knee"] * 0.30 * k)
        # руки разваливаются в стороны
        p.add_role("arm_l", ry=34.0 * k, rx=-12.0 * k)
        p.add_role("arm_r", ry=-34.0 * k, rx=-12.0 * k)
        p.add_role("fore_l", rx=-24.0 * k)
        p.add_role("fore_r", rx=-24.0 * k)
        p.move(dz=st["drop"] * k)
        out.append(p)
    return Clip(name, out, fps=fps, loop=False)


# -------------------------------------------------------------- SMD


def write_animation_smd(path, rig, clip):
    """Анимационный SMD: все кости, все кадры клипа."""
    lines = ["version 1", "nodes"]
    for i, bone in enumerate(rig.bones):
        lines.append(f'{i:3d} "{bone.name}" {rig.parent[i]}')
    lines.append(smd.dummy_node(len(rig.bones)))
    lines.append("end")
    lines.append("skeleton")
    for f, pose in enumerate(clip.frames):
        local_rot, local_pos = rig.solve(pose)
        lines.append(f"time {f}")
        for i in range(len(rig.bones)):
            p = local_pos[i]
            r = local_rot[i]
            lines.append(f"{i:3d} " + " ".join(f"{v:.6f}" for v in (*p, *r)))
    lines.append("end")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(clip.frames)


# ---------------------------------------------------------------- QC

#: Список 111 последовательностей модели игрока CS 1.6 в порядке официального
#: ``player.qc`` Valve. Элементы добавляются функцией :func:`sequence_table`.
SEQUENCES = []


def _seq(name, clip_factory, fps, loop, act=None, weight=1, events=(), blends=0):
    SEQUENCES.append(dict(name=name, factory=clip_factory, fps=fps, loop=loop,
                          act=act, weight=weight, events=tuple(events), blends=blends))


def sequence_table():
    """Собирает 111 последовательностей (порядок = индексы в .mdl)."""
    SEQUENCES.clear()
    _seq("dummy", lambda: relax_clip(False), 24, True)
    _seq("idle1", lambda: idle_clip(False), 15, True, "ACT_IDLE")
    _seq("crouch_idle", lambda: idle_clip(True), 10, True, "ACT_CROUCHIDLE")
    _seq("walk", lambda: locomotion_clip("walk", fps=30, stride=24.0, knee=34.0), 30, True, "ACT_WALK")
    _seq("run", lambda: locomotion_clip("run", frames=16, fps=60, stride=36.0, knee=62.0,
                                        bob=2.4, swing=15.0), 60, True, "ACT_RUN")
    _seq("crouchrun", lambda: locomotion_clip("crouchrun", crouch=True, fps=30, stride=20.0,
                                              knee=40.0, bob=0.8, swing=5.0), 30, True, "ACT_CROUCH")
    _seq("jump", jump_clip, 30, False, "ACT_HOP")
    _seq("longjump", longjump_clip, 30, False, "ACT_LEAP")
    _seq("swim", swim_clip, 30, True, "ACT_SWIM")
    _seq("treadwater", treadwater_clip, 24, True, "ACT_HOVER")

    def weapon(name, grip, shoot2=False, reload=True, blends=5):
        ev = ((5001, 0, "30"),)
        _seq(f"crouch_aim_{name}", lambda: single(hold_pose(grip, True)), 30, True, blends=blends)
        _seq(f"crouch_shoot_{name}", lambda: shoot_clip(grip, True), 30, False,
             events=ev, blends=blends)
        if shoot2:
            _seq(f"crouch_shoot2_{name}", lambda: shoot2_clip(grip, True), 30, False,
                 events=((5001, 0, "10"),), blends=blends)
        if reload:
            _seq(f"crouch_reload_{name}", lambda: reload_clip(grip, True), 30, False,
                 blends=blends)
        _seq(f"ref_aim_{name}", lambda: single(hold_pose(grip, False)), 30, True, blends=blends)
        _seq(f"ref_shoot_{name}", lambda: shoot_clip(grip, False), 30, False,
             events=ev, blends=blends)
        if shoot2:
            _seq(f"ref_shoot2_{name}", lambda: shoot2_clip(grip, False), 30, False,
                 events=((5001, 0, "10"),), blends=blends)
        if reload:
            _seq(f"ref_reload_{name}", lambda: reload_clip(grip, False), 30, False,
                 blends=blends)

    weapon("carbine", "rifle")
    weapon("onehanded", "pistol")
    weapon("dualpistols", "dual", shoot2=True)
    weapon("rifle", "rifle")
    weapon("mp5", "mp5")
    weapon("shotgun", "rifle")
    weapon("m249", "m249")
    _seq("I_am_a_stupid_placeholder", lambda: relax_clip(False), 30, True)
    _seq("so_am_I", lambda: relax_clip(False), 30, False)
    # граната и C4: у гранаты нет reload, у C4 он только в стойке
    _seq("ref_aim_grenade", lambda: single(hold_pose("grenade")), 20, True, blends=5)
    _seq("ref_shoot_grenade", lambda: shoot_clip("grenade"), 45, False, blends=5)
    _seq("crouch_aim_grenade", lambda: single(hold_pose("grenade", True)), 20, True, blends=5)
    _seq("crouch_shoot_grenade", lambda: shoot_clip("grenade", True), 45, False, blends=5)
    _seq("crouch_aim_c4", lambda: single(hold_pose("c4", True)), 30, True, blends=5)
    _seq("crouch_shoot_c4", lambda: shoot_clip("c4", True), 30, False, blends=5)
    _seq("ref_aim_c4", lambda: single(hold_pose("c4")), 30, True, blends=5)
    _seq("ref_shoot_c4", lambda: shoot_clip("c4"), 30, False, blends=5)
    _seq("ref_reload_c4", lambda: reload_clip("c4"), 30, False, blends=5)
    # второй блок двойных пистолетов (в player.qc он повторён целиком)
    weapon("dualpistols", "dual", shoot2=True)
    weapon("knife", "knife", reload=False)
    weapon("ak47", "rifle")
    # щит
    _seq("crouch_aim_shieldgren", lambda: single(hold_pose("shield", True)), 20, True, blends=5)
    _seq("crouch_shoot_shieldgren", lambda: shoot_clip("shield", True), 45, False, blends=5)
    _seq("ref_aim_shieldgren", lambda: single(hold_pose("shield")), 20, True, blends=5)
    _seq("ref_shoot_shieldgren", lambda: shoot_clip("shield"), 45, False, blends=5)
    _seq("crouch_aim_shieldknife", lambda: single(hold_pose("knife", True)), 12, True, blends=5)
    _seq("crouch_shoot_shieldknife", lambda: shoot_clip("knife", True), 30, False, blends=5)
    _seq("ref_aim_shieldknife", lambda: single(hold_pose("knife")), 12, True, blends=5)
    _seq("ref_shoot_shieldknife", lambda: shoot_clip("knife"), 30, False, blends=5)
    weapon("shieldgun", "shield")
    _seq("crouch_aim_shielded", lambda: single(hold_pose("shield", True)), 20, True, blends=5)
    _seq("ref_aim_shielded", lambda: single(hold_pose("shield")), 20, True, blends=5)
    # попадания
    _seq("gut_flinch", lambda: flinch_clip("gut"), 30, False, blends=5)
    _seq("head_flinch", lambda: flinch_clip("head"), 30, False, blends=5)
    # смерти
    for name, act in (("death1", "ACT_DIE_CHESTSHOT"), ("death2", "ACT_DIESIMPLE"),
                      ("death3", "ACT_DIE_BACKSHOT"), ("head", "ACT_DIE_HEADSHOT"),
                      ("gutshot", "ACT_DIE_GUTSHOT"), ("left", "ACT_DIESIMPLE"),
                      ("back", "ACT_DIEBACKWARD"), ("right", "ACT_DIESIMPLE"),
                      ("forward", "ACT_DIEFORWARD")):
        _seq(name, (lambda n=name: death_clip(n)), 30, False, act, events=((2001, 1, ""),))
    _seq("crouch_die", lambda: death_clip("crouch_die"), 30, False, events=((2001, 1, ""),))
    return SEQUENCES


def single(pose):
    """Клип из одной позы (aim-последовательности)."""
    return Clip("single", [pose], fps=30, loop=True)


def relax_clip(crouch):
    return Clip("relax", [relax_pose(crouch)], fps=15, loop=True)


def blend_variants(clip, count):
    """Разворачивает клип в ``count`` вариантов по горизонтальному углу.

    Движок смешивает их через ``blend XR -90 90``: крайние варианты — стрельба
    влево и вправо, средний — прямо. Поворот делится между корпусом (доворот)
    и руками, голова остаётся на цели.
    """
    if count <= 1:
        return [clip]
    out = []
    for b in range(count):
        t = b / (count - 1)
        yaw = -90.0 + 180.0 * t
        frames = []
        for pose in clip.frames:
            p = pose.copy()
            p.add_role("waist", rz=yaw * 0.22)
            p.add_role("spine", rz=yaw * 0.26)
            p.add_role("chest", rz=yaw * 0.22)
            p.add_role("neck", rz=-yaw * 0.28)
            p.add_role("head", rz=-yaw * 0.30)
            p.add_role("arm_r", ry=-yaw * 0.10)
            p.add_role("arm_l", ry=-yaw * 0.10)
            frames.append(p)
        out.append(Clip(clip.name, frames, fps=clip.fps, loop=clip.loop))
    return out
