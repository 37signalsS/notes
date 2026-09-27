# Надежность и высокая доступность экспортеров Prometheus

## Определения

**Graceful degradation** — паттерн, при котором экспортер продолжает работать и возвращать частичные данные при недоступности целевой системы, вместо полного отказа (crash или метрика `up == 0`).

**Circuit breaker** — паттерн защиты экспортера от каскадных сбоев: при превышении порога ошибок опроса целевой системы экспортер прекращает попытки на определенное время (OPEN state), затем постепенно возобновляет (HALF-OPEN → CLOSED).

**High Availability (HA) экспортера** — конфигурация, при которой отказ одного экземпляра экспортера не приводит к потере метрик. Реализуется через несколько реплик за балансировщиком или шардирование.

**Metamonitoring** — мониторинг самого экспортера: его доступности, времени отклика, потребления ресурсов и ошибок при опросе целевых систем.

**См. также:** [Создание собственных экспортеров](./custom_exporters.md), [Тестирование экспортеров](./exporter_testing.md), [Blackbox Exporter HA](../blackbox/blackbox_exporter_scaling_and_ha.md).

## Основные концепции

### Graceful degradation при недоступности целевой системы

Когда целевая система (БД, API, Redis) недоступна, экспортер может вести себя по-разному. Выбор стратегии зависит от критичности метрик и допустимого времени отсутствия данных.

| Стратегия | Поведение | Когда использовать | Риск |
|:---|:---|:---|:---|
| **up = 0** | Метрика `up` принимает 0, метрики целевой системы не возвращаются | Стандартный подход для простых экспортеров | Prometheus хранит "фантомные" ряды 5 минут |
| **Кэш + stale** | Возвращается кэшированное значение с пометкой `stale` | Высокая критичность метрик, 필요на непрерывность | Риск показать устаревшие данные |
| **Partial data** | Возвращаются метрики, доступные без целевой системы (metametrics) + `up=0` | Сложные экспортеры с внутренним состоянием | Увеличивает кодовую базу |
| **Fallback source** | Опрос альтернативной системы при недоступности основной | Кластерные БД с репликами | Увеличивает зависимость от инфраструктуры |

**Реализация graceful degradation на Go:**

```go
type ResilientCollector struct {
    client        *ExternalSystemClient
    cache         *MetricCache
    fallback      *FallbackClient
    circuitBreaker *CircuitBreaker
}

func (c *ResilientCollector) Collect(ch chan<- prometheus.Metric) {
    // 1. Проверяем circuit breaker
    if c.circuitBreaker.IsOpen() {
        c.collectFromCacheOrFallback(ch)
        return
    }

    // 2. Пытаемся получить данные от основной системы
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    data, err := c.client.Query(ctx)
    if err != nil {
        c.circuitBreaker.RecordFailure()

        // 3. Fallback: пробуем альтернативный источник
        if c.fallback != nil {
            data, err = c.fallback.Query(ctx)
            if err == nil {
                c.collectMetrics(ch, data, "fallback")
                return
            }
        }

        // 4. Используем кэш
        c.collectFromCacheOrFallback(ch)
        return
    }

    // 5. Успех: обновляем кэш и сбрасываем circuit breaker
    c.circuitBreaker.RecordSuccess()
    c.cache.Set(data, 30*time.Second)
    c.collectMetrics(ch, data, "live")
}

func (c *ResilientCollector) collectFromCacheOrFallback(ch chan<- prometheus.Metric) {
    if data, ok := c.cache.Get(); ok {
        c.collectMetrics(ch, data, "cache")
        return
    }
    // Кэш пуст — возвращаем только up=0
    ch <- prometheus.MustNewConstMetric(
        c.upDesc, prometheus.GaugeValue, 0,
    )
}
```

### Circuit breaker

Circuit breaker предотвращает перегрузку экспортера и целевой системы при持續ных сбоях.

**Состояния:**

```
CLOSED (норма) ──[порог ошибок]──> OPEN (блокировка)
     ^                                    │
     │                              [таймаут]
     │                                    v
     └────[успех в HALF-OPEN]──── HALF-OPEN (тест)
```

**Реализация:**

```go
type CircuitBreaker struct {
    mu               sync.Mutex
    state            string // CLOSED, OPEN, HALF_OPEN
    failureCount     int
    successCount     int
    failureThreshold int
    successThreshold int
    timeout          time.Duration
    lastFailureTime  time.Time
}

func NewCircuitBreaker(failThreshold, successThreshold int, timeout time.Duration) *CircuitBreaker {
    return &CircuitBreaker{
        state:            "CLOSED",
        failureThreshold: failThreshold,
        successThreshold: successThreshold,
        timeout:          timeout,
    }
}

func (cb *CircuitBreaker) Allow() bool {
    cb.mu.Lock()
    defer cb.mu.Unlock()

    switch cb.state {
    case "CLOSED":
        return true
    case "OPEN":
        if time.Since(cb.lastFailureTime) > cb.timeout {
            cb.state = "HALF_OPEN"
            cb.successCount = 0
            return true
        }
        return false
    case "HALF_OPEN":
        return true
    }
    return false
}

func (cb *CircuitBreaker) RecordSuccess() {
    cb.mu.Lock()
    defer cb.mu.Unlock()

    cb.failureCount = 0
    if cb.state == "HALF_OPEN" {
        cb.successCount++
        if cb.successCount >= cb.successThreshold {
            cb.state = "CLOSED"
        }
    }
}

func (cb *CircuitBreaker) RecordFailure() {
    cb.mu.Lock()
    defer cb.mu.Unlock()

    cb.failureCount++
    cb.lastFailureTime = time.Now()

    if cb.failureCount >= cb.failureThreshold {
        cb.state = "OPEN"
    }
}
```

**Рекомендуемые параметры:**

| Параметр | Значение | Обоснование |
|:---|:---|:---|
| `failureThreshold` | 3–5 | Не блокировать при единичных сбоях |
| `successThreshold` | 2–3 | Убедиться в восстановлении перед полным возобновлением |
| `timeout` | 30–60s | Дать целевой системе время на восстановление |

### Retry logic

При опросе целевых систем с нестабильной доступностью важна правильная политика повторных попыток.

**Exponential backoff с jitter:**

```go
func RetryWithBackoff(ctx context.Context, maxRetries int, baseDelay time.Duration, fn func() error) error {
    var lastErr error

    for i := 0; i < maxRetries; i++ {
        if err := fn(); err != nil {
            lastErr = err

            // Exponential backoff: base * 2^i
            delay := baseDelay * time.Duration(1<<uint(i))

            // Добавляем jitter: +/- 25%
            jitter := time.Duration(rand.Int63n(int64(delay) / 2))
            delay = delay - delay/4 + jitter

            select {
            case <-ctx.Done():
                return ctx.Err()
            case <-time.After(delay):
                continue
            }
        }
        return nil
    }
    return fmt.Errorf("max retries (%d) exceeded: %w", maxRetries, lastErr)
}

// Использование
err := RetryWithBackoff(ctx, 3, 1*time.Second, func() error {
    _, err := db.QueryContext(ctx, "SELECT 1")
    return err
})
```

**Антипаттерн — Retry Storm:**
При массовом перезапуске экспортеров все одновременно начинают retry, создавая пиковую нагрузку. Решение — добавить jitter и ограничить `maxConcurrent`.

### High Availability экспортеров

Существует три основные модели HA для экспортеров:

| Модель | Описание | Потеря данных при отказе |
|:---|:---|:---|
| **Реплики + LB** | Несколько инстансов за балансировщиком, Prometheus скрейпит Service | Нет |
| **Шардирование** | Каждый Prometheus скрейпит свой subset экспортеров | Потеря метрик shard'а |
| **Географическое размещение** | Экспортеры в разных DC проверяют локальные цели | Потеря метрик в одном DC |

```
Реплики + LB:                    Шардирование:
                    ┌─── Exp 1   Prometheus 1 ──> Shard 1 (A-M)
Prometheus ──LB─────┼─── Exp 2   Prometheus 2 ──> Shard 2 (N-Z)
                    └─── Exp 3
```

> **Подробнее:** Детали реализации моделей HA, K8s манифесты с podAntiAffinity, probe distribution, DDoS-защита: [Blackbox Exporter — HA и масштабирование](../blackbox/blackbox_exporter_scaling_and_ha.md).

### Metamonitoring экспортера

Качественный экспортер должен экспортировать метрики о собственной работе. Это позволяет отделить проблемы с целевой системой от проблем с самим экспортером.

**Обязательные метрики экспортера:**

| Метрика | Тип | Описание | Алерт |
|:---|:---|:---|:---|
| `exporter_up` | Gauge | Доступность целевой системы (1/0) | `exporter_up == 0 for 5m` |
| `exporter_scrape_duration_seconds` | Gauge | Время опроса целевой системы | `> scrape_timeout * 0.8` |
| `exporter_scrapes_total` | Counter | Количество успешных скрапингов | - |
| `exporter_scrape_errors_total` | Counter | Количество ошибок при опросе | `rate() > 0 for 15m` |
| `exporter_target_scrape_timeout_seconds_total` | Counter | Количество превышений таймаута | `> 0 for 5m` |
| `exporter_build_info` | Gauge | Версия экспортера (значение всегда 1) | - |
| `exporter_last_scrape_timestamp_seconds` | Gauge | Время последнего успешного скрапинга | `time() - value > 120` |

**Реализация метрик экспортера:**

```go
type ExporterSelfMetrics struct {
    scrapeDuration   prometheus.Gauge
    scrapesTotal     prometheus.Counter
    scrapeErrors     prometheus.Counter
    lastScrape       prometheus.Gauge
}

func NewExporterSelfMetrics() *ExporterSelfMetrics {
    return &ExporterSelfMetrics{
        scrapeDuration: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "exporter_scrape_duration_seconds",
            Help: "Duration of target scrape in seconds",
        }),
        scrapesTotal: promauto.NewCounter(prometheus.CounterOpts{
            Name: "exporter_scrapes_total",
            Help: "Total number of scrapes",
        }),
        scrapeErrors: promauto.NewCounter(prometheus.CounterOpts{
            Name: "exporter_scrape_errors_total",
            Help: "Total number of scrape errors",
        }),
        lastScrape: promauto.NewGauge(prometheus.GaugeOpts{
            Name: "exporter_last_scrape_timestamp_seconds",
            Help: "Unix timestamp of last successful scrape",
        }),
    }
}

func (m *ExporterSelfMetrics) RecordScrape(duration time.Duration, err error) {
    m.scrapeDuration.Set(duration.Seconds())
    m.scrapesTotal.Inc()
    m.lastScrape.SetToCurrentTime()
    if err != nil {
        m.scrapeErrors.Inc()
    }
}
```

**Алерты для metamonitoring:**

```yaml
groups:
  - name: exporter_self_monitoring
    rules:
      - alert: ExporterTargetDown
        expr: exporter_up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Цель экспортера {{ $labels.job }} недоступна"
          description: "Цель {{ $labels.instance }} не отвечает более 5 минут"

      - alert: ExporterScrapeSlow
        expr: exporter_scrape_duration_seconds > 10
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Медленный скрапинг {{ $labels.job }}"
          description: "Скрапинг занимает {{ $value }}s (порог: 10s)"

      - alert: ExporterHighErrorRate
        expr: rate(exporter_scrape_errors_total[5m]) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий процент ошибок экспортера {{ $labels.job }}"
          description: "{{ $value | humanizePercentage }} скрапингов завершаются ошибкой"

      - alert: ExporterStaleData
        expr: time() - exporter_last_scrape_timestamp_seconds > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Экспортер {{ $labels.job }} не обновлял данные"
          description: "Последний скрапинг был {{ $value }} секунд назад"
```

### Обновление и откат экспортеров

**Rolling update в Kubernetes:**

```bash
# Обновление образа
kubectl set image deployment/blackbox-exporter \
  -n monitoring \
  blackbox-exporter=prom/blackbox-exporter:v0.26.0

# Мониторинг rollout
kubectl rollout status deployment/blackbox-exporter -n monitoring --timeout=5m

# Проверка метрик после обновления
kubectl port-forward -n monitoring svc/blackbox-exporter 9115:9115 &
curl -s http://localhost:9115/metrics | grep '^exporter_build_info'
```

**Проверка совместимости метрик между версиями:**

```bash
# Сравнение метрик до и после обновления
curl -s http://localhost:9101/metrics_before | awk '{print $1}' | sort > /tmp/metrics_before.txt
curl -s http://localhost:9101/metrics_after | awk '{print $1}' | sort > /tmp/metrics_after.txt

# Проверка на удаленные метрики (breaking change)
diff /tmp/metrics_before.txt /tmp/metrics_after.txt
# Если есть удаленные метрики — это breaking change для дашбордов и алертов
```

**Blue-green деплой экспортера:**

```yaml
# Blue (текущая версия)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blackbox-exporter-blue
  labels:
    version: blue
spec:
  replicas: 2
  selector:
    matchLabels:
      app: blackbox-exporter
      version: blue
  template:
    metadata:
      labels:
        app: blackbox-exporter
        version: blue

---
# Green (новая версия)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blackbox-exporter-green
  labels:
    version: green
spec:
  replicas: 2
  selector:
    matchLabels:
      app: blackbox-exporter
      version: green
  template:
    metadata:
      labels:
        app: blackbox-exporter
        version: green

---
# Service переключается на новую версию
apiVersion: v1
kind: Service
metadata:
  name: blackbox-exporter
spec:
  selector:
    app: blackbox-exporter
    version: green  # переключение с blue на green
  ports:
    - port: 9115
```

## Практические сценарии

### Сценарий 1: Экспортер с circuit breaker и graceful degradation

**Ситуация:** Экспортер опрашивает PostgreSQL, который периодически становится недоступен при failover.

```go
func (c *PgExporter) Collect(ch chan<- prometheus.Metric) {
    start := time.Now()

    if !c.breaker.Allow() {
        // Circuit breaker OPEN — возвращаем кэш или up=0
        c.metrics.RecordScrape(time.Since(start), fmt.Errorf("circuit breaker open"))
        if data, ok := c.cache.Get(); ok {
            c.emitCachedMetrics(ch, data)
        } else {
            ch <- prometheus.MustNewConstMetric(c.upDesc, prometheus.GaugeValue, 0)
        }
        return
    }

    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    stats, err := c.pgClient.GetStats(ctx)
    if err != nil {
        c.breaker.RecordFailure()
        c.metrics.RecordScrape(time.Since(start), err)

        if data, ok := c.cache.Get(); ok {
            c.emitCachedMetrics(ch, data)
        } else {
            ch <- prometheus.MustNewConstMetric(c.upDesc, prometheus.GaugeValue, 0)
        }
        return
    }

    c.breaker.RecordSuccess()
    c.cache.Set(stats, 30*time.Second)
    c.metrics.RecordScrape(time.Since(start), nil)
    c.emitMetrics(ch, stats)
}
```

### Сценарий 2: Мониторинг доступности самого экспортера

**Ситуация:** Нужно знать, работает ли экспортер, даже если целевая система недоступна.

```yaml
groups:
  - name: exporter_availability
    rules:
      # Экспортер не скрапится
      - alert: ExporterAbsent
        expr: absent(up{job="myapp-exporter"})
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Экспортер {{ $labels.job }} отсутствует в targets"

      # Экспортер работает, но цель недоступна
      - alert: ExporterTargetUnreachable
        expr: up{job="myapp-exporter"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Цель экспортера {{ $labels.instance }} недоступна"

      # Экспортер работает, но метрики не обновлялись
      - alert: ExporterMetricsStale
        expr: time() - myapp_last_scrape_timestamp_seconds > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Метрики экспортера {{ $labels.job }} устарели"

      # Высокая задержка скрапинга
      - alert: ExporterScrapeLatencyHigh
        expr: histogram_quantile(0.99, rate(exporter_scrape_duration_seconds_bucket[5m])) > 10
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка скрапинга {{ $labels.job }}"
          description: "p99 скрапинга: {{ $value }}s"
```

### Сценарий 3: Retry с exponential backoff

**Ситуация:** Целевая система (API) иногда отвечает с задержкой из-за GC pause.

```go
func (c *ApiExporter) queryWithRetry(ctx context.Context) (*ApiStats, error) {
    var lastErr error
    maxRetries := 3
    baseDelay := 500 * time.Millisecond

    for i := 0; i < maxRetries; i++ {
        queryCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
        stats, err := c.apiClient.GetStats(queryCtx)
        cancel()

        if err == nil {
            return stats, nil
        }

        lastErr = err

        // Если это не сетевая ошибка — не повторяем
        if !isRetryable(err) {
            return nil, err
        }

        // Exponential backoff с jitter
        delay := baseDelay * time.Duration(1<<uint(i))
        jitter := time.Duration(rand.Int63n(int64(delay) / 4))
        delay = delay + jitter

        log.Printf("Retry %d/%d after %v: %v", i+1, maxRetries, delay, err)

        select {
        case <-ctx.Done():
            return nil, ctx.Err()
        case <-time.After(delay):
        }
    }

    return nil, fmt.Errorf("max retries exceeded: %w", lastErr)
}

func isRetryable(err error) bool {
    if errors.Is(err, context.DeadlineExceeded) {
        return true
    }
    var netErr net.Error
    if errors.As(err, &netErr) {
        return netErr.Timeout() || !netErr.Temporary()
    }
    return false
}
```

## Дополнительная информация

### Антипаттерны

| Антипаттерн | Проблема | Решение |
|:---|:---|:---|
| **Retry storm** | Все экспортеры одновременно делают retry | Jitter + limit concurrency |
| **Cache without TTL** | Кэш отдает устаревшие данные бесконечно | Всегда ставить TTL |
| **Circuit breaker без HALF-OPEN** | После сбоя экспортер навсегда блокирует запросы | Реализовать HALF-OPEN состояние |
| **livenessProbe зависит от БД** | При падении БД экспортер рестартует бесконечно | livenessProbe проверяет только /metrics |
| **Нет self-metrics** | Невозможно отличить проблему экспортера от проблемы цели | Экспортировать exporter_* метрики |

### Чек-лист надежности

1. **Graceful degradation** — экспортер не падает при недоступности цели
2. **Circuit breaker** — при持续ных ошибках экспортер перестает долбить цель
3. **Кэш с TTL** — данные доступны даже при短暂ных сбоях
4. **Retry с jitter** — temporary ошибки обрабатываются с backoff
5. **Self-metrics** — экспортер экспортирует метрики о своей работе
6. **Алерты на metametrics** — настроены алерты на `exporter_up`, `exporter_scrape_errors_total`
7. **Stale markers** — при shutdown экспортер помечает метрики как устаревшие
8. **HA** — несколько реплик за балансировщиком (для критичных экспортеров)
9. **Rolling update** — обновление без даунтайма
10. **Rollback** — возможность отката при проблемах

### Матрица HA-стратегий

| Стратегия | Сложность | Потеря данных при отказе | Когда использовать |
|:---|:---|:---|:---|
| 1 инстанс (SPOF) | Низкая | Полная потеря метрик | Dev, не критичные системы |
| Реплики + LB | Средняя | Нет (при корректном балансировании) | Production, критичные экспортеры |
| Шардирование | Высокая | Потеря метрик shard'а | Multi-target, >1000 целей |
| Multi-DC | Высокая | Потеря метрик в одном DC | Глобальные SLA |

**См. также:**
- [Blackbox Exporter — HA и масштабирование](../blackbox/blackbox_exporter_scaling_and_ha.md) — детали для Blackbox
- [Создание собственных экспортеров](./custom_exporters.md) — архитектурные паттерны
- [Тестирование экспортеров](./exporter_testing.md) — тестирование перед релизом
- [Безопасность экспортеров](./exporter_security.md) — секреты и изоляция
- [Prometheus — HA](../../concepts/high_availability.md) — HA Prometheus сервера
