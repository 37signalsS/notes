# OpenTelemetry: Продвинутое сэмплирование

## Определения

**Продвинутое сэмплирование (Advanced Sampling)** — это комплексные стратегии отбора трассировок для снижения объёма данных при сохранении репрезентативной картины. Включает tail-based sampling, комбинированные подходы и кастомные правила.

В 2026 году продвинутое сэмплирование является стандартом для production-развёртывания OTel.

## Теоретический блок

### Типы сэмплирования

| Тип | Решение | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Head-based** | В SDK до завершения трейса | Простое, быстрое | Не учитывает ошибки и задержки |
| **Tail-based** | После получения span-ов | Учитывает ошибки и задержки | Требует памяти и состояния |
| **Комбинированный** | Head + Tail | Баланс простоты и точности | Сложная конфигурация |

### Архитектура tail-based sampling

```text
Приложение → SDK (head-based) → Collector Agent → Collector Gateway (tail-based) → Backend
                                        ↓
                                   groupbytrace processor
                                        ↓
                                   sampling decisions
```

### Ключевые компоненты

1. **groupbytrace** — группирует span-ы по trace ID для принятия решений.
2. **tail_sampling** — применяет правила к сгруппированным трейсам.
3. **Балансировка по trace ID** — направляет все span-ы одного трейса на один экземпляр Gateway.

## Практические сценарии

### Сценарий 1: Tail-based sampling на Gateway

**Конфигурация Collector Gateway:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  groupbytrace:
    wait_duration: 5s
    num_traces: 1000

  tail_sampling:
    decision_wait: 10s
    num_traces: 1000
    policies:
      # Сохранять все трейсы с ошибками
      - name: errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      
      # Сохранять медленные трейсы (>1s)
      - name: slow
        type: latency
        latency: {threshold_ms: 1000}
      
      # Сохранять 10% всех трейсов
      - name: probabilistic
        type: probabilistic
        probabilistic: {sampling_percentage: 10}
      
      # Сохранять трейсы определенных сервисов
      - name: critical-services
        type: string_attribute
        string_attribute: {key: service.name, values: [payment-api, order-service]}

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [groupbytrace, tail_sampling]
      exporters: [otlp/tempo]
```

### Сценарий 2: Комбинированный подход

**Head-based sampling в SDK:**

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import (
    TraceIdRatioBased,
    ParentBased,
)

# Сохранять 50% трейсов на уровне SDK
sampler = ParentBased(TraceIdRatioBased(0.5))
provider = TracerProvider(sampler=sampler)
```

**Tail-based sampling на Gateway:**

```yaml
processors:
  tail_sampling:
    policies:
      # Сохранять 100% ошибок
      - name: errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      
      # Сохранять 100% медленных
      - name: slow
        type: latency
        latency: {threshold_ms: 1000}
      
      # Сохранять 10% остальных
      - name: probabilistic
        type: probabilistic
        probabilistic: {sampling_percentage: 10}
```

### Сценарий 3: Кастомные правила сэмплирования

**Сэмплирование по атрибутам:**

```yaml
processors:
  tail_sampling:
    policies:
      # Сохранять трейсы с определенными атрибутами
      - name: high-value-transactions
        type: string_attribute
        string_attribute:
          key: transaction.type
          values: ["purchase", "refund"]
      
      # Сохранять трейсы определенных HTTP методов
      - name: write-operations
        type: string_attribute
        string_attribute:
          key: http.method
          values: ["POST", "PUT", "DELETE"]
      
      # Сохранять трейсы с определенными status codes
      - name: client-errors
        type: status_code
        status_code: {status_codes: [CLIENT_ERROR]}
```

### Сценарий 4: Балансировка по trace ID

**Настройка балансировки в Kubernetes:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: otel-collector-gateway
spec:
  selector:
    app: otel-collector-gateway
  ports:
    - port: 4317
      targetPort: 4317
  sessionAffinity: None
```

**Конфигурация Collector Agent для маршрутизации:**

```yaml
# Collector Agent (DaemonSet)
exporters:
  loadbalancing:
    protocol:
      otlp:
        timeout: 10s
        tls:
          insecure: true
    resolver:
      dns:
        hostname: otel-collector-gateway
        port: 4317
    resolver:
      static:
        hostnames:
          - otel-collector-gateway-1
          - otel-collector-gateway-2
          - otel-collector-gateway-3

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [loadbalancing]
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Трейсы разорваны** | span-ы попадают на разные экземпляры Gateway | Настроить балансировку по trace ID |
| **Высокое потребление памяти** | Слишком много трейсов в tail-based | Уменьшить `num_traces`, увеличить `decision_wait` |
| **Потеря важных трейсов** | Неправильные правила сэмплирования | Проверить политики, протестировать на staging |
| **Медленная обработка** | Сложные правила сэмплирования | Упростить политики, увеличить ресурсы Gateway |

### Best Practices

1. **Начинайте с простых правил** — постепенно усложняйте.
2. **Тестируйте на staging** — проверяйте правила перед продакшеном.
3. **Мониторьте результаты** — отслеживайте количество сохраненных трейсов.
4. **Используйте комбинированный подход** — баланс head и tail-based.
5. **Документируйте правила** — фиксируйте логику сэмплирования.

### Ссылки

- [OTel Collector Sampling](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor)
- [Tail-based Sampling](https://opentelemetry.io/docs/collector/configuration/#tail-sampling)
- [Sampling Strategies](https://www.jaegertracing.io/docs/latest/sampling/)
