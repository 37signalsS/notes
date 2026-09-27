# Prometheus Operator — Высокая доступность

## Определения

**High Availability (HA) в Prometheus Operator** — архитектурный подход, обеспечивающий непрерывность мониторинга и алертинга при отказе отдельных компонентов (подов, узлов или целых зон доступности). Реализуется через избыточность (репликацию), автоматическую дедупликацию и топологическое распределение нагрузки.

**EndpointSlice** — объект Kubernetes API (дискавери-ресурс), содержащий IP-адреса и порты эндпоинтов Service. С версии v0.80+ Prometheus Operator использует EndpointSlice вместо устаревшего Endpoints для Service Discovery, что снижает нагрузку на API-сервер и ускоряет обнаружение целей.

**Stale Marker** — специальный маркер (`stale NaN`), который Prometheus отправляет для всех метрик пода при его остановке или перезапуске. Используется downstream-системами (Grafana, Alertmanager) для определения исчезновения источника данных. В HA-средах stale-маркеры от одной реплики могут вызвать ложные срабатывания алертов, если не настроен `for:` или `ignoreStaleMarkers: true`.

**Churn Rate** — скорость появления и исчезновения временных рядов в TSDB. Высокий churn (например, из-за короткоживущих подов) приводит к фрагментации индекса и росту потребления RAM. В HA-контексте churn усиливается, так как каждая реплика независимо обрабатывает все целевые серии.

**Топологическое шардирование (Topology Sharding)** — механизм распределения целей сбора (targets) между группами Prometheus на основе их физического расположения (например, по зонам доступности), что минимизирует межзональный трафик и повышает устойчивость к сетевым задержкам.

**Gossip (Mesh Protocol)** — протокол распространения состояний в кластере Alertmanager без центрального координатора. Каждый узел периодически обменивается сообщениями с несколькими случайными пирами, обеспечивая eventual consistency для silences, inhibitions и дедупликации алертов.

**WAL (Write-Ahead Log)** — журнал предзаписи на диске, который `remote_write` использует для буферизации метрик перед отправкой по сети. Гарантирует at-least-once delivery: при разрыве связи данные не теряются и отправляются (backfill) после восстановления соединения.

**queueConfig** — блок конфигурации очереди отправки в `remote_write`. Определяет параллелизм (`max_shards`), размер буфера (`capacity`), частоту батчей и стратегию ретраев. В HA-средах с несколькими репликами тюнинг `queueConfig` критичен для предотвращения троттлинга LTS и потерь данных.

**at-least-once delivery** — гарантия доставки данных `remote_write`, при которой каждый семпл отправляется минимум один раз. Возможны дубликаты, которые LTS (Mimir/VictoriaMetrics) дедуплицирует по `time_ms` + `fingerprint`.

---

## Основные концепции

### Высокая доступность Prometheus

Оператор управляет репликами Prometheus через `StatefulSet`. В режиме HA (минимум 2 реплики) каждый экземпляр работает независимо, собирая одни и те же метрики с одних и тех же целей.

**Ключевые принципы:**

- **Идентичность конфигурации:** Все реплики получают идентичный `prometheus.yaml` через общий Secret. Config-reloader в каждом поде отслеживает изменения и инициирует `/-/reload` независимо.
- **Внешние метки (External Labels):** Каждая реплика автоматически получает уникальную метку (например, `prometheus_replica`), которая используется Alertmanager или Thanos для дедупликации данных "на лету". В v0.92+ Operator поддерживает произвольные внешние метки через `spec.externalLabels`.
- **TSDB Изоляция:** Реплики не синхронизируют данные между собой. Если одна реплика была недоступна, данные за этот период будут только во второй реплике. При восстановлении недоступной реплики она начнет с пустой TSDB, поэтому важно настроить удаленное хранилище (Thanos, Mimir) для долгосрочного хранения.
- **Prometheus 3.0 (OTLP HA):** Новая версия поддерживает нативный прием OTLP-данных. В HA-режиме рекомендуется использовать балансировщик перед Prometheus для равномерного распределения входящих потоков OTLP/Remote Write. Для Remote Write используйте `queueConfig.max_shards` для увеличения параллелизма при высокой нагрузке.
- **Remote Write HA и WAL:** Компонент `remote_write` читает данные из WAL на диске, а не из памяти. Это гарантирует сохранность данных при перезагрузке пода. При недоступности LTS Prometheus перестает продвигать указатель WAL, накапливая данные локально до лимита `retention`. После восстановления связи происходит backfill через параллельные шарды очереди.

### Высокая доступность Alertmanager

Alertmanager использует протокол **Gossip (Mesh)** для синхронизации состояний между узлами.

- **Кластеризация:** Оператор автоматически настраивает параметры `--cluster.peer` для всех реплик, используя сервис headless. В YAML это определяется полем `spec.replicas` (минимум 3 для кворума).
- **Кворум:** Рекомендуется запускать минимум 3 реплики. Это позволяет кластеру сохранять работоспособность и консистентность при выходе из строя одного узла. При 2 репликах потеря одного узла приводит к неконсистентности silences.
- **Дедупликация уведомлений:** Alertmanager идентифицирует дубликаты алертов от HA-пары Prometheus по `external_labels` (включая `prometheus_replica`) и отправляет только одно уведомление конечному получателю.
- **Синхронизация Silences:** Информация о подавленных алертах (silences) и подтверждениях (inhibitions) мгновенно распространяется по Gossip-сети. Для этого требуется открытый порт `9094` (TCP/UDP) между всеми репликами Alertmanager.
- **Gossip и NetworkPolicy:** В Kubernetes порт 9094 должен быть разрешен в NetworkPolicy между подами Alertmanager. Без этого кластер не сможет сформировать mesh и дедуплицировать уведомления.

### Масштабирование и топологическое шардирование

Для крупных кластеров простого увеличения реплик недостаточно. Используется комбинация шардирования (горизонтальный рост) и репликации (HA).

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `replicas` | Количество копий для каждого шарда. | 2 для Production. |
| `shards` | Количество независимых групп (StatefulSet). | Зависит от объема метрик (обычно 1 шард на 1-2 млн серий). |
| `shardingStrategy` | Режим распределения целей. | `Topology` (v0.92+) для мультизональных кластеров. |

**PrometheusTopologySharding (Beta, v0.92+):**
В режиме `shardingStrategy.mode: Topology` Оператор автоматически настраивает Prometheus так, чтобы он собирал метрики только с подов, находящихся в той же зоне доступности (label `topology.kubernetes.io/zone`). Это радикально снижает затраты на трафик и повышает надежность системы.

**TopologySpreadConstraints vs podAntiAffinity:**
`topologySpreadConstraints` предпочтительнее старого `podAntiAffinity`, так как позволяет более гибко распределять поды по зонам и хостам с контролем `maxSkew`. Для HA Alertmanager используйте `topologyKey: kubernetes.io/hostname` с `whenUnsatisfiable: ScheduleAnyway`, чтобы гарантировать распределение даже при нехватке ресурсов в зоне.

**Shards vs Replicas:**
- `shards` — горизонтальное масштабирование скрейпинга (каждый шард получает свой набор целей через консистентное хэширование).
- `replicas` — избыточность внутри шарда (каждая реплика скрейпит все цели своего шарда).
Итого: общее количество подов = `shards * replicas`. При 3 шардах и 2 репликах — 6 подов Prometheus.

---

## Практические сценарии

### Конфигурация HA Prometheus с Topology Sharding

Использование `topologySpreadConstraints` предпочтительнее старого `podAntiAffinity`, так как оно позволяет более гибко распределять поды по зонам и хостам.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  shards: 3
  shardingStrategy:
    mode: Topology
  version: v3.0.1
  # Распределение подов по зонам доступности
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "topology.kubernetes.io/zone"
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: prometheus
  podDisruptionBudget:
    minAvailable: 1
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
```

### Конфигурация HA Alertmanager (Gossip Mesh)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.27.0
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "kubernetes.io/hostname"
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: alertmanager
```

### Настройка Remote Write queueConfig для HA

При нескольких репликах Prometheus суммарный поток может достигать 200k+ samples/s. Без тюнинга `queueConfig` это приводит к троттлингу LTS и росту метрики `prometheus_remote_storage_dropped_samples_total`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  shards: 2
  version: v3.0.1
  remoteWrite:
    - url: "http://victoria-metrics.monitoring.svc:8428/api/v1/write"
      queueConfig:
        capacity: 25000          # Буфер на шард (по умолчанию 10000)
        max_shards: 150          # Параллельные потоки (по умолчанию 200)
        min_shards: 10           # Минимум потоков даже при низкой нагрузке
        max_samples_per_send: 5000 # Увеличить при больших батчах
        batch_send_deadline: 3s  # Меньше дедлайн = меньше лаг
        min_backoff: 30ms
        max_backoff: 10s         # Увеличить при нестабильной сети
```

**Валидация:** Мониторьте разницу `prometheus_remote_storage_highest_timestamp_in_seconds` - `prometheus_remote_storage_queue_highest_sent_timestamp_seconds`. Если она растет — увеличивайте `max_shards`.

### NetworkPolicy для Alertmanager Gossip

Без открытия порта `9094` между репликами Alertmanager кластер не сможет сформировать mesh. В мультизональных кластерах дополнительно разрешите трафик между зонами.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alertmanager-gossip
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - protocol: TCP
          port: 9094
        - protocol: UDP
          port: 9094
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - protocol: TCP
          port: 9094
        - protocol: UDP
          port: 9094
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
```

**Диагностика:**
```bash
# Проверка порта Gossip между репликами
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- netstat -tulpn | grep 9094

# Проверка логов кластеризации
kubectl logs -n monitoring alertmanager-main-0 -c alertmanager | grep -i gossip

# Проверка участников кластера
kubectl exec -it alertmanager-main-0 -n monitoring -- amtool cluster show
```

### Stale-маркеры и предотвращение ложных алертов при rolling update

При rolling update StatefulSet или перезапуске пода Prometheus отправляет `stale NaN` для всех его метрик. В HA-среде с 2 репликами это нормально, но может вызвать срабатывание алертов на `absent()`.

```yaml
# В PrometheusRule используйте ignoreStaleMarkers: true
groups:
  - name: ha_rules
    rules:
      - alert: InstanceDown
        expr: up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Инстанс недоступен"
          description: "{{ $labels.instance }} недоступен более 5 минут"
      # Для проверок, где stale-маркеры не должны вызывать алерт:
      - alert: JobMissing
        expr: absent(up{job="my-job"})
        for: 10m
        labels:
          severity: warning
        annotations:
          ignoreStaleMarkers: "true"
```

**Дополнительные меры:**
- Установите `for: 5m` (или больше) в алертах, чтобы пропустить кратковременные пропуски.
- При использовании Thanos глобальный `for:` должен учитывать задержку сбора между шардами.
- При канареечном обновлении используйте `updateStrategy.rollingUpdate.partition` для постепенного обновления подов.

### PVC и производительность диска в HA

TSDB Prometheus чувствителен к латентности диска. В HA-среде с 2+ репликами каждый под имеет отдельный PVC, но если StorageClass использует общий бэкенд (например, NFS), contention усиливается.

```yaml
spec:
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 100Gi
        # В StorageClass должны быть mountOptions:
        # noatime,nodiratime,logbs=4M
```

**Диагностика:**
```bash
# Проверка IOPS и латентности диска внутри пода
kubectl exec -n monitoring prometheus-main-0 -- iostat -x 1 5

# Проверка типа StorageClass
kubectl get storageclass

# Проверка WAL и head chunks
kubectl exec -n monitoring prometheus-main-0 -- du -sh /prometheus/wal /prometheus/chunks_head
```

**Типичные проблемы:**
- HDD вместо SSD: latency > 20ms приводит к задержкам скрейпинга и compaction.
- Разделение WAL и Blocks на одном физическом носителе без QoS: запись WAL может "съесть" IOPS, доступные для head compaction.
- Отсутствие `allowVolumeExpansion: true`: при росте TSDB PVC не расширяется автоматически.

### PodDisruptionBudget и планируемые действия

PDB защищает HA-группу от одновременного удаления подов при плановых действиях (kubectl drain, обновление ноды).

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: prometheus-main-pdb
  namespace: monitoring
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus
      app.kubernetes.io/instance: main
```

**Для Alertmanager** используйте `minAvailable: 2` при 3 репликах, чтобы сохранить кворум при drain одной ноды.

### CRD mismatch при обновлении Operator

При обновлении Operator старые CRD могут быть несовместимы с новым контейнером. Это приводит к ошибкам `unknown field` или игнорированию полей.

```bash
# Проверка версий CRD
kubectl get crd | grep monitoring.coreos.com
kubectl describe crd prometheuses.monitoring.coreos.com | grep -A3 "Versions:"

# Проверка версии Operator
kubectl get deployment -n monitoring prometheus-operator -o jsonpath='{.spec.template.spec.containers[0].image}'
```

**Решение:**
1. Обновите CRD до версии, соответствующей Operator: `kubectl apply -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.92.0/stripped-down-crds.yaml`.
2. Никогда не используйте `kubectl apply` с CRD старой версии после обновления Operator.
3. Проверяйте events: `kubectl get events -n monitoring | grep -i "failed"`.

### Scrape timeout и target_sync_length_seconds

Цель в `Down` с `Context Deadline Exceeded`, хотя приложение отвечает на `curl`, обычно указывает на несоответствие `scrape_timeout` и `scrape_interval` или слишком большой объем метрик.

```yaml
# В ServiceMonitor или PodMonitor:
spec:
  endpoints:
    - port: http-metrics
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s   # Должен быть меньше interval
      sampleLimit: 10000   # Ограничение семплов на скрейп
      metricRelabelings:
        - sourceLabels: [__name__]
          regex: 'go_.*'
          action: drop
```

**Диагностика:**
```bash
# Проверка времени скрейпинга конкретной цели
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets \
  | jq '.data.activeTargets[] | select(.health=="down") | {job, instance, error, lastScrape}'

# Проверка метрики задержки синхронизации
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep prometheus_target_sync_length_seconds
```

**Решение:**
1. Увеличьте `scrape_timeout` (должен быть меньше `scrape_interval`).
2. Для больших объемов метрик увеличьте `sample_limit` или используйте `metric_relabel_configs` для удаления не нужных рядов.
3. Проверьте, нет ли блокирующих I/O операций в приложении во время скрейпинга.

---

## Инструментарий диагностики

### Проверка статуса Gossip-кластера Alertmanager
```bash
# Просмотр списка участников кластера
kubectl exec -it alertmanager-main-0 -n monitoring -- amtool cluster show

# Проверка порта Gossip между репликами
kubectl exec -n monitoring alertmanager-main-0 -c alertmanager -- netstat -tulpn | grep 9094

# Проверка логов кластеризации
kubectl logs -n monitoring alertmanager-main-0 -c alertmanager | grep -i gossip
```

### Проверка распределения шардов по зонам
```bash
# Список подов с указанием зоны и ноды
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus \
  -L topology.kubernetes.io/zone -o wide

# Проверка TopologySpreadConstraints
kubectl get statefulset prometheus-main -n monitoring -o yaml | grep -A20 topologySpreadConstraints
```

### Проверка Remote Write очереди
```bash
# Активные шарды и лаг отправки
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep -E "prometheus_remote_storage_shards|prometheus_remote_storage_highest_timestamp|prometheus_remote_storage_queue_highest_sent_timestamp"

# Просроченные семплы и дропы
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep -E "prometheus_remote_storage_dropped_samples_total|prometheus_remote_storage_samples_pending"
```

### Проверка WAL и TSDB
```bash
# Размер WAL и head chunks
kubectl exec -n monitoring prometheus-main-0 -- du -sh /prometheus/wal /prometheus/chunks_head

# Проверка IOPS диска
kubectl exec -n monitoring prometheus-main-0 -- iostat -x 1 5

# Проверка на коррупцию WAL
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep prometheus_tsdb_wal_corruptions_total
```

### Проверка Service Discovery и целей
```bash
# Статус всех целей
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets \
  | jq '.data.activeTargets[] | {job, instance, health, lastError}'

# Время обработки Service Discovery
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep -E "prometheus_target_sync_length_seconds|prometheus_sd_kubernetes_cache_list_duration_seconds"
```

### Ключевые метрики HA-статуса

| Метрика | Назначение |
| :--- | :--- |
| `alertmanager_cluster_members` | Количество активных узлов в Gossip-сети. |
| `prometheus_operator_shard_reconciliation_errors_total` | Ошибки при создании шардов StatefulSet. |
| `prometheus_remote_storage_shards` | Количество шардов для Remote Write (HA-нагрузка на удаленное хранилище). |
| `prometheus_sd_kubernetes_cache_list_duration_seconds` | Задержка Service Discovery (влияет на скорость подхвата HA-целей). |
| `prometheus_tsdb_wal_corruptions_total` | Коррупции WAL (требуется очистка `/wal`). |
| `prometheus_tsdb_head_series` | Количество активных серий в Head Block (мониторинг кардинальности). |
| `prometheus_remote_storage_dropped_samples_total` | Потерянные семплы при перегрузке Remote Write. |
| `prometheus_engine_queries_active` | Количество активных PromQL-запросов (троттлинг). |
| `prometheus_notifications_alertmanagers_discovered` | Количество обнаруженных Alertmanager (проверка кластеризации). |
| `prometheus_config_last_reload_success_timestamp_seconds` | Время последней успешной перезагрузки конфигурации. |

### Команды для быстрой диагностики состояния

```bash
# 1. Статус pods Operator, Prometheus и Alertmanager
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager

# 2. Проверка событий (Events) на предмет ошибок
kubectl get events -n monitoring --sort-by='.lastTimestamp' | tail -20

# 3. Проверка статуса StatefulSet
kubectl rollout status statefulset/prometheus-main -n monitoring --timeout=5m
kubectl rollout status statefulset/alertmanager-main -n monitoring --timeout=5m

# 4. Проверка сгенерированного конфига
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c

# 5. Проверка размера WAL и блоков TSDB
kubectl exec -n monitoring prometheus-main-0 -- du -sh /prometheus/wal /prometheus/chunks_head

# 6. Проверка метрик Operator
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep -E "prometheus_operator_reconcile|prometheus_config_last_reload"

# 7. Проверка Service Discovery
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/api/v1/targets \
  | jq '.data.activeTargets[] | {job, instance, health, lastError}'
```

---

## Дополнительная информация

### Рекомендации по обеспечению надежности

1.  **Resources (QoS Guaranteed):** Всегда устанавливайте `requests` равными `limits` для памяти и CPU. Это переводит поды в класс `Guaranteed` и минимизизирует риск OOMKill и троттлинга при перегрузках.
2.  **Go Garbage Collector:** Для крупных инстансов (>1M серий) настройте `goGC: 50` (по умолчанию 100). Меньшее значение увеличивает частоту GC, но снижает пиковое потребление RAM. Мониторьте `prometheus_go_goroutines` и `prometheus_engine_queries_active`.
3.  **Shard Retention Policy:** В v0.92+ включена политика `PrometheusShardRetentionPolicy` (Beta), которая предотвращает потерю данных при динамическом изменении количества шардов. При увеличении `spec.shards` Policy гарантирует, что старые шарды не удалят данные преждевременно.
4.  **WAL и диски:** Разделите WAL и TSDB blocks на разные PVC или тома, если StorageClass поддерживает это. WAL интенсивнее пишет, и на общем носителе это может создавать contention с compaction.
5.  **Сетевые доступы:** Для Alertmanager Gossip требуется открытие порта `9094` по протоколам **TCP** и **UDP**. Убедитесь, что NetworkPolicy не блокируют этот трафик внутри пространства имен. Для Remote Write убедитесь, что Egress разрешен на порт 443 (или порт LTS) и DNS разрешает имена хранилищ.
6.  **External Labels:** Никогда не используйте одинаковые `externalLabels` для разных HA-групп (шардов). Это приведет к некорректной дедупликации и потере данных в Thanos/Mimir. Каждая HA-пара должна иметь уникальный идентификатор в `externalLabels`.
7.  **Retention Size:** Используйте `retentionSize` вместо `retention` (время) при использовании быстрых SSD. Это защищает от переполнения диска: `spec.retentionSize: 100Gi` остановит прием новых данных при достижении лимита, но оставит место для WAL.
8.  **PodDisruptionBudget:** Для Prometheus HA используйте `minAvailable: 1` (при 2 репликах) или `maxUnavailable: 1` (при >2 репликах). Для Alertmanager — `minAvailable: 2` при 3 репликах для сохранения кворума.
9.  **TopologySpreadConstraints:** При использовании `shardingStrategy.mode: Topology` убедитесь, что `topologySpreadConstraints` настроены на ключ `topology.kubernetes.io/zone` и `whenUnsatisfiable: DoNotSchedule` для Prometheus. Для Alertmanager допускается `ScheduleAnyway`, чтобы избежать неразмещения при нехватке ресурсов.
10. **Мониторинг HA-здоровья:** Создайте алерты на `alertmanager_cluster_members < 3` (для 3 реплик), `prometheus_remote_storage_dropped_samples_total > 0` и `prometheus_operator_shard_reconciliation_errors_total > 0`.

### Связанные ресурсы

- **[Prometheus CRD](./crd/prometheus.md)** — полная спецификация полей для настройки HA и шардинга.
- **[Troubleshooting](./troubleshooting.md)** — диагностика проблем скрейпинга и вебхуков.
- **[Расчет ресурсов](./resource_sizing.md)** — формулы RAM/CPU/Disk, sizing для шардов и реплик.
- **[Long-term Storage](./long_term_storage_integration.md)** — интеграция Thanos Sidecar через `spec.thanos`, remoteWrite в VictoriaMetrics/Mimir.
- **[PodDisruptionBudget](./pod_disruption_budget.md)** — защита HA-групп при drain и rolling update.
- **[Self-Monitoring](./self_monitoring.md)** — алерты на health HA-компонентов.
