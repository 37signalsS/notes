# Prometheus HTTP API

[Prometheus](./overview.md) предоставляет полнофункциональный HTTP API, который позволяет выполнять запросы на языке [PromQL](./concepts/promql.md), получать метаданные и проверять состояние самого сервера. Это основной способ интеграции Prometheus с внешними системами, такими как [Grafana](../Grafana/grafana_overview.md), и кастомными приложениями.

## Определения

- **Endpoint**: Все запросы к стабильной версии API выполняются по пути `/api/v1/`.
- **Методы**: API поддерживает `GET` и `POST`. Параметры могут передаваться как в URL, так и в теле `POST` запроса с `Content-Type: application/x-www-form-urlencoded`.
- **Формат ответа**: Все ответы возвращаются в формате `JSON`.

## Основные концепции

### Статусы ответов

- `2xx`: Успешный запрос.
- `400 Bad Request`: Неверные или отсутствующие параметры.
- `422 Unprocessable Entity`: Запрос синтаксически корректен, но не может быть выполнен (например, некорректное выражение PromQL).
- `503 Service Unavailable`: Запрос временно не может быть выполнен (например, из-за таймаута или перегрузки).

### Типы данных в ответе

Поле `data.resultType` в ответе может содержать:

- `vector`: Вектор мгновенных значений (результат instant query).
- `matrix`: Матрица данных за период (результат range query).
- `scalar`: Простое числовое значение.
- `string`: Простое строковое значение.

### Формат времени

Временные метки в запросах указываются в одном из форматов:

- **Unix timestamp** (например, `1671278400`).
- **RFC3339** (например, `2022-12-17T12:00:00Z`).

---

## Практические сценарии

### Мгновенный запрос (`/query`)

Выполняет PromQL-запрос в один момент времени.

- **Endpoint**: `/api/v1/query`
- **Параметры**:
  - `query=<string>`: PromQL-запрос.
  - `time=<rfc3339 | unix_timestamp>`: (Опционально) Момент времени. По умолчанию — текущее время.

**Пример**: Получить текущее состояние всех `up` таргетов.

```bash
curl 'http://localhost:9090/api/v1/query?query=up'
```

**Пример ответа (`resultType: "vector"`)**:

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {
          "__name__": "up",
          "instance": "localhost:9090",
          "job": "prometheus"
        },
        "value": [ 1671278400.123, "1" ]
      }
    ]
  }
}
```

### Запрос за период (`/query_range`)

Выполняет PromQL-запрос за диапазон времени.

- **Endpoint**: `/api/v1/query_range`
- **Параметры**:
  - `query=<string>`: PromQL-запрос.
  - `start=<rfc3339 | unix_timestamp>`: Начало диапазона.
  - `end=<rfc3339 | unix_timestamp>`: Конец диапазона.
  - `step=<duration>`: Шаг вычислений (например, `15s`, `1m`).

**Пример**: Получить среднюю скорость роста CPU за последние 30 минут.

```bash
curl 'http://localhost:9090/api/v1/query_range' \
  --data-urlencode 'query=rate(node_cpu_seconds_total{mode="user"}[5m])' \
  --data-urlencode 'start=2025-12-17T09:30:00Z' \
  --data-urlencode 'end=2025-12-17T10:00:00Z' \
  --data-urlencode 'step=1m'
```

**Пример ответа (`resultType: "matrix"`)**:

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": { "instance": "node-exporter:9100", "job": "node" },
        "values": [
          [ 1671279000, "0.012" ],
          [ 1671279060, "0.015" ],
          [ 1671279120, "0.013" ]
        ]
      }
    ]
  }
}
```

### Поиск временных рядов по меткам (`/series`)

Находит временные ряды по селекторам.

- **Endpoint**: `/api/v1/series`
- **Параметры**:
  - `match[]=<series_selector>`: Селектор (обязательный, можно указывать несколько раз).
  - `start=<...>` и `end=<...>`: (Опционально) Временной диапазон.

**Пример**: Найти все метрики с `job="node_exporter"`.

```bash
curl -X POST -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'match[]={job="node_exporter"}' \
  'http://localhost:9090/api/v1/series'
```

### Получение метаданных

- **Все имена меток**:
  - **Endpoint**: `/api/v1/labels`
  - **Пример**: `curl http://localhost:9090/api/v1/labels`

- **Все значения для метки**:
  - **Endpoint**: `/api/v1/label/<label_name>/values`
  - **Пример**: `curl http://localhost:9090/api/v1/label/job/values`

---

## Дополнительная информация

### Статус и управление

Эндпоинты для получения информации о состоянии сервера Prometheus:

- **/api/v1/targets**: Состояние всех настроенных целей (scraped targets).
- **/api/v1/rules**: Все загруженные [правила](./rules.md) (recording и alerting).
- **/api/v1/alerts**: Список активных алертов.
- **/api/v1/alertmanagers**: Состояние подключенных серверов [Alertmanager](./alertmanager.md).
- **/api/v1/status/config**: Конфигурация Prometheus (YAML).
- **/api/v1/status/flags**: Флаги командной строки, с которыми запущен Prometheus.

### Административные операции

Эндпоинты для управления жизненным циклом (перезагрузка, выключение), создания снимков и удаления данных. По умолчанию отключены и требуют активации флагом `--web.enable-admin-api`. Использование должно быть строго ограничено.
