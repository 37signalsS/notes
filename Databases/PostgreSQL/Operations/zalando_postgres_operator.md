# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — Kubernetes-оператор с открытым исходным кодом для автоматизации полного жизненного цикла кластеров PostgreSQL. Он реализует паттерн «Контроллер», отслеживая состояние пользовательского ресурса `postgresql` (CRD) и приводя текущее состояние кластера в соответствие с декларативным описанием.

**Spilo** — специализированный Docker-образ, являющийся фундаментом оператора. Он объединяет в себе PostgreSQL, Patroni (для HA), WAL-G (для бэкапов) и набор утилит для диагностики. Spilo обеспечивает идентичность среды на всех узлах кластера.

**Patroni** — агент управления (шаблон), работающий внутри Spilo. Он отвечает за выбор лидера через DCS, настройку репликации и выполнение автоматического failover. Подробнее — **[High Availability в PostgreSQL](../Concepts/high_availability.md)**.

**DCS (Distributed Configuration Store)** — распределенное хранилище для координации Patroni. В Kubernetes оператор по умолчанию использует **Kubernetes API** (через ресурсы ConfigMaps или Endpoints) как DCS, что избавляет от необходимости развертывать внешний etcd.

**PostgresTeam** — механизм RBAC и логической группировки в операторе. Позволяет делегировать управление базами данных конкретным командам на основе идентификатора `teamId`, интегрируясь с внешними системами управления инфраструктурой.

## Основные концепции

### Архитектура и управление

Оператор функционирует как высокоуровневый оркестратор над Spilo и Patroni:

1.  **Контрольный цикл (Control Loop)**: Оператор непрерывно опрашивает Kubernetes API на предмет изменений в ресурсах `postgresql`. При обнаружении расхождений (изменение количества реплик, версии образа или параметров БД) он выполняет необходимые действия: создание StatefulSet, Service, Secrets или запуск Rolling Update.
2.  **Командная модель**: Доступ к управлению кластером жестко привязан к `teamId`. Это позволяет безопасно предоставлять доступ к CRD разным командам в рамках одного кластера Kubernetes.
3.  **Интеграция с DCS**: Оператор настраивает Patroni на использование Kubernetes API для хранения лидерских блокировок. Это критически важно для надежности: если API Kubernetes доступен, кластер сохраняет работоспособность.
4.  **Sidecars и инфраструктура**: Оператор поддерживает автоматическое внедрение Sidecar-контейнеров для мониторинга (например, `postgres-exporter`) и логирования, а также развертывание пула соединений PgBouncer.

### Сравнение с CloudNativePG (CNPG)

| Характеристика | Zalando Operator | CloudNativePG |
| :--- | :--- | :--- |
| **Основа HA** | Patroni + DCS (внутри подов) | Native K8s API (через оператор) |
| **Сложность** | Выше (требует понимания Patroni/Spilo) | Ниже (нативный K8s-native подход) |
| **Изоляция** | Управление внутри пода (Patroni PID 1) | Управление снаружи (Instance Manager) |
| **Особенности** | Богатый опыт эксплуатации (Zalando), UI | Современная кодовая база, снапшоты томов |
| **DCS** | Нужен (K8s API или etcd) | Не требуется (встроен в оператор) |

## Практические сценарии

### 1. Подготовка окружения (Prerequisites)

Перед установкой необходимо обеспечить:
- **RBAC**: Оператор требует широких прав в кластере для управления StatefulSet, Pods, Services и Endpoints.
- **StorageClass**: Наличие динамического провижининга томов с поддержкой `AllowVolumeExpansion: true` для расширения дисков без простоя.
- **S3 Bucket**: (Опционально) Для хранения бэкапов через WAL-G.

### 2. Установка оператора через Helm

```bash
# Подключение репозитория
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo update

# Установка с базовыми настройками
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace \
  --set configTarget=ConfigMap
```

### 3. Развертывание Production-кластера

Пример манифеста с PgBouncer, логическими бэкапами и тюнингом Patroni.

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: pg-prod-cluster
  namespace: database
spec:
  teamId: "data-infra"
  numberOfInstances: 3
  postgresql:
    version: "16" # Поддержка версий 14, 15, 16, 17, 18
    parameters:
      shared_buffers: "2GB"
      max_connections: "200"
      log_statement: "all"
  
  # Настройка Patroni (тюнинг HA)
  patroni:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 33554432 # 32MB

  # Интеграция с PgBouncer
  enableConnectionPooler: true
  connectionPooler:
    numberOfInstances: 2
    mode: "transaction"
    resources:
      requests: {cpu: "200m", memory: "256Mi"}
      limits: {cpu: "500m", memory: "512Mi"}

  volume:
    size: "200Gi"
    storageClass: "ssd-storage"

  # Бэкапы и обслуживание
  enableLogicalBackup: true
  logicalBackupSchedule: "00 02 * * *"
  
  resources:
    requests:
      cpu: "2"
      memory: "4Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
      
  # Создание баз и пользователей при старте
  databases:
    billing_db: billing_user
  users:
    billing_user: [superuser, createdb]
```

### 4. Клонирование и PITR (Point-in-Time Recovery)

Создание копии кластера из S3-бэкапа на определенный момент времени.

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: pg-clone-staging
spec:
  teamId: "data-infra"
  numberOfInstances: 1
  clone:
    cluster: "pg-prod-cluster"
    timestamp: "2026-08-15T10:00:00+00:00"
    s3_wal_path: "s3://my-backups/pg-prod-cluster/wal/"
  volume:
    size: "200Gi"
```

### 5. Обновление мажорной версии (Major Upgrade)

В отличие от ручного обновления, оператор может автоматизировать переход (например, 15 -> 16) через изменение поля `version` в манифесте, если это поддерживается текущим образом Spilo. 
**Внимание:** Всегда делайте ручной бэкап перед мажорным обновлением.

---

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Status: SyncFailed** | Ошибка валидации манифеста или нехватка прав RBAC. | Проверьте логи оператора: `kubectl logs -l app.kubernetes.io/name=postgres-operator`. |
| **Pod Stuck in Pending** | Недостаточно ресурсов (CPU/RAM) или нет подходящего PV. | Проверьте `kubectl describe pod`. Убедитесь, что StorageClass доступен. |
| **Multiple Masters** | Проблема с DCS (Endpoints/ConfigMaps). | Проверьте `patronictl list` внутри пода. Проверьте права оператора на работу с Endpoints. |
| **Backup Failed** | Неверные секреты AWS_ACCESS_KEY или нет доступа к S3. | Проверьте логи Sidecar-контейнера WAL-G (если используется). |
| **Logical Backup OOM** | Слишком большая БД для логического бэкапа в памяти. | Увеличьте лимиты памяти для `logical_backup` в конфигурации оператора. |

### Полезные команды SRE

1.  **Просмотр топологии кластера (внутри пода)**:
    ```bash
    kubectl exec -it pg-prod-cluster-0 -c postgres -- patronictl list
    ```
2.  **Принудительный Switchover**:
    ```bash
    kubectl exec -it pg-prod-cluster-0 -c postgres -- patronictl switchover
    ```
3.  **Проверка логов конкретного инстанса**:
    ```bash
    kubectl logs pg-prod-cluster-0 -c postgres
    ```

## Дополнительная информация

### Смотрите также

*   **[PostgreSQL в Kubernetes (CloudNativePG)](./kubernetes_deployment.md)** — глубокое сравнение альтернативного оператора.
*   **[Zalando Spilo: Манифесты](./zalando_spilo_manifests.md)** — использование образов Spilo без оператора.
*   **[High Availability в PostgreSQL](../Concepts/high_availability.md)** — теория работы Patroni, Watchdog и алгоритмов выбора лидера.
*   **[Наблюдаемость PostgreSQL](./observability.md)** — дашборды Grafana и алертинг для оператора.
*   **[Тюнинг производительности PostgreSQL](./performance_tuning.md)** — параметры `postgresql.parameters` для высоконагруженных систем.

**Инструменты:** `Zalando Postgres Operator`, `Spilo`, `Patroni`, `WAL-G`, `PgBouncer`, `kubectl`, `Helm`.
