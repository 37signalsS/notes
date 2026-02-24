# Service Discovery в Kubernetes

> Эта заметка описывает специфику обнаружения сервисов в Kubernetes. Для понимания основных концепций Service Discovery и `relabel_configs`, пожалуйста, сначала ознакомьтесь с основной заметкой: **[service_discovery_and_relabeling](../service_discovery_and_relabeling.md)**.

## Определения

**Service Discovery (Обнаружение сервисов) в Kubernetes** — это механизм, который Prometheus использует для автоматического нахождения целей (таргетов) для сбора метрик путем взаимодействия с Kubernetes API-сервером. Он позволяет динамически получать информацию об объектах кластера (таких как поды, сервисы, ноды), которые предоставляют метрики.

## Основные концепции

Prometheus предоставляет два принципиально разных способа добавления источников данных (таргетов) для сбора метрик: статическая конфигурация и динамическое обнаружение сервисов (Service Discovery). В современных динамических средах, таких как Kubernetes, Service Discovery является ключевым подходом, позволяющим автоматически определять список целевых хостов для сбора метрик (скрейпинга).

### `kubernetes_sd_configs`

Этот блок конфигурации указывает Prometheus использовать API Kubernetes для обнаружения целей. Ключевым параметром является `role`, который определяет, какие типы объектов Kubernetes будут запрашиваться.

#### Роли в Kubernetes Service Discovery

* `endpoints`: Обнаруживает все объекты `Endpoints`, связанные с [сервисами](../../Kubernetes/Networking/Service/service_overview.md). Наиболее частая роль для мониторинга.
* `service`: Обнаруживает все объекты [Service](../../Kubernetes/Networking/Service/service_overview.md).
* `pod`: Обнаруживает все объекты [Pod](../../Kubernetes/Base/Pod/pod_overview.md).
* `node`: Обнаруживает все объекты `Node` кластера.
* `ingress`: Обнаруживает все объекты [Ingress](../../Kubernetes/Networking/Ingress/overview.md).

В зависимости от выбранной роли, Prometheus получает набор целей (targets) и обогащает их метаданными.

### Метаданные обнаружения (Discovery Labels)

Когда Prometheus обнаруживает цель через Kubernetes, он добавляет к ней множество метаданных, называемых "discovery labels". Эти метки начинаются с префикса `__meta_kubernetes_` и содержат информацию из API Kubernetes.

Примеры:

* `__meta_kubernetes_namespace`: [Пространство имен](../../Kubernetes/Base/namespace.md) объекта.
* `__meta_kubernetes_service_name`: Имя сервиса.
* `__meta_kubernetes_pod_name`: Имя пода.
* `__meta_kubernetes_node_name`: Имя ноды.
* `__meta_kubernetes_service_annotation_<annotation_name>`: Значение аннотации сервиса.
* `__address__`: Реальный адрес и порт цели.

Эти метаданные являются основой для динамической фильтрации и настройки целей с помощью `relabel_configs`.

### Фильтрация и модификация целей с помощью `relabel_configs`

`relabel_configs` — это мощный механизм для изменения меток целей *перед* сбором метрик. Он позволяет фильтровать цели (действия `keep`/`drop`), переименовывать и форматировать метки (`replace`). Его главная задача в Kubernetes — это работа с метаданными (`__meta_kubernetes_*`). Все основные параметры и подробные примеры (`labelmap`, `labeldrop`) находятся в главной заметке **[Service Discovery и Relabeling](../service_discovery_and_relabeling.md#4-продвинутые-детали-действия-relabel_configs)**, которая описывает его фундаментальные принципы работы.

## Практические сценарии

### Конфигурация сбора метрик (`scrape_configs`)

Основная логика обнаружения целей описывается в секции `scrape_configs` файла `prometheus.yml` (см. [конфигурацию Prometheus](../configuration.md)). Эта секция содержит список "заданий" (jobs), каждое из которых определяет, как находить и собирать метрики с определенной группы целей.

Каждое задание идентифицируется уникальным `job_name`.

#### Статическая конфигурация (`static_configs`)

Это самый простой способ определения целей. Он используется, когда цели имеют постоянные, неизменяемые адреса.

```yaml
- job_name: 'prometheus'
  static_configs:
    - targets: ['localhost:9090']
```

Такой подход не рекомендуется для динамических сред, но может быть полезен для мониторинга самого Prometheus или внешних стабильных ресурсов.

### Упрощенное обнаружение через Prometheus Operator (`ServiceMonitor`)

Хотя `kubernetes_sd_configs` и `relabel_configs` являются мощными нативными инструментами Prometheus, их настройка может быть сложной и громоздкой. В экосистеме `kube-prometheus-stack` (см. [обзор](../kubernetes/overview.md)) эту задачу решает **[Prometheus Operator](./operator.md)** с помощью Custom Resource Definition (CRD) (см. [Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)) под названием `ServiceMonitor`.

`ServiceMonitor` — это высокоуровневая абстракция, которая позволяет декларативно описать, какие сервисы нужно мониторить.

**Преимущества использования `ServiceMonitor`:**

* **Простота:** Вместо написания сложных правил `relabel`, вы создаете простой YAML-манифест.
* **Kubernetes-native:** Управление мониторингом происходит через стандартные `kubectl apply`, что идеально вписывается в [GitOps-подход](../../GitOps/GitOps_overview.md).
* **Автоматизация:** [Prometheus Operator](./operator.md) берет на себя всю работу по генерации и обновлению конфигурации Prometheus.

#### Принцип работы

1. Вы создаете `ServiceMonitor`, в котором указываете, за сервисами с какими **лейблами** (`selector`) и в каких **[пространствах имен](../../Kubernetes/Base/namespace.md)** (`namespaceSelector`) нужно следить.
2. [Prometheus Operator](./operator.md) обнаруживает этот `ServiceMonitor`.
3. Оператор автоматически генерирует соответствующий `scrape_config` для Prometheus, включая все необходимые `relabel_configs` для выбора нужных подов на основе `Endpoints` сервиса.
4. Конфигурация Prometheus автоматически обновляется.

#### Пример манифеста `ServiceMonitor`

Предположим, у вас есть приложение, чей `Service` имеет лейбл `app: my-app`, и метрики отдаются на порту с именем `web`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app-monitor
  labels:
    # Лейбл, по которому сам Prometheus Operator находит этот ServiceMonitor
    release: prometheus 
spec:
  selector:
    matchLabels:
      app: my-app # 1. Ищем сервисы с этим лейблом
  namespaceSelector:
    matchNames:
      - production # 2. Только в этом namespace
  endpoints:
  - port: web # 3. Собираем метрики с порта с именем 'web'
    interval: 15s
    path: /metrics
```

Создав этот ресурс, вы даете команду оператору автоматически добавить все поды сервиса `my-app` в цели для сбора метрик, без необходимости вручную прописывать `relabel_configs`.

### Практические примеры нативной конфигурации

Следующие примеры демонстрируют, как настраивать Service Discovery с использованием `kubernetes_sd_configs` напрямую. Это полезно для понимания низкоуровневых механизмов, которые Prometheus Operator автоматизирует.

#### 1. Динамическое обнаружение Kubernetes API-сервера

**Задача:** Динамически находить и мониторить все экземпляры Kubernetes API-сервера.

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

1. `role: endpoints`: Prometheus ищет объекты `Endpoints`.
2. `action: keep`: Сохраняются только те цели, которые соответствуют `regex`.
3. `regex: default;kubernetes;https`: Правило отбирает цели, у которых `namespace` равен `default`, имя сервиса — `kubernetes`, а имя порта — `https`. Это точно соответствует сервису API-сервера.
4. `scheme`, `tls_config`, `bearer_token_file`: Настраивается безопасное HTTPS-соединение с авторизацией для доступа к API.

#### 2. Сбор метрик с Kubelet (через прокси)

**Задача:** Собирать метрики с `kubelet` на каждой ноде кластера. Прямой доступ к `kubelet` часто закрыт, поэтому используется проксирование через API-сервер.

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

1. `role: node`: Prometheus обнаруживает все ноды в кластере.
2. `target_label: __address__`: Первое правило `relabel` подменяет адрес цели (`__address__`, который изначально указывает на kubelet) на адрес самого API-сервера (`kubernetes.default.svc:443`).
3. `target_label: __metrics_path__`: Второе правило `relabel` динамически формирует путь для запроса. Оно берет имя ноды из мета-метки `__meta_kubernetes_node_name` и подставляет его в URL для проксирования: `/api/v1/nodes/<имя-ноды>/proxy/metrics`.

В результате Prometheus обращается к API-серверу, который, в свою очередь, проксирует запрос к `kubelet` на нужной ноде.

#### 3. Динамический сбор метрик по аннотациям

**Задача:** Автоматически начинать сбор метрик с любого сервиса, который имеет определенную аннотацию.

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

**Объяснение:**
Эта конфигурация позволяет управлять сбором метрик с помощью аннотаций на объекте `Service`:

* `prometheus.io/scrape: "true"`: Включает сбор метрик для этого сервиса (`action: keep`).
* `prometheus.io/scheme: "https"`: Позволяет переопределить схему на `https`.
* `prometheus.io/path: "/my-metrics"`: Позволяет указать нестандартный путь к метрикам.
* `prometheus.io/port: "9091"`: Позволяет указать порт, с которого нужно собирать метрики.

#### 4. Мониторинг доступности сервисов с [Blackbox Exporter](../overview.md#blackbox-exporter)

**Задача:** Проверять доступность сервисов "снаружи" с помощью [Blackbox Exporter](../overview.md#blackbox-exporter).

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
      replacement: blackbox-exporter.example.com:9115 # Адрес Blackbox Exporter
    - source_labels: [__param_target]
      target_label: instance
```

**Объяснение:**

1. `role: service`: Prometheus обнаруживает объекты `Service`.
2. `prometheus.io/probe: "true"`: Мониторинг включается для сервисов с этой аннотацией.
3. `target_label: __param_target`: Адрес целевого сервиса (например, `my-app.default.svc:80`) передается Blackbox Exporter'у через параметр `target` в URL.
4. `replacement: blackbox-exporter...`: Сам Prometheus обращается не к сервису напрямую, а к Blackbox Exporter'у, который уже выполняет проверку.
