# HTTP API Prometheus

## Определения

**HTTP API Prometheus** — стабильный программный интерфейс, позволяющий внешним системам (Grafana, кастомные скрипты, CLI-утилиты) взаимодействовать с сервером мониторинга. API предоставляет доступ к данным в [TSDB](./concepts/tsdb.md), метаданным временных рядов, статусу сервера и административным функциям.

В 2026 году (версия Prometheus v3.x) API является полностью совместимым с OpenTelemetry (OTLP) и поддерживает современные структуры данных, такие как нативные гистограммы.

| Параметр | Значение |
| :--- | :--- |
| **Базовый путь** | `/api/v1/` (стабильное API) |
| **Методы запроса** | `GET`, `POST` (с `Content-Type: application/x-www-form-urlencoded`) |
| **Формат ответа** | JSON (стандарт), Protobuf (для высокопроизводительных задач) |
| **Спецификация** | OpenAPI 3.2 (доступна по пути `/api/v1/openapi.yaml`) |
| **Флаги запуска** | `--web.enable-admin-api` (админ-эндпоинты), `--web.enable-lifecycle` (reload), `--web.enable-otlp-receiver` (OTLP) |

**См. также:** [Обзор Prometheus](./overview.md), [PromQL — функции](./concepts/promql/functions.md), [Безопасность Prometheus](./security.md), [Федерация](./scaling/federation.md).

## Основные концепции

### Коды состояния ответов

| Код | Значение | Описание |
| :--- | :--- | :--- |
| **`2xx`** | Success | Запрос успешно обработан, результат находится в поле `data`. |
| **`400`** | Bad Request | Ошибка в параметрах (неверный синтаксис времени или шага `step`). |
| **`422`** | Unprocessable Entity | Запрос синтаксически верен, но выполнение невозможно (ошибка в PromQL). |
| **`429`** | Too Many Requests | Превышен лимит запросов (настраивается через `--query.max-concurrency` или внешний балансировщик). |
| **`503`** | Service Unavailable | Ошибка выполнения на стороне сервера (таймаут или перегрузка). |

### Типы данных в JSON-ответах

Поле `resultType` в объекте `data` определяет структуру возвращаемых данных:

| `resultType` | Описание | Типичный эндпоинт |
| :--- | :--- | :--- |
| **`vector`** | Вектор мгновенных значений (Instant vector). | Мгновенный запрос (`/query`). |
| **`matrix`** | Матрица данных (Range vector). | Запрос за период (`/query_range`). |
| **`scalar`** | Одиночное числовое значение. | Результат математических функций (напр. `count()`). |
| **`string`** | Строковое значение. | Редкие системные функции. |

**Нативные гистограммы (Native Histograms):** В ответах v3.0+ гистограммы с экспоненциальными бакетами возвращаются не как набор отдельных рядов с лейблом `le`, а как единый объект внутри временного ряда с полями `buckets`, `sum` и `count`.

### Форматы времени и кодировка (UTF-8)

*   **Форматы времени:** API принимает время в секундах с миллисекундами (Unix timestamp) или в формате RFC3339 (например, `2026-07-29T10:00:00Z`).
*   **UTF-8:** Prometheus 3.x нативно поддерживает любые UTF-8 символы в именах метрик и лейблов. В HTTP API это означает, что имена с точками (стиль OpenTelemetry) передаются и принимаются без необходимости дополнительного экранирования.

### Аутентификация и авторизация при Programmatic-доступе

По умолчанию Prometheus не требует аутентификации. В production-средах доступ к API защищается на одном из уровней:

1.  **Нативная Basic Auth + TLS:** Файл конфигурации `--web.config.file` с bcrypt-хешами и TLS-сертификатами. Подробности: [Безопасность Prometheus](./security.md).
2.  **Обратный прокси (Reverse Proxy):** NGINX, Apache или облачный Ingress с Basic Auth, OAuth2 или mTLS.
3.  **Сетевая сегментация:** Ограничение доступа к порту 9090 на уровне firewall (iptables/nftables) или NetworkPolicy (Kubernetes).

**Пример programmatic-доступа с Basic Auth:**
```bash
# С авторизацией (при включенном --web.config.file)
curl -k -u admin:StrongP@ssw0rd! https://localhost:9090/api/v1/query?query=up

# С Bearer-токеном (если прокси добавляет X-Forwarded-User)
curl -k -H "Authorization: Bearer <token>" https://prometheus.example.com/api/v1/targets
```

> **Важно:** Basic Auth без TLS передаёт пароли в кодировке base64, что эквивалентно открытому тексту. TLS обязателен для любой промышленной инсталляции.

### Расширенные параметры запросов

| Параметр | Эндпоинты | Описание |
| :--- | :--- | :--- |
| `timeout` | `/query`, `/query_range` | Максимальное время выполнения PromQL-запроса (например, `5m`). По умолчанию `--query.timeout`. |
| `limit` | `/series`, `/labels`, `/label/<name>/values`, `/metadata` | Ограничение количества возвращаемых записей (защита от перегрузки). |
| `explain` | `/query`, `/query_range` | Возвращает план выполнения запроса (v3.13+). Поле `data.explanation` содержит оптимизацию PromQL. |
| `partial_response` | `/query`, `/query_range` | `true`/`false`. При `true` возвращает частичные результаты, если часть инстансов недоступна (HA-режим). |
| `start`, `end`, `step` | `/query_range` | Диапазон и шаг дискретизации. |
| `match[]` | `/series`, `/rules`, `/targets` | Повторяемый параметр для фильтрации по селекторам. |

### Структура ответов об ошибках

При ошибках API возвращает объект с полем `error` и `errorType`:

```json
{
  "status": "error",
  "errorType": "execution",
  "error": "1:1: parse error: unexpected char: '\\'"
}
```

| Поле | Назначение |
| :--- | :--- |
| `status` | `"error"` при неуспехе. |
| `errorType` | Категория: `"execution"`, `"bad_data"`, `"server_error"`. |
| `error` | Текстовое описание ошибки. |
| `warnings` | Нефатальные предупреждения (например, `Expression evaluation returned empty result`). |

---

## Практические сценарии

### 1. Выполнение мгновенных запросов — `/query`

Используется для получения среза данных на конкретный момент времени.

**Параметры:**
*   `query` (обязательно): PromQL выражение.
*   `time` (опционально): Момент времени (по умолчанию — текущее время сервера).
*   `timeout` (опционально): Лимит времени выполнения.
*   `partial_response` (опционально): Частичные результаты в HA-режиме.

**Пример:**
```bash
curl 'http://localhost:9090/api/v1/query?query=up'
```
# → результат: список активных/неактивных целей (1/0).

**С пояснением плана выполнения (v3.13+):**
```bash
curl -G 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=rate(http_requests_total[5m])' \
  --data-urlencode 'explain=true'
```
# → в ответе появится поле `data.explanation` с AST-деревом запроса.

### 2. Запросы данных за период — `/query_range`

Основной инструмент для построения графиков и анализа трендов.

| Параметр | Обязательный | Описание |
| :--- | :--- | :--- |
| `query` | Да | PromQL выражение (например, `rate(...)`). |
| `start` | Да | Время начала диапазона (RFC3339 или Unix timestamp). |
| `end` | Да | Время окончания диапазона. |
| `step` | Да | Шаг вычислений (например, `15s`, `1m`, `1h`). |
| `timeout` | Нет | Таймаут выполнения. |

**Пример:**
```bash
curl 'http://localhost:9090/api/v1/query_range' \
  --data-urlencode 'query=rate(node_cpu_seconds_total{mode="user"}[5m])' \
  --data-urlencode 'start=2026-07-29T09:30:00Z' \
  --data-urlencode 'end=2026-07-29T10:00:00Z' \
  --data-urlencode 'step=1m'
```

### 3. Поиск метаданных и управление нагрузкой

В версиях 3.x введено ограничение `limit` для предотвращения перегрузки сервера при поиске по большим объемам данных.

| Эндпоинт | Назначение | Пример с лимитом |
| :--- | :--- | :--- |
| `/api/v1/series` | Поиск временных рядов по селектору. | `curl -G '/api/v1/series' --data-urlencode 'match[]={job="node"}' -d 'limit=1000'` |
| `/api/v1/labels` | Список всех существующих имен меток. | `curl '/api/v1/labels?limit=500'` |
| `/api/v1/label/<name>/values` | Все уникальные значения для метки. | `curl '/api/v1/label/instance/values?limit=100'` |
| `/api/v1/metadata` | Информация о типах и описаниях метрик. | `curl '/api/v1/metadata?limit=100'` |

### 3.1 Диагностика целей через `/targets`

Эндпоинт `/api/v1/targets` — основной инструмент для диагностики проблем со скрейпингом:

```bash
# Все активные цели и их здоровье
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health, lastError: .lastError}'

# Только упавшие цели
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.health=="down") | {instance: .labels.instance, lastError: .lastError, lastScrape: .lastScrape}'

# Отброшенные цели (relabeling)
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.droppedTargets[] | {job: .labels.job, instance: .labels.instance}'

# Количество целей по job
curl -s 'http://localhost:9090/api/v1/targets' | jq '[.data.activeTargets[] | .labels.job] | group_by(.) | map({job: .[0], count: length})'
```

### 4. Федерация — `/federate`

Эндпоинт `/federate` используется вышестоящими серверами для сбора выбранных метрик с нижестоящих (Leaf) инстансов. Возвращает данные в текстовом формате exposition.

**Параметры:**
*   `match[]`: Повторяемый PromQL-селектор для фильтрации рядов.

**Пример (Leaf-сервер):**
```bash
curl -G 'http://leaf-dc1:9090/federate' \
  --data-urlencode 'match[]={job="node_exporter"}' \
  --data-urlencode 'match[]={job="prometheus"}'
```

**Важные особенности:**
*   Передаются только последние значения (Instant Vector).
*   Требуется `honor_labels: true` в конфигурации скрапинга на Master.
*   На Leaf-сервере должны быть настроены `external_labels` (например, `cluster: dc1`).
*   Активные запросы удерживают мьютекс на Head Block, замедляя запись.

Подробности: [Федерация Prometheus](./scaling/federation.md).

### 5. Exemplars — `/api/v1/exemplars` (v3.0+)

Exemplars — это отдельные точки данных внутри нативных гистограмм, связывающие метрики с трейсами (trace IDs).

**Пример:**
```bash
curl 'http://localhost:9090/api/v1/exemplars?match[]={__name__="http_request_duration_seconds"}'
```

### 6. Управление алертами через API

#### 6.1 Просмотр активных алертов

```bash
curl 'http://localhost:9090/api/v1/alerts' | jq '.data.alerts[] | {alertname: .labels.alertname, state: .state, summary: .annotations.summary}'
```

#### 6.2 Просмотр загруженных правил

```bash
curl 'http://localhost:9090/api/v1/rules' | jq '.data.groups[] | {name: .name, rules: (.rules | length)}'
```

#### 6.3 Отправка тестового алерта

```bash
curl -X POST http://localhost:9090/api/v1/alerts \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'data=[
    {
      "labels": {"alertname": "TestAlert", "severity": "warning", "instance": "test-01"},
      "annotations": {"summary": "Тестовый алерт", "description": "Автоматически сгенерирован"},
      "generatorURL": "http://localhost:9090"
    }
  ]'
```

---

## Дополнительная информация

### Статус и возможности сервера

*   **`/api/v1/features`**: Динамический список включенных функций (напр. `native-histograms`, `otlp-receiver`).
*   **`/api/v1/targets`**: Детальная информация о всех целях сбора и последних ошибках скрапинга. Включает `activeTargets` (скрейпятся) и `droppedTargets` (отброшены relabeling'ом).
*   **`/api/v1/dropped-targets`**: Список целей, отброшенных на этапе relabeling. Полезно для отладки `relabel_configs` — показывает почему конкретная цель не была собрана.
*   **`/api/v1/rules`**: Список всех загруженных [Recording и Alerting правил](./rules.md). Начиная с v3.13, API поддерживает пагинацию через хеш-ключи SHA-256.
*   **`/api/v1/status/tsdb`**: Статистика использования хранилища (топ лейблов, топ метрик по количеству рядов). Лимит выдачи — 10,000 записей.
*   **`/api/v1/status/config`**: Возвращает текущую конфигурацию `prometheus.yml`.
*   **`/api/v1/status/flags`**: Список флагов командной строки, с которыми был запущен Prometheus.
*   **`/api/v1/status/wal`**: Статус Write-Ahead Log (WAL) — размер, количество сегментов, последняя ошибка (если есть).

### Интеграция с OpenTelemetry (OTLP)

Prometheus 3.0+ выступает в роли полноценного OTLP-приемника.

*   **Эндпоинт:** `/api/v1/otlp/v1/metrics`
*   **Метод:** `POST`
*   **Протокол:** Protobuf через HTTP.
*   **Конфигурация:** Включается флагом `--web.enable-otlp-receiver`. Обеспечивает прямую интеграцию с SDK приложений на любых языках.

### Удаленная запись (Remote Write 2.0)

Новый стандарт передачи данных (PRW 2.0), минимизирующий нагрузку на сеть.

*   **Эндпоинт:** `/api/v1/write` (PUT/POST)
*   **Протокол:** Protobuf через HTTP (Content-Type: `application/x-protobuf`)
*   **Включение:** Флаг `--web.enable-otlp-receiver` (в Prometheus v3.x включен по умолчанию)
*   **Оптимизация:** Трафик снижен на ~60% благодаря технологии **String Interning** (передача уникальных строк один раз за сессию).
*   **Функции:** Передача экземпляров (exemplars) и метаданных вместе с образцами данных.

**Примеры клиентов, отправляющих данные через Remote Write:**
- `vmagent` (VictoriaMetrics) -> `http://prometheus:9090/api/v1/write`
- `Grafana Alloy` -> `http://prometheus:9090/api/v1/write`
- OTel Collector (экспортер `prometheusremotewrite`) -> `http://prometheus:9090/api/v1/write`
- K6 load testing -> `K6_PROMETHEUS_REMOTE_URL=http://prometheus:9090/api/v1/write`

**Проверка работоспособности:**
```bash
# Количество принятых сэмплов
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_http_requests_total{handler="/api/v1/write"}'
```

### Административное API

Требует явного включения флагом `--web.enable-admin-api`.

| Эндпоинт | Метод | Действие |
| :--- | :--- | :--- |
| `/api/v1/admin/tsdb/snapshot` | `POST` | Создание мгновенной резервной копии данных TSDB. |
| `/api/v1/admin/tsdb/delete_series` | `POST` | Удаление рядов по селектору (данные помечаются как удаленные до очистки). |
| `/api/v1/admin/tsdb/clean_tombstones` | `POST` | Принудительная компакция для удаления помеченных серий (tombstones). |
| `/-/healthy` | `GET` | Базовая проверка доступности эндпоинта. |
| `/-/ready` | `GET` | Подтверждение, что сервер загрузил конфигурацию и TSDB. |
| `/-/reload` | `POST` | Перезагрузка конфигурации без перезапуска (требует `--web.enable-lifecycle`). |

**Примеры административных операций:**

```bash
# Создание снэпшота (онлайн, без остановки)
curl -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot
# → {"data":{"name":"20230916T153745Z-<hash>"}}
# Снэпшот хранится в <storage.tsdb.path>/snapshots/<name>/

# Удаление серий по селектору (помечает как удалённые)
curl -X POST -d '{"match":{"__name__="old_metric"}}' http://localhost:9090/api/v1/admin/tsdb/delete_series

# Очистка tombstone-меток (физическое удаление)
curl -X POST http://localhost:9090/api/v1/admin/tsdb/clean_tombstones

# Hot reload конфигурации
curl -X POST http://localhost:9090/-/reload
# → "Config reloaded successfully!"
```

> **Предупреждение:** Доступ к `/api/v1/admin/` и `/-/` должен быть ограничен на уровне сетевого экрана или через [Authentication](./security.md).

### Производительность и ограничения API

Prometheus применяет server-side ограничения для защиты от перегрузки:

| Ограничение | Флаг запуска | Значение по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `--query.max-concurrency` | Максимальное количество параллельных PromQL-запросов. | `2` | Защита от исчерпания CPU/RAM. |
| `--query.max-samples` | Максимальное количество сэмплов, обрабатываемых одним запросом. | `50000000` | Защита от запросов, сканирующих всю TSDB. |
| `--query.timeout` | Таймаут выполнения PromQL. | `2m` | Защита от зависших запросов. |
| `--query.lookback-delta` | Окно поиска для мгновенных запросов. | `5m` | Дополнительное время для поиска последних сэмплов. |

**Рекомендации для клиентов:**
1.  Используйте `step` не меньше `scrape_interval` в `/query_range`.
2.  Добавляйте фильтры по `job` и `instance` для уменьшения кардинальности.
3.  При получении `429` или `503` реализуйте экспоненциальный backoff.
4.  Для Grafana используйте переменные с лимитом (`$__rate_interval`).

### Интеграция с внешними системами

#### Grafana

Grafana подключается к Prometheus как datasource. URL: `http://<prometheus>:9090`. При включенной Basic Auth в Grafana указываются логин/пароль, которые передаются в заголовке `Authorization`.

**Пример datasource через API:**
```bash
curl -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -u admin:admin \
  -d '{
    "name": "Prometheus-Prod",
    "type": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy",
    "basicAuth": true,
    "basicAuthUser": "grafana-reader",
    "jsonData": {"httpMethod": "POST"}
  }'
```

#### Кастомные скрипты (Python)

```python
import requests
import json

PROMETHEUS_URL = "https://localhost:9090"
AUTH = ("admin", "StrongP@ssw0rd!")
VERIFY_SSL = False  # Только для тестовых сред с самоподписанными сертификатами

def query(promql):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": promql},
        auth=AUTH,
        verify=VERIFY_SSL
    )
    response.raise_for_status()
    return response.json()

def query_range(promql, start, end, step):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
        auth=AUTH,
        verify=VERIFY_SSL
    )
    response.raise_for_status()
    return response.json()

# Пример использования
result = query('up')
for item in result["data"]["result"]:
    print(f"{item["metric"]["job"]}: {item["value"][1]}")
```

### Устранение неполадок HTTP API

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `401 Unauthorized` при доступе к API | Неверный пароль или хэш bcrypt | Проверить `basic_auth_users` в `web-config.yml` | Перегенерировать хэш, убедиться в корректности пароля |
| `403 Forbidden` | Ограничение по IP или NetworkPolicy | Проверить `iptables -L -n`, `nft list ruleset` | Добавить правило разрешения для доверенных подсетей |
| `429 Too Many Requests` | Превышен лимит параллельных запросов | `curl -w "%{http_code}" ...` | Увеличить `--query.max-concurrency` или добавить кэширование на стороне клиента |
| `503 Service Unavailable` | Таймаут или перегрузка сервера | Проверить `prometheus_http_request_duration_seconds_count` | Увеличить `--query.timeout`, оптимизировать PromQL, добавить ресурсы |
| `SSL handshake failure` | Несовпадение CA или истекший сертификат | `openssl s_client -connect host:port` | Обновить сертификаты, проверить `client_ca_file` |
| `x509: certificate signed by unknown authority` | CA не добавлен в доверенные | `openssl verify -CAfile ca.crt server.crt` | Убедиться, что клиент использует правильный `ca_file` |
| `connection refused` на 9090 | Порт не слушается или занят | `ss -tlnp | grep 9090` | Проверить `--web.listen-address`, firewall |
| `partial response` в данных | Запрос прерван при смене лидера (HA) | Включить `partial_response=true` | Настроить `partial_response`, проверить consistency между инстансами |
| `explain not supported` | Устаревшая версия Prometheus | `curl /api/v1/status/flags` | Обновить до v3.13+ или использовать альтернативные методы оптимизации |
| `OTLP endpoint not found` | Флаг `--web.enable-otlp-receiver` не включен | `curl https://localhost:9090/api/v1/status/flags` | Добавить флаг в команду запуска |

### Лучшие практики

1.  **Валидация через promtool:** Всегда проверяйте конфигурацию и правила перед reload. [Promtool и лучшие практики](./promtool_and_best_practices.md).
2.  **Секреты в конфигурации:** Не храните пароли в `prometheus.yml`. Используйте `credentialsFile` или переменные окружения.
3.  **Ограничение доступа:** Используйте `--web.listen-address=127.0.0.1:9090` и обратный прокси для внешнего доступа.
4.  **Мониторинг API:** Отслеживайте `prometheus_http_requests_total{code=~"5.."}` для раннего обнаружения проблем.
5.  **Hot Reload:** Используйте `/-/reload` вместо перезапуска для применения изменений конфигурации.
6.  **Rate limiting:** Настройте `--query.max-concurrency` и внешний rate limiting для защиты от DoS.
7.  **Backup TSDB:** Регулярно создавайте снэпшоты через `/api/v1/admin/tsdb/snapshot` перед критическими изменениями.
8.  **UTF-8 имена метрик:** При интеграции с OTLP-источниками убедитесь, что промежуточные прокси корректно обрабатывают UTF-8.
