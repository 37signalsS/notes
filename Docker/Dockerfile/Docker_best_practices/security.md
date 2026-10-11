# Безопасность в Dockerfile

**Актуально для:** Docker 24.x / BuildKit включён по умолчанию

## Определения

- **Поверхность атаки (Attack Surface):** Совокупность всех установленных пакетов, активных процессов, открытых портов и доступных утилит в контейнере, которые могут быть использованы для эксплولاتции.
- **Побег из контейнера (Container Escape):** Уязвимость или метод атаки, позволяющий процессу внутри контейнера преодолеть границы изоляции и получить доступ к ресурсам хостовой ОС.
- **Принцип наименьших привилегий (POLP):** Концепция, согласно которой процесс должен иметь только те права, которые минимально необходимы для его выполнения (например, запуск от непривилегированного пользователя).
- **Дайджест (SHA256 Digest):** Уникальный неизменяемый идентификатор образа по хешу содержимого. Использование дайджеста гарантирует, что вы получите ровно тот же код, который был проверен ранее, в отличие от мутабельных тегов (типа `latest`).
- **SBOM (Software Bill of Materials):** Машиночитаемый перечень всех компонентов и зависимостей образа, необходимый для аудита безопасности и соответствия стандартам (например, CycloneDX).
- **Hardening (Укрепление):** Процесс настройки образа для минимизации уязвимостей (удаление лишнего ПО, ограничение прав файловой системы).
- **Distroless / Chiseled:** Минималистичные образы, не содержащие менеджеров пакетов, shell и стандартных утилит Linux, что сводит поверхность атаки к абсолютному минимуму.
- **Rootless Docker:** Режим запуска демона Docker без прав root на хосте, предотвращающий компрометацию хоста при взломе демона. В 2026 году является рекомендованным стандартом для production-сред.
- **SELinux (Security-Enhanced Linux):** Мандатный контроль доступа (LSM) в RHEL/CentOS/Fedora, работающий по принципу enforcing/permitting по политикам. Docker применяет профиль `container_t` по умолчанию, дополняющий AppArmor на Debian-системах.
- **gVisor (runsc):** Песочница для контейнеров, в которой системные вызовы обрабатываются пользовательским ядром, а не напрямую ядром хоста. Повышает изоляцию для untrusted-кода.
- **Kata Containers:** Контейнеры, запущенные внутри легковесных виртуальных машин (QEMU/Cloud-Hypervisor), обеспечивающие аппаратную изоляцию.
- **Sandboxed Runtime:** Обобщающий термин для runtimes с повышенной изоляцией (gVisor, Kata, Firecracker).
- **.dockerignore:** Файл, исключающий файлы из контекста сборки. Без него в образ могут попасть секреты (`.env`, `*.pem`, `id_rsa`), кэши и артефакты разработки.
- **Docker Content Trust (DCT/Notary):** Механизм подписывания и верификации образов (устаревший, заменён на Cosign/Sigstore). Сохраняется для обратной совместимости.
- **Userns-remap:** Механизм маппинга UID 0 (root) внутри контейнера на непривилегированного пользователя хоста (например, UID 100000), предотвращающий эскалацию привилегий при побеге из контейнера.
- **Air-gapped среда:** Инфраструктура с физической изоляцией от внешних сетей. Требует предварительной загрузки образов и обновлений сканеров CVE.
- **Cgroups v2:** Современная версия Control Groups (стандарт по умолчанию с Docker 24+). Позволяет ограничивать CPU, RAM, I/O и количество процессов (pids-limit) для защиты от DoS-атак.
- **Linux Capabilities:** Механизм ядра Linux, разделяющий права суперпользователя (root) на отдельные полномочия (например, `NET_BIND_SERVICE`, `SYS_PTRACE`). Docker по умолчанию отключает опасные capabilities (например, `CAP_SYS_TIME`, `CAP_NET_ADMIN`), и позволяет настраивать набор через `--cap-add`/`--cap-drop`.
- **Seccomp (Secure Computing):** Механизм фильтрации системных вызовов, ограничивающий контейнер только безопасным набором системных вызовов. Docker применяет профиль `docker-default` по умолчанию, который блокирует ~44 опасных вызовов.
- **AppArmor:** Мандатный контроль доступа (LSM) в Ubuntu/Debian, ограничивающий доступ процесса к файлам, сетевым портам и capabilities на уровне политик. Docker применяет профиль `docker-default` по умолчанию.
- **SELinux (Security-Enhanced Linux):** Мандатный контроль доступа (LSM) в RHEL/CentOS/Fedora. Docker применяет профиль `container_t` по умолчанию, дополняющий AppArmor на Debian-системах.
- **VEX (Vulnerability Exploitability eXchange):** Формат аттестаций, позволяющий разработчику официально заявить, что конкретная CVE не влияет на продукт (например, из-за отсутствия вызова уязвимой функции), устраняя ложные срабатывания сканеров.

## Базовые концепции

### Минимизация поверхности атаки

Чем меньше инструментов находится в контейнере, тем сложнее злоумышленнику закрепиться в системе после взлома.
1.  **Multi-stage сборка:** Всегда разделяйте этапы сборки и рантайма. Сборочные инструменты (`gcc`, `npm`, `maven`) и исходный код не должны попадать в финальный образ.
2.  **Выбор базового образа:** Предпочитайте `scratch` (пустой образ), `distroless` или `alpine` полноразмерным образам типа `ubuntu` или `debian`.
3.  **Удаление лишнего:** Если в образе остались пакетные менеджеры, удаляйте их кэши и временные файлы в том же слое `RUN`, где они были созданы.
4.  **Изоляция зависимостей:** Используйте `COPY --link` и монтирование кэша (`--mount=type=cache`), чтобы зависимости не попадали в слои образа.
5.  **`.dockerignore`:** Исключайте из контекста сборки секреты (`.env`, `*.pem`, `id_rsa`, `*.key`), кэши (`node_modules`, `.git`) и артефакты разработки. Отсутствие `.dockerignore` — частая причина утечки секретов в образы.

### Изоляция и привилегии

По умолчанию Docker запускает процессы от пользователя `root` (UID 0), что создает риск Container Escape.
- **Инструкция USER:** Всегда создавайте системного пользователя и переключайтесь на него в конце `Dockerfile`.
- **Числовые UID:** Используйте числовые значения (например, `USER 10001`), так как Kubernetes и некоторые политики безопасности (Pod Security Standards) требуют возможности проверки UID без разбора `/etc/passwd`.
- **SUID/SGID биты:** Удаляйте эти биты у файлов, где они не нужны, чтобы предотвратить локальное повышение привилегий внутри контейнера.
- **Read-only rootfs:** Запуск контейнера с неизменяемой корневой ФС (`--read-only`) блокирует запись в системные директории, что предотвращает большинство эксплойтов. Временные данные храните в `tmpfs`.
- **Capabilities:** Используйте `--cap-drop=ALL` для удаления всех привилегий и `--cap-add` только для необходимых (например, `NET_BIND_SERVICE` для привязки к портам < 1024).
- **No-new-privileges:** Флаг `--security-opt=no-new-privileges` блокирует получение дополнительных прав дочерними процессами через SUID/SGID бинарники.
- **Seccomp:** Профиль `docker-default` включён по умолчанию. Избегайте `--security-opt seccomp=unconfined` в production.
- **AppArmor / SELinux:** Дополнительные мандатные контролы доступа (LSM). Docker применяет профили `docker-default` (AppArmor) и `container_t` (SELinux) по умолчанию. Детали: **[Укрепление контейнеров](../../Docker_security/container_hardening.md)**.
- **Rootless Docker:** Запуск демона и контейнеров от непривилегированного пользователя хоста — стандарт де-факто для production 2026. Предотвращает компрометацию хоста при взломе демона. Детали: **[Защита хоста и демона](../../Docker_security/host_daemon_hardening.md)**.
- **Resource Limits (Cgroups v2):** Ограничивайте CPU (`--cpus`), память (`--memory`, `--memory-swap`), I/O и количество процессов (`--pids-limit`) для защиты от DoS-атак. Отключение свопа (`--memory-swap` равным `--memory`) делает производительность предсказуемой. Детали: **[Укрепление контейнеров](../../Docker_security/container_hardening.md)**.
- **Sandboxed Runtimes (gVisor/Kata):** Для multi-tenancy и untrusted-кода используйте gVisor (`runsc`) или Kata Containers для аппаратной изоляции. Детали: **[Укрепление контейнеров](../../Docker_security/container_hardening.md#5-sandboxed-runtimes-повышенная-изоляция)**.

### Безопасность цепочки поставок (Supply Chain)

Гарантия того, что образ не был подменен или скомпрометирован между сборкой и запуском.
- **Pinning by Digest:** Фиксируйте базовые образы по SHA256. Теги `:latest`, `:stable` и даже `:3.21` могут быть переписаны в реестре.
- **Аттестации и подписи:** Используйте Docker Buildx для генерации аттестаций (Provenance и SBOM) и подписывайте образы (например, через `Cosign`).
- **Секреты сборки:** Никогда не передавайте секреты через `ARG` или `ENV`, так как они навсегда остаются в метаданных образа. Используйте механизмы BuildKit Secrets.
- **Верификация при запуске:** В Kubernetes используйте admission-контроллеры (Kyverno, OPA/Gatekeeper) для обязательной проверки подписей и SBOM перед запуском контейнера.

### Сетевая безопасность контейнера

Сеть — одна из наиболее уязвимых поверхностей контейнера. Docker v28+ закрывает по умолчанию входящий трафик из LAN к IP-адресам контейнеров на неопубликованные порты, но это защита от внешних соседей, а не сегментация: между контейнерами одной bridge-сети все порты остаются доступны, поэтому явная сегментация обязательна.

- **Привязка к localhost:** Используйте `-p 127.0.0.1:80:80` вместо `-p 80:80` для сервисов, не требующих внешнего доступа.
- **Открытые порты:** Каждый открытый порт — потенциальная точка атаки. Документируйте и минимизируйте количество портов.
- **Изолированные Docker networks:** Используйте отдельные сети для разных групп сервисов (frontend, backend, database) вместо общей сети `bridge`. Включите `--icc=false` для блокировки межконтейнерного взаимодействия внутри одной сети.
- **Внутренние сети (`--internal`):** Для сервисов, не требующих исходящего доступа в интернет (например, базы данных), используйте `docker network create --internal db-net`. Это блокирует весь внешний трафик.
- **DNS-безопасность:** Контейнеры наследуют DNS от хоста. Для критичных сервисов указывайте конкретные DNS-серверы через `--dns` и включайте DNSSEC (`--dns-opt edns0 trust-ad`), чтобы предотвратить DNS-отравление.
- **Шифрование Overlay-сетей:** В Docker Swarm используйте `--opt encrypted` для IPSec-шифрования трафика между узлами кластера.
- **Docker socket:** Никогда не монтируйте `/var/run/docker.sock` напрямую в продакшене. Используйте `docker-socket-proxy` с минимальными правами. Детали: **[Защита хоста и демона](../../Docker_security/host_daemon_hardening.md)**.
- **Сетевая политика (NetworkPolicy):** В Kubernetes используйте NetworkPolicy для сегментации трафика между подами. Детали: **[Сетевые политики Docker](../../Docker_network/docker_network_policies.md)**.

## Предварительные требования

- **Docker** версии 24.x или новее (Cgroups v2, BuildKit по умолчанию, Rootless стабильный).
- **Docker Compose** версии 2.x (для определения сетей, tmpfs и security-opt в `compose.yaml`).
- **Kubernetes** версии 1.28+ (для Pod Security Standards `restricted` и RuntimeDefault seccomp).
- **Linux Kernel** версии 5.19+ (полная поддержка Cgroups v2, User Namespaces, Landlock).
- **Rootless mode** (опционально, но рекомендуется): требует ядро >= 5.11 и настройки `userns`.
- **ОС хоста:** Ubuntu 22.04+/Debian 12+ (AppArmor), RHEL 9+/Fedora 40+ (SELinux enforcing).
- **Инструменты для валидации:** `trivy`, `hadolint`, `dockle`, `cosign`, `docker scout` (см. раздел валидации).

## Практические сценарии

### Сценарий 1: Укрепление образа (Hardening)

Пример создания безопасного контейнера на базе Alpine с удалением опасных прав.

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21@sha256:56fa17d2a...

# Создаем непривилегированного пользователя
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

# Копируем бинарник сразу с нужными правами
COPY --chown=appuser:appgroup ./my-app .

# Удаление SUID/SGID битов для предотвращения повышения привилегий
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

# Ограничение прав на запись (только нужные папки)
RUN chmod 0500 /app/my-app

USER 10001
ENTRYPOINT ["./my-app"]
```

### Сценарий 2: Использование BuildKit Secrets

Безопасная передача токена для установки приватных зависимостей.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .

# Секрет монтируется в RAM и не сохраняется в слоях образа
RUN --mount=type=secret,id=pip_config \
    PIP_CONFIG_FILE=/run/secrets/pip_config pip install -r requirements.txt

COPY . .
# ... дальнейшая сборка
```
Команда сборки: `docker build --secret id=pip_config,src=$HOME/.pip/pip.conf .`

### Сценарий 3: Использование Distroless (Java)

Максимальная защита для Java-приложения: в образе нет даже `sh`.

```dockerfile
# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY . .
RUN mvn package

# Рантайм на базе Distroless
FROM gcr.io/distroless/java21-debian12@sha256:d81...
COPY --from=build /app/target/app.jar /app/app.jar
USER 10001
CMD ["/app/app.jar"]
```

### Сценарий 4: Генерация SBOM при сборке

Использование современных аттестаций для комплаенса.

```bash
# Сборка с автоматическим созданием состава ПО и метаданных сборки
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --tag my-registry/app:1.2.3 \
  --push .
```
### Сценарий 5: Read-only rootfs с tmpfs

Запуск контейнера с неизменяемой файловой системой — все временные данные в tmpfs.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY . .
USER 10001
EXPOSE 3000
CMD ["node", "server.js"]
```

```bash
# Запуск с read-only rootfs и tmpfs для временных данных
docker run -d \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --tmpfs /app/logs:rw,noexec,nosuid,size=32m \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges \
  -p 3000:3000 \
  my-app:latest

# Проверка: попытка записи в корень ФС
docker exec <container> touch /test 2>&1
# → touch: /test: Read-only file system
```

### Сценарий 6: Kubernetes Security Context

Интеграция с Pod Security Standards (restricted профиль) — минимальные привилегии.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: my-registry/app@sha256:abc123...
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        limits:
          memory: "128Mi"
          cpu: "500m"
      volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /app/cache
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 64Mi
    - name: cache
      emptyDir:
        sizeLimit: 32Mi
```

**Валидация:**
```bash
# Проверка что контейнер запущен от non-root
kubectl exec secure-app -- id
# → uid=10001 gid=10001 groups=10001

# Проверка что rootfs read-only
kubectl exec secure-app -- touch /test 2>&1
# → touch: cannot touch '/test': Read-only file system
```
### Сценарий 7: Distroless Go с кросс-компиляцией

Максимально безопасный образ: ~5MB, без shell, без пакетного менеджера.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.24-alpine AS builder

ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -o /app/server .

# Финальный образ: distroless (нет shell, нет apt, нет утилит)
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

**Валидация:**
```bash
# Попытка открыть shell — невозможна
docker run --rm my-app:latest /bin/sh
# → exec: "/bin/sh": executable file not found in $PATH

# Проверка размера образа
docker images my-app:latest
# → REPOSITORY   TAG       SIZE
# → my-app       latest    5.8MB
```

### Сценарий 8: Подписание и верификация образов

Гарантия целостности образа через криптографическую подпись (Cosign/Sigstore).

```bash
# 1. Генерация ключей
cosign generate-key-pair

# 2. Подписание образа после сборки
cosign sign --key cosign.key my-registry/app:v1

# 3. Прикрепление SBOM как аттестации
cosign attest --key cosign.key --predicate sbom.json \
  --type cyclonedx my-registry/app:v1

# 4. Верификация перед запуском (в CI/CD или admission-контроллере)
cosign verify --key cosign.pub my-registry/app:v1

# 5. Верификация аттестации SBOM
cosign verify-attestation --type cyclonedx \
  --key cosign.pub my-registry/app:v1
```

**Автоматическая проверка в GitHub Actions:**

```yaml
- name: Verify image signature
  run: |
    cosign verify \
      --key cosign.pub \
      my-registry/app:${{ github.sha }}
```

**Автоматическая проверка в Kubernetes (Kyverno):**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-image-signature
      match:
        any:
          - resources:
              kinds:
                - Pod
      verifyImages:
        - imageReferences:
            - "my-registry/*"
          attestations:
            - type: https://cosign.sigstore.dev/attestation/v1
              conditions:
                - all:
                    - key: "{{ builder.id }}"
                      operator: Equals
                      value: "https://github.com/owner/repo/.github/workflows/ci.yml"
```

### Сценарий 9: Ограничение ресурсов (Cgroups v2)

Запуск контейнера с жёсткими лимитами CPU, памяти и процессов для защиты от DoS-атак.

```bash
docker run -d \
  --memory="512m" \
  --memory-swap="512m" \
  --cpus="0.5" \
  --pids-limit 100 \
  --ulimit nofile=1024:2048 \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -p 3000:3000 \
  my-app:latest
```

**Валидация:**
```bash
# Проверка лимитов
docker inspect <container> --format '{{.HostConfig.Memory}}'
# → 536870912 (512 MiB)

# Проверка pids-limit
docker inspect <container> --format '{{.HostConfig.PidsLimit}}'
# → 100

# Тест OOM: запуск с недостаточной памятью
docker run --memory="128m" my-app:latest stress --vm 1 --vm-bytes 200M
# → killed (OOM)
```

### Сценарий 10: Air-gapped среда (без доступа к интернет)

В изолированной инфраструктуре образы и обновления сканеров должны быть предварительно загружены.

```bash
# 1. Предварительная загрузка базовых образов во внутренний registry
docker pull alpine:3.21
docker tag alpine:3.21 registry.internal/alpine:3.21
docker push registry.internal/alpine:3.21

# 2. Загрузка базы данных Trivy для офлайн-сканирования
trivy image --download-db-only --db-repository registry.internal/trivy-db

# 3. Сборка с использованием внутреннего registry
docker build --build-arg BASE_IMAGE=registry.internal/alpine:3.21 -t my-app:latest .

# 4. Сканирование в air-gapped среде
trivy image --db-repository registry.internal/trivy-db my-app:latest

# 5. Генерация SBOM офлайн
syft registry.internal/my-app:latest -o cyclonedx-json > sbom.json
```

**Docker Compose для air-gapped:**
```yaml
services:
  app:
    build:
      context: .
      args:
        BASE_IMAGE: registry.internal/python:3.12-slim
    image: registry.internal/my-app:latest
```

### Сценарий 11: .dockerignore для безопасности

Исключение секретов и артефактов разработки из контекста сборки.

```dockerignore
# Секреты
.env
*.pem
*.key
id_rsa
*.p12
secrets/

# Кэши и зависимости
node_modules
__pycache__
.git
.gitlab-ci.yml
.dockerignore

# Артефакты разработки
dist
build
coverage
*.log
tmp/
temp/
```

**Валидация:**
```bash
# Проверка что секреты не попали в образ
docker build -t test-app .
docker run --rm test-app ls -la /app/.env 2>&1
# → ls: cannot access '/app/.env': No such file or directory

# Проверка размера контекста сборки (BuildKit)
docker build --no-cache --progress=plain . 2>&1 | grep "transferring context"
# → #5 transferring context: 2.048kB done (проверьте что нет лишних файлов)
```

### Сценарий 12: Запуск через gVisor (Sandboxed Runtime)

Для untrusted-кода или multi-tenancy с повышенными требованиями к изоляции.

```bash
# 1. Установка gVisor
curl -fsSL https://gvisor.dev/launch | bash

# 2. Запуск Docker демона с поддержкой runsc
# В /etc/docker/daemon.json:
cat <<EOF | sudo tee /etc/docker/daemon.json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/local/bin/runsc"
    }
  }
}
EOF
sudo systemctl restart docker

# 3. Запуск контейнера через gVisor
docker run --runtime=runsc --rm my-untrusted-app:latest

# 4. Проверка что используется runsc
docker inspect <container> --format '{{.HostConfig.Runtime}}'
# → runsc
```

**Валидация:**
```bash
# Попытка монтирования /proc (заблокировано gVisor)
docker run --runtime=runsc --rm alpine mount -t proc proc /proc 2>&1
# → mount: /proc: permission denied.

# Проверка доступных системных вызовов
docker run --runtime=runsc --rm strace -c alpine true
# → только разрешённые syscalls
```

## Валидация и диагностика

### Проверка Dockerfile

```bash
# Встроенный линтер BuildKit
docker buildx build --check .
# → [WARNING] ...: UndefinedVar: TargetStageName is not defined as an ARG

# Hadolint — статический анализ Dockerfile
hadolint Dockerfile
# → DL3008 Pin versions in apt get install
# → DL3009 Delete the apt-get lists after installing
# → DL3025 Use arguments JSON notation for CMD
```

### Проверка образа

```bash
# Trivy — поиск CVE в пакетах и зависимостях
trivy image my-app:latest
# → Total: 3 (UNKNOWN: 0, LOW: 1, MEDIUM: 1, HIGH: 1, CRITICAL: 0)

# Dockle — проверка на соответствие лучшим практикам
dockle my-app:latest
# → [PASS] CIS-DI-0001: Create a user for the container
# → [PASS] CIS-DI-0002: Use trusted base images
# → [WARN] CIS-DI-0006: Add HEALTHCHECK instruction

# Docker Scout — рекомендации и CVE
docker scout quickview my-app:latest
docker scout cves my-app:latest --only-severity critical,high

# Copacetic — патчинг образа без пересборки
trivy image --format json --output report.json my-app:latest
copa patch --image my-app:latest --report report.json --tag patched
```

### Проверка read-only и привилегий

```bash
# Проверка что rootfs read-only
docker run --rm --read-only alpine touch /test 2>&1
# → touch: /test: Read-only file system

# Проверка capabilities контейнера
docker inspect <container> --format '{{.HostConfig.CapAdd}}'
# → [NET_BIND_SERVICE]

# Проверка что контейнер запущен от non-root
docker exec <container> id
# → uid=10001 gid=10001

# Проверка seccomp-профиля
docker inspect <container> --format '{{.HostConfig.SecurityOpt}}'
# → [seccomp=default]
```

### Проверка подписи и SBOM

```bash
# Проверка подписи образа
cosign verify --key cosign.pub my-registry/app:v1

# Просмотр SBOM в образе
docker buildx imagetools inspect my-registry/app:v1 \
  --format '{{ json .SBOM }}' | jq '.artifacts | length'
# → 42

# Проверка provenance
docker buildx imagetools inspect my-registry/app:v1 \
  --format '{{ json .Provenance }}' | jq '.buildType'
# → "https://github.com/moby/buildkit/client/llb"
```

### Проверка подозрительных файлов

```bash
# Поиск SUID/SGID битов
docker run --rm my-app:latest find / -xdev -perm /6000 -type f 2>/dev/null
# → (пустой вывод = хорошо, биты удалены)

# Поиск скрытых секретов
docker run --rm my-app:latest grep -r "password\|secret\|token" /etc/ 2>/dev/null
# → (пустой вывод = хорошо)

# Проверка что в образе нет shell
docker run --rm my-app:latest /bin/sh -c "echo hacked" 2>&1
# → exec: "/bin/sh": executable file not found in $PATH
```
## Типичные ошибки и их решение

### Ошибка 1: Контейнер запущен от root

**Причина:** В Dockerfile нет инструкции `USER` или приложение требует root для привязки к порту < 1024.

```dockerfile
# ПЛОХО: нет инструкции USER
FROM node:22-alpine
WORKDIR /app
COPY . .
CMD ["node", "server.js"]

# ХОРОШО: non-root пользователь
FROM node:22-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --chown=appuser:appgroup . .
USER 10001
CMD ["node", "server.js"]
```

**Если нужен порт < 1024:** используйте `--cap-add=NET_BIND_SERVICE` вместо запуска от root.

### Ошибка 2: Секрет попадает в слой образа

**Причина:** Секрет передан через `ENV`, `ARG` или `COPY`.

```dockerfile
# ПЛОХО: пароль навсегда в истории
ENV DB_PASS=secret123
COPY .env /app/.env
RUN PGPASSWORD=$DB_PASS pg_dump ...

# ХОРОШО: секрет через BuildKit
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=db_pass \
    PGPASSWORD=$(cat /run/secrets/db_pass) pg_dump ...
```

```bash
# Запуск сборки с секретом
docker buildx build --secret id=db_pass,src=./db_pass.txt -t myapp .
```

### Ошибка 3: `--read-only` ломает приложение

**Причина:** Приложение пишет во временную директорию или логи.

```bash
# Диагностика: что именно пытается записать?
docker run --rm --read-only my-app:latest 2>&1 | grep "Read-only"

# Решение: добавить tmpfs для нужных директорий
docker run -d \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --tmpfs /app/logs:rw,noexec,nosuid,size=32m \
  my-app:latest
```

### Ошибка 4: `cap-drop=ALL` ломает сетевой доступ

**Причина:** После удаления всех capabilities контейнер не может привязаться к порту или использовать сеть.

```bash
# Диагностика: что именно требует capabilities?
docker run --rm --cap-drop=ALL my-app:latest 2>&1 | grep "capability"

# Решение: добавить только нужные capabilities
docker run -d \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --cap-add=NET_RAW \
  my-app:latest
```

### Ошибка 5: Distroless не даёт отладить проблему

**Причина:** В distroless нет shell, поэтому невозможно войти в контейнер для отладки.

```bash
# Решение 1: использовать debug-версию distroless
FROM gcr.io/distroless/base-debian12:debug

# Решение 2: multi-stage — отладка в builder, production в distroless
# syntax=docker/dockerfile:1
FROM golang:1.24-alpine AS builder
# ... сборка ...

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]

# Для отладки: собрать отдельный образ с debug
FROM gcr.io/distroless/static-debian12:debug
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

### Ошибка 6: Cosign verify падает с "no matching signatures"

**Причина:** Образ не подписан или ключ не совпадает.

```bash
# Диагностика: кто подписал образ?
cosign triangulate my-registry/app:v1
# → my-registry/app@sha256:...

# Проверка что образ вообще подписан
cosign verify --key cosign.pub my-registry/app:v1 2>&1
# → Error: no matching signatures

# Решение: убедиться что ключ правильный и образ подписан тем же ключом
cosign sign --key cosign.key my-registry/app:v1
cosign verify --key cosign.pub my-registry/app:v1
```

### Ошибка 7: Hadolint ругается на каждую строку

**Причина:** Используются устаревшие практики (без pinning версий, без `--no-install-recommends`).

```dockerfile
# ПЛОХО: без pinning и очистки
RUN apt-get update && apt-get install -y curl

# ХОРОШО: с pinning, очисткой и JSON-синтаксисом
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl=8.5.0-2ubuntu1 && \
    rm -rf /var/lib/apt/lists/*

# Отключение отдельного правила (если оно ложное)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y curl
```

### Ошибка 8: SBOM не прикрепляется к образу

**Причина:** Нет поддержки OCI 1.1 Referrers API в реестре.

```bash
# Проверка: поддерживает ли реестр referrers
docker buildx imagetools inspect my-registry/app:v1 \
  --format '{{ json .SBOM }}'
# → null (реестр не поддерживает)

# Решение: использовать реестр с OCI 1.1 (Harbor 2.11+, GHCR, Docker Hub)
# Или использовать inline SBOM (встраивается в манифест)
docker buildx build \
  --sbom=true \
  --provenance=mode=max \
  --cache-to type=registry,ref=my-registry/cache:app \
  --push -t my-registry/app:v1 .
```
## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | Всегда разделять сборку и рантайм | Инструменты сборки не попадают в образ |
| **Non-root** | `USER 10001` в конце Dockerfile | Предотвращение Container Escape |
| **Read-only** | `--read-only` + tmpfs | Блокировка записи в системные директории |
| **Capabilities** | `--cap-drop=ALL` + только нужные | Минимизация привилегий |
| **No-new-privileges** | `--security-opt=no-new-privileges` | Блокировка эскалации через SUID |
| **Pinning** | `FROM image@sha256:...` | Гарантия воспроизводимости |
| **BuildKit Secrets** | `--mount=type=secret` | Секреты не попадают в слои |
| **Distroless** | Для production Go/Java/Python | Минимальная поверхность атаки |
| **SBOM + Provenance** | `--sbom=true --provenance=mode=max` | Аудит и комплаенс |
| **Image Signing** | Cosign/Sigstore | Гарантия целостности образа |
| **Seccomp** | `docker-default` (по умолчанию) | Блокировка опасных системных вызовов |
| **AppArmor/SELinux** | `docker-default`/`container_t` (по умолчанию) | Мандатный контроль доступа |
| **Rootless Docker** | Запуск демона без root на хосте | Предотвращение компрометации хоста |
| **Resource Limits** | `--memory`, `--cpus`, `--pids-limit` | Защита от DoS-атак |
| **.dockerignore** | Исключение секретов и кэшей | Предотвращение утечки данных в образ |
| **Network Isolation** | Отдельные сети, `--internal`, `--icc=false` | Сегментация и минимизация поверхности |
| **Sandboxed Runtime** | gVisor/Kata для untrusted-кода | Аппаратная/пользовательская изоляция ядра |
| **Copacetic** | Патчинг CVE без пересборки | Быстрое исправление уязвимостей |

### Порядок инструкций в безопасном Dockerfile

```dockerfile
# 1. Версия синтаксиса
# syntax=docker/dockerfile:1

# 2. Базовый образ с pinning по дайджесту
FROM node:22-alpine@sha256:abc123... AS builder

# 3. SHELL (если нужен pipefail)
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# 4. Сборочные зависимости (builder stage)
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# 5. Исходный код
COPY --link . .
RUN npm run build

# 6. Финальная стадия (минимальный образ)
FROM node:22-alpine@sha256:abc123...

# 7. Системный пользователь (ДО копирования файлов)
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# 8. Удаление опасных битов
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + || true

# 9. Копирование артефактов с нужными правами
WORKDIR /app
COPY --from=builder --chown=appuser:appgroup /app/dist ./dist

# 10. Переключение на non-root
USER 10001

# 11. Метаданные
LABEL version="1.0" maintainer="security@example.com"

# 12. Entrypoint (exec-form)
ENTRYPOINT ["node", "dist/server.js"]
```

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Инструкция `USER` с числовым UID (не имя пользователя)
- [ ] Multi-stage: финальная стадия не содержит инструменты сборки
- [ ] Базовый образ зафиксирован по SHA256 дайджесту
- [ ] SUID/SGID биты удалены
- [ ] `.dockerignore` исключает секреты и артефакты разработки
- [ ] Нет секретов в `ENV`, `ARG` или `COPY`
- [ ] Используется `--mount=type=secret` для секретов сборки
- [ ] `--no-install-recommends` при установке пакетов
- [ ] Кэш пакетного менеджера удалён в том же RUN

**Запуск контейнера:**
- [ ] `--read-only` с tmpfs для временных данных
- [ ] `--cap-drop=ALL` + только необходимые capabilities
- [ ] `--security-opt=no-new-privileges`
- [ ] `--memory`, `--cpus`, `--pids-limit` заданы
- [ ] `--memory-swap` равен `--memory` (отключение свопа)
- [ ] Привязка портов к localhost (если не нужен внешний доступ)
- [ ] Изолированные Docker networks, `--icc=false` или `--internal`
- [ ] Конкретные `--dns` и DNSSEC для критичных сервисов

**Сборка и доставка:**
- [ ] `--sbom=true` и `--provenance=mode=max` включены
- [ ] Образ подписан через Cosign/Sigstore
- [ ] Trivy/Dockle не выявил критических проблем
- [ ] SBOM проверен (Copacetic для быстрого патчинга без пересборки)
- [ ] Удалённый кэш настроен для CI/CD
- [ ] Admission-контроллер (Kyverno/OPA) проверяет подписи перед запуском

## Граничные случаи и ограничения

### Distroless и отладка

В distroless/chiseled образах нет shell и стандартных утилит, поэтому невозможно войти в контейнер через `docker exec`. Для отладки используйте:
- Debug-версии образов: Google Distroless — тег `:debug` (BusyBox); Chainguard — `-dev`-вариант (например, `cgr.dev/chainguard/static:latest-dev`).
- Multi-stage: отладка в builder stage, production в distroless.
- `kubectl debug` с эфемерными контейнерами (Kubernetes).

### Rootless Docker и User Namespaces

Rootless mode несовместим с некоторыми возможностями:
- Нельзя монтировать `cgroups` напрямую.
- Некоторые storage drivers (devicemapper, btrfs) требуют дополнительной настройки.
- `--privileged` не работает в Rootless контейнерах (это не баг, а фича).

### Air-gapped среды

В изолированных инфраструктурах:
- Предварительно загружайте все базовые образы во внутренний registry.
- Кэшируйте базы данных CVE для Trivy/Grype.
- SBOM и подписи генерируются офлайн и хранятся в реестре.
- Copacetic не работает без доступа к репозиториям исправлений.

### gVisor/Kata Containers

- gVisor имеет ограниченную поддержку network-драйверов (не работает с `macvlan`).
- Kata Containers требует поддержки KVM на хосте и имеет больший overhead (~100MB на контейнер).
- Оба runtime несовместимы с `--privileged` и некоторыми capabilities.

### Resource Limits и OOM

- При достижении `--memory` limit Docker убивает контейнер с кодом 137 (SIGKILL).
- `--memory-swap` равный `--memory` отключает swap для контейнера, делая производительность предсказуемой.
- `--pids-limit` защищает от fork-бомб, но слишком низкое значение ( < 50) может сломать приложения с пулом потоков.

### Docker Content Trust (DCT)

DCT (Notary) является устаревшим механизмом. В 2026 году рекомендуется Cosign/Sigstore:
- DCT подписывает теги, а не дайджесты (уязвим к tag mutation).
- Cosign подписывает дайджесты, что обеспечивает неизменяемость.
- Миграция с DCT на Cosign: **[Подписание и верификация образов](../../Docker_security/image_signature_and_verification.md)**.

## Дополнительная информация

### Взаимодействие с CI/CD

**GitHub Actions с безопасностью:**

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write  # Для keyless signing через Sigstore
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: |
          docker buildx build \
            --sbom=true \
            --provenance=mode=max \
            --cache-to type=gha,mode=max \
            --cache-from type=gha \
            --push -t ghcr.io/${{ github.repository }}:${{ github.sha }} .

      - name: Sign image
        run: |
          cosign sign --yes ghcr.io/${{ github.repository }}:${{ github.sha }}

      - name: Verify signature
        run: |
          cosign verify \
            --certificate-identity "https://github.com/${{ github.repository }}/.github/workflows/build.yml@refs/heads/main" \
            --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
            ghcr.io/${{ github.repository }}:${{ github.sha }}
```

### Смотрите также

- **[Управление секретами в Docker](../../Docker_security/secrets_management.md)** — глубокий разбор ENV, Secrets и Vault.
- **[Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md)** — настройка Trivy и Grype в пайплайнах.
- **[SBOM для Docker](../../Docker_security/docker_sbom.md)** — форматы и способы генерации состава ПО.
- **[Укрепление контейнеров](../../Docker_security/container_hardening.md)** — AppArmor, Seccomp и Capabilities.
- **[Безопасность цепочки поставок](../../../Security/Supply_Chain_Security/overview.md)** — стандарты SLSA и защита от атак на зависимости.
- **[Подписание и верификация образов](../../Docker_security/image_signature_and_verification.md)** — использование Cosign и Sigstore.
- **[Изоляция Linux](../../Concepts/linux_isolation.md)** — namespaces, cgroups, capabilities и rootfs.
- **[Docker Bench for Security (CIS)](../../Docker_security/docker_bench_cis.md)** — аудит конфигурации хоста и демона по CIS Benchmark.
- **[Защита хоста и демона](../../Docker_security/host_daemon_hardening.md)** — rootless, userns-remap, защита `/var/run/docker.sock`.
- **[SSH-agent в rootless Docker](../../Docker_security/ssh-agent-rootless.md)** — доступ к приватным репозиториям без экспозиции ключа.
- **[Мониторинг безопасности в Runtime](../../Docker_security/runtime_monitoring.md)** — Falco, Tetragon, eBPF-детектирование аномалий.
- **[Антипаттерны Dockerfile](../dockerfile-anti-patterns.md)** — каталог антипаттернов: размер, безопасность, сборка, runtime.
