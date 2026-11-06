# Wesker (K29) для Counter-Strike 1.6 / GoldSrc

Готовая статичная модель без анимаций, собранная из `Models/Bodies/SKM_K29_Body01.psk`
**без уменьшения числа полигонов**: все 13 683 треугольника и 12 382 вершины
исходника попадают в `.mdl` (децимации нет, только дробление на части из-за
лимитов формата).

## Что получается

| | |
|---|---|
| Файл | `Build/goldsrc/mdl/wesker.mdl` |
| Формат | `IDST` v10 (GoldSrc), 1 140 264 байт |
| Кости | 65 (риг Unreal, обрезан до нагруженных) |
| Треугольники | 13 683 |
| Текстуры | 3 × 512×512, 8-бит BMP внутри `.mdl` |
| Габариты | 170 юнитов в высоту, ступни на Z = 0 |
| Поза | T-поза, один кадр-референс (анимации не нужны) |
| Привязки | 3 (`joint_NeckA_01`, `joint_HandRT_01`, `joint_HandLT_01`) |

Установка: положить `wesker.mdl` в `cstrike/models/player/wesker/` — внутренние
текстуры уже внутри файла, отдельные BMP не нужны.

## Сборка

```bash
python3 Tools/goldsrc/build.py               # SMD + QC + BMP + компиляция
python3 Tools/goldsrc/build.py --no-compile  # только промежуточные файлы
python3 Tools/goldsrc/build.py --texsize 256 # текстуры поменьше
```

Нужен `studiomdl` (см. `Tools/goldsrc/build_studiomdl.sh` — собирает
кросс-платформенный `fnky/studiomdl` из исходников) и переменная `STUDIOMDL`
с путём к бинарнику, если он не в `PATH`.

## Проверки

```bash
python3 Tools/goldsrc/verify_rig.py                                     # риг
python3 Tools/goldsrc/verify_mdl.py Build/goldsrc/mdl/wesker.mdl Build/goldsrc/smd
python3 Tools/goldsrc/inspect_mdl.py  Build/goldsrc/mdl/wesker.mdl Build/goldsrc/preview
```

* `verify_rig.py` — позиции суставов и вершин по весам (сейчас 0.0000);
* `verify_mdl.py` — заново реализует `AngleMatrix`/`R_ConcatTransforms` из
  Valve SDK, прогоняет по ним `mstudiobone_t.value` из готового `.mdl` и
  сверяет мировые вершины с reference-SMD (сейчас maxΔ = 0.022 юнита);
* `inspect_mdl.py` — разбор `.mdl` и три PNG-превью (спереди, сбоку, 3/4).

## Найденные подводные камни

* **PSK/FACE0000**: индексы веджей лежат в полях 0, 1, 2. Схема «0, 2, 4»
  (другая версия формата) склеивает треугольники из вершин разных частей тела.
* **Оси**: PSK уже в нужной системе (Z вверх, носки в −Y), как и штатные SMD
  Half-Life. Поворот лица в +X делает `$rotate` (по умолчанию +90°).
* **Углы**: `.mdl` и SMD хранят (pitch, yaw, roll) в радианах, матрица —
  `Rz(roll)·Ry(yaw)·Rx(pitch)`, как в `AngleMatrix` Valve SDK. Обратное
  разложение обязано учитывать gimbal lock при yaw = ±90°.
* **studiomdl**: форк требует патчей под x86_64 (см. `build_studiomdl.sh`) —
  32-битный `ALIGN` в `write.c`, `EXTERN`-дубли в `studiomdl.h`, двойной `free`
  в `scriplib.c`, индекс кости в строках `skeleton`.
