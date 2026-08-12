# ServiceMonitor — Концепции (CRD)

## Определения

**`kind: ServiceMonitor`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга (scraping targets) на основе Kubernetes Service. Это основной механизм обнаружения приложений в стеке мониторинга, который абстрагирует сложность конфигурации `kubernetes_sd_configs`.

**Discovery-паттерн** — процесс автоматического обнаружения эндпоинтов сервиса. В отличие от статического перечисления IP-адресов, `ServiceMonitor` позволяет динамически подключать новые поды приложения к мониторингу сразу после их запуска через абстракцию Endpoints или EndpointSlice.

**API version:** `monitoring.coreos.com/v1`

> **Справочная информация:** [PodMonitor CRD](./podmonitor.md) — мониторинг подов напрямую, [Prometheus CRD](./prometheus.md) — конфигурация сервера Prometheus.

## Базовые концепции

### Принцип работы и жизненный цикл

Процесс интеграции приложения в мониторинг включает следующие этапы:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `ServiceMonitor`.
2.  **Выборка (Selection):** Ресурс `Prometheus` через `serviceMonitorSelector` определяет, какие именно мониторы должны быть загружены в конкретный экземпляр сервера.
3.  **Обнаружение (Service Discovery):** Оператор запрашивает Kubernetes API для поиска сервисов, соответствующих `spec.selector`, и извлекает их эндпоинты.
4.  **Генерация и Синхронизация:** Формируется конфигурация скрейпинга, которая записывается в Kubernetes Secret. Sidecar-контейнер `config-reloader` в поде Prometheus обнаруживает обновление и инициирует `/-/reload`.
5.  **Верификация (Status):** Через подресурс `status` (в версиях 2025+) можно проверить, был ли ресурс успешно принят оператором и применен к целевым инстансам Prometheus.

### Когда использовать ServiceMonitor

*   **Stateless-микросервисы:** Стандарт для приложений за балансировщиком (Service).
*   **Стабильные интерфейсы:** Когда приложению требуется абстракция Service для связи с другими компонентами или внешнего доступа.
*   **Автоматическое масштабирование:** Новые реплики (Pods) автоматически попадают в мониторинг без изменения конфигурации.

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

## Дополнительная информация

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности / Лимиты |
| :--- | :--- | :--- |
| **`serviceDiscoveryRole`** | Роль SD. | `Endpoints` (по умолчанию) или `EndpointSlice`. |
| **`jobLabel`** | Лейбл для имени job. | Позволяет использовать лейбл сервиса вместо дефолтного имени. |
| **`targetLabels`** | Копирование лейблов. | Копирует лейблы из Service в метрики (например, `version`). |
| **`podTargetLabels`** | Лейблы из Pod. | Копирует лейблы напрямую из пода в метрики. |
| **`sampleLimit`** | Жесткий лимит сэмплов. | Скрейп падает, если лимит превышен. |

### Параметры эндпоинтов (endpoints)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **`port`** | Имя порта в Service. | **Обязательно**. |
| **`interval`** | Период скрейпинга. | `30s`. |
| **`scrapeTimeout`** | Таймаут ожидания. | Не может быть больше `interval`. |
| **`honorLabels`** | Конфликты лейблов. | `false` (лейблы Prometheus важнее). |
| **`honorTimestamps`** | Временные метки приложения. | `true`. |

### Диагностика

1.  **Проверка статуса применения:**
    `kubectl get servicemonitor <name> -o jsonpath='{.status.conditions}'` — ищите подтверждение от оператора.
2.  **Проверка в UI Prometheus:**
    `Status -> Targets`. Путь к цели: `serviceMonitor/<namespace>/<name>/<endpoint_index>`.
3.  **Отладка отфильтрованных целей:**
    Если включено `keepDroppedTargets`, проверьте вкладку `Dropped Targets` в UI Prometheus для анализа работы `relabelingConfigs`.

### Связанные темы

*   **[Service Discovery и Relabeling](../../service_discovery.md)** — основы механизмов переименования меток.
*   **[Prometheus Operator — Troubleshooting](../troubleshooting.md)** — глубокий анализ ошибок генерации конфигурации.
*   **[PodMonitor CRD](./podmonitor.md)** — альтернативный метод мониторинга без использования Service.

### См. также
* [Prometheus Operator API Specification (v1)](https://prometheus-operator.dev/docs/operator/api/)
* [Prometheus 3.0 Scrape Protocols Documentation](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config)
