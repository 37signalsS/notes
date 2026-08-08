# Тестирование и верификация: LGTM Stack и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** (текущий)

---

## Определения

**Автоматическая инструментация** — процесс внедрения механизмов сбора телеметрии (Tracer, Meter, Logger) в среду выполнения приложения без изменения его исходного кода. В Kubernetes реализуется через OpenTelemetry Operator и внедрение Sidecar или Init-контейнеров с агентами. Подробнее: **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Инъекция агента (Injection)** — механизм, при котором OpenTelemetry Operator автоматически добавляет необходимые переменные окружения и библиотеки (например, `opentelemetry-javaagent.jar`) в поды на основе аннотаций.

**Spanmetrics** — механизм генерации метрик (Request, Error, Duration — RED-метод) на основе данных трассировок непосредственно внутри OpenTelemetry Collector.

**Exemplars (Экземпляры)** — метаданные (например, TraceID), прикрепленные к конкретным точкам временных рядов в метриках. Позволяют осуществлять мгновенный переход от графиков (Prometheus) к соответствующим трассировкам (Tempo).

**Корреляция сигналов** — связывание метрик, логов и трассировок через общие идентификаторы (TraceID, SpanID) и атрибуты ресурсов. Подробнее: **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**.

---

## Основные концепции

### Схема взаимодействия компонентов

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Minikube Cluster                             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Pod: agent-example-app                     │   │
│  │                                                         │   │
│  │  ┌─────────────────┐      ┌─────────────────────────┐  │   │
│  │  │  Application    │      │  OTel Java Agent        │  │   │
│  │  │  (Spring Boot)  │◀─────│  (v2.29.0)              │  │   │
│  │  │                 │      │                         │  │   │
│  │  │  /ping endpoint │      │  Auto-instrumentation   │  │   │
│  │  └────────┬────────┘      └─────────────────────────┘  │   │
│  │           │                                             │   │
│  │           │ OTLP/gRPC (Port 4317)                       │   │
│  └───────────┼─────────────────────────────────────────────┘   │
│              │                                                 │
│              ▼                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           OTel Collector (v0.155.0)                     │   │
│  │                                                         │   │
│  │  Receivers: OTLP (gRPC/HTTP)                             │   │
│  │  Processors: batch, spanmetrics, resourcedetection      │   │
│  │  Exporters: Tempo (traces), Loki (logs), Prometheus     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Выбор метода верификации

Для подтверждения работоспособности стека необходимо проверить четыре ключевых аспекта:

1.  **Сквозная доставка (Delivery):** Попадание данных от приложения в соответствующие хранилища (Prometheus, Loki, Tempo).
2.  **Корреляция сигналов (Correlation):**
    *   **Logs -> Traces:** Переход из Loki в Tempo по TraceID.
    *   **Metrics -> Traces:** Переход от точек на графике Prometheus к трейсу Tempo (через **Exemplars**).
    *   **Traces -> Logs:** Поиск логов, относящихся к конкретному спану (через **Traces to Logs**).
3.  **Генерация производных данных (Derived Data):** Наличие RED-метрик, созданных процессором `spanmetrics`.
4.  **Атрибуты ресурсов (Resource Detection):** Наличие метаданных инфраструктуры (pod name, namespace, container name) во всех типах сигналов.

### Ключевые параметры OpenTelemetry Java Agent (v2.x+)

| Переменная | Значение для Minikube | Описание |
| :--- | :--- | :--- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.opentelemetry:4317` | Адрес коллектора в кластере |
| `OTEL_SERVICE_NAME` | `agent-example-app` | Идентификатор сервиса в Tempo/Loki/Prometheus |
| `OTEL_METRICS_EXPORTER` | `otlp` | Протокол для передачи метрик |
| `OTEL_LOGS_EXPORTER` | `otlp` | Протокол для передачи логов (включено в v2.x) |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace=demo` | Дополнительные атрибуты ресурса |

---

## Практические сценарии

### Сценарий 1: Развертывание тестового приложения с автоинструментацией

**Цель:** Запустить приложение и убедиться, что OpenTelemetry Operator успешно внедрил агент.

#### Шаг 1: Сборка и публикация образа

Используется локальный реестр, развернутый на этапе подготовки.

```bash
# Сборка приложения (пример для Spring Boot)
./gradlew bootBuildImage --imageName=registry.test:30000/agent-example-app:latest

# Публикация в локальный реестр
docker push registry.test:30000/agent-example-app:latest
```

#### Шаг 2: Создание ресурса Instrumentation

Перед запуском приложения необходимо создать конфигурацию инструментации в пространстве имен приложения.

```yaml
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
  namespace: default
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.29.0
EOF
```

#### Шаг 3: Запуск приложения с аннотацией

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations='instrumentation.opentelemetry.io/inject-java: "true"'
```

---

### Сценарий 2: Верификация данных в Grafana

**Цель:** Проверить наличие всех типов сигналов и их взаимосвязь.

#### Шаг 1: Генерация нагрузки

```bash
# Проброс порта для доступа к API
kubectl port-forward pod/agent-example-app 8080:8080 &

# Цикл запросов для генерации данных
for i in {1..10}; do curl -s localhost:8080/ping; echo ""; sleep 1; done
```

#### Шаг 2: Проверка корреляции (Logs -> Traces)

1. Откройте Grafana (`http://grafana.test`) -> **Explore**.
2. Выберите источник данных **Loki**.
3. Выполните запрос: `{service_name="agent-example-app"}`.
4. Разверните любую строку лога. В поле `traceID` должна быть активная ссылка.
5. Нажмите на ссылку `traceID` — справа откроется панель с деталями трассировки из **Tempo**.

#### Шаг 3: Проверка корреляции (Metrics -> Traces через Exemplars)

1. В Explore выберите источник данных **Prometheus**.
2. Включите опцию **Exemplars** в интерфейсе запросов.
3. Выполните запрос к метрике, сгенерированной `spanmetrics`: `calls_total{service_name="agent-example-app"}`.
4. На графике должны появиться отдельные точки (**Exemplars**).
5. При наведении на точку появится TraceID. Нажмите на него для перехода к трейсу.

#### Шаг 4: Проверка корреляции (Traces -> Logs)

1. В окне просмотра трассировки (**Tempo**) найдите любой спан.
2. Нажмите на иконку документа или кнопку **Logs for this span**.
3. Grafana автоматически сформирует запрос к Loki с фильтрацией по TraceID и временному интервалу спана.

#### Шаг 5: Верификация атрибутов ресурсов (Resource Detection)

1. В любом сигнале (лог, трейс или метрика) проверьте наличие меток:
   * `k8s.pod.name`
   * `k8s.namespace.name`
   * `k8s.node.name`
2. Наличие этих меток подтверждает, что процессор `resourcedetection` успешно обогатил данные информацией из API Kubernetes.

---

### Сценарий 3: Проверка RED-метрик (Spanmetrics)

**Цель:** Убедиться, что коллектор корректно агрегирует трейсы в метрики производительности.

#### Шаг 1: Запрос метрик в Prometheus

Выполните следующие запросы для проверки RED-метрик (Requests, Errors, Duration):
* **Rate (Requests):** `rate(calls_total{service_name="agent-example-app"}[5m])`
* **Error Rate:** `rate(calls_total{service_name="agent-example-app", status_code="STATUS_CODE_ERROR"}[5m])`
* **Latency (P99):** `histogram_quantile(0.99, sum by (le) (rate(duration_milliseconds_bucket{service_name="agent-example-app"}[5m])))`

---

## Дополнительная информация

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Нет агента в поде** | Ошибка аннотации или Instrumentation | Проверить `kubectl get instrumentation`. Проверить `kubectl describe pod` (секция Init-контейнеров). |
| **Нет Exemplars в Prometheus** | Фича не включена в Prometheus | Проверить наличие `- exemplars` в `enableFeatures` в конфигурации Prometheus. |
| **Нет TraceID в логах** | Неверный формат логов приложения | Убедиться, что используется OTLP логгер и Java Agent v2.x. |
| **Collector: Context deadline exceeded** | Сетевая изоляция | Проверить NetworkPolicies и доступность порта 4317 в пространстве имен `opentelemetry`. |
| **Spanmetrics пустые** | Ошибка в пайплайне коллектора | Проверить `service.pipelines.metrics.processors`, должен содержать `spanmetrics`. |

### Диагностические команды

```bash
# Просмотр логов автоматической инструментации (агента)
kubectl logs agent-example-app -c otel-agent

# Проверка экспорта данных в коллекторе (поиск ошибок экспорта)
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100 | grep -i error

# Проверка наличия эндпоинтов для скрейпинга метрик
kubectl get endpoints -n monitoring
```

### См. также
- **[OpenTelemetry: Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — глубокое погружение в настройку агентов.
- **[Grafana: Визуализация и корреляция](../../../Grafana/grafana_overview.md)** — работа с дашбордами и источниками данных.
- **[Архитектура наблюдаемости: RED-метод](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)** — теоретические основы метрик.

### Связанные материалы SSoT

- **[OpenTelemetry: Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**
- **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**
- **[Grafana: Обзор](../../../Grafana/grafana_overview.md)**

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (назад)

