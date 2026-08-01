# Prometheus Operator — Высокая доступность

## Определения

**High Availability (HA) в Prometheus Operator** — обеспечение отказоустойчивости стека мониторинга через запуск нескольких реплик Prometheus и Alertmanager с автоматической синхронизацией состояния и распределением по узлам кластера.

> **См. также:** [Scaling Overview](../../scaling/overview.md) — базовая HA без Operator, [Alertmanager HA](../../alertmanager.md#высокая-доступность-ha) — gossip-протокол.

## Основные концепции

### HA Prometheus

Prometheus Operator управляет репликами Prometheus через StatefulSet. Каждая реплика собирает **одни и те же метрики** независимо.

**Ключевые принципы:**

- **Минимум 2 реплики** для отказоустойчивости.
- **Одинаковая конфигурация** на всех репликах (управляется Operator).
- **Внешние метки (External Labels):** Каждая реплика получает уникальную метку (например, `prometheus_replica`), что критично для дедупликации в Thanos или Alertmanager.
- **StatefulSet** сохраняет идентичность pod'ов и привязку к хранилищу при перезапусках.
- **Локальная TSDB:** Каждый экземпляр хранит собственные данные; синхронизация данных между репликами средствами Prometheus не предусмотрена.

### HA Alertmanager

Alertmanager использует **gossip-протокол** (порт 9094) для кластеризации:

- **Минимум 3 реплики** для обеспечения кворума и корректной работы в случае сбоя одного узла.
- **Дедупликация алертов:** При получении идентичных оповещений от нескольких Prometheus, Alertmanager отправляет уведомление только один раз.
- **Синхронизация состояний:** Silences и информация о подавлениях (inhibitions) синхронизируются между репликами через Mesh-сеть.
- **Автоматизация:** Prometheus Operator автоматически настраивает `--cluster.peer` для всех pod'ов, используя DNS-имена StatefulSet.

### Шардирование (Sharding)

Для распределения нагрузки (CPU/Memory/Scrape targets) цели скрейпинга разделяются между несколькими StatefulSet:

| Параметр | Описание |
|---|---|
| `replicas` | Количество реплик внутри каждого шарда (для HA) |
| `shards` | Количество независимых StatefulSet (для горизонтального масштабирования) |

**Механизм:** Prometheus Operator использует хэширование целей. С версии Operator v0.93.0 рекомендуется использовать `PrometheusTopologySharding` (Beta), который учитывает топологию кластера при распределении шардов.

### Отказоустойчивость на уровне узлов (Anti-Affinity)

Для реальной высокой доступности реплики одного компонента должны находиться на **разных физических узлах**. Это достигается через `podAntiAffinity` в спецификации ресурсов.

## Практические сценарии

### Конфигурация HA Prometheus с Anti-Affinity и PDB

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.13.2
  serviceAccountName: prometheus
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app.kubernetes.io/name: prometheus
      topologyKey: "kubernetes.io/hostname"
  # Поддержка Pod Disruption Budget через Operator
  podDisruptionBudget:
    minAvailable: 1
  externalLabels:
    cluster: production
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

### Конфигурация HA Alertmanager

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.33.1
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: alertmanager
        topologyKey: "kubernetes.io/hostname"
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### Проверка статуса высокой доступности

```bash
# Проверка реплик Prometheus
kubectl get prometheus -n monitoring
# → NAME   VERSION   REPLICAS   READY   RECONCILED   AVAILABLE
# → main   v3.13.2   2          2       True         True

# Проверка распределения по узлам
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o wide
# → prometheus-main-0   1/1   Running   node-1
# → prometheus-main-1   1/1   Running   node-2

# Проверка кластера Alertmanager через логи (поиск gossip-сообщений)
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager | grep "memberlist: Adding member"
# → level=info ts=... component=cluster msg="memberlist: Adding member alertmanager-main-1..."

# Проверка gossip-соединений API
kubectl exec -it alertmanager-main-0 -n monitoring -- \
  wget -qO- http://localhost:9093/api/v2/status | jq '.cluster'
# → { "peers": [ { "name": "...", "address": "..." }, ... ], "status": "ready" }
```

### Интеграция Thanos Sidecar для глобального HA

Thanos позволяет объединять данные из разных HA-реплик, выполняя дедупликацию на лету.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  thanos:
    version: v0.42.0
    image: quay.io/thanos/thanos:v0.42.0
  # Внешняя метка обязательна для дедупликации в Thanos Query
  externalLabels:
    prometheus_group: main-ha
```

## Дополнительная информация

### Метрики мониторинга HA-стека

| Метрика | Описание | Критическое значение |
|---|---|---|
| `prometheus_operator_spec_replicas` | Ожидаемое количество реплик | `!= actual_replicas` |
| `alertmanager_cluster_members` | Общее количество узлов в gossip-кластере | `< 3` |
| `alertmanager_cluster_health_score` | Индикатор здоровья кластера (0 — ок) | `> 0` |
| `up{job="prometheus"}` | Доступность конкретного инстанса | `0` (потеря реплики) |
| `prometheus_operator_reconcile_errors_total` | Ошибки конфигурации оператором | `rate > 0` |

### Рекомендации по обеспечению надежности

1.  **Pod Disruption Budget (PDB):** Всегда настраивайте PDB для Prometheus и Alertmanager, чтобы предотвратить одновременный вывод всех реплик из строя при обслуживании узлов.
2.  **Resources:** Устанавливайте `requests` равными `limits` для памяти (Guaranteed QoS), чтобы избежать OOMKill при всплесках нагрузки.
3.  **Storage:** Используйте `VolumeClaimTemplate` для обеспечения независимых дисков каждой реплике. Не используйте общие тома (RWX).
4.  **Сетевые политики:** Убедитесь, что порт `9094` (TCP/UDP) открыт между подами Alertmanager для работы gossip.

### Сравнение подходов к масштабированию

| Ограничение | Решение через HA | Решение через Thanos/Mimir |
|---|---|---|
| **Отказ узла** | Да (через реплики) | Да |
| **Дублирование данных** | Нет (каждая TSDB уникальна) | Да (дедупликация при чтении) |
| **Глобальный вид** | Нет | Да (Querier объединяет данные) |
| **Хранение годами** | Нет (локальный диск ограничен) | Да (S3/GCS/Azure Storage) |

> **См. также:** [Prometheus CRD](./crd/prometheus.md), [Alertmanager CRD](./crd/alertmanager.md), [Security](./Security/index.md), [Troubleshooting](./troubleshooting.md).
