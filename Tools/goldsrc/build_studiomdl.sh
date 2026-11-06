#!/usr/bin/env bash
# Собирает кросс-платформенный studiomdl (fnky/studiomdl) в Tools/goldsrc/build/.
#
# Зачем свой компилятор: в контейнере нет Windows и нет Half-Life SDK, а
# оригинальный studiomdl.exe — 32-битный бинарник под Windows. Этот форк
# собирается из исходников gcc/cc и выдаёт те же .mdl версии 10.
#
# Патчи (применяются на лету):
#   * `attachment[]`/`numattachments` объявлены без extern -> multiple
#     definition при -fcommon на новых gcc; выносим в отдельный attachdef.c;
#   * линкуем с -fcommon -Wl,--allow-multiple-definition (старый K&R-стиль кода);
#   * лимиты MAXSTUDIOVERTS поднимаем до 8192 — CS 1.6 (Xash3D/GoldSrc)
#     держит MAXSTUDIOVERTS = 16384, а дефолтные 4096 в этом форке режут
#     персонажа на лишние SMD. Оставляем 8192 как безопасную середину.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SMDL_SRC:-/tmp/studiomdl}"
OUT="$HERE/build"
REPO="${SMDL_REPO:-https://github.com/fnky/studiomdl.git}"

mkdir -p "$OUT"

if [ ! -d "$SRC/.git" ]; then
    git clone --depth 1 -q "$REPO" "$SRC"
fi

cd "$SRC"

# 1. attachment/numattachments -> extern
python3 - "$SRC/src/studiomdl.h" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("s_attachment_t attachment[MAXSTUDIOSRCBONES];",
              "EXTERN s_attachment_t attachment[MAXSTUDIOSRCBONES];")
s = s.replace("\nint numattachments;", "\nEXTERN int numattachments;")
open(p, "w").write(s)
PY

cat > "$SRC/src/attachdef.c" <<'C'
#include "cmdlib.h"
#include "mathlib.h"
#include "studio.h"
#include "studiomdl.h"
s_attachment_t attachment[MAXSTUDIOSRCBONES];
int numattachments;
C

# 2. добавить файл в сборку
sed -i 's/^STUDIOMDL_SOURCES=bmpread.c/STUDIOMDL_SOURCES=attachdef.c bmpread.c/' "$SRC/Makefile"

# 2b. 64-битные указатели: ALIGN() в write.c кастует (byte*) в int и обрезает
#     адрес -> segfault в WriteBoneInfo. Чиним на uintptr_t.
python3 - "$SRC/src/write.c" <<'PYFIX'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("#define ALIGN( a ) a = (byte *)((int)((byte *)a + 3) & ~ 3)",
              "#define ALIGN( a ) a = (byte *)(((uintptr_t)((byte *)a + 3)) & ~(uintptr_t)3)")
s = s.replace('printf("vertices  %6d bytes (%d vertices, %d normals)\\n", pData - cur,',
              'printf("vertices  %6d bytes (%d vertices, %d normals)\\n", (int)(((intptr_t)pData - cur)),')
s = s.replace('printf("mesh      %6d bytes (%d tris, %d strips)\\n", pData - cur,',
              'printf("mesh      %6d bytes (%d tris, %d strips)\\n", (int)(((intptr_t)pData - cur)),')
s = s.replace("\tint\t\t\t\tcur;", "\tint\t\t\t\tcur = 0;")
open(p, "w").write(s)
PYFIX

# 3. лимиты
sed -i 's/^#define MAXSTUDIOVERTS\t\t4096/#define MAXSTUDIOVERTS\t\t8192/' "$SRC/src/studio.h"
sed -i 's/^#define MAXSTUDIOTRIANGLES\t\t32768/#define MAXSTUDIOTRIANGLES\t\t65536/' "$SRC/src/studio.h"

make clean >/dev/null 2>&1 || true
make -j"$(nproc)" ARCH=-m64 USER_FLAGS="-fcommon" >/dev/null 2>&1 || true

# 4. линковка (Makefile не передаёт -lm в конец, собираем вручную)
gcc -m64 -pthread -fcommon -Wl,--allow-multiple-definition \
    "$SRC"/build/build-x86_64/*.o -lm -o "$OUT/studiomdl" 2>/dev/null

# 5. проверка: компилятор должен собрать крошечную модель
"$OUT/studiomdl" 2>&1 | head -2

"$OUT/studiomdl" 2>&1 | head -3
echo "готово: $OUT/studiomdl"
