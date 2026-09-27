# ServiceMonitor — Концепции (CRD)

## Определения

**`kind: ServiceMonitor`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга (scraping targets) на основе Kubernetes Service. Это основной механизм обнаружения приложений в стеке мониторинга, который абстрагирует сложность конфигурации `kubernetes_sd_configs`.

**Discovery-паттерн** — процесс автоматического обнаружения эндпоинтов сервиса. В отличие от статического перечисления IP-адресов, `ServiceMonitor` позволяет динамически подключать новые поды приложения к мониторингу сразу после их запуска через абстракцию Endpoints или EndpointSlice.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [PodMonitor CRD](./podmonitor.md) — мониторинг подов напрямую, [Prometheus CRD](./prometheus.md) — конфигурация сервера Prometheus.

## Базовые концепции

### Архитектура управления целями скрейпинга

ServiceMonitor CRD является декларативным описанием желаемого состояния целей мониторинга. Оператор отслеживает изменения ресурса и автоматически генерирует конфигурацию для Prometheus:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `ServiceMonitor` в кластере через Kubernetes API Watch.
2.  **Выборка (Selection):** Ресурс `Prometheus` через `serviceMonitorSelector` определяет, какие именно мониторы должны быть загружены в конкретный экземпляр сервера.
3.  **Обнаружение (Service Discovery):** Оператор запрашивает Kubernetes API для поиска сервисов, соответствующих `spec.selector`, и извлекает их эндпоинты через `EndpointSlice` (предпочтительно) или `Endpoints`.
4.  **Генерация и Синхронизация:** Формируется конфигурация скрейпинга, которая записывается в Kubernetes Secret. Sidecar-контейнер `config-reloader` в поде Prometheus обнаруживает обновление и инициирует `/-/reload`.
5.  **Верификация (Status):** Через подресурс `status` можно проверить, был ли ресурс успешно принят оператором и применен к целевым инстансам Prometheus.

### Принцип работы и жизненный цикл

Процесс интеграции приложения в мониторинг включает следующие этапы:

1.  **Декларация:** Пользователь создает объект `ServiceMonitor` с указанием селектора Service и порта для скрейпинга.
2.  **Выборка:** Ресурс `Prometheus` через `serviceMonitorSelector` определяет, какие мониторы должны быть загружены.
3.  **Обнаружение:** Оператор находит соответствующие Service и извлекает IP-адреса эндпоинтов через Kubernetes API.
4.  **Генерация конфигурации:** Формируется секция `scrape_config` в `prometheus.yaml` на основе параметров эндпоинтов.
5.  **Монтирование:** Конфигурация записывается в Secret, который монтируется в под Prometheus.
6.  **Синхронизация:** Sidecar `prometheus-config-reloader` обнаруживает изменения и отправляет `/-/reload`.
7.  **Верификация:** Через подресурс `status` можно отследить успешность применения к целевым инстансам.

### Селекторы и изоляция конфигурации

Для того чтобы Prometheus загрузил `ServiceMonitor`, в спецификации ресурса `Prometheus` должны быть настроены селекторы:

| Селектор | Тип ресурса | Назначение |
| :--- | :--- | :--- |
| **`serviceMonitorSelector`** | `ServiceMonitor` | Фильтрует мониторы по меткам (labels). |
| **`serviceMonitorNamespaceSelector`** | `ServiceMonitor` | Определяет, в каких namespace искать мониторы. |

> **Ловушка «Пустого селектора»:** Если `serviceMonitorSelector: {}` — выбираются ВСЕ `ServiceMonitor` во ВСЕХ namespace, разрешенных `serviceMonitorNamespaceSelector`. Это может привести к взрывному росту количества целей. Для изоляции используйте явные `matchLabels`.

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **ServiceMonitor** | Описание целей | Декларативное описание того, откуда и как собирать метрики. |
| **Service** | Абстракция доступа | Kubernetes Service, через который Prometheus обнаруживает эндпоинты. |
| **EndpointSlice** | Топология целей | Объект, содержащий IP-адреса и порты эндпоинтов Service. |
| **Prometheus** | Агрегатор | Использует `serviceMonitorSelector` для выбора ServiceMonitor и генерации конфигурации. |
| **ConfigMap/Secret** | Конфигурация | Сгенерированный Operator файл конфигурации Prometheus. |
| **Alertmanager** | Доставка | Получает алерты от Prometheus (не связан напрямую с ServiceMonitor). |

### Когда использовать ServiceMonitor

*   **Stateless-микросервисы:** Стандарт для приложений за балансировщиком (Service).
*   **Стабильные интерфейсы:** Когда приложению требуется абстракция Service для связи с другими компонентами или внешнего доступа.
*   **Автоматическое масштабирование:** Новые реплики (Pods) автоматически попадают в мониторинг без изменения конфигурации.

> **Критическая деталь (Label Selector):** Для того чтобы Prometheus, установленный через Helm-чарт `kube-prometheus-stack`, обнаружил ваш `ServiceMonitor`, он **ОБЯЗАТЕЛЬНО** должен содержать метку, соответствующую селектору `serviceMonitorSelector` в ресурсе Prometheus (обычно `release: <имя_релиза>`). Без этого лейбла монитор будет игнорироваться.

### Подресурс `status` и `conditions`

ServiceMonitor имеет подресурс `status`, который содержит условия (`conditions`), описывающие состояние применения ресурса:

```yaml
status:
  conditions:
    - type: Reconciled
      status: "True"
      lastTransitionTime: "2025-09-15T10:00:00Z"
      reason: ReconciliationSucceeded
      message: "Successfully applied ServiceMonitor to 2 targets"
  targets:
    - namespace: production
      name: web-app
      endpoint: http
```

Если условие `Reconciled` имеет статус `False` или `Unknown` — Operator не смог применить конфигурацию. Проверьте логи оператора и корректность селекторов.

### Новые возможности (2025–2026)

*   **Prometheus 3.0+ Scrape Protocols:** Нативная поддержка `scrapeProtocols` (Protobuf, OTLP) для ускорения сбора данных и совместимости с OpenTelemetry.
*   **Native Histograms (v3.4+):** Поддержка разреженных гистограмм через `nativeHistogramBucketLimit` и флаг `convertHistogramsToNHCB` для автоматической конвертации классических гистограмм.
*   **Обогащение метаданными:** Параметр `attachMetadata.node` прикрепляет лейблы узла к метрикам, а `promoteScopeMetadata` переносит метаданные OTLP в лейблы Prometheus.
*   **ProxyConfig:** Гибкая настройка прокси-серверов через `proxyUrl`, `noProxy` и поддержку системных переменных окружения `proxyFromEnvironment`.
*   **Debug-инструменты:** Поле `keepDroppedTargets` позволяет сохранять в памяти Prometheus ограниченное количество целей, отсеченных правилами relabeling, для упрощения отладки.

## Практические сценарии

### Сценарий 1: Стандартный мониторинг с защитой от перегрузки

Сбор метрик с лимитами на количество сэмплов и лейблов для защиты TSDB.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: my-app
  endpoints:
    - port: http-metrics
      interval: 15s
      sampleLimit: 5000         # Лимит сэмплов на скрейп
      labelLimit: 50            # Лимит количества лейблов
      labelNameLengthLimit: 64
  namespaceSelector:
    matchNames:
      - production
      - staging
```

### Сценарий 2: Использование Prometheus 3.x и Native Histograms

Настройка для высокопроизводительного сбора метрик с автоматической конвертацией гистограмм.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: performance-app-monitor
spec:
  endpoints:
    - port: metrics
      scrapeProtocols: 
        - PrometheusProtobuf
        - OpenTelemetryProtobuf
      nativeHistogramBucketLimit: 160
      convertHistogramsToNHCB: true # Доступно с Prometheus 3.4+
      enableHttp2: true
  selector:
    matchLabels:
      app: high-load-service
```

### Сценарий 3: Защищенный скрейпинг через прокси

Конфигурация для работы в изолированных сетях с использованием корпоративного прокси.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: proxy-service-monitor
spec:
  endpoints:
    - port: https
      scheme: https
      proxyConfig:
        proxyUrl: http://squid.corp.internal:3128
        noProxy: "localhost,127.0.0.1,.internal.svc"
      tlsConfig:
        insecureSkipVerify: false
        ca:
          secret:
            name: root-ca
            key: ca.crt
  selector:
    matchLabels:
      env: restricted
```

### Сценарий 4: Обогащение данными узла и OTLP

Автоматическое добавление контекста инфраструктуры к метрикам приложения.

```yaml
spec:
  attachMetadata:
    node: true
  endpoints:
    - port: web
      promoteScopeMetadata: true # Перенос метаданных OTLP
      relabelings:
        - sourceLabels: [__meta_kubernetes_node_label_topology_kubernetes_io_zone]
          targetLabel: availability_zone
```

### Сценарий 5: Мультитенантность и изоляция сервисов через namespaceSelector

Разделение мониторинга между командами (tenants) с использованием отдельных namespace и селекторов.

```yaml
# Namespace: tenant-a
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: tenant-a-app-monitor
  labels:
    tenant: a
spec:
  selector:
    matchLabels:
      app: tenant-a-api
  endpoints:
    - port: http-metrics
      interval: 15s
  namespaceSelector:
    matchNames:
      - tenant-a
```

```yaml
# Namespace: monitoring
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: tenant-a
spec:
  serviceMonitorSelector:
    matchLabels:
      tenant: a
  serviceMonitorNamespaceSelector:
    matchNames:
      - tenant-a
```

### Сценарий 6: Сбор метрик с HTTPS-сервисов и валидация сертификатов

Настройка для внутренних сервисов с самоподписанными сертификатами.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: internal-https-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: internal-api
  endpoints:
    - port: https
      scheme: https
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
      tlsConfig:
        ca:
          secret:
            name: internal-ca
            key: ca.crt
        cert:
          secret:
            name: prometheus-client-cert
            key: tls.crt
        key:
          secret:
            name: prometheus-client-cert
            key: tls.key
        serverName: api.internal.example.com
```

### Сценарий 7: Мониторинг через Service с relabeling и фильтрацией метрик

Настройка сбора только критических метрик и обогащение их служебными лейблами.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: filtered-metrics-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: order-service
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
      metricRelabelings:
        - sourceLabels: [__name__]
          regex: (http_requests_total|http_request_duration_seconds|node_memory_MemAvailable_bytes)
          action: keep
        - sourceLabels: [__name__]
          targetLabel: __tmp_metric
        - targetLabel: team
          replacement: "platform"
        - targetLabel: environment
          replacement: "production"
      relabelings:
        - sourceLabels: [__meta_kubernetes_service_label_version]
          targetLabel: version
```

### Сценарий 8: Мониторинг нескольких портов одного Service

Сбор метрик с разных портов одного Kubernetes Service в одном ServiceMonitor.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: multi-port-service-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: multi-port-app
  endpoints:
    - port: http-metrics
      interval: 30s
      path: /metrics
    - port: grpc-metrics
      interval: 30s
      path: /metrics
      scheme: http
    - port: health
      interval: 60s
      path: /healthz
```

## Дополнительная информация

### Требования к правам (RBAC)

**ServiceAccount и Role для применения ServiceMonitor через CI/CD:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus-servicemonitor-applier
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: prometheus-servicemonitor-applier
  namespace: monitoring
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["servicemonitors"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["servicemonitors/status"]
    verbs: ["get", "update"]
  - apiGroups: [""]
    resources: ["services", "endpointslices"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: prometheus-servicemonitor-applier
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: prometheus-servicemonitor-applier
    namespace: monitoring
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: prometheus-servicemonitor-applier
```

**Права для Prometheus Server (читает ServiceMonitor):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-k8s-servicemonitors
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["servicemonitors"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services", "endpoints", "endpointslices", "pods"]
    verbs: ["get", "list", "watch"]
```

> **Примечание:** При использовании Helm-чарта `kube-prometheus-stack` RBAC создается автоматически. Для ручного деплоя или кастомных манифестов — создавайте объекты явно.

### Основные параметры спецификации

| Параметр | Описание | Особенности / Лимиты |
| :--- | :--- | :--- |
| **`serviceDiscoveryRole`** | Роль Service Discovery. | `Endpoints` (по умолчанию) или `EndpointSlice`. `EndpointSlice` предпочтительнее для кластеров с большим количеством целей. |
| **`jobLabel`** | Лейбл для имени job. | Позволяет использовать лейбл сервиса вместо дефолтного имени. |
| **`targetLabels`** | Копирование лейблов. | Копирует лейблы из Service в метрики (например, `version`). |
| **`podTargetLabels`** | Лейблы из Pod. | Копирует лейблы напрямую из пода в метрики. |
| **`sampleLimit`** | Жесткий лимит сэмплов. | Скрейп падает, если лимит превышен. |
| **`attachMetadata`** | Метаданные объектов. | Прикрепляет метаданные узла или пода к метрикам. |

### Параметры эндпоинтов (endpoints)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **`port`** | Имя или номер порта в Service. | **Обязательно**. |
| **`interval`** | Период скрейпинга. | `30s`. |
| **`scrapeTimeout`** | Таймаут ожидания ответа. | Не может быть больше `interval`. |
| **`honorLabels`** | Конфликты лейблов. | `false` (лейблы Prometheus важнее). |
| **`honorTimestamps`** | Временные метки приложения. | `true`. |
| **`scheme`** | Протокол (http/https). | Определяется автоматически. |
| **`path`** | Путь для сбора метрик. | `/metrics`. |
| **`params`** | Дополнительные query-параметры. | — |
| **`tlsConfig`** | TLS-конфигурация. | — |
| **`proxyConfig`** | Настройки прокси. | — |
| **`relabelings`** | Правила переименования меток. | — |
| **`metricRelabelings`** | Фильтрация/преобразование метрик. | — |

### Ограничения и крайние случаи

1.  **Имя порта vs номер порта:** В `endpoints.port` можно указать либо имя порта из Service, либо номер. Смешение подходов в одном ресурсе или несоответствие имени порта в Service приводит к ошибкам обнаружения. Рекомендуется использовать имена портов (Named Ports) для стабильности.
2.  **Пустой селектор:** `serviceMonitorSelector: {}` в ресурсе Prometheus выбирает ВСЕ ServiceMonitor во всех разрешенных namespace. Это может привести к взрывному росту количества целей и перегрузке Prometheus. Используйте явные `matchLabels` для изоляции.
3.  **EndpointSlice vs Endpoints:** В современных кластерах (K8s >= 1.21) используется `EndpointSlice`. Operator предпочитает `EndpointSlice` для снижения нагрузки на API. Если `EndpointSlice` недоступен, автоматически используется устаревший `Endpoints`.
4.  **Конфликты лейблов (`honorLabels`):** При `honorLabels: false` (по умолчанию) Prometheus перезаписывает лейблы приложения своими. При `honorLabels: true` приоритет имеют лейблы приложения, что может привести к дублированию метрик.
5.  **Лимит целей на скрейп:** Большое количество эндпоинтов в одном Service (сотни реплик) может создать пиковую нагрузку на Prometheus. Используйте `sampleLimit` и `labelLimit` для защиты TSDB.
6.  **CEL-валидация:** CEL-выражения проверяют только синтаксис, но не семантику конфигурации. Например, неверное имя порта будет принято CRD, но обнаружен только при попытке скрейпинга.
7.  **Задержка обновления эндпоинтов:** При масштабировании Deployment или rolling update новые поды могут не появиться в `EndpointSlice` несколько секунд. Это нормальное поведение Kubernetes, не является ошибкой Operator.
8.  **Горячая перезагрузка:** Изменения в ServiceMonitor применяются с задержкой до 60-90 секунд (время обнаружения изменений ConfigMap/Secret контейнером config-reloader).

### Валидация работоспособности

После создания или обновления ресурса `ServiceMonitor` выполните проверки:

```bash
# 1. Проверка статуса ресурса и условий
kubectl get servicemonitor app-monitor -n production -o yaml

# 2. Проверка условий (conditions)
kubectl get servicemonitor app-monitor -n production -o jsonpath='{.status.conditions[*].type}'
kubectl get servicemonitor app-monitor -n production -o jsonpath='{.status.conditions[?(@.type=="Reconciled")].status}'

# 3. Проверка целей в Prometheus UI
kubectl port-forward -n monitoring svc/prometheus-main 9090:9090
# Откройте http://localhost:9090/targets и найдите job по имени ServiceMonitor

# 4. Проверка логов Operator на предмет ошибок reconciliation
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100 | grep -i "servicemonitor" | tail -20

# 5. Проверка логов config-reloader
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50

# 6. Проверка загрузки конфигурации через API Prometheus
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job | startswith("servicemonitor"))'
```

### Типичные проблемы и устранение неполадок

#### Проблема 1: Цели не появляются в Prometheus

*   **Причина:** Несовпадение лейблов между `serviceMonitorSelector` в объекте Prometheus и `labels` в ServiceMonitor.
*   **Диагностика:**
    ```bash
    kubectl get servicemonitor --all-namespaces -o wide | grep release
    kubectl get prometheus main -n monitoring -o yaml | grep -A5 serviceMonitorSelector
    ```
*   **Решение:** Добавьте соответствующий лейбл в `ServiceMonitor.metadata.labels` или измените `serviceMonitorSelector` в объекте Prometheus.

#### Проблема 2: Скрейпинг возвращает ошибку 404

*   **Причина:** Неверный `path` или `port` в `endpoints`. Порт должен соответствовать имени или номеру в Service.
*   **Диагностика:**
    ```bash
    kubectl describe service my-app -n production | grep -A5 "Port:"
    kubectl get endpoints my-app -n production
    ```
*   **Решение:** Проверьте, что `endpoints.port` соответствует порту в Service, а `path` существует в приложении.

#### Проблема 3: Ошибка TLS-сертификата при скрейпинге

*   **Причина:** Неверная конфигурация `tlsConfig`, истекший сертификат или несовпадение `serverName`.
*   **Диагностика:**
    ```bash
    openssl s_client -connect my-app.production:443 -servername my-app.production
    ```
*   **Решение:** Проверьте `tlsConfig.ca`, `tlsConfig.cert`, `tlsConfig.key` и `serverName`. Убедитесь, что сертификат действует.

#### Проблема 4: Метрики содержат нежелательные лейблы (кардинальность)

*   **Причина:** Отсутствие `metricRelabelings` для фильтрации или `labelLimit` для ограничения.
*   **Диагностика:**
    ```bash
    curl -s http://localhost:9090/api/v1/series?match[]=up{job="my-app"}&limit=100 | jq '.data | length'
    ```
*   **Решение:** Добавьте `metricRelabelings` с `action: keep` для нужных метрик и `labelLimit` для ограничения количества лейблов.

#### Проблема 5: Скрейпинг работает слишком часто или редко

*   **Причина:** Неверный `interval` в ServiceMonitor или глобальный `scrape_interval` в Prometheus переопределяет локальный.
*   **Диагностика:**
    ```bash
    kubectl get prometheus main -n monitoring -o yaml | grep -A5 "scrapeInterval"
    ```
*   **Решение:** Убедитесь, что `endpoints.interval` не конфликтует с глобальными настройками. Локальный `interval` имеет приоритет.

#### Проблема 6: Скрейпинг через прокси возвращает ошибку соединения

*   **Причина:** Неверный `proxyUrl`, блокировка на файрволе или отсутствие маршрута до прокси.
*   **Диагностика:**
    ```bash
    kubectl exec -n monitoring prometheus-main-0 -- curl -x http://squid.corp.internal:3128 https://my-app.production/metrics -I
    ```
*   **Решение:** Проверьте доступность прокси из пода Prometheus, корректность `proxyUrl` и `noProxy`.

### Лучшие практики

1.  **Используйте явные селекторы:** Никогда не используйте пустой `serviceMonitorSelector: {}` в production. Всегда указывайте `matchLabels` для изоляции.
2.  **Используйте Named Ports:** В Service и ServiceMonitor указывайте имена портов (`name: http-metrics`), а не номера. Это повышает стабильность конфигурации при изменении портов.
3.  **Настраивайте лимиты:** Всегда добавляйте `sampleLimit`, `labelLimit`, `labelNameLengthLimit` для защиты TSDB от взрывного роста кардинальности.
4.  **Группируйте по namespace:** Размещайте ServiceMonitor в том же namespace, что и целевые сервисы, или используйте `namespaceSelector` для явного указания области.
5.  **Используйте `metricRelabelings`:** Фильтруйте ненужные метрики на стороне сбора, а не на стороне хранения. Это снижает потребление памяти и диска.
6.  **Настраивайте TLS для внутренних сервисов:** Если сервис использует HTTPS, всегда указывайте `tlsConfig.ca` для корректной валидации сертификата.
7.  **Храните в Git:** Все ServiceMonitor должны находиться в репозитории и доставляться через CI/CD. Это обеспечивает аудит и возможность отката.
8.  **Используйте `attachMetadata`:** Включайте `attachMetadata.node` для обогащения метрик информацией об узле, что упрощает диагностику проблем инфраструктуры.
9.  **Тестируйте перед деплоем:** Используйте `kubectl apply --dry-run=server` и проверяйте доступность эндпоинтов перед применением ServiceMonitor.
10. **Именуйте по стандарту:** Используйте паттерн `<service-name>-monitor` или `<team>-<service>-monitor` для однозначной идентификации.
11. **Настраивайте таймауты:** Для медленных сервисов устанавливайте `scrapeTimeout` явно, чтобы избежать накопления зависших скрейпов.
12. **Мониторьте мета-мониторинг:** Настройте алерты на `prometheus_sd_received_updates_total` и `prometheus_sd_discovered_targets` для отслеживания здоровья Service Discovery.

### См. также

*   **[Prometheus CRD](./prometheus.md)** — настройка селекторов и схем валидации имен.
*   **[PodMonitor CRD](./podmonitor.md)** — альтернативный метод мониторинга без использования Service.
*   **[Probe CRD](./probe.md)** — blackbox-мониторинг внешних эндпоинтов.
*   **[Prometheus Operator — Troubleshooting](../troubleshooting.md)** — глубокий анализ ошибок генерации конфигурации.
*   **[Service Discovery и Relabeling](../../service_discovery.md)** — основы механизмов переименования меток.

### См. также (внешние)

* [Prometheus Operator API Specification (v1)](https://prometheus-operator.dev/docs/operator/api/)
* [Prometheus 3.0 Scrape Protocols Documentation](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config)
