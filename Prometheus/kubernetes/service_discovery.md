# Service Discovery в Kubernetes

> Эта заметка описывает специфику обнаружения сервисов в Kubernetes через нативную конфигурацию Prometheus. Для понимания общих принципов скрейпинга и механизмов `relabel_configs` сначала ознакомьтесь с разделом: **[Service Discovery и Relabeling](../service_discovery_and_relabeling.md)**.

## Определения

**Service Discovery (Обнаружение сервисов) в Kubernetes** — динамический процесс автоматического поиска целей (targets) для сбора метрик путем опроса Kubernetes API. Prometheus запрашивает список объектов кластера и использует их метаданные для формирования конфигурации скрейпинга.

**kubernetes_sd_configs** — основной блок в конфигурационном файле Prometheus, определяющий параметры взаимодействия с Kubernetes API и роли обнаруживаемых объектов.

**Relabeling** — механизм фильтрации и модификации меток (labels) на этапе обнаружения целей, позволяющий динамически изменять параметры скрейпинга (адрес, путь, протокол) на основе метаданных Kubernetes.

> **См. также:** [Prometheus Operator](./operator/concepts.md), [Обзор мониторинга Kubernetes](./overview.md), [Конфигурация Prometheus](../configuration.md).

## Основные концепции

### Конфигурация kubernetes_sd_configs

Блок `kubernetes_sd_configs` позволяет Prometheus подключаться к API-серверу и подписываться на изменения объектов. Настройка фильтрации на уровне API снижает нагрузку на API-сервер и уменьшает потребление памяти Prometheus, так как он не хранит информацию о ненужных целях.

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
        # Фильтрация по пространствам имен (опционально)
        namespaces:
          names: ['production', 'staging']
        # Фильтрация на уровне API через селекторы (опционально)
        selectors:
          - role: pod
            label: "monitor=true"
            field: "status.phase=Running"
```

#### Роли обнаружения

| Роль | Описание | Типичное применение |
| :--- | :--- | :--- |
| **node** | Обнаруживает один эндпоинт на каждый узел кластера. | Метрики Kubelet, cAdvisor, Node Exporter. |
| **pod** | Обнаруживает все поды и выставляет их IP как цели. | Sidecar-контейнеры, приложения без Service. |
| **service** | Обнаруживает каждый сервис и его порты. | Blackbox-мониторинг эндпоинта сервиса. |
| **endpoints** | Обнаруживает эндпоинты, связанные с сервисом. | Стандартный мониторинг приложений (наиболее часто). |
| **endpointslice** | Обнаруживает объекты EndpointSlice (масштабируемая замена Endpoints). | Рекомендуется для кластеров с >1000 подов. |
| **ingress** | Обнаруживает каждый путь в объектах Ingress. | Проверка доступности внешних маршрутов через Blackbox. |

### Метаданные обнаружения (Meta Labels)

Во время обнаружения Prometheus создает временные метки с префиксом `__meta_kubernetes_`. Они доступны для использования в `relabel_configs`, но отбрасываются после завершения этапа переименования, если не были явно скопированы в постоянные метки.

| Метка | Роль | Описание |
| :--- | :--- | :--- |
| `__meta_kubernetes_namespace` | Все | Пространство имен объекта. |
| `__meta_kubernetes_node_name` | Pod, Endpoints, Node | Имя узла, где находится цель. |
| `__meta_kubernetes_pod_name` | Pod, Endpoints | Имя пода. |
| `__meta_kubernetes_pod_ip` | Pod, Endpoints | Внутренний IP-адрес пода. |
| `__meta_kubernetes_pod_label_<name>` | Pod, Endpoints | Значение лейбла пода с именем `<name>`. |
| `__meta_kubernetes_pod_annotation_<name>` | Pod, Endpoints | Значение аннотации пода. |
| `__meta_kubernetes_pod_container_name` | Pod | Имя конкретного контейнера в поде. |
| `__meta_kubernetes_pod_container_port_name`| Pod | Имя порта контейнера. |
| `__meta_kubernetes_service_name` | Service, Endpoints | Имя сервиса. |
| `__meta_kubernetes_service_label_<name>` | Service, Endpoints | Значение лейбла сервиса. |
| `__meta_kubernetes_service_annotation_<name>`| Service, Endpoints | Значение аннотации сервиса. |
| `__meta_kubernetes_endpoint_address_target_name`| Endpoints | Имя целевого объекта эндпоинта (обычно под). |
| `__meta_kubernetes_endpoint_port_name` | Endpoints | Имя порта в эндпоинте. |
| `__meta_kubernetes_endpointslice_address_type` | EndpointSlice | Тип адреса (IPv4, IPv6, FQDN). |
| `__address__` | Все | IP-адрес и порт цели (по умолчанию). |

## Практические сценарии

### 1. Мониторинг API-сервера (Control Plane)

Kubernetes API-сервер представлен сервисом `kubernetes` в namespace `default`. Мы используем роль `endpoints` для его нахождения.

```yaml
- job_name: 'kubernetes-apiservers'
  kubernetes_sd_configs:
    - role: endpoints
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  relabel_configs:
    # Фильтруем только сервис kubernetes в default namespace и порт https
    - source_labels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name, __meta_kubernetes_endpoint_port_name]
      action: keep
      regex: default;kubernetes;https
```

### 2. Сбор метрик с Kubelet и cAdvisor

Kubelet предоставляет метрики самого себя (`/metrics`) и контейнеров (`/metrics/cadvisor`). Доступ к ним часто осуществляется через проксирование API-сервера для упрощения аутентификации.

```yaml
- job_name: 'kubernetes-nodes'
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  kubernetes_sd_configs:
    - role: node
  relabel_configs:
    # Копируем лейблы узла в метрики
    - action: labelmap
      regex: __meta_kubernetes_node_label_(.+)
    # Перенаправляем запрос на API-сервер
    - target_label: __address__
      replacement: kubernetes.default.svc:443
    # Формируем путь для проксирования к конкретной ноде
    - source_labels: [__meta_kubernetes_node_name]
      regex: (.+)
      target_label: __metrics_path__
      replacement: /api/v1/nodes/${1}/proxy/metrics
```

### 3. Сбор метрик по аннотациям (Standard Discovery)

Классический подход, при котором Prometheus автоматически скрейпит любые сервисы, имеющие определенные аннотации.

```yaml
- job_name: 'kubernetes-service-endpoints'
  kubernetes_sd_configs:
    - role: endpoints
  relabel_configs:
    # Скрейпим только если prometheus.io/scrape: "true"
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scrape]
      action: keep
      regex: true
    # Переопределяем схему (http/https) из аннотации
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scheme]
      action: replace
      target_label: __scheme__
      regex: (https?)
    # Переопределяем путь метрик
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_path]
      action: replace
      target_label: __metrics_path__
      regex: (.+)
    # Переопределяем порт (важно, если сервис имеет несколько портов)
    - source_labels: [__address__, __meta_kubernetes_service_annotation_prometheus_io_port]
      action: replace
      target_label: __address__
      regex: ([^:]+)(?::\d+)?;(\d+)
      replacement: $1:$2
    # Пробрасываем лейблы сервиса в метрики
    - action: labelmap
      regex: __meta_kubernetes_service_label_(.+)
    # Добавляем namespace и имя сервиса как постоянные метки
    - source_labels: [__meta_kubernetes_namespace]
      target_label: kubernetes_namespace
    - source_labels: [__meta_kubernetes_service_name]
      target_label: kubernetes_name
```

### 4. Blackbox-мониторинг сервисов

Проверка доступности HTTP эндпоинтов сервисов через внешний Blackbox Exporter.

```yaml
- job_name: 'kubernetes-services-blackbox'
  metrics_path: /probe
  params:
    module: [http_2xx]
  kubernetes_sd_configs:
    - role: service
  relabel_configs:
    # Скрейпим только если есть аннотация prometheus.io/probe: "true"
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_probe]
      action: keep
      regex: true
    # Передаем адрес сервиса в параметр target для Blackbox Exporter
    - source_labels: [__address__]
      target_label: __param_target
    # Указываем адрес самого Blackbox Exporter как адрес скрейпинга
    - target_label: __address__
      replacement: blackbox-exporter.monitoring.svc.cluster.local:9115
    # Сохраняем исходный адрес в метку instance
    - source_labels: [__param_target]
      target_label: instance
    # Добавляем метаданные сервиса
    - action: labelmap
      regex: __meta_kubernetes_service_label_(.+)
```

### 5. Обнаружение через ServiceMonitor и PodMonitor

В инфраструктуре с Prometheus Operator нативная конфигурация `kubernetes_sd_configs` скрыта за абстракциями CRD.

**Пример ServiceMonitor:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: monitoring
  labels:
    release: prometheus-stack # Метка для выбора Прометеусом
spec:
  selector:
    matchLabels:
      app: my-app # Селектор для поиска Service
  endpoints:
  - port: metrics # Имя порта в Service
    interval: 30s
    path: /metrics
```

**Преимущества ServiceMonitor:**
*   **Декларативность:** Описание мониторинга рядом с кодом приложения.
*   **Безопасность:** Operator сам управляет RBAC и секретами для скрейпинга.
*   **Автоматизация:** Не нужно вручную писать сложные `relabel_configs`.
*   **Масштабируемость:** Упрощенное управление сотнями приложений через GitOps.

> **См. также:** [ServiceMonitor CRD — детальное руководство](./operator/crd/servicemonitor.md).

## Дополнительная информация

### Детальная настройка Relabeling

`relabel_configs` — это мощный конвейер обработки. Понимание порядка действий критично.

| Действие (Action) | Описание | Типичный случай |
| :--- | :--- | :--- |
| `keep` | Оставляет только цели, соответствующие regex. | Фильтрация по аннотации `scrape: true`. |
| `drop` | Отбрасывает цели, соответствующие regex. | Игнорирование подов в `kube-system`. |
| `replace` | Заменяет значение метки или создает новую. | Изменение `__address__` или `__metrics_path__`. |
| `labelmap` | Копирует все метки, подходящие под regex, в новые метки. | Массовый проброс лейблов Kubernetes в Prometheus. |
| `labeldrop` | Удаляет метки, подходящие под regex. | Очистка отладочных или служебных меток. |
| `hashmod` | Вычисляет хэш и применяет остаток от деления. | **Шардирование:** распределение целей между несколькими серверами Prometheus. |

### Сравнение подходов к обнаружению

| Характеристика | Native SD (YAML) | ServiceMonitor (CRD) | Static Configs |
| :--- | :--- | :--- | :--- |
| **Сложность** | Высокая (нужен опыт с regex) | Низкая (декларативный YAML) | Минимальная |
| **Гибкость** | Максимальная (любые манипуляции) | Ограничена схемой CRD | Отсутствует |
| **Удобство для команд** | Низкое (одна большая конфиг-мапа) | Высокое (каждая команда владеет своим CRD) | Нулевое |
| **Производительность** | Высокая (при тонкой настройке) | Зависит от Operator | Максимальная |
| **Рекомендация** | Для Edge-кейсов и legacy | **Рекомендуемый стандарт** | Только для внешних систем |

### Нюансы масштабирования и безопасности

1.  **EndpointSlice:** В кластерах с тысячами подов стандартные `Endpoints` вызывают огромную нагрузку на API-сервер, так как при изменении одного пода пересылается список всех IP. `EndpointSlice` решает эту проблему, разбивая список на части. В Prometheus используйте `role: endpointslice`.
2.  **RBAC:** Для работы SD Prometheus должен иметь ClusterRole с правами `get`, `list`, `watch` на ресурсы `nodes`, `pods`, `services`, `endpoints`, `endpointslices`, `ingresses`.
3.  **Шардирование:** При достижении лимитов по CPU/RAM на одном сервере Prometheus, используйте действие `hashmod` в `relabel_configs` совместно с `kubernetes_sd_configs` для распределения скрейпинга подов между N инстансами Prometheus.
4.  **Field Selectors:** Используйте `selectors` в `kubernetes_sd_configs` для фильтрации полей на стороне API (например, `status.phase=Running`), чтобы Prometheus не тратил ресурсы на обработку упавших подов.

### Рекомендации

*   **Всегда используйте namespaces/selectors**, если мониторинг ограничен частью кластера.
*   **Не пробрасывайте все лейблы K8s** в метрики через `labelmap` без разбора — это может привести к взрывному росту кардинальности (high cardinality).
*   **Используйте ServiceMonitor** как основной инструмент, оставляя нативный SD для инфраструктурных задач (мониторинг самого K8s).
*   **Валидируйте TLS:** При мониторинге API-сервера или Kubelet всегда используйте `ca_file` и `bearer_token_file`.

> **См. также:** [Масштабирование Prometheus](../scaling/overview.md), [RBAC в Kubernetes](../../Security/rbac/rbac_overview.md).
