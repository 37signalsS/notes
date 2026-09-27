# Обогащение метрик Node Exporter через Relabeling (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** обогащение метрик Node Exporter через механизмы relabeling в составе kube-prometheus-stack.
> **Смежные темы:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — общие концепции трансформации меток; [Kubernetes SD](../../service_discovery.md) — механизмы обнаружения целей в K8s; [Конфигурация экспортеров](../exporters_config.md) — базовые параметры Node Exporter в Helm-чарте.

## Определения

**`scrapeClasses`** — механизм в `kube-prometheus-stack` (начиная с v50+), позволяющий определять именованные наборы правил relabeling в `values.yaml`. Эти правила автоматически внедряются в конфигурацию скрейпинга компонентов (например, Node Exporter), что позволяет избежать дублирования YAML-кода.

**`relabelingConfigs`** (Target Relabeling) — конфигурация правил, применяемых к целям **до** начала сбора данных. Используется для фильтрации объектов скрейпинга и модификации меток на основе метаданных (например, `__meta_kubernetes_pod_node_name`).

**`metricRelabelings`** (Metric Relabeling) — конфигурация правил, применяемых к метрикам **после** их получения от экспортера, но до записи в базу данных (TSDB). Это основной инструмент для удаления ненужных меток и снижения кардинальности (индексного веса данных).

**Обогащение метрик (Enrichment)** — процесс добавления дополнительных контекстных меток (имя узла, зона, роль, команда) для повышения информативности дашбордов и точности алертинга.

**PodMonitor** — Custom Resource Definition в Prometheus Operator, предназначенный для декларативного описания целей скрейпинга метрик напрямую с подов Kubernetes. Для Node Exporter KPS автоматически создаёт PodMonitor, который можно дополнить relabeling-правилами через `scrapeClasses`.

**attachMetadata** — параметр в спецификации PodMonitor/ServiceMonitor, автоматически добавляющий метаданные Kubernetes (лейблы узла, annotations) к метрикам без ручного relabeling.

## Предварительные требования

### Аппаратные и программные требования

- Kubernetes 1.28+ (проверка: `kubectl version --short`).
- Helm 3.14+ (`helm version`).
- kube-prometheus-stack 88.1.x+.
- Node Exporter запущен как DaemonSet на целевых узлах.
- Prometheus Operator имеет права `list`/`watch` на ресурсы `pods` и `nodes` (обязательно при использовании `attachMetadata.node: true`).

### RBAC для attachMetadata

При включении `attachMetadata.node: true` Prometheus ServiceAccount требует дополнительных прав:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-node-metadata
rules:
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-node-metadata-binding
subjects:
  - kind: ServiceAccount
    name: prometheus-kube-prometheus-stack
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: prometheus-node-metadata
  apiGroup: rbac.authorization.k8s.io
```

Без этих прав метки узла не появятся в метриках, а в логах Operator будет ошибка типа `failed to list nodes: nodes is forbidden`.

## Основные концепции

### Механизм работы scrapeClasses

```
values.yaml (секция scrapeClasses)
    │
    ├── Определение класса "node-exporter-standard"
    │       └── relabelingConfigs (правила трансформации)
    │
    └── Привязка класса к компоненту:
            nodeExporter.podMonitor.scrapeClass: "node-exporter-standard"
```

При такой структуре Prometheus Operator автоматически объединяет глобальные настройки класса с конкретным монитором экспортера.

### Жизненный цикл конфигурации

1. **Helm-рендер:** При `helm upgrade` чарт генерирует PodMonitor для Node Exporter.
2. **Внедрение scrapeClass:** Если указан `scrapeClass`, Operator подставляет relabeling-правила из `prometheusSpec.scrapeClasses` в сгенерированный PodMonitor.
3. **Service Discovery:** Prometheus обнаруживает PodMonitor, получает мета-лейблы от Kubernetes API.
4. **Target Relabeling:** Применяются `relabelings` из PodMonitor/ScrapeClass — фильтрация целей, копирование мета-лейблов.
5. **Scrape:** Prometheus опрашивает `/metrics` на порту 9100.
6. **Metric Relabeling:** Применяются `metricRelabelings` — удаление лишних меток/рядов до записи в TSDB.
7. **Запись в TSDB:** Очищенные и обогащённые метрики сохраняются в head block.

### Зачем обогащать метрики Node Exporter

| Проблема | Решение через Relabeling | Описание |
|:---|:---|:---|
| Нечитаемый `instance` | Копирование имени узла в метку `node` | Заменяет `<IP>:9100` на понятное имя хоста. |
| Отсутствие контекста роли | Маппинг меток `node-role` из K8s | Позволяет разделять метрики master и worker узлов. |
| Высокая кардинальность | Удаление меток `pod`, `namespace` | Экономит место в TSDB, убирая уникальные ID подов для системных метрик. |
| Топологический анализ | Проброс меток `zone` и `region` | Необходимо для анализа производительности в разных AZ. |

### Различия механизмов трансформации

| Метод | Где настраивается | Когда выполняется | Основная цель |
|:---|:---|:---|:---|
| **`relabelings`** | PodMonitor / ScrapeClass | До сбора (SD) | Фильтрация целей, изменение адресов, копирование мета-лейблов. |
| **`metricRelabelings`** | PodMonitor / ServiceMonitor | После сбора | Удаление лишних меток, фильтрация метрик, снижение кардинальности. |
| **`attachMetadata`** | Спецификация монитора | В процессе SD | Авто-подтягивание метаданных узла (Node) к поду. |

> **См. также:** [relabel_configs и metric_relabel_configs](../../../service_discovery_and_relabeling.md).

## Практические сценарии

### Сценарий 1: Добавление читаемого имени узла в метрики

**Задача:** Метка `instance` по умолчанию содержит `<IP>:9100`. Добавить понятное имя узла в метку `node`.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter-class
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            targetLabel: node
            action: replace
```

**Результат в Prometheus:**
- До: `node_cpu_seconds_total{instance="10.0.1.5:9100", job="node-exporter"}`
- После: `node_cpu_seconds_total{instance="10.0.1.5:9100", node="worker-01", job="node-exporter"}`

**Пример PromQL:**
```promql
# CPU usage по имени узла
avg by(node) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))
```

### Сценарий 2: Перенос меток топологии и роли из Kubernetes

**Задача:** Использовать системные метки узлов (`zone`, `role`) непосредственно в метриках Prometheus.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter-enriched
        relabelingConfigs:
          # Требует nodeExporter.podMonitor.attachMetadata.node: true
          - sourceLabels: [__meta_kubernetes_node_label_topology_kubernetes_io_zone]
            targetLabel: zone
            action: replace
          - sourceLabels: [__meta_kubernetes_node_label_node_role_kubernetes_io_control_plane]
            targetLabel: node_role
            replacement: "master"
            action: replace
```

### Сценарий 3: Копирование аннотаций узлов (Environment, Team)

**Задача:** На узлах заданы аннотации `environment: prod` и `team: dba`. Перенести их в метрики.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: metadata-enricher
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_node_annotation_environment]
            targetLabel: env
            action: replace
          - sourceLabels: [__meta_kubernetes_node_annotation_team]
            targetLabel: team
            action: replace
```

### Сценарий 4: Снижение кардинальности через Metric Relabeling

**Задача:** Удалить высококардинальные метки (`pod`, `namespace`, `container`), которые бесполезны для Node Exporter, так как он привязан к узлу.

```yaml
# values.yaml
nodeExporter:
  podMonitor:
    metricRelabelings:
      - action: labeldrop
        regex: (pod|namespace|container|endpoint|service)
```

**Результат:** Существенное сокращение объема индекса (Label Index) в TSDB.

### Сценарий 5: Фильтрация целей (Keep)

**Задача:** Собирать метрики Node Exporter только с узлов, имеющих метку `monitoring=enabled`.

```yaml
# values.yaml
nodeExporter:
  podMonitor:
    relabelings:
      - sourceLabels: [__meta_kubernetes_node_label_monitoring]
        regex: "enabled"
        action: keep
```

### Сценарий 6: Использование labelmap для автоматического копирования лейблов

**Задача:** Автоматически скопировать все лейблы пода, начинающиеся с префикса `app_`, в метрики без создания отдельного правила для каждого лейбла.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter-labelmap
        relabelingConfigs:
          - action: labelmap
            regex: __meta_kubernetes_pod_label_app_(.+)
```

**Результат:** Все лейблы вида `app_team=backend` автоматически появятся в метриках как `team="backend"`.

### Сценарий 7: Объединение нескольких scrapeClasses

**Задача:** Применить базовый класс для всех компонентов и дополнительный класс только для Node Exporter.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      # Базовый класс для всех компонентов
      - name: common-standard
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_namespace]
            targetLabel: namespace
            action: replace
      # Дополнительный класс только для Node Exporter
      - name: node-exporter-extra
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            targetLabel: node
            action: replace

nodeExporter:
  podMonitor:
    scrapeClass: "node-exporter-extra"
    # Примечание: классы не объединяются автоматически.
    # Если нужны правила из common-standard, продублируйте их в node-exporter-extra
    # или используйте отдельный механизм (например, prometheusSpec.scrapeConfig).
```

### Сценарий 8: Удаление метрик Go runtime через metricRelabelings

**Задача:** Node Exporter содержит метрики Go runtime (`go_*`, `promhttp_*`), которые не несут смысла для инфраструктурного мониторинга. Удалить их для экономии места в TSDB.

```yaml
# values.yaml
nodeExporter:
  podMonitor:
    metricRelabelings:
      - sourceLabels: [__name__]
        regex: "go_.*|promhttp_.*|process_cpu_seconds_total|process_max_fds|process_open_fds"
        action: drop
```

### Сценарий 9: Отдельный DaemonSet Node Exporter с кастомными коллекторами

**Задача:** Стандартный DaemonSet из чарта не включает коллекторы `systemd` и `ntp`. Запустить отдельный DaemonSet с дополнительными флагами и настроить отдельный PodMonitor с обогащением.

```yaml
# values.yaml
nodeExporter:
  enabled: false  # Отключаем встроенный экспортер

# Отдельный DaemonSet (применяется через отдельный манифест или субчарт)
# Пример манифеста node-exporter-custom.yaml:
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter-custom
  namespace: monitoring
  labels:
    app.kubernetes.io/name: node-exporter-custom
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter-custom
  template:
    metadata:
      labels:
        app.kubernetes.io/name: node-exporter-custom
    spec:
      hostNetwork: true
      hostPID: true
      tolerations:
        - operator: Exists
          effect: NoSchedule
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.12.1
          args:
            - --path.procfs=/host/proc
            - --path.sysfs=/host/sys
            - --path.rootfs=/rootfs
            - --collector.systemd
            - --collector.ntp
          ports:
            - containerPort: 9100
              hostPort: 9100
              name: metrics
          volumeMounts:
            - name: proc
              mountPath: /host/proc
              readOnly: true
            - name: sys
              mountPath: /host/sys
              readOnly: true
            - name: rootfs
              mountPath: /rootfs
              readOnly: true
      volumes:
        - name: proc
          hostPath:
            path: /proc
        - name: sys
          hostPath:
            path: /sys
        - name: rootfs
          hostPath:
            path: /
---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: node-exporter-custom
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter-custom
  podMetricsEndpoints:
    - port: metrics
      interval: 15s
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_node_name]
          targetLabel: node
          action: replace
      metricRelabelings:
        - action: labeldrop
          regex: (pod|namespace|container|endpoint|service)
```

### Сценарий 10: Проверка доступности порта 9100 через Blackbox Exporter

**Задача:** Помимо сбора метрик, необходимо проверять доступность самого Node Exporter на каждом узле через Blackbox Exporter.

```yaml
# values.yaml
prometheus-blackbox-exporter:
  enabled: true
  config:
    modules:
      node_exporter_tcp:
        prober: tcp
        timeout: 5s

# Probe CRD для проверки доступности Node Exporter на всех нодах
---
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: node-exporter-availability
  namespace: monitoring
spec:
  jobName: "node-exporter-tcp-check"
  module: node_exporter_tcp
  prober:
    url: prometheus-blackbox-exporter.monitoring.svc:9115
  targets:
    staticConfig:
      static:
        - 10.0.1.10:9100
        - 10.0.1.11:9100
        - 10.0.1.12:9100
  interval: 30s
  timeout: 10s
```

**Важно:** При изменении топологии кластера (добавление/удаление узлов) статические списки в `staticConfig` необходимо обновлять вручную или генерировать через CI/CD.

### Сценарий 11: Валидация конфигурации перед применением

**Задача:** Проверить корректность YAML-конфигурации и убедиться, что PodMonitor сгенерирован корректно.

```bash
# 1. Проверка синтаксиса values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml | kubectl apply --dry-run=client -f -

# 2. Проверка сгенерированного PodMonitor
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml | grep -A20 "relabelings\|metricRelabelings\|scrapeClass"

# 3. Проверка внедрённых relabeling-правил в сгенерированном конфиге Prometheus
kubectl get secret monitoring-kube-prometheus-prometheus -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip -c | grep -A40 "scrape_configs.*node-exporter"

# 4. Проверка наличия меток в метриках
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
# В Prometheus UI: Status -> Service Discovery -> найти node-exporter
# Проверить, что метки __meta_kubernetes_node_label_* присутствуют
```

### Сценарий 12: Апгрейд и откат конфигурации

**Задача:** Безопасно обновить конфигурацию relabeling в production-среде с возможностью отката.

```bash
# 1. Создание резервной копии текущего состояния
helm get values monitoring -n monitoring > values-backup-$(date +%Y%m%d).yaml
kubectl get podmonitor,servicemonitor,prometheusrule -n monitoring -o yaml > cr-backup-$(date +%Y%m%d).yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# 3. Проверка rollout DaemonSet Node Exporter
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m

# 4. Проверка наличия новых меток в метриках
kubectl exec -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload -- \
  curl -s http://localhost:9090/api/v1/label/node/values | jq '.data'

# 5. Откат при необходимости
helm rollback monitoring -n monitoring
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m
```

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| Метки не добавляются | Класс не привязан к монитору | Проверьте `nodeExporter.podMonitor.scrapeClass` в `values.yaml`. |
| Метки пустые | Не включен `attachMetadata` | Добавьте `attachMetadata: { node: true }` в настройки PodMonitor. |
| Метки `node_role` отсутствуют | Узлу не assigned метка `node-role.kubernetes.io/control-plane` | Проверьте `kubectl get nodes -L node-role.kubernetes.io/control-plane`. |
| Цели (Targets) исчезли | Ошибка в правиле `keep` | Проверьте регулярное выражение. Временно измените на `replace` для отладки. |
| Метки не удаляются | Ошибка в `labeldrop` | Проверьте, что правило находится в `metricRelabelings`, а не в `relabelings`. |
| Ошибки в логах оператора | Неверный синтаксис YAML | Проверьте отступы и названия полей в `values.yaml`. |
| attachMetadata не работает | Недостаточно прав RBAC | Убедитесь, что ServiceAccount Prometheus имеет `list`/`watch` на `nodes`. |
| Высокая кардинальность после обогащения | Добавлены уникальные аннотации | Удалите `labeldrop` для аннотаций с уникальными значениями (деплой ID, временные метки). |

### Диагностика из интерфейса Prometheus

1. **Проверка SD:** Перейдите в `Status -> Service Discovery`. Найдите пул `node-exporter`. Там видны все "Discovered Labels" (с префиксом `__meta`).
2. **Проверка итоговых меток:** Перейдите в `Status -> Targets`. Сравните колонку "Labels" (что попало в базу) и колонку "Discovered Labels".
3. **Проверка конфига:** Перейдите в `Status -> Runtime & Build Information -> Configuration`. Найдите секцию `scrape_config` для Node Exporter и убедитесь, что ваши правила встроены корректно.
4. **Проверка кардинальности:** Перейдите в `Status -> TSDB` и проверьте количество активных временных рядов. При росте >10M рядов на инстанс требуется снижение кардинальности.

### Полезные команды

```bash
# Проверка наличия scrapeClass в сгенерированном PodMonitor
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml | grep scrapeClass

# Просмотр логов конфигуратора (sidecar в поде Prometheus)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload

# Проверка прав ServiceAccount Prometheus на nodes
kubectl get clusterrolebinding -n monitoring | grep prometheus
kubectl auth can-i list nodes --as=system:serviceaccount:monitoring:prometheus-kube-prometheus-stack

# Поиск меток node в текущих метриках
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
curl -s 'http://localhost:9090/api/v1/label/node/values' | jq '.data'

# Проверка количества временных рядов по job
curl -s 'http://localhost:9090/api/v1/series?match[]={job="node-exporter"}' | jq '.data | length'
```

### Очистка и откат

```bash
# Удаление только scrapeClasses из конфигурации (сохраняет остальные настройки)
# В values.yaml закомментируйте или удалите секцию scrapeClasses,
# затем выполните helm upgrade.

# Полный откат к предыдущему релизу
helm rollback monitoring -n monitoring

# Проверка rollout после отката
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m

# Удаление пользовательских PodMonitor (если создавались вручную)
kubectl delete podmonitor -n monitoring <custom-podmonitor-name>
```

### Рекомендации (Best Practices)

1. **Сначала `replace`, потом `keep/drop`:** Всегда сначала добавляйте метки для идентификации, и только потом фильтруйте цели.
2. **Используйте `attachMetadata.node`:** Это мощный инструмент современных версий оператора, позволяющий PodMonitor видеть метки узла без сложных Join-запросов.
3. **Контролируйте кардинальность:** Не копируйте в метрики аннотации с уникальными значениями (например, временные метки деплоя).
4. **Централизация через scrapeClasses:** Описывайте общие правила (env, cluster_name) один раз в `scrapeClasses` и переиспользуйте их для всех компонентов.
5. **Валидируйте перед деплоем:** Всегда проверяйте синтаксис через `helm template` и `kubectl apply --dry-run` перед применением.
6. **Используйте `labelmap` с осторожностью:** Массовое копирование лейблов может привести к неожиданному росту кардинальности. Всегда тестируйте на стенде.
7. **RBAC минимальных прав:** Не назначайте `cluster-admin` без необходимости. Для `attachMetadata.node` достаточно `get`, `list`, `watch` на `nodes`.
8. **Изменяйте через Git:** Все изменения в `values.yaml` и манифесты должны храниться в репозитории для аудита и отката.
9. **Разделяйте классы по ответственности:** Один класс — одна логика (например, `node-exporter-topology`, `node-exporter-cardinality`). Это упрощает отладку.
10. **Мониторьте сам мониторинг:** Добавьте алерт на `prometheus_operator_reconcile_errors_total > 0` для отслеживания ошибок конфигурации.

### Граничные случаи

1. **K0s/K3s:** В распределённых K8s-дистрибутивах метки узлов могут отличаться. Проверяйте актуальные названия (`node-role.kubernetes.io/control-plane` vs `node-role.kubernetes.io/master`).
2. **hostNetwork-конфликты:** При `hostNetwork: true` Node Exporter использует порт 9100 хоста. Убедитесь, что порт не занят другими сервисами (nagios, zabbix agent).
3. **Managed-кластеры:** Некоторые managed-сервисы запрещают `hostPID` и `hostNetwork`. В таком случае используйте стандартный DaemonSet без этих флагов и настройте коллекторы без доступа к PID namespace.
4. **Случайный listen-адрес:** По умолчанию Node Exporter слушает на `0.0.0.0:9100`. При `hostNetwork: true` убедитесь, что нет конфликта с другими подами на том же порту.
5. **OOMKilled при обогащении:** Добавление relabeling незначительно увеличивает потребление памяти Prometheus, но при >1000 узлах проверяйте `prometheusSpec.resources.limits.memory`.
6. **terminationGracePeriodSeconds:** При rollout DaemonSet Grace Period по умолчанию 30s. Для Node Exporter это может быть недостаточно при большом количестве метрик. Увеличьте до 60s в PodMonitor.
7. **NetworkPolicy:** При включенном NetworkPolicy в кластере разрешите ingress на порт 9100 для PodSelector Prometheus и egress для Blackbox Exporter.
8. **Ротация сертификатов:** При использовании TLS для scrape-целей (не относится к Node Exporter по умолчанию, но актуально для расширенных сценариев) убедитесь, что `tlsConfig.ca` указывает на актуальный Secret.
9. **namespaceSelector:** По умолчанию PodMonitor ищет поды во всех namespaces. Ограничьте `namespaceSelector` для снижения нагрузки на API.
10. **Кардинальность при copy меток:** Копирование лейблов с узлов (`node-role`, `zone`) безопасно, так как количество узлов ограничено. Копирование лейблов подов (`pod`, `namespace`) в Node Exporter метрики опасно — это приведёт к взрывному росту рядов.

### Связанные ресурсы

| Ресурс | Описание |
|:---|:---|
| [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) | Полный справочник действий: `keep`, `drop`, `replace`, `labelmap`, `labeldrop`. |
| [Конфигурация экспортеров](../exporters_config.md) | Настройка Node Exporter и других агентов в Helm-чарте. |
| [PodMonitor CRD](../../operator/crd/podmonitor.md) | Детальное описание спецификации монитора подов, attachMetadata, limits. |
