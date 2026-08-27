# Алерты для Kubernetes-приложений — Grafana Alerting

> Версия (проверено август 2026): Grafana 12.x/13.x, kube-state-metrics 2.x, кластер Kubernetes 1.25+, cAdvisor (встроен в kubelet), Prometheus Operator / kube-prometheus-stack. Алерты создаются как Grafana-managed правила, использующие Prometheus в качестве источника данных (данные скребутся из kube-state-metrics, cAdvisor и node-exporter).

## Определения

**Kubernetes Alerts** — специализированный набор правил оповещений для мониторинга состояния рабочих нагрузок (Workloads) и инфраструктуры кластера Kubernetes (K8s). В Grafana Alerting это Grafana-managed alert rules, вычисляемые сервером Grafana на основе метрик из Prometheus-совместимого источника.

**kube-state-metrics (KSM)** — сервис мониторинга, который слушает API-сервер Kubernetes и генерирует метрики о состоянии объектов (поды, деплойменты, ноды, PVC) в формате Prometheus. KSM отражает **желаемое vs фактическое состояние** (desired vs actual), а не потребление ресурсов. В версии 2.x метрики `kube_pod_container_status_waiting_reason`, `kube_pod_container_status_last_terminated_reason`, `kube_deployment_status_replicas_available` и `kube_node_status_condition` стабильны и пригодны для алертинга.

**cAdvisor (Container Advisor)** — агент, интегрированный в kubelet, предоставляющий детальную информацию о потреблении ресурсов (CPU, Memory, Disk IO) на уровне каждого контейнера. Источник метрик `container_*`.

**Node Exporter** — стандартный экспортер для мониторинга аппаратных и системных метрик узлов кластера (диск, сеть, Load Average, память). Источник метрик `node_*`.

**kube-prometheus-stack** — Helm-чарт (prometheus-community, 87.x+, OCI-артефакт), объединяющий Prometheus Operator, Prometheus, Alertmanager, Grafana, node-exporter и kube-state-metrics с набором готовых правил и дашбордов. В 2026 году — де-факто стандарт развёртывания стека мониторинга в K8s.

**Recording Rule (Правило записи)** — предварительно вычисляемое выражение, результат которого сохраняется как новая метрика. Снижает нагрузку на источник и ускоряет оценку алертов.

## Базовые концепции

### Источники метрик и зоны ответственности

Каждая метрика приходит из конкретного экспортера — путаница в источниках ведёт к неработающим алертам.

| Экспортер | Что измеряет | Примеры метрик для алертинга |
| :--- | :--- | :--- |
| **kube-state-metrics** | Состояние объектов API (желаемое vs фактическое) | `kube_pod_container_status_waiting_reason`, `kube_deployment_status_replicas_available`, `kube_node_status_condition`, `kube_pod_status_ready` |
| **cAdvisor (kubelet)** | Потребление ресурсов контейнеров | `container_cpu_cfs_throttled_seconds_total`, `container_memory_working_set_bytes`, `container_spec_memory_limit_bytes` |
| **Node Exporter** | Аппаратные/ОС метрики узла | `node_filesystem_avail_bytes`, `node_memory_MemAvailable_bytes`, `node_cpu_seconds_total` |
| **kubelet** | Состояние томов и сертификатов | `kubelet_volume_stats_*`, `kubelet_certificate_manager_*` |
| **etcd / API-server** | Control Plane (требует отдельных scrape-джобов) | `etcd_server_leader_changes_seen_total`, `apiserver_request_duration_seconds_bucket` |

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
| **Интервал оценки** | 30s | Для динамичного окружения K8s интервал в 1m может быть слишком долгим. Критичные алерты — 15–30s, стандарт — 1m, несрочные/шумные — 5m. |
| **`for` (Задержка)** | 0m–15m | 0m для событий (OOM, leader change), 2m–5m для состояний (CrashLoop, NodeNotReady), 15m для ресурсов и недоступных реплик. |
| **Метки (Labels)** | `severity`, `cluster`, `namespace` | Необходимы для фильтрации в политиках уведомлений и подавления (Inhibition). Добавляйте `team` для владельца. |
| **Аннотации** | `runbook_url`, `dashboard_url`, `summary` | Прямая связь алерта с инструкцией по исправлению и визуальным контекстом; снижает время реакции (MTTR). |
| **`execErrState`** | `KeepLastState` | При транзитной ошибке источника (сетевой блип, таймаут) не переводить алерт в `Alerting` — иначе ложные страницы. Исследуйте причину ошибок отдельно. |
| **`noDataState`** | `Alerting` (critical) / `NoData` (warning) | Для критичных алертов пропажа метрики = инцидент (KSM/Prometheus упал). Для warning оставляйте `NoData`, чтобы не страдать на перекатах. |
| **Окно в `rate()`** | `$__rate_interval` | Встроенная переменная подстраивает окно под интервал скрейпа и оценки, гарантируя достаточную выборку и устойчивость к дрейфу scrape interval. |

### Стратегия: От причин к симптомам

Рекомендуется разделять алерты на:
1.  **Symptom-based (Critical):** То, что напрямую влияет на доступность (ошибки API, падение реплик, NodeNotReady). Требует немедленной реакции (page).
2.  **Cause-based (Warning):** То, что является предвестником сбоя (рост потребления ресурсов, приближение к лимитам). Анализ в рабочее время (тикет/Slack).

Градация severity (пример):
- `critical` — страница on-call (PagerDuty/Opsgenie), немедленное действие.
- `warning` — уведомление в канал команды, разбор в рабочее время.
- `info` — только в ленту/дашборд, без уведомления.

Эта модель совпадает с [best practices](../alerting/best_practices.md): симптомы первичны, инфраструктурные сигналы — поддержка диагностики, а не повод для страницы.

### Многомерные правила и снижение шума

- **Многомерность:** одно правило должно масштабироваться на весь кластер через метки (`namespace`, `pod`, `container`), а не дублироваться «на каждый сервис». Grafana порождает отдельный экземпляр алерта на каждый уникальный набор меток.
- **`group_by`:** группируйте уведомления по `['alertname', 'cluster', 'namespace']`. **Не группируйте и не создавайте алерты по высококардинальным меткам** (`pod`, `instance`, `container`) без необходимости — это взрывает количество экземпляров и шум.
- **`keep_firing_for`:** удерживайте алерт активным несколько минут после возврата в норму, чтобы избежать каскадов `Alerting`/`Resolved` (flapping) на границе порога.
- **Сглаживание:** используйте `avg_over_time()` / окно в `rate()` и осмысленный `for`, чтобы не алертить на кратковременные пики.
- **Минимальный объём (volume floor):** для алертов по долям (ошибки %) добавляйте `and sum(...) > N`, чтобы 1 павший запрос из 20 не поднимал on-call.
- **`absent()` для доступности:** отсутствие метрики часто важнее её значения — алерт на падение KSM/node-exporter через `absent()`.

## Практические сценарии

### Предварительные требования

- **Grafana:** 12.x или 13.x (OSS/Enterprise); файловый провиженинг недоступен в Grafana Cloud.
- **Источник данных:** Prometheus/Mimir настроен и проверен (совпадающий `datasourceUid`). Метрики `kube_*` скребутся из kube-state-metrics, `container_*` — из cAdvisor (kubelet), `node_*` — из node-exporter.
- **kube-state-metrics 2.x:** развёрнут и экспортирует нужные метрики (проверьте `kube_pod_container_status_waiting_reason`, `kube_node_status_condition`).
- **Контакт-пойнты:** хотя бы один настроен (Slack/Telegram) и протестирован кнопкой Test (см. [Provisioning](../alerting/provisioning.md)).
- **Метки:** во все правила добавлены `cluster` (при нескольких кластерах) и `namespace` — иначе при мультикластере алерты неразличимы.
- **Секреты:** при файловом провиженинге включён `enable_env_vars_interpolation = true` в `grafana.ini` для `${TOKEN}`.

### Структура провиженинга (полный файл правил)

Каждый файл начинается с `apiVersion: 1` и содержит одну или несколько групп. Группы с общим `interval` оцениваются синхронно — это важно для выражений, ссылающихся друг на друга.

```yaml
# provisioning/alerting/rules/k8s-workloads.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: "Kubernetes / Workloads"
    folder: "Kubernetes"
    folderUid: "k8s-folder"
    interval: 30s
    rules:
      # ... правила ниже ...
```

Поле `datasourceUid: prometheus_ds_uid` — **плейсхолдер**, замените на реальный UID источника данных Grafana. Все правила имеют статичный `uid` для идемпотентности.

### Группа: Состояние рабочих нагрузок (Workloads)

#### Алерт: Цикличный перезапуск (CrashLoopBackOff)
```yaml
      - uid: pod_crashloop_backoff
        title: Pod is in CrashLoopBackOff
        condition: A
        for: 5m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Пользовательский под {{ $labels.pod }} в состоянии CrashLoopBackOff"
          description: "Под в namespace {{ $labels.namespace }} перезапускается слишком часто."
          runbook_url: "https://wiki.example.com/runbooks/crashloopbackoff"
          dashboard_url: "https://grafana.example.com/d/k8s-pod"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            queryType: ""
            relativeTimeRange:
              from: 600
              to: 0
            model:
              expr: 'kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1'
              instant: true
              format: time_series
```

#### Алерт: Завершение по нехватке памяти (OOMKilled)
```yaml
      - uid: pod_oomkilled
        title: Pod was OOMKilled
        condition: A
        for: 0m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Под {{ $labels.pod }} завершён по OOMKilled (container {{ $labels.container }})"
          description: "Контейнер превысил лимит памяти и был убит OOM Killer."
          runbook_url: "https://wiki.example.com/runbooks/oomkilled"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            queryType: ""
            relativeTimeRange:
              from: 600
              to: 0
            model:
              expr: 'kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1'
              instant: true
              format: time_series
```

> `for: 0m` — OOM это дискретное событие, фиксируемое сразу. Учтите: `last_terminated_reason` отражает **только последнее** завершение; если под восстановился, метка может оставаться до следующего перезапуска. Для устойчивого детекта используйте счётчик рестартов: `increase(kube_pod_container_status_restarts_total[1h]) > 5`.

#### Алерт: Под не готов (Pod Not Ready)
```yaml
      - uid: pod_not_ready
        title: Pod is not ready
        condition: A
        for: 15m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Под {{ $labels.namespace }}/{{ $labels.pod }} не готов > 15m"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_status_ready{condition="false"} == 1'
              instant: true
```

#### Алерт: Ошибка загрузки образа (ImagePullBackOff)
```yaml
      - uid: pod_imagepullbackoff
        title: Pod is in ImagePullBackOff
        condition: A
        for: 5m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Под {{ $labels.pod }} не может загрузить образ"
          runbook_url: "https://wiki.example.com/runbooks/imagepull"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"} == 1'
              instant: true
```

#### Алерт: Несовпадение числа реплик Deployment (Replicas Mismatch)
```yaml
      - uid: deployment_replicas_mismatch
        title: Deployment has unavailable replicas
        condition: A
        for: 15m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} не раскатал реплики"
          description: "Запрошено {{ $value }} реплик, доступно меньше."
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_deployment_spec_replicas != kube_deployment_status_available_replicas'
              instant: true
```

#### Алерт: Зависший раскат Deployment (Rollout Stuck)
```yaml
      - uid: deployment_rollout_stuck
        title: Deployment rollout is stuck
        condition: A
        for: 30m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} завис в раскате"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_deployment_status_observed_generation != kube_deployment_metadata_generation'
              instant: true

### Группа: Ресурсы и лимиты

#### Алерт: CPU Throttling (Ограничение производительности)
Сигнализирует о том, что контейнер упирается в CPU Limit и его производительность искусственно ограничивается (CFS throttling срабатывает только при наличии `limits.cpu`).
```yaml
      - uid: container_cpu_throttling
        title: Container is being CPU throttled
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Контейнер {{ $labels.namespace }}/{{ $labels.pod }}/{{ $labels.container }} троттлится по CPU"
          description: "Суммарное время ограничения CPU > 1s за 5m — возможно, лимит CPU слишком жёсткий."
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum(rate(container_cpu_cfs_throttled_seconds_total[5m])) by (namespace, pod, container) > 1'
              instant: true
```

#### Алерт: Использование памяти близко к лимиту
```yaml
      - uid: container_memory_near_limit
        title: Container memory usage near limit
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Контейнер {{ $labels.namespace }}/{{ $labels.pod }}/{{ $labels.container }} использует >90% лимита памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'container_memory_working_set_bytes{container!=""} / container_spec_memory_limit_bytes > 0.9 and container_spec_memory_limit_bytes > 0'
              instant: true
```
> Условие `container_spec_memory_limit_bytes > 0` отсекает контейнеры без лимита (деление на 0 даёт `NaN` и скрывает алерт). Для детекта утечек памяти коррелируйте с ростом `container_memory_working_set_bytes` во времени.

#### Алерт: HPA не может масштабировать (AbleToScale=false)
```yaml
      - uid: hpa_not_able_to_scale
        title: HPA is unable to scale
        condition: A
        for: 15m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} не может масштабировать"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_horizontalpodautoscaler_status_condition{condition="AbleToScale",status="false"} == 1'
              instant: true
```

### Группа: Инфраструктура узлов (Nodes)

#### Алерт: Узел не готов (Node Not Ready)
```yaml
      - uid: node_not_ready
        title: Node is not ready
        condition: A
        for: 5m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Узел {{ $labels.node }} не в состоянии Ready > 5m"
          runbook_url: "https://wiki.example.com/runbooks/node-not-ready"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_node_status_condition{condition="Ready", status="true"} == 0'
              instant: true
```

#### Алерт: Давление на ресурсы узла (Node Pressure)
```yaml
      - uid: node_resource_pressure
        title: Node is under resource pressure
        condition: A
        for: 2m
        noDataState: Alerting
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Узел {{ $labels.node }} под давлением ({{ $labels.condition }})"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kube_node_status_condition{condition=~"DiskPressure|MemoryPressure|PIDPressure", status="true"} == 1'
              instant: true
```

#### Алерт: Свободное место на диске узла (root)
```yaml
      - uid: node_disk_space_low
        title: Node root filesystem is almost full
        condition: A
        for: 15m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "На узле {{ $labels.node }} осталось <15% места на {{ $labels.mountpoint }}"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: '(node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.15'
              instant: true
```

#### Алерт: Доступная память узла низка
```yaml
      - uid: node_memory_low
        title: Node has low available memory
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "На узле {{ $labels.node }} доступно <10% памяти"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: '(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) < 0.10'
              instant: true
```

### Группа: Хранилища (Storage)

#### Алерт: Исчерпание Inodes на томе
```yaml
      - uid: pvc_inodes_low
        title: PVC Inodes low
        condition: A
        for: 15m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "PVC {{ $labels.namespace }}/{{ $labels.persistentvolumeclaim }} — inodes < 10%"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kubelet_volume_stats_inodes_free / kubelet_volume_stats_inodes * 100 < 10'
              instant: true
```

#### Алерт: Место на PVC заканчивается
```yaml
      - uid: pvc_space_low
        title: PVC free space low
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "PVC {{ $labels.namespace }}/{{ $labels.persistentvolumeclaim }} — свободно < 10%"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes < 0.1'
              instant: true
```

### Группа: Control Plane

> Требует отдельных scrape-джобов (в kube-prometheus-stack они преднастроены): etcd, kube-apiserver, kube-controller-manager.

#### Алерт: Задержка API Server (99-й перцентиль)
```yaml
      - uid: apiserver_high_latency
        title: API server request latency high (p99)
        condition: A
        for: 10m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "API Server p99 > 1s за 10m"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH|WATCHLIST"}[5m])) by (le)) > 1'
              instant: true
```

#### Алерт: Смена лидера etcd
```yaml
      - uid: etcd_leader_change
        title: etcd leader changed
        condition: A
        for: 0m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Произошла смена лидера etcd — возможна деградация Control Plane"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'changes(etcd_server_leader_changes_seen_total[15m]) > 0'
              instant: true
```

#### Алерт: Истечение сертификатов kubelet
```yaml
      - uid: kubelet_cert_expiry
        title: Kubelet certificate expiring soon
        condition: A
        for: 0m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Сертификат kubelet на {{ $labels.node }} истекает < 7 дней"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'min(kubelet_certificate_manager_server_ttl_seconds, kubelet_certificate_manager_client_ttl_seconds) < 86400 * 7'
              instant: true
```
> Метрики `kubelet_certificate_manager_*` экспортируются самим kubelet (`/metrics`); убедитесь, что они скребутся. Для API Server/controller-manager используйте аналогичные метрики из их scrape-джобов.

### Группа: Доступность экспортеров (absent)

Отсутствие метрик часто важнее значения — если KSM или node-exporter упали, целевые алерты «ослепнут».

```yaml
      - uid: ksm_down
        title: kube-state-metrics is down
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Метрики kube-state-metrics отсутствуют — K8s-алерты не работают"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'absent(kube_node_status_condition{condition="Ready"})'
              instant: true

      - uid: node_exporter_down
        title: Node exporter is down
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: KeepLastState
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Node Exporter недоступен для части узлов (нет метрик node_*)"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'absent(up{job="kubernetes-nodes"})'
              instant: true
```

### Маршрутизация уведомлений (Notification Policy)

Дерево политик — единый ресурс (см. [Provisioning](../alerting/provisioning.md)). Маршрутизация по `severity` и `team`; группировка по `alertname`/`cluster`/`namespace`.

```yaml
# provisioning/alerting/policies/k8s-routing.yaml
apiVersion: 1
policies:
  - orgId: 1
    receiver: "default-slack"
    group_by: ["alertname", "cluster", "namespace"]
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: "critical-pager"
        object_matchers:
          - ["severity", "=", "critical"]
        continue: true
      - receiver: "team-slack"
        object_matchers:
          - ["team", "=~", "backend|frontend|platform"]
```

### Контакт-пойнты

Каналы доставки (Slack/Telegram/Webhook/PagerDuty) настраиваются в том же провиженинге — см. [Provisioning](../alerting/provisioning.md) (раздел Contact Points) и [интеграцию с Telegram](../alerting/telegram-integration.md). Минимальный пример Slack:

```yaml
# provisioning/alerting/contactpoints/k8s-receivers.yaml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: "critical-pager"
    receivers:
      - uid: cp_pager_01
        type: pagerduty
        settings:
          integrationKey: ${PAGERDUTY_KEY}
  - name: "team-slack"
    receivers:
      - uid: cp_slack_01
        type: slack
        settings:
          recipient: "#k8s-alerts"
          token: ${SLACK_TOKEN}
```

### Подавление зависимых алертов (Inhibition)

Если узел недоступен (`NodeNotReady`), десятки `PodNotReady`/`PodCrashLooping` на нём не несут новой информации. Inhibition скрывает зависимые алерты, пока активен корневой. В Grafana 13+ правила подавления настраиваются через App Platform API (beta, без UI) или UI Alerting → Inhibition rules; подробнее и пример `curl` — в [best practices](../alerting/best_practices.md) (раздел «Стратегии подавления»). Матчеры:

- **Source:** `alertname = NodeNotReady`, `severity = critical`.
- **Target:** `alertname =~ "PodNotReady|PodCrashLooping|PodImagePullBackOff"`.
- **Equal labels:** `cluster`, `node` (подавлять только на том же узле).

### Recording Rules (предвычисление)

Тяжёлые агрегации вычисляются заранее и переиспользуются алертами/дашбордами:

```yaml
# provisioning/alerting/rules/k8s-recording.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: "Kubernetes / Recording"
    folder: "Kubernetes"
    folderUid: "k8s-folder"
    interval: 1m
    rules:
      - uid: rec_pod_cpu_throttled
        title: "pod:container_cpu_throttled:rate5m"
        record:
          metric: "pod:container_cpu_throttled:rate5m"
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_seconds_total[5m]))'
              instant: true
```

### Проверка корректности (Validation)

- **Предпросмотр запроса:** в UI **Alerting → Alert rules → Preview** (или в Explore) убедитесь, что PromQL возвращает ожидаемые серии и условие даёт `true` для тестового случая.
- **Состояние правила:** **Alerting → Alert rules** показывает `Normal`/`Pending`/`Alerting` и время последней оценки; `execErrState: KeepLastState` при ошибке покажет `Error` без срабатывания.
- **State history:** **Alerting → History** видит все переходы, включая подавленные тишиной/mute, — полезно для «сработал, но не уведомил».
- **`promtool` (проверка выражений):** для отладки PromQL выражений вне Grafana:
  ```bash
  promtool check rules /tmp/k8s-rules.prometheus.yaml   # → "Checking 12 rules...  SUCCESS"
  ```
  > `promtool` принимает формат Prometheus rule_files (`groups:` + `rules:` с `alert:`), а не `apiVersion: 1` Grafana. Используйте его только для валидации самих PromQL-выражений, экспортированных в Prometheus-формат.
- **Проверка доставки:** во время `Alerting` проверьте канал (Slack/Telegram) и **Alerting → Silences/Notifications**; кнопка **Test** на контакт-пойнте проверяет шаблон.
- **События K8s (корреляция):** `kubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp'` — поиск `OOMKilled`, `FailedScheduling`, `Unhealthy`.
- **Hot Reload провиженинга:**
  ```bash
  curl -X POST "http://admin:admin@localhost:3000/api/admin/provisioning/alerting/reload"   # → 200 OK
  ```

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Алерт вечно `NoData` | KSM/Prometheus недоступен, неверный `datasourceUid`, пустой селектор | Проверьте `absent(kube_node_status_condition)`; сверьте UID источника; протестируйте PromQL в Explore |
| OOMKilled «ложно» срабатывает | `last_terminated_reason` хранит последнее завершение даже у восстановившегося пода | Используйте `increase(kube_pod_container_status_restarts_total[1h]) > 5` для окна, либо `for: 0m` как событие |
| CPU Throttling на idle-контейнере | Порог `> 1` слишком низок / лимит CPU жёсткий | Коррелируйте с `container_cpu_usage_seconds_total`; поднимите лимит или порог |
| `NodeNotReady` дёргается при drain | Плановый вывод узла | `for: 5m` + Mute Timing на окно обслуживания; используйте `kubectl cordon`/`drain` корректно |
| `CrashLoopBackOff` не срабатывает | Старая KSM (метрика только в 2.x) | Обновите kube-state-metrics до 2.x; проверьте наличие `kube_pod_container_status_waiting_reason` |
| Взрыв экземпляров (шум) | `group_by`/`labels` по высокой кардинальности (`pod`, `container`) | Группируйте по `alertname`/`cluster`/`namespace`; убирайте high-card метки из алерта |
| Алерты Control Plane пустые | Нет scrape-джобов etcd/apiserver | Настройте соответствующие ServiceMonitor/PodMonitor (есть в kube-prometheus-stack) |
| Правило не загрузилось из файла | Нет `apiVersion: 1` / файл вне `provisioning/alerting/rules` | Проверьте путь и корневой ключ `groups`; вызовите reload, см. логи `logger=provisioning` |
| Ложные страницы при блипе источника | `execErrState: Alerting` (по умолчанию) | Установите `execErrState: KeepLastState` для Prometheus-правил |

### Граничные случаи (Edge Cases)

- **`last_terminated_reason` — только последнее завершение:** если под восстановился, метка OOMKilled может оставаться до следующего перезапуска; комбинируйте с детектом рестартов.
- **CFS throttling только при `limits.cpu`:** без лимита `container_cpu_cfs_throttled_seconds_total` не генерируется — алерт по CPU не сработает «тихо».
- **Деление на 0:** `container_spec_memory_limit_bytes == 0` (нет лимита) даёт `NaN`; обязателен фильтр `> 0` в числителе/знаменателе.
- **Inodes ≠ Bytes:** исчерпание inodes и места — разные алерты; диск может быть полон по inodes при свободном месте.
- **Мультикластер:** без метки `cluster` алерты из разных кластеров неразличимы и смешиваются в маршрутизации.
- **HPA `AbleToScale=false` при деплое:** ожидаемо в первые минуты (нет метрик) — не поднимайте critical.
- **KSM v1 vs v2:** имена метрик ресурсов изменились в 2.x (`kube_pod_container_resource_requests` с лейблом `resource` вместо суффиксов `_cpu_cores`); убедитесь в версии.
- **Процент ошибок без объёма:** алерт `error% > 5%` страницает при 1 ошибке из 20 — добавляйте `and sum(...) > 10`.
- **Mute Timing ≠ отключение оценки:** алерт продолжает переходить в `Alerting`, просто не уведомляет; для подавления по меткам — Silence/Inhibition.

### Лучшие практики и очистка (Best Practices & Cleanup)

- Задавайте **статичные `uid`** всем правилам — провиженинг идемпотентен, сохраняется история при пересоздании.
- Группируйте уведомления по `['alertname', 'cluster', 'namespace']`; избегайте `pod`/`instance` в `group_by`.
- Используйте осмысленный `for` (2–15m) и `keep_firing_for` против flapping; сглаживайте окном `rate()`/`avg_over_time()`.
- Все критичные алерты — с `runbook_url`/`dashboard_url` и владельцем (`team`): алерт без владельца игнорируется.
- `execErrState: KeepLastState` для Prometheus-правил; `noDataState: Alerting` для критичных (ловит падение KSM).
- Используйте `$__rate_interval` вместо фиксированного окна — устойчивость к дрейфу scrape interval.
- Проектируйте **многомерные** правила (масштаб на кластер через метки), а не дубликаты «на сервис».
- Добавляйте `absent()` для мониторинга доступности самих экспортеров.
- Регулярно пересматривайте алерты: удаляйте те, что не ведут к действию (борьба с alert fatigue).
- **Очистка:** удаление правила из файла → перезагрузка провиженинга удаляет его из Grafana; перед массовыми изменениями экспортируйте текущее состояние (`GET /api/v1/provisioning/.../export`) как бэкап.

## Управление алертами как кодом (Alerting as Code)

Ручное редактирование алертов в UI не рекомендуется для Production-сред. Используйте следующие инструменты:
- **Terraform/OpenTofu:** Ресурсы `grafana_alert_rule` и `grafana_notification_policy`.
- **Grizzly:** Утилита от Grafana Labs для синхронизации YAML-описаний.
- **Prometheus Operator:** Использование Custom Resources `PrometheusRule` (если алерты вычисляются во внешнем Ruler/Alertmanager kube-prometheus-stack, а не Grafana-managed).
- **Provisioning:** Встроенный механизм Grafana для загрузки правил из YAML-файлов при старте (см. [Provisioning](../alerting/provisioning.md) — полный справочник по структуре, политикам, contact points и mute timings).

> Разделение ответственности: Grafana Provisioning управляет *внутренним* Alertmanager Grafana; `AlertmanagerConfig` (CRD Prometheus Operator) — внешним Alertmanager kube-prometheus-stack. Их связь — через контакт-пойнт типа `prometheus-alertmanager` или Data Source с опцией приёма Grafana-managed алертов (см. [Provisioning](../alerting/provisioning.md), раздел «Взаимодействие с Kubernetes и AlertmanagerConfig»).

## Дополнительная информация

**См. также:**

- [Провиженинг алертов в Grafana](../alerting/provisioning.md) — полная структура YAML (rules, policies, contact points, mute timings).
- [Лучшие практики алертинга](../alerting/best_practices.md) — методологии RED/USE, Burn Rate, снижение шума, Inhibition.
- [Основные концепции Grafana Alerting](../alerting/concepts.md) — архитектура конвейера выражений, состояния и маршрутизации.
```
