# ServiceMonitor — Концепции (CRD)

## Определения

**`kind: ServiceMonitor`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга (scraping targets) на основе Kubernetes Service. Это основной механизм обнаружения приложений в стеке мониторинга, который абстрагирует сложность конфигурации `kubernetes_sd_configs`.

**Discovery-паттерн** — процесс автоматического обнаружения эндпоинтов сервиса. В отличие от статического перечисления IP-адресов, `ServiceMonitor` позволяет динамически подключать новые поды приложения к мониторингу сразу после их запуска.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [PodMonitor CRD](./podmonitor.md) — мониторинг подов напрямую, [Prometheus CRD](./prometheus.md) — конфигурация сервера Prometheus.

## Базовые концепции

### Принцип работы и жизненный цикл

Процесс интеграции приложения в мониторинг через ServiceMonitor включает следующие этапы:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `ServiceMonitor`.
2.  **Выборка (Selection):** Ресурс `Prometheus` через `serviceMonitorSelector` определяет, какие именно мониторы должны быть загружены в конкретный экземпляр сервера.
3.  **Обнаружение (Service Discovery):** Оператор запрашивает Kubernetes API для поиска сервисов, соответствующих `spec.selector`, и извлекает их эндпоинты (Endpoints или EndpointSlice).
4.  **Генерация:** Формируется итоговая конфигурация скрейпинга (`scrape_config`), которая записывается в Kubernetes Secret.
5.  **Перезагрузка:** Sidecar-контейнер `config-reloader` инициирует обновление конфигурации Prometheus без остановки процесса.

### Когда использовать ServiceMonitor

*   **Stateless-микросервисы:** Стандарт для приложений за балансировщиком (Service).
*   **Стабильные интерфейсы:** Когда приложению требуется абстракция Service для связи с другими компонентами.
*   **Автоматическое масштабирование:** Новые реплики (Pods) автоматически попадают в мониторинг через механизм Endpoints.

### Новые возможности (2025–2026)

*   **Prometheus 3.0 Ready:** Поддержка `scrapeProtocols` (включая Protobuf для ускорения сбора данных) и `fallbackScrapeProtocol`.
*   **Нативные гистограммы:** Возможность сбора высокоточных разреженных гистограмм через `scrapeNativeHistograms` (требует Prometheus >= 3.0).
*   **EndpointSlice:** Явное управление механизмом обнаружения через `serviceDiscoveryRole` для снижения нагрузки на API в крупных кластерах.
*   **Обогащение метаданными:** Параметр `attachMetadata.node` позволяет автоматически прикреплять лейблы узла к метрикам приложения.
*   **ProxyConfig:** Нативная настройка прокси-сервера для скрейпинга эндпоинтов напрямую в CRD.

## Практические сценарии

### Сценарий 1: Стандартный мониторинг приложения

Сбор метрик с сервиса с именем порта `http-metrics` во всех неймспейсах.

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
      app.kubernetes.io/name: my-cool-app
  namespaceSelector:
    any: true
  endpoints:
    - port: http-metrics
      interval: 15s
      path: /metrics
```

### Сценарий 2: Использование Prometheus 3.0 и Protobuf

Настройка сбора данных в бинарном формате для снижения нагрузки на CPU и сеть.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: modern-app-monitor
spec:
  endpoints:
    - port: metrics
      scrapeProtocols: 
        - PrometheusProto
        - OpenMetricsText1.0.0
      scrapeNativeHistograms: true
  selector:
    matchLabels:
      app: performance-critical
```

### Сценарий 3: Защищенный скрейпинг (mTLS + OAuth2)

Конфигурация для сбора метрик с сервиса, требующего авторизации.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-service-monitor
spec:
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        ca:
          secret:
            name: trusted-ca
            key: ca.crt
      oauth2:
        clientId:
          secret:
            name: monitoring-oauth
            key: id
        clientSecret:
          name: monitoring-oauth
          key: secret
        tokenUrl: https://auth.corp.local/token
  selector:
    matchLabels:
      security: high
```

### Сценарий 4: Обогащение данными узла (attachMetadata)

Позволяет группировать метрики приложения по параметрам сервера (например, Availability Zone).

```yaml
spec:
  attachMetadata:
    node: true
  endpoints:
    - port: web
      relabelings:
        - sourceLabels: [__meta_kubernetes_node_label_topology_kubernetes_io_zone]
          targetLabel: region
```

## Дополнительная информация

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности (2026) |
| :--- | :--- | :--- |
| **`serviceDiscoveryRole`** | Механизм поиска эндпоинтов. | `Endpoints` или `EndpointSlice`. |
| **`jobLabel`** | Лейбл сервиса для имени job. | По умолчанию берется из имени Service. |
| **`targetLabels`** | Перенос лейблов сервиса в метрики. | Помогает сохранить контекст (env, team). |
| **`sampleLimit`** | Лимит сэмплов на один скрейп. | Защита Prometheus от "тяжелых" целей. |
| **`scrapeProtocols`** | Приоритет протоколов. | Доступно в Prometheus 3.0+. |

### Параметры эндпоинтов (endpoints)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **`port`** | Имя порта в объекте Service. | Обязательно (не номер порта). |
| **`interval`** | Частота опроса. | `30s` (настраивается в Helm). |
| **`scrapeTimeout`** | Время ожидания ответа. | Должно быть `<= interval`. |
| **`honorLabels`** | Приоритет лейблов приложения. | `false` (Prometheus имеет приоритет). |
| **`proxyConfig`** | Настройка прокси. | Введено в v0.84. |

### Диагностика

1.  **Проверка обнаружения сервиса:**
    `kubectl get servicemonitor <name> -n <namespace> -o yaml` — проверьте поле `status` (если включен подресурс status).
2.  **Проверка в UI Prometheus:**
    Меню `Status -> Targets`. Ищите job в формате `serviceMonitor/<namespace>/<name>/<index>`.
3.  **Логи оператора:**
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator` — ищите ошибки `failed to generate config`.

### Связанные темы

*   **[Service Discovery и Relabeling](../../service_discovery.md)** — основы обнаружения целей в Kubernetes.
*   **[Prometheus Operator — Troubleshooting](../troubleshooting.md)** — решение проблем с генерацией конфигурации.
*   **[Reliability Scores](../../../GEMINI.md)** — методология оценки достоверности (Score: 10).

### См. также
* [Официальная спецификация ServiceMonitor](https://github.com/prometheus-operator/prometheus-operator/blob/main/Documentation/api.md#servicemonitor)
* [Документация Prometheus 3.0: Scrape Protocols](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config)
