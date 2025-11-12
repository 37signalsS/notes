# Обнаружение сервисов (Service Discovery) в Kubernetes

Вся мощь Prometheus раскрывается при использовании механизма Service Discovery, который позволяет динамически обнаруживать цели для сбора метрик вместо статического указания IP-адресов. Это особенно актуально в динамических средах, таких как Kubernetes, где IP-адреса подов и количество экземпляров могут часто меняться.

Prometheus поддерживает различные механизмы Service Discovery, и для Kubernetes используется `kubernetes_sd_configs`. Этот механизм позволяет Prometheus обращаться к Kubernetes API-серверу и запрашивать информацию об объектах кластера.

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

## Практические примеры

### 1. Сбор метрик с Kubernetes API-серверов

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
*   [[./setup.md]]
*   [[./helm_chart_configuration.md]]
*   [[../scaling/federation.md]]
