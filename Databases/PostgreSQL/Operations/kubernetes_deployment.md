# PostgreSQL в Kubernetes (CloudNativePG)

## Определения

**CloudNativePG (CNPG)** — это специализированный Kubernetes-оператор с открытым исходным кодом, предназначенный для управления полным жизненным циклом кластеров PostgreSQL. В отличие от традиционных решений (Patroni), CNPG изначально спроектирован для Kubernetes, используя его внутренние механизмы (API Server, Etcd) для обеспечения отказоустойчивости и управления состоянием.

**Инстанс-менеджер (Instance Manager)** — легковесный процесс (написанный на Go), который запускается внутри каждого пода PostgreSQL вместо стандартного `init` процесса. Он отвечает за мониторинг локальной БД, управление конфигурацией и выполнение команд оператора, исключая зависимость от внешних инструментов типа SSH.

**Декларативное управление БД** — подход, при котором администратор описывает в YAML-файле желаемое состояние кластера (версия, количество реплик, параметры тюнинга), а оператор непрерывно приводит текущее состояние к целевому (Reconciliation Loop).

**Volume Snapshot** — технология мгновенного создания копии данных на уровне хранилища (CSI). CNPG использует снапшоты для быстрого развертывания новых реплик (Seeding) и ускоренного восстановления.

## Базовые концепции

### Архитектура: Cloud Native vs Legacy HA
Традиционные кластеры PostgreSQL на ВМ полагаются на **Patroni + etcd/Consul** для выбора мастера. В Kubernetes это создает "проблему матрешки" (база для базы). 
CNPG решает это иначе:
- **Кворум через Kubernetes API:** Оператор использует `Lease` объекты Kubernetes для отслеживания лидера.
- **Отсутствие Sidecar:** Логика управления находится в основном процессе пода (Instance Manager), что упрощает диагностику и снижает потребление ресурсов.
- **Интеграция с K8s Service:** Мастер и реплики доступны через нативные Service, которые автоматически переключаются при сбоях.

### Жизненный цикл и обновление (Rolling Updates)
CNPG минимизирует время простоя при обслуживании:
1. **Switchover-first:** При обновлении образа или изменении параметров, требующих перезапуска, оператор сначала корректно переключает роль `Primary` на здоровую реплику.
2. **Graceful Shutdown:** Мастер дожидается завершения текущих транзакций перед остановкой.
3. **Автоматический Rejoin:** Старый мастер после обновления автоматически восстанавливается как реплика через `pg_rewind`.

### Стратегии хранения и QoS
Для Production-баз данных критически важно обеспечить предсказуемую производительность:
- **Guaranteed QoS:** Всегда устанавливайте `requests` равными `limits`. Это предотвращает вытеснение (Eviction) пода при нехватке ресурсов на узле.
- **Local Persistent Volumes:** Для максимальной производительности (минимальный latency) рекомендуется использовать локальные NVMe диски, хотя это требует ручного управления привязкой к узлам через Affinity.

## Предварительные требования
*   Кластер Kubernetes версии 1.29+ (Noble/Jammy на узлах).
*   Установленный **cert-manager** (рекомендуется для управления TLS).
*   Поддержка **CSI-драйвером** функций VolumeSnapshot (для быстрых бэкапов).
*   Плагин `kubectl-cnpg` для удобства администрирования.

## Практические сценарии

### Шаг 1: Установка оператора

```bash
# Добавление репозитория
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts

# Установка оператора с включенным PodMonitor для Prometheus
helm upgrade --install cnpg cloudnative-pg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --set monitoring.podMonitor.enabled=true

# Установка плагина управления
kubectl krew install cnpg
```

### Шаг 2: Манифест Production-кластера (PostgreSQL 18)

Этот манифест реализует лучшие практики 2026 года: изоляцию, безопасность и отказоустойчивость.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-prod
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:18
  
  # Синхронная репликация (гарантия отсутствия потери данных)
  minSyncReplicas: 1
  maxSyncReplicas: 1

  # Аутентификация (современный стандарт SCRAM)
  bootstrap:
    initdb:
      database: app_db
      owner: app_user
      secret:
        name: pg-app-user-creds

  # Тюнинг PostgreSQL параметров
  postgresql:
    parameters:
      shared_buffers: "1Gi"
      max_connections: "500"
      log_statement: "all"
      # Использование AIO из PG 18 (если ядро Linux поддерживает)
      io_direct: "data,wal"

  # Хранилище с использованием снапшотов
  storage:
    size: 200Gi
    storageClass: premium-rwo-ssd

  # Ресурсы (Guaranteed QoS)
  resources:
    requests:
      cpu: "4"
      memory: "8Gi"
    limits:
      cpu: "4"
      memory: "8Gi"

  # Разнесение по разным зонам доступности
  affinity:
    enablePodAntiAffinity: true
    topologyKey: topology.kubernetes.io/zone

  # Бэкапы в S3 (Cloud-native PITR)
  backup:
    barmanObjectStore:
      destinationPath: "s3://backups/pg-prod"
      endpointURL: "https://s3.yandexcloud.net"
      s3Credentials:
        accessKeyId: { name: s3-creds, key: ID }
        secretAccessKey: { name: s3-creds, key: SECRET }
      wal:
        compression: gzip
```

### Шаг 3: Настройка Pooler (PgBouncer)
Для работы с сотнями микросервисов необходимо использовать пулер соединений. CNPG позволяет создать его как нативный ресурс.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: pg-prod-pooler
spec:
  cluster:
    name: pg-prod
  instances: 3
  type: rw # Доступ к мастеру (или 'ro' для реплик)
  pgbouncer:
    poolMode: transaction
    parameters:
      max_client_conn: "5000"
      default_pool_size: "50"
```

### Шаг 4: Управление расписанием бэкапов
```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: pg-prod-daily
spec:
  schedule: "0 0 2 * * *" # Ежедневно в 2 часа ночи
  cluster:
    name: pg-prod
```

### Шаг 5: Операционные задачи через kubectl-cnpg

**Проверка статуса кластера:**
```bash
kubectl cnpg status pg-prod
# Показывает роль каждого пода, лаг репликации и статус WAL
```

**Подключение к psql:**
```bash
kubectl cnpg psql pg-prod -- -d app_db
```

**Безопасный Switchover (плановое обслуживание):**
```bash
kubectl cnpg switchover pg-prod --target pg-prod-2
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Pending` поды | Нехватка ресурсов или отсутствие PVC в нужной зоне. | Проверьте `kubectl describe pod` и наличие свободных PV в AZ. |
| `WAL archiving failing` | Ошибка доступа к S3 или неверные ключи. | Проверьте логи оператора: `kubectl logs -n cnpg-system deploy/cnpg-controller-manager`. |
| `OOM Killed` | Postgres потребил больше памяти, чем лимит K8s. | Проверьте `shared_buffers` + `work_mem * max_connections`. Увеличьте лимит RAM. |
| `Instance manager connection error` | Проблемы с сетевыми политиками или Cilium. | Разрешите трафик между подами кластера по порту 8000 (внутренний API CNPG). |

## Пограничные случаи и ограничения

### Крупные базы (>5 ТБ)
На таких объемах `pg_basebackup` через сеть может длиться сутки. 
- **Решение:** Используйте **Volume Snapshots** для создания кластера. Это сокращает время инициализации реплики с часов до минут.
- В манифесте: `bootstrap.recovery.volumeSnapshot.name`.

### Миграция с других операторов
Миграция с Zalando или ручного кластера выполняется через `bootstrap.externalClusters`. CNPG подключится к старому мастеру как реплика и выполнит полную синхронизацию данных.

## Дополнительная информация

### Выбор между CNPG и Zalando Operator

| Критерий | CloudNativePG (CNPG) | Zalando Operator |
| :--- | :--- | :--- |
| **Управление HA** | Нативное (Kubernetes API) | Patroni (требует DCS) |
| **Бинарный файл** | Единый Instance Manager (Go) | Spilo (Bash + Python + Patroni) |
| **Бэкапы** | Встроенный Barman-движок | WAL-G (через Sidecar) |
| **Пулер** | Нативный ресурс `Pooler` | Отдельные манифесты Deployment |
| **Версия PostgreSQL** | Всегда актуальная (18+) | Зависит от образов Spilo |

### Связанные документы
- **[Наблюдаемость PostgreSQL](./observability.md)** — дашборды Grafana и алертинг.
- **[Сетевая связность](./kubernetes_connectivity.md)** — Service Mesh, Ingress и Topology Routing.
- **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — альтернативный подход.
- **[Backup and Recovery](../Concepts/backup_and_recovery.md)** — теория PITR и WAL.
