# ISC DHCP-сервер: Настройка DHCP Relay

> **Важно:** ISC DHCP устарел. Для новых развертываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Утилита `dhcrelay` все еще используется.

DHCP-запросы являются широковещательными и по умолчанию не выходят за пределы своей подсети (VLAN). Если DHCP-сервер находится в другой подсети, клиенты не смогут его обнаружить. Эту проблему решает **DHCP Relay Agent**.

> **См. также:** [DHCP Relay Agent](../../../Networking/Protocols/dhcp.md#базовые-концепции) — концепция.

## Принцип работы

1. Маршрутизатор (или другой L3-устройство), имеющий интерфейсы в нескольких подсетях, настраивается как DHCP Relay.
2. Получив широковещательный `DHCPDISCOVER` от клиента, Relay "заворачивает" его в unicast-пакет и пересылает на указанный IP-адрес реального DHCP-сервера.
3. DHCP-сервер отправляет ответ обратно Relay-агенту, который, в свою очередь, пересылает его клиенту.

## Установка и настройка

### Debian/Ubuntu

1. **Установка пакета:**

    ```bash
    sudo apt update
    sudo apt install isc-dhcp-relay
    ```

2. **Настройка:**
    В Debian настройки DHCP Relay задаются в `/etc/default/isc-dhcp-relay`:

    ```bash
    sudo systemctl edit --full isc-dhcp-relay
    ```

    Можно отредактировать файл напрямую:

    ```ini
    SERVERS="10.0.4.4 10.0.4.5"
    INTERFACES="eth0 eth1"
    OPTIONS=""
    ```

3. **Запуск:**

    ```bash
    sudo systemctl start isc-dhcp-relay
    sudo systemctl enable isc-dhcp-relay
    ```

### RHEL/Rocky Linux/AlmaLinux

1. **Установка пакета:**
    Пакет `dhcp-relay` является частью `dhcp-server`.

    ```bash
    sudo dnf install dhcp-server 
    ```

2. **Настройка службы:**
    В systemd-юните службы `dhcrelay.service` нужно указать IP-адреса DHCP-серверов.

    ```bash
    sudo systemctl edit --full dhcrelay.service
    ```

    В секции `[Service]` найдите строку `ExecStart` и добавьте в конец IP-адреса ваших DHCP-серверов.

    Пример:

    ```ini
    [Service]
    ...
    ExecStart=/usr/sbin/dhcrelay -d --no-pid $DHCRELAY_ARGS 10.0.4.4 10.0.4.5
    ```

    Где `10.0.4.4` и `10.0.4.5` — адреса ваших отказоустойчивых DHCP-серверов.

3. **Запуск службы:**

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start dhcrelay
    sudo systemctl enable dhcrelay
    ```

    После этого устройство начнет пересылать DHCP-запросы из всех подсетей, в которых у него есть активные интерфейсы.

---

## Навигация по документации DHCP

| Тема | Файл |
| :--- | :--- |
| **[Обзор и архитектура](./isc_dhcp_server_overview.md)** | Точка входа, Kea DHCP |
| **[Базовая настройка](./isc_dhcp_server_basic_config.md)** | Установка, конфигурация |
| **[Резервирование IP](./isc_dhcp_server_reservations.md)** | Static allocation, маршруты |
| **[Failover](./isc_dhcp_server_failover.md)** | Отказоустойчивость |
| **[DHCP Relay](./isc_dhcp_server_relay.md)** | Ретрансляция между подсетями |
| **[Проверка и мониторинг](./isc_dhcp_server_verification.md)** | Верификация, логи |
| **[Протокол DHCP](../../../Networking/Protocols/dhcp.md)** | Теория, DORA, безопасность |
