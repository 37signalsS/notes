# vCluster — установка и развёртывание

## Определения

**vCluster CLI (Command Line Interface)** — основной инструмент управления жизненным циклом виртуальных кластеров: создание, настройка, подключение и удаление.

**vCluster Standalone** — режим установки (v0.30+), позволяющий развернуть Control Plane vCluster как независимый процесс непосредственно на ОС хоста (Bare Metal/VM). Решает проблему "Cluster Zero", не требуя предварительного наличия Kubernetes.

**vind (vCluster in Docker)** — драйвер для запуска виртуальных кластеров в контейнерах Docker (аналог `kind`). Идеально подходит для локальной разработки и тестирования.

**Дистрибутив (Distro)** — реализация Control Plane. В версиях v0.33+ основным и рекомендуемым является стандартный **Kubernetes (upstream)**. Поддержка K3s в новых мажорных версиях прекращена в пользу встроенного etcd и чистого K8s.

**vcluster.yaml** — унифицированный конфигурационный файл. В версиях 2026 года (v0.30+) структура оптимизирована: параметры масштабирования, безопасности и сетевого взаимодействия вынесены на верхний уровень.

## Основные концепции

### Способы установки CLI

| Платформа | Метод установки | Команда |
| :--- | :--- | :--- |
| **macOS** | Homebrew | `brew install loft-sh/tap/vcluster` |
| **Linux** | curl (бинарный файл) | `curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64" && sudo install -c -m 0755 vcluster /usr/local/bin` |
| **Windows** | PowerShell (scoop) | `scoop bucket add loft-sh https://github.com/loft-sh/scoop-bucket && scoop install vcluster` |

### Методы развертывания виртуального кластера

| Метод | Описание | Команда / Инструмент |
| :--- | :--- | :--- |
| **Host-based (Pod)** | Запуск vCluster внутри существующего K8s. | `vcluster create my-vc` |
| **Standalone** | Прямая установка на Linux-хост. | `install-standalone.sh` |
| **Docker-based (vind)** | Запуск в локальном Docker-окружении. | `vcluster create my-vc --driver docker` |
| **Helm** | Развертывание через пакетный менеджер. | `helm install vcluster loft/vcluster` |

### Параметры создания vCluster (v0.30+)

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-n` / `--namespace` | Пространство имен (для Host-based режима). | `team-a` |
| `--kubernetes-version` | Версия Kubernetes (по умолчанию v1.36.0+). | `1.35.2` |
| `--driver` | Выбор драйвера выполнения. | `docker`, `k8s` |
| `-f` / `--config` | Путь к файлу `vcluster.yaml`. | `./config.yaml` |
| `--vcluster-name` | Имя инстанса (для Standalone режима). | `management-cluster` |

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

### Удаление кластера

```bash
# Удаление виртуального кластера (Host-based)
vcluster delete my-vc -n my-namespace

# Удаление локального Docker-кластера (vind)
vcluster delete local-vc --driver docker

# Удаление с сохранением хранилища данных (PVC)
vcluster delete dev-vc -n team-alpha --keep-pvc
```

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)

### См. также

- [Установка через Helm](../../ToolsUtilities/Helm/helm_overview.md)
- [kind — практические сценарии](../../Installation/kind/kind_practical_scenarios.md)

### Внешние ссылки

- [vCluster Installation Guide (Official)](https://www.vcluster.com/docs/getting-started/installation)
- [vCluster CLI Releases on GitHub](https://github.com/loft-sh/vcluster/releases)
- [Standalone Mode Documentation](https://www.vcluster.com/docs/features/standalone)
