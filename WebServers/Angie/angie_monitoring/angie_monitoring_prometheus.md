# Мониторинг Angie — интеграция с Prometheus

## Определения

**Нативный экспорт метрик** — встроенный механизм Angie (модуль `ngx_http_prometheus_module`), позволяющий серверу самостоятельно формировать и отдавать данные в текстовом формате Prometheus (Text format) или OpenMetrics. Это избавляет от необходимости развертывания промежуточных агентов (sidecar-экспортеров).

**OpenMetrics** — стандарт передачи метрик, развивающий формат Prometheus. Он включает поддержку метаданных (Unit, Help), меток (Exemplars) и более строгого синтаксиса. Angie поддерживает OpenMetrics нативно.

**Шаблоны метрик (`prometheus_all.conf`)** — конфигурационный файл, содержащий определения соответствия внутренних переменных Angie именам метрик Prometheus. Поставляется вместе с дистрибутивом и является необходимым условием для работы экспорта.

**Prometheus TSDB** — специализированное хранилище временных рядов (Time Series Database), используемое Prometheus для хранения метрик на локальном диске. Данные индексируются и сжимаются, что позволяет хранить месяцы истории на одном узле без зависимостей от внешних СУБД.

**Pull-based Monitoring** — модель сбора метрик, при которой Prometheus сам опрашивает (scrape) зарегистрированные источники метрик. В отличие от push-модели, это позволяет централизованно управлять частотой сбора и сразу обнаруживать недоступные цели.

**Scrape** — процесс опроса Prometheus одного эндпоинта экспорта метрик. Настраивается через `scrape_interval` и `scrape_timeout` в конфигурации Prometheus. При каждом scrape Prometheus выполняет HTTP GET к целевому URL и парсит полученный текст.

**Exporter** — компонент, преобразующий метрики приложения или системы в формат, понятный Prometheus. В случае с Angie экспортер встроен в сам веб-сервер; внешние экспортеры (например, `nginx-prometheus-exporter` или `node_exporter`) требуются только для систем, где нативного экспорта нет.

**Label (Метка)** — пара `key="value"`, добавляемая к каждой метрике Prometheus для идентификации измерений (например, `host`, `vhost`, `status`). Директивы Angie позволяют фильтровать метрики по статусам (`status=5xx`) или группам.

**Histogram Bucket** — интервал значений в гистограмме. Angie позволяет задавать бакеты явно через директиву `metric_zone ... histogram <bucket1> <bucket2> ...`. Prometheus ожидает дополнительный бакет `+Inf` в конце; `prometheus_all.conf` добавляет его автоматически.

**Recording Rule** — предвычисленное выражение PromQL, периодически сохраняемое как новая временная серия. Используется для оптимизации часто выполняемых запросов и сокращения времени отрисовки дашбордов.

**Alerting Rule** — правило Prometheus, генерирующее алерт, когда выражение PromQL истинно в течение заданного времени (`for`). После срабатывания алерт отправляется в Alertmanager.

**Alertmanager** — компонент экосистемы Prometheus, принимающий алерты, дедуплицирующий, группирующий и маршрутизирующий их по получателям (email, Slack, PagerDuty, webhook).

**Grafana** — платформа визуализации метрик. Для Angie существуют готовые официальные дашборды, использующие метрики, отдаваемые нативным экспортером.

**PromQL** — язык запросов к Prometheus. Позволяет выбирать, агрегировать и вычислять производные метрики (средние, процентили, скорости роста).

**Service Discovery (Сервис-дискавери)** — механизм Prometheus для автоматического обнаружения targets. В контексте bare-metal/on-premise используются статические конфигурации (`file_sd`) или DNS-дискавери; облачные механизмы не рассматриваются.

## Базовые концепции

### Архитектура сбора данных

Angie собирает данные из разделяемой памяти (Shared Memory) и преобразует их в текстовый вид при поступлении запроса от Prometheus.

```
[ Angie Shared Memory ] ──(ngx_http_prometheus_module)──> [ HTTP Response (Prometheus Format) ]
```

1. **Сбор:** Воркеры Angie обновляют счетчики в `status_zone` и `metric_zone` в реальном времени.
2. **Агрегация:** При обращении к эндпоинту экспорта модуль считывает текущие значения из памяти.
3. **Трансляция:** Данные форматируются согласно правилам из `prometheus_all.conf`.

### Типы генерируемых метрик

- **Counter (Счетчик):** Монотонно растущее значение (например, `angie_http_requests_total`).
- **Gauge (Измеритель):** Значение, которое может как расти, так и уменьшаться (например, `angie_http_connections_active`).
- **Histogram (Гистограмма):** Распределение данных по бакетам (например, `angie_metric_rt_hist_bucket`).

### Lifecycle метрики

Каждая метрика проходит жизненный цикл:

1. **Создание:** При старте Angie модуль `ngx_http_prometheus_module` создает дескрипторы метрик на основе `prometheus_all.conf`.
2. **Сбор:** Воркеры инкрементируют/обновляют значения в разделяемой памяти при каждом запросе или событии соединения.
3. **Экспорт:** При HTTP GET к эндпоинту Prometheus модуль форматирует текущие значения в Text/OpenMetrics.
4. **Сборка Prometheus:** Prometheus парсит ответ, добавляет временную метку и сохраняет в TSDB.
5. **Удаление:** На основе `scrape_interval` и `retention` старые образцы удаляются из TSDB по истечении срока хранения.

### Prometheus конфигурация и scrape-процесс

На стороне Prometheus целевой эндпоинт описывается в блоке `scrape_configs`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "angie"
    static_configs:
      - targets: ["web-01.internal:9113", "web-02.internal:9113"]
```

**Параметры:**

| Параметр | Описание |
|:---|:---|
| `scrape_interval` | Частота опроса эндпоинта (например, `15s`). При высокой нагрузке можно снизить до `5s`, но это увеличит объем TSDB. |
| `scrape_timeout` | Таймаут одного запроса. Должен быть меньше `scrape_interval` (рекомендуется `10s` при `15s` interval). |
| `metrics_path` | Путь эндпоинта (по умолчанию `/metrics`). Angie использует кастомный путь `/p8s` или `/metrics` в зависимости от конфигурации. |
| `scheme` | `http` или `https`. При доступе к Angie через внутреннюю сеть достаточно HTTP. |
| `params` | Дополнительные query-параметры, если эндпоинт поддерживает фильтрацию. |

### prometheus_all.conf и маппинг метрик

Файл `prometheus_all.conf` содержит директивы `prometheus_metric`, связывающие внутренние переменные Angie с именами метрик Prometheus. Пример фрагмента:

```nginx
prometheus_metric angie_http_requests_total type=counter help="Total number of HTTP requests" zone=status_zone;
prometheus_metric angie_http_connections_active type=gauge help="Active connections" zone=status_zone;
prometheus_metric angie_metric_rt_hist type=histogram help="Upstream response time" zone=metric_zone buckets=0.05 0.1 0.25 0.5 1 2;
```

**Правила именования:**
- Префикс `angie_` используется для всех стандартных метрик.
- Для метрик, привязанных к зоне, имя зоны добавляется как метка `zone` или `vhost` в зависимости от типа зоны.
- Метрики из `metric_zone` включают метку `key` с значением ключа агрегации.

## Практические сценарии

### Сценарий 1: Конфигурация экспорта для мониторинга кластера

Этот сценарий описывает настройку выделенного эндпоинта с ограничением доступа.

```nginx
http {
    # 1. Загрузка определений метрик (обязательно в контексте http)
    include prometheus_all.conf;

    server {
        listen 80;
        server_name example.com;
        
        # 2. Зона статуса для сбора данных по хосту
        status_zone vhost_prod;

        # 3. Эндпоинт для сбора данных (скрейпинга)
        location = /p8s {
            # Активация экспорта всех стандартных метрик
            prometheus all;
            
            # Ограничение доступа по IP (безопасность)
            allow 10.0.10.5; # IP сервера Prometheus
            deny all;
        }
    }
}
```

### Сценарий 2: Использование кастомных гистограмм для SLA

Использование `metric_zone` позволяет отслеживать время ответа бэкендов в разрезе SLO.

```nginx
http {
    include prometheus_all.conf;
    
    # Определение гистограммы для отслеживания Latency
    # Бакеты: 50мс, 100мс, 250мс, 500мс, 1с, 2с
    metric_zone api_latency:10m histogram 0.05 0.1 0.25 0.5 1 2;

    server {
        listen 80;
        
        # Запись времени ответа в гистограмму
        metric api_latency $upstream_response_time;

        location /api/ {
            proxy_pass http://backend;
        }
    }
}
```

### Сценарий 3: Фильтрация отдаваемых метрик

Для снижения нагрузки на Prometheus и уменьшения объема трафика можно отдавать только критически важные данные.

```nginx
location /metrics/critical {
    # Отдавать только метрики со статусом 5xx
    prometheus all status=5xx;
}
```

### Сценарий 4: Полная конфигурация Prometheus для кластера Angie

Настройка `prometheus.yml` для сбора метрик с нескольких экземпляров Angie.

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: "prod-web"

scrape_configs:
  - job_name: "angie"
    static_configs:
      - targets:
        - "web-01.internal:9113"
        - "web-02.internal:9113"
        - "web-03.internal:9113"
    metrics_path: "/p8s"
    scheme: "http"
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: "([^:]+)"
        replacement: "${1}"
```

**Валидация конфигурации:**
```bash
# Проверка синтаксиса Prometheus
promtool check config /etc/prometheus/prometheus.yml
# → Checking /etc/prometheus/prometheus.yml
# → SUCCESS: 0 rules found

# Проверка доступности targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
```

### Сценарий 5: Recording Rules для часто запрашиваемых агрегатов

Recording Rules позволяют предвычислять часто используемые выражения PromQL, снижая нагрузку на Prometheus и ускоряя дашборды.

```yaml
groups:
  - name: angie.rps
    interval: 15s
    rules:
      - record: angie:http_requests_per_second:rate5m
        expr: sum(rate(angie_http_requests_total[5m])) by (instance, vhost)

  - name: angie.error_rate
    interval: 30s
    rules:
      - record: angie:http_error_rate:ratio
        expr: sum(rate(angie_http_responses_total{status=~"5.."}[5m])) / sum(rate(angie_http_requests_total[5m]))
```

**Проверка:**
```bash
# Проверка синтаксиса правил
promtool check rules /etc/prometheus/rules/angie_rules.yml

# Проверка результата после загрузки
curl -s 'http://localhost:9090/api/v1/query?query=angie:http_requests_per_second:rate5m' | jq '.data.result[].value'
```

### Сценарий 6: Alerting Rules для критических порогов

Настройка алертов при превышении порогов ошибок, latency или исчерпании соединений.

```yaml
groups:
  - name: angie.alerts
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: angie:http_error_rate:ratio > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокий процент 5xx ошибок на {{ $labels.instance }}"
          description: "Error rate {{ $value }} превышает порог 5% в течение 2 минут."

      - alert: HighLatency
        expr: histogram_quantile(0.95, sum(rate(angie_metric_rt_hist_bucket[5m])) by (le, instance)) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency > 1с на {{ $labels.instance }}"
          description: "95-й персентиль latency составляет {{ $value }} секунд."

      - alert: AngieDown
        expr: up{job="angie"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Angie недоступен: {{ $labels.instance }}"
```

### Сценарий 7: Экспорт пользовательских метрик через prometheus_template

Интеграция кастомных `metric_zone` и `metric_complex_zone` с Prometheus через `prometheus_template`. Подробное описание смотри в [Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md); здесь — краткий пример.

```nginx
http {
    include prometheus_all.conf;

    prometheus_template business_metrics {
        'angie_shop_revenue_total{shop_id="$1"}' $p8s_value
            path=~^/http/metric_zones/shop_stats/metrics/([^/]+)/total_revenue$
            type=counter;

        'angie_http_vhost_latency_avg{host="$1"}' $p8s_value
            path=~^/http/metric_zones/geo_latency/metrics/([^/]+)$
            type=gauge;
    }

    server {
        listen 80;
        location /p8s {
            prometheus business_metrics;
            allow 10.0.10.5;
            deny all;
        }
    }
}
```

### Сценарий 8: Интеграция с blackbox-экспортером для внешних проверок

Проверка доступности Angie извне через blackbox-exporter (modu`blackbox_exporter`). Позволяет отслеживать не только метрики процесса, но и ответы HTTP/HTTPS.

```yaml
# blackbox.yml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      method: GET

# prometheus.yml
scrape_configs:
  - job_name: "blackbox-angie"
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - http://web-01.internal/p8s
        - http://web-02.internal/p8s
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 127.0.0.1:9115  # blackbox-exporter
```

## Диагностика и проверка

### Проверка эндпоинта вручную

Перед добавлением в Prometheus проверьте корректность ответа с помощью `curl`:

```bash
# Проверка эндпоинта и заголовка Content-Type
curl -v http://localhost/p8s

# Ожидаемый результат в теле ответа:
# HELP angie_http_requests_total Total number of HTTP requests
# TYPE angie_http_requests_total counter
# angie_http_requests_total{instance="web-01"} 12345
```

### Валидация с помощью promtool

```bash
# Проверка формата экспорта
curl -s http://localhost/p8s | promtool check metrics /dev/stdin
# → Checking /dev/stdin
# → SUCCESS: 42 metrics found
```

## Операции и команды

### Основные curl-команды для экспорта

```bash
# Проверка доступности эндпоинта Prometheus
curl -sf http://localhost/p8s | head -n 10
# → HELP angie_http_requests_total ...
# → TYPE angie_http_requests_total counter
# → angie_http_requests_total{...} 12345

# Подсчет количества уникальных метрик
curl -s http://localhost/p8s | grep -E '^[a-z_]+{' | wc -l
# → 42

# Проверка конкретной метрики
curl -s http://localhost/p8s | grep '^angie_http_requests_total'
# → angie_http_requests_total{instance="web-01",vhost="main"} 4321

# Проверка гистограммы (наличие бакетов)
curl -s http://localhost/p8s | grep 'angie_metric_rt_hist_bucket'
# → angie_metric_rt_hist_bucket{le="0.05"} 120
# → angie_metric_rt_hist_bucket{le="0.1"} 350
# → angie_metric_rt_hist_bucket{le="+Inf"} 500

# Проверка фильтрации по статусу
curl -s 'http://localhost/p8s?status=5xx' | head -n 5
# → HELP angie_http_responses_total ...
# → TYPE angie_http_responses_total counter
# → angie_http_responses_total{status="500"} 3
```

### Проверка конфигурации Angie

```bash
# Проверка включен ли модуль Prometheus
angie -V 2>&1 | grep -o 'http_prometheus_module'
# → --with-http_prometheus_module=dynamic

# Проверка наличия include prometheus_all.conf
angie -T | grep -A2 'prometheus_all'
# → /etc/angie/prometheus/prometheus_all.conf

# Проверка загруженных директив prometheus
angie -T | grep 'prometheus'
# → prometheus all;
# → metric_zone api_latency:10m histogram ...;
```

### Проверка Prometheus

```bash
# Проверка доступности targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="angie") | {instance: .labels.instance, health: .health}'
# → {"instance":"web-01.internal:9113","health":"up"}

# Проверка метрик через API Prometheus
curl -s 'http://localhost:9090/api/v1/query?query=angie_http_requests_total' | jq '.data.result[].value'
# → [["2026-09-21T11:00:00Z","4321"]]

# Проверка правил (recording + alerting)
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name | startswith("angie"))'
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
|:---|:---|:---|
| **Ошибка: `unknown directive "prometheus"`** | Модуль `ngx_http_prometheus_module` не загружен или не включен в сборку. | Проверьте вывод `angie -V` на наличие `--with-http_prometheus_module`. В официальных пакетах модуль включен по умолчанию. |
| **Пустой ответ или отсутствие метрик** | Не подключен `prometheus_all.conf` или не созданы `status_zone`. | Добавьте `include` и убедитесь, что в блоках `server` или `upstream` есть зоны. |
| **Prometheus не видит target (state=down)** | Неверный `metrics_path`, блокировка firewall или недоступность из сети Prometheus. | Проверьте `curl` с хоста Prometheus, убедитесь что порт открыт и путь совпадает с `metrics_path`. |
| **Ошибка: `parse error` в Prometheus** | Версия `prometheus_all.conf` несовместима с версией Angie или ручное редактирование сломало синтаксис. | Восстановите оригинальный `prometheus_all.conf` из пакета и проверьте конфигурацию через `angie -t`. |
| **Отсутствуют гистограммные бакеты** | Зона `metric_zone` объявлена без параметра `histogram` или бакеты не заданы. | Убедитесь, что `metric_zone` объявлена как `histogram <bucket1> <bucket2> ...` и метка записывается через `metric`. |
| **Метрики не обновляются после reload** | `prometheus all` или `include prometheus_all.conf` находятся в блоке, который не перезагружается. | Убедитесь, что директивы находятся в контексте `http` и затрагивают нужные `server` блоки. |
| **Метрики сбрасываются при restart** | Разделяемая память resides в RAM. | Это ожидаемое поведение. Для персистентности используйте внешние системы сбора (Prometheus, Grafana). |
| **High cardinality в Prometheus** | Создано слишком много уникальных ключей в `metric_zone` (например, по полному URI или User-Agent). | Ограничьте длину ключа, используйте префиксы или агрегируйте метрики на стороне Angie. |
| **Scrape timeout** | Слишком малое значение `scrape_timeout` при большом объеме метрик. | Увеличьте `scrape_timeout` до `10s` или `15s`, либо уменьшите количество экспортируемых метрик через фильтрацию. |

## Лучшие практики

### Безопасность

1. **Ограничивайте доступ к эндпоинту Prometheus** по IP или через внутреннюю сеть. Минимальная конфигурация:
   ```nginx
   location = /p8s {
       prometheus all;
       allow 10.0.10.5;
       deny all;
   }
   ```
2. **Используйте TLS** при доступе к метрикам через ненадежные каналы.
3. **Не размещайте метрики на публичных интерфейсах.** Даже без данных аутентификации, метрики раскрывают топологию и нагрузки.

### Производительность

1. **Scrape interval:** для большинства production-сценариев достаточно `15s`. Более частый сбор (`5s`) оправдан только при расследовании инцидентов.
2. **Фильтрация метрик:** используйте `prometheus all status=5xx` или именованные директивы для снижения объема передаваемых данных.
3. **Размер зон:** `status_zone` и `metric_zone` потребляют разделяемую память. Для кластеров с сотнями виртуальных хостов выделяйте от 1 МБ до 10 МБ на зону.
4. **Cardinality:** избегайте высококардинальных метрик. Максимальная длина ключа `metric_zone` — 255 символов; слишком длинные ключи обрезаются.

### Эксплуатация

1. **Именование меток:** в `metric_zone` используйте осмысленные ключи (`api_v1`, `static_files`) вместо необработанных URI.
2. **Верификация после изменений:** после добавления новых `metric_zone` проверяйте появление метрик через `curl -s http://localhost/p8s | grep <metric_name>`.
3. **Резервное копирование:** `prometheus_all.conf` поставляется с пакетом. При обновлении Angie проверяйте изменения в shipped-версии файла.
4. **Алертинг:** настраивайте алерты на основе recording rules, а не на сырые метрики, чтобы избежать флута при изменении внутренних имен метрик.

### Отладка

1. **Сравнение API и Prometheus:** при расхождениях проверяйте, что `status_zone` создана до `reload`, и что в `prometheus_all.conf` нет опечаток.
2. **Promtool:** используйте `promtool check metrics` для валидации вывода и `promtool check rules` для проверки правил.
3. **Логи Angie:** при проблемах с модулем Prometheus проверяйте `error.log` на наличие `prometheus`:
   ```bash
   grep -i prometheus /var/log/angie/error.log | tail -20
   ```

## Дополнительная информация

### Визуализация

Для быстрого старта используйте дашборд в Grafana:
- **ID:** `20719` (Официальный дашборд Angie).

### Производительность

Нативный экспорт Angie на 15–25% эффективнее внешних экспортеров, так как не требует парсинга JSON и промежуточного хранения данных в другом процессе.

### Сравнение инструментов

| Характеристика | Native Prometheus Export | Console Light / API |
|:---|:---|:---|
| **Гранулярность** | Зависит от `scrape_interval` (от 5s) | Реал-тайм (~1 сек) |
| **История** | Глубина хранения месяцы/годы (TSDB) | Отсутствует |
| **Масштаб** | Весь кластер и инфраструктура | Один узел Angie |
| **Алертинг** | Нативный (Alertmanager) | Отсутствует |
| **Overhead** | Зависит от частоты скрапинга | Минимальный (браузер опрашивает API) |
| **Назначение** | Тренды, Capacity Planning, SLA | Оперативная отладка |

### Ограничения

1. **Pull-модель:** Prometheus должен иметь сетевой доступ до эндпоинта Angie. При использовании firewall или NAT требуется проброс портов или reverse-proxy.
2. **Cardinality:** каждая уникальная комбинация меток создает отдельную временную серию. При высокой кардинальности TSDB быстро растет.
3. **Один источник:** стандартный экспорт покрывает только метрики Angie. Для метрик ОС (CPU, RAM, disk I/O) требуется отдельный `node_exporter`.
4. **Отсутствие истории при restart:** метрики в разделяемой памяти сбрасываются при `stop/start`. Это не влияет на Prometheus TSDB, но может создавать "провалы" на графиках.

### Связанные технологии

- **[Основные концепции мониторинга](./angie_monitoring_concepts.md)** — определения `status_zone`, `metric_zone`, расчет памяти
- **[Настройка Console Light и API](./angie_monitoring_console.md)** — веб-интерфейс для оперативного контроля
- **[Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md)** — `metric_zone`, `prometheus_template`, APDEX, бизнес-метрики
- **[Возможности Angie Pro](./angie_monitoring_pro.md)** — динамическое управление весами, `upstream_probe`, KV-зоны
- **[Работа с конфигурацией через API](./angie_monitoring_api.md)** — полная таблица эндпоинтов, keepalive, JSON-схемы

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Пользовательские метрики и их экспорт](./angie_monitoring_custom_metrics.md)
- [Настройка Console Light и API](./angie_monitoring_console.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
