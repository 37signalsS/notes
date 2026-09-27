# Конфигурация экспортеров в kube-prometheus-stack

## Определения

**Экспортеры в kube-prometheus-stack** — встроенные компоненты Helm-чарта (субчарты), развёртывающие агенты сбора метрик как нативные Kubernetes-объекты. Чарт из коробки управляет тремя основными экспортерами:

1. **Node Exporter** (DaemonSet) — сбор аппаратных и ОС-метрик (CPU, память, диск, сеть). Разворачивается на каждой ноде кластера.
2. **kube-state-metrics** (Deployment) — генерация метрик на основе состояния объектов Kubernetes API (Pod, Deployment, Service, StatefulSet и др.).
3. **Blackbox Exporter** (Deployment) — проактивный blackbox-мониторинг доступности внешних и внутренних эндпоинтов (HTTP/TCP/ICMP/DNS).

## Архитектура

```
kube-prometheus-stack (values.yaml)
  ├── nodeExporter
  │     └── DaemonSet (prometheus-node-exporter)
  │           ├── hostNetwork: true
  │           ├── hostPID: true
  │           ├── hostPath: /proc, /sys, /rootfs
  │           └── PodMonitor (автогенерация)
  │
  ├── kubeStateMetrics
  │     └── Deployment (kube-state-metrics)
  │           ├── ServiceMonitor
  │           └── autosharding (опционально)
  │
  └── prometheus-blackbox-exporter
        ├── Deployment
        ├── ConfigMap (modules)
        └── Probe CRD (цели проверок)
```

**Поток метрик:**
1. Node Exporter экспонирует метрики на порту `9100` каждого узла.
2. PodMonitor/Servicemonitor, создаваемые чартом, регистрируют цели в Prometheus Operator.
3. Operator генерирует scrape-конфигурацию и передает её Prometheus Server.
4. Prometheus опрашивает экспортеры по Pull-модели и сохраняет данные в TSDB.

## Предварительные требования

### Аппаратные требования

| Компонент | CPU Request | Memory Request | CPU Limit | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| **Node Exporter** | 50m | 64Mi | 150m | 128Mi |
| **kube-state-metrics** | 100m | 128Mi | 250m | 256Mi |
| **Blackbox Exporter** | 50m | 64Mi | 100m | 128Mi |

### Программные требования

- Kubernetes 1.28+ (проверка: `kubectl version --short`).
- Helm 3.14+ (`helm version`).
- kube-prometheus-stack 88.1.x+.
- StorageClass с поддержкой `ReadWriteOnce` (если включена персистентность для Prometheus).
- Для Blackbox Exporter: сетевые политики, разрешающие исходящие подключения к проверяемым целям.

### RBAC

ServiceAccount Prometheus должен иметь права `get`, `list`, `watch` на:
- `pods`, `nodes`, `services`, `endpoints` в мониторимых namespaces.
- `secrets` в namespace, где хранятся сертификаты etcd (если используется TLS).

## Основные концепции

### Конфигурация Node Exporter

Управляется через секцию `nodeExporter.*` (и пробрасывается в субчарт `prometheus-node-exporter.*`).

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `nodeExporter.enabled` | Включение компонента | `true` |
| `nodeExporter.hostNetwork` | Использование сети хоста для сетевых метрик | `true` |
| `nodeExporter.hostPID` | Доступ к PID namespace хоста для метрик процессов | `true` |
| `nodeExporter.hostRootfsMount` | Монтирование корневой ФС хоста в `/rootfs` | `true` |
| `nodeExporter.tolerations` | Толерации для размещения на tainted-нодах (master) | `[]` |
| `nodeExporter.extraArgs` | Дополнительные флаги запуска (коллекторы) | `[]` |
| `prometheus-node-exporter.resources` | Requests/limits контейнера | `{}` |

**Ключевые особенности в KPS:**
- Работает как `DaemonSet` — строго по одному Pod на каждую ноду.
- Монтирует директории хоста (`/proc`, `/sys`, `/rootfs`) через `hostPath` для безопасного доступа к метрикам ядра в изолированной среде контейнера.
- Скрейпинг настраивается автоматически через встроенный `PodMonitor`.
- Для master-нод требуются явные tolerations (см. [Мониторинг master-нод](./practical_scenarios/master_nodes_monitoring.md)).

### Конфигурация kube-state-metrics (KSM)

Управляется через секцию `kubeStateMetrics.*` (пробрасывается в субчарт `kube-state-metrics.*`).

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `kubeStateMetrics.enabled` | Включение компонента | `true` |
| `kube-state-metrics.replicas` | Количество реплик (для HA) | `1` |
| `kube-state-metrics.autosharding.enabled` | Включение автоматического шардирования | `false` |
| `kube-state-metrics.autosharding.replicas` | Количество шардов | `2` |
| `kube-state-metrics.collectors` | Выбор отслеживаемых ресурсов | (Все базовые ресурсы) |
| `kube-state-metrics.resources` | Requests/limits | `{}` |

**Ключевые особенности в KPS:**
- Работает как `Deployment`. В кластерах >500 узлов требуется включение **автошардирования** (`autosharding.enabled: true`), чтобы KSM не исчерпал лимиты API-сервера.
- Не путать с `metrics-server`: KSM отдаёт детальные метрики состояния в Prometheus (для алертов/дашбордов), а `metrics-server` — агрегированные метрики ресурсов в kubelet (для HPA/VPA).
- Включает `ServiceMonitor` для автоматического скрейпинга Prometheus.

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
- Поддерживаемые протоколы: HTTP(S), TCP, ICMP, DNS, gRPC, Unix Domain Sockets.

## Практические сценарии

### Production-конфигурация экспортеров

```yaml
# Node Exporter — сбор метрик со всех нод, включая master
nodeExporter:
  enabled: true
  hostNetwork: true
  hostPID: true
  hostRootfsMount: true
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
  extraArgs:
    - --collector.systemd
    - --collector.ntp

# kube-state-metrics — мониторинг объектов K8s
kubeStateMetrics:
  enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi
  # Включение автошардирования для кластеров >500 узлов
  # autosharding:
  #   enabled: true
  #   replicas: 3
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

### NetworkPolicy для экспортеров

При включении networkPolicy в кластере необходимо разрешить трафик для экспортеров:

```yaml
# Разрешить Prometheus скрейпить Node Exporter
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape-node
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-node-exporter
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 9100

# Разрешить Blackbox Exporter проверять внешние цели
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-blackbox-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-blackbox-exporter
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 80
        - protocol: ICMP
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
  interval: 30s
  timeout: 10s
```

> **См. также:** [Blackbox Exporter — конфигурация модулей](../../Exporters/blackbox/blackbox_exporter_modules_configuration.md).

### Включение Node Exporter на master-нодах

Master-ноды имеют taint `NoSchedule`, поэтому DaemonSet Node Exporter не запускается на них без явных tolerations.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - operator: "Exists"
      effect: "NoSchedule"
```

> **Подробнее:** [Master Nodes Monitoring](./practical_scenarios/master_nodes_monitoring.md) — полные сценарии, troubleshooting, PromQL-проверки.

### Обогащение метрик через relabeling

Механизм `scrapeClasses` позволяет определить relabeling-правила для Node Exporter, которые автоматически применяются к его PodMonitor.

> **Подробнее:** [Node Exporter Metrics Enrichment](./practical_scenarios/node_exporter_enrichment.md) — scrapeClasses, relabelingConfigs, 5 сценариев обогащения, troubleshooting.

### Отключение экспортеров

```yaml
# Отключение Node Exporter (если используется внешний мониторинг хостов)
nodeExporter:
  enabled: false

# Отключение kube-state-metrics (если используется отдельный экземпляр)
kubeStateMetrics:
  enabled: false

# Отключение Blackbox Exporter
prometheus-blackbox-exporter:
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

# Проверка метрик Node Exporter
kubectl exec -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -c node-exporter -- \
  wget -qO- http://localhost:9100/metrics | head -20

# Проверка метрик kube-state-metrics
kubectl exec -n monitoring -l app.kubernetes.io/name=kube-state-metrics -c kube-state-metrics -- \
  wget -qO- http://localhost:8080/metrics | head -20

# Проверка метрик Blackbox Exporter
kubectl exec -n monitoring -l app.kubernetes.io/name=prometheus-blackbox-exporter -c blackbox-exporter -- \
  wget -qO- http://localhost:9115/metrics | head -20
```

### Валидация конфигурации перед применением

```bash
# 1. Проверка синтаксиса values.yaml
helm template monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml | kubectl apply --dry-run=client -f -

# 2. Проверка сгенерированных ресурсов
helm get manifest monitoring -n monitoring | grep -A5 "kind: PodMonitor"

# 3. Проверка наличия PodMonitor для Node Exporter
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml
```

### Обновление конфигурации экспортеров

```bash
# 1. Создание резервной копии текущих значений
helm get values monitoring -n monitoring > values-backup.yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values-backup.yaml \
  -f values.yaml

# 3. Проверка rollout
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m
kubectl rollout status deployment/kube-state-metrics -n monitoring --timeout=5m
kubectl rollout status deployment/prometheus-blackbox-exporter -n monitoring --timeout=5m

# 4. Проверка новых targets в Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# http://localhost:9090/targets
```

### Очистка окружения

```bash
# Удаление только экспортеров (остальные компоненты сохраняются)
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set nodeExporter.enabled=false \
  --set kubeStateMetrics.enabled=false \
  --set prometheus-blackbox-exporter.enabled=false

# Полное удаление стека
helm uninstall monitoring -n monitoring

# Удаление namespace (если пустой)
kubectl delete namespace monitoring

# Удаление CRD (осторожно — удалит все Custom Resources!)
kubectl delete crd prometheuses.monitoring.coreos.com
kubectl delete crd alertmanagers.monitoring.coreos.com
kubectl delete crd servicemonitors.monitoring.coreos.com
kubectl delete crd podmonitors.monitoring.coreos.com
kubectl delete crd prometheusrules.monitoring.coreos.com
kubectl delete crd probes.monitoring.coreos.com
kubectl delete crd alertmanagerconfigs.monitoring.coreos.com
```

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Экспортер | Параметр | Начальное значение | Метрика для наблюдения |
| :--- | :--- | :--- | :--- |
| Node Exporter | `requests.memory` | `64Mi` | `container_memory_working_set_bytes` |
| Node Exporter | `requests.cpu` | `50m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |
| Node Exporter | `limits.cpu` | `150m` | `container_cpu_usage_seconds_total` |
| kube-state-metrics | `requests.memory` | `128Mi` | `container_memory_working_set_bytes` |
| kube-state-metrics | `requests.cpu` | `100m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |
| Blackbox Exporter | `requests.memory` | `64Mi` | `container_memory_working_set_bytes` |
| Blackbox Exporter | `requests.cpu` | `50m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |

### Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Node Exporter не запускается на master | Отсутствуют tolerations | Добавьте `tolerations: - operator: "Exists" effect: "NoSchedule"`. |
| KSM: метрики отсутствуют | Неправильные селекторы | Проверьте `serviceMonitorSelector` в `values.yaml`. |
| Blackbox Exporter недоступен | Неверный `prober.url` в Probe | Используйте полное имя сервиса: `<service>.<namespace>.svc:9115`. |
| Метрики Node Exporter пустые | Неверные `hostPath` | Проверьте монтирование `/proc`, `/sys`, `/rootfs` в DaemonSet. |
| Высокое потребление CPU | Слишком частый скрейпинг | Увеличьте `scrape_interval` до 30s в PodMonitor. |
| OOMKilled экспортера | Недостаточно limits | Увеличьте `limits.memory` на 50-100%. |
| ICMP не работает в Blackbox | Отсутствует `cap_net_raw` | Выполните `setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter`. |
| Configuration Drift | Изменения через UI | Все изменения вносите через `values.yaml` или отдельные манифесты. |

### Граничные случаи и ограничения

1. **Master-ноды:** Node Exporter по умолчанию не запускается на control-plane из-за taint. Требуются явные tolerations.
2. **Автошардирование KSM:** Работает только при `replicas > 1` и требует соответствующих прав RBAC для доступа к API.
3. **ICMP в Blackbox:** В Kubernetes требует `cap_add: [NET_RAW]` в securityContext Deployment. Без этого модуль `icmp` возвращает ошибку.
4. **HostNetwork:** При `hostNetwork: true` Node Exporter использует сеть хоста. Убедитесь, что порт 9100 не конфликтует с другими сервисами на узле.
5. **Сетевые политики:** При включенном NetworkPolicy в кластере разрешите egress для Blackbox Exporter и ingress для скрейпинга Prometheus.
6. **Высокая кардинальность:** Node Exporter выдает ~1000+ метрик на хост. При >500 узлах используйте `metricRelabelings` для удаления лишних лейблов.
7. **Коллекторы KSM:** Некоторые ресурсы (CRD) требуют явного включения в `collectors`. Базовый набор включает стандартные ресурсы K8s.
8. **Конфигурация как код:** Изменения, сделанные через UI Grafana/Prometheus, не сохраняются обратно в Helm-чарт. Все изменения должны вноситься через `values.yaml` или отдельные манифесты.

### Рекомендации по ресурсам

| Экспортер | Параметр | Рекомендация |
| :--- | :--- | :--- |
| Node Exporter | CPU Request | 50m (минимально), 100m (рекомендуется для production) |
| Node Exporter | Memory Request | 64Mi |
| Node Exporter | CPU Limit | 150m |
| Node Exporter | Memory Limit | 128Mi |
| kube-state-metrics | CPU Request | 100m |
| kube-state-metrics | Memory Request | 128Mi |
| kube-state-metrics | Replicas | 1 (standalone), 2-3 (HA, >500 узлов с автошардированием) |
| Blackbox Exporter | CPU Request | 50m |
| Blackbox Exporter | Memory Request | 64Mi |
| Blackbox Exporter | Scrape Interval | 30s (внешние сервисы), 15s (внутренние) |

### Связанные темы

*   **[Экспортеры — общая информация](../../Exporters/overview.md)** — принцип работы, выбор экспортера, безопасность.
*   **[Обогащение метрик Node Exporter](./practical_scenarios/node_exporter_enrichment.md)** — scrapeClasses, relabeling, снижение кардинальности.
*   **[Мониторинг master-нод](./practical_scenarios/master_nodes_monitoring.md)** — tolerations, ServiceMonitor для control-plane.
