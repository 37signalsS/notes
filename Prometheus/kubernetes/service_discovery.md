# Обнаружение сервисов в Kubernetes (Service Discovery)

> Эта заметка описывает специфику обнаружения сервисов в Kubernetes через нативную конфигурацию Prometheus. Для понимания общих принципов скрейпинга и механизмов `relabel_configs` сначала ознакомьтесь с разделом: **[Service Discovery и Relabeling](../service_discovery_and_relabeling.md)**.

## Определения

**Service Discovery (Обнаружение сервисов) в Kubernetes** — динамический процесс автоматического поиска целей (targets) для сбора метрик путем периодического опроса Kubernetes API. Prometheus запрашивает актуальный список объектов и использует их метаданные (лейблы, аннотации, IP) для формирования конфигурации скрейпинга.

**kubernetes_sd_configs** — специализированный блок в конфигурации Prometheus, определяющий параметры взаимодействия с Kubernetes API-сервером. Позволяет фильтровать цели на стороне API, снижая нагрузку на Control Plane.

**Relabeling (Переименование метрик)** — конвейер обработки метаданных на этапе обнаружения. Позволяет отфильтровывать цели (`keep`/`drop`) и динамически изменять параметры подключения (`__address__`, `__scheme__`) до того, как данные попадут в TSDB.

**EndpointSlice** — современный (v1.21+) и масштабируемый ресурс Kubernetes для хранения информации о сетевых эндпоинтах. Является заменой устаревшего ресурса `Endpoints`, устраняя проблемы производительности в кластерах с тысячами подов.

> **См. также:** [Prometheus Operator](./operator/concepts.md), [Обзор мониторинга Kubernetes](./overview.md), [Конфигурация Prometheus](../configuration.md).

## Основные концепции

### Конфигурация kubernetes_sd_configs

Блок `kubernetes_sd_configs` позволяет Prometheus устанавливать Watch-соединение с API-сервером. В версиях Prometheus 3.x оптимизирована обработка неизменных объектов, что существенно снижает потребление RAM при скрейпинге больших сред.

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
        # Использование метаданных для обогащения (Prometheus 2.35+)
        attach_metadata:
          node: true
        # Фильтрация по пространствам имен
        namespaces:
          names: ['production', 'staging']
        # Селекторы на стороне API (Field/Label selectors)
        selectors:
          - role: pod
            label: "monitor=true"
            field: "status.phase=Running"
```

#### Роли обнаружения

| Роль | Описание | Рекомендация и применение |
| :--- | :--- | :--- |
| **node** | Один эндпоинт на каждый узел кластера. | Метрики Kubelet, cAdvisor, Node Exporter. |
| **pod** | Все поды и их IP-адреса. | Для sidecar-контейнеров или приложений без Service. |
| **service** | Обнаруживает порты самого Service (ClusterIP). | Blackbox-мониторинг балансировщика. |
| **endpoints** | Старый метод обнаружения подов через Service. | **Legacy:** вызывает нагрузку на API в больших кластерах. |
| **endpointslice** | Современный метод обнаружения через EndpointSlice. | **Standard:** использовать для всех приложений (K8s v1.21+). |
| **ingress** | Каждый путь (path) в объектах Ingress. | Проверка доступности внешних маршрутов. |

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
| `__meta_kubernetes_pod_container_name` | Pod, Endpoints | Имя конкретного контейнера в поде. |
| `__meta_kubernetes_pod_container_port_name`| Pod, Endpoints | Имя порта контейнера. |
| `__meta_kubernetes_pod_container_port_number`| Pod, Endpoints | Номер порта контейнера. |
| `__meta_kubernetes_service_name` | Service, Endpoints | Имя сервиса. |
| `__meta_kubernetes_service_label_<name>` | Service, Endpoints | Значение лейбла сервиса. |
| `__meta_kubernetes_service_annotation_<name>`| Service, Endpoints | Значение аннотации сервиса. |
| `__meta_kubernetes_endpoint_address_target_name`| Endpoints | Имя целевого объекта эндпоинта (обычно под). |
| `__meta_kubernetes_endpoint_port_name` | Endpoints | Имя порта в эндпоинте. |
| `__meta_kubernetes_endpointslice_address_type` | EndpointSlice | Тип адреса (IPv4, IPv6, FQDN). |
| `__meta_kubernetes_ingress_name` | Ingress | Имя объекта Ingress. |
| `__meta_kubernetes_ingress_scheme` | Ingress | Протокол (http/https) из правил Ingress. |
| `__address__` | Все | IP-адрес и порт цели (по умолчанию). |

## Практические сценарии

### 1. Мониторинг API-сервера (Control Plane)

Kubernetes API-сервер представлен сервисом `kubernetes` в namespace `default`. Мы используем роль `endpointslice` (или `endpoints`) для его нахождения.

```yaml
- job_name: 'kubernetes-apiservers'
  kubernetes_sd_configs:
    - role: endpointslice
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    # Проверка имени сервера (в K8s API сертификат выписан на это имя)
    server_name: kubernetes
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  relabel_configs:
    # Оставляем только сервис kubernetes в default namespace и порт https
    - source_labels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name, __meta_kubernetes_endpoint_port_name]
      action: keep
      regex: default;kubernetes;https
```

### 2. Сбор метрик с Kubelet и cAdvisor

Kubelet предоставляет системные метрики (`/metrics`) и метрики контейнеров (`/metrics/cadvisor`). Доступ через прокси API-сервера безопаснее, но требует прав RBAC.

```yaml
- job_name: 'kubernetes-nodes'
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  kubernetes_sd_configs:
    - role: node
      attach_metadata:
        node: true
  relabel_configs:
    # Маппинг лейблов узла в метрики
    - action: labelmap
      regex: __meta_kubernetes_node_label_(.+)
    # Перенаправление на API-сервер для проксирования
    - target_label: __address__
      replacement: kubernetes.default.svc:443
    - source_labels: [__meta_kubernetes_node_name]
      regex: (.+)
      target_label: __metrics_path__
      replacement: /api/v1/nodes/${1}/proxy/metrics/cadvisor
```

### 3. Обнаружение по аннотациям (Standard Discovery)

Универсальный паттерн для автоматического сбора метрик с любых приложений без правки конфига Prometheus.

```yaml
- job_name: 'kubernetes-service-endpoints'
  kubernetes_sd_configs:
    - role: endpointslice
  relabel_configs:
    # 1. Фильтрация: скрейпим только если аннотация prometheus.io/scrape == "true"
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scrape]
      action: keep
      regex: true
    # 2. Динамическая схема (http/https)
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scheme]
      action: replace
      target_label: __scheme__
      regex: (https?)
    # 3. Динамический путь (/metrics, /prometheus)
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_path]
      action: replace
      target_label: __metrics_path__
      regex: (.+)
    # 4. Переопределение порта
    - source_labels: [__address__, __meta_kubernetes_service_annotation_prometheus_io_port]
      action: replace
      target_label: __address__
      regex: ([^:]+)(?::\d+)?;(\d+)
      replacement: $1:$2
    # 5. Обогащение лейблами
    - action: labelmap
      regex: __meta_kubernetes_service_label_(.+)
    - source_labels: [__meta_kubernetes_namespace]
      target_label: namespace
    - source_labels: [__meta_kubernetes_service_name]
      target_label: service
```

### 4. Внешний мониторинг через Blackbox Exporter

Проверка доступности HTTP/TCP эндпоинтов сервисов "снаружи".

```yaml
- job_name: 'kubernetes-services-blackbox'
  metrics_path: /probe
  params:
    module: [http_2xx]
  kubernetes_sd_configs:
    - role: service
  relabel_configs:
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_probe]
      action: keep
      regex: true
    - source_labels: [__address__]
      target_label: __param_target
    - target_label: __address__
      replacement: blackbox-exporter.monitoring.svc.cluster.local:9115
    - source_labels: [__param_target]
      target_label: instance
```

### 5. Использование ServiceMonitor и ScrapeConfig (Operator)

Для сред с Prometheus Operator нативная конфигурация заменяется декларативными ресурсами.

**ScrapeConfig (v0.65+):** Позволяет использовать нативный синтаксис `kubernetes_sd_configs` внутри ресурсов Оператора для сложных случаев.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-sd-example
spec:
  kubernetesSDConfigs:
    - role: Pod
  relabelConfigs:
    - action: keep
      sourceLabels: [__meta_kubernetes_pod_label_app]
      regex: custom-app
```

> **См. также:** [ServiceMonitor CRD — детали](./operator/crd/servicemonitor.md), [PodMonitor CRD](./operator/crd/podmonitor.md).

## Дополнительная информация

### Детальная настройка Relabeling

`relabel_configs` — это мощный конвейер обработки. Понимание порядка действий критично для эффективной фильтрации.

| Действие (Action) | Описание | Типичный случай |
| :--- | :--- | :--- |
| `keep` | Оставляет только цели, соответствующие regex. | Фильтрация по аннотации `scrape: true`. |
| `drop` | Отбрасывает цели, соответствующие regex. | Игнорирование системных неймспейсов. |
| `replace` | Заменяет значение метки или создает новую. | Изменение `__address__` или схемы. |
| `labelmap` | Копирует все метки, подходящие под regex, в новые метки. | Проброс лейблов K8s в метрики. |
| `labeldrop` | Удаляет метки, подходящие под regex. | Очистка служебных меток перед записью в TSDB. |
| `hashmod` | Вычисляет хэш и применяет остаток от деления. | **Шардирование:** распределение нагрузки. |

### Безопасность и RBAC

Для работы SD Prometheus должен иметь права на чтение объектов API. Пример ClusterRole для корректной работы всех ролей обнаружения:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-sd
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/proxy", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["discovery.k8s.io"]
  resources: ["endpointslices"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch"]
- nonResourceURLs: ["/metrics"]
  verbs: ["get"]
```

### Масштабирование и шардирование

При достижении лимитов по CPU/RAM на одном сервере Prometheus используется **шардирование** — распределение целей между несколькими инстансами.

**Пример конфигурации для шардирования (Шард №1 из 2):**
```yaml
relabel_configs:
  - source_labels: [__address__]
    modulus: 2    # Общее количество шардов
    target_label: __tmp_hash
    action: hashmod
  - source_labels: [__tmp_hash]
    regex: 0      # Индекс текущего шарда (0 для первого, 1 для второго)
    action: keep
```

### Нюансы эксплуатации

1.  **EndpointSlice:** В кластерах с >500 узлами использование роли `endpoints` может приводить к лагам API из-за огромного размера объектов Endpoints. Всегда предпочитайте `endpointslice`.
2.  **Field Selectors:** Для снижения нагрузки на Prometheus используйте фильтрацию на стороне API через `selectors` в `kubernetes_sd_configs` (например, не скрейпить поды в статусе `Pending`).
3.  **Кардинальность:** Ограничивайте использование `labelmap`. Массовый проброс лейблов из Kubernetes (особенно динамических, вроде `pod-template-hash`) может привести к взрывному росту временных рядов.

### Рекомендации

*   **Используйте namespaces/selectors**, чтобы ограничить область видимости Prometheus только нужными сегментами.
*   **Используйте ServiceMonitor** как стандарт де-факто для приложений, оставляя нативный SD для инфраструктурного мониторинга.
*   **Валидируйте TLS:** При мониторинге API-сервера или Kubelet всегда используйте `ca_file` и `server_name` для предотвращения MITM.
*   **EndpointSlice:** Это единственный путь для масштабирования в 2026 году.

> **См. также:** [Масштабирование Prometheus](../scaling/overview.md), [RBAC в Kubernetes](../../Kubernetes/Security/rbac/rbac_overview.md).
