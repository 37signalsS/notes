# Стратегии сэмплирования в Jaeger

**Актуально для:** Jaeger v2.x / OpenTelemetry Collector v0.118+ / Kubernetes 1.28–1.32

> **Статус:** Документация описывает архитектуру и практическую настройку всех моделей сэмплирования для **Jaeger v2** (на базе кодовой базы OpenTelemetry Collector). Рассматриваются on-premise и bare-metal сценарии без использования проприетарных облачных платформ и без AI-компонентов.

**Сэмплирование (Sampling)** в распределенной трассировке — это комплекс алгоритмов и политик отбора трасс, позволяющий сократить объемы дисковых операций, сетевого трафика и процессорного времени при сохранении статистически достоверной картины производительности и гарантированном захвате аномалий и сбоев.

В высоконагруженных production-контурах запись 100% спанов в постоянное хранилище (ClickHouse, Elasticsearch) технически и экономически нецелесообразна: при потоках от 50 000 до 500 000 спанов/с это приводит к взрывному росту дискового I/O, затрат на хранение и деградации производительности поисковых запросов. Корректно спроектированная стратегия сэмплирования решает эту проблему за счет разделения потоков на рутинные и аномальные.

Смежные документы:
* Общие архитектурные концепции: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Расчет вычислительных ресурсов под объемы трасс: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Анализ задержек и критического пути: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Развертывание в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Отказоустойчивость кластера: **[High Availability и DR для Jaeger](./jaeger_high_availability.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Head-based Sampling** | Метод сэмплирования, при котором решение о сохранении или отбрасывании трассы принимается в момент инициации корневого спана (Root Span) в SDK приложения |
| **Tail-based Sampling** | Метод сэмплирования, при котором решение о сохранении трассы принимается на уровне коллектора после сбора всех спанов графа на основе итогового статуса (ошибка), длительности или атрибутов |
| **Remote Sampling** | Архитектурный механизм Jaeger, позволяющий централизованно управлять стратегиями сэмплирования микросервисов через HTTP/gRPC эндпоинты коллектора без перезапуска приложений |
| **Adaptive Sampling** | Динамический механизм обратной связи в Jaeger: коллектор анализирует входящий трафик по парам `(service, operation)` и автоматически рассчитывает вероятности для удержания заданного целевого RPS |
| **Per-Operation Sampling** | Гранулярная стратегия сэмплирования, задающая индивидуальные лимиты и вероятности для конкретных эндпоинтов (например, 100% для оплаты и 0.1% для healthcheck) |
| **`loadbalancing` Exporter** | Компонент OpenTelemetry Collector, обеспечивающий детерминированную маршрутизацию спанов с одинаковым `trace_id` на один и тот же бэкенд-инстанс коллектора по алгоритму консистентного хэширования |
| **`tail_sampling` Processor** | Процессор OpenTelemetry Collector, буферизирующий спаны трассы в оперативной памяти на заданный интервал (`decision_wait`) и вычисляющий композитные правила фильтрации |
| **Decision Wait** | Временной интервал ожидания поступления всех дочерних спанов распределенной трассы в памяти процессора `tail_sampling` до принятия решения о записи |
| **2-Tier Architecture (Двухуровневая архитектура)** | Топология развертывания коллекторов: уровень маршрутизации (Tier 1 Gateway с `loadbalancingexporter`) и уровень агрегации и фильтрации (Tier 2 Core с `tail_sampling`) |
| **Guaranteed Throughput (Нижняя граница RPS)** | Минимальное гарантированное число трасс в секунду для редких операций, предотвращающее их полное исчезновение из аналитики при низких вероятностях |

---

## Базовые концепции и архитектура

### 1. Сравнительный анализ моделей сэмплирования

Выбор модели сэмплирования определяет точку принятия решения, требования к вычислительным ресурсам и гарантии захвата инцидентов:

| Критерий | Head-based Sampling | Adaptive Sampling | Tail-based Sampling |
| :--- | :--- | :--- | :--- |
| **Точка принятия решения** | SDK клиента (старт корневого спана) | SDK клиента (по динамическим весам коллектора) | Collector (после завершения трассы) |
| **Осведомленность об ошибках** | Отсутствует (решение принимается до выполнения) | Отсутствует (чисто статистическое распределение) | Полная (сохраняет 100% ошибок и аномалий) |
| **Осведомленность о длительности (Latency)** | Отсутствует | Отсутствует | Полная (сохраняет все вызовы выше p95/p99) |
| **Нагрузка на сеть от приложений** | Минимальная (отброшенные спаны не отправляются) | Минимальная | Полная (все спаны передаются на уровень коллектора) |
| **Потребление RAM коллектором** | Минимальное (потоковая запись) | Минимальное | Высокое (буферизация графов в RAM на `decision_wait`) |
| **Сложность инфраструктуры** | Низкая (1 уровень коллекторов) | Средняя (настройка `remote_sampling`) | Высокая (2-Tier архитектура с роутингом по `trace_id`) |
| **Применение в Production** | Фоновые рутинные сервисы, сверхвысокий RPS | Крупные микросервисные ландшафты со статическим лимитом | Критичные платежные шлюзы, SLO-контуры, отладка инцидентов |

---

### 2. Remote и Adaptive Sampling в Jaeger v2

В архитектуре Jaeger v2 централизованное управление сэмплированием реализуется расширением `jaeger_sampling` (или `remote_sampling` в зависимости от сборки коллектора).

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Контур Remote / Adaptive Sampling                    │
│                                                                        │
│   [ Microservice A (OTel SDK) ] ───► OTLP Spans ──┐                    │
│                 ▲                                 │                    │
│                 │ Polling GET /api/sampling       │                    │
│                 │ (каждые 60 сек)                 ▼                    │
│   ┌─────────────┴──────────────────────────────────────────────────┐   │
│   │                     Jaeger v2 Collector                        │   │
│   │                                                                │   │
│   │  [ Extension: remote_sampling ]                                │   │
│   │         ├── Статический файл стратегий (strategies.json)       │   │
│   │         └── Расчет Adaptive Sampling (Feedback Loop)           │   │
│   │                     ▲                                          │   │
│   │                     │ Анализ входящего потока (RPS per op)     │   │
│   │  [ Receivers ] ─────┴────► [ Processors ] ───► [ Exporters ]   │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

#### Механизм Adaptive Sampling (Обратная связь)
1. Коллектор Jaeger непрерывно подсчитывает частоту появления спанов для каждой пары `(service_name, operation_name)`.
2. Администратор задает целевое количество сохраняемых спанов в секунду (`target_samples_per_second`, например, 5 спанов/с на операцию).
3. Коллектор вычисляет новую вероятность по формуле:
   $$P = \min\left(1.0, \frac{\text{Target RPS}}{\text{Current RPS}}\right)$$
4. Клиентские SDK периодически опрашивают эндпоинт `http://jaeger-collector:5778/api/sampling?service=<service_name>` и обновляют локальные вероятности без перезагрузки процессов.

---

### 3. Кластерная проблема Tail-based Sampling и двухуровневая архитектура (2-Tier)

Процессор `tail_sampling` принимает решение на основе анализа **всего графа спанов**. Если спаны одного трейса разделены между разными инстансами коллектора, процессор принимает решение на основе неполных данных:

```
[ОШИБОЧНАЯ ТОПОЛОГИЯ: Обычный L4/L7 Балансировщик]

Client ──► K8s Service (Round-Robin)
                 ├── Span 1 (Root, 200 OK)    ──► Collector Pod 1 ──► [tail_sampling: Ошибок нет -> DROP]
                 └── Span 2 (DB, 500 ERROR)  ──► Collector Pod 2 ──► [tail_sampling: Сохранил обрубок без Root]
```

#### Решение: Двухуровневая архитектура с `loadbalancingexporter`

Для корректной работы Tail-based сэмплирования в масштабируемом кластере разворачивается двухуровневый конвейер:

```
[ПРОДАКШЕН ТОПОЛОГИЯ: 2-Tier Architecture]

Приложения (OTel SDK / Beyla)
       │
       ▼ (OTLP gRPC)
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 1: Gateway Collectors (Stateless, DaemonSet или Deployment)      │
│                                                                        │
│   Receivers: otlp                                                      │
│   Processors: memory_limiter, batch                                    │
│   Exporters:                                                           │
│     loadbalancing:                                                     │
│       routing_key: "traceID"                                           │
│       resolver: dns (headless service -> IPs всех подов Tier 2)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Хэширование TraceID
                                    ▼ (Все спаны трейса X -> Pod Y)
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 2: Core Jaeger v2 Collectors (Stateful буферизация в RAM)         │
│                                                                        │
│   Receivers: otlp                                                      │
│   Processors:                                                          │
│     1. memory_limiter (Защита от OOM)                                  │
│     2. tail_sampling (decision_wait: 10s, фильтр ошибок и задержек)    │
│     3. batch (Формирование пачек для СУБД)                             │
│   Exporters:                                                           │
│     jaeger_storage_exporter ──► ClickHouse Кластер                     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Конфигурация статических и Per-Operation стратегий через Remote Sampling

**Задача:** Сконфигурировать централизованную раздачу стратегий сэмплирования в Jaeger v2:
* Сервис `billing-service`: сохранять 100% спанов для эндпоинта `/checkout`, 50% для `/invoice`, базово 10%.
* Сервис `frontend-api`: отсекать спаны мониторинга `/healthz` (0.01%) и сэмплировать 5% обычных запросов.
* Все остальные сервисы: вероятностное сэмплирование 1% с гарантированным минимумом 1 спан в 5 секунд.

#### 1. Создание манифеста стратегий (`sampling_strategies.json`)

```json
{
  "service_strategies": [
    {
      "service": "billing-service",
      "type": "probabilistic",
      "param": 0.1,
      "operation_strategies": [
        {
          "operation": "POST /api/v1/checkout",
          "type": "probabilistic",
          "param": 1.0
        },
        {
          "operation": "POST /api/v1/invoice",
          "type": "probabilistic",
          "param": 0.5
        }
      ]
    },
    {
      "service": "frontend-api",
      "type": "probabilistic",
      "param": 0.05,
      "operation_strategies": [
        {
          "operation": "GET /healthz",
          "type": "probabilistic",
          "param": 0.0001
        },
        {
          "operation": "GET /metrics",
          "type": "probabilistic",
          "param": 0.0001
        }
      ]
    }
  ],
  "default_strategy": {
    "type": "probabilistic",
    "param": 0.01,
    "operation_strategies": []
  }
}
```

#### 2. Конфигурация Jaeger v2 (`config.yaml`)

```yaml
extensions:
  jaeger_storage:
    backends:
      clickhouse_main:
        clickhouse:
          endpoint: "tcp://192.168.10.21:9000"
          database: "jaeger_v2"
          username: "jaeger"
          password: "SecretStoragePassword123"

  jaeger_query:
    storage:
      traces: clickhouse_main

  remote_sampling:
    file: /etc/jaeger/sampling_strategies.json
    http:
      endpoint: 0.0.0.0:5778
    grpc:
      endpoint: 0.0.0.0:5779

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 8192
    timeout: 2s

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_main

service:
  extensions: [jaeger_storage, jaeger_query, remote_sampling]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

#### 3. Проверка выдачи стратегии клиентам через CLI

```bash
# Проверка выдачи стратегий для billing-service
curl -sS "http://127.0.0.1:5778/api/sampling?service=billing-service" | jq .
# → {
# →   "strategyType": "PROBABILISTIC",
# →   "probabilisticSampling": { "samplingRate": 0.1 },
# →   "operationSampling": {
# →     "defaultSamplingRate": 0.1,
# →     "perOperationStrategies": [
# →       { "operation": "POST /api/v1/checkout", "probabilisticSampling": { "samplingRate": 1 } },
# →       { "operation": "POST /api/v1/invoice", "probabilisticSampling": { "samplingRate": 0.5 } }
# →     ]
# →   }
# → }
```

---

### Сценарий 2: Развертывание 2-Tier кластера с Tail-Based сэмплированием в Kubernetes

**Задача:** Построить масштабируемый отказоустойчивый конвейер в Kubernetes:
* **Tier 1 (Gateway):** 3 реплики коллектора за стандартным Service. Балансируют спаны по `trace_id` на Tier 2 через Headless Service.
* **Tier 2 (Core Collectors):** 4 реплики Jaeger v2. Принимают шардированные спаны, буферизируют в RAM на 10 секунд и сохраняют:
  1. 100% трасс со статусом ошибки (`status.code == ERROR` или HTTP 5xx).
  2. 100% медленных трасс (длительность более 750 мс).
  3. 1% успешных штатных трасс.

#### 1. Манифест Headless Service для подов Tier 2

```yaml
apiVersion: v1
kind: Service
metadata:
  name: jaeger-tier2-headless
  namespace: observability
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: jaeger-tier2-core
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
```

#### 2. Конфигурация Tier 1: Gateway Collector (Манифест ConfigMap)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-gateway-config
  namespace: observability
data:
  config.yaml: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318

    processors:
      memory_limiter:
        check_interval: 500ms
        limit_percentage: 80
        spike_limit_percentage: 20

      batch:
        send_batch_size: 4096
        timeout: 1s

    exporters:
      loadbalancing:
        routing_key: "traceID"
        protocol:
          otlp:
            timeout: 5s
            tls:
              insecure: true
        resolver:
          dns:
            hostname: jaeger-tier2-headless.observability.svc.cluster.local
            port: 4317

    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [loadbalancing]
```

#### 3. Конфигурация Tier 2: Jaeger v2 Core с Tail-Based Sampling

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jaeger-tier2-config
  namespace: observability
data:
  config.yaml: |
    extensions:
      jaeger_storage:
        backends:
          clickhouse_main:
            clickhouse:
              endpoint: "tcp://clickhouse-cluster.database.svc:9000"
              database: "jaeger_v2"
              username: "jaeger"
              password: "SecureProductionStoragePassword"

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317

    processors:
      # КРИТИЧЕСКИ ВАЖНО: memory_limiter обязан быть строго ПЕРВЫМ
      memory_limiter:
        check_interval: 1s
        limit_percentage: 75
        spike_limit_percentage: 15

      tail_sampling:
        decision_wait: 10s
        num_traces: 25000
        expected_new_traces_per_sec: 2000
        policies:
          # Политика 1: Сохранять 100% сбоев
          - name: filter-errors
            type: status_code
            status_code:
              status_codes: [ERROR]

          # Политика 2: Сохранять медленные транзакции (медленнее 750 мс)
          - name: filter-latency
            type: latency
            latency:
              threshold_ms: 750

          # Политика 3: Сохранять ошибки HTTP (5xx) по атрибуту
          - name: filter-http-5xx
            type: numeric_attribute
            numeric_attribute:
              key: "http.status_code"
              min_value: 500
              max_value: 599

          # Политика 4: Сохранять 1% штатного трафика для фоновой аналитики
          - name: filter-probabilistic
            type: probabilistic
            probabilistic:
              sampling_percentage: 1.0

      # batch процессор ставится ПОСЛЕ tail_sampling перед экспортером
      batch:
        send_batch_size: 8192
        timeout: 2s

    exporters:
      jaeger_storage_exporter:
        trace_storage: clickhouse_main

    service:
      extensions: [jaeger_storage]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, tail_sampling, batch]
          exporters: [jaeger_storage_exporter]
```

#### 4. Валидация работы двухуровневого конвейера

```bash
# 1. Проверка обнаружения эндпоинтов Tier 2 через DNS-резолвер в логах Gateway
kubectl logs -n observability -l app=otel-gateway --tail=50 | grep "loadbalancing"
# → {"level":"info","msg":"DNS resolver endpoints updated","endpoints":["10.244.2.14:4317","10.244.3.28:4317","10.244.4.19:4317","10.244.5.31:4317"]}

# 2. Мониторинг метрик принятия решений tail_sampling на одном из подов Tier 2
kubectl exec -n observability deploy/jaeger-tier2-core -- curl -s http://127.0.0.1:8888/metrics | grep "processor_tail_sampling"
# → processor_tail_sampling_count_traces_sampled{policy="filter-errors"} 412
# → processor_tail_sampling_count_traces_sampled{policy="filter-latency"} 189
# → processor_tail_sampling_count_traces_sampled{policy="filter-probabilistic"} 3201
# → processor_tail_sampling_count_traces_dropped_total 248900
```

---

## Формулы расчета и Capacity Planning для Tail-Based Sampling

Tail-based сэмплирование требует выделения значительных объемов оперативной памяти на подах Tier 2, так как спаны удерживаются в RAM на протяжении `decision_wait`.

### Формула требуемой оперативной памяти (RAM Sizing):

$$\text{RAM}_{\text{tail}} = \text{Throughput (spans/s)} \times \text{Avg Span Size (bytes)} \times \text{decision\_wait (s)} \times K_{\text{overhead}}$$

Где:
* $\text{Avg Span Size}$ — средний размер спана в памяти процесса (в OTel Collector структуры `pdata` занимают в среднем **1.2–1.8 КБ** на спан с учетом внутренних указателей и слайсов).
* $\text{decision\_wait}$ — время ожидания прихода финального спана (обычно 10–15 секунд).
* $K_{\text{overhead}}$ — коэффициент запаса на хэш-таблицы индексации трейсов и аллокации Go runtime (рекомендуется **1.5**).

#### Пример инженерного расчета:
* Входящий поток: $30\,000$ спанов/с на кластер из 4 реплик Tier 2 ($7\,500$ спанов/с на реплику).
* Средний размер спана в памяти: $1\,500$ байт.
* `decision_wait`: $10$ секунд.
* $\text{RAM}_{\text{node}} = 7\,500 \times 1\,500 \times 10 \times 1.5 = 168\,750\,000\text{ байт} \approx 161\text{ МБ}$ чистого буфера трейсов.
* С учетом пиков трафика (Spike factor $\times 3$) и работы `batch` процессора для реплики Tier 2 минимальный лимит памяти должен составлять **4–8 ГБ RAM**.

---

## Устранение неполадок (Troubleshooting)

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Реплики Tier 2 падают с кодом OOMKilled (Exit Code 137)** | Всплеск трафика переполнил память до истечения `decision_wait`, либо `memory_limiter` отсутствует / стоит после `tail_sampling` | `kubectl describe pod` показывает OOM; метрика `otelcol_processor_memory_limiter_current_usage_mib` достигает лимита cgroup | 1. Переместить `memory_limiter` строго на первое место в списке процессоров.<br>2. Уменьшить `decision_wait` с 30s до 10s.<br>3. Увеличить число реплик Tier 2 в Deployment. |
| **В Jaeger UI отображаются неполные трассы с ошибками (потерян Root Span)** | Трафик на Tier 2 подается через L4 балансировщик (round-robin) без `loadbalancing` экспортера | В логах Tier 2: спаны приходят независимо; трассы в UI не содержат клиентского спана | Проверить конфигурацию Tier 1: убедиться, что используется `loadbalancing` exporter с `routing_key: "traceID"` и DNS-резолвером на Headless Service. |
| **Метрика `processor_tail_sampling_count_traces_dropped` равна нулю** | Ошибка синтаксиса политик или задана политика, захватывающая 100% трафика (например, `probabilistic: 100%`) | Выгрузка метрик: `curl localhost:8888/metrics \| grep processor_tail_sampling` | Проверить логику блока `policies`. Проверить регистр значений статусов (`status_codes: [ERROR]`, а не `error`). |
| **Микросервисы не забирают стратегии сэмплирования (404/500 на порту 5778)** | В Jaeger v2 не включено расширение `remote_sampling` в секции `service.extensions` | `curl -I http://jaeger-collector:5778/api/sampling?service=test` возвращает Connection Refused | Добавить расширение в конфигурацию: `service.extensions: [..., remote_sampling]`, открыть порт 5778 в Service Kubernetes. |
| **Дисбаланс нагрузки между репликами Tier 2** | Неравномерное хэширование TraceID или статическое кэширование DNS в `loadbalancing` экспортере | Мониторинг CPU подов Tier 2 показывает загрузку одного пода на 90%, остальных на 10% | В секции `resolver.dns` уменьшить интервал обновления: добавить `dns: { hostname: ..., timeout: 5s, interval: 5s }`. |

---

## Лучшие практики

1. **Строгая очередность процессоров (Guardrail):** В конвейере Tier 2 порядок процессоров обязан быть следующим:
   ```yaml
   processors: [memory_limiter, tail_sampling, batch]
   ```
   Помещение `batch` перед `tail_sampling` задерживает передачу спанов и ломает расчет `decision_wait`. Помещение `memory_limiter` после любого из них делает защиту от OOM неэффективной.
2. **Гарантированное сэмплирование критических бизнес-транзакций:** В `sampling_strategies.json` всегда настраивайте per-operation правила со 100% сбором для платежных транзакций, списаний средств и вызовов авторизации.
3. **Изоляция трафика проверок жизнеспособности (Liveness/Readiness):** Вызовы `/healthz`, `/readyz`, `/metrics` и сетевые пинги должны отсекаться еще на уровне клиентов (0.001%–0.01% через Remote Sampling), чтобы не нагружать сетевой стек и буферы очередей Tier 1 Gateway.
4. **Оптимальный интервал `decision_wait`:** Для микросервисов с синхронными HTTP/gRPC вызовами оптимальное значение составляет **5–10 секунд**. Увеличение до 30+ секунд допустимо только при наличии асинхронных очередей задач (Celery, Kafka), но требует пропорционального увеличения RAM на нодах хранения.
5. **Запас емкости пула Tier 2:** Рассчитывайте число реплик Tier 2 с коэффициентом запаса $N+2$. При плановом обновлении пода Tier 2 хэш-кольцо `loadbalancing` экспортера временно перестраивается, что вызывает краткосрочный всплеск спанов на оставшихся нодах.

---

## Дополнительная информация

**Смежные материалы в базе знаний:**
* Архитектура и конвейеры Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Анализ узких мест и RED-метрик: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Расчет ресурсов оборудования под объемы трасс: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Отказоустойчивое развертывание: **[High Availability и DR для Jaeger](./jaeger_high_availability.md)**
* Общая спецификация протокола передачи: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**

**Официальная документация:**
* [OpenTelemetry Tail Sampling Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor)
* [OpenTelemetry Load Balancing Exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/loadbalancingexporter)
* [Jaeger Remote Sampling Configuration Guide](https://www.jaegertracing.io/docs/latest/sampling/)
