# BIND: Реагирование на инциденты и live-отладка

---

## Определения

**Incident Response (реагирование на инциденты)** — процесс обнаружения, анализа, локализации и устранения инцидентов, связанных с DNS-сервисом. В контексте BIND: отклонения от нормы в ответах DNS, деградация производительности, атаки на DNS-инфраструктуру.

**Live Debugging (отладка в реальном времени)** — сбор и анализ данных о работающем DNS-сервере без остановки сервиса. Включает: анализ логов, tcpdump, rndc-команды, проверку кэша, мониторинг соединений.

**Postmortem (ретроспектива инцидента)** — документ, описывающий: что произошло, когда, почему, какие действия были предприняты, какие выводы сделаны и какие меры предотвращения приняты.

**RCODE (Response Code)** — код ответа DNS, указывающий на результат обработки запроса. Ключевые: NOERROR (0), SERVFAIL (2), NXDOMAIN (3), REFUSED (5).

---

## Базовые концепции

### Типы DNS-инцидентов

| Тип | Симптомы | Серьёзность | Время реакции |
| :--- | :--- | :--- | :--- |
| **DNS-сервис недоступен** | `SERVFAIL` на все запросы, таймауты | Критическая | < 5 мин |
| **Высокий SERVFAIL rate** | > 1% запросов возвращают SERVFAIL | Высокая | < 15 мин |
| **Zone transfer failure** | Slave не получает обновления | Средняя | < 1 часа |
| **DNSSEC validation failure** | `SERVFAIL` после подписания зоны | Высокая | < 15 мин |
| **Cache poisoning attempt** | Подозрительные записи в кэше | Критическая | < 5 мин |
| **DDoS-атака** | Резкий рост QPS, истощение ресурсов | Критическая | < 5 мин |
| **Zone file corruption** | `named` не загружает зону, ошибки в логах | Высокая | < 30 мин |
| **Split-brain (HA-кластер)** | Два master-сервера отдают разные данные | Критическая | < 10 мин |

### Диагностический метод outside-in

```text
1. Внешний мир (клиент)
   │  dig @8.8.8.8 example.com
   │
2. Публичные резолверы
   │  dig @1.1.1.1 example.com
   │
3. Авторитативные серверы
   │  dig @ns1.example.com example.com
   │
4. Сам сервер (localhost)
   │  dig @127.0.0.1 example.com
   │
5. Конфигурация и логи
   │  named-checkconf, journalctl, tcpdump
```

### Метрики для мониторинга инцидентов

| Метрика | Порог алерта | Источник |
| :--- | :--- | :--- |
| `probe_success` | < 1 (недоступен) | Blackbox Exporter |
| `SERVFAIL rate` | > 1% за 5 мин | Prometheus |
| `DNS latency p99` | > 100 мс за 5 мин | Prometheus |
| `Zone transfer lag` | > 30 мин | rndc zonestatus |
| `Cache hit ratio` | < 70% за 15 мин | Prometheus |
| `Query reject rate` | > 10 req/s | Prometheus |

---

## Практические сценарии

### 1. Live-отладка: быстрая диагностика

**Сценарий:** Пользователи жалуются, что сайт не открывается.

```bash
# Шаг 1: Проверка из внешнего мира
dig @8.8.8.8 example.com +short
# → 192.0.2.1 (OK, если IP правильный)

# Шаг 2: Проверка через авторитативный сервер
dig @ns1.example.com example.com +short +time=2
# → 192.0.2.1 (OK)

# Шаг 3: Проверка через localhost
dig @127.0.0.1 example.com +short
# → 192.0.2.1 (OK)

# Шаг 4: Если проблема найдена — проверка типа записи
dig @127.0.0.1 example.com A +noall +answer
dig @127.0.0.1 example.com AAAA +noall +answer
dig @127.0.0.1 example.com MX +noall +answer
```

**Сценарий:** `SERVFAIL` на все запросы.

```bash
# Шаг 1: Проверка статуса named
sudo systemctl status named
# → Active: active (running) — OK
# → Active: inactive (dead) — проблема

# Шаг 2: Проверка конфигурации
sudo named-checkconf
# → errors: ... (есть ошибки)
# → no errors (конфиг ок)

# Шаг 3: Проверка загрузки зон
sudo rndc zonestatus example.com
# → type: master
# → files: ... (зона загружена)

# Шаг 4: Проверка кэша
sudo rndc dumpdb -cache
sudo rndc recursing
# → Если есть stuck recursion — проблема с upstream

# Шаг 5: Проверка сетевых подключений
sudo ss -tlnp | grep named
# → Должен слушать на порту 53
```

### 2. Анализ DNS-трафика через tcpdump

```bash
# Захват DNS-трафика на порту 53
sudo tcpdump -i eth0 port 53 -nn -c 100
# → 14:32:01.123456 IP 192.168.1.100.54321 > 10.0.0.1.53: 12345+ A? example.com. (30)
# → 14:32:01.124567 IP 10.0.0.1.53 > 192.168.1.100.54321: 12345 1/0/0 A 192.0.2.1 (30)

# Фильтрация по имени
sudo tcpdump -i eth0 port 53 and host 10.0.0.1 -nn -l | grep "example.com"

# Захват только ошибок (SERVFAIL)
sudo tcpdump -i eth0 port 53 -nn -l -w /tmp/dns-debug.pcap &
# Затем анализ в Wireshark или tshark:
tshark -r /tmp/dns-debug.pcap -Y "dns.flags.rcode == 2"

# Анализ трансферов зон
sudo tcpdump -i eth0 port 53 -nn -l | grep "AXFR\|IXFR"
```

### 3. Анализ кэша через rndc

```bash
# Дамп кэша в файл
sudo rndc dumpdb -cache
# Файл: /var/cache/bind/named_dump.db

# Просмотр содержимого кэша
sudo rndc recursing
# → Показывает текущие рекурсивные запросы

# Очистка кэша (при подозрении на отравление)
sudo rndc flush
sudo rndc flushname example.com

# Проверка устаревших записей в кэше
sudo rndc serving
# → Показывает текущие обслуживаемые зоны и кэш
```

### 4. Анализ логов при инциденте

```bash
# Последние ошибки
sudo journalctl -u named -n 100 --no-pager | grep -i "error\|fail\|refused"

# Поиск SERVFAIL
sudo journalctl -u named --since "1 hour ago" | grep "SERVFAIL"

# Поиск трансферов
sudo journalctl -u named --since "1 hour ago" | grep -i "transfer\|notify"

# Поиск ACL-блокировок
sudo journalctl -u named --since "1 hour ago" | grep -i "refused\|denied\|acl"

# Поиск DNSSEC-ошибок
sudo journalctl -u named --since "1 hour ago" | grep -i "dnssec\|sig\|rrsig"
```

### 5. Быстрая остановка DDoS-атаки

```bash
# Шаг 1: Определение типа атаки
sudo tcpdump -i eth0 port 53 -nn -c 1000 | \
  awk '{print $5}' | cut -d. -f1-4 | sort | uniq -c | sort -rn | head -10
# → Показывает IP-адреса с наибольшим количеством запросов

# Шаг 2: Включение RRL (если не включён)
sudo rndc rate-limit example.com on

# Шаг 3: Блокировка атакующих IP через ACL
sudo iptables -I INPUT -s <attacker_ip> -p udp --dport 53 -j DROP

# Шаг 4: Мониторинг
watch -n 1 "sudo rndc status | grep -A3 'queries'"
```

### 6. Восстановление повреждённого зонного файла

```bash
# Шаг 1: Определение проблемы
sudo named-checkzone example.com /var/lib/bind/db.example.com
# → dns_rdata_fromtext: ... near '...': unknown class/type
# → zone example.com/IN: loading from master file ... failed: bad name

# Шаг 2: Восстановление из backup
sudo cp /var/backup/db.example.com.20260915 /var/lib/bind/db.example.com

# Шаг 3: Валидация
sudo named-checkzone example.com /var/lib/bind/db.example.com
# → OK

# Шаг 4: Применение
sudo rndc reload example.com

# Шаг 5: Проверка
dig @127.0.0.1 example.com +short
```

### 7. Откат DNSSEC-подписи (если подпись сломана)

```bash
# Шаг 1: Диагностика
delv @127.0.0.1 example.com +rtrace 2>&1 | tail -20
# → bogus: RRSIG validation failed

# Шаг 2: Временное отключение DNSSEC (NTA)
sudo rndc nta -lifetime 1h example.com
# → Отключает DNSSEC для example.com на 1 час

# Шаг 3: Проверка
dig @127.0.0.1 example.com +dnssec +short
# → Теперь возвращает ответ без DNSSEC-валидации

# Шаг 4: Постоянное исправление
# Переподписать зону
dnssec-signzone -A -3 $(head -c 1000 /dev/urandom | sha1sum | cut -b 1-16) \
  -N INCREMENT -o example.com -t /var/lib/bind/db.example.com

# Применение
sudo rndc reload example.com

# Шаг 5: Удаление NTA
sudo rndc nta -remove example.com
```

### 8. Шаблон Postmortem-документа

```markdown
# Postmortem: DNS Incident — [дата]

## Резюме
- **Начало:** YYYY-MM-DD HH:MM UTC
- **Окончание:** YYYY-MM-DD HH:MM UTC
- **Длительность:** X часов Y минут
- **Влияние:** [описание воздействия на пользователей]
- **Серьёзность:** P1/P2/P3/P4

## Timeline (хронология)
| Время (UTC) | Событие |
| :--- | :--- |
| HH:MM | Обнаружена аномалия в мониторинге |
| HH:MM | Начата диагностика |
| HH:MM | Определена причина |
| HH:MM | Применено исправление |
| HH:MM | Сервис восстановлен |

## Причина (Root Cause)
[Подробное описание технической причины инцидента]

## Действия (What Went Well / What Went Wrong)
### Что прошло хорошо:
- [список]

### Что прошло плохо:
- [список]

## Действия по предотвращению (Action Items)
| # | Действие | Ответственный | Срок | Статус |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [описание] | [имя] | [дата] | open |
| 2 | [описание] | [имя] | [дата] | open |

## Метрики
- Количество пострадавших пользователей: X
- Количество DNS-запросов с ошибкой: X
- Время до обнаружения (MTTD): X минут
- Время до восстановления (MTTR): X минут
```

---

## Типичные ошибки и их решение

### named не запускается после изменения конфигурации

**Симптом:** `Job for named.service failed...`

**Решение:**

```bash
# 1. Проверка ошибок
sudo named-checkconf
# → Покажет конкретную строку с ошибкой

# 2. Просмотр логов
sudo journalctl -u named -n 50

# 3. Откат изменений
cd /etc/bind
git checkout named.conf.local   # если используется git

# 4. Запуск в foreground для диагностики
sudo named -g -c /etc/bind/named.conf -d 3
```

### DNS-ответы приходят с задержкой > 500 мс

**Симптом:** `dig` выполняется > 500 мс.

**Решение:**

```bash
# 1. Проверка нагрузки
top -c | grep named
# → CPU%, MEM%

# 2. Проверка размера кэша
sudo rndc status | grep -A5 "cache"
# → cache size: ...

# 3. Очистка кэша (если много мусора)
sudo rndc flush

# 4. Проверка upstream-серверов
for fwd in 8.8.8.8 1.1.1.1 9.9.9.9; do
  echo "$fwd: $(dig @$fwd example.com +short +time=1)"
done
```

### Slave-сервер устарел (zone serial mismatch)

**Симптом:** Slave отдаёт устаревшие данные.

**Решение:**

```bash
# 1. Проверка serial
dig @master example.com SOA +short
# → ns1.example.com. admin.example.com. 2026091501 ...
dig @slave example.com SOA +short
# → ns1.example.com. admin.example.com. 2026091001 ... (старый)

# 2. Принудительный трансфер
sudo rndc retransfer example.com

# 3. Проверка
sudo rndc zonestatus example.com | grep serial
```

---

## Лучшие практики

*   **Мониторинг 24/7** — настройте Prometheus + Blackbox Exporter + Alertmanager. Алерты на SERVFAIL, latency, availability.
*   **Runbook** — создайте пошаговые инструкции для каждого типа инцидента. Не полагайтесь на память.
*   **Резервное копирование** — ежедневный backup zone-файлов и ключей. Храните минимум 30 дней.
*   **Репетиции** — регулярно проводите tabletop exercises (模拟 инцидентов) для проверки готовности команды.
*   **Postmortem без обвинений** — фокус на процессах, а не на людях. Цель — предотвращение повторения.
*   **Логирование** — всегда включайте querylog при инцидентах. Отключайте после решения.
*   **Версионирование** — храните конфигурацию BIND в Git. Каждое изменение — коммит с описанием.
*   **Автоматизация** — скрипты для типичных операций (ротация ключей, failover, backup).

---

## Дополнительная информация

### Инструментарий

- **tcpdump / tshark:** Захват и анализ DNS-трафика.
- **rndc:** Управление и диагностика BIND.
- **named-checkconf / named-checkzone:** Валидация конфигурации.
- **dig / kdig / delv:** Диагностика DNS-ответов.
- **Prometheus + Blackbox Exporter:** Мониторинг в реальном времени.

### Связанные разделы

*   [BIND: Логирование и мониторинг](./logging-and-monitoring.md) — настройка логов, Prometheus, Grafana.
*   [BIND: Troubleshooting](./troubleshooting.md) — детальная диагностика ошибок.
*   [BIND: HA-кластер](./high-availability-cluster.md) — failover и split-brain.
*   [Диагностика DNS](../../../Linux/Diagnostics/Networking/dns/overview.md) — инструменты диагностики.
*   [Мониторинг DNS](../../../Networking/Protocols/DNS/dns_monitoring.md) — архитектура мониторинга.
