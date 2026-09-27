# Мониторинг K3s: Prometheus + Grafana

Руководство по развертыванию стека мониторинга Prometheus + Grafana + Alertmanager внутри кластера K3s. Описывает установку через kube-prometheus-stack, настройку дашбордов, алертов и метрик K3s.

Контекст: Часть серии по созданию dev-окружения в K3s. Мониторинг критичен для наблюдаемости за GitLab, Harbor, ArgoCD и dev-контейнерами. См. [Архитектура K3s](./k3s_architecture.md), [Логирование](./k3s_logging.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **kube-prometheus-stack** | Umbrella Helm-чарт, объединяющий Prometheus Operator, Grafana, Alertmanager, kube-state-metrics, node-exporter, PrometheusRule и ServiceMonitor CRD в единый стек. |
| **Prometheus Operator** | Kubernetes-контроллер, управляющий инстансами Prometheus через CRD (Prometheus, ServiceMonitor, PrometheusRule). Автоматизирует конфигурацию scrape. |
| **ServiceMonitor** | CRD Prometheus Operator, описывающий, какие сервисы скrapeить и с какой периодичностью. Заменяет ручную конфигурацию `scrape_configs`. |
| **PrometheusRule** | CRD Prometheus Operator для декларативного определения alerting и recording rules. Хранится в Git и применяется через GitOps. |
| **Alertmanager** | Компонент стека Prometheus для маршрутизации, группировки и deduplication алертов. Поддерживает интеграции: Slack, Telegram, PagerDuty, webhook. |
| **kube-state-metrics** | Агент, генерирующий метрики из состояния Kubernetes-объектов (поды, ноды, deployments, replica-sets). Дополняет metrics-server. |
| **node-exporter** | Агент, собирающий метрики хост-узла: CPU, RAM, диск, сеть, файловые системы. Запускается как DaemonSet на каждой ноде. |
| **Grafana Alloy** | Универсальный агент телеметрии (метрики, логи, трейсы), заменяющий Promtail и Grafana Agent. Рекомендуется для сбора логов в Loki. |

Навигация: [Prometheus Operator](../../Prometheus/kubernetes/operator/installation.md) | [Grafana](../../Grafana/grafana_overview.md) | [Loki](../../Loki/loki_overview.md)

---

## Основные концепции

### Архитектура мониторинга в K3s

```text
┌─────────────────────────────────────────────────────────────────┐
│                     K3s Cluster (Single Node)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    scrape     ┌─────────────────────────────┐  │
│  │ node-exporter│ ◀──────────── │                             │  │
│  │ (DaemonSet)  │               │      Prometheus             │  │
│  └──────────────┘               │      (StatefulSet)          │  │
│                                  │                             │  │
│  ┌──────────────┐    scrape     │  retention: 15d             │  │
│  │ kube-state-  │ ◀──────────── │  storage: 10Gi PVC          │  │
│  │ metrics      │               │                             │  │
│  └──────────────┘               └──────────┬──────────────────┘  │
│                                             │                     │
│  ┌──────────────┐    metrics    ┌──────────▼──────────────────┐  │
│  │   Grafana    │ ◀──────────── │     Alertmanager            │  │
│  │  (Deploy)    │               │     (StatefulSet)           │  │
│  └──────┬───────┘               └──────────┬──────────────────┘  │
│         │                                   │                     │
│         │ dashboards                        │ alerts              │
│         ▼                                   ▼                     │
│  ┌──────────────┐               ┌──────────────────────────────┐  │
│  │  Browser     │               │  Slack / Telegram / Webhook  │  │
│  └──────────────┘               └──────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  ServiceMonitor: GitLab, Harbor, ArgoCD, NGINX Ingress       │ │
│  │  PrometheusRule: K3s alerts, app alerts                      │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Состав метрик K3s

| Источник | Тип метрик | Примеры |
| :--- | :--- | :--- |
| **node-exporter** | Хост-метрики | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes` |
| **kube-state-metrics** | K8s-объекты | `kube_pod_status_phase`, `kube_deployment_status_replicas`, `kube_node_status_condition` |
| **kubelet** | Внутренние K3s | `kubelet_runtime_operations_errors_total`, `kubelet_pleg_relist_duration_seconds` |
| **cAdvisor** | Контейнеры | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` |
| **Prometheus** | Мета-метрики | `prometheus_tsdb_head_series`, `prometheus_rule_evaluation_duration_seconds` |
| **Приложения** | Бизнес-метрики | GitLab: `gitlab_pipeline_count`, Harbor: `harbor_project_total` |

### Ресурсные требования для dev-окружения

| Компонент | CPU Request | Memory Request | PVC | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus** | 500m | 2Gi | 10Gi | Основной потребитель памяти |
| **Grafana** | 250m | 512Mi | 2Gi | Дашборды и алерты |
| **Alertmanager** | 100m | 128Mi | 1Gi | Минимальные требования |
| **node-exporter** | 100m | 128Mi | - | DaemonSet (на каждой ноде) |
| **kube-state-metrics** | 100m | 128Mi | - | Stateless |
| **Итого** | ~1050m | ~3Gi | ~13Gi | Дополнительно к GitLab/Harbor |

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация |
| :--- | :--- | :--- |
| **K3s** | v1.28+ | v1.36.3+k3s1 |
| **Helm** | 3.14+ | v4.2.3 |
| **StorageClass** | `local-path` | Встроенный в K3s |
| **NGINX Ingress** | Установлен | Для доступа к Grafana по HTTP |

### Предварительные шаги

1. **Проверка StorageClass:**
```bash
kubectl get sc
# → NAME                    PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE
# → local-path (default)   rancher.io/local-path   Delete          WaitForFirstConsumer
```

2. **Создание namespace:**
```bash
kubectl create namespace monitoring
```

---

## Практические сценарии

### 1. Установка kube-prometheus-stack через Helm

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка (минимальная конфигурация для K3s)
helm install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123 \
  --set grafana.service.type=LoadBalancer \
  --set prometheus.prometheusSpec.retention=15d \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=local-path \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=10Gi \
  --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.storageClassName=local-path \
  --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.resources.requests.storage=2Gi \
  --set nodeExporter.enabled=true \
  --set kubeStateMetrics.enabled=true

# Ожидание готовности
kubectl -n monitoring get pods -w
# → NAME                                                     READY   STATUS    AGE
# → alertmanager-kube-prometheus-alertmanager-0              2/2     Running   30s
# → kube-prometheus-grafana-xxx                              3/3     Running   30s
# → kube-prometheus-kube-prometheus-operator-xxx             1/1     Running   30s
# → kube-prometheus-kube-prometheus-prometheus-node-exporter-xxx  1/1     Running   30s
# → kube-prometheus-kube-state-metrics-xxx                   1/1     Running   30s
# → prometheus-kube-prometheus-prometheus-0                  2/2     Running   30s
```

**Валидация:**
```bash
# Проверка сервисов
kubectl -n monitoring get svc
# → NAME                                            TYPE           CLUSTER-IP     EXTERNAL-IP
# → alertmanager-kube-prometheus-alertmanager        ClusterIP      10.43.x.x      <none>
# → kube-prometheus-grafana                          LoadBalancer   10.43.x.x      192.168.1.x
# → kube-prometheus-kube-prometheus-prometheus       LoadBalancer   10.43.x.x      192.168.1.x

# Проверка доступности Grafana
curl -s -o /dev/null -w "%{http_code}" http://grafana.dev.local
# → 302 (редирект на логин)

# Проверка Prometheus
curl -s -o /dev/null -w "%{http_code}" http://prometheus.dev.local
# → 200
```

### 2. Настройка ServiceMonitor для K3s-сервисов

ServiceMonitor автоматически告诉 Prometheus скrapeить метрики из указанных сервисов.

```yaml
# serviceMonitor-gitlab.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: gitlab-monitoring
  namespace: monitoring
  labels:
    release: kube-prometheus
spec:
  namespaceSelector:
    matchNames:
      - gitlab
  selector:
    matchLabels:
      app: webservice
  endpoints:
    - port: http
      path: /-/metrics
      interval: 30s
```

```yaml
# serviceMonitor-harbor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: harbor-monitoring
  namespace: monitoring
  labels:
    release: kube-prometheus
spec:
  namespaceSelector:
    matchNames:
      - harbor
  selector:
    matchLabels:
      app: harbor-core
  endpoints:
    - port: http
      path: /api/v2.0/metrics
      interval: 60s
```

```yaml
# serviceMonitor-argocd.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: argocd-monitoring
  namespace: monitoring
  labels:
    release: kube-prometheus
spec:
  namespaceSelector:
    matchNames:
      - argocd
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

```bash
# Применение
kubectl apply -f serviceMonitor-gitlab.yaml
kubectl apply -f serviceMonitor-harbor.yaml
kubectl apply -f serviceMonitor-argocd.yaml

# Проверка, что Prometheus обнаружил.targets
kubectl -n monitoring exec prometheus-kube-prometheus-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[].labels.job'
# → "gitlab-monitoring"
# → "harbor-monitoring"
# → "argocd-monitoring"
```

### 3. Настройка алертов (PrometheusRule)

```yaml
# prometheusRules-k3s.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: k3s-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus
spec:
  groups:
    - name: k3s-node-alerts
      rules:
        - alert: K3sNodeNotReady
          expr: kube_node_status_condition{condition="Ready",status="true"} == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "K3s нода {{ $labels.node }} не готова"
            description: "Нода {{ $labels.node }} не в статусе Ready более 5 минут"

        - alert: K3sHighCPU
          expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Высокая CPU на {{ $labels.instance }}"
            description: "CPU используется более 85% на протяжении 10 минут"

        - alert: K3sHighMemory
          expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 90
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Критически высокое потребление RAM"
            description: "Использование RAM превышает 90%"

        - alert: K3sDiskSpaceLow
          expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 15
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Мало места на диске"
            description: "Свободного места менее 15%"

    - name: k3s-pod-alerts
      rules:
        - alert: K3sPodCrashLooping
          expr: rate(kube_pod_container_status_restarts_total[15m]) * 60 * 5 > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} перезапускается"
            description: "Pod перезапускается более 5 раз за 15 минут"

        - alert: K3sPodNotReady
          expr: kube_pod_status_phase{phase=~"Pending|Unknown"} > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} не готов"
            description: "Pod находится в статусе Pending более 15 минут"

        - alert: K3sContainerOOMKilled
          expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0
          for: 0m
          labels:
            severity: critical
          annotations:
            summary: "Container OOMKilled в {{ $labels.namespace }}/{{ $labels.pod }}"
            description: "Контейнер был убит из-за нехватки памяти"

    - name: k3s-storage-alerts
      rules:
        - alert: K3sPVCPending
          expr: kube_persistentvolumeclaim_status_phase{phase="Pending"} > 0
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.namespace }}/{{ $labels.persistentvolumeclaim }} в Pending"
            description: "PVC не может быть привязан более 30 минут"

        - alert: K3sPersistentVolumeFillingUp
          expr: (kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes) * 100 < 15
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} заполняется"
            description: "Свободного места менее 15%"
```

```bash
kubectl apply -f prometheusRules-k3s.yaml

# Проверка правил
kubectl -n monitoring get prometheusrule
# → NAME              AGE
# → k3s-alerts        30s

# Проверка в Prometheus UI: Status -> Rules
```

### 4. Настройка Grafana дашбордов

```bash
# Получение пароля Grafana
kubectl -n monitoring get secret kube-prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 -d
# → admin123

# Импорт дашбордов по ID (через UI или API)
# Рекомендуемые дашборды:
# 315  — Kubernetes Cluster Monitoring (神话)
# 15661 — K3s cluster overview
# 13770 — Node Exporter Full
# 12006 — Kubernetes Pods
```

**Автоматическое provisioning дашбордов через ConfigMap:**

```yaml
# configmap-grafana-dashboards.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  k3s-cluster.json: |
    {
      "dashboard": {
        "title": "K3s Cluster Overview",
        "uid": "k3s-cluster",
        "panels": [
          {
            "title": "CPU Usage",
            "type": "timeseries",
            "targets": [
              {
                "expr": "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)",
                "legendFormat": "{{ instance }}"
              }
            ]
          }
        ]
      }
    }
```

### 5. Настройка Alertmanager (интеграция с Telegram)

```yaml
# alertmanager-config.yaml
apiVersion: v1
kind: Secret
metadata:
  name: kube-prometheus-alertmanager
  namespace: monitoring
type: Opaque
stringData:
  alertmanager.yaml: |
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname', 'namespace']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      receiver: 'telegram-bot'
      routes:
        - match:
            severity: critical
          receiver: 'telegram-bot'
          repeat_interval: 1h
    receivers:
      - name: 'telegram-bot'
        telegram_configs:
          - bot_token: '<BOT_TOKEN>'
            chat_id: <CHAT_ID>
            parse_mode: 'HTML'
            message: |
              {{ range .Alerts }}
              <b>{{ .Labels.alertname }}</b>
              Severity: {{ .Labels.severity }}
              Namespace: {{ .Labels.namespace }}
              Description: {{ .Annotations.description }}
              {{ end }}
```

```bash
# Применение конфигурации Alertmanager
kubectl apply -f alertmanager-config.yaml

# Перезапуск Alertmanager для применения изменений
kubectl -n monitoring delete pod alertmanager-kube-prometheus-alertmanager-0
# → Pod будет пересоздан автоматически
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: Prometheus не скrapeит.targets

```bash
# Проверка ServiceMonitor
kubectl -n monitoring get servicemonitor -o wide
# → Убедитесь, что labels совпадают с selector в Prometheus Operator

# Проверка targets в Prometheus
# UI: Status -> Targets (или API)
kubectl -n monitoring exec prometheus-kube-prometheus-prometheus-0 -c prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
# → {"job": "gitlab-monitoring", "health": "up"}

# Если target в состоянии "down":
# 1. Проверьте доступность сервиса из пода Prometheus
kubectl -n monitoring exec prometheus-kube-prometheus-prometheus-0 -c prometheus -- \
  wget -qO- 'http://gitlab-webservice-default.gitlab.svc.cluster.local:8181/-/metrics' | head -5
```

### Ошибка: Grafana не показывает данные

```bash
# Проверка datasource
kubectl -n monitoring get secret kube-prometheus-grafana -o jsonpath="{.data.prometheus-yaml}" | base64 -d

# Проверка подключения Grafana к Prometheus
kubectl -n monitoring exec deploy/kube-prometheus-grafana -c grafana -- \
  wget -qO- 'http://kube-prometheus-prometheus.monitoring.svc:9090/api/v1/status/config' | head -1
# → {"status":"success",...}
```

### Ошибка: PVC для Prometheus в статусе Pending

```bash
# Проверка StorageClass
kubectl get sc
# → local-path должен быть default

# Проверка PV
kubectl get pv | grep prometheus
# → Если нет, проверьте поды local-path-provisioner
kubectl -n kube-system get pods | grep local
```

---

## Дополнительная информация

### Интеграция с существующим стеком

Если Prometheus/Grafana уже установлены вне K3s (на хосте), можно настроить remote write из K3s:

```yaml
# values.yaml для kube-prometheus-stack
prometheus:
  prometheusSpec:
    remoteWrite:
      - url: "http://<external-prometheus>:9090/api/v1/write"
```

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Ресурсы** | Prometheus потребляет 2+ ГБ RAM | В dev-окружении установите `retention=7d` и limits |
| **Диск** | Метрики заполняют PVC | Настройте retention policy и мониторинг диска |
| **node-exporter** | Доступ к /proc и /sys на хосте | Используйте `hostPID: false`, `hostNetwork: false` |
| **Alertmanager** | Дублирование алертов | Настройте `group_by` и `group_wait` |

### См. также

- [Prometheus Operator](../../Prometheus/kubernetes/operator/installation.md) -- ручная установка Operator
- [Концепции Prometheus Operator](../../Prometheus/kubernetes/operator/concepts.md) -- CRD, ServiceMonitor, PrometheusRule
- [Grafana](../../Grafana/grafana_overview.md) -- обзор Grafana
- [Loki для логов](../../Loki/loki_overview.md) -- архитектура Loki
- [Логирование K3s](./k3s_logging.md) -- централизованный сбор логов
