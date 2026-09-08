# Подготовка окружения для развертывания LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)** (текущий)
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Назначение документа

Документ описывает подготовку локального окружения инженера DevOps/SRE для развертывания полного стека наблюдаемости **LGTM** (Loki, Grafana, Tempo, Mimir/Prometheus) и слоя инструментации **OpenTelemetry** в одноузловом кластере Minikube. Описанные шаги являются первым этапом практического руководства и обязательны перед переходом к развертыванию.

Результатом выполнения является полностью сконфигурированное окружение, в котором:
- установлены и доступны в `PATH` базовые CLI-инструменты (`docker`, `kubectl`, `helm`, `git`, `minikube`);
- запущен локальный кластер Kubernetes с предсказуемыми параметрами ресурсов;
- добавлены Helm-репозитории для всех чартов, используемых в последующих сценариях;
- настроены дополнительные утилиты (`jq`, `yq`, `stern`, `k9s`), ускоряющие работу в следующих файлах руководства;
- активированы критичные для стека аддоны Minikube (Ingress, metrics-server, local storage).

Документ намеренно фокусируется на практической стороне и не дублирует теорию, которая подробно раскрыта в профильных файлах (см. раздел «Связанные темы»).

---

## Предварительные требования

К началу работы должны быть выполнены следующие условия:

| Категория | Требование | Назначение |
| :--- | :--- | :--- |
| **Операционная система** | macOS 13+ (Intel/Apple Silicon), Ubuntu 22.04+ / Debian 12+, Windows 11 + WSL2 | Поддерживается актуальными версиями Docker Engine и Minikube |
| **Docker Engine** | 24.0+ (с поддержкой cgroups v2 и `overlay2`) | Требуется драйвером `docker` для Minikube |
| **Аппаратные ресурсы** | 4 CPU / 8 ГБ RAM / 40 ГБ диска (минимум); 6 CPU / 12 ГБ RAM / 60 ГБ диска (рекомендуется) | Полный стек LGTM + OTel |
| **Виртуализация** | Вложенная виртуализация не требуется (драйвер `docker`) | Драйвер запускает узел в контейнере |
| **Сеть** | Доступ в Интернет к `github.com`, `ghcr.io`, `docker.io`, `gcr.io`, `quay.io`, `objects.githubusercontent.com` | Загрузка образов и Helm-чартов |
| **Свободные порты на хосте** | `8443` (API-server Minikube), `80`/`443` (Ingress), `5000` (insecure registry), `30000-32767` (NodePort) | Сервисы кластера и доступ к ним |
| **Права** | Возможность создавать Docker-контейнеры (в Linux — членство в группе `docker` или доступ к `/var/run/docker.sock`) | Minikube запускает узел как контейнер |

> **Важно:** На Linux требуется ядро ≥ 5.4 с поддержкой **cgroup v2** и `overlay2`. На устаревших дистрибутивах (CentOS 7, Ubuntu 18.04) Minikube v1.34+ не запустится. Используйте только поддерживаемые ОС.

---

## Определения

**Docker** — платформа для разработки, доставки и запуска приложений в контейнерах. Используется как среда выполнения (runtime) для Minikube (драйвер `docker` запускает узел Kubernetes внутри Docker-контейнера, а не в полноценной VM). Подробнее: **[Docker: Обзор](../../../Docker/docker_overview.md)**.

**Container runtime (среда выполнения контейнеров)** — программа, непосредственно исполняющая контейнеры на узле. В Minikube по умолчанию используется `containerd` (с версии 1.30+); `cri-dockerd` остаётся опциональным для совместимости. Подробнее: **[Minikube: Концепции](../../Installation/minikube/minikube_concepts.md)**.

**Git** — распределенная система управления версиями. Необходима для клонирования демонстрационных репозиториев и конфигураций. Подробнее: **[Git: Основы](../../../Git/git_basics.md)**.

**Minikube** — инструмент для запуска локального кластера Kubernetes на персональном компьютере. В контексте данного руководства Minikube запускается через драйвер `docker`, который создаёт одноузловой кластер в изолированном контейнере. Подробнее: **[Minikube: Концепции](../../Installation/minikube/minikube_concepts.md)**.

**kubectl** — утилита командной строки для управления кластерами Kubernetes. Подробнее: **[Kubernetes: Обзор](../../kubernetes_overview.md)**.

**Helm** — пакетный менеджер для Kubernetes, упрощающий развертывание и управление приложениями. Используется для установки всех компонентов стека LGTM, OTel Operator, cert-manager и локального реестра. Подробнее: **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)**.

**kubeconfig** — файл конфигурации, содержащий параметры подключения к кластерам Kubernetes. Minikube автоматически создаёт контекст `minikube` в `~/.kube/config`. Подробнее: **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.

**Helm-чарт (Chart)** — пакет Helm, содержащий шаблоны манифестов Kubernetes, values-файл с параметрами по умолчанию и метаданные. Чарт может размещаться в классическом репозитории (с `index.yaml`) или в OCI-реестре как образ.

**OCI-репозиторий (Open Container Initiative)** — хранилище артефактов, совместимое со спецификацией OCI Distribution (тот же протокол, что используется для Docker-образов). С 2025–2026 года всё больше чартов (Loki, Tempo, Grafana) публикуются в OCI-формате, что обеспечивает атомарность публикации, подпись артефактов и использование единых механизмов аутентификации.

**Ingress** — ресурс Kubernetes, описывающий маршрутизацию внешнего HTTP(S)-трафика к сервисам внутри кластера. Требует Ingress-контроллера (Nginx, Traefik, HAProxy). В Minikube используется встроенный Nginx.

**metrics-server** — аддон, агрегирующий метрики использования ресурсов с подов и узлов. Без него не работают `kubectl top`, Horizontal Pod Autoscaler (HPA) и ряд возможностей Prometheus Adapter.

**Persistent Volume (PV) и Persistent Volume Claim (PVC)** — абстракции Kubernetes для долговременного хранения данных, переживающего перезапуск пода. В Minikube используется `standard` StorageClass с провижионером `k8s.io/minikube-hostpath`.

**Cgroup v2 (Control Group version 2)** — иерархическая подсистема ядра Linux для ограничения и учета ресурсов (CPU, память, I/O). Minikube ≥ v1.30 и Kubernetes ≥ 1.27 по умолчанию рассчитывают ресурсы через cgroup v2. На хосте с cgroup v1 возможны проблемы с `system.slice` и корректным определением лимитов.

**OverlayFS (overlay2)** — файловая система ядра Linux, используемая Docker как storage driver по умолчанию. Требует ядро ≥ 4.0. Альтернативы (`devicemapper`, `btrfs`) устарели для Minikube.

---

## Основные концепции

### Архитектура рабочего окружения

Окружение инженера состоит из двух слоев: **хост-система** (рабочая станция с установленными CLI-инструментами) и **узел Minikube** (контейнер с плоскостью управления Kubernetes и узел для запуска подов).

```text
┌──────────────────────────────────────────────────────────────────────┐
│                      Хост-система (рабочая станция)                  │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │  Docker  │  │   Git    │  │  Helm 3  │  │  kubectl + jq/yq     │   │
│  │  Engine  │  │  (clone) │  │ (install)│  │  + stern/k9s (опц.)  │   │
│  └─────┬────┘  └──────────┘  └─────┬────┘  └──────────┬───────────┘   │
│        │                           │                   │               │
│        │ docker.sock / buildx      │ helm install       │ API :8443      │
│        ▼                           ▼                   ▼               │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    Minikube (контейнер/VM)                     │  │
│  │  ┌─────────────────────────┐   ┌────────────────────────────┐  │  │
│  │  │   Control Plane (k8s)   │   │   Узлы (workload)         │  │  │
│  │  │  - kube-apiserver :8443 │   │   - kube-proxy             │  │  │
│  │  │  - etcd                 │   │   - containerd             │  │  │
│  │  │  - kube-scheduler       │   │   - CNI (bridge/cilium)    │  │  │
│  │  │  - kube-controller-mgr  │   │   - kubelet                │  │  │
│  │  │  - CoreDNS              │   │   - CRI (containerd)       │  │  │
│  │  └─────────────────────────┘   └────────────────────────────┘  │  │
│  │                                                                │  │
│  │  Аддоны: ingress-nginx, metrics-server, local-path-storage    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Связи и потоки:**
1. CLI-инструменты (`kubectl`, `helm`) на хосте обращаются к API-server Minikube через `~/.kube/config` (контекст `minikube`) по адресу `https://<minikube-ip>:8443`.
2. Драйвер `docker` запускает Minikube как контейнер `minikube` и монтирует Docker-сокет хоста внутрь, чтобы kubelet внутри Minikube мог запускать вложенные контейнеры (nested containers).
3. Образы подов (Loki, Tempo, Grafana, OTel Collector) скачиваются из registry через стандартный Docker-стек внутри Minikube.

### Требования к ресурсам

Для стабильной работы стека LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) и OpenTelemetry требуются значительные ресурсы. Недостаток памяти часто приводит к аварийному завершению подов (**OOMKill**).

| Компонент | Минимальные | Рекомендуемые |
| :--- | :--- | :--- |
| **CPU** | 4 ядра | 6 ядер |
| **Память (RAM)** | 8 ГБ | 12 ГБ |
| **Дисковое пространство** | 40 ГБ | 60 ГБ |

**Рекомендуемые параметры запуска Minikube:** `--cpus 4 --memory 12288mb` (12 ГБ). Если планируется использование Mimir вместо Prometheus, память следует увеличить до 16 ГБ.

**Расчёт бюджета памяти** (для рекомендуемой конфигурации 12 ГБ):
- **Хост-система и Docker Engine:** ~1.5 ГБ
- **Control plane Minikube** (kubelet, kube-apiserver, etcd, CoreDNS): ~1 ГБ
- **Ingress-nginx + metrics-server:** ~0.5 ГБ
- **cert-manager:** ~0.5 ГБ
- **Loki** (single-binary, 1 реплика): ~1 ГБ
- **Tempo** (1 реплика): ~0.5 ГБ
- **Prometheus** (или Mimir — 2 ГБ) + Grafana: ~2–3 ГБ
- **OpenTelemetry Operator + Collector:** ~0.5 ГБ
- **Тестовое приложение (OTel-demo) и headroom:** ~1 ГБ

> **Важно:** Сумма лимитов подов в Minikube должна быть **меньше** параметра `--memory`, иначе поды будут получать `OOMKilled` под нагрузкой. Minikube резервирует ~25% памяти под control plane и поды самого кластера.

**Расчёт бюджета CPU:** 4 ядра в режиме `docker` означают, что Minikube получит доступ к 4 vCPU хоста. Control plane и системные поды Minikube потребляют ~0.5 vCPU. Остальное распределяется между пользовательскими нагрузками. На 6 vCPU помещается полный стек LGTM + OTel + тестовое приложение с запасом для всплесков.

**Расчёт дискового пространства:** Каждый под системы Minikube (включая kube-apiserver, etcd, coredns, ingress-контроллер) и образы стека занимают ~10–15 ГБ. С добавлением тестового приложения, темплейтов Grafana и кэша Helm — 50–60 ГБ достаточно для полного цикла работы без ручной очистки.

### Используемые Helm-репозитории (состояние на 2026 г.)

С 2026 года многие чарты перешли на использование **OCI-репозиториев** для повышения безопасности и производительности.

| Репозиторий | URL / Идентификатор OCI | Назначение | Тип |
| :--- | :--- | :--- | :--- |
| **prometheus-community** | `https://prometheus-community.github.io/helm-charts` | kube-prometheus-stack | HTTP |
| **grafana-community (OCI)** | `oci://ghcr.io/grafana-community/helm-charts` | Loki, Tempo (OSS версии) | OCI |
| **grafana** | `https://grafana.github.io/helm-charts` | Grafana, Mimir, Alloy | HTTP |
| **jetstack** | `https://charts.jetstack.io` | cert-manager | HTTP |
| **twuni** | `https://twuni.github.io/docker-registry.helm` | Docker Registry (локальный) | HTTP |
| **open-telemetry** | `https://open-telemetry.github.io/opentelemetry-helm-charts` | OTel Operator | HTTP |

**Особенности работы с OCI-репозиториями:**

OCI-чарты Helm не требуют `helm repo add` — они подтягиваются по URL напрямую. Пример:

```bash
# Классический репозиторий — сначала add, потом install
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kube-prometheus prometheus-community/kube-prometheus-stack

# OCI-репозиторий — install сразу, без add
helm install loki oci://ghcr.io/grafana-community/helm-charts/loki \
  --version 6.0.0 \
  --namespace loki --create-namespace
```

> **Преимущества OCI:** атомарные публикации, поддержка подписи артефактов (cosign), единая аутентификация через `helm registry login ghcr.io`. **Недостаток:** нельзя посмотреть `helm search repo loki` — используйте `helm show` или `helm pull --untar`.

---

## Практические сценарии

> **Замечание по структуре:** Шаги внутри сценариев рассчитаны на последовательное выполнение в рамках одного сеанса терминала. Переменные окружения (`KUBECONFIG`, `MINIKUBE_HOME`, `HELM_NAMESPACE`) и алиасы переиспользуются между шагами.

### Сценарий 1: Проверка и установка базовых инструментов

**Цель:** Убедиться, что на хост-системе установлены все CLI-инструменты, необходимые для последующих сценариев. Установить недостающие.

#### Шаг 1.1: Проверка наличия инструментов и их версий

```bash
docker --version
# → Expected: Docker version 24.0.x (или выше)

minikube version
# → Expected: minikube version: v1.34.x (или выше)

kubectl version --client
# → Expected: Client Version: v1.30.x или выше

helm version --short
# → Expected: v3.15.x (SemVer: 3.15.x) или выше

git --version
# → Expected: git version 2.39.x или выше

curl --version | head -1
# → Expected: curl 8.x

jq --version
# → Expected: jq-1.7 (опционально, но крайне полезно для парсинга JSON-манифестов)
```

> **Важно:** Minikube ≥ v1.34 поддерживает Kubernetes 1.30+ (рекомендуется). Использование устаревших версий Minikube (< 1.30) приведёт к невозможности установить современные Helm-чарты (cert-manager ≥ 1.15, Loki ≥ 6.0).

#### Шаг 1.2: Установка недостающих инструментов

**macOS (через Homebrew):**

```bash
# Установка базового набора
brew install docker docker-compose minikube kubernetes-cli helm git jq yq

# Опционально: удобные утилиты для работы с кластером
brew install k9s stern kube-ps1

# yq ≥ 4.x (для YAML-манифестов Kubernetes)
brew install yq
yq --version
# → Expected: yq (https://github.com/mikefarah/yq/) version 4.x.x
```

**Ubuntu / Debian:**

```bash
# Установка базового набора
sudo apt-get update
sudo apt-get install -y docker.io git curl wget jq

# kubectl (последняя стабильная)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -m 0755 kubectl /usr/local/bin/kubectl

# Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# yq
sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
sudo chmod a+x /usr/local/bin/yq
```

**Windows (PowerShell с WSL2):**

```powershell
# Внутри WSL2-дистрибутива (Ubuntu) — команды идентичны разделу Ubuntu/Debian.
# На хост-Windows: установите Docker Desktop с включённой интеграцией WSL2.
```

#### Шаг 1.3: Проверка Docker Engine и прав доступа

```bash
# Проверка работоспособности Docker daemon
docker info >/dev/null 2>&1 && echo "Docker OK" || echo "Docker не запущен или недоступен"
# → Expected: Docker OK

# Версия Docker Engine (необходимо ≥ 20.10)
docker version --format '{{.Server.Version}}'
# → Expected: 24.0.x или выше

# Storage driver (должен быть overlay2)
docker info --format '{{.Driver}}'
# → Expected: overlay2

# На Linux: проверка членства в группе docker (иначе потребуется sudo)
groups | grep -q docker && echo "OK: пользователь в группе docker" || echo "WARN: пользователь не в группе docker"
```

> **На Linux** без членства в группе `docker` Minikube потребует `sudo` или ручного монтирования сокета. Рекомендуется добавить пользователя в группу и перелогиниться:
>
> ```bash
> sudo usermod -aG docker $USER
> newgrp docker
> ```

### Сценарий 2: Клонирование демонстрационных репозиториев

**Цель:** Подготовить локальные копии репозиториев с примерами инструментации и конфигурациями, которые используются в сценариях тестирования.

```bash
# Создание рабочей директории
mkdir -p ~/work/observability && cd ~/work/observability

# Примеры использования OpenTelemetry (Java, Python, Node.js, .NET, Go)
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git

# Демонстрационное приложение OTel-demo (microservices с полной инструментацией)
git clone https://github.com/open-telemetry/opentelemetry-demo.git

# Практические примеры по наблюдаемости
git clone https://github.com/memori-dev/observability-practice.git

# Дополнительно: набор манифестов и dashboards от сообщества Grafana
git clone https://github.com/grafana/tempo.git
```

> **Примечание:** Репозиторий `opentelemetry-demo` содержит Helm-чарт `kubernetes-helm`, который разворачивает полноценный микросервисный стек (frontend, checkout, payment, recommendation, account, fraud-detection, shipping, currency, ad, cart, product-catalog, email) с уже подключенной инструментацией. Используется на этапе тестирования (см. файл `lgtm_otel_minikube_test_app_verification.md`).

### Сценарий 3: Настройка Helm-репозиториев

**Цель:** Добавить все репозитории, из которых будут устанавливаться чарты стека LGTM и OTel Operator. OCI-репозитории не требуют `helm repo add` — они подключаются по URL.

```bash
# Классические репозитории (HTTP + index.yaml)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://twuni.github.io/docker-registry.helm
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

# Синхронизация индексов
helm repo update

# Проверка добавленных репозиториев
helm repo list
# → Expected: список из 5 репозиториев с их URL

# Проверка доступности OCI-репозитория grafana-community (без add)
helm show chart oci://ghcr.io/grafana-community/helm-charts/loki --version 6.0.0 >/dev/null \
  && echo "OCI-репозиторий Loki доступен" \
  || echo "OCI-репозиторий Loki недоступен"
```

> **Важно:** Если прокси-сервер организации перехватывает HTTPS, `helm repo update` может завершиться с ошибкой `x509: certificate signed by unknown authority`. В таком случае задайте переменную окружения `HELM_SECURE_BUNDLE_FILE=/path/to/ca-bundle.crt` или используйте `--debug --tls-server-name` для диагностики. **Облачные registry не используются**, но корпоративный proxy/mirror может потребовать отдельной настройки.

### Сценарий 4: Запуск кластера Minikube

**Цель:** Развернуть одноузловой кластер Kubernetes с параметрами, достаточными для всего стека LGTM + OTel.

```bash
# Создание выделенного профиля, чтобы не пересекаться с другими Minikube-кластерами
minikube profile add lgtm
minikube profile lgtm

minikube start \
  --profile=lgtm \
  --cpus=4 \
  --memory=12288mb \
  --disk-size=50g \
  --addons=ingress,metrics-server,default-storageclass \
  --insecure-registry="10.0.0.0/24" \
  --driver=docker \
  --kubernetes-version=stable
```

**Разбор параметров:**

| Параметр | Значение | Назначение |
| :--- | :--- | :--- |
| `--profile=lgtm` | `lgtm` | Именованный профиль; позволяет иметь несколько кластеров |
| `--cpus=4` | 4 vCPU | Минимум для полного стека |
| `--memory=12288mb` | 12 ГБ | Обеспечивает headroom для OOMKills |
| `--disk-size=50g` | 50 ГБ | Хранилище для образов и PVC |
| `--addons=ingress,metrics-server,default-storageclass` | Аддоны | Ingress-контроллер, сбор метрик, динамический StorageClass |
| `--insecure-registry="10.0.0.0/24"` | CIDR | Диапазон Docker-драйвера, в котором registry доступен без TLS |
| `--driver=docker` | Docker | Рекомендуемый драйвер; запускает узел в контейнере |
| `--kubernetes-version=stable` | `stable` | Актуальный стабильный K8s (см. вывод `minikube start`) |

> **Важно:** Использование драйвера `docker` является рекомендуемым. При использовании других драйверов (например, `virtualbox`, `kvm2`, `qemu2`, `hyperv`) может потребоваться дополнительная настройка сети для доступа к `insecure-registry`. На Windows драйвер `hyperv` требует включённой роли Hyper-V и не работает в WSL2; в WSL2 всегда используется `docker`.

> **Про `--insecure-registry="10.0.0.0/24"`:** Docker-драйвер Minikube выделяет контейнеру сеть в этом диапазоне. Указание CIDR разрешает пушить образы в локальный registry (`twuni/docker-registry`) без TLS — требуется для `lgtm_otel_minikube_auxiliary_components.md`.

### Сценарий 5: Проверка готовности кластера

**Цель:** Подтвердить, что кластер работает, API-server отвечает, kubelet готов, аддоны активны.

```bash
# Общее состояние Minikube
minikube status --profile=lgtm
# → Expected:
#   minikube
#   type: Control Plane
#   host: Running
#   kubelet: Running
#   apiserver: Running
#   kubeconfig: Configured

# Узлы
kubectl get nodes -o wide
# → Expected: 1 узел со статусом Ready, роль control-plane, версия v1.30+

# Проверка API-server (dns и endpoint)
kubectl cluster-info
# → Expected: Kubernetes control plane is running at https://192.168.x.x:8443
#            CoreDNS is running at https://...

# Полный список аддонов
minikube addons list --profile=lgtm
# → Expected: ingress, metrics-server, default-storageclass в статусе enabled

# Проверка StorageClass (для PVC, которые потребуются Loki/Prometheus/Tempo)
kubectl get storageclass
# → Expected: standard (default) с провижионером k8s.io/minikube-hostpath

# Проверка, что Ingress-контроллер поднял под
kubectl -n ingress-nginx get pods
# → Expected: ingress-nginx-controller-* в статусе Running (1/1)

# Проверка, что metrics-server работает
kubectl top nodes
# → Expected: таблица с CPU и Memory для узла minikube

# Проверка IP Minikube (потребуется для /etc/hosts при работе с Ingress)
minikube ip --profile=lgtm
# → Expected: 192.168.x.x (запомнить для добавления DNS-записей)
```

> **Если `kubectl top nodes` не работает** с ошибкой `Metrics API not available`, подождите 30–60 секунд после старта — metrics-server собирает данные с задержкой. Проверить состояние: `kubectl -n kube-system get pods -l k8s-app=metrics-server`.

---

## Дополнительная информация

### Хост-система: подготовка на уровне ОС (Linux)

Для корректной работы Minikube на Linux требуется предварительная настройка ядра и системных подсистем. Эти шаги выполняются **один раз** на хост-машине и не зависят от Minikube.

#### Проверка cgroup v2

Minikube ≥ v1.30 и Kubernetes ≥ 1.27 по умолчанию работают в режиме unified cgroup hierarchy (cgroup v2). На старых дистрибутивах возможен fallback на cgroup v1, что приводит к ошибкам при старте kubelet.

```bash
# Проверка: точка монтирования должна указывать на /sys/fs/cgroup
stat -fc %T /sys/fs/cgroup/
# → Expected: cgroup2fs (хорошо)
#             tmpfs (значит cgroup v1, требуется обновление ОС)
```

Если cgroup v1, обновите дистрибутив до **Ubuntu 22.04+**, **Debian 12+**, **RHEL 9+** или активируйте unified cgroup hierarchy вручную (`GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"`).

#### Проверка отключённого swap

kubelet по умолчанию отказывается работать при активном swap. Minikube с драйвером `docker` **не требует** swap, но если он активен в системе, Docker-контейнер Minikube может не стартовать.

```bash
swapon --show
# → Expected: пустой вывод (swap отключён) ИЛИ только zram, который допустим
```

Для отключения файла подкачки (если требуется):

```bash
sudo swapoff -a
sudo sed -i '/\bswap\b/d' /etc/fstab
```

#### Проверка поддержки overlay2

```bash
grep -E "overlay" /proc/filesystems
# → Expected: nodev overlay (поддержка включена)
```

Если `overlay` отсутствует, загрузите модуль вручную: `sudo modprobe overlay` и добавьте его в `/etc/modules-load.d/`.

#### Требуемые порты

Minikube и зависимые сервисы используют следующие порты. Убедитесь, что они не заняты и не блокируются фаерволом (`ufw`, `firewalld`, `iptables`):

| Порт | Сервис | Назначение |
| :--- | :--- | :--- |
| 8443 | kube-apiserver | API Kubernetes |
| 10250 | kubelet | Управление узлом |
| 80, 443 | ingress-nginx | HTTP(S) Ingress |
| 5000 | docker-registry | Локальный реестр (insecure) |
| 30000–32767 | NodePort | Доступ к сервисам вне кластера |
| 53 (UDP) | CoreDNS | Разрешение имён внутри кластера |

```bash
# Проверка занятости порта
sudo ss -tlnp | grep ':8443 ' || echo "Порт 8443 свободен"
```

### macOS: подготовка Docker Desktop

На macOS Minikube через драйвер `docker` использует Docker Desktop. Убедитесь, что:

1. **Docker Desktop запущен** и в трее иконка показывает «Docker Desktop is running».
2. **Выделено достаточно ресурсов:** Docker Desktop → Settings → Resources → Advanced:
   - CPUs: 4
   - Memory: 10 ГБ
   - Swap: 2 ГБ
   - Disk image size: 60 ГБ
3. **Включён VirtioFS** (Settings → Experimental → Use VirtioFS) — ускоряет I/O в 2–3 раза на Apple Silicon.
4. **Проброс DNS** в порядке: `minikube ssh -- nslookup kubernetes.default` должен вернуть IP из `10.96.0.0/12`.

### Конфигурация kubectl и kubeconfig

После `minikube start` контекст `lgtm` автоматически добавляется в `~/.kube/config`. Для удобства работы:

```bash
# Просмотр текущего контекста
kubectl config current-context
# → Expected: lgtm

# Быстрое переключение
kubectl config use-context lgtm

# Установка контекста по умолчанию через переменную окружения (без изменений kubeconfig)
export KUBECONFIG=~/.kube/config

# Автодополнение (bash)
source <(kubectl completion bash)
alias k=kubectl
complete -F __start_kubectl k

# Проверка: tab-tab после `k get po` должен предлагать namespaces
```

Подробнее об управлении несколькими контекстами: **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.

### Pre-flight проверка перед развертыванием стека

Перед переходом к следующему файлу (`lgtm_otel_minikube_auxiliary_components.md`) рекомендуется прогнать сводную проверку:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Pre-flight check ==="

# 1. Утилиты
for tool in docker minikube kubectl helm git; do
  command -v "$tool" >/dev/null 2>&1 \
    && echo "OK    $tool: $(command -v $tool)" \
    || { echo "FAIL  $tool не найден"; exit 1; }
done

# 2. Docker
docker info >/dev/null 2>&1 \
  && echo "OK    Docker daemon работает" \
  || { echo "FAIL  Docker daemon недоступен"; exit 1; }

# 3. Minikube
minikube status --profile=lgtm >/dev/null 2>&1 \
  && echo "OK    Minikube запущен" \
  || { echo "FAIL  Minikube не запущен"; exit 1; }

# 4. kubectl
kubectl get nodes --no-headers | grep -q " Ready " \
  && echo "OK    Узел Kubernetes в статусе Ready" \
  || { echo "FAIL  Нет Ready-узлов"; exit 1; }

# 5. Аддоны
for addon in ingress metrics-server default-storageclass; do
  status=$(minikube addons list --profile=lgtm 2>/dev/null | awk -v a="$addon" '$1==a {print $3}')
  [ "$status" = "enabled" ] \
    && echo "OK    addon: $addon enabled" \
    || echo "WARN  addon: $addon не enabled (может потребоваться для следующих сценариев)"
done

# 6. Helm-репозитории
helm repo list | grep -q "prometheus-community" \
  && echo "OK    Helm-репозиторий prometheus-community добавлен" \
  || echo "WARN  Helm-репозиторий prometheus-community не добавлен"

# 7. StorageClass
kubectl get storageclass standard >/dev/null 2>&1 \
  && echo "OK    StorageClass 'standard' доступен" \
  || echo "WARN  StorageClass 'standard' не найден (потребуется для PVC Loki/Prometheus)"

# 8. Свободное место на хосте
free_disk=$(df -BG "$HOME" | awk 'NR==2 {print $4}' | tr -d 'G')
[ "$free_disk" -ge 20 ] \
  && echo "OK    Свободно на диске хоста: ${free_disk}G" \
  || echo "WARN  Менее 20G свободно (рекомендуется ≥ 30G)"

echo "=== Pre-flight завершён ==="
```

### Типичные проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ошибка при запуске Minikube: `insufficient memory`** | Хост-система не имеет свободной RAM | Закройте ресурсоемкие приложения. Минимальный порог для LGTM — 8 ГБ. На macOS уменьшите лимиты Docker Desktop. |
| **Docker daemon не найден / `Cannot connect to Docker daemon`** | Docker не запущен или пользователь без прав | Запустите Docker Desktop или `sudo systemctl start docker`. На Linux: `sudo usermod -aG docker $USER && newgrp docker`. |
| **`ImagePullBackOff` при обращении к локальному registry** | Ошибка `insecure-registry` | Убедитесь, что параметр `--insecure-registry="10.0.0.0/24"` указан при `minikube start`. Перезапустите кластер. |
| **`kubectl: connection refused`** | Кластер не запущен или упал | Выполните `minikube status --profile=lgtm`. Если упал из-за ресурсов — увеличьте лимиты и перезапустите. |
| **`swap on` блокирует запуск kubelet** | Активный файл подкачки | `sudo swapoff -a` и `sudo sed -i '/\bswap\b/d' /etc/fstab`. Перезапустить хост или контейнер Minikube. |
| **`cgroup v1 detected` / kubelet падает с `failed to set cgroup`** | Устаревшее ядро или ОС | Обновитесь до Ubuntu 22.04+ / Debian 12+. Проверьте `stat -fc %T /sys/fs/cgroup/`. |
| **`minikube start` зависает на `Pulling base image`** | Медленный/заблокированный доступ к `registry.k8s.io` | Настройте прокси-зеркало для Docker (`/etc/docker/daemon.json` → `"registry-mirrors": [...]`). |
| **Helm: `Error: failed to download chart`** | Репозиторий не добавлен или устарел | `helm repo add <name> <url>` (если HTTP) или проверьте URL OCI. `helm repo update`. |
| **`kubectl top nodes` возвращает `Metrics API not available`** | metrics-server не успел собрать метрики | Подождите 30–60 секунд. Проверьте: `kubectl -n kube-system logs -l k8s-app=metrics-server`. |
| **`The connection to the server localhost:8080 was refused`** | `KUBECONFIG` указывает на несуществующий файл | `unset KUBECONFIG`. Minikube автоматически использует `~/.kube/config`. |
| **DNS внутри подов не резолвит внешние домены** | CoreDNS не запущен или некорректная upstream-конфигурация | `kubectl -n kube-system rollout restart deployment/coredns`. Проверить ConfigMap: `kubectl -n kube-system get configmap coredns -o yaml`. |
| **Ingress-контроллер не стартует: `hostPort 80/443 already in use`** | На хосте занят 80/443 (apache, nginx) | Остановите локальный web-сервер или измените тип Minikube-аддона на `ingress-dns`. |
| **Minikube кластер работает, но `kubectl` ругается на x509** | kubeconfig повреждён или указывает на старый сертификат | `minikube delete --profile=lgtm && minikube start ...` (пересоздаст сертификаты). |
| **Apple Silicon: образы `linux/amd64` тянутся через эмуляцию** | Multi-arch образы не имеют `arm64` слоя | Используйте `--driver=docker` с нативной архитектурой или указывайте `--platform=linux/arm64` в Docker. |

### Диагностика

```bash
# Сводный статус компонентов
minikube status --profile=lgtm
kubectl get nodes
kubectl get pods -A

# Логи control plane Minikube (если кластер не стартует)
minikube logs --profile=lgtm

# Логи kubelet
minikube ssh --profile=lgtm -- sudo journalctl -u kubelet --no-pager | tail -50

# Логи конкретного системного пода
kubectl -n kube-system logs <pod-name> --previous
kubectl -n kube-system describe pod <pod-name>

# Состояние Docker-контейнеров (для драйвера docker)
docker ps -a | grep minikube

# Использование ресурсов на уровне Minikube
minikube ssh --profile=lgtm -- top -bn1 | head -20
minikube ssh --profile=lgtm -- free -h
minikube ssh --profile=lgtm -- df -h /var/lib

# Сетевая диагностика изнутри Minikube
minikube ssh --profile=lgtm -- ip addr show
minikube ssh --profile=lgtm -- ip route

# Проверка доступности registry
minikube ssh --profile=lgtm -- curl -sv http://10.0.0.1:5000/v2/_catalog 2>&1 | head -20
```

### Очистка окружения

Если кластер больше не нужен, освободите ресурсы хоста:

```bash
# Остановка кластера (сохраняет данные, освобождает CPU/RAM)
minikube stop --profile=lgtm
# → Expected: Stopping node "lgtm" ...
#            Powering off "lgtm" via SSH ...

# Полное удаление кластера (уничтожает все данные)
minikube delete --profile=lgtm
# → Expected: Removed all traces of the "lgtm" cluster.

# Удаление профиля
minikube profile delete lgtm

# Удаление контекста из kubeconfig
kubectl config delete-context lgtm
kubectl config delete-cluster lgtm

# Очистка Docker-ресурсов (опционально)
docker system prune -af
docker volume prune -f

# Очистка Helm-релизов и кэша
helm list --all-namespaces
helm uninstall <release> -n <namespace>
rm -rf ~/.cache/helm
```

> **Важно:** Команда `minikube delete` безвозвратно удаляет все PVC, Secrets, ConfigMap и пользовательские данные в кластере. Перед удалением убедитесь, что ценная информация (дашборды Grafana, query-логи в Tempo, метрики в Prometheus) экспортирована.

### Связанные темы

- **[Minikube: Практические сценарии](../minikube/minikube_practical_scenarios.md)** — подробные сценарии запуска, multi-node кластеры, профили, драйверы.
- **[Minikube: Концепции](../minikube/minikube_concepts.md)** — архитектура Minikube, драйверы, жизненный цикл.
- **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)** — пакетный менеджер, OCI-репозитории, values.
- **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)** — управление контекстами, несколько кластеров.
- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)** — следующий шаг после подготовки окружения.

---

**Навигация по руководству:**

- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
