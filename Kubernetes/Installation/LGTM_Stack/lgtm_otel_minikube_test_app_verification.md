# Тестирование и верификация стека LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** ← текущий

## Определения

**Тестовое приложение** — Java-приложение с инструментацией OpenTelemetry для генерации телеметрии (логи, метрики, трассировки). Используется для верификации работы стека LGTM + OTel.

**Автоматическая инструментация** — процесс внедрения OTel SDK в приложение без изменения кода через Java Agent. OTel Operator автоматически инжектирует агент в Pod при наличии аннотации `instrumentation.opentelemetry.io/inject-java`. Полная документация: **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Ручная инструментация** — явное указание Java Agent через переменную окружения `JAVA_TOOL_OPTIONS` и настройка OTel exporter через переменные `OTEL_*`.

**Spanmetrics** — метрики, сгенерированные из трассировок (RED-метод: Rate, Errors, Duration) процессором spanmetrics в OTel Collector.

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

### Методы инструментации

| Метод | Преимущества | Недостатки | Сценарий |
| :--- | :--- | :--- | :--- |
| **Автоматическая** | Не требует изменения кода, быстрое внедрение | Ограниченная гибкость | Разработка, тестирование |
| **Ручная** | Полный контроль, кастомные атрибуты | Требует изменения кода/конфигурации | Production, специфичная бизнес-логика |

### Переменные окружения OTel

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Endpoint OTel Collector | `http://default-collector.opentelemetry:4317` |
| `OTEL_SERVICE_NAME` | Имя сервиса для телеметрии | `agent-example-app` |
| `OTEL_LOGS_EXPORTER` | Экспортёр логов | `otlp` |
| `OTEL_METRICS_EXPORTER` | Экспортёр метрик | `otlp` |
| `OTEL_TRACES_EXPORTER` | Экспортёр трассировок | `otlp` |
| `JAVA_TOOL_OPTIONS` | Опции JVM для Java Agent | `-javaagent:/path/to/opentelemetry-javaagent.jar` |

---

## Практические сценарии

### Сценарий 1: Запуск приложения с автоматической инструментацией

**Цель:** Развернуть тестовое приложение с автоматической инъекцией OTel Agent через Operator.

#### Шаг 1: Сборка Docker-образа

```bash
# Переход в директорию с примером
cd opentelemetry-java-examples/agent/agent-example-app

# Сборка JAR
./gradlew clean bootJar

# Сборка Docker-образа
docker build -t registry.test:30000/agent-example-app:latest .

# Отправка в локальный Registry
docker push registry.test:30000/agent-example-app:latest
```

#### Шаг 2: Запуск Pod с аннотацией инструментации

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations='instrumentation.opentelemetry.io/inject-java: "true"' \
  --namespace=default
```

**Аннотация:** `instrumentation.opentelemetry.io/inject-java: "true"` указывает OTel Operator внедрить Java Agent в Pod.

#### Шаг 3: Проверка статуса Pod

```bash
# Проверка Pod
kubectl get pods -l app=agent-example-app

# Проверка инъекции агента
kubectl describe pod -l app=agent-example-app | grep -A 5 "OTEL"
```

**Ожидаемый результат:** Pod в статусе `Running`, переменные окружения OTel установлены.

---

### Сценарий 2: Запуск приложения с ручной инструментацией

**Цель:** Развернуть приложение с явным указанием Java Agent (без Operator).

#### Шаг 1: Сборка образа без встроенного агента

```bash
cd opentelemetry-java-examples/agent/agent-example-app

# Убедитесь, что Dockerfile не содержит opentelemetry-javaagent.jar
docker build -t registry.test:30000/agent-example-app-no-agent:latest .
docker push registry.test:30000/agent-example-app-no-agent:latest
```

#### Шаг 2: Запуск Pod с явным указанием агента

```bash
kubectl run agent-example-app-manual \
  --image=registry.test:30000/agent-example-app-no-agent:latest \
  --port=8080 \
  --labels="app=agent-example-app-manual" \
  --env="JAVA_TOOL_OPTIONS=-javaagent:/path/to/opentelemetry-javaagent.jar" \
  --env="OTEL_EXPORTER_OTLP_ENDPOINT=http://default-collector.opentelemetry:4317" \
  --env="OTEL_LOGS_EXPORTER=otlp" \
  --env="OTEL_SERVICE_NAME=agent-example-app-manual" \
  --namespace=default
```

> **Примечание:** Этот метод требует, чтобы JAR-файл агента был доступен в контейнере (через `initContainer` или встраивание в образ).

---

### Сценарий 3: Верификация телеметрии

**Цель:** Проверить сбор логов, метрик и трассировок в Grafana.

#### Шаг 1: Проброс порта к Pod

```bash
kubectl port-forward pod/$(kubectl get pods -l app=agent-example-app -o jsonpath='{.items[0].metadata.name}') \
  8080:8080 \
  --namespace=default
```

#### Шаг 2: Генерация нагрузки

```bash
# Генерация тестовых запросов
curl localhost:8080/ping
curl localhost:8080/endpoint1
curl localhost:8080/endpoint2
```

#### Шаг 3: Проверка в Grafana

Откройте Grafana (<http://grafana.test>) и перейдите в раздел **Explore**.

**Логи (Loki):**

1. Выберите Data Source `Loki`
2. Используйте запрос: `{service_name="agent-example-app"}`
3. Вы увидите логи приложения с метаданными

**Трассировки (Tempo):**

1. В логах найдите поле `traceID`
2. Кликните по ссылке для перехода в Tempo
3. Вы увидите полную трассировку запроса с деталями спанов

**Метрики (Prometheus):**

1. Выберите Data Source `Prometheus`
2. Используйте запрос: `traces_spanmetrics_latency_bucket{service_name="agent-example-app"}`
3. Вы увидите метрики задержек, сгенерированные из спанов

---

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Pod в статусе Pending** | Недостаточно ресурсов | Проверить `kubectl describe pod`, увеличить ресурсы Minikube |
| **Нет телеметрии в Grafana** | Collector не получает данные | Проверить логи Collector: `kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector` |
| **Агент не инжектируется** | Operator не работает | Проверить `kubectl get pods -n opentelemetry-operator`, аннотацию Pod |
| **Ошибка подключения к Collector** | Неправильный endpoint | Проверить сервис: `kubectl get svc -n opentelemetry` |
| **404 в Grafana** | Data source не настроен | Проверить конфигурацию kube-prometheus-stack |

### Диагностика

```bash
# Проверка Pod и событий
kubectl get pods -l app=agent-example-app
kubectl describe pod -l app=agent-example-app

# Логи приложения
kubectl logs -l app=agent-example-app

# Проверка Collector
kubectl get otelcol -n opentelemetry
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector

# Проверка сервисов
kubectl get svc -n opentelemetry
kubectl get svc -n loki
kubectl get svc -n tempo

# Тестирование endpoints
curl -k https://loki.test/loki/api/v1/labels
curl http://tempo.tempo:3200/ready
```

### Ссылки на SSoT

- **[Instrumentation SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — автоматическая и ручная инструментация
- **[OTel Architecture](../../../OpenTelemetry/architecture_signals.md)** — сигналы и архитектура
- **[Grafana overview](../../../Grafana/grafana_overview.md)** — визуализация телеметрии
- **[Loki overview](../../../Loki/loki_overview.md)** — сбор логов
- **[Tempo overview](../../../Tempo/index.md)** — хранение трассировок

### Ресурсы

- **[OpenTelemetry Java Examples](https://github.com/open-telemetry/opentelemetry-java-examples)**
- **[OTel Operator Documentation](https://opentelemetry-operator.readthedocs.io/)**
- **[Grafana Explore](https://grafana.com/docs/grafana/latest/explore/)**

---

**Навигация по руководству:**

- **[← Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
