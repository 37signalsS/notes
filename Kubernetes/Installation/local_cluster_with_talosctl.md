# Установка и управление кластером через Talos Linux

Руководство по развертыванию Kubernetes с использованием Talos Linux — специализированной операционной системы, управляемой исключительно через API.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Talos Linux** | Минималистичная, безопасная ОС с открытым исходным кодом, созданная специально для Kubernetes. Не имеет SSH, оболочки (shell) и пакетного менеджера. |
| **talosctl** | Утилита командной строки (CLI) для взаимодействия с gRPC API узлов Talos. Основной инструмент администрирования. |
| **Machine Config** | Декларативный YAML-файл, описывающий состояние узла (сеть, диски, манифесты Kubernetes). Единственный источник истины для конфигурации каждого узла. |
| **talosconfig** | Файл конфигурации клиента, содержащий эндпоинты узлов и mTLS-сертификаты для доступа к API. По умолчанию位于 `~/.talos/config`. |
| **Config Patch** | YAML или JSON-файл с фрагментом конфигурации, который накладывается на базовую Machine Config при генерации или применении. Позволяет переопределять отдельные параметры без редактирования полного конфига. |
| **Image Factory** | Сервис Sidero Labs для кастомизации образов Talos Linux (добавление расширений, изменение параметров ядра) через web-интерфейс или API. Генерирует ISO, PXE-артефакты и загрузочные облака. |
| **Omni** | Платформа управления (SaaS или Self-hosted) от Sidero Labs для автоматизации жизненного цикла кластеров Talos. Предоставляет web-интерфейс и API для управления кластерами. |
| **Secure Boot** | Механизм проверки целостности загрузочной цепочки с помощью подписей UEFI. Talos поддерживает Secure Boot и TPM (Trusted Platform Module) для аттестации узлов. |
| **etcd** | Распределённое ключ-значение хранилище, используемое Kubernetes для хранения состояния кластера. В Talos управляется автоматически через Machine Config. |
| **Static Pod** | Под, управляемый напрямую kubelet на конкретном узле через манифест в `/etc/kubernetes/manifests/`, без участия API-сервера. Компоненты Control Plane в Talos работают как Static Pods. |

## Основные концепции

### Архитектура Talos Linux

Talos радикально отличается от традиционных дистрибутивов Linux (Ubuntu, RHEL):

- **API-First**: Управление осуществляется через gRPC. Даже чтение логов ядра или изменение настроек сети происходит через API. Единая точка входа — порт 50000 (`apid`).
- **Immutable & Read-only**: Корневая файловая система (`/`) доступна только для чтения и находится в RAM. Изменения не сохраняются после перезагрузки. Обновления выполняются через атомарную A/B замену образа на диске.
- **Security by Default**:
    - **No SSH**: Порт 22 отсутствует. Исключается вектор атак через брутфорс или уязвимости SSH-сервера. Все операции выполняются через gRPC API с аутентификацией по клиентским сертификатам.
    - **No Shell**: Отсутствует интерактивная оболочка. Все команды — типизированные API-вызовы, логируемые и авторизуемые через Machine Config.
    - **mTLS**: Весь трафик между `talosctl` и узлами, а также между самими узлами, зашифрован и аутентифицирован.
    - **Minimal Attack Surface**: ОС содержит менее 50 бинарных файлов (против 1280+ в Ubuntu Server), каждый из которых необходим для работы Kubernetes.
- **Ephemeral Nodes**: Узлы считаются расходным материалом. Обновление ОС или конфигурации часто сводится к замене узла или его перезагрузке с новым конфигом.
- **Declarative Configuration**: Конфигурация каждого узла описывается одним YAML-файлом (Machine Config). Состояние узла всегда соответствует описанному в конфигурации — конфигурационный дрифт структурно невозможен.

### Machine Config и её компоненты

Machine Config — центральный элемент управления Talos. Файл содержит несколько YAML-документов, разделённых `---`. Документы обрабатываются последовательно, более поздние переопределяют ранние.

| Секция | Назначение |
| :--- | :--- |
| `machine` | Параметры узла: сеть, диски,afety, kubelet, 时间, расширения |
| `cluster` | Параметры кластера: имя, endpoint, DNS, controle-plane, networking |
| `controlPlane` | Конфигурация control-plane (только для `controlplane.yaml`) |
| `worker` | Конфигурация worker-узла (только для `worker.yaml`) |

### Config Patching — наложение конфигураций

Config Patching позволяет изменять Machine Config без редактирования полного YAML-файла. Патчи применяются при генерации (`talosctl gen config`) или при的应用 к существующему узлу (`talosctl apply-config --patch`).

**Типы патчей:**
- **Строковые патчи** (RFC 6902 JSON Patch) — точечные изменения конкретных полей
- **Стратегические патчи** (RFC 7396 JSON Merge Patch) — замена целых секций

```yaml
# Пример строчного патча (RFC 6902)
- op: replace
  path: /machine/network/interfaces/0/addresses/0
  value: 192.168.1.101/24

# Пример стратегического патча (RFC 7396)
machine:
  network:
    interfaces:
      - interface: eth0
        addresses:
          - 192.168.1.101/24
```

### Сетевая модель

Talos предоставляет гибкую конфигурацию сети на уровне Machine Config:

- **Статический IP**: Указание адресов, шлюзов и DNS в `machine.network`
- **DHCP**: Автоматическое получение адреса (по умолчанию)
- **Bonding**: Агрегация интерфейсов для отказоустойчивости
- **VLAN**: Поддержка VLAN-тегирования
- **Bridge**: Создание мостов для контейнерных сетей

```yaml
# Пример сетевой конфигурации
machine:
  network:
    interfaces:
      - interface: eth0
        addresses:
          - 192.168.1.101/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.1.1
        mtu: 1500
    nameservers:
      - 8.8.8.8
      - 1.1.1.1
```

### Дисковая подсистема

Talos требует выделенный диск для установки. Корневая файловая система — это-read-only SquashFS образ, монтируемый в RAM. Данные хранятся на ephemeral разделе (tmpfs) или на выделенных дисках для persistent storage.

| Раздел | Назначение | Тип |
| :--- | :--- | :--- |
| `ESP` | EFI System Partition (для UEFI) | FAT32 |
| `boot` | Загрузчик и ядро | ext4 |
| `metal` | Корневая файловая система (read-only) | SquashFS |
| `ephemeral` | Временные данные (перезапуск = потеря) | ext4/xfs |
| `state` | Состояние узла (Machine Config, сертификаты) | ext4/xfs |

**Минимальные требования к диску:** 500 MB для системы + выделенные диски для данных etcd и persistent volumes.

### Обновление кластера

Talos использует атомарную A/B схему обновления:

1. Новый образ ОС записывается на неактивный раздел
2. Обновляется Machine Config (версия Talos и Kubernetes)
3. Узел перезагружается на новый образ
4. При ошибке — автоматический откат на предыдущий образ

```bash
# Обновление одного узла
talosctl upgrade --nodes 192.168.1.101 --image ghcr.io/siderolabs/installer:v1.13.8

# Обновление кластера (rolling update)
talosctl upgrade --nodes 192.168.1.101,192.168.1.102,192.168.1.103 \
  --image ghcr.io/siderolabs/installer:v1.13.8
```

### Сравнение с традиционными методами

| Критерий | Talos Linux | Kubeadm (Ubuntu/Debian) |
| :--- | :--- | :--- |
| **Управление ОС** | Декларативное (YAML) | Императивное (Bash/Ansible) |
| **Обновление K8s** | Одной командой через API | Пошагово (apt update, kubeadm upgrade) |
| **Безопасность** | Максимальная (mTLS, no SSH) | Требует ручной настройки Hardening |
| **Зависимости** | Встроены (containerd, kubelet) | Устанавливаются отдельно |
| **Конфигурационный дрифт** | Структурно невозможен | Возможен, требует мониторинга |
| **Атака** | <50 бинарных файлов | 1280+ бинарных файлов |
| **Boot Time** | ~1 мин | 5-10 мин |
| **Образ ОС** | ~100 MB | 2.5-4 GB |

## Практические сценарии

### 1. Подготовка окружения

Для работы требуется `talosctl`. Рекомендуется управлять версией через **mise**.

#### Установка talosctl

```bash
# Установка через официальный скрипт (Linux/macOS)
curl -sL https://talos.dev/install | sh

# Установка через Homebrew (macOS/Linux) — рекомендуется
brew tap siderolabs/tap
brew install siderolabs/tap/sidero-tools

# Проверка версии (Актуальная на август 2026: v1.13.x)
talosctl version --client
# → Client: v1.13.8
```

#### Управление версиями через mise

```bash
# Добавление плагина
mise plugin add talosctl https://github.com/bjw-s/asdf-talosctl.git

# Установка конкретной версии
mise install talosctl 1.13.8

# Глобальная версия
mise use -g talosctl@1.13.8

# Или в .tool-versions файла проекта
echo "talosctl 1.13.8" >> .tool-versions
```

### 2. Создание локального кластера в Docker

Идеально для тестирования и разработки. Каждый узел — Docker-контейнер с полным стеком Talos + Kubernetes.

```bash
# Создание кластера (1 CP + 1 Worker)
talosctl cluster create --name lab-cluster --wait

# Получение kubeconfig
talosctl kubeconfig .

# Проверка узлов
kubectl get nodes
# → node1   Ready   control-plane   v1.36.2

# Удаление кластера
talosctl cluster destroy --name lab-cluster
```

**Продвинутые параметры создания:**

```bash
# Создание кластера с 3 CP + 2 Worker (HA-конфигурация)
talosctl cluster create --name ha-lab \
  --control-plane-nodes 3 \
  --worker-nodes 2 \
  --wait

# Указание версии Kubernetes
talosctl cluster create --name k8s-lab \
  --kubernetes-version 1.36.2

# С кастомными портами (избегаем конфликтов)
talosctl cluster create --name lab2 \
  --experimental-control-plane-port 7443
```

### 3. Генерация конфигурации для Bare Metal / VM

Для реальных инсталляций сначала генерируются секреты и конфиги.

```bash
# Генерация секретов и базовых конфигов
talosctl gen config my-cluster https://<load-balancer-ip-or-dns>:6443

# Результат:
# → controlplane.yaml - конфиг для мастеров
# → worker.yaml - конфиг для воркеров
# → talosconfig - конфиг для администратора
```

**Параметры gen config:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--cluster-name` | Имя кластера | `my-cluster` |
| `--endpoint` | URL API-сервера | `https://192.168.1.100:6443` |
| `--kubernetes-version` | Версия Kubernetes | `1.36.2` |
| `--talos-version` | Версия Talos | `v1.13.8` |
| `--config-patch-control-plane` | Патч для CP | `@patch-cp.yaml` |
| `--config-patch-worker` | Патч для Worker | `@patch-worker.yaml` |
| `--config-patch` | Патч для всех узлов | `@patch-all.yaml` |

### 4. Применение конфигурации к узлам

После генерации конфигов необходимо применить их к физическим узлам.

#### Bare Metal установка (UEFI/BIOS)

```bash
# Скачивание ISO-образа Talos Linux
curl -LO https://github.com/siderolabs/talos/releases/latest/download/metal-amd64.iso

# Запись на USB-накопитель (Linux)
sudo dd if=metal-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync

# Запись на USB-накопитель (macOS)
diskutil unmountDisk /dev/disk2
sudo dd if=metal-amd64.iso of=/dev/rdisk2 bs=4m
```

**Процесс загрузки с USB:**
1. Вставить USB в сервер
2. При POST нажать клавишу_BOOT_ (F12 для Dell, F11 для HP, F2 для Supermicro)
3. Выбрать USB-устройство в меню загрузки
4. Talos загрузится и отобразит IP-адрес узла
5. Узел войдёт в режим **maintenance** и будет ожидать Machine Config

> **Важно:** На экране Talos нет приглашения для входа. Нет SSH. Нет оболочки. Всё управление через `talosctl`.

#### Применение конфигурации

```bash
# Применение конфигурации к control-plane узлу (первичная установка)
talosctl apply-config --insecure \
  --nodes 192.168.1.101 \
  --file controlplane.yaml

# Применение конфигурации к worker-узлу
talosctl apply-config --insecure \
  --nodes 192.168.1.102 \
  --file worker.yaml
```

> **Параметр `--insecure`:** Необходим при первичной установке, когда узел ещё не имеет конфигурации и TLS не установлен. После применения конфига узел перезагрузится и установит Talos на диск. Все последующие подключения будут через mTLS.

#### Проверка статуса узла после установки

```bash
# Настройка окружения
export TALOSCONFIG="$HOME/.talos/config"

# Проверка здоровья узла
talosctl health --nodes 192.168.1.101

# Просмотр сервисов
talosctl services --nodes 192.168.1.101

# Просмотр IP-адреса узла
talosctl get links --nodes 192.168.1.101
```

### 5. Бутстрап кластера

После применения конфигурации ко всем узлам необходимо инициировать Kubernetes:

```bash
# Бутстрап Kubernetes на первом control-plane узле
# ВАЖНО: команду bootstrap выполнять ТОЛЬКО ОДИН РАЗ на ОДНОМ узле
talosctl bootstrap --nodes 192.168.1.101

# Ожидание готовности (обычно 2-5 минут)
kubectl wait --for=condition=Ready nodes --all --timeout=300s
```

**Получение kubeconfig:**

```bash
# Получение kubeconfig и слияние с ~/.kube/config
talosctl kubeconfig --nodes 192.168.1.101

# Или в отдельный файл
talosctl kubeconfig --nodes 192.168.1.101 --force --talosconfig ~/.talos/config

# Проверка подключения
kubectl get nodes
# → NAME           STATUS   ROLES           AGE   VERSION
# → master-1       Ready    control-plane   5m    v1.36.2
# → worker-1       Ready    <none>          4m    v1.36.2
```

### 6. Multi-node HA-кластер (High Availability)

Для production-окружений рекомендуется минимум 3 control-plane узла.

#### Генерация конфигурации для HA

```bash
# Генерация с контролем версий
talosctl gen config my-ha-cluster https://192.168.1.100:6443 \
  --kubernetes-version 1.36.2 \
  --talos-version v1.13.8 \
  --config-patch-control-plane @cp-patch.yaml \
  --config-patch-worker @worker-patch.yaml
```

#### Пример патча для control-plane

```yaml
# cp-patch.yaml
machine:
  kubelet:
    extraConfig:
      serverTLSBootstrap: true
  network:
    interfaces:
      - interface: eth0
        addresses:
          - 192.168.1.101/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.1.1
    nameservers:
      - 8.8.8.8
      - 1.1.1.1
cluster:
  controlPlane:
    replicas: 3
  etcd:
    advertisedEndpoints:
      - 192.168.1.101
      - 192.168.1.102
      - 192.168.1.103
```

#### Последовательность развёртывания

```bash
# 1. Применение конфигурации ко всем узлам
for node in 192.168.1.101 192.168.1.102 192.168.1.103; do
  talosctl apply-config --insecure --nodes $node --file controlplane.yaml
done

for node in 192.168.1.104 192.168.1.105; do
  talosctl apply-config --insecure --nodes $node --file worker.yaml
done

# 2. Бутстрап (ТОЛЬКО на первом CP узле)
talosctl bootstrap --nodes 192.168.1.101

# 3. Ожидание готовности
kubectl wait --for=condition=Ready nodes --all --timeout=300s

# 4. Проверка etcd
talosctl etcd members --nodes 192.168.1.101
```

### 7. Config Patching — кастомизация конфигурации

#### Статическая сеть (вместо DHCP)

```yaml
# patch-network.yaml
machine:
  network:
    interfaces:
      - interface: eth0
        dhcp: false
        addresses:
          - 192.168.1.101/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.1.1
        mtu: 1500
    nameservers:
      - 192.168.1.1
      - 8.8.8.8
```

```bash
# Генерация с патчем
talosctl gen config my-cluster https://192.168.1.100:6443 \
  --config-patch-control-plane @patch-network.yaml

# Или применение к существующему узлу
talosctl apply-config --nodes 192.168.1.101 \
  --file patch-network.yaml
```

#### Настройка дисков и хранилища

```yaml
# patch-disk.yaml
machine:
  disks:
    - device: /dev/sdb
      partitions:
        - label: data
          size: 100GiB
  kubelet:
    extraMounts:
      - destination: /var/lib/extra
        type: bind
        source: /var/lib/extra
        options:
          - rbind
          - rshared
          - rw
```

#### Дополнения (Extensions)

Talos позволяет добавлять драйверы или специфическое ПО (например, NVIDIA, iSCSI) через расширения.

```yaml
# extensions-patch.yaml
machine:
  install:
    extensions:
      - image: ghcr.io/siderolabs/nvidia-gpu-6.18:595.x.x
      - image: ghcr.io/siderolabs/iscsi-tools:0.1.4
```

> **Важно:** Расширения должны совпадать по версии ядра и Talos. Используйте Image Factory для генерации кастомного ISO.

### 8. Настройка безопасности Kubelet (Server TLS Bootstrap)

Для обеспечения проверяемого TLS между API-сервером и Kubelet (для `kubectl logs`, `exec`), необходимо включить ротацию серверных сертификатов. В Talos это делается одной строкой в конфигурации узла.

```yaml
machine:
  kubelet:
    extraConfig:
      serverTLSBootstrap: true
```

После применения конфигурации (`talosctl apply-config`) и перезапуска сервиса kubelet, узел начнет отправлять CSR для серверного сертификата. Для автоматического одобрения этих запросов требуется установка контроллера одобрения (см. [Управление сертификатами](../Operations/certificate_management.md)).

### 9. Управление узлами (Day 2 Operations)

#### Масштабирование кластера

```bash
# Добавление worker-узла
# 1. Сгенерировать или использовать существующий worker.yaml
# 2. Применить конфигурацию к новому узлу
talosctl apply-config --insecure --nodes 192.168.1.106 --file worker.yaml

# Добавление control-plane узла (для HA)
# 1. Использовать controlplane.yaml
talosctl apply-config --insecure --nodes 192.168.1.104 --file controlplane.yaml

# 2. Присоединение к существующему кластеру (если кластер уже бутстраплен)
talosctl apply-config --nodes 192.168.1.104 --file controlplane.yaml
```

#### Удаление узла

```bash
# Удаление worker-узла
# 1. Дренаж узла
kubectl drain worker-1 --ignore-daemonsets --delete-emptydir-data

# 2. Удаление из кластера
kubectl delete node worker-1

# 3. Сброс узла Talos (возврат в maintenance mode)
talosctl reset --nodes 192.168.1.102

# Удаление control-plane узла (осторожно!)
# 1. Убедиться, что кластер остаётся HA (минимум 2 CP узла)
# 2. Выполнить дренаж и удаление
kubectl drain master-2 --ignore-daemonsets --delete-emptydir-data
kubectl delete node master-2
talosctl reset --nodes 192.168.1.102
```

#### Просмотр логов и диагностика

```bash
# Логи сервисов
talosctl logs --nodes 192.168.1.101 kubelet

# Логи контейнеров (через кластер)
talosctl logs --nodes 192.168.1.101 --namespace kube-system kube-apiserver

# Дамп всей конфигурации
talosctl get machineconfig --nodes 192.168.1.101 -o yaml

# Список всех ресурсов
talosctl get --nodes 192.168.1.101
```

### 10. Диагностика и Troubleshooting

Поскольку SSH нет, используются специфические команды `talosctl`.

```bash
# Просмотр логов ядра (аналог dmesg)
talosctl dmesg --nodes 192.168.1.101

# Проверка состояния здоровья узла
talosctl health --nodes 192.168.1.101

# Интерактивный дашборд (аналог htop + k9s для ОС)
talosctl dashboard --nodes 192.168.1.101

# Сбор диагностического пакета для поддержки
talosctl support --nodes 192.168.1.101

# Просмотр метаданных узла
talosctl get members --nodes 192.168.1.101

# Проверка etcd
talosctl etcd members --nodes 192.168.1.101
talosctl etcd alarm list --nodes 192.168.1.101

# Просмотр процессов (аналог ps aux)
talosctl processes --nodes 192.168.1.101

# Проверка сетевых интерфейсов
talosctl get links --nodes 192.168.1.101
talosctl get addresses --nodes 192.168.1.101
```

## Устранение проблем

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`connection refused`** | Узел в maintenance mode или не применялся конфиг | Применить конфигурацию через `talosctl apply-config --insecure` |
| **`no route to host`** | Проблемы с сетью (firewall, неверный IP) | Проверить маршрутизацию, firewall, IP-адрес узла |
| **`certificate has expired`** | Истёк срок действия клиентского сертификата | Пересоздать talosconfig: `talosctl kubeconfig` |
| **`etcd cluster has no healthy members`** | Проблемы с etcd (диск, сеть, консенсус) | Проверить `talosctl etcd members`, перезапустить узлы |
| **`node not ready`** | kubelet не может подключиться к API | Проверить логи kubelet: `talosctl logs kubelet` |
| **`failed to pull image`** | Проблемы с доступом к registry | Проверить DNS, сеть, credentials для приватных registry |
| **`disk not found`** | Talos не может найти диск для установки | Проверить `talosctl get disks`, убедиться в наличии выделенного диска |
| **Bootstrap зависает** | Проблемы с network или DNS | Проверить `talosctl dmesg`, сетевую конфигурацию |

### Диагностический чек-лист

```bash
# 1. Проверка подключения к API
talosctl health --nodes <IP>

# 2. Просмотр логов ядра
talosctl dmesg --nodes <IP>

# 3. Проверка сервисов
talosctl services --nodes <IP>

# 4. Просмотр конфигурации
talosctl get machineconfig --nodes <IP> -o yaml

# 5. Проверка etcd
talosctl etcd members --nodes <IP>

# 6. Просмотр процессов
talosctl processes --nodes <IP>

# 7. Сбор полного диагностического пакета
talosctl support --nodes <IP>
```

### Восстановление после сбоя

```bash
# Сброс узла до заводского состояния (maintenance mode)
talosctl reset --nodes <IP>

# Принудительное обновление (если обновление застряло)
talosctl upgrade --nodes <IP> --image ghcr.io/siderolabs/installer:v1.13.8 --force

# Откат на предыдущую версию (если A/B rollback не сработал)
# Откат происходит автоматически при неудачном обновлении
# Ручной откат:
talosctl upgrade --nodes <IP> --image ghcr.io/siderolabs/installer:<предыдущая_версия>
```

## Дополнительная информация

### Совместимость (Август 2026)

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| **Talos OS** | v1.13.8 | Стабильная ветка |
| **Kubernetes** | 1.31 - 1.36 | Полная поддержка |
| **Linux Kernel** | 6.18.x | С поддержкой cgroup v2 |
| **containerd** | 2.x | Встроенный CRI-плагин |

### Лучшие практики

- **Минимум 3 CP узла** для production — обеспечивает отказоустойчивость control plane.
- **Выделенные диски NVMe для etcd** — etcd чувствителен к задержкам ввода-вывода (fsync <10 мс).
- **Настройка `serverTLSBootstrap: true`** — необходима для корректной работы `kubectl exec`, `kubectl logs`.
- **Config Patching** — используйте патчи вместо редактирования полного конфига для воспроизводимости.
- **Версионирование конфигов** — храните Machine Config в Git для отслеживания изменений.
- **Бэкапы etcd** — регулярно создавайте снимки состояния кластера.
- **Rolling Updates** — обновляйте узлы по одному для минимизации даунтайма.

### Требования к оборудованию

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядер |
| **RAM** | 2 GB | 8+ GB |
| **Диск** | 500 MB (система) | NVMe для etcd |
| **Сеть** | 100 Mbps | 1+ Gbps |
| **UEFI/BIOS** | UEFI (рекомендуется) | UEFI + Secure Boot |

### Полезные команды

```bash
# Быстрый обзор кластера
talosctl get members
talosctl health

# Управление конфигурацией
talosctl get machineconfig -o yaml
talosctl apply-config --nodes <IP> --file new-config.yaml

# Диагностика
talosctl dmesg
talosctl services
talosctl processes
talosctl dashboard

# Обновление
talosctl upgrade --nodes <IP> --image ghcr.io/siderolabs/installer:<version>

# Сброс
talosctl reset --nodes <IP>
```

## Дополнительные ссылки

- [Официальная документация Talos](https://docs.siderolabs.com/talos/)
- [Репозиторий системных расширений](https://github.com/siderolabs/extensions)
- [Image Factory — кастомизация образов](https://www.talos.dev/v1.13/learn-more/image-factory/)
- **[Kubeconfig: Настройка подключения](../Operations/kubeconfig_and_connection.md)** — управление доступом.
- **[Управление сертификатами](../Operations/certificate_management.md)** — ротация и CSR.
- **[mise: Управление инструментами](../../mise.md)** — менеджер версий talosctl.

## См. также

- [Создание локальных кластеров через kind](./kind/kind_concepts.md)
- [Создание локальных кластеров через minikube](./minikube/minikube_concepts.md)
- [Архитектура Control Plane](../Concepts/control_plane_architecture.md)
