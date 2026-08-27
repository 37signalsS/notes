# ISC DHCP — проверка, мониторинг и диагностика

> **Важно:** Программный стек ISC DHCP официально достиг стадии **EOL (End of Life)**. Для новых инсталляций в 2026 году **настоятельно рекомендуется** использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**, где мониторинг реализован через нативный REST API и экспорт метрик в Prometheus.

---

## Определения

**Проверка конфигурации (dhcpd -t)** — процесс статической валидации синтаксиса файла `dhcpd.conf`. Позволяет обнаружить ошибки (пропущенные точки с запятой, незакрытые скобки) до того, как они приведут к падению сервиса при перезагрузке.

**Файл аренды (dhcpd.leases)** — основной артефакт состояния сервера. Это текстовая база данных, в которой сервер фиксирует каждое назначение IP-адреса, время начала и окончания аренды, а также идентификаторы клиентов.

**omshell (Object Management Shell)** — интерактивная консоль для взаимодействия с работающим сервером через протокол **OMAPI**. Позволяет просматривать и изменять объекты (leases, hosts, groups) в оперативной памяти демона.

---

## Основные концепции

### Ключевые системные артефакты

| Артефакт | Debian / Ubuntu | RHEL / Rocky / Alma |
| :--- | :--- | :--- |
| **Lease-файл** | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/dhcpd/dhcpd.leases` |
| **Имя службы** | `isc-dhcp-server` | `dhcpd` |
| **Журналы** | `journalctl -u isc-dhcp-server` | `journalctl -u dhcpd` |

### Интерпретация системных журналов

Основные события, фиксируемые сервером:
- **DORA-процесс:** Последовательность `DHCPDISCOVER`, `DHCPOFFER`, `DHCPREQUEST`, `DHCPACK`. Разрыв цепочки указывает на конкретный этап проблемы (например, отсутствие ACK часто означает конфликт IP).
- **DHCPDECLINE:** Клиент обнаружил, что предложенный IP уже занят (через ARP-запрос). Сервер помечает адрес как `abandoned`.
- **DHCPINFORM:** Клиент уже имеет статический IP, но запрашивает дополнительные опции (DNS, NTP).

---

## Практические сценарии

### Глубокий анализ файла аренды

Файл аренды дополняется новыми записями в конец. Пример детальной записи:

```text
lease 10.0.10.25 {
  starts 1 2026/07/20 12:00:00; # Формат: <день_недели> <дата> <время>
  ends 2 2026/07/21 12:00:00;
  cltt 1 2026/07/20 11:55:00;   # Client Last Transaction Time
  binding state active;         # Состояние: active, free, backup, abandoned
  next binding state free;
  hardware ethernet 00:50:56:b1:22:33;
  uid "\001\000PV\261\"3";      # Client Identifier (RFC 2132)
  client-hostname "srv-db-01";
}
```

### Диагностика через tcpdump

Для отладки в сегментированных сетях (через Relay) используйте расширенные фильтры:

```bash
# Просмотр DHCP трафика с детализацией полей (включая giaddr и опции)
sudo tcpdump -i any port 67 or port 68 -vv -n
# → DHCP-DISCOVER from 00:11... via 10.0.1.1 (giaddr)

# Фильтрация только ответов сервера (Offers/Acks)
sudo tcpdump -i eth0 udp port 67 -n
```

### Управление через omshell

Требует наличия настроенного порта OMAPI и ключа в `dhcpd.conf`.

```bash
omshell
> server localhost
> port 7911
> key omapi-key "base64_secret"
> connect
# Просмотр конкретной аренды
> new lease
> set ip-address = 10.0.10.25
> open
# → obj: lease ... binding-state = 00:00:00:01 (active)
```

---

## Устранение неполадок

### Статус «Abandoned» (Заброшенные адреса)

Если сервер получает `DHCPDECLINE`, IP-адрес помечается как `abandoned` и не выдается другим клиентам в течение `abandoned-lease-time` (по умолчанию — время аренды).

**Действия:**
1.  Выясните, кто занимает адрес (через `arping <IP>`).
2.  Если конфликт разрешен, можно очистить состояние через `omshell` или удалением записи из `dhcpd.leases` (при выключенном сервере).

### Клиент не получает адрес (Checklist)

1.  **Синтаксис:** `dhcpd -t -cf /etc/dhcp/dhcpd.conf` (# → success).
2.  **Сетевая связность:** Проверьте, доходят ли DISCOVER пакеты (`tcpdump`). Если нет — проблема в **DHCP Relay** или настройках **VLAN**.
3.  **Исчерпание пула:** `grep "no free leases" /var/log/syslog`. Проверьте размеры диапазонов `range` в подсетях.
4.  **Права на файл аренды:** Убедитесь, что пользователь `dhcpd` может писать в `/var/lib/dhcp/`.

---

## Диагностика Kea DHCP (для сравнения)

При переходе с ISC DHCP на Kea ключевые команды отличаются:

```bash
# Проверка синтаксиса Kea
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf

# Статус сервиса Kea
systemctl status kea-dhcp4 kea-ctrl-agent

# Просмотр логов Kea (включая DEBUG)
journalctl -u kea-dhcp4 -f | grep -E "ALLOC|SUBNET|CLASS|DROP"

# REST API Kea: все аренды
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get-all"}' | jq '.arguments.leases | length'

# REST API Kea: поиск по MAC
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "lease4-get-by-hw-address", "args": {"hw-address": "00:50:56:b1:22:33"}}' | jq

# REST API Kea: статистика по подсети
curl -s -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"command": "statistic-get", "args": {"name": "subnet[1].assigned-addresses"}}' | jq

# Kea: конфигурация логирования (временный DEBUG)
# В kea-dhcp4.conf:
# "loggers": [{"name": "kea-dhcp4", "severity": "DEBUG", "debuglevel": 99}]
# После отладки: вернуть severity "INFO"
```

### Сравнение: ISC vs Kea Diagnostic Commands

| Задача | ISC DHCP | Kea DHCP |
| :--- | :--- | :--- |
| **Проверка конфига** | `dhcpd -t -cf /etc/dhcp/dhcpd.conf` | `kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf` |
| **Просмотр аренд** | `cat /var/lib/dhcp/dhcpd.leases` | `curl localhost:8000/ (REST API)` |
| **Поиск по MAC** | `grep "00:50:56:b1:22:33" dhcpd.leases` | REST API `lease4-get-by-hw-address` |
| **Статистика** | `grep -c "binding state active" dhcpd.leases` | REST API `statistic-get` |
| **Debug-режим** | `dhcpd -d -f` (foreground) | `kea-dhcp4.conf: severity=DEBUG` |
| **Перезагрузка конфига** | `systemctl restart isc-dhcp-server` | REST API `config-reload` (без перезапуска!) |
| **Abandoned** | `grep "abandoned" dhcpd.leases` | REST API `lease4-get` (state field) |
| **Failover статус** | `journalctl -u isc-dhcp-server \| grep failover` | REST API `statistic-get` (ha-state) |

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **Валидация перед перезапуском:** Никогда не делайте `systemctl restart` без предварительного `dhcpd -t` (ISC) или `kea-dhcp4 -t` (Kea). Одна ошибка в конфигурации остановит выдачу адресов во всей сети.
- **Мониторинг:** Рекомендуется использовать внешний скрипт-экспортер (например, `dhcpd-leases-exporter` для ISC или `kea-exporter` для Kea) для визуализации заполнения пулов в **Grafana**.

### Связанные разделы

- **[Обзор архитектуры ISC DHCP](./isc_dhcp_server_overview.md)** — компоненты и жизненный цикл.
- **[Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура и опции `dhcpd.conf`.
- **[Настройка Failover](./isc_dhcp_server_failover.md)** — диагностика состояния синхронизации.
- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор Kea DHCP.
- **[Диагностика DHCP — Теория](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — глубокий разбор заголовков и DORA.
- **[Мониторинг и наблюдаемость DHCP](../../../../Networking/Protocols/DHCP/dhcp_monitoring_observability.md)** — Prometheus, Grafana, SIEM.
