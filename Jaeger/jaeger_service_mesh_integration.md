# Интеграция Jaeger с Service Mesh

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

**Интеграция Jaeger с Service Mesh** — это процесс настройки распределенной трассировки в средах с Istio, Linkerd или Cilium. Service Mesh автоматически генерирует спаны для межсервисных вызовов, но требует согласованности форматов пропагации контекста, конфигурации телеметрии и предотвращения конфликтов между спанами, сгенерированными mesh и приложением. В 2026 году стандартом является W3C Trace Context, поддержка Ambient Mesh и автоматическая коррекция атрибутов через Envoy.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Интеграция с Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Service Mesh** | Инфраструктурный слой (Istio, Linkerd, Cilium), управляющий сетевыми взаимодействиями, безопасностью и наблюдаемостью микросервисов |
| **Sidecar Proxy** | Прокси (Envoy для Istio), внедряемый в под приложения для перехвата трафика |
| **Ambient Mesh** | Архитектура Istio без sidecar: трафик обрабатывается CNI-плагином и ztunnel на уровне узла |
| **Telemetry API** | Kubernetes CRD (`Telemetry`, `Tracing`) для конфигурации сбора телеметрии в Istio |
| **Trace Context Propagation** | Механизм передачи `trace_id`/`span_id` между сервисами через HTTP-заголовки |
| **W3C Trace Context** | Отраслевой стандарт (`traceparent`, `tracestate`) по умолчанию для Jaeger v2 и OTel |
| **B3 Propagation** | Исторический формат Zipkin (`X-B3-TraceId`, `X-B3-SpanId`), поддерживаемый для обратной совместимости |
| **Envoy Span Generation** | Автоматическое создание спанов Envoy для входящих/исходящих HTTP- и TCP-соединений |
| **Ztunnel** | Компонент Istio Ambient Mesh, работающий на уровне узла для L4 трассировки без sidecar |

---

## Базовые концепции

### Архитектура трассировки в Service Mesh

```
┌─────────────┐     HTTP      ┌─────────────┐     HTTP      ┌─────────────┐
│   Client    │──────────────▶│   Sidecar   │──────────────▶│   Server    │
│             │               │   (Envoy)   │               │             │
└─────────────┘               └──────┬──────┘               └──────┬──────┘
                                    │                            │
                             Спан client                   Спан server
                             (Envoy auto)                  (Envoy auto)
```

В mesh-среде трейс строится из трех типов спанов:
1. **App spans:** Генерируются кодом приложения через OTel SDK.
2. **Mesh spans:** Генерируются sidecar-прокси (Envoy) автоматически.
3. **Infrastructure spans:** Генерируются инфраструктурными компонентами (gateway, ztunnel).

### Сравнение Sidecar vs Ambient

| Критерий | Sidecar (Istio) | Ambient (Istio) |
| :--- | :--- | :--- |
| **Архитектура** | Envoy в каждом поде | Ztunnel на узле + CNI |
| **Спаны** | Envoy генерирует спаны для HTTP/gRPC | Ztunnel генерирует спаны только для TCP/METRICS |
| **Производительность** | Оверхead 5-10% CPU/RAM на под | Нулевой overhead для приложения |
| **Гибкость** | Полный контроль над Envoy конфигурацией | Ограниченная конфигурация (Istio API) |
| **Sentry spans** | Да (с полными атрибутами) | Нет (только connection-level) |

### Форматы пропагации контекста

| Формат | Заголовки | Использование |
| :--- | :--- | :--- |
| **W3C Trace Context** | `traceparent`, `tracestate` | Стандарт по умолчанию для Jaeger v2 и OpenTelemetry |
| **B3 (Zipkin)** | `X-B3-TraceId`, `X-B3-SpanId`, `X-B3-Sampled` | Исторически использовался в Istio < 1.20 |
| **Jaeger Thrift** | `uber-trace-id` | Устарел, не рекомендуется |

**Важно:** Jaeger v2 может принимать B3 и конвертировать его в W3C для внутреннего хранения, но рекомендуется перевести mesh на нативный W3C.

### Атрибуты, добавляемые Envoy

Envoy автоматически добавляет в спаны следующие атрибуты:

| Атрибут | Описание |
| :--- | :--- |
| `http.method` | HTTP-метод запроса |
| `http.url` | Полный URL запроса |
| `http.status_code` | Код ответа |
| `http.host` | Хост из заголовка Host |
| `grpc.status_code` | Статус gRPC |
| `net.peer.ip` | IP адрес клиента/сервера |
| `k8s.namespace.name` | Неймспейс пода (через k8sattributes) |
| `k8s.pod.name` | Имя пода |

---

## Практические сценарии

### Сценарий 1: Настройка трассировки в Istio (Sidecar)

**Ситуация:** Нужно включить распределенную трассировку для namespace `production` в Istio.

```yaml
# tracing.yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: mesh-default
  namespace: istio-system
spec:
  tracing:
    - providers:
        - name: otel
      randomSamplingPercentage: 10
      customTags:
        environment:
          environment:
            value: "production"
        service_version:
          header:
            name: "x-service-version"
```

**Настройка EnvoyFilter для W3C:**

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: trace-context-propagation
  namespace: istio-system
spec:
  workloadSelector:
    labels:
      istio: sidecar-injector
  configPatches:
    - applyTo: HTTP_FILTER
      match:
        context: SIDECAR_INBOUND
        listener:
          filterChain:
            filter:
              name: envoy.filters.network.http_connection_manager
      patch:
        operation: MERGE
        value:
          name: envoy.filters.http.trace
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.http.trace.v3.Trace
            provider:
              - name: otel
                tracer:
                  typed_config:
                    "@type": type.googleapis.com/opentelemetry.io.collector.trace.proto.TraceConfig
                    service_name: "istio-proxy"
```

**Валидация:**

1. Применить конфигурацию: `kubectl apply -f tracing.yaml`.
2. Отправить запрос через service mesh: `curl -X GET http://my-app.production.svc:8080/api`.
3. Проверить в Jaeger UI наличие трейса с двумя спанами: `istio-proxy` (client) и `my-app` (server).
4. Убедиться, что `traceparent` заголовок корректно передается между сервисами.

### Сценарий 2: Настройка Ambient Mesh (ztunnel) tracing

**Ситуация:** Нужно включить трассировку в Ambient Mesh без sidecar-контейнеров.

```yaml
# ambient-tracing.yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: ambient-default
  namespace: istio-system
spec:
  tracing:
    - providers:
        - name: otel
      randomSamplingPercentage: 5
      target:
        - meshes:
            meshName: default
```

**Ограничения Ambient Mesh:**

- Ztunnel генерирует спаны только для TCP/METRICS, но не для HTTP-атрибутов.
- Для детальных HTTP-спанов требуется Standalone Sidecar или приложение с OTel SDK.
- Отсутствует возможность кастомизации атрибутов на уровне EnvoyFilter.

**Валидация:**

1. Применить конфигурацию: `kubectl apply -f ambient-tracing.yaml`.
2. Отправить запрос: `curl -X GET http://my-app.production.svc:8080/api`.
3. В Jaeger UI найти трейс с span `ztunnel` (connection-level).

### Сценарий 3: Предотвращение дублирования спанов

**Сиituaция:** При использовании Istio sidecar и OTel SDK в приложении трейсы дублируются: создаются два спана для одного и того же вызова (один Envoy, один SDK).

**Решение 1: Отключение Envoy tracing для приложения**

```yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: disable-envoy-tracing
  namespace: my-app
spec:
  tracing:
    - providers:
        - name: otel
      disableSpanReporting: true
      target:
        - workloads:
            labels:
              app: my-app
```

**Решение 2: Использование SpanProcessor для фильтрации**

```yaml
# collector-config.yaml
processors:
  filter:
    traces:
      span:
        - 'span.kind != server'  # Отфильтровать серверные спаны от Envoy, оставить только клиентские
```

**Валидация:**

1. Отправить запрос: `curl -X GET http://my-app.production.svc:8080/api`.
2. В Jaeger UI убедиться, что для каждого вызова создается ровно один спан (либо от Envoy, либо от SDK).

### Сценарий 4: Конфигурация B3 → W3C конвертера

**Ситуация:** Некоторые сервисы еще отправляют спаны в формате B3, необходимо конвертировать их в W3C.

```yaml
# collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  transform:
    traces:
      span_mappings:
        - source: 'attributes["http.b3.traceid"]'
          target: 'trace_id'
        - source: 'attributes["http.b3.spanid"]'
          target: 'span_id'

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_v2

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [transform, batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация:**

1. Отправить запрос с B3 заголовками: `curl -H "X-B3-TraceId: 1234567890" http://my-app:8080/api`.
2. В Jaeger UI убедиться, что трейс сохранен с корректным `trace_id` в W3C формате.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Разорванные трейсы** | Envoy не пропускает `traceparent` или используется B3 в mesh и W3C в приложении | Единый формат: W3C Trace Context. Проверить `meshConfig.defaultConfig.tracing` |
| **Дублирование спанов** | Sidecar и SDK создают спаны для одного и того же вызова | Отключить `span_reporting` в Telemetry API для workloads с SDK |
| **Отсутствие атрибутов k8s** | `k8sattributes` processor не настроен или RBAC недостаточный | Добавить права `get`, `watch`, `list` на `pods`, `nodes`, `namespaces` |
| **Ztunnel не генерирует спаны** | Ambient Mesh не поддерживает HTTP-атрибуты в спанах | Использовать Standalone Sidecar для HTTP-трассировки или добавить OTel SDK в приложение |
| **Clock Skew в mesh** | Разная синхронизация времени между sidecar и приложением | Настроить NTP/chrony на всех узлах |

---

## Лучшие практики

1.  **Используйте W3C Trace Context:** Это стандарт по умолчанию для Jaeger v2 и OpenTelemetry. Откажитесь от B3.
2.  **Sidecar для HTTP, Ambient для TCP:** Если нужны детальные HTTP-спаны с атрибутами, используйте Sidecar. Для базовой L4 трассировки — Ambient.
3.  **Избегайте дублирования:** Если приложение инструментировано OTel SDK, отключите Envoy span reporting для данного workload.
4.  **Согласуйте sampling между mesh и приложением:** Используйте один и тот же `samplingPercentage` в Telemetry API и OTel SDK.
5.  **k8sattributes повсеместно:** Добавляйте метаданные Kubernetes (pod, namespace, node) на уровне Collector, а не только Envoy.

---

## Очистка окружения

```bash
# Удаление ресурсов Istio Telemetry
kubectl delete telemetry mesh-default -n istio-system
kubectl delete telemetry ambient-default -n istio-system
kubectl delete telemetry disable-envoy-tracing -n my-app

# Удаление EnvoyFilter
kubectl delete envoyfilter trace-context-propagation -n istio-system

# Удаление тестовых неймспейсов
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Конфигурация OpenTelemetry Operator: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* k8sattributes processor: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Контекстная пропагация: **[Обзор Jaeger](./jaeger_overview.md)**
* Service Mesh концепции: **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)**
* Наблюдаемость в Istio: **[Наблюдаемость в Istio: Kiali, телеметрия и федерация идентичности](../Service_Mesh/istio_observability_and_tools.md)**

### См. также

* [Istio Telemetry API Documentation](https://istio.io/latest/docs/reference/config/istio.mesh.v1alpha1/#Telemetry)
* [OpenTelemetry and Istio Tracing](https://istio.io/latest/docs/ops/integrations/opentelemetry/)
