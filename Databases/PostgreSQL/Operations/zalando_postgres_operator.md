# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — Kubernetes-оператор с открытым исходным кодом для автоматизации полного жизненного цикла кластеров PostgreSQL. Использует Custom Resource Definitions (CRD) для декларативного управления базами данных.

**Spilo** — базовый Docker-образ кластера, объединяющий PostgreSQL и Patroni. Обеспечивает консистентность среды и инструментов управления.

**Patroni** — Python-приложение, управляющее жизненным циклом инстанса PostgreSQL. Оно автоматизирует выбор лидера, настройку репликации и переключение при сбоях (failover). Подробнее — **[High Availability](../Concepts/high_availability.md)**.

**PostgresTeam** — механизм RBAC в операторе, позволяющий делегировать управление кластерами конкретным командам на основе `teamId`.

**PgBouncer** — легкий пул соединений. Оператор поддерживает автоматическое развертывание PgBouncer в качестве Sidecar или отдельного Deployment.

## Основные концепции

### Архитектура и управление

Оператор работает как контроллер, обеспечивая:
1. **Командная модель**: Доступ к ресурсам разграничивается через `teamId`. Только члены команды (или суперпользователи) могут изменять манифест кластера.
2. **Гибкое масштабирование**: Увеличение количества реплик (`numberOfInstances`) или размера диска (`volume.size`) выполняется одной правкой YAML.
3. **Клонирование и PITR**: Поддержка создания новых кластеров из существующих (cloning) или из бэкапов в S3 (Bootstrap) для тестирования на реальных данных.
4. **Управление пулом**: Встроенная поддержка PgBouncer позволяет обслуживать тысячи соединений с минимальными затратами ресурсов.

### Сравнение с CloudNativePG (CNPG)

| Характеристика | Zalando Operator | CloudNativePG |
| :--- | :--- | :--- |
| **Основа HA** | Patroni (внутри подов) | Native K8s API (через оператор) |
| **Сложность** | Выше (требует понимания Patroni) | Ниже (нативный K8s подход) |
| **Инфраструктура** | Требует etcd (или K8s API как DCS) | Без внешних зависимостей |
| **Особенности** | Командная модель, богатый UI | Снапшоты томов, современная кодовая база |

## Практические сценарии

### Шаг 1: Установка оператора через Helm

```bash
# Подключение репозитория
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo update

# Установка
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace
```

### Шаг 2: Развертывание кластера с PgBouncer и S3-бэкапами

Пример манифеста для Production-среды.

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: pg-prod-cluster
  namespace: database
spec:
  teamId: "billing-team"
  numberOfInstances: 3
  postgresql:
    version: "17"
    parameters:
      shared_buffers: "1GB"
      max_connections: "100"
  
  # Интеграция с PgBouncer
  enableConnectionPooler: true
  connectionPooler:
    numberOfInstances: 2
    mode: "transaction"
    resources:
      requests: {cpu: "100m", memory: "100Mi"}
      limits: {cpu: "500m", memory: "200Mi"}

  volume:
    size: "100Gi"
    storageClass: "premium-rwo"

  # Настройка бэкапов в S3 (WAL-G)
  enableLogicalBackup: true
  logicalBackupSchedule: "00 01 * * *"
  
  resources:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "2"
      memory: "2Gi"
```

### Шаг 3: Клонирование из бэкапа (PITR)

Создание тестового кластера на основе состояния основного кластера на определенный момент времени.

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: pg-clone
spec:
  teamId: "billing-team"
  numberOfInstances: 1
  clone:
    cluster: "pg-prod-cluster"
    timestamp: "2026-08-03T12:00:00+00:00"
  # ... ресурсы и хранилище
```

## Дополнительная информация

### Диагностика и SRE

1. **Проверка статуса Patroni**:
   ```bash
   kubectl exec -it pg-prod-cluster-0 -c postgres -- patronictl list
   ```
2. **Логи оператора**:
   Критически важны при ошибках синхронизации (SyncFailed).
   ```bash
   kubectl logs -l app.kubernetes.io/name=postgres-operator -n postgres-operator
   ```
3. **Обновление конфигурации**:
   При изменении `postgresql.parameters` оператор может выполнить Rolling Update. Проверяйте `status.postgreSQL` для отслеживания процесса.

### Смотрите также

* **[PostgreSQL в Kubernetes (CloudNativePG)](./kubernetes_deployment.md)** — сравнение и альтернатива.
* **[Zalando Spilo: Манифесты](./zalando_spilo_manifests.md)** — ручное управление без оператора.
* **[High Availability](../Concepts/high_availability.md)** — теория работы Patroni и DCS.
* **[Наблюдаемость PostgreSQL](./observability.md)** — мониторинг кластеров под управлением оператора.
