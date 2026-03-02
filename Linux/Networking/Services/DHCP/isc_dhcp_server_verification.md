# ISC DHCP-сервер: Проверка и мониторинг

## 1. Проверка и запуск службы

1.  **Проверка синтаксиса конфигурации:**
    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
    ```
    *Если команда не найдена, может потребоваться `isc-dhcp-server -t`*

2.  **Запуск/перезапуск и добавление в автозагрузку:**
    ```bash
    # Для systemd (современные дистрибутивы)
    sudo systemctl restart isc-dhcp-server  # или dhcpd
    sudo systemctl enable isc-dhcp-server   # или dhcpd
    ```

## 2. Верификация и мониторинг

### На сервере

-   **Проверка статуса службы:**
    ```bash
    systemctl status isc-dhcp-server  # или dhcpd
    ```

-   **Просмотр логов:**
    -   В логах failover-пары ищите сообщения `balanced` или `normal`, подтверждающие успешную синхронизацию.
    -   Через `journalctl`:
        ```bash
        sudo journalctl -u isc-dhcp-server -f
        ```
    -   Логи могут также писаться в `/var/log/syslog` или `/var/log/messages`, в зависимости от настроек `rsyslog` и `log-facility` в `dhcpd.conf`. Вы увидите 4 сообщения DORA для каждого клиента.

-   **Просмотр выданных аренд:**
    ```bash
    cat /var/lib/dhcpd/dhcpd.leases
    ```
    В файле будет информация о выданном IP, MAC-адресе клиента, времени начала и окончания аренды.

### На клиенте (Linux)

1.  **Проверка полученного IP:**
    ```bash
    ip addr show eth0
    ```
    Найдите `inet` адрес и убедитесь, что он из правильного диапазона. Пометка `dynamic` подтверждает получение по DHCP.

2.  **Проверка шлюза и статичных маршрутов:**
    ```bash
    ip route
    ```
    Вы должны увидеть `default via <IP-шлюза>` и другие маршруты, если они были переданы сервером.

3.  **Проверка DNS-серверов:**
    ```bash
    cat /etc/resolv.conf
    ```
    Файл должен содержать адреса DNS-серверов, указанные в `dhcpd.conf`.

4.  **Просмотр деталей аренды (через NetworkManager):**
    ```bash
    nmcli device show eth0 | grep IP4
    ```
---
*   **Назад:** [Настройка DHCP Relay](./isc_dhcp_server_relay.md)
*   **В начало:** [Обзор ISC DHCP](./isc_dhcp_server_overview.md)
