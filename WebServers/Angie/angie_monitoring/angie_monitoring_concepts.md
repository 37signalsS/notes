# Мониторинг Angie — основные концепции

**Актуально для:** Angie 1.12.x

## Определения

**Мониторинг Angie** — комплексный процесс непрерывного сбора, агрегации и анализа метрик внутреннего состояния веб-сервера и проксируемого трафика. В отличие от Nginx OSS, Angie предоставляет нативный REST API и встроенный OpenMetrics/Prometheus-экспортер, что устраняет необходимость развертывания сторонних вспомогательных процессов (sidecar-экспортеров) на хосте.

**Зона статуса (status_zone)** — именованный сегмент в разделяемой памяти, выделяемый для сбора и атомарного обновления счетчиков сетевого трафика, запросов и кодов ответа. Директива `status_zone` задается статическим идентификатором на уровне виртуальных серверов (`server`), путей (`location`) или L4-прокси (`stream { server { ... } }`).

**Shared Memory (Разделяемая память)** — область оперативной памяти Linux, разделяемая между всеми рабочими процессами (`worker processes`) сервера через системные механизмы IPC (`mmap`/`shmget`). Обеспечивает согласованность и непрерывность счетчиков метрик без межпроцессных блокировок сокетов.

**Аллокатор слэбов (Slab Allocator, ngx_slab_stat)** — внутренний менеджер памяти Angie, управляющий выделением мелких структур фиксированного размера внутри зон разделяемой памяти. Разбивает страницы памяти (по 4 КБ) на слоты от 8 до 2048 байт. Состояние аллокатора доступно для мониторинга через `/status/slabs/`.

**ngx_http_api_module** — встроенный модуль Angie, предоставляющий REST-интерфейс для чтения метрик состояния сервера, активной конфигурации и управления апстримами в режиме реального времени. Данные передаются в формате JSON. Включен в стандартные пакеты по умолчанию (отключается при компиляции флагом `--without-http_api_module`).

**ngx_http_prometheus_module** — встроенный модуль нативного экспорта метрик в формате OpenMetrics / Prometheus Text format. Формирует текстовый поток метрик напрямую из разделяемой памяти по правилам шаблона `prometheus_all.conf`.

**Пользовательские метрики (модуль metric / metric_complex_zone)** — механизм создания произвольных счетчиков и гистограмм (начиная с Angie 1.6.0 и 1.11.0) в разделяемой памяти на основе внутренних переменных сервера, позволяющий отслеживать задержки и бизнес-показатели без парсинга логов.

**Stub Status (ngx_http_stub_status_module)** — минималистичный модуль, унаследованный от Nginx. Предоставляет базовую текстовую сводку по активным соединениям и обработанным запросам. Не требует выделения зон в разделяемой памяти и применяется для легковесных liveness-проверок.

**Поколение конфигурации (Generation)** — целочисленный монотонно возрастающий счетчик версий конфигурации master-процесса. Инкрементируется при каждом успешном сигнале перезагрузки конфигурации (`reload` / `SIGHUP`). Позволяет выявлять зависшие worker-процессы старых ревизий.

**Зомби-воркер (Zombie Worker Process)** — рабочий процесс предыдущего поколения конфигурации, который не смог завершиться после `reload` из-за незакрытых длительных соединений (WebSockets, HTTP keepalive, streaming).

**In-flight запросы (Concurrency)** — запросы клиентов, принятые рабочим процессом и находящиеся в стадии обработки или ожидания ответа от бэкенда в текущий момент времени. В логах не отображаются до момента завершения транзакции.

**Зона кэша (Cache Zone / keys_zone)** — сегмент разделяемой памяти, задаваемый директивой `proxy_cache_path ... keys_zone=<name>:<size>`. Хранит хэш-таблицу ключей кэшированных файлов и метаданные, собирая статистику попаданий (`HIT`, `MISS`, `EXPIRED`, `STALE`, `UPDATING`, `BYPASS`).

**Keepalive Connection Pool** — пул постоянных TCP-соединений к серверам группы `upstream`, сохраняемых открытыми между запросами клиентов. Метрики пула отражают число активных (`active`) и простаивающих (`idle`) соединений.

**SRE Golden Signals (Четыре золотых сигнала)** — базовый набор метрик работоспособности сервиса по методологии Google SRE: задержка (Latency), трафик (Traffic), ошибки (Errors) и насыщенность (Saturation).

**Upstream Probe (Angie Pro)** — нативный механизм активных проверок жизнеспособности бэкендов в коммерческой версии Angie Pro (директива `upstream_probe`), поддерживающий HTTP-проверки по телу и статусу ответа с гибкими интервалами и порогами срабатывания.

---

## Базовые концепции и архитектура

### 1. Архитектурная модель сбора метрик

Внутренняя система наблюдаемости Angie построена на изоляции процессов и разделяемой памяти ядра Linux. В многопроцессной модели Master-Worker каждый worker-процесс обслуживает неблокирующие сетевые события через `epoll`.

```
                         [ Входящие запросы клиентов ]
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                 Worker Processes (N ядер CPU)               │
        │   Worker 1             Worker 2             Worker N        │
        └───────┬────────────────────┬────────────────────┬───────────┘
                │                    │                    │
                │ Атомарные операции │ (без блокировок)   │
                ▼                    ▼                    ▼
        ┌─────────────────────────────────────────────────────────────┐
        │            Shared Memory (Разделяемая память)               │
        │ ┌────────────────────────┐  ┌─────────────────────────────┐ │
        │ │ status_zone / zone     │  │ ngx_slab_stat (Слоты/Стран.)│ │
        │ └────────────────────────┘  └─────────────────────────────┘ │
        │ ┌────────────────────────┐  ┌─────────────────────────────┐ │
        │ │ metric_zone / complex  │  │ proxy_cache keys_zone       │ │
        │ └────────────────────────┘  └─────────────────────────────┘ │
        └──────────────────────────────┬──────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
      ┌───────────────────────────┐         ┌───────────────────────────┐
      │    ngx_http_api_module    │         │ ngx_http_prometheus_module│
      │   (REST API: JSON)        │         │ (OpenMetrics: Text)       │
      │   GET /status/            │         │ GET /status/prometheus    │
      └─────────────┬─────────────┘         └─────────────┬─────────────┘
                    │                                     │
                    ▼                                     ▼
       [ CLI / jq / Console Light ]              [ Prometheus Server ]
```

1. **Сбор:** В процессе обработки сетевых событий воркеры выполняют атомарные операции инкремента 64-битных счетчиков в разделяемой памяти без взаимных блокировок (lockless atomics).
2. **Хранение:** Данные структурированы по зонам (`status_zone`, `upstream zone`, `metric_zone`, `keys_zone`).
3. **Чтение:** Модули `api` и `prometheus` читают данные напрямую из разделяемой памяти, преобразуя их в форматы JSON или OpenMetrics на лету без влияния на производительность основного цикла обработки трафика.

---

### 2. Сравнительный анализ инструментов наблюдения

Для правильного выбора инструмента в инфраструктуре DevOps и системного администрирования необходимо сопоставлять характеристики источников данных:

| Критерий | REST API (`ngx_http_api_module`) | Prometheus (`ngx_http_prometheus_module`) | `stub_status` | Access/Error Logs |
|:---|:---|:---|:---|:---|
| **Формат вывода** | Иерархический JSON | OpenMetrics / Plain text | Неструктурированный текст | Сырой текст / JSON / Syslog |
| **Потребление памяти** | Требует `status_zone` в shm | Требует `status_zone` в shm | Не требует разделяемой памяти | Зависит от буферов записи на диск |
| **In-flight запросы** | Да (в реальном времени) | Да (текущий срез) | Да (`Reading`, `Writing`) | Нет (запись строго после завершения) |
| **Детализация** | Полная (VHost, Location, Upstream, Slabs, SSL, Cache) | Полная (по меткам и именам метрик) | Минимальная (только общие соединения/запросы) | Максимальная (детали каждого отдельного HTTP-запроса) |
| **Влияние на I/O диска** | 0% (работа в ОЗУ) | 0% (работа в ОЗУ) | 0% (работа в ОЗУ) | Высокое (дисковые операции записи и ротации) |
| **Хранение истории** | Нет (только текущие счетчики) | Нет (хранится во внешнем TSDB) | Нет | Да (хранится в файлах/хранилищах логов) |
| **Основной сценарий** | Локальная диагностика, Console Light, скрипты автоматизации | Общесистемный мониторинг, дашборды Grafana, алертинг | Health check балансировщиков L4, старые агенты | Аудит безопасности, поиск редких краевых аномалий, трассировка |

---

### 3. Организация разделяемой памяти и Slab Allocator

Разделяемая память Angie организуется страницами фиксированного размера (по умолчанию 4 КБ в Linux x86_64). Для выделения мелких объектов (структуры пиров апстрима, счетчики зон) используется собственный аллокатор слэбов (Slab Allocator).

- **Страницы (Pages):** Память зоны разбивается на страницы. Страница может быть свободной (`free`), занятой целиком (`used`) или разбитой на слоты фиксированного размера (`slots`).
- **Слоты (Slots):** Размеры слотов кратны степеням двойки (8, 16, 32, 64, 128, 256, 512, 1024, 2048 байт).
- **Отказы аллокации (`fails`):** Если для нового объекта нужного размера нет свободного слота и невозможно выделить новую страницу, счетчик отказов аллокации инкрементируется, а в лог ошибок записывается сообщение:
  `[crit] ... ngx_slab_alloc() failed: no memory in status_zone "<name>"`

```
Зона разделяемой памяти (например, 1 МБ = 256 страниц по 4 КБ):
┌──────────┬──────────┬──────────┬──────────┬──────────────────────────┐
│ Страница │ Страница │ Страница │ Страница │ ... Свободные страницы   │
│ 1 (Слоты │ 2 (Слоты │ 3        │ 4        │                          │
│ по 64 Б) │ по 128 Б)│ (Целиком)│ (Целиком)│                          │
└──────────┴──────────┴──────────┴──────────┴──────────────────────────┘
```

#### Расчет объема разделяемой памяти

1. **Для зон виртуальных серверов и локаций (`status_zone`):**
   - Базовая структура зоны занимает около 1–2 КБ.
   - Минимальный размер зоны — `64k`. Зоны в `64k` достаточно для отслеживания отдельного виртуального хоста или локации с запасом.
2. **Для групп апстримов (`upstream zone`):**
   - Каждый сервер (peer) в апстриме занимает около 512–1024 байт (хранение IP, порта, весов, состояний доступности, счетчиков ответов, пула соединений).
   - Формула:
     $$\text{Размер зоны} \ge (\text{Число серверов} \times 1.5\,\text{КБ}) + 64\,\text{КБ (служебные структуры)}$$
   - Для пула из 50 серверов: `128k`.
   - Для динамических кластеров на сотни серверов: `1m` – `4m`.
3. **Для зон кэширования (`proxy_cache_path keys_zone`):**
   - 1 МБ памяти `keys_zone` вмещает метаданные приблизительно 8 000 кэшированных ключей.
   - Зона `keys_zone=cache_zone:10m` рассчитана примерно на 80 000 объектов в кэше.

---

### 4. Архитектура процессов и жизненный цикл поколений (Generation)

При обслуживании веб-сервера на уровне ОС Linux критически важно понимать поведение процессов при перезагрузке конфигурации (`systemctl reload angie` или `kill -HUP <master_pid>`):

```
1. Старт сервера:
   Master (PID: 1000, Gen: 1) ──┬── Worker (PID: 1001, Gen: 1)
                                └── Worker (PID: 1002, Gen: 1)

2. Выполнение `angie -s reload`:
   Master (PID: 1000, Gen: 2) ──┬── Worker (PID: 1003, Gen: 2) [Принимают новый трафик]
                                ├── Worker (PID: 1004, Gen: 2) [Принимают новый трафик]
                                │
                                ├── Worker (PID: 1001, Gen: 1, shutting down) [Дообслуживают старые TCP-сессии]
                                └── Worker (PID: 1002, Gen: 1, shutting down) [Дообслуживают старые TCP-сессии]
```

- **Инкремент поколения:** При успешном чтении новой конфигурации Master увеличивает значение `generation` на 1.
- **Старые воркеры:** Переходят в состояние graceful shutdown — закрывают слушающие сокеты, прекращают принимать новые соединения и завершаются по окончании обслуживания текущих клиентов.
- **Проблема «Зомби-воркеров»:** Если клиент держит открытое HTTP/1.1 keepalive-соединение или постоянный WebSocket-поток, воркер старого поколения не может завершиться самостоятельно.
- **Предотвращение:** Обязательная директива `worker_shutdown_timeout` в глобальном контексте конфигурации принудительно обрывает зависшие соединения по истечении тайм-аута и освобождает ресурсы ОС.

---

### 5. Методологии SRE и системного администрирования

Интеграция метрик Angie в практику SRE и системного администрирования базируется на признанных стандартах индустрии.

#### 5.1. Четыре золотых сигнала (Google SRE Golden Signals)

Подробнее о методологии см. в [Методологии мониторинга](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

1. **Задержка (Latency):**
   - Время обработки запроса клиенту (`$request_time`).
   - Время ответа апстрима (`$upstream_response_time`, `health.response_time`).
   - Контролируется через процентили (p50, p95, p99) с помощью модуля `metric_zone` или логов.
2. **Трафик (Traffic):**
   - Интенсивность запросов (RPS) по виртуальным серверам (`requests.total`).
   - Сетевой объем входящего и исходящего трафика (`data.received`, `data.sent`).
3. **Ошибки (Errors):**
   - Ошибки уровня веб-сервера (`responses.5xx`).
   - Ошибки доступности бэкендов (`health.fails`, `upstream.fails`).
   - Ошибки исчерпания соединений и лимитов (`limit_conn.rejected`, `limit_req.rejected`).
4. **Насыщенность (Saturation):**
   - Коэффициент занятости пула соединений (`connections.active` по отношению к `worker_connections * worker_processes`).
   - Использование памяти зон статуса и кэша (`used / size` в `/status/slabs/`).
   - Очередь сокетов на уровне ядра Linux (`ListenOverflows` / `ListenDrops`).

#### 5.2. Методология USE (Utilization, Saturation, Errors) для хоста Angie

Применяется системными администраторами для диагностики узла под нагрузкой:

- **Utilization (Утилизация):** Загрузка CPU рабочими процессами Angie, доля используемой памяти в зонах shm, объем открытых файловых дескрипторов относительно `worker_rlimit_nofile`.
- **Saturation (Насыщенность):** Длина очереди слушающего сокета TCP (backlog), число клиентов в статусе ожидания обработки (`Waiting`), отказы выделения слэбов (`fails > 0` в `/status/slabs/`).
- **Errors (Ошибки):** Сбои аллокации памяти, аномальные завершения процессов воркеров (segfaults/OOM Killer), сетевые сбросы соединений (`dropped`).

#### 5.3. Методология RED (Rate, Errors, Duration) для сервисов за Angie

Применяется инженерами сопровождения для каждого upstream-сервиса:

- **Rate:** `rate(angie_http_requests_total[1m])`
- **Errors:** `rate(angie_http_responses_total{status=~"5.."}[1m])`
- **Duration:** Распределение гистограммы времени ответа апстрима.

---

### 6. SLI, SLO и расчет Error Budget

В SRE-подходе статические пороговые алерты (например, «если 5xx > 10, то отправить письмо») заменяются контролем скорости расходования бюджета ошибок (Error Budget Burn Rate).

- **SLI (Service Level Indicator):** Доля успешных запросов к общему числу запросов:
  $$\text{SLI} = \frac{\sum \text{Requests}_{2xx,3xx,4xx}}{\sum \text{Requests}_{\text{total}}}$$
  *(Примечание: клиентские ошибки 4xx, кроме 429, обычно не включаются в бюджет ошибок сервиса).*
- **SLO (Service Level Objective):** Целевой показатель надежности за плавающий период (например, 99.9% за 30 дней).
- **Error Budget:** Допустимая доля сбоев ($100\% - 99.9\% = 0.1\%$).
- **Multi-Window Multi-Burn-Rate:** Метод раннего обнаружения инцидентов. Если сервис сжигает 2% бюджета ошибок за 1 час (Burn Rate = 14.4), дежурный инженер оповещается немедленно. Если сжигается 5% за 6 часов (Burn Rate = 6), формируется предупреждение без ночных вызовов.

---

## Практические сценарии

### Сценарий 1: Базовая изоляция эндпоинта мониторинга

Создание выделенного внутреннего интерфейса управления и мониторинга на локальном loopback-адресе, изолированного от публичного трафика.

```nginx
# /etc/angie/conf.d/management.conf

server {
    listen 127.0.0.1:8888;
    server_name localhost;

    # Запрет логирования регулярных проверок мониторинга для снижения I/O
    access_log off;
    error_log /var/log/angie/management_error.log warn;

    # Основной REST API Angie
    location /status/ {
        api;
        allow 127.0.0.1;
        deny all;
    }

    # Нативный экспорт метрик в формате OpenMetrics / Prometheus
    location = /status/prometheus {
        prometheus all;
        allow 127.0.0.1;
        deny all;
    }

    # Минималистичный liveness-эндпоинт
    location = /healthz {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Проверка синтаксиса и применения:**
```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

sudo systemctl reload angie
```

**Верификация работоспособности:**
```bash
curl -sf http://127.0.0.1:8888/status/angie/ | jq '{version, generation}'
# → {
# →   "version": "1.12.3",
# →   "generation": 1
# → }
```

---

### Сценарий 2: Глобальный мониторинг и детализация по виртуальным хостам и путям

Сбор дифференцированной статистики для разделения пользовательского API и отдачи статики.

```nginx
# /etc/angie/http.d/production_site.conf

server {
    listen 10.0.0.10:80;
    listen 10.0.0.10:443 ssl;
    server_name app.internal.net;

    # Активация счетчиков всего виртуального сервера
    status_zone vhost_app_internal;

    # Критичный API — отдельная зона для отслеживания ошибок и задержек
    location /api/v2/ {
        status_zone loc_api_v2;
        proxy_pass http://backend_api_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Отдача медиа-контента — мониторинг нагрузки на диск
    location /media/ {
        status_zone loc_media_storage;
        root /var/data/storage;
        expires 30d;
    }
}
```

**Проверка метрик зоны через API:**
```bash
curl -s http://127.0.0.1:8888/status/http/server_zones/vhost_app_internal/ | jq .requests
# → {
# →   "total": 128450,
# →   "discarded": 0
# → }

curl -s http://127.0.0.1:8888/status/http/location_zones/loc_api_v2/ | jq .responses.codes
# → {
# →   "200": 124100,
# →   "400": 312,
# →   "500": 4
# → }
```

---

### Сценарий 3: Мониторинг балансировки L7-апстримов и пула keepalive

Для получения телеметрии по серверам кластера блок `upstream` обязательно должен содержать директиву `zone`.

```nginx
# /etc/angie/http.d/upstreams.conf

upstream backend_api_cluster {
    # Выделение разделяемой памяти: 256 КБ на зону
    zone backend_api_cluster 256k;

    # Серверы кластера
    server 10.0.1.11:8080 weight=3 max_fails=2 fail_timeout=10s;
    server 10.0.1.12:8080 weight=3 max_fails=2 fail_timeout=10s;
    server 10.0.1.13:8080 backup;

    # Пул постоянных TCP-соединений к бэкендам
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}
```

**Проверка метрик апстрима:**
```bash
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | jq '.peers[] | {server, state, active: .selected.current, fails: .health.fails, keepalive}'
# → {
# →   "server": "10.0.1.11:8080",
# →   "state": "up",
# →   "active": 4,
# →   "fails": 0,
# →   "keepalive": 12
# → }
# → {
# →   "server": "10.0.1.12:8080",
# →   "state": "up",
# →   "active": 2,
# →   "fails": 0,
# →   "keepalive": 10
# → }
# → {
# →   "server": "10.0.1.13:8080",
# →   "state": "backup",
# →   "active": 0,
# →   "fails": 0,
# →   "keepalive": 0
# → }
```

---

### Сценарий 4: Мониторинг проксирования L4 TCP/UDP (Stream)

Сбор телеметрии на транспортном уровне при проксировании не-HTTP протоколов (например, базы данных PostgreSQL или очередей сообщений).

```nginx
# /etc/angie/stream.d/postgres_proxy.conf

stream {
    upstream pgsql_cluster {
        zone pgsql_cluster 128k;
        server 10.0.2.21:5432 max_conns=100;
        server 10.0.2.22:5432 max_conns=100;
    }

    server {
        listen 10.0.0.10:5432;
        status_zone stream_pgsql_front;
        proxy_pass pgsql_cluster;
        proxy_timeout 10m;
        proxy_connect_timeout 2s;
    }
}
```

**Верификация L4-метрик:**
```bash
curl -s http://127.0.0.1:8888/status/stream/server_zones/stream_pgsql_front/ | jq '{connections: .connections, data: .data}'
# → {
# →   "connections": 420,
# →   "data": {
# →     "received": 104857600,
# →     "sent": 524288000
# →   }
# → }
```

---

### Сценарий 5: Легковесный liveness-чекер через stub_status

Для сетевых балансировщиков (например, Keepalived или HAProxy) `stub_status` оптимален, так как отдает ответ минимального размера и не нагружает JSON-парсер.

```nginx
# /etc/angie/conf.d/healthcheck.conf

server {
    listen 127.0.0.1:8081;

    location /healthz {
        stub_status;
        access_log off;
    }
}
```

**Проверка через curl:**
```bash
curl -s http://127.0.0.1:8081/healthz
# → Active connections: 2
# → server accepts handled requests
# →  142050 142050 380412
# → Reading: 0 Writing: 1 Waiting: 1
```

---

### Сценарий 6: Мониторинг и контроль зон дискового кэша

Отслеживание утилизации разделяемой памяти метаданных кэша и коэффициента попадания (`Cache Hit Ratio`).

```nginx
# /etc/angie/http.d/caching.conf

proxy_cache_path /var/cache/angie/assets
    levels=1:2
    keys_zone=assets_cache:20m
    max_size=10g
    inactive=24h
    use_temp_path=off;

server {
    listen 80;
    server_name static.internal.net;

    location / {
        proxy_pass http://backend_storage;
        proxy_cache assets_cache;
        proxy_cache_valid 200 302 12h;
        proxy_cache_valid 404 1m;
        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

**Чтение телеметрии кэша:**
```bash
curl -s http://127.0.0.1:8888/status/http/caches/assets_cache/ | jq .
# → {
# →   "size": 20971520,
# →   "used": 4194304,
# →   "cold": 0,
# →   "hit": 84200,
# →   "miss": 1210,
# →   "expired": 350,
# →   "stale": 12,
# →   "updating": 0,
# →   "bypass": 5
# → }
```

**Расчет Hit Ratio в Bash:**
```bash
curl -s http://127.0.0.1:8888/status/http/caches/assets_cache/ | jq '
  (.hit / (.hit + .miss + .expired + .stale + .bypass) * 100) as $ratio |
  {cache_hit_ratio_percent: $ratio, memory_usage_percent: (.used / .size * 100)}'
# → {
# →   "cache_hit_ratio_percent": 98.16,
# →   "memory_usage_percent": 20.0
# → }
```

---

### Сценарий 7: Sysadmin Health Check скрипт для локальных систем мониторинга

Практический скрипт проверки работоспособности для Zabbix Agent, Nagios или локального cron-демона без внешних зависимостей.

```bash
#!/usr/bin/env bash
# /usr/local/bin/check_angie_health.sh
# Коды возврата: 0 - OK, 1 - WARNING, 2 - CRITICAL

set -euo pipefail

STATUS_URL="http://127.0.0.1:8888/status"
SLABS_URL="${STATUS_URL}/slabs/"
ANGIE_URL="${STATUS_URL}/angie/"

# 1. Проверка доступности API
if ! RESPONSE=$(curl -sf --max-time 3 "${ANGIE_URL}"); then
    echo "CRITICAL: Angie API недоступен на ${ANGIE_URL}"
    exit 2
fi

VERSION=$(echo "${RESPONSE}" | jq -r '.version // empty')
GENERATION=$(echo "${RESPONSE}" | jq -r '.generation // empty')

if [[ -z "${VERSION}" || -z "${GENERATION}" ]]; then
    echo "CRITICAL: Получен некорректный ответ от API Angie"
    exit 2
fi

# 2. Проверка отказов аллокации в Slab-аллокаторе памяти
SLAB_FAILS=$(curl -sf --max-time 3 "${SLABS_URL}" | jq '[.[].slots[]?.fails // 0] | add // 0')

if [[ "${SLAB_FAILS}" -gt 0 ]]; then
    echo "WARNING: Зафиксированы отказы в slab-аллокаторе памяти (fails: ${SLAB_FAILS}). Требуется увеличить зоны!"
    exit 1
fi

echo "OK: Angie v${VERSION} (gen: ${GENERATION}), memory slabs healthy (fails: 0)"
exit 0
```

**Настройка прав и тестовый запуск:**
```bash
sudo chmod 755 /usr/local/bin/check_angie_health.sh
/usr/local/bin/check_angie_health.sh
# → OK: Angie v1.12.3 (gen: 1), memory slabs healthy (fails: 0)
```

---

### Сценарий 8: SRE: Настройка Prometheus Recording Rules и Multi-Burn-Rate алертинга

Конфигурация правил Prometheus для bare-metal инфраструктуры (SLO 99.9%, допустимый бюджет ошибок 0.1%).

```yaml
# /etc/prometheus/rules/angie_slo_rules.yml

groups:
  - name: angie_slo_recording_rules
    interval: 30s
    rules:
      # Базовый SLI: доля HTTP-ошибок уровня 5xx за 5 минут
      - record: job:angie_http_requests:rate5m
        expr: sum(rate(angie_http_requests_total[5m]))

      - record: job:angie_http_errors:rate5m
        expr: sum(rate(angie_http_responses_total{status=~"5.."}[5m]))

      - record: job:angie_http_error_ratio:5m
        expr: |
          job:angie_http_errors:rate5m
          /
          job:angie_http_requests:rate5m

      # Скорость сжигания бюджета (Burn Rate) за 1 час и 6 часов
      # При SLO 99.9% допустимая частота ошибок: 0.001
      - record: job:angie_error_budget_burn_rate:1h
        expr: |
          (
            sum(rate(angie_http_responses_total{status=~"5.."}[1h]))
            /
            sum(rate(angie_http_requests_total[1h]))
          ) / 0.001

      - record: job:angie_error_budget_burn_rate:6h
        expr: |
          (
            sum(rate(angie_http_responses_total{status=~"5.."}[6h]))
            /
            sum(rate(angie_http_requests_total[6h]))
          ) / 0.001

  - name: angie_slo_alerting_rules
    rules:
      # Критический алерт: 2% бюджета сжигается за 1 час (Burn Rate > 14.4)
      - alert: AngieHighErrorBudgetBurnRate1h
        expr: job:angie_error_budget_burn_rate:1h > 14.4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Критическая скорость сжигания бюджета ошибок Angie (хост {{ $labels.instance }})"
          description: "Текущий Burn Rate равен {{ $value | printf \"%.2f\" }}x (более 2% месячного бюджета будет потеряно за час)."

      # Предупреждающий алерт: 5% бюджета сжигается за 6 часов (Burn Rate > 6)
      - alert: AngieSlowErrorBudgetBurnRate6h
        expr: job:angie_error_budget_burn_rate:6h > 6
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Постепенная деградация SLO Angie (хост {{ $labels.instance }})"
          description: "Текущий 6-часовой Burn Rate равен {{ $value | printf \"%.2f\" }}x."
```

**Проверка синтаксиса правил через `promtool`:**
```bash
promtool check rules /etc/prometheus/rules/angie_slo_rules.yml
# → Checking /etc/prometheus/rules/angie_slo_rules.yml
# →   SUCCESS: 6 rules found
```

---

### Сценарий 9: Детекция и безопасное завершение зомби-воркеров

Скрипт системного администратора для выявления зависших процессов старого поколения после reload конфигурации.

```bash
#!/usr/bin/env bash
# /usr/local/bin/detect_zombie_workers.sh
# Выявление процессов воркеров Angie с поколением ниже актуального

set -euo pipefail

STATUS_URL="http://127.0.0.1:8888/status/angie/"

# Получение актуального поколения master-процесса
MASTER_GEN=$(curl -sf "${STATUS_URL}" | jq -r '.generation')

echo "Текущее поколение мастер-процесса: ${MASTER_GEN}"

# Поиск всех воркеров в системе
ZOMBIES_FOUND=0
while read -r PID CMD; do
    echo "Анализ процесса PID: ${PID} (${CMD})"
    # Если процесс содержит метку 'is shutting down' или generation не совпадает
    if ps -p "${PID}" -o args= | grep -q "shutting down"; then
        echo "ВНИМАНИЕ: Процесс ${PID} завис в состоянии graceful shutdown!"
        ZOMBIES_FOUND=$((ZOMBIES_FOUND + 1))
    fi
done < <(pgrep -f "angie: worker process" || true)

if [[ "${ZOMBIES_FOUND}" -eq 0 ]]; then
    echo "Все рабочие процессы соответствуют актуальному поколению."
else
    echo "Обнаружено ${ZOMBIES_FOUND} зависших процессов. Проверьте 'worker_shutdown_timeout'!"
fi
```

**Тестовый запуск:**
```bash
/usr/local/bin/detect_zombie_workers.sh
# → Текущее поколение мастер-процесса: 3
# → Все рабочие процессы соответствуют актуальному поколению.
```

---

## Операции и команды

Практические рецепты для терминала инженера при инспекции узла:

| Цель операции | Команда CLI | Ожидаемый результат |
|:---|:---|:---|
| **Проверка доступности API** | `curl -sf http://127.0.0.1:8888/status/angie/ \| jq .` | JSON с полями `version`, `generation`, `uptime` |
| **Проверка поколения мастера** | `curl -s http://127.0.0.1:8888/status/angie/ \| jq -r .generation` | Целочисленный номер (например, `# → 2`) |
| **Сверка воркеров в ОС** | `ps -eo pid,ppid,args \| grep "angie: worker"` | Список процессов с родительским PID мастера |
| **Список server_zones** | `curl -s http://127.0.0.1:8888/status/http/server_zones/ \| jq 'keys'` | JSON-массив имен зон (`["vhost_app", ...]`) |
| **Состояние апстримов** | `curl -s http://127.0.0.1:8888/status/http/upstreams/ \| jq 'keys'` | Список зарегистрированных групп балансировки |
| **Проверка сбоев в slabs** | `curl -s http://127.0.0.1:8888/status/slabs/ \| jq 'to_entries[] \| {zone: .key, fails: [.value.slots[]?.fails // 0] \| add}'` | Список зон с числом отказов аллокации |
| **Проверка пула keepalive** | `curl -s http://127.0.0.1:8888/status/http/upstreams/<name>/ \| jq .keepalive` | Число активных постоянных соединений |
| **Проверка сокетов ядра** | `ss -lntp '( sport = :80 or sport = :443 )'` | Состояние `Send-Q` и `Recv-Q` слушающих сокетов |
| **Дропы очереди сокетов** | `netstat -s \| grep -E 'listen queue\|overflowed'` | Нулевые или минимальные значения счетчиков ядра |

### Примеры разбора JSON с фильтрацией `jq`

**Выгрузка серверов со статусом ошибки в апстриме:**
```bash
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_api_cluster/ | \
  jq '.peers[] | select(.state != "up" and .state != "backup") | {server, state, fails: .health.fails}'
# → (пустой вывод, если все серверы доступны)
```

**Мониторинг соединений в реальном времени:**
```bash
curl -s http://127.0.0.1:8888/status/connections/ | jq .
# → {
# →   "accepted": 412589,
# →   "dropped": 0,
# →   "active": 18,
# →   "idle": 5
# → }
```

---

## Устранение неполадок

### Диагностическая матрица типичных инцидентов

| Симптом / Ошибка | Первопричина | Команда диагностики | Способ решения |
|:---|:---|:---|:---|
| `[crit] ... ngx_slab_alloc() failed: no memory in status_zone` | Переполнение разделяемой памяти зоны из-за нехватки страниц или фрагментации слотов | `curl -s http://127.0.0.1:8888/status/slabs/<zone>/ \| jq .` | Увеличить размер зоны в директиве (`zone <name> 1m;` вместо `64k;`) и перезагрузить конфигурацию |
| Воркеры старого поколения продолжают висеть часами после reload | Длительные соединения (WebSocket, SSE, keepalive) удерживают воркер в памяти | `ps -eo pid,cmd \| grep "angie: worker process.*shutting down"` | Добавить в `angie.conf` директиву `worker_shutdown_timeout 30s;` |
| `/status/http/upstreams/` возвращает `{}` или пустой список серверов | В блоке `upstream` отсутствует директива `zone` | `grep -rn "upstream" /etc/angie/` | Добавить `zone <name> 128k;` внутрь каждого блока `upstream` |
| Ошибка `unknown directive "api"` при тестировании `angie -t` | Angie скомпилирован без модуля `ngx_http_api_module` | `angie -V 2>&1 \| grep -o -- '--without-http_api_module'` | Установить официальный бинарный пакет Angie или пересобрать без флага `--without-http_api_module` |
| Высокий latency и скачки CPU при обращении к `/status/` | Запрос корневого эндпоинта `/status/` форматирует огромный JSON на тысячах зон | `top -b -n 1 \| grep angie` | Использовать параметр `?pretty=off` или опрашивать только конкретную подветку (например, `/status/http/upstreams/`) |
| Всплеск 502/504 Bad Gateway при живых бэкендах | Переполнение очереди `backlog` слушающего сокета на стороне ОС | `ss -lnt '( sport = :80 )'` и `netstat -s \| grep -i listen` | Увеличить `listen 80 backlog=4096;` в Angie и `sysctl -w net.core.somaxconn=4096` в Linux |
| Деградация пула keepalive к апстримам (`keepalive: 0`) | Запросы уходят по протоколу HTTP/1.0 с заголовком `Connection: close` | Проверить блок `location` в конфигурации | Указать `proxy_http_version 1.1;` и `proxy_set_header Connection "";` в `location` |

---

## Лучшие практики

### 1. Архитектура и расчет памяти
- **Статические имена зон:** Директива `status_zone` не поддерживает динамические переменные (например, `$host`). Имя должно быть статической константой, иначе конфигурация не пройдет валидацию `angie -t`.
- **Запас памяти для апстримов:** Всегда выделяйте в блоках `upstream` не менее `128k` разделяемой памяти. Для динамических сред с частым обновлением узлов выделяйте `1m`–`2m`.
- **Контроль фрагментации:** Настройте периодический мониторинг счетчика `fails` в `/status/slabs/`. Рост `fails` выше 0 свидетельствует о скором падении аллокатора.

### 2. Безопасность и сетевая изоляция
- **Изоляция интерфейса управления:** Никогда не публикуйте порт мониторинга в Интернет. Привязывайте `listen` строго к `127.0.0.1` или изолированному служебному интерфейсу (Management VLAN/VPN).
- **Сетевые ACL:** Всегда дублируйте защиту директивами `allow 127.0.0.1; allow <monitoring_ip>; deny all;`.
- **Ограничение прав:** В стандартной открытой версии Angie модуль API работает только в режиме чтения. В Angie Pro при включении модификации конфигурации директивой `api /config/;` выносите эндпоинт модификации на отдельный защищенный сокет с взаимной аутентификацией TLS.

### 3. Эксплуатация воркеров и High Availability
- **Обязательный тайм-аут остановки:** Всегда объявляйте `worker_shutdown_timeout 30s;` (или `60s` при наличии длительных соединений) на верхнем уровне `angie.conf`. Это гарантирует отсутствие зомби-процессов после обновления пакетов или reload.
- **Предварительная валидация:** Любые действия по перезагрузке конфигурации должны предваряться командой `angie -t`.
- **Мониторинг поколения:** Включите счетчик поколения (`/status/angie/generation`) в систему алертинга. Если номер поколения в API изменился, а количество процессов воркеров превышает `worker_processes * 2` дольше 1 минуты — формируйте предупреждение.

### 4. SRE-подход и управление алертами
- **Комбинация с метриками ядра Linux:** Метрики уровня приложения (Angie) обязательно должны коррелировать с системными метриками хоста (`node_exporter`): CPU utilization воркеров, Context Switches, TCP socket drops.
- **Избегайте шумных пороговых алертов:** Не настраивайте оповещения на одиночные 5xx-ошибки. Используйте multi-window multi-burn-rate алертинг на основе Prometheus Recording Rules.
- **Разделение метрик и логов:** Высокочастотные числовые показатели агрегируйте в памяти через `status_zone` и экспортируйте через Prometheus, а детальные события с телами и заголовками направляйте в структурированный JSON access-log с буферизацией (`access_log ... buffer=64k flush=5s;`).

---

## Дополнительная информация

### Связанные разделы документации базы знаний

- **[Работа с API мониторинга](./angie_monitoring_api.md)** — полное описание дерева эндпоинтов, параметров фильтрации и структуры JSON.
- **[Интерфейс Console Light](./angie_monitoring_console.md)** — установка, настройка и развертывание встроенного веб-дашборда.
- **[Нативный экспорт в Prometheus](./angie_monitoring_prometheus.md)** — интеграция с Prometheus, правила `prometheus_all.conf` и метки OpenMetrics.
- **[Пользовательские метрики и гистограммы](./angie_monitoring_custom_metrics.md)** — настройка модуля `ngx_http_metric_module` и сбор кастомных таймингов.
- **[Возможности мониторинга в Angie Pro](./angie_monitoring_pro.md)** — активные проверки `upstream_probe`, динамическое управление пирами и разделяемые зоны кластера.
- **[Логирование в Angie](../angie_logging.md)** — форматы `access_log`, ротация логов без потерь через USR1 и запись в syslog.
- **[Graceful Reload и перезапуск воркеров](../angie-graceful-reload.md)** — архитектура сигналов UNIX, замена бинарного файла на лету и управление поколениями процессов.

### Методологические стандарты SRE

- **[Методологии мониторинга (USE, RED, Golden Signals)](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — фундаментальные принципы выбора метрик, расчета Error Budget и архитектуры Observability.

---

**См. также:**
- [Настройка Console Light и API](./angie_monitoring_console.md)
- [Работа с конфигурацией через API](./angie_monitoring_api.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
- [Пользовательские метрики](./angie_monitoring_custom_metrics.md)
