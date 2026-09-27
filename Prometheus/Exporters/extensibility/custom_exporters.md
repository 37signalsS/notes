# Создание собственных экспортеров Prometheus

## Определения

**Собственный экспортер Prometheus** — специализированный адаптер, транслирующий проприетарные данные внешних систем в метрики формата Prometheus (Text, OpenMetrics, Protobuf или OTLP).

Экспортер выступает в роли моста: он принимает HTTP-запросы от Prometheus, опрашивает целевую систему (API, БД, сетевое оборудование, legacy-сервисы) и возвращает структурированный ответ. В современных реалиях 2026 года стандартом является поддержка **Native Histograms**, **Exemplars**, **UTF-8** имен метрик и **Stale Markers**.

**См. также:** [Расширяемость — Концепции](./concepts.md), [Клиентские библиотеки](./client_libraries.md).

### Основные термины

**Collector (Коллектор)** — интерфейс или компонент, реализующий логику сбора метрик. В контексте собственных экспортеров Collector инкапсулирует группу связанных метрик и предоставляет метод `Describe` (дескрипторы) и `Collect` (значения). Это основа для пользовательских метрик и внутренних коллекторов.

**Registry (Реестр метрик)** — контейнер, управляющий жизненным циклом метрик внутри процесса. Отвечает за регистрацию, дедупликацию имен, итерируемость и экспозицию метрик. Каждая метрика должна быть зарегистрирована ровно один раз; попытка повторной регистрации вызывает панику.

**DefaultRegister (Глобальный реестр)** — стандартный экземпляр `Registry`, доступный через пакет `prometheus.DefaultRegister` (Go) или `REGISTRY` (Python). Используется для быстрого старта, но в производственных средах часто заменяется на кастомный реестр для изоляции метрик и контроля жизненного цикла.

**Metric Family (Семейство метрик)** — дескриптор метрики, объединяющий имя, HELP-строку, тип и набор лейблов. Collector возвращает семейства через канал, что позволяет единообразно обрабатывать метрики разных типов в рамках одного экспорта.

**Exposition (Экспозиция)** — процесс преобразования зарегистрированных метрик в текстовый или бинарный формат и передача их по HTTP. Является конечной точкой Pull-модели Prometheus; именно на нее направлены запросы скрапинга.

**Exemplar (Экземпляр)** — ссылка на конкретный образец трассировки (trace), привязанный к отдельному значению метрики. В Prometheus 3.0+ поддерживается на уровне клиентских библиотек через параметр `exemplar` при инкрементации счетчика или гистограммы.

**OpenMetrics** — открытый формат экспозиции метрик, ставший стандартом для Prometheus 3.0+. Включает расширенные возможности: UTF-8 в именах, Exemplars, единый формат единиц измерения.

**Stale Marker (Маркер устаревания)** — специальное значение `stale NaN`, передаваемое экспортером для принудительного удаления временного ряда из TSDB без ожидания стандартного `lookback delta` (5 минут). Критично для корректной работы при graceful shutdown.

**Native Histogram (Нативная гистограмма)** — гистограмма с экспоненциальными бакетами вместо фиксированных границ. В Prometheus 3.0+ позволяет значительно повысить точность квантилей при снижении объема хранимых данных.

**Scrape Protocol (Протокол скрейпинга)** — формат, в котором Prometheus получает метрики от экспортера. Начиная с Prometheus v2.49+, поддерживается явный выбор через `scrape_protocols` в конфигурации сервера.

**Exporter-Toolkit** — стандартный набор инструментов для разработки экспортеров на Go, обеспечивающий поддержку TLS, базовой аутентификации и динамической конфигурации.

## Основные концепции

### Архитектурные паттерны

Выбор паттерна определяет, как экспортер будет собирать и предоставлять данные. Каждый паттерн имеет свои trade-offs в части задержки, надежности и потребления ресурсов.

1.  **Collector Interface (Рекомендуемый для активных систем):** Реализация интерфейса `Collector` в клиентской библиотеке. Данные собираются только в момент запроса от Prometheus. Это гарантирует актуальность метрик и отсутствие постоянной фоновой нагрузки. Идеально подходит для систем с быстрым API (< 1 секунды на запрос).

2.  **Background Polling (Кэширующий экспортер):** Экспортер периодически опрашивает систему в фоне и хранит данные в кэше (in-memory или on-disk). Используется, если опрос цели занимает значительное время (больше `scrape_timeout`, обычно >10 секунд) или целевая система имеет strict rate limiting. Кэш должен иметь TTL для предотвращения возврата устаревших данных.

3.  **Multi-target Pattern:** Один экземпляр экспортера обслуживает множество целей. Адрес цели передается как параметр запроса (например, `/probe?target=192.168.1.1`). Используется в Blackbox Exporter и Script Exporter. Ключевое преимущество — один процесс на сотни целей; недостаток — необходимость корректной настройки `relabel_configs` на стороне Prometheus.

4.  **Push-gateway Bridge:** Экспортер может выступать прокси для Push-модели, собирая данные от эфемерных задач и отдавая их Prometheus по Pull-модели через Pushgateway. Используется при интеграции с batch-системами, где экспортер не является long-running процессом.

5.  **OTLP Receiver:** Собственный экспортер может принимать метрики в формате OTLP от других систем и транслировать их в формат Prometheus. Используется при построении шлюзов observability или миграции с OpenTelemetry Stack.

### Сравнение паттернов

| Параметр | Collector Interface | Background Polling | Multi-target | Push-gateway Bridge |
| :--- | :--- | :--- | :--- | :--- |
| **Задержка данных** | Минимальная (в момент скрапинга) | Средняя (зависит от TTL кэша) | Минимальная | Средняя |
| **Нагрузка на целевую систему** | Пиковая при каждом скрапинге | Равномерная | Пиковая при каждом скрапинге | Зависит от источника |
| **Память экспортера** | Минимальная | Высокая (кэш) | Средняя | Минимальная |
| **Сложность отладки** | Низкая | Средняя | Высокая | Низкая |
| **Поддержка Native Histograms** | Да | Да | Да | Да |

### Когда писать свой экспортер

| Сценарий | Решение |
| :--- | :--- |
| Есть готовый в [каталоге](../other_exporters.md) | Использовать готовый и проверенный сообществом. |
| Требуются метрики из простых скриптов | [Textfile Collector](./textfile_collector.md). |
| Закрытая система / Legacy API | Разработать собственный экспортер. |
| Инструментация своего приложения | [Прямая инструментация](./client_libraries.md). |
| Переход на OTLP | Использовать OpenTelemetry SDK с экспортом в Prometheus. |
| Нужен multi-target паттерн | Использовать [Blackbox Exporter](../blackbox/blackbox_exporter_overview.md) или Script Exporter. |

### Поддержка возможностей Prometheus 3.0+

При разработке современных экспортеров необходимо учитывать следующие технологии:

*   **Native Histograms:** Использование экспоненциальных бакетов вместо фиксированных границ позволяет значительно повысить точность квантилей при снижении объема хранимых данных. В Go используйте `prometheus.NewHistogram` с `NativeHistogramBucketFactor`; в Python — `histogram` с `buckets=None`.
*   **UTF-8 Names:** Поддержка точек в именах метрик (например, `myapp.requests.total`) для совместимости с OpenTelemetry. В Prometheus 3.0+ UTF-8 имена поддерживаются нативно.
*   **Exemplars:** Передача ID трассировок вместе с метриками для быстрой навигации к логам и трейсам. Требует извлечения `trace_id` из контекста запроса (например, через OpenTelemetry baggage).
*   **OpenMetrics 2.0:** Новый заголовок `# EOF` и расширенные типы. Клиентские библиотеки Prometheus 3.0+ используют OpenMetrics по умолчанию.
*   **OTLP Receiver:** Prometheus 3.0+ может принимать метрики напрямую по OTLP на порту 4317 (gRPC) или 4318 (HTTP). Для кастомных экспортеров это означает возможность отправки данных без дополнительного OTel Collector.

### Матрица совместимости версий

| Возможность | Prometheus v2.40 | Prometheus v2.49+ | Prometheus v3.0+ |
| :--- | :--- | :--- | :--- |
| **Native Histograms** | Частичная | Полная | Полная + sparse |
| **UTF-8 в именах** | Нет | Частичная (escaping) | Полная |
| **OpenMetrics 2.0** | Нет | Да | Да |
| **OTLP Receiver** | Нет | Нет | Да (нативный) |
| **scrape_protocols** | Нет | Да | Да (+ OTLP) |
| **Exemplars** | Нет | Да | Да |

### Выбор протокола: OpenMetrics vs OTLP

| Сценарий | Рекомендуемый протокол | Причина |
| :--- | :--- | :--- |
| **Legacy / Infra** | OpenMetrics (Pull) | Простота, совместимость с Service Discovery. |
| **Собственные экспортеры** | OpenMetrics (Pull) | Стандарт, широкая поддержка в client_golang. |
| **OTel-instrumented приложения** | OTLP (Pull/Push) | Унификация с трейсами, гибкость имен (UTF-8). |
| **Edge / IoT** | OTLP (Push) | Работа за NAT, отсутствие входящих соединений. |

## Практические сценарии

### Реализация интерфейса Collector на Go

Для профессиональной разработки на Go используется интерфейс `prometheus.Collector`. В примере ниже реализован экспортер для опроса внешнего API с обработкой ошибок и метриками о собственной работе.

```go
package main

import (
    "context"
    "fmt"
    "net/http"
    "time"

    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "github.com/prometheus/exporter-toolkit/web"
    "log"
)

// ExternalSystemClient имитирует клиент для внешней системы
type ExternalSystemClient struct {
    timeout time.Duration
}

func NewExternalSystemClient(timeout time.Duration) *ExternalSystemClient {
    return &ExternalSystemClient{timeout: timeout}
}

func (c *ExternalSystemClient) Query(ctx context.Context) (float64, error) {
    // Реальная реализация: HTTP-запрос, SQL-запрос, SNMP-get и т.д.
    return 42.5, nil
}

// MyCollector структура для хранения дескрипторов метрик
type MyCollector struct {
    upMetric      *prometheus.Desc
    latencyMetric *prometheus.Desc
    client        *ExternalSystemClient
}

// NewMyCollector конструктор коллектора
func NewMyCollector(client *ExternalSystemClient) *MyCollector {
    return &MyCollector{
        upMetric: prometheus.NewDesc(
            "myapp_external_system_up",
            "Статус доступности внешней системы",
            nil, nil,
        ),
        latencyMetric: prometheus.NewDesc(
            "myapp_external_system_latency_seconds",
            "Задержка запросов к внешней системе (Native Histogram)",
            []string{"endpoint"}, nil,
        ),
        client: client,
    }
}

// Describe регистрирует метрики
func (c *MyCollector) Describe(ch chan<- *prometheus.Desc) {
    ch <- c.upMetric
    ch <- c.latencyMetric
}

// Collect собирает данные в реальном времени
func (c *MyCollector) Collect(ch chan<- prometheus.Metric) {
    ctx, cancel := context.WithTimeout(context.Background(), c.client.timeout)
    defer cancel()

    start := time.Now()
    value, err := c.client.Query(ctx)
    latency := time.Since(start).Seconds()

    if err != nil {
        ch <- prometheus.MustNewConstMetric(c.upMetric, prometheus.GaugeValue, 0)
        // Ошибка: метрика задержки не отправляется, чтобы не искажать данные
        log.Printf("ERROR: failed to query external system: %v", err)
        return
    }

    ch <- prometheus.MustNewConstMetric(c.upMetric, prometheus.GaugeValue, 1)
    ch <- prometheus.MustNewConstMetric(c.latencyMetric, prometheus.GaugeValue, latency)
}

// InternalMetricsCollector собирает метрики о работе самого экспортера
type InternalMetricsCollector struct {
    scrapesTotal prometheus.Counter
    errorsTotal  prometheus.Counter
    scrapeErrors prometheus.Counter
}

func NewInternalMetricsCollector() *InternalMetricsCollector {
    return &InternalMetricsCollector{
        scrapesTotal: promauto.NewCounter(prometheus.CounterOpts{
            Name: "myapp_exporter_scrapes_total",
            Help: "Total number of scrapes.",
        }),
        errorsTotal: promauto.NewCounter(prometheus.CounterOpts{
            Name: "myapp_exporter_errors_total",
            Help: "Total number of errors.",
        }),
        scrapeErrors: promauto.NewCounter(prometheus.CounterOpts{
            Name: "myapp_exporter_scrape_errors_total",
            Help: "Total number of scrape errors.",
        }),
    }
}

func (m *InternalMetricsCollector) Describe(ch chan<- *prometheus.Desc) {}

func (m *InternalMetricsCollector) Collect(ch chan<- prometheus.Metric) {
    // Метрики о работе экспортера
    // В реальном коде здесь будут значения из внутренних счетчиков
}

func main() {
    client := NewExternalSystemClient(5 * time.Second)
    collector := NewMyCollector(client)
    internal := NewInternalMetricsCollector()

    prometheus.MustRegister(collector)
    prometheus.MustRegister(internal)

    http.Handle("/metrics", promhttp.Handler())

    server := &http.Server{Addr: ":9101"}
    log.Println("Starting exporter on :9101")

    if err := web.ListenAndServe(server, &web.FlagConfig{}, log.Default()); err != nil {
        log.Fatal(err)
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:9101/metrics | promtool check metrics
# → SUCCESS

curl -s http://localhost:9101/metrics | grep "myapp_external_system"
# → myapp_external_system_up 1
# → myapp_external_system_latency_seconds{endpoint="default"} 0.001234
```

### Развертывание: systemd unit

```ini
# /etc/systemd/system/myapp-exporter.service
[Unit]
Description=MyApp Custom Exporter
After=network.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/myapp-exporter
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp-exporter
sudo systemctl status myapp-exporter
# → active (running)
```

### Развертывание: Docker

```dockerfile
# Dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o exporter .

FROM alpine:latest
RUN addgroup -g 1001 -S prometheus && adduser -u 1001 -S prometheus -G prometheus
COPY --from=builder --chown=prometheus:prometheus /app/exporter /usr/local/bin/exporter
USER prometheus
EXPOSE 9101
ENTRYPOINT ["exporter"]
```

```bash
docker build -t myapp-exporter:latest .
docker run -d \
  --name myapp-exporter \
  --network host \
  --memory 128m \
  --cpus 0.5 \
  -v /etc/myapp-exporter/config.yml:/etc/config.yml:ro \
  myapp-exporter:latest
```

### Развертывание: Docker Compose

```yaml
version: '3.8'

services:
  myapp-exporter:
    build: .
    ports:
      - "9101:9101"
    volumes:
      - ./config.yml:/etc/config.yml:ro
    environment:
      - CONFIG_PATH=/etc/config.yml
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v3.0.0
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
```

### Реализация на Python (Custom Collector)

Python библиотека позволяет создавать кастомные сборщики через `REGISTRY`. В примере ниже показан экспортер для опроса состояния резервного копирования.

```python
from prometheus_client import start_http_server, GaugeMetricFamily, Counter
import requests
import time
import os

class BackupCollector:
    def __init__(self, backup_service_url):
        self.backup_service_url = backup_service_url
        self.errors_total = Counter(
            'myapp_backup_errors_total',
            'Total number of backup check errors'
        )

    def collect(self):
        try:
            response = requests.get(f"{self.backup_service_url}/status", timeout=5)
            response.raise_for_status()
            data = response.json()

            last_success = GaugeMetricFamily(
                'myapp_backup_last_success_timestamp_seconds',
                'Timestamp of last successful backup'
            )
            last_success.add_metric([], data.get('last_success_timestamp', 0))

            backup_size = GaugeMetricFamily(
                'myapp_backup_size_bytes',
                'Size of last backup in bytes'
            )
            backup_size.add_metric([], data.get('size_bytes', 0))

            yield last_success
            yield backup_size

        except Exception as e:
            self.errors_total.inc()
            # Возвращаем метрику доступности с значением 0
            up = GaugeMetricFamily('myapp_backup_up', 'Backup service availability')
            up.add_metric([], 0)
            yield up

if __name__ == '__main__':
    port = int(os.environ.get('EXPORTER_PORT', 9102))
    backup_url = os.environ.get('BACKUP_URL', 'http://localhost:8080')

    from prometheus_client import REGISTRY
    REGISTRY.register(BackupCollector(backup_url))

    start_http_server(port)
    print(f"Exporter started on :{port}")
    while True:
        time.sleep(1)
```

**Запуск:**
```bash
python3 backup_exporter.py --port 9102
```

**Валидация:**
```bash
curl -s http://localhost:9102/metrics | promtool check metrics
# → SUCCESS

curl -s http://localhost:9102/metrics | grep "myapp_backup"
# → myapp_backup_last_success_timestamp_seconds 0
# → myapp_backup_size_bytes 1048576
# → myapp_backup_up 1
```

### Инструментация в Java (Spring Boot 3.x / Micrometer — кастомные метрики)

Spring Boot 3.x использует Micrometer как абстракцию над метриками. При наличии `micrometer-registry-prometheus` на classpath эндпоинт `/actuator/prometheus` доступен автоматически.

```java
// pom.xml
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>

// application.yml
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  metrics:
    enable:
      all: true
    distribution:
      percentiles-histogram:
        http.server.requests: true

// Кастомный сборщик для внешней системы
@Component
public class ExternalSystemMetrics implements MeterBinder {

    private final String externalSystemUrl;

    public ExternalSystemMetrics(@Value("${external.system.url}") String externalSystemUrl) {
        this.externalSystemUrl = externalSystemUrl;
    }

    @Override
    public void bindTo(MeterRegistry registry) {
        // Создаем метрики
        Gauge.builder("myapp_external_system_queue_size")
            .description("Current queue size in external system")
            .baseUnit("items")
            .register(registry);

        Counter.builder("myapp_external_system_errors_total")
            .description("Errors when communicating with external system")
            .register(registry);
    }

    @Scheduled(fixedRate = 5000)
    public void updateMetrics() {
        try {
            // Опрос внешней системы
            int queueSize = fetchQueueSize();
            registry.find("myapp_external_system_queue_size")
                .tag("endpoint", externalSystemUrl)
                .gauge()
                .set(queueSize);
        } catch (Exception e) {
            registry.counter("myapp_external_system_errors_total").increment();
        }
    }

    private int fetchQueueSize() {
        // Реальная логика опроса
        return 42;
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8080/actuator/prometheus | promtool check metrics
```

### Инструментация в .NET (ASP.NET Core)

Библиотека `prometheus-net` интегрируется с ASP.NET Core через middleware.

```csharp
// Program.cs
using Prometheus;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
builder.Services.AddMetricFactory(); // Регистрация фабрики метрик

var app = builder.Build();

app.UseMetricServer(); // Эндпоинт /metrics
app.UseHttpMetrics();  // Автоматические метрики ASP.NET

// Кастомная метрика
var orderCounter = Metrics.CreateCounter("orders_total", "Total orders processed",
    new CounterConfiguration { LabelNames = new[] { "status" } });

app.MapPost("/orders", (Order order) => {
    orderCounter.WithLabels("completed").Inc();
    return Results.Ok();
});

// Gauge для внешней системы
var externalSystemGauge = Metrics.CreateGauge(
    "myapp_external_system_health_score",
    "Health score of external system",
    new GaugeConfiguration { Unit = "score" }
);

// Обновление метрики по расписанию
var timer = new PeriodicTimer(TimeSpan.FromSeconds(5));
_ = Task.Run(async () => {
    while (await timer.WaitForNextTickAsync())
    {
        try
        {
            double score = await FetchHealthScoreAsync();
            externalSystemGauge.Set(score);
        }
        catch
        {
            // Логирование ошибки
        }
    }
});

app.Run();
```

### Инструментация в Node.js (Cluster Mode)

В кластерном режиме Node.js создается несколько воркеров, каждый со своим `Registry`. Используйте `AggregatorRegistry` для объединения метрик.

```javascript
const client = require('prom-client');
const express = require('express');
const cluster = require('cluster');

const app = express();
const register = new client.Registry();

// В режиме кластера используем отдельный реестр
if (cluster.isMaster) {
  const aggregator = new client.AggregatorRegistry();
  
  cluster.fork().on('listening', () => {
    // Воркеры отправляют метрики через EventEmitter
  });
}

const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.1, 0.5, 1, 1.5, 2, 5],
  registers: [register]
});

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.get('/api', (req, res) => {
  const end = httpRequestDuration.startTimer();
  res.json({ status: 'ok' });
  end({ method: req.method, route: '/api', status_code: res.statusCode });
});
```

### Инструментация в Rust

```rust
use prometheus::{Counter, Histogram, HistogramOpts, Opts, Registry, TextEncoder};
use std::collections::HashMap;
use lazy_static::lazy_static;

lazy_static! {
    static ref REGISTRY: Registry = Registry::new_custom(Some("myapp".to_string()), None)
        .expect("Failed to create registry");

    static ref EXTERNAL_QUERIES: Counter = Counter::with_opts(Opts::new(
        "myapp_external_queries_total",
        "Total number of queries to external system"
    )).expect("Failed to create counter");

    static ref EXTERNAL_ERRORS: Counter = Counter::with_opts(Opts::new(
        "myapp_external_errors_total",
        "Total number of errors when querying external system"
    )).expect("Failed to create counter");
}

fn main() {
    REGISTRY.register(Box::new(EXTERNAL_QUERIES.clone()))
        .expect("Failed to register counter");

    EXTERNAL_QUERIES.inc();

    // Эндпоинт /metrics
    let encoder = TextEncoder::new();
    let metric_families = REGISTRY.gather();
    encoder.encode(&metric_families, &mut std::io::stdout()).unwrap();
}
```

## Дополнительная информация

### Собственные метрики экспортера (Internal)

Качественный экспортер должен отдавать метрики о собственной работе. Это позволяет отделить проблемы с целевой системой от проблем с самим экспортером.

*   `exporter_scrape_duration_seconds` — сколько времени занял опрос цели.
*   `exporter_scrapes_total` — общее количество попыток опроса.
*   `exporter_errors_total` — количество ошибок при общении с внешней системой.
*   `exporter_targets_total` — количество целей (для multi-target паттерна).
*   `exporter_last_scrape_timestamp_seconds` — время последнего успешного скрапинга.
*   `exporter_build_info` — метаинформация о версии экспортера (значение всегда `1`).

### Тестирование экспортера

Перед релизом экспортер необходимо проверить на соответствие стандартам форматирования:

1.  **Linter:** Используйте утилиту `promtool` для проверки формата метрик.
    ```bash
    curl -s http://localhost:9101/metrics | promtool check metrics
    # → SUCCESS: 123 metrics
    ```
2.  **Unit-тесты:** Проверяйте, что `Collect` корректно обрабатывает ошибки API внешней системы и не «крашит» экспортер. В Go используйте `prometheus.NewCounterVec` для учета ошибок в тестах.
3.  **Smoke-тесты:** Убедитесь, что при недоступности цели метрика `up` принимает значение `0`.
    ```bash
    curl -s http://localhost:9101/metrics | grep '^myapp_external_system_up'
    # → myapp_external_system_up 0
    ```
4.  **Stale marker:** Проверьте, что при остановке экспортер передает `stale NaN`.
    ```bash
    # Остановите экспортер и проверьте через 5 минут
    curl -s http://localhost:9090/api/v1/query?query=myapp_external_system_up
    # Ряд должен отсутствовать или иметь значение stale
    ```

### Чек-лист SRE перед развертыванием экспортера

1.  **Выбран оптимальный паттерн** — Collector Interface, Background Polling, Multi-target или Push-gateway Bridge.
2.  **Имена метрик соответствуют конвенциям** — нижний регистр, `_total` для счетчиков, базовые единицы в названии.
3.  **Лейблы не содержат высококардинальных значений** — нет email, ID сессий, полных URL.
4.  **Настроен `scrape_timeout`** — меньше `scrape_interval` минимум на 2 секунды.
5.  **Настроены лимиты ресурсов** — CPU и Memory limits для контейнера/systemd unit.
6.  **Реализован stale marker** — экспортер передает `stale NaN` при shutdown.
7.  **Эндпоинт защищен** — TLS, Basic Auth или сетевая изоляция (Firewall/NetworkPolicy).
8.  **Протестирован формат** — `promtool check metrics` проходит без ошибок.
9.  **Настроены алерты** — `up` метрика, отсутствие данных (`absent_over_time`).
10. **Документирована зависимость** — при сбое экспортера какие алерты должны сработать.

### Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `duplicate metrics registration` | Попытка зарегистрировать метрику с уже существующим именем | Используйте уникальные имена или проверяйте регистрацию через `Registry.Register()` с обработкой `AlreadyRegisteredError`. |
| `stale markers missing` | При завершении процесса метрики не помечаются как устаревшие | Убедитесь, что используется корректный `Collector` и экспозиция завершается штатно. |
| `scrape timeout` | Опрос цели занимает больше времени, чем `scrape_timeout` в Prometheus | Увеличьте `scrape_timeout` или перейдите на паттерн Background Polling с кэшированием. |
| `high cardinality` | Слишком много уникальных комбинаций лейблов | Ограничьте количество лейблов, используйте [Relabeling](../../service_discovery_and_relabeling.md) для фильтрации. |
| `missing _total suffix` | Счетчик без обязательного суффикса `_total` | Добавьте `_total` к имени счетчика в соответствии со спецификацией. |
| `invalid metric value` | Метрика возвращает `NaN` или `Inf` без маркера stale | Используйте `prometheus.NewInvalidMetric` только для stale NaN, а не для ошибок. |
| `connection refused` | Целевая система недоступна | Проверьте сетевую доступность, firewall, корректность адреса в конфигурации. |

### Безопасность экспортеров

Экспортеры часто имеют доступ к критическим системным вызовам или данным БД. Рекомендации:

*   **TLS и аутентификация:** Используйте `exporter-toolkit` для настройки TLS и Basic Auth. Никогда не оставляйте эндпоинты открытыми в публичных сетях. Подробнее: [Безопасность Prometheus](../../security.md).
*   **Минимальные привилегии:** Запуск процесса от не-root пользователя с доступом только к необходимым ресурсам.
*   **Сетевая изоляция:** Ограничение доступа к порту экспортера на уровне Firewall (только для IP серверов мониторинга) или NetworkPolicy.
*   **Секреты:** Никогда не передавайте API-ключи или пароли через лейблы метрик. Используйте переменные окружения или внешние секреты (Vault, etcd).

### Производительность и ресурсы

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| `scrape_timeout` | < `scrape_interval` на 2–3s | Предотвращение наложения скрапингов |
| `scrape_interval` (инфраструктура) | 30–60s | Баланс актуальности и нагрузки |
| `scrape_interval` (приложения) | 5–15s | Более частый сбор для критичных сервисов |
| CPU limit (экспортер) | 0.5–2 ядра | Зависит от паттерна сбора |
| Memory limit (экспортер) | 128–512MB | Для кэширующих экспортеров — до 2GB |
| Лимит открытых файлов | 65536 | Для multi-target экспортеров с сотнями целей |

**Производительность Prometheus при большом количестве экспортеров:**
При 500 целях с 1000 метрик каждая TSDB записывает ~500K samples/цикл. Это требует:
- WAL на NVMe SSD (высокая IOPS)
- Head Block RAM: ~8–16 ГБ на 1M активных рядов
- scrape_interval: не ниже 15s для предотвращения перегрева индекса

### Жизненный цикл и управление

*   **Грейсфул-шатдаун:** При завершении работы экспортер должен явно передавать `stale NaN` для всех метрик, чтобы Prometheus немедленно прекращал отслеживание рядов. Это критично для снижения churn rate в динамических средах.
*   **Реинициализация:** При рестарте приложения все метрики сбрасываются. Если требуется сохранение состояния между перезапусками, используйте [Textfile Collector](./textfile_collector.md) для записи итоговых значений или [Pushgateway](../../pushgateway.md).
*   **Мониторинг библиотеки:** Сама библиотека может потреблять ресурсы при большом количестве метрик. Мониторьте память процесса и время экспозиции.
*   **Обновление:** При обновлении клиентской библиотеки проверяйте breaking changes в API (например, изменение сигнатур `Collect` или `Describe`).

### Edge cases и ограничения

*   **Textfile Collector и Native Histograms:** Формат `.prom` поддерживает только классические бакеты. Для нативных гистограмм используйте OTLP или бинарный Protobuf.
*   **Script Exporter и concurrency:** Если Prometheus делает параллельные запросы к Script Exporter, убедитесь, что скрипты потокобезопасны или экспортер использует очередь.
*   **Pushgateway и репликация:** Pushgateway — single point of failure. Для production развертывайте минимум 2 инстанса за балансировщиком с sticky sessions (ключ — grouping key).
*   **OTLP и UTF-8:** При использовании UTF-8 имен убедитесь, что версия Grafana >= 11 корректно экранирует символы для предотвращения XSS.
*   **Native Histograms и TSDB:** При большом количестве уникальных комбинаций лейблов в нативных гистограммах может наблюдаться рост потребления памяти. Используйте `max_sigma_buckets` для ограничения количества бакетов.

### Технические требования

*   **Порты:** Резервируйте порты в диапазоне `9100–9999`, сверяясь с [реестром портов](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).
*   **Таймауты:** Ответ должен возвращаться быстрее, чем настроенный `scrape_timeout` в Prometheus (по умолчанию 10с).
*   **Лейблы:** Не добавляйте лейблы инфраструктуры (env, zone) внутри кода. Используйте [Relabeling](../../service_discovery_and_relabeling.md) для обогащения данных.
*   **Лимиты ресурсов:** Устанавливайте CPU и Memory limits для процесса экспортера, особенно при использовании паттерна Background Polling.

**См. также:**
*   [Тестирование экспортеров](./exporter_testing.md) — юнит-тесты, интеграция, benchmarking.
*   [Kubernetes паттерны](./k8s_exporter_patterns.md) — Deployment, DaemonSet, Sidecar, probes.
*   [Надежность экспортеров](./exporter_reliability.md) — graceful degradation, circuit breaker, HA.
*   [Безопасность экспортеров](./exporter_security.md) — секреты, TLS, NetworkPolicy.
*   [Blackbox Exporter — пример Multi-target](../blackbox/blackbox_exporter_overview.md).
*   [Типы метрик](../../concepts/metric_types/overview.md).
*   [Remote Write 2.0](../../scaling/remote_read_write.md).
*   [Формат экспозиции](../../concepts/metric_types/exposition_format.md).
