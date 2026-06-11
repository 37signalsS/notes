# ISC DHCP — проверка, мониторинг и диагностика

> **Важно:** ISC (Internet Systems Consortium) DHCP устарел. Для новых развёртываний используйте **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**. Мониторинг Kea осуществляется через **JSON (JavaScript Object Notation)** и специализированный агент управления.

## Определения

**Проверка конфигурации (dhcpd -t)** — процесс валидации синтаксиса основного файла конфигурации `dhcpd.conf` без фактического запуска службы. Является обязательным шагом перед каждым перезапуском сервера.

**Файл аренды (dhcpd.leases)** — файл состояния, в котором **DHCP-сервер (Dynamic Host Configuration Protocol)** хранит информацию о текущих и истёкших арендах **IP-адресов (Internet Protocol)**. Используется сервером для восстановления состояния после перезагрузки.

> **Смежные темы:** [Анализ DHCP-трафика и диагностика](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md) — использование Wireshark, механизм продления аренды и авторитативный режим.

## Основные концепции

### Ключевые артефакты

| Артефакт | Debian/Ubuntu | RHEL (Red Hat Enterprise Linux) |
| :--- | :--- | :--- |
| **Lease-файл** | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/dhcpd/dhcpd.leases` |
| **Имя службы** | `isc-dhcp-server` | `dhcpd` |
| **Логи** | `/var/log/syslog` | `/var/log/messages` |

### Что искать в логах

- **Последовательность DORA** — четыре сообщения на каждого клиента: **Discover** (обнаружение), **Offer** (предложение), **Request** (запрос), **Ack** (подтверждение).
- **Статус Failover** — сообщения `balanced` или `normal` подтверждают корректную синхронизацию пары серверов.
- **Ошибки парсинга** — сообщения `Bad keyword` или `unexpected end of file` указывают на синтаксические ошибки в `dhcpd.conf`.
- **IP-конфликты** — получение сообщения `DHCPDECLINE` от клиента означает, что выданный адрес уже занят; сервер пометит его как конфликтный.

## Практические сценарии

### Проверка и запуск службы

1. **Валидация конфигурации:**

    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
    ```

    Использование флага `-lf` позволяет явно указать файл аренды (полезно при отладке):

    ```bash
    sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf -lf /var/lib/dhcp/dhcpd.leases 2>&1 | less
    ```

2. **Управление службой:**

    ```bash
    # Debian/Ubuntu
    sudo systemctl restart isc-dhcp-server
    sudo systemctl enable isc-dhcp-server

    # RHEL/Rocky Linux/AlmaLinux
    sudo systemctl restart dhcpd
    sudo systemctl enable dhcpd
    ```

### Мониторинг состояния

**Статус службы:**

```bash
systemctl status isc-dhcp-server   # или dhcpd для RHEL
```

**Логи в реальном времени:**

```bash
sudo journalctl -u isc-dhcp-server -f   # или -u dhcpd
```

**Просмотр текущих аренд:**

```bash
cat /var/lib/dhcp/dhcpd.leases     # Для Debian/Ubuntu
```

Пример записи в файле:

```text
lease 10.0.10.5 {
  starts 1 2026/04/06 10:00:00;
  ends 2 2026/04/07 10:00:00;
  hardware ethernet 08:00:27:1A:2B:3C;
  client-hostname "fileserver";
}
```

### Диагностика на стороне клиента (Linux)

Для проверки полученных параметров используйте стандартные сетевые инструменты:

```bash
# Проверка полученного IP-адреса
ip addr show eth0

# Проверка таблицы маршрутизации (шлюз по умолчанию)
ip route

# Проверка DNS-серверов
cat /etc/resolv.conf
```

### Устранение неполадок (Troubleshooting)

**Клиент не получает IP-адрес:**

1. Проверьте доступность порта **UDP (User Datagram Protocol)** 67 на сервере:

   ```bash
   nc -uvz <dhcp-server-ip> 67
   ```

2. Убедитесь, что клиент и сервер находятся в одной подсети, либо настроен **[DHCP Relay](./isc_dhcp_server_relay.md)**.
3. Проверьте наличие свободных адресов в пуле (диапазоне `range`) внутри `dhcpd.conf`.

## Дополнительная информация

### Примечания по эксплуатации

- Перед каждым перезапуском службы **обязательно** запускайте `dhcpd -t`. Сервер может не запуститься, если в конфигурации допущена ошибка.
- Не удаляйте файл аренды вручную. Это приведёт к потере сервером информации об активных клиентах и может вызвать конфликты IP-адресов при перевыдаче уже занятых адресов.
- Опция `authoritative;` заставляет сервер активно «исправлять» клиентов с неверными адресами, отправляя им `DHCPNAK`. Подробнее см. в [диагностике DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md).

### См. также

- [Обзор ISC DHCP](./isc_dhcp_server_overview.md) — архитектура и сравнение с Kea.
- [Диагностика и анализ трафика DHCP](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md) — общие методы и Wireshark.
- [Базовая настройка ISC DHCP](./isc_dhcp_server_basic_config.md) — структура конфигурационных файлов.
