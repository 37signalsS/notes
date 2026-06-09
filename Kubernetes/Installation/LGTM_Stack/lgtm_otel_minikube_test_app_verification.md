# Тестирование и верификация стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** ← текущий

## Определения

**Автоматическая инструментация** — внедрение OpenTelemetry SDK в приложение без изменения кода (например, через Java Agent). Подробнее: **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Ручная инструментация** — явная настройка SDK и экспортёров через код или переменные окружения. Подробнее: **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Spanmetrics** — метрики (RED-метод), генерируемые из трассировок процессором OpenTelemetry Collector.

---

## Основные концепции

### Архитектура инструментации

```
┌─────────────────────────────────────────────────────────────────┐
│                    Minikube Cluster                             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Pod: agent-example-app                     │   │
│  │                                                         │   │
│  │  ┌─────────────────┐      ┌─────────────────────────┐  │   │
│  │  │  Application    │      │  OTel Java Agent        │  │   │
│  │  │  (Spring Boot)  │◀─────│  (auto-injected)        │  │   │
│  │  │                 │      │                         │  │   │
│  │  │  /ping endpoint │      │  Tracer, Meter, Logger  │  │   │
│  │  └────────┬────────┘      └─────────────────────────┘  │   │
│  │           │                                             │   │
│  │           │ OTLP (gRPC/HTTP)                            │   │
│  └───────────┼─────────────────────────────────────────────┘   │
│              │                                                 │
│              ▼                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           OTel Collector (opentelemetry namespace)      │   │
│  │                                                         │   │
│  │  receivers: otlp/grpc:4317, otlp/http:4318              │   │
│  │  processors: batch, spanmetrics, attributes             │   │
│  │  exporters: otlp→Tempo, loki→Loki, prometheus→Prometheus│   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Сравнение методов инструментации

| Метод | Преимущества | Сценарий |
| :--- | :--- | :--- |
| **Автоматическая** | Не требует изменения кода | Разработка, стандартные фреймворки |
| **Ручная** | Полный контроль над данными | Production, кастомная логика |

### Основные переменные окружения OpenTelemetry

| Переменная | Назначение |
| :--- | :--- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Адрес OpenTelemetry Collector |
| `OTEL_SERVICE_NAME` | Имя сервиса для идентификации |
| `OTEL_LOGS_EXPORTER` | Тип экспортёра логов |
| `OTEL_METRICS_EXPORTER` | Тип экспортёра метрик |
| `OTEL_TRACES_EXPORTER` | Тип экспортёра трассировок |

---

## Практические сценарии

### Сценарий 1: Запуск приложения с автоматической инструментацией

**Цель:** Развернуть приложение с инъекцией агента через Operator.

#### Шаг 1: Подготовка образа

```bash
# Сборка JAR
./gradlew clean bootJar

# Сборка и отправка образа
docker build -t registry.test:30000/agent-example-app:latest .
docker push registry.test:30000/agent-example-app:latest
```

#### Шаг 2: Запуск в Kubernetes

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations='instrumentation.opentelemetry.io/inject-java: "true"' \
  --namespace=default
```

**Аннотация:** `inject-java: "true"` инициирует внедрение агента OpenTelemetry Operator-ом.

---

### Сценарий 2: Верификация телеметрии в Grafana

**Цель:** Проверить корреляцию сигналов в интерфейсе Grafana.

#### Шаг 1: Генерация трафика

```bash
# Проброс порта
kubectl port-forward svc/agent-example-app 8080:8080

# Отправка запросов
curl localhost:8080/ping
```

#### Шаг 2: Анализ данных

Откройте Grafana (<http://grafana.test>) → **Explore**.

1. **Логи (Loki):** Выберите запрос `{service_name="agent-example-app"}`. В логах должен присутствовать `traceID`.
2. **Трассировки (Tempo):** Перейдите по `traceID` из лога для просмотра визуализации пути запроса.
3. **Метрики (Prometheus):** Проверьте метрику `traces_spanmetrics_latency_bucket` для анализа задержек.

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Нет телеметрии** | Collector не получает данные | Проверить логи Collector и endpoint в приложении |
| **Агент не инжектируется** | Ошибка Operator | Проверить статус OpenTelemetry Operator и аннотации |
| **404 в Grafana** | Ошибка Data Source | Проверить URL источников данных в настройках Grafana |

### Диагностика

```bash
# Логи Collector
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector

# Описание пода приложения
kubectl describe pod -l app=agent-example-app
```

### Ссылки на SSoT

- **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)**
- **[Signals Architecture](../../../OpenTelemetry/architecture_signals.md)**
- **[Grafana Overview](../../../Grafana/grafana_overview.md)**
