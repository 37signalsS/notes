# FTP: Мониторинг и логирование

---

## Определения

**Мониторинг** — процесс сбора, анализа и визуализации метрик состояния системы для обеспечения её работоспособности, производительности и безопасности.

**Prometheus** — система мониторинга и алертинга с открыт исходным кодом, собирающая метрики через HTTP и хранящая их в временно́м ряде. Стандарт для云原生 мониторинга.

**Exporter** — компонент, преобразующий метрики приложения в формат Prometheus. Для FTP используется `vsftpd_exporter` или кастомные скрипты.

**Alertmanager** — компонент Prometheus для маршрутизации и отправки алертов через различные каналы (email, Slack, Telegram).

**Loki** — система агрегации логов от Grafana, индексирующая только метки (без полнотекстового поиска). Легковесная альтернатива ELK.

**Grafana** — платформа для визуализации данных и построения дашбордов. Поддерживает Prometheus, Loki, Elasticsearch и другие источники.

---

## Основные концепции

### Архитектура мониторинга FTP

```
┌─────────────────────────────────────────────────────────────┐
│                     Monitoring Stack                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   vsftpd     │    │  Prometheus  │    │   Grafana    │  │
│  │   (logs)     │    │  (metrics)   │    │  (dashboard) │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │          │
│         ▼                   ▼                   ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │    Loki      │    │ Alertmanager │    │   Dashboards │  │
│  │  (logs)      │    │  (alerts)    │    │   (visual)   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Метрики для мониторинга

**Системные метрики:**
- `vsftpd_connections_total` — общее количество соединений
- `vsftpd_connections_active` — активные соединения
- `vsftpd_bytes_transferred_total` — объём переданных данных
- `vsftpd_errors_total` — количество ошибок
- `vsftpd_uptime_seconds` — время работы сервера

**Бизнес-метрики:**
- `vsftpd_users_active` — количество активных пользователей
- `vsftpd_transfers_in_progress` — текущие передачи
- `vsftpd_bandwidth_usage_bytes` — использование пропускной способности

**Системные метрики Linux:**
- `node_cpu_seconds_total` — использование CPU
- `node_memory_MemAvailable_bytes` — доступная память
- `node_filesystem_avail_bytes` — доступное место на диске
- `node_network_receive_bytes_total` — сетевой трафик

### Уровни логирования

| Уровень | Описание | Использование |
| :--- | :--- | :--- |
| **ERROR** | Критические ошибки | Алертинг |
| **WARNING** | Предупреждения | Мониторинг |
| **INFO** | Информационные сообщения | Аудит |
| **DEBUG** | Отладочная информация | Траблшутинг |

---

## Практические сценарии

### 1. Настройка логирования vsftpd

#### Конфигурация логов

```bash
# /etc/vsftpd.conf
# Основные логи
xferlog_enable=YES
xferlog_file=/var/log/xferlog
vsftpd_log_file=/var/log/vsftpd.log

# Детальное логирование FTP-команд
log_ftp_protocol=YES

# Логирование TLS
debug_ssl=YES
```

#### Формат логов vsftpd

```
# /var/log/vsftpd.log
Tue Sep 14 10:00:01 2026 [pid 12345] [ftpuser] OK UPLOAD: Client "10.0.0.1", "/upload/file.txt", 1024 bytes, 0.12 secs
Tue Sep 14 10:05:02 2026 [pid 12346] [ftpuser] OK DOWNLOAD: Client "10.0.0.1", "/upload/file.txt", 1024 bytes, 0.10 secs
Tue Sep 14 10:10:03 2026 [pid 12347] [anonymous] FAIL LOGIN: Client "10.0.0.2", "Invalid password"
```

#### Формат xferlog

```
# /var/log/xferlog
Tue Sep 14 10:00:01 2026 1 10.0.0.1 1024 /upload/file.txt b _ o r ftpuser ftp 0 * c
Tue Sep 14 10:05:02 2026 0 10.0.0.1 1024 /upload/file.txt b _ o r ftpuser ftp 0 * c
```

### 2. Интеграция с Loki (сбор логов)

#### Установка Promtail

```yaml
# promtail-config.yml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: vsftpd
    static_configs:
      - targets:
          - localhost
        labels:
          job: vsftpd
          host: ftp-server
          __path__: /var/log/vsftpd.log
    pipeline_stages:
      - regex:
          expression: '^(?P<timestamp>\w+ \w+ \d+ \d+:\d+:\d+ \d+) \[pid \d+\] \[(?P<user>\w+)\] (?P<status>\w+ \w+): (?P<message>.*)'
      - labels:
          user:
          status:
      - timestamp:
          source: timestamp
          format: "Jan _2 15:04:05 2006"
```

#### Docker Compose для стека

```yaml
# docker-compose-monitoring.yml
version: '3.8'

services:
  loki:
    image: grafana/loki:latest
    container_name: loki
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
    command: -config.file=/etc/loki/local-config.yaml

  promtail:
    image: grafana/promtail:latest
    container_name: promtail
    volumes:
      - ./promtail-config.yml:/etc/promtail/config.yml
      - /var/log:/var/log:ro
      - /var/log/vsftpd.log:/var/log/vsftpd.log:ro
    command: -config.file=/etc/promtail/config.yml

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

volumes:
  grafana-data:
```

### 3. Настройка Prometheus

#### Конфигурация

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "ftp_alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

scrape_configs:
  - job_name: 'vsftpd'
    static_configs:
      - targets: ['ftp-server:9100']
    metrics_path: '/metrics'
    
  - job_name: 'node'
    static_configs:
      - targets: ['ftp-server:9100']
```

#### Alert rules

```yaml
# ftp_alerts.yml
groups:
  - name: ftp_alerts
    rules:
      - alert: FTPDown
        expr: up{job="vsftpd"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "FTP server is down"
          description: "FTP server {{ $labels.instance }} has been down for more than 1 minute."
          
      - alert: FTPHighConnections
        expr: vsftpd_connections_active > 40
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High number of FTP connections"
          description: "FTP server {{ $labels.instance }} has {{ $value }} active connections."
          
      - alert: FTPHighBandwidth
        expr: rate(vsftpd_bytes_transferred_total[5m]) > 100000000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High FTP bandwidth usage"
          description: "FTP server {{ $labels.instance }} is using {{ $value }} bytes/sec."
```

### 4. Дашборд Grafana

#### Импорт дашборда

```bash
# Основные панели
- FTP Connections (line chart)
- FTP Bandwidth (line chart)
- FTP Errors (stat)
- FTP Uptime (stat)
- FTP Users Active (gauge)
- FTP Transfers (bar chart)
```

#### Прометеус-запросы для дашборда

```promql
# Активные соединения
vsftpd_connections_active

# Пропускная способность (байт/сек)
rate(vsftpd_bytes_transferred_total[5m])

# Ошибки в минуту
rate(vsftpd_errors_total[1m])

# Процент ошибок
rate(vsftpd_errors_total[5m]) / rate(vsftpd_connections_total[5m]) * 100

# Активные пользователи
vsftpd_users_active
```

### 5. Аудит действий пользователей

#### Скрипт аудита

```bash
#!/bin/bash
# /usr/local/bin/ftp_audit.sh
LOG_FILE="/var/log/vsftpd_audit.log"

# Парсинг лога vsftpd
grep -E "OK|FAIL" /var/log/vsftpd.log | while read line; do
    TIMESTAMP=$(echo $line | awk '{print $1, $2, $3, $4}')
    USER=$(echo $line | grep -oP '\[\K[^\]]+' | head -1)
    ACTION=$(echo $line | grep -oP '(OK|FAIL) \K\w+')
    CLIENT=$(echo $line | grep -oP 'Client "\K[^"]+')
    FILE=$(echo $line | grep -oP '"\K[^"]+' | tail -1)
    
    echo "$TIMESTAMP | USER=$USER | ACTION=$ACTION | CLIENT=$CLIENT | FILE=$FILE" >> $LOG_FILE
done
```

#### Cron job

```bash
# /etc/cron.d/ftp_audit
*/5 * * * * root /usr/local/bin/ftp_audit.sh
```

---

## Дополнительная информация

### Диагностика

```bash
# Проверка логов vsftpd
sudo tail -f /var/log/vsftpd.log
sudo journalctl -u vsftpd -f

# Проверка Prometheus метрик
curl http://localhost:9100/metrics | grep vsftpd

# Проверка Loki запросов
curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode 'query={job="vsftpd"} |~ "FAIL"' \
  --data-urlencode 'start=1h'

# Проверка Grafana
curl -s http://admin:admin@localhost:3000/api/search?query=FTP
```

### Частые ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Нет метрик** | Экспортер не запущен | Проверьте `node_exporter` или `vsftpd_exporter` |
| **Логи не собираются** | Promtail не видит файл | Проверьте volume mounts и права |
| **Алерты не приходят** | Alertmanager не настроен | Проверьте `alerting` в prometheus.yml |
| **Дашборд пустой** | Нет данных в Prometheus | Проверьте `scrape_configs` |

### Рекомендации

1. **Структурированные логи:** Используйте JSON-формат для удобного парсинга.
2. **Централизация:** Собирайте логи в Loki/ELK для поиска и анализа.
3. **Алертинг:** Настройте алерты на критические события (down, high errors).
4. **Retention:** Настройте хранение метрик и логов (30 дней для Prometheus, 7 дней для Loki).
5. **Безопасность:** Ограничьте доступ к Grafana и Prometheus через OAuth/Proxy.

### Связанные темы

- **[Prometheus: обзор](../../../Prometheus/prometheus_overview.md)** — архитектура Prometheus
- **[Grafana: обзор](../../../Grafana/grafana_overview.md)** — визуализация данных
- **[Loki: обзор](../../../Loki/loki_overview.md)** — агрегация логов
- **[vsftpd: настройка](./vsftpd_setup.md)** — базовая конфигурация vsftpd
