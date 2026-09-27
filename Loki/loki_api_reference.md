# API Grafana Loki: справочник

## Определения

**Push API (`/loki/api/v1/push`)** — HTTP POST endpoint для отправки логов в Loki. Принимает запросы в формате Snappy-compressed protobuf или JSON. Используется агентами (Alloy, Promtail, Fluent Bit) для доставки логов. Поддерживает structured metadata для OpenTelemetry.

**Query API (`/loki/api/v1/query_range`)** — HTTP GET endpoint для выполнения LogQL запросов с указанием временного диапазона. Возвращает логи, метрики или series. Основной endpoint для Grafana и API-клиентов.

**Instant Query API (`/loki/api/v1/query`)** — HTTP GET endpoint для мгновенных LogQL запросов (метрики без временного диапазона). Возвращает результат в указанный момент времени.

**Labels API (`/loki/api/v1/labels`, `/loki/api/v1/label/<name>/values`)** — HTTP GET endpoints для получения списка labels и их значений. Используется для автокомплита и навигации по данным.

**Series API (`/loki/api/v1/series`)** — HTTP GET endpoint для получения списка series (комбинаций labels), соответствующих селектору и временному диапазону.

**Ready API (`/ready`)** — HTTP GET endpoint для проверки готовности Loki. Возвращает 200 OK когда все компоненты готовы обрабатывать запросы. Используется в Kubernetes readiness probes.

**Metrics Query API (`/loki/api/v1/query_range` с metric expression)** — HTTP GET endpoint для выполнения LogQL metric запросов (rate, count_over_time, etc.). Возвращает временные ряды.

---

## Основные концепции

### Структура URL Loki API

```
http://<loki-host>:3100/loki/api/v1/<endpoint>?<query_params>
```

### Аутентификация

Loki поддерживает несколько методов аутентификации:

| Метод | Описание | Использование |
| :--- | :--- | :--- |
| **auth_enabled: false** | Без аутентификации | Dev/test, Single Binary |
| **auth_enabled: true + X-Scope-OrgID** | Tenant-based аутентификация | Production, multi-tenant |
| **X-Scope-OrgID** | Header с ID тенанта | Все запросы при multi-tenancy |
| **Bearer token** | JWT token в Authorization header | Интеграция с IdP |
| **Basic auth** | Логин:пароль в Authorization header | Простая аутентификация |

### Форматы данных

**Push API:**
```json
{
  "streams": [
    {
      "stream": {
        "app": "nginx",
        "env": "prod"
      },
      "values": [
        ["1697056800000000000", "2023-10-11T12:00:00Z error message"],
        ["1697056801000000000", "2023-10-11T12:00:01Z warning message"]
      ]
    }
  ]
}
```

**Query API Response:**
```json
{
  "status": "success",
  "data": {
    "resultType": "streams",
    "result": [
      {
        "stream": {
          "app": "nginx"
        },
        "values": [
          ["1697056800000000000", "2023-10-11T12:00:00Z error message"]
        ]
      }
    ],
    "stats": {
      "totalEntriesRef": 100,
      "totalChunksRef": 10,
      "chunkRefsFetchDuration": "1.5ms"
    }
  }
}
```

### Ограничения запросов

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `start` | Начало временного диапазона (Unix nanosecond) | - |
| `end` | Конец временного диапазона (Unix nanosecond) | - |
| `limit` | Максимальное количество логов | 100 |
| `direction` | Направление: `forward` или `backward` | backward |
| `query` | LogQL запрос | - |
| `step` | Шаг для metric запросов (sec) | 1s |
| `interval` | Интервал для batch запросов | - |

---

## Практические сценарии

### Сценарий 1: Push API — отправка логов через curl

```bash
# Отправка одного stream
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [
      {
        "stream": {
          "app": "myapp",
          "env": "prod"
        },
        "values": [
          ["'$(date +%s)000000000'", "2023-10-11T12:00:00Z ERROR Something went wrong"]
        ]
      }
    ]
  }'

# Отправка нескольких entries
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [
      {
        "stream": {
          "app": "nginx",
          "job": "access-logs"
        },
        "values": [
          ["1697056800000000000", "192.168.1.1 - - [11/Oct/2023:12:00:00 +0000] GET /api/v1/users 200 1234"],
          ["1697056801000000000", "192.168.1.2 - - [11/Oct/2023:12:00:01 +0000] POST /api/v1/orders 201 5678"],
          ["1697056802000000000", "192.168.1.3 - - [11/Oct/2023:12:00:02 +0000] GET /api/v1/products 200 9012"]
        ]
      }
    ]
  }'

# Отправка с structured metadata (Loki 3.x)
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [
      {
        "stream": {
          "app": "myapp"
        },
        "values": [
          ["1697056800000000000", "2023-10-11T12:00:00Z ERROR Something went wrong"]
        ]
      }
    ]
  }'
```

### Сценарий 2: Query Range API — запрос логов

```bash
# Запрос логов за последние 1 час
START=$(date -v-1H +%s)000000000
END=$(date +%s)000000000

curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={app=\"nginx\"}" \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode "limit=100" \
  --data-urlencode "direction=backward"

# Запрос с grep-паттерном
curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={app=\"nginx\"} |= \"error\"" \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode "limit=50"

# Запрос с JSON фильтрацией
curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={app=\"nginx\"} | json | status >= 500" \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode "limit=100"

# Запрос с multiple labels
curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={app=\"nginx\", env=\"prod\", instance=~\".*1\"}" \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode "limit=100"

# Запрос с limit и direction
curl -G http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={app=\"nginx\"}" \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode "limit=10" \
  --data-urlencode "direction=forward"
```

### Сценарий 3: Instant Query API — мгновенные метрики

```bash
# Количество логов за 5 минут
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode "query=count_over_time({app=\"nginx\"}[5m])"

# Rate логов за 1 минуту
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode "query=sum(rate({app=\"nginx\"}[1m]))"

# Top 10 labels по количеству логов
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode "query=topk(10, sum by (app) (count_over_time({job=~\".*\"}[1h])))"

# Количество error логов
curl -G http://localhost:3100/loki/api/v1/query \
  --data-urlencode "query=sum(count_over_time({app=\"nginx\"} |= \"error\"[1h]))"
```

### Сценарий 4: Labels API — навигация по данным

```bash
# Получить все labels
curl -G http://localhost:3100/loki/api/v1/labels \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# Получить значения конкретного label
curl -G http://localhost:3100/loki/api/v1/label/app/values \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# Получить labels для конкретного тенанта
curl -G http://localhost:3100/loki/api/v1/labels \
  -H "X-Scope-OrgID: tenant-1" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"
```

### Сценарий 5: Series API — поиск series

```bash
# Найти все series для label selector
curl -G http://localhost:3100/loki/api/v1/series \
  --data-urlencode "match[]={app=\"nginx\"}" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"

# Найти series с regex label
curl -G http://localhost:3100/loki/api/v1/series \
  --data-urlencode "match[]={app=~\"nginx|apache\"}" \
  --data-urlencode "start=$(date -v-1H +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"
```

### Сценарий 6: Admin API — управление кластером

```bash
# Проверка готовности
curl http://localhost:3100/ready

# Проверка здоровья
curl http://localhost:3100/health

# Метрики Prometheus
curl http://localhost:3100/metrics

# Удаление данных по label (ОПАСНО!)
curl -X POST http://localhost:3100/loki/api/v1/delete \
  -H "Content-Type: application/json" \
  -d '{
    "selector": "{app=\"test\"}",
    "start": 1697056800000000000,
    "end": 1697057100000000000
  }'

# Отмена удаления
curl -X POST http://localhost:3100/loki/api/v1/delete/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "request-id-from-delete-response"
  }'
```

### Сценарий 7: Интеграция с Python (простой клиент)

```python
import requests
import json
from datetime import datetime, timedelta

class LokiClient:
    def __init__(self, host="http://localhost:3100", tenant_id=None):
        self.host = host
        self.tenant_id = tenant_id
        self.headers = {"Content-Type": "application/json"}
        if tenant_id:
            self.headers["X-Scope-OrgID"] = tenant_id

    def push(self, streams):
        """Отправка логов в Loki"""
        url = f"{self.host}/loki/api/v1/push"
        payload = {"streams": streams}
        response = requests.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def query_range(self, query, start, end, limit=100, direction="backward"):
        """Запрос логов за временной диапазон"""
        url = f"{self.host}/loki/api/v1/query_range"
        params = {
            "query": query,
            "start": start,
            "end": end,
            "limit": limit,
            "direction": direction
        }
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def query_instant(self, query):
        """Мгновенный запрос"""
        url = f"{self.host}/loki/api/v1/query"
        params = {"query": query}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def labels(self, start, end):
        """Получение списка labels"""
        url = f"{self.host}/loki/api/v1/labels"
        params = {"start": start, "end": end}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def label_values(self, label_name, start, end):
        """Получение значений label"""
        url = f"{self.host}/loki/api/v1/label/{label_name}/values"
        params = {"start": start, "end": end}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def ready(self):
        """Проверка готовности"""
        url = f"{self.host}/ready"
        response = requests.get(url)
        return response.status_code == 200


# Использование
client = LokiClient("http://localhost:3100", tenant_id="tenant-1")

# Проверка готовности
if client.ready():
    print("Loki is ready")

# Отправка логов
streams = [
    {
        "stream": {"app": "myapp", "env": "prod"},
        "values": [
            [str(int(datetime.now().timestamp() * 1e9)), "Test log message"]
        ]
    }
]
client.push(streams)

# Запрос логов
end = int(datetime.now().timestamp() * 1e9)
start = int((datetime.now() - timedelta(hours=1)).timestamp() * 1e9)
result = client.query_range("{app=\"myapp\"}", start, end)
print(json.dumps(result, indent=2))
```

### Сценарий 8: Интеграция с Go (простой клиент)

```go
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "net/http"
    "net/url"
    "time"
)

type LokiClient struct {
    Host     string
    TenantID string
    Client   *http.Client
}

type PushRequest struct {
    Streams []Stream `json:"streams"`
}

type Stream struct {
    Stream map[string]string `json:"stream"`
    Values [][]string        `json:"values"`
}

type QueryResponse struct {
    Status string `json:"status"`
    Data   struct {
        ResultType string        `json:"resultType"`
        Result     []interface{} `json:"result"`
    } `json:"data"`
}

func NewLokiClient(host, tenantID string) *LokiClient {
    return &LokiClient{
        Host:     host,
        TenantID: tenantID,
        Client:   &http.Client{Timeout: 30 * time.Second},
    }
}

func (c *LokiClient) Push(streams []Stream) error {
    req := PushRequest{Streams: streams}
    body, _ := json.Marshal(req)

    httpReq, _ := http.NewRequest("POST", c.Host+"/loki/api/v1/push", bytes.NewReader(body))
    httpReq.Header.Set("Content-Type", "application/json")
    if c.TenantID != "" {
        httpReq.Header.Set("X-Scope-OrgID", c.TenantID)
    }

    resp, err := c.Client.Do(httpReq)
    if err != nil {
        return err
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusNoContent {
        body, _ := io.ReadAll(resp.Body)
        return fmt.Errorf("push failed: %s", string(body))
    }
    return nil
}

func (c *LokiClient) QueryRange(query string, start, end time.Time, limit int) (*QueryResponse, error) {
    params := url.Values{}
    params.Set("query", query)
    params.Set("start", fmt.Sprintf("%d", start.UnixNano()))
    params.Set("end", fmt.Sprintf("%d", end.UnixNano()))
    params.Set("limit", fmt.Sprintf("%d", limit))
    params.Set("direction", "backward")

    httpReq, _ := http.NewRequest("GET", c.Host+"/loki/api/v1/query_range?"+params.Encode(), nil)
    if c.TenantID != "" {
        httpReq.Header.Set("X-Scope-OrgID", c.TenantID)
    }

    resp, err := c.Client.Do(httpReq)
    if err != nil {
        return nil, err
    }
    defer resp.Body.Close()

    var result QueryResponse
    json.NewDecoder(resp.Body).Decode(&result)
    return &result, nil
}

func (c *LokiClient) Ready() bool {
    resp, err := c.Client.Get(c.Host + "/ready")
    if err != nil {
        return false
    }
    defer resp.Body.Close()
    return resp.StatusCode == http.StatusOK
}

func main() {
    client := NewLokiClient("http://localhost:3100", "tenant-1")

    if client.Ready() {
        fmt.Println("Loki is ready")
    }

    // Push logs
    streams := []Stream{
        {
            Stream: map[string]string{"app": "myapp"},
            Values: [][]string{
                {fmt.Sprintf("%d", time.Now().UnixNano()), "Test log message"},
            },
        },
    }
    client.Push(streams)

    // Query logs
    result, _ := client.QueryRange(
        `{app="myapp"}`,
        time.Now().Add(-time.Hour),
        time.Now(),
        100,
    )
    fmt.Printf("Result: %+v\n", result)
}
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **401 Unauthorized** | Нет X-Scope-OrgID header при auth_enabled: true | Добавьте `X-Scope-OrgID: <tenant-id>` в заголовки |
| **400 Bad Request** | Неверный формат query или start/end | Проверьте формат: start/end в nanosecond, query — валидный LogQL |
| **500 Internal Server Error** | Loki не может обработать запрос | Проверьте логи Loki, перезапустите компоненты |
| **413 Payload Too Large** | Push payload превышает max_body_size | Увеличьте `server.http_server_max_body_size` или разбейте payload |
| **timeout awaiting response** | Запрос выполняется слишком долго | Увеличьте `max_query_length`, уменьшите `limit`, оптимизируйте query |
| **"entry too large"** | Отдельный log entry превышает max_entry_size | Увеличьте `limits_config.max_entry_size` или уменьшите размер entry |
| **"too many entries"** | limit превышает max_query_series | Увеличьте `max_query_series` или уменьшите limit |

---

## Дополнительная информация

### Лучшие практики

1. **Используйте POST для Push API:** GET не поддерживает body, поэтому push всегда через POST.
2. **Сжимайте данные:** Используйте Snappy compression для Push API — снижает network traffic на 50–70%.
3. **Устанавливайте合理的 limits:** `limit=100` по умолчанию; для production — `limit=1000` с pagination.
4. **Валидируйте queries:** Перед отправкой проверяйте LogQL через Grafana Explore.
5. **Используйте tenant isolation:** Всегда передавайте `X-Scope-OrgID` в multi-tenant окружении.
6. **Мониторьте latency:** Используйте метрики `loki_request_duration_seconds` для отслеживания.
7. **Кэшируйте результаты:** Используйте Query Frontend с result cache для повторяющихся запросов.
8. **Версионируйте API:** Используйте фиксированные версии API (`/loki/api/v1/`).

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Эффективный LogQL](./loki_stack_setup/logql_examples.md) — продвинутые паттерны LogQL
- [Multi-tenancy в Loki](./loki_multi_tenancy_guide.md) — изоляция тенантов
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-конфигурация
