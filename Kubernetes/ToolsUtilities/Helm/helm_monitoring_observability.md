# Мониторинг и observability Helm-релизов

---

## Определения

**Helm Release** — развёрнутый экземпляр чарта в Kubernetes, управляемый через Secret (`sh.helm.release.v1.<name>.v<revision>`). Статус релиза (`deployed`, `failed`, `superseded`, `pending-*`)反映了 текущее состояние развёртывания.

**kube-state-metrics** — компонент Prometheus, экспортирующий метрики состояния Kubernetes-объектов, включая Helm-релизы через специализированный коллектор `helmrelease`.

**Helm Release Metrics** — семейство метрик `kube_helm_release_*`, отслеживающих статус, версию, количество ревизий и флаг наличия ошибок у каждого Helm-релиза в кластере.

**Grafana Dashboard** — визуализация метрик Helm-релизов через предустроенные или кастомные дашборды, обеспечивающие обзор здоровья всех развёрнутых чартов.

**Alerting Rules** — правила Prometheus для генерации алертов при обнаружении проблем с Helm-релизами: failed-ревизии, устаревшие версии, отсутствие обновлений.

**Helmwave Monitors** — пост-деплойные проверки готовности релизов (Prometheus / HTTP) с автоматическим откатом при провале, встроенные в Helmwave.

---

## Базовые концепции

### Архитектура мониторинга Helm

```
Prometheus
  └─ kube-state-metrics (helm collector)
       └─ kube_helm_release_* metrics
            ├─ kube_helm_release_info
            ├─ kube_helm_release_deployed
            ├─ kube_helm_release_failed
            ├─ kube_helm_release_revision
            └─ kube_helm_release_namespace
  └─ Alertmanager
       └─ Alerting Rules
            ├─ HelmReleaseFailed
            ├─ HelmReleaseStale
            └─ HelmReleaseMaxRevisions
```

### Типы метрик Helm

| Метрика | Тип | Описание |
|---------|-----|----------|
| `kube_helm_release_info` | gauge | Информация о релизе (chart, version, app_version, namespace) |
| `kube_helm_release_deployed` | gauge | 1 если релиз в статусе `deployed`, 0 — иначе |
| `kube_helm_release_failed` | gauge | 1 если релиз в статусе `failed`, 0 — иначе |
| `kube_helm_release_revision` | gauge | Текущий номер ревизии релиза |
| `kube_helm_release_namespace` | gauge | Namespace релиза |

### Когда мониторить Helm-релизы

| Сценарий | Метрика / Алерт | Действие |
|----------|-----------------|----------|
| Релиз в `failed` | `kube_helm_release_failed == 1` | Немедленный алерт, диагностика |
| Релиз устарел (нет обновлений > N дней) | `time() - kube_helm_release_info > N` | Проверка актуальности чарта |
| Количество ревизий аномально высоко | `kube_helm_release_revision > N` | Проверка частоты обновлений |
| Релиз не в `deployed` | `kube_helm_release_deployed == 0` | Диагностика статуса |

### kube-state-metrics: коллектор Helm

Для включения метрик Helm в kube-state-metrics необходимо активировать коллектор `helmrelease`:

```yaml
# Values для kube-state-metrics
kube-state-metrics:
  collectors:
    - helmrelease  # по умолчанию включён в актуальных версиях
```

Если коллектор отключён:
```bash
# Проверка доступных коллекторов
kubectl get deployment kube-state-metrics -n monitoring -o jsonpath='{.spec.template.spec.containers[0].args}'
```

---

## Практические сценарии

### PrometheusRule для алертов на Helm-релизы

```yaml
# values.yaml
alerting:
  enabled: true
  helmRelease:
    failed:
      enabled: true
      for: "5m"
    stale:
      enabled: true
      thresholdDays: 30
    maxRevisions:
      enabled: true
      threshold: 50
```

```yaml
# templates/prometheusrule.yaml
{{- if .Values.alerting.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: {{ include "myapp.fullname" . }}-helm-alerts
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
    - name: helm-releases
      rules:
        {{- if .Values.alerting.helmRelease.failed.enabled }}
        - alert: HelmReleaseFailed
          expr: kube_helm_release_failed == 1
          for: {{ .Values.alerting.helmRelease.failed.for | quote }}
          labels:
            severity: critical
          annotations:
            summary: "Helm release {{ "{{" }} $labels.name {{ "}}" }} failed"
            description: >
              Helm release {{ "{{" }} $labels.name {{ "}}" }} в namespace
              {{ "{{" }} $labels.namespace {{ "}}" }} находится в статусе failed
              более {{ .Values.alerting.helmRelease.failed.for }}.
              Текущая ревизия: {{ "{{" }} $labels.revision {{ "}}" }}.
            runbook_url: "https://wiki.example.com/runbooks/helm-release-failed"
        {{- end }}

        {{- if .Values.alerting.helmRelease.stale.enabled }}
        - alert: HelmReleaseStale
          expr: |
            (time() - kube_helm_release_info) > {{ mul .Values.alerting.helmRelease.stale.thresholdDays 86400 }}
          for: "1h"
          labels:
            severity: warning
          annotations:
            summary: "Helm release {{ "{{" }} $labels.name {{ "}}" }} stale"
            description: >
              Helm release {{ "{{" }} $labels.name {{ "}}" }} в namespace
              {{ "{{" }} $labels.namespace {{ "}}" }} не обновлялся более
              {{ .Values.alerting.helmRelease.stale.thresholdDays }} дней.
        {{- end }}

        {{- if .Values.alerting.helmRelease.maxRevisions.enabled }}
        - alert: HelmReleaseMaxRevisions
          expr: kube_helm_release_revision > {{ .Values.alerting.helmRelease.maxRevisions.threshold }}
          for: "1h"
          labels:
            severity: warning
          annotations:
            summary: "Helm release {{ "{{" }} $labels.name {{ "}}" }} has many revisions"
            description: >
              Helm release {{ "{{" }} $labels.name {{ "}}" }} имеет
              {{ "{{" }} $labels.revision {{ "}}" }} ревизий. Рекомендуется
              настроить --history-max или очистить историю.
        {{- end }}
{{- end }}
```

### ServiceMonitor для метрик Helm (если свой exporter)

```yaml
# values.yaml
serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  scrapeTimeout: 10s
```

```yaml
# templates/servicemonitor.yaml
{{- if .Values.serviceMonitor.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "myapp.fullname" . }}-helm-metrics
  namespace: {{ .Values.serviceMonitor.namespace }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kube-state-metrics
  namespaceSelector:
    matchNames:
      - {{ .Values.serviceMonitor.namespace }}
  endpoints:
    - port: http-metrics
      interval: {{ .Values.serviceMonitor.interval }}
      scrapeTimeout: {{ .Values.serviceMonitor.scrapeTimeout }}
      path: /metrics
      params:
        collect[]:
          - helmrelease
{{- end }}
```

### Grafana Dashboard (JSON Model) для Helm-релизов

```yaml
# values.yaml
grafana:
  enabled: true
  dashboard:
    enabled: true
    namespace: monitoring
    labels:
      grafana_dashboard: "1"
```

```yaml
# templates/grafana-dashboard-configmap.yaml
{{- if and .Values.grafana.enabled .Values.grafana.dashboard.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-helm-dashboard
  namespace: {{ .Values.grafana.dashboard.namespace }}
  labels:
    {{- toYaml .Values.grafana.dashboard.labels | nindent 4 }}
data:
  helm-releases.json: |
    {
      "dashboard": {
        "title": "Helm Releases Overview",
        "uid": "helm-releases",
        "panels": [
          {
            "title": "Helm Releases by Status",
            "type": "stat",
            "targets": [
              {
                "expr": "count(kube_helm_release_deployed == 1) or vector(0)",
                "legendFormat": "Deployed"
              },
              {
                "expr": "count(kube_helm_release_failed == 1) or vector(0)",
                "legendFormat": "Failed"
              }
            ]
          },
          {
            "title": "Helm Release Revisions",
            "type": "timeseries",
            "targets": [
              {
                "expr": "kube_helm_release_revision",
                "legendFormat": "{{ "{{" }} namespace {{ "}}" }}/{{ "{{" }} name {{ "}}" }}"
              }
            ]
          },
          {
            "title": "Failed Helm Releases",
            "type": "table",
            "targets": [
              {
                "expr": "kube_helm_release_failed == 1",
                "format": "table"
              }
            ]
          }
        ]
      }
    }
{{- end }}
```

### Мониторинг через Helmwave Monitors

Helmwave предоставляет встроенные пост-деплойные проверки готовности:

```yaml
# helmwave.yml.tpl
releases:
  - name: myapp
    namespace: apps
    chart: myrepo/myapp
    wait: watcher
    timeout: 10m
    monitors:
      - type: prometheus
        url: http://prometheus:9090
        query: |
          kube_deployment_status_replicas_available{namespace="apps", deployment="myapp"} > 0
        success_threshold: 3
        failure_threshold: 1
        total_timeout: 5m
      - type: http
        url: http://myapp:8080/healthz
        success_threshold: 1
        failure_threshold: 3
        interval: 5s
```

### Helm status + kubectl для быстрой диагностики

```bash
# Просмотр всех Helm-релизов в кластере
helm list -A -o json | jq '.[] | {name, namespace, revision, status, chart, app_version}'

# Фильтрация failed-релизов
helm list -A --failed -o json | jq '.[] | {name, namespace, revision}'

# Просмотр метрик Helm через Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090
# Запрос: count(kube_helm_release_deployed == 1) by (namespace)

# Быстрая проверка здоровья всех релизов
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do
  echo "=== Namespace: $ns ==="
  helm list -n "$ns" -o json 2>/dev/null | jq -r '.[] | "\(.name)\t\(.status)\t\(.chart)\t\(.app_version)"'
done
```

### Алерт на отсутствие метрик (Dead Man's Switch)

```yaml
# templates/prometheusrule.yaml (дополнение)
{{- if .Values.alerting.enabled }}
        - alert: HelmMetricsMissing
          expr: |
            absent(kube_helm_release_info)
          for: "10m"
          labels:
            severity: critical
          annotations:
            summary: "Helm metrics not available"
            description: >
              kube-state-metrics не экспортирует метрики Helm-релизов.
              Проверьте, что коллектор helmrelease активирован.
{{- end }}
```

---

## Дополнительная информация

### Лучшие практики

1. **Включите коллектор:** Убедитесь, что `kube-state-metrics` экспортирует метрики `helmrelease`.
2. **Настройте алерты:** Минимум алерты на `failed` и `stale` релизы.
3. **Используйте Grafana Dashboard:** Обзорный дашборд для всех Helm-релизов в кластере.
4. **Helmwave Monitors:** Для критичных релизов настраивайте пост-деплойные проверки.
5. **--history-max:** Ограничивайте количество ревизий (10–20) для чистоты метрик.
6. **Разделяйте окружения:** Отдельные namespace для Dev/Staging/Prod упрощают фильтрацию метрик.
7. **Audit trail:** Сохраняйте вывод `helm history` как артефакт для compliance.

### Интеграция с существующим мониторингом

| Инструмент | Интеграция | Описание |
|------------|------------|----------|
| Prometheus | kube-state-metrics | Сбор метрик `kube_helm_release_*` |
| Grafana | Dashboard JSON | Визуализация статуса релизов |
| Alertmanager | PrometheusRule | Алерты на failed/stale релизы |
| Helmwave | monitors | Пост-деплойные проверки готовности |
| ArgoCD | notifications | Уведомления о статусе релизов |
| Flux | alerts | Алерты через Provider/Alert CRD |

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
|----------|-------------------|---------|
| Метрики `kube_helm_release_*` отсутствуют | Коллектор `helmrelease` отключён | Включите collectors в values kube-state-metrics |
| Алерты не срабатывают | Prometheus не скрейпит kube-state-metrics | Проверьте ServiceMonitor и targets |
| Dashboard пустой | Нет данных в Prometheus | Проверьте `kubectl port-forward` и query |
| Helmwave monitor fails | Prometheus недоступен из кластера | Проверьте network policies и DNS |
| Слишком много алертов | Нет фильтрации по namespace | Добавьте label selectors в alerting rules |

### См. также

- [Управление версиями Helm](./helm_release_versioning.md) — SemVer, ревизии и история релизов.
- [Команды и рабочий процесс Helm](./helm_commands_and_workflow.md) — жизненный цикл релизов.
- [Helmwave: декларативный оркестратор](./helmwave_overview.md) — мониторы и kubedog.
- [Prometheus: метрики Kubernetes](../../../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — архитектура мониторинга.
- [kube-state-metrics](../../../../MonitoringLogging/metrics-server.md) — экспорт метрик Kubernetes.
