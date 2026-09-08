# vCluster — установка и развёртывание

> Документ покрывает все пути первичного развёртывания vCluster: установку CLI, выбор режима запуска (Host-based, Standalone, Docker/vind, Helm), полный жизненный цикл (create / upgrade / pause / resume / delete) и сопутствующие операции для DevOps/SRE/sysadmin. Архитектурные концепции (Syncer, Backing Store, Resource Patching, Sleep Mode) описаны в [обзоре](./vcluster_overview.md), сетевая связность и доступ — в [vcluster_connectivity.md](./vcluster_connectivity.md), безопасность и патчи — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**vCluster CLI (Command Line Interface)** — основной инструмент управления жизненным циклом виртуальных кластеров: создание, настройка, подключение и удаление. Бинарный файл написан на Go, статически слинкован, распространяется под BSL (Business Source License) с открытым исходным кодом. Версии: stable-релиз каждые ~6 недель, правая цифра в SemVer обозначает совместимость API.

**vCluster Standalone** — режим установки (v0.30+), позволяющий развернуть Control Plane vCluster как независимый процесс непосредственно на ОС хоста (Bare Metal/VM). Решает проблему "Cluster Zero", не требуя предварительного наличия Kubernetes. Устанавливается через `install-standalone.sh`, работает как systemd-юнит.

**vind (vCluster in Docker)** — драйвер для запуска виртуальных кластеров в контейнерах Docker (аналог `kind`). Идеально подходит для локальной разработки и тестирования. Control Plane работает в одном контейнере, "worker-узлы" эмулируются через `vcluster-node` внутри того же сетевого namespace. Полезен для CI без доступа к реальному кластеру.

**Дистрибутив (Distro)** — реализация Control Plane. В версиях v0.33+ основным и рекомендуемым является стандартный **Kubernetes (upstream)**. Поддержка K3s в новых мажорных версиях прекращена в пользу встроенного etcd и чистого K8s. Доступные дистрибутивы: `k8s` (Vanilla), `k3s` (legacy), `k0s` (облегчённый).

**vcluster.yaml** — унифицированный конфигурационный файл. В версиях 2026 года (v0.30+) структура оптимизирована: параметры масштабирования, безопасности и сетевого взаимодействия вынесены на верхний уровень. Заменяет разрозненные Helm values, используется CLI и Helm-установщиком.

**Backing Store (Хранилище состояния)** — компонент, в котором виртуальный Control Plane хранит своё состояние. В v0.33+ по умолчанию используется embedded etcd (для Vanilla K8s) или SQLite (для K3s). Также поддерживаются внешние PostgreSQL/MySQL через драйвер Kine.

**Host-based mode (Pod mode)** — основной production-режим: Control Plane vCluster работает как набор подов внутри namespace хостового Kubernetes. Syncer внутри пода обеспечивает связь с API хоста. Требует, чтобы хост-кластер уже существовал.

**Sleep Mode (Режим сна)** — функция (v0.20+), позволяющая останавливать все workload-поды и переводить Control Plane в idle-состояние при отсутствии активности. Auto-wakeup активирует кластер при первом обращении к API. Подробное описание — в [обзоре](./vcluster_overview.md#sleep-mode-внутренний-механизм).

**Driver (Драйвер)** — абстракция в vcluster CLI, описывающая, где физически запускается Control Plane. Возможные значения: `k8s` (по умолчанию, Host-based), `docker` (vind), `local` (in-process). Выбирается флагом `--driver`.

**Loft** — компания-разработчик vCluster и одноимённая Enterprise-платформа для централизованного управления виртуальными кластерами. Open Source-версия vCluster CLI работает без Loft Platform, но некоторые функции (UI, SSO, централизованный аудит) доступны только в коммерческой редакции.

**Helm Chart (loft/vcluster)** — официальный чарт vCluster (https://charts.loft.sh), используется для GitOps-установки. Поддерживает как `values.yaml`, так и `vcluster.yaml` через `extraArgs` и custom ресурсы.

## Основные концепции

### Способы установки CLI

| Платформа | Метод установки | Команда |
| :--- | :--- | :--- |
| **macOS** | Homebrew | `brew install loft-sh/tap/vcluster` |
| **Linux** | curl (бинарный файл) | `curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64" && sudo install -c -m 0755 vcluster /usr/local/bin` |
| **Windows** | PowerShell (scoop) | `scoop bucket add loft-sh https://github.com/loft-sh/scoop-bucket && scoop install vcluster` |

#### Установка конкретной версии CLI (для воспроизводимости)

Production-окружения требуют зафиксированной версии CLI, чтобы избежать несовместимости с helm-чартом или API-серверами vCluster. Установка по тегу:

```bash
# Linux: установка конкретной версии (например, v0.34.0)
VERSION="v0.34.0"
curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/download/${VERSION}/vcluster-linux-amd64" \
  && sudo install -c -m 0755 vcluster /usr/local/bin/vcluster
vcluster version
# → vcluster version v0.34.0
```

#### Автодополнение (bash/zsh)

CLI поддерживает автодополнение для основных команд. Это сокращает ошибки в длинных флагах (`--driver`, `--kubernetes-version`).

```bash
# bash
vcluster completion bash | sudo tee /etc/bash_completion.d/vcluster > /dev/null
# zsh
vcluster completion zsh > "${fpath[1]}/_vcluster"
```

#### Проверка целостности бинарника (cosign)

Скачиваемый бинарник подписан Sigstore (cosign). На CI-агентах и в production рекомендуется верифицировать подпись, чтобы не запускать подменённый код:

```bash
# Скачать подпись и сертификат
curl -L -O "https://github.com/loft-sh/vcluster/releases/download/v0.34.0/vcluster-linux-amd64.sig"
curl -L -O "https://github.com/loft-sh/vcluster/releases/download/v0.34.0/vcluster-linux-amd64.pem"

# Проверить подпись
cosign verify-blob \
  --certificate vcluster-linux-amd64.pem \
  --signature vcluster-linux-amd64.sig \
  --certificate-identity-regexp "https://github.com/loft-sh/vcluster" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  vcluster-linux-amd64
# → Verified OK
```

### Методы развертывания виртуального кластера

| Метод | Описание | Команда / Инструмент |
| :--- | :--- | :--- |
| **Host-based (Pod)** | Запуск vCluster внутри существующего K8s. | `vcluster create my-vc` |
| **Standalone** | Прямая установка на Linux-хост. | `install-standalone.sh` |
| **Docker-based (vind)** | Запуск в локальном Docker-окружении. | `vcluster create my-vc --driver docker` |
| **Helm** | Развертывание через пакетный менеджер. | `helm install vcluster loft/vcluster` |

#### Сравнение режимов развёртывания

| Критерий | Host-based (Pod) | Standalone | Docker (vind) | Helm |
| :--- | :--- | :--- | :--- | :--- |
| **Требуется хост-кластер** | Да | Нет | Нет (Docker) | Да |
| **Изоляция Control Plane** | namespace хоста | Процесс ОС | Docker-контейнер | namespace хоста |
| **HA внутри vCluster** | Возможна (реплики etcd) | Нет (single-node) | Нет | Возможна |
| **CI-friendly** | Средне (нужен kubeconfig) | Низко (нужен Linux-хост) | Отлично (Docker in Docker) | Средне |
| **Production-ready** | Да | Только Edge/Bare-Metal | Только локальная разработка | Да |
| **Платформы** | Любой K8s | Linux (systemd) | Docker Engine | Любой K8s |
| **Удаление** | `vcluster delete` | `install-standalone.sh --cleanup` | `vcluster delete` | `helm uninstall` |
| **Лицензия** | OSS | OSS | OSS | OSS |

### Параметры создания vCluster (v0.30+)

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-n` / `--namespace` | Пространство имен (для Host-based режима). | `team-a` |
| `--kubernetes-version` | Версия Kubernetes (по умолчанию v1.36.0+). | `1.35.2` |
| `--driver` | Выбор драйвера выполнения. | `docker`, `k8s` |
| `-f` / `--config` | Путь к файлу `vcluster.yaml`. | `./config.yaml` |
| `--vcluster-name` | Имя инстанса (для Standalone режима). | `management-cluster` |

#### Полный список флагов `vcluster create` (v0.34+)

| Флаг | Назначение |
| :--- | :--- |
| `--update-current` | Сразу переключить `kubectl` на новый контекст. |
| `--background` / `-b` | Запустить connect в фоне, не блокируя терминал. |
| `--local-port` | Явный локальный порт для port-forward (по умолчанию — случайный). |
| `--context` | Хост-контекст для подключения к управляющему кластеру. |
| `--kubeconfig` | Путь к kubeconfig хоста (если нестандартный). |
| `--connect` | Сразу подключиться после создания (по умолчанию для интерактивного режима). |
| `--no-connect` | Создать без подключения (для автоматизации/CI). |
| `--extra-args` | Произвольные флаги, прокидываемые в `vcluster.yaml` (например, `--extra-args sync.fromHost.storageClasses.enabled=true`). |
| `--skip-wait` | Не ждать готовности Control Plane (полезно в CI-пайплайнах). |

## Практические сценарии

### Создание виртуального кластера (разные режимы)

```bash
# Классический режим (внутри существующего namespace хост-кластера)
vcluster create dev-vc -n team-alpha

# Режим vind (локально в Docker, без хост-кластера K8s)
vcluster create local-vc --driver docker

# Создание с использованием конфигурационного файла
vcluster create prod-vc -f vcluster.yaml
```

### Развертывание vCluster Standalone (v0.30+)

Установка напрямую на Linux-сервер (Bare Metal или VM).

```bash
# Загрузка и запуск скрипта установки
curl -sfL https://github.com/loft-sh/vcluster/releases/download/v0.36.0/install-standalone.sh | \
  sh -s -- --vcluster-name mgmt-cluster

# Проверка состояния процесса (в ОС)
systemctl status vcluster-mgmt-cluster

# Получение kubeconfig
cat /var/lib/vcluster/mgmt-cluster/kubeconfig.yaml
```

#### Полный жизненный цикл Standalone-кластера

Standalone-режим требует чуть больше ручных операций, чем Host-based, потому что нет k8s-механизмов (Rollout, ReplicaSet) для само-восстановления. Ниже — типичный набор операций.

```bash
# Создание
curl -sfL https://github.com/loft-sh/vcluster/releases/download/v0.34.0/install-standalone.sh | \
  sh -s -- --vcluster-name edge-cluster --version v0.34.0

# Просмотр состояния
systemctl status vcluster-edge-cluster
# → Active: active (running) since ...

# Чтение kubeconfig
cat /var/lib/vcluster/edge-cluster/kubeconfig.yaml

# Подключение как текущий контекст
vcluster connect edge-cluster --kubeconfig /var/lib/vcluster/edge-cluster/kubeconfig.yaml --update-current
kubectl get nodes
# → NAME           STATUS   ROLES                  VERSION
# → vcluster-node  Ready    control-plane,master   v1.31.0

# Просмотр логов (journald)
journalctl -u vcluster-edge-cluster -f

# Остановка (без удаления данных)
sudo systemctl stop vcluster-edge-cluster

# Возобновление
sudo systemctl start vcluster-edge-cluster

# Удаление с очисткой данных
curl -sfL https://github.com/loft-sh/vcluster/releases/download/v0.34.0/install-standalone.sh | \
  sh -s -- --vcluster-name edge-cluster --cleanup
```

#### Параметры `install-standalone.sh`

| Флаг | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `--vcluster-name` | Имя экземпляра (один хост = один кластер). | — |
| `--version` | Версия vCluster. | latest |
| `--data-dir` | Директория данных (etcd, kubeconfig). | `/var/lib/vcluster/<name>` |
| `--bind-address` | IP/интерфейс для API. | `0.0.0.0` |
| `--port` | Порт API. | `6443` |
| `--cleanup` | Удалить всё (используется при деинсталляции). | — |

> **Безопасность:** по умолчанию API слушает `0.0.0.0:6443`. На публичных серверах ограничьте `--bind-address` (например, `127.0.0.1` для локальной разработки или `10.0.0.5` для частного интерфейса) и настройте файрвол. TLS-сертификат включает SAN только для localhost, поэтому для внешнего доступа потребуется `--tls-san=<ваш-FQDN>` (флаг появился в v0.32+).

### Пример современной конфигурации vcluster.yaml (v0.34+)

Новый формат фокусируется на функциональности, а не только на параметрах пода.

```yaml
# vcluster.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
      image: "registry.k8s.io/kube-apiserver:v1.36.0"
  backingStore:
    etcd:
      embedded:
        enabled: true

# Настройка режима сна (Sleep Mode)
sleep:
  enabled: true
  autoSleep: 3600 # Уход в сон через 1 час бездействия
  timezone: "Europe/Moscow"

# Сетевые настройки (Gateway API)
networking:
  gatewayAPI:
    enabled: true

# Синхронизация ресурсов
sync:
  fromHost:
    storageClasses:
      enabled: true
```

#### Полный справочник `vcluster.yaml` (v0.34+)

```yaml
# vcluster.yaml
controlPlane:
  # Дистрибутив Control Plane: k3s, k8s, k0s
  distro:
    k8s:
      enabled: true
      image: "registry.k8s.io/kube-apiserver:v1.36.0"
      version: "1.36.0"
    # K3s — для лёгких dev/staging (legacy)
    k3s:
      enabled: false
      image: "ghcr.io/loft-sh/vcluster-k3s:v0.34.0"
  # Хранилище состояния
  backingStore:
    etcd:
      embedded:
        enabled: true
        size: "8Gi"                 # Размер PVC etcd
        storageClassName: "fast-ssd"
    # Внешний PostgreSQL через Kine
    database:
      enabled: false
      dataSource: "postgresql://user:pass@host:5432/vc?sslmode=require"
  # StatefulSet для Control Plane
  statefulSet:
    replicas: 1                      # 3 для production HA
    securityContext:
      runAsUser: 10000
      runAsNonRoot: true
    resources:
      requests:
        cpu: 150m
        memory: 200Mi
      limits:
        cpu: 500m
        memory: 512Mi
  # Флаги kube-apiserver
  apiserver:
    extraArgs:
      - --audit-log-maxage=30
      - --audit-log-maxbackup=10
      - --audit-log-maxsize=100

# Синхронизация
sync:
  toHost:
    pods:
      enabled: true
    services:
      enabled: true
    ingresses:
      enabled: true
  fromHost:
    storageClasses:
      enabled: true
    ingressClasses:
      enabled: true
    nodes:
      enabled: true
    priorityClasses:
      enabled: true

# Сеть
networking:
  # Внешний API через Gateway API
  gatewayAPI:
    enabled: true
    apiServer:
      enabled: true
      host: "vc.example.com"
      gatewayRef:
        name: "external-gateway"
        namespace: "infra"
  # Legacy Ingress
  ingress:
    enabled: false
    host: "vc.example.com"
  # Дополнительные SAN в сертификате API
  proxy:
    extraSANs:
      - "vc.example.com"
      - "1.2.3.4"
  # vCluster VPN (WireGuard)
  vpn:
    enabled: true
    autoConnect: true

# Режим сна
sleepMode:
  enabled: true
  autoSleepSeconds: 3600
  autoWakeup: true
  timezone: "Europe/Moscow"

# Политики безопасности
policies:
  podSecurityStandard: restricted
  networkPolicy:
    enabled: true
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "50"
  limitRange:
    enabled: true
    default:
      cpu: 500m
      memory: 512Mi

# Helm overrides (полный доступ к values чарта)
helm:
  values:
    - some-experimental-key: value
```

### Установка через Helm

Рекомендуется для интеграции с GitOps-инструментами (ArgoCD, Flux).

```bash
# Добавление репозитория
helm repo add loft https://charts.loft.sh
helm repo update

# Установка через Helm с использованием vcluster.yaml
helm install my-vcluster loft/vcluster \
  --namespace my-namespace \
  --create-namespace \
  --values vcluster.yaml
```

#### Helm-установка для ArgoCD ApplicationSet

Helm-установка — основной путь для GitOps: declarative-манифест применяется ArgoCD/Flux, кластер всегда соответствует состоянию в Git. Ниже — паттерн ApplicationSet для управления множеством vCluster.

```yaml
# argocd-applicationset.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: vcluster-tenants
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - name: team-alpha
            namespace: team-alpha
            version: "1.35.2"
          - name: team-beta
            namespace: team-beta
            version: "1.34.0"
  template:
    metadata:
      name: 'vc-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://charts.loft.sh
        chart: vcluster
        targetRevision: v0.34.0
        helm:
          releaseName: 'vc-{{name}}'
          values: |
            controlPlane:
              distro:
                k8s:
                  version: "{{version}}"
            sync:
              fromHost:
                nodes:
                  enabled: true
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{namespace}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

> **Предупреждение:** `selfHeal: true` конфликтует со Sleep Mode — ArgoCD будет будить спящий кластер чаще ожидаемого. Для спящих сред добавляйте `ignoreDifferences: ... jsonPointers: [/spec/replicas]` или отключайте selfHeal.

#### Миграция с `vcluster create` на Helm

Если изначально кластер был создан через CLI, его можно перевести под управление Helm без потери данных (PVC с etcd остаётся):

```bash
# 1. Экспортировать текущую конфигурацию в values.yaml
vcluster describe my-vc -n my-namespace --format yaml > values.yaml

# 2. Создать helm-релиз "поверх" существующего namespace
helm install vc-my-vc loft/vcluster \
  --namespace my-namespace \
  --values values.yaml

# 3. (Опционально) пометить ресурсы как managed-by Helm
kubectl -n my-namespace label statefulset vc-my-vc app.kubernetes.io/managed-by=Helm
```

### Удаление кластера

```bash
# Удаление виртуального кластера (Host-based)
vcluster delete my-vc -n my-namespace

# Удаление локального Docker-кластера (vind)
vcluster delete local-vc --driver docker

# Удаление с сохранением хранилища данных (PVC)
vcluster delete dev-vc -n team-alpha --keep-pvc
```

### Управление жизненным циклом (lifecycle)

vCluster CLI предоставляет полный набор операций для управления состоянием кластера. Это критично для CI/CD-пайплайнов и администрирования.

```bash
# Upgrade — обновление до новой версии vCluster
vcluster upgrade my-vc -n my-namespace --version v0.35.0

# Pause — остановка Syncer и Control Plane (данные сохраняются)
vcluster pause my-vc -n my-namespace
# → vCluster my-vc в namespace my-namespace успешно приостановлен

# Resume — возобновление
vcluster resume my-vc -n my-namespace
# → vCluster my-vc в namespace my-namespace успешно возобновлён

# Sleep — режим сна (только при включённом sleepMode.enabled)
vcluster sleep my-vc -n my-namespace
# → Поды масштабированы до 0; Auto-wakeup активен

# Wake — принудительное пробуждение
vcluster wake my-vc -n my-namespace
# → Control Plane восстановлен за 12s

# List — список всех vCluster в namespace
vcluster list -n my-namespace
# → NAME      NAMESPACE    STATUS    VERSION    AGE
# → my-vc     my-namespace Running   v0.34.0    14d

# Describe — детальная информация (включая состояние Syncer, Backing Store)
vcluster describe my-vc -n my-namespace
```

#### Сравнение операций lifecycle

| Операция | Что останавливается | Данные | Возобновление | Время |
| :--- | :--- | :--- | :--- | :--- |
| **Pause** | Syncer + Control Plane поды | Полностью сохранены | `vcluster resume` | ~5s |
| **Sleep** | Workload-поды (replicas=0) + idle Control Plane | Сохранены | `vcluster wake` или auto | 3-15s |
| **Delete** | Все поды, PVC (если не `--keep-pvc`) | Удаляются | Невозможно | ~10s |
| **Upgrade** | Кратковременный рестарт | Сохранены | Автоматически | 30-60s |

### CI/CD-паттерн: создание временного кластера в пайплайне

Один из самых популярных сценариев — изолированное тестирование PR в чистом кластере. Ниже — bash-сниппет, который создаёт кластер, прогоняет тесты и удаляет всё за собой.

```bash
#!/usr/bin/env bash
set -euo pipefail

VC_NAME="pr-${CI_PR_NUMBER:-local}-${CI_COMMIT_SHA::8}"
NS="ci-${CI_PR_NUMBER:-local}"

# Cleanup hook
cleanup() {
  echo ">>> Cleanup vCluster ${VC_NAME}"
  vcluster delete "${VC_NAME}" -n "${NS}" >/dev/null 2>&1 || true
  kubectl delete namespace "${NS}" --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 1. Создать namespace и vCluster
kubectl create namespace "${NS}" || true
vcluster create "${VC_NAME}" \
  -n "${NS}" \
  -f ci/vcluster.yaml \
  --no-connect \
  --skip-wait

# 2. Дождаться готовности
vcluster wait --ready "${VC_NAME}" -n "${NS}" --timeout 5m

# 3. Подключиться
vcluster connect "${VC_NAME}" -n "${NS}" --update-current

# 4. Запустить тесты
kubectl apply -f tests/manifests/
kubectl wait --for=condition=Ready pod -l app=test --timeout 3m
./tests/run.sh
```

### Установка с воздушным зазором (Air-gapped / offline)

В закрытых контурах нет доступа к `ghcr.io` и `registry.k8s.io`. Требуется предварительная загрузка образов на внутренний registry.

```bash
# 1. На машине с интернетом — скачать образы и переложить в локальный registry
IMAGES=(
  "ghcr.io/loft-sh/vcluster:v0.34.0"
  "ghcr.io/loft-sh/vcluster-syncer:v0.34.0"
  "registry.k8s.io/kube-apiserver:v1.35.2"
  "registry.k8s.io/etcd:3.5.13-0"
  "registry.k8s.io/kube-controller-manager:v1.35.2"
  "registry.k8s.io/kube-scheduler:v1.35.2"
  "docker.io/coredns/coredns:1.11.1"
)
for img in "${IMAGES[@]}"; do
  docker pull "$img"
  docker tag "$img" "registry.corp.local/k8s/${img##*/}"
  docker push "registry.corp.local/k8s/${img##*/}"
done

# 2. На целевом кластере — создать imagePullSecret
kubectl -n team-alpha create secret docker-registry corp-registry \
  --docker-server=registry.corp.local \
  --docker-username=robot \
  --docker-password="${REGISTRY_TOKEN}"

# 3. Использовать в vcluster.yaml
```

```yaml
# vcluster.yaml
controlPlane:
  statefulSet:
    imagePullSecrets:
      - name: corp-registry
    image: registry.corp.local/k8s/vcluster:v0.34.0
  distro:
    k8s:
      image: registry.corp.local/k8s/kube-apiserver:v1.35.2
```

### Требования к окружению

| Компонент | Минимум | Рекомендуется | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes Host** | v1.28 | v1.31+ | Версия хост-кластера влияет на доступные API. |
| **vCluster CLI** | v0.30 | v0.34+ | Поддержка Unified Config, Sleep Mode, Generic Sync. |
| **Helm** | v3.12 | v3.14+ | Для GitOps-установки. |
| **kubectl** | Совместим с хостом | v1.31+ | Для управления. |
| **Container Runtime** | containerd 1.7 / CRI-O 1.25 | containerd 2.0 | На worker-узлах (для workload-подов). |
| **CPU (на vCluster)** | 300m requests | 750m limits | Vanilla K8s, см. таблицу ниже. |
| **RAM (на vCluster)** | 430Mi requests | 1Gi limits | Vanilla K8s. |
| **Диск (etcd PVC)** | 2Gi | 8Gi | Зависит от числа объектов. |
| **Standalone ОС** | Linux amd64, systemd | Linux 5.15+, cgroup v2 | Для Bare-Metal/Edge. |

#### Ресурсы Control Plane по дистрибутивам

| Дистрибутив | CPU request | RAM request | CPU limit | RAM limit |
| :--- | :--- | :--- | :--- | :--- |
| **K3s** (SQLite) | 50m | 100Mi | 200m | 256Mi |
| **K3s** (embedded etcd) | 100m | 150Mi | 300m | 384Mi |
| **Vanilla K8s + etcd** | 300m | 430Mi | 750m | 1Gi |
| **K0s** | 100m | 150Mi | 300m | 384Mi |

Для планирования емкости хост-кластера на N vCluster:

```text
Host CPU headroom ≥ N × 300m + 20% (резерв на workload-пики)
Host RAM headroom ≥ N × 500Mi + 30% (резерв на Auto Nodes / HPA)
```

При N > 50 рекомендуется переходить на Auto Nodes или внешний Backing Store.

### Диагностика проблем установки

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `vcluster create` зависает на `Waiting for vcluster to come up` | ImagePullBackOff — нет доступа к registry. | `kubectl -n <ns> get pods`; `kubectl -n <ns> describe pod <syncer>`. |
| `error: failed to create statefulset: forbidden` | SA `vcluster` не имеет прав создавать RBAC. | Проверить ClusterRoleBinding в namespace. |
| `Error: incompatible Kubernetes versions` | vCluster v0.34 не поддерживает хост v1.27. | Обновить хост или понизить vCluster. |
| Standalone: `systemd unit not found` | Скрипт запущен не от root, или нет systemd. | Запускать через `sudo`; проверить `/run/systemd/system`. |
| PVC `Pending` после создания | StorageClass по умолчанию не настроен на хосте. | Указать `controlPlane.statefulSet.volumeClaimTemplates.spec.storageClassName`. |
| Helm: `Error: rendered manifests contain a resource that already exists` | vCluster уже создан через CLI ранее. | Сначала `vcluster delete`, потом `helm install` (или наоборот). |
| `vcluster connect` сразу после create падает | Control Plane ещё не Ready. | Добавить `vcluster wait --ready` перед connect. |
| `x509: certificate signed by unknown authority` | vCluster API перевыпустил CA после upgrade. | `kubectl -n <ns> delete pod -l app=vcluster` (форсирует рестарт). |

### Best Practices установки

- **Версионирование CLI:** зафиксируйте версию CLI в `Dockerfile` (для CI) или в Ansible/Puppet. v0.34 → v0.35 иногда требует ручной миграции `vcluster.yaml`.
- **Версионирование чарта:** используйте `targetRevision: v0.34.0` в ArgoCD, а не `latest`. Иначе ночное обновление chart может сломать прод.
- **Лимиты по умолчанию:** всегда задавайте `LimitRange` в namespace хоста и `policies.limitRange` в `vcluster.yaml`, чтобы один тенант не исчерпал ресурсы.
- **Именование:** префиксы тенантов (`team-alpha-prod`, `team-alpha-staging`) — упрощает фильтрацию в observability.
- **Air-gapped registry:** в закрытых контурах используйте отдельный проект/репозиторий `k8s/` для образов vCluster; настройте retention-policy 90 дней.
- **Cleanup-проверка:** после `vcluster delete` убедитесь, что namespace и PVC удалены. Иногда PVC остаются из-за finalizer'ов — `kubectl get pvc -A | grep vcluster`.
- **Резервное копирование Backing Store:** для Vanilla K8s — etcd snapshots (`etcdctl snapshot save` в поде); для PostgreSQL — `pg_dump` по расписанию.
- **Тестовые среды через Sleep Mode:** для dev-окружений разработчиков включайте `sleepMode.autoWakeup: true` с `autoSleepSeconds: 3600` — экономия CPU/RAM ~70%.

### Очистка

```bash
# Удаление vCluster (полная очистка namespace и PVC)
vcluster delete my-vc -n my-namespace

# Удаление без PVC (для последующего восстановления)
vcluster delete dev-vc -n team-alpha --keep-pvc

# Остановка всех workload-подов без удаления кластера (мягкая остановка)
vcluster pause my-vc -n my-namespace

# Возобновление
vcluster resume my-vc -n my-namespace

# Принудительное удаление (если namespace застрял)
kubectl delete namespace my-namespace --force --grace-period=0
```

> Все операции идемпотентны: повторный `delete` не приводит к ошибкам, повторный `create` поверх существующего namespace вернёт осмысленную ошибку `already exists`.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)

### См. также

- [Установка через Helm](../../ToolsUtilities/Helm/helm_overview.md)
- [kind — практические сценарии](../../Installation/kind/kind_practical_scenarios.md)
- [Helm — команды и workflow](../../ToolsUtilities/Helm/helm_commands_and_workflow.md)

### Внешние ссылки

- [vCluster Installation Guide (Official)](https://www.vcluster.com/docs/getting-started/installation)
- [vCluster CLI Releases on GitHub](https://github.com/loft-sh/vcluster/releases)
- [Standalone Mode Documentation](https://www.vcluster.com/docs/features/standalone)
- [vCluster Helm Chart](https://github.com/loft-sh/vcluster/tree/main/charts/vcluster)
