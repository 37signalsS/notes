# ISC DHCP — проверка, мониторинг и диагностика

> **Важно:** Программный стек ISC DHCP официально достиг стадии **EOL (End of Life)**. Для новых инсталляций в 2026 году **настоятельно рекомендуется** использовать **[Kea DHCP](./isc_dhcp_server_overview.md#kea-dhcp-современная-альтернатива)**, где мониторинг реализован через нативный REST API и экспорт метрик в Prometheus.

---

## Определения

**Проверка конфигурации (dhcpd -t)** — процесс статической валидации синтаксиса файла `dhcpd.conf`. Позволяет обнаружить ошибки (пропущенные точки с запятой, незакрытые скобки) до того, как они приведут к падению сервиса при перезагрузке.

**Файл аренды (dhcpd.leases)** — основной артефакт состояния сервера. Это текстовая база данных, в которой сервер фиксирует каждое назначение IP-адреса, время начала и окончания аренды, а также идентификаторы клиентов.

**omshell (Object Management Shell)** — интерактивная консоль для взаимодействия с работающим сервером через протокол **OMAPI**. Позволяет просматривать и изменять объекты (leases, hosts, groups) в оперативной памяти демона.

**Authoritative режим** — поведение сервера, при котором он отправляет `DHCPNAK` в ответ на запросы клиентов к неверным или устаревшим IP-адресам из его пула. Без `authoritative;` сервер игнорирует такие запросы, что полезно при миграции между DHCP-серверами.

**Commit-before-ACK** — механизм гарантии целостности: перед отправкой `DHCPACK` клиенту сервер выполняет `fsync()` записи об аренде в `dhcpd.leases`. При внезапном сбое питания это предотвращает потерю данных, но создаёт нагрузку на диск.

**Abandoned-lease-time** — период, в течение которого адрес не выётся другим клиентам после получения `DHCPDECLINE`. По умолчанию равен `max-lease-time`.

---

## Основные концепции

### Ключевые системные артефакты

| Артефакт | Debian / Ubuntu | RHEL / Rocky / Alma |
| :--- | :--- | :--- |
| **Lease-файл** | `/var/lib/dhcp/dhcpd.leases` | `/var/lib/dhcpd/dhcpd.leases` |
| **Имя службы** | `isc-dhcp-server` | `dhcpd` |
| **Журналы** | `journalctl -u isc-dhcp-server` | `journalctl -u dhcpd` |

### Проверка состояния службы (Health Check)

Перед диагностикой убедитесь, что служба активна и слушает нужные порты:

```bash
# Статус systemd (Debian/Ubuntu)
systemctl status isc-dhcp-server

# Статус systemd (RHEL/Rocky)
systemctl status dhcpd

# Прослушиваемые порты: UDP 67/68, TCP 7911 (OMAPI), TCP 647 (failover)
ss -ulpn | grep -E ':67|:68|:7911|:647'

# Проверка рабочего процесса
pgrep -a dhcpd
# → 1234 /usr/sbin/dhcpd -q -cf /etc/dhcp/dhcpd.conf

# Ресурсы процесса
ps -p $(pgrep dhcpd) -o pid,rss,vsz,%cpu,%mem,cmd
```

Проверьте права на файл аренды: сервер должен иметь возможность записывать в него. Неверные права — частая причина тишины в логах.

```bash
ls -la /var/lib/dhcp/dhcpd.leases
# → -rw-r--r-- 1 dhcpd dhcpd ... /var/lib/dhcp/dhcpd.leases
```

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

### Аудит базы аренд

Для оперативного анализа используйте grep по текстовому файлу. Ключевые команды:

```bash
# Подсчёт записей по состояниям
grep -c "binding state active" /var/lib/dhcp/dhcpd.leases
grep -c "binding state free" /var/lib/dhcp/dhcpd.leases
grep -c "binding state abandoned" /var/lib/dhcp/dhcpd.leases
grep -c "binding state backup" /var/lib/dhcp/dhcpd.leases

# Поиск аренды по MAC
grep "00:11:22:33:44:55" /var/lib/dhcp/dhcpd.leases -A 8

# Проверка дублирования IP в active-арендах
awk '/^lease /{ip=$2} /binding state active/{print ip}' /var/lib/dhcp/dhcpd.leases | sort | uniq -d

# Проверка дублирования MAC в active-арендах
awk '/hardware ethernet /{mac=$3} /binding state active/{print mac}' /var/lib/dhcp/dhcpd.leases | sort | uniq -d

# Поиск старых аренд (старше 30 дней)
awk '/^lease /{ip=$2} /starts/{start=$0} /ends/ && $0 < "2026 08 13"' /var/lib/dhcp/dhcpd.leases
```

> **Важно:** `dhcpd.leases` — текстовый файл, дополняемый в конец. При сбое питания последняя запись может быть не завершена. Проверяйте целостность через `tail -5` перед анализом.

### Семантическая валидация конфигурации

Статическая проверка (`dhcpd -t`) обнаруживает синтаксические ошибки, но не семантические. Проверьте вручную:

```bash
# 1. Проверка синтаксиса (обязательно)
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf
# → Internet Systems Consortium DHCP Server v4.4.x
# → Compiled relationship files for....
# → success

# 2. Поиск потенциальных пересечений диапазонов
grep -E "^[[:space:]]*range" /etc/dhcp/dhcpd.conf

# 3. Проверка, что все подсети имеют маску
grep -E "^subnet" /etc/dhcp/dhcpd.conf

# 4. Проверка директивы authoritative
grep "authoritative" /etc/dhcp/dhcpd.conf

# 5. Проверка failover-консистентности (на Primary и Secondary)
diff <(grep -v "^#" /etc/dhcp/dhcpd.conf | grep -v "^$") \
     <(ssh dhcp-secondary "grep -v '^#' /etc/dhcp/dhcpd.conf | grep -v '^$'")

# 6. Проверка, что failover peer объявлен глобально
grep -E "^failover peer" /etc/dhcp/dhcpd.conf
```

Для проверки резервирований:

```bash
# Извлечение всех host declarations
grep -E "^host|fixed-address|hardware ethernet" /etc/dhcp/dhcpd.conf

# Проверка, что все fixed-address попадают в обслуживаемые подсети
# (требуется внешний скрипт для проверки вхождения IP в range)
```

### Верификация статических резервирований

После настройки `host` declarations проверьте, что сервер корректно их применяет:

```bash
# 1. Проверка синтаксиса
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf

# 2. Запрос от клиента (принудительный renew)
sudo dhclient -r eth0 && sudo dhclient -v eth0

# 3. Поиск в lease-файле после запроса
grep "00:11:22:33:44:55" /var/lib/dhcp/dhcpd.leases -A 8

# 4. Проверка, что адрес постоянный (binding state active, фиксированный IP)
# Если клиент получает другой адрес — проверьте Client-ID vs MAC:
grep "00:11:22:33:44:55" /var/log/syslog | grep DHCP
```

**Распространённая ошибка:** Клиент отправляет `Client Identifier` (UID), отличный от MAC-адреса. В этом случае `hardware ethernet` в `dhcpd.conf` не сработает. Используйте `ignore-client-uids true;` или укажите `uid` в блоке `host`.

### Диагностика через tcpdump

Для захвата и анализа DHCP-трафика используйте **[tcpdump — сетевой анализатор пакетов](../../../../Linux/Diagnostics/Networking/tcpdump.md)** с фильтрами по портам 67/68. Для DHCP-специфичных фильтров и анализа DORA/SARR процессов также обратитесь к **[Анализ DHCP-трафика](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)**.

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

### Проверка Failover-пары

```bash
# 1. Мониторинг логов в реальном времени
sudo journalctl -u isc-dhcp-server -f | grep -E "failover|partner"

# 2. Проверка TCP-соединения на порту 647
nc -zv 10.0.4.5 647
# → Connection succeeded

# 3. Проверка состояния через omshell
omshell <<EOF
server localhost
port 7911
key omapi-key "secret"
connect
new failover-state
open name="dhcp-failover"
EOF
# → local-state = 00:00:00:01 (normal)
# → partner-state = 00:00:00:01 (normal)

# 4. Проверка синхронизации конфигурации
diff /etc/dhcp/dhcpd.conf <(ssh dhcp-secondary "cat /etc/dhcp/dhcpd.conf")

# 5. Проверка, что резервирования совпадают на обоих узлах
diff <(grep "^host" /etc/dhcp/dhcpd.conf) <(ssh dhcp-secondary "grep '^host' /etc/dhcp/dhcpd.conf")

# 6. Проверка брандмауэра (failover-порт 647 только для партнёра)
iptables -L -n | grep 647
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

### DNS не обновляется (DDNS)

1.  Проверьте директиву `ddns-update-style` в `dhcpd.conf`.
2.  Проверьте логи: `grep -i "unable to add" /var/log/syslog`.
3.  Убедитесь, что сервер имеет права на запись в DNS-зону (TSIG-ключ, ACL в BIND).

### Failover не переходит в `normal`

1.  Проверьте разницу времени: `chronyc tracking` или `ntpq -p`. Разница > 60 сек остановит синхронизацию.
2.  Проверьте брандмауэр: порт TCP 647 должен быть открыт в обоих направлениях.
3.  Проверьте идентичность конфигураций: `diff /etc/dhcp/dhcpd.conf` между узлами.

### Pool exhaustion (исчерпание пула)

```bash
# Подсчёт active-аренд
grep -c "binding state active" /var/lib/dhcp/dhcpd.leases

# Логи с предупреждениями
journalctl -u isc-dhcp-server --since "1 hour ago" | grep "no free leases"
```

**Решение:** Увеличьте `range` в пуле или сократите `default-lease-time`.

### Медленный DORA (ответ сервера > 1 секунды)

1.  Проверьте I/O диска: `iostat -x 1 5`. Высокая `await` (> 20 мс) указывает на проблему с `fsync`.
2.  Проверьте сложность `class`-выражений в `dhcpd.conf`.
3.  Проверьте задержку в failover-канале: RTT > 100 мс требует увеличения `max-response-delay`.

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

### Процедура безопасного перезапуска (Failover-пара)

Для минимизации простоя в парах Failover используйте поочерёдный перезапуск (один узел остаётся обслуживать клиентов, пока второй обновляется):

```bash
# На Secondary (резервный узел):
sudo systemctl restart isc-dhcp-server

# Проверьте, что Secondary перешёл в normal
sudo journalctl -u isc-dhcp-server -f | grep failover

# На Primary (основной узел):
sudo systemctl restart isc-dhcp-server
```

Для принудительного привязывания к интерфейсу и предотвращения запуска на неправильном:

```bash
# systemd drop-in override (Debian/Ubuntu)
sudo systemctl edit isc-dhcp-server
# → [Service]
# → ExecStart=
# → ExecStart=/usr/sbin/dhcpd -q -cf /etc/dhcp/dhcpd.conf eth0
```

### Бэкап и восстановление lease-базы

Файл `dhcpd.leases` является критически важным артефактом состояния. Без него все клиенты получат новые адреса после перезапуска.

```bash
# Создание бэкапа (во время работы сервера)
sudo cp /var/lib/dhcp/dhcpd.leases /backup/dhcpd.leases.$(date +%Y%m%d_%H%M%S)

# Проверка целостности: последняя запись должна заканчиваться на '}'
tail -5 /var/lib/dhcp/dhcpd.leases

# Восстановление (сервер должен быть остановлен)
sudo systemctl stop isc-dhcp-server
sudo cp /backup/dhcpd.leases.20260912 /var/lib/dhcp/dhcpd.leases
sudo systemctl start isc-dhcp-server
```

### Рекомендации по эксплуатации

- **Валидация перед перезапуском:** Никогда не делайте `systemctl restart` без предварительного `dhcpd -t` (ISC) или `kea-dhcp4 -t` (Kea). Одна ошибка в конфигурации остановит выдачу адресов во всей сети.
- **Мониторинг:** Рекомендуется использовать внешний скрипт-экспортер (например, `dhcpd-leases-exporter` для ISC или `kea-exporter` для Kea) для визуализации заполнения пулов в **Grafana**.

### Связанные разделы

- **[Обзор архитектуры ISC DHCP](./isc_dhcp_server_overview.md)** — компоненты и жизненный цикл.
- **[Базовая настройка](./isc_dhcp_server_basic_config.md)** — структура и опции `dhcpd.conf`.
- **[Диагностика DHCP — Теория](../../../../Networking/Protocols/DHCP/dhcp_analysis_troubleshooting.md)** — глубокий разбор заголовков и DORA.
