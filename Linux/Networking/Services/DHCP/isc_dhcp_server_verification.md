# ISC DHCP-сервер: Проверка и мониторинг

> **Важно:** ISC DHCP устарел. Для новых развертываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Мониторинг через JSON/CTRL-agent.

## 1. Проверка и запуск службы

1. **Проверка синтаксиса конфигурации:**

    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
    ```

    *Если команда не найдена, может потребоваться `isc-dhcp-server -t`*

2. **Запуск/перезапуск и добавление в автозагрузку:**

    ```bash
    # Для systemd (современные дистрибутивы)
    sudo systemctl restart isc-dhcp-server  # или dhcpd
    sudo systemctl enable isc-dhcp-server   # или dhcpd
    ```

## 2. Верификация и мониторинг

### На сервере

- **Проверка статуса службы:**

    ```bash
    systemctl status isc-dhcp-server  # или dhcpd
    ```

- **Просмотр логов:**
  - В логах failover-пары ищите сообщения `balanced` или `normal`, подтверждающие успешную синхронизацию.
  - Через `journalctl`:

        ```bash
        sudo journalctl -u isc-dhcp-server -f
        ```

  - Логи могут также писаться в `/var/log/syslog` или `/var/log/messages`, в зависимости от настроек `rsyslog` и `log-facility` в `dhcpd.conf`. Вы увидите 4 сообщения DORA для каждого клиента.

- **Просмотр выданных аренд:**

    ```bash
    cat /var/lib/dhcpd/dhcpd.leases
    ```

    В файле будет информация о выданном IP, MAC-адресе клиента, времени начала и окончания аренды.

### На клиенте (Linux)

1. **Проверка полученного IP:**

    ```bash
    ip addr show eth0
    ```

    Найдите `inet` адрес и убедитесь, что он из правильного диапазона. Пометка `dynamic` подтверждает получение по DHCP.

2. **Проверка шлюза и статичных маршрутов:**

    ```bash
    ip route
    ```

    Вы должны увидеть `default via <IP-шлюза>` и другие маршруты, если они были переданы сервером.

3. **Проверка DNS-серверов:**

    ```bash
    cat /etc/resolv.conf
    ```

    Файл должен содержать адреса DNS-серверов, указанные в `dhcpd.conf`.

4. **Просмотр деталей аренды (через NetworkManager):**

    ```bash
    nmcli device show eth0 | grep IP4
    ```

## Troubleshooting

### Клиент не получает IP

1. **Проверка доступности сервера:**

```bash
# С сервера: проверка порта UDP/67
nc -uvz <dhcp-server> 67
```

1. **Проверка логов на клиенте:**

```bash
# Журнал NetworkManager
sudo journalctl -u NetworkManager -f

# Прямой запуск dhclient для отладки
sudo dhclient -v eth0
```

1. **Проверка широковещательного домена:**

- Убедитесь, что клиент и сервер в одной подсети
- Для разных подсетей проверьте настройку [DHCP Relay](./isc_dhcp_server_relay.md)

### Конфликты IP-адресов

```bash
# Проверка существующих аренд
cat /var/lib/dhcp/dhcpd.leases | grep -A 5 "lease"

# Поиск дубликатов MAC-адресов
grep "hardware ethernet" /var/lib/dhcp/dhcpd.leases
```

### Ошибки в конфигурации

```bash
# Детальная проверка синтаксиса
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf -lf /var/lib/dhcp/dhcpd.leases

# Проверка с выводом всех ошибок
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf 2>&1 | less
```

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
