# MongoDB Operator (Community) для Kubernetes

**Актуально для:** MongoDB Community Operator 2.x, Kubernetes 1.22+

## Определения

**MongoDB Kubernetes Operator (Community)** — это специализированный контроллер (Operator pattern), предназначенный для автоматизации жизненного цикла MongoDB Community Edition в кластерах Kubernetes. Он преобразует сложные задачи администрирования (развертывание, репликация, failover, обновление) в декларативные операции через Custom Resource Definitions (CRD).

- **Репозиторий:** [github.com/mongodb/mongodb-kubernetes-operator](https://github.com/mongodb/mongodb-kubernetes-operator)
- **Custom Resource Definition (CRD):** Основной ресурс — `MongoDBCommunity`, который описывает желаемое состояние кластера.
- **Цикл сверки (Reconciliation Loop):** Непрерывный процесс, в котором оператор отслеживает изменения в ресурсах `MongoDBCommunity` и манипулирует объектами Kubernetes (StatefulSet, Services, Secrets) для достижения целевого состояния.

### Системные требования и зависимости (Prerequisites)

Перед установкой оператора необходимо обеспечить наличие следующих компонентов:
1.  **cert-manager:** **Обязателен**. Используется для выпуска внутренних сертификатов для mTLS между узлами и вебхуков оператора.
2.  **Kubernetes v1.22+:** Оператор использует современные возможности API.
3.  **StorageClass:** Наличие хранилища с поддержкой `Dynamic Provisioning`. Для производственных сред рекомендуется использование SSD-накопителей с поддержкой блокового уровня (ReadWriteOnce).
4.  **Admission Webhooks:** В кластере должен быть разрешен трафик к API-серверу для валидации манифестов.

## Базовые концепции

### Архитектура и компоненты

Оператор управляет набором стандартных ресурсов Kubernetes, абстрагируя сложность настройки MongoDB:

1.  **StatefulSet:** Гарантирует стабильные имена хостов (напр., `mongo-0.mongo-svc`) и сохранение данных при перезагрузках. Каждый под получает свой PVC через `volumeClaimTemplates`.
2.  **Headless Service:** Необходим для корректной работы DNS-имен внутри Replica Set, что позволяет узлам находить друг друга без балансировщика.
3.  **Secrets:**
    *   `mongodb-keyfile`: Ключ для аутентификации узлов кластера (внутренний протокол репликации).
    *   `user-password`: Хранение паролей пользователей (SCRAM-SHA-256).
    *   `tls-certs`: Сертификаты для защиты трафика (mTLS между узлами и клиентами).
4.  **ConfigMaps:** Хранение сгенерированных конфигурационных файлов `mongod.conf`.
5.  **ServiceAccount, Role, RoleBinding:** Оператор создаёт сервисные аккаунты для управления ресурсами вnamespace.

### Безопасность и аутентификация

Оператор поддерживает несколько режимов аутентификации:
- **SCRAM-SHA-256:** Стандартный режим. Пароли хранятся в Kubernetes Secret.
- **X.509:** Взаимная TLS-аутентификация между клиентами и серверами. Требурует cert-manager или предварительно созданные сертификаты.
- **Keyfile:** Внутренняя аутентификация узлов Replica Set. Оператор генерирует ключ автоматически.

### Хранилище и производительность

- **WiredTiger Cache:** Оператор автоматически устанавливает `storage.wiredTiger.engineConfig.cacheSizeGB` = 50% от лимита RAM пода. Если лимит не задан — используется 50% от запрошенного ресурса.
- **Journal:** Включён по умолчанию. Для高性能 хранилищ можно настроить `storage.journal.commitIntervalMs`.
- **Диски:** Требуются диски с поддержкой `fsync`. На контейнерах (K8s/Docker) всегда задавайте лимит `cacheSizeGB`, иначе MongoDB займёт всю RAM хоста.

### Жизненный цикл ресурсов (Lifecycle)

- **Provisioning:** Оператор создает PVC, запускает поды и автоматически выполняет `rs.initiate()`.
- **Self-healing:** Если под падает, StatefulSet его перезапускает. Если узел становится недоступным, MongoDB выполняет перевыборы, а оператор следит за тем, чтобы новый под корректно вошел в кластер.
- **Vertical Scaling:** При изменении ресурсов (CPU/RAM) оператор выполняет Rolling Update, перезапуская поды по очереди, чтобы сохранить доступность.
- **Upgrade:** При изменении поля `spec.version` оператор выполняет Rolling Update с проверкой совместимости версий внутри Replica Set.

## Практические сценарии

### 1. Установка инфраструктуры и оператора

Сначала необходимо установить `cert-manager` (если не установлен):
```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set installCRDs=true
```

Затем установка самого оператора:
```bash
helm repo add mongodb https://mongodb.github.io/helm-charts
helm install mongodb-operator mongodb/mongodb-community-operator --namespace mongodb --create-namespace
```

**Helm: настройка значений (values.yaml):**
```yaml
# values.yaml — кастомизация установки оператора
operator:
  # Ресурсы оператора
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  # Количество реплик оператора (HA)
  replicas: 1
  # Webhook (требуется cert-manager)
  webhook:
    enabled: true

# Опционально: автоматическое создание namespace
namespace:
  create: true
```

```bash
# Установка с кастомными значениями
helm install mongodb-operator mongodb/mongodb-community-operator \
  --namespace mongodb --create-namespace \
  -f values.yaml

# Обновление оператора
helm repo update
helm upgrade mongodb-operator mongodb/mongodb-community-operator \
  --namespace mongodb -f values.yaml

# Проверка статуса
helm status mongodb-operator -n mongodb
kubectl get pods -n mongodb -l app.kubernetes.io/name=mongodb-community-operator
```

**Helm: проверка доступных версий и конфигурации:**
```bash
# Список доступных версий чарта
helm search repo mongodb/mongodb-community-operator --versions

# Текущие значения (rendered)
helm get values mongodb-operator -n mongodb

# Все значения по умолчанию
helm show values mongodb/mongodb-community-operator
```

> **Важно:** версия чарта Helm и версия оператора (CRD) должны совпадать с версией MongoDB, которую вы разворачиваете. Проверяйте [MongoDB Enterprise Kubernetes Operator Compatibility](https://www.mongodb.com/docs/kubernetes-operator/current/reference/operator-compatibility/).

### 2. Развертывание отказоустойчивой Replica Set (v8.0)

Манифест ниже создает кластер из 3 узлов с включенной авторизацией.

```yaml
apiVersion: mongodbcommunity.mongodb.com/v1
kind: MongoDBCommunity
metadata:
  name: prod-mongodb
  namespace: mongodb
spec:
  members: 3
  type: ReplicaSet
  version: "8.0.0"
  security:
    authentication:
      modes: ["SCRAM"]
  users:
    - name: admin-user
      db: admin
      passwordSecretRef:
        name: mongo-admin-password # Предварительно создать: kubectl create secret generic mongo-admin-password --from-literal=password='your-secure-pwd'
      roles:
        - name: root
          db: admin
  statefulSet:
    spec:
      template:
        spec:
          # Рекомендуется разносить узлы по разным физическим нодам
          affinity:
            podAntiAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                - labelSelector:
                    matchExpressions:
                      - key: app
                        operator: In
                        values:
                          - prod-mongodb-svc
                  topologyKey: "kubernetes.io/hostname"
      volumeClaimTemplates:
        - metadata:
            name: data-volume
          spec:
            accessModes: [ "ReadWriteOnce" ]
            storageClassName: "standard" # Укажите ваш StorageClass
            resources:
              requests:
                storage: 50Gi
```

### 3. Тонкая настройка и оптимизация

Параметры передаются через `additionalMongodConfig`. Это позволяет адаптировать БД под нагрузку без ручного редактирования файлов.

```yaml
spec:
  additionalMongodConfig:
    storage.wiredTiger.engineConfig.cacheSizeGB: 1.0
    operationProfiling.mode: slowOp
    operationProfiling.slowOpThresholdMs: 200
    net.compression.compressors: zstd
    replication.oplogSizeMB: 2048
```

### 4. Мониторинг и метрики

Для мониторинга MongoDB в Kubernetes используйте Prometheus Exporter как боковой контейнер (sidecar) или DaemonSet.

**Sidecar пример:**
```yaml
spec:
  statefulSet:
    spec:
      template:
        spec:
          containers:
          - name: mongodb-exporter
            image: bitnami/mongodb-exporter:0.23.0
            ports:
            - containerPort: 9216
            env:
            - name: MONGODB_URI
              value: "mongodb://admin-user:$(PASS)@localhost:27017/admin?authSource=admin"
            envFrom:
            - secretRef:
                name: mongo-admin-password
```

**Ключевые метрики:**
- `mongodb_oplog_window` — размер oplog в секундах
- `mongodb_rs_members_state` — состояние узлов (1=PRIMARY, 2=SECONDARY, etc.)
- `mongodb_rs_optime_lag` — задержка репликации в секундах
- `mongodb_connections_current` — текущие соединения

### 5. Обновление версии MongoDB

При изменении `spec.version` оператор выполняет Rolling Update.

```yaml
spec:
  version: "8.0.1"
```

**Валидация:**
```bash
# Отслеживание прогресса
kubectl rollout status statefulset/prod-mongodb -n mongodb
# → statefulset rolling update complete

# Проверка версии
kubectl exec -it prod-mongodb-0 -n mongodb -- mongosh --eval "db.version()"
# → 8.0.1

# Проверка статуса репликации
kubectl exec -it prod-mongodb-0 -n mongodb -- mongosh --eval "rs.status()"
# → Все члены в состоянии PRIMARY/SECONDARY, version: 1
```

### 6. Вертикальное масштабирование (Vertical Scaling)

```yaml
spec:
  statefulSet:
    spec:
      template:
        spec:
          containers:
          - name: mongodb
            resources:
              requests:
                cpu: "2"
                memory: "4Gi"
              limits:
                cpu: "4"
                memory: "8Gi"
```

**Валидация:**
```bash
kubectl rollout status statefulset/prod-mongodb -n mongodb
kubectl get pods -n mongodb -l app=prod-mongodb-svc -o wide
# → MEMORY limits обновлены, поды перезапущены по очереди
```

### 7. Резервное копирование и восстановление

В Community версии оператора бэкапы требуют настройки внешнего решения (например, Velero или кастомных CronJobs с `mongodump`).

**Вариант A: CronJob с mongodump (логический бэкап):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mongodb-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: mongodb:8.0
            command:
            - /bin/sh
            - -c
            - "mongodump --uri=\"mongodb://admin-user:$(PASS)@prod-mongodb-svc:27017/admin?authSource=admin\" --archive=/backup/mongo-$(date +%F).gz --gzip"
            env:
            - name: PASS
              valueFrom:
                secretKeyRef:
                  name: mongo-admin-password
                  key: password
            volumeMounts:
            - name: backup-storage
              mountPath: /backup
          volumes:
          - name: backup-storage
            persistentVolumeClaim:
              claimName: mongo-backup-pvc
          restartPolicy: OnFailure
```

**Вариант B: Velero (физический бэкап PVC + K8s-ресурсов):**

Velero делает снапшот PVC (физический уровень) и сохраняет K8s-ресурсы (StatefulSet, Secrets, CRD MongoDBCommunity). Это быстрее `mongodump` для больших БД, но требует StorageClass с поддержкой снапшотов (CSI).

```bash
# Установка Velero (пример для AWS)
velero install \
  --provider aws \
  --bucket mongo-backups \
  --backup-location-config region=us-east-1 \
  --snapshot-location-config region=us-east-1 \
  --plugins velero/velero-plugin-for-aws:v1.8 \
  --use-volume-snapshots=true

# Бэкап MongoDB (PVC + K8s-ресурсы)
velero backup create mongodb-backup-$(date +%F) \
  --include-namespaces mongodb \
  --snapshot-volumes

# Список бэкапов
velero backup get

# Восстановление в новый namespace
velero restore create mongodb-restore \
  --from-backup mongodb-backup-2026-10-04 \
  --namespace-mappings mongodb:mongodb-restored
```

> **Важно:** Velero восстанавливает PVC (файлы данных), но для согласованности (application-consistent) остановите запись перед снапшотом (`db.fsyncLock()`) или используйте Percona Backup for MongoDB (PBM) для PITR. См. **[Бэкап и DR](./mongodb-backup-dr.md)** и **[Velero](../../Kubernetes/ToolsUtilities/velero-overview.md)**.

**Сравнение подходов:**

| Метод | Уровень | RPO | RTO | Когда |
| :--- | :--- | :--- | :--- | :--- |
| CronJob + mongodump | Логический | Минуты | Долго | Малые БД, точечное восстановление |
| Velero (PVC snapshot) | Физический | Минуты | Быстро | Большие БД, восстановление кластера |
| PBM | Физический + oplog | Секунды | Средне | Production, PITR |

**Валидация:**
```bash
# Запуск вручную (CronJob)
kubectl create job --from=cronjob/mongodb-backup manual-backup -n mongodb
kubectl logs job/manual-backup -n mongodb
# → output shows dump progress

# Проверка файла бэкапа
kubectl exec -it mongo-backup-pvc -- ls -la /backup
# → mongo-2026-09-30.gz

# Проверка Velero бэкапа
velero backup describe mongodb-backup-2026-10-04
```

## Диагностика и решение проблем (Troubleshooting)

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pending Pods** | Нехватка ресурсов или сбой PVC. | `kubectl describe pod <name>` | Проверьте квоты и наличие свободного места в StorageClass. |
| **Webhooks Error** | cert-manager не готов или заблокирован порт 9443. | `kubectl logs deployment/mongodb-operator` | Перезагрузите оператор, проверьте `MutatingWebhookConfiguration`. |
| **Replica Not Sync** | Проблемы с сетевой связностью. | `kubectl exec -it <pod> -- mongosh` | Выполните `rs.status()` внутри БД. Проверьте Headless Service. |
| **OOM Kill** | Не настроен лимит кэша WiredTiger. | `kubectl get pod <name> -o yaml` | Убедитесь, что `cacheSizeGB` установлен в 50% от лимита RAM. |
| **CrashLoopBackOff** | Неверная конфигурация `mongod.conf` или нехватка файловых дескрипторов. | `kubectl logs <pod>` | Проверьте `ulimit -n` (должен быть ≥ 64000). Проверьте `additionalMongodConfig` на ошибки YAML. |
| **Stale Config** | Устаревший routing table на mongos или шарде. | Логи `mongos`: `StaleConfig error` | Автоматически исправляется retry. При устойчивых ошибках перезапустите mongos. |
| **PVC Pending** | StorageClass не поддерживает динамическое provisioning или исчерпаны квоты. | `kubectl get pvc`, `kubectl describe pvc <name>` | Проверьте наличие StorageClass и свободных ресурсов в PV-пуле. |
| **PodAntiAffinity Conflict** | Недостаточно узлов для размещения всех подов с anti-affinity. | `kubectl describe pod <pod>` | Уменьшите количество членов или уберите anti-affinity для dev-сред. |

### Полезные команды
- **Просмотр состояния кластера:** `kubectl get mongodbcommunity prod-mongodb -o yaml`
- **Логи оператора:** `kubectl logs -l app.kubernetes.io/name=mongodb-community-operator`
- **Проверка статуса репликации:**
  ```bash
  kubectl exec -it prod-mongodb-0 -- mongosh --eval "rs.status()"
  ```
- **Доступ к mongosh внутри пода:**
  ```bash
  kubectl exec -it prod-mongodb-0 -n mongodb -- mongosh -u admin-user -p --authenticationDatabase admin
  ```
- **Просмотр событий кластера:**
  ```bash
  kubectl describe mongodbcommunity prod-mongodb -n mongodb
  ```

## Команды администрирования (Reference)

| Команда / Действие | Описание |
| :--- | :--- |
| `kubectl get mongodbcommunity` | Список всех кластеров MongoDB, управляемых оператором. |
| `kubectl describe mongodbcommunity <name>` | Детали кластера: статус, сообщения, события. |
| `kubectl logs -l app.kubernetes.io/name=mongodb-community-operator` | Логи оператора для диагностики. |
| `kubectl rollout status statefulset/<name>` | Статус Rolling Update (обновление версии или ресурсов). |
| `kubectl scale mongodbcommunity/<name> --replicas=N` | Масштабирование количества членов Replica Set. |
| `kubectl delete mongodbcommunity/<name>` | Удаление кластера (с финализаторами очистки). |
| `kubectl get pods -l app=<name>-svc` | Поды конкретного кластера. |
| `kubectl get pvc -l app=<name>-svc` | PVC кластера. |
| `kubectl exec -it <pod> -- mongosh` | Подключение к mongosh внутри пода. |

## Лучшие практики (Best Practices)

### Проектирование кластера
- **Pod Anti-Affinity:** Используйте `podAntiAffinity` с `topologyKey: kubernetes.io/hostname` для распределения подов по разным физическим узлам. Это повышает отказоустойчивость.
- **Resource Limits:** Всегда задавайте `requests` и `limits` для CPU и памяти. Без лимитов WiredTiger может использовать всю RAM хоста.
- **StorageClass:** Используйте StorageClass с поддержкой `fsGroup` и `ReadWriteOnce`. Для production предпочитайте SSD-накопители с высоким IOPS.
- **Secrets Management:** Пароли храните в Kubernetes Secrets. Для production используйте внешние KMS (HashiCorp Vault) с External Secrets Operator.

### Операционная стабильность
- **cert-manager:** Убедитесь, что cert-manager запущен и готов перед установкой оператора. Проверяйте статус через `kubectl get pods -n cert-manager`.
- **Мониторинг:** Настройте алерты на `mongodb_rs_optime_lag > 10s` и `mongodb_rs_members_state != 1/2`.
- ** Rolling Update:** Изменяйте `spec.version` только на патч-версии внутри одной мажорной версии (например, 8.0.0 → 8.0.1). Для мажорных обновлений (7.0 → 8.0) тестируйте сначала в staging.
- **Резервное копирование:** Тестируйте восстановление из бэкапа минимум раз в квартал. Храните бэкапы в отдельном namespace или кластере.

### Безопасность
- **Network Policies:** Ограничьте доступ к порту 27017 только namespace приложения. Используйте NetworkPolicy для сегментации.

  **Пример NetworkPolicy (разрешить только приложению):**
  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: mongodb-allow-app
    namespace: mongodb
  spec:
    podSelector:
      matchLabels:
        app: prod-mongodb-svc
    policyTypes:
    - Ingress
    ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: app-production  # только namespace приложения
        podSelector:
          matchLabels:
            app: my-app
      ports:
      - protocol: TCP
        port: 27017
    egress: []  # разрешить весь egress (или ограничить)
  ```

  **Пример: запретить весь ingress по умолчанию (default-deny):**
  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: mongodb-deny-all
    namespace: mongodb
  spec:
    podSelector:
      matchLabels:
        app: prod-mongodb-svc
    policyTypes:
    - Ingress
  ```

  > **Важно:** NetworkPolicy работает только с CNI-плагинами, поддерживающими NetworkPolicy (Calico, Cilium, Weave Net). Проверьте: `kubectl get networkpolicies -n mongodb`.

- **RBAC:** Оператор требует определенных прав. Не расширяйте его ClusterRole без необходимости. Используйте минимальные привилегии.
- **TLS:** Включайте TLS для внутреннего трафика (`spec.security.tls.enabled: true`). Используйте cert-manager для автоматической ротации сертификатов.
- **Аудит:** Включите `auditLog` в `additionalMongodConfig` для отслеживания всех операций доступа.

### Отказоустойчивость
- **Replica Set:** Используйте минимум 3 узла данных (без арбитров). Арбитры не хранят данные и не могут стать Primary.
- **Pod Disruption Budget:** Создайте PDB для обеспечения минимального количества готовых подов при плановых работах:
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: mongodb-pdb
  spec:
    minAvailable: 2
    selector:
      matchLabels:
        app: prod-mongodb-svc
  ```
- **Readiness Probe:** Используйте пользовательскую readiness probe, проверяющую `rs.status()`. Стандартная проверка TCP может считаться успешной, пока узел не готов к приему writes.
- **Backup Strategy:** Комбинируйте логические бэкапы (`mongodump`) с физическими снапшотами (если StorageClass поддерживает).

## Дополнительная информация

### Ограничения Community версии
- Отсутствие Ops Manager (визуальный мониторинг и управление).
- Ручное управление шардированием (нужно создавать несколько объектов `MongoDBCommunity`).
- Упрощенный механизм бэкапов.
- Нет встроенной поддержки Search Index и Vector Search.

### Смотрите также
- **[Обзор MongoDB (SSoT)](./mongodb.md)** — глубокая теория СУБД.
- **[Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)** — основы паттерна.
- **[cert-manager](../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)** — настройка TLS.
- **[Высокая доступность MongoDB](./high_availability.md)** — Replica Set, failover, мониторинг.
- **[Шардирование MongoDB](./mongodb-sharding.md)** — масштабирование, распределение данных.
- **[Администрирование MongoDB](./mongodb-administration.md)** — мониторинг, бэкапы, обновление.
- **[Репликация в MongoDB](./mongodb-replication.md)** — механизмы Replica Set и Oplog.
