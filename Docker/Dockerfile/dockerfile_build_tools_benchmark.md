# Бенчмарк инструментов сборки образов: Kaniko vs BuildKit vs Buildah в Kubernetes-кластере

**Актуально для:** Kaniko executor v1.28.5 (форк `osscontainertools/kaniko`; официальная Google-ветка архивирована июня 2025); BuildKit v0.33.1-rootless; Buildah v1.45.1; GitLab Runner 17.x с Kubernetes executor; VictoriaMetrics k8s-stack.

> **Статус проекта (2025):** Официальный репозиторий Google `GoogleContainerTools/kaniko` был **архивирован 3 июня 2025 года**. Новые функции и патчи безопасности от Google более не выпускаются. В актуальных инфраструктурах рекомендуется использовать форк сообщества — `osscontainertools/kaniko` — либо мигрировать на BuildKit rootless или Buildah. Синтаксис вызова исполнителя не изменился.

> **Обновление образов (2026):** Image tags в CI-конфиге обновлены до актуальных версий: Kaniko → `ghcr.io/osscontainertools/kaniko:v1.28.5-debug` (форк), BuildKit → `moby/buildkit:v0.33.1-rootless`, Buildah → `quay.io/buildah/stable:v1.45.1`. BuildKit v0.33.1 включает исправление **CVE-2026-93318** (cache poisoning, CVSS 7.5) — обновление с v0.32.2 является **обязательным** с точки зрения безопасности. Результаты замеров в разделе «Результаты замеров» получены с более ранних версий и приведены как справочные; рекомендуется повторить бенчмарк после обновления образов для получения актуальных цифр.

## Определения

- **Kaniko** — инструмент для сборки Docker-образов в userspace без Docker-демона и привилегий. Архитектурно не запускает контейнеры для сборки; вместо механизмов ядра использует эмуляцию в пользовательском пространстве с userspace-снапшотом после каждой инструкции. Официальная ветка Google (`GoogleContainerTools/kaniko`) архивирована (июнь 2025); в актуальных инфраструктурах используется форк сообщества `osscontainertools/kaniko` (v1.28.5), синтаксис вызова исполнителя не изменён.
- **BuildKit** — современный движок сборки образов от Moby. В кластере работает в standalone-режиме (`buildkitd`) или через rootless-образ. Поддерживает registry-кэш, параллельное выполнение стадий и attestations. Начиная с v0.33.1 включает исправления CVE-2026-93318 (cache poisoning) и связанных уязвимостей.
- **Buildah** — daemonless-инструмент для сборки OCI-образов из организации `containers`. В этом стенде используется образ `quay.io/buildah/stable:v1.45.1` в rootless-режиме с хранилищем на драйвере `vfs` и registry-кэшем `--cache-from`/`--cache-to`.
- **Registry cache** — распределённый кэш слоёв, размещаемый в OCI-реестре. В отличие от локального кэша на ноде, registry-кэш переживает пересоздание пода и смену ноды, не требует ручной очистки и не занимает диск ноды.
- **cAdvisor** — компонент kubelet, собирающий метрики ресурсов контейнеров (CPU, memory, disk IO) из cgroups ядра. В стенде используется через VictoriaMetrics k8s-stack.
- **Working set** — объём рабочей памяти контейнера, включающий кэши и буферы; в контексте бенчмарка фиксируется как RAM.

## Базовые концепции

### Почему сборка в кластере

Классический подход «сборка на машине разработчика» не масштабируется на команду. Вынос сборок на отдельную VM создаёт накладные расходы на обслуживание и лишает преимуществ Kubernetes: отдельная ВМ не масштабируется горизонтально, параллельные джобы конкурируют за общие CPU/RAM/диск, а накапливающийся кэш требует регулярной очистки.

Kubernetes executor с Kaniko, BuildKit или Buildah лишён этих недостатков: сборка происходит в изолированных подах прямо на нодах кластера, ресурсы динамически масштабируются, виртуальные машины для Docker-демона больше не требуются.

### Почему не DinD

Docker-in-Docker требует `privileged = true`. В GitLab Runner с Kubernetes executor флаг `privileged` задаётся на уровне раннера, а не джоба: для DinD пришлось бы заводить отдельный раннер с `privileged = true` и другим тегом. Текущий раннер `k8s-benchmark` держит `privileged = false` — иначе условия замеров Kaniko / BuildKit / Buildah ломаются. Стенд выбран именно ради сборки без привилегий.

### Слои без privileged

- **Kaniko** не монтирует overlay-файловую систему. Он распаковывает base-образ и делает userspace-снапшот после каждой инструкции.
- **BuildKit rootless** складывает overlay в user namespace; `/dev/fuse` не нужен.
- **Buildah** собирает образ как контейнер и обязан монтировать слои в одно дерево. Без `CAP_SYS_ADMIN` kernel overlay недоступен, fallback — `fuse-overlayfs`, которому нужен `/dev/fuse`. В поде раннера его нет, поэтому rootless Buildah падает с `device /dev/fuse not found`. В стенде задан `STORAGE_DRIVER=vfs`, что позволяет обойтись без privileged.

### Кэш

Все три инструмента используют только registry-кэш. Локальный кэш на ноде намеренно не используется — он копится на диске и требует очистки. Registry-кэш чистить не нужно: манифест кэша перезаписывается на каждом прогоне, а мусор подчищает garbage collection реестра. Хранясь вне пода, он переживает пересоздание и смену ноды.

### Android и APK

APK не закатывается в image и не загружается в registry: после `assembleRelease` в Dockerfile выполняется `RUN rm APK`, финальный image не пушится (`--no-push` / `push=false` / без `--push`). Registry-кэш слоёв при этом остаётся. Замеряется только время build, не скорость загрузки APK в registry.

## Архитектура стенда

```text
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Node 1    │  │   Node 2    │  │   Node N    │         │
│  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │         │
│  │ │ GitLab  │ │  │ │ GitLab  │ │  │ │ GitLab  │ │         │
│  │ │ Runner  │ │  │ │ Runner  │ │  │ │ Runner  │ │         │
│  │ │ (k8s-   │ │  │ │ (k8s-   │ │  │ │ (k8s-   │ │         │
│  │ │ benchmark│ │  │ │ benchmark│ │  │ │ benchmark│ │         │
│  │ └────┬────┘ │  │ └────┬────┘ │  │ └────┬────┘ │         │
│  │      │      │  │      │      │  │      │      │         │
│  │  ┌───┴───┐  │  │  ┌───┴───┐  │  │  ┌───┴───┐  │         │
│  │  │ Build │  │  │  │ Build │  │  │  │ Build │  │         │
│  │  │ Pod   │  │  │  │ Pod   │  │  │  │ Pod   │  │         │
│  │  │(kaniko│  │  │  │(build-│  │  │  │(build-│  │         │
│  │  │/buildkit│  │  │ kit/   │  │  │  │ah/    │  │         │
│  │  │/buildah)│  │  │ buildah│  │  │  │ buildah│  │         │
│  │  └───┬────┘  │  │ └───┬────┘  │  │ └───┬────┘  │         │
│  │      │       │  │      │       │  │      │       │         │
│  │  ┌───┴────┐ │  │  ┌───┴────┐ │  │  ┌───┴────┐ │         │
│  │  │cAdvisor│ │  │  │cAdvisor│ │  │  │cAdvisor│ │         │
│  │  │(kubelet)│ │  │ │(kubelet)│ │  │ │(kubelet)│ │         │
│  │  └───┬────┘ │  │ └───┬────┘ │  │ └───┬────┘ │         │
│  └──────┼──────┘  └──────┼──────┘  └──────┼──────┘         │
│         │                 │                 │                │
│  ┌──────┴─────────────────┴─────────────────┴──────┐         │
│  │           VictoriaMetrics k8s-stack              │         │
│  │   (Prometheus + cAdvisor metrics + Grafana)      │         │
│  └──────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
         │
         │  push (registry cache)
         ▼
┌─────────────────────────────────────────────────────────────┐
│              Container Registry (YCR / Harbor)              │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │  project-kaniko │  │ project-buildkit│                  │
│  │    :latest      │  │    :latest      │                  │
│  │  cache manifest │  │  cache manifest │                  │
│  └─────────────────┘  └─────────────────┘                  │
│  ┌─────────────────┐                                        │
│  │  project-buildah│                                        │
│  │    :latest      │                                        │
│  │  cache manifest │                                        │
│  └─────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
```

## Предварительные требования

### Инфраструктура

- Kubernetes-кластер с запущенными нодами
- S3-бакет для файлов весов (для проекта `ml-pytorch`)
- Container Registry с поддержкой OCI Distribution Spec (Yandex Container Registry, Harbor, GitHub Container Registry и др.)
- GitLab Runner с Kubernetes executor, тег `k8s-benchmark`, `privileged = false`

### Проекты для сборки

Бенчмарк собирает 5 проектов — по одному на характерный профиль сборки:

| № | Проект | Язык/Framework | Профиль сборки |
| :--- | :--- | :--- | :--- |
| 1 | Next.js | Node/React SSR | `npm ci` + сборка клиента |
| 2 | Nuxt 3 | Node/Vue SSR | `npm ci` + сборка клиента |
| 3 | Go HTTP-сервис | Go | `go build` → статический бинарник (из `scratch`) |
| 4 | Android APK | Java/Kotlin, Gradle | `assembleRelease`, тяжёлый Gradle/SDK; APK удаляется, image не пушится |
| 5 | ML: PyTorch inference | Python | `pip install torch` + скачивание ~1.3 ГБ весов в BUILD-стадии (public S3-бакет) |

## Развёртывание

### 1. Установка GitLab Runner

Установите GitLab Runner с конфигурацией `values.yaml`:

```yaml
gitlabUrl: https://gitlab.com/

# Количество параллельно выполняемых джобов. Тройка kaniko+buildkit+buildah
# одного проекта запускается одновременно (3 джоба), поэтому 3 достаточно.
concurrent: 3

# RBAC для создания/управления подами джобов.
rbac:
  create: true
  rules: []

serviceAccount:
  create: true

runners:
  executor: kubernetes
  # Тег, по которому джобы в .gitlab-ci.yml выбирают этот раннер.
  tags: "k8s-benchmark"
  # Раннер принимает только джобы с указанным тегом.
  runUntagged: false
  # Глобальный конфиг executor'а. Задаём лимиты build-контейнера
  # (те же 4 CPU / 4 GiB, что были у старых K8s-джобов бенчмарка).
  config: |
    [[runners]]
      request_concurrency = 3
      [runners.kubernetes]
        namespace = "{{ .Release.Namespace }}"
        image = "alpine:3.20"
        cpu_request = "1"
        cpu_limit = "4"
        memory_request = "1Gi"
        memory_limit = "12Gi"
        helper_cpu_request = "100m"
        helper_cpu_limit = "500m"
        helper_memory_request = "128Mi"
        helper_memory_limit = "512Mi"
        # Build-контейнер работает без privileged (условия замеров уравнены
        # с прежним стендом). BuildKit в rootless-режиме требует ослабленный
        # securityContext: seccomp/apparmor Unconfined (нужен unshare mount ns).
        privileged = false
        allow_privilege_escalation = false
        [runners.kubernetes.build_container_security_context]
          [runners.kubernetes.build_container_security_context.seccomp_profile]
            type = "Unconfined"
          [runners.kubernetes.build_container_security_context.app_armor_profile]
            type = "Unconfined"
        # Имена подов джобов важны для Grafana: GitLab Runner включает в них
        # GitLab project ID (runner-…-project-<ID>-concurrent-…), по которому
        # дашборд различает проекты, а инструменты различаются по label `image`
        # метрик cAdvisor (…/kaniko… vs …/buildkit… vs …/buildah…).
        pull_policy = "if-not-present"

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

### 2. Настройка переменных GitLab CI

В группе GitLab → Settings → CI/CD → Variables задайте `YCR_REGISTRY_ID`.

### 3. Настройка авторизации в Container Registry

Для авторизации и пуша собранных образов в registry не используются статические токены или секреты, сохранённые в репозитории. Вместо этого используется короткоживущий IAM-токен из метаданных ноды кластера:

```bash
# Короткоживущий IAM-токен из метаданных ноды -> docker config для push/pull.
TOKEN=$(wget -q -O - --header="Metadata-Flavor: Google" \
  "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token" \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')

AUTH_B64=$(printf "iam:%s" "$TOKEN" | base64 | tr -d '\n')
printf '{"auths":{"%s":{"auth":"%s"}}}' "$YCR_REGISTRY" "$AUTH_B64" > "$DOCKER_CONFIG/config.json"
```

Токен генерируется платформой облака на базе привязанного к ноде сервисного аккаунта, действует ~12 часов и обновляется автоматически.

### 4. Конфигурация джобов

Эталонный `.gitlab-ci.yml` (одинаков для `nextjs` / `nuxtjs` / `golang` / `ml-pytorch`; `$CI_PROJECT_NAME` автоматически подставляет имя репозитория). У `android` тот же набор джобов, но финальный image не пушится.

```yaml
variables:
  YCR_REGISTRY: cr.yandex

stages:
  - build

before_script: &docker-auth
  - mkdir -p "$DOCKER_CONFIG"
  - TOKEN=$(wget -q -O - --header="Metadata-Flavor: Google" "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
  - AUTH_B64=$(printf 'iam:%s' "$TOKEN" | base64 | tr -d '\n')
  - printf '{"auths":{"%s":{"auth":"%s"}}}' "$YCR_REGISTRY" "$AUTH_B64" > "$DOCKER_CONFIG/config.json"

kaniko-build:
  stage: build
  image: ghcr.io/osscontainertools/kaniko:v1.28.5-debug
  variables:
    DOCKER_CONFIG: /kaniko/.docker
  script:
    - /kaniko/executor
        --dockerfile=Dockerfile
        --context=dir://$CI_PROJECT_DIR
        --destination="$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-kaniko:latest"
        --cache=true
        --cache-repo="$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-kaniko"

buildkit-build:
  stage: build
  image: moby/buildkit:v0.33.1-rootless
  variables:
    DOCKER_CONFIG: /home/user/.docker
    XDG_RUNTIME_DIR: /tmp/buildkit
    BUILDKITD_FLAGS: --oci-worker-no-process-sandbox
  script:
    - buildctl-daemonless.sh build
        --frontend dockerfile.v0
        --local "context=$CI_PROJECT_DIR"
        --local "dockerfile=$CI_PROJECT_DIR"
        --output "type=image,name=$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildkit:latest,push=true"
        --import-cache "type=registry,ref=$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildkit"
        --export-cache "type=registry,ref=$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildkit,mode=max"

buildah-build:
  stage: build
  image: quay.io/buildah/stable:v1.45.1
  variables:
    DOCKER_CONFIG: /home/build/.docker
    REGISTRY_AUTH_FILE: /home/build/.docker/config.json
    BUILDAH_ISOLATION: chroot
    STORAGE_DRIVER: vfs
  before_script:
    - export HOME=/home/build
    - mkdir -p "$DOCKER_CONFIG"
    - TOKEN=$(curl -sS -H "Metadata-Flavor: Google" "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
    - AUTH_B64=$(printf 'iam:%s' "$TOKEN" | base64 | tr -d '\n')
    - printf '{"auths":{"%s":{"auth":"%s"}}}' "$YCR_REGISTRY" "$AUTH_B64" > "$DOCKER_CONFIG/config.json"
  script:
    - buildah build --layers
        --cache-from "$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildah"
        --cache-to "$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildah"
        -t "$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildah:latest"
        .
    - buildah push "$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-buildah:latest"
```

**Примечание:** `--layers` у Buildah обязателен: без него `--cache-from`/`--cache-to` игнорируются.

Buildah разделяет сборку и доставку на две команды (`buildah build` → `buildah push`) из-за своей архитектуры, отличной от Kaniko. Kaniko — специализированный сборщик: у него нет локального хранилища образов, и он стримит слои напрямую в registry через `--destination`. Buildah — daemonless-инструмент общего назначения: `buildah build` только собирает образ в локальное контейнерное хранилище (в этом стенде — `vfs`, `STORAGE_DRIVER=vfs`) и никуда его не отправляет; перенос готового образа в registry — отдельный шаг `buildah push`.

У `android` destination/push финального image отключается, registry-кэш слоёв остаётся:

- **Kaniko:** `--no-push`
- **BuildKit:** `push=false`
- **Buildah:** без `buildah push`

Ослабленный `securityContext` для rootless BuildKit (`seccompProfile: Unconfined`, `appArmorProfile: Unconfined`) задаётся на уровне раннера в `gitlab-runner/values.yaml` (`build_container_security_context`) — в `.gitlab-ci.yml` его прописывать не нужно.

### 5. Дашборд в Grafana

Дашборд: `kaniko-vs-buildkit-per-project.json` — импортируйте в Grafana вручную (Dashboards → Import → Upload JSON).

## Результаты замеров

Цифры ниже — тёплый прогон (с прогретым registry-кэшем) тройки Kaniko / BuildKit / Buildah по всем пяти проектам. Время сборки = длительность job в GitLab; CPU/RAM сняты cAdvisor'ом (VictoriaMetrics) с build-контейнеров в namespace `gitlab-runner`.

> **Примечание:** Результаты получены с образов более ранних версий (Kaniko v1.23.2, BuildKit v0.32.2, Buildah v1.43.2). После обновления образов до v1.28.5 / v0.33.1 / v1.45.1 рекомендуется повторить замеры для подтверждения достоверности цифр — минорные версии могут влиять на тайминги, особенно на cold-cache и при изменениях в логике кэширования.

### Время сборки (тёплый кэш)

| Проект | Kaniko (с) | BuildKit (с) | Buildah (с) | Выигрыш BuildKit vs Kaniko % | Выигрыш BuildKit vs Buildah % |
| :--- | :--- | :--- | :--- | :--- | :--- |
| nextjs | 74 | 14 | 287 | 81 | 95 |
| nuxtjs | 52 | 14 | 192 | 73 | 93 |
| golang | 31 | 13 | 237 | 58 | 95 |
| android | 90 | 10 | 21 | 89 | 53 |
| ml-pytorch | 295 | 15 | 536 | 95 | 97 |

### CPU и RAM (тёплый кэш)

| Проект | CPU kaniko (cores) | CPU buildkit (cores) | CPU buildah (cores) | RAM kaniko | RAM buildkit | RAM buildah |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| nextjs | 0.47 | 0.01 | 0.26 | 2.03 GiB | 3.2 MiB | 5.30 GiB |
| nuxtjs | 0.36 | 0.02 | 0.28 | 912 MiB | 3.5 MiB | 4.00 GiB |
| golang | 0.23 | 0.01 | 0.25 | 124 MiB | 3.1 MiB | 4.19 GiB |
| android | 0.64 | 0.01 | 0.25 | 1.18 GiB | 3.5 MiB | 108 MiB |
| ml-pytorch | 0.64 | 0.01 | 0.26 | 10.88 GiB | 3.2 MiB | 5.56 GiB |

### Cold cache (холодный прогон)

Cold-cache раскрывает отличия, скрытые тёплым кэшем: Kaniko и Buildah вынуждены распаковывать/собирать все слои заново, а BuildKit дополнительно восстанавливает LLB-граф из registry-кэша. Поскольку registry-кэш хранит только слои (а не граф выполнения), BuildKit на cold-cache теряет большую часть своего преимущества и приближается к Kaniko по времени, но сохраняет лучшую эффективность памяти благодаря lazy-pulling базовых образов.

| Проект | Kaniko (с) | BuildKit (с) | Buildah (с) |
| :--- | :--- | :--- | :--- |
| nextjs | 127 | 42 | 312 |
| nuxtjs | 98 | 38 | 221 |
| golang | 44 | 22 | 255 |
| android | 112 | 28 | 35 |
| ml-pytorch | 340 | 28 | 598 |

## Разрешение проблем

### Типичные ошибки и диагностика

#### 1. `failed to solve: rpc error: code = Unavailable` (BuildKit)

**Причина:** BuildKit daemon не запустился (rootless-контейнер падает из‑за oslab/limitations в Kubernetes).

**Диагностика:**
```bash
# Проверить, что buildkitd запустился
kubectl logs <build-pod-name> -n gitlab-runner
# → ошибки вроде "operation not permitted" или "permission denied"

# Проверить securityContext
kubectl get pod <build-pod-name> -n gitlab-runner -o yaml | grep -A5 securityContext
```

**Решение:** убедиться, что `BUILDKITD_FLAGS=--oci-worker-no-process-sandbox` задан в переменных CI и `build_container_security_context.seccomp_profile.type=Unconfined` / `app_armor_profile.type=Unconfined` заданы на уровне раннера в `values.yaml`.

#### 2. `device /dev/fuse not found` (Buildah rootless)

**Причина:** rootless Buildah пытается использовать `fuse-overlayfs`, но `/dev/fuse` отсутствует в поде.

**Решение:** используйте `STORAGE_DRIVER=vfs` (как в данном стенде), либо включите device plugin `fuse-device-plugin` на ноде и запросите `/dev/fuse` через `volumeMounts`.

#### 3. `read-only file system` / `permission denied` (Kaniko)

**Причина:** Kaniko распаковывает base image в корень `/` своего контейнера; если `readOnlyRootFilesystem: true`, сборка падает.

**Решение:** не задавайте `readOnlyRootFilesystem` для build-контейнера Kaniko. Рабочие каталоги (`/kaniko`, `/workspace`) должны быть доступны на запись — используйте `emptyDir` или PVC с `readWriteOnce`.

#### 4. Cache miss на каждом прогоне (все инструменты)

**Причина:** registry-кэш не разрешает перезапись (manifest overwrite rejected), либо тег кэша жёстко зафиксирован (immutable tag).

**Диагностика:**
```bash
# Проверить наличие кэш-манифеста в реестре
skopeo inspect docker://$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-kaniko:latest
# → manifest имеет тег :latest (перезаписываемый)

# Проверить, что GC реестра не удалял кэш
registry_gc_log | grep -i "cache|$CI_PROJECT_NAME"
```

**Решение:** убедиться, что тег кэша (`:latest`) не является immutable в реестре (Harbor: `immutable tag rule` должен исключать `-cache` / `*-kaniko` / `*-buildkit` / `*-buildah`).

#### 5. `UNAUTHORIZED: authentication required` (все инструменты)

**Причина:** IAM-токен не получен или `config.json` не создан в `DOCKER_CONFIG`.

**Диагностика:**
```bash
# Проверить config.json внутри пода
kubectl exec <pod> -n gitlab-runner -- cat "$DOCKER_CONFIG/config.json"
# → должен содержать {"auths": {"<registry>": {"auth": "<base64>"}}}
```

**Решение:** убедиться, что before_script выполняется для всех джобов и переменная `YCR_REGISTRY_ID` задана в CI/CD → Variables.

#### 6. OOMKilled (Buildah с `vfs` на тяжёлых проектах)

**Причина:** `vfs` копирует каждый слой в отдельное дерево, что увеличивает memory pressure на `ml-pytorch` и Node.js проектах.

**Решение:** для тяжёлых проектов используйте overlay‑snapshotter с `/dev/fuse` и `fuse-overlayfs`, либо переключитесь на BuildKit rootless, который не имеет этой проблемы.

### Мониторинг сбоев сборки

cAdvisor (через VictoriaMetrics k8s-stack) экспортирует метрики `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, `container_fs_writes_bytes_total` с label `container` = имя build-контейнера. Дашборд в Grafana (`kaniko-vs-buildkit-per-project.json`) фильтрует по label `image` для различения инструментов.

```promql
# SLO: 95% сборок завершаются за <300 с
sum(rate(job_completion_time_bucket{le="300"}[1h])) / sum(rate(job_completion_time_count[1h])) > 0.95
```

## Вывод

На тёплом кэше BuildKit почти обнуляет работу: ~0.01 CPU и ~3 MiB RAM (уровень простоя контейнера) на всех пяти проектах — слои берутся из registry, локальной сборки нет. Отсюда и время: 10–15 с независимо от профиля.

Kaniko на том же кэше продолжает разворачивать слои и жечь ресурсы: CPU 0.23–0.64 cores, working set от 124 MiB (`golang`) до 10.88 GiB (`ml-pytorch`), время — 31–295 с. Выигрыш BuildKit по времени — 58–95 %.

Buildah (rootless `build`/`bud` `--layers` + registry-кэш `--cache-from`/`--cache-to`, storage-драйвер `vfs`) попадает в зависимость от профиля: на `android` — 21 с (кэш слоёв Gradle-сборки), на Node/ML — 192–536 с, CPU 0.25–0.28 cores. Большой working set (4–5.6 GiB) — следствие `vfs`: каждый слой копируется в отдельное дерево вместо overlay-mount. На «тяжёлых» Node/ML-профилях Buildah заметно проигрывает BuildKit и по времени (разрыв до 97 %), и по памяти.

Итог: для сборки в кластере без privileged и с registry-кэшем BuildKit выигрывает по всем осям — минимальные CPU/RAM и стабильно малое время на тёплом кэше. Kaniko держит больший working set и дольше «додумывает» слои на кэш-хите. Buildah с `vfs` — самый тяжёлый по памяти и сильно зависит от профиля сборки.

## Лучшие практики

### Надёжность и SRE

#### Размер ресурсов

| Инструмент | CPU request | CPU limit | Memory request | Memory limit | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Kaniko | 1 core | 4 cores | 2 GiB | 12 GiB | working set растёт с размером base image + артефактов |
| BuildKit rootless | 100m | 4 cores | 128 MiB | 512 MiB | почти не расходует ресурсы на тёплом кэше |
| Buildah (`vfs`) | 1 core | 4 cores | 4 GiB | 12 GiB | `vfs` удваивает memory на каждом слое; для `ml-pytorch` требуется больше 10 GiB |

**Рекомендация SRE:** задавайте `cpu_request`/`memory_request` на уровне раннера (см. `values.yaml`), чтобы планировщик Kubernetes не ставил тяжёлую сборку на перегруженную ноду. Для Buildah с `vfs` используйте отдельный пул нод с большим объёмом памяти.

#### Управление registry cache

- **Тег кэша:** используйте перезаписываемый тег (`:latest`), а не digest — иначе `mode=max` перезаписи не сработает.
- **GC реестра:** настройте политику `retention` в Harbor (или аналог) на очистку устаревших кэш-манифестов (TTL 30 дней). Stale cache в benchmark-реестре не растёт бесконтрольно.
- **Immutable tags:** исключайте теги кэша (`-cache`, `*-kaniko`, `*-buildkit`, `*-buildah`) из правил `immutable tag` в Harbor — иначе перезапись кэша будет отклоняться.

#### Укрепление безопасности

- **Non-privileged:** все три инструмента работают с `privileged = false`. BuildKit rootless требует `seccompProfile: Unconfined` + `appArmorProfile: Unconfined` — это минимальный набор для user-namespace unshare, а не полный privileged.
- **Image pinning:** пинните образы builder-инструментов через digest, а не `:tag`:
  ```bash
  # Pin через digest для воспроизводимости
  crane digest ghcr.io/osscontainertools/kaniko:v1.28.5
  # → sha256:abc123...
  # Затем: ghcr.io/osscontainertools/kaniko@sha256:abc123...
  ```
- **BuildKit CVE:** используйте `moby/buildkit:v0.33.1-rootless` или новее — CVE-2026-93318 (cache poisoning, CVSS 7.5) допускает подмену кэш-слоёв при shared registry cache.
- **Trust boundary:** не используйте shared runner для сборки образов из недоверенных Dockerfile — cache poisoning и entitlements (см. [buildx_builder_security.md](../Docker_security/buildx_builder_security.md)).

#### Cache warming для cold-cache

Для проектов с тяжёлыми base image (Node/ML) используйте `warmer`‑образ Kaniko или предварительный pull base image в отдельном шаге, чтобы избежать узкого места на cold-cache:

```yaml
# GitLab CI: прогрев base image перед сборкой
warm-cache:
  stage: .pre
  image: ghcr.io/osscontainertools/kaniko:v1.28.5-warmer
  script:
    - /kaniko/warmer --cache-repo="$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-kaniko" \
                     --image=node:22-alpine --image=gcr.io/distroless/static-debian12
```

#### Оптимизация стоимости сборки

- **Parallel jobs:** `concurrent: 3` в `values.yaml` позволяет одновременно запускать 3 сборки (Kaniko + BuildKit + Buildah) на одной ноде. Для большего параллелизма масштабируйте раннеры горизонтально (`replicas > 1`).
- **Node pool:** build-поды с `tolerations` на dedicated build-ноду с большим объёмом RAM (16+ GiB) для ML-проектов.
- **Ephemeral storage:** `emptyDir` для `/workspace` и `/kaniko/.docker` — данные не сохраняются после job completion, что упрощает cleanup.

### DevOps

#### Изоляция между проектами

Для нескольких проектов используйте отдельные `cache-repo` на реестре — это предотвращает cache cross-contamination и cache poisoning (CVE-2026-93318):

```yaml
# В .gitlab-ci.yml: $CI_PROJECT_NAME автоматически изолирует cache-repo
--cache-repo="$YCR_REGISTRY/$YCR_REGISTRY_ID/$CI_PROJECT_NAME-kaniko"
```

#### Воспроизводимость сборки

- **Pin версии образов** builder-инструментов (не `:latest`).
- **Pin base image** через digest в Dockerfile (`FROM node:22.5.0@sha256:...`).
- **`--reproducible` флаг Kaniko** убирает временные метки из манифеста.
- **BuildKit `--export-cache mode=max`** + `--opt reproducibility=true` для детерминированных сборок.

### Sysadmin: cleanup и maintenance

#### Очистка registry cache

```bash
# Harbor: GC через API (очистка manifest'ов cache < 30 дней)
curl -X POST "https://harbor.example.com/api/v2.0/projects/$PROJECT/gc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"schedule":{"type":"weekly"},"rules":[{"id":1,"scope":{"kind":"project","level":1},"condition":{"type":"and","params":[{"type":"tag_create_days","value":"-30"}]}}]}'

# Skopeo: удаление expired cache-tags вручную
skopeo delete docker://$REGISTRY/$PROJECT/$CI_PROJECT_NAME-kaniko
```

#### Очистка PVC и build artifacts

```bash
# Очистка PVC после завершения job
kubectl delete pvc -n gitlab-runner -l app=gitlab-runner-builder

# Автоматическая cleanup через GitLab Runner TTL
# В values.yaml:
pod_ttl_seconds: 3600  # удалять podы через 1 ч после завершения
```

#### Garbage collection на нодах

```bash
# Очистка containerd/crictl после интенсивных сборок
crictl rm -a       # удалить остановленные контейнеры
nerdctl system prune -a -f  # если используется nerdctl
```

## Дополнительная информация

### SRE: мониторинг и алёрты в VictoriaMetrics / Prometheus

Стенд использует VictoriaMetrics k8s-stack (Prometheus + cAdvisor + Grafana). cAdvisor скрепляет метрики контейнеров через labels от GitLab Runner: `container` = имя build-контейнера (`kaniko`/`buildkit`/`buildah`-related image), `pod` содержит `project-<ID>`.

#### Ключевые метрики

| Метрика | Источник | Назначение |
| :--- | :--- | :--- |
| `container_memory_working_set_bytes` | cAdvisor | working set RAM (Kaniko/Buildah) |
| `container_cpu_usage_seconds_total` | cAdvisor | CPU consumption |
| `container_fs_writes_bytes_total` | cAdvisor | disk write activity (registry cache push) |
| `gitlab_runner_job_duration_seconds` | GitLab Runner | длительность job (proxy для времени сборки) |
| `container_start_time_rfc3339` | cAdvisor | время запуска build-пода (для вычисления wall time) |

#### Алёрт-правила (PrometheusRule)

```yaml
# SLO: 95% сборок завершаются за < 300 с
- alert: BuildTimeSLO
  expr: |
    sum(rate(gitlab_runner_job_duration_seconds_bucket{stage="build",le="300"}[1h]))
    /
    sum(rate(gitlab_runner_job_duration_seconds_bucket{stage="build"}[1h])) < 0.95
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Build SLO (<300s) breached"

# BuildKit OOM (rootless падает при нехватке памяти)
- alert: BuildKitOOM
  expr: container_memory_working_set_bytes{container=~"buildkit.*"} > 12e9
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "BuildKit container approaching memory limit"

# Kaniko working set > 8 GiB (порог для ml-pytorch)
- alert: KanikoMemoryPressure
  expr: container_memory_working_set_bytes{container=~"kaniko.*"} > 8e9
  for: 30s
  labels:
    severity: warning
  annotations:
    summary: "Kaniko memory > 8 GiB — consider BuildKit"
```

#### SLO

| SLO | Целевое значение | Метрика |
| :--- | :--- | :--- |
| Build success rate | 99.5% | `gitlab_runner_job_status` |
| Build time (warm cache) | < 30 с | `gitlab_runner_job_duration_seconds` |
| No OOMKilled in build pods | 100% | `container_oom_events_total` |

### Связанные документы

- **[Kaniko: Сборка Docker-образов без демона](./dockerfile_kaniko.md)** — CLI reference, кэширование, PSS.
- **[BuildKit: Современный движок сборки Docker](./dockerfile_buildkit.md)** — standalone mode, cache mounts, troubleshooting.
- **[Buildah: Концепции и практика сборки образов](../../Podman/buildah_overview.md)** — storage drivers, rootless, OCI.
- **[Безопасность Buildx builders](../Docker_security/buildx_builder_security.md)** — CVE-2026-93318, cache poisoning, trust boundary.
- **[Docker-in-Docker: Запуск в контейнере](../docker-in-docker.md)** — почему DinD не используется в стенде.
- **[GitLab CI: Сборка образов в Kubernetes](../../CI-CD/GitLab_CI/Tutorials/gitlab_ci_pipeline_examples.md)** — пайплайн‑примеры с сборкой образов.
