# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

**Spilo** — Docker-образ от Zalando, объединяющий PostgreSQL, Patroni для обеспечения высокой доступности и инструменты для резервного копирования (WAL-E/WAL-G).

**Patroni** — шаблонное решение для создания отказоустойчивых кластеров PostgreSQL. Автоматизирует управление ролями (Primary/Replica) и процесс переключения при сбоях (failover). Подробнее — **[High Availability](../Concepts/high_availability.md#patroni-стандарт-де-факто)**.

**DCS (Distributed Configuration Store)** — распределенное хранилище конфигурации (etcd, Consul, ZooKeeper) или API Kubernetes, используемое Patroni для хранения состояния кластера и выбора лидера.

## Основные концепции

### Подход к развертыванию

Развертывание через прямые манифесты Kubernetes (StatefulSet, Service, RBAC) обеспечивает максимальный контроль над конфигурацией, но требует более глубокого понимания внутренних механизмов Spilo по сравнению с использованием **[Zalando Postgres Operator](./zalando_postgres_operator.md)**.

### Динамическое управление точками доступа (Endpoints)

Для корректной маршрутизации трафика только на мастер-узел (Primary) Spilo использует механизм прямого манипулирования ресурсами `Endpoints`:

1. Создается `Service` без селектора (selector-less service).
2. Создается объект `Endpoints` с тем же именем, что и сервис.
3. Инстанс Patroni, выбранный лидером (Primary), отправляет запрос к Kubernetes API для обновления этого `Endpoints`, вписывая свой IP-адрес.
4. Клиентские приложения подключаются к сервису, который всегда указывает на актуальный мастер.

**Требование:** ServiceAccount подов PostgreSQL должен иметь RBAC-права на `patch` и `update` ресурсов `endpoints` и `configmaps`.

### Управление конфигурацией

Настройка Spilo и Patroni выполняется через переменные окружения в спецификации контейнера. Основные параметры включают настройки подключения к DCS, параметры аутентификации и правила архивирования логов.

## Практические сценарии

### Подготовка манифестов

Ниже приведены ключевые фрагменты манифестов для развертывания кластера из 3 узлов.

#### Спецификация StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg-cluster
  namespace: database
spec:
  replicas: 3
  serviceName: "pg-cluster-config"
  selector:
    matchLabels:
      application: spilo
  template:
    metadata:
      labels:
        application: spilo
        spilo-cluster: pg-prod
    spec:
      serviceAccountName: spilo-sa
      containers:
      - name: postgres
        image: "registry.opensource.zalan.do/acid/spilo-15:3.2-p1"
        env:
          - name: SCOPE
            value: "pg-prod"
          - name: KUBERNETES_SCOPE_LABEL
            value: "spilo-cluster"
          # Настройка DCS через Kubernetes API
          - name: DCS_ENABLE_KUBERNETES_API
            value: "true"
          - name: KUBERNETES_LABELS
            value: '{"application": "spilo"}'
          # Переменные для WAL-G (бэкап в S3)
          - name: WALG_S3_PREFIX
            value: "s3://backups/pg-prod"
```

#### Настройка Affinity (Отказоустойчивость)

Для защиты от выхода из строя целой ноды необходимо распределить поды кластера по разным узлам:

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: spilo-cluster
          operator: In
          values: ["pg-prod"]
      topologyKey: "kubernetes.io/hostname"
```

#### Настройка сервисов для доступа

```yaml
# Сервис для мастера (управляется Patroni через Endpoints)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod
spec:
  ports:
  - port: 5432
    targetPort: 5432
---
# Пустой объект Endpoints, который будет обновлять Patroni
apiVersion: v1
kind: Endpoints
metadata:
  name: pg-prod
subsets: []
```

### Операции и обслуживание

**Проверка состояния кластера:**

Выполняется изнутри любого пода PostgreSQL с помощью утилиты `patroni_ctl`.

```bash
kubectl exec -it pg-cluster-0 -n database -- patroni_ctl list
```

**Ожидаемый вывод:**

```text
+---------+--------------+--------------+--------+---------+----+-----------+
| Cluster | Member       | Host         | Role   | State   | TL | Lag in MB |
+---------+--------------+--------------+--------+---------+----+-----------+
| pg-prod | pg-cluster-0 | 10.244.1.25  | Leader | running |  1 |           |
| pg-prod | pg-cluster-1 | 10.244.2.29  |        | running |  1 |         0 |
| pg-prod | pg-cluster-2 | 10.244.3.26  |        | running |  1 |         0 |
+---------+--------------+--------------+--------+---------+----+-----------+
```

**Плановое переключение ролей (Switchover):**

Используется для обслуживания узла-лидера без аварийного завершения транзакций.

```bash
kubectl exec -it pg-cluster-0 -n database -- patroni_ctl switchover
```

## Дополнительная информация

### Сравнение с оператором

Развертывание через манифесты рекомендуется только в случаях, когда требуются специфические настройки Spilo, не поддерживаемые **[Zalando Postgres Operator](./zalando_postgres_operator.md)** (например, кастомные sidecar-контейнеры или сложные схемы монтирования томов).

### Связанные документы

- **Теория высокой доступности:** **[High Availability](../Concepts/high_availability.md)**
- **Резервное копирование:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Управление через оператор:** **[Zalando Postgres Operator](./zalando_postgres_operator.md)**
- **PostgreSQL в Kubernetes:** **[Kubernetes Deployment](./kubernetes_deployment.md)**
