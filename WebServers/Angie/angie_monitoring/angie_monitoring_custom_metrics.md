# Мониторинг Angie — пользовательские метрики

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Модуль metric** (`ngx_http_metric_module` в HTTP и `ngx_stream_metric_module` в Stream) — встроенный модуль веб-сервера Angie (HTTP-модуль появился в Angie 1.6.0, Stream — в 1.7.0), предназначенный для создания произвольных числовых счетчиков, агрегатов и распределений (гистограмм) на основе внутренних переменных сервера. Модуль исключает необходимость развертывания внешних log-парсеров (mtail, Vector) для извлечения прикладной и сетевой телеметрии.

**Зона метрик (metric_zone)** — именованный сегмент в разделяемой памяти (Shared Memory), выделенный для агрегации метрик одного типа (`count`, `sum`, `gauge`, `histogram`, `average`, `min`, `max`, `last`) по динамическому ключу (например, код страны, тип клиента, имя сервиса).

**Комплексная зона метрик (metric_complex_zone)** — расширенная структура разделяемой памяти (появилась в Angie 1.11.0), позволяющая в рамках одной записи ключа агрегировать сразу несколько разнородных показателей (например, количество запросов, среднее время обработки и объем переданного трафика). Существенно снижает накладные расходы на служебные структуры и фрагментацию памяти.

**Директива metric** — операционная директива Angie, инициирующая запись или модификацию значения метрики в указанной зоне при наступлении определенной фазы обработки запроса или сессии (`on=request` или `on=end`).

**prometheus_template** — директива конфигурации Angie, связывающая внутренние JSON-пути API `/status/http/metric_zones/...` с именами метрик, лейблами и типами в формате OpenMetrics / Prometheus Text format. Позволяет веб-серверу нативно отдавать агрегированные кастомные показатели напрямую скрейперам Prometheus/VictoriaMetrics без внешних трансляторов.

**$p8s_value** — внутренняя системная переменная шаблонизатора `prometheus_template`, содержащая актуальное числовое значение метрики, извлеченное по соответствующему пути API.

**Политика вытеснения (expire) и discard_key** — механизм управления жизненным циклом записей в разделяемой памяти при нехватке места:
- `expire=on`: активирует LRU-вытеснение наименее востребованных ключей.
- `discard_key=<имя>`: резервирует специальный ключ, в котором суммируются числовые значения удаляемых записей, предотвращая расхождение глобальных счетчиков при ротации памяти.

**Аллокатор Slab (Slab Allocator)** — менеджер памяти ядра Angie, выделяющий внутри `metric_zone` слоты фиксированного размера (чанги) под узлы красно-черного дерева (rbtree) и очереди LRU. Состояние пулов контролируется через `/status/slabs/<zone>`.

**Кардинальность (Cardinality)** — количество уникальных ключей, регистрируемых в зоне метрик. Высокая кардинальность (High Cardinality) при использовании ненормализованных данных (UUID, произвольные URI, client IP) ведет к быстрому исчерпанию разделяемой памяти и деградации производительности TSDB.

**SRE Golden Signals (Четыре золотых сигнала)** — ключевые метрики работоспособности сервиса (Latency, Traffic, Errors, Saturation). Кастомные зоны метрик Angie позволяют формировать гранулярные SLI для задержек и ошибок на уровне L7 и L4 без задержки, характерной для обработки журналов.

**APDEX (Application Performance Index)** — международный стандарт оценки удовлетворенности пользователей производительностью приложения на основе категоризации времени ответа (удовлетворительно, допустимо, неудовлетворительно) через бакеты гистограммы.

---

## Базовые концепции и архитектура

### 1. Архитектура сбора данных в Shared Memory

Кастомные метрики функционируют на базе неблокирующих атомарных операций в разделяемой памяти Linux (`shmget`/`mmap`), разделяемой между master-процессом и всеми рабочими процессами (worker processes):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Рабочие процессы Angie                           │
│   Worker 1                     Worker 2                     Worker N        │
└───────┬────────────────────────────┬────────────────────────────┬───────────┘
        │                            │                            │
        │ Атомарные lock-free записи │ (без блокировки сокетов)   │
        ▼                            ▼                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Shared Memory (Аллокатор Slab)                          │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ metric_zone / metric_complex_zone                                       │ │
│ │  ├── Индекс: Красно-черное дерево (rbtree) поиска по ключам             │ │
│ │  ├── Очередь: Двусвязный список LRU (при expire=on)                     │ │
│ │  └── Значения: Счетчики, бакеты гистограмм, скользящие средние          │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────┬───────────────────┘
                       │                                  │
                       ▼                                  ▼
        ┌──────────────────────────────┐  ┌──────────────────────────────────┐
        │  ngx_http_api_module         │  │  ngx_http_prometheus_module      │
        │  GET /status/http/           │  │  Шаблонизатор prometheus_template│
        │  metric_zones/<zone>/...     │  │  GET /p8s (OpenMetrics / Text)   │
        └──────────────────────────────┘  └──────────────────────────────────┘
```

1. **Инициализация зон:** При старте или перезагрузке (`reload`) master-процесс создает сегменты разделяемой памяти заданного размера.
2. **Фиксация значений:** При наступлении выбранной фазы (`on=request` или `on=end`) воркер вычисляет ключ и значение переменной, находит узел в rbtree и атомарно обновляет структуру.
3. **Чтение через API:** Модуль `ngx_http_api_module` сериализует состояние узлов дерева в JSON.
4. **Формирование OpenMetrics:** Модуль `ngx_http_prometheus_module` обходит пути API по регулярным выражениям из `prometheus_template`, подставляя значения `$p8s_value` в поток ответа Prometheus.

### 2. Сравнение структур памяти: metric_zone vs metric_complex_zone

Выбор типа зоны напрямую влияет на потребление оперативной памяти и нагрузку на процессор:

| Параметр | Простая зона (`metric_zone`) | Комплексная зона (`metric_complex_zone`) |
|:---|:---|:---|
| **Количество метрик на ключ** | Строго 1 тип метрики | Несколько разнородных метрик |
| **Накладные расходы на ключ** | ~128 байт (rbtree-узел + LRU-ссылки) на каждую отдельную зону | ~128 байт суммарно на ключ для группы метрик |
| **Размер записи значения** | +8 байт (counter/gauge) или бакеты | +8 байт на каждое скалярное поле в структуре |
| **Поведение при обновлении** | Отдельный поиск в rbtree для каждого показателя | Один поиск ключа в rbtree для обновления группы метрик |
| **Рекомендуемое применение** | Одиночные счетчики (User-Agent, APDEX-гистограмма) | Профилирование API, заказы, биллинг, детальная статистика L4/L7 |

### 3. Жизненный цикл метрик (Lifecycle)

1. **Создание дескрипторов:** При запуске Angie выделяет память под зоны. Если при проверке конфигурации памяти недостаточно, сервер аварийно завершает старт с ошибкой аллокации.
2. **Агрегация в runtime:** Воркеры выполняют операции инкремента, вычисления EMA или раскладки по бакетам.
3. **Очистка и вытеснение (LRU Eviction):**
   - При `expire=off` (по умолчанию): при заполнении памяти новые ключи игнорируются, в журнал `error.log` пишется предупреждение `ngx_slab_alloc() failed`.
   - При `expire=on`: удаляется наименее востребованный узел. Если задан `discard_key=имя`, значения вытесняемого ключа суммируются в этом ключе.
4. **Персистентность при обслуживании:**
   - Команда `systemctl reload angie` (сигнал `SIGHUP`) **сохраняет** сегменты памяти и все накопленные метрики.
   - Команда `systemctl restart angie` полностью пересоздает разделяемую память, сбрасывая все счетчики в ноль.

### 4. Поддерживаемые типы агрегации

В директивах `metric_zone` и внутри блока `metric_complex_zone` доступны следующие типы показателей:

- **count** — монотонно растущий целочисленный счетчик событий (соответствует Prometheus `counter`).
- **sum** — накопление суммы числовых значений (например, переданных байт, стоимости заказов).
- **gauge** — текущее вещественное или целочисленное значение (может увеличиваться и уменьшаться).
- **histogram `<b1> <b2> ...`** — распределение значений по возрастающим бакетам. Angie автоматически добавляет финальный бакет `+Inf`.
- **average `mean|exp` `[window=time]` `[count=n]`** — расчет среднего значения:
  - `mean`: среднее арифметическое за окно выборки.
  - `exp`: экспоненциальное скользящее среднее (EMA) с учетом временного окна (`window=30s`) или количества событий (`count=100`).
- **min / max** — фиксация минимального или максимального значения за интервал времени.
- **last** — сохранение последнего переданного значения.

### 5. Моменты фиксации метрик (Фазовый контроль)

Параметр `on` директивы `metric` определяет фазу цикла обработки запроса:

```nginx
metric browsers $http_user_agent on=request;
metric backend_sla $server_name=$upstream_response_time on=end;
```

- **`on=request`** — срабатывает сразу после разбора заголовков HTTP-клиента (фаза `NGX_HTTP_POST_READ_PHASE`).
  - *Доступные переменные:* `$uri`, `$host`, `$http_user_agent`, `$remote_addr`, `$ssl_protocol`.
  - *Недоступные переменные:* `$status`, `$bytes_sent`, `$request_time`, `$upstream_response_time` (они еще не определены).
- **`on=end`** (по умолчанию) — срабатывает в фазе логирования после отправки всего тела ответа клиенту (`NGX_HTTP_LOG_PHASE`).
  - *Доступные переменные:* все внутренние тайминги, статусы проксирования и размер переданных данных.

### 6. Контекст Stream (L4-метрики)

Модуль `ngx_stream_metric_module` работает в контексте `stream` для TCP/UDP-проксирования. Директива `metric_zone` задается на уровне `stream`, а сбор осуществляется на уровне `server` в момент закрытия сессии:
- *Переменные L4:* `$session_time`, `$bytes_sent`, `$bytes_received`, `$status`, `$upstream_connect_time`.

---

## Практические сценарии и конфигурация

### Сценарий 1: SRE SLI/SLO мониторинг Latency и расчет APDEX

Отслеживание задержек обработки запросов бэкендами с бакетами под соглашения об уровне обслуживания (SLO: 50ms, 100ms, 250ms, 500ms, 1s, 2s).

```nginx
http {
    include /etc/angie/prometheus_all.conf;

    # Зона гистограммы времени ответа upstream с автоматической очисткой
    metric_zone upstream_latency:8m histogram 0.05 0.1 0.25 0.5 1.0 2.0 
        expire=on discard_key=expired;

    # Зона для расчета индекса APDEX (целевое T=0.5s, допустимое 4T=2.0s)
    metric_zone apdex_sla:4m histogram 0.5 2.0
        expire=on;

    server {
        listen 80;
        server_name api.example.internal;

        location /api/ {
            proxy_pass http://backend_pool;
            
            # Фиксация задержки бэкенда в разрезе виртуального хоста
            metric upstream_latency $server_name=$upstream_response_time on=end;
            
            # Фиксация времени полного запроса для расчета APDEX
            metric apdex_sla $server_name=$request_time on=end;
        }
    }
}
```

**Проверка через API:**
```bash
# Получение бакетов гистограммы задержек
curl -s http://127.0.0.1:8888/status/http/metric_zones/upstream_latency/metrics/api.example.internal/ | jq .
# → {
# →   "histogram": {
# →     "0.05": 14230,
# →     "0.1": 8940,
# →     "0.25": 1205,
# →     "0.5": 310,
# →     "1.0": 45,
# →     "2.0": 8,
# →     "Inf": 2
# →   }
# → }
```

### Сценарий 2: Защита от High Cardinality через нормализацию ключей в map

Прямая запись URI (`$uri`) или клиентских идентификаторов в метрики приводит к переполнению памяти и деградации Prometheus. Нормализация через `map` сжимает миллионы уникальных путей до фиксированных шаблонов.

```nginx
http {
    # Нормализация URI: замена UUID и числовых ID на статические плейсхолдеры
    map $uri $normalized_api_route {
        default                                "other";
        ~^/api/v[0-9]+/users/[0-9a-fA-F\-]+$   "/api/v1/users/:id";
        ~^/api/v[0-9]+/orders/[0-9]+$          "/api/v1/orders/:id";
        ~^/api/v[0-9]+/catalog/?$              "/api/v1/catalog";
        ~^/healthz$                            "/healthz";
    }

    # Классификация User-Agent для исключения длинных строк браузеров
    map $http_user_agent $client_device_type {
        default                  "desktop";
        ~*(android|iphone|ipad)  "mobile";
        ~*(curl|wget|promtool)   "tool";
        ~*(bot|crawler|spider)   "bot";
        ""                       "unknown";
    }

    # Выделение зоны с жестким ограничением кардинальности
    metric_zone api_routes:4m count expire=on discard_key=other_routes;
    metric_zone client_types:2m count;

    server {
        listen 80;

        location /api/ {
            proxy_pass http://backend_pool;

            metric api_routes $normalized_api_route on=request;
            metric client_types $client_device_type on=request;
        }
    }
}
```

**Проверка через API:**
```bash
curl -s http://127.0.0.1:8888/status/http/metric_zones/api_routes/metrics/ | jq keys
# → [
# →   "/api/v1/catalog",
# →   "/api/v1/orders/:id",
# →   "/api/v1/users/:id",
# →   "other",
# →   "other_routes"
# → ]
```

### Сценарий 3: Комплексная зона (metric_complex_zone) для L7-сервисов

Одновременный сбор агрегированных бизнес-показателей и задержек без фрагментации разделяемой памяти.

```nginx
http {
    # Объявление комплексной структуры метрик
    metric_complex_zone service_telemetry:16m {
        requests_total  count;
        bytes_sent      sum;
        latency_avg     average mean window=60s;
        latency_hist    histogram 0.05 0.1 0.25 0.5 1.0 2.5;
        errors_5xx      count;
    } expire=on discard_key=overflow;

    # Вычисление флага ошибки 5xx для инкремента
    map $status $is_server_error {
        ~^5  1;
        default 0;
    }

    server {
        listen 80;
        server_name checkout.example.internal;

        location /checkout/ {
            proxy_pass http://checkout_backend;

            # Атомарное обновление нескольких метрик в одной записи ключа
            metric service_telemetry "checkout_service"=requests_total:1 
                                     bytes_sent:$bytes_sent 
                                     latency_avg:$request_time 
                                     latency_hist:$request_time 
                                     errors_5xx:$is_server_error 
                                     on=end;
        }
    }
}
```

**Проверка через API:**
```bash
curl -s http://127.0.0.1:8888/status/http/metric_zones/service_telemetry/metrics/checkout_service/ | jq .
# → {
# →   "requests_total": 45120,
# →   "bytes_sent": 84219030,
# →   "latency_avg": 0.084,
# →   "latency_hist": {
# →     "0.05": 31000,
# →     "0.1": 11200,
# →     "0.25": 2500,
# →     "0.5": 380,
# →     "1.0": 35,
# →     "2.5": 5,
# →     "Inf": 0
# →   },
# →   "errors_5xx": 12
# → }
```

### Сценарий 4: Мониторинг L4 TCP/UDP-проксирования (Stream)

Сбор телеметрии сетевых задержек и объемов трафика для кластера баз данных PostgreSQL через модуль `ngx_stream_metric_module`.

```nginx
stream {
    # Зона метрик сессий PostgreSQL в контексте stream
    metric_zone pg_sessions:4m count expire=on;
    metric_zone pg_traffic_bytes:4m sum;
    metric_zone pg_duration:4m average mean window=5m;

    upstream pg_cluster {
        server 192.168.10.21:5432 max_fails=3 fail_timeout=10s;
        server 192.168.10.22:5432 backup;
    }

    server {
        listen 5432;
        proxy_pass pg_cluster;

        # Фиксация сетевых метрик по завершении TCP-сессии
        metric pg_sessions $server_addr;
        metric pg_traffic_bytes $server_addr=$bytes_sent;
        metric pg_duration $server_addr=$session_time;
    }
}
```

**Проверка через API Stream:**
```bash
curl -s http://127.0.0.1:8888/status/stream/metric_zones/pg_traffic_bytes/metrics/ | jq .
# → {
# →   "192.168.1.15": {
# →     "sum": 1548290400
# →   }
# → }
```

### Сценарий 5: Анализ эффективности и объема кэша

Отслеживание объема переданных данных в зависимости от статуса кэширования (`HIT`, `MISS`, `BYPASS`, `EXPIRED`).

```nginx
http {
    proxy_cache_path /var/cache/angie/data levels=1:2 keys_zone=static_cache:10m 
                     max_size=1g inactive=60m;

    metric_complex_zone cache_analytics:8m {
        cache_bytes sum;
        cache_ops   count;
    };

    server {
        listen 80;

        location /assets/ {
            proxy_pass http://static_origin;
            proxy_cache static_cache;
            proxy_cache_valid 200 302 60m;

            # Запись объема байт и операций под ключом статуса кэша
            metric cache_analytics $upstream_cache_status=cache_bytes:$bytes_sent 
                                   cache_ops:1 on=end;
        }
    }
}
```

**Проверка через API:**
```bash
curl -s http://127.0.0.1:8888/status/http/metric_zones/cache_analytics/metrics/ | jq .
# → {
# →   "HIT": { "cache_bytes": 482910300, "cache_ops": 18230 },
# →   "MISS": { "cache_bytes": 104820190, "cache_ops": 3120 },
# →   "EXPIRED": { "cache_bytes": 5210340, "cache_ops": 180 }
# → }
```

### Сценарий 6: Нативный экспорт кастомных метрик в Prometheus через prometheus_template

Экспорт кастомных зон в формате OpenMetrics без использования сторонних экспортеров с объединением со стандартными метриками.

```nginx
http {
    include /etc/angie/prometheus_all.conf;

    # Шаблон сопоставления путей API Angie с метриками Prometheus
    prometheus_template custom_sre_telemetry {
        # Преобразование комплексной зоны checkout_service в счетчики
        'angie_custom_service_requests_total{service="$1"}' $p8s_value
            path=~^/http/metric_zones/service_telemetry/metrics/([^/]+)/requests_total$
            type=counter;

        'angie_custom_service_errors_5xx_total{service="$1"}' $p8s_value
            path=~^/http/metric_zones/service_telemetry/metrics/([^/]+)/errors_5xx$
            type=counter;

        'angie_custom_service_latency_seconds_avg{service="$1"}' $p8s_value
            path=~^/http/metric_zones/service_telemetry/metrics/([^/]+)/latency_avg$
            type=gauge;

        # Экспорт бакетов гистограммы задержек
        'angie_custom_upstream_latency_seconds_bucket{service="$1",le="$2"}' $p8s_value
            path=~^/http/metric_zones/upstream_latency/metrics/([^/]+)/histogram/([^/]+)$
            type=counter;

        # Экспорт нормализованных маршрутов
        'angie_custom_route_requests_total{route="$1"}' $p8s_value
            path=~^/http/metric_zones/api_routes/metrics/([^/]+)/count$
            type=counter;
    }

    server {
        listen 127.0.0.1:9090;
        server_name localhost;

        location = /metrics {
            # Активация стандартных метрик (all) совместно с пользовательским шаблоном
            prometheus all custom_sre_telemetry;
            
            allow 127.0.0.1;
            allow 192.168.1.0/24;
            deny all;
        }
    }
}
```

**Валидация через curl и promtool:**
```bash
# Получение потока метрик
curl -s http://127.0.0.1:9090/metrics | grep 'angie_custom_' | head -n 8
# → # TYPE angie_custom_service_requests_total counter
# → angie_custom_service_requests_total{service="checkout_service"} 45120
# → # TYPE angie_custom_service_latency_seconds_avg gauge
# → angie_custom_service_latency_seconds_avg{service="checkout_service"} 0.084
# → # TYPE angie_custom_upstream_latency_seconds_bucket counter
# → angie_custom_upstream_latency_seconds_bucket{service="api.example.internal",le="0.05"} 14230
# → angie_custom_upstream_latency_seconds_bucket{service="api.example.internal",le="0.1"} 23170
# → angie_custom_upstream_latency_seconds_bucket{service="api.example.internal",le="+Inf"} 24740

# Синтаксическая валидация OpenMetrics через promtool
curl -s http://127.0.0.1:9090/metrics | promtool check metrics /dev/stdin
# → SUCCESS
```

### Сценарий 7: PromQL-запросы и правила алертинга Alertmanager

Готовые правила мониторинга SLO для Prometheus/VictoriaMetrics на основе кастомных метрик Angie.

```yaml
# /etc/prometheus/rules/angie_custom_alerts.yml
groups:
  - name: angie_custom_sli_alerts
    rules:
      # Расчет частоты запросов по сервисам (RPS)
      - record: job:angie_custom_requests:rate5m
        expr: sum by (service) (rate(angie_custom_service_requests_total[5m]))

      # Расчет доли ошибок 5xx (SLI Error Rate)
      - record: job:angie_custom_error_ratio:5m
        expr: >
          sum by (service) (rate(angie_custom_service_errors_5xx_total[5m]))
          /
          sum by (service) (rate(angie_custom_service_requests_total[5m]))

      # Расчет 95-го процентиля времени ответа upstream
      - record: job:angie_custom_p95_latency:5m
        expr: >
          histogram_quantile(0.95, sum by (service, le) (
            rate(angie_custom_upstream_latency_seconds_bucket[5m])
          ))

      # Алерт: Превышение бюджета ошибок (> 1% ошибок 5xx за 5 минут)
      - alert: AngieServiceHighErrorRate
        expr: job:angie_custom_error_ratio:5m > 0.01
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Высокая доля ошибок 5xx на Angie: {{ $labels.service }}"
          description: "Сервис {{ $labels.service }} отдает {{ $value | humanizePercentage }} ошибок 5xx (SLO порог: 1%)."

      # Алерт: Деградация задержек (P95 > 500мс)
      - alert: AngieServiceLatencySLOBreach
        expr: job:angie_custom_p95_latency:5m > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Превышение SLO времени ответа upstream: {{ $labels.service }}"
          description: "95-й процентиль задержки составляет {{ $value | humanizeDuration }} (порог: 500ms)."
```

### Сценарий 8: Автоматизация контроля зон метрик через Bash-скрипт

Скрипт для проверки заполнения slab-памяти зон, обнаружения аномалий кардинальности и сработавших `discard_key`.

```bash
#!/usr/bin/env bash
# /usr/local/bin/check_angie_metric_zones.sh
set -euo pipefail

API_BASE="http://127.0.0.1:8888/status"
CRITICAL_SLAB_PERCENT=85

echo "=== Проверка зон метрик Angie ==="

# 1. Проверка списка HTTP зон
zones=$(curl -sf "${API_BASE}/http/metric_zones/" | jq -r 'keys[]')

for zone in $zones; do
    key_count=$(curl -sf "${API_BASE}/http/metric_zones/${zone}/metrics/" | jq 'length')
    has_discard=$(curl -sf "${API_BASE}/http/metric_zones/${zone}/metrics/" | jq 'has("discard") or has("overflow") or has("expired")')
    
    echo "Зона: [${zone}] | Активных ключей: ${key_count}"
    
    if [ "${key_count}" -eq 0 ]; then
        echo "  ПРЕДУПРЕЖДЕНИЕ: Зона ${zone} пуста (счетчики не обновляются)!"
    fi
    
    if [ "${has_discard}" = "true" ]; then
        echo "  ВНИМАНИЕ: Зафиксированы вытесненные записи в discard_key зоны ${zone}!"
    fi
done

# 2. Проверка состояния разделяемой памяти Slab
echo -e "\n=== Состояние аллокатора Slab для зон метрик ==="
slab_data=$(curl -sf "${API_BASE}/slabs/")

for zone in $zones; do
    if echo "${slab_data}" | jq -e --arg z "${zone}" 'has($z)' > /dev/null; then
        total_pages=$(echo "${slab_data}" | jq -r --arg z "${zone}" '.[$z].pages.total')
        used_pages=$(echo "${slab_data}" | jq -r --arg z "${zone}" '.[$z].pages.used')
        usage_pct=$(( used_pages * 100 / total_pages ))
        
        echo "Зона Slab [${zone}]: занято ${usage_pct}% страниц (${used_pages}/${total_pages})"
        if [ "${usage_pct}" -ge "${CRITICAL_SLAB_PERCENT}" ]; then
            echo "  КРИТИЧЕСКАЯ ОШИБКА: Память зоны ${zone} близка к исчерпанию (${usage_pct}%)!"
        fi
    fi
done
```

**Исполнение и вывод:**
```bash
chmod +x /usr/local/bin/check_angie_metric_zones.sh
/usr/local/bin/check_angie_metric_zones.sh
# → === Проверка зон метрик Angie ===
# → Зона: [api_routes] | Активных ключей: 5
# → Зона: [service_telemetry] | Активных ключей: 1
# → Зона: [upstream_latency] | Активных ключей: 2
# → 
# → === Состояние аллокатора Slab для зон метрик ===
# → Зона Slab [api_routes]: занято 14% страниц (14/100)
# → Зона Slab [service_telemetry]: занято 28% страниц (112/400)
# → Зона Slab [upstream_latency]: занято 35% страниц (70/200)
```

---

## Операции и команды

### 1. Инспекция кастомных метрик через REST API

```bash
# Список всех зарегистрированных зон пользовательских метрик
curl -s http://127.0.0.1:8888/status/http/metric_zones/ | jq keys
# → [
# →   "api_routes",
# →   "client_types",
# →   "service_telemetry",
# →   "upstream_latency"
# → ]

# Детальная статистика ключей конкретной зоны
curl -s http://127.0.0.1:8888/status/http/metric_zones/upstream_latency/metrics/ | jq '{
  total_keys: length,
  sample_keys: (keys_unsorted[0:3])
}'
# → {
# →   "total_keys": 2,
# →   "sample_keys": [
# →     "api.example.internal",
# →     "expired"
# →   ]
# → }

# Чтение значений конкретного ключа в комплексной зоне
curl -s http://127.0.0.1:8888/status/http/metric_zones/service_telemetry/metrics/checkout_service/ | jq .
# → {
# →   "requests_total": 45120,
# →   "bytes_sent": 84219030,
# →   "latency_avg": 0.084,
# →   "errors_5xx": 12
# → }

# Чтение метрик уровня Stream L4
curl -s http://127.0.0.1:8888/status/stream/metric_zones/pg_sessions/metrics/ | jq .
# → {
# →   "192.168.1.15": 1420
# → }
```

### 2. Мониторинг аллокатора Slab и фрагментации памяти

```bash
# Проверка распределения слотов и свободной памяти для конкретной зоны метрик
curl -s http://127.0.0.1:8888/status/slabs/service_telemetry/ | jq '{
  pages_total: .pages.total,
  pages_used: .pages.used,
  pages_free: .pages.free,
  slots: [.slots[] | select(.reqs > 0) | {size: .size, used: .used, fails: .fails}]
}'
# → {
# →   "pages_total": 400,
# →   "pages_used": 112,
# →   "pages_free": 288,
# →   "slots": [
# →     { "size": 128, "used": 45, "fails": 0 },
# →     { "size": 256, "used": 12, "fails": 0 }
# →   ]
# → }
```

### 3. Проверка экспорта OpenMetrics / Prometheus

```bash
# Сбор и фильтрация кастомных метрик по префиксу
curl -s http://127.0.0.1:9090/metrics | grep '^angie_custom_'
# → angie_custom_service_requests_total{service="checkout_service"} 45120
# → angie_custom_service_latency_seconds_avg{service="checkout_service"} 0.084

# Проверка корректности типов (TYPE) кастомных метрик
curl -s http://127.0.0.1:9090/metrics | grep -E '^# TYPE angie_custom'
# → # TYPE angie_custom_service_requests_total counter
# → # TYPE angie_custom_service_latency_seconds_avg gauge
# → # TYPE angie_custom_upstream_latency_seconds_bucket counter

# Подсчет количества уникальных временных рядов (Series Count)
curl -s http://127.0.0.1:9090/metrics | grep -v '^#' | grep -c '^angie_'
# → 48
```

### 4. Верификация конфигурации и управление сервисом

```bash
# Проверка наличия модулей metric в скомпилированном бинарнике Angie
angie -V 2>&1 | grep -oE '\-\-with-(http|stream)_metric_module'
# → --with-http_metric_module
# → --with-stream_metric_module

# Синтаксическая валидация конфигурационных файлов с выводом активных зон
angie -T | grep -E 'metric_zone|metric_complex_zone|prometheus_template'
# → metric_zone upstream_latency:8m histogram ...;
# → metric_complex_zone service_telemetry:16m { ... };
# → prometheus_template custom_sre_telemetry { ... };

# Безопасная перезагрузка конфигурации с сохранением разделяемой памяти метрик
angie -t && systemctl reload angie
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

---

## Устранение неполадок

| Симптом | Первопричина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Ошибка: `unknown directive "metric_zone"` или `"metric"`** | Модуль `ngx_http_metric_module` не включен в сборку или отсутствует директива загрузки динамического модуля. | Выполнить `angie -V 2>&1 \| grep metric`. Проверить версию Angie (требуется ≥ 1.6.0). | Обновить Angie до актуальной версии (`dnf upgrade angie` / `apt install angie`). Убедиться, что модуль скомпилирован. |
| **Зона создана, но массив ключей в API пуст (`[]`)** | 1. Директива `metric` не добавлена в рабочий `location`.<br>2. Переменная-ключ пуста.<br>3. Переменная вычисляется позже фазы `on=request`. | Проверить значение переменной через `add_header X-Debug $var;`. Проверить фазу `on=request` vs `on=end`. | Использовать `on=end` для таймингов и статусов (`$upstream_response_time`, `$status`). Обеспечить значение ключа по умолчанию через `map`. |
| **Ошибки `ngx_slab_alloc() failed: no memory` в `error.log`** | Исчерпана разделяемая память зоны из-за высокой кардинальности (High Cardinality) при `expire=off`. | Проверить `error.log`: `grep 'ngx_slab_alloc' /var/log/angie/error.log`. Проверить `/status/slabs/<zone>`. | 1. Включить `expire=on`.<br>2. Настроить `discard_key`.<br>3. Увеличить размер зоны (`metric_zone name:32m`).<br>4. Нормализовать ключи через `map`. |
| **Метрики отсутствуют в выводе Prometheus (`/metrics`)** | Регулярное выражение `path` в `prometheus_template` не совпадает с реальным путем в JSON API. | Проверить точный путь через `curl http://127.0.0.1:8888/status/http/metric_zones/<zone>/metrics/<key>/`. | Исправить регулярное выражение `path=~^/...$` в `prometheus_template`. Убедиться в корректности номеров групп захвата (`$1`, `$2`). |
| **Promtool сообщает о синтаксической ошибке в метриках** | Недопустимые символы в именах меток, полученных из ключа, либо неверный маппинг типа. | Запустить `curl -s ... \| promtool check metrics /dev/stdin`. | Санитизировать ключи через `map`, исключая пробелы, кириллицу и спецсимволы. Использовать `counter` для сумм/счетчиков, `gauge` для задержек. |
| **Ключи обрезаются до нечитаемого вида** | Длина ключа превышает жесткий лимит ядра Angie в 255 байт. | Проверить ключи через `/status/http/metric_zones/<zone>/metrics/`. | Использовать хэширование (например, `$md5`) или нормализацию строк до фиксации в метрике. |
| **Значения метрик обнуляются после регламентных работ** | Сервис был перезапущен командой `restart` вместо `reload`. | Проверить аптайм мастер-процесса: `systemctl status angie`. | Использовать `systemctl reload angie` (сигнал `SIGHUP`) для применения конфигурации без сброса Shared Memory. |
| **Значение `discard_key` лавинообразно растет** | Скорость появления новых ключей превышает емкость зоны; активный LRU-сброс искажает гранулярность. | Сравнить значение ключа `discard` с остальными через API. | Увеличить размер зоны памяти и сократить кардинальность нормализацией. |

---

## Лучшие практики

### 1. Безопасность (Security)

- **Изоляция эндпоинтов телеметрии:** Запрещайте доступ к эндпоинтам `/status/` и `/metrics` из внешних публичных сетей. Размещайте их на выделенном Loopback-интерфейсе (`127.0.0.1:9090`) или внутренней сети управления:
  ```nginx
  server {
      listen 127.0.0.1:9090;
      server_name localhost;

      location /metrics {
          prometheus all custom_sre_telemetry;
          allow 127.0.0.1;
          allow 10.200.0.0/16; # Подсеть серверов Prometheus
          deny all;
      }
  }
  ```
- **Предотвращение утечки персональных данных (PII):** Никогда не используйте в качестве ключей `metric` сырые значения `$http_authorization`, `$request_uri` (содержащие токены в Query string), email или номера телефонов. Это нарушает требования безопасности и приводит к неконтролируемой кардинальности.

### 2. Производительность и сайзинг памяти (Sizing & Performance)

- **Расчет необходимого объема Shared Memory:**
  Каждая уникальная запись ключа требует:
  $$\text{Memory per Key} \approx 128\text{ байт (rbtree + LRU)} + \text{длина ключа} + \text{размер структуры метрик}$$
  - Для простой зоны `count` с 10 000 уникальных ключей средней длины 32 байта:
    $$10\,000 \times (128 + 32 + 8) \approx 1.68\text{ МБ}$$
    *Рекомендация:* выделять зону с двукратным запасом — `metric_zone routes:4m count expire=on;`.
  - Для гистограммы на 8 бакетов:
    $$10\,000 \times (128 + 32 + 9 \times 8) \approx 2.32\text{ МБ}$$
    *Рекомендация:* выделять зону не менее 8 МБ.
- **Применение `metric_complex_zone`:** Если требуется собирать 3 и более метрик по одному объекту (например, RPS, Latency, Bytes), всегда используйте `metric_complex_zone` вместо нескольких `metric_zone`. Это снижает расход памяти на 60–70% за счет исключения дублирования узлов rbtree и очередей LRU.
- **Обязательное использование `expire=on` и `discard_key`:** В продакшн-контурах зоны с динамическими ключами всегда должны объявляться с параметрами `expire=on discard_key=expired_total`. Это гарантирует стабильность веб-сервера при резких всплесках кардинальности без потери общих сумм.

### 3. Эксплуатация и SRE (Operational Excellence)

- **Нормализация через `map`:** Любой пользовательский ввод перед передачей в метрики должен валидироваться через `map` со строгим значением `default`.
- **Мониторинг самого мониторинга:** Настройте в Alertmanager оповещение на заполненность страниц slab-аллокатора зон метрик (`/status/slabs/`) с порогом 80%, чтобы заранее выявлять нехватку памяти.
- **Валидация при CI/CD:** Перед деплоем конфигурации с новыми шаблонами `prometheus_template` выполняйте валидацию синтаксиса OpenMetrics через тестовый скрейп и утилиту `promtool`.

---

## Дополнительная информация

### Сравнение подходов к сбору метрик

| Критерий | Angie Custom Metrics (`metric_zone`) | Стандартные зоны (`status_zone`) | Парсинг логов (Vector / mtail) | Внешний экспортер (Sidecar) |
|:---|:---|:---|:---|:---|
| **Потребление CPU** | Минимальное (lock-free атомарные операции в RAM) | Минимальное | Высокое (парсинг строк логов на диске) | Среднее (периодический опрос API и сериализация) |
| **Задержка данных** | 0 секунд (реальное время) | 0 секунд | Задержка буферизации диска (1–5 сек) | Задержка интервала скрейпинга (15–30 сек) |
| **Гибкость ключей** | Любые переменные сервера, вычисляемые поля, мапы | Фиксированные сущности (сервер, локация, апстрим) | Любые поля из строки лога | Ограничено метриками экспортера |
| **Поддержка гистограмм** | Произвольные бакеты для любых таймингов | Только базовые тайминги апстримов | Настраиваемые бакеты | Фиксированные бакеты |
| **Персистентность** | В RAM (сброс при restart, сохранение при reload) | В RAM | На диске в файле лога | Зависит от хранилища TSDB |
| **Автономность** | Полная (встроено в бинарник Angie) | Полная | Требует отдельного процесса демона | Требует отдельного процесса демона |

### Технические ограничения

1. **Максимальная длина ключа:** 255 байт. Строки большей длины усекаются, что может приводить к коллизиям ключей.
2. **Волатильность памяти при перезапуске:** Данные зон хранятся в ОЗУ. При аварийном падении хоста или выполнении `systemctl restart` значения обнуляются. Историчность должна обеспечиваться внешним хранилищем временных рядов (Prometheus, VictoriaMetrics).
3. **Режим API:** В версии Angie Open Source чтение данных через `/status/` работает строго в режиме `read-only` (методы GET и HEAD). Ручной сброс счетчиков через API без перезапуска master-процесса не поддерживается.

### Связанные ссылки

- [Основные концепции мониторинга Angie](./angie_monitoring_concepts.md) — расчет разделяемой памяти, архитектура worker-процессов и slab-аллокатор.
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md) — базовые шаблоны `prometheus_all.conf`, настройка скрейпинга и типы метрик.
- [Работа с конфигурацией через API](./angie_monitoring_api.md) — полная спецификация REST-эндпоинтов, структуры JSON и методы доступа.
- [Настройка Console Light и API](./angie_monitoring_console.md) — интерактивная веб-панель мониторинга в режиме реального времени.
- [Возможности Angie Pro](./angie_monitoring_pro.md) — активные проверки доступности `upstream_probe` и расширенные функции мониторинга.

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
- [Работа с конфигурацией через API](./angie_monitoring_api.md)
- [Настройка Console Light и API](./angie_monitoring_console.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
