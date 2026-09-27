# Развертывание OpenTelemetry в Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (текущий)
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Назначение документа

Документ описывает развертывание и настройку компонентов OpenTelemetry в кластере Minikube для сбора, обработки и экспорта телеметрии (метрик, логов и трассировок) в стек LGTM.

- **Что разворачивается:** OpenTelemetry Operator v0.158.0 (chart v0.122.0), OTel Collector v0.158.0 (chart v0.172.0, app v0.159.0), ресурс `Instrumentation` для Java-приложений с автоинструментацией v2.30.0.
- **Что НЕ описывается:** настройка приложений (см. **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**), развертывание стека LGTM (см. **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**), production-конфигурация (см. раздел «Безопасность и Production» ниже).

---

## Предварительные требования

До развертывания OpenTelemetry Operator и Collector убедитесь в выполнении следующих условий:

1. **Minikube запущен** с ресурсами не менее 4 CPU и 8 ГБ RAM (рекомендуется 6 CPU / 12 ГБ RAM). Подробнее: **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)**.
2. **cert-manager установлен** и работает (необходим для webhook оператора). Проверка:

   ```bash
   kubectl get pods -n cert-manager
   # → Expected: cert-manager-*, cert-manager-cainjector-*, cert-manager-webhook-* в статусе Running
   ```

3. **Helm 3.x установлен** и репозиторий `open-telemetry` добавлен. Проверка:

   ```bash
   helm repo list | grep open-telemetry
   # → Expected: open-telemetry  https://open-telemetry.github.io/opentelemetry-helm-charts
   ```

4. **kubectl подключен** к кластеру Minikube. Проверка:

   ```bash
   kubectl cluster-info
   # → Expected: Kubernetes control plane is running at https://192.168.49.2:8443
   ```

5. **Стек LGTM развернут** (Prometheus, Loki, Tempo) и доступен по DNS-именам в кластере. Проверка:

   ```bash
   kubectl get svc -n monitoring prometheus-operated
   kubectl get svc -n loki loki
   kubectl get svc -n tempo tempo
   ```

---

## Определения

**OpenTelemetry (OTel)** — открытый стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных (метрик, логов и трассировок). Подробнее: **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**.

**OpenTelemetry Operator** — Kubernetes-контроллер, автоматизирующий управление жизненным циклом OTel Collector и процессом инструментации приложений. Управляет ресурсами через CRD `OpenTelemetryCollector` и `Instrumentation`.

**OTel Collector** — центральный компонент для обработки данных, работающий по принципу конвейера (Receivers -> Processors -> Exporters -> Extensions). Подробнее: **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**.

**Автоматическая инструментация** — механизм внедрения OTel SDK в среду выполнения приложения (например, через Java Agent) без изменения исходного кода. Подробнее: **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**OTLP (OpenTelemetry Line Protocol)** — универсальный протокол передачи телеметрии, используемый для взаимодействия всех компонентов OTel. Подробнее: **[Протокол OTLP](../../../OpenTelemetry/otlp_protocol.md)**.

**Resource** — стандартизированный набор атрибутов (Resource Attributes), описывающий источник телеметрии: `service.name`, `service.version`, `k8s.pod.name`, `k8s.namespace.name` и т. д. Resource проставляется один раз и далее используется во всех сигналах (traces/metrics/logs), что позволяет объединять данные одного пода на дашбордах.

**Конвейер (Pipeline)** — описание маршрута обработки одного типа сигнала (traces/metrics/logs) от получения до экспорта. Pipeline объединяет `receivers`, `processors` и `exporters` в секции `service.pipelines`.

**Sampler** — компонент, решающий, какие трейсы сохранять (head-based — на стороне SDK по вероятности; tail-based — на стороне Collector после анализа полного трейса).

**Mutating Webhook** — механизм Kubernetes API, через который OpenTelemetry Operator автоматически модифицирует манифесты подов при их создании, добавляя init-контейнеры и переменные окружения для автоинструментации.

---

## Основные концепции

### Архитектура OpenTelemetry в кластере Minikube

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                            │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────────────────────┐   │
│  │   Приложение    │     │   OpenTelemetry Operator        │   │
│  │   (Java/OTel)   │     │   (v0.158.0)                    │   │
│  │                 │     │                                 │   │
│  │  ┌───────────┐  │     │  ┌───────────────────────────┐  │   │
│  │  │ OTel SDK  │──┼─────┼─▶│  OpenTelemetryCollector   │  │   │
│  │  └───────────┘  │OTLP │  │  (v0.158.0)               │  │   │
│  └─────────────────┘     │  └─────────────┬─────────────┘  │   │
│                          │                │                 │   │
│                          │  ┌─────────────▼─────────────┐  │   │
│                          │  │    Instrumentation CRD    │  │   │
│                          │  │  (Auto-instrumentation)   │  │   │
│                          │  └───────────────────────────┘  │   │
│                          └─────────────────────────────────┘   │
│                                           │                     │
│                    ┌──────────────────────┼──────────────────┐ │
│                    │                      │                  │ │
│                    ▼                      ▼                  ▼ │
│            ┌──────────────┐      ┌──────────────┐   ┌────────┐│
│            │    Tempo     │      │   Loki       │   │Prometheus│
│            │  (traces)    │      │   (logs)     │   │(metrics)│
│            │  :4317       │      │  :3100       │   │ :9090  │
│            └──────────────┘      └──────────────┘   └────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Поток данных:

1. Приложение (или его init-контейнер с агентом) формирует сигналы через OTel SDK и отправляет их по OTLP/gRPC (порт 4317) или OTLP/HTTP (порт 4318) в Collector.
2. Collector применяет конвейеры: enrich (`resourcedetection`, `k8sattributes`), sampler (`tail_sampling`), batch, и отправляет данные в соответствующие backend-системы.
3. Tempo хранит трейсы, Loki — логи, Prometheus — метрики. Grafana объединяет все три сигнала через корреляцию по `trace_id` и `service.name`.

### Топологии развертывания Collector

| Топология | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Deployment (один экземпляр)** | Один под, обрабатывающий все сигналы кластера | Minikube / dev-окружение |
| **Deployment (несколько реплик)** | Несколько подов за LoadBalancer Service | Средние production-кластеры |
| **Agent (DaemonSet) + Gateway (Deployment)** | DaemonSet собирает данные на каждом узле, Gateway агрегирует и экспортирует | Большие production-кластеры, экономия трафика и отказоустойчивость |
| **Sidecar (в каждом поде)** | Collector как sidecar-контейнер рядом с приложением | Строгая изоляция tenant-данных, Istio Ambient без ztunnel |

> **Примечание:** В данном руководстве используется топология `Deployment` с одной репликой. Топология `Agent + Gateway` рассмотрена в сценарии 8 как production-рекомендация.

### Компоненты Collector

| Группа | Назначение | Используемые в Minikube |
| :--- | :--- | :--- |
| **Receivers** | Прием входящих данных | `otlp` (gRPC/HTTP), `prometheus` (scrape приложений), `filelog` (хост-логи) |
| **Processors** | Преобразование и фильтрация | `batch`, `memory_limiter`, `resourcedetection`, `k8sattributes`, `spanmetrics`, `tail_sampling`, `attributes`, `resource` |
| **Exporters** | Отправка в системы хранения | `otlp` (Tempo), `loki`, `prometheus` (self-monitoring), `debug` (отладка) |
| **Extensions** | Дополнительные сервисы (не участвуют в pipeline) | `health_check`, `pprof`, `zpages`, `bearertokenauth` |

### CRD OpenTelemetry Operator

| CRD | Назначение | Версия API |
| :--- | :--- | :--- |
| `opentelemetrycollectors.opentelemetry.io` | Описывает развертывание и конфигурацию OTel Collector | `v1alpha1` (стабильная для большинства полей), `v1beta1` (новая, введена в Operator v0.110.0, рекомендуется для новых развертываний) |
| `instrumentations.opentelemetry.io` | Описывает настройки автоинструментации для конкретного языка | `v1alpha1` |
| `targetallocators.opentelemetry.io` | Управляет Target Allocator для Prometheus ServiceMonitors | `v1alpha1` |

> **Важно:** Начиная с Operator v0.110.0, `v1beta1` для `OpenTelemetryCollector` считается предпочтительной. Поле `spec.config` остается обратно совместимым между версиями API. В данном руководстве используется `v1alpha1` для совместимости с широким набором диаграмм и документации.

### Ресурсные профили (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) | Примечание |
| :--- | :--- | :--- | :--- |
| **OTel Operator** | 100m / 500m | 128Mi / 512Mi | Включает webhook-сервер |
| **OTel Collector** | 100m / 500m | 256Mi / 1024Mi | Основной конвейер обработки |
| **Java Agent** (init-контейнер) | 50m / 200m (на Pod) | 128Mi / 512Mi (на Pod) | Автоматическая инструментация |

> **Примечание:** В Minikube используется один экземпляр Collector (Deployment). Для production рекомендуется топология Agent (DaemonSet) + Gateway (Deployment) для разделения нагрузки и отказоустойчивости.

### Жизненный цикл OpenTelemetryCollector

1. Пользователь применяет манифест `kind: OpenTelemetryCollector`.
2. OpenTelemetry Operator создает Deployment/StatefulSet/DaemonSet, ConfigMap с конфигурацией, ServiceAccount, Service, ServiceMonitor (если включено).
3. Operator следит за состоянием подов и обновляет `status.scale.replicas`, `status.image`, `status.conditions` (тип `Available`, `Progressing`, `Degraded`).
4. При изменении `spec.config` или `spec.image` Operator выполняет rolling update подов.
5. При удалении CR Operator каскадно удаляет все созданные ресурсы.

---

## Практические сценарии

### Сценарий 1: Установка OpenTelemetry Operator

**Цель:** Подготовить кластер к управлению ресурсами OpenTelemetry.

#### Шаг 1: Добавление репозитория Helm

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
# → Expected: "... has been added to your repositories"
```

#### Шаг 2: Установка оператора

Актуальные версии на сентябрь 2026 г.:

| Компонент | Версия | Источник |
| :--- | :--- | :--- |
| Chart `opentelemetry-operator` | 0.122.0 | open-telemetry/opentelemetry-helm-charts |
| Operator binary | v0.158.0 | open-telemetry/opentelemetry-operator |
| Встроенный Java auto-instrumentation | v2.30.0 | поставляется в образе оператора |

```bash
helm upgrade --install opentelemetry-operator \
  open-telemetry/opentelemetry-operator \
  --version 0.122.0 \
  --namespace opentelemetry-operator \
  --create-namespace \
  --set admissionWebhooks.certManager.enabled=true
# → Expected: "opentelemetry-operator" has been upgraded
```

> **Замечание о флаге `--version 0.122.0`:** Явная фиксация версии чарта защищает от неконтролируемых апгрейдов при `helm repo update`. Для production-окружений рекомендуется всегда фиксировать версию и обновлять её явно через `helm upgrade ... --reuse-values` после ревью release notes.

#### Шаг 3: Валидация установки

```bash
# Проверка статуса подов оператора
kubectl get pods -n opentelemetry-operator
# → Expected: opentelemetry-operator-* в статусе Running (1/1)

# Проверка CRD
kubectl get crd | grep opentelemetry
# → Expected:
#   instrumentation.opentelemetry.io
#   opentelemetrycollectors.opentelemetry.io

# Проверка готовности оператора
kubectl get deployment -n opentelemetry-operator opentelemetry-operator -o jsonpath='{.status.readyReplicas}'
# → Expected: 1
```

---

### Сценарий 2: Развертывание и настройка OTel Collector

**Цель:** Настройка конвейера обработки сигналов для передачи в стек LGTM.

#### Шаг 1: Создание namespace

```bash
kubectl create namespace opentelemetry --dry-run=client -o yaml | kubectl apply -f -
# → Expected: namespace/opentelemetry created (или unchanged)
```

#### Шаг 2: Применение конфигурации Collector

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 1
  config: |
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
        spike_limit_percentage: 25

      batch:
        timeout: 1s
        send_batch_size: 1024

      resourcedetection:
        detectors: [env, system, k8snode]

      spanmetrics:
        metrics_exporter: prometheus
        dimensions:
          - name: service.name
          - name: span.name

    exporters:
      otlp:
        endpoint: tempo.tempo:4317
        tls:
          insecure: true

      loki:
        endpoint: http://loki.loki:3100/loki/api/v1/push

      prometheus:
        endpoint: 0.0.0.0:8889

    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, spanmetrics, batch]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [loki]
EOF
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector created
```

#### Шаг 3: Валидация развертывания Collector

```bash
# Проверка статуса Collector
kubectl get opentelemetrycollector -n opentelemetry
# → Expected: otel-collector   ...   Available   True

# Проверка подов Collector
kubectl get pods -n opentelemetry
# → Expected: otel-collector-* в статусе Running (1/1)

# Проверка сервисов Collector
kubectl get svc -n opentelemetry
# → Expected:
#   otel-collector          ClusterIP   ...   4317/TCP,4318/TCP   (OTLP)
#   otel-collector-monitoring ClusterIP ...   8888/TCP            (metrics)
#   otel-collector-otlp     ClusterIP   ...   4317/TCP,4318/TCP   (для внешних подключений)

# Проверка внутренних метрик коллектора
kubectl port-forward -n opentelemetry svc/otel-collector-monitoring 8888:8888 &
curl -s http://localhost:8888/metrics | head -5
# → Expected: otelcol_receiver_accepted_spans, otelcol_exporter_sent_spans и т.д.
```

---

### Сценарий 3: Настройка автоматической инструментации

**Цель:** Подготовка глобального профиля инструментации для Java-приложений.

#### Шаг 1: Создание ресурса Instrumentation

Используется Java auto-instrumentation v2.30.0 — версия, поставляемая в комплекте с Operator v0.158.0. Указание собственного тега `image` позволяет зафиксировать известную совместимую версию агента и не зависеть от того, какая версия агента будет включена в следующий релиз оператора.

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.30.0
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_TRACES_EXPORTER
        value: otlp
      - name: OTEL_SERVICE_NAME
        valueFrom:
          fieldRef:
            apiVersion: v1
            fieldPath: metadata.labels['app.kubernetes.io/name']
EOF
# → Expected: instrumentation.opentelemetry.io/java-instrumentation created
```

> **Замечание о `OTEL_SERVICE_NAME`:** Значение по умолчанию для имени сервиса — `unknown_service` (для Java) и имя Deployment (для других языков). Чтобы на дашбордах Grafana отображались человекочитаемые имена сервисов, рекомендуется задавать `OTEL_SERVICE_NAME` явно через Downward API на метку `app.kubernetes.io/name` или `app`.

#### Шаг 2: Валидация Instrumentation

```bash
# Проверка создания ресурса
kubectl get instrumentation -n opentelemetry
# → Expected: java-instrumentation   ...   http://otel-collector.opentelemetry:4317

# Проверка деталей (образ агента)
kubectl get instrumentation java-instrumentation -n opentelemetry -o jsonpath='{.spec.java.image}'
# → Expected: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.30.0

# Проверка доступности образа агента (опционально)
kubectl describe instrumentation java-instrumentation -n opentelemetry
# → Expected: секция Conditions с Status: True
```

#### Шаг 3: Тестирование внедрения (опционально)

Для проверки корректности работы Instrumentation создайте тестовый под:

```bash
kubectl run test-otel-pod \
  --image=nginx:alpine \
  --namespace=opentelemetry \
  --annotations='instrumentation.opentelemetry.io/inject-java: "true"' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl wait --for=condition=ready pod/test-otel-pod --timeout=60s

# Проверка init-контейнера (должен содержать образ autoinstrumentation-java)
kubectl describe pod test-otel-pod -n opentelemetry | grep -A 5 "Init Containers"
# → Expected: init-контейнер otel-agent с образом autoinstrumentation-java:2.30.0

# Очистка тестового пода
kubectl delete pod test-otel-pod -n opentelemetry
```

---

### Сценарий 4: Откат конфигурации Collector

**Цель:** Восстановление предыдущей работоспособной конфигурации Collector при ошибочных изменениях.

#### Шаг 1: Просмотр истории изменений

```bash
# Список ревизий Collector
kubectl rollout history deployment/otel-collector-collector -n opentelemetry
# → Expected: список ревизий (REVISION)

# Просмотр деталей конкретной ревизии
kubectl rollout history deployment/otel-collector-collector -n opentelemetry --revision=1
# → Expected: конфигурация Collector из первой ревизии
```

#### Шаг 2: Откат к предыдущей версии

```bash
kubectl rollout undo deployment/otel-collector-collector -n opentelemetry
# → Expected: deployment.apps/otel-collector-collector rolled back

# Ожидание завершения отката
kubectl rollout status deployment/otel-collector-collector -n opentelemetry --timeout=120s
# → Expected: deployment "otel-collector-collector" successfully rolled out

# Валидация: поды перезапущены с предыдущей конфигурацией
kubectl get pods -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector
# → Expected: новые поды в статусе Running
```

#### Шаг 3: Откат к конкретной ревизии

```bash
kubectl rollout undo deployment/otel-collector-collector -n opentelemetry --to-revision=1
# → Expected: deployment.apps/otel-collector-collector rolled back
```

---

### Сценарий 5: Масштабирование Collector

**Цель:** Изменение количества экземпляров Collector и ресурсных запросов.

#### Шаг 1: Масштабирование по репликам

```bash
# Увеличение до 2 реплик (для отказоустойчивости)
kubectl patch opentelemetrycollector otel-collector -n opentelemetry \
  --type=merge -p '{"spec":{"replicas":2}}'
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector patched

# Ожидание готовности
kubectl rollout status deployment/otel-collector-collector -n opentelemetry --timeout=120s

# Валидация
kubectl get pods -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector
# → Expected: 2 пода в статусе Running
```

#### Шаг 2: Изменение ресурсных запросов

```bash
# Увеличение CPU и Memory limits
kubectl patch opentelemetrycollector otel-collector -n opentelemetry \
  --type=merge -p '{
    "spec": {
      "resources": {
        "limits": {
          "cpu": "1000m",
          "memory": "2Gi"
        },
        "requests": {
          "cpu": "200m",
          "memory": "512Mi"
        }
      }
    }
  }'
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector patched

# Валидация: проверка обновленных лимитов
kubectl get deployment otel-collector-collector -n opentelemetry \
  -o jsonpath='{.spec.template.spec.containers[0].resources}'
# → Expected: {"limits":{"cpu":"1000m","memory":"2Gi"},"requests":{"cpu":"200m","memory":"512Mi"}}
```

#### Шаг 3: Возврат к стандартным ресурсам (Minikube)

```bash
kubectl patch opentelemetrycollector otel-collector -n opentelemetry \
  --type=merge -p '{
    "spec": {
      "replicas": 1,
      "resources": {
        "limits": {
          "cpu": "500m",
          "memory": "1024Mi"
        },
        "requests": {
          "cpu": "100m",
          "memory": "256Mi"
        }
      }
    }
  }'
```

---

### Сценарий 6: Обновление OTel Operator и Collector

**Цель:** Безопасное обновление компонентов OpenTelemetry до актуальных версий.

#### Шаг 1: Проверка текущей и доступной версии

```bash
# Текущая версия чарта
helm list -n opentelemetry-operator
# → Expected: appversion = v0.158.0, chart = opentelemetry-operator-0.122.0

# Доступные версии
helm search repo open-telemetry/opentelemetry-operator
# → Expected: latest available chart version
```

#### Шаг 2: Обновление Operator

```bash
helm upgrade opentelemetry-operator \
  open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --set admissionWebhooks.certManager.enabled=true \
  --reuse-values
# → Expected: "opentelemetry-operator" has been upgraded

# Ожидание готовности нового пода
kubectl rollout status deployment/opentelemetry-operator -n opentelemetry-operator --timeout=180s
# → Expected: deployment "opentelemetry-operator" successfully rolled out
```

#### Шаг 3: Валидация после обновления

```bash
# Проверка версии Operator
kubectl get deployment opentelemetry-operator -n opentelemetry-operator \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
# → Expected: ghcr.io/open-telemetry/opentelemetry-operator/opentelemetry-operator:v0.158.0

# Проверка работоспособности Collector
kubectl get opentelemetrycollector -n opentelemetry
# → Expected: otel-collector ... Available True

# Проверка Instrumentation
kubectl get instrumentation -n opentelemetry
# → Expected: java-instrumentation ... Ready True
```

> **Примечание:** Обновление Operator НЕ перезапускает существующие Collector'ы автоматически. Для применения новой версии Collector потребуется пересоздание ресурса `OpenTelemetryCollector` или обновление его конфигурации. Аналогично, обновление образа Java-агента через `spec.java.image` в CR `Instrumentation` не инициирует рестарт уже работающих подов — для применения нового агента требуется рестарт приложений (rollout Deployment) или удаление подов.

> **Особенности Operator v0.158.0:** Начиная с этого релиза feature gates `operator.networkpolicy` и `operand.networkpolicy` переведены в beta и включены по умолчанию. Operator автоматически создает NetworkPolicy для своих подов и для управляемых подов Collector. Если в кластере используется CNI с запретом на создание NetworkPolicy (например, в некоторых изолированных Minikube-конфигурациях), может потребоваться явно отключить feature gate флагом `--feature-gates=operator.networkpolicy=false,operand.networkpolicy=false` в Helm-значении `manager.extraArgs`.

---

### Сценарий 7: Включение расширений health_check, pprof, zpages и debug-экспортера

**Цель:** Получить инструменты диагностики и самоконтроля Collector без модификации приложений.

#### Шаг 1: Патч существующего Collector с extensions и debug exporter

```bash
kubectl patch opentelemetrycollector otel-collector -n opentelemetry --type=json -p='[
  {"op":"replace","path":"/spec/config","value":{
    "receivers":{
      "otlp":{
        "protocols":{
          "grpc":{"endpoint":"0.0.0.0:4317"},
          "http":{"endpoint":"0.0.0.0:4318"}
        }
      }
    },
    "processors":{
      "memory_limiter":{"check_interval":"1s","limit_percentage":80,"spike_limit_percentage":25},
      "batch":{"timeout":"1s","send_batch_size":1024},
      "resourcedetection":{"detectors":["env","system","k8snode"]},
      "k8sattributes":{"extract":{"metadata":["k8s.pod.name","k8s.namespace.name","k8s.deployment.name","k8s.node.name"]},"passthrough":false}
    },
    "exporters":{
      "otlp":{"endpoint":"tempo.tempo:4317","tls":{"insecure":true},"sending_queue":{"enabled":true,"num_consumers":10,"queue_size":5000}},
      "loki":{"endpoint":"http://loki.loki:3100/loki/api/v1/push"},
      "prometheus":{"endpoint":"0.0.0.0:8889"},
      "debug":{"verbosity":"normal","sampling_initial":5,"sampling_thereafter":200}
    },
    "extensions":{
      "health_check":{"endpoint":"0.0.0.0:13133"},
      "pprof":{"endpoint":"0.0.0.0:1777"},
      "zpages":{"endpoint":"0.0.0.0:55679"}
    },
    "service":{
      "extensions":["health_check","pprof","zpages"],
      "pipelines":{
        "traces":{"receivers":["otlp"],"processors":["memory_limiter","k8sattributes","resourcedetection","batch"],"exporters":["otlp","debug"]},
        "metrics":{"receivers":["otlp"],"processors":["memory_limiter","k8sattributes","resourcedetection","batch"],"exporters":["prometheus"]},
        "logs":{"receivers":["otlp"],"processors":["memory_limiter","k8sattributes","resourcedetection","batch"],"exporters":["loki"]}
      }
    }
  }}
]'
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector patched
```

#### Шаг 2: Проверка расширений

```bash
# Health check
kubectl port-forward -n opentelemetry svc/otel-collector 13133:13133 &
curl -s http://localhost:13133/status
# → Expected: {"status":"Server available","upSince":"...","uptime":"..."}

# pprof
kubectl port-forward -n opentelemetry svc/otel-collector 1777:1777 &
curl -s http://localhost:1777/debug/pprof/ | head -5
# → Expected: HTML-листинг доступных профилей (/debug/pprof/heap, /debug/pprof/goroutine и т. д.)

# zpages (внутренние страницы состояния)
kubectl port-forward -n opentelemetry svc/otel-collector 55679:55679 &
curl -s http://localhost:55679/ | head -5
# → Expected: страница с разделами (pipeline, component, tracez и др.)
```

> **Примечание:** Debug exporter пишет трейсы в логи пода. Чтобы не засорять логи, увеличьте `sampling_thereafter` до 500–1000, либо удалите debug из pipeline после отладки. Нагрузка от debug exporter на production-кластерах недопустима.

---

### Сценарий 8: Production-топология Agent (DaemonSet) + Gateway (Deployment)

**Цель:** Разделить прием телеметрии (на каждом узле) и агрегацию/экспорт (центральный сервис). Это уменьшает сетевой трафик между узлами и устраняет единую точку отказа.

#### Шаг 1: Развертывание Agent (DaemonSet)

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-agent
  namespace: opentelemetry
spec:
  mode: daemonset
  serviceAccount: opentelemetry-agent-sa
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
      kubeletstats:
        collection_interval: 20s
        auth_type: serviceAccount
        endpoint: https://${env:K8S_NODE_NAME}:10250
        insecure_skip_verify: true
      filelog:
        include:
          - /var/log/pods/*/*/*.log
        exclude:
          - /var/log/pods/*/otc-container/*.log
        operators:
          - type: container
    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
      k8sattributes:
        extract:
          metadata:
            - k8s.pod.name
            - k8s.namespace.name
            - k8s.deployment.name
            - k8s.node.name
      batch:
        timeout: 5s
    exporters:
      otlp:
        endpoint: otel-gateway-collector.opentelemetry:4317
        tls:
          insecure: true
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlp]
        metrics:
          receivers: [otlp, kubeletstats]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlp]
        logs:
          receivers: [otlp, filelog]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [otlp]
EOF
```

#### Шаг 2: Развертывание Gateway (Deployment)

Gateway принимает данные от всех Agent'ов, обогащает и экспортирует в backend:

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-gateway
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 2
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
      batch:
        timeout: 5s
        send_batch_size: 5000
      resourcedetection:
        detectors: [env, system]
      tail_sampling:
        decision_wait: 10s
        num_traces: 50000
        expected_new_traces_per_sec: 1000
        policies:
          - name: errors
            type: status_code
            status_code: {status_codes: [ERROR]}
          - name: slow
            type: latency
            latency: {threshold_ms: 500}
          - name: probabilistic
            type: probabilistic
            probabilistic: {sampling_percentage: 5}
    exporters:
      otlp:
        endpoint: tempo.tempo:4317
        tls: {insecure: true}
        sending_queue:
          enabled: true
          num_consumers: 20
          queue_size: 10000
      loki:
        endpoint: http://loki.loki:3100/loki/api/v1/push
      prometheus:
        endpoint: 0.0.0.0:8889
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, tail_sampling, batch]
          exporters: [otlp]
        metrics:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [prometheus]
        logs:
          receivers: [otlp]
          processors: [memory_limiter, resourcedetection, batch]
          exporters: [loki]
EOF
```

#### Шаг 3: Валидация

```bash
# Должно быть N подов Agent (по числу узлов) и 2 пода Gateway
kubectl get pods -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector
# → Expected: otel-agent-collector-*  (N шт., по числу узлов)
#             otel-gateway-collector-* (2 шт.)

# Проверка, что Agent отправляет данные в Gateway
kubectl logs -n opentelemetry -l app.kubernetes.io/component=opentelemetry-collector --tail=50 | grep -E "endpoint|otlp" | head
```

> **Примечание:** В Minikube всего один узел, поэтому DaemonSet даст только один под. Тем не менее топология остается полезной как отработка production-паттерна. Для реального тестирования используйте `minikube start --nodes 3`.

---

### Сценарий 9: Включение scrape приложений через Prometheus receiver

**Цель:** Позволить OTel Collector самостоятельно опрашивать приложения, экспортирующие метрики в формате Prometheus, без отдельного Prometheus job.

#### Шаг 1: Добавление receivers в Collector

```bash
kubectl patch opentelemetrycollector otel-collector -n opentelemetry --type=json -p='[
  {"op":"add","path":"/spec/config/receivers/prometheus","value":{
    "config":{
      "scrape_configs":[
        {
          "job_name":"kubernetes-pods",
          "kubernetes_sd_configs":[{"role":"pod"}],
          "relabel_configs":[
            {"source_labels":["__meta_kubernetes_pod_annotation_prometheus_io_scrape"],"action":"keep","regex":"true"},
            {"source_labels":["__meta_kubernetes_pod_annotation_prometheus_io_path"],"action":"replace","target_label":"__metrics_path__","regex":"(.+)"},
            {"source_labels":["__address__","__meta_kubernetes_pod_annotation_prometheus_io_port"],"action":"replace","regex":"([^:]+)(?::\\d+)?;(\\d+)","replacement":"$1:$2","target_label":"__address__"},
            {"source_labels":["__meta_kubernetes_namespace"],"action":"replace","target_label":"namespace"},
            {"source_labels":["__meta_kubernetes_pod_name"],"action":"replace","target_label":"pod"}
          ]
        }
      ]
    }
  }}
]'
```

#### Шаг 2: Добавление receiver в metrics pipeline

```bash
kubectl patch opentelemetrycollector otel-collector -n opentelemetry --type=json -p='[
  {"op":"replace","path":"/spec/config/service/pipelines/metrics/receivers","value":["otlp","prometheus"]}
]'
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector patched
```

#### Шаг 3: Валидация

```bash
# Collector должен начать scrape подов с аннотацией prometheus.io/scrape=true
curl -s http://localhost:8889/metrics | grep -E "scrape_samples_scraped|up" | head -5
# → Expected: ненулевые метрики scrape после обнаружения targets
```

> **Альтернатива — Target Allocator:** Для кластеров с сотнями ServiceMonitors рекомендуется использовать встроенный Target Allocator (CRD `TargetAllocator`), который распределяет scrape-нагрузку между репликами Collector. Это рассматривается отдельно в сценарии 11.

---

### Сценарий 10: Multi-language Instrumentation (Python, Node.js, .NET, Go)

**Цель:** Расширить автоматическую инструментацию на другие языки runtime.

#### Шаг 1: Создание отдельных ресурсов Instrumentation

```bash
# Python (OpenTelemetry Python auto-instrumentation v0.64b0 поставляется с Operator v0.158.0)
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: python-instrumentation
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  python:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.64b0
    env:
      - name: OTEL_TRACES_EXPORTER
        value: otlp
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_LOGS_EXPORTER
        value: otlp
EOF
# → Expected: instrumentation.opentelemetry.io/python-instrumentation created

# Node.js
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: nodejs-instrumentation
  namespace: opentelemetry
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  nodejs:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:0.78.0
EOF
# → Expected: instrumentation.opentelemetry.io/nodejs-instrumentation created
```

#### Шаг 2: Активация для подов

Чтобы применить инструментацию к поду, добавьте аннотацию в манифест Deployment/Pod:

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"
    instrumentation.opentelemetry.io/inject-python: "true"
    instrumentation.opentelemetry.io/inject-nodejs: "true"
    instrumentation.opentelemetry.io/inject-dotnet: "true"
    instrumentation.opentelemetry.io/inject-go: "true"
```

> **Механика:** Operator через Mutating Webhook проверяет наличие аннотаций, ищет соответствующий CR `Instrumentation` в namespace пода и добавляет init-контейнер с агентом + переменные окружения. Если для языка нет ресурса `Instrumentation` в namespace — инструментация не применяется, ошибок не возникает.

#### Шаг 3: Валидация

```bash
# Список ресурсов Instrumentation
kubectl get instrumentation -n opentelemetry
# → Expected:
#   java-instrumentation        ...
#   python-instrumentation      ...
#   nodejs-instrumentation      ...

# Проверка init-контейнеров в поде
kubectl describe pod <имя-пода> | grep -A 3 "Init Containers"
# → Expected: opentelemetry-auto-instrumentation для каждого языка
```

> **Ограничения:** Node.js и Python требуют совместимости с версией runtime (Node.js ≥ 18, Python ≥ 3.8). Java 8+ поддерживается полностью. Go auto-instrumentation находится в статусе beta и требует ручной линковки через `-ldflags="-X .../instrumentation/version"` при сборке бинарника.

---

### Сценарий 11: Target Allocator для Prometheus ServiceMonitors

**Цель:** Распределить scrape-нагрузку Prometheus по нескольким репликам Collector.

#### Шаг 1: Развертывание Collector с Target Allocator

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  mode: statefulset
  replicas: 3
  targetAllocator:
    enabled: true
    replicas: 3
    serviceAccount: opentelemetry-target-allocator-sa
    prometheusCR:
      enabled: true
      scrapeInterval: 30s
      serviceMonitorSelector:
        matchLabels:
          release: prometheus
      podMonitorSelector:
        matchLabels:
          release: prometheus
  config:
    receivers:
      prometheus:
        config:
          global:
            scrape_interval: 30s
    exporters:
      otlp:
        endpoint: tempo.tempo:4317
        tls: {insecure: true}
      prometheus:
        endpoint: 0.0.0.0:8889
    service:
      pipelines:
        metrics:
          receivers: [prometheus]
          processors: [batch]
          exporters: [otlp, prometheus]
EOF
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector created
```

#### Шаг 2: Валидация

```bash
# Должен быть создан под Target Allocator
kubectl get pods -n opentelemetry -l app.kubernetes.io/name=opentelemetry-target-allocator
# → Expected: otel-collector-target-allocator-* в статусе Running

# Endpoints для Prometheus receiver
kubectl get svc -n opentelemetry otel-collector-target-allocator
# → Expected: ClusterIP service на порту 80

# Проверка, что ServiceMonitors обнаружены
curl -s http://<pod-ip-targetallocator>:80/api/v1/targets | jq '.data.activeTargets | length'
# → Expected: количество обнаруженных Prometheus targets
```

> **Преимущество:** Target Allocator позволяет масштабировать scrape-нагрузку линейно: 3 реплики Collector обслуживают в 3 раза больше targets, чем одна. Поды Collector запрашивают у Target Allocator только свою долю targets и опрашивают только их.

---

### Сценарий 12: RBAC, ServiceAccount и NetworkPolicy

**Цель:** Минимальные привилегии для OpenTelemetry Operator и Collector.

#### Шаг 1: ServiceAccount для Collector

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: otel-collector-sa
  namespace: opentelemetry
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector
rules:
  - apiGroups: [""]
    resources: ["pods", "namespaces", "nodes"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["replicasets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: otel-collector
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: otel-collector
subjects:
  - kind: ServiceAccount
    name: otel-collector-sa
    namespace: opentelemetry
EOF
# → Expected: serviceaccount/otel-collector-sa created
#              clusterrole.rbac.authorization.k8s.io/otel-collector created
#              clusterrolebinding.rbac.authorization.k8s.io/otel-collector created
```

#### Шаг 2: Привязка ServiceAccount к OpenTelemetryCollector

```bash
kubectl patch opentelemetrycollector otel-collector -n opentelemetry --type=merge -p '{"spec":{"serviceAccount":"otel-collector-sa"}}'
# → Expected: opentelemetrycollector.opentelemetry.io/otel-collector patched
```

#### Шаг 3: NetworkPolicy (по умолчанию в Operator v0.158.0)

Начиная с Operator v0.158.0, NetworkPolicy для Collector создается автоматически. Если требуется более строгая политика, можно создать NetworkPolicy вручную:

```bash
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: opentelemetry-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
        - protocol: TCP
          port: 8889
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: tempo
      ports:
        - protocol: TCP
          port: 4317
    - to:
        - namespaceSelector:
            matchLabels:
              name: loki
      ports:
        - protocol: TCP
          port: 3100
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
EOF
# → Expected: networkpolicy.networking.k8s.io/otel-collector created
```

> **Осторожно:** Убедитесь, что в кластере установлен CNI с поддержкой NetworkPolicy (Calico, Cilium, Weave). Стандартный kubenet не поддерживает NetworkPolicy.

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Collector в CrashLoopBackOff** | Ошибка в YAML-конфигурации | Проверить логи: `kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector` |
| **Нет трейсов в Tempo** | Неверный эндпоинт экспортера | Проверить доступность `tempo.tempo:4317` внутри кластера |
| **Метрики не доходят до Prometheus** | Ошибка скрейпинга | Проверить порт `8889` и наличие аннотаций Prometheus в сервисе коллектора |
| **Агент не внедряется** | Отсутствует cert-manager | Убедиться, что cert-manager установлен (необходим для webhooks оператора) |
| **Operator не стартует** | Conflict с предыдущим release | Проверить `helm list -n opentelemetry-operator`. Удалить старый release: `helm uninstall opentelemetry-operator -n opentelemetry-operator` |
| **Instrumentation в статусе Unknown** | Operator не может внедрить агент | Проверить webhook Operator: `kubectl get pods -n opentelemetry-operator`. Проверить доступность API кластера |
| **Loki: ошибка push из Collector** | Loki не готов или неверный endpoint | Проверить `kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- http://loki.loki:3100/ready` |
| **Tempo: нет данных** | Неверный endpoint в Collector | Проверить `tempo.tempo:4317` (gRPC). Убедиться, что Tempo доступен из namespace `opentelemetry` |
| **Spanmetrics пустые** | `spanmetrics` не в pipeline | Проверить `service.pipelines.traces.processors` должен содержать `spanmetrics` |
| **Memory pressure Collector** | Высокая нагрузка, мало памяти | Увеличить `memory_limiter.limit_percentage` или ресурсы Collector |
| **Порт 4317 занят** | Конфликт с другим сервисом | Проверить `kubectl get svc -A | grep 4317`. Изменить порт в конфигурации Receiver |
| **Webhook rejection** | Certificate не сформирован | Проверить `kubectl get certificates -n opentelemetry-operator`. Перезапустить Operator |
| **Prometheus receiver не скрейпит поды** | Не установлен `ServiceAccount` с правами на чтение подов, либо отсутствует RBAC | Проверить `kubectl auth can-i list pods -n default --as=system:serviceaccount:opentelemetry:otel-collector-sa`. Должно быть `yes`. Добавить ClusterRole как в сценарии 12 |
| **Трейсы без атрибутов `k8s.*`** | Не подключен `k8sattributes` processor | Добавить `k8sattributes` в `service.pipelines.traces.processors` (сценарий 7). Убедиться, что у ServiceAccount есть права `get/list/watch pods,namespaces,nodes` |
| **Collector стартует но нет данных в Tempo/Loki** | DNS-разрешение для backend-сервисов не работает из namespace `opentelemetry` | `kubectl exec -n opentelemetry deploy/otel-collector -- nslookup tempo.tempo`. Если не разрешается — проверить NetworkPolicy и CoreDNS |
| **Init-контейнер Java-агента OOMKilled** | Недостаточно памяти для распаковки агента (~250 МБ на старте) | Увеличить `resources.limits.memory` для init-контейнера в спецификации OpenTelemetryCollector: `spec.resources.initContainer.limits.memory: 512Mi` |
| **Operator создает NetworkPolicy, но кластер не поддерживает** | Включен feature gate по умолчанию в v0.158.0 на CNI без поддержки | Передать `manager.extraArgs: --feature-gates=operator.networkpolicy=false,operand.networkpolicy=false` в Helm values |
| **`error: failed to determine CRD versions`** | Несовместимая версия CRD после апгрейда | `kubectl delete crd opentelemetrycollectors.opentelemetry.io instrumentation.opentelemetry.io` и переустановить Operator |
| **Operator v0.158.0 на Kubernetes 1.28-** | Operator v0.157.0+ требует Kubernetes ≥ 1.29 | Обновить кластер или откатить Operator на совместимую версию (v0.151.0 поддерживает K8s 1.27+) |
| **Health check endpoint не отвечает** | Не включен `health_check` extension или он не добавлен в `service.extensions` | Добавить extension в `config` (сценарий 7) и в `service.extensions` |

### Диагностика

```bash
# Статус всех ресурсов OTel
kubectl get otelcol,instrumentation -n opentelemetry

# Внутренние метрики коллектора (длина очередей, батчи)
kubectl port-forward -n opentelemetry svc/otel-collector-monitoring 8888:8888 &
curl -s http://localhost:8888/metrics | grep -E "otelcol_receiver_accepted|otelcol_exporter_sent"

# Проверка логов Collector (поиск ошибок экспорта)
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100 | grep -i error

# Проверка событий в namespace
kubectl get events -n opentelemetry --sort-by='.lastTimestamp' | tail -10

# Проверка версий компонентов
kubectl get deployment opentelemetry-operator -n opentelemetry-operator \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
echo ""
kubectl get opentelemetrycollector otel-collector -n opentelemetry -o jsonpath='{.status.image}'
echo ""

# Проверка DNS-разрешения Collector
kubectl exec -n opentelemetry deploy/otel-collector -- nslookup tempo.tempo
kubectl exec -n opentelemetry deploy/otel-collector -- nslookup loki.loki
kubectl exec -n opentelemetry deploy/otel-collector -- nslookup prometheus-operated.monitoring

# Проверка использования ресурсов
kubectl top pods -n opentelemetry --sort-by=memory
```

### Ограничения и известные проблемы

| Ограничение | Описание | Обходной путь |
| :--- | :--- | :--- |
| **Эфемерное хранилище** | Данные Collector теряются при перезапуске Minikube | Для production использовать PersistentVolume или внешние системы хранения |
| **100% сэмплирование** | Все трейсы сохраняются (высокая нагрузка на Tempo) | Для production включить tail-based sampling в OTel Collector |
| **Deployment (не DaemonSet)** | Один экземпляр Collector, single point of failure | Для production использовать DaemonSet (Agent) + Deployment (Gateway) |
| **TLS отключен** | Данные передаются без шифрования | Для production настроить mTLS между всеми компонентами |
| **Только Java-приложения** | Инструментация настроена только для Java | Для Python/Node.js/.NET добавить соответствующие `Instrumentation` ресурсы |
| **Без RBAC** | Все операции выполняются от имени администратора кластера | Для production настроить RoleBinding и ServiceAccount для Operator и Collector |

**Известные проблемы:**

1. **Задержка появления метрик spanmetrics:** После первого запроса метрики появляются в Prometheus через 15-30 секунд (задержка scrape + process_time).

2. **Webhook timeout при установке Operator:** Если cert-manager не готов, установка Operator может зависнуть на несколько минут. Убедитесь, что cert-manager работает до начала установки.

3. **Конфликт портов Collector:** Порт 4317 (gRPC) и 4318 (HTTP) должны быть уникальными в пределах namespace. Измените порты в конфигурации, если другой компонент уже использует их.

4. **memory_limiter и OOMKill:** Если `limit_percentage` установлен слишком высоко (>90%), Collector может быть OOMKill при резком всплеске нагрузки. Рекомендуется `limit_percentage: 80`.

### Лучшие практики развертывания OTel

1. **Всегда используйте memory_limiter:** Это критически важный processor для предотвращения OOMKill. Устанавливайте `check_interval: 1s`, `limit_percentage: 80`.

2. **Batch processor обязателен:** Без `batch` данные отправляются по одному, что кратно увеличивает нагрузку на сеть и backend-системы.

3. **resourcedetection в каждом pipeline:** Процессор `resourcedetection` обогащает данные информацией о поде, ноде, namespace. Это критически важно для корректной работы алертов и дашбордов.

4. **Разделяйте pipelines:** Не смешивайте трейсы, метрики и логи в одном pipeline. Каждый тип данных должен иметь свой pipeline с набором processors и exporters.

5. **Тестируйте конфигурацию перед применением:** Используйте `kubectl apply --dry-run=client -o yaml` для валидации манифеста. Дополнительно используйте утилиту `otelcol validate` локально для проверки секции `config:`:

   ```bash
   # Локально (требуется установленный otelcol-contrib)
   otelcol validate --config=/path/to/config.yaml
   # → Expected: "otelcol validate" без ошибок ИЛИ сообщение с указанием секции, в которой найдена проблема
   ```

6. **Следите за метриками Collector:** port-forward к метрикам Collector (порт 8888) и мониторьте длину очередей и количество отправленных данных. Ключевые метрики для алертинга:

   - `otelcol_exporter_queue_size` — текущая длина очереди экспортера (резкий рост указывает на проблемы с backend);
   - `otelcol_exporter_send_failed_*` — количество неудачных отправок;
   - `otelcol_receiver_refused_*` — количество отклоненных receiver'ом данных (типично при переполнении `memory_limiter`);
   - `otelcol_processor_dropped_spans` — спаны, отброшенные процессорами.

7. **Не используйте insecure: true в production:** Настройте mTLS между Collector и backend-системами.

8. **Регулярно обновляйте Operator и Collector:** Следите за релизами и применяйте обновления через Helm с `--reuse-values`.

### Очистка ресурсов OTel

Для удаления только ресурсов OpenTelemetry (без удаления стека LGTM):

```bash
# Удаление Instrumentation
kubectl delete instrumentation java-instrumentation -n opentelemetry

# Удаление Collector
kubectl delete opentelemetrycollector otel-collector -n opentelemetry

# Удаление namespace
kubectl delete namespace opentelemetry

# Удаление Operator через Helm
helm uninstall opentelemetry-operator -n opentelemetry-operator

# Удаление namespace Operator
kubectl delete namespace opentelemetry-operator

# Удаление CRD (опционально, если不会再 использовать OTel)
kubectl delete crd instrumentation.opentelemetry.io
kubectl delete crd opentelemetrycollectors.opentelemetry.io

# Проверка удаления
kubectl get otelcol,instrumentation -A
# → Expected: No resources found
```

### Связанные темы

- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**
- **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**
- **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** — современная альтернатива для экосистемы Grafana.

### Безопасность и Production

> **Внимание:** Данная конфигурация оптимизирована для Minikube.

| Аспект | Minikube (Dev) | Production (рекомендация) |
| :--- | :--- | :--- |
| **TLS** | Insecure (отключен) | mTLS между всеми компонентами |
| **Режим Collector** | Deployment | DaemonSet (Agent) + Deployment (Gateway) |
| **Сэмплирование** | 100% (без сэмплирования) | Tail-based sampling для снижения нагрузки |
| **Хранение** | Эфемерное | S3/GCS для Tempo/Loki, EBS для Prometheus |
| **Аутентификация OTLP** | Без аутентификации | Extension `bearertokenauth` или `oauth2` |
| **Устойчивость очередей** | Только in-memory `sending_queue` | Extension `file_storage` для persistent queue (переживает рестарт Collector) |
| **Сетевые политики** | Не настроены | NetworkPolicy (см. сценарий 12) — Operator v0.158.0 создает их по умолчанию |
| **Multi-tenancy** | Нет | Отдельные Collector на команду/среду + Resource Attributes `tenant.id` |

#### Persistent queue (file_storage) для отказоустойчивости

В Minikube Collector хранит неотправленные данные в оперативной памяти. При рестарте пода (например, после `kubectl rollout restart`) буфер теряется. Extension `file_storage` позволяет сохранить очередь на диск:

```yaml
extensions:
  file_storage/alloy_data:
    directory: /var/lib/otelcol/storage
    timeout: 10s

exporters:
  otlp/tempo:
    endpoint: tempo.tempo:4317
    tls: {insecure: true}
    sending_queue:
      enabled: true
      storage: file_storage/alloy_data
      num_consumers: 10
      queue_size: 5000

service:
  extensions: [file_storage/alloy_data]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo]
```

> **Важно:** В Minikube каталог `/var/lib/otelcol/storage` эфемерен и привязан к emptyDir. Для production необходимо смонтировать туда PVC с подходящим StorageClass (например, gp3 с IOPS > 1000). Иначе при рестарте ноды данные все равно будут потеряны.

#### mTLS через cert-manager

Operator v0.158.0 поддерживает автоматическую выдачу сертификатов для OTLP-приемников. Конфигурация с mTLS требует:

1. Включить `admissionWebhooks.certManager.enabled=true` (уже включено в сценарии 1).
2. В CR `OpenTelemetryCollector` определить `spec.tls`:

   ```yaml
   spec:
     tls:
       minVersion: "1.3"
       cipherSuites: ["TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384"]
       caBundle: <base64-CA-bundle-или-пустая-строка-для-cert-manager>
     config:
       receivers:
         otlp:
           protocols:
             grpc:
               endpoint: 0.0.0.0:4317
               tls:
                 cert_file: /etc/otelcol/tls/tls.crt
                 key_file: /etc/otelcol/tls/tls.key
                 client_ca_file: /etc/otelcol/tls/ca.crt
   ```

3. Operator создаст Secret с сертификатами и смонтирует его в под.

> **Альтернатива:** Для внутренних сервисов, где mTLS избыточен, можно ограничиться NetworkPolicy + Service Mesh (Istio/Linkerd) с автоматическим mTLS на уровне mesh — в этом случае OTLP передается plaintext внутри mesh-сети, а шифрование обеспечивается sidecar-прокси.

#### Аутентификация приложений через bearer token

Если приложения должны авторизоваться перед отправкой данных в Collector (например, при multi-tenancy):

```yaml
extensions:
  bearertokenauth:
    token: <секретный-токен>
    # Или для нескольких клиентов:
    # tokens:
    #   - token: <token-1>
    #     tenant: tenant-a
    #   - token: <token-2>
    #     tenant: tenant-b

receivers:
  otlp:
    protocols:
      grpc:
        auth:
          authenticator: bearertokenauth

service:
  extensions: [bearertokenauth]
```

В приложении задается заголовок `Authorization: Bearer <token>`. Этот же токен должен знать Collector. Для ротации токенов используйте внешний Secret Manager (HashiCorp Vault, Sealed Secrets).

#### Head-based vs Tail-based sampling

| Решение | Когда применять | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Head-based (parent-based, в SDK)** | Большинство production-кейсов | Минимальная нагрузка на backend; не требует хранения состояния | Решение принимается до завершения трейса — можно потерять интересные трейсы |
| **Tail-based (в Gateway Collector)** | Когда нужно сохранить все ошибки, но отбросить 95% успешных | Полная информация о трейсе при принятии решения | Требует хранения трейсов в памяти Gateway (`num_traces`); дополнительная задержка `decision_wait` |
| **Composite (head на SDK + tail на Gateway)** | Самый распространенный production-паттерн | SDK отбрасывает 95% трейсов на раннем этапе, Gateway принимает решение по оставшимся 5% | Более сложная конфигурация |

#### Подавление шумных трейсов (filter processor)

Если часть эндпоинтов (например, `/healthz`, `/metrics`) генерирует избыточные трейсы, отбрасывайте их на этапе Collector:

```yaml
processors:
  filter/empty_traces:
    traces:
      span:
        - 'attributes["http.target"] == "/healthz"'
        - 'attributes["http.target"] == "/readyz"'
  filter:
    metrics:
      metric:
        - 'name == "http.server.duration" and attributes["http.target"] == "/healthz"'

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [filter/empty_traces, batch]
      exporters: [otlp/tempo]
```

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** (вперед)
- **[Production Hardening](./lgtm_production_hardening.md)** (дополнительно)

