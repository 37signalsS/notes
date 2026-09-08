# Сравнение Glibc и Musl libc

## Определения

**Стандартная библиотека C (libc)** — фундаментальный компонент любой POSIX-совместимой операционной системы. Она предоставляет интерфейс между пользовательскими приложениями и ядром Linux, реализуя системные вызовы, управление памятью, ввод-вывод и работу с многопоточностью.

**Glibc (GNU C Library)** — основная реализация libc в мире Linux, развиваемая проектом GNU. Является стандартом де-факто для большинства серверных и десктопных дистрибутивов (Debian, RHEL, Ubuntu).

**Musl libc** — современная, легковесная реализация libc, ориентированная на простоту кода, корректность по стандартам POSIX и минимальное потребление ресурсов. Основная библиотека в Alpine Linux и специализированных контейнерных ОС (Wolfi, Alpaquita).

**ABI (Application Binary Interface)** — двоичный интерфейс приложения, определяющий соглашения о вызовах,Layout структур, формат объектных файлов и имена символов. Glibc и musl имеют **несовместимые ABI**: бинарники, скомпилированные под одну библиотеку, не запустятся в среде с другой без пересборки или слоя совместимости.

**Динамический загрузчик (Dynamic Loader / Interpreter)** — программа, загружаемая в память процесса перед исполняемым файлом и отвечающая за разрешение зависимостей. У glibc это `/lib64/ld-linux-x86-64.so.2` (x86_64), у musl — `/lib/ld-musl-x86_64.so.1`. Путь к загрузчику жестко прописан в бинарнике (сегмент `PT_INTERPRETER`).

**Статическая линковка** — включение всех необходимых библиотек (включая libc) непосредственно в исполняемый файл. Результат — автономный бинарник, не зависящий от версии libc в целевой системе.

**Динамическая линковка** — подключение библиотек во время запуска процесса. Бинарник меньше, но требует наличия совместимых `.so`-файлов в целевом окружении.

---

## Основные концепции

### Техническое сравнение (2024–2026)

| Аспект | Glibc (v2.4x) | Musl (v1.2.x) |
| :--- | :--- | :--- |
| **Производительность** | Высокая в многопоточных и математических задачах. | Средняя; приоритет предсказуемости над скоростью. |
| **Статическая линковка** | Сложная (зависимость от NSS). | Идеальная (полностью автономные бинарники). |
| **Размер (динамика)** | ~2-3 МБ (библиотека + зависимости). | ~600-800 КБ (монолитный файл). |
| **Безопасность** | Intel CET, Memory Sealing (`mseal`). | «Безопасность через простоту»: малая поверхность атаки. |
| **DNS (Resolver)** | Сложный: NSS через `/etc/nsswitch.conf`. | Простой: прямой DNS-клиент, нет поддержки NSS. |
| **Локали (Locales)** | Полная поддержка (любые кодировки). | Только UTF-8 (минимализм). |
| **Потоки (Threads)** | Большой дефолтный стек (~8 МБ). | Малый дефолтный стек (~128 КБ). |
| **ABI совместимость** | Стандарт индустрии; все дистрибутивы используют glibc. | Отличная от glibc; бинарники несовместимы. |
| **Поддерживаемые архитектуры** | x86_64, i386, ARM64, ARM32, RISC-V, POWER, s390x, MIPS. | x86_64, i386, ARM64, ARM32, RISC-V, POWER, s390x, MIPS, Xtensa. |
| **Обработка сигналов** | Полная поддержка POSIX + GNU extensions. | Строго POSIX; нет `sigqueue()` с `sigval`. |
| **vDSO** | Полная поддержка (clock_gettime, getrandom 6.11+). | Поддержка ограничена базовыми функциями. |

### Архитектура и внутреннее устройство

#### Динамический загрузчик и интерпретатор

Glibc использует сложный многоступенчатый загрузчик `ld-linux-x86-64.so.2`, который поддерживает:
- RPATH и RUNPATH для поиска библиотек.
- LD_PRELOAD и LD_LIBRARY_PATH.
- Поддержку аудита-хуков (`LD_AUDIT`).
- Группы символов (`--as-needed`).
- Версионирование символов (GLIBC_2.2.5, GLIBC_2.34 и т.д.).

Musl использует монолитный загрузчик `ld-musl-x86_64.so.1`, который:
- Имеет встроенный резолвер (нет отдельного `libnss_*.so`).
- Не поддерживает LD_PRELOAD в традиционном понимании (есть `LD_PRELOAD` но с ограничениями).
- Не поддерживает версионирование символов.
- Быстрее загружается из-за простоты кода.

#### Системные вызовы и обертки

Оба загрузчика предоставляют обертки (wrappers) над системными вызовами ядра. Glibc добавляет:
- Дополнительную валидацию аргументов.
- Поддержку `errno` и thread-local storage (TLS).
- GNU extensions (например, `getline()`, `asprintf()`).

Musl стремится к минимальным оберткам, передавая аргументы напрямую в syscall без лишней логики. Это уменьшает overhead, но исключает расширения GNU.

#### Модель потоков (Threading)

**Glibc (NPTL — Native POSIX Threading Library):**
- Основана на `clone3()` с флагами `CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID`.
- Дефолтный размер стека: **8 МБ** (настраивается через `ulimit -s`).
- Поддержка TLS (Thread-Local Storage) через сегмент GS/FS.
- Реализация `pthread_mutex` на основе `futex` с оптимизациями для contended/uncontended путей.
- Поддержка `thread_local` в C11 и `thread_local` в C++11.

**Musl (собственная реализация):**
- Также использует `clone3()`, но с упрощенными флагами.
- Дефолтный размер стека: **128 КБ** (настраивается через `pthread_attr_setstacksize`).
- TLS реализован через сегмент GS (на x86_64) с фиксированным расположением.
- `pthread_mutex` использует простой spinlock + futex.
- Нет поддержки `thread_local` в старом коде (требует C11 или новее).

#### Аллокаторы памяти

**Glibc (ptmalloc2 → ptmalloc3):**
- Арена-базированный аллокатор, наследие Doug Lea.
- Каждый `malloc()` создает arenas (по одной на поток) для уменьшения конкуренции.
- Поддерживает `mmap` для больших выделений (>128 КБ по умолчанию).
- В версиях 2025+ поддерживает 2MB Hugepages по умолчанию на AArch64.
- Переменная окружения `MALLOC_ARENA_MAX` ограничивает количество arenas (по умолчанию 8 * number_of_cores).
- `tcache` (thread cache) для быстрых выделений малого размера.

**Musl (mallocng — с v1.2):**
- Полностью переписанный аллокатор, пришедший на смену старому.
- Основан на бинарных деревьях (binning) по размерам.
- Защита от переполнений кучи (heap overflow) через проверки границ.
- Минимальный overhead по памяти (~4-16 байт на выделение).
- Нет arenas: вместо этого используется глобальный lock-free список страниц.
- Работает медленнее glibc при экстремальной конкуренции (сотни потоков), но более предсказуемо по памяти.

#### Обработка сигналов

**Glibc:**
- Поддерживает POSIX сигналы + расширения: `sigqueue()` (передача данных с сигналом), `sigaltstack()`.
- Многопоточная доставка сигналов: сигнал может быть доставлен конкретному потоку.
- `pthread_sigmask()` для управления маской сигналов на уровне потока.
- Обработка `SIGSEGV` с расширениями для `dlopen()` и `mmap()`.

**Musl:**
- Строгое следование POSIX.
- Нет `sigqueue()` с передачей `union sigval` (функция-заглушка возвращает `ENOSYS`).
- Сигналы доставляются потоку, вызвавшему `clone()`, или первому потоку.
- `sigaltstack()` работает, но с ограничениями на размер.

#### Локали и кодировки

**Glibc:**
- Полная поддержка локалей через `/usr/lib/locale/locale-archive` или `/usr/share/i18n/locales`.
- Поддерживаются любые кодировки: UTF-8, ISO-8859, KOI8-R, CP1251.
- Функции `setlocale()`, `localeconv()`, `nl_langinfo()`.
- Генерация локалей: `locale-gen` (Debian/Ubuntu) или `localedef`.

**Musl:**
- Поддерживается **только UTF-8** (POSIX-локаль `C.UTF-8`).
- Нет поддержки многоязычных локалей (`ru_RU.UTF-8`, `de_DE.UTF-8` и т.д.).
- Это не bug, а design decision: musl считает, что все современные приложения должны использовать UTF-8.
- Для работы с не-UTF-8 данными приложение должно обрабатывать кодировки самостоятельно (например, через ICU).

#### Time64 и проблема 2038 года

**Проблема:** 32-битное представление времени (time_t) основано на секундах с эпохи Unix (01.01.1970). Значение `2^31 - 1` (19.01.2038 03:14:07 UTC) является максимальным для 32-битного знакового целого. После этой даты время "переворачивается" в 1901 год.

**Musl (начиная с v1.2.0):**
- Полностью перешел на 64-битные типы времени (`time_t`, `struct timespec`, `struct timeval`) для **всех архитектур**, включая 32-битные ARM и x86.
- Явный break of ABI: старые бинарники, скомпилированные для musl pre-1.2, могут потребовать пересборки.
- Поддержка `TIME_SIZE=64` в конфигурации.

**Glibc:**
- Поддерживает Time64 на 32-битных системах, но **требует явной пересборки** приложений с флагами компиляции.
- На x86_64 и AArch64 (64-битные) `time_t` уже 64-битный, проблема неактуальна.
- На 32-битных системах (ARM, x86) по умолчанию используется 32-битный `time_t` для обратной совместимости.
- Для перехода на 64 бита нужны новые версии glibc (2.34+), ядра (5.1+) и перекомпиляция всех библиотек.

#### Безопасность

**Glibc:**
- **Intel CET (Control-flow Enforcement Technology):** Shadow Stack + Indirect Branch Tracking (IBT). Включен по умолчанию в GCC 8+ при сборке на поддерживаемом железе.
- **FORTIFY_SOURCE:** Макросы, заменяющие `memcpy`, `strcpy`, `sprintf` на проверенные версии (`memcpy_chk`, `__builtin_object_size`). Требует оптимизации `-O2` и выше.
- **Memory Sealing (`mseal()`):** Системный вызов (ядро 6.10+) для «запечатывания» областей памяти. Glibc оборачивает его через wrapper.
- **Stack Smashing Protection:** Canary-значение на стеке (`-fstack-protector-strong`).
- **RELRO (Relocation Read-Only):** Полное перемещение GOT в read-only память (`-Wl,-z,relro,-z,now`).
- **Address Space Layout Randomization (ASLR):** Полная поддержка через kernel.

**Musl:**
- **«Безопасность через простоту»:** Меньший кодbase означает меньше потенциальных уязвимостей.
- **Stack Protection:** Включен по умолчанию при компиляции musl.
- **Position-Independent Executable (PIE):** Поддержка включена.
- **FORTIFY_SOURCE:** Поддерживается на уровне исходников musl.
- **Нет CET:** Musl не имеет специфичных реализаций для CET (зависит от компилятора и ядра).
- **Heap overflow protection:** Встроено в mallocng через проверки границ блоков.

### Особенности разрешения имен (DNS)

**Musl** реализует резолвер иначе, чем glibc:
- **Параллельные запросы:** musl отправляет запросы на записи A и AAAA одновременно по UDP. В сетях с некорректно настроенными Firewall или старыми DNS-серверами это может приводить к таймаутам в 5 секунд.
- **Отсутствие NSS:** musl не читает `/etc/nsswitch.conf` и не поддерживает модули типа `nss-mdns` или `nss-myhostname`. Разрешение имен всегда идет через `/etc/hosts` и `/etc/resolv.conf`.

### Реализация malloc

*   **Glibc (ptmalloc):** Арена-базированный аллокатор, оптимизированный для высокой пропускной способности. В версиях 2025+ поддерживает 2MB Hugepages по умолчанию на AArch64.
*   **Musl (mallocng):** Пришел на смену старому аллокатору в v1.2. Ориентирован на защиту от переполнений кучи (heap) и минимальный оверхед по памяти. Работает медленнее glibc при экстремальной конкуренции сотен потоков.

### Математические вычисления

Для математических вычислений **glibc** значительно быстрее за счет проекта **CORE-MATH** (v2.43+). Он обеспечивает векторизацию вычислений и использование аппаратных инструкций (AVX-512, AMX), в то время как musl придерживается базовых реализаций для переносимости.

---

## Практические сценарии

### 1. Сборка для контейнеров (локальный продакшен)

**Musl** — выбор для минимизации образов (Alpine). Однако для приложений с нативными зависимостями (Python wheels, Java JNI) часто предпочтительнее **Wolfi** (использует glibc, но сохраняет легкость Alpine).

```dockerfile
# Пример сборки статического бинарника Rust с musl
FROM rust:1.80-alpine AS builder
RUN apk add --no-cache musl-dev
RUN rustup target add x86_64-unknown-linux-musl
COPY . .
RUN cargo build --release --target x86_64-unknown-linux-musl

FROM scratch
COPY --from=builder /target/x86_64-unknown-linux-musl/release/myapp /myapp
ENTRYPOINT ["/myapp"]
```

### 2. Ошибка "No such file or directory"

Типичная проблема при запуске бинарника glibc (например, скачанного из GitHub) в Alpine.

**Причина:** Бинарник ищет интерпретатор `/lib64/ld-linux-x86-64.so.2`, который в Alpine отсутствует.
**Решение:**
1. Собрать бинарник статически.
2. Использовать слой совместимости: `apk add gcompat`.
3. Использовать `patchelf` для смены пути к загрузчику.

### 3. Проблема 2038 года (Time64)

**Musl** полностью перешел на 64-битные типы времени для всех архитектур (включая 32-битные ARM/x86) начиная с версии 1.2.0. Это делает его идеальным выбором для **Embedded** систем, которые должны работать после 2038 года. Glibc поддерживает Time64 на 32-битных системах, но требует явной пересборки приложений с флагами компиляции.

### 4. Выбор libc для production-серверов (методология)

При выборе ОС для production-сервера учитывайте:

| Критерий | Glibc (Debian/Ubuntu/RHEL) | Musl (Alpine/Wolfi) |
| :--- | :--- | :--- |
| **Совместимость ПО** | Высокая (стандарт индустрии). | Средняя (требует проверки native-зависимостей). |
| **Размер образа** | Средний (100-300 МБ). | Минимальный (5-20 МБ). |
| **Безопасность** | Стандартная (зависит от hardening политик). | Повышенная (малая поверхность атаки). |
| **Срок поддержки** | Долгий LTS (5-10 лет). | Короткий (~2 года на релиз). |
| **Экосистема пакетов** | Огромная (apt: 60 000+). | Умеренная (apk: ~13 000). |
| **Поддержка enterprise** | Да (Red Hat, Canonical, SUSE). | Ограниченная (проприетарные драйверы). |

**Рекомендации:**
- **Glibc:** Для баз данных (PostgreSQL, MySQL), мониторинга (Prometheus, Grafana), Java-сервисов, сложных Python-стеков.
- **Musl:** Для микросервисов (Go, Rust), edge-nginx, cron-серверов, утилит, встроенных систем.

### 5. Валидация бинарной совместимости

Перед развертыванием проверьте, что бинарник может быть запущен:

```bash
# Проверка типа файла и требуемого интерпретатора
file /usr/local/bin/myapp
# → ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2

# Проверка зависимостей
ldd /usr/local/bin/myapp
# → linux-vdso.so.1 (0x...)
# → libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6 (0x...)
# → libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x...)
# → /lib64/ld-linux-x86-64.so.2 (0x...)

# Проверка на Alpine (musl)
ldd /usr/local/bin/myapp
# → Error: not a dynamic executable
# (Это значит, что бинарник слинкован для glibc и не запустится)
```

### 6. Статическая линковка для портативных утилит

Создание автономных бинарников для развертывания без зависимостей:

```bash
# Go: статический бинарник без libc
CGO_ENABLED=0 go build -o myapp-static main.go
file myapp-static
# → ELF 64-bit LSB executable, x86-64, statically linked

# Rust: musl target
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
file target/x86_64-unknown-linux-musl/release/myapp
# → ELF 64-bit LSB executable, x86-64, dynamically linked, interpreter /lib/ld-musl-x86_64.so.1

# C: полная статическая линковка
gcc -static -o myapp-static main.c -lm
file myapp-static
# → ELF 64-bit LSB executable, x86-64, statically linked
```

**Важно:** Полностью статические бинарники (особенно с glibc) могут вести себя иначе в chroot/контейнерах (отсутствие NSS, resolv.conf).

### 7. Тюнинг musl для высоконагруженных сервисов

Musl оптимизирован для малого потребления памяти, но при экстремальной многопоточности (500+ потоков) может быть узким местом.

```bash
# Проверка текущего размера стека потока
ulimit -s
# → 128 (KB) — дефолт для musl

# Увеличение размера стека для конкретного сервиса
pthread_attr_setstacksize(&attr, 1024 * 1024);  # 1 MB

# Ограничение количества потоков
ulimit -u 4096  # максимальное число процессов/потоков

# Мониторинг потребления памяти
ps -T -p <PID> -o pid,tid,pcpu,pmem,comm
pmap -x <PID> | grep -E "total|anonymous"
```

### 8. Диагностика и устранение проблем DNS в production

Мускулярный резолвер — частая причина задержек:

```bash
# Проверка параллельных запросов в musl
strace -e trace=network -f curl -s https://example.com 2>&1 | grep -E "sendto|recvfrom"
# В musl будут видны два одновременно отправленных UDP-запроса (A и AAAA)

# Измерение времени разрешения
time getent hosts example.com
# → 5.01s (таймаут) при проблемах с IPv6

# Решение: настройка resolv.conf
cat /etc/resolv.conf
# nameserver 10.0.0.1
# options timeout:2 attempts:1 ndots:2
```

### 9. Настройка локалей и часовых поясов для многорегиональных сервисов

При работе с гетерогенной средой (Debian + Alpine):

```bash
# Debian/Ubuntu (glibc)
dpkg-reconfigure locales
locale-gen ru_RU.UTF-8
update-locale LANG=ru_RU.UTF-8

# Alpine (musl)
apk add --no-cache tzdata
cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime
echo "Europe/Moscow" > /etc/timezone

# Проверка текущей локали
locale
# → LANG=ru_RU.UTF-8
# → LC_ALL=

# Проверка часового пояса
date
# → Sun Sep  6 12:40:42 MSK 2026
```

### 10. Анализ потребления памяти в контейнерах

Musl часто показывает меньший RSS, но это может быть обманчиво:

```bash
# Сравнение потребления памяти
docker stats --no-stream

# Детальный анализ через /proc
PID=$(docker inspect -f '{{.State.Pid}}' myapp)
cat /proc/$PID/status | grep -E "VmRSS|VmSize|Threads"
cat /proc/$PID/smaps | grep -E "Rss|Pss" | awk '{sum+=$2} END {print sum/1024 " MB"}'

# Проверка arenas в glibc
cat /proc/$PID/smaps | grep -c "heap"
# Каждая arena — отдельный heap

# Проверка malloc trim
MALLOC_TRIM_THRESHOLD_=0 strace -e trace=brk,mmap ./myapp
```

### 11. Безопасность через musl: уменьшение поверхности атаки

```bash
# Проверка подключенных библиотек (Debian/Ubuntu)
ldd /usr/bin/ssh | wc -l
# → 6-8 библиотек

# Проверка в Alpine
ldd /usr/bin/ssh | wc -l
# → 2-3 библиотеки (musl + ld-musl)

# Поиск потенциально уязвимых функций
nm -D /lib/x86_64-linux-gnu/libc.so.6 | grep -E "gets|strcpy|sprintf"
# В musl этих функций меньше или они помечены как deprecated

# Проверка флагов hardening
readelf -l /usr/bin/ssh | grep -E "GNU_RELRO|BIND_NOW"
# → GNU_RELRO в обоих
# → BIND_NOW только в glibc с LDFLAGS
```

### 12. Миграция с glibc на musl: стратегия и план

Поэтапный подход к переходу:

1. **Аудит зависимостей:** Выявите все нативные библиотеки (Python wheels, Node.js modules, Go cgo).
2. **Тестовый стенд:** Запустите приложение в Alpine в изолированном окружении.
3. **Сборка в musl-среде:** Используйте multi-stage Docker или отдельный билд-сервер с Alpine.
4. **Тестирование:** Юнит-тесты, интеграционные тесты, нагрузочное тестирование.
5. **Распространение:** Постепенно rolling-out на 5% → 25% → 100% трафика.
6. **Rollback plan:** Сохраните предыдущий glibc-образ для быстрого отката.

### 13. Бенчмаркинг производительности libc

Измерение влияния libc на производительность:

```bash
# CPU-интенсивive тесты (CINEBENCH, sysbench)
sysbench cpu run
# Сравните время на glibc vs musl

# Память-интенсивive тесты
sysbench memory run
# Musl обычно показывает меньший overhead

# Многопоточные тесты
sysbench threads run
# Glibc выигрывает при > 100 потоках

# DNS-резолвинг
time getent hosts example.com
# Musl: параллельные запросы (быстрее при рабочем IPv6)
# Glibc: последовательные запросы (стабильнее при сбоях IPv6)

# Статическая линковка
hyperfine --warmup 2 './glibc-app' './musl-app'
```

### 14. Интеграция с менеджером пакетов (apk vs apt)

Различия в управлении пакетами, влияющие на выбор libc:

```bash
# Debian/Ubuntu (glibc)
apt update && apt install -y package-name
apt-cache search keyword
dpkg -l | grep package-name

# Alpine (musl)
apk update && apk add --no-cache package-name
apk search keyword
apk list --installed | grep package-name

# Особенности Alpine
apk add --virtual .build-deps gcc musl-dev  # временные зависимости сборки
apk del .build-deps                            # удаление группы

# Проверка версии libc в системе
ldd --version           # glibc
# → ldd (Ubuntu GLIBC 2.39-0ubuntu2) 2.39

/lib/ld-musl-x86_64.so.1 --version  # musl
# → musl libc (x86_64)
# → Version 1.2.5
```

### 15. Валидация libc в CI/CD пайплайнах

Автоматическая проверка совместимости:

```bash
#!/bin/bash
# validate_libc.sh — проверка libc в артефакте сборки

ARTIFACT="./build/myapp"

# Определение требуемой libc
REQUIRED_LIBC=$(readelf -l "$ARTIFACT" | grep interpreter | sed 's|.*/\(.*\)/ld-\(.*\)\.so.*|\2|')
echo "Требуемый интерпретатор: $REQUIRED_LIBC"

# Проверка на целевом хосте
TARGET_LIBC=$(ldd --version 2>&1 | head -1)
if echo "$REQUIRED_LIBC" | grep -q "musl"; then
    if ! echo "$TARGET_LIBC" | grep -q "musl"; then
        echo "ОШИБКА: Бинарник требует musl, целевая система использует glibc"
        exit 1
    fi
else
    if echo "$TARGET_LIBC" | grep -q "musl"; then
        echo "ОШИБКА: Бинарник требует glibc, целевая система использует musl"
        exit 1
    fi
fi

echo "Проверка пройдена"
```

### 16. Работа с унаследованными бинарниками

Запуск старых бинарников на современных системах:

```bash
# Диагностика проблемы
file legacy_app
readelf -l legacy_app | grep interpreter
ldd legacy_app  # не работает для glibc-бинарников на Alpine

# Варианты решения:
# 1. Контейнер с соответствующей ОС
docker run --rm -it debian:bookworm ./legacy_app

# 2. chroot сlegacy-ОС
debootstrap --arch amd64 bookworm /srv/debian-chroot http://deb.debian.org/debian
chroot /srv/debian-chroot ./legacy_app

# 3. gcompat (ограниченно)
apk add --no-cache gcompat
./legacy_app  # может работать для простых утилит

# 4. Пересборка из исходников (рекомендуется)
git clone https://github.com/vendor/legacy.git
cd legacy
make clean && make
```

### 17. Развертывание на Embedded/IoT устройствах

Musl — стандарт для встроенных Linux:

```bash
# Сборка под Embedded ARM
rustup target add armv7-unknown-linux-musleabihf
cargo build --release --target armv7-unknown-linux-musleabihf

# Сборка под RISC-V
rustup target add riscv64gc-unknown-linux-musl
cargo build --release --target riscv64gc-unknown-linux-musl

# Проверка размера бинарника
ls -lh target/*/release/myapp
# → 1.2M (статика + musl = минимальный размер)

# Загрузка на устройство
scp target/armv7-unknown-linux-musleabihf/release/myapp root@device:/usr/local/bin/
```

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Причина и решение |
| :--- | :--- |
| **Segfault в musl** | Вероятно, переполнение стека потока. Musl использует очень маленький дефолтный стек. Решение: увеличить лимит через `pthread_attr_setstacksize`. |
| **DNS-таймауты** | Параллельные A/AAAA запросы в musl. Решение: использовать `ndots:1` или настроить DNS-прокси (CoreDNS). |
| **Медленная работа Go** | Go в связке с cgo и musl может работать медленнее из-за реализации планировщика. Решение: использовать `CGO_ENABLED=0` (нативный Go аллокатор). |
| **Ошибка "No such file or directory"** | Бинарник glibc запущен в Alpine. Решение: статическая линковка, gcompat или patchelf. |
| **Неверное время в контейнере** | Musl требует `tzdata` для работы с часовыми поясами. Решение: `apk add --no-cache tzdata`. |
| **Segfault при статической линковке glibc** | Glibc не поддерживает полную статическую линковку с NSS. Решение: musl или динамическая линковка. |
| **"undefined symbol" при запуске** | Бинарник использует GNU extension, отсутствующую в musl. Решение: пересборка или замена функции. |
| **Высокое потребление памяти glibc** | Арены аллокатора. Решение: `MALLOC_ARENA_MAX=2` или `MALLOC_TRIM_THRESHOLD_=0`. |

### Граничные случаи и ограничения

- **Go + musl:** Полностью статичные бинарники при `CGO_ENABLED=0` не зависят от libc. При `CGO_ENABLED=1` требуется musl-dev.
- **Python + musl:** Многие пакеты (NumPy, Pandas) не имеют pre-built wheels для Alpine. Требуется компиляция, что увеличивает размер образа и время сборки.
- **Java + musl:** JVM требует glibc для JNA/JNI. Используйте образаы с встроенным glibc-слоем (eclipse-temurin).
- **Node.js + musl:** Нативные модули (`sharp`, `bcrypt`) требуют `python3`, `make`, `g++` в Alpine.
- **Static linking + NSS:** Полностью статичные glibc-бинарники не разрешают имена через NSS (nsswitch.conf игнорируется). Используйте `/etc/hosts` или IP-адреса.
- **musl + seccomp:** Musl использует меньше syscall, что упрощает написание seccomp-профилей.
- **futex2:** Musl был одним из первых пользователей `futex2` (ядро 6.16+), что улучшает производительность на NUMA-системах.

### Лучшие практики

1. **Используйте musl** для микросервисов, утилит и встроенных систем, где критичны размер и безопасность.
2. **Используйте glibc** для enterprise-приложений, баз данных и систем с широким набором зависимостей.
3. **Избегайте смешивания** glibc и musl в одной container-среде без явной необходимости.
4. **Статическая линковка:** Предпочитайте musl для статических бинарников; для glibc используйте динамическую линковку или `gcompat` как временное решение.
5. **DNS:** В среде с Alpine всегда настраивайте `resolv.conf` (`ndots:2`, `timeout:2`) или используйте локальный кэширующий DNS-сервер.
6. **Локали:** В Alpine используйте `C.UTF-8`. Если нужны сложные локали — переходите на Wolfi/Chainguard.
7. **Безопасность:** Обновляйте musl и glibc регулярно. Musl обновляется через каждое обновление Alpine (Patch-релизы).
8. **Тестирование:** Всегда тестируйте бинарники в целевой среде (не только в среде сборки).

### Связанные темы

- **[Dockerfile для Alpine Linux](../../Docker/Dockerfile/dockerfile_alpine_linux.md)** — практические нюансы работы с musl.
- **[Устранение несовместимости libc](../../Docker/Docker_troubleshooting/alpine_glibc_compatibility.md)** — запуск glibc-приложений в Alpine.
- **[Интерфейсы ядра Linux](./kernel/kernel_interfaces.md)** — как libc вызывает syscalls.
- **[DNS-клиент в Linux](../Networking/Concepts/dns_client.md)** — детальный разбор работы резолверов.
- **[Диагностика DNS в контейнерах](../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — решение проблем с резолвом.
- **[Конфигурация DNS-клиента](../../Linux/Diagnostics/Networking/dns/configuration.md)** — glibc против musl в контексте DNS.
- **[Порядок разрешения имён в Linux](../../Linux/Diagnostics/Networking/dns/name_resolution.md)** — NSS и musl-specific особенности.

### Ресурсы

- [Сравнение от разработчиков musl (официальный сайт)](https://wiki.musl-libc.org/functional-comparisons.html)
- [Glibc — новости релизов](https://www.gnu.org/software/libc/)
- [Alpine Linux — пакеты musl](https://gitlab.alpinelinux.org/alpine/aports/-/tree/master/main/musl)
- [Wolfi / Chainguard](https://edu.chainguard.dev/chainguard/chainguard-images/wolfi/)
- [The musl libc website](https://musl.libc.org/)
