# Мониторинг и наблюдаемость DNS

## Определения

**DNS SLA (Service Level Agreement)** — соглашение об уровне dịch DNS-сервиса. Ключевые метрики: доступность (availability), латентность (latency) и корректность (correctness) ответов. Типичные SLA: 99.99% доступности, p99 латентность < 50 мс.

**DNS Success Rate** — доля успешных DNS-запросов (ответ NOERROR или NXDOMAIN) от общего числа запросов. Серверные ошибки (SERVFAIL, REFUSED, TIMEOUT) снижают success rate. Целевой показатель: > 99.9%.

**DNS Query Rate (QPS)** — количество DNS-запросов в секунду. Определяет требования к пропускной способности сервера и размеру кэша.

**DNS Cache Hit Ratio (CHR)** — доля запросов, разрешённых из кэша без обращения к авторитативным серверам. Высокий CHR (> 90%) снижает нагрузку на сеть и уменьшает латентность. Низкий CHR указывает на неоптимальный размер кэша или нестандартные имена.

**Blackbox Exporter** — Prometheus-экспортер для проверки внешних сервисов (HTTP, TCP, DNS, ICMP) «извне». Модуль `dns` отправляет тестовый запрос к указанному резолверу и экспортирует метрики: `probe_dns_lookup_time_seconds`, `probe_success`, `probe_dns_rcode`.

**BIND Statistics Channel** — встроенный HTTP/XML-интерфейс BIND (по умолчанию порт 8080), предоставляющий детальные метрики: количество запросов по типам (A, AAAA, MX, ...), кэш-статистика, количество рекурсий, ошибок, трансферов зон.

**CoreDNS Metrics** — Prometheus-метрики, экспортируемые CoreDNS через плагин `prometheus` (по умолчанию на `:9153/metrics`). Ключевые метрики: `coredns_dns_requests_total`, `coredns_dns_response_rcode_count_total`, `coredns_forward_request_duration_seconds`.

---

## Базовые концепции

### Архитектура мониторинга DNS

Мониторинг DNS строится на трёх уровнях:

1. **Экспорт метрик (Metrics Export)** — серверы DNS экспортируют свои внутренние счётчики в формате Prometheus (BIND statistics channel, CoreDNS plugin `prometheus`, Unbound `unbound-metrics`).
2. **Внешний probing** — Blackbox Exporter отправляет тестовые DNS-запросы снаружи и измеряет: время ответа, код ответа (RCODE), доступность резолвера.
3. **Дашборды и алертинг** — Grafana визуализирует метрики, Prometheus Alertmanager генерирует алерты при отклонениях от SLA.

```text
┌──────────────┐     ┌───────────────────┐     ┌──────────────┐
│  DNS Server  │────>│  Prometheus       │────>│  Grafana     │
│  (metrics)   │     │  (scrape)         │     │  (dashboard) │
└──────────────┘     └───────────────────┘     └──────────────┘
                           ▲
┌──────────────┐            │
│  Blackbox    │────────────┘  (probing)
│  Exporter    │
└──────────────┘
```

### Ключевые метрики для DNS

| Метрика | Источник | Описание | Целевое значение |
| :--- | :--- | :--- | :--- |
| `probe_success` | Blackbox Exporter | 1 = ответ получен, 0 = таймаут/ошибка | > 99.9% |
| `probe_dns_lookup_time_seconds` | Blackbox Exporter | Время разрешения имени | p99 < 0.05 сек |
| `probe_dns_rcode` | Blackbox Exporter | Код ответа (0=NOERROR, 3=NXDOMAIN, 2=SERVFAIL) | 0 или 3 |
| `coredns_dns_requests_total` | CoreDNS | Общее количество запросов по ресурсу/rcode | Мониторинг роста |
| `coredns_forward_request_duration_seconds` | CoreDNS | Латентность пересылки в upstream | p99 < 0.5 сек |
| `named_recursions_total` | BIND | Количество рекурсивных запросов | Нет spike'ов |
| `named_cache_hits` | BIND | Попадания в кэш | CHR > 90% |
| `named_query_rejects` | BIND | Отклонённые запросы (ACL) | Мониторинг аномалий |

### Определение SLA для DNS-сервиса

**Пример SLA-контракта:**

| Метрика | Цель | Алерт |
| :--- | :--- | :--- |
| Availability | 99.99% (52 мин/год downtime) | < 99.9% за 5 мин |
| Latency (p99) | < 50 мс | > 100 мс за 5 мин |
| Success Rate | > 99.9% | < 99.5% за 5 мин |
| SERVFAIL Rate | < 0.1% | > 1% за 5 мин |
| Cache Hit Ratio | > 85% | < 70% за 15 мин |

### Источники метрик

**BIND (.named):**
```text
# Включить statistics channel в named.conf.options:
statistics-channels {
    inet 127.0.0.1 port 8080 allow { 127.0.0.1; };
};
```
```bash
# Просмотр метрик
curl -s http://127.0.0.1:8080 | python3 -m json.tool | head -50
```

**CoreDNS (Corefile):**
```text
prometheus :9153
```
```bash
# Просмотр метрик
curl -s http://localhost:9153/metrics | grep coredns_dns_requests
```

**Unbound:**
```yaml
# /etc/unbound/unbound.conf
remote-control:
    control-enable: yes
    control-interface: 127.0.0.1
    control-port: 8953
```
```bash
# Просмотр метрик
unbound-control stats_noreset
```

---

## Практические сценарии

### Предусловия

```bash
# Debian/Ubuntu
sudo apt install prometheus prometheus-node-exporter grafana

# Blackbox Exporter (отдельный бинарник)
wget https://github.com/prometheus/blackbox_exporter/releases/latest/download/blackbox_exporter-*.linux-amd64.tar.gz
tar xzf blackbox_exporter-*.linux-amd64.tar.gz
sudo mv blackbox_exporter-*/blackbox_exporter /usr/local/bin/
```

### 1. Настройка Blackbox Exporter для DNS-мониторинга

**Конфигурация Blackbox Exporter (`/etc/blackbox_exporter/blackbox.yml`):**
```yaml
modules:
  dns_udp:
    prober: dns
    dns:
      transport_protocol: "udp"
      query_name: "example.com"
      query_type: "A"
      valid_rcodes:
        - NOERROR
        - NXDOMAIN
      preferred_ip_protocol: "ip4"
      timeout: 5s

  dns_tcp:
    prober: dns
    dns:
      transport_protocol: "tcp"
      query_name: "example.com"
      query_type: "A"
      valid_rcodes:
        - NOERROR
        - NXDOMAIN
      timeout: 5s

  dns_over_tls:
    prober: dns
    dns:
      transport_protocol: "tcp"
      dns_over_tls: true
      query_name: "example.com"
      query_type: "A"
      tls_config:
        insecure_skip_verify: false
      timeout: 5s
```

### 2. Настройка Prometheus для скрапинга DNS-метрик

**Конфигурация Prometheus (`/etc/prometheus/prometheus.yml`):**
```yaml
scrape_configs:
  # Метрики от Blackbox Exporter (probing DNS)
  - job_name: "blackbox_dns"
    metrics_path: /probe
    params:
      module: [dns_udp]
    static_configs:
      - targets:
          - "127.0.0.1:53"          # Локальный резолвер
          - "9.9.9.9"               # Quad9
          - "1.1.1.1"               # Cloudflare
        labels:
          dns_server: "public"
      - targets:
          - "10.0.0.53"             # Внутренний BIND
        labels:
          dns_server: "internal"
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115  # Blackbox Exporter

  # Метрики CoreDNS (если используется)
  - job_name: "coredns"
    static_configs:
      - targets: ["coredns.kube-system:9153"]
    metrics_path: /metrics

  # Метрики BIND (statistics channel)
  - job_name: "bind"
    static_configs:
      - targets: ["127.0.0.1:8080"]
    scrape_interval: 15s
```

### 3. Правила алертинга (Prometheus Alert Rules)

**Файл `/etc/prometheus/rules/dns_alerts.yml`:**
```yaml
groups:
  - name: dns_alerts
    rules:
      # DNS-сервис недоступен
      - alert: DNSUnreachable
        expr: probe_success{job="blackbox_dns"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "DNS-сервер {{ $labels.instance }} недоступен"
          description: "DNS-запрос к {{ $labels.instance }} не получил ответ в течение 2 минут"

      # Высокий уровень SERVFAIL
      - alert: HighServfailRate
        expr: |
          rate(probe_dns_rcode{rcode="SERVFAIL"}[5m])
          / rate(probe_dns_rcode[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "SERVFAIL rate > 1% для {{ $labels.instance }}"
          description: "Более 1% DNS-запросов завершаются ошибкой SERVFAIL"

      # Высокая латентность DNS
      - alert: HighDNSLatency
        expr: histogram_quantile(0.99, rate(probe_dns_lookup_time_seconds_bucket[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DNS p99 latency > 100 мс"
          description: "П99 латентность DNS-резолвинга превышает 100 мс"

      # Низкий Cache Hit Ratio (CoreDNS)
      - alert: LowCacheHitRatio
        expr: |
          rate(coreDNS_dns_responses_total{rcode="NOERROR"}[15m])
          / (rate(coreDNS_dns_responses_total[15m]) + rate(coreDNS_dns_queries_total[15m])) < 0.7
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Cache Hit Ratio < 70%"
          description: "Эффективность кэширования DNS снизилась ниже 70%"
```

### 4. Grafana-дашборд для DNS

**Основные панели дашборда:**

| Панель | Метрика | Тип визуализации |
| :--- | :--- | :--- |
| DNS Availability | `probe_success` | Stat (99.9% зелёный, < 99.9% красный) |
| DNS Latency (p50/p95/p99) | `probe_dns_lookup_time_seconds` | Time series |
| DNS QPS | `rate(probe_dns_rcode[5m])` | Time series |
| SERVFAIL Rate | `rate(probe_dns_rcode{rcode="SERVFAIL"}[5m])` | Time series |
| Cache Hit Ratio | `named_cache_hits / named_query_rejects` | Gauge |
| Upstream Latency | `coredns_forward_request_duration_seconds` | Heatmap |

**Импорт готового дашборда:**
- ID дашборда `14518` — CoreDNS мониторинг
- ID дашборда `11453` — BIND мониторинг

### 5. Проверка метрик через curl

```bash
# 1. Проверка Blackbox Exporter (probing DNS)
curl -s "http://localhost:9115/probe?target=9.9.9.9&module=dns_udp" | grep probe_success
# → probe_success 1  (DNS доступен)

# 2. Проверка времени ответа
curl -s "http://localhost:9115/probe?target=9.9.9.9&module=dns_udp" | grep probe_dns_lookup_time
# → probe_dns_lookup_time_seconds 0.023  (23 мс)

# 3. Проверка RCODE
curl -s "http://localhost:9115/probe?target=9.9.9.9&module=dns_udp" | grep probe_dns_rcode
# → probe_dns_rcode 0  (NOERROR)

# 4. Проверка CoreDNS метрик
curl -s http://localhost:9153/metrics | grep "coredns_dns_requests_total"
# → coredns_dns_requests_total{server="dns",zone="cluster.local.",proto="udp",type="A"} 1523

# 5. Проверка BIND statistics channel
curl -s http://127.0.0.1:8080/stats/json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Queries:', data['nsstat'].get('QrySuccess', 0))
print('Cache hits:', data['cachestat'].get('CacheHits', 0))
"
```

### 6. Диагностика проблем через метрики

```bash
# Поиск DNS-серверов с высокой ошибкой SERVFAIL
curl -s "http://localhost:9115/probe?target=10.0.0.53&module=dns_udp" | grep probe_dns_rcode
# → probe_dns_rcode 2  (SERVFAIL — проблема)

# Проверка доступности всех резолверов
for target in 8.8.8.8 9.9.9.9 1.1.1.1; do
  result=$(curl -s "http://localhost:9115/probe?target=$target&module=dns_udp" | grep probe_success | awk '{print $2}')
  echo "$target: $result"
done
# → 8.8.8.8: 1
# → 9.9.9.9: 1
# → 1.1.1.1: 1
```

---

## Лучшие практики

*   **Минимум 3 уровня мониторинга:** Blackbox (probing), Application Metrics (BIND/CoreDNS), и Infrastructure Metrics (CPU, RAM, Network).
*   **Проверяйте DNS снаружи и изнутри:** Blackbox Exporter проверяет доступность «как видит клиент»; метрики сервера показывают внутреннее состояние.
*   **Мониторьте RCODE распределение:** Не только success/fail, но и распределение по кодам (NOERROR, NXDOMAIN, SERVFAIL, REFUSED). Рост NXDOMAIN может указывать на DNS-спуфинг; рост SERVFAIL — на проблемы с upstream.
*   **Настраивайте алерты по Percentiles:** Используйте `histogram_quantile(0.99, ...)` вместо средних значений. Среднее скрывает хвостовую латентность.
*   **Сравнивайте резолверы:** Мониторьте несколько DNS-серверов параллельно и сравнивайте их метрики для выявления «слабого звена».
*   **Логируйте DNS-запросы при проблемах:** Временно включайте `querylog` в BIND для анализа проблемных запросов. Не держите `querylog` включённым постоянно — это нагружает диск.

---

## Дополнительная информация

### Инструментарий

- **Blackbox Exporter:** Внешний probing (DNS, HTTP, TCP, ICMP). Документация: `prometheus.io/docs/guides/blackbox-exporter`.
- **BIND Statistics Channel:** Встроенный HTTP-интерфейс (порт 8080 по умолчанию).
- **CoreDNS plugin prometheus:** Экспорт метрик на `:9153/metrics`.
- **Grafana:** Визуализация и алертинг. Готовые дашборды: CoreDNS (#14518), BIND (#11453).
- **Prometheus Alertmanager:** Отправка алертов в Slack, PagerDuty, Telegram.

### Ключевые RFC

- **RFC 8484:** DNS over HTTPS (DoH) — метрики для мониторинга шифрованного DNS.
- **RFC 9250:** DNS over QUIC (DoQ) — метрики для нового транспорта.

### Связанные разделы

- [Протокол DNS](./dns.md) — общая архитектура и порты.
- [Производительность DNS-резолвинга](../../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md) — оптимизация латентности.
- [Инструмент dig](../../../Linux/Diagnostics/Networking/dns/dig_tool.md) — ручная диагностика.
- [Безопасность DNS](./dns_security.md) — мониторинг атак.
- [Blackbox Exporter: DNS модуль](../../../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md) — конфигурация probing.
