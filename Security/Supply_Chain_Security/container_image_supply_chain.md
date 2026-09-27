# Безопасность цепочки поставок контейнерных образов

## Определения

* **Container Image Supply Chain (Цепочка поставок контейнерных образов):** Совокупность всех компонентов, участвующих в создании, хранении и распространении Docker/OCI-образов: базовые образы, пакеты ОС, зависимости приложения, инструменты сборки, реестры артефактов и механизмы распространения.
* **Distroless Image (Образ без дистрибутива):** Минимальный образ, содержащий только приложение и его runtime-зависимости (без shell, пакетного менеджера, утилит ОС). Снижает поверхность атаки на порядки. Примеры: Google Distroless, Chainguard, Wolfi.
* **Digest Pinning (Фиксация по дайджесту):** Привязка образа к неизменяемому хеш-сумме (`image@sha256:...`), а не к изменяемому тегу (`image:latest`). Гарантирует, что при повторном pull скачивается идентичный артефакт.
* **Multi-stage Build (Многоступенчатая сборка):** Паттерн Dockerfile, при котором сборка и запуск происходят в разных стадиях. Финальный образ содержит только скомпилированный бинарник и минимальный runtime, исключая инструменты сборки.
* **Hardened Base Image (Усиленный базовый образ):** Базовый образ, оптимизированный для безопасности: минимальный набор пакетов, регулярные обновления безопасности, предустановленный SBOM, отсутствие known CVE.
* **Image Provenance (Происхождение образа):** Аттестация, описывающая процесс создания образа: какой Dockerfile, какие зависимости, какой CI/CD-пайплайн, какой реестр. Позволяет проверить, что образ не был подменён.

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
FROM golang:1.22@sha256:abc123... AS builder
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
# → my-app       latest    8.2 МБ (вместо 800+ МБ с golang:1.22)

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

## Лучшие практики

1. **Distroless/scratch по умолчанию:** Используйте минимальные образы, если нет веских причин для полного дистрибутива.
2. **Digest pinning всегда:** Никогда не используйте теги `latest`, `stable`, `v1` в production. Фиксируйте по `@sha256:...`.
3. **Multi-stage builds:** Сборка в изолированном окружении, runtime в distroless/scratch.
4. **Регулярное обновление:** Автоматизируйте обновление базовых образов через Renovate/Dependabot с SCA-гейтами.
5. **Подпись перед деплоем:** Kyverno/OPA блокируют образы без валидной подписи Cosign/Notation.
6. **SBOM для каждого образа:** Генерация SBOM при сборке, прикрепление через OCI 1.1 Referrers API.
7. **Минимизация прав:** `USER nonroot:nonroot`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`.

## Устранение неполадок

| Симптом | Причина | Решение |
|:--- |:--- |:--- |
| Distroless: `exec: "sh": not found` | В образе отсутствует shell | Используйте `kubectl debug --target` с эфемерным контейнером |
| Digest pinning ломает Renovate | Renovate не распознаёт формат | Убедитесь, что `pinDigests: true` в конфигурации |
| Trivy находит CVE в distroless | Устаревший базовый образ | Обновите тег: `chainguard.dev/static:latest` |
| SBOM не содержит компонентов | Syft не распознал distroless | Distroless не содержит пакетов — это нормально |

## Граничные случаи и ограничения

* **Distroless и отладка:** В distroless нет shell и утилит. Для отладки используйте `kubectl debug` с эфемерными контейнерами или `--share-processes` для просмотра процессов.
* **Multi-arch образы:** При фиксации по digest учитывайте, что digest разный для `linux/amd64` и `linux/arm64`. Используйте image index (manifest list) для мультиархитектурных образов.
* **Air-gapped среды:** Distroless-образы необходимо предварительно скопировать в локальный реестр. Chainguard/Wolfi доступны через `cgr.dev/chainguard/`.
* **Лицензирование:** Distroless-образы Google используют Apache 2.0. Chainguard — полностью open-source. Учитывайте требования лицензий при выборе базового образа.

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
