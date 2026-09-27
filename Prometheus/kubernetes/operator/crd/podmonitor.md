# PodMonitor — Концепции (CRD)

## Определения

**`kind: PodMonitor`** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга метрик напрямую с подов Kubernetes. В отличие от `ServiceMonitor`, он не использует абстракцию Service для обнаружения эндпоинтов, а взаимодействует с Kubernetes API для получения IP-адресов подов напрямую. Это является основным механизмом (SSoT) для мониторинга сущностей без сетевой абстракции Service.

**Скрейпинг подов (Pod Scraping)** — механизм сбора метрик, при котором Prometheus обращается к каждому поду отдельно. Это критично для систем, где каждый экземпляр приложения имеет уникальное состояние или когда использование Service невозможно или избыточно.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [ServiceMonitor](./servicemonitor.md) — мониторинг через Service, [Prometheus CRD](./prometheus.md) — конфигурация сервера Prometheus.

## Базовые концепции

### Принцип работы и жизненный цикл

Процесс автоматизации сбора метрик через PodMonitor включает следующие этапы:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `PodMonitor` в кластере.
2.  **Обнаружение целей:** На основе `selector` и `namespaceSelector`, указанных в CRD, Оператор находит соответствующие поды через Kubernetes API.
3.  **Генерация конфигурации:** Оператор формирует секцию `scrape_config` в конфигурационном файле Prometheus, используя IP-адреса найденных подов.
4.  **Применение (Apply):** Обновленная конфигурация записывается в Secret, который монтируется в под Prometheus.
5.  **Перезагрузка:** Контейнер `prometheus-config-reloader` (sidecar) обнаруживает изменение Secret и отправляет сигнал `/-/reload` серверу Prometheus.

### Архитектура прямого скрейпинга подов

Интеграция строится на модели прямого доступа без абстракции Service:

```text
[ Prometheus ]
      |
      | (kubernetes_sd_configs → role: pod)
      v
[ Kubernetes API ] -----> [ Pods (IP:Port) ]
      |
      | (__meta_kubernetes_pod_*)
      v
[ Prometheus TSDB ]
```

В отличие от `ServiceMonitor`, здесь Prometheus использует IP-адрес пода напрямую. Это исключает задержки обновления Endpoints и позволяет скрейпить поды до того, как они будут добавлены в Service.

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
*   **Sidecar-метрики:** Когда приложение использует sidecar-контейнер (например, Envoy), который должен скрейпиться отдельно от основного пода.
*   **Отсутствие Service:** Когда приложение не имеет Kubernetes Service по архитектурным или security-причинам.
*   **Mesh-инфраструктура:** Service Mesh (Istio, Linkerd), где sidecar-прокси требует прямого доступа к порту `15090` для метрик.

### Сравнение с ServiceMonitor

| Характеристика | PodMonitor | ServiceMonitor |
| :--- | :--- | :--- |
| **Объект обнаружения** | Pod | Service |
| **Зависимость от Service** | Отсутствует | Обязательна |
| **Режим работы** | Прямой доступ к IP пода | Доступ через эндпоинты сервиса |
| **Meta-лейблы** | `__meta_kubernetes_pod_*` | `__meta_kubernetes_endpoint_*`, `__meta_kubernetes_service_*` |
| **Обнаружение Sidecars** | Проще (выбор порта пода) | Сложнее (требует Named Port в Service) |
| **Основной кейс** | Stateful-системы, инфраструктурные агенты | Stateless-микросервисы |

### Сравнение с Probe

| Характеристика | PodMonitor | Probe |
| :--- | :--- | :--- |
| **Тип мониторинга** | Whitebox (внутреннее состояние) | Blackbox (внешняя доступность) |
| **Источник данных** | `/metrics` самого приложения | Эндпоинт `/probe` экспортера |
| **Цели** | Поды внутри K8s | Любые эндпоинты (внешние URL, IP, Ingress) |
| **Протоколы** | HTTP (Prometheus format) | HTTP, HTTPS, TCP, ICMP, DNS, gRPC |
| **Механизм обнаружения** | Service Discovery через K8s API | Статические списки или Ingress-селекторы |
| **Зависимость от K8s Service** | Отсутствует | Отсутствует |

### Селекторы в ресурсе Prometheus

Для того чтобы Prometheus обнаружил ресурсы `PodMonitor`, в спецификации ресурса `Prometheus` должен быть настроен `podMonitorSelector`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: prometheus
  namespace: monitoring
spec:
  podMonitorSelector:
    matchLabels:
      release: prometheus-stack
```

> **Важно:** Без соответствующего `podMonitorSelector` ресурсы `PodMonitor` игнорируются Prometheus. Это распространенная ошибка при первом развертывании. В Helm-чарте `kube-prometheus-stack` по умолчанию используется селектор `release: <имя_релиза>`, поэтому все PodMonitor должны содержать этот лейбл.

### Новые возможности (2025–2026)

*   **Native Histograms (Prometheus 3.0+):** Поддержка разреженных гистограмм через `nativeHistogramBucketLimit`, `nativeHistogramMinBucketFactor` и флаг `scrapeNativeHistograms`.
*   **Scrape Protocols:** Явный выбор приоритета протоколов (`scrapeProtocols`) для оптимизации сбора данных.
*   **ProxyConfig:** Гибкая настройка прокси-серверов через `proxyUrl`, `noProxy` и поддержка системных переменных окружения `proxyFromEnvironment`.
*   **Обогащение метаданными:** Параметр `attachMetadata.node` прикрепляет лейблы узла к метрикам, а `promoteScopeMetadata` переносит метаданные OTLP в лейблы Prometheus.
*   **keepDroppedTargets:** Сохранение в памяти Prometheus ограниченного количества целей, отсеченных правилами relabeling, для упрощения отладки.

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

### Сценарий 5: Мониторинг DaemonSet (Node Exporter)

Сбор метрик с локальных агментов на каждом узле кластера.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: node-exporter-monitor
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter
  namespaceSelector:
    matchNames:
      - monitoring
  podMetricsEndpoints:
    - port: http-metrics
      interval: 15s
      path: /metrics
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_node_name]
          targetLabel: node
        - action: drop
          regex: __meta_kubernetes_pod_label_(.+)  # Очистка дублирующихся лейблов
```

### Сценарий 6: Защита от высокой кардинальности

Ограничение количества сэмплов и метрик для предотвращения OOM в TSDB.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: cardinality-protected-monitor
spec:
  selector:
    matchLabels:
      app: high-cardinality-app
  namespaceSelector:
    matchNames:
      - production
  sampleLimit: 5000            # Максимум сэмплов на скрейп
  targetLimit: 200             # Максимум целей
  labelLimit: 50               # Максимум лейблов на временной ряд
  labelNameLengthLimit: 64     # Ограничение длины имени лейбла
  podMetricsEndpoints:
    - port: metrics
      interval: 30s
      metricRelabelings:
        - sourceLabels: [__name__]
          regex: "go_.*"        # Удаление стандартных метрик Go
          action: drop
        - sourceLabels: [__name__]
          regex: "process_.*"
          action: drop
```

### Сценарий 7: Изолированный доступ через корпоративный прокси

Для кластеров в изолированных сетях без прямого доступа к подам.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: isolated-network-monitor
spec:
  selector:
    matchLabels:
      app: isolated-service
  namespaceSelector:
    matchNames:
      - production
  podMetricsEndpoints:
    - port: https
      scheme: https
      proxyConfig:
        proxyUrl: http://squid.corp.internal:3128
        noProxy: "localhost,127.0.0.1,.internal.svc"
      tlsConfig:
        insecureSkipVerify: false
        ca:
          secret:
            name: internal-ca
            key: ca.crt
      interval: 30s
      scrapeTimeout: 10s
```

### Сценарий 8: Переиспользование лейблов пода через podTargetLabels

Автоматическое перенос лейблов из пода в метрики для группировки в Grafana.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: label-inheritance-monitor
spec:
  selector:
    matchLabels:
      app: multi-tier-app
  namespaceSelector:
    matchNames:
      - production
      - staging
  podTargetLabels:
    - app
    - version
    - team
    - environment
  podMetricsEndpoints:
    - port: metrics
      interval: 15s
      honorLabels: false  # Лейблы PodMonitor важнее лейблов приложения
      relabelings:
        - sourceLabels: [__meta_kubernetes_namespace]
          targetLabel: namespace
        - sourceLabels: [__meta_kubernetes_pod_name]
          targetLabel: pod
```

> **Примечание:** `podTargetLabels` позволяет избежать дублирования `relabelings` для стандартных лейблов. Лейблы, указанные в `podTargetLabels`, автоматически добавляются ко всем метрикам от подов, соответствующих селектору. Используйте `honorLabels: false`, чтобы лейблы из PodMonitor имели приоритет над лейблами, отдаваемыми приложением.

## Дополнительная информация

### Требования к правам (RBAC)

Для корректной работы PodMonitor и связанных функций Prometheus Operator необходимо настроить права доступа:

**Для Prometheus Operator:**
*   Права `get`, `list`, `watch` на ресурсы `pods` в целевых неймспейсах.
*   Права `get`, `list`, `watch` на ресурсы `endpoints` в целевых неймспейсах (требуется для полной функциональности, даже если PodMonitor работает напрямую с подами).
*   Права на чтение `secrets` для получения учетных данных (OAuth2, Basic Auth, TLS).

**Для Prometheus ServiceAccount:**
*   **`attachMetadata.node: true`:** Требует прав `list` и `watch` на ресурс `nodes`.
*   **Стандартная работа:** Права `list` и `watch` на `pods` в целевых неймспейсах.

**Пример Role и RoleBinding:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: prometheus-pod-monitor
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]  # Только если используется attachMetadata.node
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: prometheus-pod-monitor
  namespace: production
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: Role
  name: prometheus-pod-monitor
  apiGroup: rbac.authorization.k8s.io
```

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
| **`labelLimit`** | Лимит количества лейблов на временной ряд. | Защита от высокой кардинальности. |
| **`labelNameLengthLimit`** | Максимальная длина имени лейбла. | Ограничение длины строки. |
| **`scrapeProtocols`** | Приоритет протоколов скрейпинга. | OpenTelemetry-Proto, PrometheusText. |
| **`scrapeNativeHistograms`** | Включение нативных гистограмм. | Требует Prometheus >= 3.0. |

### Параметры под-эндпоинтов (podMetricsEndpoints)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| **`port`** | Имя порта контейнера. | Обязательно (имя, а не номер). |
| **`path`** | Путь к метрикам. | `/metrics`. |
| **`scheme`** | Протокол сбора данных. | `http` (доступен `https`). |
| **`interval`** | Частота опроса. | `30s` (стандарт чарта). |
| **`scrapeTimeout`** | Время ожидания ответа. | Должно быть `<= interval`. |
| **`honorLabels`** | Приоритет лейблов приложения. | `false` (лейблы таргета важнее). |
| **`honorTimestamps`** | Использование временных меток приложения. | `true`. |
| **`tlsConfig`** | Настройка TLS для HTTPS. | Используется при `scheme: https`. |
| **`oauth2` / `authorization`** | Настройки аутентификации. | Взаимно исключают друг друга. |
| **`proxyConfig`** | Настройка прокси. | Используется для выхода в изолированные сети. |
| **`relabelings`** | Обработка таргетов ДО сбора. | Используется для фильтрации и модификации целей. |
| **`metricRelabelings`** | Обработка метрик ПОСЛЕ сбора. | Используется для удаления лишних метрик перед записью. |

### Различия Relabeling механизмов

*   **`relabelings`**: Применяются на этапе обнаружения целей (Service Discovery). С их помощью можно отфильтровать ненужные поды (`action: keep` или `drop`) или изменить мета-информацию о цели до того, как начнется опрос.
*   **`metricRelabelings`**: Применяются к уже полученным данным. Это основной инструмент для экономии места в TSDB путем удаления высококардинальных или ненужных метрик (`action: labeldrop`, `labelkeep`).

### Ограничения и крайние случаи

*   **Имя порта:** Параметр `port` должен содержать **имя** порта контейнера, а не номер. Это частая ошибка при миграции с ServiceMonitor.
*   **Зависимость от RBAC:** Для работы `attachMetadata.node` и даже стандартного обнаружения подов у Prometheus ServiceAccount должны быть права `list`/`watch` на `pods` (и `nodes` для attachMetadata).
*   **Cardinality:** Каждый уникальный под создает отдельный временной ряд с метками `pod`, `namespace`, `node`. Для >10 000 подов используйте шардирование Prometheus или разделение на несколько PodMonitor.
*   **Таймауты:** `scrapeTimeout` должен быть меньше или равен `interval`. Рекомендуемое соотношение: таймаут = 30-50% от интервала.
*   **NetworkPolicy:** Prometheus должен иметь сетевой доступ к IP-адресам подов напрямую. Если между ними стоит NetworkPolicy, убедитесь, что разрешен трафик на порт метрик.
*   **Stale-метрики:** При перезапуске пода Prometheus генерирует `stale NaN` для всех его метрик. Убедитесь, что алерты имеют достаточный `for:` duration (не менее 2-3 scrape intervals).
*   **IP vs Hostname:** Prometheus Operator по умолчанию использует IP-адреса подов. Если требуется использовать hostname, настройте `podMonitor.<name>.podTargetLabels` или используйте relabeling для замены `__address__`.
*   **Зависимость от подов в Running:** PodMonitor по умолчанию обнаруживает поды в фазе `Running`. Поды в `Pending` или `CrashLoopBackOff` не попадут в цели, что корректно для большинства случаев, но может скрывать проблемы при старте приложения.

### Диагностика

1.  **Проверка обнаружения подов:**
    `kubectl get podmonitor <name> -n <namespace> -o yaml` (проверьте поле `status`, если оно поддерживается версией оператора).
2.  **Проверка в UI Prometheus:**
    Меню `Status -> Targets`. Ищите job в формате `podMonitor/<namespace>/<name>/<index>`.
3.  **Логи Оператора:**
    `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator` — ищите ошибки с текстом `failed to generate config`.

### Типичные проблемы и устранение неполадок

1.  **PodMonitor не появляется в Targets Prometheus**
    *   **Причина:** Отсутствует `podMonitorSelector` в ресурсе `Prometheus` или несовпадающие лейблы.
    *   **Решение:** Проверьте `kubectl get prometheus -o yaml | grep -A5 podMonitorSelector`. Убедитесь, что PodMonitor имеет соответствующие лейблы (обычно `release: <имя_релиза>`).

2.  **Ошибка `port not found` или `connection refused`**
    *   **Причина:** Имя порта в `podMetricsEndpoints.port` не совпадает с именем порта в контейнере пода.
    *   **Решение:** Проверьте порты пода: `kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].ports[*].name}'`. Убедитесь, что имя указано корректно (case-sensitive).

3.  **Selector не находит поды**
    *   **Причина:** Лейблы в `selector` не совпадают с лейблами пода.
    *   **Решение:** Проверьте лейблы: `kubectl get pods -n <namespace> --show-labels`. Используйте `kubectl get pods -l app=my-database` для проверки селектора.

4.  **`attachMetadata.node` не работает**
    *   **Причина:** Недостаточно прав у Prometheus ServiceAccount на ресурс `nodes`.
    *   **Решение:** Убедитесь, что в кластере есть Role/RoleBinding с правами `list` и `watch` на `nodes` для ServiceAccount Prometheus.

5.  **Высокая кардинальность и OOM Prometheus**
    *   **Причина:** Слишком много подов или метрик с уникальными лейблами.
    *   **Решение:** Примените `sampleLimit`, `targetLimit`, `labelLimit`. Используйте `metricRelabelings` для удаления высококардинальных метрик. Рассмотрите шардирование Prometheus.

6.  **NetworkPolicy блокирует скрейпинг**
    *   **Причина:** Между подом Prometheus и целевым подом стоит NetworkPolicy, запрещающая трафик.
    *   **Решение:** Добавьте правило в NetworkPolicy, разрешающее трафик от Prometheus на порт метрик целевых подов.

7.  **Stale-метрики вызывают ложные алерты**
    *   **Причина:** При перезапуске пода Prometheus генерирует `stale NaN`, что может сработать `absent()` или `changes()` алерты.
    *   **Решение:** Увеличьте `for:` в алертах до 2-3 интервалов скрейпинга. Используйте `min_over_time()` или `avg_over_time()` для сглаживания.

8.  **ScrapeClass не применяется**
    *   **Причина:** PodMonitor не помечен соответствующим классом или класс не настроен в `values.yaml`.
    *   **Решение:** Проверьте `nodeExporter.podMonitor.scrapeClass` в Helm-значениях. Убедитесь, что PodMonitor имеет метку, соответствующую классу (если требуется).

### Валидация работоспособности

После развертывания выполните следующие проверки:

**1. Проверка доступности эндпоинта метрик (ad-hoc):**
```bash
# Получение IP пода и порта
POD_IP=$(kubectl get pod -n production -l app=my-database -o jsonpath='{.items[0].status.podIP}')
POD_PORT=$(kubectl get pod -n production -l app=my-database -o jsonpath='{.spec.containers[0].ports[?(@.name=="metrics")].containerPort}')

# Проверка доступности метрик
curl http://${POD_IP}:${POD_PORT}/metrics
```
Ожидаемый результат: HTTP 200 с текстовым форматом Prometheus.

**2. Проверка в Prometheus:**
```promql
# Проверка успешности всех проверок за последние 5 минут
up{job=~"podMonitor/.*"}

# Проверка кардинальности
count by (job, pod) (up{job=~"podMonitor/.*"})
```

**3. Проверка статуса применения:**
```bash
kubectl get podmonitor -n monitoring
kubectl describe podmonitor <name> -n <namespace>
```

**4. Проверка сгенерированной конфигурации:**
```bash
kubectl get secret prometheus-<name> -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | grep -A20 "podMonitor/"
```

### Лучшие практики

*   **Селекторы:** Используйте максимально конкретные селекторы. Избегайте пустых `{}` селекторов, которые могут привести к неожиданному набору целей.
*   **Namespace:** Ограничьте `namespaceSelector` конкретными неймспейсами. Используйте `any: true` только при необходимости мониторинга всего кластера.
*   **Интервалы:** Устанавливайте интервалы скрейпинга не менее 15s для стабильных сервисов и не более 60s для инфраструктурных метрик. Более частые скрейпы (5s) оправданы только для критических компонентов.
*   **Таймауты:** Устанавливайте `scrapeTimeout` на 30-50% меньше `interval`. Например, при `interval: 30s` используйте `scrapeTimeout: 10s`.
*   **Кардинальность:** Всегда используйте `metricRelabelings` для удаления неиспользуемых метрик. Особенно это касается метрик Go runtime (`go_*`, `process_*`) и метрик клиентских библиотек.
*   **Безопасность:** Используйте TLS (`scheme: https`) для всех внутренних сервисов, которые его поддерживают. Никогда не отключайте `insecureSkipVerify` в production без веской причины.
*   **Мониторинг самого Prometheus:** Добавьте алерты на `up{job="prometheus"} < 1` и `prometheus_rule_group_last_consistency_error_total > 0`.
*   **Присоединение метаданных:** Используйте `attachMetadata.node` для инфраструктурных метрик (node-exporter, kube-state-metrics), но избегайте его для прикладных сервисов, где метки узла не несут смысла.
*   **Версионирование:** Храните манифесты PodMonitor в Git с четким именованием (`<app>-<env>-monitor.yaml`). Используйте GitOps-инструменты (ArgoCD, Flux) для развертывания.

### См. также

*   [ServiceMonitor CRD](./servicemonitor.md) — мониторинг через Kubernetes Service.
*   [Probe CRD](./probe.md) — blackbox-мониторинг внешних эндпоинтов.
*   [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — основы обнаружения целей и механизмы трансформации меток.
*   [Prometheus Operator — Troubleshooting](../troubleshooting.md) — алгоритмы решения проблем с генерацией конфигурации и скрейпингом.
*   [Официальная спецификация PodMonitor](https://github.com/prometheus-operator/prometheus-operator/blob/main/Documentation/api.md#podmonitor) — полный список параметров API от разработчиков.
