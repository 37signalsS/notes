# BIND: Логирование и мониторинг

---

## Определения

**BIND Logging** — подсистема демона `named`, предоставляющая гибкую настройку журналирования через каналы (channels) и категории (categories). Каждый канал определяет destination (файл, syslog, stdout), severity level и формат вывода. Категории группируют типы событий (запросы, ошибки, трансферы, DNSSEC).

**Query Log** — лог DNS-запросов, обрабатываемых сервером. Содержит: имя клиента, запрошенное имя, тип записи, RCODE ответа, количество ответов. Используется для анализа трафика, поиска аномалий и аудита.

**Statistics Channel** — встроенный HTTP/XML/API интерфейс BIND (порт 8080 по умолчанию), предоставляющий метрики в формате JSON/XML. Источник данных для Prometheus-экспортера.

**BIND Exporter** — Prometheus-экспортер, скрапливающий метрики из BIND statistics channel и предоставляющий их в формате Prometheus. Основные метрики: `named_queries_total`, `named_cache_hits`, `named_query_rejects`.

**dnstap** — формат логирования DNS-трафика, основанный на Protocol Buffers. Позволяет записывать полные DNS-сообщения (включая транспорт) в структурированном формате. Интегрируется с fluentd, Vector, Logstash.

---

## Базовые концепции

### Архитектура логирования BIND

```text
                    ┌──────────────────────────────┐
                    │          named (BIND)          │
                    │                                │
                    │  ┌──────────┐  ┌────────────┐ │
                    │  │ Channel  │  │ Category   │ │
                    │  │ (output) │  │ (event     │ │
                    │  │          │  │  type)     │ │
                    │  └────┬─────┘  └─────┬──────┘ │
                    └───────┼──────────────┼────────┘
                            │              │
                ┌───────────┼──────────────┼───────────┐
                │           │              │           │
          ┌─────▼─────┐ ┌──▼────┐  ┌──────▼─────┐ ┌──▼──────┐
          │  File      │ │Syslog │  │ stdout     │ │dnstap   │
          │  (/var/log │ │       │  │            │ │(socket) │
          │  /named/)  │ │       │  │            │ │         │
          └───────────┘ └───────┘  └────────────┘ └─────────┘
                                    │
                              ┌─────▼──────┐
                              │ journald   │
                              │ (systemd)  │
                              └────┬───────┘
                                   │
                         ┌─────────▼────────┐
                         │ Centralized Log  │
                         │ (rsyslog/ELK/    │
                         │  Loki/Vector)    │
                         └──────────────────┘
```

### Уровни логирования (severity)

| Уровень | Описание | Когда использовать |
| :--- | :--- | :--- |
| `critical` | Критические ошибки, требующие немедленного вмешательства | Всегда |
| `error` | Ошибки обработки запросов, конфигурации | Всегда |
| `warning` | Предупреждения ( POTENTIAL проблема) | Всегда |
| `notice` | Информационные события (загрузка зоны, перезагрузка) | Рекомендуется |
| `info` | Детальная информация (отдельные запросы, ответы) | Только для отладки |
| `debug` | Детальная отладочная информация | Только при инцидентах |
| `dynamic` | Изменяемый уровень через `rndc trace` | Временная отладка |

### Категории логирования

| Категория | Описание | Типичный use-case |
| :--- | :--- | :--- |
| `queries` | DNS-запросы и ответы | Аудит, анализ трафика |
| `query-errors` | Ошибки обработки запросов | Диагностика проблем |
| `rate-limit` | Срабатывания RRL | Мониторинг атак |
| `xfer-in` | Входящие трансферы зон (AXFR/IXFR) | Мониторинг синхронизации |
| `xfer-out` | Исходящие трансферы зон | Мониторинг secondaries |
| `dnssec` | События DNSSEC (подписи, ключи) | Безопасность |
| `network` | Сетевые ошибки ( timeouts, refused) | Диагностика сети |
| `resolver` | Рекурсивные запросы к upstream | Мониторинг forwarding |
| `security` | ACL, TSIG, unauthorized access | Аудит безопасности |
| `lame-servers` | Ответы от некорректных серверов | Мониторинг качества |

---

## Практические сценарии

### Предусловия

```bash
# Установка зависимостей
sudo apt install bind9 bind9utils rsyslog prometheus prometheus-node-exporter

# Создание директории для логов
sudo mkdir -p /var/log/named
sudo chown bind:bind /var/log/named
```

### 1. Базовая настройка логирования в BIND

**Конфигурация `/etc/bind/named.conf`:**

```conf
logging {
    // Канал для DNS-запросов
    channel "query_log" {
        file "/var/log/named/query.log" versions 5 size 50m;
        severity info;
        print-time yes;
        print-category yes;
        print-severity yes;
    };

    // Канал для ошибок
    channel "error_log" {
        file "/var/log/named/error.log" versions 5 size 20m;
        severity warning;
        print-time yes;
        print-category yes;
        print-severity yes;
    };

    // Канал для трансферов зон
    channel "transfer_log" {
        file "/var/log/named/transfer.log" versions 3 size 10m;
        severity info;
        print-time yes;
    };

    // Канал для security
    channel "security_log" {
        file "/var/log/named/security.log" versions 5 size 20m;
        severity info;
        print-time yes;
    };

    // Канал для rate-limit
    channel "ratelimit_log" {
        file "/var/log/named/rate-limit.log" versions 3 size 10m;
        severity info;
        print-time yes;
    };

    // Привязка категорий к каналам
    category queries { "query_log"; };
    category query-errors { "error_log"; };
    category rate-limit { "ratelimit_log"; };
    category xfer-in { "transfer_log"; };
    category xfer-out { "transfer_log"; };
    category security { "security_log"; };
    category dnssec { "error_log"; };
    category network { "error_log"; };
    category default { "error_log"; };
};
```

**Применение:**

```bash
# Проверка конфигурации
sudo named-checkconf
# → no errors

# Перезагрузка
sudo rndc reconfig

# Проверка создания логов
ls -la /var/log/named/
# → query.log  error.log  transfer.log  security.log  rate-limit.log
```

### 2. Настройка ротации логов (logrotate)

**Файл `/etc/logrotate.d/named`:**

```bash
/var/log/named/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 bind bind
    postrotate
        /usr/sbin/rndc flush 2>/dev/null || true
    endscript
}
```

```bash
# Проверка
sudo logrotate -d /etc/logrotate.d/named
# → dry-run

# Принудительная ротация
sudo logrotate -f /etc/logrotate.d/named
```

### 3. Интеграция с syslog/rsyslog

**Файл `/etc/rsyslog.d/50-named.conf`:**

```bash
# Логи BIND → отдельный файл
if $programname == 'named' then /var/log/named/syslog.log
& stop
```

**Настройка BIND для вывода в syslog:**

```conf
logging {
    channel "syslog_channel" {
        syslog local0;      # Отправка в syslog (local0 facility)
        severity info;
    };

    channel "syslog_errors" {
        syslog local1;      # Ошибки в отдельный facility
        severity warning;
    };

    category queries { "syslog_channel"; };
    category query-errors { "syslog_errors"; };
    category security { "syslog_errors"; };
};
```

**Файл `/etc/rsyslog.d/60-named-facility.conf`:**

```bash
# local0 → запросы
local0.*    /var/log/named/syslog-queries.log

# local1 → ошибки
local1.*    /var/log/named/syslog-errors.log
```

```bash
# Перезапуск rsyslog
sudo systemctl restart rsyslog

# Проверка
logger -p local0.info "test syslog from BIND"
tail -f /var/log/named/syslog-queries.log
```

### 4. Централизованное логирование через rsyslog → ELK/Loki

**Файл `/etc/rsyslog.d/50-named-elk.conf`:**

```bash
# Отправка логов BIND в Logstash/Loggly/Loki
if $programname == 'named' then {
    action(
        type="omfwd"
        target="logstash.internal"
        port="514"
        protocol="tcp"
        template="RSYSLOG_SyslogProtocol23Format"
    )
}
```

**Файл Logstash для парсинга DNS-логов:**

```ruby
# /etc/logstash/conf.d/dns.conf
input {
  tcp {
    port => 514
    type => "syslog"
  }
}

filter {
  if [type] == "syslog" {
    grok {
      match => { "message" => "%{SYSLOGTIMESTAMP:timestamp} %{SYSLOGHOST:hostname} named\[%{INT:pid}\]: %{GREEDYDATA:log_message}" }
    }

    # Парсинг DNS-запросов
    if "query:" in [log_message] {
      grok {
        match => { "log_message" => "client %{IP:client_ip}#%{INT:client_port} \(%{DATA:query_name}\): query: %{DATA:query_name} %{WORD:query_type}" }
      }
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch.internal:9200"]
    index => "dns-logs-%{+YYYY.MM.dd}"
  }
}
```

**Интеграция с Loki (через Promtail):**

```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: named
    static_configs:
      - targets:
          - localhost
        labels:
          job: named
          __path__: /var/log/named/*.log
    pipeline_stages:
      - regex:
          expression: '^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
      - labels:
          timestamp:
```

### 5. Настройка Prometheus-мониторинга BIND

**Шаг 1: Включение statistics channel:**

```conf
// /etc/bind/named.conf.options
options {
    // ... другие опции ...

    statistics-channels {
        inet 127.0.0.1 port 8080 allow { 127.0.0.1; };
    };
};
```

**Шаг 2: Установка BIND Exporter:**

```bash
# Скачивание
wget https://github.com/prometheus-community/bind_exporter/releases/latest/download/bind_exporter-*.linux-amd64.tar.gz
tar xzf bind_exporter-*.linux-amd64.tar.gz
sudo mv bind_exporter-*/bind_exporter /usr/local/bin/

# Systemd unit
sudo tee /etc/systemd/system/bind_exporter.service <<EOF
[Unit]
Description=BIND Exporter
After=network.target

[Service]
Type=simple
User=bind
ExecStart=/usr/local/bin/bind_exporter \
  --bind.stats-url=http://127.0.0.1:8080/stats \
  --bind.stats-command=running \
  --web.listen-address=:9119
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now bind_exporter
```

**Шаг 3: Конфигурация Prometheus:**

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: "bind"
    static_configs:
      - targets: ["127.0.0.1:9119"]
    scrape_interval: 15s
```

**Шаг 4: Ключевые PromQL-метрики:**

```promql
# Общий QPS (queries per second)
rate(named_queries_total[5m])

# Cache Hit Ratio
named_cache_hits / (named_cache_hits + named_cache_misses)

# SERVFAIL rate
rate(named_queries_total{rcode="SERVFAIL"}[5m])

# Трансферы зон (AXFR/IXFR)
rate(named_zone_transfer_done_total[5m])

# Отклонённые запросы (ACL)
rate(named_query_rejects_total[5m])

# Рекурсивные запросы к upstream
rate(named_recursive_replies_total[5m])

# Время рекурсии (p99)
histogram_quantile(0.99, rate(named_recursive_duration_seconds_bucket[5m]))
```

### 6. Prometheus Alert Rules для BIND

**Файл `/etc/prometheus/rules/bind_alerts.yml`:**

```yaml
groups:
  - name: bind_alerts
    rules:
      # DNS-сервис недоступен
      - alert: BINDDown
        expr: up{job="bind"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "BIND-сервер {{ $labels.instance }} недоступен"

      # Высокий SERVFAIL rate
      - alert: HighServfailRate
        expr: |
          rate(named_queries_total{rcode="SERVFAIL"}[5m])
          / rate(named_queries_total[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SERVFAIL rate > 1% для {{ $labels.instance }}"

      # Низкий Cache Hit Ratio
      - alert: LowCacheHitRatio
        expr: |
          named_cache_hits / (named_cache_hits + named_cache_misses) < 0.7
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Cache Hit Ratio < 70% для {{ $labels.instance }}"

      # Массовые трансферы зон
      - alert: HighZoneTransferRate
        expr: rate(named_zone_transfer_done_total[5m]) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень трансферов зон на {{ $labels.instance }}"

      # Высокий rate rejected queries
      - alert: HighQueryRejectionRate
        expr: rate(named_query_rejects_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Массовое отклонение запросов на {{ $labels.instance }}"
```

### 7. Настройка dnstap (современное логирование)

**Предусловия:**

```bash
# dnstap требует пересборки BIND с поддержкой FSTRM
sudo apt install libfstrm-dev libprotobuf-dev protobuf-compiler
```

**Конфигурация BIND:**

```conf
// /etc/bind/named.conf
options {
    // ...
    dnstap-output unix "/var/run/named/dnstap.sock";
    dnstap-output version "v1";
};
```

**Запуск dnstap-приёмника (fstrm_capture):**

```bash
# Установка
sudo apt install framestreams-utils

# Запуск
fstrm_capture \
  --socket-path /var/run/named/dnstap.sock \
  --output-file /var/log/named/dnstap.pb \
  --max-writes 1000
```

**Парсинг dnstap через Python:**

```python
#!/usr/bin/env python3
"""Парсинг dnstap логов BIND"""
import dnstap_socket
import json

def handle_dnstap(msg):
    data = {
        "type": msg.type,
        "query_name": msg.query_name,
        "query_type": msg.query_type,
        "rcode": msg.rcode,
        "client_ip": msg.client_ip,
        "timestamp": msg.time_sec,
    }
    print(json.dumps(data))

# Запуск
socket = dnstap_socket.DnstapSocket("/var/run/named/dnstap.sock")
socket.on_data(handle_dnstap)
socket.run()
```

### 8. Включение querylog временно (для отладки)

```bash
# Включение querylog
sudo rndc querylog on

# Просмотр логов запросов
tail -f /var/log/named/query.log
# → client @0x7f8a1b2c3d40 192.168.1.100#54321 (example.com): query: example.com IN A + (192.168.1.100)

# Отключение querylog (обязательно!)
sudo rndc querylog off
```

**Важно:** `querylog` создает интенсивный диск I/O. Не держите его включенным постоянно — используйте только для отладки.

---

## Типичные ошибки и их решение

### Логи не создаются

**Симптом:** Файлы логов в `/var/log/named/` пусты или не создаются.

**Причины:**
1. Неверные права доступа на директорию
2. Категории не привязаны к каналам
3. `named` запущен от пользователя без прав на запись

**Решение:**

```bash
# 1. Проверка прав
ls -la /var/log/named/
# → drwxr-x--- 2 bind bind ... (должно быть)

# 2. Исправление прав
sudo chown -R bind:bind /var/log/named
sudo chmod 750 /var/log/named

# 3. Проверка конфигурации
sudo named-checkconf

# 4. Перезагрузка
sudo rndc reconfig
```

### Statistics channel недоступен

**Симптом:** `curl http://127.0.0.1:8080/stats/json` возвращает Connection refused.

**Причина:** Statistics channel не настроен или слушает другой порт.

**Решение:**

```bash
# 1. Проверка конфигурации
grep -A5 "statistics-channels" /etc/bind/named.conf.options

# 2. Проверка прослушивания
sudo ss -tlnp | grep 8080

# 3. Проверка ACL
# Разрешить доступ только с localhost
statistics-channels {
    inet 127.0.0.1 port 8080 allow { 127.0.0.1; };
};
```

### Логи слишком большие

**Симптом:** Дисковое пространство заканчивается из-за логов BIND.

**Решение:**

```bash
# 1. Уменьшить severity level
# Было: severity info; → Стало: severity warning;

# 2. Ограничить размер файла
channel "query_log" {
    file "/var/log/named/query.log" versions 3 size 10m;  # versions 3, max 10MB
};

# 3. Включить ротацию
sudo logrotate -f /etc/logrotate.d/named

# 4. Найти большие логи
du -sh /var/log/named/*
```

---

## Лучшие практики

*   **Разделяйте логи по типам** — запросы, ошибки, трансферы, security в отдельные файлы. Упрощает поиск и ротацию.
*   **Не держите `querylog` включенным постоянно** — используйте только для отладки. В продакшене включайте `querylog` через `rndc querylog on` при инцидентах.
*   **Настройте ротацию** — `versions 5 size 50m` для query log, `versions 3 size 10m` для остальных.
*   **Используйте dnstap** для полного аудита DNS-трафика — он записывает полные DNS-сообщения, включая транспорт и EDNS.
*   **Мониторьте через Prometheus** — statistics channel + bind_exporter + Grafana dashboards.
*   **Настраивайте алерты** — SERVFAIL rate > 1%, Cache Hit Ratio < 70%, DNS server down.
*   **Отправляйте логи в централизованную систему** — rsyslog → ELK/Loki для корреляции с другими сервисами.
*   **Используйте `print-time yes`** во всех каналах — без временных меток логи бесполезны для диагностики.

---

## Дополнительная информация

### Ключевые RFC

*   **RFC 3164:** The BSD Syslog Protocol.
*   **RFC 5424:** The Syslog Protocol (современный).
*   **RFC 8484:** DNS over HTTPS (DoH) — метрики для мониторинга.

### Инструментарий

- **dnstap:** Структурированное логирование DNS-трафика (Protocol Buffers).
- **bind_exporter:** Prometheus-экспортер для BIND.
- **fstrm_capture:** Утилита для записи dnstap-потоков.
- **Promtail:** Сбор логов для Loki.

### Связанные разделы

*   [Мониторинг DNS](../../../Networking/Protocols/DNS/dns_monitoring.md) — архитектура мониторинга, Blackbox Exporter, алертинг.
*   [BIND: Обзор](./overview.md) — архитектура и роли серверов.
*   [BIND: DoT/DoH сервер](./dot-doh-server.md) — шифрование DNS-трафика.
*   [Grafana: Dashboard](../../../Grafana/grafana-dashboards.md) — визуализация метрик.
*   [Prometheus: Alerting](../../../Grafana/alerting/best_practices.md) — лучшие практики алертинга.
