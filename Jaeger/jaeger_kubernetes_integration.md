# Интеграция Jaeger с Kubernetes

Развертывание Jaeger в Kubernetes упрощается с помощью **Jaeger Operator**, который автоматизирует установку, управление и конфигурацию компонентов Jaeger через Custom Resources (CRD). Это предпочтительный метод для production-окружений.

---

## Определения

*   **Jaeger Operator:** Контроллер Kubernetes, который отслеживает ресурсы `Jaeger` (CRD) и управляет соответствующими объектами (Deployments, Services, DaemonSets и т.д.).
*   **Custom Resource (CR):** Объект `kind: Jaeger`, который описывает желаемое состояние инсталляции Jaeger (например, стратегия `allInOne` или `production`).

---

## Основные концепции

### Паттерны развертывания агента

Существует два основных подхода к развертыванию Jaeger Agent для сбора трассировок с приложений:

1.  **Sidecar:** Агент развертывается как дополнительный контейнер в каждом поде приложения.
    *   **Плюсы:** Простота конфигурации для приложения (всегда отправляет спаны на `localhost`). Изоляция ресурсов.
    *   **Минусы:** Более высокое потребление ресурсов (память, CPU) в масштабе кластера.
    *   **Реализация:** Автоматически управляется Jaeger Operator через аннотацию.

2.  **DaemonSet:** Один экземпляр агента развертывается на каждом узле кластера.
    *   **Плюсы:** Эффективное использование ресурсов (один агент на узел).
    *   **Минусы:** Приложению необходимо знать IP-адрес хоста (`hostIP`) для отправки спанов. Требует `hostPort`.
    *   **Реализация:** Задается в CR `Jaeger` в секции `spec.agent.strategy`.

### Подключение приложений

Приложение должно быть сконфигурировано для отправки трассировок агенту или коллектору.
*   При использовании **Sidecar**-агента, SDK настраивается на отправку данных на `localhost:6831`.
*   При использовании **DaemonSet**-агента, SDK должен использовать `hostIP` пода в качестве адреса.
*   Как альтернатива, приложения могут отправлять данные напрямую в **Collector** через соответствующий Kubernetes Service (например, `jaeger-collector.observability.svc.cluster.local`).

---

## Практические сценарии

### Сценарий 1: Развертывание через Jaeger Operator

#### 1. Установка Operator
Jaeger Operator можно установить с помощью Helm или из OperatorHub.

#### 2. Создание Jaeger Instance
Создайте YAML-файл, описывающий нужную конфигурацию.

**Для разработки (all-in-one):**
```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-dev
spec:
  strategy: allInOne # Все компоненты в одном поде
  storage:
    type: memory
  ingress:
    enabled: true # Автоматически создать Ingress для доступа к UI
```

**Для production:**
```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-prod
spec:
  strategy: production # Раздельные, масштабируемые компоненты
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch-client:9200
  collector:
    replicas: 3
  agent:
    strategy: DaemonSet # Использовать DaemonSet для агентов
```

#### 3. Автоматическое внедрение агента (Sidecar Injection)

Чтобы Operator автоматически добавил sidecar-контейнер с агентом в под вашего приложения, добавьте аннотацию в `metadata` вашего Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        "sidecar.jaegertracing.io/inject": "true"
    spec:
      containers:
      - name: my-app
        image: my-app-image:1.0
        env:
        # SDK будет отправлять спаны на localhost, где их перехватит sidecar-агент
        - name: JAEGER_AGENT_HOST
          value: "localhost"
```

### Сценарий 2: Интеграция с OpenTelemetry Collector

Вместо Jaeger Agent можно использовать OpenTelemetry Collector. Приложение отправляет данные в OTel Collector, который, в свою очередь, экспортирует их в Jaeger Collector.

**Конфигурация приложения:**
```yaml
env:
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector-service:4318" # Адрес сервиса OTel Collector
- name: OTEL_TRACES_EXPORTER
  value: "otlp"
```
Это позволяет использовать единый коллектор для всех сигналов телеметрии (трассировок, метрик, логов).

---

## Дополнительная информация

*   **Сравнение моделей развертывания:** Подробнее см. в [**Вариантах развертывания Jaeger**](./jaeger_deployment_options.md).
*   **Архитектура:** Обзор компонентов Jaeger доступен в [**Архитектуре Jaeger**](./jaeger_architecture.md).
