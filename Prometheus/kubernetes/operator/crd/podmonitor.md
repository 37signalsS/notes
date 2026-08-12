# PodMonitor — Концепции (CRD)

## Определения

**`kind: PodMonitor`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга метрик напрямую с подов Kubernetes. В отличие от `ServiceMonitor`, он не использует абстракцию Service для обнаружения эндпоинтов, а взаимодействует с Kubernetes API для получения IP-адресов подов напрямую. Это является основным механизмом (SSoT) для мониторинга сущностей без сетевой абстракции Service.

**Скрейпинг подов (Pod Scraping)** — механизм сбора метрик, при котором Prometheus обращается к каждому поду отдельно. Это критично для систем, где каждый экземпляр приложения имеет уникальное состояние или когда использование Service невозможно или избыточно.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [ServiceMonitor](./servicemonitor.md) — мониторинг через Service, [Prometheus CRD](./prometheus.md) — конфигурация сервера Prometheus.

## Базовые концепции

### Принцип работы

Процесс автоматизации сбора метрик через PodMonitor включает следующие этапы:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `PodMonitor` в кластере.
2.  **Обнаружение целей:** На основе `selector` и `namespaceSelector`, указанных в CRD, Оператор находит соответствующие поды через Kubernetes API.
3.  **Генерация конфигурации:** Оператор формирует секцию `scrape_config` в конфигурационном файле Prometheus, используя IP-адреса найденных подов.
4.  **Применение (Apply):** Обновленная конфигурация записывается в Secret, который монтируется в под Prometheus.
5.  **Перезагрузка:** Контейнер `prometheus-config-reloader` (sidecar) обнаруживает изменение Secret и отправляет сигнал `/-/reload` серверу Prometheus.

### Использование ScrapeClass (Helm-интеграция)

В современных инсталляциях (kube-prometheus-stack) используется механизм **ScrapeClass**. Он позволяет:
*   Централизованно управлять настройками (например, `relabelings` для обогащения метрик Node Exporter).
*   Применять общие правила ко всем PodMonitor, помеченным соответствующим классом.
*   Упростить конфигурацию в мультикластерных средах через `values.yaml` Helm-чарта.

### Когда использовать PodMonitor

*   **Stateful-приложения:** Базы данных (PostgreSQL, MongoDB), очереди сообщений (RabbitMQ), где важно отслеживать состояние каждого конкретного узла (шарда или реплики).
*   **DaemonSets:** Проверка локальных агентов на каждом узле кластера.
*   **Динамические топологии:** Системы с частым изменением количества реплик, где прямой скрейпинг исключает задержки обновления эндпоинтов в Service.
*   **Специфические порты:** Когда метрики отдаются на портах, которые не проброшены через Service для экономии ресурсов или безопасности.

### Сравнение с ServiceMonitor

| Характеристика | PodMonitor | ServiceMonitor |
| :--- | :--- | :--- |
| **Объект обнаружения** | Pod | Service |
| **Зависимость от Service** | Отсутствует | Обязательна |
| **Режим работы** | Прямой доступ к IP пода | Доступ через эндпоинты сервиса |
| **Meta-лейблы** | `__meta_kubernetes_pod_*` | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` |
| **Обнаружение Sidecars** | Проще (выбор порта пода) | Сложнее (требует Named Port в Service) |
| **Основной кейс** | Stateful-системы, инфраструктурные агенты | Stateless-микросервисы |

## Практические сценарии

### Сценарий 1: Базовая конфигурация для StatefulSet

Сбор метрик с каждого пода приложения в неймспейсе `production`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: database-monitor
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: my-database
  namespaceSelector:
    matchNames:
      - production
  podMetricsEndpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

### Сценарий 2: Использование OAuth2 и современной авторизации (2025+)

Настройка защищенного скрейпинга с использованием OAuth2.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: secure-app-monitor
spec:
  selector:
    matchLabels:
      app: secure-app
  podMetricsEndpoints:
    - port: https
      scheme: https
      oauth2:
        clientId:
          secret:
            name: oauth-credentials
            key: client-id
        clientSecret:
          name: oauth-credentials
          key: client-secret
        tokenUrl: https://auth.example.com/token
      tlsConfig:
        insecureSkipVerify: true
```

### Сценарий 3: Нативные гистограммы (Prometheus 3.0)

Настройка сбора высокоточных разреженных гистограмм.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: latency-monitor
spec:
  selector:
    matchLabels:
      app: high-traffic-service
  podMetricsEndpoints:
    - port: metrics
      nativeHistogramBucketLimit: 160
      nativeHistogramMinBucketFactor: 1.1
      scrapeClassicHistograms: false  # Отключить старые гистограммы для экономии места
```

### Сценарий 4: Обогащение метаданными нод (attachMetadata)

Добавление информации об узле (Node), на котором запущен под, для расширенного анализа.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: node-aware-monitor
spec:
  attachMetadata:
    node: true  # Требует прав list/watch на nodes у Prometheus ServiceAccount
  selector:
    matchLabels:
      app: worker
  podMetricsEndpoints:
    - port: metrics
      relabelings:
        - sourceLabels: [__meta_kubernetes_node_label_topology_kubernetes_io_zone]
          targetLabel: availability_zone
```

## Дополнительная информация

### Основные параметры спецификации

| Параметр | Описание | Особенности |
| :--- | :--- | :--- |
| **`selector`** | Селектор для поиска подов. | Обязательное поле. |
| **`namespaceSelector`** | Список неймспейсов для поиска. | `any: true` для поиска по всему кластеру. |
| **`jobLabel`** | Лейбл пода для имени `job`. | Если не задан, используется `<namespace>/<name>`. |
| **`podTargetLabels`** | Лейблы пода, переносимые в метрики. | Полезно для фильтрации в Grafana. |
| **`attachMetadata.node`** | Присоединение метаданных узла. | Требует Prometheus v2.35+. |
| **`sampleLimit`** | Лимит сэмплов на одну цель. | Защита от переполнения памяти (OOM). |
| **`targetLimit`** | Лимит количества целей. | Ограничение числа подов для скрейпинга. |
| **`scrapeProtocols`** | Приоритет протоколов скрейпинга. | OpenTelemetry-Proto, PrometheusText. |

### Параметры под-эндпоинтов (podMetricsEndpoints)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **`port`** | Имя порта контейнера. | Обязательно (имя, а не номер). |
| **`path`** | Путь к метрикам. | `/metrics`. |
| **`scheme`** | Протокол сбора данных. | `http` (доступен `https`). |
| **`interval`** | Частота опроса. | `30s` (стандарт чарта). |
| **`scrapeTimeout`** | Время ожидания ответа. | Должно быть `<= interval`. |
| **`honorLabels`** | Приоритет лейблов приложения. | `false` (лейблы таргета важнее). |
| **`tlsConfig`** | Настройка TLS для HTTPS. | Используется при `scheme: https`. |
| **`oauth2` / `authorization`** | Настройки аутентификации. | Взаимно исключают друг друга. |
| **`relabelings`** | Обработка таргетов ДО сбора. | Используется для фильтрации и модификации целей. |
| **`metricRelabelings`** | Обработка метрик ПОСЛЕ сбора. | Используется для удаления лишних метрик перед записью. |

### Различия Relabeling механизмов

*   **`relabelings`**: Применяются на этапе обнаружения целей (Service Discovery). С их помощью можно отфильтровать ненужные поды (`action: keep` или `drop`) или изменить мета-информацию о цели до того, как начнется опрос.
*   **`metricRelabelings`**: Применяются к уже полученным данным. Это основной инструмент для экономии места в TSDB путем удаления высококардинальных или ненужных метрик (`action: labeldrop`, `labelkeep`).

### Требования к правам (RBAC)

Для корректной работы расширенных функций Prometheus ServiceAccount должен обладать соответствующими правами в кластере:
*   **`attachMetadata.node: true`**: Требует прав `list` и `watch` на ресурс `nodes`.
*   **Стандартная работа**: Права `list` и `watch` на `pods` и `endpoints` в целевых неймспейсах.

### Диагностика

1.  **Проверка обнаружения подов:**
    `kubectl get podmonitor <name> -n <namespace> -o yaml` (проверьте поле `status`, если оно поддерживается версией оператора).
2.  **Проверка в UI Prometheus:**
    Меню `Status -> Targets`. Ищите job в формате `podMonitor/<namespace>/<name>/<index>`.
3.  **Логи Оператора:**
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator` — ищите ошибки с текстом `failed to generate config`.

### См. также

*   [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — основы обнаружения целей и механизмы трансформации меток.
*   [Prometheus Operator — Troubleshooting](../troubleshooting.md) — алгоритмы решения проблем с генерацией конфигурации и скрейпингом.
*   [Официальная спецификация PodMonitor](https://github.com/prometheus-operator/prometheus-operator/blob/main/Documentation/api.md#podmonitor) — полный список параметров API от разработчиков.
