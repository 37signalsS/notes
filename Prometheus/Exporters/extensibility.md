# Расширяемость экспортеров Prometheus

## Определения

**Расширяемость экспортеров** — возможность добавления произвольных метрик в Prometheus через внешние скрипты или создания собственных экспортеров с использованием клиентских библиотек.

## Textfile Collector

### Определения

**Textfile Collector** — механизм `node_exporter` для сбора произвольных метрик, предоставляемых внешними скриптами или приложениями.

### Принцип работы

1. Внешний скрипт (например, на Python или Bash) выполняется по расписанию (cron)
2. Скрипт выполняет свою логику: парсит логи, опрашивает оборудование, проверяет статус сервиса
3. Результат записывается в виде метрик в текстовый файл с расширением `.prom` в специальную директорию
4. `node_exporter` автоматически читает все `.prom` файлы из этой директории и добавляет метрики к общему выводу на `/metrics`

### Практические сценарии

#### Пример 1: Базовое использование

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

#### Пример 2: Скрипт сбора метрик версии приложения

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

#### Пример 3: Мониторинг SSL-сертификатов

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

#### Пример 4: Мониторинг резервного копирования

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

#### Пример 5: Сбор метрик из логов

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

### Формат файлов `.prom`

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

## Написание собственных экспортеров

### Общие рекомендации

#### Именование метрик

* **Нижний регистр:** `[a-zA-Z0-9_:]`
* **Суффиксы:**
  * `_total` — для counter (обязательно)
  * `_sum`, `_count`, `_bucket` — для histogram
  * `_info` — для метрик с информацией (версия, конфигурация)
* **Префиксы:** избегать `process_`, `scrape_` (зарезервированы)
* **Единицы измерения:** включать в название (`_seconds`, `_bytes`, `_count`)

**Примеры правильных имён:**

```
nginx_http_request_duration_seconds
mysql_queries_total
app_memory_usage_bytes
node_cpu_seconds_total
```

#### Выбор labels

* **Не использовать** в лейблах: `region`, `zone`, `cluster`, `az`, `datacenter`, `customer` — это задача [Service Discovery](../service_discovery_and_relabeling.md)
* **Избегать высокой кардинальности:** не использовать `request_id`, `user_id`, `email`
* **Метрика должна иметь смысл при агрегации:** не разделять `read/write` с помощью лейбла, лучше сделать две разные метрики

**Примеры правильных лейблов:**

```
http_requests_total{method="GET",status="200"}
mysql_queries_total{database="users"}
```

**Примеры неправильных лейблов:**

```
http_requests_total{request_id="abc123"}     # Высокая кардинальность
user_actions_total{user_email="..."}         # Высокая кардинальность
```

#### Рекомендации по коду

* Получение данных должно происходить только в момент скрапинга Prometheus'ом
* Не выставлять временные метки (timestamp), это задача Prometheus
* Выбирать порт с учетом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
* Использовать стандартные порты (диапазон 9100-9200)

### Пример экспортера на Go

**Простейший экспортер, который инкрементирует счетчик каждые 2 секунды:**

**Код (`example_exporter.go`):**

```go
package main

import (
        "net/http"
        "time"
        log "github.com/sirupsen/logrus"

        "github.com/prometheus/client_golang/prometheus"
        "github.com/prometheus/client_golang/prometheus/promhttp"
        "github.com/prometheus/client_golang/prometheus/promauto"
)

func recordMetrics() {
        go func() {
                for {
                        opsProcessed.Inc()
                        time.Sleep(2 * time.Second)
                }
        }()
}

var (
        opsProcessed = promauto.NewCounter(prometheus.CounterOpts{
                Name: "example_exporter_processed_ops_total",
                Help: "The total number of processed events",
        })
)

func main() {
        recordMetrics()

        http.Handle("/metrics", promhttp.Handler())
        log.Info("Beginning to serve on port :2112")
        log.Fatal(http.ListenAndServe(":2112", nil))
}
```

**Установка зависимостей и запуск:**

```bash
# Инициализация модуля
go mod init example_exporter

# Установка зависимостей
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
go get github.com/prometheus/client_golang/prometheus/promauto
go get github.com/sirupsen/logrus

# Запуск
go run example_exporter.go
```

**Проверка:**

```bash
curl http://localhost:2112/metrics
```

### Пример экспортера на Python

**Использование библиотеки `prometheus_client`:**

```python
#!/usr/bin/env python3

from prometheus_client import start_http_server, Counter, Gauge
import time
import random

# Создаем метрики
REQUESTS = Counter('http_requests_total', 'Total HTTP requests', ['method'])
MEMORY = Gauge('app_memory_usage_bytes', 'Memory usage in bytes')

def collect_metrics():
    """Сбор метрик"""
    while True:
        # Эмулируем сбор метрик
        MEMORY.set(random.randint(100000000, 500000000))
        time.sleep(5)

if __name__ == '__main__':
    # Запускаем HTTP-сервер
    start_http_server(8000)
    
    # Запускаем сбор метрик в фоне
    import threading
    threading.Thread(target=collect_metrics, daemon=True).start()
    
    # Эмулируем обработку запросов
    while True:
        method = random.choice(['GET', 'POST', 'PUT', 'DELETE'])
        REQUESTS.labels(method=method).inc()
        time.sleep(1)
```

**Установка и запуск:**

```bash
pip install prometheus_client
python example_exporter.py
```

### Клиентские библиотеки

| Язык | Репозиторий | Документация |
| :--- | :--- | :--- |
| Go | [prometheus/client_golang](https://github.com/prometheus/client_golang) | [pkg.go.dev](https://pkg.go.dev/github.com/prometheus/client_golang) |
| Python | [prometheus/client_python](https://github.com/prometheus/client_python) | [pypi.org](https://pypi.org/project/prometheus-client/) |
| Java | [prometheus/client_java](https://github.com/prometheus/client_java) | [github.com](https://github.com/prometheus/client_java) |
| JavaScript | [siimon/prom-client](https://github.com/siimon/prom-client) | [npmjs.com](https://www.npmjs.com/package/prom-client) |
| Ruby | [prometheus/client_ruby](https://github.com/prometheus/client_ruby) | [rubygems.org](https://rubygems.org/gems/prometheus-client) |
| .NET | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | [nuget.org](https://www.nuget.org/packages/prometheus-net) |

## Дополнительная информация

### Связанные темы

* [Node Exporter](./node_exporter.md) — основной экспортер для Linux
* [Service Discovery и Relabeling](../service_discovery_and_relabeling.md)
* [Лейблы и кардинальность](../concepts/labels_and_cardinality.md)
* [Типы метрик](../concepts/metric_types.md)

### Официальные ресурсы

* [Instrumenting Client Libraries](https://prometheus.io/docs/instrumenting/clientlibs/)
* [Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
