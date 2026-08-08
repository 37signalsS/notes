# Алерты для Kubernetes-приложений — Grafana Alerting

## Определения

**Kubernetes Alerts** — специализированный набор правил оповещений для мониторинга состояния рабочих нагрузок (Workloads) и инфраструктуры кластера Kubernetes (K8s).

**kube-state-metrics (KSM)** — сервис мониторинга, который слушает API-сервер Kubernetes и генерирует метрики о состоянии объектов (поды, деплойменты, ноды) в формате Prometheus.

**cAdvisor (Container Advisor)** — агент, интегрированный в Kubelet, предоставляющий детальную информацию о потреблении ресурсов (CPU, Memory, Disk IO) на уровне каждого контейнера.

**Node Exporter** — стандартный экспортер для мониторинга аппаратных и системных метрик узлов кластера (диск, сеть, Load Average).

**Версия (2025 год):** Grafana 11.x+, kube-state-metrics 2.x+, Prometheus Operator.

## Базовые концепции

### Категории мониторинга

| Категория | Объекты | Основные метрики |
| :--- | :--- | :--- |
| **Уровень приложений** | Pod, Deployment, StatefulSet | Рестарты, OOMKilled, ImagePullBackOff, Readiness |
| **Уровень ресурсов** | Container | CPU/Memory Limits vs Usage, CPU Throttling |
| **Уровень узлов** | Node | NodeNotReady, Pressure (Disk, Memory, PID) |
| **Уровень хранилищ** | PVC, PV | PVC Capacity, Inode Usage, Volume Errors |
| **Control Plane** | API Server, etcd | API Latency (99th), etcd Leader Changes |

### Рекомендации по настройке

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Интервал оценки** | 30s | Для динамичного окружения K8s интервал в 1m может быть слишком долгим. |
| **`for` (Задержка)** | 0m–15m | 0m для событий (OOM), 2m–5m для состояний (CrashLoop), 15m для ресурсов. |
| **Метки (Labels)** | `severity`, `cluster`, `namespace` | Необходимы для фильтрации в политиках уведомлений и подавления (Inhibition). |
| **Аннотации** | `runbook_url`, `dashboard_url` | Прямая связь алерта с инструкцией по исправлению и визуальным контекстом. |

### Стратегия: От причин к симптомам

Рекомендуется разделять алерты на:
1.  **Symptom-based (Critical):** То, что напрямую влияет на доступность (ошибки API, падение реплик). Требует немедленной реакции.
2.  **Cause-based (Warning):** То, что является предвестником сбоя (рост потребления ресурсов, приближение к лимитам). Анализ в рабочее время.

---

## Практические сценарии

### Группа: Состояние рабочих нагрузок (Workloads)

#### Алерт: Цикличный перезапуск (CrashLoopBackOff)
```yaml
      - uid: pod_crashloop_backoff
        title: Pod is in CrashLoopBackOff
        condition: A
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Пользовательский под {{ $labels.pod }} в состоянии CrashLoopBackOff"
          description: "Под в namespace {{ $labels.namespace }} перезапускается слишком часто."
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1'
```

#### Алерт: Завершение по нехватке памяти (OOMKilled)
```yaml
      - uid: pod_oomkilled
        title: Pod was OOMKilled
        condition: A
        for: 0m
        labels:
          severity: critical
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1'
```

### Группа: Ресурсы и лимиты

#### Алерт: CPU Throttling (Ограничение производительности)
Сигнализирует о том, что контейнер упирается в CPU Limit и его производительность искусственно ограничивается.
```yaml
      - uid: container_cpu_throttling
        title: Container is being CPU throttled
        condition: A
        for: 5m
        labels:
          severity: warning
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum(rate(container_cpu_cfs_throttled_seconds_total[5m])) by (namespace, pod, container) > 1'
```

### Группа: Инфраструктура узлов (Nodes)

#### Алерт: Узел не готов (Node Not Ready)
```yaml
      - uid: node_not_ready
        title: Node is not ready
        condition: A
        for: 5m
        labels:
          severity: critical
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_node_status_condition{condition="Ready", status="true"} == 0'
```

#### Алерт: Давление на ресурсы узла (Node Pressure)
```yaml
      - uid: node_resource_pressure
        title: Node is under resource pressure
        condition: A
        for: 2m
        labels:
          severity: critical
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_node_status_condition{condition=~"DiskPressure|MemoryPressure|PIDPressure", status="true"} == 1'
```

### Группа: Хранилища (Storage)

#### Алерт: Исчерпание Inodes на томе
```yaml
      - uid: pvc_inodes_low
        title: PVC Inodes low
        condition: A
        for: 15m
        labels:
          severity: warning
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kubelet_volume_stats_inodes_free / kubelet_volume_stats_inodes * 100 < 10'
```

---

## Управление алертами как кодом (Alerting as Code)

Ручное редактирование алертов в UI не рекомендуется для Production-сред. Используйте следующие инструменты:
- **Terraform/OpenTofu:** Ресурсы `grafana_alert_rule` и `grafana_notification_policy`.
- **Grizzly:** Утилита от Grafana Labs для синхронизации YAML-описаний.
- **Prometheus Operator:** Использование Custom Resources `PrometheusRule` (если Grafana работает в режиме управления правилами бэкенда).
- **Provisioning:** Встроенный механизм Grafana для загрузки правил из YAML-файлов при старте.

## Дополнительная информация

**См. также:**

- [Провиженинг алертов в Grafana](./provisioning.md) — детали настройки YAML.
- [Лучшие практики алертинга](./best_practices.md) — методологии RED и USE.
- [Мониторинг ресурсов нод node-exporter](../../Prometheus/Exporters/node_exporter.md).
- [Kube-state-metrics — детальное описание](../../Prometheus/Exporters/kube_state_metrics.md).
