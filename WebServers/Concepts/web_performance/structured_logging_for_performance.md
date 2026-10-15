# Structured Logging и анализ для веб-производительности

**Актуально для:** Nginx 1.26+, Angie 1.8+ / 1.12.x, Envoy 1.30+, Linux Kernel 5.15+ / 6.x, Vector 0.40+, ClickHouse 24.x+

## Определения

**Structured Logging (Структурированное логирование)** — метод записи событий веб-сервера в стандартизированном машиночитаемом формате (преимущественно JSON или NDJSON), где каждое поле обладает строгим именем и типизированным значением. В отличие от неструктурированных текстовых строк (`Combined Log Format`), исключает необходимость в ресурсоемком и нестабильном парсинге регулярными выражениями (regex) на стороне сборщиков логов.

**Access Log (Журнал доступа)** — системный журнал веб-сервера или обратного прокси (Reverse Proxy), фиксирующий метаданные каждого завершенного клиентского HTTP/HTTPS-запроса или сессии. В задачах анализа веб-производительности служит первичным источником гранулярных таймингов и метрик передачи данных.

**Декомпозиция времени ответа (Timing Breakdown)** — набор взаимосвязанных временных метрик, фиксируемых веб-сервером на различных этапах жизненного цикла запроса:
*   `$request_time` (в Nginx/Angie) / `%DURATION%` (в Envoy) — общее время обработки запроса с момента считывания первых байт от клиента до отправки последнего байта ответа в сетевой сокет (включая ожидание клиента и сетевую передачу).
*   `$upstream_connect_time` — время, затраченное на установление TCP-соединения (или TCP + TLS handshake) с вышестоящим бэкендом (upstream).
*   `$upstream_header_time` — задержка между отправкой запроса бэкенду и получением первого байта заголовков ответа (истинный серверный Time to First Byte — TTFB бэкенда).
*   `$upstream_response_time` — полное время от начала соединения с бэкендом до получения последнего байта тела ответа от него.

**Kernel Socket Metrics (`$tcpinfo_rtt`, `$tcpinfo_rttvar`, `$tcpinfo_snd_cwnd`)** — диагностические метрики клиентского TCP-соединения, извлекаемые веб-сервером из ядра Linux через системный вызов `getsockopt(..., IPPROTO_TCP, TCP_INFO, ...)`. Позволяют выявить, вызвана ли высокая задержка `$request_time` медленным сетевым каналом пользователя (высокий RTT) или серверным узким местом.

**Буферизация записи логов (`buffer=size`, `flush=time`)** — механизм агрегации сформированных строк журнала в оперативной памяти рабочего процесса (worker process) перед сбросом на диск с помощью системного вызова `write(2)`. Предотвращает блокировку цикла обработки событий (Event Loop) при дисковых задержках.

**Сэмплирование и условное логирование (`if=condition`)** — выборочная запись запросов на основе заданных критериев (HTTP-статус, длительность выполнения, принадлежность к синтетическим health check). Позволяет на 80–95% сократить объем дискового ввода-вывода (I/O) и трафика доставки логов в высоконагруженных системах без потери критических аномалий.

**Экранирование символов (`escape=json`)** — встроенный режим сериализации строк в Nginx/Angie, заменяющий специальные управляющие символы (переводы строк, кавычки, null-байты) на безопасные escape-последовательности формата JSON, что предотвращает инъекции в лог и поломку парсеров.

**Correlation ID / W3C Trace Context (`$request_id`, `traceparent`)** — уникальный сквозной идентификатор транзакции, генерируемый граничным прокси или передаваемый клиентом в заголовках `X-Request-ID` или `traceparent` (RFC W3C Trace Context). Позволяет сопоставлять запись access-лога веб-сервера с логами микросервисов бэкенда и спанами распределенной трассировки.

**Logs-to-Metrics (Метрики из логов)** — архитектурный паттерн извлечения числовых агрегатов (счетчики кодов, квантили и перцентили задержек p50, p95, p99, гистограммы) непосредственно из потока структурированных логов для вычисления SLI/SLO и визуализации в системах мониторинга.

---

## Архитектура и базовые концепции

### Анатомия задержек запроса на Reverse Proxy

При оценке производительности веб-приложений ключевой задачей SRE/DevOps является локализация узкого места: возникла ли задержка на сетевом плече «клиент — прокси», внутри самого веб-сервера, на сетевом плече «прокси — бэкенд» или в коде/базе данных бэкенда.

В архитектуре Nginx/Angie тайминги соотносятся следующим образом:

```text
[ Клиент ] ──────── TCP Handshake / TLS ────────► [ Nginx / Angie ] ────── TCP / TLS ──────► [ Upstream Бэкенд ]
    │                                                     │                                          │
    │── HTTP Request Headers / Body ─────────────────────►│ (Старт: $request_time)                   │
    │                                                     │── Connect ($upstream_connect_time) ─────►│
    │                                                     │── Request transmission ─────────────────►│
    │                                                     │                                          │ [ Обработка ]
    │                                                     │◄─ First Header Byte ($u_header_time) ────│ (TTFB бэкенда)
    │                                                     │◄─ Last Body Byte ($u_response_time) ─────│
    │◄─ Response Headers & First Bytes ───────────────────│                                          │
    │◄─ Last Response Byte ───────────────────────────────│ (Конец: $request_time, фаза NGX_HTTP_LOG)
```

#### Математические зависимости и интерпретация метрик

1.  **Сетевая задержка до бэкенда:**
    $$\Delta t_{\text{connect}} = \$upstream\_connect\_time$$
    Если значение превышает 1–2 мс в локальной сети датацентра (on-premise), это сигнализирует о переполнении очереди сокетов бэкенда (`listen backlog`), нехватке свободных воркеров приложения, исчерпании эфемерных портов или отсутствии Keepalive-пула соединений.
2.  **Чистое время генерации ответа бэкендом (Backend Latency / TTFB):**
    $$\Delta t_{\text{backend\_processing}} = \$upstream\_header\_time - \$upstream\_connect\_time$$
    Отражает время, затраченное бэкендом (PHP-FPM, Go, Node.js, Java) на обработку бизнес-логики и ожидание запросов к СУБД/кэшу до отправки первого байта HTTP-заголовков.
3.  **Время отдачи тела бэкендом:**
    $$\Delta t_{\text{backend\_transfer}} = \$upstream\_response\_time - \$upstream\_header\_time$$
    Задержка вызвана генерацией или передачей тяжелого тела ответа (например, выгрузка большого JSON или потокового файла).
4.  **Клиентская задержка и передача по внешней сети:**
    $$\Delta t_{\text{client\_network}} = \$request\_time - \$upstream\_response\_time$$
    *   **$\Delta t_{\text{client\_network}} \approx 0$**: Сеть быстрая, ответ компактный; общее время полностью лимитировано бэкендом.
    *   **$\Delta t_{\text{client\_network}} \gg 0$**: Бэкенд ответил мгновенно, но клиент медленно считывает данные из сокета (высокий RTT, мобильная связь, блокировка TCP Receive Window), либо клиент медленно отправлял `POST`/`PUT` payload на прокси до обращения к апстриму.

---

### Влияние подсистемы логирования на системную производительность

Запись журналов в высоконагруженных окружениях (10 000 – 100 000+ RPS) способна стать критическим фактором деградации производительности:

```text
[ Небуферизованный лог (По умолчанию) ]
Worker Event Loop ──► Сформирована строка ──► write(2) ──► Блокировка ядра (I/O Wait / Page Lock)
* Любая задержка дисковой подсистемы (flush dirty pages, RAID sync) блокирует рабочий поток Nginx,
  замораживая обработку сотен параллельных сетевых соединений в данном воркере.

[ Оптимизированный буферизованный лог ]
Worker Event Loop ──► Запись в кольцевой буфер RAM ──► Возврат в Event Loop (0 системных вызовов)
                               │
                [ По достижении buffer=128k или таймаута flush=1s ]
                               │
                               ▼
               Пакетный системный вызов write(2)
```

1.  **Блокировка рабочего потока (Event Loop Stalls):**
    Nginx и Angie используют неблокирующий асинхронный цикл обработки событий на базе `epoll(7)`. Однако стандартные системные вызовы `write(2)` в обычный файл на диске **не являются неблокирующими**. Если ядро сбрасывает грязные страницы (`dirty pages`) на диск или дисковый массив перегружен, процесс переходит в состояние `D` (Uninterruptible Sleep), прекращая обработку сетевых событий.
2.  **Экономия процессорных циклов (Syscall Overhead):**
    При 50 000 RPS небуферизованное логирование выполняет 50 000 системных вызовов `write(2)` в секунду, вызывая постоянные переключения контекста между User-Space и Kernel-Space. Буфер размером `128k` сбрасывает данные пачками по 200–500 записей за один вызов, снижая накладные расходы ядра более чем на 90%.
3.  **Дисковый DoS (I/O Saturation):**
    Всплеск ошибок 5xx при сбое базы данных генерирует лавину подробных логов, приводя к исчерпанию дисковых IOPS и переполнению раздела `/var/log`.

---

### Архитектура конвейера доставки и аналитики логов (Logs-to-Metrics)

Для анализа производительности на уровне SRE используется разделение контура сбора и хранения на компоненты с открытым исходным кодом без облачных зависимостей:

```text
┌───────────────────────┐
│     Nginx / Angie     │ (Fast Path: буферизованная запись NDJSON)
└───────────┬───────────┘
            │
            ▼ /var/log/nginx/access_perf.json (или UNIX Domain Socket)
┌───────────────────────┐
│        Vector         │ (Локальный агент: парсинг, типизация, дедупликация)
└───────────┬───────────┘
            │
            ├────────────────────────────────────────┐
            ▼ (Batch HTTP/TCP)                       ▼ (Batch HTTP)
┌───────────────────────┐                ┌───────────────────────┐
│      ClickHouse       │                │      Grafana Loki     │
│ (OLAP-база: тайминги, │                │ (Индексация метаданных│
│  перцентили, аналитика│                │  и поиск по трейсам)  │
│  по миллиардам строк) │                └───────────────────────┘
└───────────────────────┘
```

1.  **Локальный транспорт:** Логи пишутся веб-сервером в локальный файл с ротацией либо в UNIX Domain Socket / именованный пайп (`FIFO`).
2.  **Агент сбора (Vector / Fluent Bit):** Агент читает строки, выполняет десериализацию JSON, преобразует строковые значения в типы `Float32`/`UInt32`, обрабатывает ретраи апстримов и группирует записи в микробатчи.
3.  **Аналитическое хранилище (ClickHouse):** Колоночная СУБД ClickHouse с движком `MergeTree` обеспечивает сжатие данных логов в 5–10 раз и расчет перцентилей задержки (p50, p95, p99) по миллионам записей за доли секунды.

---

## Практические сценарии

### Сценарий 1: Эталонный производственный JSON-лог в Nginx / Angie

Стандартная директива `log_format` в Nginx при пустом значении апстрима (например, если запрос обслужен из кэша или локально) записывает дефис `"-"`. Если в шаблоне JSON числовое поле объявлено без кавычек (`"upstream_response_time": $upstream_response_time`), Nginx формирует невалидный JSON: `"upstream_response_time": -`, что приводит к аварийному сбросу парсеров Vector/Logstash.

Ниже приведена надежная конфигурация с предварительной нормализацией через `map` и включением метрик TCP ядра Linux:

```nginx
# /etc/nginx/conf.d/logging_perf.conf

# 1. Нормализация числовых переменных: замена дефиса на null или 0
map $upstream_response_time $clean_upstream_response_time {
    ""        null;
    "-"       null;
    default   $upstream_response_time;
}

map $upstream_connect_time $clean_upstream_connect_time {
    ""        null;
    "-"       null;
    default   $upstream_connect_time;
}

map $upstream_header_time $clean_upstream_header_time {
    ""        null;
    "-"       null;
    default   $upstream_header_time;
}

# 2. Сэмплирование: отключение логирования успешных статических файлов и health check
map $status $is_error {
    ~^[45]    1;  # 4xx и 5xx логируются всегда
    default   0;
}

map $request_uri $is_healthcheck {
    ~*^/(healthz|ready|live|metrics)$  1;
    default                             0;
}

# Логируем, если это ошибка, либо если это не health-check
map $is_error$is_healthcheck $loggable {
    "01"      0;  # 2xx/3xx на healthcheck -> НЕ логировать
    default   1;  # Все остальные запросы -> логировать
}

# 3. Определение структурированного JSON-формата
log_format performance_json escape=json '{'
    '"timestamp":"$time_iso8601",'
    '"request_id":"$request_id",'
    '"client_ip":"$remote_addr",'
    '"vhost":"$host",'
    '"method":"$request_method",'
    '"uri":"$uri",'
    '"args":"$args",'
    '"protocol":"$server_protocol",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"body_bytes_sent":$body_bytes_sent,'
    '"request_length":$request_length,'
    '"request_time":$request_time,'
    '"upstream_addr":"$upstream_addr",'
    '"upstream_status":"$upstream_status",'
    '"upstream_connect_time":$clean_upstream_connect_time,'
    '"upstream_header_time":$clean_upstream_header_time,'
    '"upstream_response_time":$clean_upstream_response_time,'
    '"upstream_cache_status":"$upstream_cache_status",'
    '"tcp_rtt_us":$tcpinfo_rtt,'
    '"tcp_snd_cwnd":$tcpinfo_snd_cwnd,'
    '"connection":$connection,'
    '"connection_requests":$connection_requests,'
    '"http_user_agent":"$http_user_agent"'
'}';

# 4. Применение буферизованной записи с фильтрацией
server {
    listen 80;
    listen 443 ssl reuseport;
    server_name api.internal.local;

    # Буфер 256k, принудительный сброс каждую секунду, фильтр $loggable
    access_log /var/log/nginx/access_perf.json performance_json buffer=256k flush=1s if=$loggable;
    error_log  /var/log/nginx/error.log warn;

    location / {
        proxy_pass http://backend_pool;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

### Сценарий 2: Структурированное логирование задержек в Envoy Proxy

Для инфраструктур на базе Envoy Proxy (API Gateway / Ingress) структурированное логирование настраивается через фильтр `envoy.access_loggers.file`:

```yaml
# /etc/envoy/envoy.yaml (фрагмент фильтра HTTP Connection Manager)
static_resources:
  listeners:
  - name: ingress_listener
    address:
      socket_address: { address: 0.0.0.0, port_value: 8080 }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http
          access_log:
          - name: envoy.access_loggers.file
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.access_loggers.file.v3.FileAccessLog
              path: /var/log/envoy/access_perf.json
              log_format:
                json_format:
                  timestamp: "%START_TIME(%Y-%m-%dT%H:%M:%S.%3fZ)%"
                  request_id: "%REQ(X-REQUEST-ID)%"
                  client_ip: "%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%"
                  authority: "%REQ(:AUTHORITY)%"
                  method: "%REQ(:METHOD)%"
                  path: "%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%"
                  status: "%RESPONSE_CODE%"
                  response_flags: "%RESPONSE_FLAGS%"
                  bytes_received: "%BYTES_RECEIVED%"
                  bytes_sent: "%BYTES_SENT%"
                  duration_ms: "%DURATION%"
                  upstream_service_time_ms: "%RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)%"
                  upstream_cluster: "%UPSTREAM_CLUSTER%"
                  upstream_host: "%UPSTREAM_HOST%"
                  downstream_direct_rtt_us: "%DOWNSTREAM_DIRECT_REMOTE_ADDRESS_RTT%"
```

---

### Сценарий 3: Конвейер сбора и нормализации в Vector (VRL) с записью в ClickHouse

При работе механизма `proxy_next_upstream` в Nginx (повторные попытки при таймаутах) переменные `$upstream_response_time` и `$upstream_addr` содержат несколько значений через запятую: `"0.500, 0.020"`. Агент Vector на базе языка преобразований VRL (Vector Remap Language) разделяет эти значения и отправляет данные напрямую в ClickHouse по протоколу HTTP.

Конфигурация `/etc/vector/vector.yaml`:

```yaml
sources:
  nginx_perf_logs:
    type: file
    include:
      - /var/log/nginx/access_perf.json
    read_from: beginning

transforms:
  normalize_and_clean:
    type: remap
    inputs:
      - nginx_perf_logs
    source: |
      # Парсинг NDJSON
      payload, err = parse_json(.message)
      if err != null {
        abort
      }

      # Перенос полей в корень события
      . = payload

      # Обработка цепочки ретраев upstream_response_time ("0.500, 0.020" -> берем финальный тайминг)
      if is_string(.upstream_response_time) {
        parts = split!(string!(.upstream_response_time), ", ")
        .upstream_response_time = to_float(parts[-1]) ?? null
      }

      # Приведение числовых типов для ClickHouse
      .status = to_int!(.status)
      .bytes_sent = to_int!(.bytes_sent)
      .body_bytes_sent = to_int!(.body_bytes_sent)
      .request_length = to_int!(.request_length)
      .request_time = to_float!(.request_time)
      .tcp_rtt_ms = (to_float(.tcp_rtt_us) ?? 0.0) / 1000.0

      # Вычисление чистой клиентской задержки
      if .upstream_response_time != null {
        .client_network_latency = .request_time - .upstream_response_time
      } else {
        .client_network_latency = 0.0
      }

sinks:
  clickhouse_storage:
    type: clickhouse
    inputs:
      - normalize_and_clean
    endpoint: "http://127.0.0.1:8123"
    database: "observability"
    table: "nginx_access_perf"
    skip_unknown_fields: true
    batch:
      max_bytes: 10485760  # 10 МБ
      timeout_secs: 2
```

---

### Сценарий 4: Создание схемы и аналитические запросы в ClickHouse

#### 1. DDL таблицы с эффективным сжатием и партиционированием

```sql
CREATE DATABASE IF NOT EXISTS observability;

CREATE TABLE observability.nginx_access_perf
(
    timestamp DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    request_id String CODEC(ZSTD(3)),
    client_ip IPv4 CODEC(ZSTD(1)),
    vhost LowCardinality(String),
    method LowCardinality(String),
    uri String CODEC(ZSTD(3)),
    status UInt16 CODEC(T64, ZSTD(1)),
    bytes_sent UInt64 CODEC(T64, ZSTD(1)),
    request_time Float32 CODEC(Gorilla, ZSTD(1)),
    upstream_addr LowCardinality(String),
    upstream_status LowCardinality(String),
    upstream_connect_time Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    upstream_header_time Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    upstream_response_time Nullable(Float32) CODEC(Gorilla, ZSTD(1)),
    upstream_cache_status LowCardinality(String),
    tcp_rtt_ms Float32 CODEC(Gorilla, ZSTD(1)),
    client_network_latency Float32 CODEC(Gorilla, ZSTD(1))
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (status, vhost, uri, timestamp)
SETTINGS index_granularity = 8192;
```

#### 2. SQL-запрос: Анализ квантилей производительности (P50, P90, P99) по эндпоинтам

```sql
-- Расчет распределения задержек бэкенда и сети за последний час
SELECT
    uri,
    count() AS total_requests,
    round(quantile(0.50)(request_time), 3) AS req_time_p50,
    round(quantile(0.95)(request_time), 3) AS req_time_p95,
    round(quantile(0.99)(request_time), 3) AS req_time_p99,
    round(quantile(0.95)(upstream_header_time), 3) AS backend_ttfb_p95,
    round(quantile(0.95)(client_network_latency), 3) AS client_net_p95,
    round(avg(tcp_rtt_ms), 2) AS avg_tcp_rtt_ms
FROM observability.nginx_access_perf
WHERE timestamp >= now() - INTERVAL 1 HOUR
  AND status = 200
GROUP BY uri
HAVING total_requests > 100
ORDER BY req_time_p99 DESC
LIMIT 10;
```

#### 3. SQL-запрос: Локализация виновников клиентских обрывов (HTTP 499)

Код 499 выставляется Nginx, когда клиент закрывает соединение до завершения передачи ответа сервером. Запрос определяет, бросает ли клиент соединение из-за долгого ответа бэкенда или проблема в сетевом канале:

```sql
SELECT
    uri,
    upstream_addr,
    count() AS total_aborts,
    round(avg(request_time), 3) AS avg_wait_before_abort,
    round(avg(upstream_header_time), 3) AS avg_backend_ttfb,
    round(avg(tcp_rtt_ms), 2) AS avg_client_rtt
FROM observability.nginx_access_perf
WHERE timestamp >= now() - INTERVAL 3 HOUR
  AND status = 499
GROUP BY uri, upstream_addr
ORDER BY total_aborts DESC
LIMIT 10;
```

---

### Сценарий 5: Локальный экспресс-анализ логов через `clickhouse-local` и CLI-утилиты

Для экстренной диагностики на боевом сервере без подключения к централизованным базам используется легковесная утилита `clickhouse-local`:

```bash
# Мгновенный расчет перцентилей задержек прямо из JSON-файла
clickhouse-local --query "
SELECT
    status,
    count() AS req_count,
    round(quantile(0.50)(request_time), 3) AS p50,
    round(quantile(0.95)(request_time), 3) AS p95,
    round(quantile(0.99)(request_time), 3) AS p99,
    round(max(request_time), 3) AS max_time
FROM file('/var/log/nginx/access_perf.json', JSONEachRow)
WHERE timestamp >= now() - INTERVAL 15 MINUTE
GROUP BY status
ORDER BY req_count DESC;"
```

Пример вывода:
```text
┌─status─┬─req_count─┬───p50─┬───p95─┬───p99─┬─max_time─┐
│    200 │     45210 │ 0.012 │ 0.085 │ 0.241 │    1.120 │
│    304 │      8120 │ 0.002 │ 0.005 │ 0.011 │    0.045 │
│    502 │       340 │ 3.001 │ 3.002 │ 3.004 │    3.005 │
│    499 │       120 │ 1.540 │ 2.890 │ 4.120 │    5.002 │
└────────┴───────────┴───────┴───────┴───────┴──────────┘
# → Сразу видна аномалия: код 502 жестко висит на 3.001s (сработал таймаут proxy_connect_timeout)
```

---

## Операции и команды

### Валидация и проверка целостности журналов

```bash
# 1. Валидация синтаксиса конфигурации веб-сервера
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Проверка корректности формирования JSON первых 100 строк лога
head -n 100 /var/log/nginx/access_perf.json | jq -e . > /dev/null
echo $?
# → 0 (ошибок нет, синтаксис NDJSON валиден)

# 3. Фильтрация медленных запросов (>1 секунды) в потоковом режиме с форматированием
tail -f /var/log/nginx/access_perf.json | jq -r 'select(.request_time > 1.0) | "[\(.timestamp)] \(.status) \(.method) \(.uri) | total=\(.request_time)s upstream=\(.upstream_response_time)s rtt=\(.tcp_rtt_us)us"'
# → [2026-10-14T19:50:00+03:00] 200 GET /api/v1/search | total=1.450s upstream=1.420s rtt=3500us
```

### Безопасная ротация без потери буферизованных данных

```bash
# Конфигурация Logrotate: /etc/logrotate.d/nginx_perf
cat << 'EOF' > /etc/logrotate.d/nginx_perf
/var/log/nginx/access_perf.json {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        # Отправка сигнала USR1 мастер-процессу для переоткрытия дескрипторов
        [ -f /run/nginx.pid ] && kill -USR1 $(cat /run/nginx.pid)
    endscript
}
EOF

# Тестовый прогон ротации в режиме отладки
logrotate -d /etc/logrotate.d/nginx_perf
# → reading config file /etc/logrotate.d/nginx_perf
# → handling /var/log/nginx/access_perf.json ...
```

### Диагностика дисковой утилизации подсистемы логирования

```bash
# Мониторинг задержек дискового ввода-вывода (поиск высоких await и утилизации %util)
iostat -xz 1 5
# → Device: r/s  w/s   rkB/s   wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await w_await aqu-sz rareq-sz wareq-sz  svctm  %util
# → nvme0n1 0.00 450.00 0.00  57600.00 0.00   120.00  0.00   21.05   0.00    0.12    0.05    0.00   128.00   0.02   1.10

# Мониторинг объема дискового ввода-вывода конкретных процессов Nginx
pidstat -d -p $(pgrep -d',' -f "nginx: worker") 1 3
# → 19:51:00 UID PID   kB_rd/s kB_wr/s kB_ccwr/s iodelay Command
# → 19:51:01 33  14210 0.00    4200.00 0.00      0       nginx
```

---

## Диагностика и устранение неисправностей

| Проблема | Диагностика | Первопричина | Решение |
| :--- | :--- | :--- | :--- |
| **Воркеры Nginx зависают в состоянии `D` (I/O wait)** | `top -b -n 1 \| grep nginx`, проверка поля `S` (значение `D`). `pidstat -d` показывает задержки диска. | Небуферизованный `access_log` выполняет синхронный системный вызов `write(2)` при высокой нагрузке на диск. | Добавить параметры буферизации `buffer=128k flush=1s` в директиву `access_log`. |
| **Падение агентов сбора (Vector / Fluent Bit) с ошибкой JSON-парсинга** | В логах агента: `expected value at line 1 column 145`. Анализ через `jq . /var/log/nginx/access_perf.json`. | Отсутствие кавычек вокруг переменной `$upstream_response_time` при пустом апстриме привело к записи дефиса: `"time": -`. | Применить маппинг в `nginx.conf` (`map $upstream_response_time $clean_time`) с заменой `"-"` на `null`, либо заключить значение в кавычки. |
| **Неверное вычисление перцентилей при ретраях бэкенда** | В логах строковое значение таймингов содержит запятую: `"upstream_response_time": "1.000, 0.020"`. | Директива `proxy_next_upstream` перенаправила запрос на второй сервер; Nginx записал времена обоих попыток через запятую. | В скрипте VRL/Logstash разбивать строку функцией `split(..., ", ")` и извлекать последний элемент массива `[-1]`. |
| **Рост числа ошибок 499 (Client Closed Request)** | Запрос в ClickHouse: `$request_time` высокий, а `$upstream_response_time` равен `null` или мал. | Клиент разорвал соединение до того, как бэкенд успел сгенерировать ответ (агрессивный клиентский таймаут), либо бэкенд завис на блокировке СУБД. | Сравнить `$request_time` с клиентским RTT (`$tcpinfo_rtt`) и проверить задержки запросов на бэкенде. |
| **Переполнение диска `/var/log` во время аварии (Disk Flood)** | Команда `df -h /var/log` фиксирует 100% заполнение при росте ошибок 5xx. | Лавинообразное увеличение объема логов при аварии базы данных или DDoS-атаке. | Настроить условное логирование `if=$loggable`, вынести `/var/log` на отдельный LVM-том с опцией квотирования, включить ротацию по размеру (`maxsize 1G`). |
| **Потеря логов при отправке через Syslog UDP** | Несовпадение счетчика запросов веб-сервера со счетчиком в хранилище логов. `netstat -su \| grep "receive errors"`. | Переполнение буфера сокета UDP ядра Linux под всплеском трафика. | Увеличить параметры ядра `sysctl -w net.core.rmem_max=26214400`, перейти на UNIX Domain Socket или потоковую запись в локальный файл с буфером. |

---

## Рекомендации и Best Practices

### Оптимальные параметры буферизации для различных профилей нагрузки

| Профиль нагрузки | RPS | Рекомендуемый размер буфера | Интервал сброса (`flush`) | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **Умеренный (General Web)** | < 1 000 | `buffer=32k` | `flush=2s` | Баланс между оперативным отображением логов и защитой диска |
| **Высоконагруженный (High-load API)** | 1 000 – 20 000 | `buffer=128k` | `flush=1s` | Минимизация системных вызовов ядра, гарантированная задержка не более 1 с |
| **Экстремальный (AdTech / Real-time)** | > 50 000 | `buffer=256k` | `flush=5s` | Максимальная пропускная способность I/O, пакетный сброс |

### Политика безопасности и маскирования данных (Security & Privacy)

1.  **Санитизация чувствительных параметров (PII & Credentials):**
    Никогда не записывайте заголовки `Authorization`, `Proxy-Authorization`, `Cookie` и тело запроса в `access_log`. Для URL-адресов с конфиденциальными GET-параметрами (токены, ключи сессий) используйте замену через `map`:
    ```nginx
    map $args $clean_args {
        ~*(?i)(token|access_token|password|secret)=[^&]+  "REDACTED";
        default                                           $args;
    }
    ```
2.  **Изоляция дискового пространства:**
    Раздел `/var/log` обязан находиться на отдельном дисковом томе или логическом разделе (LVM), изолированном от корневого раздела `/`. Это предотвращает остановку операционной системы и системных служб при внезапном переполнении логов.
3.  **Корреляция между слоями (End-to-End Tracing):**
    Граничный прокси обязан генерировать сквозной идентификатор запроса (например, `$request_id`) и передавать его бэкендам через заголовок `X-Request-ID`, а также формировать стандартный заголовок W3C `traceparent` для интеграции с OpenTelemetry/Jaeger.
4.  **SLI/SLO на основе логов:**
    Используйте структурированные логи для вычисления SLO доступности и задержки:
    *   **Availability SLI:** $\frac{\text{count}(status < 500)}{\text{count}(все\ запросы)} \times 100\%$ (за исключением клиентских ошибок 4xx).
    *   **Latency SLI:** $\frac{\text{count}(request\_time \le 0.200)}{\text{count}(все\ запросы)} \times 100\%$ (доля запросов быстрее 200 мс).

---

## Дополнительная информация

### См. также

*   [Анализ access-логов Nginx (GoAccess и CLI)](../../Nginx/Operations/nginx_log_analysis.md) — консольный интерактивный анализ и генерация быстрых отчетов.
*   [Логирование в Angie](../../Angie/angie_logging.md) — нативный JSON в `error_log`, фильтрация ошибок по тегам и ограничение скорости записи.
*   [Обзор веб-производительности](./overview.md) — системные метрики производительности, TTFB и жизненный цикл запроса.
*   [Мониторинг кэширования в Nginx/Angie](../../Nginx/Performance/Caching/monitoring.md) — специализированное логирование статусов кэша (`$upstream_cache_status`).
*   [Circuit Breaker и деградация сервисов](./circuit_breaker_and_degradation.md) — использование метрик логов для активации защитных механизмов.
*   [Вектор (Vector) overview](../../../Vector/vector_overview.md) — архитектура высокопроизводительного агента доставки логов.
*   [Vector Remap Language (VRL)](../../../Vector/vrl_language.md) — синтаксис и функции трансформации структурированных логов.
*   [Архитектура ClickHouse](../../../Databases/ClickHouse/clickhouse-architecture.md) — движки таблиц `MergeTree`, сжатие и организация хранения.
*   [ClickHouse Performance](../../../Databases/ClickHouse/clickhouse-performance.md) — тонкая настройка производительности и индексации в ClickHouse.
*   [Структурированное логирование (системный уровень)](../../../Linux/SystemAdministration/Logging/structured_logging.md) — стандарты логирования приложений и общие форматы.

### Спецификации и стандарты

*   **RFC 9110 (HTTP Semantics)** — стандарт протокола HTTP, определение методов, кодов состояния и семантики заголовков.
*   **RFC 5424 (The Syslog Protocol)** — спецификация сетевого протокола Syslog.
*   **W3C Trace Context (Recommendation)** — стандарт распространения контекста распределенной трассировки (`traceparent`, `tracestate`).
