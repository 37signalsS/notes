# NetworkManager в RHEL/CentOS

**NetworkManager** — это динамическая система управления сетью, являющаяся стандартом в дистрибутивах семейства RHEL (Red Hat Enterprise Linux), включая CentOS Stream, AlmaLinux и Rocky Linux. Начиная с RHEL 9, NetworkManager стал единственным поддерживаемым инструментом, полностью вытеснив устаревшие скрипты `network-scripts` (ifcfg).

## Определения

- **NetworkManager** — системная служба, управляющая сетевыми интерфейсами, профилями соединений и состоянием линков.
- **nmcli (Network Manager Command Line Interface)** — основной инструмент командной строки для императивного управления сетью.
- **nmtui (Network Manager Text User Interface)** — интерактивный текстовый интерфейс для базовой настройки.
- **Keyfile** — современный формат хранения конфигурации (`.nmconnection`), представляющий собой INI-подобный файл. В RHEL 9+ является форматом по умолчанию.
- **Nmstate** — декларативный API и библиотека для управления сетевыми настройками через YAML/JSON. Позволяет описывать "желаемое состояние" сети независимо от бэкенда.
- **NetworkManager-cloud-setup** — специализированный компонент для автоматической настройки вторичных IP-адресов и маршрутов в облачных окружениях (AWS, Azure, GCP).

## Базовые концепции

NetworkManager разделяет **устройства** (физические адаптеры) и **соединения** (профили настроек). Одно устройство может иметь множество профилей, но активно одновременно только одно соединение.

### Хранение конфигурации

| Версия | Формат хранения | Директория |
| :--- | :--- | :--- |
| **RHEL 9+** | **Keyfile** | `/etc/NetworkManager/system-connections/` |
| **RHEL 7/8** | **ifcfg** | `/etc/sysconfig/network-scripts/` |

**Важно:** В RHEL 9 формат `ifcfg` объявлен устаревшим (**deprecated**). Для миграции существующих соединений в современный формат используйте команду:
```bash
sudo nmcli connection migrate
```

### Декларативное управление (Nmstate)

Nmstate позволяет избежать выполнения множества команд `nmcli`. Вместо этого администратор создает YAML-файл с описанием всей сетевой топологии. Это идеальный подход для автоматизации через Ansible или Terraform.
Пример проверки текущего состояния через Nmstate:
```bash
nmstatectl show eth0
```

## Практические сценарии

### 1. Базовое управление (nmcli)

```bash
# Состояние всех устройств (кратко)
nmcli device status

# Полная информация о конкретном интерфейсе
nmcli device show eth0

# Список всех профилей соединений
nmcli connection show
```

### 2. Настройка статического IP и DNS (IPv4 и IPv6)

Для RHEL 9+ рекомендуется явно указывать параметры для обоих стеков.

```bash
# Настройка IPv4
sudo nmcli connection modify 'eth0' \
    ipv4.method manual \
    ipv4.addresses 192.168.1.100/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "1.1.1.1,8.8.8.8"

# Настройка IPv6 (SLAAC + Static)
sudo nmcli connection modify 'eth0' \
    ipv6.method auto \
    ipv6.addresses "2001:db8::100/64"

# Применение изменений
sudo nmcli connection up 'eth0'
```

### 3. Декларативная настройка через Nmstate (Bridge)

Пример YAML-файла (`bridge.yaml`) для создания сетевого моста:

```yaml
interfaces:
  - name: br0
    type: linux-bridge
    state: up
    ipv4:
      enabled: true
      address:
        - ip: 192.168.100.1
          prefix-length: 24
      dhcp: false
    bridge:
      port:
        - name: eth1
```
Применение: `sudo nmstatectl apply bridge.yaml`

### 4. Настройка агрегации каналов (Bonding)

> **Внимание:** Технология **Teaming** (`teamd`) признана устаревшей в RHEL 9 и удалена в RHEL 10. Всегда используйте **Bonding**.

```bash
# 1. Создание мастер-интерфейса (LACP)
sudo nmcli connection add type bond con-name bond0 ifname bond0 mode 802.3ad

# 2. Добавление портов (slaves)
sudo nmcli connection add type ethernet con-name bond0-port1 ifname eth1 master bond0
sudo nmcli connection add type ethernet con-name bond0-port2 ifname eth2 master bond0

# 3. Настройка IP и запуск
sudo nmcli connection modify bond0 ipv4.addresses 10.0.0.10/24 ipv4.method manual
sudo nmcli connection up bond0
```

### 5. Настройка VRF (Изоляция маршрутизации)

Используется для разделения трафика управления и трафика данных.

```bash
# Создание VRF с таблицей маршрутизации 100
sudo nmcli connection add type vrf ifname vrf100 con-name vrf100 table 100

# Привязка интерфейса к VRF
sudo nmcli connection modify 'eth1' connection.slave-type vrf connection.master vrf100

# Запуск команды внутри VRF
ip vrf exec vrf100 curl icanhazip.com
```

### 6. Маршрутизация на основе политик (PBR)

Добавление правил маршрутизации через `nmcli` (сохраняется в профиле соединения).

```bash
# Создание таблицы маршрутизации 200 для трафика из специфической подсети
sudo nmcli connection modify 'eth0' \
    +ipv4.routing-rules "from 172.16.1.0/24 table 200" \
    +ipv4.routes "0.0.0.0/0 172.16.1.254 table 200"

sudo nmcli connection up 'eth0'
```

### 7. Облачные настройки (NM-cloud-setup)

В публичных облаках (AWS, Azure) NetworkManager может автоматически настраивать вторичные интерфейсы:
```bash
# Включение автоматической настройки для всех интерфейсов
sudo systemctl enable --now nm-cloud-setup.service
sudo systemctl enable --now nm-cloud-setup.timer
```

### 8. Интеграция с systemd-resolved

Чтобы NetworkManager корректно передавал настройки DNS в `systemd-resolved`, проверьте конфиг:

```ini
# /etc/NetworkManager/conf.d/10-dns-resolved.conf
[main]
dns=systemd-resolved
```

### 9. Использование скриптов-диспетчеров

Dispatcher-скрипты позволяют выполнять действия при смене статуса интерфейса.

Пример скрипта (`/etc/NetworkManager/dispatcher.d/99-custom-log`):
```bash
#!/bin/bash
INTERFACE=$1
ACTION=$2

logger "NetworkManager: Interface $INTERFACE is $ACTION"
```
Не забудьте установить права: `sudo chmod +x /etc/NetworkManager/dispatcher.d/99-custom-log`

## Дополнительная информация

### Диагностика и отладка

| Задача | Команда |
| :--- | :--- |
| Проверка примененных настроек | `nmcli -f all connection show eth0` |
| Логирование в реальном времени | `journalctl -u NetworkManager -f` |
| Включение Debug-режима | `nmcli general logging level DEBUG` |
| Проверка скриптов-диспетчеров | `ls /etc/NetworkManager/dispatcher.d/` |

### См. также

- **[Постоянная настройка сети](./index.md)** — сравнение с Netplan и networkd.
- **[Настройка DNS-клиента](../../Concepts/dns_client.md)** — подробнее о резолверах.
- **[Link Aggregation (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — глубокое погружение в режимы бондинга.
- **[iproute2: Обзор](../../Tools/iproute2/overview.md)** — утилиты для проверки текущего состояния ядра.
