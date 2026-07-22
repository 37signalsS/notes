# Алерты для Kubernetes-приложений — Grafana Alerting

## Определения

**Kubernetes Alerts** — специализированный набор правил оповещений для мониторинга состояния рабочих нагрузок (Workloads) и инфраструктуры кластера Kubernetes (K8s).

**kube-state-metrics (KSM)** — сервис мониторинга, который слушает API-сервер Kubernetes и генерирует метрики о состоянии объектов (поды, деплойменты, ноды) в формате Prometheus.

**cAdvisor (Container Advisor)** — агент, интегрированный в Kubelet, предоставляющий детальную информацию о потреблении ресурсов (CPU, Memory, Disk IO) на уровне каждого контейнера.

**Node Exporter** — стандартный экспортер для мониторинга аппаратных и системных метрик узлов кластера (диск, сеть, Load Average).

**Текущая версия (февраль 2026):** Grafana 12.x+, kube-state-metrics 2.x+, Prometheus Operator.

## Базовые концепции

### Категории мониторинга (Baseline 2026)

| Категория | Объекты | Основные метрики |
| :--- | :--- | :--- |
| **Уровень приложений** | Pod, Deployment, StatefulSet | Рестарты, OOMKilled, ImagePullBackOff, Readiness |
| **Уровень ресурсов** | Container | CPU/Memory Limits vs Usage, Throttling |
| **Уровень узлов** | Node | NodeNotReady, DiskPressure, MemoryPressure |
| **Уровень хранилищ** | PVC, PV | PVC Capacity, Volume Errors |
| **Control Plane** | API Server, etcd | API Latency (99th), etcd Leader Changes |

### Рекомендации по настройке

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Интервал оценки** | 30s | Для K8s динамики интервал в 1m может быть слишком долгим для критичных сбоев. |
| **`for` (Задержка)** | 0m–15m | 0m для событий (OOM), 2m–5m для состояний (CrashLoop), 15m для ресурсов. |
| **Метки (Labels)** | `severity`, `cluster`, `namespace` | Необходимы для фильтрации в Notification Policies и подавления (Inhibition). |
| **Аннотации** | `runbook_url`, `dashboard_url` | Прямая связь алерта с инструкцией по исправлению и визуальным контекстом. |

### Стратегия: От причин к симптомам

В 2026 году рекомендуется разделять алерты на:
1.  **Symptom-based (Critical):** То, что видит пользователь (ошибки API, недоступность сервиса). Будит инженера.
2.  **Cause-based (Warning):** То, что может стать причиной сбоя скоро (нехватка памяти, высокая нагрузка CPU). Отправляется в мессенджеры.

## Практические сценарии

### Группа: Состояние рабочих нагрузок (Workloads)

#### Алерт: Цикличный перезапуск (CrashLoopBackOff)
Обнаруживает поды, которые не могут запуститься или падают сразу после старта.

```yaml
# provisioning/alerting/rules/k8s-workloads.yaml
      - uid: pod_crashloop_backoff
        title: Pod is in CrashLoopBackOff
        condition: A
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Пользовательский под {{ $labels.pod }} в состоянии CrashLoopBackOff"
          description: "Под в namespace {{ $labels.namespace }} перезапускается слишком часто."
          runbook_url: "https://wiki.example.com/k8s/troubleshooting#crashloop"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1'
```

#### Алерт: Ошибка загрузки образа (ImagePullBackOff)
Критично при деплое новых версий.

```yaml
      - uid: pod_image_pull_error
        title: Pod cannot pull image
        condition: A
        for: 10m
        labels:
          severity: warning
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} == 1'
```

### Группа: Инфраструктура узлов (Nodes)

#### Алерт: Узел не готов (Node Not Ready)
Критическая недоступность части вычислительных ресурсов кластера.

```yaml
      - uid: node_not_ready
        title: Node is not ready
        condition: A
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Узел {{ $labels.node }} не в статусе Ready"
          description: "Кластер {{ $labels.cluster }} потерял узел. Поды будут перенесены (evicted)."
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_node_status_condition{condition="Ready", status="true"} == 0'
```

### Группа: Хранилища (Storage)

#### Алерт: Переполнение тома (PVC Saturation)
Предупреждение о нехватке места в PersistentVolume.

```yaml
      - uid: pvc_disk_space_low
        title: PVC disk space low
        condition: A
        for: 15m
        labels:
          severity: warning
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes * 100 < 10'
```

### Группа: Control Plane (API Server)

#### Алерт: Высокая задержка API сервера
Сигнализирует о деградации производительности всего кластера.

```yaml
      - uid: apiserver_latency_high
        title: API Server Latency high
        condition: A
        for: 5m
        labels:
          severity: warning
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{job="apiserver"}[5m])) by (le)) > 1'
```

## Управление алертами как кодом (Alerting as Code)

В 2026 году ручное редактирование алертов в UI запрещено для Production-сред. Используйте следующие инструменты:
- **Terraform/OpenTofu:** Для управления `grafana_alert_rule` и `grafana_notification_policy`.
- **Grizzly:** Утилита от Grafana Labs для синхронизации YAML-описаний алертов.
- **Prometheus Operator:** Если используется self-hosted стек, основным SSoT являются объекты `PrometheusRule` в Kubernetes.

## Интеллектуальный анализ (AI RCA)

Современные системы (например, **K8sGPT** или интегрированный **Grafana Incident AI**) позволяют автоматически обогащать алерты контекстом:
- Анализ логов в момент срабатывания.
- Предложение kubectl-команд для диагностики.
- Группировка подов по общей причине (например, общая недоступность БД).

## Дополнительная информация

**См. также:**

- [Provisioning алертов в Grafana](./provisioning.md) — детали настройки YAML.
- [Best Practices: Алертинг](./best_practices.md) — методологии RED и USE.
- [Мониторинг ресурсов нод node-exporter](../../Prometheus/Exporters/node_exporter.md).
- [Kube-state-metrics — детали метрик](../../Prometheus/Exporters/kube_state_metrics.md).
