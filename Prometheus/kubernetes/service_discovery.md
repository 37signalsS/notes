# Обнаружение сервисов в Kubernetes (Service Discovery)

> Эта заметка описывает специфику обнаружения сервисов в Kubernetes через нативную конфигурацию Prometheus. Для понимания общих принципов скрейпинга и механизмов `relabel_configs` сначала ознакомьтесь с разделом: **[Service Discovery и Relabeling](../service_discovery_and_relabeling.md)**.

## Определения

**Service Discovery (Обнаружение сервисов) в Kubernetes** — динамический процесс автоматического поиска целей (targets) для сбора метрик путем периодического опроса Kubernetes API. Prometheus запрашивает актуальный список объектов и использует их метаданные (лейблы, аннотации, IP) для формирования конфигурации скрейпинга.

**kubernetes_sd_configs** — специализированный блок в конфигурации Prometheus, определяющий параметры взаимодействия с Kubernetes API-сервером. Позволяет фильтровать цели на стороне API, снижая нагрузку на Control Plane.

**Relabeling (Переименование метрик)** — конвейер обработки метаданных на этапе обнаружения. Позволяет отфильтровывать цели (`keep`/`drop`) и динамически изменять параметры подключения (`__address__`, `__scheme__`) до того, как данные попадут в TSDB.

**EndpointSlice** — современный (v1.21+) и масштабируемый ресурс Kubernetes для хранения информации о сетевых эндпоинтах. Является заменой устаревшего ресурса `Endpoints`, устраняя проблемы производительности в кластерах с тысячами подов.

**attach_metadata** — механизм Prometheus (с версии 2.35+), автоматически добавляющий метаданные узла или пода к собранным метрикам. Позволяет обогатить метрики информацией о зоне доступности, роли узла и других атрибутах без ручного relabeling.

**PodMonitor** — CRD в Prometheus Operator для декларативного прямого скрейпинга подов без абстракции Service. Используется для stateful-приложений, DaemonSet и sidecar-контейнеров. Подробнее: [PodMonitor CRD](./operator/crd/podmonitor.md).

**Probe** — CRD для декларативного описания blackbox-проверок внешних эндпоинтов (HTTP, TCP, ICMP, DNS, gRPC). Позволяет управлять доступностью URL и сервисов через Blackbox Exporter без нативного kubernetes_sd_configs.

**ScrapeConfig** — CRD (v0.65+), позволяющий использовать нативный синтаксис `kubernetes_sd_configs` внутри ресурсов Prometheus Operator для сложных случаев, не покрываемых ServiceMonitor/PodMonitor (например, внешние статические цели или специфичные настройки Discovery).

> **См. также:** [Prometheus Operator](./operator/concepts.md), [Обзор мониторинга Kubernetes](./overview.md), [Конфигурация Prometheus](../configuration.md).

## Основные концепции

### Конфигурация kubernetes_sd_configs

Блок `kubernetes_sd_configs` позволяет Prometheus устанавливать Watch-соединение с API-сервером. В версиях Prometheus 3.x оптимизирована обработка неизмененных объектов, что существенно снижает потребление RAM при скрейпинге больших сред.

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

#### attach_metadata

Параметр `attach_metadata` автоматически добавляет метаданные к собранным метрикам без ручного relabeling:

```yaml
attach_metadata:
  node: true    # Добавляет __meta_kubernetes_node_label_* и __meta_kubernetes_node_name
```

**Поддерживаемые варианты:**
*   `node` — метаданные узла (лейблы, имя, регион, зона доступности).
*   `pod` — метаданные пода (имя, namespace, IP, readiness).

**Примечание:** Использование `attach_metadata` требует дополнительных прав RBAC для Prometheus ServiceAccount:
*   `attach_metadata.node: true` — требует `list`/`watch` на ресурсе `nodes`.
*   `attach_metadata.pod: true` — требует `list`/`watch` на ресурсе `pods`.

#### Селекторы на стороне API (selectors)

Для снижения нагрузки на Control Plane используйте фильтрацию на стороне API. Prometheus передает селекторы напрямую в Kubernetes API, и API-сервер возвращает только подходящие объекты.

| Тип селектора | Синтаксис в `kubernetes_sd_configs` | Пример использования |
| :--- | :--- | :--- |
| **Label Selector** | `label: "app=my-app"` | Выбор подов с определенным лейблом. |
| **Field Selector** | `field: "status.phase=Running"` | Исключение подов в статусе Pending/Failed. |
| **Combined** | Оба поля одновременно | Минимизация ответа API и снижение RAM на Prometheus. |

**Пример с комбинированной фильтрацией:**
```yaml
selectors:
  - role: pod
    label: "prometheus.io/scrape=true"
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
| `__meta_kubernetes_node_label_<name>` | Pod, Endpoints, Node | Значение лейбла узла (требуется attach_metadata.node). |
| `__meta_kubernetes_pod_name` | Pod, Endpoints | Имя пода. |
| `__meta_kubernetes_pod_ip` | Pod, Endpoints | Внутренний IP-адрес пода. |
| `__meta_kubernetes_pod_host_ip` | Pod, Endpoints | IP хоста, на котором запущен под. |
| `__meta_kubernetes_pod_ready` | Pod, Endpoints | Статус готовности пода (`true`/`false`). |
| `__meta_kubernetes_pod_phase` | Pod, Endpoints | Фаза жизненного цикла пода (`Running`, `Pending`, `Succeeded`, `Failed`, `Unknown`). |
| `__meta_kubernetes_pod_label_<name>` | Pod, Endpoints | Значение лейбла пода с именем `<name>`. |
| `__meta_kubernetes_pod_annotation_<name>` | Pod, Endpoints | Значение аннотации пода. |
| `__meta_kubernetes_pod_container_name` | Pod, Endpoints | Имя конкретного контейнера в поде. |
| `__meta_kubernetes_pod_container_port_name`| Pod, Endpoints | Имя порта контейнера. |
| `__meta_kubernetes_pod_container_port_number`| Pod, Endpoints | Номер порта контейнера. |
| `__meta_kubernetes_service_name` | Service, Endpoints | Имя сервиса. |
| `__meta_kubernetes_service_label_<name>` | Service, Endpoints | Значение лейбла сервиса. |
| `__meta_kubernetes_service_annotation_<name>`| Service, Endpoints | Значение аннотации сервиса. |
| `__meta_kubernetes_service_port_name` | Service, Endpoints | Имя порта сервиса. |
| `__meta_kubernetes_endpoint_address_target_name`| Endpoints | Имя целевого объекта эндпоинта (обычно под). |
| `__meta_kubernetes_endpoint_port_name` | Endpoints | Имя порта в эндпоинте. |
| `__meta_kubernetes_endpointslice_address_type` | EndpointSlice | Тип адреса (IPv4, IPv6, FQDN). |
| `__meta_kubernetes_ingress_name` | Ingress | Имя объекта Ingress. |
| `__meta_kubernetes_ingress_scheme` | Ingress | Протокол (http/https) из правил Ingress. |
| `__address__` | Все | IP-адрес и порт цели (по умолчанию). |

### Альтернативные механизмы обнаружения (CRD)

В средах с Prometheus Operator нативная конфигурация `kubernetes_sd_configs` часто заменяется декларативными CRD, которые генерируют эквивалентную конфигурацию автоматически:

| CRD | Назначение | Когда использовать |
| :--- | :--- | :--- |
| **ServiceMonitor** | Обнаружение через Service (EndpointSlice/Endpoints) | Основной механизм для stateless-приложений за балансировщиком. |
| **PodMonitor** | Прямой скрейпинг подов по IP | Stateful-системы, DaemonSet, sidecar-контейнеры без Service. |
| **Probe** | Blackbox-проверки внешних эндпоинтов | Внешние URL, Ingress, TCP-порты. |
| **ScrapeConfig** | Нативный `kubernetes_sd_configs` внутри Operator | Сложные сценарии: внешние статические цели, специфичные настройки Discovery. |

> **См. также:** [ServiceMonitor CRD — детали](./operator/crd/servicemonitor.md), [PodMonitor CRD](./operator/crd/podmonitor.md), [Probe CRD](./operator/crd/probe.md).

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

**В Prometheus 3.0+:** Обратите внимание, что Prometheus больше не добавляет порты по умолчанию (80/443). Убедитесь, что `__address__` и `__metrics_path__` сформированы корректно.

### 3. Обнаружение по аннотациям (Standard Discovery)

Универсальный паттерн для автоматического сбора метрик с любых приложений без правки конфига Prometheus.

```yaml
- job_name: 'kubernetes-service-endpoints'
  kubernetes_sd_configs:
    - role: endpointslice
      # Фильтрация на стороне API: только Running поды
      selectors:
        - role: pod
          field: "status.phase=Running"
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

### 4. Мониторинг kube-state-metrics

Kube-State-Metrics (KSM) генерирует метрики на основе состояния объектов Kubernetes API (Deployments, Pods, PV/PVC), которые нельзя получить изнутри контейнеров.

```yaml
- job_name: 'kubernetes-kube-state-metrics'
  kubernetes_sd_configs:
    - role: endpointslice
      namespaces:
        names: ['kube-system', 'monitoring']
      selectors:
        - role: service
          label: "app.kubernetes.io/name=kube-state-metrics"
  relabel_configs:
    - source_labels: [__meta_kubernetes_service_name]
      regex: kube-state-metrics
      action: keep
    - source_labels: [__meta_kubernetes_service_port_http-metrics]
      regex: .*
      action: keep
    - action: labelmap
      regex: __meta_kubernetes_service_label_(.+)
    - source_labels: [__meta_kubernetes_namespace]
      target_label: namespace
```

### 5. Мониторинг CoreDNS

CoreDNS критически важен для работы Service Discovery внутри кластера. Ее метрики собираются через ServiceDiscovery.

```yaml
- job_name: 'kubernetes-coredns'
  kubernetes_sd_configs:
    - role: endpointslice
      namespaces:
        names: ['kube-system']
      selectors:
        - role: service
          label: "k8s-app=kube-dns"
  relabel_configs:
    - source_labels: [__meta_kubernetes_service_name]
      regex: kube-dns
      action: keep
    - source_labels: [__meta_kubernetes_service_port_metrics]
      regex: .*
      action: keep
    - action: labelmap
      regex: __meta_kubernetes_service_label_(.+)
    - source_labels: [__meta_kubernetes_namespace]
      target_label: namespace
```

### 6. Мониторинг статических подов Control Plane (etcd, API server)

Компоненты Control Plane в кластерах kubeadm запускаются как Static Pods на мастер-узлах с `hostNetwork: true`. Они не имеют стандартного Kubernetes Service, поэтому для их обнаружения создается Headless Service и EndpointSlice вручную.

```yaml
- job_name: 'kubernetes-etcd'
  kubernetes_sd_configs:
    - role: endpointslice
      namespaces:
        names: ['kube-system']
      selectors:
        - role: service
          label: "k8s-app=etcd"
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    cert_file: /etc/prometheus/secrets/etcd-client/tls.crt
    key_file: /etc/prometheus/secrets/etcd-client/tls.key
  relabel_configs:
    - source_labels: [__meta_kubernetes_service_name]
      regex: etcd-k8s
      action: keep
    - source_labels: [__meta_kubernetes_service_port_https-metrics]
      regex: .*
      action: keep
```

**Важно:** Для доступа к метрикам etcd требуются клиентские TLS-сертификаты. Подробнее: [Мониторинг etcd через kube-prometheus-stack](./Kube_Prometheus_Stack_Helm/etcd-monitoring.md).

### 7. Внешний мониторинг через Blackbox Exporter

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

### 8. Использование ServiceMonitor, PodMonitor, Probe и ScrapeConfig (Operator)

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
      namespaces:
        names: ['production']
      selectors:
        - role: pod
          label: "app=custom-app"
          field: "status.phase=Running"
  relabelConfigs:
    - action: keep
      sourceLabels: [__meta_kubernetes_pod_label_app]
      regex: custom-app
    - action: labelmap
      regex: __meta_kubernetes_pod_label_(.+)
```

**PodMonitor (для прямого скрейпинга подов):**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: database-monitor
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: my-database
  namespaceSelector:
    matchNames:
      - production
  attachMetadata:
    node: true
  podMetricsEndpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

**Probe (для blackbox-мониторинга):**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: ingress-probe
  labels:
    release: prometheus-stack
spec:
  jobName: ingress-probe
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
    scheme: http
  timeout: 5s
  interval: 30s
  module: http_2xx
  targets:
    staticConfig:
      static:
        - api.example.com
        - app.example.com/healthz
```

> **См. также:** [ServiceMonitor CRD — детали](./operator/crd/servicemonitor.md), [PodMonitor CRD](./operator/crd/podmonitor.md), [Probe CRD](./operator/crd/probe.md).

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

**Важно (Prometheus 3.0+):** В веб-интерфейсе доступен визуальный отладчик релейблинга (**Relabeling Debugger**), позволяющий отследить трансформацию меток по шагам.

### Безопасность и RBAC

Для работы SD Prometheus должен иметь права на чтение объектов API. Пример ClusterRole для корректной работы всех ролей обнаружения:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-sd
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/proxy", "services", "endpoints", "endpointslices", "pods"]
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

В Prometheus Operator шардирование настраивается через параметр `spec.shards` в ресурсе `Prometheus`, что автоматически распределяет цели между репликами.

### Особенности Prometheus 3.x в Service Discovery

В мажорной версии 3.x (актуальной на 2026 год) произошел ряд качественных изменений:

*   **Event-driven SD Manager:** Механизм стал полностью событийным. Если в Kubernetes или Consul не произошло изменений, Prometheus не пересчитывает цели, что экономит до 30-40% ресурсов CPU на больших инсталляциях.
*   **Отсутствие портов по умолчанию:** Prometheus больше не пытается угадать порт на основе схемы (80 для http, 443 для https). Если порт не передан через SD или не указан явно в `__address__`, скрейпинг может завершиться ошибкой.
*   **Нативная поддержка UTF-8:** Метки теперь могут содержать любые символы Юникода. Это позволяет использовать человекочитаемые теги без транслитерации.
*   **Scrape Protocols:** Возможность явного выбора приоритета протоколов (`scrapeProtocols`) для оптимизации сбора данных.

### Мониторинг работоспособности Service Discovery

После настройки SD выполните базовые проверки:

```bash
# 1. Проверка обнаружения целей в Prometheus API
kubectl port-forward -n monitoring svc/prometheus-main 9090:9090 &
curl -s "http://localhost:9090/api/v1/targets" | jq '.data.activeTargets | length'
curl -s "http://localhost:9090/api/v1/targets" | jq '.data.activeTargets[] | select(.labels.job | startswith("kubernetes"))'

# 2. Проверка в UI Prometheus
# Откройте http://localhost:9090/targets — все цели должны быть в состоянии UP

# 3. Проверка логов Prometheus на предмет ошибок SD
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus | grep -i "error\|failed\|sd" | tail -20

# 4. Проверка прав RBAC
kubectl auth can-i list endpointslices --namespace production --as system:serviceaccount:monitoring:prometheus
kubectl auth can-i list pods --namespace production --as system:serviceaccount:monitoring:prometheus
```

**Ключевые метрики для мониторинга SD:**
```promql
# Количество активных целей по job
count by (job) (up{job=~"kubernetes.*"})

# Ошибки обнаружения
prometheus_sd_received_updates_total{job="kubernetes-service-endpoints"}

# Обнаруженные цели
prometheus_sd_discovered_targets{job="kubernetes-service-endpoints"}

# Размер конфигурации
prometheus_config_last_reload_success_timestamp_seconds < time() - 300
```

### Нюансы эксплуатации

1.  **EndpointSlice:** В кластерах с >500 узлами использование роли `endpoints` может приводить к лагам API из-за огромного размера объектов Endpoints. Всегда предпочитайте `endpointslice`.
2.  **Field Selectors:** Для снижения нагрузки на Prometheus используйте фильтрацию на стороне API через `selectors` в `kubernetes_sd_configs` (например, не скрейпить поды в статусе `Pending`).
3.  **Кардинальность:** Ограничивайте использование `labelmap`. Массовый проброс лейблов из Kubernetes (особенно динамических, вроде `pod-template-hash`) может привести к взрывному росту временных рядов.
4.  **attach_metadata:** Используйте `attachMetadata.node` для инфраструктурных метрик (Node Exporter, Kubelet), но избегайте его для прикладных сервисов, где метки узла не несут смысла.
5.  **Race Condition при скрейпинге:** При быстром масштабировании Deployment новые поды могут не появиться в EndpointSlice несколько секунд. Это нормальное поведение Kubernetes. Убедитесь, что интервал скрейпинга не короче 10 секунд.
6.  **Prometheus 3.0+ Port Defaults:** В версии 3.0+ Prometheus больше не добавляет порты по умолчанию. Если `__address__` не содержит порт, скрейпинг завершится ошибкой. Всегда проверяйте формирование `__address__` в конфигурации.

### Диагностика и типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Цели не появляются в Prometheus** | Несовпадение лейблов в `serviceMonitorSelector`, неправильный порт или путь | Проверьте `kubectl get servicemonitor -o yaml` и селекторы в ресурсе `Prometheus` |
| **OOMKilled Prometheus** | Превышение лимитов RAM при высокой кардинальности | Увеличьте `resources.limits.memory`, настройте `sample_limit` и `metric_relabel_configs` |
| **Скрейпинг возвращает 404** | Неверный `path` или `port` в `endpoints` | Проверьте `kubectl describe service <name> -n <ns> \| grep -A5 "Port:"` |
| **TLS-ошибка при скрейпинге** | Неверный `server_name`, истекший сертификат или несовпадение CA | Проверьте `ca_file` и `server_name` в `tls_config` |
| **Цели в статусе Down** | NetworkPolicy блокирует трафик, под не готов | Проверьте `kubectl get networkpolicy`, статус пода (`kubectl get pod <pod> -o wide`) |
| **DNS NXDOMAIN** | Кастомный `dnsPolicy` без корректных nameservers | Проверьте `dnsConfig` в спецификации Prometheus, статус CoreDNS |
| **EndpointSlice не обновляется** | Проблема с Endpoints controller или Readiness Probe | Проверьте `kubectl describe endpointslices -l kubernetes.io/service-name=<svc>`, логи kube-controller-manager |
| **Config-reloader ошибка** | Некорректный синтаксис YAML или отсутствуют права на Secret | Проверьте `kubectl logs -c config-reloader`, выполните `promtool check config` |
| **Медленное обновление целей** | Большой кластер, частые изменения, низкий `refresh_interval` | Увеличьте `refresh_interval` в `kubernetes_sd_configs` или настройте селекторы для фильтрации на стороне API |

### Рекомендации

*   **Используйте `endpointslice` роль** как стандарт для всех приложений (K8s v1.21+). Это единственный путь для масштабирования в 2026 году.
*   **Используйте `namespaces` и `selectors`**, чтобы ограничить область видимости Prometheus только нужными сегментами и снизить нагрузку на API-сервер.
*   **Используйте ServiceMonitor/PodMonitor/Probe** как стандарт де-факто для приложений, оставляя нативный SD для инфраструктурного мониторинга (Kubelet, API server).
*   **Валидируйте TLS:** При мониторинге API-сервера или Kubelet всегда используйте `ca_file` и `server_name` для предотвращения MITM.
*   **Используйте `attach_metadata.node`** для обогащения метрик инфраструктурными лейблами (зона, регион, роль узла).
*   **Контролируйте кардинальность:** Используйте `labeldrop` и `metric_relabel_configs` для удаления неиспользуемых мета-лейблов перед записью в TSDB.
*   **Настраивайте `scrape_interval` не менее 15s** для стандартных сервисов и не более 60s для инфраструктурных метрик.

> **См. также:** [Масштабирование Prometheus](../scaling/overview.md), [RBAC в Kubernetes](../../Kubernetes/Security/rbac/rbac_overview.md), [Service Discovery и Relabeling — общий обзор](../service_discovery_and_relabeling.md).
