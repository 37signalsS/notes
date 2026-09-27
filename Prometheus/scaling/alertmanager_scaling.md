# Масштабирование Alertmanager

При масштабировании Prometheus (шардинг, федерация, multiple инстансы) количество генерируемых алертов растет пропорционально. Alertmanager должен обрабатывать десятки тысяч алертов в секунду, обеспечивать доставку в несколько каналов и не терять данные при сбоях. Данный файл описывает архитектурные решения и практические настройки для масштабирования Alertmanager.

> **См. также:** [Alertmanager — управление оповещениями](../alertmanager.md), [Правила алертинга](../rules.md), [Масштабирование Prometheus: обзор](./overview.md).

## Определения

| Термин | Описание |
|:---|:---|
| **Gossip-протокол** | Протокол децентрализованного обмена состоянием между узлами кластера Alertmanager. Каждый узел периодически отправляет heartbeat и обменивается информацией о состоянии алертов и силенсов. |
| **Mesh (кластер)** | Группа из 3+ инстансов Alertmanager, объединенных через gossip-протокол. Обеспечивает отказоустойчивость: при падении одного узла остальные продолжают обработку. |
| **Inhibition Rule** | Правило подавления алертов. Если активен критический алерт (например, `InstanceDown`), более мягкие зависимые алерты (высокий CPU) подавляются, чтобы не засорять каналы уведомлений. |
| **Silence** | Временное подавление алертов по маске (regex по меткам). Используется для planned maintenance, избежания спама при известных проблемах. |
| **Mute Time Interval** | Период, в течение которого определенные алерты не отправляются (например, ночью для некритичных оповещений). В отличие от Silence, работает по расписанию. |
| **Alert Storm** | Ситуация, когда одновременно генерируется аномально большое количество алертов (обычно при массовом сбое инфраструктуры). Требует специальных механизмов защиты. |

## Базовые концепции

### Когда требуется масштабирование Alertmanager

| Показатель | Зона комфорта | Предупреждение | Критический режим | Действие |
|:---|:---|:---|:---|:---|
| **Активные алерты** | < 1 000 | 1 000–10 000 | > 10 000 | Включить кластер, оптимизировать правила |
| **Скорость поступления алертов** | < 100/сек | 100–500/сек | > 500/сек | Добавить узлы кластера, увеличить группировку |
| **Количество Receiver** | < 5 | 5–15 | > 15 | Разделить по Alertmanager-кластерам (по team/service) |
| **Количество правил inhibition** | < 10 | 10–50 | > 50 | Пересмотреть иерархию алертов |
| **Задержка доставки** | < 1с | 1–10с | > 10с | Увеличить кластер, проверить network latency |

### Кластеризация Alertmanager (Gossip Protocol)

Кластер Alertmanager строится на протоколе gossip (аналогичном Consul/Raft). Каждый узел знает о состоянии всех остальных и может independently доставлять алерты.

**Принцип работы:**
1. **Heartbeat:** Каждый узел каждые 0.5сек отправляет heartbeat всем узлам кластера.
2. **State dissemination:** При изменении состояния (новый алерт, silence, resolved) узел рассылает обновление через gossip.
3. **Convergence:** Все узлы приходят к согласованному состоянию (eventual consistency). Время convergence —通常 1–3 секунды.
4. **Failure detection:** Если узел не отвечает > 10 секунд, он объявляется как failed, и его алерты берут на себя оставшиеся узлы.

**Кворум кластера:**
- **Минимум 3 узла** для отказоустойчивости (переносит падение 1 узла)
- **Рекомендуется 3–5 узлов** для production
- **Нечетное число узлов** — рекомендация для избежания split-brain (хотя gossip-протокол не требует кворума как Raft)

**Пример запуска кластера (3 узла):**
```bash
# Узел 1
alertmanager \
  --cluster.listen-address=0.0.0.0:9094 \
  --cluster.peer=alertmanager-2:9094 \
  --cluster.peer=alertmanager-3:9094 \
  --config.file=/etc/alertmanager/alertmanager.yml

# Узел 2
alertmanager \
  --cluster.listen-address=0.0.0.0:9094 \
  --cluster.peer=alertmanager-1:9094 \
  --cluster.peer=alertmanager-3:9094 \
  --config.file=/etc/alertmanager/alertmanager.yml

# Узел 3
alertmanager \
  --cluster.listen-address=0.0.0.0:9094 \
  --cluster.peer=alertmanager-1:9094 \
  --cluster.peer=alertmanager-2:9094 \
  --config.file=/etc/alertmanager/alertmanager.yml
```

### Маршрутизация алертов при масштабировании

При большом количестве алертов критически важно правильно настроить маршрутизацию, чтобы не перегружать один канал уведомлений.

**Иерархия маршрутизации:**
```yaml
route:
  receiver: 'default'
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    # Критичные алерты — немедленно в PagerDuty
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      group_wait: 10s
      repeat_interval: 1h

    # Алерты по командам
    - match_re:
        team: '(backend|frontend|infra)'
      receiver: 'team-${1}'
      group_by: ['alertname', 'service']

    # Тихие алерты — в Slack
    - match:
        severity: warning
      receiver: 'slack-warning'
      group_interval: 15m
      repeat_interval: 12h
```

**Матрица маршрутизации по масштабу:**

| Сценарий | group_wait | group_interval | repeat_interval | Receiver |
|:---|:---|:---|:---|:---|
| **Critical (InstanceDown)** | 10s | 5m | 1h | PagerDuty |
| **Warning (HighCPU)** | 30s | 15m | 12h | Slack |
| **Info (Deployment)** | 60s | 30m | 24h | Email |
| **Maintenance window** | — | — | — | Silence |

### Inhibition Rules при масштабировании

Inhibition предотвращает «шторм» зависимых алертов при массовом сбое. Если упала вся нода, нет смысла получать алерты на каждый под на этой ноде.

```yaml
inhibit_rules:
  # Если InstanceDown — подавить все алерты по этому инстансу
  - source_match:
      alertname: 'InstanceDown'
    target_match_re:
      alertname: '.+'
    equal: ['instance']

  # Если PodCrashLooping — подавить OOMKilled для того же пода
  - source_match:
      alertname: 'PodCrashLooping'
    target_match:
      alertname: 'PodOOMKilled'
    equal: ['namespace', 'pod']

  # Если NodeDown — подавить все node-метрики
  - source_match:
      alertname: 'NodeDown'
    target_match_re:
      alertname: 'Node.+'
    equal: ['instance']
```

### Защита от Alert Storm

При массовых сбоях (сетевой partition, падение Kubernetes API, обновление CNI) может генерироваться десятки тысяч алертов одновременно. Без защиты это приводит к:
- Переполнению очереди Alertmanager
- Потере критичных алертов в потоке
- Перегрузке каналов доставки (Slack rate limit, PagerDuty throttle)

**Механизмы защиты:**

1. **`group_by` с агрессивной группировкой:**
   ```yaml
   group_by: ['alertname', 'service']  # Без instance/pod — алерты сгрегируются
   ```

2. **`group_wait` для буферизации:**
   ```yaml
   group_wait: 30s  # Накапливает алерты за 30сек перед отправкой
   ```

3. **Лимит `alert_limit` в правилах Prometheus:**
   ```yaml
   groups:
     - name: production
       alert_limit: 100  # Не более 100 активных алертов от группы
   ```

4. **`max_alerts` в alerting rules (v2.47+):**
   ```yaml
   - alert: HighErrorRate
     expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
     max_alerts: 50  # Ограничение количества сгенерированных алертов
   ```

5. **Силлентсы при planned maintenance:**
   ```bash
   amtool silence add alertname=~'.*' cluster="prod-dc1" \
     --comment="Плановое обновление CNI" --duration=2h
   ```

## Практические сценарии

### Сценарий 1: HA-кластер Alertmanager (Kubernetes)

**Развёртывание через kube-prometheus-stack:**
```yaml
# values.yaml
alertmanager:
  alertmanagerSpec:
    replicas: 3
    storage:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi
    # Географическое распределение (если есть multiple zones)
    # podAntiAffinity:
    #   preferredDuringSchedulingIgnoredDuringExecution:
    #     - weight: 100
    #       podAffinityTerm:
    #         labelSelector:
    #           matchLabels:
    #             app.kubernetes.io/name: alertmanager
    #         topologyKey: topology.kubernetes.io/zone
```

**Проверка кластера:**
```bash
# Статус кластера
kubectl exec -n monitoring alertmanager-monitoring-0 -- \
  amtool cluster peers

# Ожидаемый вывод:
#  alertmanager-0 alertmanager-1 alertmanager-2
```

### Сценарий 2: Мульти-тенантная маршрутизация

Для больших организаций с несколькими командами — разделение алертов по Alertmanager-кластерам или receiver-ам:

```yaml
route:
  receiver: 'global-default'
  group_by: ['alertname', 'cluster']
  group_wait: 30s

  routes:
    # Команда Backend
    - match:
        team: backend
      receiver: 'slack-backend'
      group_by: ['alertname', 'service']
      routes:
        - match:
            severity: critical
          receiver: 'pagerduty-backend'

    # Команда Infrastructure
    - match:
        team: infra
      receiver: 'slack-infra'
      group_by: ['alertname', 'node']
      routes:
        - match:
            severity: critical
          receiver: 'pagerduty-infra'

    # Команда Database
    - match:
        team: db
      receiver: 'slack-db'
      group_by: ['alertname', 'database']
```

### Сценарий 3: Capacity Planning для Alertmanager

**Расчет ресурсов:**

| Параметр | Формула | Пример (10 000 алертов/день) |
|:---|:---|:---|
| **CPU** | 0.1 ядро на 1 000 активных алертов | 1 ядро |
| **RAM** | 512 MiB + 1 MiB на 100 алертов | 612 MiB |
| **Disk** | 100 MiB + retention × скорость записи | 100 MiB + 50 MiB = 150 MiB |
| **Network** | 1 KB на алерт × количество receiver | ~10 KB/сек |

**Мониторинг Alertmanager:**
```promql
# Процент failed доставки (критичная метрика)
rate(alertmanager_notifications_failed_total[5m])
  / rate(alertmanager_notifications_total[5m]) * 100

# Задержка доставки (p99)
histogram_quantile(0.99,
  sum(rate(alertmanager_notification_latency_seconds_bucket[5m])) by (le)
)

# Количество узлов кластера
alertmanager_cluster_members

# Количество активных алертов
alertmanager_alerts

# Количество подавленных алертов (silences)
alertmanager_silenced_alerts
```

### Сценарий 4: Интеграция с масштабированной архитектурой Prometheus

Когда Prometheus шардирован (несколько инстансов), все они отправляют алерты в один Alertmanager-кластер:

```yaml
# prometheus.yml на КАЖДОМ шарде
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager-1:9093
            - alertmanager-2:9093
            - alertmanager-3:9093
      timeout: 10s
```

**Важно:** При шардированном Prometheus алерты с одинаковыми `alertname` и `labels` могут приходить с разных шардов. Alertmanager выполняет **deduplication** по комбинации `alertname` + `labels` — дубликаты объединяются автоматически.

### Сценарий 5: Mute Time Intervals (тихие часы)

```yaml
# alertmanager.yml
mutetime_files:
  - /etc/alertmanager/mutetimes/workhours.yml

# mutetimes/workhours.yml
- times:
    - start_time: '22:00'
      end_time: '08:00'
      location: 'Europe/Moscow'
  target_match:
    severity: warning
```

## Диагностика и решение проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Alertmanager не принимает алерты** | Prometheus не может достучаться до Alertmanager | Проверить `up{job="alertmanager"}`, сетевую доступность порта 9093 |
| **Дубликаты алертов в уведомлениях** | Несколько Alertmanager без кластеризации | Объединить в кластер через `--cluster.peer` |
| **Aлерты теряются при рестарте** | Нет persistent storage для silences/state | Добавить PVC для `/var/lib/alertmanager` |
| **Доставка > 10 секунд** | Перегрузка кластера или медленный receiver | Увеличить узлы кластера, проверить `alertmanager_notification_latency_seconds` |
| **Slack rate limit (429)** | Слишком частые уведомления | Увеличить `group_wait` и `group_interval`, добавить `repeat_interval` |
| **Split-brain (дубликаты)** | Кластер не сходится к consensus | Проверить gossip: `amtool cluster peers`, увеличить `--cluster.probe-interval` |
| **High memory usage** | Много активных silences или алертов | Очистить устаревшие silences: `amtool silence expire` |

## Граничные случаи и ограничения

### Кластер Alertmanager
- **Gossip — eventually consistent:** При partition сети возможны временные расхождения в state. Алерты могут быть доставлены дважды (duplicate delivery). Receiver должны поддерживать идемпотентность.
- **Максимум узлов:** Практический лимит — 9 узлов. При большем количестве gossip-трафик становится значительным.
- **Нечетное число:** Рекомендуется для стабильности, но не требуется (gossip не использует кворум).

### Inhibition Rules
- **Цепочки inhibition:** A подавляет B, B подавляет C. Если A активен — C тоже подавляется. Убедитесь, что критичные алерты не попадают в цепочки подавления.
- **Equal label:** Указывайте `equal: ['instance']` для изоляции подавления по конкретным инстансам, а не глобально.

### Silence vs Mute Time
- **Silence — ручное подавление:** Используйте для planned maintenance с конкретным `--duration`.
- **Mute Time — автоматическое по расписанию:** Используйте для регулярных тихих окон (ночь, выходные).
- **Silence переживает рестарт** (если есть persistence), Mute Time — нет (определяется в конфиге).

## Дополнительная информация

### Лучшие практики (2025–2026)

1. **Кластер из 3 узлов** — минимум для production. Один узел может упасть без потери данных.
2. **Persistent silences** — без persistent storage все silences теряются при рестарте.
3. **`group_by` по alertname + cluster/service** — оптимальная группировка для масштаба.
4. **Inhibition для critical алертов** — подавляйте зависимые алерты при массовых сбоях.
5. **Мета-мониторинг:** Алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0` — «тихий» сбой доставки остаётся незамеченным без мониторинга самого алертинга.
6. **Mute Time для nightly maintenance** — автоматическое подавление некритичных алертов в ночное время.
7. **Разделение по командам** — используйте `routes` с `match` по `team` для изоляции алертов разных команд.

### См. также
*   [Alertmanager — управление оповещениями](../alertmanager.md) — полная документация по компоненту
*   [Правила алертинга](../rules.md) — alerting rules и recording rules
*   [Масштабирование Prometheus: обзор](./overview.md) — общие стратегии масштабирования
*   [Федерация](./federation.md) — иерархическая агрегация и ее влияние на алертинг
