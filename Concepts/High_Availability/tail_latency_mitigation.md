# Управление задержками (Tail Latency Mitigation)

## Предварительные требования

Для полноценного понимания данного раздела предполагается знакомство с:
- Базовыми концепциями **[очередей и очередного теории](./scalability_laws.md)**: Закон Литтла, Формула Кингмана, утилизация
- Метриками **[высокой доступности](./ha_overview.md)**: RTO, RPO, MTTR, SLO/SLI
- Протоколами HTTP/1.1, HTTP/2, gRPC и их таймаут-механизмами
- Концепциями **[высокодоступных архитектур](./ha_clustering_and_load_balancing.md)**: Active-Active, балансировка нагрузки
- Инструментами мониторинга: Prometheus (гистограммы), Grafana, распределенная трассировка (Jaeger/Zipkin)
- Базовыми средствами диагностики Linux: `ss`, `curl`, `netstat`, `perf`

---

## Определения

**Tail Latency (Хвост задержек)** — время ответа для наихудших перцентилей запросов: 5% (p95), 1% (p99) или 0.1% (p99.9). В то время как медиана (p50) отражает типичное поведение системы, «хвосты» показывают опыт пользователей, столкнувшихся с аномальными задержками. Для современных высокодоступных (HA) систем именно p99 является основной метрикой стабильности, так как «хвосты» часто являются предвестниками каскадных сбоев и насыщения ресурсов.

### Проблема Fan-out (Умножение задержек)

В микросервисной архитектуре один пользовательский запрос часто инициирует десятки параллельных вызовов к внутренним компонентам. Общая задержка системы определяется самым медленным из этих вызовов.

**Математическая модель:**
Если запрос зависит от $n$ параллельных подзапросов, и вероятность того, что подзапрос будет медленным (выйдет за p99), равна $p$, то вероятность $P_{slow}$ того, что весь пользовательский запрос будет медленным, составляет:
$$P_{slow} = 1 - (1 - p)^n$$

*Пример:*
- При $p = 0.01$ (p99 задержка 1с) и $n = 100$ вызовов:
- $P_{slow} = 1 - (0.99)^{100} \approx 63.4\%$.
- **Вывод:** Даже если 99% внутренних запросов выполняются мгновенно, более половины пользователей увидят задержку в 1 секунду.

## Основные концепции

Проблема «хвостов» неразрывно связана с фундаментальными законами очередей:

1.  **Связь с законом Литтла:** Рост задержки при стабильном входящем RPS неизбежно ведет к росту количества одновременно обрабатываемых запросов (Concurrency). Это быстро истощает пулы потоков и соединения с БД. Подробнее: **[Закон Литтла](./scalability_laws.md)**.
2.  **Эффект Кингмана:** При приближении утилизации ресурсов ($U$) к 100%, время ожидания в очереди растет экспоненциально. Любой микро-всплеск задержки («хвост») на одном узле мгновенно «забивает» очередь, превращаясь в долговременный затор. Подробнее: **[Формула Кингмана](./scalability_laws.md)**.
3.  **Retry Storms (Штормы повторов):** Автоматические повторные попытки (Retries) клиентов при таймаутах создают избыточную нагрузку, которая еще сильнее замедляет систему, вызывая каскадный отказ.

Стратегии борьбы делятся на две категории:
- **Срезание хвоста (Reduction):** Снижение вероятности возникновения медленных ответов через архитектурные оптимизации.
- **Изоляция хвоста (Masking):** Маскировка задержек, чтобы один «больной» узел не мог дестабилизировать всю цепочку вызовов.

*Диагностика низкоуровневых причин задержек в ядре Linux (CFS Throttling, Lock Contention) описана в разделе **[Диагностика Tail Latency](../../Linux/Diagnostics/Performance/diagnosing_tail_latency.md)**.*

## Практические сценарии

### Сценарии уменьшения задержек (Reduction)

Цель — предотвратить возникновение «хвоста» или сократить его длительность на ранних этапах.

#### 1. Hedged Requests (Подстраховка)

**Принцип:** Если запрос не завершился за время p95, параллельно отправляется дубликат (Backup Request) на другую реплику. Используется первый успешный ответ.

**Практическая реализация (Go):**

```go
func hedgedRequest(ctx context.Context, replicas []string, timeout time.Duration) ([]byte, error) {
    ctx, cancel := context.WithCancel(ctx)
    defer cancel()

    resultCh := make(chan result, len(replicas))
    for _, addr := range replicas {
        go func(addr string) {
            data, err := doRequest(ctx, addr)
            resultCh <- result{data: data, err: err}
        }(addr)
    }

    // Первый ответ — принять, остальные отменить
    first := <-resultCh
    if first.err != nil {
        return nil, first.err
    }
    return first.data, nil
}
```

**Валидация:**
```bash
# Сравнение p99 с Hedged и без
# Без Hedged:
curl -s http://localhost:9090/metrics | grep 'http_request_duration_seconds{quantile="0.99"}'
# → 1200ms

# С Hedged (порог = p95 = 200ms):
curl -s http://localhost:9090/metrics | grep 'http_request_duration_seconds{quantile="0.99"}'
# → 250ms (снижение на ~80%)
```

**Ограничения:**
- Работает только для **идемпотентных** операций (чтение, GET-запросы). Для записи (POST/PUT) дублирование вызывает побочные эффекты.
- Нагрузка на бэкенд растет на ~5% (при типичном p99 = 1% трафика × 1 дубликат).
- Необходим точный мониторинг p95 в реальном времени (Adaptive Hedging).

#### 2. Adaptive Hedging (Адаптивная подстраховка)

**Принцип:** Порог для отправки дубликата вычисляется динамически на основе текущего p95 системы, а не фиксирован.

**Реализация (Prometheus + скрипт):**

```python
import time
import requests

def get_adaptive_threshold():
    """Получение текущего p95 из Prometheus для использования как порог Hedging"""
    prometheus_url = "http://localhost:9090/api/v1/query"
    query = 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))'
    resp = requests.get(prometheus_url, params={"query": query})
    p95 = float(resp.json()["data"]["result"][0]["value"][1])
    return p95 * 1.1  # +10% запас

# Динамический порог обновляется каждые 30 сек
THRESHOLD = get_adaptive_threshold()
```

**Эффект:** Система автоматически адаптируется к дневным всплескам нагрузки.

**Валидация:**
```bash
# Проверка, что порог Hedging обновляется динамически
# Симуляция пиковой нагрузки:
hey -z 30s -q 10 -c 50 http://localhost:8080/api/heavy

# В логах сервиса:
# → Hedged request sent (threshold=180ms, actual=210ms)
# → Hedged request sent (threshold=220ms, actual=350ms)  # порог вырос под нагрузкой

# Проверка метрик Prometheus
curl -s http://localhost:9090/api/v1/query?query=hedged_requests_total
# → hedged_requests_total{service="api", quantile="0.95"} 1523
```

#### 3. Request Coalescing (Объединение запросов)

**Принцип:** Если к системе пришло много запросов на один и тот же «горячий» ресурс, сервер делает один запрос к источнику, раздавая результат всем ожидающим.

**Реализация (Go с sync.Once):**

```go
type Coalescer struct {
    mu    sync.Mutex
    cache map[string]*singleflight.Group
}

func (c *Coalescer) Do(key string, fn func() (interface{}, error)) (interface{}, error) {
    c.mu.Lock()
    if c.cache == nil {
        c.cache = make(map[string]*singleflight.Group)
    }
    g, ok := c.cache[key]
    if !ok {
        g = &singleflight.Group{}
        c.cache[key] = g
    }
    c.mu.Unlock()

    return g.Do(key, fn) // singleflight гарантирует однократное выполнение
}
```

**Валидация:**
```bash
# Сравнение количества запросов к БД до и после Coalescing
# До: 10,000 запросов к одному и тому же пользователю при Cache Stampede
psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
# → 500 одновременных запросов

# После Coalescing:
psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
# → 1-5 одновременных запросов (остальные получают результат из кэша)
```

#### 4. Exponential Backoff + Jitter

**Принцип:** Ретраи с экспоненциальной задержкой и **случайным шумом (Jitter)** предотвращают синхронизацию клиентов.

**Реализация:**

```python
import random
import time

def retry_with_backoff(max_retries=5, base_delay=1.0, max_delay=30.0):
    for attempt in range(max_retries):
        delay = min(base_delay * (2 ** attempt), max_delay)
        # Full Jitter: случайный выбор от 0 до delay
        jittered_delay = random.uniform(0, delay)
        time.sleep(jittered_delay)
        try:
            return make_request()
        except RequestException:
            if attempt == max_retries - 1:
                raise
```

**Валидация:**
```bash
# Проверка распределения задержек между ретраями
# Без Jitter: все клиенты retry одновременно → Thundering Herd
# С Jitter: задержки распределены равномерно
for i in $(seq 1 100); do
  curl -s -w "%{time_total}\n" -o /dev/null http://localhost/retry-endpoint
done | sort -n | awk '{sum+=$1; a[NR]=$1} END {
  print "p50:", a[int(NR*0.5)];
  print "p95:", a[int(NR*0.95)];
  print "p99:", a[int(NR*0.99)];
}'
```

### Сценарии маскировки задержек (Masking)

Цель — изолировать задержки, чтобы они не вызывали каскадного падения всей инфраструктуры.

#### 1. Circuit Breaker (Предохранитель)

Автоматическое размыкание цепи запросов при превышении порога ошибок или таймаутов от зависимости.

**Состояния:**
- *Closed* (работает) → *Open* (запросы отклоняются мгновенно) → *Half-Open* (проверка восстановления)

**Реализация на HAProxy (TCP mode):**

```
# /etc/haproxy/haproxy.cfg
backend app_servers
    option httpchk GET /health
    http-check expect status 200

    # Circuit Breaker: 3 провала за 10 сек → размыкание на 30 сек
    default-server inter 3s fall 3 rise 2 slowstart 60s

    server app1 10.0.0.1:8080 check
    server app2 10.0.0.2:8080 check
    server app3 10.0.0.3:8080 check backup  # Backup-сервер при Open
```

**Реализация на NGINX (Health Check + Max Fails):**

```nginx
# /etc/nginx/conf.d/upstream.conf
upstream backend {
    zone backend 64k;
    least_conn;

    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.3:8080 backup;
}

server {
    location / {
        proxy_pass http://backend;
        proxy_connect_timeout 2s;    # Быстрый таймаут на подключение
        proxy_read_timeout 5s;       # Таймаут чтения ответа

        # Fallback при отказе всех бэкендов
        error_page 502 503 504 /fallback.html;
    }

    location /fallback.html {
        internal;
        return 200 '{"status":"degraded","message":"Service temporarily unavailable"}';
        add_header Content-Type application/json;
    }
}
```

**Валидация:**
```bash
# Имитация отказа бэкенда
sudo systemctl stop app@10.0.0.1

# Проверка, что HAProxy переключился на backup
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep app_servers
# → app1,DOWN,...
# → app3,UP,... (backup вступил в игру)

# Проверка fallback на NGINX
curl -s http://localhost/fallback.html
# → {"status":"degraded","message":"Service temporarily unavailable"}
```

#### 2. Deadline Propagation (Передача дедлайна)

**Принцип:** Первый сервис в цепочке (Edge Gateway) ставит дедлайн (например, 2000 мс). Каждый следующий сервис вычитает время своей обработки и передает остаток дальше.

**Реализация (gRPC — современный стандарт):**

```go
// Клиент: установка дедлайна
ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
defer cancel()

// Вызов downstream-сервиса с передачей дедлайна
resp, err := orderService.GetOrder(ctx, &pb.OrderRequest{Id: orderId})
// Если downstream не успеет — context.DeadlineExceeded
```

**Реализация (REST — через заголовки):**

```
# Клиент → Gateway
POST /api/orders HTTP/1.1
X-Request-Deadline: <T_base>  # T_deadline = now + 2с

# Gateway → Order Service (вычел 200мс на свою обработку)
POST /internal/orders HTTP/1.1
X-Request-Deadline: <T_base - 200мс>  # Остаток: 1.8 сек
```

**Валидация:**
```bash
# Проверка, что дедлайн передается через цепочку
# (на каждом сервисе логируем оставшееся время)
curl -v http://localhost/api/orders/123 \
  -H "X-Request-Deadline: $(date -u -d '+2 seconds' +%Y-%m-%dT%H:%M:%S.000Z)"

# В логах Gateway:
# → Received request, deadline remaining: 1980ms
# В логах Order Service:
# → Received request, deadline remaining: 1650ms (после network hop)
```

#### 3. Load Shedding (Сброс нагрузки)

**Принцип:** Принудительное отклонение «лишнего» трафика для удержания утилизации ресурсов в безопасных пределах (U < 0.8).

**Реализация (NGINX limit_req):**

```nginx
# /etc/nginx/conf.d/rate_limiting.conf
http {
    # Общий лимит: 1000 RPS, burst до 200, без задержки
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=1000r/s;

    server {
        location /api/ {
            limit_req zone=api_limit burst=200 nodelay;
            limit_req_status 429;  # Too Many Requests

            proxy_pass http://backend;
        }

        # Критические эндпоинты без ограничения
        location /api/payment/ {
            # Нет limit_req — платежи не сбрасываются
            proxy_pass http://payment_backend;
        }
    }
}
```

**Приоритезация (очередь приоритетов):**

```
# /etc/nginx/conf.d/upstream_priority.conf
# Tier 1: Критический (платежи, аутентификация) — без ограничений
# Tier 2: Основной (API, CRUD) — нормальные лимиты
# Tier 3: Аналитика, отчеты — жесткие лимиты, первые отклоняются
```

**Валидация:**
```bash
# Проверка rate limiting
for i in $(seq 1 500); do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost/api/search
done | sort | uniq -c
# → 200: 300 (прошли)
# → 429: 200 (отклонены, Retry-After: 1)

# Проверка текущей утилизации
curl -s http://localhost:9090/metrics | grep 'system_cpu_utilization'
# → 0.75 (в пределах нормы U < 0.8)
```

#### 4. Backpressure (Обратное давление)

**Принцип:** Система сообщает клиенту, что она перегружена, до того, как ресурсы будут полностью исчерпаны.

**Реализация (HTTP 429 + Retry-After):**

```nginx
# NGINX возвращает 429 с Retry-After
location /api/ {
    limit_req zone=api_limit burst=200 nodelay;
    limit_req_status 429;

    # Добавление Retry-After заголовка
    add_header Retry-After 5 always;
}
```

**Реализация (gRPC — через лимитер):**

```go
// Простой concurrency limiter
type ConcurrencyLimiter struct {
    sem chan struct{}
}

func NewConcurrencyLimiter(maxConcurrent int) *ConcurrencyLimiter {
    return &ConcurrencyLimiter{sem: make(chan struct{}, maxConcurrent)}
}

func (l *ConcurrencyLimiter) Allow() bool {
    select {
    case l.sem <- struct{}{}:
        return true
    default:
        return false  # → grpc.Code.ResourceExhausted
    }
}

func (l *ConcurrencyLimiter) Release() {
    <-l.sem
}
```

**Валидация:**
```bash
# Проверка количества 429 ответов
curl -s http://localhost:9090/metrics | grep 'http_responses_total{code="429"}'
# → 150 (отклоненных запросов за последнюю минуту)

# Проверка Retry-After заголовка
curl -sI http://localhost/api/heavy-endpoint | grep Retry-After
# → Retry-After: 5
```

#### 5. Паттерн «Good Enough» (Достаточно хорошо)

**Принцип:** При задержке в «тяжелом» сервисе система отдает упрощенный дефолтный ответ. Цель — сохранить работоспособность UI ценой временного снижения качества контента.

**Реализация (NGINX fallback):**

```nginx
# /etc/nginx/conf.d/fallback.conf
server {
    location /api/recommendations {
        proxy_pass http://recommendation_engine;
        proxy_connect_timeout 1s;  # Быстрый таймаут
        proxy_read_timeout 2s;

        # Fallback на кэшированный «хороший» ответ
        error_page 502 503 504 = @fallback_recommendations;
    }

    location @fallback_recommendations {
        # Отдаем статический «хороший» ответ из кэша
        proxy_pass http://cache_backend/static/top10_products.json;
        add_header X-Fallback "true";
    }
}
```

**Валидация:**
```bash
# Проверка, что fallback отдает «достаточно хороший» ответ
curl -s http://localhost/api/recommendations | python3 -m json.tool
# → {"products": [...], "source": "cache", "fallback": true}

# Проверка заголовка X-Fallback
curl -sI http://localhost/api/recommendations | grep X-Fallback
# → X-Fallback: true
```

## Tuning Linux kernel и systemd для снижения Tail Latency

### Сетевые параметры ядра (sysctl)

Для минимизации задержек на уровне сетевого стека Linux:

```bash
# /etc/sysctl.d/99-tail-latency.conf

# Уменьшение TIME_WAIT таймаута для быстрого освобождения портов
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1

# Увеличение локальных портов для исходящих соединений
net.ipv4.ip_local_port_range = 1024 65535

# Оптимизация буферов socket (подбирайте под RAM)
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864

# Отключение TCP timestamp (если не используется для PAWS)
net.ipv4.tcp_timestamps = 0

# Включение TCP Fast Open (если поддерживается)
net.ipv4.tcp_fastopen = 3

# Отключение ICMP redirect (для серверов)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
```

**Валидация:**
```bash
# Проверка применения параметров
sudo sysctl --system
# → Applying /etc/sysctl.d/99-tail-latency.conf

# Проверка текущих значений
sysctl net.ipv4.tcp_fin_timeout net.ipv4.tcp_tw_reuse net.ipv4.ip_local_port_range

# Проверка TIME_WAIT сокетов
ss -s
# → 4320 TIME-WAIT (сервер: 4320, входящие: 0, выходящие: 4320)
```

### Tuning cgroup v2 (для контейнеров и systemd)

```bash
# Проверка версии cgroup
cat /proc/filesystems | grep cgroup2
mount | grep cgroup2

# Настройка memory pressure для систем сжатия
# /etc/systemd/system.conf
[Manager]
DefaultMemoryPressureThresholdSec=30s

# Для конкретного сервиса (например, order-service)
# /etc/systemd/system/order-service.service.d/latency.conf
[Service]
# Ограничение по памяти (в байтах)
MemoryMax=2G
MemoryHigh=1.5G

# При достижении MemoryHigh — throttling в 20% периода
CPUQuota=200%
IOWeight=50
```

**Валидация:**
```bash
# Проверка memory pressure
systemctl show order-service -p MemoryPressure
# → MemoryPressure=0

# Мониторинг throttling
systemctl status order-service
# → CPU throttle: 0.00s

# Анализ через bpftrace (если установлен)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_nanosleep { @[comm] = count(); }'
```

### systemd-сервисы: параметры задержки

```ini
# /etc/systemd/system/order-service.service.d/latency.conf
[Service]
# Привязка к NUMA-узлу 0 (если сервер имеет 2+ сокета)
NUMAPolicy=preferred
NUMANode=0

# Разрешение на приоритетный I/O
IOSchedulingClass=realtime
IOSchedulingPriority=1

# Ограничение числа открытых файлов (file descriptors)
LimitNOFILE=65536

# Увеличенный лимит locked memory (для JIT/HugePages)
LimitMEMLOCK=infinity

# Запуск после network.target
After=network-online.target
Wants=network-online.target
```

**Валидация:**
```bash
# Проверка параметров сервиса
systemctl show order-service -p NUMAPolicy,NUMANode,IOSchedulingClass,LimitNOFILE

# Проверка открытых файлов
ls /proc/$(pgrep order-service)/fd | wc -l
# → 1240 (в пределах лимита)

# Проверка NUMA-политики
numastat -p $(pgrep order-service)
```

### Инструменты диагностики (bpftrace, perf, off-CPU)

```bash
# Off-CPU анализ: сколько времени процесс ждет готовности CPU
sudo perf sched timehist -p $(pgrep order-service)

# Отложенные системные вызовы (blocked on I/O)
sudo perf sched record -p $(pgrep order-service) -a -- sleep 10
sudo perf sched latency

# Анализ задержек на уровне ядра (usdt)
sudo bpftrace -e 'uretprobe:/usr/lib/x86_64-linux-gnu/libc.so.6:clock_gettime { @start[tid] = nsecs; } ustack:gettimeofday { @latency[tid] = hist((nsecs - @start[tid]) / 1000); } interval:s:5 { print(@latency); clear(@latency); }'

# DNS-резолвинг (проверка задержек в /etc/resolv.conf)
dig +stats example.com @8.8.8.8
# → ;; Query time: 2 msec
```

## Дополнительная информация

Эффективная борьба с «хвостами» невозможна без следующих инструментов:
- **Распределенная трассировка:** позволяет визуализировать цепочку вызовов и точно определить, на каком именно сетевом хопе, БД-запросе или блокировке «залип» конкретный p99 запрос. См. **[Jaeger и трассировка](../Observability_and_Monitoring/traces_deep_dive.md)**.
- **Тюнинг сетевого стека:** включение **[TCP Fast Open](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** и оптимизация `tcp_max_syn_backlog` для исключения задержек на этапе установления соединений.
- **Идемпотентность API:** критическое условие для безопасного применения Hedged Requests и автоматических ретраев без риска дублирования транзакций.
- **Мониторинг перцентилей:** вместо средних значений (avg) необходимо мониторить p95/p99/p99.9 через Prometheus Histograms или OpenTelemetry. Ключевые метрики: `http_request_duration_seconds{quantile="0.99"}`, `grpc_server_handling_seconds{quantile="0.99"}`.

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **p99 резко вырос, p50 в норме** | Фоновая задача (GC, индексация) блокирует один поток; «хвост» на одной реплике | `curl -s http://localhost:9090/metrics \| grep 'http_request_duration_seconds{quantile="0.99"}'` — точный p99; `ss -tnp \| grep ESTABLISHED` — проверка количества соединений | Hedged Requests; выделение фоновых задач в отдельный пул потоков |
| **p50 и p99 одновременно выросли** | Общая перегрузка; нехватка CPU/RAM; проблема с БД | `top -bn1 \| head -5` — загрузка CPU; `free -m` — использование RAM; `pg_stat_activity` / `mysql -e "SHOW PROCESSLIST"` — активные запросы | Load Shedding; вертикальное масштабирование; оптимизация запросов к БД |
| **Периодические всплески p99** | Кэш-промахи (Cold Cache); Cron-задачи; пакетная обработка | `curl -s http://localhost:9090/metrics \| grep 'cache_hits_total'` — hit-rate кэша; `crontab -l` — проверка расписания | Request Coalescing; prefetching; разреживание Cron-задач |
| **Каскадный рост задержек** | Retry Storm: клиенты массово повторяют запросы | `ss -tnp \| grep -c ':443'` — количество соединений; `curl -s http://localhost:9090/metrics \| grep 'http_responses_total{code="429"}'` — количество 429 | Circuit Breaker; Exponential Backoff + Jitter;.setRequestTimeout |
| **Задержки только на одном узле кластера** | Numa-aware scheduling; «горячий» поток; проблема с конкретным диском | `numactl --hardware` — проверка NUMA; `iostat -x 1 5` — I/O по дискам; `perf top -p <pid>` — горячие функции | Привязка процесса к NUMA-узлу (`numactl --cpunodebind=0`); балансировка I/O |
| **High Latency при Low Throughput** | Локальные блокировки (mutex); DNS-резолвинг; TLS handshake | `strace -p <pid> -c` — системные вызовы; `dig +stats example.com` — время DNS; `openssl s_client -connect host:443` — время TLS | Кеширование DNS (nscd/systemd-resolved); TLS Session Resumption; уменьшение contention на блокировках |

## Лучшие практики (Best Practices)

1. **Мониторить перцентили, а не средние:** Метрики `avg` скрывают проблемы — p99/p99.9 показывают реальный пользовательский опыт. Настройте报警 alerting на p99 > 2x от p50.
2. **Hedged Requests только для чтения:** Использование Hedged для записей (POST/PUT) приводит к дублированию транзакций. Для записей используйте идемпотентные ключи.
3. **Circuit Breaker обязателен для внешних зависимостей:** Каждый вызов к внешнему сервису (БД, API, микросервис) должен иметь Circuit Breaker с fallback-стратегией.
4. **Exponential Backoff + Jitter — стандарт для ретраев:** Без Jitter все клиенты retry одновременно после сбоя (Thundering Herd). Jitter обязательное условие.
5. **Load Shedding до исчерпания ресурсов:** Утилизация CPU > 80% — сигнал для включения Load Shedding. Не ждите, пока система начнет тормозить.
6. **Тестировать таймауты в staging:** Перед деплоем проверяйте поведение при задержках 200мс, 500мс, 2с на каждом сервисе. Используйте `tc netem delay` для имитации задержек.
7. **Регулярно калибровать пороги Hedged/Backoff:** Порог Hedged должен обновляться динамически (Adaptive Hedging). Фиксированные пороги устаревают при изменении профиля нагрузки.
8. **Документировать fallback-стратегии:** Для каждого критичного эндпоинта определите «Good Enough» ответ. При каких условиях он отдается? Как часто обновляется кэш?

## Граничные случаи и ограничения (Edge Cases)

- **Hedged Requests + неидемпотентные операции:** Дублирование POST-запроса без идемпотентного ключа приведет к созданию двух транзакций. Всегда проверяйте идемпотентность перед включением Hedged.
- **Circuit Breaker при медленных зависимостях:** Если БД отвечает медленно, но без ошибок (например, 3 сек), Circuit Breaker не сработает (он срабатывает только при ошибках или таймаутах). Добавьте `proxy_read_timeout` в NGINX или `context.WithTimeout` в gRPC.
- **Load Shedding и приоритеты:** При неправильной настройке приоритетов Load Shedding может отклонять критические запросы. Всегда тестируйте сценарий, когда 100% трафика — это критические эндпоинты.
- **Backpressure и клиенты без Retry-After:** Старые клиенты могут игнорировать заголовок Retry-After и продолжать слать запросы, создавая Thundering Herd. Решение: добавить экспоненциальную задержку на стороне клиента.
- **Request Coalescing и мутабельные данные:** Coalescing для данных, которые часто меняются, может вердать устаревший результат. Ограничивайте время жизни Coalesced-запроса (например, TTL = 1 сек).
- **Асинхронные системы и Deadlines:** Deadline Propagation не работает с асинхронными очередями (Kafka, RabbitMQ). Для очередей используйте TTL сообщений и Dead Letter Queues.
- **Дрейф времени между узлами:** При使用的 времени в Deadline Propagation НЕПОСРЕДСТВЕННО зависит от синхронизации часов (NTP). Дрейф > 100мс приводит к тому, что Deadline у следующего сервиса может быть уже исчерпан.
- **Паузы GC (Garbage Collection):** Для языков с сборщиком мусора (Go, Java, Node.js) паузы GC до 100мс могут сделать утилизацию 70% смертельной для p99. Решение: настройте GC параметры (`GOMAXPROCS`, `-XX:MaxGCPauseMillis`, `--max-old-space-size`), мониторьте через `jstat`/`go tool trace`.
- **CPU frequency scaling:** `intel_pstate` или `acpi-cpufreq` могут снижать частоту ядра при низкой нагрузке, вызывая всплески p99 при sudden spikes. Решение: установите `performance` governor или используйте `tuned` с профилем `latency-performance`.
- **Hypervisor Steal Time:** В виртуализированных средах (KVM, VMware) `%steal` CPU > 10% указывает на contention на хосте. Мониторьте через `top` (столбец `st`) или `mpstat -P ALL`.
- **cgroup throttling в контейнерах:** Если `cpu.cfs_quota_us` < `cpu.cfs_period_us` * cores, контейнер будет throttled. Проверяйте через `docker stats` или `kubectl top pods`.
- **Transparent Huge Pages (THP):** Фоновая компакция THP вызывает latency spikes до 100мс. Отключите: `echo never > /sys/kernel/mm/transparent_hugepage/enabled`.
- **IRQ affinity и сетевые прерывания:** Если все прерывания NIC обрабатывает одно ядро, возникает очереди. Решение: `irqbalance` или ручная привязка через `/proc/irq/*/smp_affinity`.
- **Дисковый I/O scheduler:** `mq-deadline` или `bfq` снижают latency для SSD/NVMe по сравнению с `cfq`. Проверяйте: `cat /sys/block/sda/queue/scheduler`.
- **[Законы масштабируемости](./scalability_laws.md)** — теоретические основы пропускной способности и очередей.
- **[Диагностика Tail Latency](../../Linux/Diagnostics/Performance/diagnosing_tail_latency.md)** — низкоуровневые причины задержек в ядре Linux.
- **[SRE и бюджеты ошибок](../sre_concepts_main.md)** — как SLO диктуют выбор стратегии борьбы с задержками.

---

## Связанные концепции

- **[Паттерны микросервисной архитектуры](../../Concepts/microservice_patterns.md)** — отказоустойчивость и масштабируемость.
- **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)** — паттерн сброса нагрузки при исчерпании пропускной способности.
- **[Reliability Patterns](../../CI-CD/Core_Concepts/reliability_patterns.md)** — обзор паттернов надежности: Circuit Breaker, Retry Budget, Timeout.
- **[Диагностика Tail Latency](../../Linux/Diagnostics/Performance/diagnosing_tail_latency.md)** — поиск причин на уровне ОС (CFS Throttling, Lock Contention).
- **[TCP Tuning](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — оптимизация сетевого стека для низких задержек.

---

## Контрольный список проектирования Tail Latency Mitigation

- [ ] Настроен мониторинг p95/p99/p99.9 (Prometheus Histograms или OpenTelemetry)
- [ ] Circuit Breaker настроен для каждой внешней зависимости
- [ ] Hedged Requests включены для идемпотентных операций (чтение)
- [ ] Exponential Backoff + Jitter реализованы на клиенте
- [ ] Load Shedding настроен (порог U < 0.8)
- [ ] Backpressure реализован (HTTP 429 + Retry-After)
- [ ] Fallback-ответы (Good Enough) определены для критичных эндпоинтов
- [ ] Deadline Propagation реализована в цепочке вызовов
- [ ] Timeout-ы протестированы в staging (200мс, 500мс, 2с)
- [ ] Идемпотентность API проверена для всех операций, использующих Hedged/Retry
- [ ] sysctl параметры для сети настроены (tcp_fin_timeout, tcp_tw_reuse, rmem/wmem)
- [ ] cgroup v2 лимиты проверены (MemoryHigh, CPUQuota, IOWeight)
- [ ] systemd-сервисы имеют NUMAPolicy, IOSchedulingClass, LimitNOFILE
- [ ] THP отключены, CPU governor установлен в performance/latency-performance
- [ ] NTP синхронизация настроена (chrony/ntpd) для Deadline Propagation
- [ ] GC паузы профилированы и настроены (GOMAXPROCS, MaxGCPauseMillis)
- [ ] Проверено отсутствие hypervisor steal time > 10% (`top`, `mpstat`)
