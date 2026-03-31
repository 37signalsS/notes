# Алерты для Kubernetes-приложений

## Определения

**Kubernetes Alerts** — набор правил оповещений для мониторинга здоровья приложений и инфраструктуры Kubernetes.

**kube-state-metrics** — источник метрик о состоянии объектов Kubernetes (поды, деплойменты, ноды).

**cAdvisor** — источник метрик об использовании ресурсов контейнерами (CPU, память).

**Текущая версия (февраль 2026):** Grafana 12.x, kube-state-metrics 2.x

## Базовые концепции

### Категории алертов

| Категория | Метрики | Источник |
| :--- | :--- | :--- |
| **Контейнеры** | Рестарты, OOM, CPU, память | kube-state-metrics, cAdvisor |
| **Поды** | Статус, готовость, перезапуски | kube-state-metrics |
| **Деплойменты** | Реплики, доступность | kube-state-metrics |
| **Ноды** | Давление ресурсов, недоступность | kube-state-metrics, node-exporter |

### Рекомендации по настройке

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Интервал оценки** | 30s–1m для критичных, 5m для warning | Баланс между скоростью и нагрузкой |
| **`for`** | 0m для OOM, 1–5m для рестартов, 10m для ресурсов | Фильтрация кратковременных аномалий |
| **`NoData`** | NoData (не Alerting) | Метрики могут быть непостоянны |
| **`Error`** | Error | Ошибка оценки = проблема |

### Уровни критичности

| Уровень | Сценарии | Реакция |
| :--- | :--- | :--- |
| **Critical** | OOM Killed, CrashLoopBackOff, недоступность ноды | Немедленная (PagerDuty, звонок) |
| **Warning** | Высокое потребление CPU/памяти, частичная недоступность | В рабочее время (Email, Slack) |
| **Info** | Плановые рестарты, масштабирование | Только дашборды |

## Практические сценарии

### Алерт на перезапуск контейнера

**Назначение:** Обнаружение нестабильности контейнеров.

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

**Параметры:**
- **Выражение:** `increase(kube_pod_container_status_restarts_total[5m]) > 0`
- **Порог:** Любой рестарт за 5 минут
- **`for`:** 1m (подтверждение)

---

### Алерт на OOM Killed

**Назначение:** Обнаружение нехватки памяти.

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

**Параметры:**
- **Выражение:** `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1`
- **Порог:** Любое событие
- **`for`:** 0m (немедленное срабатывание)

---

### Алерт на недоступность реплик

**Назначение:** Контроль доступности деплоймента.

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

**Параметры:**
- **Выражение:** `kube_deployment_status_replicas_available / kube_deployment_status_replicas * 100`
- **Порог:** < 90%
- **`for`:** 5m

---

### Алерт на высокое потребление CPU

**Назначение:** Обнаружение перегрузки контейнеров.

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

**Параметры:**
- **Выражение:** `rate(container_cpu_usage_seconds_total[5m]) / kube_pod_container_resource_limits{resource="cpu"} * 100`
- **Порог:** > 80% от limits
- **`for`:** 10m

---

### Алерт на высокое потребление памяти

**Назначение:** Обнаружение утечек памяти.

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

**Параметры:**
- **Выражение:** `container_memory_usage_bytes / kube_pod_container_resource_limits{resource="memory"} * 100`
- **Порог:** > 85% от limits
- **`for`:** 10m

---

### Сводная таблица алертов

| Алерт | Метрика | Порог | `for` | Критичность |
| :--- | :--- | :--- | :--- | :--- |
| Перезапуск контейнера | `kube_pod_container_status_restarts_total` | > 0 за 5m | 1m | Critical |
| OOM Killed | `kube_pod_container_status_last_terminated_reason` | == 1 | 0m | Critical |
| Недоступность реплик | `kube_deployment_status_replicas_available` | < 90% | 5m | Warning |
| Высокое CPU | `container_cpu_usage_seconds_total` | > 80% limits | 10m | Warning |
| Высокая память | `container_memory_usage_bytes` | > 85% limits | 10m | Warning |

## Дополнительная информация

**Связанные темы:**

- [Provisioning алертов](./provisioning.md) — структура правил алертинга
- [Основные концепции Grafana Alerting](./concepts.md) — состояния правил, NoData, Error
- [Best practices](./best_practices.md) — рекомендации по настройке `for` и интервалов
- [Общие принципы алертинга](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — методологии и рекомендации
- [Observability в контейнерах](../../Concepts/Observability_and_Monitoring/observability_in_containers.md) — мониторинг контейнеризированных приложений
