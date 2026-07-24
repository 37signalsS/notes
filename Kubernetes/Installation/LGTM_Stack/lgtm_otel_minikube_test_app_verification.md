# Тестирование и верификация: LGTM Stack и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** 

---

## Определения

**Автоматическая инструментация** — процесс внедрения механизмов сбора телеметрии (Tracer, Meter, Logger) в среду выполнения приложения без изменения его исходного кода. В Kubernetes реализуется через OpenTelemetry Operator и внедрение Sidecar или Init-контейнеров с агентами. Подробнее: **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Инъекция агента (Injection)** — механизм, при котором OpenTelemetry Operator автоматически добавляет необходимые переменные окружения и библиотеки (например, `opentelemetry-javaagent.jar`) в поды на основе аннотаций.

**Spanmetrics** — механизм генерации метрик (Request, Error, Duration — RED-метод) на основе данных трассировок непосредственно внутри OpenTelemetry Collector.

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

Для подтверждения работоспособности стека необходимо проверить три ключевых аспекта:
1. **Сквозная доставка (Delivery):** Попадание данных от приложения в соответствующие хранилища.
2. **Корреляция (Correlation):** Возможность перехода между сигналами в Grafana (из лога в трейс по TraceID).
3. **Генерация производных данных (Derived Data):** Наличие RED-метрик, созданных процессором `spanmetrics`.

### Ключевые параметры OpenTelemetry Java Agent (v2.x+)

| Переменная | Значение для Minikube | Описание |
| :--- | :--- | :--- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.opentelemetry:4317` | Адрес коллектора в кластере |
| `OTEL_SERVICE_NAME` | `agent-example-app` | Идентификатор сервиса в Tempo/Loki |
| `OTEL_METRICS_EXPORTER` | `otlp` | Протокол для передачи метрик |
| `OTEL_LOGS_EXPORTER` | `otlp` | Протокол для передачи логов (начиная с v2.0) |

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

#### Шаг 2: Проверка трассировок и логов (Loki -> Tempo)

1. Откройте Grafana (`http://grafana.test`) -> **Explore**.
2. Выберите источник данных **Loki**.
3. Выполните запрос: `{service_name="agent-example-app"}`.
4. Разверните любую строку лога. В поле `traceID` должна быть активная ссылка (благодаря настройке `derivedFields`).
5. Нажмите на ссылку `traceID` — откроется панель с трассировкой из **Tempo**.

#### Шаг 3: Проверка Spanmetrics (Prometheus)

1. Переключите источник данных на **Prometheus**.
2. Найдите метрику `calls_total` или `duration_milliseconds_bucket`.
3. Убедитесь, что в метках присутствует `service_name="agent-example-app"`. Эти метрики были сгенерированы коллектором из трейсов.

---

## Дополнительная информация

### Устранение неисправностей

| Проблема | Вероятная причина | Диагностика |
| :--- | :--- | :--- |
| **Нет агента в поде** | Operator не видит аннотацию или Instrumentation | `kubectl describe pod agent-example-app` (проверить наличие init-контейнера) |
| **Collector: Context deadline exceeded** | Проблема сетевой связности | `kubectl exec` в под приложения и проверить доступность порта 4317 коллектора |
| **В логах нет TraceID** | Старая версия логгера или SDK | Проверить версию Java Agent (требуется 2.x для нативной поддержки логов) |
| **Spanmetrics пустые** | Трассировки не доходят до процессора | Проверить `receivers` и `service.pipelines` в конфиге Collector |

### Диагностические команды

```bash
# Просмотр логов автоматической инструментации (агента)
kubectl logs agent-example-app -c otel-agent

# Проверка экспорта данных в коллекторе
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100
```

### Связанные материалы SSoT

- **[OpenTelemetry: Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — подробнее о настройке агентов.
- **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)** — подробнее о корреляции.
- **[Grafana: Обзор](../../../Grafana/grafana_overview.md)** — работа с визуализацией.

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (назад)

