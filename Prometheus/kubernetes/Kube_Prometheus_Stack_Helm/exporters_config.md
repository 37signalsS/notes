# Конфигурация экспортеров в kube-prometheus-stack

## Определения

**Экспортеры в kube-prometheus-stack** — встроенные компоненты Helm-чарта (субчарты), развёртывающие агенты сбора метрик как нативные Kubernetes-объекты. Чарт из коробки управляет тремя основными экспортерами:

1. **Node Exporter** (DaemonSet) — сбор аппаратных и ОС-метрик (CPU, память, диск, сеть). Разворачивается на каждой ноде кластера.
2. **kube-state-metrics** (Deployment) — генерация метрик на основе состояния объектов Kubernetes API (Pod, Deployment, Service, StatefulSet и др.).
3. **Blackbox Exporter** (Deployment) — проактивный blackbox-мониторинг доступности внешних и внутренних эндпоинтов (HTTP/TCP/ICMP/DNS).

> **См. также:** [Экспортеры — общая информация](../../Exporters/overview.md), [Node Exporter](../../Exporters/node_exporter.md).

## Основные концепции

### Конфигурация Node Exporter

Управляется через секцию `nodeExporter.*` (и пробрасывается в субчарт `prometheus-node-exporter.*`).

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `nodeExporter.enabled` | Включение компонента | `true` |
| `nodeExporter.hostNetwork` | Использование сети хоста для сетевых метрик | `true` |
| `nodeExporter.hostPID` | Доступ к PID namespace хоста для метрик процессов | `true` |
| `nodeExporter.tolerations` | Толерации для размещения на tainted-нодах (master) | `[]` |
| `prometheus-node-exporter.extraArgs` | Отключение/включение конкретных коллекторов | `[]` |

**Ключевые особенности в KPS:**
- Работает как `DaemonSet` — строго по одному Pod на каждую ноду.
- Монтирует директории хоста (`/proc`, `/sys`, `/rootfs`) через `hostPath` для безопасного доступа к метрикам ядра в изолированной среде контейнера.
- Скрейпинг настраивается автоматически через встроенный `ServiceMonitor` или `PodMonitor`.

### Конфигурация kube-state-metrics (KSM)

Управляется через секцию `kubeStateMetrics.*` (пробрасывается в субчарт `kube-state-metrics.*`).

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `kubeStateMetrics.enabled` | Включение компонента | `true` |
| `kube-state-metrics.replicas` | Количество реплик (для HA) | `1` |
| `kube-state-metrics.autosharding.enabled` | Включение автоматического шардирования | `false` |
| `kube-state-metrics.collectors` | Выбор отслеживаемых CRD/объектов | (Все базовые ресурсы) |

**Ключевые особенности в KPS:**
- Работает как `Deployment`. В кластерах >500 узлов требуется включение **автошардирования** (`autosharding.enabled: true`), чтобы KSM не исчерпал лимиты API-сервера.
- Не путать с `metrics-server`: KSM отдаёт детальные метрики состояния в Prometheus (для алертов/дашбордов), а `metrics-server` — агрегированные метрики ресурсов в kubelet (для HPA/VPA).

### Конфигурация Blackbox Exporter

Управляется через секцию `prometheus-blackbox-exporter.*`.

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `prometheus-blackbox-exporter.enabled` | Включение компонента | `false` (по умолчанию выключен) |
| `prometheus-blackbox-exporter.config` | Глобальная конфигурация модулей проверок | `{}` |
| `prometheus-blackbox-exporter.serviceMonitor.enabled` | Создание ServiceMonitor для метрик самого экспортера | `false` |

**Ключевые особенности в KPS:**
- Является опциональным. Конфигурация модулей (`http_2xx`, `tcp_connect`) задаётся централизованно в `config`.
- Для настройки самих целей скрейпинга (что проверять) используется CRD `Probe` от Prometheus Operator, а не статические конфиги.

## Практические сценарии

### Production-конфигурация экспортеров

```yaml
# Node Exporter — сбор метрик со всех нод, включая master
nodeExporter:
  enabled: true
  hostNetwork: true
  hostPID: true
  tolerations:
    - operator: "Exists"
      effect: "NoSchedule"
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 150m
      memory: 128Mi

# kube-state-metrics — мониторинг объектов K8s
kube-state-metrics:
  enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi
  # Сбор метрик со всех namespaces
  additionalLabels:
    app.kubernetes.io/part-of: monitoring

# Blackbox Exporter — мониторинг внешних эндпоинтов
prometheus-blackbox-exporter:
  enabled: true
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 128Mi
  config:
    modules:
      http_2xx:
        prober: http
        timeout: 10s
        http:
          valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
          valid_status_codes: [200]
          preferred_ip_protocol: "ip4"
      tcp_connect:
        prober: tcp
        timeout: 10s
      icmp_probe:
        prober: icmp
        timeout: 10s
        icmp:
          preferred_ip_protocol: "ip4"
```

### Обогащение метрик Node Exporter через relabeling

Механизм `scrapeClasses` позволяет определить relabeling-правила для Node Exporter, которые автоматически применяются к его PodMonitor.

> **Подробнее:** [Node Exporter Metrics Enrichment](./practical_scenarios/node_exporter_enrichment.md) — scrapeClasses, relabelingConfigs, 5 сценариев обогащения, troubleshooting.

### Мониторинг master-нод

Master-ноды имеют taint `NoSchedule`, поэтому DaemonSet Node Exporter не запускается на них без явных tolerations.

> **Подробнее:** [Master Nodes Monitoring](./practical_scenarios/master_nodes_monitoring.md) — полные сценарии, troubleshooting, PromQL-проверки.

### Отключение экспортеров

```yaml
# Отключение Node Exporter (если используется внешний мониторинг хостов)
nodeExporter:
  enabled: false

# Отключение kube-state-metrics (если используется отдельный экземпляр)
kube-state-metrics:
  enabled: false
```

> **Важно:** Отключение экспортеров приведёт к потере соответствующих метрик в Prometheus.

### Проверка работы экспортеров

```bash
# Проверка подов экспортеров
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter
kubectl get pods -n monitoring -l app.kubernetes.io/name=kube-state-metrics
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-blackbox-exporter

# Проверка targets в Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# Открыть http://localhost:9090/targets — все экспортеры должны быть в статусе UP

# Проверка метрик
kubectl exec -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -c node-exporter -- \
  wget -qO- http://localhost:9100/metrics | head -20
```

### Blackbox Exporter: создание Probe для внешних эндпоинтов

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-websites
  namespace: monitoring
spec:
  module: http_2xx
  prober:
    url: prometheus-blackbox-exporter.monitoring.svc:9115
  targets:
    staticConfig:
      static:
        - https://example.com
        - https://api.example.com
        - https://app.example.com
```

> **См. также:** [Blackbox Exporter — конфигурация модулей](../../Exporters/blackbox/blackbox_exporter_modules_configuration.md).

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Экспортер | Параметр | Начальное значение | Метрика для наблюдения |
| :--- | :--- | :--- | :--- |
| Node Exporter | `requests.memory` | `64Mi` | `container_memory_usage_bytes` |
| Node Exporter | `requests.cpu` | `50m` | `rate(container_cpu_usage_seconds_total[5m])` |
| kube-state-metrics | `requests.memory` | `128Mi` | `container_memory_usage_bytes` |
| kube-state-metrics | `requests.cpu` | `100m` | `rate(container_cpu_usage_seconds_total[5m])` |
| Blackbox Exporter | `requests.memory` | `64Mi` | `container_memory_usage_bytes` |
| Blackbox Exporter | `requests.cpu` | `50m` | `rate(container_cpu_usage_seconds_total[5m])` |

### Связанные темы

- [Экспортеры — общая информация](../../Exporters/overview.md) — принцип работы, выбор экспортера
- [Node Exporter](../../Exporters/node_exporter.md) — метрики, коллекторы, алерты
- [Blackbox Exporter](../../Exporters/blackbox/blackbox_exporter_overview.md) — blackbox-мониторинг
- [Обогащение метрик node-exporter](./practical_scenarios/node_exporter_enrichment.md) — relabeling
- [Сбор метрик с master-нод](./practical_scenarios/master_nodes_monitoring.md) — tolerations
- [Prometheus Operator CRD: Probe](../operator/crd/probe.md) — CRD для Blackbox Exporter
