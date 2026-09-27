# Prometheus: promtool и лучшие практики

## Определения

В данном разделе рассматриваются инструменты валидации и комплексные рекомендации по промышленной эксплуатации [Prometheus](./overview.md).

*   **`promtool`** — официальная CLI-утилита, поставляемая вместе с Prometheus. Предназначена для статической валидации конфигурации, синтаксиса правил алертинга и записи, запуска unit-тестов, а также для низкоуровневого анализа базы данных TSDB.
*   **Кардинальность (Cardinality)** — количество уникальных временных рядов (time series) в системе. Это ключевой фактор, определяющий потребление оперативной памяти и дисковой подсистемы. Подробности: [Лейблы и кардинальность](./concepts/labels_and_cardinality.md).
*   **Долгосрочное хранение (LTS)** — архитектурный паттерн выноса данных за пределы локальной TSDB для хранения метрик на протяжении месяцев и лет. Подробности: [Обзор масштабирования](./scaling/overview.md).

**См. также:** [Обзор Prometheus](./overview.md), [Конфигурация](./configuration.md), [Правила](./rules.md).

## Основные концепции

### Валидация конфигурации

Синтаксические или логические ошибки в основном конфигурационном файле (`prometheus.yml`) или в файлах правил могут привести к отказу сервиса при перезапуске или пропуску важных алертов.
В современных инфраструктурах (GitOps) статическая проверка через `promtool check config` является **обязательным** этапом конвейера CI/CD перед деплоем или вызовом HTTP-метода `/-/reload`.

### Управление ресурсами и GOMEMLIMIT

Prometheus хранит индексы и кэши в оперативной памяти. В контейнеризированных средах (Kubernetes) неконтролируемый рост памяти приводит к убийству процесса (OOMKilled).

*   **Requests & Limits:** Всегда задавайте `requests` и `limits`. Рекомендуемое соотношение для `memory` — 1:1 (Guaranteed QoS), чтобы избежать выселения (eviction) пода при перегрузке ноды.
*   **GOMEMLIMIT (Go 1.19+):** Критически важно для современных версий. Установите `GOMEMLIMIT` на 10–20% ниже `limits.memory`. Это заставит сборщик мусора (GC) работать агрессивнее при приближении к пределу, предотвращая OOM.

### Контроль кардинальности

Взрыв кардинальности (Cardinality Explosion) — основная причина падения серверов мониторинга.

**Антипаттерны в именовании лейблов (Запрещено):**
*   Уникальные бизнес-идентификаторы: `user_id`, `session_id`, `email`, `transaction_id`.
*   Сырые данные: полные URL-адреса с параметрами (`/api/v1/users/9348/profile`), хэши коммитов в каждом запросе.

**Рекомендации:**
*   Очищайте и агрегируйте данные на этапе скрапинга с помощью [Relabeling](./service_discovery_and_relabeling.md) (например, заменяйте `/api/v1/users/9348` на `/api/v1/users/:id`).
*   Используйте `promtool tsdb analyze` для регулярного офлайн-аудита базы данных и выявления метрик-рекордсменов.
*   **Native Histograms:** (Prometheus 3.0+) Переход с классических гистограмм на нативные снижает кардинальность на порядки за счет удаления лейбла `le`.

### Отказоустойчивость

Локальная TSDB спроектирована для высокой производительности записи (оперативный мониторинг), но не является распределенной. Для построения отказоустойчивых систем (HA) следует разворачивать несколько независимых инстансов Prometheus (Agent Mode или полноценных), собирающих одни и те же цели, и отправлять данные через `remote_write` в централизованное хранилище.

## Практические сценарии

### 1. Использование promtool в CI/CD

**Проверка основной конфигурации:**
```bash
promtool check config /etc/prometheus/prometheus.yml
```

**Проверка синтаксиса файлов правил:**
```bash
promtool check rules /etc/prometheus/rules/*.yml
```

**Юнит-тестирование логики алертов:**
Позволяет убедиться, что правила записи и алерты работают корректно без запуска реального сервера (требует подготовки `test.yml` с входными данными).
```bash
promtool test rules /etc/prometheus/test.yml
```

**Проверка формата метрик кастомного экспортера:**
Убедитесь, что вывод вашего скрипта соответствует спецификации OpenMetrics/Prometheus Text Format.
```bash
curl -s http://localhost:9100/metrics | promtool check metrics
```

### 2. Юнит-тестирование PromQL-правил

Тестирование правил через `promtool test rules` позволяет проверить логику без запуска реального сервера. Тест описывает входные данные (`input_series`), ожидаемые результаты recording rules (`exp_samples`) и алертов (`exp_alerts`).

**Структура тестового файла:**

```yaml
# tests/promql_tests.yml
rule_files:
  - ../rules.yml                    # Файл с тестируемыми правилами

evaluation_interval: 1m            # Интервал вычисления правил

tests:
  # --- Тест 1: Recording rule для rate() ---
  - interval: 1m
    name: "Rate calculation"
    input_series:
      - series: 'http_requests_total{job="api", instance="host1"}'
        values: '0+100x10'          # 0, 100, 200, ... 900 (100 запросов/мин)
    alert_rule_test: []             # Нет алертов для этого теста
    promql_expr_test:
      - expr: rate(http_requests_total{job="api"}[5m])
        eval_time: 5m
        exp_samples:
          - labels: '{job="api", instance="host1"}'
            value: 1.6666666666666667  # ~100/60 = 1.67 req/s

  # --- Тест 2: Alerting rule (High Error Rate) ---
  - interval: 1m
    name: "High error rate alert"
    input_series:
      # Нормальный трафик: 100 запросов/мин, 0 ошибок
      - series: 'http_requests_total{job="api", status="200"}'
        values: '0+100x10'
      # Ошибки появляются на 3-й минуте
      - series: 'http_requests_total{job="api", status="500"}'
        values: '0 0 0 30 30 30 30 30 30 30'
    alert_rule_test:
      # На 2-й минуте алерта нет (ошибок нет)
      - eval_time: 2m
        alertname: HighErrorRate
        exp_alerts: []
      # На 5-й минуте алерт срабатывает (доля > 5% в течение 5 минут)
      - eval_time: 5m
        alertname: HighErrorRate
        exp_alerts:
          - labels:
              alertname: HighErrorRate
              job: api
              severity: critical

  # --- Тест 3: Histogram quantile ---
  - interval: 1m
    name: "Latency p99 calculation"
    input_series:
      - series: 'http_request_duration_seconds_bucket{job="api", le="0.1"}'
        values: '0+50x10'
      - series: 'http_request_duration_seconds_bucket{job="api", le="0.5"}'
        values: '0+80x10'
      - series: 'http_request_duration_seconds_bucket{job="api", le="1.0"}'
        values: '0+95x10'
      - series: 'http_request_duration_seconds_bucket{job="api", le="+Inf"}'
        values: '0+100x10'
      - series: 'http_request_duration_seconds_sum{job="api"}'
        values: '0+25x10'
      - series: 'http_request_duration_seconds_count{job="api"}'
        values: '0+100x10'
    promql_expr_test:
      - expr: histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{job="api"}[5m])))
        eval_time: 5m
        exp_samples:
          - labels: '{le="0.99"}'
            value: 0.94  # p99 между 0.5 и 1.0
```

**Запуск тестов:**

```bash
# Запуск всех тестов
promtool test rules tests/promql_tests.yml
# → Unit Testing: PASS

# Запуск с подробным выводом
promtool test rules --log.level=debug tests/promql_tests.yml

# Запуск конкретного теста по имени (v3.0+)
promtool test rules --test.name="High error rate alert" tests/promql_tests.yml
```

**Формат `input_series`:**

| Синтаксис | Описание | Пример |
|:---|:---|:---|
| `0+100x10` | Старт 0, прирост 100, 10 шагов | 0, 100, 200, ... 900 |
| `0 0 0 30 30` | Явные значения через пробел | 0, 0, 0, 30, 30 |
| `0+100x5 0+50x5` | Конкатенация: 5 шагов +100, затем 5 шагов +50 | 0..400, 0..200 |

**Формат `exp_samples`:**

| Поле | Описание |
|:---|:---|
| `labels` | Лейблы ожидаемого ряда (могут отличаться от входных) |
| `value` | Ожидаемое числовое значение (допускается погрешность ~1e-6) |

### 3. Анализ состояния TSDB

Для поиска утечек кардинальности и самых "тяжёлых" метрик используйте команды, описанные в разделе [Внутреннее устройство TSDB — анализ через promtool](./concepts/tsdb.md#анализ-tsdb-с-помощью-promtool). Краткий список:

```bash
# Офлайн анализ всей базы (Prometheus должен быть остановлен или это должен быть снимок)
promtool tsdb analyze /path/to/tsdb/data

# Анализ конкретного исторического блока по его ID (например, 01G8...).
promtool tsdb analyze --block-id <block-id> /path/to/tsdb/data

# Проверка целостности индексных файлов и блоков (Corruption check)
promtool tsdb check-blocks /path/to/tsdb/data

# Дамп сырых данных (series/samples) в текстовом виде
promtool tsdb dump /path/to/tsdb/data
```

*Вывод команд покажет топ-10 метрик по количеству рядов, самые тяжёлые лейблы и общую статистику.*

### 3. Kubernetes: Оптимальная конфигурация ресурсов

Пример манифеста с учетом лучших практик (Guaranteed QoS + GOMEMLIMIT):

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: prometheus
spec:
  template:
    spec:
      containers:
      - name: prometheus
        image: prom/prometheus:v3.13.2
        env:
          - name: GOMEMLIMIT
            value: "3500MiB" # ~85% от Limits
        resources:
          requests:
            cpu: "1000m"
            memory: "4Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi" # Строгое ограничение OOM
```

## Дополнительная информация

### Сводная таблица команд promtool

| Команда | Описание |
| :--- | :--- |
| `promtool check config <file>` | Полная валидация YAML-конфигурации (в v3 проверяет UTF-8 совместимость). |
| `promtool check rules <file>` | Проверка синтаксиса файлов правил записи и оповещения. |
| `promtool test rules <file>` | Выполнение юнит-тестов (Mock data -> Expected results). Подробнее: [Юнит-тестирование PromQL](#2-юнит-тестирование-promql-правил). |
| `promtool query instant <server> <expr>` | Мгновенный запрос к Prometheus (отладка). |
| `promtool query range <server> <expr>` | Запрос диапазона (отладка графиков). |
| `promtool query diff <server> <expr1> <expr2>` | Сравнение результатов двух запросов. |
| `promtool check metrics` | Валидация формата экспозиции (через stdin). |
| `promtool tsdb analyze <path>` | Сбор статистики по кардинальности, churn rate и лейблам. Подробнее: [Внутреннее устройство TSDB](./concepts/tsdb.md#анализ-tsdb-с-помощью-promtool). |
| `promtool tsdb check-blocks <path>` | Валидация целостности данных TSDB на диске. Подробнее: [Внутреннее устройство TSDB](./concepts/tsdb.md#анализ-tsdb-с-помощью-promtool). |
| `promtool tsdb dump <path>` | Дамп сырых данных (series/samples) в текстовом виде. Подробнее: [Внутреннее устройство TSDB](./concepts/tsdb.md#анализ-tsdb-с-помощью-promtool). |

### Выбор решений для долгосрочного хранения (LTS)

| Решение | Метод интеграции | Особенности архитектуры |
| :--- | :--- | :--- |
| **[VictoriaMetrics](../VictoriaMetrics/overview.md)** | `remote_write` | Экстремально высокая плотность сжатия, монолит/кластер, низкое потребление CPU. |
| **[Thanos](./scaling/thanos_overview.md)** | Sidecar + Object Storage (S3) | Идеально для работы с дешевыми облачными хранилищами, объединение данных "на лету". |
| **[Grafana Mimir](../Mimir/mimir_overview.md)** | `remote_write` | Cloud-native микросервисная архитектура, нативная мульти-тенантность. |

Подробное сравнение приведено в разделе [Решения для масштабирования](./scaling/overview.md#решения-для-долгосрочного-хранения-long-term-storage).
