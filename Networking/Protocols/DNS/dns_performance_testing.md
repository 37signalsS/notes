# Тестирование производительности DNS

## Определения

**DNS Benchmarking** — процесс измерения пропускной способности (QPS — Queries Per Second) и латентности DNS-резолвера под нагрузкой. Цель — определить максимальную производительность сервера и выявить узкие места (bottlenecks) до возникновения проблем в продакшене.

**dnsperf** — стандартный инструмент ISC (Internet Systems Consortium) для нагрузочного тестирования DNS-серверов. Отправляет UDP/TCP-запросы из файла и собирает статистику: QPS, латентность (min/max/avg/p99), количество ошибок, таймаутов.

**queryperf** — альтернативный инструмент ISC, включённый в пакет `bind9-utils`. Аналог `dnsperf`, но с несколько иной семантикой: использует `queryfile` и поддерживает параллельные потоки через параметр `-d`.

**dnspyre** — современный инструмент для DNS-бенчмаркинга, написанный на Go. Поддерживает:
- Параллельные соединения (concurrency)
- Автоматическое определение RTT
- P50/P95/P99 латентность
- Графический вывод (ASCII-chart)
- DoT/DoH протоколы

**DNS Baseline** — минимальный набор метрик (QPS, латентность, error rate), установленный в спокойном состоянии. Используется как référence для сравнения при изменении конфигурации или нагрузки.

---

## Базовые концепции

### Методология тестирования

**Этапы бенчмаркинга DNS:**

1. **Подготовка (Baseline):** Измерить текущую производительность в спокойном состоянии. Записать QPS, латентность, error rate.
2. **Нагрузка (Load Test):** Постепенно увеличивать QPS до предела. Определить точку насыщения (saturation point).
3. **Стресс (Stress Test):** Превысить нормальную нагрузку в 2–5 раз. Проверить поведение при перегрузке.
4. **Длительный тест (Endurance):** Поддерживать высокую нагрузку в течение 15–60 минут для выявления утечек памяти и деградации.

**Ключевые метрики:**

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **QPS (Queries Per Second)** | Количество запросов, обработанных за секунду | Зависит от сервера: BIND ~10K–50K, Unbound ~50K–200K |
| **Latency (p50)** | Медианное время ответа | < 5 мс (локально), < 50 мс (через сеть) |
| **Latency (p99)** | 99-й процентиль латентности | < 20 мс (локально), < 100 мс (через сеть) |
| **Error Rate** | Доля ошибок (SERVFAIL, REFUSED, timeout) | < 0.1% |
| **Timeout Rate** | Доля запросов с таймаутом | < 0.01% |
| **Cache Hit Rate** | Доля запросов из кэша | > 90% (при наличии кэша) |

### Факторы, влияющие на производительность

| Фактор | Влияние | Как проверить |
| :--- | :--- | :--- |
| **Размер кэша** | Маленький кэш → больше обращений к authoritative | `resolvectl statistics`, `rndc status` |
| **Количество concurrent connections** | Мало соединений → блокировка при высокой нагрузке | `ulimit -n`, `net.core.somaxconn` |
| **Размер UDP-буфера** | Маленький буфер → дропы пакетов | `sysctl net.core.rmem_max`, `net.core.wmem_max` |
| **conntrack table** | Переполнение → дропы новых соединений | `sysctl net.netfilter.nf_conntrack_max` |
| **Рекурсия** | Рекурсивные запросы дольше итеративных | `dig +trace` для анализа цепочки |
| **DNSSEC валидация** | Проверка подписей добавляет задержку | Сравнение с/без `cd` флага в dig |
| **CPU ядро** | BIND单线readed для обработки запросов | `named -V` (проверка multithreading) |

### Инструменты: сравнение

| Инструмент | Язык | Установка | DoT/DoH | Простота | График |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **dnsperf** | C | `apt install dnsperf` | Нет | Средняя | Нет |
| **queryperf** | C | `apt install bind9-utils` | Нет | Средняя | Нет |
| **dnspyre** | Go | `go install github.com/manybubbles/dnspyre@latest` | Да | Высокая | ASCII |
| **dns hammer** | Go | `go install github.com/canieug/dns-hammer@latest` | Да | Высокая | Нет |

---

## Практические сценарии

### Предусловия

```bash
# Debian/Ubuntu
sudo apt install dnsperf bind9-utils

# dnspyre (Go)
go install github.com/manybubbles/dnspyre@latest
# → бинарник в ~/go/bin/dnspyre

# Проверка наличия инструментов
dnsperf -v 2>&1 | head -1
# → dnsperf 2.x.x

queryperf -v 2>&1 | head -1
# → queryperf version: $Id: ... $

dnspyre --version 2>&1
# → dnspyre version: x.x.x
```

### 1. Базовый тест через dnsperf

**Создание файла запросов (`queries.txt`):**
```text
example.com A
google.com A
github.com A
cloudflare.com AAAA
example.org MX
```

**Запуск теста:**
```bash
# Базовый тест: 1000 запросов, 10 concurrent
dnsperf -s 127.0.0.1 -d queries.txt -c 10 -n 1000 -l 30
# → -s: сервер (resolver)
# → -d: файл запросов
# → -c: количество параллельных соединений
# → -n: общее количество запросов
# → -l: длительность теста в секундах (0 = неограниченно)
```

**Пример вывода:**
```text
DNS Performance Testing Tool
[Status] Server:       127.0.0.1
[Status] Sending queries:  to 127.0.0.1
[Status] Running test for 30 seconds

Statistics:
  Queries sent:         15234
  Queries completed:    15234
  Queries lost:         0
  Queries per second:   507.8

  Min latency:          0.12 ms
  Max latency:          23.45 ms
  Avg latency:          1.23 ms
  Stddev deviation:     0.89 ms

  Latency p50:          0.98 ms
  Latency p90:          2.15 ms
  Latency p95:          3.42 ms
  Latency p99:          8.67 ms
```

### 2. Тест через queryperf

**Создание файла (`queryfile.txt`):**
```text
example.com A
google.com A
github.com A
cloudflare.com AAAA
example.org MX
```

**Запуск:**
```bash
queryperf -d queryfile.txt -s 127.0.0.1 -c 10 -q 1000
# → -d: файл запросов
# → -s: сервер
# → -c: параллельные потоки
# → -q: количество запросов на поток
```

**Пример вывода:**
```text
DNS Performance Testing Tool
QPS: 485.3
Min latency: 0.15 ms
Max latency: 19.82 ms
Avg latency: 1.34 ms
Stddev: 0.92 ms
P50: 1.05 ms
P90: 2.38 ms
P95: 3.89 ms
P99: 9.23 ms
```

### 3. Тест через dnspyre (современный)

**Базовый тест:**
```bash
dnspyre --server 127.0.0.1 --queries 10000 --concurrency 20 example.com
# → --server: DNS-резолвер
# → --queries: общее количество запросов
# → --concurrency: параллельные запросы
# → Домен для тестирования (один)
```

**Пример вывода:**
```text
Benchmarking 127.0.0.1 with 10000 queries using 20 goroutines
Queries sent:     10000
Queries answered: 10000
Queries failed:   0
Duration:         4.23s
QPS:              2364.1

Latency (ms):
  min    avg    max    p99     p95     p50
  0.08   0.42   12.3   2.89    1.23    0.35
```

**Тест с несколькими доменами:**
```bash
# Создание файла с доменами
cat > domains.txt << 'EOF'
example.com
google.com
github.com
cloudflare.com
EOF

# Тест с файлом доменов
dnspyre --server 127.0.0.1 --file domains.txt --queries 5000 --concurrency 50
```

**Тест с DoT:**
```bash
dnspyre --server 9.9.9.9 --tls --queries 1000 --concurrency 10 example.com
```

**Тест с DoH:**
```bash
dnspyre --doh https://dns.google/dns-query --queries 1000 --concurrency 10 example.com
```

### 4. Стресс-тест: определение предела

```bash
# Пошаговое увеличение нагрузки
for concurrency in 10 50 100 200 500 1000; do
  echo "=== Concurrency: $concurrency ==="
  dnspyre --server 127.0.0.1 --queries 5000 --concurrency $concurrency example.com 2>&1 | grep -E "QPS|failed|p99"
  echo ""
done
# Пример вывода:
# === Concurrency: 10 ===
# QPS: 485.3    failed: 0   p99: 2.89ms
# === Concurrency: 50 ===
# QPS: 2134.7   failed: 0   p99: 5.23ms
# === Concurrency: 100 ===
# QPS: 3456.2   failed: 0   p99: 8.67ms
# === Concurrency: 200 ===
# QPS: 3891.4   failed: 2   p99: 15.34ms  ← начало деградации
# === Concurrency: 500 ===
# QPS: 3201.8   failed: 45  p99: 89.23ms  ← перегрузка
# === Concurrency: 1000 ===
# QPS: 1567.3   failed: 234 p99: 342.1ms  ← отказ
```

### 5. Тест производительности кэша

```bash
# Шаг 1: Первый запрос (cold cache) — все запросы идут к authoritative
dnspyre --server 127.0.0.1 --queries 1000 --concurrency 1 example.com 2>&1 | grep "QPS"
# → QPS: 156.3  (медленно — cold cache)

# Шаг 2: Повторный запрос (warm cache) — ответы из кэша
dnspyre --server 127.0.0.1 --queries 10000 --concurrency 50 example.com 2>&1 | grep "QPS"
# → QPS: 8923.4  (быстро — warm cache)

# Шаг 3: Проверка размера кэша
resolvectl statistics
# → Current Cache Size: 4523
```

### 6. Сравнение производительности разных серверов

```bash
# Тест BIND vs Unbound vs systemd-resolved
for server in 127.0.0.1:53 10.0.0.53:53 10.0.0.54:53; do
  echo "=== Server: $server ==="
  dnspyre --server "$server" --queries 5000 --concurrency 20 example.com 2>&1 | grep -E "QPS|failed|p99"
done
# → 127.0.0.1:53: QPS: 4523.1  failed: 0  p99: 3.21ms
# → 10.0.0.53:53: QPS: 8912.4  failed: 0  p99: 1.45ms
# → 10.0.0.54:53: QPS: 1245.7  failed: 12 p99: 45.67ms  ← проблемный сервер
```

### 7. Длительный тест (Endurance)

```bash
# Тест в течение 15 минут для выявления утечек памяти
dnspyre --server 127.0.0.1 --queries 0 --concurrency 100 --duration 15m example.com
# → --queries 0: бесконечное количество запросов
# → --duration 15m: ограничение по времени
# → Мониторинг: QPS не должен падать со временем, p99 не должен расти
```

```bash
# Мониторинг использования памяти BIND во время теста
watch -n 5 "ps aux | grep named | grep -v grep | awk '{print \$6/1024 \" MB\"}'"
# → Если память растёт — утечка кэша или соединений
```

### 8. Тест влияния DNSSEC на производительность

```bash
# Тест с DNSSEC валидацией
dnspyre --server 127.0.0.1 --queries 5000 --concurrency 20 dnssec-failed.org 2>&1 | grep -E "QPS|p99"
# → QPS: 1234.5  p99: 12.34ms

# Тест без DNSSEC (через +cd флаг — через dig, или через unbound-control)
# dnspyre не поддерживает +cd, используем dig для ручной проверки
dig @127.0.0.1 dnssec-failed.org +cd +stats
# → Query time: 2 msec  (без валидации — быстрее)
```

---

## Лучшие практики

*   **Снимите baseline перед изменениями:** Всегда измеряйте текущую производительность перед любыми конфигурационными изменениями. Сравнивайте результаты до/после.
*   **Тестируйте на чистом сервере:** Убедитесь, что на тестовом сервере нет других нагрузок. Используйте отдельный VM или bare-metal сервер.
*   **Используйте несколько инструментов:** `dnsperf` для стандартизации (ISC-стандарт), `dnspyre` для наглядности (ASCII-графики).
*   **Тестируйте UDP и TCP отдельно:** UDP — основной транспорт DNS, но при больших ответах (>512 байт) используется TCP. Проверяйте оба сценария.
*   **Мониторьте p99, а не avg:** Среднее значение скрывает проблемы с хвостовой латентностью. P99 показывает реальный опыт самых «невезучих» запросов.
*   **Проверяйте conntrack:** При высокой нагрузке UDP conntrack в Linux может стать узким местом. Увеличьте `net.netfilter.nf_conntrack_max`.
*   **Не тестируйте через VPN:** VPN добавляет латентность, которая искажает результаты. Тестируйте по прямому каналу.
*   **Повторяйте тест 3 раза:** DNS-резолвер может давать разброс результатов. Запускайте тест 3 раза и берите медиану.

---

## Дополнительная информация

### Инструментарий

- **dnsperf:** ISC DNS Performance Testing Tool. Репозиторий: `github.com/dnsperf/dnsperf`.
- **queryperf:** Включён в пакет `bind9-utils`. ISC стандарт.
- **dnspyre:** Современный Go-инструмент. Репозиторий: `github.com/manybubbles/dnspyre`.
- **dns-hammer:** Ещё один Go-инструмент для нагрузочного тестирования.
- **resolvectl statistics:** Статистика кэша systemd-resolved.

### Ключевые RFC

- **RFC 1035:** DNS specification — базовые ограничения протокола.
- **RFC 7766:** DNS Transport over TCP — оптимизация TCP-соединений.

### Связанные разделы

- [Производительность DNS-резолвинга](../../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md) — оптимизация латентности в продакшене.
- [Мониторинг DNS](./dns_monitoring.md) — Prometheus, Grafana, алертинг.
- [Инструмент dig](../../../Linux/Diagnostics/Networking/dns/dig_tool.md) — ручная диагностика.
- [Безопасность DNS](./dns_security.md) — влияние DNSSEC на производительность.
