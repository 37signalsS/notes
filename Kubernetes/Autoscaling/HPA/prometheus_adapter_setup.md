# Prometheus Adapter: настройка и интеграция с HPA

**Актуально для:** Prometheus Adapter v0.12.x, Kubernetes 1.26–1.32+

## Определения

**Prometheus Adapter** — расширение API-сервера Kubernetes (Aggregated API Server), реализующее спецификации Custom Metrics API (`custom.metrics.k8s.io`) и External Metrics API (`external.metrics.k8s.io`). Преобразует запросы контроллера HPA в PromQL-запросы к инстансу Prometheus и возвращает нормализованные метрики.

**Kubernetes Aggregation Layer** — встроенный механизм `kube-apiserver`, позволяющий подключать специализированные вспомогательные API-серверы без изменения кода основного ядра Kubernetes. Маршрутизация запросов осуществляется через объект `APIService`.

**Custom Metrics API (`custom.metrics.k8s.io`)** — версионированный интерфейс API Kubernetes для предоставления метрик, ассоциированных с конкретными объектами кластера (Pod, Service, Ingress, Deployment). Используется типами метрик HPA `Pods` и `Object`.

**External Metrics API (`external.metrics.k8s.io`)** — версионированный интерфейс API Kubernetes для передачи метрик систем, не привязанных напрямую к объектам подов внутри кластера (длина очереди RabbitMQ, лаг партиций Kafka, число соединений к внешней СУБД). Используется типом метрики HPA `External`.

**Discovery Rule** — декларативное правило в конфигурации адаптера, описывающее четыре фазы обработки метрики: обнаружение рядов (`seriesQuery`), привязка к ресурсам Kubernetes (`resources`), трансформация имени (`name`) и шаблон запроса PromQL (`metricsQuery`).

---

## Архитектура и принцип работы

### Архитектура Aggregation Layer

```
                     ┌──────────────────────────────────────────────┐
                     │              kube-apiserver                  │
                     │          (Aggregation Layer Proxy)           │
                     └──────┬────────────────────┬──────────────────┘
                            │                    │
          /apis/metrics.k8s.io                   │ /apis/custom.metrics.k8s.io
                            │                    │ /apis/external.metrics.k8s.io
                            ▼                    ▼
                 ┌──────────────────┐   ┌───────────────────────────┐
                 │  Metrics Server  │   │    Prometheus Adapter     │
                 │  (CPU / Memory)  │   │  (Aggregated API Server)  │
                 └──────────────────┘   └─────────────┬─────────────┘
                                                      │
                                                      │ HTTP / HTTPS (PromQL)
                                                      ▼
                                        ┌───────────────────────────┐
                                        │        Prometheus         │
                                        │ (TSDB / Scrape Targets)   │
                                        └───────────────────────────┘
```

1. **HPA Controller** (в составе `kube-controller-manager`) с периодичностью `--horizontal-pod-autoscaler-sync-period` (по умолчанию 15 секунд) запрашивает метрики у `kube-apiserver`.
2. **`kube-apiserver`** сверяется с объектами `APIService` (`v1beta1.custom.metrics.k8s.io` и `v1beta1.external.metrics.k8s.io`) и проксирует TLS-запрос в под `prometheus-adapter` через сервис кластера.
3. **Prometheus Adapter** транслирует поступивший REST-запрос в PromQL-выражение, подставляя параметры объекта и временные окна в настроенный шаблон правила.
4. **Prometheus** выполняет вычисление PromQL и возвращает вектор значений адаптеру.
5. **Prometheus Adapter** упаковывает результат в структуру `MetricValueList` и возвращает ответ контроллеру HPA.

### Различия Custom Metrics и External Metrics

| Характеристика | Custom Metrics (`custom.metrics.k8s.io`) | External Metrics (`external.metrics.k8s.io`) |
|:---|:---|:---|
| **Привязка к объектам** | Строго к объекту Kubernetes (Pod, Ingress, Service, Namespace) | Без жесткой привязки к объекту Kubernetes (глобальный сервис, брокер сообщений) |
| **Секция в config.yaml** | `rules:` | `externalRules:` |
| **Секция в Helm values** | `rules.custom:` | `rules.external:` |
| **Тип метрики в HPA** | `Pods` или `Object` | `External` |
| **Тип таргета HPA** | `AverageValue` (для `Pods`), `Value` / `AverageValue` (для `Object`) | `Value` или `AverageValue` |
| **Фильтрация в HPA** | По имени пода или метаданным объекта | Через `selector.matchLabels` |
| **Примеры применения** | HTTP RPS приложения, latency Ingress, активные gRPC-стримы | Глубина очереди RabbitMQ, лаг группы Kafka, подключения к PostgreSQL |

### Механизм преобразования PromQL в метрики Kubernetes

Каждое правило преобразования состоит из четырех последовательных этапов:

```
[Discovery: seriesQuery] ──► [Association: resources] ──► [Naming: name] ──► [Querying: metricsQuery]
```

1. **Discovery (`seriesQuery`, `seriesFilters`):**
   Адаптер периодически обращается к эндпоинту `/api/v1/series` в Prometheus для поиска доступных рядов. Фильтры отсекают лишние метрики, снижая объем оперативной памяти.
2. **Association (`resources`):**
   Определяет соответствие между лейблами Prometheus и ресурсами Kubernetes API. По умолчанию лейбл `namespace` мапится в пространство имен, а лейбл `pod` — в имя пода. Для объектов уровня кластера или других API-групп (например, Ingress) задаются явные переопределения (`overrides`).
3. **Naming (`name.matches`, `name.as`):**
   Регулярное выражение трансформирует внутреннее имя метрики Prometheus в публичное имя метрики в Custom Metrics API (например, удаление суффикса `_total` и замена на `_per_second`).
4. **Querying (`metricsQuery`):**
   Go-шаблон PromQL, который компилируется при запросе от HPA. Переменные шаблона:
   - `<<.Series>>`: исходное имя метрики в Prometheus.
   - `<<.LabelMatchers>>`: набор селекторов лейблов, сформированный адаптером на основе запрашиваемого объекта (`namespace="default",pod=~"app-.*"`).
   - `<<.GroupBy>>`: список ресурсов для группировки агрегации (`pod`, `namespace`). Не используется для `externalRules`.

### Сравнение с KEDA (Prometheus Adapter vs KEDA)

| Критерий | Prometheus Adapter | KEDA |
|:---|:---|:---|
| **Архитектурная роль** | Aggregated API Server для Prometheus | Оператор масштабирования на основе событий + External Metrics Server |
| **Источники метрик** | Исключительно Prometheus / Cortex / Thanos / VictoriaMetrics | 60+ встроенных скейлеров (Kafka, RabbitMQ, PostgreSQL, Redis, Prometheus) |
| **Масштабирование в 0 (Scale to Zero)** | Не поддерживается (минимальное число реплик HPA равно 1) | Поддерживается нативно через управление Deployment/StatefulSet |
| **Сложность PromQL** | Любые сложные составные выражения, объединения векторов, квантили | Ограничена одиночными скалярными запросами скейлера |
| **Нагрузка на инфраструктуру** | Постоянный опрос Prometheus с интервалом синхронизации HPA | Опрос внешних источников оператором с настраиваемым `pollingInterval` |
| **Сложность внедрения** | Требует понимания Go-шаблонов адаптера и маппинга лейблов | Декларативные CRD `ScaledObject` и `TriggerAuthentication` |

---

## Установка и практическая конфигурация

### Требования к окружению (Prerequisites)

- Кластер Kubernetes версии 1.26–1.32+ с правами доступа `cluster-admin`.
- Включенный механизм Kubernetes Aggregation Layer на нодах Control Plane (в `kube-apiserver` настроены параметры `--requestheader-client-ca-file`, `--proxy-client-cert-file`, `--proxy-client-key-file`). В стандартных установках через `kubeadm`, `RKE2` и `k3s` данный механизм активен по умолчанию.
- Развернутый инстанс Prometheus (например, из состава `kube-prometheus-stack`), доступный по сети из неймспейса установки адаптера.
- Установленный пакетный менеджер Helm v3.12+.

### Шаг 1: Развертывание через Helm

Создайте файл значений `values.yaml` для релиза Prometheus Adapter:

```yaml
# values.yaml для prometheus-community/prometheus-adapter
prometheus:
  # Внутренний DNS-адрес сервиса Prometheus в кластере
  url: http://prometheus-kube-prometheus-prometheus.monitoring.svc
  port: 9090
  path: ""

replicas: 2

# Гарантия непрерывной работы при обслуживании нод кластера
podDisruptionBudget:
  enabled: true
  minAvailable: 1

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Настройка правил трансформации метрик
rules:
  default: false
  custom:
    # Правило 1: HTTP RPS на каждый отдельный под
    - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)_total$"
        as: "${1}_per_second"
      metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'

    # Правило 2: P99 Latency по объекту Ingress
    - seriesQuery: 'http_request_duration_seconds_bucket{namespace!="",ingress!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
      name:
        matches: "^(.*)_bucket$"
        as: "${1}_p99"
      metricsQuery: 'histogram_quantile(0.99, sum(rate(<<.Series>>{<<.LabelMatchers>>}[5m])) by (le, <<.GroupBy>>))'

    # Правило 3: Активные TCP-соединения на под
    - seriesQuery: 'net_connections_established{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)$"
        as: "active_connections"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'

  external:
    # Правило 4: Количество сообщений в очереди RabbitMQ (External Metric)
    - seriesQuery: 'rabbitmq_queue_messages{queue!=""}'
      resources:
        namespaced: true
      name:
        matches: "^rabbitmq_queue_messages$"
        as: "rabbitmq_queue_messages"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>})'
```

Выполните установку чарта:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --create-namespace \
  --values values.yaml \
  --wait
```

### Шаг 2: Конфигурация через нативный ConfigMap (без Helm)

Если адаптер разворачивается через сырые манифесты Kubernetes, структура `config.yaml` внутри ConfigMap имеет следующий вид:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-adapter-config
  namespace: monitoring
data:
  config.yaml: |
    rules:
      - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            pod: {resource: "pod"}
        name:
          matches: "^(.*)_total$"
          as: "${1}_per_second"
        metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'

    externalRules:
      - seriesQuery: 'rabbitmq_queue_messages{queue!=""}'
        resources:
          namespaced: true
        name:
          matches: "^rabbitmq_queue_messages$"
          as: "rabbitmq_queue_messages"
        metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>})'
```

После редактирования ConfigMap перезапустите Deployment:

```bash
kubectl rollout restart deployment prometheus-adapter -n monitoring
# → deployment.apps/prometheus-adapter restarted
```

### Шаг 3: Настройка RBAC

Для работы Aggregation Layer адаптеру требуются права делегирования аутентификации и авторизации:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-adapter:system:auth-delegator
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:auth-delegator
subjects:
  - kind: ServiceAccount
    name: prometheus-adapter
    namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: prometheus-adapter-auth-reader
  namespace: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: extension-apiserver-authentication-reader
subjects:
  - kind: ServiceAccount
    name: prometheus-adapter
    namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-adapter-resource-reader
rules:
  - apiGroups: [""]
    resources: ["namespaces", "pods", "services", "configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-adapter-resource-reader-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus-adapter-resource-reader
subjects:
  - kind: ServiceAccount
    name: prometheus-adapter
    namespace: monitoring
```

---

## Эксплуатация и валидация

### Валидация регистрации APIService

Убедитесь, что `kube-apiserver` успешно зарегистрировал эндпоинты кастомных и внешних метрик:

```bash
kubectl get apiservice | grep -E "custom.metrics|external.metrics"
# → v1beta1.custom.metrics.k8s.io     monitoring/prometheus-adapter   True        5m
# → v1beta1.external.metrics.k8s.io   monitoring/prometheus-adapter   True        5m
```

Если статус не равен `True`, обратитесь к разделу [Диагностика и устранение неисправностей](#диагностика-и-устранение-неисправностей).

### Проверка обнаружения метрик через Raw API

Проверьте список всех обнаруженных и опубликованных адаптером кастомных метрик:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq -r '.resources[].name'
# → pods/http_requests_per_second
# → ingresses.networking.k8s.io/http_request_duration_seconds_p99
# → pods/active_connections
```

Запросите текущее значение метрики для подов в пространстве имен `default`:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second" | jq .
```

Ожидаемый ответ:

```json
{
  "kind": "MetricValueList",
  "apiVersion": "custom.metrics.k8s.io/v1beta1",
  "metadata": {},
  "items": [
    {
      "describedObject": {
        "kind": "Pod",
        "namespace": "default",
        "name": "my-app-7b9d5c64bf-8xzl2",
        "apiVersion": "/v1"
      },
      "metricName": "http_requests_per_second",
      "timestamp": "2026-10-12T17:30:00Z",
      "value": "250m",
      "periodSeconds": 120
    }
  ]
}
```

> **Примечание:** Значение `250m` означает 250 миллиединиц (0.25 RPS), так как API Kubernetes возвращает дробные величины в милли-квантах.

Запросите внешнюю метрику с фильтрацией по имени очереди:

```bash
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/default/rabbitmq_queue_messages?labelSelector=queue%3Dorders" | jq .
```

Ожидаемый ответ:

```json
{
  "kind": "ExternalMetricValueList",
  "apiVersion": "external.metrics.k8s.io/v1beta1",
  "metadata": {},
  "items": [
    {
      "metricName": "rabbitmq_queue_messages",
      "metricLabels": {
        "queue": "orders"
      },
      "timestamp": "2026-10-12T17:30:00Z",
      "value": "45"
    }
  ]
}
```

---

## Практические сценарии манифестов HPA

### Сценарий 1: HPA по HTTP RPS на под (тип Pods)

Масштабирование сервиса `my-app` на основе средней нагрузки на каждый инстанс. Целевой показатель — 500 запросов в секунду на под:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-rps-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
```

### Сценарий 2: HPA по задержке P99 на Ingress (тип Object)

Масштабирование бэкенда на основе 99-го перцентиля задержки ответов на уровне Ingress-контроллера. Целевой порог — 500 миллисекунд (записывается как `500m`):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-latency-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Object
      object:
        describedObject:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          name: my-app-ingress
        metric:
          name: http_request_duration_seconds_p99
        target:
          type: Value
          value: "500m"
```

### Сценарий 3: HPA по глубине очереди RabbitMQ (тип External)

Масштабирование воркеров-обработчиков очереди сообщений. Используется тип таргета `AverageValue`, чтобы общее количество сообщений делилось на текущее число реплик воркеров (целевая нагрузка: 30 сообщений на один под):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: queue-consumer-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: queue-consumer
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: rabbitmq_queue_messages
          selector:
            matchLabels:
              queue: "orders"
        target:
          type: AverageValue
          averageValue: "30"
```

### Сценарий 4: Мультиметрический HPA с профилями стабилизации

Комплексный профиль автомасштабирования, учитывающий базовую загрузку CPU, бизнес-трафик (RPS) и время отклика (Latency). HPA вычисляет желаемое число реплик по каждому правилу независимо и выбирает **максимальное**:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-multi-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 25
  metrics:
    # Метрика 1: Загрузка CPU (стандартный ресурс Metrics Server)
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    # Метрика 2: HTTP RPS на под (Custom Metrics API)
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
    # Метрика 3: P99 Latency (Custom Metrics API)
    - type: Pods
      pods:
        metric:
          name: http_request_duration_seconds_p99
        target:
          type: AverageValue
          averageValue: "500m"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
      selectPolicy: Min
```

---

## Диагностика и устранение неисправностей

### Сводная таблица неисправностей

| Проблема | Диагностическая команда | Вероятная причина | Решение |
|:---|:---|:---|:---|
| APIService в статусе `False` | `kubectl describe apiservice v1beta1.custom.metrics.k8s.io` | 1. Сетевая недоступность порта 6443/443 адаптера для Control Plane.<br>2. Ошибка валидации TLS-сертификата (`x509: certificate signed by unknown authority`). | 1. Проверить NetworkPolicy и правила firewall между мастерами и воркерами.<br>2. Проверить `caBundle` в APIService или включить выпуск сертификатов через `cert-manager`. |
| HPA показывает `TARGETS: <unknown>` | `kubectl describe hpa <name>` | 1. Имя метрики в HPA не совпадает с `name.as`.<br>2. Лейбл `pod` в метрике Prometheus не совпадает с именем пода.<br>3. PromQL возвращает пустой вектор. | 1. Сверить имя через `kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1`.<br>2. Настроить relabeling в Prometheus или блок `resources.overrides`.<br>3. Протестировать PromQL в интерфейсе Prometheus. |
| Метрика отсутствует в выводе Raw API | `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" \| jq .` | `seriesQuery` не находит рядов в TSDB Prometheus при периодическом поиске (Discovery). | Проверить наличие метрик запросом: `curl "http://prometheus:9090/api/v1/series?match[]=<seriesQuery>"`. |
| Адаптер возвращает ошибку `HTTP 500` или timeout | `kubectl logs -n monitoring deploy/prometheus-adapter` | Prometheus перегружен и не успевает отвечать за `--prometheus-timeout` (по умолчанию 5 секунд). | 1. Увеличить таймаут флагом `--prometheus-timeout=15s`.<br>2. Оптимизировать PromQL и вынести сложные квантили в Recording Rules. |
| OOMKilled пода адаптера | `kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-adapter` | Высокая кардинальность (High Cardinality) метрик в `seriesQuery`. | Сузить фильтры `seriesQuery` и `seriesFilters`, убрать маппинг неиспользуемых метрик. |

### Пошаговые процедуры отладки

#### 1. Проверка сетевой связности между компонентами

Проверьте доступность Prometheus из пода адаптера:

```bash
kubectl exec -n monitoring deploy/prometheus-adapter -- \
  wget -qO- http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090/-/healthy
# → Prometheus Server is Healthy.
```

Проверьте доступность API-сервера адаптера из Control Plane:

```bash
kubectl run test-curl --image=curlimages/curl --rm -it --restart=Never -- \
  curl -k -v https://prometheus-adapter.monitoring.svc:443/healthz
# → < HTTP/2 200
# → < ok
```

#### 2. Детальный аудит логов адаптера

Для выявления синтаксических ошибок PromQL и сбоев сопоставления лейблов запустите просмотр логов:

```bash
kubectl logs -n monitoring deploy/prometheus-adapter -f --tail=100 | grep -E "level=error|unable to|failed"
```

Для глубокого анализа включите подробное логирование, добавив в Deployment аргумент `--v=6` или `--v=10` в `values.yaml` (`logLevel: 6`).

#### 3. Тестирование генерации PromQL-запроса

Чтобы узнать точный PromQL-запрос, отправляемый адаптером в Prometheus, выполните прямой вызов Raw API с открытым логом адаптера:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second"
```

В логах адаптера появится строка вида:

```text
querying prometheus for query "sum(rate(http_requests_total{namespace=\"default\",pod=~\"my-app-.*\"}[2m])) by (pod)"
```

Скопируйте сгенерированный запрос и выполните его в UI Prometheus (`Status -> Targets` и `Graph`), чтобы убедиться в наличии актуальных точек данных.

---

## Лучшие практики

### 1. Использование Prometheus Recording Rules для квантилей и тяжелых вычислений

Прямой расчет функции `histogram_quantile()` через `metricsQuery` каждые 15 секунд создает значительную нагрузку на TSDB Prometheus при большом числе подов и высокой кардинальности меток `le`.

**Рекомендация:** Настройте в Prometheus предварительный расчет метрики через `PrometheusRule`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: app-recording-rules
  namespace: monitoring
spec:
  groups:
    - name: app.hpa.rules
      rules:
        - record: job:http_request_duration_seconds:p99
          expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, namespace, ingress))
```

В адаптере запрашивайте уже вычисленный скалярный ряд без повторного расчета квантиля:

```yaml
rules:
  custom:
    - seriesQuery: 'job:http_request_duration_seconds:p99{namespace!="",ingress!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          ingress: {resource: "ingress", group: "networking.k8s.io", version: "v1"}
      name:
        matches: "^(.*)$"
        as: "http_request_duration_seconds_p99"
      metricsQuery: 'sum(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
```

### 2. Контроль кардинальности (Cardinality Control)

- Запрещено использовать жадные селекторы вида `seriesQuery: '{__name__=~".*"}'`. Всегда указывайте строгие префиксы (`http_requests_.*`) и обязательные условия (`namespace!=""`).
- Используйте `seriesFilters` для исключения вспомогательных рядов (`_created`, `_info`).
- Ограничивайте частоту скрейпинга в Prometheus: интервал скрейпинга приложения должен быть согласован с окном `rate()`. Для скрейпинга 15 секунд оптимальное окно `rate()` составляет `[1m]`–`[2m]`.

### 3. Отказоустойчивость и сайзинг ресурсов

- **Количество реплик:** Всегда запускайте не менее 2 реплик адаптера (`replicas: 2`). Так как `kube-apiserver` агрегирует запросы через балансировщик Service, отказ одного пода не приведет к отключению HPA.
- **PodDisruptionBudget:** Задавайте `minAvailable: 1`, чтобы защитить кластер от потери Custom Metrics API во время планового обновления нод (`drain`).
- **Размещение на инфраструктурных узлах:** Используйте `nodeSelector` или `tolerations` для размещения адаптера на надежных System / Infra нодах.

### 4. Настройка интервалов стабилизации и подавление дребезга (Flapping)

Метрики приложений (RPS, queue depth) обладают более высокой волатильностью по сравнению с CPU и Memory. Без настройки профиля `behavior` в HPA кластер будет подвержен циклическому масштабированию туда-обратно:

- Устанавливайте `scaleDown.stabilizationWindowSeconds` от 300 до 600 секунд (5–10 минут), чтобы избежать преждевременного удаления подов при кратковременном спаде трафика.
- Для `scaleUp` ограничивайте максимальный прирост реплик процентной политикой (`Percent: 100` каждые 15 секунд), чтобы предотвратить истощение ресурсов нод при резких спайках.

---

## Дополнительная информация

### Совместимость версий

| Версия Prometheus Adapter | Версия Kubernetes | Поддерживаемые спецификации Metrics API |
|:---|:---|:---|
| **v0.12.x** | 1.26 – 1.32+ | `custom.metrics.k8s.io/v1beta1`, `custom.metrics.k8s.io/v1beta2`, `external.metrics.k8s.io/v1beta1` |
| **v0.11.x** | 1.22 – 1.28 | `custom.metrics.k8s.io/v1beta1`, `custom.metrics.k8s.io/v1beta2`, `external.metrics.k8s.io/v1beta1` |
| **v0.10.x** | 1.20 – 1.25 | `custom.metrics.k8s.io/v1beta1`, `external.metrics.k8s.io/v1beta1` |

### См. также

- **[HPA: Основные концепции](./hpa_concepts.md)** — архитектура контроллера, математическая формула расчета реплик и жизненный цикл автомасштабирования.
- **[HPA: Практические сценарии](./hpa_scenarios.md)** — сценарии использования HPA для различных типов нагрузок и метрик.
- **[HPA: Продвинутые механизмы масштабирования](./hpa_advanced.md)** — глубокая настройка поведения (behavior), cgroups v2 и тонкая калибровка стабилизации.
- **[KEDA: Основные концепции](../keda/keda_concepts.md)** — альтернативный подход к автомасштабированию на базе внешних триггеров и очередей с поддержкой scale-to-zero.
- **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — системное руководство по диагностике сбоев петли управления HPA.
