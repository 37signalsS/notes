# Высокая доступность (High Availability) Prometheus

> **См. также:** [Масштабирование Prometheus](../scaling/overview.md), [Alertmanager](../alertmanager.md), [Remote Read/Write](../scaling/remote_read_write.md), [Thanos](../scaling/thanos_overview.md), [Федерация](../scaling/federation.md).

## Определения

* **High Availability (HA)** — отказоустойчивость, достигаемая дублированием компонентов. Два или более экземпляра Prometheus независимо опрашивают одни и те же цели, гарантируя непрерывность сбора метрик при падении одного из них.
* **Active-Active** — модель HA, где все экземпляры работают одновременно и обрабатывают нагрузку. Применяется к Prometheus: несколько серверов собирают одни метрики параллельно.
* **Дедупликация** — механизм удаления дублей при запросе данных из нескольких HA-экземпляров. Выполняется на уровне Alertmanager (для алертов) или внешнего слоя (Thanos Query, VictoriaMetrics) для метрик.
* **External Labels** — метки, добавляемые к данным экземпляра (например, `prometheus_replica`), позволяющие различать идентичные метрики из разных источников и выполнять дедупликацию.

## Основные концепции

### Паттерны HA для Prometheus

| Паттерн | Описание | Когда использовать |
|:---|:---|:---|
| **Два экземпляра + LB** | Два сервера за балансировщиком (HAProxy/Nginx) | Простые среды, fewer 500K серий |
| **Agent Mode + LTS** | Несколько Agent-экземпляров, Remote Write в централизованное хранилище | Мультикластеры, edge-кластеры |
| **Thanos/VictoriaMetrics** | HA-пары + внешний слой дедупликации и хранения | Крупные продуктивные среды |

### Ключевые принципы

1. **Идентичная конфигурация:** Все экземпляры получают одинаковый `prometheus.yml`. Конфигурация распространяется через shared Secret или version control.
2. **Независимость TSDB:** Экземпляры не синхронизируют данные между собой. Если один был недоступен, данные за этот период существуют только в другом.
3. **Внешние метки:** Каждый экземпляр получает уникальную метку (например, `prometheus_replica`), используемую для дедупликации.
4. **Alertmanager кластер:** Алерты отправляются во все экземпляры Alertmanager, которые выполняют дедупликацию через Gossip-протокол.

### Alertmanager кластер

Alertmanager использует Gossip-протокол для синхронизации состояния:

- **Минимум 3 узла** для кворума (переносит падение 1 узла)
- **Рекомендовано 3-5 узлов** для production
- **Нечетное число узлов** — рекомендация для предотвращения split-brain
- **Кластер TLS (v0.24+)** — шифрование трафика между узлами (порт 9094)

**Ключевые параметры Gossip:**
- Heartbeat: каждые 0.5 секунды
- Обнаружение отказа: > 10 секунд без ответа
- Сходимость: 1-3 секунды

### Remote Write как стратегия HA

```
Prometheus 1 --Remote Write--> LTS (VictoriaMetrics/Mimir)
Prometheus 2 --Remote Write--> LTS (VictoriaMetrics/Mimir)
```

- **At-least-once delivery:** Гарантия доставки данных (возможны дубли при восстановлении связи)
- **WAL-буфер:** Данные читаются с диска, а не из памяти — защита при рестарте
- **Backfill:** При недоступности LTS данные копятся в WAL, при восстановлении — агрессивная отправка

### Сценарии отказов и восстановления

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Дребезг графиков в HA** | Разница времени скрейпинга между репликами | Настроить `--query.lookback-delta` или внешнюю дедупликацию |
| **Потеря данных при Remote Write** | Переполнение очереди или недоступность LTS | Увеличить `max_shards` и `capacity`, мониторить `prometheus_remote_storage_dropped_samples_total` |
| **Hang Prometheus** | Тяжелые PromQL-запросы | Использовать `--query.max-concurrency` и `--query.timeout` |
| **Потеря данных при долгом outage LTS** | WAL превысил retention | Данные в старых сегментах WAL безвозвратно теряются |

## Практические примеры

### Запуск двух экземпляров Prometheus (bare-metal)

```bash
# Экземпляр 1
prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/data/prometheus-1 \
  --web.listen-address=:9090

# Экземпляр 2
prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/data/prometheus-2 \
  --web.listen-address=:9091
```

### Конфигурация HAProxy для балансировки

```
frontend prometheus_front
    bind *:9090
    default_backend prometheus_back

backend prometheus_back
    balance roundrobin
    server prom1 127.0.0.1:9090 check
    server prom2 127.0.0.1:9091 check backup
```

### Запуск кластера Alertmanager (3 узла)

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

### Конфигурация HA-пары с Remote Write

```yaml
# prometheus-1.yml и prometheus-2.yml (идентичные)
global:
  external_labels:
    prometheus_replica: 'prom-1'  # Уникальное для каждого экземпляра

remote_write:
  - url: "http://victoriametrics:8428/api/v1/write"
    queue_config:
      max_shards: 30
      capacity: 10000
```

### Мониторинг здоровья HA

```promql
# Дедупликация алертов в Alertmanager
alertmanager_notifications_total

# Отброшенные сэмплы при Remote Write
rate(prometheus_remote_storage_dropped_samples_total[5m])

# Размер очереди Remote Write
prometheus_remote_storage_queue_segments
```

## Дополнительная информация

* **Масштабирование и HA:** [Масштабирование Prometheus](../scaling/overview.md)
* **Alertmanager кластер:** [Alertmanager](../alertmanager.md), [Масштабирование Alertmanager](../scaling/alertmanager_scaling.md)
* **Remote Write HA:** [Remote Read/Write](../scaling/remote_read_write.md)
* **Глобальная HA с Thanos:** [Thanos](../scaling/thanos_overview.md)
* **Федерация:** [Федерация Prometheus](../scaling/federation.md)
* **HA в Kubernetes:** [High Availability (Operator)](../kubernetes/operator/high_availability.md)
* **Общие концепции HA:** [Обзор HA](../../Concepts/High_Availability/ha_overview.md)
