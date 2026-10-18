# Безопасность цепочки поставок контейнерных образов

**Актуально для:** Docker Engine 29.x, BuildKit 0.34+, Cosign v3.1+, Syft v1.54+, Trivy ≥ 0.71.0, CycloneDX 1.7, Kyverno v1.19+, Kubernetes 1.31+

## Определения

* **Container Image Supply Chain (Цепочка поставок контейнерных образов):** Совокупность всех компонентов, участвующих в создании, хранении и распространении Docker/OCI-образов: базовые образы, пакеты ОС, зависимости приложения, инструменты сборки, реестры артефактов и механизмы распространения.
* **Distroless Image (Образ без дистрибутива):** Минимальный образ, содержащий только приложение и его runtime-зависимости (без shell, пакетного менеджера, утилит ОС). Снижает поверхность атаки на порядки. Примеры: Google Distroless, Chainguard, Wolfi.
* **Digest Pinning (Фиксация по дайджесту):** Привязка образа к неизменяемому хеш-сумме (`image@sha256:...`), а не к изменяемому тегу (`image:latest`). Гарантирует, что при повторном pull скачивается идентичный артефакт.
* **Multi-stage Build (Многоступенчатая сборка):** Паттерн Dockerfile, при котором сборка и запуск происходят в разных стадиях. Финальный образ содержит только скомпилированный бинарник и минимальный runtime, исключая инструменты сборки.
* **Hardened Base Image (Усиленный базовый образ):** Базовый образ, оптимизированный для безопасности: минимальный набор пакетов, регулярные обновления безопасности, предустановленный SBOM, отсутствие known CVE.
* **Image Provenance (Происхождение образа):** Аттестация, описывающая процесс создания образа: какой Dockerfile, какие зависимости, какой CI/CD-пайплайн, какой реестр. Позволяет проверить, что образ не был подменён.
* **Scratch Image (Пустой образ):** Нулевой образ Docker (`FROM scratch`) — отсутствует даже минимальная файловая система. Используется для статически компилированных бинарников (Go, Rust, C с `CGO_ENABLED=0`). Размер 0 МБ, минимальная поверхность атаки.
* **Hermetic Build (Герметичная сборка):** Сборка в изолированной среде без доступа к внешней сети. Все зависимости верифицируются по хеш-суммам (Content Addressable Storage). Подробнее — в `Security/Supply_Chain_Security/build_integrity.md`.

## Предпосылки

Перед внедрением практик безопасности образов необходимо:

1. **Docker Engine 29.x** с активным BuildKit (`DOCKER_BUILDKIT=1`) и buildx для кэширования слоёв.
2. **Локальный реестр** (Harbor v2.15+, Nexus, или Artifactory) с поддержкой OCI 1.1 Referrers API для хранения подписей и SBOM.
3. **Инструменты сканирования** (Syft v1.54+, Trivy ≥ 0.71.0) установлены на build-раннере CI/CD.
4. **Cosign v3.1+** для подписи образов и аттестаций (см. `Security/Supply_Chain_Security/artifact_signing.md`).
5. **Kyverno v1.19+** или OPA Gatekeeper в Kubernetes-кластере для admission-контроля.
6. **Доступ к источникам базовых образов:** официальные образы (`docker.io`, `gcr.io`) или внутренние (Chainguard `cgr.dev`, Distroless `gcr.io/distroless`).

## Установка и настройка

### Активация BuildKit и buildx

```bash
# Включение BuildKit по умолчанию
export DOCKER_BUILDKIT=1
docker buildx version
# → github.com/docker/buildx/0.34.0+0a0f545

# Настройка для постоянного использования
echo 'export DOCKER_BUILDKIT=1' >> ~/.bashrc
```

### Установка Syft (SBOM generation)

```bash
# Linux (x86_64)
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin
syft version
# → Syft 1.54.0

# macOS
brew install anchore/tap/syft
```

### Установка Trivy (vulnerability scanning)

```bash
# Linux
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin v0.71.0
trivy version
# → Version: 0.71.0

# macOS
brew install aquasecurity/tap/trivy
```

### Установка Cosign (image signing)

```bash
# Via GitHub Releases
curl -sSL https://github.com/sigstore/cosign/releases/download/v3.1.0/cosign-linux-amd64 -o /usr/local/bin/cosign
chmod +x /usr/local/bin/cosign
cosign version
# → Cosign version: v3.1.0
```

## Основные концепции

### Уровни защиты контейнерного образа

| Уровень | Практика | Инструменты |
|:--- |:--- |:--- |
| **1. Выбор базового образа** | Distroless, distroless-derived, Alpine, scratch | Chainguard, Google Distroless, Wolfi |
| **2. Безопасная сборка** | Multi-stage, digest pinning, hermetic builds | Docker BuildKit, Kaniko, Earthly |
| **3. Сканирование** | Vulnerability scanning, SBOM generation | Trivy, Grype, Syft, Docker Scout |
| **4. Подпись** | Криптографическая подпись образов | Cosign, Notation |
| **5. Хранение** | Изолированный реестр с RBAC и сканированием | Harbor, Nexus, Artifactory |
| **6. Admission control** | Блокировка неподписанных/уязвимых образов | Kyverno, OPA Gatekeeper |
| **7. Runtime monitoring** | Обнаружение drift и аномалий | Falco, Tetragon |

### Сравнение базовых образов

| Образ | Размер | Shell | Пакеты | CVE | SBOM | Подпись |
|:--- |:--- |:--- |:--- |:--- |:--- |:--- |
| **ubuntu:24.04** | ~78 МБ | bash | ~100+ | Много | Нет | Нет |
| **alpine:3.21** | ~8 МБ | ash | ~12 | Мало | Нет | Нет |
| **distroless/static** | ~2 МБ | Нет | 0 | Нет | Предустановлен | Chainguard |
| **distroless/java** | ~50 МБ | Нет | JRE only | Минимум | Предустановлен | Chainguard |
| **wolfi-base** | ~6 МБ | sh (busybox) | Минимум | Нет | Предустановлен | Chainguard |
| **scratch** | 0 МБ | Нет | 0 | Нет | Нет | Нет |

**Критерий выбора:**
- **scratch:** Статически скомпилированные Go/Rust бинарники.
- **distroless:** Приложения на Java, Python, Node.js, Go (когда нужен runtime, но не нужен shell).
- **Alpine:** Когда нужен пакетный менеджер для установки зависимостей, но нужна минимальность.
- **wolfi:** Когда нужна оптимизация для безопасности и бинарные пакеты (apt/apk).

## Практические сценарии

### Сценарий 1: Multi-stage безопасная сборка (Go)

```dockerfile
# Stage 1: Сборка с зависимостями
FROM golang:1.24@sha256:abc123... AS builder
WORKDIR /app
COPY go.mod go.sum ./
# Герметичная сборка зависимостей
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-buildid=" -o /app/server .

# Stage 2: Distroless runtime
FROM gcr.io/distroless/static:nonroot
COPY --from=builder /app/server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

**Валидация:**
```bash
# Проверка размера образа
docker images my-app:latest
# → REPOSITORY   TAG       SIZE
# → my-app       latest    8.2 МБ (вместо 800+ МБ с golang:1.24)

# Проверка отсутствия shell
docker run --rm my-app:latest sh
# → exec: "sh": executable file not found in $PATH

# Проверка отсутствия пакетного менеджера
docker run --rm my-app:latest apk
# → exec: "apk": executable file not found in $PATH
```

### Сценарий 2: Digest pinning в Dockerfile и Kubernetes

```dockerfile
# Dockerfile — фиксация по digest
FROM python:3.12-slim@sha256:9a8b7c6d5e4f... AS builder
# НЕ ИСПОЛЬЗУЙТЕ: FROM python:3.12-slim (тег изменяем)
```

```yaml
# Kubernetes Deployment — фиксация по digest
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
        - name: app
          image: harbor.internal/my-app@sha256:abc123def456...
          # НЕ ИСПОЛЬЗУЙТЕ: image: harbor.internal/my-app:latest
          # НЕ ИСПОЛЬЗУЙТЕ: image: harbor.internal/my-app:v1.0.0
```

```bash
# Проверка: образ зафиксирован по digest
kubectl get pod my-app-xyz -o jsonpath='{.spec.containers[0].image}'
# → harbor.internal/my-app@sha256:abc123def456...
```

**Разрешение digest для любого образа:**

```bash
# Получение digest для официального образа
docker inspect --format='{{index .RepoDigests 0}}' gcr.io/distroless/static:nonroot
# → gcr.io/distroless/static@sha256:1234567890abcdef...

# Для локального образа
docker images --digests my-app:latest
# → REPOSITORY   TAG       DIGEST                                                                   CREATED          SIZE
# → my-app       latest    sha256:abc123def456789...                                               2 minutes ago   8.2МB
```

### Сценарий 3: Dockerfile с минимальной поверхностью атаки

```dockerfile
# BAD: Полный образ с избыточными компонентами
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y \
    python3 python3-pip curl wget vim git netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*
# → ubuntu:24.04 (~78 МБ), curl/wget/netcat — вектор для reverse shell

# GOOD: Минимальный distroless
FROM gcr.io/distroless/python3-debian12
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["main.py"]
# → distroless/python3 (~50 МБ), нет shell, нет curl/wget
```

### Сценарий 4: Проверка подписи образа перед деплоем (Admission Control)

```yaml
# Kyverno: блокировка образов без валидной подписи
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-signature
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-cosign-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.internal/*"]
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                      -----END PUBLIC KEY-----
```

```bash
# Проверка: образ без подписи блокируется
kubectl run test --image=harbor.internal/my-app:unsigned --dry-run=server
# → Error: admission webhook denied the request

# Проверка: образ с подписью проходит
kubectl run test --image=harbor.internal/my-app@sha256:abc123... --dry-run=server
# → pod/test created (dry-run)
```

### Сценарий 5: Сканирование SBOM базового образа

```bash
# 1. Генерация SBOM для базового образа
syft gcr.io/distroless/static:nonroot -o cyclonedx-json > base-sbom.json

# 2. Проверка количества компонентов
jq '.components | length' base-sbom.json
# → 0 (distroless не содержит пакетов)

# 3. Сканирование на CVE
trivy image gcr.io/distroless/static:nonroot
# → 0 vulnerabilities found

# 4. Сравнение с полным образом
syft ubuntu:24.04 -o cyclonedx-json | jq '.components | length'
# → 142 (ubuntu содержит 142 компонента)
trivy image ubuntu:24.04 --severity CRITICAL
# → 12 critical vulnerabilities
```

### Сценарий 6: Renovate для автоматического обновления базовых образов

```json
// renovate.json — обновление базовых образов с digest pinning
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "docker": {
    "pinDigests": true
  },
  "packageRules": [
    {
      "matchManagers": ["dockerfile"],
      "matchUpdateTypes": ["minor", "patch"],
      "automerge": true
    },
    {
      "matchManagers": ["dockerfile"],
      "matchDepTypes": ["label:distroless"],
      "groupName": "distroless-base-images"
    }
  ]
}
```

## Валидация

```bash
# 1. Проверка: distroless-образ не содержит shell
FROM gcr.io/distroless/static:nonroot
RUN echo "test" > /tmp/test && cat /tmp/test
EOF
# Build succeeds, runtime test:
# docker run --rm my-app:latest which sh
# → (пустой вывод — sh не найден)

# 2. Проверка: образ не содержит пакетного менеджера
docker run --rm my-app:latest /bin/sh -c "ls /lib/apk/db/ || echo 'no apk'"
# → no apk

# 3. Проверка: USER nonroot в образе
docker inspect my-app:latest | jq -r '.[0].Config.User'
# → nonroot

# 4. Проверка: SBOM генерируется корректно
syft my-app:latest -o cyclonedx-json | jq '.components | length'
# → 0  (для distroless)

# 5. Проверка: Trivy находит 0 уязвимостей
trivy image --severity CRITICAL my-app:latest
# → 0 vulnerabilities found

# 6. Проверка: digest pinning в Kubernetes
kubectl get deployment my-app -o json | jq -r '.spec.template.spec.containers[0].image'
# → harbor.internal/my-app@sha256:abc123def456...

# 7. Проверка: Kyverno блокирует образы без подписи
kubectl auth can-i create pod --namespace=production
kubectl run test --image=harbor.internal/my-app:unsigned --dry-run=server
# → Error: admission webhook denied the request

# 8. Проверка: образ в registry прошёл сканирование Trivy
curl -s https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:abc123/vulnerabilities
# → {"total":0,"application/vnd.scanner.adapter.vuln.report.hours"}
```

## Лучшие практики

1. **Distroless/scratch по умолчанию:** Используйте минимальные образы, если нет веских причин для полного дистрибутива. Для статических Go/Rust-бинарников — `scratch`; для Python/Java/Node.js — `distroless`.
2. **Digest pinning всегда:** Никогда не используйте теги `latest`, `stable`, `v1` в production. Фиксируйте по `@sha256:...`. Автоматизируйте через Renovate (`pinDigests: true`).
3. **Multi-stage builds:** Сборка в изолированном окружении, runtime в distroless/scratch. Исключайте `.git`, `node_modules`, исходники из финального образа.
4. **Регулярное обновление:** Автоматизируйте обновление базовых образов через Renovate/Dependabot с SCA-гейтами. Для distroless используйте `label:distroless` в групповом правиле.
5. **Подпись перед деплоем:** Kyverno/OPA блокируют образы без валидной подписи Cosign/Notation. Используйте keyless-подпись через OIDC (GitHub Actions, GitLab CI).
6. **SBOM для каждого образа:** Генерируйте SBOM при сборке (Syft), прикрепляйте через OCI 1.1 Referrers API в Harbor. Для distroless SBOM будет пустым — это ожидаемо.
7. **Минимизация прав:** `USER nonroot:nonroot`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`. См. `Docker/Dockerfile/Docker_best_practices/security.md` для полного списка security-флагов.
8. **Не кэшируйте зависимости в образе:** Используйте `--mount=type=cache,target=/go/pkg/mod` (Go), `--mount=type=cache,target=/root/.npm` (Node.js) — кэш не попадает в слои образа.
9. **Сканируйте на этапе build:** Добавьте Trivy-шаг в CI/CD перед push в registry. Блокируйте CVE CRITICAL и HIGH.
10. **Не храните секреты в образе:** Используйте `.dockerignore` для исключения `.env`, `*.pem`, `*.key`; передавайте секреты через Kubernetes Secrets или HashiCorp Vault.

## Устранение неполадок

| Симптом | Причина | Решение |
|:--- |:--- |:--- |
| Distroless: `exec: "sh": not found` | В образе отсутствует shell | Используйте `kubectl debug --target` с эфемерным контейнером (см. `Kubernetes/Base/Pod/ephemeral_containers.md`) |
| Digest pinning ломает Renovate | Renovate не распознаёт формат | Убедитесь, что `pinDigests: true` в конфигурации |
| Trivy находит CVE в distroless | Устаревший базовый образ | Обновите тег: `cgr.dev/distroless/static:latest` или `gcr.io/distroless/static:nonroot-debian12` |
| SBOM не содержит компонентов | Syft не распознал distroless | Distroless не содержит пакетов — это нормально |
| Cosign: `no matching signatures` | Ключ rotated/истёк | Проверьте `cosign verify --certificate-oidc-issuer` и обновите публичный ключ в Kyverno |
| Kyverno: `ClusterPolicy is deprecated` | v1.19+ требует `ImageValidatingPolicy` | Мигрируйте с `verifyImages` на `ImageValidatingPolicy` (см. `artifact_signing.md`) |
| Harbor: SBOM исчезает после retention | Retention Policy удаляет referrers | Исключите SBOM из retention или используйте `Artifact-Cleanup` с исключением `|application/vnd.cyclonedx.json` |
| syft: `unsupported reference format` | Registry не поддерживает OCI 1.1 Referrers | Добавьте `--oci-platform linux/amd64` или используйте `--from registry` |
| BuildKit cache: невоспроизводимый образ | Cache между сборками | Используйте `--cache-from=type=inline` и `--cache-to=type=inline,mode=max` |

## Граничные случаи и ограничения

* **Distroless и отладка:** В distroless нет shell и утилит. Для отладки используйте `kubectl debug` с эфемерными контейнерами (`-c debug --image=nixery.dev/busybox`) или `--share-processes` для просмотра процессов. Также смотрите `Docker/Docker_troubleshooting/debugging_distroless.md`.
* **Multi-arch образы:** При фиксации по digest учитывайте, что digest разный для `linux/amd64` и `linux/arm64`. Используйте image index (manifest list) для мультиархитектурных образов, или фиксируйте digest для конкретной архитектуры.
* **Air-gapped среды:** Distroless-образы необходимо предварительно скопировать в локальный реестр. Chainguard/Wolfi доступны через `cgr.dev/chainguard/`. Используйте `skopeo copy` для миграции образов между реестрами без Docker daemon.
* **Лицензирование:** Distroless-образы Google используют Apache 2.0. Chainguard — полностью open-source. Учитывайте требования лицензий при выборе базового образа.
* **Statically linked binaries only:** Distroless и scratch требуют полностью статической линковки. C-расширения (Python C extensions, Java JNI) требуют glibc — используйте `-static` для GCC или переходите на `distroless/python3-debian12` (включает glibc).
* **Java Native Memory Tracking:** Distroless Java образы не включают JFR/JMC по умолчанию. Добавьте `-XX:StartFlightRecording` через `JAVA_TOOL_OPTIONS` и используйте `jcmd` через sidecar-контейнер.
* **Cosign и multi-arch:** Cosign подписывает image index как единое целое. `cosign verify` автоматически выбирает архитектуру подходящим под хост.
* **BuildKit cache между сборками:** При использовании `--mount=type=cache` кэш может устаревать и включать over-the-air атаки. Используйте `--shm-size=0` для изоляции и `BUILDKIT_CACHE_MOUNT_ID` для версионирования кэша.
* **Docker Content Trust (legacy):** Если используется Notary v1 (Docker Content Trust), мигрируйте на Cosign/Sigstore — Notary v1 не поддерживает SBOM-аттестации.

## Дополнительная информация

### Стандарты и ресурсы

* **Google Distroless:** <https://github.com/GoogleContainerTools/distroless> — официальный репозиторий.
* **Chainguard Images:** <https://www.chainguard.dev/chainguard-images> — hardened-образы с SBOM и подписями.
* **Wolfi:** <https://github.com/wolfi-dev> — безопасный дистрибутив для контейнеров.
* **Dockerfile Best Practices:** <https://docs.docker.com/build/building/best-practices/> — рекомендации по безопасной сборке.

### Связанные документы

* [Обзор безопасности цепочки поставок](./overview.md) — ландшафт угроз и общие принципы.
* [Целостность сборки](./build_integrity.md) — SLSA, provenance, герметичные сборки.
* [Подпись артефактов](./artifact_signing.md) — Cosign, Notation, OCI 1.1 Referrers.
* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX.
* [Docker Security](../../Docker/Docker_security/overview.md) — общая безопасность Docker.
* [Dockerfile Best Practices](../../Docker/Dockerfile/Docker_best_practices/security.md) — безопасные Dockerfile.
