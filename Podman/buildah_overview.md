# Buildah: Концепции и практика сборки образов

## Определения

**Buildah** — специализированный инструмент командной строки для сборки образов контейнеров, полностью соответствующих стандартам **OCI (Open Container Initiative)**. Buildah спроектирован как модульный инструмент, который не требует фонового демона и предоставляет низкоуровневый ("хирургический") доступ к файловой системе и метаданным образа.

**Daemonless** — архитектура без постоянно запущенного фонового процесса. Buildah работает по модели fork-exec: процесс запускается, выполняет конкретную операцию (например, копирование файла или коммит слоя) и немедленно завершается.

**Working Container (Рабочий контейнер)** — это временная сущность в локальном хранилище, представляющая собой распакованную файловую систему базового образа с наложенным на нее записываемым слоем. Buildah манипулирует этим слоем, позволяя "закоммитить" его в итоговый образ в любой момент.

**Extreme Distroless** — методика создания минимальных образов (часто на базе `scratch`), в которых отсутствуют даже базовые утилиты ОС (пакетные менеджеры, оболочки, coreutils).

**Containerfile** — файл описания сборки, синтаксически совместимый с `Dockerfile`. Buildah автоматически ищет в контексте сборки `Containerfile`, а при его отсутствии — `Dockerfile`. Дополнительно поддерживаются heredoc-синтаксис для `RUN`/`COPY`/`ADD` и файл исключений `.containerignore` (аналог `.dockerignore`).

**Build context (Контекст сборки)** — каталог, из которого инструкции `COPY`/`ADD` получают исходные файлы; исключаемые файлы задаются в `.dockerignore`/`.containerignore`.

**scratch** — пустой образ без единого слоя. Используется как отправная точка для сборки "с нуля" и для distroless-образов: в него копируются только статически скомпилированные бинарники и необходимые библиотеки.

Проект развивается в организации `containers`. Актуальная стабильная версия на момент написания — **v1.45.0** (июль 2026). Репозиторий переехал из `github.com/containers/buildah` в `github.com/podman-container-tools/buildah` (старый адрес работает через редирект).

---

## Основные концепции

### Ключевые возможности

- **Бездемонная сборка (daemonless):** не требует запущенного Docker-демона, работает без привилегий root в пользовательском пространстве.
- **Скриптовая сборка:** низкоуровневый контроль над образом через `from`/`run`/`copy`/`config`/`commit`.
- **Dockerfile-совместимость:** `buildah build` (прежнее имя `buildah bud`) с поддержкой multi-stage, build-args и кэширования слоев.
- **Контроль слоев:** множество операций в одном рабочем контейнере и единственный `commit` в конце — итоговый образ с минимальным числом слоев; `--squash` сводит все слои в один.
- **Монтирование rootfs на хост:** `buildah mount` позволяет править файловую систему образа как обычный каталог (установка софта инструментами хоста).
- **Multi-arch:** создание и публикация манифест-списков (`buildah manifest`), кросс-сборка через `--platform`.
- **OCI-форматы:** поддержка транспортов `dir:`, `oci:`, `oci-archive:`, `docker-archive:` и общего хранилища `containers-storage:` с Podman.
- **Rootless:** полная поддержка безрутового режима через user namespaces и `buildah unshare`.
- **Встроенная генерация SBOM:** `buildah build --sbom` собирает Software Bill of Materials (например, через syft) непосредственно при сборке.

### Жизненный цикл рабочего контейнера

1. **Создание:** `buildah from <базовый образ>` — создается рабочий контейнер; команда возвращает его имя (обычно случайная строка), которое нужно сохранить в переменную и переиспользовать в последующих командах.
2. **Модификация:** `buildah run`, `buildah copy`, `buildah add`, `buildah mount`/`buildah unmount`, `buildah config` — изменение файловой системы и метаданных без создания слоев.
3. **Фиксация:** `buildah commit` — состояние рабочего контейнера записывается в хранилище как новый образ.
4. **Очистка:** `buildah rm` — удаление рабочего контейнера (флаг `--rm` у `commit` делает это автоматически).

Важно: рабочий контейнер не предназначен для запуска долгоживущих процессов — `buildah run` выполняет команду и завершается, изменения остаются в записываемом слое.

### Два режима сборки

| Режим | Команда | Когда использовать |
| :--- | :--- | :--- |
| Dockerfile-сборка | `buildah build` (алиас `bud`) | Перенос существующих Dockerfile, стандартные пайплайны, кэширование слоев. |
| Скриптовая сборка | `from`/`run`/`copy`/`config`/`commit` | Distroless-образы, гранулярный контроль слоев, сложная логика, установка через хост. |

`buildah bud` сохранен как алиас для обратной совместимости; в актуальной документации и CI/CD рекомендуется использовать `buildah build`.

По умолчанию `buildah build` НЕ кэширует промежуточные слои (`--layers=false`), в отличие от `podman build`, где кэширование включено по умолчанию. Для включения кэша используйте `--layers=true` или переменную окружения `BUILDAH_LAYERS=true`.

### Справочник основных команд

| Команда | Назначение |
| :--- | :--- |
| `buildah from <image>` | Создать рабочий контейнер из базового образа. |
| `buildah run <ctr> -- <cmd>` | Выполнить команду внутри рабочего контейнера. |
| `buildah copy <ctr> <src> <dest>` | Скопировать файлы/каталоги из контекста в образ. |
| `buildah add <ctr> <src> <dest>` | Копирование с поддержкой URL и авто-распаковки архивов (tar/zip). |
| `buildah mount <ctr>` / `buildah unmount` | Смонтировать rootfs как каталог на хосте / размонтировать. |
| `buildah config` | Установить метаданные образа (entrypoint, env, port, user, labels). |
| `buildah commit` | Записать рабочий контейнер как образ. |
| `buildah build` (алиас `bud`) | Сборка из Dockerfile/Containerfile. |
| `buildah push <image> <transport>` | Опубликовать образ в реестр или транспорт назначения. |
| `buildah manifest create/add/push` | Работа с multi-arch манифест-списками. |
| `buildah images` / `buildah containers` | Список локальных образов / рабочих контейнеров. |
| `buildah rm` / `buildah rmi` | Удалить рабочий контейнер / локальный образ. |
| `buildah unshare` | Войти в user namespace для отладки и операций в rootless-режиме. |
| `buildah login` / `buildah logout` | Управление учетными данными реестров. |

### Уникальные преимущества Buildah (за пределами Dockerfile)

Buildah предоставляет возможности, которые технически невозможно или крайне сложно реализовать через стандартный `docker build`.

#### 1. Изолированная установка через `buildah mount`
В Docker для установки софта (`RUN apt install`) вы обязаны иметь пакетный менеджер *внутри* образа.
- **Решение Buildah:** Вы можете смонтировать файловую систему будущего образа как папку на хосте и использовать пакетный менеджер **хоста** для установки софта внутрь образа.
- **Практический пример:**
  ```bash
  # Создаем пустой контейнер
  newcontainer=$(buildah from scratch)
  # Монтируем его ФС в директорию на хосте
  scratchmnt=$(buildah mount $newcontainer)
  
  # Установка софта через менеджер пакетов хоста (dnf) прямо в точку монтирования образа
  # В итоговом образе НЕ будет dnf, rpm или их зависимостей
  # --releasever указывает на актуальный релиз Fedora (на момент написания — 44)
  dnf install --installroot=$scratchmnt --releasever=44 python3-minimal -y
  
  # Очистка и фиксация
  buildah unmount $newcontainer
  buildah commit $newcontainer my-pure-python
  ```
- **Результат:** Образ содержит только бинарные файлы Python и библиотеки. Поверхность атаки минимизирована, так как в образе нет инструментов для скачивания или компиляции вредоносного кода.

#### 2. Полный контроль над гранулярностью слоев
- **Проблема Docker:** Каждая инструкция (`COPY`, `RUN`) создает слой. Объединение команд через `&&` — единственный способ уменьшить их количество, что портит читаемость.
- **Решение Buildah:** Вы можете выполнить сотни операций (копирование, изменение прав, удаление временных файлов) в рамках одного рабочего контейнера и вызвать `buildah commit` только один раз в самом конце.
- **Результат:** Итоговый образ имеет ровно один слой, при этом сборочный скрипт остается чистым и структурированным.

#### 3. Сборка «снаружи» (Out-of-band manipulation)
- **Проблема Docker:** Код сборки выполняется *внутри* контейнера. Это требует запуска процессов из базового образа, что может быть небезопасно.
- **Решение Buildah:** Вы можете манипулировать файлами образа снаружи, просто копируя их в точку монтирования. Вам вообще не обязательно запускать какой-либо код из образа во время сборки.
- **Результат:** Максимальная безопасность при работе с образами из недоверенных источников.

### Сравнение механизмов сборки

| Характеристика | Buildah (CLI) | Podman Build / `bud` | Docker BuildKit |
| :--- | :--- | :--- | :--- |
| **Формат описания** | Скрипты (Bash/Python/etc) | Dockerfile / Containerfile | Dockerfile + расширения |
| **Управление слоями** | Ручное (через `commit`) | Автоматическое | Автоматическое + кэш |
| **OCI Manifests** | Нативная поддержка | Через `podman manifest` | Через `buildx` |
| **Сборка без демона** | Полная (Daemonless) | Полная (через код Buildah) | Требует `buildkitd` |
| **Монтирование ФС** | Да (`buildah mount`) | Нет | Только внутри `RUN` |
| **Кэширование слоев** | `--layers=true`, распределенный кэш `--cache-from`/`--cache-to` | Включено по умолчанию | Включено + registry cache |
| **Rootless-сборка** | Полная поддержка | Полная поддержка | Требует настройки rootless buildkit |
| **SBOM-генерация** | Встроенная (`--sbom`, syft) | Встроенная (`podman build --sbom`) | Отдельный плагин `docker sbom` |

---

## Настройка и внедрение в Production

### 1. Rootless-режим и Storage Driver

В безрутовом режиме Buildah часто сталкивается с ограничениями ядра на монтирование. Для стабильной работы необходимо использовать **fuse-overlayfs**.

**Файл конфигурации:** `~/.config/containers/storage.conf` (создайте, если отсутствует):

```ini
[storage]
# Использование overlay драйвера (стандарт OCI)
driver = "overlay"

[storage.options]
# Программа монтирования для работы без прав root
mount_program = "/usr/bin/fuse-overlayfs"
# Опция для ускорения работы в некоторых файловых системах
mountopt = "nodev,metacopy=on"
```

Особенности rootless-режима:
- Требуются включенные user namespaces в ядре (на большинстве дистрибутивов включены по умолчанию).
- На ядрах 5.11+ доступен нативный rootless-overlay; `fuse-overlayfs` остается универсальным запасным вариантом.
- Для операций, требующих привилегий внутри user namespace (например, монтирование), используйте обертку `buildah unshare`:
  ```bash
  # Выполнить команду в user namespace Buildah (аналог root внутри namespace)
  buildah unshare -- dnf install --installroot=$scratchmnt python3-minimal -y
  ```
- Локальные данные (образы, контейнеры) в rootless-режиме хранятся в `~/.local/share/containers/storage`, конфигурация — в `~/.config/containers/`. Подробнее в [Podman: Rootless](./podman_rootless.md).

### 2. Сборка в Kubernetes (Image-in-Image)

Для запуска Buildah внутри Pod'а (например, в GitLab Runner или Tekton) требуются специфические настройки изоляции. Это безопасная альтернатива Docker-in-Docker: не требуется привилегированный демон и доступ к сокету хоста.

**Пример манифеста (фрагмент SecurityContext):**

```yaml
spec:
  containers:
  - name: buildah-builder
    image: quay.io/buildah/stable:v1.45
    securityContext:
      # Требуются для корректного маппинга UID/GID в User Namespaces
      capabilities:
        add: ["SETUID", "SETGID"]
    env:
    - name: STORAGE_DRIVER
      value: "overlay"
    - name: BUILDAH_ISOLATION
      value: "chroot" # Важно для работы внутри контейнера
    volumeMounts:
    - name: varlibcontainers
      mountPath: /var/lib/containers
  volumes:
  - name: varlibcontainers
    emptyDir: {}
```

Примечания к развертыванию в Kubernetes:
- Запиннивайте версию образа (`quay.io/buildah/stable:v1.45`) вместо `:latest` для воспроизводимости сборок.
- `BUILDAH_ISOLATION=chroot` позволяет Buildah работать без монтирования и без дополнительных capability; `chroot` не требует прав root.
- В полностью безрутовом сценарии (user namespace + `buildah unshare`) privileged-капабилити не нужны, но требуется поддержка userns в кластере.
- Хранилище `emptyDir` эфемерно: для сохранения кэша слоев между запусками монтируйте PVC или используйте распределенный кэш (`--cache-to`).

---

## Практические сценарии

### 1. Установка

```bash
# Fedora / RHEL / Rocky Linux
sudo dnf install -y buildah

# Debian / Ubuntu
sudo apt update && sudo apt install -y buildah

# macOS (Homebrew)
brew install buildah

# Контейнерный образ (для CI/CD и локальных проверок)
docker run --rm quay.io/buildah/stable:v1.45 buildah --version

# Проверка установки и версии
buildah --version
# → buildah version 1.45.0 (image-spec 1.1.0, runtime-spec 1.2.0)
```

### 2. Базовый цикл сборки через скрипт

```bash
#!/bin/bash
# 1. Создаем рабочий контейнер
container=$(buildah from alpine:latest)

# 2. Выполняем действия (без создания промежуточных слоев)
buildah run $container -- apk add --no-cache nodejs npm
buildah copy $container ./package.json /app/
buildah run $container --workingdir /app -- npm install
buildah copy $container ./src /app/src

# 3. Настраиваем метаданные (Config)
buildah config --author "DevOps Team" \
               --port 3000 \
               --env NODE_ENV=production \
               --entrypoint '["node", "/app/src/index.js"]' \
               $container

# 4. Фиксируем образ (создается единственный слой со всеми изменениями)
buildah commit --rm $container my-node-app:v1
# → <image-id>
```

### 3. Многоэтапная сборка (Multi-stage) в Bash

Buildah позволяет копировать файлы между любыми образами на хосте без ограничений, накладываемых синтаксисом Dockerfile.

```bash
# Этап 1: Сборка артефакта (Builder)
builder=$(buildah from golang:1.26-alpine)
buildah run $builder -- go build -o /app/server main.go
b_mnt=$(buildah mount $builder)

# Этап 2: Финальный образ (Runtime)
runtime=$(buildah from alpine:latest)
r_mnt=$(buildah mount $runtime)

# Копируем бинарник напрямую между смонтированными путями
cp ${b_mnt}/app/server ${r_mnt}/usr/bin/server

# Финализация
buildah unmount $runtime
buildah commit $runtime my-app-prod
buildah rm $builder $runtime
```

Аналогичный результат достигается через Dockerfile-сборку — см. следующий сценарий.

### 4. Сборка из Dockerfile/Containerfile

Канонический режим для переноса существующих Dockerfile. Поддерживает multi-stage, build-args, heredoc и кэширование.

**Пример Containerfile (multi-stage):**

```dockerfile
FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY . .
RUN go build -o /app/server main.go

FROM alpine:latest
COPY --from=builder /app/server /usr/bin/server
EXPOSE 8080
ENTRYPOINT ["/usr/bin/server"]
```

**Команды сборки:**

```bash
# Сборка с тегом (Containerfile или Dockerfile из текущего каталога)
buildah build -t my-app:v1 .
# → STEP 1/5: FROM golang:1.26-alpine AS builder
# → STEP 2/5: WORKDIR /src
# → ...
# → COMMIT my-app:v1

# Включение кэша промежуточных слоев (повторные сборки ускоряются)
buildah build --layers=true -t my-app:v1 .

# Сборка конкретного этапа multi-stage
buildah build --target builder -t my-app:builder .

# Передача build-аргументов (файл и CLI объединяются, CLI имеет приоритет)
buildah build --build-arg VERSION=1.2.0 --build-arg-file .build-args -t my-app:v1 .

# Сборка для другой платформы (для RUN требуется qemu-user-static на хосте)
buildah build --platform linux/arm64 -t my-app:arm64 .

# Кросс-сборка в один multi-arch манифест
buildah build --manifest my-app:latest --platform linux/amd64,linux/arm64 .

# Детерминированная сборка: одинаковый дайджест для одинаковых входов
buildah build --timestamp 0 -t my-app:v1 .
```

### 5. Кэширование промежуточных слоев

В отличие от BuildKit, Buildah кэширует слои в локальном хранилище `containers-storage:` (по умолчанию выключено) и дополнительно поддерживает распределенный кэш в реестрах.

```bash
# Локальный кэш промежуточных слоев
buildah build --layers=true -t my-app:v1 .

# Или через переменную окружения (действует на все сборки)
export BUILDAH_LAYERS=true

# Распределенный кэш: промежуточные слои публикуются и извлекаются из реестра.
# В отличие от BuildKit, не раздувает итоговый образ промежуточными изображениями
# (подход аналогичен kaniko).
buildah build --layers=true \
    --cache-to registry.example.com/my-app/cache \
    --cache-from registry.example.com/my-app/cache \
    --cache-ttl 24h \
    -t my-app:v1 .

# Сохранение промежуточных этапов multi-stage для последующих сборок
buildah build --layers=true --save-stages -t my-app:v1 .
```

### 6. Публикация образов в реестр

```bash
# Авторизация в реестре (учетные данные в $XDG_RUNTIME_DIR/containers/auth.json)
buildah login registry.example.com -u user -p password

# Публикация локального образа
buildah push my-app:v1 docker://registry.example.com/team/my-app:v1

# Публикация с явными учетными данными и без проверки TLS (внутренний реестр)
buildah push --creds user:pass --tls-verify=false my-app:v1 docker://internal-registry.local/team/my-app:v1

# Сохранение дайджеста результата в файл (для CI/CD и аудита)
buildah push --digestfile image.digest my-app:v1 docker://registry.example.com/team/my-app:v1

# Выбор алгоритма сжатия слоев при передаче (gzip | zstd)
buildah push --compression-format zstd my-app:v1 docker://registry.example.com/team/my-app:v1

# Сохранение в архив, совместимый с docker load
buildah push my-app:v1 docker-archive:my-app.tar:my-app:v1

# Экспорт в OCI Layout каталог (для air-gapped сред)
buildah push my-app:v1 oci:my-app-oci:v1
```

### 7. Distroless-образ на базе scratch

Реализация методики Extreme Distroless: финальный образ содержит только статический бинарник без слоев, оболочек и пакетных менеджеров.

```bash
# Сборка статического бинарника в этапе builder
builder=$(buildah from golang:1.26-alpine)
buildah run $builder -- go build -o /static-app main.go
b_mnt=$(buildah mount $builder)
cp $b_mnt/static-app ./static-app
buildah rm $builder

# Финальный образ на scratch: только бинарник и метаданные
scratch=$(buildah from scratch)
buildah copy $scratch ./static-app /app
buildah config --entrypoint '["/app"]' --user 65535 $scratch
buildah commit $scratch my-distroless-app
```

### 8. Работа с Multi-arch манифестами

Buildah — основной инструмент для создания манифестов, объединяющих образы для разных платформ под одним тегом.

```bash
# Создание пустого манифеста
buildah manifest create my-app:latest

# Добавление архитектур (может быть как локальный образ, так и удаленный)
buildah manifest add my-app:latest docker://my-app-amd64:v1
buildah manifest add my-app:latest docker://my-app-arm64:v1

# Пуш манифеста со всеми архитектурами в реестр
buildah manifest push --all my-app:latest docker://registry.com/my-app:latest

# Инспекция манифеста (список платформ)
buildah manifest inspect my-app:latest

# Сборка multi-arch манифеста напрямую из Containerfile
buildah build --manifest my-app:latest --platform linux/amd64,linux/arm64 .
```

### 9. Управление локальным хранилищем

```bash
# Список локальных образов
buildah images
# → REPOSITORY   TAG   IMAGE ID   CREATED   SIZE

# Список рабочих контейнеров
buildah containers

# Удаление всех рабочих контейнеров
buildah rm -a

# Удаление образов
buildah rmi my-app:v1

# Очистка зависших промежуточных образов (слои от --layers)
buildah images --filter dangling=true
buildah rmi --prune
```

---

## Дополнительная информация

### Связанные разделы
- **[Rootless режим в Podman](./podman_rootless.md)** — детали работы `fuse-overlayfs` и user namespaces.
- **[Skopeo: Транспортировка](./skopeo_overview.md)** — перемещение образов между реестрами и транспортами.
- **[Интеграция с Ansible](../Ansible/ansible_buildah_image_building.md)** — автоматизация сборки через плейбуки.

### Ссылки
- **[Официальный репозиторий Buildah](https://github.com/podman-container-tools/buildah)**
- **[Анонсы релизов Buildah](https://buildah.io/releases/)**

### Рекомендации
- Используйте `buildah build` (алиас `bud`) для простых задач и совместимости с существующими Dockerfile; включайте `--layers=true` для ускорения повторных сборок.
- Переходите на скриптовую сборку Buildah, если вам нужны сверхмалые образы (Distroless) или сложная логика на этапе билда.
- Для отладки используйте `buildah unshare`, чтобы войти в пространство имен пользователя и увидеть файловую систему так же, как её видит Buildah.
- В CI/CD вместо Docker-in-Docker используйте Buildah: нет привилегированного демона и сокета, сборка выполняется в user space. Подробности — в сценарии сборки в Kubernetes.
