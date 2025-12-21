> Эта заметка описывает специфику обнаружения сервисов в Kubernetes. Для понимания основных концепций Service Discovery и `relabel_configs`, пожалуйста, сначала ознакомьтесь с основной заметкой: **[[../service_discovery_and_relabeling.md]]**.

# Обнаружение сервисов (Service Discovery)

Prometheus предоставляет два принципиально разных способа добавления источников данных (таргетов) для сбора метрик: статическая конфигурация и динамическое обнаружение сервисов (Service Discovery).

В то время как статическая конфигурация требует ручного перечисления всех эндпоинтов, **Service Discovery** является одним из самых мощных механизмов Prometheus. Он позволяет автоматически определять список целевых хостов для сбора метрик (скрейпинга), а также то, откуда Prometheus может получить информацию об этих хостах. Ключевое преимущество такого подхода — при добавлении новых хостов, соответствующих критериям, сбор метрик с них начинается автоматически. В современных динамических средах, таких как облака и Kubernetes, где инфраструктура постоянно меняется, эта возможность крайне востребована.

## Типы источников для Service Discovery

Можно выделить два основных типа источников данных для Service Discovery:

1.  **На основе файлов (`file_sd_config`):** В качестве источника данных выступает локальный файл (в формате YAML или JSON), в котором перечислены таргеты. Это похоже на статическую конфигурацию, но с ключевым отличием: Prometheus динамически перечитывает этот файл, что позволяет обновлять список целей без перезапуска самого сервера Prometheus.
2.  **На основе API провайдеров:** В этом случае Prometheus получает данные для обнаружения сервисов напрямую из API различных провайдеров. Список поддерживаемых интеграций очень велик и включает в себя Azure, Amazon EC2, Kubernetes, Consul, OpenStack и многие другие.

Помимо списка хостов, Prometheus получает от провайдера и **метаданные** для каждого таргета (например, регион, тип инстанса, теги). В дальнейшем эти метаданные можно преобразовывать в лейблы метрик, что позволяет создавать более гибкие визуализации и правила алертинга (например, группируя по региону).

## Service Discovery в Kubernetes

Для Kubernetes используется `kubernetes_sd_configs`. Этот механизм позволяет Prometheus обращаться к Kubernetes API-серверу и запрашивать информацию об объектах кластера.

## Конфигурация сбора метрик (`scrape_configs`)

Основная логика обнаружения целей описывается в секции `scrape_configs` файла `prometheus.yml`. Эта секция содержит список "заданий" (jobs), каждое из которых определяет, как находить и собирать метрики с определенной группы целей.

Каждое задание идентифицируется уникальным `job_name`.

### Статическая конфигурация (`static_configs`)

Это самый простой способ определения целей. Он используется, когда цели имеют постоянные, неизменяемые адреса.

```yaml
- job_name: 'prometheus'
  static_configs:
    - targets: ['localhost:9090']
```

Такой подход не рекомендуется для динамических сред, но может быть полезен для мониторинга самого Prometheus или внешних стабильных ресурсов.

## `kubernetes_sd_configs`

Этот блок конфигурации указывает Prometheus использовать API Kubernetes для обнаружения целей. Ключевым параметром является `role`, который определяет, какие типы объектов Kubernetes будут запрашиваться.

### Роли в Kubernetes Service Discovery

*   `endpoints`: Обнаруживает все объекты `Endpoints`. Наиболее частая роль для мониторинга сервисов.
*   `service`: Обнаруживает все объекты `Service`.
*   `pod`: Обнаруживает все объекты `Pod`.
*   `node`: Обнаруживает все объекты `Node`.
*   `ingress`: Обнаруживает все объекты `Ingress`.

В зависимости от выбранной роли, Prometheus получает набор целей (targets) и обогащает их метаданными.

### Метаданные обнаружения (Discovery Labels)

Когда Prometheus обнаруживает цель через Kubernetes, он добавляет к ней множество метаданных, называемых "discovery labels". Эти метки начинаются с префикса `__meta_kubernetes_` и содержат информацию из API Kubernetes.

Примеры:
*   `__meta_kubernetes_namespace`: Пространство имен объекта.
*   `__meta_kubernetes_service_name`: Имя сервиса.
*   `__meta_kubernetes_pod_name`: Имя пода.
*   `__meta_kubernetes_node_name`: Имя ноды.
*   `__meta_kubernetes_service_annotation_<annotation_name>`: Значение аннотации сервиса.
*   `__address__`: Реальный адрес и порт цели.

Эти метаданные являются основой для динамической фильтрации и настройки целей с помощью `relabel_configs`.

## Фильтрация и модификация целей с помощью `relabel_configs`

`relabel_configs` — это мощный механизм, позволяющий изменять метки целей *перед* сбором метрик. Он позволяет фильтровать цели, переименовывать метки и динамически настраивать параметры сбора.

Основные параметры правила `relabel_configs`:
*   `source_labels`: Список исходных меток, значения которых объединяются.
*   `regex`: Регулярное выражение, применяемое к значению из `source_labels`.
*   `action`: Действие, выполняемое при совпадении `regex`.
    *   `keep`: Сохранить цель, если `regex` совпадает.
    *   `drop`: Отбросить цель, если `regex` совпадает.
    *   `replace`: Заменить значение `target_label` на основе `replacement`.
*   `target_label`: Целевая метка для изменения.
*   `replacement`: Строка для замены, может использовать группы захвата из `regex` (например, `$1`).

---

## Упрощенное обнаружение через Prometheus Operator (`ServiceMonitor`)

Хотя `kubernetes_sd_configs` и `relabel_configs` являются мощными нативными инструментами Prometheus, их настройка может быть сложной и громоздкой. В экосистеме `kube-prometheus-stack` эту задачу решает **Prometheus Operator** с помощью Custom Resource Definition (CRD) под названием `ServiceMonitor`.

`ServiceMonitor` — это высокоуровневая абстракция, которая позволяет декларативно описать, какие сервисы нужно мониторить.

**Преимущества использования `ServiceMonitor`:**
*   **Простота:** Вместо написания сложных правил `relabel`, вы создаете простой YAML-манифест.
*   **Kubernetes-native:** Управление мониторингом происходит через стандартные `kubectl apply`, что идеально вписывается в GitOps-подход.
*   **Автоматизация:** Prometheus Operator берет на себя всю работу по генерации и обновлению конфигурации Prometheus.

### Принцип работы

1.  Вы создаете `ServiceMonitor`, в котором указываете, за сервисами с какими **лейблами** (`selector`) и в каких **пространствах имен** (`namespaceSelector`) нужно следить.
2.  Prometheus Operator обнаруживает этот `ServiceMonitor`.
3.  Оператор автоматически генерирует соответствующий `scrape_config` для Prometheus, включая все необходимые `relabel_configs` для выбора нужных подов на основе `Endpoints` сервиса.
4.  Конфигурация Prometheus автоматически обновляется.

### Пример манифеста `ServiceMonitor`

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

## Практические примеры нативной конфигурации

Следующие примеры демонстрируют, как настраивать Service Discovery с использованием `kubernetes_sd_configs` напрямую. Это полезно для понимания низкоуровневых механизмов, которые Prometheus Operator автоматизирует.

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
1.  `role: endpoints`: Prometheus ищет объекты `Endpoints`.
2.  `action: keep`: Сохраняются только те цели, которые соответствуют `regex`.
3.  `regex: default;kubernetes;https`: Правило отбирает цели, у которых `namespace` равен `default`, имя сервиса — `kubernetes`, а имя порта — `https`. Это точно соответствует сервису API-сервера.
4.  `scheme`, `tls_config`, `bearer_token_file`: Настраивается безопасное HTTPS-соединение с авторизацией для доступа к API.

### 2. Сбор метрик с Kubelet (через прокси)

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
1.  `role: node`: Prometheus обнаруживает все ноды в кластере.
2.  `target_label: __address__`: Первое правило `relabel` подменяет адрес цели (`__address__`, который изначально указывает на kubelet) на адрес самого API-сервера (`kubernetes.default.svc:443`).
3.  `target_label: __metrics_path__`: Второе правило `relabel` динамически формирует путь для запроса. Оно берет имя ноды из мета-метки `__meta_kubernetes_node_name` и подставляет его в URL для проксирования: `/api/v1/nodes/<имя-ноды>/proxy/metrics`.

В результате Prometheus обращается к API-серверу, который, в свою очередь, проксирует запрос к `kubelet` на нужной ноде.

### 3. Динамический сбор метрик по аннотациям

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
*   `prometheus.io/scrape: "true"`: Включает сбор метрик для этого сервиса (`action: keep`).
*   `prometheus.io/scheme: "https"`: Позволяет переопределить схему на `https`.
*   `prometheus.io/path: "/my-metrics"`: Позволяет указать нестандартный путь к метрикам.
*   `prometheus.io/port: "9091"`: Позволяет указать порт, с которого нужно собирать метрики.

### 4. Мониторинг доступности сервисов с Blackbox Exporter

**Задача:** Проверять доступность сервисов "снаружи" с помощью Blackbox Exporter.

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
1.  `role: service`: Prometheus обнаруживает объекты `Service`.
2.  `prometheus.io/probe: "true"`: Мониторинг включается для сервисов с этой аннотацией.
3.  `target_label: __param_target`: Адрес целевого сервиса (например, `my-app.default.svc:80`) передается Blackbox Exporter'у через параметр `target` в URL.
4.  `replacement: blackbox-exporter...`: Сам Prometheus обращается не к сервису напрямую, а к Blackbox Exporter'у, который уже выполняет проверку.

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./helm_chart_configuration.md]]
*   [[../scaling/federation.md]]
