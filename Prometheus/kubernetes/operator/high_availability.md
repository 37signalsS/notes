# Prometheus Operator — Высокая доступность

## Определения

**High Availability (HA) в Prometheus Operator** — архитектурный подход, обеспечивающий непрерывность мониторинга и алертинга при отказе отдельных компонентов (подов, узлов или целых зон доступности). Реализуется через избыточность (репликацию), автоматическую дедупликацию и топологическое распределение нагрузки.

**Топологическое шардирование (Topology Sharding)** — механизм распределения целей сбора (targets) между группами Prometheus на основе их физического расположения (например, по зонам доступности), что минимизирует межзональный трафик и повышает устойчивость к сетевым задержкам.

---

## Основные концепции

### Высокая доступность Prometheus

Оператор управляет репликами Prometheus через `StatefulSet`. В режиме HA (минимум 2 реплики) каждый экземпляр работает независимо, собирая одни и те же метрики с одних и тех же целей.

**Ключевые принципы:**

- **Идентичность конфигурации:** Все реплики получают идентичный `prometheus.yml`.
- **Внешние метки (External Labels):** Каждая реплика автоматически получает уникальную метку (например, `prometheus_replica`), которая используется Alertmanager или Thanos для дедупликации данных "на лету".
- **TSDB Изоляция:** Реплики не синхронизируют данные между собой. Если одна реплика была недоступна, данные за этот период будут только во второй реплике.
- **Prometheus 3.0 (OTLP HA):** Новая версия поддерживает нативный прием OTLP-данных. В HA-режиме рекомендуется использовать балансировщик перед Prometheus для равномерного распределения входящих потоков OTLP/Remote Write.

### Высокая доступность Alertmanager

Alertmanager использует протокол **Gossip (Mesh)** для синхронизации состояний между узлами.

- **Кластеризация:** Оператор автоматически настраивает параметры `--cluster.peer` для всех реплик, используя сервис headless.
- **Кворум:** Рекомендуется запускать минимум 3 реплики. Это позволяет кластеру сохранять работоспособность и консистентность при выходе из строя одного узла.
- **Дедупликация уведомлений:** Alertmanager идентифицирует дубликаты алертов от HA-пары Prometheus и отправляет только одно уведомление конечному получателю.
- **Синхронизация Silences:** Информация о подавленных алертах (silences) и подтверждениях (inhibitions) мгновенно распространяется по Gossip-сети.

### Масштабирование и топологическое шардирование

Для крупных кластеров простого увеличения реплик недостаточно. Используется комбинация шардирования (горизонтальный рост) и репликации (HA).

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `replicas` | Количество копий для каждого шарда. | 2 для Production. |
| `shards` | Количество независимых групп (StatefulSet). | Зависит от объема метрик (обычно 1 шард на 1-2 млн серий). |
| `shardingStrategy` | Режим распределения целей. | `Topology` (v0.92+) для мультизональных кластеров. |

**PrometheusTopologySharding (Beta, v0.92+):**
В режиме `shardingStrategy.mode: Topology` Оператор автоматически настраивает Prometheus так, чтобы он собирал метрики только с подов, находящихся в той же зоне доступности (label `topology.kubernetes.io/zone`). Это радикально снижает затраты на трафик и повышает надежность системы.

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

---

## Инструментарий диагностики

### Проверка статуса Gossip-кластера Alertmanager
```bash
# Просмотр списка участников кластера
kubectl exec -it alertmanager-main-0 -n monitoring -- amtool cluster show
```

### Проверка распределения шардов по зонам
```bash
# Список подов с указанием зоны и ноды
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus \
  -L topology.kubernetes.io/zone -o wide
```

### Ключевые метрики HA-статуса

| Метрика | Назначение |
| :--- | :--- |
| `alertmanager_cluster_members` | Количество активных узлов в Gossip-сети. |
| `prometheus_operator_shard_reconciliation_errors_total` | Ошибки при создании шардов StatefulSet. |
| `prometheus_remote_storage_shards` | Количество шардов для Remote Write (HA-нагрузка на удаленное хранилище). |
| `prometheus_sd_kubernetes_cache_list_duration_seconds` | Задержка Service Discovery (влияет на скорость подхвата HA-целей). |

---

## Дополнительная информация

### Рекомендации по обеспечению надежности

1.  **Resources (QoS):** Всегда устанавливайте `requests` равными `limits` для памяти. Это переводит поды в класс `Guaranteed` и минимизирует риск OOMKill при перегрузках.
2.  **Shard Retention Policy:** В v0.92+ включена политика `PrometheusShardRetentionPolicy` (Beta), которая предотвращает потерю данных при динамическом изменении количества шардов.
3.  **Сетевые доступы:** Для Alertmanager Gossip требуется открытие порта `9094` по протоколам **TCP** и **UDP**. Убедитесь, что NetworkPolicy не блокируют этот трафик внутри пространства имен.
4.  **External Labels:** Никогда не используйте одинаковые `externalLabels` для разных HA-групп (шардов). Это приведет к некорректной дедупликации и потере данных в Thanos/Mimir.

### Связанные ресурсы

- **[Scaling Overview](../../scaling/overview.md)** — общие подходы к масштабированию вне контекста Оператора.
- **[Prometheus CRD](./crd/prometheus.md)** — полная спецификация полей для настройки HA и шардинга.
- **[Troubleshooting](./troubleshooting.md)** — диагностика проблем скрейпинга и вебхуков.
