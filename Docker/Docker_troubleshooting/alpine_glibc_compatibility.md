# Устранение несовместимости Glibc и Alpine Linux (musl)

**Актуально для:** Alpine Linux 3.24.x, gcompat (официальные репозитории Alpine), Wolfi (Chainguard, rolling-release), Docker Engine 29.x

## Определения

**Проблема несовместимости libc** — ситуация, когда бинарный файл, скомпилированный для GNU C Library (`glibc`), не запускается в Alpine Linux, использующем `musl libc`. Библиотеки несовместимы на бинарном уровне (ABI): разные пути к интерпретаторам, разные наборы символов, разные реализации подсистем (резолвер, локали).

**Динамический загрузчик (Dynamic Loader / Interpreter)** — программа, загружаемая ядром до старта процесса и разрешающая зависимости. Путь жёстко прописан в бинарнике (сегмент `PT_INTERPRETER`). У glibc это `/lib64/ld-linux-x86-64.so.2`, у musl — `/lib/ld-musl-x86_64.so.1`.

**gcompat** — пакет из официальных репозиториев Alpine: слой совместимости, предоставляющий заглушку glibc-загрузчика и библиотеку `libgcompat.so`, реализующую часть glibc-символов поверх musl.

**Wolfi** — «un-distro» от Chainguard: отдельный дистрибутив с форматом пакетов `apk` (как Alpine), но со всеми пакетами, скомпилированными против `glibc`.

**Типичные симптомы:**
- `./myapp: No such file or directory` — файл существует, но ядро не нашло интерпретатор `/lib64/ld-linux-x86-64.so.2`.
- `error while loading shared libraries: libc.so.6: cannot open shared object file`.
- `Error relocating ./myapp: <symbol>: symbol not found` — символ не реализован в musl/gcompat.

## Основные концепции

### Почему бинарники glibc не работают в Alpine

1. **Разные пути загрузчика.** Бинарник glibc ищет загрузчик в `/lib64/`, в то время как в Alpine musl-загрузчик находится в `/lib/` и называется `ld-musl-x86_64.so.1`.
2. **Разные наборы символов.** `glibc` содержит сотни нестандартных функций (например, `__strcat_chk`, `__pthread_register_cancel`), отсутствующих в минималистичной `musl`.
3. **Разный резолвер DNS.** `glibc` использует NSS (`/etc/nsswitch.conf`, модули `nss-mdns`, `nss-myhostname`); `musl` — прямой DNS-клиент без NSS (детали — в разделе про резолвер ниже).
4. **Разные локали.** `glibc` ожидает скомпилированные файлы локалей в `/usr/lib/locale/`; `musl` поддерживает только UTF-8 (`C.UTF-8`).

### Как работает gcompat

Пакет `gcompat` устанавливает заглушку загрузчика с именем glibc-интерпретатора (`/lib/ld-linux-x86-64.so.2` и `/lib64/ld-linux-x86-64.so.2`). При запуске glibc-бинарника заглушка перенаправляет управление на musl-загрузчик и автоматически подключает `libgcompat.so`. Sonames `libc.so.6`, `libpthread.so.0`, `libdl.so.2`, `librt.so.1` маппятся на musl.

**Ограничения (важно):**
- Не все glibc-символы реализованы — отсутствие символа даёт `Error relocating ... symbol not found`.
- Сложные приложения (Java, Python с нативными модулями, C++ с исключениями) могут падать с segfault.
- Часто требуются дополнительные пакеты: `libstdc++` (C++), `libucontext` (`makecontext`/`getcontext`/`setcontext`).
- gcompat не заменяет резолвер musl и не добавляет NSS.

### Резолвер musl и опции resolv.conf

musl отправляет запросы A и AAAA параллельно (glibc — последовательно). В сетях с некорректно настроенным IPv6 это даёт таймауты до 5 секунд.

Из строки `options` в `/etc/resolv.conf` musl поддерживает **только** `ndots:` (по умолчанию 1, макс. 15), `attempts:` (по умолчанию 2, макс. 10) и `timeout:` (по умолчанию 5, макс. 60). Опции `single-request-reopen`, `edns0`, `use-vc` **не поддерживаются** (игнорируются), `trust-ad` — no-op (всегда включён). Максимум 3 nameserver. Для объединения разных пространств имён нужен DNS-прокси (dnsmasq, CoreDNS).

### Инструментарий для диагностики

| Утилита | Пакет | Назначение |
| :--- | :--- | :--- |
| `file ./binary` | `file` | Проверка типа файла и пути к требуемому интерпретатору |
| `readelf -l ./binary \| grep interpreter` | `binutils` | Точное определение пути к загрузчику (`PT_INTERPRETER`) |
| `ldd ./binary` | — | Список зависимостей; строка `not found` — библиотека отсутствует |
| `scanelf -i ./binary` | `pax-utils` | Проверка интерпретатора (рекомендована авторами gcompat) |
| `patchelf --print-interpreter ./binary` | `patchelf` | Просмотр текущего интерпретатора |

## Требования

| Компонент | Требование |
| :--- | :--- |
| Docker Engine | 29.x (см. строку версии) |
| Репозитории | Доступ к официальным репозиториям Alpine (`gcompat`, `patchelf`, `pax-utils`) |
| Для пересборки | Исходный код приложения и toolchain (Go / Rust / gcc) |
| Для диагностики | Бинарник приложения, доступный в контейнере |

## Практические сценарии

### Сценарий 1: Диагностика — определение требуемой libc

```bash
docker run --rm -v "$PWD":/w -w /w alpine:3.24 sh -c \
  "apk add --no-cache file binutils >/dev/null && file ./myapp && readelf -l ./myapp | grep interpreter"
# → ELF 64-bit LSB executable, x86-64, ..., interpreter /lib64/ld-linux-x86-64.so.2   ← glibc
# → ELF 64-bit LSB executable, x86-64, ..., interpreter /lib/ld-musl-x86_64.so.1    ← musl
# → ELF 64-bit LSB executable, x86-64, statically linked                            ← libc не нужна
```

### Сценарий 2: Нативная пересборка (Золотой стандарт)

Самый надёжный способ — полностью статический бинарник, не зависящий от системных библиотек.

**Для Go (CGO_ENABLED=0):**
```dockerfile
FROM golang:1.27-alpine AS builder
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/myapp .

FROM alpine:3.24
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /out/myapp /usr/local/bin/myapp
ENTRYPOINT ["myapp"]
```
*`CGO_ENABLED=0` требует, чтобы приложение и зависимости не использовали cgo (нет `net` с cgo, sqlite и т.п.). `ca-certificates` нужен для HTTPS, `tzdata` — для часовых поясов.*

**Для Rust (musl target):**
```bash
apk add --no-cache musl-dev
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
```

**Для C (полная статика):**
```bash
gcc -static -o myapp-static main.c -lm
```
*Полностью статические glibc-бинарники не работают с NSS (`nsswitch.conf` игнорируется) и `dlopen()` — для glibc предпочтительна динамическая линковка; статика — прерогатива musl.*

### Сценарий 3: Использование gcompat (Официальный метод Alpine)

```dockerfile
FROM alpine:3.24
RUN apk add --no-cache gcompat libstdc++ libucontext

COPY ./my-glibc-app /usr/local/bin/
CMD ["my-glibc-app"]
```

Проверка разрешения зависимостей:
```bash
docker run --rm my-gcompat-app sh -c \
  "apk add --no-cache binutils >/dev/null && ldd /usr/local/bin/my-glibc-app"
# → libc.so.6 => /lib/ld-musl-x86_64.so.1
# → libstdc++.so.6 => /usr/lib/libstdc++.so.6
# (строки "not found" отсутствуют)
```
*Ограничение: сложные приложения (Java, Python с нативными модулями) могут падать с segfault — см. сценарий 4.*

### Сценарий 4: Переход на Wolfi / Chainguard

Wolfi — отдельный дистрибутив (не Alpine) с пакетами `apk`, скомпилированными против `glibc`. Образ `wolfi-base` содержит: `apk-tools`, `busybox`, `ca-certificates-bundle`, `chainguard-baselayout`, `glibc`, `glibc-locale-posix`, `ld-linux`.

```dockerfile
FROM cgr.dev/chainguard/wolfi-base:latest
RUN apk add --no-cache curl
CMD ["my-glibc-app"]
```
*Wolfi — rolling-release: фиксируйте образ по дайджесту (`cgr.dev/chainguard/wolfi-base@sha256:...`). Исключения: `cgr.dev/chainguard/static`, `busybox` и `git` основаны на Alpine/musl — для них существуют Wolfi-варианты с тегом `:latest-glibc`.*

### Сценарий 5: Ручная корректировка путей (patchelf)

`patchelf` **не может** сделать glibc-бинарник работающим на musl: смена интерпретатора на musl-загрузчик оставляет `DT_NEEDED` (`libc.so.6`) неразрешённым. Корректные случаи применения:

**a) Исправление пути интерпретатора для musl-бинарника** (например, после кросс-сборки с другим путём):
```bash
apk add --no-cache patchelf
patchelf --set-interpreter /lib/ld-musl-x86_64.so.1 ./myapp
patchelf --print-interpreter ./myapp
# → /lib/ld-musl-x86_64.so.1
```

**b) Добавление `libgcompat.so` в `DT_NEEDED`** (рекомендация авторов gcompat, когда символы не подхватываются автоматически):
```bash
patchelf --add-needed libgcompat.so ./myapp
```

### Сценарий 6: Локали и часовые пояса

1. **Locales:** `musl` поддерживает только UTF-8 (`C.UTF-8`). glibc-приложение, требующее `ru_RU.UTF-8`, может упасть с `setlocale: LC_ALL: cannot change locale`.
    - **Решение:** `apk add --no-cache musl-locales` (частичная поддержка) или `LANG=C.UTF-8`; для полных локалей — Wolfi (`glibc-locale-posix`) или glibc-образ.
2. **Timezones:** данные о поясах в `/usr/share/zoneinfo` отсутствуют по умолчанию.
    - **Решение:** `apk add --no-cache tzdata` (см. сценарий 2).

### Сценарий 7: Переход на glibc-based образ

Когда пересборка невозможна (проприетарный бинарник без исходников, Java/JNI, Python wheels):

```dockerfile
FROM debian:bookworm-slim
COPY ./my-glibc-app /usr/local/bin/
CMD ["my-glibc-app"]
```

## Операции и команды

| Команда | Описание |
| :--- | :--- |
| `file ./binary` | Тип файла и требуемый интерпретатор |
| `readelf -l ./binary \| grep interpreter` | Путь к загрузчику (`PT_INTERPRETER`) |
| `ldd ./binary` | Зависимости; `not found` — библиотека отсутствует |
| `scanelf -i ./binary` | Проверка интерпретатора (`pax-utils`) |
| `apk add --no-cache gcompat` | Слой совместимости glibc → musl |
| `apk add --no-cache musl-locales tzdata` | Локали и часовые пояса |
| `patchelf --set-interpreter <path> ./binary` | Смена интерпретатора (только для musl-бинарников) |
| `patchelf --add-needed libgcompat.so ./binary` | Добавление `libgcompat.so` в `DT_NEEDED` |
| `docker run --rm <image> cat /etc/os-release` | Проверка ОС целевого образа |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `No such file or directory` при запуске существующего файла | Интерпретатор `/lib64/ld-linux-x86-64.so.2` отсутствует | Сценарии 2–4 |
| `libc.so.6: cannot open shared object file` | Нет gcompat или бинарник требует glibc | `apk add gcompat` или пересборка |
| `Error relocating ... symbol not found` | Символ не реализован в gcompat | Пересборка; `patchelf --add-needed libgcompat.so`; доп. shim |
| Segfault после `apk add gcompat` | Неполная совместимость (Java, нативные модули) | Wolfi или glibc-образ |
| `setlocale: LC_ALL: cannot change locale` | Локаль не скомпилирована | `C.UTF-8`, `musl-locales`, Wolfi |
| Неверное время в контейнере | Нет `tzdata` | `apk add --no-cache tzdata` |
| Таймауты DNS ~5 с | Параллельные A/AAAA musl при сломанном IPv6 | `options timeout:2 attempts:1` (поддерживается); исправить IPv6 или DNS-прокси. `single-request-reopen` musl не поддерживает |
| `ERROR: unable to select packages: alpine-glibc` | Пакет `alpine-glibc` не существует | `apk add --no-cache gcompat` |

## Валидация

```bash
# 1. Бинарник слинкован под musl или статический
docker run --rm -v "$PWD":/w -w /w alpine:3.24 sh -c \
  "apk add --no-cache file >/dev/null && file ./myapp"
# → interpreter /lib/ld-musl-x86_64.so.1  или  statically linked

# 2. Приложение запускается в целевом образе
docker run --rm my-alpine-app --version
# → версия приложения, код возврата 0

# 3. Нет неразрешённых зависимостей (после gcompat)
docker run --rm my-gcompat-app sh -c \
  "apk add --no-cache binutils >/dev/null && ldd /usr/local/bin/myapp | grep -c 'not found'"
# → 0

# 4. Часовой пояс применён
docker run --rm my-alpine-app date
# → время в ожидаемом поясе (требует tzdata)
```

## Лучшие практики

1. **Пересборка под musl** — предпочтительный путь: `CGO_ENABLED=0` для Go, `x86_64-unknown-linux-musl` для Rust.
2. **gcompat — временное решение** для простых утилит; не используйте для production-critical сервисов без нагрузочного тестирования.
3. **Фиксируйте образы по дайджесту** — особенно Wolfi (rolling-release) и любые `:latest`-теги.
4. **Включайте `ca-certificates` и `tzdata`** в runtime-образ, даже для статических бинарников.
5. **Тестируйте в целевой среде**, а не в среде сборки: `file`/`ldd` — в целевом образе.
6. **Не смешивайте glibc и musl** в одной среде без явной необходимости.
7. **Для проприетарных бинарников** без исходников — Wolfi или `debian:bookworm-slim`.

## Дополнительная информация

### Сравнение подходов

| Метод | Совместимость | Размер | Комментарий |
| :--- | :--- | :--- | :--- |
| **Статическая линковка (musl)** | 100% (Go/Rust/C) | Минимальный | Для glibc-статики: NSS и `dlopen` не работают |
| **Wolfi / Chainguard** | 100% (glibc) | Малый | rolling-release; отдельный дистрибутив, не Alpine |
| **gcompat** | Частичная (зависит от символов) | Минимальный | Не все символы; segfault для сложных приложений |
| **debian:bookworm-slim** | 100% (glibc) | Средний (~30–80 МБ) | Стандарт индустрии |

### Граничные случаи

- **Java:** JVM с JNA/JNI требует glibc — используйте glibc-based образ или Wolfi.
- **Python:** многие пакеты (NumPy, Pandas) не имеют pre-built wheels для Alpine — компиляция из исходников увеличивает время сборки и размер образа.
- **Node.js:** нативные модули (`sharp`, `bcrypt`, `sqlite3`) требуют `python3`, `make`, `g++` в Alpine.
- **Статический glibc:** NSS не работает — разрешение имён только через `/etc/hosts` или IP-адреса.
- **musl:** максимум 3 nameserver в `resolv.conf`; для объединения пространств имён — DNS-прокси.

### Очистка

```bash
docker rm -f my-test-app
docker image prune
```

### Связанные темы

- **[Сравнение Glibc и Musl](../../Linux/Core/glibc_vs_musl.md)** — теоретическая база различий (ABI, потоки, аллокаторы, локали).
- **[Dockerfile для Alpine Linux](../Dockerfile/dockerfile_alpine_linux.md)** — общие принципы работы с дистрибутивом, multi-stage, apk.
- **[Проблема DNS ndots:5](../../Networking/Protocols/DNS/dns_resolution.md)** — почему Alpine тормозит в Kubernetes.
- **[Диагностика DNS в контейнерах](../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — решение проблем с резолвом.
