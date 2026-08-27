# Query API Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

**Jaeger Query API** — это REST-интерфейс для программного доступа к данным трассировок, сервисам и зависимостям. В Jaeger v2 API разделен на версии (`v1`, `v2`, `v3`), где `v3` предоставляет расширенные возможности агрегации и сводок. Понимание эндпоинтов необходимо для интеграции с внешними системами, автоматизации и построения кастомных дашбордов.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура и роли компонентов: **[Архитектура Jaeger](./jaeger_architecture.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Query Service** | Статeless-сервис, предоставляющий REST API для чтения данных из хранилища. В v2 интегрирован в Query extension единого бинарного файла |
| **Query API v1** | Базовый набор эндпоинтов (`/api/services`, `/api/traces`, `/api/operations`) для поиска и получения трасс |
| **Query API v2** | Расширенный API с поддержкой потоковой передачи данных (gRPC), улучшенной пагинацией и фильтрацией |
| **Query API v3** | Новейший API для агрегированных сводок (`trace-summaries`) и аналитики на уровне трейсов |
| **SpanID / TraceID** | Идентификаторы спана и трассы, используемые как параметры пути в эндпоинтах |
| **Lookback** | Параметр, ограничивающий глубину поиска по времени (например, `lookback=1h`) |
| **MinDuration / MaxDuration** | Фильтры по длительности трассы в наносекундах или читаемом формате (`5s`, `100ms`) |
| **Tags** | Ключ-значение атрибуты для фильтрации спанов и трасс (например, `{"http.status_code":"500"}`) |

---

## Базовые концепции

### Архитектура Query API

Query Service в Jaeger v2 работает как stateless-слой над хранилищем. Он не хранит данные самостоятельно, а выполняет запросы к ClickHouse, Elasticsearch или другому бэкенду через Storage Extension.

```
Приложение → UI / API Client → Query Service (порт 16686) → Storage Extension → ClickHouse / Elasticsearch
```

### Версии API

| Версия | Протокол | Основные возможности | Рекомендуемое применение |
| :--- | :--- | :--- | :--- |
| **v1** | HTTP/JSON | Базовый поиск по сервисам, операциям, трассам | Обратная совместимость, простые скрипты |
| **v2** | HTTP/JSON + gRPC | Потоковая передача трейсов, улучшенная пагинация | High-load клиенты, интеграции с gRPC |
| **v3** | HTTP/JSON | Агрегированные сводки (`trace-summaries`), аналитика | Мониторинг, алертинг, автоматизация |

### Основные эндпоинты

#### v1 API (HTTP)

| Эндпоинт | Метод | Описание |
| :--- | :--- | :--- |
| `/api/services` | GET | Список всех сервисов, отправивших спаны |
| `/api/operations` | GET | Список операций для указанного сервиса (`?service=<name>`) |
| `/api/traces` | GET | Поиск трасс по фильтрам (сервис, операция, теги, длительность, время) |
| `/api/trace/{traceID}` | GET | Получение полной трассы по идентификатору |
| `/api/dependencies` | GET | Граф зависимостей между сервисами за указанный интервал (`?start&end`) |

#### v3 API (HTTP)

| Эндпоинт | Метод | Описание |
| :--- | :--- | :--- |
| `/api/v3/trace-summaries` | GET | Агрегированные сводки по трассам (сервис, минимальная длительность, время) |
| `/api/v3/traces` | GET | Поиск трейсов с поддержкой расширенной фильтрации |

### Параметры фильтрации `/api/traces`

| Параметр | Тип | Описание | Пример |
| :--- | :--- | :--- | :--- |
| `service` | string | Имя сервиса | `api-gateway` |
| `operation` | string | Имя операции | `POST /v1/orders` |
| `tags` | JSON | Фильтр по атрибутам спанов | `{"error":"true","http.status_code":"500"}` |
| `minDuration` | string | Минимальная длительность трассы | `500ms`, `2s` |
| `maxDuration` | string | Максимальная длительность | `5s` |
| `start` | int64 | Начало окна поиска (Unix epoch, наносекунды) | `1710000000000000000` |
| `end` | int64 | Конец окна поиска | `1710003600000000000` |
| `lookback` | string | Альтернатива `start`/`end`: относительное время | `1h`, `30m` |
| `limit` | int | Количество трасс в ответе (максимум 1000) | `20` |

### Формат ответа `/api/trace/{traceID}`

Каждая трасса содержит:
- **traceID:** Уникальный идентификатор трассы.
- **spans:** Массив спанов с полями `spanID`, `operationName`, `startTime`, `duration`, `tags`, `logs`, `references`.
- **processes:** Словарь процессов (сервисов), участвовавших в трассе.
- **warnings:** Массив нефатальных предупреждений (например, `incomplete` при частичных данных).

### Ограничения и особенности

- **Pagination:** v1 API использует cursor-based пагинацию через заголовок `Trace-Offset`. При большом объеме данных используйте `limit` + `start`/`end`.
- **Глубина поиска:** В production с большим объемом данных ограничьте период поиска (`lookback`) до 1–6 часов для интерактивных запросов.
- **Дублирование спанов:** При использовании Kafka consumer groups убедитесь, что consumer group уникален для Query Service, иначе возможны дубли или пропуски.
- **Rate limiting:** В Kubernetes настроите NetworkPolicy и ingress-контроллер для защиты Query API от перегрузки.

---

## Практические сценарии

### Сценарий 1: Поиск ошибок за последний час

**Ситуация:** Необходимо найти все трассы с HTTP 500 за последний час для сервиса `api-gateway`.

```bash
curl -s 'http://jaeger-query:16686/api/traces?service=api-gateway&tags=%7B%22http.status_code%22%3A%22500%22%7D&lookback=1h&limit=50' | jq '.data[] | {traceID, duration, spans: [.spans[].operationName]}'
```

**Ожидаемый результат:** JSON-массив с 50 трассами, содержащими минимум один спан с тегом `http.status_code=500`.

### Сценарий 2: Получение агрегированной сводки через v3 API

**Ситуация:** Нужно получить статистику по медленным трейсам для дашборда или алерта.

```bash
curl -s 'http://jaeger-query:16686/api/v3/trace-summaries?service=api-gateway&minDuration=2s&lookback=1h' | jq '.data[] | {traceID, serviceName, duration}'
```

**Ожидаемый результат:** JSON с агрегированными суммари по трассам, длительностью более 2 секунд.

### Сценарий 3: Построение графа зависимостей

**Ситуация:** Необходимо визуализировать вызовы между сервисами за последние 24 часа.

```bash
curl -s 'http://jaeger-query:16686/api/dependencies?start=1710000000000000000&end=1710003600000000000' | jq '.'
```

**Ожидаемый результат:** JSON с массивом связей `{parent: "service-a", child: "service-b", callCount: 1234}`.

### Сценарий 4: Автоматизация выгрузки трасс через Python

**Ситуация:** Нужно выгрузить все трассы для сервиса `payment` за последние 6 часов для офлайн-анализа.

```python
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://jaeger-query:16686"
SERVICE = "payment"
LOOKBACK = "6h"
LIMIT = 100

def get_traces(service, lookback, limit):
    url = f"{BASE_URL}/api/traces"
    params = {
        "service": service,
        "lookback": lookback,
        "limit": limit
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()["data"]

traces = get_traces(SERVICE, LOOKBACK, LIMIT)
print(f"Found {len(traces)} traces")

# Фильтрация по длительности
slow_traces = [t for t in traces if t["duration"] > 2_000_000_000]  # 2s в наносекундах
print(f"Slow traces: {len(slow_traces)}")

# Сохранение в файл
with open("payment_traces.json", "w") as f:
    json.dump(traces, f, indent=2)
```

**Валидация:**
1. Запустить скрипт и убедиться, что файл `payment_traces.json` создан.
2. Проверить, что все `traceID` в файле уникальны.
3. Убедиться, что длительности трасс соответствуют фильтру.

### Сценарий 5: Интеграция с Grafana через JSON API

**Ситуация:** Нужно построить кастомный дашборд Grafana, показывающий количество ошибок по данным Jaeger Query API.

1. В Grafana создать панель типа **Table** с источником данных **JSON**.
2. В URL источника указать:
   ```
   http://jaeger-query:16686/api/traces?service=api-gateway&tags=%7B%22http.status_code%22%3A%22500%22%7D&lookback=5m&limit=1000
   ```
3. В transformation добавить **Count** по полю `traceID`.

**Валидация:**
1. Вызвать ошибку в приложении.
2. Убедиться, что панель обновилась и показывает увеличение счетчика.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Пустой ответ `/api/services`** | Query Extension не настроен или хранилище пустое | Проверить конфигурацию `jaeger_storage` и наличие данных в БД |
| **Трасса не найдена по `traceID`** | TTL хранилища истек или неверный ID | Проверить TTL в ClickHouse/Elasticsearch, убедиться что ID передан без `0x` префикса |
| **Большой объем данных в `/api/traces`** | Отсутствует `limit` или `lookback` слишком широкий | Всегда указывайте `limit` и ограничьте `lookback` до минимально необходимого окна |
| **Ошибка 500 при запросе зависимостей** | Хранилище не поддерживает `/api/dependencies` (например, Badger) | Используйте внешнюю БД (ClickHouse, Elasticsearch) |
| **Дублирование спанов в ответе** | Несколько Consumer Group читают из Kafka без идемпотентности | Настройте уникальный `group.id` для Query или используйте直連ное хранилище |
| **Высокая задержка ответа API** | Сложный запрос к ClickHouse без индексов | Добавьте индексы по `service_name`, `operation_name`, настроить TTL |

---

## Лучшие практики

1.  **Используйте v3 API для агрегации:** Для дашбордов и алертов предпочитайте `/api/v3/trace-summaries` вместо ручной фильтрации v1.
2.  **Ограничивайте `lookback` и `limit`:** Интерактивные запросы ограничьте окном 1–6 часов и `limit` ≤ 1000.
3.  **Кэшируйте повторяющиеся запросы:** Для скриптов мониторинга кэшируйте `/api/services` и `/api/operations` (изменяются редко).
4.  **Используйте gRPC для high-load:** При построении кастомных клиентов используйте v2 gRPC API вместо HTTP для снижения накладных расходов.
5.  **Мониторинг Query Service:** Настройте алерты на `jaeger_query_search_latency_seconds` и `jaeger_query_requests_total`.

---

## Очистка окружения

```bash
# Очистка in-memory данных (если использовался All-in-one)
docker restart jaeger

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Поиск и анализ трейсов в UI: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Автоматизация и алертинг: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Развертывание Query Service: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Интеграция с Grafana: **[Grafana: Источники данных](../Grafana/grafana_datasources.md)**
* Корреляция метрик и трейсов (Exemplars): **[Grafana: Корреляция телеметрии](../Grafana/grafana_correlation_exemplars.md)**

### См. также

* [Official Jaeger Query API Documentation](https://www.jaegertracing.io/docs/latest/query-api/)
* [OpenTelemetry Collector gRPC Streaming](https://opentelemetry.io/docs/collector/configuration/#grpc)
