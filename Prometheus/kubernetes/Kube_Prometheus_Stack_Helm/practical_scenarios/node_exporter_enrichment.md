# Node Exporter Metrics Enrichment via Relabeling (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** обогащение метрик Node Exporter через relabeling в kube-prometheus-stack.  
> **Смежные темы:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — общие концепции relabeling; [Kubernetes SD](../../service_discovery.md) — обнаружение целей в K8s; [Конфигурация экспортеров](../exporters_config.md) — параметры Node Exporter в Helm-чарте.

## Definitions

**`scrapeClasses`** — механизм kube-prometheus-stack, позволяющий определить именованные наборы relabeling-правил, которые можно применять к конкретным scrape-конфигурациям (например, к Node Exporter) через `values.yaml`. Не является нативной функцией Prometheus; специфичен для Helm-чарта.

**`relabelingConfigs`** — список правил relabeling в рамках `scrapeClasses`. Работает как `relabel_configs` в нативном Prometheus: модифицирует метки цели **до** сбора метрик.

**Обогащение метрик (enrichment)** — процесс добавления, удаления или преобразования метрик/лейблов для повышения читаемости, стандартизации или контроля кардинальности.

## Basic Concepts

### Механизм работы scrapeClasses

```
values.yaml (scrapeClasses)
    │
    ├── scrapeClass: "node-exporter"
    │       └── relabelingConfigs → применяются к PodMonitor Node Exporter
    │
    └── Prometheus Operator генерирует конфигурацию
            └── Вставка relabelingConfigs в scrape_config Node Exporter
                    └── Prometheus собирает метрики с обогащёнными лейблами
```

`scrapeClasses` автоматически применяются к соответствующим PodMonitor/ServiceMonitor ресурсам, создаваемым чартом. Для Node Exporter это PodMonitor `prometheus-node-exporter`.

### Зачем обогащать метрики Node Exporter

| Проблема | Решение через relabeling |
|---|---|
| `instance` содержит IP:порт (нечитаемо) | Копирование имени узла в отдельную метку `node` |
| Метрики без информации о роли узла | Добавление лейблов `role`, `env`, `datacenter` из annotations |
| Высокая кардинальность из-за избыточных метрик | Удаление ненужных лейблов через `labeldrop` |
| Необходимость фильтрации по фичам узлов | Копирование node labels из K8s в метрики |

### Отличие от других механизмов relabeling

| Механизм | Где применяется | Контекст |
|---|---|---|
| **`scrapeClasses.relabelingConfigs`** | `values.yaml` kube-prometheus-stack | Helm-чарт, автоматически привязывается к PodMonitor/ServiceMonitor |
| **`additionalScrapeConfigs`** | `values.yaml` kube-prometheus-stack | Ручные scrape_configs для внешних целей |
| **`relabelings` в PodMonitor CRD** | YAML манифест PodMonitor | Prometheus Operator CRD |
| **`relabel_configs` в prometheus.yml** | Нативная конфигурация Prometheus | Bare-metal/Docker развёртывания |

> **См. также:** [relabel_configs и metric_relabel_configs](../../../service_discovery_and_relabeling.md), [External Monitoring](./external_monitoring.md) — `additionalScrapeConfigs`.

## Practical Scenarios

### Сценарий 1: Добавление читаемого имени узла в метрики

**Задача:** Метка `instance` по умолчанию содержит `<IP>:9100`. Добавить понятное имя узла в метку `node`.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            targetLabel: node
            action: replace
```

**Результат в Prometheus:**

```
# До обогащения:
node_cpu_seconds_total{instance="10.0.1.5:9100", job="node-exporter"}

# После обогащения:
node_cpu_seconds_total{instance="10.0.1.5:9100", job="node-exporter", node="k8s-worker-01"}
```

**PromQL-запрос с enriched-метрикой:**

```promql
# CPU usage по конкретному узлу по имени
avg by(node) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))
```

### Сценарий 2: Добавление роли узла из Kubernetes labels

**Задача:** На узлах Kubernetes установлены labels (`node.kubernetes.io/role`, `topology.kubernetes.io/zone`). Перенести их в метрики Prometheus.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter
        relabelingConfigs:
          # Копирование имени узла
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            targetLabel: node
            action: replace
          # Копирование zone из K8s label узла
          - sourceLabels: [__meta_kubernetes_endpoint_topology_zone]
            targetLabel: zone
            action: replace
          # Копирование role из K8s label
          - sourceLabels: [__meta_kubernetes_endpoint_label_node_kubernetes_io_role]
            targetLabel: node_role
            action: replace
```

**Пример PromQL с enriched-лейблами:**

```promql
# CPU usage по ролям узлов (worker vs master)
avg by(node_role) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))

# Сравнение метрик по зонам доступности
avg by(zone) (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

### Сценарий 3: Добавление кастомных лейблов из annotations узлов

**Задача:** На узлах Kubernetes заданы annotations (`environment`, `team`). Перенести их в метрики.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter
        relabelingConfigs:
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            targetLabel: node
            action: replace
          # Копирование annotation environment
          - sourceLabels: [__meta_kubernetes_pod_annotation_environment]
            targetLabel: env
            action: replace
            replacement: "${1}"
          # Копирование annotation team
          - sourceLabels: [__meta_kubernetes_pod_annotation_team]
            targetLabel: team
            action: replace
```

> **Примечание:** Для PodMonitor Node Exporter доступны meta-лейблы пода, а не узла. Для доступа к labels/annotations узлов через PodMonitor используется `__meta_kubernetes_pod_node_name` как ключ связывания.

### Сценарий 4: Снижение кардинальности — удаление избыточных лейблов

**Задача:** Удалить лейблы с высокой кардинальностью (например, `pod`, `namespace`), чтобы уменьшить объём хранимых временных рядов.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter
        relabelingConfigs:
          # Удаление лейбла pod (высокая кардинальность)
          - regex: "pod"
            action: labeldrop
          # Удаление лейбла namespace
          - regex: "namespace"
            action: labeldrop
```

> **Важно:** `labeldrop` удаляет лейблы из **всех** метрик Node Exporter. Используйте с осторожностью — лейбл `instance` обычно необходим для идентификации цели.

### Сценарий 5: Фильтрация — сбор метрик только с определённых узлов

**Задача:** Собирать метрики Node Exporter только с узлов определённой роли (например, `worker`).

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeClasses:
      - name: node-exporter
        relabelingConfigs:
          # Сбор только с worker-узлов
          - sourceLabels: [__meta_kubernetes_pod_node_name]
            regex: ".*worker.*"
            action: keep
```

> **Альтернатива:** Вместо relabeling-фильтрации используйте `nodeSelector` или `affinity` в Helm values для ограничения нод, на которых запускается DaemonSet Node Exporter.

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Relabeling не применяется | `scrapeClasses` не привязан к PodMonitor | Проверить, что `scrapeClass: "node-exporter"` указан в PodMonitor Node Exporter |
| Лейбл не появляется в метриках | Meta-лейбл недоступен в контексте PodMonitor | Проверить доступные `__meta_*` через `/api/v1/targets/metadata` в Prometheus UI |
| Лейбл пустой | Source label не найден или пуст | Проверить `kubectl get nodes -o yaml` на наличие нужного label/annotation |
| Метрики пропали после relabeling | `keep`-правило отфильтровало все цели | Проверить regex; временно заменить на `replace` для отладки |
| Высокая кардинальность после enrichment | Добавлен лейбл с уникальными значениями | Использовать `labeldrop` или агрегировать значения |

### Диагностика

```bash
# Проверить сгенерированную конфигурацию Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Посмотреть relabeling-конфигурацию для Node Exporter
# http://localhost:9090/config

# Проверить доступные meta-лейблы для target
# http://localhost:9090/api/v1/targets?scrapePool=node-exporter

# Проверить, что PodMonitor использует scrapeClass
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml | grep scrapeClass

# Протестировать relabeling-правила
# http://localhost:9090/targets — посмотреть "Discovered Labels" vs "Target Labels"
```

### Best Practices

1. **Начинайте с `replace`** — добавление новых лейблов безопаснее, чем `keep`/`drop`, которые могут скрыть цели.
2. **Проверяйте regex** — используйте [Prometheus relabeling tester](https://relabeler.promlabs.com/) для валидации правил перед применением.
3. **`__meta_*` зависят от типа SD** — для PodMonitor Node Exporter доступны `__meta_kubernetes_pod_*`; для ServiceMonitor — `__meta_kubernetes_endpoint_*` и `__meta_kubernetes_service_*`.
4. **`metric_relabel_configs` для пост-обработки** — если нужно фильтровать/изменять метрики **после** сбора (до записи в TSDB), используйте `metricRelabelings` в PodMonitor CRD.
5. **Избегайте высокой кардинальности** — не копируйте уникальные идентификаторы (UID, pod name) в лейблы — это создаёт экспоненциальный рост временных рядов.

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [Relabeling в Prometheus](../../../service_discovery_and_relabeling.md) | Все relabeling-действия: `keep`, `drop`, `replace`, `labelmap`, `labeldrop`, `hashmod` |
| [Kubernetes SD](../../service_discovery.md) | Meta-лейблы для pod, endpoint, service, node discovery |
| [Конфигурация экспортеров](../exporters_config.md) | Параметры Node Exporter в kube-prometheus-stack |
| [ServiceMonitor relabelings](../../../operator/crd/servicemonitor.md) | Relabeling в Prometheus Operator CRD |
