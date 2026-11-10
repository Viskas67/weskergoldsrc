/*
 * pushka_give.sma — выдача кастомной «пушки» по команде (CS 1.6 / AMX Mod X)
 * ---------------------------------------------------------------------------
 * Команды (консоль сервера / админ-консоль / чат):
 *   amx_pushka               — выдать пушку себе
 *   amx_pushka <ник>         — выдать игроку (можно часть ника)
 *   amx_pushka #<userid>     — выдать по userid (userid видно в status)
 *   amx_pushka @all|@t|@ct   — выдать всем / Т / КТ
 *   say /pushka [ник]        — то же самое из чата (и say_team, и !pushka)
 *   amx_pushka_cfg           — показать текущие настройки
 *   amx_pushka_scan          — найти classname оружейных энтити на карте
 *
 * Как выдаётся (по порядку; первое сработавшее — победа):
 *   1) вызов public-функции плагина пушки (если он такую предоставляет);
 *   2) give_item(id, "<pushka_classname>");
 *   3) спавн энтити на землю перед игроком + принудительный подбор.
 *
 * Всё настраивается без перекомпиляции через amx_cvar (дефолты — в блоке
 * DEF_* ниже), например:
 *   amx_cvar pushka_classname "weapon_pushka"
 *   amx_cvar pushka_func      "give_pushka"
 *   amx_cvar pushka_plugin    "pushka.amxx"
 *   amx_cvar pushka_access    "d"
 *
 * Компиляция: scripting/compile.sh pushka_give.sma  ->  pushka_give.amxx
 * Установка:  .amxx в addons/amxmodx/plugins/, строка pushka_give.amxx в
 *             addons/amxmodx/configs/plugins.ini — ниже плагина пушки.
 *
 * ВАЖНО ПРО РУССКИЙ ТЕКСТ: CS 1.6 читает чат в кодировке Windows-1251,
 * поэтому кириллица в UTF-8-файле превращается в игре в «кракозябры».
 * Здесь все сообщения латиницей — работает всегда. Хочешь по-русски —
 * переведи строки MSG_* в блоке ниже, сохрани .sma в Windows-1251
 * (AMXX Studio: ANSI / Notepad++: Кодировки -> Windows-1251) и компилируй.
 */

#include <amxmodx>
#include <amxmisc>
#include <fakemeta>
#include <fun>

#define PLUGIN_NAME    "Pushka Give"
#define PLUGIN_VERSION "1.0"
#define PLUGIN_AUTHOR  "wesker"

/* ======================= НАСТРОЙКИ ПО УМОЛЧАНИЮ ======================= */

// Файл плагина пушки (ровно как в plugins.ini) — нужен для вызова его функции.
#define DEF_PLUGIN_FILE "pushka.amxx"

// Имя public-функции плагина пушки, которой он выдаёт оружие: give_pushka(id).
// Пусто = не пытаться (тогда работают give_item и спавн).
// Найти: открой pushka.sma и поищи "public " и "give_item".
#define DEF_FUNC        ""

// classname энтити пушки. Стандартный ствол CS: weapon_ak47, weapon_awp,
// weapon_deagle и т.д. У кастомной пушки classname ищи в её плагине:
// CreateEntity / CreateNamedEntity / give_item.
#define DEF_CLASSNAME   "weapon_pushka"

// Флаг доступа AMXX (a..z; можно несколько букв, напр. "de").
// d = ADMIN_LEVEL_A (обычный админ), e = ADMIN_LEVEL_B и т.д.
#define DEF_ACCESS      "d"

// 1 = писать в чат всем "X дал пушку Y", 0 = только самому админу/игроку
#define DEF_ANNOUNCE    "1"

// 1 = если в руки выдать не удалось, ронять пушку на землю перед игроком
#define DEF_DROP        "1"

/* =========================== ТЕКСТЫ СООБЩЕНИЙ =========================== */

#define MSG_TAG         "[Pushka]"
#define MSG_NOACCESS    "No access to this command."
#define MSG_SELF_DEAD   "Can't give to yourself: you are dead or not in game."
#define MSG_NO_TARGET   "Player '%s' not found (or dead)."
#define MSG_FAILED      "Failed to give to %s - check pushka_classname / pushka_func."
#define MSG_TOTAL       "Result: given %d of %d."
#define MSG_DONE        "Done."
#define MSG_YOUGOT      "You have been given the pushka."
#define MSG_SELFTOOK    "%s took the pushka"
#define MSG_ADMINGAVE   "%s gave the pushka to %s"
#define MSG_SCAN_EMPTY1 "No weapon entities on the map."
#define MSG_SCAN_EMPTY2 "Take the pushka with its own plugin, or look in pushka.sma: CreateNamedEntity / give_item."
#define MSG_SCAN_FOUND  "Found weapon entities: %d, matched pushka_classname: %d"

/* ======================================================================== */

// forward-объявления: убирают warning 208 (function with tag result...)
stock bool:has_access(id);
stock bool:give_pushka(id);
stock bool:try_call_plugin_func(id);
stock bool:try_give_item(id);
stock bool:try_drop(id);

new g_cvar_class, g_cvar_func, g_cvar_plugin, g_cvar_access, g_cvar_announce, g_cvar_drop;
new g_maxplayers;
new g_targets[32];
new g_count;

public plugin_init()
{
	register_plugin(PLUGIN_NAME, PLUGIN_VERSION, PLUGIN_AUTHOR);

	g_maxplayers = get_maxplayers();

	g_cvar_class    = create_cvar("pushka_classname", DEF_CLASSNAME,   FCVAR_NONE, "entity classname of the pushka weapon");
	g_cvar_func     = create_cvar("pushka_func",      DEF_FUNC,        FCVAR_NONE, "public function of the pushka plugin, e.g. give_pushka (empty = skip)");
	g_cvar_plugin   = create_cvar("pushka_plugin",    DEF_PLUGIN_FILE, FCVAR_NONE, "pushka plugin filename in plugins/");
	g_cvar_access   = create_cvar("pushka_access",    DEF_ACCESS,      FCVAR_NONE, "amx_pushka access flag(s), a-z");
	g_cvar_announce = create_cvar("pushka_announce",  DEF_ANNOUNCE,    FCVAR_NONE, "1 = announce giving in chat to everyone");
	g_cvar_drop     = create_cvar("pushka_drop",      DEF_DROP,        FCVAR_NONE, "1 = drop the pushka on the ground if giving into hands failed");

	// уровень 0: доступ проверяем сами, чтобы флаг можно было менять через cvar
	register_concmd("amx_pushka",      "cmd_give", 0, "<name|#userid|@all> - give the pushka");
	register_concmd("amx_pushka_cfg",  "cmd_cfg",  0, "show pushka_give settings");
	register_concmd("amx_pushka_scan", "cmd_scan", 0, "find weapon classnames on the map");

	register_clcmd("say /pushka",      "cmd_chat");
	register_clcmd("say !pushka",      "cmd_chat");
	register_clcmd("say_team /pushka", "cmd_chat");
	register_clcmd("say_team !pushka", "cmd_chat");
}

/* =============================== КОМАНДЫ =============================== */

public cmd_give(id)
{
	if (!has_access(id))
	{
		reply(id, MSG_NOACCESS);
		return PLUGIN_HANDLED;
	}

	new arg[64];
	read_argv(1, arg, charsmax(arg));

	do_give(id, arg);
	return PLUGIN_HANDLED;
}

public cmd_chat(id)
{
	if (!has_access(id))
	{
		reply(id, MSG_NOACCESS);
		return PLUGIN_HANDLED;
	}

	new said[128], arg[64];
	read_args(said, charsmax(said));
	remove_quotes(said);
	trim(said);

	// сказано "/pushka ник" — берём всё после первого пробела
	arg[0] = 0;
	new sp = strfind(said, " ");
	if (sp != -1)
	{
		copy(arg, charsmax(arg), said[sp + 1]);
		trim(arg);
	}

	do_give(id, arg);
	return PLUGIN_HANDLED;
}

public cmd_cfg(id)
{
	if (!has_access(id))
	{
		reply(id, MSG_NOACCESS);
		return PLUGIN_HANDLED;
	}

	new cls[64], func[64], plug[64], acc[16], ann[8], drp[8];
	get_pcvar_string(g_cvar_class,    cls,  charsmax(cls));
	get_pcvar_string(g_cvar_func,     func, charsmax(func));
	get_pcvar_string(g_cvar_plugin,   plug, charsmax(plug));
	get_pcvar_string(g_cvar_access,   acc,  charsmax(acc));
	get_pcvar_string(g_cvar_announce, ann,  charsmax(ann));
	get_pcvar_string(g_cvar_drop,     drp,  charsmax(drp));

	reply(id, "classname: %s | func: %s | plugin: %s", cls, func[0] ? func : "(none)", plug);
	reply(id, "access: %s | announce: %s | drop: %s", acc, ann, drp);

	return PLUGIN_HANDLED;
}

public cmd_scan(id)
{
	if (!has_access(id))
	{
		reply(id, MSG_NOACCESS);
		return PLUGIN_HANDLED;
	}

	new want[64];
	get_pcvar_string(g_cvar_class, want, charsmax(want));

	new maxents = global_get(glb_maxEntities);
	new count = 0, found = 0;
	new cls[64];

	for (new ent = 1; ent < maxents; ent++)
	{
		if (!pev_valid(ent))
			continue;

		pev(ent, pev_classname, cls, charsmax(cls));
		if (!cls[0])
			continue;

		// всё, что похоже на оружие, плюс точное совпадение с настройкой
		if (containi(cls, "weapon") != -1 || containi(cls, "pushka") != -1 || equal(cls, want))
		{
			reply(id, "  %s  [#%d]", cls, ent);
			found++;
			if (equal(cls, want))
				count++;
		}
	}

	if (!found)
	{
		reply(id, MSG_SCAN_EMPTY1);
		reply(id, MSG_SCAN_EMPTY2);
	}
	else
	{
		reply(id, MSG_SCAN_FOUND, found, count);
	}

	return PLUGIN_HANDLED;
}

/* =============================== ВЫДАЧА =============================== */

stock do_give(admin, arg[])
{
	new count = collect_targets(admin, arg);

	if (!count)
	{
		if (!arg[0] || equali(arg, "@me") || equali(arg, "me"))
			reply(admin, MSG_SELF_DEAD);
		else
			reply(admin, MSG_NO_TARGET, arg);

		return 0;
	}

	new given = 0;
	new map[32];
	get_mapname(map, charsmax(map));

	new admin_name[32];
	if (admin > 0 && is_user_connected(admin))
		get_user_name(admin, admin_name, charsmax(admin_name));
	else
		copy(admin_name, charsmax(admin_name), "SERVER");

	for (new i = 0; i < g_count; i++)
	{
		new target = g_targets[i];
		new tname[32];
		get_user_name(target, tname, charsmax(tname));

		if (!give_pushka(target))
		{
			reply(admin, MSG_FAILED, tname);
			continue;
		}

		given++;

		if (get_pcvar_num(g_cvar_announce))
		{
			if (admin == target)
				chat_all(MSG_SELFTOOK, tname);
			else
				chat_all(MSG_ADMINGAVE, admin_name, tname);
		}
		else if (admin != target)
		{
			reply(target, MSG_YOUGOT);
		}

		log_to_file("pushka.log", "%s (%d) gave pushka to %s (%d) on %s",
			admin_name, admin, tname, target, map);
	}

	if (count > 1 || given != count)
		reply(admin, MSG_TOTAL, given, count);
	else
		reply(admin, MSG_DONE);

	return given;
}

stock bool:give_pushka(id)
{
	if (try_call_plugin_func(id))
		return true;

	if (try_give_item(id))
		return true;

	if (get_pcvar_num(g_cvar_drop) && try_drop(id))
		return true;

	return false;
}

// 1) вызов public-функции из плагина пушки: give_pushka(id)
stock bool:try_call_plugin_func(id)
{
	new func[64];
	get_pcvar_string(g_cvar_func, func, charsmax(func));
	if (!func[0])
		return false;

	new plug[64];
	get_pcvar_string(g_cvar_plugin, plug, charsmax(plug));
	if (!plug[0])
		return false;

	// callfunc_begin: 1 — успех, -1 — плагин не найден, -2 — функция не найдена
	if (callfunc_begin(func, plug) != 1)
		return false;

	callfunc_push_int(id);
	callfunc_end();
	return true;
}

// 2) штатный give_item по classname (модуль fun)
stock bool:try_give_item(id)
{
	new cls[64];
	get_pcvar_string(g_cvar_class, cls, charsmax(cls));
	if (!cls[0])
		return false;

	return (give_item(id, cls) > 0);
}

// 3) фолбэк: заспавнить энтити перед игроком и заставить её подобраться
stock bool:try_drop(id)
{
	new cls[64];
	get_pcvar_string(g_cvar_class, cls, charsmax(cls));
	if (!cls[0])
		return false;

	new Float:origin[3], Float:angles[3], Float:fwd[3], Float:spot[3];
	pev(id, pev_origin, origin);
	pev(id, pev_v_angle, angles);
	engfunc(EngFunc_AngleVectors, angles, fwd, NULL_VECTOR, NULL_VECTOR);

	spot[0] = origin[0] + fwd[0] * 40.0;
	spot[1] = origin[1] + fwd[1] * 40.0;
	spot[2] = origin[2] + 24.0;

	// ищем пол под точкой спавна
	new Float:start[3], Float:stop[3], Float:floor_pos[3];
	copy_vec(start, spot);
	start[2] += 40.0;
	copy_vec(stop, spot);
	stop[2] -= 500.0;

	engfunc(EngFunc_TraceLine, start, stop, IGNORE_MONSTERS, id, 0);
	get_tr2(0, TR_vecEndPos, floor_pos);
	floor_pos[2] += 2.0;

	new ent = engfunc(EngFunc_CreateNamedEntity, engfunc(EngFunc_AllocString, cls));
	if (ent <= 0)
		return false;

	set_pev(ent, pev_origin, floor_pos);
	set_pev(ent, pev_angles, angles);
	set_pev(ent, pev_movetype, MOVETYPE_TOSS);
	set_pev(ent, pev_solid, SOLID_TRIGGER);
	dllfunc(DLLFunc_Spawn, ent);

	// принудительный подбор: дергаем touch-обработчик энтити
	dllfunc(DLLFunc_Touch, ent, id);
	return true;
}

/* ================================ ЦЕЛИ ================================ */

stock collect_targets(admin, arg[])
{
	g_count = 0;
	trim(arg);

	// без аргумента / @me — себе
	if (!arg[0] || equali(arg, "@me") || equali(arg, "me"))
	{
		add_target(admin);
		return g_count;
	}

	// @all
	if (equali(arg, "@all") || equali(arg, "all"))
	{
		for (new i = 1; i <= g_maxplayers; i++)
			add_target(i);
		return g_count;
	}

	// @t / @ct
	if (equali(arg, "@t") || equali(arg, "t"))
	{
		for (new i = 1; i <= g_maxplayers; i++)
			if (is_user_connected(i) && get_user_team(i) == 1)
				add_target(i);
		return g_count;
	}

	if (equali(arg, "@ct") || equali(arg, "ct"))
	{
		for (new i = 1; i <= g_maxplayers; i++)
			if (is_user_connected(i) && get_user_team(i) == 2)
				add_target(i);
		return g_count;
	}

	// #userid
	if (arg[0] == '#')
	{
		new userid = str_to_num(arg[1]);
		for (new i = 1; i <= g_maxplayers; i++)
			if (is_user_connected(i) && get_user_userid(i) == userid)
				add_target(i);

		return g_count;
	}

	// ник: сначала точное совпадение, потом единственное частичное
	new exact = 0, partial = 0, partial_count = 0;
	new uname[32];

	for (new i = 1; i <= g_maxplayers; i++)
	{
		if (!is_user_connected(i))
			continue;

		get_user_name(i, uname, charsmax(uname));

		if (equali(uname, arg))
		{
			exact = i;
			break;
		}

		if (containi(uname, arg) != -1)
		{
			partial = i;
			partial_count++;
		}
	}

	if (exact)
		add_target(exact);
	else if (partial_count == 1)
		add_target(partial);

	return g_count;
}

stock add_target(id)
{
	if (id < 1 || id > g_maxplayers)
		return 0;

	if (!is_user_connected(id) || !is_user_alive(id))
		return 0;

	for (new i = 0; i < g_count; i++)
		if (g_targets[i] == id)
			return 0;

	if (g_count >= sizeof g_targets)
		return 0;

	g_targets[g_count++] = id;
	return 1;
}

/* =============================== УТИЛИТЫ =============================== */

stock bool:has_access(id)
{
	if (!id)
		return true; // консоль сервера

	new flags[16];
	get_pcvar_string(g_cvar_access, flags, charsmax(flags));
	if (!flags[0])
		return true;

	return (get_user_flags(id) & read_flags(flags)) ? true : false;
}

stock reply(id, const fmt[], any:...)
{
	new msg[192];
	vformat(msg, charsmax(msg), fmt, 3);

	if (id > 0 && is_user_connected(id))
		client_print(id, print_chat, "%s %s", MSG_TAG, msg);
	else
		server_print("%s %s", MSG_TAG, msg);
}

stock chat_all(const fmt[], any:...)
{
	new msg[192];
	vformat(msg, charsmax(msg), fmt, 3);

	client_print(0, print_chat, "%s %s", MSG_TAG, msg);
}

stock copy_vec(Float:dest[3], const Float:src[3])
{
	dest[0] = src[0];
	dest[1] = src[1];
	dest[2] = src[2];
}
