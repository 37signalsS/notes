# Обогащение метрик Node Exporter через Relabeling (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** обогащение метрик Node Exporter через механизмы relabeling в составе kube-prometheus-stack.  
> **Смежные темы:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) — общие концепции трансформации меток; [Kubernetes SD](../../service_discovery.md) — механизмы обнаружения целей в K8s; [Конфигурация экспортеров](../exporters_config.md) — базовые параметры Node Exporter в Helm-чарте.

## Определения

**`scrapeClasses`** — механизм в `kube-prometheus-stack` (начиная с v50+), позволяющий определять именованные наборы правил relabeling в `values.yaml`. Эти правила автоматически внедряются в конфигурацию скрейпинга компонентов (например, Node Exporter), что позволяет избежать дублирования YAML-кода.

**`relabelingConfigs`** (Target Relabeling) — конфигурация правил, применяемых к целям **до** начала сбора данных. Используется для фильтрации объектов скрейпинга и модификации меток на основе метаданных (например, `__meta_kubernetes_pod_node_name`).

**`metricRelabelings`** (Metric Relabeling) — конфигурация правил, применяемых к метрикам **после** их получения от экспортера, но до записи в базу данных (TSDB). Это основной инструмент для удаления ненужных меток и снижения кардинальности (индексного веса данных).

**Обогащение метрик (Enrichment)** — процесс добавления дополнительных контекстных меток (имя узла, зона, роль, команда) для повышения информативности дашбордов и точности алертинга.

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
| **`relabelingConfigs`** | `scrapeClasses` или PodMonitor | До сбора (SD) | Фильтрация целей, изменение адресов. |
| **`metricRelabelings`** | PodMonitor / ServiceMonitor | После сбора | Удаление лишних меток, фильтрация метрик. |
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

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| Метки не добавляются | Класс не привязан к монитору | Проверьте `nodeExporter.podMonitor.scrapeClass` в `values.yaml`. |
| Метки пустые | Не включен `attachMetadata` | Добавьте `attachMetadata: { node: true }` в настройки PodMonitor. |
| Цели (Targets) исчезли | Ошибка в правиле `keep` | Проверьте регулярное выражение. Временно измените на `replace` для отладки. |
| Метки не удаляются | Ошибка в `labeldrop` | Проверьте, что правило находится в `metricRelabelings`, а не в `relabelings`. |
| Ошибки в логах оператора | Неверный синтаксис YAML | Проверьте отступы и названия полей в `values.yaml`. |

### Диагностика из интерфейса Prometheus

1. **Проверка SD:** Перейдите в `Status -> Service Discovery`. Найдите пул `node-exporter`. Там видны все "Discovered Labels" (с префиксом `__meta`).
2. **Проверка итоговых меток:** Перейдите в `Status -> Targets`. Сравните колонку "Labels" (что попало в базу) и колонку "Discovered Labels".
3. **Проверка конфига:** Перейдите в `Status -> Runtime & Build Information -> Configuration`. Найдите секцию `scrape_config` для Node Exporter и убедитесь, что ваши правила встроены корректно.

### Полезные команды

```bash
# Проверка наличия scrapeClass в сгенерированном PodMonitor
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml | grep scrapeClass

# Просмотр логов конфигуратора (sidecar в поде Prometheus)
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload
```

### Рекомендации (Best Practices)

1. **Сначала `replace`, потом `keep/drop`:** Всегда сначала добавляйте метки для идентификации, и только потом фильтруйте цели.
2. **Используйте `attachMetadata.node`:** Это мощный инструмент современных версий оператора, позволяющий PodMonitor видеть метки узла без сложных Join-запросов.
3. **Контролируйте кардинальность:** Не копируйте в метрики аннотации с уникальными значениями (например, временные метки деплоя).
4. **Централизация через scrapeClasses:** Описывайте общие правила (env, cluster_name) один раз в `scrapeClasses` и переиспользуйте их для всех компонентов.

### Связанные ресурсы

| Ресурс | Описание |
|:---|:---|
| [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md) | Полный справочник действий: `keep`, `drop`, `replace`, `labelmap`, `labeldrop`. |
| [Kubernetes Service Discovery](../../service_discovery.md) | Доступные мета-лейблы для разных типов объектов Kubernetes. |
| [Конфигурация экспортеров](../exporters_config.md) | Настройка Node Exporter и других агентов в Helm-чарте. |
| [PodMonitor CRD](../operator/crd/podmonitor.md) | Детальное описание спецификации монитора подов. |
