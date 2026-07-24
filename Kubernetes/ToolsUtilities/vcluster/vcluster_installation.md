# vCluster — установка и развёртывание

## Определения

**vCluster CLI (Command Line Interface)** — утилита командной строки для управления жизненным циклом виртуальных кластеров: создание, удаление, подключение и настройка конфигурации.

**Distro (Дистрибутив)** — вариант реализации Control Plane виртуального кластера. Основные варианты: Kubernetes (vanilla), K3s (по умолчанию), K0s. Выбор влияет на потребление ресурсов и доступный функционал API.

**vcluster.yaml** — единый файл конфигурации (введен в v0.20+), который описывает параметры дистрибутива, правила синхронизации ресурсов, настройки безопасности и расширенные функции (например, Sleep Mode).

## Основные концепции

### Способы установки CLI

| Платформа | Метод установки | Команда |
| :--- | :--- | :--- |
| **macOS** | Homebrew | `brew install loft-sh/vcluster/vcluster` |
| **Linux** | curl (бинарный файл) | `curl -L -o vcluster https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64` |
| **Windows** | Chocolatey | `choco install vcluster` |

### Параметры создания vCluster

При использовании CLI v0.20+ основные параметры передаются через флаги или файл конфигурации.

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-n` / `--namespace` | Пространство имен в хост-кластере | `my-namespace` |
| `--kubernetes-version` | Желаемая версия Kubernetes | `1.32.0` |
| `--distro` | Выбор дистрибутива | `k3s`, `k0s`, `k8s` |
| `-f` / `--config` | Путь к файлу конфигурации | `vcluster.yaml` |

## Практические сценарии

### Установка vCluster CLI

```bash
# Проверка установленной версии
vcluster --version

# Обновление до последней версии
vcluster upgrade
```

### Создание виртуального кластера

```bash
# Быстрое создание с настройками по умолчанию (K3s)
vcluster create my-vcluster -n my-namespace

# Создание с выбором версии и дистрибутива
vcluster create dev-cluster -n team-a \
  --distro k8s \
  --kubernetes-version 1.31.0

# Создание на основе файла конфигурации
vcluster create prod-vcluster -n production -f vcluster.yaml
```

### Пример конфигурации vcluster.yaml (v0.20+)

Новый формат конфигурации более структурирован и интуитивно понятен:

```yaml
# vcluster.yaml
controlPlane:
  distro:
    k3s:
      enabled: true
  backingStore:
    etcd:
      embedded:
        enabled: true

# Настройка контекста при экспорте kubeconfig
exportKubeConfig:
  context: "my-vcluster-context"

# Правила синхронизации
sync:
  fromHost:
    storageClasses:
      enabled: true
  toHost:
    ingresses:
      enabled: true
```

### Удаление кластера

```bash
# Удаление виртуального кластера и всех связанных ресурсов
vcluster delete my-vcluster -n my-namespace

# Удаление без удаления пространства имен (если нужно сохранить другие ресурсы)
vcluster delete my-vcluster -n my-namespace --keep-pvc
```

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)
- [Установка через Helm](../../ToolsUtilities/Helm/helm_overview.md)

### Внешние ссылки

- [Официальное руководство по установке](https://www.vcluster.com/docs/getting-started/installation)
- [Список релизов vCluster CLI на GitHub](https://github.com/loft-sh/vcluster/releases)
