# LDAP мониторинг и метрики

## Определения

**openldap_exporter** — Prometheus-экспортер для OpenLDAP, собирающий метрики из `cn=monitor` (OLC) и `cn=snmp,o=monitor`.

**389DS SNMP** — встроенная поддержка SNMP MIB для мониторинга 389 Directory Server.

**Access Log** — лог операций клиента (bind, search, modify). Содержит поле `etime` (время выполнения в секундах).

**Error Log** — лог ошибок сервера. Содержит информацию о критических сбоях.

**cn=monitor** — специальная LDAP-база данных OpenLDAP, предоставляющая метрики производительности в реальном времени.

** latency** — задержка ответа LDAP-сервера на запрос. Целевое значение: < 100ms для search, < 50ms для bind.

**Throughput** — количество операций в секунду. Зависит от индексов, размера базы и аппаратных ресурсов.

---

## Базовые концепции

### Архитектура мониторинга LDAP

```text
┌──────────────────┐     ┌──────────────────┐
│   LDAP-сервер    │     │  openldap_exporter│
│  (slapd/ns-slapd)│     │  (Prometheus)     │
│                  │     │                   │
│  cn=monitor      │◄────│  Метрики:         │
│  Access Log      │     │  - operations     │
│  Error Log       │     │  - connections    │
└────────┬─────────┘     │  - database       │
         │               │  - replication    │
         ▼               └────────┬──────────┘
┌──────────────────┐              │
│   ELK / Loki     │◄─────────────┘
│   (Log Aggregation)│
└──────────────────┘
         │
         ▼
┌──────────────────┐
│   Grafana        │
│   (Dashboard)    │
└──────────────────┘
```

### Ключевые метрики для мониторинга

| Метрика | Источник | Описание | Алерт |
|:---|:---|:---|:---|
| `ldap_up` | Exporter | Доступность сервера (0/1) | Если 0 — критический |
| `ldap_connections_total` | cn=monitor | Количество соединений | > 80% от max |
| `ldap_operations_total` | cn=monitor | Операции в секунду | Резкий рост/спад |
| `ldap_search_latency_seconds` | Access Log | Латентность поиска | > 500ms |
| `ldap_bind_latency_seconds` | Access Log | Латентность bind | > 200ms |
| `ldap_errors_total` | Error Log | Количество ошибок | Рост ошибок |
| `ldap_replication_lag_seconds` | RUV | Лаг репликации | > 60 секунд |
| `ldap_database_size_bytes` | cn=monitor | Размер базы данных | Рост > 10% в день |
| `ldap_cache_hit_ratio` | cn=monitor | Коэффициент попаданий в кэш | < 85% |

## Практические сценарии

### 1. Настройка openldap_exporter

```bash
# Установка (Docker)
docker run -d --name openldap-exporter \
  -p 9111:9111 \
  -e LDAP_URL=ldap://ldap.example.com:389 \
  -e LDAP_BIND_DN="cn=readonly,ou=services,dc=example,dc=com" \
  -e LDAP_BIND_PASSWORD_FILE=/run/secrets/ldap_password \
  --secret ldap_password \
  ghcr.io/zevenet/openldap-exporter:latest

# Или через Docker Compose
```

Пример docker-compose.yml:

```yaml
version: '3.8'
services:
  openldap-exporter:
    image: ghcr.io/zevenet/openldap-exporter:latest
    ports:
      - "9111:9111"
    environment:
      LDAP_URL: "ldap://ldap.example.com:389"
      LDAP_BIND_DN: "cn=readonly,ou=services,dc=example,dc=com"
      LDAP_BASE_DN: "dc=example,dc=com"
    secrets:
      - ldap_password
    restart: unless-stopped

secrets:
  ldap_password:
    file: ./ldap_password.txt
```

### 2. Настройка метрик для 389DS

```bash
# Включение SNMP (389DS)
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-snmp-access=on \
  nsslapd-snmp-agent=on

# Настройка JSON-логов для парсинга
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-accesslog-level=4 \
  nsslapd-log-format=json
```

### 3. Prometheus конфигурация

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'openldap'
    static_configs:
      - targets: ['ldap-exporter:9111']
    scrape_interval: 30s

  - job_name: '389ds'
    static_configs:
      - targets: ['389ds-exporter:9111']
    scrape_interval: 30s
```

### 4. Grafana Dashboard: базовые панели

```json
{
  "panels": [
    {
      "title": "LDAP Operations/sec",
      "type": "graph",
      "targets": [
        {
          "expr": "rate(ldap_operations_total[5m])",
          "legendFormat": "{{operation}}"
        }
      ]
    },
    {
      "title": "LDAP Search Latency",
      "type": "graph",
      "targets": [
        {
          "expr": "histogram_quantile(0.95, rate(ldap_search_latency_seconds_bucket[5m]))",
          "legendFormat": "p95"
        }
      ]
    },
    {
      "title": "LDAP Connections",
      "type": "stat",
      "targets": [
        {
          "expr": "ldap_connections_current",
          "legendFormat": "Current"
        }
      ]
    }
  ]
}
```

### 5. Алерты (Prometheus Alerting Rules)

```yaml
# alerts.yml
groups:
  - name: ldap
    rules:
      - alert: LDAPDown
        expr: ldap_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "LDAP server is down"
          description: "LDAP server {{ $labels.instance }} is unreachable"

      - alert: LDAPHighLatency
        expr: histogram_quantile(0.95, rate(ldap_search_latency_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LDAP search latency is high"
          description: "p95 latency is {{ $value }}s"

      - alert: LDAPReplicationLag
        expr: ldap_replication_lag_seconds > 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LDAP replication lag is high"
          description: "Replication lag is {{ $value }}s"

      - alert: LDAPCacheHitRatioLow
        expr: ldap_cache_hit_ratio < 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "LDAP cache hit ratio is low"
          description: "Cache hit ratio is {{ $value | humanizePercentage }}"
```

### 6. Сбор логов через Prometheus Loki

```yaml
# promtail-config.yml
scrape_configs:
  - job_name: ldap
    static_configs:
      - targets:
          - localhost
        labels:
          job: ldap
          __path__: /var/log/dirsrv/slapd-*/access
    pipeline_stages:
      - regex:
          expression: '.*etime=(?P<etime>[0-9.]+).*'
      - labels:
          etime:
```

### 7. Сбор метрик из Access Log (парсинг)

```bash
# Поиск медленных операций (>100ms) в 389DS
grep "etime=1" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'etime=' '{print $2}' | cut -d' ' -f1 | sort -rn | head -20

# Поиск неиндексированных поисков (notes=U)
grep "notes=U" /var/log/dirsrv/slapd-localhost/access | wc -l

# Подсчет операций по типу
grep -o "op=[0-9]*" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'=' '{print $2}' | sort | uniq -c | sort -rn
```

### 8. Мониторинг через Zabbix (SNMP)

```bash
# Настройка SNMP-агента
# /etc/snmp/snmpd.conf
view systemview included .1.3.6.1.4.1.36703

# Получение метрик через snmpwalk
snmpwalk -v2c -c public ldap.example.com .1.3.6.1.4.1.36703
```

## Дополнительная информация

### Рекомендуемые пороги алертов

| Метрика | Warning | Critical |
|:---|:---|:---|
| `ldap_up` | — | 0 (1 минута) |
| `ldap_search_latency_p95` | > 500ms | > 2s |
| `ldap_bind_latency_p95` | > 200ms | > 1s |
| `ldap_connections_ratio` | > 70% max | > 90% max |
| `ldap_replication_lag` | > 30s | > 300s |
| `ldap_cache_hit_ratio` | < 90% | < 70% |
| `ldap_errors_rate` | > 10/min | > 50/min |

### 9. Централизованный сбор логов через Syslog

**389DS в Syslog:**

```bash
# Настройка Syslog-клиента в 389DS
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-accesslog-syslog=on \
  nsslapd-errorlog-syslog=on \
  nsslapd-accesslog-syslog-level=6

# /etc/rsyslog.d/ldap.conf (на сервере сбора логов)
if $programname == 'ns-slapd' then /var/log/ldap/ldap.log
if $programname == 'ns-slapd' then stop
```

**OpenLDAP в Syslog:**

```bash
# /etc/rsyslog.d/slapd.conf
if $syslogtag == 'slapd' then /var/log/ldap/slapd.log
if $syslogtag == 'slapd' then stop

# Включить Syslog в OpenLDAP
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=config
changetype: modify
replace: olcLogLevel
olcLogLevel: stats
EOF
```

### 10. Сбор логов через ELK Stack

**Filebeat → Logstash → Elasticsearch:**

```yaml
# filebeat.yml
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /var/log/dirsrv/slapd-localhost/access
    - /var/log/dirsrv/slapd-localhost/errors
  fields:
    service: ldap
  fields_under_root: true

- type: log
  enabled: true
  paths:
    - /var/log/slapd-access.log
    - /var/log/slapd.log
  fields:
    service: openldap
  fields_under_root: true

output.logstash:
  hosts: ["logstash:5044"]
```

**Logstash pipeline:**

```ruby
# /etc/logstash/conf.d/ldap.conf
input {
  beats {
    port => 5044
  }
}

filter {
  if [service] == "ldap" {
    grok {
      match => { "message" => "%{TIMESTAMP_ISO8601:timestamp}.*conn=%{NUMBER:conn_id}.*op=%{NUMBER:op_id}.*RESULT err=%{NUMBER:err_code}" }
    }
    if [err_code] == "49" {
      mutate { add_tag => ["auth_failure"] }
    }
    if [err_code] == "0" {
      mutate { add_tag => ["success"] }
    }
    mutate {
      convert => {
        "err_code" => "integer"
        "conn_id" => "integer"
      }
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "ldap-%{+YYYY.MM.dd}"
  }
}
```

**Kibana дашборд (описание):**
- Панель "Auth Failures" — количество ошибок err=49 по времени
- Панель "Top Failed DNs" — какие DN пытались аутентифицироваться
- Панель "Slow Queries" — операции с etime > 1
- Панель "Operations/sec" — график операций по типу

### 11. Мониторинг через Loki + Promtail

```yaml
# promtail-config.yml (дополнение)
scrape_configs:
  - job_name: ldap
    static_configs:
      - targets:
          - localhost
        labels:
          job: ldap
          host: ldap-01
          __path__: /var/log/dirsrv/slapd-*/access
    pipeline_stages:
      - regex:
          expression: '.*conn=(?P<conn>\d+).*op=(?P<op>\d+).*src=(?P<src_ip>\S+).*'
      - labels:
          conn:
          op:
          src_ip:
      - regex:
          expression: '.*etime=(?P<etime>[0-9.]+).*'
      - metrics:
          ldap_search_duration:
            type: histogram
            description: "LDAP search duration in seconds"
            source: etime
            config:
              buckets: [0.1, 0.5, 1, 2, 5]
      - drop:
          expression: ".*"
          source: filename

# Grafana Query для Loki
# {job="ldap"} |= "err=49" | pattern "src=<src_ip>" | line_format "Auth failure from {{.src_ip}}"
```

### 12. Автоматический скрипт аудита безопасности

```bash
#!/bin/bash
# ldap-audit.sh — проверка конфигурации безопасности
set -euo pipefail

HOST="ldap://localhost"
BASE="dc=example,dc=com"
DN="cn=Directory Manager"
PASS=""

echo "=== LDAP Security Audit ==="

# 1. Проверка TLS
echo -n "[1] TLS: "
PORT=$(echo $HOST | grep -q ldaps && echo 636 || echo 389)
if openssl s_client -connect localhost:$PORT </dev/null 2>/dev/null | grep -q "BEGIN CERTIFICATE"; then
  echo "OK (сертификат установлен)"
else
  echo "FAIL (нет TLS)"
fi

# 2. Проверка Anonymous Bind
echo -n "[2] Anonymous Bind: "
RESULT=$(ldapsearch -x -H $HOST -b "" -s base "(objectClass=*)" namingContexts 2>/dev/null || true)
if echo "$RESULT" | grep -q "namingContexts"; then
  echo "WARN (anonymous bind работает)"
else
  echo "OK (anonymous bind отключен)"
fi

# 3. Проверка версии TLS
echo -n "[3] TLS Version: "
TLS_VER=$(openssl s_client -connect localhost:$PORT </dev/null 2>/dev/null | grep "Protocol" | awk '{print $NF}')
if [[ "$TLS_VER" == "TLSv1.2" || "$TLS_VER" == "TLSv1.3" ]]; then
  echo "OK ($TLS_VER)"
else
  echo "WARN ($TLS_VER — используйте TLS 1.2+)"
fi

# 4. Проверка порта без TLS
echo -n "[4] Unencrypted LDAP (389): "
if nc -z localhost 389 && ! echo | openssl s_client -connect localhost:389 2>/dev/null | grep -q "BEGIN"; then
  echo "WARN (порт 389 открыт без TLS)"
else
  echo "OK (не используется или шифруется)"
fi

echo "=== Audit Complete ==="
```

### Интеграция с централизованными системами

| Система | Метод | Назначение |
|:---|:---|:---|
| **Prometheus** | openldap_exporter | Метрики производительности |
| **Grafana** | Dashboard | Визуализация |
| **ELK Stack** | Filebeat | Сбор и анализ логов |
| **Grafana Loki** | Promtail | Легковесный сбор логов |
| **Zabbix** | SNMP | Мониторинг и алертинг |
| **VictoriaMetrics** | Remote Write | Хранение метрик |
| **Syslog (rsyslog/syslog-ng)** | Syslog-клиент | Централизованный сбор логов |

### См. также

- **[389DS: Обзор](./389ds/overview.md)** — логирование и мониторинг 389DS
- **[OpenLDAP: установка](./openldap_basics.md)** — настройка `cn=monitor`
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[Prometheus](../Prometheus/)** — настройка сбора метрик
- **[Grafana](../Grafana/)** — создание дашбордов
- **[ELK Stack](../ELK_Stack/)** — централизованный сбор логов
- **[LDAP: интеграция с внешними системами](./ldap_integrations.md)** — Grafana, GitLab, Vault, Keycloak
