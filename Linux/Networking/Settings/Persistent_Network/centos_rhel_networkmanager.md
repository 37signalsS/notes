# NetworkManager в RHEL/CentOS

**Reliability Score: 10 (SSoT + Web)**

**NetworkManager** — это динамическая система управления сетью, являющаяся стандартом в дистрибутивах семейства RHEL (Red Hat Enterprise Linux), включая CentOS Stream, AlmaLinux и Rocky Linux. Начиная с RHEL 9, NetworkManager стал единственным поддерживаемым инструментом, полностью вытеснив старые скрипты `ifcfg-rh`.

## Определения

- **NetworkManager** — демон, управляющий сетевыми интерфейсами и профилями соединений.
- **nmcli (Network Manager Command Line Interface)** — мощный инструмент командной строки для управления сетью.
- **Keyfile** — новый стандарт хранения конфигурации (`.nmconnection`), заменивший формат `ifcfg`.
- **VRF (Virtual Routing and Forwarding)** — технология создания изолированных таблиц маршрутизации на одном физическом хосте.
- **Nmstate** — декларативный API для управления сетью через YAML/JSON.

## Базовые концепции

NetworkManager разделяет **устройства** (физические/виртуальные адаптеры) и **соединения** (профили настроек). Одно устройство может иметь множество профилей (например, «Home», «Work», «Static»), но активно одновременно только одно.

### Хранение конфигурации (v1.20+)

| Версия | Формат хранения | Путь |
| :--- | :--- | :--- |
| **RHEL 9+** | **Keyfile (INI)** | `/etc/NetworkManager/system-connections/` |
| **RHEL 7/8** | **ifcfg (Shell)** | `/etc/sysconfig/network-scripts/` |

**Важно:** В RHEL 9 формат `ifcfg` объявлен **deprecated**. Для миграции существующих соединений в новый формат используйте команду:
```bash
sudo nmcli connection migrate
```

### Принципы работы
NetworkManager отслеживает изменения в реальном времени. Если вы редактируете файлы вручную (не рекомендуется), необходимо выполнить `nmcli connection reload`. Рекомендуется использовать `nmcli` или Ansible (RHEL System Roles) для обеспечения идемпотентности.

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

### 2. Настройка статического IP и DNS (RHEL 9+)

```bash
# Модификация существующего соединения
sudo nmcli connection modify 'eth0' \
    ipv4.method manual \
    ipv4.addresses 192.168.1.100/24 \
    ipv4.gateway 192.168.1.1 \
    ipv4.dns "1.1.1.1,8.8.8.8" \
    ipv4.dns-search "corp.internal" \
    connection.autoconnect yes

# Применение изменений
sudo nmcli connection up 'eth0'
```

### 3. Настройка агрегации каналов (Bonding)

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

### 4. Настройка VRF (Изоляция маршрутизации)

Используется для разделения трафика управления и трафика данных.

```bash
# Создание VRF с таблицей маршрутизации 100
sudo nmcli connection add type vrf ifname vrf100 con-name vrf100 table 100

# Привязка интерфейса к VRF
sudo nmcli connection modify 'eth1' connection.slave-type vrf connection.master vrf100

# Запуск команды внутри VRF
ip vrf exec vrf100 curl icanhazip.com
```

### 5. Интеграция с systemd-resolved

Чтобы NetworkManager корректно передавал настройки DNS в `systemd-resolved`, проверьте конфиг:

```ini
# /etc/NetworkManager/conf.d/10-dns-resolved.conf
[main]
dns=systemd-resolved
```

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
