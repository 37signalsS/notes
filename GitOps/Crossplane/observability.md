# Crossplane: Observability (метрики, алерты, логи)

## Определения

**Метрики Crossplane** — Prometheus-совместимые показатели, которые Crossplane и провайдеры экспортируют на порту `8080` (`/metrics`). Позволяют наблюдать здоровье control plane и managed-ресурсов (MR).

**Условия Ready / Synced** — два ключевых Kubernetes-условия на каждом MR/XR:
- `Synced=True` — состояние в облаке соответствует желаемому (Crossplane успешно применил изменения).
- `Ready=True` — ресурс полностью provisioned и доступен. Ресурс может быть `Ready` но `Synced=False`, если его изменили вручную в облаке (дрейф).

> Метрики Crossplane не имеют гарантии стабильности (могут меняться между версиями).

## Базовые концепции

- **Core-метрики** экспортирует сам Crossplane; **provider-метрики** (`crossplane_managed_resource_*`) — все провайдеры на базе `crossplane-runtime`.
- Сбор не включён автоматически: нужен `PodMonitor`/`ServiceMonitor` или `DeploymentRuntimeConfig` с аннотациями Prometheus.
- Upjet-провайдеры дают дополнительные метрики (вызовы облачного API и т.п.).

## Практические сценарии

### 1. Включение сбора (DeploymentRuntimeConfig / PodMonitor)
```yaml
apiVersion: pkg.crossplane.io/v1alpha1
kind: DeploymentRuntimeConfig
metadata:
  name: metrics
spec:
  deploymentTemplate:
    spec:
      selector: {}
      metadata:
        annotations:
          prometheus.io/scrape: "true"
          prometheus.io/port: "8080"
          prometheus.io/path: /metrics
```
Либо создайте `PodMonitor` на поды `crossplane-system` с портом `8080`.

### 2. Быстрая проверка метрик вручную
```bash
kubectl -n crossplane-system port-forward deployment/crossplane 8080:8080
curl -s localhost:8080/metrics | grep crossplane_managed_resource
```

### 3. Ключевые метрики провайдеров
| Метрика | Смысл |
| --- | --- |
| `crossplane_managed_resource_exists` | количество существующих MR |
| `crossplane_managed_resource_ready` | MR в `Ready=True` |
| `crossplane_managed_resource_synced` | MR в `Synced=True` |
| `crossplane_managed_resource_drift_seconds` | время с последней успешной сверки при обнаружении рассинхрона |
| `crossplane_managed_resource_first_time_to_readiness_seconds` | время до первого `Ready` |
| `crossplane_managed_resource_deletion_seconds` | время удаления MR |

### 4. PromQL-запросы
```promql
# Доля неготовых MR
1 - (crossplane_managed_resource_ready / crossplane_managed_resource_exists)

# Обнаруженный дрейф
crossplane_managed_resource_drift_seconds > 0

# Провайдер не здоров (по условиям Provider)
kube_customresourcestatus_conditions{type="Healthy",status="False",kind="Provider"}
```

### 5. Alertmanager-правила
```yaml
groups:
  - name: crossplane
    rules:
      - alert: CrossplaneMRNotReady
        expr: crossplane_managed_resource_ready == 0
        for: 10m
        labels: { severity: critical }
        annotations:
          summary: "MR {{ $labels.name }} не готов >10m"
      - alert: CrossplaneDriftDetected
        expr: crossplane_managed_resource_drift_seconds > 0
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Дрейф ресурса {{ $labels.name }}"
      - alert: ProviderNotHealthy
        expr: kube_customresourcestatus_conditions{type="Healthy",status="False",kind="Provider"} == 1
        for: 5m
        labels: { severity: critical }
```

### 6. Grafana-дашборд
Готовый дашборд Crossplane Metrics: [grafana.com/dashboards/24549](https://grafana.com/grafana/dashboards/24549-crossplane-metrics/). Импортируйте по ID; источник — Prometheus с собранными метриками.

### 7. Логи и трассировка
```bash
kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-yandex-cloud -c provider-yandex-cloud
crossplane alpha trace <kind> <name>   # цепочка реконсиляции XR/MR
```

## Дополнительная информация

- [Metrics (официальная документация)](https://docs.crossplane.io/latest/guides/metrics/)
- [Crossplane Metrics Dashboard (Grafana)](https://grafana.com/grafana/dashboards/24549-crossplane-metrics/)
- Референсная платформа наблюдения: `upbound/configuration-observability-oss`.

Смежные темы:
- [Тестирование платформы](./testing_crossplane.md) — ловить `Synced=False` до прода.
- [Provider Kubernetes: отладка](./provider_kubernetes_setup.md) — `crossplane alpha trace`.
- [GitOps Integration](./gitops_integration.md) — мониторинг доставки.
- [Обзор Crossplane](./overview.md).
