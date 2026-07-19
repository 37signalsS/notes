# PostgreSQL в Kubernetes (CloudNativePG)

## Определения

**CloudNativePG (CNPG)** — современный Kubernetes-оператор с открытым исходным кодом для автоматизации полного жизненного цикла кластеров PostgreSQL. Проект входит в CNCF Sandbox и ориентирован на "облачно-нативный" (Cloud Native) подход, используя внутренние механизмы Kubernetes вместо внешних инструментов управления кворумом (например, Patroni).

**Оператор (Operator)** — паттерн в Kubernetes, объединяющий Custom Resources и контроллеры для автоматизации задач администратора БД: развертывание, масштабирование, бэкапы и восстановление. Подробнее — [Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md).

## Основные концепции

### Почему CloudNativePG?

В отличие от классических решений, CNPG глубоко интегрирован в экосистему Kubernetes:
- **Отсутствие внешних зависимостей:** не требует etcd или Consul для управления состоянием кластера.
- **Декларативность:** всё управление (включая конфигурацию PostgreSQL и бэкапы) описывается через YAML.
- **Безопасность:** по умолчанию работает в режиме non-privileged контейнеров.
- **Observability:** нативная поддержка Prometheus и структурированное логирование в формате JSON.

### Архитектура высокой доступности (HA)

Для обеспечения надежности в production-средах CNPG использует:
1. **Topology Spread Constraints:** распределение подов по разным зонам доступности (Availability Zones) или физическим нодам для защиты от сбоев оборудования.
2. **Pod Disruption Budget (PDB):** гарантирует, что при плановом обслуживании нод (drain) в кластере останется минимально необходимое количество реплик.
3. **Quorum-based Failover:** оператор сам управляет продвижением (promote) реплики до primary, минимизируя время простоя.

### Управление ресурсами и памятью

PostgreSQL в Kubernetes требует тщательной настройки лимитов:
- **Requests vs Limits:** рекомендуется устанавливать `requests` равными `limits` для CPU и RAM, чтобы избежать вытеснения пода или непредсказуемой производительности.
- **HugePages:** для высоконагруженных баз данных рекомендуется включение HugePages на уровне нод и проброс их в под через `resources.limits`.
- **Shared Buffers:** CNPG автоматически рассчитывает `shared_buffers` (обычно 25% от лимита памяти), но параметр можно переопределить в `spec.postgresql.parameters`.

## Практические сценарии

### Установка оператора и плагина

Рекомендуемый способ установки — через Helm или прямые манифесты.

```bash
# Установка через Helm
helm upgrade --install cnpg cloudnative-pg/cloudnative-pg --namespace cnpg-system --create-namespace

# Установка плагина kubectl-cnpg (через Krew)
kubectl krew install cnpg
```

### Развертывание production-кластера

Пример конфигурации с учетом отказоустойчивости и ресурсов.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-prod
spec:
  instances: 3
  
  # Ограничение ресурсов
  resources:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "2"
      memory: "4Gi"

  # Распределение по зонам/нодам
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: "topology.kubernetes.io/zone"
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          "cnpg.io/cluster": "pg-prod"

  # Хранилище
  storage:
    size: "50Gi"
    storageClass: "premium-rwo" # Пример для SSD в облаке

  # Настройка PostgreSQL
  postgresql:
    parameters:
      max_connections: "200"
      shared_buffers: "1GB"

  # Резервное копирование в S3
  backup:
    barmanObjectStore:
      destinationPath: "s3://my-backups/pg-prod"
      endpointURL: "https://s3.amazonaws.com"
      s3Credentials:
        accessKeyId:
          name: s3-creds
          key: ID
        secretAccessKey:
          name: s3-creds
          key: SECRET
      wal:
        compression: gzip
```

### Операционные задачи

**Проверка состояния кластера:**
```bash
kubectl cnpg status pg-prod
```

**Интерактивное подключение:**
```bash
kubectl cnpg psql pg-prod
```

**Перезапуск (Rolling Update):**
При изменении параметров в YAML оператор автоматически выполнит последовательный перезапуск подов (сначала реплики, затем переключение primary и перезапуск старого primary).

**Масштабирование:**
Для добавления или удаления реплик достаточно изменить значение `spec.instances` в манифесте.

## Дополнительная информация

### Выбор между CNPG и Zalando Operator

- **CloudNativePG:** если вам нужна нативная интеграция с K8s, отсутствие Patroni/etcd и современная кодовая база. Идеально для новых проектов.
- **Zalando Operator:** если требуется совместимость с устоявшимися практиками Patroni или специфические возможности Spilo (например, интеграция с OAuth2). Подробнее — [Zalando Postgres Operator](./zalando_postgres_operator.md).

### Связанные документы

- [PostgreSQL Overview](../overview.md) — основы СУБД.
- [Наблюдаемость PostgreSQL](./observability.md) — интеграция с Prometheus и Grafana.
- [Сетевая связность](./kubernetes_connectivity.md) — доступ к базе изнутри и снаружи K8s.
- [Backup and Recovery](../Concepts/backup_and_recovery.md) — концепции PITR и WAL.
- [StatefulSet](../../../Kubernetes/Base/StatefulSet/statefulset_overview.md) — как K8s управляет состоянием.
