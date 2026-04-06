# ISC DHCP Relay — настройка утилиты `dhcrelay`

> **Важно:** ISC DHCP устарел. Для новых развертываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Утилита `dhcrelay` всё ещё поддерживается.

## Definitions

**DHCP Relay Agent** — компонент (обычно на маршрутизаторе или Linux-хосте), который пересылает DHCP-запросы между подсетями, преобразуя broadcast в unicast.

**Проблема:** DHCP-запросы (`DHCPDISCOVER`) являются широковещательными и не выходят за пределы своей подсети. Если DHCP-сервер расположен в другой подсети, клиенты не смогут его обнаружить без Relay Agent.

> **Концепция:** [DHCP Relay Agent](../../../../Networking/Protocols/DHCP/dhcp_relay.md) — принцип работы, поля `giaddr`/`hops`, RFC.

## Basic Concepts

### Принцип работы

1. Клиент отправляет broadcast `DHCPDISCOVER`.
2. Relay Agent перехватывает запрос, добавляет `giaddr` (IP шлюза), увеличивает `hops`.
3. Relay пересылает запрос через unicast на указанный DHCP-сервер.
4. DHCP-сервер определяет подсеть клиента по `giaddr`, подбирает IP из пула и возвращает ответ.
5. Relay доставляет ответ (`DHCPOFFER`/`DHCPACK`) клиенту.

### Когда использовать

- Центральная DHCP-инфраструктура для множества VLAN/подсетей.
- Отказ от развёртывания DHCP-сервера в каждой подсети.
- Linux-маршрутизатор как альтернатива аппаратным решениям (Cisco `ip helper-address`).

## Practical Scenarios

### Debian/Ubuntu

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

    Либо через systemd-override:

    ```bash
    sudo systemctl edit --full isc-dhcp-relay
    ```

3. **Запуск:**

    ```bash
    sudo systemctl start isc-dhcp-relay
    sudo systemctl enable isc-dhcp-relay
    ```

### RHEL/Rocky Linux/AlmaLinux

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

## Additional Information

### Диагностика

- `journalctl -u isc-dhcp-relay -f` — логи Relay на Debian/Ubuntu.
- `journalctl -u dhcrelay -f` — логи на RHEL-подобных системах.
- `tcpdump -i eth0 port 67 or port 68` — проверка прохождения DHCP-запросов.

### Связанные документы

- Концепция: [DHCP Relay Agent](../../../../Networking/Protocols/DHCP/dhcp_relay.md)
- Обзор ISC DHCP: [isc_dhcp_server_overview.md](./isc_dhcp_server_overview.md)
- Базовая настройка: [isc_dhcp_server_basic_config.md](./isc_dhcp_server_basic_config.md)
- Failover: [isc_dhcp_server_failover.md](./isc_dhcp_server_failover.md)
