# Prometheus HTTP API

[Prometheus](./overview.md) предоставляет HTTP API для выполнения [PromQL](./concepts/promql/functions.md)-запросов, получения метаданных и управления сервером. Основной способ интеграции с внешними системами — [Grafana](../Grafana/grafana_overview.md), кастомные приложения.

## Definitions

| Параметр | Значение |
|---|---|
| **Base path** | `/api/v1/` (стабильная версия) |
| **Методы** | `GET`, `POST` (`Content-Type: application/x-www-form-urlencoded`) |
| **Формат ответа** | JSON |
| **Документация** | `/api/v1/openapi.yaml` (OpenAPI 3.2) |

## Basic Concepts

### Статусы ответов

| Код | Значение |
|---|---|
| `2xx` | Успешный запрос |
| `400` | Неверные/отсутствующие параметры |
| `422` | Запрос корректен, но невыполним (некорректный PromQL) |
| `503` | Временная недоступность (таймаут, перегрузка) |

### Типы данных в ответе

| `resultType` | Описание | Источник |
|---|---|---|
| `vector` | Вектор мгновенных значений | Instant query |
| `matrix` | Матрица данных за период | Range query |
| `scalar` | Числовое значение | Scalar query |
| `string` | Строковое значение | String query |

### Формат времени

| Формат | Пример |
|---|---|
| Unix timestamp | `1671278400` |
| RFC3339 | `2022-12-17T12:00:00Z` |

## Practical Scenarios

### Мгновенный запрос — `/query`

Выполняет PromQL-запрос в один момент времени.

| Параметр | Обязательный | Описание |
|---|---|---|
| `query` | Да | PromQL-выражение |
| `time` | Нет | Момент времени (по умолчанию — текущее) |

```bash
curl 'http://localhost:9090/api/v1/query?query=up'
```

Ответ (`resultType: "vector"`):

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [{
      "metric": {"__name__": "up", "instance": "localhost:9090", "job": "prometheus"},
      "value": [1671278400.123, "1"]
    }]
  }
}
```

### Запрос за период — `/query_range`

Выполняет PromQL-запрос за диапазон времени.

| Параметр | Обязательный | Описание |
|---|---|---|
| `query` | Да | PromQL-выражение |
| `start` | Да | Начало диапазона |
| `end` | Да | Конец диапазона |
| `step` | Да | Шаг вычислений (`15s`, `1m`) |

```bash
curl 'http://localhost:9090/api/v1/query_range' \
  --data-urlencode 'query=rate(node_cpu_seconds_total{mode="user"}[5m])' \
  --data-urlencode 'start=2025-12-17T09:30:00Z' \
  --data-urlencode 'end=2025-12-17T10:00:00Z' \
  --data-urlencode 'step=1m'
```

Ответ (`resultType: "matrix"`):

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [{
      "metric": {"instance": "node-exporter:9100", "job": "node"},
      "values": [
        [1671279000, "0.012"],
        [1671279060, "0.015"]
      ]
    }]
  }
}
```

### Поиск временных рядов — `/series`

Находит временные ряды по селекторам меток.

| Параметр | Обязательный | Описание |
|---|---|---|
| `match[]` | Да | Селектор (можно несколько раз) |
| `start` | Нет | Начало диапазона |
| `end` | Нет | Конец диапазона |

```bash
curl -X POST -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'match[]={job="node_exporter"}' \
  'http://localhost:9090/api/v1/series'
```

### Получение метаданных

| Endpoint | Описание | Пример |
|---|---|---|
| `/api/v1/labels` | Все имена меток | `curl http://localhost:9090/api/v1/labels` |
| `/api/v1/label/<name>/values` | Значения конкретной метки | `curl http://localhost:9090/api/v1/label/job/values` |
| `/api/v1/metadata` | Метрики с описанием и типами | `curl http://localhost:9090/api/v1/metadata` |
| `/api/v1/status/tsdb` | Статистика TSDB (серий, лейблов) | `curl http://localhost:9090/api/v1/status/tsdb` |

Подробнее: [Лейблы и кардинальность](./concepts/labels_and_cardinality.md).

## Additional Information

### Статус и управление

| Endpoint | Описание |
|---|---|
| `/api/v1/targets` | Состояние всех настроенных целей |
| `/api/v1/targets/metadata` | Метаданные таргетов (тип, help) |
| `/api/v1/rules` | Загруженные [правила](./rules.md) (recording + alerting) |
| `/api/v1/alerts` | Активные алерты |
| `/api/v1/alertmanagers` | Подключённые серверы [Alertmanager](./alertmanager.md) |
| `/api/v1/status/config` | Конфигурация Prometheus (YAML) |
| `/api/v1/status/flags` | Флаги командной строки |

### Административные операции

Требуют флаг `--web.enable-admin-api`. Использование строго ограничено.

| Endpoint | Метод | Описание |
|---|---|---|
| `/api/v1/admin/tsdb/snapshot` | `POST` | Создание снимка TSDB |
| `/api/v1/admin/tsdb/delete_series` | `POST` | Удаление серий по селектору |
| `/api/v1/admin/tsdb/clean_tombstones` | `POST` | Очистка tombstones |
| `/api/v1/admin/tsdb/snapshots` | `GET` | Список снимков |
| `/-/healthy` | `GET` | Проверка работоспособности |
| `/-/ready` | `GET` | Готовность к обслуживанию запросов |

Подробнее: [Безопасность](./security.md).
