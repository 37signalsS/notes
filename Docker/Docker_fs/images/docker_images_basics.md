# Docker: основы образов

## Предварительные требования

Перед выполнением практических сценариев убедитесь, что окружение готово:

- **Docker Engine** версии **24.0+** (BuildKit включён как рантайм сборки по умолчанию с 23.0+). Проверка: `docker version --format '{{.Server.Version}}'` → `27.3.1`.
- **Доступ к демону**: сокет `/var/run/docker.sock` (штатный) либо переменная `DOCKER_HOST`. Без прав возникает `permission denied while trying to connect to the Docker daemon socket`.
- **Реестр (для pull/push)**: доступ к Docker Hub, Harbor, ECR, GCR или локальному реестру. Для приватных — предварительный `docker login`. См. **[Реестры Docker](../../docker_registries.md)**.
- **Multi-arch сборка**: `docker buildx` (встроен с 23.0). Проверка: `docker buildx version`. Для кросс-платформенной эмуляции — QEMU:
  ```bash
  docker run --privileged multiarch/qemu-user-static --reset -p yes
  # → (выводится строка регистрации каждой архитектуры; ошибок нет)
  docker buildx ls
  # → NAME/NODE      DRIVER/ENDPOINT         STATUS    BUILDKIT  PLATFORMS
  # → default        docker-container                  running   v0.16.0    linux/amd64,linux/arm64,...
  ```
- **Утилиты хоста для диагностики**: `jq` (парсинг JSON из `inspect`), `dive` (интерактивный просмотр слоёв). Опционально, но рекомендуется.

## Определения

- **Образ (Image)** — неизменяемый (read-only) пакет, содержащий всё необходимое для запуска приложения: программный код, среду выполнения, библиотеки, переменные окружения и конфигурационные файлы. Образ является «чертежом» или шаблоном для создания контейнеров.
- **Слой (Layer)** — образ состоит из упорядоченного набора слоев файловой системы. Каждый слой представляет собой результат выполнения одной инструкции в `Dockerfile` (например, `RUN`, `COPY`) и фиксирует изменения относительно предыдущего состояния.
- **Тег (Tag)** — человекочитаемый изменяемый псевдоним для конкретной версии образа (например, `nginx:1.27` или `myapp:stable`). Один и тот же тег может со временем указывать на разные образы (mutable reference).
- **Дайджест (Digest)** — уникальный неизменяемый идентификатор образа, представляющий собой криптографический хеш **SHA256 (Secure Hash Algorithm 256-bit)** его манифеста. Гарантирует побайтовую идентичность артефакта.
- **Манифест (Manifest)** — JSON-файл, описывающий образ: его слои, архитектуру и метаданные.
- **Image ID** — внутренний идентификатор образа в локальном хранилище. Это SHA256-хеш **конфигурации образа** (`config.json`), а не манифеста. Отображается в сокращённом (12 hex) и полном (64 hex) виде. Важно не путать с дайджестом: дайджест адресует образ в реестре (по манифесту), а Image ID — локально (по конфигурации); они вычисляются от разных объектов и обычно не совпадают.
- **Репозиторий (Repository)** — именованная коллекция образов в реестре (например, `library/nginx` или `registry.example.com/team/app`). Тег уточняет конкретную версию внутри репозитория.
- **Реестр (Registry)** — сервер хранения и распространения образов (Docker Hub, Harbor, ECR, GCR). См. **[Реестры Docker](../../docker_registries.md)**.
- **Union Mount / Copy-on-Write (CoW)** — механизм наложения слоёв: все слои образа (read-only) монтируются как единая файловая система, а любая запись контейнера перехватывается в отдельный тонкий записываемый слой. Благодаря этому десятки контейнеров могут делить один и тот же read-only образ, не изменяя его.
- **Кэш сборки (Build cache)** — механизм переиспользования уже собранных слоёв между запусками `docker build`. Ключ к скорости итераций: если инструкция и её контекст не изменились, Docker берёт слой из кэша вместо повторного выполнения.

## Основные концепции

### Анатомия образа: слои и хранилище

Образ представляет собой стек неизменяемых слоев, объединенных в единое представление.

- **Слоеная структура**: Каждая команда `RUN`, `COPY`, `ADD` создает новый слой. Если слой уже существует (например, при повторной сборке), Docker переиспользует его из кэша.
- **Драйверы хранения**: Объединение слоев выполняется драйвером (обычно **[OverlayFS](../docker_overlayfs.md)**). Все слои образа доступны только для чтения; при запуске контейнера сверху добавляется тонкий записываемый слой (writable layer).
- **containerd image store**: В современных версиях Docker (24.0+) доступно новое хранилище образов на базе `containerd`. Оно обеспечивает нативную поддержку многоархитектурных образов в локальном хранилище и лучшую интеграцию с экосистемой Kubernetes.
- **Адресуемость по содержимому (Content-Addressable Storage)**: слои и образы идентифицируются по хешу их содержимого. Поэтому общие слои между разными образами физически хранятся один раз (дедупликация), что экономит место.

### Жизненный цикл образа

Типичный путь артефакта: **build** (`docker build`) → **tag** (`docker tag`) → **push** (`docker push`) → **pull** (`docker pull`) → **run** (`docker run`) → при необходимости **rmi / prune** (удаление). Образ остаётся неизменным на всех этапах; меняются только ссылки (теги) и размещение (локальный кеш ↔ реестр).

### Многоархитектурные образы (Multi-platform)

Современные образы часто поставляются как **Manifest Lists** (или OCI Index). Один тег (например, `python:3.12-slim`) может ссылаться на разные образы для `amd64`, `arm64`, `s390x` и других платформ. Docker автоматически выбирает нужный вариант в зависимости от архитектуры хоста.

### Тег против дайджеста: стабильность развертывания

Разграничение этих понятий критично для надежности (Reliability):
- **Тег (`ubuntu:24.04`)**: Может измениться. Если поставщик обновит образ и переназначит тег, `docker pull` скачает новую версию, что может нарушить работу приложения.
- **Дайджест (`ubuntu@sha256:...`)**: Никогда не меняется. Использование дайджеста гарантирует, что в любой среде (dev, stage, prod) будет запущен один и тот же бинарный артефакт.

## Практические сценарии

### Сценарий 1: Исследование структуры слоев

Команда `docker history` показывает этапы сборки и размер каждого слоя.

```bash
docker history nginx:latest
# → IMAGE          CREATED        CREATED BY                                      SIZE
# → <missing>      3 weeks ago    /bin/sh -c #(nop)  CMD ["nginx" "-g" "daem…      0B
# → <missing>      3 weeks ago    /bin/sh -c #(nop) COPY file:e6e33c7e0e754b…      4.62kB
# → <missing>      3 weeks ago    /bin/sh -c #(nop) ADD file:abc123 in /           142MB
```
*Примечание:* Метка `<missing>` в выводе современных версий Docker (BuildKit) означает, что слои были собраны на другой машине или загружены из реестра — локально доступны только метаданные промежуточных шагов.

### Сценарий 2: Получение и использование дайджеста

Для фиксации конкретной версии образа в манифестах Kubernetes или Docker Compose.

```bash
# Получение полного RepoDigest
docker inspect nginx:latest --format '{{index .RepoDigests 0}}'
# → nginx@sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45

# Запуск по дайджесту
docker run -d nginx@sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45
# → 3f1c... (ID запущенного контейнера)
```

### Сценарий 3: Инспекция многоархитектурных манифестов

Чтобы увидеть, какие платформы поддерживает образ в реестре, используется команда `docker manifest inspect`.

```bash
docker manifest inspect python:3.12-slim
# → {
# →    "schemaVersion": 2,
# →    "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
# →    "manifests": [
# →      { "platform": { "architecture": "amd64", "os": "linux" }, "digest": "sha256:..." },
# →      { "platform": { "architecture": "arm64", "os": "linux" }, "digest": "sha256:..." }
# →    ]
# → }
```

### Сценарий 4: Метаданные и их влияние

Инструкция `LABEL` добавляет метаданные (версия, автор, описание). Хотя `LABEL` не создает тяжелых слоев в файловой системе, она изменяет конфигурацию образа (`config.json`), что приводит к изменению его дайджеста.

Подробный разбор влияния `LABEL` на дайджест и воспроизводимость сборок — см. **[Инструкции Dockerfile: Базовый образ и Метаданные](../../Dockerfile/Instructions/base_image_and_metadata.md#инструкция-label-аннотирование-образа)**.

### Сценарий 5: Сборка образа и просмотр слоёв

```bash
docker build -t myapp:1.0 .
# → [+] Building 12.3s (8/8) FINISHED
# →  => [internal] load build definition from Dockerfile          0.1s
# →  => => writing image sha256:9f86d081884c...                    0.0s
# →  => => naming to docker.io/library/myapp:1.0                   0.0s

docker history myapp:1.0
# → IMAGE      CREATED       CREATED BY                                      SIZE      COMMENT
# → 9f86...    2 min ago     /bin/sh -c #(nop)  CMD ["python" "-m" "app"]   0B
# → <missing>  2 min ago     /bin/sh -c pip install -r requirements.txt     38.2MB
# → <missing>  5 min ago     /bin/sh -c #(nop) COPY . .                     12.4MB

docker images myapp
# → REPOSITORY   TAG       IMAGE ID       CREATED     SIZE
# → myapp        1.0       9f86d081884c   2 min ago   920MB
```
Инструкции выполняются сверху вниз; каждая создаёт слой. Если `Dockerfile` не менялся, повторный `docker build` берёт слои из кэша (строки `CACHED`).

### Сценарий 6: Тегирование и публикация в реестр

Тег — это лишь указатель (alias) на существующий Image ID; `docker push` отправляет в реестр недостающие слои и манифест.

```bash
docker tag myapp:1.0 registry.example.com/team/myapp:1.0
# → (вывод отсутствует — создан alias на тот же Image ID)

docker push registry.example.com/team/myapp:1.0
# → The push refers to repository [registry.example.com/team/myapp]
# → 3b8a...: Pushed
# → a1c2...: Pushed
# → 1.0: digest: sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45 size: 41234567
```

### Сценарий 7: Инспекция метаданных, Image ID и дайджеста

```bash
# Локальный идентификатор (хеш config.json)
docker inspect --format '{{.Id}}' myapp:1.0
# → sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08

# Дайджест в реестре (после push), адресует манифест
docker image inspect --format '{{index .RepoDigests 0}}' myapp:1.0
# → registry.example.com/team/myapp@sha256:f6a02b669bf8e59b20d361e148045a5f15915a7704b4df915340156f4a883a45
```
`{{.Id}}` (config hash) и `RepoDigest` (manifest hash) — разные сущности; для воспроизводимого деплоя используйте дайджест из реестра.

### Сценарий 8: Многоархитектурная сборка через buildx

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:multi --push .
# → [+] Building 45.2s ...
# →  => => pushing manifest for registry.example.com/team/myapp:multi
# →  => => pushing layer for linux/amd64
# →  => => pushing layer for linux/arm64

docker buildx imagetools inspect myapp:multi
# → Name: docker.io/library/myapp:multi
# → MediaType: application/vnd.docker.distribution.manifest.list.v2+json
# → Manifests:
# →   Platform: linux/amd64
# →   Platform: linux/arm64
```

### Сценарий 9: Явное управление кэшем сборки

```bash
# Полная пересборка без использования кэша
docker build --no-cache -t myapp:clean .
# → [+] Building 38.1s (8/8) FINISHED
```
Для ускорения повторяющихся шагов (зависимости пакетных менеджеров) в BuildKit используется монтирование кэша: `RUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt` — кэш сохраняется между сборками вне слоёв образа.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `permission denied while trying to connect to the Docker daemon socket` | Пользователь не в группе `docker` | `sudo usermod -aG docker $USER` и перелогиньтесь, либо запускайте через `sudo` (временно) |
| `pull access denied for X, repository does not exist` | Неверное имя/тег или нет доступа | проверьте имя реестра и тега; `docker login`; `docker manifest inspect X` |
| `no matching manifest for linux/arm64/v8` | Образ отсутствует для платформы | используйте `docker buildx build --platform=linux/arm64` или `--platform` при `run`/`pull` |
| `denied: requested access to the resource is denied` (при push) | Нет авторизации или неверный репозиторий | `docker login`; тег должен содержать имя реестра: `registry/myapp:1.0` |
| `toomanyrequests: Rate limited` (Docker Hub) | Превышен анонимный лимит pull | `docker login` (увеличивает лимит) либо используйте зеркало/кэш-реестр |
| `image with reference ... already exists` (при `tag`) | Тег уже занят другим Image ID | `docker rmi <repo>:<tag>` перед повторным `tag` (удаляет только ссылку, не слои) |
| `<missing>` в `docker history` | Сборка через BuildKit / импорт из реестра | Норма: метаданные промежуточных слоёв недоступны локально; функционально не влияет |
| `failed to solve: ...` при buildx multi-arch | Нет эмуляции QEMU | зарегистрируйте бинформаты: `docker run --privileged multiarch/qemu-user-static --reset -p yes` |

## Рекомендации и очистка

**Лучшие практики:**
- Пините базовые образы по дайджесту (`FROM alpine@sha256:...`), а не по `latest` или плавающему минорному тегу — это единственная гарантия воспроизводимости. См. **[Версионирование и тегирование](../../Docker_registries/image_versioning_and_tagging.md)**.
- Используйте multi-stage сборки для уменьшения размера и поверхности атаки. Подробнее — **[Оптимизация сборки Docker-образов](../../Dockerfile/Docker_best_practices/build_optimization.md)**.
- Не помещайте секреты в образ: даже удалённые в следующем `RUN` файлы физически остаются в нижних слоях (см. **[Управление слоями](./layer_management.md)**, раздел о whiteout). Используйте BuildKit secrets mount (`RUN --mount=type=secret`) или внешние Secret-механизмы.
- Для переноса образов в изолированные контуры — `docker save`/`load` или `skopeo` (см. **[Перенос и экспорт образов](./diagnostics_transfer.md)**).
- Регулярно отслеживайте занятое место: `docker system df`.

**Очистка окружения (revert / cleanup):**
```bash
# Удалить конкретный тег/образ по Image ID (удаляет только ссылки и неиспользуемые слои)
docker rmi myapp:1.0
# → Untagged: myapp:1.0
# → Deleted: sha256:9f86d081884c...

# Удалить «висячие» образы (без тегов) — освобождает место общих слоёв
docker image prune -f
# → Deleted Images: ...  Total reclaimed space: 1.2GB

# Удалить ВСЕ неиспользуемые образы (не запущенные ни в одном контейнере)
docker image prune -a -f
# → Total reclaimed space: 5.7GB

# Полная очистка: образы, контейнеры, сети, кэш сборки
docker system prune -a --volumes -f
```
Любую очистку через `prune`/`rmi` можно откатить только повторным `docker pull` или `docker build` — удалённые слои и образы безвозвратны.

## Особые случаи и ограничения

- **`latest` — антипаттерн**: мутабельный тег, не гарантирует одинаковый контент; запрещён в продакшене.
- **Тег можно переназначить в реестре**: `docker pull myapp:1.0` в разное время может вернуть разный контент. Дайджест — единственная неизменная гарантия.
- **Image ID ≠ RepoDigest**: локально образ адресуется по ID (хеш `config.json`), в реестре — по дайджесту (хеш манифеста). Они не совпадают, не путайте при диагностике.
- **Общие слои (дедупликация)**: несколько образов физически используют один и тот же read-only слой; удаление одного образа не удаляет слой, пока на него ссылается другой.
- **Висячие образы (dangling)**: образы без тегов (тег переназначен) занимают место и чистятся `docker image prune`.
- **`docker image prune -a` безвозвратен**: удаляет все неиспользуемые образы; потребуется повторный pull/build.
- **containerd image store (Docker 29.1+ / containerd 2.0)**: `RepoDigests` формируется иначе, дефолтное хранилище меняется; поведение интеграции с Kubernetes отличается (см. «Примечания по версиям»).
- **Секреты в нижних слоях**: `RUN` с секретом оставляет его в слое навсегда, даже если файл удалён следующей инструкцией (whiteout только скрывает). Распаковка архива раскроет «удалённый» секрет.
- **Windows-контейнеры**: используют иной формат слоёв и изоляцию; архивы/образы Windows несовместимы с Linux-хостом и наоборот.

## Примечания по версиям

- **Docker Engine 24.0+**: containerd image store доступен опционально; команды `build`, `tag`, `push`, `history`, `inspect` стабильны на всех современных версиях (27/28/29).
- **BuildKit**: рантайм сборки по умолчанию с 23.0+; обеспечивает кэш-монтирование (`--mount=type=cache`), secret-монтирование и параллельную сборку.
- **Docker 29.1 / containerd 2.0**: нативный containerd image store включён по умолчанию; образы физически лежат в containerd, `RepoDigests` и дефолтный путь хранения могут отличаться от классического `/var/lib/docker`.
- **docker buildx**: встроен с 23.0; для multi-arch требует инициализации билдера (`docker buildx create --use`) и регистрации QEMU на хосте.
- **skopeo** (≥ 1.14): альтернатива daemonless-переноса образов без Docker-демона (см. **[Перенос и экспорт образов](./diagnostics_transfer.md)**).

## Дополнительная информация

Темы сохранения слоёв, стратегий тегирования и оптимизации сборки раскрыты в смежных материалах. Глубокий разбор влияния `LABEL` на дайджест — в **[Инструкции Dockerfile: Базовый образ и Метаданные](../../Dockerfile/Instructions/base_image_and_metadata.md#инструкция-label-аннотирование-образа)**.

### См. также

- **[Сравнение образа и контейнера](./image_vs_container.md)** — ключевые различия между статическим шаблоном и живым процессом.
- **[Анализ и управление слоями](./layer_management.md)** — глубокое погружение в структуру слоев и инструмент dive.
- **[Стратегии версионирования и тегирования](../../Docker_registries/image_versioning_and_tagging.md)** — лучшие практики именования образов.
