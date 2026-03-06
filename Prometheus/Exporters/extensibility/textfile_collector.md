# Textfile Collector

## Определения

**Textfile Collector** — механизм `node_exporter` для сбора произвольных метрик, предоставляемых внешними скриптами или приложениями.

## Принцип работы

1. Внешний скрипт (например, на Python или Bash) выполняется по расписанию (cron)
2. Скрипт выполняет свою логику: парсит логи, опрашивает оборудование, проверяет статус сервиса
3. Результат записывается в виде метрик в текстовый файл с расширением `.prom` в специальную директорию
4. `node_exporter` автоматически читает все `.prom` файлы из этой директории и добавляет метрики к общему выводу на `/metrics`

## Практические сценарии

### Пример 1: Базовое использование

**Создаем файл с метрикой:**

```bash
mkdir -p /var/lib/prometheus/node-exporter
cat <<EOF > /var/lib/prometheus/node-exporter/custom_metric.prom
# TYPE my_custom_metric counter
# HELP my_custom_metric This is a custom metric.
my_custom_metric 100
EOF
```

**Настраиваем node_exporter:**

```bash
# /etc/sysconfig/node_exporter
OPTIONS="--collector.textfile.directory=/var/lib/prometheus/node-exporter"
```

**Перезапускаем node_exporter:**

```bash
systemctl restart node_exporter
```

**Проверяем:**

```bash
curl -s http://localhost:9100/metrics | grep my_custom_metric
```

### Пример 2: Скрипт сбора метрик версии приложения

**Bash-скрипт (`/usr/local/bin/app_version_exporter.sh`):**

```bash
#!/bin/bash

METRIC_FILE="/var/lib/prometheus/node-exporter/app_version.prom"
APP_VERSION=$(curl -s http://localhost:8080/version | jq -r '.version')
BUILD_DATE=$(curl -s http://localhost:8080/version | jq -r '.build_date')

cat > $METRIC_FILE <<EOF
# HELP app_version_info Информация о версии приложения
# TYPE app_version_info gauge
app_version_info{version="${APP_VERSION}",build_date="${BUILD_DATE}"} 1
EOF
```

**Добавляем в cron (каждые 5 минут):**

```bash
*/5 * * * * /usr/local/bin/app_version_exporter.sh
```

### Пример 3: Мониторинг SSL-сертификатов

**Скрипт (`/usr/local/bin/ssl_expiry_exporter.sh`):**

```bash
#!/bin/bash

METRIC_FILE="/var/lib/prometheus/node-exporter/ssl_expiry.prom"
DOMAIN="example.com"
PORT="443"

# Получаем дату истечения сертификата
EXPIRY_DATE=$(echo | openssl s_client -servername $DOMAIN -connect $DOMAIN:$PORT 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
EXPIRY_TIMESTAMP=$(date -d "$EXPIRY_DATE" +%s 2>/dev/null)
CURRENT_TIMESTAMP=$(date +%s)
DAYS_LEFT=$(( (EXPIRY_TIMESTAMP - CURRENT_TIMESTAMP) / 86400 ))

cat > $METRIC_FILE <<EOF
# HELP ssl_cert_expiry_days Дней до истечения SSL-сертификата
# TYPE ssl_cert_expiry_days gauge
ssl_cert_expiry_days{domain="$DOMAIN"} $DAYS_LEFT

# HELP ssl_cert_expiry_timestamp Timestamp истечения SSL-сертификата
# TYPE ssl_cert_expiry_timestamp gauge
ssl_cert_expiry_timestamp{domain="$DOMAIN"} $EXPIRY_TIMESTAMP
EOF
```

### Пример 4: Мониторинг резервного копирования

**Скрипт (`/usr/local/bin/backup_status_exporter.sh`):**

```bash
#!/bin/bash

METRIC_FILE="/var/lib/prometheus/node-exporter/backup_status.prom"
BACKUP_DIR="/var/backups"

# Находим последний файл бэкапа
LAST_BACKUP=$(ls -t $BACKUP_DIR/*.tar.gz 2>/dev/null | head -1)

if [ -n "$LAST_BACKUP" ]; then
    LAST_BACKUP_TIME=$(stat -c %Y "$LAST_BACKUP")
    BACKUP_SIZE=$(stat -c %s "$LAST_BACKUP")
    BACKUP_AGE=$(( $(date +%s) - LAST_BACKUP_TIME ))
    STATUS=1
else
    LAST_BACKUP_TIME=0
    BACKUP_SIZE=0
    BACKUP_AGE=0
    STATUS=0
fi

cat > $METRIC_FILE <<EOF
# HELP backup_last_success_timestamp Timestamp последнего успешного бэкапа
# TYPE backup_last_success_timestamp gauge
backup_last_success_timestamp $LAST_BACKUP_TIME

# HELP backup_last_size_bytes Размер последнего бэкапа в байтах
# TYPE backup_last_size_bytes gauge
backup_last_size_bytes $BACKUP_SIZE

# HELP backup_age_seconds Возраст последнего бэкапа в секундах
# TYPE backup_age_seconds gauge
backup_age_seconds $BACKUP_AGE

# HELP backup_status Статус бэкапа (1=успешно, 0=нет бэкапа)
# TYPE backup_status gauge
backup_status $STATUS
EOF
```

**Алерт в Prometheus (бэкап старше 24 часов):**

```yaml
- alert: BackupTooOld
  expr: backup_age_seconds > 86400
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Резервная копия устарела"
    description: "Последний бэкап был создан более 24 часов назад"
```

### Пример 5: Сбор метрик из логов

**Скрипт (`/usr/local/bin/log_metrics_exporter.sh`):**

```bash
#!/bin/bash

METRIC_FILE="/var/lib/prometheus/node-exporter/app_logs.prom"
LOG_FILE="/var/log/myapp/application.log"

# Считаем количество ошибок за последние 5 минут
ERROR_COUNT=$(grep -c "ERROR" $LOG_FILE 2>/dev/null || echo 0)
WARN_COUNT=$(grep -c "WARN" $LOG_FILE 2>/dev/null || echo 0)

cat > $METRIC_FILE <<EOF
# HELP app_log_errors_total Количество ошибок в логе
# TYPE app_log_errors_total counter
app_log_errors_total $ERROR_COUNT

# HELP app_log_warnings_total Количество предупреждений в логе
# TYPE app_log_warnings_total counter
app_log_warnings_total $WARN_COUNT
EOF
```

## Формат файлов `.prom`

**Правила:**

* Файл должен иметь расширение `.prom`
* Каждая метрика должна иметь `# HELP` и `# TYPE`
* Поддерживаемые типы: `counter`, `gauge`, `histogram`, `summary`
* Имена метрик: нижний регистр, `[a-zA-Z0-9_:]`
* Зарезервированные суффиксы: `_total`, `_sum`, `_count`, `_bucket`, `_info`

**Пример корректного файла:**

```prom
# HELP http_requests_total Общее количество HTTP-запросов
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/api"} 1500
http_requests_total{method="POST",path="/api"} 300

# HELP http_request_duration_seconds Время обработки запроса
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.1"} 1000
http_request_duration_seconds_bucket{le="0.5"} 1400
http_request_duration_seconds_bucket{le="1.0"} 1480
http_request_duration_seconds_bucket{le="+Inf"} 1500
http_request_duration_seconds_sum 450.5
http_request_duration_seconds_count 1500

# HELP app_memory_usage_bytes Использование памяти приложением
# TYPE app_memory_usage_bytes gauge
app_memory_usage_bytes 524288000
```

## Связанные темы

* [Node Exporter](../node_exporter.md) — основной экспортер для Linux
* [Расширяемость экспортеров](./concepts.md) — базовые концепции
* [Создание собственных экспортеров](./custom_exporters.md) — написание экспортеров на Go и Python
