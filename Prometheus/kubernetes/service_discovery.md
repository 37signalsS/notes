# Service Discovery в Kubernetes

> Эта заметка описывает специфику обнаружения сервисов в Kubernetes. Для понимания основных концепций Service Discovery и `relabel_configs`, пожалуйста, сначала ознакомьтесь с основной заметкой: **[Service Discovery и Relabeling](../service_discovery_and_relabeling.md)**.

## Определения

**Service Discovery (Обнаружение сервисов) в Kubernetes** — механизм автоматического нахождения целей для сбора метрик через Kubernetes API. Позволяет динамически получать информацию об объектах кластера (поды, сервисы, ноды).

> **См. также:** [Prometheus Operator](./operator/concepts.md), [Configuration](../configuration.md).

## Основные концепции

### kubernetes_sd_configs

Блок конфигурации для использования Kubernetes API:

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
```

#### Роли в Kubernetes Service Discovery

| Роль | Описание |
|---|---|
| **endpoints** | Обнаружение Endpoint объектов (чаще всего) |
| **service** | Обнаружение Service объектов |
| **pod** | Обнаружение Pod объектов |
| **node** | Обнаружение Node объектов |
| **ingress** | Обнаружение Ingress объектов |

### Метаданные обнаружения (Discovery Labels)

Метаданные с префиксом `__meta_kubernetes_`:

| Метка | Описание |
|---|---|
| `__meta_kubernetes_namespace` | Namespace объекта |
| `__meta_kubernetes_service_name` | Имя сервиса |
| `__meta_kubernetes_pod_name` | Имя пода |
| `__meta_kubernetes_node_name` | Имя ноды |
| `__meta_kubernetes_service_annotation_<name>` | Значение аннотации сервиса |
| `__meta_kubernetes_pod_label_<label>` | Значение лейбла пода |
| `__address__` | Адрес и порт цели |

## Практические сценарии

### 1. Динамическое обнаружение API-сервера

**Задача:** Мониторинг Kubernetes API-сервера:

```yaml
- job_name: 'kubernetes-api-servers'
  kubernetes_sd_configs:
    - role: endpoints
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  relabel_configs:
    - source_labels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name, __meta_kubernetes_endpoint_port_name]
      action: keep
      regex: default;kubernetes;https
```

**Объяснение:**

1. `role: endpoints` — поиск Endpoint объектов
2. `action: keep` с `regex` — фильтрация по namespace, сервису и порту
3. `scheme: https` + `tls_config` — безопасное соединение

### 2. Сбор метрик с Kubelet

**Задача:** Мониторинг kubelet на всех нодах через API-сервер:

```yaml
- job_name: 'kubernetes-nodes'
  kubernetes_sd_configs:
    - role: node
  scheme: https
  tls_config:
    ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  relabel_configs:
    - action: labelmap
      regex: __meta_kubernetes_node_label_(.+)
    - target_label: __address__
      replacement: kubernetes.default.svc:443
    - source_labels: [__meta_kubernetes_node_name]
      regex: (.+)
      target_label: __metrics_path__
      replacement: /api/v1/nodes/${1}/proxy/metrics
```

**Объяснение:**

1. `role: node` — обнаружение всех нод
2. `__address__` → `kubernetes.default.svc:443` — замена адреса на API-сервер
3. `__metrics_path__` — формирование пути для проксирования

### 3. Сбор метрик по аннотациям

**Задача:** Автоматический сбор метрик с сервисов по аннотациям:

```yaml
- job_name: 'kubernetes-service-endpoints'
  kubernetes_sd_configs:
    - role: endpoints
  relabel_configs:
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scrape]
      action: keep
      regex: "true"
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scheme]
      action: replace
      target_label: __scheme__
      regex: (https?)
    - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_path]
      action: replace
      target_label: __metrics_path__
      regex: (.+)
    - source_labels: [__address__, __meta_kubernetes_service_annotation_prometheus_io_port]
      action: replace
      target_label: __address__
      regex: ([^:]+)(?::\d+)?;(\d+)
      replacement: $1:$2
```

**Использование аннотаций на Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/scheme: "https"
    prometheus.io/path: "/metrics"
    prometheus.io/port: "8080"
```

### 4. Blackbox-мониторинг сервисов

**Задача:** Проверка доступности сервисов через Blackbox Exporter:

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
      regex: "true"
    - source_labels: [__address__]
      target_label: __param_target
    - target_label: __address__
      replacement: blackbox-exporter.monitoring.svc.cluster.local:9115
    - source_labels: [__param_target]
      target_label: instance
```

**Использование:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  annotations:
    prometheus.io/probe: "true"
```

> **См. также:** [Blackbox Exporter](../Exporters/blackbox/blackbox_exporter_installation_and_setup.md).

### 5. Упрощенное обнаружение через ServiceMonitor

**Вместо нативной конфигурации используйте ServiceMonitor:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: production
  labels:
    release: monitoring  # Важно для Helm
spec:
  selector:
    matchLabels:
      app: my-app
  namespaceSelector:
    matchNames:
      - production
  endpoints:
    - port: web
      interval: 15s
      path: /metrics
```

**Преимущества:**

* Простота декларативной конфигурации
* Автоматическая генерация scrape_config
* Интеграция с GitOps
* Не требует ручного написания relabel_configs

> **См. также:** [Prometheus Operator](../../GitOps/ArgoCD/synchronization/concepts.md).

## Дополнительная информация

### Relabel configs

`relabel_configs` — механизм фильтрации и модификации меток перед скрейпингом:

| Действие | Описание |
|---|---|
| `keep` | Сохранить цели, соответствующие regex |
| `drop` | Удалить цели, соответствующие regex |
| `replace` | Заменить/добавить метку |
| `labelmap` | Создать метки из discovery labels |
| `labeldrop` | Удалить метки по regex |
| `hashmod` | Хэширование для шардирования |

> **См. также:** [Service Discovery и Relabeling](../service_discovery_and_relabeling.md).

### Сравнение подходов

| Подход | Сложность | Гибкость | Рекомендация |
|---|---|---|---|
| **Нативный (kubernetes_sd_configs)** | Высокая | Максимальная | Для сложных сценариев |
| **ServiceMonitor/PodMonitor** | Низкая | Ограниченная | Для большинства случаев |
| **Static configs** | Минимальная | Отсутствует | Только для стабильных целей |

### Рекомендации

**Используйте ServiceMonitor/PodMonitor когда:**

* Работаете в Kubernetes
* Хотите простую декларативную конфигурацию
* Используете GitOps

**Используйте нативный подход когда:**

* Нужна максимальная гибкость
* Сложные правила фильтрации
* Интеграция с внешними системами

### Связанные темы

* [Prometheus Operator](./operator/concepts.md) — автоматизация через CRD
* [Overview](./overview.md) — обзор мониторинга в Kubernetes
* [Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — основные концепции
* [Configuration](../configuration.md) — настройка Prometheus
* [Blackbox Exporter](../Exporters/blackbox/blackbox_exporter_installation_and_setup.md) — blackbox-мониторинг
