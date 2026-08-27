# High Availability и Disaster Recovery для Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**High Availability (HA)** и **Disaster Recovery (DR)** для Jaeger — это набор архитектурных решений, обеспечивающих непрерывную работу системы трассировки при отказах компонентов, сетевых разрывах или катастрофах. В production-средах Jaeger является частью экосистемы наблюдаемости, и его недоступность приводит к слепоте при диагностике инцидентов. Поэтому проектирование HA/DR для Jaeger — не опция, а требование.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Развертывание: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.

---

## Опредеitions

| Термин | Описание |
| :--- | :--- |
| **High Availability (HA)** | Архитектурный подход, обеспечивающий непрерывную работу при отказе отдельных компонентов (нод, процессов, дисков) |
| **Disaster Recovery (DR)** | Процесс восстановления после масштабных катастроф (потеря дата-центра, повреждение кластера БД) |
| **RTO (Recovery Time Objective)** | Максимальное допустимое время простоя системы |
| **RPO (Recovery Point Objective)** | Максимально допустимый объем потери данных (например, 5 минут трейсов) |
| **Failover** | Автоматическое переключение на резервный компонент при отказе основного |
| **Load Balancer (LB)** | Устройство/сервис для распределения трафика между репликами Query/Collector |
| **Circuit Breaker** | Паттерн, прекращающий отправку запросов в неработающее хранилище для предотвращения каскадных сбоев |

---

## Базовые концепции

### Уровни отказоустойчивости

| Уровень | Описание | Компоненты | RTO | RPO |
| :--- | :--- | :--- | :--- | :--- |
| **Basic** | Один инстанс каждого компонента | Collector 1, Query 1, ClickHouse 1 | Часы | Часы |
| **HA (High Availability)** | Множество реплик stateless-компонентов, HA Storage | Collector 3+, Query 2+, ClickHouse RF=2 | Минуты | Минуты |
| **DR (Disaster Recovery)** | Географическое распределение, бэкапы, резервный кластер | Collector + Query + Kafka + ClickHouse в двух ЦОД | Десятки минут | Десятки минут |

### Компоненты и их отказоустойчивость

| Компонент | HA механизм | DR механизм |
| :--- | :--- | :--- |
| **Collector** | Deployment с 3+ репликами, HPA, PodDisruptionBudget | Географическое распределение, multi-cluster Kafka |
| **Query** | Stateless, горизонтальное масштабирование за LB | Кеширующий reverse proxy (Varnish), multi-region deployment |
| **Storage (ClickHouse)** | Replicated MergeTree, ZooKeeper/ClickHouse Keeper для координации | Бэкапы в S3, кросс-региональная репликация |
| **Storage (Elasticsearch)** | Мастер-ноды 3+, реплики шардов | Снимки (snapshots) в S3, CCR (Cross-Cluster Replication) |
| **Kafka** | Replication Factor 3, ISR (In-Sync Replicas) | MirrorMaker 2 для репликации между кластерами |

### Что происходит при сбоях

| Сбой | Влияние | Автоматическое восстановление | Действия |
| :--- | :--- | :--- | :--- |
| **Падение одного Collector** | Потеря части входящего потока (если нет LB health check) | Kubernetes перезапускает под, LB отключает unhealthy instance | Проверить `otelcol_receiver_refused_spans_total` |
| **Падение ClickHouse шарда** | Поиск работает частично, запись может замедлиться | ClickHouse reroutes запросы на реплики | Проверить `jaeger_span_store_write_errors_total` |
| **Потеря Kafka брокера** | Задержка потребления сообщений Ingester | Автоматический failover на ISR-реплику | Проверить `consumer_lag` |
| **Падение всего ЦОД** | Полная недоступность Jaeger | Переключение на резервный кластер | Восстановление из бэкапа, RTO зависит от DR стратегии |

---

## Практические сценарии

### Сценарий 1: Настройка HA для Collector и Query в Kubernetes

**Ситуация:** Необходимо обеспечить отказоустойчивость Collector и Query в Kubernetes.

```yaml
# collector-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: jaeger-collector
    spec:
      serviceAccountName: jaeger-collector
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: jaeger-collector
                topologyKey: kubernetes.io/hostname
      containers:
        - name: collector
          image: jaegertracing/jaeger:2.0.0
          ports:
            - containerPort: 4317
            - containerPort: 4318
            - containerPort: 8888
          livenessProbe:
            httpGet:
              path: /
              port: 8888
            initialDelaySeconds: 15
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /
              port: 8888
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 2000m
              memory: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger-collector
  namespace: observability
spec:
  selector:
    app.kubernetes.io/name: jaeger-collector
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
    - name: otlp-http
      port: 4318
      targetPort: 4318
  type: ClusterIP
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: jaeger-collector-pdb
  namespace: observability
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector
```

**Валидация:**

1. Применить манифесты: `kubectl apply -f collector-ha.yaml`.
2. Проверить реплики: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-collector`.
3. Убедиться, что PodDisruptionBudget активен: `kubectl get pdb -n observability jaeger-collector-pdb`.
4. Проверить, что Service балансирует трафик: `kubectl describe svc jaeger-collector -n observability`.

### Сценарий 2: Настройка HA для ClickHouse

**Ситуация:** Необходимо обеспечить отказоустойчивость ClickHouse кластера с репликацией.

```bash
# 1. Конфигурация первого узла (clickhouse-01)
# /etc/clickhouse-server/config.xml
<clickhouse>
  <listen_host>0.0.0.0</listen_host>
  <remote_servers>
    <jaeger_cluster>
      <shard>
        <replica>
          <host>clickhouse-01</host>
          <port>9000</port>
        </replica>
        <replica>
          <host>clickhouse-02</host>
          <port>9000</port>
        </replica>
      </shard>
    </jaeger_cluster>
  </remote_servers>
</clickhouse>

# 2. Создание базы с движком ReplicatedMergeTree
clickhouse-client --query "
CREATE DATABASE IF NOT EXISTS jaeger_v2;

CREATE TABLE IF NOT EXISTS jaeger_v2.spans
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/jaeger_v2.spans', '{replica}')
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (service_name, operation_name, start_time_ns)
TTL start_time_ns + INTERVAL 7 DAY;
"

# 3. Проверка репликации
clickhouse-client --query "SELECT count() FROM jaeger_v2.spans" --host clickhouse-01
clickhouse-client --query "SELECT count() FROM jaeger_v2.spans" --host clickhouse-02
```

**Валидация:**

1. Остановить один узел: `docker stop clickhouse-02`.
2. Отправить тестовый спан и убедиться, что запись проходит через `clickhouse-01`.
3. Запустить узел и убедиться, что данные синхронизировались.

### Сценарий 3: Бэкап и восстановление ClickHouse

**Ситуация:** Необходимо настроить регулярные бэкапы и проверить процесс восстановления.

```bash
# 1. Создание бэкапа
clickhouse-client --query "BACKUP TABLE jaeger_v2.spans TO 's3://backups/jaeger/$(date +%Y%m%d_%H%M%S)'"

# 2. Восстановление из бэкапа
clickhouse-client --query "RESTORE TABLE jaeger_v2.spans FROM 's3://backups/jaeger/20260824_120000'"

# 3. Проверка
clickhouse-client --query "SELECT count() FROM jaeger_v2.spans"
```

### Сценарий 4: Кластерный DR с использованием Kafka MirrorMaker 2

**Ситуация:** Необходимо настроить асинхронную репликацию топика `jaeger-spans` между primary и DR кластерами Kafka.

```bash
# 1. Создание топика в DR кластере
kafka-topics.sh --create \
  --topic jaeger-spans-dr \
  --bootstrap-server kafka-dr:9092 \
  --partitions 12 \
  --replication-factor 3

# 2. Запуск MirrorMaker 2
/opt/kafka/bin/kafka-mirror-maker.sh \
  --consumer.config /opt/kafka/config/consumer-primary.properties \
  --producer.config /opt/kafka/config/producer-dr.properties \
  --whitelist "jaeger-spans" \
  --num.streams 4
```

**Валидация:**

1. Отправить тестовое сообщение в primary топик.
2. Убедиться, что оно появилось в DR топике.
3. Проверить `consumer_lag` в DR кластере.

---

## Лучшие практики

1.  **Минимум 3 реплики Collector:** Одна может упасть, вторая обновляться, третья обрабатывает трафик.
2.  **PodDisruptionBudget:** Защищает от одновременного удаления всех реплик при drain узла.
3.  **ClickHouse ReplicatedMergeTree:** Используйте ReplicatedMergeTree вместо MergeTree для HA.
4.  **Kafka Replication Factor 3:** Минимум 3 реплики для durability.
5.  **Регулярные бэкапы:** Автоматические бэкапы ClickHouse в S3 с retention 30 дней.
6.  **Мониторинг lag и disk:** Настройте алерты на `consumer_lag` и `disk_usage` до наступления проблем.
7.  **Тестируйте failover:** Регулярно проверяйте переключение на резервные компоненты (Chaos Engineering).

---

## Очистка окружения

```bash
# Остановка Docker Compose
docker compose down -v

# Удаление данных ClickHouse
docker volume rm jaeger_clickhouse_data

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Обзор HA/DR паттернов: **[Высокая доступность: Обзор](../Concepts/High_Availability/ha_overview.md)**
* Стратегии DR: **[Аварийное восстановление](../Concepts/disaster_recovery.md)**
* Storage и бэкенды: **[Обзор Jaeger](./jaeger_overview.md)**
* Kafka replication: **[Apache Kafka: Обзор](../Kafka/kafka_overview.md)**
* ClickHouse replication: **[ClickHouse: Обзор](../Databases/ClickHouse/clickhouse.md)**

### См. также

* [Jaeger Production Deployment Guide](https://www.jaegertracing.io/docs/latest/deployment/)
* [ClickHouse High Availability](https://clickhouse.com/docs/en/guides/sre/configuring-availability)
