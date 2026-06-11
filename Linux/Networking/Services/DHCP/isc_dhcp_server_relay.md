# ISC DHCP Relay — настройка утилиты dhcrelay

> **Важно:** ISC DHCP устарел. Для новых развёртываний рекомендуется использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Утилита `dhcrelay` всё ещё поддерживается для существующих инфраструктур.

## Определения

**DHCP Relay Agent** — компонент (обычно на маршрутизаторе или Linux-хосте), который пересылает DHCP-запросы между подсетями, преобразуя broadcast в unicast.

**dhcrelay** — специализированная утилита из состава пакета ISC DHCP для выполнения функций ретранслятора в ОС Linux.

> **Основной документ:** [Концепция DHCP Relay](../../../../Networking/Protocols/DHCP/dhcp_relay.md) — принцип работы, поля `giaddr`/`hops`, RFC.

## Основные концепции

### Назначение в Linux

В Linux-системах `dhcrelay` используется для организации централизованной DHCP-инфраструктуры, когда один сервер обслуживает несколько VLAN или удалённых подсетей. Это позволяет избежать развёртывания DHCP-сервера в каждом широковещательном сегменте.

**Ключевые особенности:**

- Работает как посредник между клиентами и удалённым сервером.
- Использует интерфейсы, подключённые к клиентским подсетям и к подсети сервера.
- Позволяет Linux-маршрутизатору заменять аппаратные решения (например, Cisco `ip helper-address`).

## Практические сценарии

### Debian / Ubuntu

1. **Установка:**

    ```bash
    sudo apt update
    sudo apt install isc-dhcp-relay
    ```

2. **Настройка** (`/etc/default/isc-dhcp-relay`):

    ```ini
    SERVERS="10.0.4.4 10.0.4.5"
    INTERFACES="eth0 eth1"
    OPTIONS=""
    ```

    Либо через переопределение systemd:

    ```bash
    sudo systemctl edit --full isc-dhcp-relay
    ```

3. **Запуск:**

    ```bash
    sudo systemctl start isc-dhcp-relay
    sudo systemctl enable isc-dhcp-relay
    ```

### RHEL / Rocky Linux / AlmaLinux

1. **Установка:**

    ```bash
    sudo dnf install dhcp-server
    ```

2. **Настройка** — редактирование systemd-юнита `dhcrelay.service`:

    ```bash
    sudo systemctl edit --full dhcrelay.service
    ```

    В секции `[Service]` изменить `ExecStart`:

    ```ini
    [Service]
    ...
    ExecStart=/usr/sbin/dhcrelay -d --no-pid $DHCRELAY_ARGS 10.0.4.4 10.0.4.5
    ```

3. **Запуск:**

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start dhcrelay
    sudo systemctl enable dhcrelay
    ```

## Дополнительная информация

### Диагностика

- `journalctl -u isc-dhcp-relay -f` — логи Relay на Debian/Ubuntu.
- `journalctl -u dhcrelay -f` — логи на RHEL-подобных системах.
- `tcpdump -i eth0 port 67 or port 68` — проверка прохождения DHCP-пакетов.

### Связанные документы

- [Концепция DHCP Relay Agent](../../../../Networking/Protocols/DHCP/dhcp_relay.md)
- [Обзор ISC DHCP](./isc_dhcp_server_overview.md)
- [Базовая настройка ISC DHCP](./isc_dhcp_server_basic_config.md)
- [Настройка Failover](./isc_dhcp_server_failover.md)
