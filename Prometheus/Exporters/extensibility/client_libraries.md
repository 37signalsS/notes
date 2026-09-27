# Клиентские библиотеки Prometheus

## Определения

**Клиентская библиотека Prometheus** — программный интерфейс (API) для инструментации приложений, предназначенный для управления метриками и их экспозиции в форматах Prometheus Text, OpenMetrics или OTLP.

Библиотеки решают две основные задачи:
1.  **Прямая инструментация:** Встраивание сбора метрик непосредственно в код бизнес-логики для отслеживания производительности, ошибок и бизнес-показателей в реальном времени.
2.  **Создание кастомных экспортеров:** Разработка адаптеров для внешних систем без нативной поддержки Prometheus ([Создание собственных экспортеров](./custom_exporters.md)).

**Registry (Реестр метрик)** — контейнер, управляющий жизненным циклом метрик внутри процесса. Отвечает за регистрацию, дедупликацию имен, итерируемость и экспозицию метрик. Каждая метрика должна быть зарегистрирована ровно один раз; попытка повторной регистрации вызывает панику.

**DefaultRegister (Глобальный реестр)** — стандартный экземпляр `Registry`, доступный через пакет `prometheus.DefaultRegister` (Go) или `REGISTRY` (Python). Используется для быстрого старта, но в производственных средах часто заменяется на кастомный реестр для изоляции метрик и контроля жизненного цикла.

**Collector (Коллектор)** — интерфейс или компонент, реализующий логику сбора метрик. В контексте клиентских библиотек Collector инкапсулирует группу связанных метрик и предоставляет метод `Describe` (дескрипторы) и `Collect` (значения). Это основа для пользовательских метрик и внутренних коллекторов (например, `NewGoCollector`).

**Metric Family (Семейство метрик)** — дескриптор метрики, объединяющий имя, HELP-строку, тип и набор лейблов. Collector возвращает семейства через канал, что позволяет единообразно обрабатывать метрики разных типов в рамках одного экспорта.

**Exposition (Экспозиция)** — процесс преобразования зарегистрированных метрик в текстовый или бинарный формат и передача их по HTTP. Является конечной точкой Pull-модели Prometheus; именно на нее направлены запросы скрапинга.

**Stale Marker (Маркер устаревания)** — специальный заголовок и метка `stale` в формате OpenMetrics, которые библиотека автоматически добавляет при удалении метрики из реестра или завершении работы процесса. Позволяет Prometheus корректно обрабатывать исчезновение временных рядов без ручного управления.

**Exemplar (Экземпляр)** — ссылка на конкретный образец трассировки (trace), привязанный к отдельному значению метрики. В Prometheus 3.0+ поддерживается на уровне клиентских библиотек через параметр `exemplar` при инкрементации счетчика или гистограммы. Требует предварительного извлечения `trace_id` из контекста запроса (например, через OpenTelemetry API).

**Scrape Protocol (Протокол скрейпинга)** — формат, в котором Prometheus получает метрики от экспортера. Клиентские библиотеки могут экспонировать метрики в нескольких форматах; начиная с Prometheus 2.49+, поддерживается явный выбор через `scrape_protocols` в конфигурации сервера.

## Основные концепции

### Архитектура и жизненный цикл

Жизненный цикл метрики в клиентской библиотеке состоит из четырех этапов:
1.  **Создание (Creation):** Инициализация дескриптора с указанием имени, HELP-строки, типа и лейблов. В Go — через `prometheus.NewDesc` или обертку `promauto`; в Python — через класс `Gauge`, `Counter`, `Histogram`.
2.  **Регистрация (Registration):** Добавление метрики в `Registry`. При использовании `promauto` регистрация происходит автоматически. Ручная регистрация требует вызова `Registry.Register()`, который проверяет уникальность имени.
3.  **Наблюдение (Observation):** Изменение значений метрик в процессе работы приложения (инкремент счетчика, установка значения Gauge, запись в гистограмму). Все операции потокобезопасны и не требуют внешней блокировки.
4.  **Экспозиция (Exposition):** На запрос `/metrics` библиотека итерирует по зарегистрированным Collectors, вызывает их `Collect()`, сериализует метрики в выбранный формат и возвращает HTTP-ответ.

Критически важный аспект: **метрики существуют только внутри процесса**. При падении приложения все неперсистентные метрики теряются. Для сохранения состояния между перезапусками используйте [Textfile Collector](./textfile_collector.md) или [Pushgateway](../../pushgateway.md).

### Поддерживаемые языки (2026)

Библиотеки делятся на официальные (поддерживаемые командой Prometheus) и одобренные сообществом. Все современные версии поддерживают формат **OpenMetrics**, **Exemplars** и нативный прием **OTLP**.

| Язык | Библиотека | Статус / Особенности |
| :--- | :--- | :--- |
| **Go** | [client_golang](https://github.com/prometheus/client_golang) | Официальная. Эталонная реализация, полная поддержка Native Histograms и UTF-8. |
| **Java** | [client_java](https://github.com/prometheus/client_java) | Официальная. Глубокая интеграция с Micrometer, Spring Boot 3.x и Quarkus. |
| **Python** | [client_python](https://github.com/prometheus/client_python) | Официальная. Поддержка мультипроцессного режима (WSGI/ASGI) и декораторов. |
| **Rust** | [prometheus-client-mmap](https://github.com/tikv/rust-prometheus) | Сообщество. Оптимизирована для систем с минимальным оверхедом. |
| **Node.js** | [prom-client](https://github.com/siimon/prom-client) | Сообщество. Поддержка TypeScript и агрегации воркеров (Cluster mode). |
| **.NET** | [prometheus-net](https://github.com/prometheus-net/prometheus-net) | Сообщество. Нативная интеграция с диагностикой .NET 8+ и OTel. |

### Модели развертывания

| Модель | Описание | Когда использовать |
| :--- | :--- | :--- |
| **In-process** | Метрики собираются внутри основного процесса приложения. Единый HTTP-эндпоинт `/metrics`. | Long-running сервисы: API, worker, daemon. |
| **Sidecar** | Отдельный легковесный процесс, собирающий метрики из shared storage (текстовые файлы, unix socket). | Legacy приложения без возможности пере编译, multi-process среды (uWSGI, gunicorn). |
| **Pushgateway Bridge** | Приложение отправляет метрики в Pushgateway, который затем скрейпится Prometheus. | Ephemeral задачи: cron, CI/CD пайплайны, batch-обработка. |

### Технологические возможности (Prometheus 3.0+)

1.  **Native Histograms (Нативные гистограммы):** Обеспечивают высокую точность квантилей без ручного подбора границ корзин. Библиотеки Go и Java автоматически генерируют экспоненциальные бакеты, что снижает нагрузку на хранилище и упрощает конфигурацию.
2.  **Exemplars (Экземпляры):** Позволяют связать метрики с трейсами OpenTelemetry, передавая `trace_id` прямо в строке метрики. Это критично для перехода от графиков задержек к конкретным запросам в Jaeger/Tempo.
3.  **OTLP Integration:** Современные библиотеки могут экспортировать данные как через стандартный HTTP-скрейпинг, так и отправлять (push) их в формате OTLP в Prometheus OTLP Receiver или OpenTelemetry Collector.
4.  **UTF-8 Support:** Поддержка расширенных имен метрик и лейблов, что упрощает прямую трансляцию имен из OpenTelemetry без их искажения (например, использование точек в именах).

### Способы регистрации метрик

| Способ | Где используется | Характеристики |
| :--- | :--- | :--- |
| **Автоматическая (`promauto`)** | Go | Метрики регистрируются в `DefaultRegister` при первом использовании. Минимальный код, но менее гибкий контроль. |
| **Явная через `Registry`** | Все языки | Явный вызов `Registry.Register()`. Позволяет создавать изолированные реестры, управлять порядком экспозиции и обрабатывать ошибки регистрации. |
| **Декораторы** | Python | Обертка `@start_http_server` или `@Summary` автоматически создает и регистрирует метрики. Удобно для быстрого прототипирования. |
| **Кастомный Collector** | Все языки | Реализация интерфейса `Collector` для сложной логики сбора. Используется в кастомных экспортерах и когда метрики зависят от внешних систем. |
| **Multiprocess Collector** | Python (WSGI/ASGI) | Специальный режим `multiprocess.MultiProcessCollector` для агрегации метрик из нескольких воркеров через shared файлы. Требует настройки каталога для временных файлов. |

## Практические сценарии

### Инструментация в Go (С учетом Native Histograms)

Использование `promauto` для автоматической регистрации и нативных гистограмм для точного измерения задержек.

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    // Нативная гистограмма (v3.0+)
    requestLatency = promauto.NewHistogram(prometheus.HistogramOpts{
        Namespace: "api",
        Subsystem: "http",
        Name:      "request_duration_seconds",
        Help:      "Duration of HTTP requests in seconds (Native Histogram).",
        NativeHistogramBucketFactor: 1.1,
    })

    httpRequests = promauto.NewCounterVec(prometheus.CounterOpts{
        Namespace: "api",
        Subsystem: "http",
        Name:      "requests_total",
        Help:      "Total number of HTTP requests.",
    }, []string{"method", "code"})
)

func main() {
    http.Handle("/metrics", promhttp.Handler())
    
    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        timer := prometheus.NewTimer(requestLatency)
        defer timer.ObserveDuration()
        
        w.WriteHeader(http.StatusOK)
        httpRequests.WithLabelValues(r.Method, "200").Inc()
    })

    http.ListenAndServe(":8080", nil)
}
```

**Валидация:**
```bash
curl -s http://localhost:8080/metrics | promtool check metrics
# → "SUCCESS: 2 metric families found"
```

### Инструментация в Python (Multiprocess / WSGI)

В средах с несколькими воркерами (gunicorn, uWSGI) каждый процесс имеет свой `Registry`. Для корректной агрегации метрик используйте `MultiProcessCollector`.

```python
from prometheus_client import Counter, Gauge, multiprocess, start_http_server
import os

# Путь к каталогу для shared файлов между воркерами
os.environ['PROMETHEUS_MULTIPROC_DIR'] = '/tmp/prometheus_metrics'
multiprocess.MultiProcessCollector(Gauge)

REQUESTS = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
ACTIVE_USERS = Gauge('active_users', 'Current active users')

def handle_request(method, endpoint):
    REQUESTS.labels(method=method, endpoint=endpoint).inc()

def set_active_users(count):
    ACTIVE_USERS.set(count)

if __name__ == '__main__':
    start_http_server(8000)
```

**Конфигурация gunicorn:**
```bash
gunicorn app:app \
  --workers 4 \
  --worker-class sync \
  --env PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_metrics \
  --bind 0.0.0.0:8080
```

**Очистка:**
```bash
# При рестарте удалите устаревшие файлы
rm -rf /tmp/prometheus_metrics/*
```

### Инструментация в Java (Spring Boot 3.x / Micrometer)

Spring Boot 3.x использует Micrometer как абстракцию над метриками. При наличии `micrometer-registry-prometheus` на classpath эндпоинт `/actuator/prometheus` доступен автоматически.

```java
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

// Кастомная метрика в коде
@Component
public class OrderMetrics {
    private final MeterRegistry registry;
    private final Counter orderCounter;
    private final Timer orderProcessingTimer;

    public OrderMetrics(MeterRegistry registry) {
        this.registry = registry;
        this.orderCounter = registry.counter("orders_total", "status", "pending");
        this.orderProcessingTimer = registry.timer("order_processing_seconds", "status", "completed");
    }

    public void recordOrder(String status) {
        orderCounter.increment();
    }

    public void recordProcessingTime(Duration duration) {
        orderProcessingTimer.record(duration);
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8080/actuator/prometheus | promtool check metrics
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

### Инструментация в .NET

Библиотека `prometheus-net` интегрируется с ASP.NET Core через middleware.

```csharp
// Program.cs
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

app.Run();
```

## Дополнительная информация

### Валидация инструментации

Качество инструментации проверяется на трех уровнях:

1.  **Формат метрик:**
    ```bash
    curl -s http://localhost:8080/metrics | promtool check metrics
    # Проверяет соответствие спецификации Prometheus Text/OpenMetrics
    ```
2.  **Логика именования:**
    ```bash
    curl -s http://localhost:8080/metrics | promtool check metrics --compliance-level strict
    # Проверяет наличие _total для счетчиков, корректность лейблов
    ```
3.  **Значения метрик:**
    ```bash
    curl -s http://localhost:8080/metrics | grep -E "^# TYPE|^api_http_requests_total"
    # Визуальная проверка корректности типов и значений
    ```

### Критерии выбора метода инструментации

| Критерий | Клиентская библиотека | Textfile Collector | OTel SDK |
| :--- | :--- | :--- | :--- |
| **Тип сервиса** | Долгоживущий (API, DB) | Краткосрочный (Cron) | Cloud-Native / Multi-cloud |
| **Точность** | Максимальная | Низкая (stale data) | Высокая |
| **Сложность** | Средняя (код) | Низкая (скрипт) | Высокая (конфигурация) |
| **Возможности** | Exemplars, Native Histograms | Только Counter/Gauge | Traces, Logs, Metrics |

### Рекомендации по безопасности

1.  **Exporter-Toolkit:** При написании собственных экспортеров на Go всегда используйте `prometheus/exporter-toolkit` для реализации TLS и аутентификации.
2.  **Защита эндпоинта:** Не выставляйте эндпоинт `/metrics` в публичный интернет без защиты на уровне Ingress или Firewall.
3.  **Порты:** Следуйте [реестру портов Prometheus](https://github.com/prometheus/prometheus/wiki/Default-port-allocations) для предотвращения конфликтов.

### Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `duplicate metrics registration` | Попытка зарегистрировать метрику с уже существующим именем | Используйте уникальные имена или проверяйте регистрацию через `Registry.Register()` с обработкой `AlreadyRegisteredError`. |
| `stale markers missing` | При завершении процесса метрики не помечаются как устаревшие | Убедитесь, что используется корректный `Collector` и экспозиция завершается штатно. |
| `multiprocess metrics mismatch` | Воркеры используют разные каталоги для shared файлов | Проверьте переменную окружения `PROMETHEUS_MULTIPROC_DIR` и права на каталог. |
| `high cardinality` | Слишком много уникальных комбинаций лейблов | Ограничьте количество лейблов, используйте [Relabeling](../../service_discovery_and_relabeling.md) для фильтрации. |
| `missing _total suffix` | Счетчик без обязательного суффикса `_total` | Добавьте `_total` к имени счетчика в соответствии со спецификацией. |

### Производительность и ресурсы

Клиентские библиотеки добавляют минимальный накладной расход:
- **Память:** ~10–50 MB на процесс в зависимости от количества метрик и размера лейблов. Каждая метрика требует ~100–500 байт для хранения дескриптора.
- **CPU:** Экспозиция метрик занимает 1–5% CPU при типичной нагрузке (до 10 000 метрик, 1 scrape/с). Нативные гистограммы требуют больше CPU при записи, но меньше при чтении.
- **Сеть:** Формат OpenMetrics на 20–30% больше по объему, чем классический Prometheus Text, из-за дополнительных полей `# HELP` и `# TYPE`. Protobuf и OTLP эффективнее для больших объемов.

### Жизненный цикл и управление

- **Грейсфул-шатдаун:** При завершении работы приложения метрики автоматически помечаются как `stale`. В Go это происходит при закрытии HTTP-сервера; в Python — при завершении главного процесса. Для мультипроцессных сред убедитесь, что все воркеры завершаются корректно.
- **Реинициализация:** При рестарте приложения все метрики сбрасываются. Если требуется сохранение состояния между перезапусками, используйте [Textfile Collector](./textfile_collector.md) для записи итоговых значений или [Pushgateway](../../pushgateway.md).
- **Мониторинг библиотеки:** Сама библиотека может потреблять ресурсы при большом количестве метрик. Мониторьте память процесса и время экспозиции (`exporter_scrape_duration_seconds` в собственных метриках, если экспортер их предоставляет).

**См. также:**
*   [Тестирование экспортеров](./exporter_testing.md) — тестирование инструментации и экспортеров.
*   [Надежность экспортеров](./exporter_reliability.md) — graceful degradation, circuit breaker.
*   [Метрики рантайма Go](./go_runtime_metrics.md)
*   [Формат экспозиции](../../concepts/metric_types/exposition_format.md)
*   [Расширяемость — Концепции](./concepts.md)
