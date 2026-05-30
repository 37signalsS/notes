# Алерты для Kubernetes-приложений (Grafana)

## Определения

**Kubernetes Alerts** — набор правил оповещений для мониторинга состояния приложений и инфраструктуры Kubernetes (K8s).

**kube-state-metrics (KSM)** — сервис, генерирующий метрики о состоянии объектов Kubernetes (поды, деплойменты, ноды) на основе данных из API-сервера (Application Programming Interface).

**cAdvisor (Container Advisor)** — агент, встроенный в Kubelet, который собирает и экспортирует метрики ресурсов (процессор, память, сеть, диск) для всех работающих контейнеров на узле.

**Текущая версия (февраль 2026):** Grafana 12.x, kube-state-metrics 2.x

## Базовые концепции

### Категории алертов

| Категория | Метрики | Источник данных |
| :--- | :--- | :--- |
| **Контейнеры** | Рестарты, OOM (Out Of Memory), CPU, память | kube-state-metrics, cAdvisor |
| **Поды** | Статус фазы, готовность (Readiness), перезапуски | kube-state-metrics |
| **Деплойменты** | Доступные реплики, желаемое состояние | kube-state-metrics |
| **Узлы (Nodes)** | Давление ресурсов, статус доступности | kube-state-metrics, node-exporter |

### Рекомендации по настройке

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Интервал оценки** | 30s–1m для критичных, 5m для предупреждений | Баланс между скоростью реакции и нагрузкой на систему |
| **`for`** | 0m для OOM, 1–5m для рестартов, 10m для ресурсов | Фильтрация кратковременных пиков и ложных срабатываний |
| **`NoData`** | `NoData` (или `OK`) | Метрики динамических объектов могут исчезать при удалении подов |
| **`Error`** | `Error` (или `Alerting`) | Ошибка оценки правила требует расследования |

### Уровни критичности

| Уровень | Сценарии | Способ уведомления |
| :--- | :--- | :--- |
| **Critical** | OOM Killed, CrashLoopBackOff, недоступность узла | Немедленно (PagerDuty, звонок, Telegram) |
| **Warning** | Высокое потребление CPU/памяти (RAM — Random Access Memory), нехватка реплик | В рабочее время (Slack, Email) |
| **Info** | Плановые работы, автоматическое масштабирование | Только дашборды и журналы |

## Практические сценарии

### Алерт: Перезапуск контейнера

Обнаружение цикличных перезапусков (CrashLoopBackOff) или случайных падений.

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
          description: "Зафиксирован рост счетчика рестартов в namespace {{ $labels.namespace }}. Причина: {{ $labels.reason }}"
          runbook: "Проверьте логи: kubectl logs -n {{ $labels.namespace }} {{ $labels.pod }} -c {{ $labels.container }} --previous"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'increase(kube_pod_container_status_restarts_total{namespace=~".+"}[5m]) > 0'
              instant: true
              format: table
```

### Алерт: Завершение по нехватке памяти (OOM Killed)

Срабатывает немедленно при убийстве процесса ядром из-за превышения лимитов памяти.

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
          description: "Процесс в контейнере превысил лимит памяти (Memory Limit) в namespace {{ $labels.namespace }}"
          runbook: "Увеличьте лимиты памяти (resources.limits.memory) или проверьте приложение на утечки"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1'
              instant: true
              format: table
```

### Алерт: Недоступность реплик приложения

Контроль соответствия текущего количества подов желаемому в Deployment или StatefulSet.

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
          summary: "Недоступны реплики в Deployment {{ $labels.deployment }}"
          description: "Доступно: {{ $value }}%, ожидалось: 100%. Namespace: {{ $labels.namespace }}"
          runbook: "Проверьте статус подов: kubectl get pods -n {{ $labels.namespace }} -l app={{ $labels.deployment }}"
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

### Алерт: Высокое потребление ресурсов (CPU/Memory)

Мониторинг утилизации ресурсов относительно установленных лимитов.

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
          description: "Среднее потребление за 5 минут: {{ $value }}% от лимита (Limit)"
          runbook: "Проверьте распределение нагрузки или увеличьте CPU Requests/Limits"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: |
                rate(container_cpu_usage_seconds_total{namespace=~".+", container!=""}[5m])
                /
                kube_pod_container_resource_limits{resource="cpu", namespace=~".+"}
                * 100
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [80] }
                  query: { params: [A] }
```

### Сводная таблица правил

| Алерт | Метрика | Условие (Порог) | Задержка (`for`) | Критичность |
| :--- | :--- | :--- | :--- | :--- |
| **Рестарт контейнера** | `kube_pod_container_status_restarts_total` | `increase > 0` (5m) | 1m | Critical |
| **OOM Killed** | `kube_pod_container_status_last_terminated_reason` | `== 1` | 0m | Critical |
| **Недоступность реплик** | `kube_deployment_status_replicas_available` | `< 90%` | 5m | Warning |
| **Высокое CPU** | `container_cpu_usage_seconds_total` | `> 80% limit` | 10m | Warning |
| **Высокая память** | `container_memory_usage_bytes` | `> 85% limit` | 10m | Warning |

## Дополнительная информация

**См. также:**

- [Provisioning алертов](./provisioning.md) — декларативное управление правилами через YAML (YAML Ain't Markup Language)
- [Основные концепции алертинга](./concepts.md) — жизненный цикл и состояния оповещений
- [Best Practices: Алертинг](./best_practices.md) — общие рекомендации по настройке порогов
- [Общие рекомендации по мониторингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — методологии RED и Golden Signals
- [Мониторинг контейнеров](../../Concepts/Observability_and_Monitoring/observability_in_containers.md) — особенности сбора метрик в K8s
