# Инструменты сборки в Linux

## Определения

* **GCC (GNU Compiler Collection)** — основной набор компиляторов в Linux для языков C, C++, Fortran и других.
* **LLVM/Clang** — современная инфраструктура компилятора и фронтенд для C-подобных языков, обеспечивающая быструю компиляцию, модульность и глубокую диагностику.
* **Make** — классическая утилита автоматизации сборки, выполняющая команды на основе графа зависимостей, описанных в `Makefile`.
* **CMake** — кроссплатформенная система генерации файлов сборки (мета-сборщик), создающая конфигурации для Make, Ninja или IDE.
* **Ninja** — низкоуровневая система сборки, ориентированная на скорость выполнения. В отличие от Make, Ninja генерирует минимально необходимый граф и оптимизирована для инкрементальных сборок.
* **Meson** — современная система сборки, использующая Ninja в качестве бэкенда. Фокусируется на удобстве пользователя и высокой производительности.
* **Autotools (GNU Build System)** — набор инструментов (Autoconf, Automake, Libtool) для создания переносимых пакетов исходного кода.
* **GNU `ld`** — классический линковщик binutils, принимающий объектные файлы и библиотеки и формирующий исполняемый файл или разделяемую библиотеку по списку входов (объектных файлов и `-l` аргументов). Является линковщиком по умолчанию для GCC.
* **`gold`** — более быстрый линковщик из binutils от Google, созданный для уменьшения времени линковки больших проектов. На 2026 год находится в режиме поддержки (maintenance); для новых проектов предпочтительнее `lld` или `mold`.
* **LLVM `lld`** — кроссплатформенный линковщик проекта LLVM, замена `ld`/`gold`. Быстрая и интегрирована с Clang. Активно развивается, часто выбирается в больших проектах (Android, Chromium).
* **mold** — современный, высокопроизводительный линковщик (стандарт 2026 года), работающий в несколько раз быстрее `ld` и `gold` за счет агрессивного распараллеливания.
* **AS (`as`, GNU `as`)** — ассемблер, превращающий ассемблерный код (от компилятора или `.s`/`.S` файлов) в объектный (`.o`).
* **`ar`** — архиватор, созданный для построения статических библиотек (`.a`/«архивов» из объектных файлов) и добавления/удаления объектов из архива.
* **`ranlib`** — генерирует индекс символов в архиве `ar`, ускоряющий последующую линковку со статической библиотекой.
* **`strip`** — удаляет таблицу символов и (опционально) отладочную информацию из бинарника для уменьшения размера.
* **`objcopy`** — копирует объектный/исходный файл с трансформацией (удаление/переименование секций, замена символов, извлечение/вставка отладочной информации).
* **ccache** — обертка над компилятором для кэширования результатов сборки объектных файлов, значительно ускоряющая повторную компиляцию.
* **pkg-config** — инструмент для получения параметров компиляции и линковки установленных библиотек.
* **`ld.so` (динамический загрузчик, `ld-linux`)** — пользовательская программа, загружающая разделяемые библиотеки (`.so`) и разрешающая символы перед запуском и во время выполнения динамически связанных бинарников.
* **Динамическая компоновка (Dynamic Linking)** — механизм связывания программы с разделяемыми библиотеками (`.so` файлы) в момент её запуска или выполнения.
* **Статическая компоновка (Static Linking)** — включение всех необходимых библиотек непосредственно в исполняемый файл, исключая зависимости от внешних `.so`.
* **Отложенная привязка (Lazy Binding)** — техника оптимизации, при которой реальный адрес внешней функции разрешается динамическим линковщиком только при её первом вызове.
* **SONAME** — поле разделяемой библиотеки (`DT_SONAME`), определяющее её «долгое» имя (например `libssl.so.3`), которым линковщик помечает зависимость в потребителе.
* **RPATH / RUNPATH** — записи в ELF (`DT_RPATH`/`DT_RUNPATH`, `DT_RPATH` устарел), задающие директории поиска разделяемых библиотек для конкретного бинарника; RUNPATH переопределяет стандартный поиск, но не наследуется для зависимых библиотек.
* **Hardening** — комплекс флагов компиляции/линовки (FORTIFY_SOURCE, SSP, PIE, RELRO, CET) и runtime-защитных механизмов, повышающих устойчивость бинарника к эксплойтам.
* **Воспроизводимая сборка (Reproducible Build)** — свойство, при котором одинаковый исходный код и одинаковые параметры сборки дают битово идентичный (или стойкий по хешу) артефакт независимо от времени, пути и хоста.
* **Статический анализ** — проверка исходного кода и/или объектных файлов без выполнения программы (cppcheck, clang-tidy, scan-build) для поиска неопределённого поведения, утечек и уязвимостей.

## Основные концепции

### Жизненный цикл создания бинарного файла
1. **Препроцессинг (`cpp`):** Обработка макросов (`#define`), включение заголовков (`#include`), условная компиляция (`#ifdef`).
2. **Компиляция (`cc1`):** Преобразование исходного кода в ассемблерный код.
3. **Ассемблирование (`as`):** Создание объектных файлов (`.o`), содержащих машинный код.
4. **Компоновка (Линковка) (`ld` / `gold` / `lld` / `mold`):** Объединение объектных файлов и библиотек в единый исполняемый файл или библиотеку.

### Иерархия систем сборки
* **Низкий уровень (Ninja):** Фокусируется только на максимально быстром выполнении команд компиляции, почти не имеет логики условий.
* **Средний уровень (Make):** Позволяет описывать зависимости и логику сборки вручную, поддерживает переменные и простые функции.
* **Высокий уровень (CMake, Meson):** Позволяет описывать проект декларативно, автоматически генерируя файлы для Make или Ninja в зависимости от платформы.

### Иерархия линковщиков
* **Низкий уровень (`ld`):** Прямой вызов линковщика с полным списком объектных файлов и библиотек.
* **Средний уровень (`-fuse-ld=` и `CMAKE_LINKER_TYPE`):** Переключение между `ld`/`gold`/`lld`/`mold` через флаг компилятора (`-fuse-ld=mold`) или переменную CMake (`CMAKE_LINKER_TYPE=MOLD`, CMake 3.29+).
* **Высокий уровень (CMake, Meson, Autotools):** Абстракция над линковщиком через `-L`/`-l`/импортные цели; выбор линковщика задаётся на этапе конфигурации сборки.

#### Сравнительная таблица линковщиков
| Линковщик | Скорость | Параллелизм | Кроссплатформенность | Статус на 2026 |
| :--- | :--- | :--- | :--- | :--- |
| **GNU `ld`** | Базовая | Есть | Linux/*nix | Поддержка, уступает новым |
| **`gold`** | ↑↑ | Есть | Linux, macOS (устар.) | Maintenance; не рекомендуется к новым проектам |
| **LLVM `lld`** | ↑↑↑ | Есть | Да (Linux/Windows/macOS) | Активно развивается |
| **mold** | ↑↑↑↑ | Агрессивный | Linux/*nix | Де-факто стандарт 2026 для Linux |

Выбор линковщика не влияет на семантику программы, но существенно меняет время сборки больших проектов (особенно с LTO).

### Версионирование символов и SONAME
Разделяемая библиотека объявляет своё долгое имя через `DT_SONAME` (например `libssl.so.3`). При линковке потребитель запоминает этот SONAME как зависимость (`DT_NEEDED`) вместо пути к файлу, что позволяет:
* заменять реализацию (`libssl.so.3` → другая сборка той же версии) без пересборки потребителей;
* незамедлительно ломать ABI при смене major-версии (`libssl.so.3` → `libssl.so.4`), если символы удалены — линковка/запуск потребителей завершатся ошибкой.

Соглашения именования: `libNAME.so` (dev-ссылка) → `libNAME.so.MAJOR` (SONAME) → `libNAME.so.MAJOR.MIN.PATCH` (файл на диске).

### Управление путями поиска библиотек (RPATH, RUNPATH, ldconfig)
Динамический загрузчик разрешает зависимости в следующем порядке:
1. Путь к интерпретатору из `PT_INTERPRETER` (`ld-linux-x86-64.so.2` для glibc; `ld-musl-*.so.1` для musl).
2. `DT_RPATH` (устаревший) — если `DT_RUNPATH` отсутствует.
3. Переменная окружения `LD_LIBRARY_PATH`.
4. `DT_RUNPATH` (современный) — но **только для прямых зависимостей**, не наследуется для `.so`, загруженных по цепочке.
5. Кеш динамических библиотек `/etc/ld.so.cache` (обновляется `ldconfig`).
6. Стандартные директории `/lib`, `/usr/lib` (и их вариации архитектурных канонических путей).
7. `/etc/ld.so.preload` — принудительная предзагрузка библиотек (см. «Трассировка и отладка» → LD_PRELOAD).

**Важно:** `LD_LIBRARY_PATH` и `LD_PRELOAD` игнорируются для установленных (setuid) бинарников из соображений безопасности. `DT_RPATH` устарел и может конфликтовать с `DT_RUNPATH`; при наличии обоих используется `DT_RUNPATH`.

### Продвинутые оптимизации
* **LTO (Link Time Optimization):** Оптимизация на этапе линковки. Позволяет компилятору видеть весь проект целиком, удалять неиспользуемый код и выполнять инлайнинг функций между разными объектными файлами.
* **PGO (Profile Guided Optimization):** Сборка на основе профиля использования. Программа собирается с инструментарием, прогоняется на реальных данных, и затем пересобирается с использованием накопленной статистики для максимальной производительности.
* **BOLT (Binary Optimization and Layout Tool):** Пост-линковочная оптимизация (Meta) для перестановки блоков/функций в бинарнике.

### Принцип работы ccache
`ccache` перехватывает вызовы компилятора и создает уникальный хэш на основе:
* Содержимого исходного файла.
* Всех включенных заголовочных файлов.
* Флагов компиляции и версии самого компилятора.
При совпадении хэша `ccache` мгновенно подставляет готовый результат из своего хранилища, минуя стадию компиляции.

### Механизм PLT и GOT
Для реализации динамической линковки используются две таблицы:
* **PLT (Procedure Linkage Table):** Содержит короткие инструкции (заглушки) для вызова внешних функций. При первом вызове заглушка передаёт управление динамическому линковщику (`ld.so`).
* **GOT (Global Offset Table):** Хранит абсолютные адреса символов в памяти. После первого разрешения адреса линковщик записывает его в GOT, и последующие вызовы через PLT проходят мгновенно.

### Инструменты анализа ELF (арсенал для devops/SRE)
* **`file`:** определяет тип, архитектуру, признаки линковки (statically/dynamically linked), интерпретатор.
* **`readelf`:** низкоуровневый просмотр ELF — заголовки (`-h`), секции (`-S`), сегменты (`-l`), динамические символы (`--dyn-syms`), нужные библиотеки (`-d | grep NEEDED`), RPATH/RUNPATH.
* **`objdump`:** дизассемблирование (`-d`), таблица программ (`-p`, в т.ч. `NEEDED`), работа с секциями (`-h`/`-j`).
* **`nm`:** символы объектных/исходных файлов (`-n` по адресу, `-D` — динамические/экспортируемые, `T`/`U`/`B`/`D`/`W`).
* **`ldd`:** высокоуровневый вывод зависимостей (`.so`) и разрешённых путей; **недостаток** — исполняет бинарник, поэтому ненадёжен для повреждённых/setuid-объектов.
* **`objcopy`:** `--only-keep-debug` для выноса debug-информации, `--strip-unneeded` для удаления ненужных символов.
* **`ar`/`ranlib`:** инспекция и создание статических библиотек (`.a`).
* **`strings`:** поиск человекочитаемых строк (версии символов, пути, версии glibc).
* **`checksec`:** проверка hardening-флагов (NX, PIE, Canary, RELRO).

## Практические сценарии

### Настройка ccache и mold
**Установка:**
```bash
# Debian/Ubuntu
sudo apt install ccache mold
# RHEL/CentOS
sudo dnf install ccache mold
```

**Использование с CMake:**
Рекомендуемый способ интеграции в современные проекты для ускорения сборки:
```bash
cmake -B build -G Ninja \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DCMAKE_EXE_LINKER_FLAGS="-fuse-ld=mold"
```
* `# → Использование mold вместо стандартного ld сокращает время линковки больших проектов в разы`

**Статистика ccache:**
```bash
ccache -s
# → выводит попадания (cache hit) и промахи (cache miss)
```

### Управление кэшем ccache в CI/system-wide
Для воспроизводимых и быстрых сборок в CI/DevOps-агентах кэш следует выносить наружу и ограничивать:
```bash
# Общий кэш для всех сборок под хорошим хостом
export CCACHE_DIR="/var/cache/ccache"
export CCACHE_BASEDIR="$(pwd)"          # изоляция хэшей от путей к исходникам
export CCACHE_MAXSIZE="10G"
export CCACHE_SLOPPINESS="timeMacros,include_file_mtime,file_macro"
ccache -z                # сброс статистики перед прогоном
make -j"$(nproc)"
ccache -s                # статистика: cache hit/miss, cache size
ccache --cleanup         # принудительная очистка по размеру
```
* `CCACHE_BASEDIR` избавляет от промахов кэша из-за разных абсолютных путей к исходникам.
* `CCACHE_SLOPPINESS` повышает hit-rate, но снижает гарантии воспроизводимости — используйте в CI, а в релизной сборке отключайте.

### Инструменты анализа бинарников
**Просмотр зависимостей от библиотек (ldd):**
```bash
ldd /usr/bin/ls
# → linux-vdso.so.1 => (0x00007ffcc338b000)
# → libselinux.so.1 => /lib/x86_64-linux-gnu/libselinux.so.1 (0x00007f8...)
```

**Анализ таблицы символов (nm):**
```bash
nm -D /usr/lib/x86_64-linux-gnu/libssl.so.3 | grep SSL_connect
# → 00000000000456a0 T SSL_connect
# → T означает, что символ находится в секции .text (экспортируемая функция)
```

**Проверка ELF-заголовков и секций (readelf):**
```bash
# Тип бинарника, архитектура, точка входа
readelf -h my_app
# Список секций (.text, .data, .bss, .rodata)
readelf -S my_app
```

### Управление кэшем динамических библиотек (ldconfig) — для SRE
`ldconfig` строит и обновляет `/etc/ld.so.cache` — хеш-таблицу путей к `.so`. Вызывается триггером менеджера пакетов после установки/удаления библиотек.

```bash
# Пересобрать кеш после добавления/удаления .so вручную
sudo ldconfig

# Просмотр кеша (все известные .so)
ldconfig -p | grep libcurl

# Точная диагностика: как загрузчик ищет библиотеку
ldconfig -p | grep libc.so.6
# → libc.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libc.so.6

# Проверить, какие директории включены в кеш
ldconfig -v 2>/dev/null | grep -E "SEARCH|=>|:" 
```
**Файлы конфигурации:**
* `/etc/ld.so.conf` — включает директории и файлы из `/etc/ld.so.conf.d/*.conf`.
* `/etc/ld.so.conf.d/*.conf` — рекомендуемое место для сторонних путей (`sudo sh -c 'echo /opt/myapp/lib > /etc/ld.so.conf.d/myapp.conf' && ldconfig`).
* `/var/cache/ldconfig` — внутренний кеш `ldconfig` (а не пользовательский `/etc/ld.so.cache`).

**SRE-подводные камни:**
* `ldconfig` без прав root пересобирает только пользовательский кеш, если `LD_LIBRARY_PATH` уже указывает путь — используйте `ldconfig -n DIR` для локального поиска без кеша.
* При развёртывании сторонних `.so` не кладите их в `/usr/local/lib`, а используйте dedicated `.conf` в `ld.so.conf.d/` — это проще аудировать и откатывать.

### Диагностика зависимостей и линковки
`ldd` удобен, но иногда недостаточен (не выводит RPATH/RUNPATH, «запускает» бинарник). Для SRE/devops используйте низкоуровневые инструменты:
```bash
# Дерево зависимостей (включая транзитивные .so) — lddtree из пакета psmisc
lddtree /usr/bin/ls
# → |      |- /lib/x86_64-linux-gnu/libpthread.so.0
# → |-`-- /lib/x86_64-linux-gnu/libc.so.6

# Только прямые зависимости (DT_NEEDED) без выполнения бинарника
objdump -p /usr/bin/ls | grep NEEDED
# → NEEDED               libselinux.so.1
# → NEEDED               libpcre2-8.so.0

# RPATH/RUNPATH (DT_RPATH/DT_RUNPATH) и интерпретатор
readelf -d /usr/bin/ls | grep -E "RPATH|RUNPATH|INTERP"
# → 0x0000000000000019 (RUNPATH) Library rpath: [/usr/lib/myapp]

# Интерпретатор динамического загрузчика
readelf -l /usr/bin/ls | grep interpreter
# → [Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]
```
**`ldd` ненадёжен, когда:**
* бинарник повреждён или имеет неверный интерпретатор (на Alpine/wine) — `ldd` может вывести `not a dynamic executable` или попытаться выполнить;
* бинарник setuid — `ldd` игнорирует `LD_LIBRARY_PATH`; предпочитайте `objdump -p` / `readelf -d`.

### Использование pkg-config
Позволяет автоматически получить флаги для компиляции и линковки установленных библиотек:
```bash
gcc main.c $(pkg-config --cflags --libs openssl) -o my_secure_app
```
**Диагностика проблем pkg-config:**
```bash
# Проверить, зарегистрирована ли библиотека
pkg-config --exists openssl && echo "found" || echo "missing"

# Где ищет .pc-файлы
pkg-config --variable=pc_path pkg-config
# → /usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig

# Добавить путь к .pc-файлам сторонней библиотеки
export PKG_CONFIG_PATH="/opt/myapp/lib/pkgconfig:$PKG_CONFIG_PATH"

# Статическая линковка (подхват .la-файлы с -static)
gcc main.c $(pkg-config --static --cflags --libs libpng16) -o app
```

### Диагностика "symbol not found" и "version X not found"
Эти ошибки часты при переносе бинарника между хостами с разными версиями glibc/библиотек.

```bash
# Вывести требуемые версии символов (например, GLIBC_2.29)
readelf -V ./my_app
objdump -T ./my_app | grep -i glibc

# Проверить, какие символы НЕ разрешаются в текущей системе
LD_DEBUG=bindings ./my_app 2>&1 | grep -i "symbol\|cannot"
# → symbol=memcpy;  lookup in file libc.so.6
# → symbol version mismatch: ./my_app: version `GLIBC_2.34' not defined

# Решение 1: собрать на целевой/старой glibc или использовать Patchelf для смены интерпретатора
# Решение 2: понизить требуемую версию через `-Wl,--enable-symbol-versioning` или rebuild
```
* `ldd ./my_app` иногда скрывает причину; используйте `LD_DEBUG=bindings`/`symbols` для полной картины.

### Отладка линковки через LD_DEBUG
Переменная окружения `LD_DEBUG` заставляет динамический линковщик выводить подробные логи работы:
```bash
# Посмотреть, какие библиотеки и откуда загружаются
LD_DEBUG=libs ls

# Посмотреть процесс разрешения каждого символа (binding)
LD_DEBUG=bindings ./my_application

# Полный дамп (libs, bindings, symbols, reloc) — вредит производительности
LD_DEBUG=all ./my_application 2> ld_debug.log
```
Полный список фильтров: `libs`, `files`, `symbols`, `bindings`, `reloc`, `auxv`, `config`, `all`.

**Отключение Lazy Binding:**
Полезно для проверки наличия всех символов сразу при старте (например, в CI) или для уменьшения задержек первого вызова:
```bash
export LD_BIND_NOW=1
./my_application
# Либо на этапе линковки: -Wl,-z,now (включает BIND_NOW / полную задержку разрешения)
```

### Проверка hardening (checksec) — для SRE/аудита
```bash
# Анализ ELF-файла
checksec --file=./my_app
# → RELRO:  Full RELRO
# → STACK:  Canary found
# → NX:     NX enabled
# → PIE:    PIE enabled
# → RPATH:  No RPATH
# → RUNPATH: No RUNPATH
```
Соответствие флагам сборки: `-fstack-protector-strong`, `-D_FORTIFY_SOURCE=3`, `-fPIE -pie`, `-Wl,-z,relro,-z,now`, `-fcf-protection` (CET). Если флаги выключены — исправьте `CMakeLists.txt`/`Makefile`.

### Воспроизводимая сборка и верификация (diffoscope)
Для SRE важно, чтобы одинаковые исходники давали идентичный бинарник:
```bash
# Сборка 1
SOURCE_DATE_EPOCH=1735689600 CFLAGS="-fdebug-prefix-map=$(pwd)=." ./configure --prefix=/usr
make -j"$(nproc)" && cp my_app /tmp/build1/my_app

# Сборка 2
SOURCE_DATE_EPOCH=1735689600 CFLAGS="-fdebug-prefix-map=$(pwd)=." ./configure --prefix=/usr
make -j"$(nproc)" && cp my_app /tmp/build2/my_app

# Сравнение (diffoscope покажет, где различается)
diffoscope /tmp/build1/my_app /tmp/build2/my_app
# → (пустой вывод = артефакты идентичны)

# Отключить build-id для строгого сравнения (иначе хеши различаются)
readelf -n ./my_app | grep "Build ID"
# → отключить: -Wl,--build-id=none
```

### Разделение отладочной информации (debug-info split)
Чтобы не разворачивать тяжёлые debug-символы в продакшшене, но сохранять возможность debug:
```bash
# 1. Выделить debug-секцию в отдельный файл
objcopy --only-keep-debug my_app my_app.debug
# 2. Удалить debug из основного бинарника
objcopy --strip-debug my_app
# 3. «Подсоединить» debug-файл по build-id
objcopy --add-gnu-debuglink=my_app.debug my_app
# Теперь gdb ./my_app автоматически найдёт my_app.debug
file my_app
# → ELF 64-bit LSB pie executable, x86-64, …, with debug_info, not stripped
```
* В дистрибутивах debug-информация упаковывается в отдельные `-debuginfo`/`-dbg` пакеты (см. `package_build`).

### Autotools (GNU Build System): классический workflow
Для портативных пакетов исходного кода:
```bash
# 1. Автоконфигурация (только для checkout из VCS; release tarballs уже содержат configure)
autoreconf -fi

# 2. Конфигурация: --prefix задаёт корень установки, --with-... включает опции
./configure --prefix=/opt/myapp --enable-static --with-libcurl

# 3. Сборка с параллелизмом
make -j"$(nproc)"

# 4. Тесты (если есть цель check)
make check

# 5. Установка в прибрежный корень (DESTDIR) — для сборки пакетов
make DESTDIR="$(pwd)/staging" install

# 6. Быстрая пересборка без реконфигурации
make -C build_dir
```
* **out-of-tree сборка:** `./configure` в отдельной директории сохраняет исходники чистыми: `mkdir build && cd build && ../configure`
* **`--sysconfdir`, `--localstatedir`, `--sbindir`** важны для SRE: фиксируют пути к конфигам/данным.
* **`-C` (cache):** `make -C dir` — сборка в другом каталоге.

### Meson: современный workflow
```bash
# Конфигурация и сборка (Ninja backend по умолчанию)
meson setup build --buildtype=release -Dprefix=/opt/myapp -Ddefault_library=shared
ninja -C build

# Тесты
meson test -C build

# Установка в DESTDIR
DESTDIR="$(pwd)/staging" meson install -C build

# Перенастройка без пересоздания build dir
meson configure build -Dcpp_args="-fvisibility=hidden"
ninja -C build
```
* `--wipe` сбрасывает кэш конфигурации: `meson setup --wipe build`.

### CMake: production-ready workflow для SRE/devops
```bash
# Out-of-source сборка с Ninja и кэшированием компилятора
cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/opt/myapp \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DCMAKE_LINKER_TYPE=MOLD          # CMake 3.29+

# Параллельная сборка и тесты
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure

# Установка с DESTDIR (для пакетирования) и RPATH по умолчанию
DESTDIR="$(pwd)/staging" cmake --install build

# RPATH: делать бинарник переносимым без LD_LIBRARY_PATH
cmake -S . -B build \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
  -DCMAKE_INSTALL_RPATH='$ORIGIN/../lib'
```
**Toolchain-файлы для кросс-компиляции** (arm64 → x86_64):
`aarch64-toolchain.cmake`:
```cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_FIND_ROOT_PATH /usr/aarch64-linux-gnu)
```
```bash
cmake -S . -B build-arm -DCMAKE_TOOLCHAIN_FILE=../aarch64-toolchain.cmake
```
**CMake Presets (CMake 3.19+)** стандартизируют конфигурацию сборки и кросс-компиляцию — храните `CMakePresets.json` рядом с `CMakeLists.txt`.

### Пример продвинутого Makefile
```makefile
CC = gcc
CFLAGS = -Wall -Wextra -O3 -march=native
LDFLAGS = -fuse-ld=mold
TARGET = my_app
SRCS = main.c utils.c
OBJS = $(SRCS:.c=.o)

# Поддержка ccache, если он установлен
ifneq ($(shell which ccache),)
    CC := ccache $(CC)
endif

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $(TARGET) $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
```

**Полезные опции командной строки:**
```bash
# Сухой запуск: показать команды без выполнения
make -n

# Использовать альтернативный Makefile
make -f custom.mk

# Обновить timestamps (перестроит зависимости)
make -t

# Вывод всех выполняемых команд (verbose)
make V=1

# Параллельная сборка на N потоков
make -j"$(nproc)"

# Построить несколько целей
make all clean
```

### Статический анализ и compile_commands.json (для CI)
Для перехвата багов до сборки и интеграции с IDE/clangd:
```bash
# 1. Сгенерировать compile_commands.json через bear (BEaR) во время сборки
bear -- make -j"$(nproc)"
# → compile_commands.json: БД комманд компиляции для clangd/IDE

# 2. Статический анализ
cppcheck --enable=all --error-exitcode=1 --suppress=missingInclude src/
# → удобно в CI для C/C++

# 3. clang-tidy (на основе compile_commands.json)
clang-tidy -p build src/*.cpp -- --std=c++20

# 4. scan-build (статический анализатор на базе Clang)
scan-build make
```
* cppcheck/clang-tidy — обязательный CI-этап; ловят неопределённое поведение и утечки до запуска.

### Профилирование сборки и валидация LTO/PGO
Для SRE, оценивающего эффективность тулчейна:
```bash
# Тайминг стадий сборки (cc1/compile — vs — link)
time cmake --build build -j"$(nproc)"
# real    0m3.210s
# user    0m28.400s   # user >> real => хорошая параллельность

# PGO pipeline (gcc)
cmake -B pgo-gen -G Ninja -DCMAKE_C_FLAGS="-fprofile-generate" && cmake --build pgo-gen
./pgo-gen/tests --run-full-suite              # сбор профиля нагрузкой
llvm-profdata merge -o default.profdata pgo-gen/*.profraw  # для clang
cmake -B pgo-use -G Ninja -DCMAKE_C_FLAGS="-fprofile-use"  # (gcc: -fprofile-use)
cmake --build pgo-use

# BOLT (пост-линковочная оптимизация) — для горячих binary-only сервисов
llvm-bolt my_app -o my_app.bolt -reorder-blocks=cache -reorder-functions=hfsort
```

## Дополнительная информация

### См. также
* **[Оптимизация сборки в Docker (C++)](../../Docker/Dockerfile/Docker_best_practices/cpp.md)** — применение ccache, mold и Ninja в контейнерах, hardening и воспроизводимые сборки.
* **[Сравнение Glibc и Musl libc](../Core/glibc_vs_musl.md)** — архитектурные различия стандартных библиотек и работа динамического загрузчика.
* **[Трассировка и LD_PRELOAD](../Diagnostics/Troubleshooting/tracing_and_debugging.md)** — переопределение функций библиотек без пересборки.
* **[Сборка пакетов: этапы жизненного цикла](../PackageManagement/package_build/basic_concepts.md)** — как build tools вписываются в DEB/RPM сборку.

### Справочные ресурсы
* [GNU Make Manual](https://www.gnu.org/software/make/manual/) — стандарт автоматизации.
* [CMake Documentation](https://cmake.org/documentation/) — современные практики управления проектами.
* [Meson Documentation](https://mesonbuild.com/) — официальный сайт Meson.
* [Динамический линковщик ld.so(8)](https://man7.org/linux/man-pages/man8/ld.so.8.html) — официальная документация.
* [Autotools Manual](https://www.gnu.org/software/automake/manual/) — портативные пакеты исходного кода.
