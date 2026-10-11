# MySQL Operator для Kubernetes

**Актуально для:** MySQL Operator 2.x, MySQL 8.0 / 8.4 LTS

## Определения

**MySQL Operator for Kubernetes** — специализированный контроллер, реализующий паттерн **Operator**, который автоматизирует управление жизненным циклом InnoDB Cluster в Kubernetes. Он берет на себя задачи инициализации, масштабирования, резервного копирования и восстановления, используя декларативный подход.

**InnoDB Cluster** — нативное высокодоступное решение от Oracle, объединяющее **Group Replication** (синхронная репликация на базе Paxos), **MySQL Router** (прокси для маршрутизации трафика) и **MySQL Shell** (инструмент администрирования).

**Reconciliation Loop (Цикл согласования)** — основной механизм работы оператора, который непрерывно сравнивает текущее состояние ресурсов в кластере с желаемым (описанным в YAML) и выполняет действия по их приведению в соответствие.

**Custom Resource Definition (CRD)** — расширение API Kubernetes, позволяющее оператору создавать и управлять специфичными для MySQL объектами (`InnoDBCluster`, `MySQLBackup` и др.) как стандартными ресурсами K8s.

## Базовые концепции

### 1. Архитектура управления

Оператор состоит из центрального контроллера, который наблюдает за CRD, и набора Sidecar-контейнеров внутри подов с базой данных.

*   **InnoDBCluster CR**: Определяет топологию (Single-Primary по умолчанию), версию СУБД, количество узлов и требования к хранилищу.
*   **MySQL Router CR**: Развертывается как отдельный Deployment или DaemonSet. Он обеспечивает прозрачный Read/Write Split: запросы на запись идут на Primary узел, запросы на чтение — на Secondary узлы.
*   **Storage Management**: Оператор использует `VolumeClaimTemplates` для создания уникальных Persistent Volume Claims (PVC) для каждого узла. При удалении пода оператор гарантирует, что новый под привяжется к тому же PVC, сохраняя данные.

### 2. Group Replication и консенсус

В отличие от классической репликации, InnoDB Cluster в Kubernetes использует Group Replication:
- **Кворум:** Для работы кластера требуется большинство узлов (минимум 2 из 3).
- **Автоматический Failover:** Если мастер-под падает, оставшиеся узлы выбирают нового лидера через протокол консенсуса. Оператор обновляет конфигурацию MySQL Router, чтобы трафик мгновенно переключился на новый адрес.

### 3. Предварительные требования (Prerequisites)

**Инфраструктура и ОС:**
- **Kubernetes**: Версия 1.27+ (рекомендуется).
- **StorageClass**: Должен поддерживать динамическое создание томов с `accessModes: [ReadWriteOnce]`. Для Production критически важна поддержка быстрых SSD/NVMe.
- **Ресурсы**: Минимум 2 ГБ RAM на каждый узел MySQL для стабильной работы Group Replication.
- **Сеть**: Порты `3306/tcp` (MySQL), `8443/tcp` (Router HTTP), `10008/tcp` (Raft, если используется HA Orchestrator) должны быть открыты между узлами.
- **NTP**: Синхронизация времени через `chrony` или `systemd-timesyncd` обязательна. Расхождение > 100 ms ломает GTID и мониторинг лага.
- **Лимиты файлов**: `ulimit -n` должен быть ≥ 65535 для пода MySQL. Проверка: `ulimit -n` внутри пода или на узле.
- **Security Context**: Под MySQL должен работать от непривилегированного пользователя (`runAsUser: 999`, `runAsGroup: 999`), без прав `privileged: true`.

**Планирование емкости (Capacity Planning):**
- **RAM**: `innodb_buffer_pool_size` (~70% RAM на узел) + overhead ОС + per-connection buffers ≤ выделенный лимит пода.
- **Диск**: Под `datadir` + binlog + relay log + slow query log. Минимум 20% свободного пространства для дефрагментации и бэкапов.
- **IOPS**: Настройте `requests`/`limits` CPU и memory в YAML с запасом 20–30% на пики нагрузки.

## Практические сценарии

### 1. Установка через Helm

```bash
# Добавление репозитория
helm repo add mysql-operator https://mysql.github.io/mysql-operator/
helm repo update

# Установка с ограничением прав (Namespace-scoped)
helm install mysql-operator mysql-operator/mysql-operator \
  --namespace mysql-operator \
  --create-namespace \
  --set installRouter=true
```

### 2. Развертывание кластера с Anti-Affinity и ресурсами

Пример для Production: использование Anti-Affinity, чтобы узлы базы данных не попадали на один физический хост, и лимитов ресурсов.

```yaml
apiVersion: mysql.oracle.com/v2
kind: InnoDBCluster
metadata:
  name: main-db
  namespace: database
spec:
  instances: 3
  version: "8.4.10"
  secretName: mysql-credentials
  podSpec:
    securityContext:
      runAsUser: 999
      runAsGroup: 999
      fsGroup: 999
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
                - key: "mysql.oracle.com/cluster"
                  operator: In
                  values: ["main-db"]
            topologyKey: "kubernetes.io/hostname"
    resources:
      requests:
        cpu: "1"
        memory: "2Gi"
      limits:
        cpu: "2"
        memory: "4Gi"
  router:
    instances: 2
    httpServerPort: 8443
  datadirVolumeClaimTemplate:
    storageClassName: local-ssd
    resources:
      requests:
        storage: 50Gi
```

### 3. Горизонтальное и вертикальное масштабирование

**Горизонтальное (изменение кол-ва узлов):**
Просто измените параметр `spec.instances` в манифесте и примените его (`kubectl apply`). Оператор автоматически добавит новый узел, инициирует `Clone Plugin` для копирования данных и введет его в группу.

**Вертикальное (изменение ресурсов):**
Обновите `spec.podSpec.resources`. Оператор будет выполнять **Rolling Update**, поочередно перезапуская узлы (сначала Secondary, затем Primary после перевыборов), минимизируя простой.

### 4. Управление секретами и паролями

Не храните пароли в YAML. Создайте секрет заранее:

```bash
kubectl create secret generic mysql-credentials \
  --from-literal=rootUser=root \
  --from-literal=rootPassword=$(openssl rand -base64 12) \
  --from-literal=rootHost='%'
```

### 5. Валидация кластера

```bash
# Проверка статуса кластера
kubectl get innodbcluster main-db -n database
# → NAME      AGE   INSTANCES   STATUS
# → main-db   10m   3           ONLINE

# Детальный статус (включая топологию Group Replication)
kubectl get innodbcluster main-db -n database -o yaml

# Проверка подов
kubectl get pods -n database -l mysql.oracle.com/cluster=main-db
# → NAME         READY   STATUS
# → main-db-0    2/2     Running
# → main-db-1    2/2     Running
# → main-db-2    2/2     Running
```

**Валидация через MySQL Shell внутри кластера:**

```bash
# Подключение к любому узлу через Router
mysqlsh root@mysql-router.database.svc.cluster.local:6446
# → Внутри shell:
\cluster checkForServerUpgrade
\cluster.status
```

### 6. Мониторинг и наблюдаемость

Оператор предоставляет:
- **Kubernetes Events**: События при создании, обновлении, сбоях и восстановлении узлов.
- **Health Endpoints** (MySQL 8.4 LTS): `/health/live`, `/health/ready`, `/health/leader` для liveness/readiness-проб.
- **CR Status**: Поле `.status.conditions` в `InnoDBCluster` содержит `Ready`, `Synced`, `Progressing`.

**Prometheus-мониторинг (черезmysqld_exporter на каждом узле):**

```yaml
# ServiceMonitor для Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mysql-cluster
  namespace: database
spec:
  selector:
    matchLabels:
      mysql.oracle.com/cluster: main-db
  endpoints:
    - port: metrics
      interval: 15s
```

### 7. Бэкапы

Используйте `MySQLBackup` CR для автоматизации резервного копирования. Рекомендуется:
- Хранить бэкапы на локальных быстрых дисках кластера.
- Сначала выполнять полный бэкап, затем инкрементальные.
- Внешнее копирование бэкапов orchestrirуйте через CronJob, который забирает файлы с узлов кластера.

## Диагностика и устранение неисправностей

### Типовые состояния кластера
- **`ONLINE`**: Кластер полностью исправен.
- **`RECOVERING`**: Узел присоединяется к группе и синхронизирует данные (используется Clone Plugin).
- **`OFFLINE` / `UNREACHABLE`**: Узел недоступен. Проверьте состояние пода и сетевую связность.

### Таблица типовых проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в CrashLoopBackOff** | Неверные права на `datadir` PVC, нехватка памяти, несовместимость версии | Проверьте логи `kubectl logs <pod> -c mysql`, права `fsGroup`, `limits` memory |
| **Кластер не переходит в ONLINE** | Кворум недостигнут, поврежден `datadir`, неверный `server-id` | Проверьте количество готовых подов, логи Group Replication, уникальность `server-id` |
| **Split-Brain** | Потеря кворума (большинства узлов) | Кластер переходит в Read-Only. Восстановите PVC, проверьте логи оператора, при необходимости выполните принудительную инициализацию через MySQL Shell |
| **PVC не освобождается** | Политика `retain` в StorageClass или финализатор оператора не сработал | Удалите PVC вручную после подтверждения, что данные не нужны |
| **Router не направляет трафик** | Под Router не готов, неверные адреса бэкендов | Проверьте `kubectl get pods -l component=router`, логи Router, сервис `mysql-router` |
| **Clone Plugin не запускается** | Недостаточно прав, неверный `clone_admin_donor` | Проверьте пользователя с `CLONE_ADMIN`, сетевую связность между подами |

### Команды отладки

```bash
# Проверка детального статуса кластера
kubectl get innodbcluster main-db -n database -o yaml

# Доступ к встроенному логу ошибок MySQL
kubectl logs main-db-0 -c mysql -n database

# Проверка статуса MySQL Router
kubectl logs -l component=router -n database

# Проверка событий кластера
kubectl get events -n database --sort-by='.lastTimestamp' | grep main-db

# Проверка состояния PVC
kubectl get pvc -n database
```

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Anti-Affinity**: Всегда используйте `podAntiAffinity`, чтобы выход из строя одного гипервизора не убил весь кластер.
2.  **PDB**: Настраивайте `PodDisruptionBudget` для предотвращения одновременного удаления слишком большого количества узлов при обслуживании K8s.
3.  **Бэкапы**: Используйте `MySQLBackup` CR с локальным хранилищем. Оркестрируйте внешнее копирование через CronJob.
4.  **RBAC**: Ограничьте права сервис-аккаунта оператора. Используйте `Role` и `RoleBinding` в namespace, а не `ClusterRole`.
5.  **Network Policy**: Разрешите только необходимые порты между подами MySQL и Router. Запретите доступ из других namespaces.
6.  **Readiness Probe**: Настройте `initialDelaySeconds` с запасом на холодный старт InnoDB (30–60 секунд при большом Buffer Pool).
7.  **Resource Quotas**: Установите `ResourceQuota` в namespace `database`, чтобы предотвратить неконтролируемое потребление ресурсов.
8.  **Версионность**: Фиксируйте версию MySQL в CR (`version: "8.4.10"`), не используйте тег `latest`.

### Краевые случаи (Edge Cases)

- **Имена подов**: Оператор использует StatefulSet, поэтому имена подов (`db-0`, `db-1`) фиксированы. Не пытайтесь менять их вручную.
- **Обновление сертификатов**: Если `tlsUseSelfSigned: true`, оператор сам ротирует сертификаты. При использовании внешних CA следите за сроком их действия в секретах.
- **Очень большой Buffer Pool (>64GB)**: Увеличивайте `innodb_buffer_pool_chunk_size` до 1G для уменьшения времени старта. Убедитесь, что `initialDelaySeconds` readiness-пробы достаточно велик.
- **Высоконагруженные системы (>5000 QPS)**: Уменьшайте `innodb_adaptive_hash_index` до `OFF`, увеличивайте `innodb_read_io_threads` и `innodb_write_io_threads`.
- **Миграция с классической репликации**: Убедитесь, что `server-id` уникален, GTID включен, и все транзакции реплицированы перед переключением на InnoDB Cluster.
- **Потеря кворума при обновлении**: При Rolling Update убедитесь, что `maxUnavailable` в PDB не позволяет остановить больше одного узла одновременно.

### См. также

- **[Обзор MySQL и форков](./overview.md)** — архитектура InnoDB и WAL.
- **[Репликация MySQL: Обзор](./replication/overview.md)** — теоретические основы GTID, Group Replication и Binlog.
- **[Orchestrator: Failover и топология](./orchestrator.md)** — автоматический failover для классической репликации.
- **[Резервное копирование MySQL](./backup_and_recovery/overview.md)** — стратегии бэкапов и восстановления.
- **[Конфигурация MySQL](./configuration.md)** — параметры `my.cnf` для InnoDB Cluster.
- **[Безопасность MySQL](./security.md)** — hardening, TDE, keyring.
- **[StatefulSet: Лучшие практики](../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md)** — специфика работы с stateful-приложениями.
- **[Официальная документация MySQL Operator](https://dev.mysql.com/doc/mysql-operator/en/)**
