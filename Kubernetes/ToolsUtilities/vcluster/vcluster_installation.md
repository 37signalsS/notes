# vCluster — Установка и развертывание

## Definitions

**vCluster CLI** — утилита командной строки для управления виртуальными Kubernetes-кластерами (создание, удаление, подключение, настройка).

**Distro** — вариант реализации Control Plane vCluster: Kubernetes (vanilla), K3s, K0s. Влияет на потребление ресурсов и доступные функции.

**values.yaml** — YAML-файл конфигурации Helm chart vCluster, определяющий параметры Control Plane, syncer и синхронизации ресурсов.

## Basic Concepts

### Варианты установки CLI

| Платформа | Менеджер пакетов | Команда |
| :--- | :--- | :--- |
| **macOS** | Homebrew | `brew install loft-sh/vcluster/vcluster` |
| **Linux** | Бинарный файл | Загрузка с GitHub, установка в `/usr/local/bin` |
| **Windows** | Chocolatey | `choco install vcluster` |

### Параметры создания vCluster

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-n` / `--namespace` | Namespace в host-кластере | `my-namespace` |
| `--kubernetes-version` | Версия K8s для vCluster | `1.31.0` |
| `--distro` | Вариант дистрибутива | `k3s`, `k0s`, `kubernetes` |
| `-f` / `--values` | Файл values.yaml | `values.yaml` |

### Структура values.yaml

Основные секции конфигурации:

| Секция | Назначение |
| :--- | :--- |
| `controlPlane` | Ресурсы, планирование, политика StatefulSet |
| `syncer` | Аргументы, service account, настройки синхронизации |
| `sync` | Синхронизация ресурсов (fromHost/toHost) |

## Practical Scenarios

### Установка vCluster CLI

```bash
# macOS (Homebrew)
brew install loft-sh/vcluster/vcluster

# Linux
curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64"
sudo install -c -m 0755 vcluster /usr/local/bin

# Windows (Chocolatey)
choco install vcluster

# Проверка установки
vcluster --version
```

### Создание vCluster

```bash
# Базовое создание
vcluster create my-vcluster -n my-namespace

# С указанием версии Kubernetes
vcluster create my-vcluster -n my-namespace \
  --kubernetes-version 1.31.0

# С использованием K3s
vcluster create my-vcluster -n my-namespace \
  --distro k3s

# С кастомными values
vcluster create my-vcluster -n my-namespace \
  -f values.yaml
```

### Пример values.yaml

```yaml
# values.yaml
controlPlane:
  statefulSet:
    scheduling:
      podManagementPolicy: Parallel
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 2Gi

syncer:
  extraArgs:
    - --service-account=my-vcluster-sa
```

### Удаление vCluster

```bash
# Через vCluster CLI
vcluster delete my-vcluster -n my-namespace

# Вручную: удаление Helm релиза
helm uninstall my-vcluster -n my-namespace

# Вручную: удаление namespace
kubectl delete namespace my-namespace
```

## Additional Information

Подробное описание архитектуры и компонентов: [vcluster_overview.md](./vcluster_overview.md). Подключение и доступ к vCluster: [vcluster_connectivity.md](./vcluster_connectivity.md). Безопасность и синхронизация ресурсов: [vcluster_security_and_sync.md](./vcluster_security_and_sync.md). Общая документация Helm: [helm_overview.md](../Helm/helm_overview.md).
