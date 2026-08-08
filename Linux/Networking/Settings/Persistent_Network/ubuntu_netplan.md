# Настройка Netplan в Ubuntu

**Netplan** — это стандартная утилита для конфигурации сети в дистрибутивах Ubuntu (начиная с версии 17.10) и Debian (v12+), использующая декларативный подход на основе файлов в формате YAML (Yet Another Markup Language). Netplan выступает в роли абстрактного слоя: он не настраивает сетевые интерфейсы напрямую, а генерирует конфигурационные файлы для выбранных бэкендов (**renderers**), таких как `systemd-networkd` (основной выбор для серверов) или `NetworkManager` (для рабочих станций).

С выходом **Netplan 1.0** (апрель 2024) проект признан стабильным и рекомендованным для использования во всех окружениях, включая встраиваемые системы и облака.

## Определения

- **Backend (Renderer / Бэкенд)** — системная служба, которая непосредственно управляет сетевыми интерфейсами. Основные варианты: `systemd-networkd` и `NetworkManager`.
- **YAML (Yet Another Markup Language)** — человекочитаемый формат сериализации данных, чувствительный к отступам (использование табуляции запрещено).
- **Match** — секция, позволяющая идентифицировать сетевой интерфейс по различным критериям (MAC-адрес, драйвер, имя), прежде чем применять к нему настройки.
- **Set-name** — параметр, позволяющий переименовать интерфейс при его обнаружении (часто используется совместно с `match`).
- **Пути конфигурации (в порядке приоритета):**
  - `/run/netplan/*.yaml` — временные настройки (например, от `cloud-init`).
  - `/etc/netplan/*.yaml` — основные настройки администратора.
  - `/lib/netplan/*.yaml` — настройки, поставляемые системными пакетами.
- **Интерфейс командной строки (CLI):**
  - `netplan status` — вывод детального состояния всех интерфейсов, включая IP, маршруты и DNS.
  - `netplan get [key]` — получение текущей конфигурации или значения конкретного ключа.
  - `netplan set [key=value]` — динамическое изменение параметров через CLI (сохраняется в `/etc/netplan/`).

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

1. **`renderer`**: определяет бэкенд управления. На серверах рекомендуется `networkd`, на десктопах — `NetworkManager`.
2. **`match`**: позволяет привязать конфиг к конкретному «железу».
   ```yaml
   match:
     macaddress: 52:54:00:12:34:56
   ```
3. **`set-name`**: переименование интерфейса (например, в `eth0` для совместимости).
4. **`optional: true`**: не блокирует загрузку системы, если линк на интерфейсе отсутствует.
5. **`critical: true`**: интерфейс важен для загрузки (например, при загрузке по iSCSI/NFS).
6. **`activation-mode`**: (v0.101+) может принимать значения `up`, `off`, `manual`. Позволяет поднять интерфейс без назначения IP.

## Практические сценарии

### 1. Статический IP-адрес и маршруты

Параметры `gateway4` и `gateway6` устарели. Используйте секцию `routes`.

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

### 2. Сетевой мост (Bridge) и VLAN

Мост с поддержкой фильтрации VLAN (VLAN-aware).

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

### 3. Маршрутизация на основе политик (PBR) и VRF

Использование VRF для полной изоляции сетевого стека.

```yaml
network:
  version: 2
  renderer: networkd
  vrfs:
    vrf-blue:
      table: 10
      interfaces: [enp0s8]
  ethernets:
    enp0s8:
      addresses: [10.0.0.10/24]
      routes:
        - to: default
          via: 10.0.0.1
          table: 10
```

### 4. Агрегация каналов (Bonding) и SR-IOV

Настройка виртуальных функций (VF) для высокопроизводительных систем.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0:
      virtual-functions:
        - count: 4
          # v0.100+: назначение MAC и VLAN для VF
          vlan: 100
```

### 5. Современный WiFi (WPA3-SAE)

Требует `renderer: NetworkManager` и поддержку со стороны драйвера.

```yaml
network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlan0:
      dhcp4: true
      access-points:
        "MyHomeWiFi":
          password: "my-secure-password"
          auth:
            key-management: sae # WPA3
```

### 6. Нативный Wireguard (v0.100+)

Создание туннеля напрямую через Netplan.

```yaml
network:
  version: 2
  tunnels:
    wg0:
      mode: wireguard
      key: <private_key_content>
      port: 51820
      addresses: [10.100.0.1/24]
      peers:
        - keys:
            public: <peer_public_key>
          endpoint: 1.2.3.4:51820
          allowed-ips: [10.100.0.0/24]
```

## Дополнительная информация

### Управление и диагностика

| Команда | Описание |
| :--- | :--- |
| `sudo netplan try` | Безопасное применение с автооткатом через 120 секунд. |
| `sudo netplan apply` | Немедленное применение конфигурации. |
| `sudo netplan --debug generate` | Проверка синтаксиса и генерация конфигов для бэкендов без их применения. |
| `netplan status` | Вывод сводки по интерфейсам, IP и маршрутам (v0.100+). |
| `journalctl -u systemd-networkd` | Логи бэкенда при использовании `renderer: networkd`. |
| `journalctl -u NetworkManager` | Логи бэкенда при использовании `renderer: NetworkManager`. |

### Типичные ошибки и решение

- **Ошибка отступов (YAML):** Netplan крайне чувствителен к пробелам. Используйте 2 или 4 пробела, табуляция (Tab) строго запрещена.
- **Конфликт бэкендов:** Если в системе запущены и `systemd-networkd`, и `NetworkManager`, они могут конфликтовать за управление интерфейсом. Убедитесь, что `renderer` выбран правильно для вашей роли (сервер/десктоп).
- **Отсутствие пакетов для WiFi/VPN:** Для работы WiFi (WPA3) требуется `wpasupplicant`, для Wireguard — `wireguard-tools`. Netplan лишь генерирует конфиги, но не заменяет сами инструменты.
- **Интерфейс не поднимается:** Проверьте вывод `netplan status` и убедитесь, что параметр `optional: true` не мешает ожиданию готовности сети другими службами.

### Особенности работы

- **Объединение файлов:** Если в `/etc/netplan/` несколько файлов, они объединяются лексикографически. Файл `99-custom.yaml` переопределит настройки из `01-netcfg.yaml`.
- **Взаимодействие с Cloud-Init:** Часто облачные провайдеры создают файл в `/etc/netplan/50-cloud-init.yaml`. Не редактируйте его напрямую; создайте файл с более высоким приоритетом (например, `90-local.yaml`).

### См. также

- **[systemd-networkd](./systemd_networkd.md)** — глубокая настройка основного бэкенда для серверов.
- **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — теория LACP и балансировки.
- **[Маршрутизация по политикам (PBR)](../../Policy_Based_Routing/index.md)** — подробный обзор таблиц и правил.
- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — взаимодействие Netplan с `systemd-resolved`.

