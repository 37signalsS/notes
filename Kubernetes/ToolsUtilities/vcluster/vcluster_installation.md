# vCluster — Установка и развёртывание

## Определения

**vCluster CLI (Command Line Interface)** — утилита командной строки для управления виртуальными Kubernetes-кластерами (создание, удаление, подключение, настройка).

**Distro (Дистрибутив)** — вариант реализации Control Plane vCluster: Kubernetes (vanilla), K3s, K0s. Выбор дистрибутива влияет на потребление ресурсов и доступный функционал.

**values.yaml (Yet Another Markup Language)** — основной файл конфигурации Helm chart vCluster, определяющий параметры Control Plane, syncer и правила синхронизации ресурсов.

## Основные концепции

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
| `--kubernetes-version` | Версия Kubernetes для vCluster | `1.32.0` |
| `--distro` | Вариант дистрибутива | `k3s`, `k0s`, `kubernetes` |
| `-f` / `--values` | Путь к файлу values.yaml | `values.yaml` |

### Структура конфигурации values.yaml

Основные секции конфигурации:

| Секция | Назначение |
| :--- | :--- |
| `controlPlane` | Настройка ресурсов CPU (Central Processing Unit) / RAM, планирование и параметры StatefulSet |
| `syncer` | Аргументы запуска, ServiceAccount, глобальные настройки синхронизатора |
| `sync` | Детальная настройка синхронизации ресурсов (fromHost/toHost) |

## Практические сценарии

### Установка vCluster CLI

```bash
# macOS (Homebrew)
brew install loft-sh/vcluster/vcluster

# Linux
curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64"
sudo install -c -m 0755 vcluster /usr/local/bin

# Windows (Chocolatey)
choco install vcluster

# Проверка версии
vcluster --version
```

### Создание vCluster

```bash
# Базовое создание кластера
vcluster create my-vcluster -n my-namespace

# Создание с указанием конкретной версии Kubernetes
vcluster create my-vcluster -n my-namespace \
  --kubernetes-version 1.32.0

# Использование облегченного дистрибутива K3s
vcluster create my-vcluster -n my-namespace \
  --distro k3s

# Создание с применением кастомной конфигурации
vcluster create my-vcluster -n my-namespace \
  -f values.yaml
```

### Пример конфигурации values.yaml

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
# Удаление через vCluster CLI
vcluster delete my-vcluster -n my-namespace

# Удаление только Helm-релиза (вручную)
helm uninstall my-vcluster -n my-namespace

# Полное удаление namespace (вручную)
kubectl delete namespace my-namespace
```

## Дополнительная информация

### Внутренние ссылки

- [vCluster — Обзор и архитектура](./vcluster_overview.md)
- [vCluster — Подключение и доступ](./vcluster_connectivity.md)
- [vCluster — Безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)
- [Установка через Helm](../Helm/helm_overview.md)

### Внешние ссылки

- [vCluster Installation Guide](https://www.vcluster.com/docs/getting-started/installation)
- [vCluster CLI GitHub Releases](https://github.com/loft-sh/vcluster/releases)
