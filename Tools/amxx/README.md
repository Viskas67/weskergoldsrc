# pushka_give — выдача кастомной «пушки» по команде (CS 1.6, AMX Mod X)

Плагин-выдавальщик для случая, когда сама пушка живёт в отдельном плагине.
Он не знает, как устроена твоя пушка, поэтому пробует три способа по очереди
и останавливается на первом сработавшем:

1. вызывает `public`-функцию твоего плагина пушки (если он её отдаёт);
2. делает `give_item(id, "<classname>")`;
3. спавнит энтити пушки перед игроком на землю и дёргает её `Touch`
   (принудительный подбор).

## Установка

```
addons/amxmodx/scripting/pushka_give.sma   -> компилировать
addons/amxmodx/plugins/pushka_give.amxx
addons/amxmodx/configs/plugins.ini         -> строка pushka_give.amxx
                                              НИЖЕ строки с плагином пушки
```

Компиляция: `scripting/compile.sh pushka_give.sma` (Linux) или
AMXX Studio / любой онлайн-компилятор AMXX 1.8.2+.

Если хочешь русские сообщения — переведи строки `MSG_*` в начале файла и
сохрани `.sma` в кодировке **Windows-1251**, иначе в игре будут кракозябры
(CS 1.6 читает чат как cp1251).

## Команды

| Команда | Что делает |
|---|---|
| `amx_pushka` | выдать себе |
| `amx_pushka <ник>` | выдать игроку, можно часть ника |
| `amx_pushka #<userid>` | выдать по userid |
| `amx_pushka @all` / `@t` / `@ct` | всем / Т / КТ |
| `say /pushka [ник]` | то же из чата (`!pushka` и `say_team` тоже) |
| `amx_pushka_cfg` | показать настройки |
| `amx_pushka_scan` | найти classname оружейных энтити на карте |

Примеры:

```
amx_pushka Vasya
amx_pushka @t
say /pushka
```

## Настройка (без перекомпиляции)

```
amx_cvar pushka_classname "weapon_pushka"
amx_cvar pushka_func      "give_pushka"
amx_cvar pushka_plugin    "pushka.amxx"
amx_cvar pushka_access    "d"
amx_cvar pushka_announce  "1"
amx_cvar pushka_drop      "1"
```

* `pushka_classname` — classname энтити пушки. Стандартный ствол:
  `weapon_ak47`, `weapon_awp`, `weapon_deagle`, … У кастомной пушки смотри
  в её `.sma`: `CreateEntity`, `CreateNamedEntity`, `give_item`.
* `pushka_func` — имя `public`-функции плагина пушки, например
  `give_pushka`; тогда будет вызвано `give_pushka(id)`. Пусто — вызов
  пропускается.
* `pushka_plugin` — имя файла плагина пушки ровно как в `plugins.ini`
  (`callfunc_begin` требует точного имени, например `pushka.amxx`).
* `pushka_access` — флаг доступа, по умолчанию `d` (ADMIN_LEVEL_A).
  Флаги админов задаются в `addons/amxmodx/configs/users.ini`.
* `pushka_announce` — писать ли в чат всем «X дал пушку Y».
* `pushka_drop` — ронять пушку на землю, если в руки выдать не удалось.

Значения по умолчанию заданы в блоке `DEF_*` в начале `.sma`;
`create_cvar` создаёт `configs/pushka_give.cfg`, куда можно вписать свои.

## Как узнать, что писать в настройках

1. Открой `.sma` своего плагина пушки.
2. `Ctrl+F` по `give_item` или `CreateNamedEntity` — это и есть `classname`.
3. `Ctrl+F` по `public` — если есть функция вида `public give_pushka(id)`,
   её имя идёт в `pushka_func`.
4. Если плагин пушки создаёт оружие по своему меню/команде, посмотри, что
   он вызывает внутри (`zp_give_item`, `give_item`, `fm_give_item`), и
   повтори это в `pushka_func`/`pushka_classname`.
5. На живом сервере: `amx_pushka_scan` в консоли покажет classname всех
   оружейных энтити, которые сейчас есть на карте.

## Диагностика

| Симптом | Причина |
|---|---|
| `Failed to give to X` | неверный `pushka_classname`, нет `pushka_func`, или пушка выдаётся только своим кодом |
| `Unknown command amx_pushka` | `.amxx` не в `plugins/` или плагин не загрузился (`amx_plugins` покажет ошибку) |
| команда есть, но `No access` | у админа нет флага из `pushka_access` |
| в чате кракозябры | `.sma` в UTF-8, нужен Windows-1251 |
