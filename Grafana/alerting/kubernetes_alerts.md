# Алерты для Kubernetes-приложений

Этот сценарий описывает настройку критически важных алертов для мониторинга здоровья приложения в Kubernetes.

## Алерт на падение контейнера

```yaml
# provisioning/alerting/kubernetes-container-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: kubernetes-container-health
    folder: Kubernetes
    interval: 30s
    rules:
      - uid: container_restarted
        title: Container restarted
        condition: A
        for: 1m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} перезапустился"
          description: "Причина: {{ $labels.reason }}, Exit code: {{ $labels.exit_code }}"
          runbook: "Проверьте логи: kubectl logs -n {{ $labels.namespace }} {{ $labels.pod }} -c {{ $labels.container }}"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'increase(kube_pod_container_status_restarts_total{namespace=~".+"}[5m]) > 0'
              instant: true
              format: table
```

## Алерт на OOM Killed

```yaml
      - uid: container_oom_killed
        title: Container OOM Killed
        condition: A
        for: 0m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.container }} убит по OOM в поде {{ $labels.pod }}"
          description: "Namespace: {{ $labels.namespace }}, Причина: OOMKilled"
          runbook: "Увеличьте memory limits или оптимизируйте потребление памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1'
              instant: true
              format: table
```

## Алерт на недоступность реплик

```yaml
      - uid: deployment_replicas_unavailable
        title: Deployment replicas unavailable
        condition: B
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Недоступны реплики в deployment {{ $labels.deployment }}"
          description: "Доступно: {{ $value }}%, Ожидалось: 100%"
          runbook: "Проверьте события: kubectl describe deployment -n {{ $labels.namespace }} {{ $labels.deployment }}"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_deployment_status_replicas_available{namespace=~".+"} / kube_deployment_status_replicas{namespace=~".+"} * 100'
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: lt, params: [90] }
                  query: { params: [A] }
```

## Алерт на высокое потребление CPU

```yaml
      - uid: container_cpu_high
        title: Container CPU usage high
        condition: B
        for: 10m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Высокое потребление CPU контейнером {{ $labels.container }}"
          description: "Потребление: {{ $value }}% от limits"
          runbook: "Проанализируйте нагрузку на приложение"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: |
                rate(container_cpu_usage_seconds_total{namespace=~".+", container!=""}[5m])
                /
                kube_pod_container_resource_limits{resource="cpu", namespace=~".+"}
                * 100
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [80] }
                  query: { params: [A] }
```

## Алерт на высокое потребление памяти

```yaml
      - uid: container_memory_high
        title: Container Memory usage high
        condition: B
        for: 10m
        noDataState: NoData
        execErrState: Error
        labels:
          service: kubernetes
          severity: warning
        annotations:
          summary: "Высокое потребление памяти контейнером {{ $labels.container }}"
          description: "Потребление: {{ $value }}% от limits"
          runbook: "Проверьте на наличие утечек памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: |
                container_memory_usage_bytes{namespace=~".+", container!=""}
                /
                kube_pod_container_resource_limits{resource="memory", namespace=~".+"}
                * 100
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [85] }
                  query: { params: [A] }
```

---

**Связанные темы:**

* [Provisioning](./provisioning.md) — структура правил алертинга
* [Основные концепции](./concepts.md) — состояния правил, NoData, Error
* [Best practices](./best_practices.md) — рекомендации по настройке `for` и интервалов
