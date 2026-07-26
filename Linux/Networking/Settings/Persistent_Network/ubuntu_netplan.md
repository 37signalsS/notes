# Настройка Netplan в Ubuntu

**Netplan** — это стандартная утилита для конфигурации сети в дистрибутивах Ubuntu (начиная с версии 17.10), использующая декларативный подход на основе файлов в формате YAML (Yet Another Markup Language). Netplan выступает в роли абстрактного слоя: он не настраивает сетевые интерфейсы напрямую, а генерирует конфигурационные файлы для выбранных бэкендов (**renderers**), таких как `systemd-networkd` (основной выбор для серверов) или `NetworkManager` (для рабочих станций).

## Определения

- **Backend (Renderer / Бэкенд)** — системная служба, которая непосредственно управляет сетевыми интерфейсами. Основные варианты: `systemd-networkd` и `NetworkManager`.
- **YAML (Yet Another Markup Language)** — человекочитаемый формат сериализации данных, чувствительный к отступам (использование табуляции запрещено).
- **Пути конфигурации (в порядке приоритета):**
  - `/run/netplan/*.yaml` — временные настройки (например, от `cloud-init`).
  - `/etc/netplan/*.yaml` — основные настройки администратора.
  - `/lib/netplan/*.yaml` — настройки, поставляемые системными пакетами.
- **Интерфейс командной строки (CLI):**
  - `netplan status` — просмотр текущего состояния сети (доступно в новых версиях).
  - `netplan get` — вывод текущей конфигурации в формате YAML.
  - `netplan set` — изменение параметров через CLI.

## Базовые концепции

### Структура конфигурации

Файлы Netplan всегда начинаются с корневого блока `network`. Критически важно соблюдать иерархию отступов (обычно 2 или 4 пробела).

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: true
      optional: true
```

### Ключевые параметры

1. **`renderer`**: определяет, кто будет управлять сетью. На серверах без GUI рекомендуется `networkd`.
2. **`optional: true`**: предотвращает задержку загрузки системы при отсутствии линка на интерфейсе (например, если кабель не подключен).
3. **`critical: true`**: указывает, что интерфейс необходим для монтирования корневой ФС (используется в initramfs).
4. **`activation-mode`**: позволяет перевести интерфейс в состояние `up` без назначения IP-адресов.

## Практические сценарии

### 1. Статический IP-адрес и маршруты

В современных версиях Netplan параметры `gateway4` и `gateway6` объявлены **устаревшими**. Рекомендуется использовать секцию `routes`.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      addresses:
        - 10.10.10.10/24
      routes:
        - to: default
          via: 10.10.10.1
          metric: 100
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```

### 2. Сетевой мост (Bridge)

Используется для виртуализации (KVM/QEMU) или объединения сегментов сети.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
  bridges:
    br0:
      interfaces: [enp0s3]
      addresses: [192.168.1.50/24]
      parameters:
        stp: true
        forward-delay: 0
```

### 3. Маршрутизация на основе политик (PBR)

Позволяет направлять трафик через разные шлюзы в зависимости от источника.

```yaml
network:
  version: 2
  ethernets:
    enp0s3:
      addresses: [10.0.0.10/24]
      routing-policy:
        - from: 10.0.0.10
          table: 101
      routes:
        - to: default
          via: 10.0.0.1
          table: 101
```

### 4. Агрегация каналов (Bonding) и VLAN

```yaml
network:
  version: 2
  renderer: networkd
  bonds:
    bond0:
      interfaces: [enp3s0, enp3s1]
      parameters:
        mode: 802.3ad
        mii-monitor-interval: 1
  vlans:
    bond0.10:
      id: 10
      link: bond0
      addresses: [172.16.10.1/24]
```

## Дополнительная информация

### Управление и диагностика

| Команда | Описание |
| :--- | :--- |
| `sudo netplan try` | Безопасное применение с автооткатом через 120 секунд. |
| `sudo netplan apply` | Немедленное применение конфигурации. |
| `sudo netplan --debug generate` | Проверка синтаксиса и генерация конфигов для бэкендов без их применения. |
| `netplan status` | Вывод сводки по интерфейсам, IP и маршрутам. |

### Особенности работы

- **Объединение файлов:** если в `/etc/netplan/` несколько файлов, они объединяются лексикографически. Файл `99-custom.yaml` переопределит настройки из `01-netcfg.yaml`.
- **Взаимодействие с Cloud-Init:** часто облачные провайдеры создают файл в `/etc/netplan/50-cloud-init.yaml`. Не редактируйте его напрямую, создайте файл с более высоким приоритетом (например, `90-local.yaml`).

### См. также

- **[systemd-networkd](./systemd_networkd.md)** — глубокая настройка бэкенда networkd.
- **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — теория LACP (Link Aggregation Control Protocol) и балансировки.
- **[Маршрутизация по политикам (PBR)](../../Policy_Based_Routing/index.md)** — подробный обзор таблиц и правил.
- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — как Netplan взаимодействует с `systemd-resolved`.
