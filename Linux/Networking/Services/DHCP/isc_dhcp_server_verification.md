# ISC DHCP — проверка, мониторинг и troubleshooting

> **Важно:** ISC DHCP устарел. Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Мониторинг Kea — через JSON/CTRL-agent.

## Definitions

**Config validation (`dhcpd -t`)** — проверка синтаксиса `dhcpd.conf` без запуска службы. Обязательный шаг перед каждым перезапуском.

**Lease file (`dhcpd.leases`)** — файл состояния, хранящий текущие и истёкшие аренды. Используется сервером для восстановления состояния после перезагрузки.

> **Смежные темы:** [Анализ DHCP-трафика и troubleshooting](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md) — Wireshark, освобождение/обновление аренды, authoritative-режим.

## Basic Concepts

### Ключевые артефакты

| Артефакт | Debian/Ubuntu | RHEL/Rocky/Alma |
|----------|---------------|-----------------|
| Lease-файл | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/dhcpd/dhcpd.leases` |
| Имя службы | `isc-dhcp-server` | `dhcpd` |
| Логи | `/var/log/syslog` | `/var/log/messages` |

### Что искать в логах

- **DORA-последовательность** — 4 сообщения на каждого клиента (Discover → Offer → Request → Ack).
- **Failover-статус** — сообщения `balanced` или `normal` подтверждают синхронизацию пары.
- **Ошибки парсинга** — `Bad keyword`, `unexpected end of file` — проблема в `dhcpd.conf`.
- **IP-конфликты** — `DHCPDECLINE` от клиента, сервер помечает адрес как конфликтный.

## Practical Scenarios

### Проверка и запуск службы

1. **Валидация конфигурации:**

    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
    ```

    Флаг `-lf` позволяет указать lease-файл явно (полезно при отладке):

    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf -lf /var/lib/dhcp/dhcpd.leases 2>&1 | less
    ```

2. **Перезапуск службы:**

    ```bash
    # Debian/Ubuntu
    sudo systemctl restart isc-dhcp-server
    sudo systemctl enable isc-dhcp-server

    # RHEL/Rocky/Alma
    sudo systemctl restart dhcpd
    sudo systemctl enable dhcpd
    ```

### Мониторинг

**Статус службы:**

```bash
systemctl status isc-dhcp-server   # или dhcpd
```

**Логи в реальном времени:**

```bash
sudo journalctl -u isc-dhcp-server -f   # или -u dhcpd
```

**Просмотр текущих аренд:**

```bash
cat /var/lib/dhcp/dhcpd.leases     # Debian
cat /var/lib/dhcpd/dhcpd.leases    # RHEL
```

Формат записи:

```
lease 10.0.10.5 {
  starts 1 2026/04/06 10:00:00;
  ends 2 2026/04/07 10:00:00;
  hardware ethernet 08:00:27:1A:2B:3C;
  client-hostname "fileserver";
}
```

### Диагностика на клиенте (Linux)

```bash
# Полученный IP
ip addr show eth0

# Маршруты (шлюз, статические маршруты)
ip route

# DNS-серверы
cat /etc/resolv.conf

# Детали через NetworkManager
nmcli device show eth0 | grep IP4
```

### Troubleshooting

**Клиент не получает IP:**

```bash
# Проверка UDP 67 на сервере
nc -uvz <dhcp-server> 67

# Логи NetworkManager на клиенте
sudo journalctl -u NetworkManager -f

# Ручной запуск dhclient с отладкой
sudo dhclient -v eth0
```

- Убедиться, что клиент и сервер в одной подсети, либо настроен [DHCP Relay](./isc_dhcp_server_relay.md).

**IP-конфликты:**

```bash
# Поиск активных аренд
grep -A 5 "^lease" /var/lib/dhcp/dhcpd.leases

# Поиск дубликатов MAC
grep "hardware ethernet" /var/lib/dhcp/dhcpd.leases
```

## Additional Information

### Примечания

- Перед каждым перезапуском запускайте `dhcpd -t` — сервер откажется стартовать с невалидным конфигом.
- Lease-файл не удаляйте вручную — сервер потеряет состояние активных арен. Для сброса используйте корректную процедуру: остановить службу → переименовать lease → запустить.
- Опция `authoritative;` в `dhcpd.conf` заставляет сервер отправлять `DHCPNAK` клиентам с некорректными IP из чужих подсетей (подробнее — [dhcp_analysis_troubleshooting.md](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md#авторитативный-и-неавторитативный-dhcp-сервер)).

### Связанные документы

- Анализ и Wireshark: [dhcp_analysis_troubleshooting.md](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)
- Обзор ISC DHCP: [isc_dhcp_server_overview.md](./isc_dhcp_server_overview.md)
- Базовая настройка: [isc_dhcp_server_basic_config.md](./isc_dhcp_server_basic_config.md)
- Failover: [isc_dhcp_server_failover.md](./isc_dhcp_server_failover.md)
- DHCP Relay: [isc_dhcp_server_relay.md](./isc_dhcp_server_relay.md)
