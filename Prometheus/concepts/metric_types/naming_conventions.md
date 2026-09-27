# Соглашения по именованию метрик Prometheus

## Определения

**Соглашения по именованию метрик** — это набор правил и рекомендаций по присвоению имён, суффиксов и лейблов метрикам в [Prometheus](../../overview.md), обеспечивающий единообразие, предсказуемость и совместимость в экосистеме мониторинга.

Правильное именование критично для: автоматического определения типа метрики по имени, корректной работы функций PromQL (`rate()`, `histogram_quantile()`), интеграции с Grafana (автоматические префиксы единиц), и interoperability с OpenTelemetry и другими системами мониторинга.

## Основные концепции

### Регулярное выражение для имён

Имена метрик и лейблов в Prometheus должны соответствовать регулярному выражению:

```text
[a-zA-Z_:][a-zA-Z0-9_:]*
```

- Первый символ — буква, цифра или подчёркивание/двоеточие.
- Допустимы: латинские буквы, цифры, `_`, `:`.
- Запрещены: кириллица, пробелы, точки, дефисы, спецсимволы.
- **Prometheus v3.0+:** полная поддержка UTF-8 через `escaping=allow-utf-8` в заголовке `Accept`. Позволяет использовать любые символы, включая кириллицу и точки (для совместимости с OpenTelemetry).

### Структура имени метрики

Имя метрики состоит из трёх частей:

```text
<namespace>_<subsystem>_<name>_<unit>_<suffix>
```

| Часть | Обязательность | Описание | Пример |
|:---|:---|:---|:---|
| **namespace** | Рекомендуется | Общее пространство имён (название приложения или экспортёра) | `node_`, `http_`, `process_` |
| **subsystem** | Опционально | Подсистема внутри namespace | `node_filesystem_`, `http_request_` |
| **name** | Обязательно | Описательное имя метрики | `http_request_duration` |
| **unit** | Рекомендуется | Базовая единица измерения | `_seconds`, `_bytes` |
| **suffix** | Обязательно для Counter | Суффикс типа метрики | `_total`, `_bucket`, `_info` |

**Примеры разбора:**

| Полное имя | namespace | subsystem | name | unit | suffix |
|:---|:---|:---|:---|:---|:---|
| `http_request_duration_seconds` | `http` | `request` | `duration` | `seconds` | — |
| `node_network_receive_bytes_total` | `node` | `network` | `receive` | `bytes` | `total` |
| `process_resident_memory_bytes` | `process` | — | `resident_memory` | `bytes` | — |
| `myapp_orders_completed_total` | `myapp` | — | `orders_completed` | — | `total` |

### Суффиксы по типам метрик

Каждый тип метрики имеет обязательные или рекомендуемые суффиксы:

| Тип метрики | Обязательный суффикс | Описание | Пример |
|:---|:---|:---|:---|
| **Counter** | `_total` | Кумулятивный счётчик. Суффикс обязателен — без него `rate()` и `increase()` не будут работать корректно. | `http_requests_total` |
| **Gauge** | Нет обязательного | Значение произвольно меняется. Суффикс определяет единицу. | `node_memory_MemAvailable_bytes` |
| **Histogram** | `_bucket`, `_sum`, `_count` (автоматические) | Суффиксы добавляются библиотекой. Базовое имя — без суффиксов. | `http_request_duration_seconds` → `_bucket`, `_sum`, `_count` |
| **Summary** | `{quantile}`, `_sum`, `_count` (автоматические) | Квантили через лейбл, `_sum`/`_count` — автоматические. | `http_request_duration_seconds{quantile="0.99"}` |
| **Info** | `_info` | Метрика-индикатор (значение всегда 1, полезная информация — в лейблах). | `app_build_info` |
| **Stateset** | Нет обязательного | Множественные состояния через лейбл. | `node_systemd_unit_state` |

### Базовые единицы измерения

Prometheus использует **базовые единицы** (base units), а не производные. Это обеспечивает автоматическое масштабирование в Grafana и совместимость между сервисами.

| Величина | Базовая единица | Суффикс метрики | НЕ используйте |
|:---|:---|:---|:---|
| Время | секунды | `_seconds` | `_ms`, `_minutes`, `_hours` |
| Размер / объём | байты | `_bytes` | `_kb`, `_mb`, `_gb`, `_bits` |
| Температура | градусы Цельсия | `_celsius` | `_fahrenheit` |
| Доля / вероятность | ratio (0..1) | `_ratio` | `_percent` (для хранения) |
| Вес | граммы | `_grams` | `_kg`, `_tonnes` |

**Правило:** Всегда храните в метрике базовую единицу. Конвертацию в `ms`, `KiB`, `%` выполняйте на уровне PromQL или в Grafana через `unit` датасурса.

**Пример:**
```promql
# Неправильно: метрика хранит миллисекунды
http_request_duration_ms

# Правильно: метрика хранит секунды, конвертация в PromQL
http_request_duration_seconds * 1000  # → результат в ms
```

### Именование лейблов

Лейблы добавляют контекст к метрикам. Правила именования лейблов критичны для производительности и читаемости:

| Правило | Описание | Пример |
|:---|:---|:---|
| **snake_case** | Имена лейблов — в нижнем регистре с подчёркиваниями. | `status_code`, `method`, `instance` |
| **Низкая кардинальность** | Каждая уникальная комбинация лейблов создаёт отдельный временной ряд. Избегайте `user_id`, `request_id`, `session_id`. | `job`, `method`, `status_code` — хорошо; `user_id` — плохо |
| **Избегайте зарезервированных лейблов** | `__name__`, `job`, `instance` — управляются Prometheus автоматически. Не используйте их в коде приложения. | — |
| **Статические vs динамические** | Статические лейблы (версия, окружение) допустимы. Динамические (ID пользователей) — только если кардинальность контролируется. | `env="prod"` — хорошо; `trace_id="abc"` — плохо |
| **Единообразие значений** | Используйте консистентные значения: lowercase, без пробелов, стандартные слова. | `method="GET"`, `status="success"` |

### Паттерны именования для стандартных метрик

| Паттерн | Описание | Пример |
|:---|:---|:---|
| `<noun>_total` | Кумулятивный счётчик событий | `http_requests_total`, `disk_reads_total` |
| `<noun>_bytes` | Текущее значение в байтах (Gauge) | `node_memory_MemAvailable_bytes`, `process_resident_memory_bytes` |
| `<noun>_seconds` | Временна́я величина в секундах (Gauge или Histogram) | `http_request_duration_seconds`, `process_start_time_seconds` |
| `<noun>_ratio` | Доля от 0 до 1 (Gauge) | `node_cpu_seconds_total` (режим → ratio через rate) |
| `<noun>_info` | Статическая информация (Gauge = 1) | `app_build_info{version="1.2.3"}` |
| `<subsystem>_<metric>` | Подсистема через подчёркивание | `node_filesystem_free_bytes`, `container_cpu_usage_seconds_total` |

### Порядок слов в имени

Следуйте паттерну **что_измеряется_в_чём**:

```text
<объект>_<свойство>_<единица>
```

| Объект | Свойство | Единица | Результат |
|:---|:---|:---|:---|
| `http_request` | `duration` | `seconds` | `http_request_duration_seconds` |
| `node_filesystem` | `free` | `bytes` | `node_filesystem_free_bytes` |
| `container_cpu` | `usage` | `seconds` | `container_cpu_usage_seconds_total` |
| `process_resident_memory` | — | `bytes` | `process_resident_memory_bytes` |

**Антипаттерн:** `http_seconds_request_duration` — неправильный порядок, нарушает читаемость.

### Метрики-счётчики vs метрики-значения

| Паттерн | Тип | Суффикс | Пример |
|:---|:---|:---|:---|
| Количество событий | Counter | `_total` | `http_requests_total` |
| Размер / объём | Gauge или Counter | `_bytes` | `node_memory_MemAvailable_bytes` (Gauge), `node_network_receive_bytes_total` (Counter) |
| Время выполнения | Histogram или Summary | `_seconds` | `http_request_duration_seconds` |
| Текущее состояние | Gauge | без суффикса или `_bytes`/`_seconds` | `up`, `node_load1` |
| Информация | Gauge (=1) | `_info` | `app_build_info` |

## Практические сценарии

### Сценарий 1: Правильное именование HTTP-метрик

Для HTTP-сервиса стандартный набор метрик с корректными именами:

```go
// REQUESTS — Counter: количество запросов по методам и статусам
http_requests_total{method="GET", status_code="200", handler="/api/users"}

// LATENCY — Histogram: распределение длительности запросов
http_request_duration_seconds{method="GET", handler="/api/users"}

// IN-FLIGHT — Gauge: количество текущих обрабатываемых запросов
http_requests_in_flight{handler="/api/users"}

// RESPONSE SIZE — Histogram: распределение размеров ответов
http_response_size_bytes{method="GET", handler="/api/users"}
```

**Почему так:**
- `http_requests_total` — Counter с `_total`, агрегируется через `rate()`.
- `http_request_duration_seconds` — Histogram в секундах (базовая единица), агрегируется через `histogram_quantile()`.
- `http_requests_in_flight` — Gauge, потому что значение уменьшается при завершении запроса.
- `http_response_size_bytes` — Histogram в байтах, показывает распределение размеров ответов.

### Сценарий 2: Метрики基础设施 (node_exporter-style)

```text
# CPU — Counter (только растёт, сбрасывается при рестарте)
node_cpu_seconds_total{mode="idle", cpu="0"}
node_cpu_seconds_total{mode="user", cpu="0"}

# Память — Gauge (текущее состояние)
node_memory_MemTotal_bytes
node_memory_MemAvailable_bytes

# Диск — Counter (трафик) и Gauge (состояние)
node_disk_read_bytes_total{device="sda"}
node_disk_written_bytes_total{device="sda"}
node_filesystem_free_bytes{mountpoint="/", device="/dev/sda1"}
node_filesystem_files_free{mountpoint="/"}

# Сеть — Counter (трафик)
node_network_receive_bytes_total{device="eth0"}
node_network_transmit_bytes_total{device="eth0"}

# Загрузка — Gauge (мгновенное значение)
node_load1
node_load5
node_load15
```

### Сценарий 3: Метрики контейнеров (cadvisor-style)

```text
# CPU — Counter (кумулятивное потребление)
container_cpu_usage_seconds_total{container="nginx", pod="web-01", namespace="production"}
container_cpu_cfs_throttled_seconds_total{container="nginx", pod="web-01"}

# Память — Gauge (текущее потребление)
container_memory_working_set_bytes{container="nginx", pod="web-01"}
container_memory_rss{container="nginx", pod="web-01"}

# Сеть — Counter (трафик)
container_network_receive_bytes_total{interface="eth0", pod="web-01"}
container_network_transmit_bytes_total{interface="eth0", pod="web-01"}

# Ограничения — Gauge (статические значения из limits/requests)
container_spec_cpu_quota{container="nginx"}
container_spec_memory_limit_bytes{container="nginx"}
```

### Сценарий 4: Именование для бэкапов и cron-задач

```text
# Gauge: временная́я метка последнего успешного запуска
backup_last_success_timestamp_seconds{job="nightly-backup"}

# Counter: количество запусков
backup_runs_total{job="nightly-backup", status="success"}
backup_runs_total{job="nightly-backup", status="failed"}

# Gauge: текущий статус (1 = выполняется, 0 = не выполняется)
backup_in_progress{job="nightly-backup"}
```

### Сценарий 5: Диагностика через имена метрик

Prometheus автоматически определяет тип метрики по суффиксу. Проверьте корректность:

```bash
# 1. Проверка суффикса _total для Counter
curl -s http://localhost:9090/metrics | grep '^# TYPE .*_total'
# → Все Counter должны иметь суффикс _total

# 2. Проверка отсутствия _total у Gauge
curl -s http://localhost:9090/metrics | grep '^# TYPE.*gauge' | grep '_total'
# → Не должно быть Gauge с суффиксом _total

# 3. Проверка единиц измерения
curl -s http://localhost:9090/metrics | grep '^# UNIT'
# → Все метрики с единицами должны иметь директиву # UNIT

# 4. Проверка HELP-описаний
curl -s http://localhost:9090/metrics | grep '^# HELP' | wc -l
# → Количество HELP-строк должно совпадать с количеством TYPE-строк
```

### Сценарий 6: Миграция неправильных имён

Если метрика уже используется в продакшене, переименование требует осторожности:

```yaml
# recording rule для миграции: старое имя → новое имя
groups:
- name: migration.rules
  rules:
  # Было: http_request_time_ms (миллисекунды, без _total)
  # Стало: http_request_duration_seconds (секунды, базовая единица)
  - record: http_request_duration_seconds_bucket
    expr: http_request_time_ms_bucket / 1000

  - record: http_request_duration_seconds_sum
    expr: http_request_time_ms_sum / 1000

  - record: http_request_duration_seconds_count
    expr: http_request_time_ms_count
```

**Процесс миграции:**
1. Создайте recording rules с новыми именами.
2. Обновите дашборды и алерты на новые имена.
3. Дождитесь стабильной работы (≥ 2 недель).
4. Обновите код приложения на новые имена.
5. Удалите recording rules.

### Сценарий 7: Интеграция с OpenTelemetry (OTLP)

При приёме метрик через OTLP, Prometheus v3.0+ сохраняет оригинальные имена OTel:

```text
# OpenTelemetry имя (с точками) — Prometheus v3.0+ сохраняет как есть
http.server.request.duration
http.server.request.body.size

# Ранее (v2.x) — точки заменялись на подчёркивания
http_server_request_duration
```

**Рекомендация:** При создании новых метрик используйте имена, совместимые с OTel:
```text
# Правильно (совместимо с OTel и Prometheus v3.0+)
http_server_request_duration_seconds

# Неправильно (промежуточное решение, которое придётся менять)
http_srv_req_dur_sec
```

## Дополнительная информация

### Таблица суффиксов и их значение

| Суффикс | Тип метрики | Описание | Пример |
|:---|:---|:---|:---|
| `_total` | Counter | Кумулятивный счётчик (обязателен) | `requests_total` |
| `_bytes` | Gauge/Counter | Размер в байтах | `memory_bytes`, `network_bytes_total` |
| `_seconds` | Gauge/Histogram/Summary | Время в секундах | `duration_seconds`, `start_time_seconds` |
| `_ratio` | Gauge | Доля от 0 до 1 | `cpu_usage_ratio` |
| `_info` | Gauge (=1) | Статическая информация | `build_info`, `config_info` |
| `_bucket` | Histogram | Корзина гистограммы (автоматический) | `duration_seconds_bucket` |
| `_sum` | Histogram/Summary | Сумма наблюдений (автоматический) | `duration_seconds_sum` |
| `_count` | Histogram/Summary | Количество наблюдений (автоматический) | `duration_seconds_count` |
| `_created` | Counter/Histogram/Summary | Время создания (OpenMetrics) | `requests_total_created` |

### Частые ошибки именования

| Ошибка | Проблема | Решение |
|:---|:---|:---|
| `http_requests` (без `_total`) | Counter без суффикса `_total` — `rate()` не работает корректно | Добавить `_total`: `http_requests_total` |
| `http_request_duration_ms` | Производная единица (`ms`) вместо базовой (`seconds`) | Переименовать в `http_request_duration_seconds` |
| `memory_usage_percent` | Процент вместо ratio (0..1) | Использовать `memory_usage_ratio` или хранить ratio |
| `request_count` | Суффикс `count` вместо `total` для Counter | Использовать `requests_total` |
| `api_latency_p99` | Перцентиль в имени метрики — нельзя агрегировать | Использовать `api_request_duration_seconds` и вычислять p99 через PromQL |
| `user_logins_total{user_id="..."}` | Высокая кардинальность в лейблах | Убрать `user_id` или использовать recording rule |
| `cpu` (слишком общее) | Неясно, что именно измеряется | Использовать `process_cpu_seconds_total` или `node_cpu_seconds_total` |
| `http_request_duration{method="GET"}` (без единиц) | Нет единиц измерения — Grafana не может авто-масштабировать | Добавить `_seconds`: `http_request_duration_seconds` |

### Рекомендации по именованию

1. **Всегда указывайте базовые единицы:** `_seconds`, `_bytes`, `_celsius`, `_ratio`.
2. **Counter всегда с `_total`:** Без этого суффикса `rate()` и `increase()` работают некорректно.
3. **Используйте snake_case:** `http_request_duration_seconds`, не `httpRequestDurationSeconds`.
4. **Избегайте аббревиатур:** `http`, `tcp`, `dns` — допустимы. `req`, `conn`, `mem` — лучше писать полностью.
5. **Информация — через `_info`:** Версия, конфигурация, окружение — Gauge со значением 1, полезные данные — в лейблах.
6. **Не дублируйте тип в имени:** `http_requests_total_counter` — избыточно. Достаточно `http_requests_total`.
7. **Группируйте по подсистеме:** `node_filesystem_*`, `container_cpu_*`, `http_request_*`.

### Соответствие OpenTelemetry

| OpenTelemetry | Prometheus (v3.0+) | Комментарий |
|:---|:---|:---|
| `http.server.request.duration` | `http.server.request.duration` | UTF-8 сохраняет точки |
| `system.cpu.utilization` | `system.cpu.utilization` | Ratio-метрики без суффикса |
| `process.runtime.go.memory.usage` | `process.runtime.go.memory.usage` | Базовые единицы |

### См. также

- [Типы метрик: обзор](./overview.md) — классификация типов и критерии выбора.
- [Counter](./counter.md) — детали суффикса `_total` и обработка сбросов.
- [Gauge](./gauge.md) — паттерны использования для текущих значений.
- [Histogram](./histogram.md) — структура корзин и `_bucket`/`_sum`/`_count`.
- [Формат экспозиции](./exposition_format.md) — технические детали передачи метрик.
