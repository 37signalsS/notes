# ISC DHCP-сервер: Настройка DHCP Relay

DHCP-запросы являются широковещательными и по умолчанию не выходят за пределы своей подсети (VLAN). Если DHCP-сервер находится в другой подсети, клиенты не смогут его обнаружить. Эту проблему решает **DHCP Relay Agent**.

## Принцип работы
1.  Маршрутизатор (или другой L3-устройство), имеющий интерфейсы в нескольких подсетях, настраивается как DHCP Relay.
2.  Получив широковещательный `DHCPDISCOVER` от клиента, Relay "заворачивает" его в unicast-пакет и пересылает на указанный IP-адрес реального DHCP-сервера.
3.  DHCP-сервер отправляет ответ обратно Relay-агенту, который, в свою очередь, пересылает его клиенту.

## Установка и настройка (RHEL/CentOS)

1.  **Установка пакета:**
    Пакет `dhcp-relay` является частью `dhcp-server`. Если `dhcp-server` уже установлен, relay доступен. В других системах может называться `isc-dhcp-relay`.
    ```bash
    sudo dnf install dhcp-server 
    ```

2.  **Настройка службы:**
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

3.  **Запуск службы:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start dhcrelay
    sudo systemctl enable dhcrelay
    ```
    После этого устройство начнет пересылать DHCP-запросы из всех подсетей, в которых у него есть активные интерфейсы.

---
*   **Далее:** [Проверка и мониторинг](./isc_dhcp_server_verification.md)
*   **Назад:** [Настройка Failover](./isc_dhcp_server_failover.md)
