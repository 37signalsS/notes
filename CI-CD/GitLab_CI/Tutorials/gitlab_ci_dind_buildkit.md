# GitLab CI: сборка Docker-образов через DinD с кэшированием BuildKit

**Актуально для:** GitLab CI 19.x / GitLab Runner 19.x / Docker Engine 29.x

## Определения

  - **Docker-in-Docker (DinD)** — запуск Docker-демона внутри контейнера задачи в GitLab CI. Требует `privileged: true` на Runner. Демон и CLI должны использовать одну мажорную версию (например, `docker:29` + `docker:29.8-dind`). Подробнее: [Docker-in-Docker — концепции и подходы]../../../Docker/docker-in-docker.md).
  - **BuildKit** — современный движок сборки Docker (включён по умолчанию с Docker 23.0+). Управляется через `docker buildx build`. Поддерживает параллелизм, registry-кэширование и multi-arch. Подробнее: [BuildKit: современный движок сборки Docker]../../../Docker/Dockerfile/dockerfile_buildkit.md).
  - **DOCKER_TLS_CERTDIR** — переменная, включающая TLS-аутентификацию между клиентом Docker и DinD-демоном. GitLab автоматически монтирует общий том `/certs` между сервисом и контейнером задачи.
  - **Registry mirror** — pull-through кэш для Docker Hub. Сокращает время скачивания базовых образов и обходит rate limit.
  - **Trivy** — сканер уязвимостей контейнерных образов. Интегрируется в пайплайн через отдельный job и артефакты `container_scanning`.

## Как это работает

GitLab CI использует Docker executor для запуска задач. Чтобы собрать Docker-образ внутри задачи, необходимо:

1. **Запустить DinD-сервис** — `docker:29.8-dind` как sidecar-контейнер в `services`.
2. **Включить TLS** — `DOCKER_TLS_CERTDIR: "/certs"` заставляет entrypoint `docker:dind` сгенерировать сертификаты и запустить демон на порту 2376 с TLS. GitLab автоматически монтирует том `/certs` в оба контейнера (сервис и job), а также выставляет `DOCKER_HOST=tcp://docker:2376`, `DOCKER_TLS_VERIFY=1`, `DOCKER_CERT_PATH=/certs/client`.
3. **Выполнить `docker login`** перед сборкой — нужен для пуша образа и кэша в Container Registry.
4. **Собрать и запушить образ** через `docker buildx build --push` с флагами кэширования.

Схема:

```
Хост (GitLab Runner)
  └── Container (task: docker:29-cli)
        ├── DinD sidecar (docker:29.8-dind)  ← общий том /certs
        └── docker buildx build → registry (push)
```

## Предварительные требования

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **GitLab** | 18.0+ | `Help → About` в UI |
| **GitLab Runner** | 19.0+, Docker executor | `gitlab-runner --version` |
| **privileged mode** | `privileged = true` в `config.toml` | обязательно для DinD |
| **Container Registry** | включён в проекте | Deploy → Container Registry |
| **Docker образы** | `docker:29` (CLI) + `docker:29.8-dind` (сервис) | одна мажорная версия |
| **Registry mirror** (опц.) | доступен proxy (registry:2 с `proxy.remoteurl`) | `curl -I https://mirror.example.com/v2/` |

## Базовая настройка DinD

```yaml
# .gitlab-ci.yml
variables:
  DOCKER_TLS_CERTDIR: "/certs"
  DOCKER_BUILDKIT: "1"

services:
  - name: docker:29.8-dind
    command: ["--registry-mirror", "https://mirror.example.com"]

build:
  image: docker:29
  stage: build
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
  script:
    - docker buildx create --use --name builder
    - docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" \
        --tag "$CI_REGISTRY_IMAGE:latest" \
        --push \
        .
```

**Параметры:**

- `DOCKER_TLS_CERTDIR: "/certs"` — включает TLS между CLI и DinD. GitLab автоматически монтирует том и выставляет `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH`. Без него — `Cannot connect to the Docker daemon at tcp://docker:2376`.
- `command: ["--registry-mirror", ...]` — флаг передаётся в `dockerd` внутри сервиса. Без mirror каждый DinD-runner тянет `alpine:3.21` напрямую с Docker Hub, упираясь в rate limit (+30–60 с).
- `docker buildx create --use --name builder` — создаёт builder с драйвером `docker-container`, требуемый для registry cache.

**Валидация:**

```bash
docker version --format '{{.Server.Version}}'
# → 29.x.x
docker info --format '{{.Driver}}'
# → overlay2
```

## TLS-сертификаты

Без общего `DOCKER_TLS_CERTDIR` Docker CLI не может подключиться к DinD-демону:

```
Cannot connect to the Docker daemon at tcp://docker:2376.
```

**Решение:** `DOCKER_TLS_CERTDIR: "/certs"` — GitLab автоматически монтирует том между сервисом и контейнером задачи. Оба видят `/certs/client`.

Для отладки (только не в production):

```yaml
variables:
  DOCKER_TLS_CERTDIR: ""
  DOCKER_HOST: tcp://docker:2375
```

## Registry mirror

Registry mirror — pull-through кэш для Docker Hub. Без него каждый DinD-runner тянет `alpine:3.21` напрямую с Docker Hub, упираясь в rate limit и добавляя 30–60 секунд.

```yaml
services:
  - name: docker:29.8-dind
    command: ["--registry-mirror", "https://mirror.example.com"]
```

`mirror.example.com` — собственный Registry proxy (registry:2 с конфигом):

```yaml
# docker-compose.yml
services:
  registry:
    image: registry:2
    volumes:
      - ./config.yml:/etc/docker/registry/config.yml
```

```yaml
# config.yml
proxy:
  remoteurl: https://registry-1.docker.io
```

## Кэширование BuildKit: inline или registry

### Inline cache

Встраивает метаданные кэша в слой образа. Просто, но вынужденный тянуть весь образ для следующей сборки:

```yaml
script:
  - docker pull "$CI_REGISTRY_IMAGE:latest" || true
  - docker build \
      --build-arg BUILDKIT_INLINE_CACHE=1 \
      --cache-from "$CI_REGISTRY_IMAGE:latest" \
      --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" \
      --tag "$CI_REGISTRY_IMAGE:latest" \
      .
  - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  - docker push "$CI_REGISTRY_IMAGE:latest"
```

### Registry cache (рекомендуется)

Хранит кэш как отдельный манифест в registry. Тег `cache` содержит только метаданные + diff — маленький размер. `mode=max` кэширует все стадии сборки, а не только финальную:

```yaml
script:
  - docker buildx build \
      --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
      --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
      --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" \
      --push \
      .
```

**Механика для multi-stage .NET-сборки:**

- `restore` (NuGet) — меняется редко (только при изменении `.csproj`). С `mode=max` берётся из кэша даже на раннерах без локального кэша.
- `build` — меняется каждый коммит, но зависимости из `restore` подставляются из кэша.

**Ожидаемый результат:** инкрементальные сборки занимают 30–60 секунд вместо 5 минут.

```bash
docker buildx build --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max -t myapp . 
# → [internal] load build context
# → CACHED [builder 1/3] FROM ...
```

## Multi-arch сборки

```yaml
build:
  image: docker:29
  services:
    - name: docker:29.8-dind
      command: ["--registry-mirror", "https://mirror.example.com"]
  script:
    - docker run --privileged --rm tonistiigi/binfmt --install all
    - docker buildx create --use --name multiarch
    - docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache \
        --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max \
        --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" \
        --push \
        .
```

- `tonistiigi/binfmt --install all` — регистрирует QEMU-эмуляторы для всех платформ.
- Сборка под эмулируемую архитектуру идёт в 3–5 раз медленнее. Используйте registry cache для компенсации.

## Сканирование Trivy в том же пайплайне

```yaml
stages:
  - build
  - scan

scan:
  image:
    name: aquasec/trivy:0.76.0
    entrypoint: [""]
  stage: scan
  needs: [build]
  script:
    - trivy image \
        --format json \
        --output trivy-report.json \
        --severity HIGH,CRITICAL \
        --exit-code 1 \
        "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  artifacts:
    when: always
    reports:
      container_scanning: trivy-report.json
```

- `--exit-code 1` — пайплайн падает при HIGH/CRITICAL уязвимостях.
- Артефакт `container_scanning` отображается в MR во вкладке Security.
- Всегда фиксируйте версию образа Trivy (см. [Security scanning deep dive](../Tutorials/security_scanning_deep_dive.md)).

## Kaniko как альтернатива

Если привилегированные контейнеры недоступны (часто в Kubernetes-инсталляциях):

```yaml
build:
  image:
    name: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
    entrypoint: [""]
  script:
    - /kaniko/executor \
        --context . \
        --dockerfile Dockerfile \
        --destination "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" \
        --cache=true \
        --cache-repo="$CI_REGISTRY_IMAGE:cache"
```

- Kaniko не требует `privileged` режима.
- Компромисс: работает медленнее BuildKit и не поддерживает параллельные multi-arch сборки (multi-platform — только последовательно через `--custom-platform`). См. [Kaniko: сборка без демона]../../../Docker/Dockerfile/dockerfile_kaniko.md).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot connect to the Docker daemon at tcp://docker:2376` | `DOCKER_TLS_CERTDIR` не задан или сертификаты не смонтированы | Установите `DOCKER_TLS_CERTDIR: "/certs"`; проверьте `services` |
| `Cannot connect to the Docker daemon at tcp://docker:2375` | TLS отключён, порт 2375 безопасен только для отладки | Включите TLS через `DOCKER_TLS_CERTDIR`; не используйте в production |
| `error: failed to solve: cache cache: pull access denied` | Нет прав на чтение/запись кэш-образа в Registry | Выполните `docker login` перед сборкой; проверьте права на `CI_REGISTRY` |
| Registry mirror не работает | `--registry-mirror` не передаётся в `dockerd` | Проверьте `command` в сервисе; логи `docker:dind` |
| `operation not permitted` при `--platform` | Не установлены QEMU-эмуляторы | `docker run --privileged --rm tonistiigi/binfmt --install all` |
| `exec format error` | Архитектура образа (arm64) не поддерживается хостом без эмуляции | Используйте `--platform linux/amd64` или установите binfmt |

## Лучшие практики

### Сборка и кэширование

- **Фиксируйте версии образов.** `docker:29.8-dind`, `aquasec/trivy:0.76.0`, `ghcr.io/osscontainertools/kaniko:v1.28.5-debug` — в production не используйте `:latest`: иначе раннер получает образ с новым драйвером, флагом или форматом логов.
- **Согласованность CLI и DinD.** Демон и CLI должны быть в одной мажорной версии (`docker:29` + `docker:29.8-dind`) — иначе `buildx` registry cache и `--platform` работают непредсказуемо.
- **Registry mirror.** Pull-through кэш `registry:2` со `proxy.remoteurl: https://registry-1.docker.io` устраняет Docker Hub rate limit и экономит 30–60 с на cold-start.
- **Registry cache вместо Docker volume.** `--cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max` сохраняет кэш между эфемерными раннерами и восстанавливает его сразу после `docker login`.
- **Сканируйте каждый образ.** Trivy с `--exit-code 1` и артефактом `container_scanning` блокирует слияние образа с HIGH/CRITICAL уязвимостями.
- **Multi-arch только при необходимости.** `--platform linux/amd64,linux/arm64` + QEMU + binfmt увеличивает сборку в 3–5 раз; компенсируйте registry cache и нативными билдерами.

### Безопасность и доверие

- **DinD требует `privileged: true`** — это эквивалент root на хосте (seccomp/AppArmor снимаются целиком). Модели DinD/DooD/Kaniko/Sysbox и риски — в [Docker-in-Docker: Запуск Docker внутри контейнера](../../../Docker/docker-in-docker.md).
- **Доверяйте кэш внутри trust boundary.** Реестр-кэш — общий ресурс: при сборке недоверенного Dockerfile на shared builder возможен cache poisoning. Для недоверенных образов используйте `--no-cache` и отдельный `cache-repo` — см. [Buildx builder security](../../../Docker/Docker_security/buildx_builder_security.md).

### Очистка и GC

- **Cleanup policies Container Registry** удаляют старые теги и кэш-манифесты (`*:cache`), не давая registry расти безграниц — см. [Registry Cleanup Policies](../Advanced/container_registry.md#registry-cleanup-policies).
- **Очищайте buildx builders** на эфемерных раннерах: `docker buildx rm <name>` в `after_script`, либо используйте [Fleeting](fleeting_autoscaling_runners.md) для автоскейлинга VM-раннеров.

## См. также

- [Docker-in-Docker: Запуск Docker внутри контейнера]../../../Docker/docker-in-docker.md) — концепции, подходы (DinD/DooD/Kaniko/Sysbox), безопасность
- [BuildKit: Современный движок сборки Docker]../../../Docker/Dockerfile/dockerfile_buildkit.md) — архитектура, cache mounts, GC, buildctl
- [Kaniko: Сборка без демона]../../../Docker/Dockerfile/dockerfile_kaniko.md) — user-space сборка без privileged
  - [Container Registry в GitLab CI/CD](../Advanced/container_registry.md) — управление образами, cleanup policies, SBOM
  - [Сценарии кэширования GitLab CI](../Advanced/gitlab_ci_caching/cache_scenarios.md#сценарий-8--кэширование-слоёв-docker-через-registry-buildkit) — Docker layer caching через Registry (inline cache)
  - [Security scanning deep dive](security_scanning_deep_dive.md) — Trivy, SAST, DAST в GitLab CI
  - [GitLab Runner и executors](../Advanced/gitlab_ci_runners_executors.md) — Docker executor, DooD vs DinD
