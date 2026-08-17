# MongoDB Operator (Community) для Kubernetes

## Определения

**MongoDB Kubernetes Operator (Community)** — это специализированный контроллер (Operator pattern), предназначенный для автоматизации жизненного цикла MongoDB Community Edition в кластерах Kubernetes. Он преобразует сложные задачи администрирования (развертывание, репликация, failover, обновление) в декларативные операции через Custom Resource Definitions (CRD).

- **Репозиторий:** [github.com/mongodb/mongodb-kubernetes-operator](https://github.com/mongodb/mongodb-kubernetes-operator)
- **Custom Resource Definition (CRD):** Основной ресурс — `MongoDBCommunity`, который описывает желаемое состояние кластера.
- **Цикл сверки (Reconciliation Loop):** Непрерывный процесс, в котором оператор отслеживает изменения в ресурсах `MongoDBCommunity` и манипулирует объектами Kubernetes (StatefulSet, Services, Secrets) для достижения целевого состояния.

### Системные требования и зависимости (Prerequisites)

Перед установкой оператора необходимо обеспечить наличие следующих компонентов:
1.  **cert-manager:** **Обязателен**. Используется для выпуска внутренних сертификатов для mTLS между узлами и вебхуков оператора.
2.  **Kubernetes v1.22+:** Оператор использует современные возможности API.
3.  **StorageClass:** Наличие хранилища с поддержкой `Dynamic Provisioning`. Для производственных сред рекомендуется использование SSD (напр., `gp3` в AWS или `ssd` в Yandex Cloud).
4.  **Admission Webhooks:** В кластере должен быть разрешен трафик к API-серверу для валидации манифестов.

## Базовые концепции

### Архитектура и компоненты
Оператор управляет набором стандартных ресурсов Kubernetes, абстрагируя сложность настройки MongoDB:
1.  **StatefulSet:** Гарантирует стабильные имена хостов (напр., `mongo-0.mongo-svc`) и сохранение данных при перезагрузках.
2.  **Headless Service:** Необходим для корректной работы DNS-имен внутри Replica Set, что позволяет узлам находить друг друга.
3.  **Secrets:**
    *   `mongodb-keyfile`: Ключ для аутентификации узлов кластера.
    *   `user-password`: Хранение паролей пользователей (SCRAM).
    *   `tls-certs`: Сертификаты для защиты трафика.
4.  **ConfigMaps:** Хранение сгенерированных конфигурационных файлов `mongod.conf`.

### Жизненный цикл ресурсов (Lifecycle)
- **Provisioning:** Оператор создает PVC, запускает поды и автоматически выполняет `rs.initiate()`.
- **Self-healing:** Если под падает, StatefulSet его перезапускает. Если узел становится недоступным, MongoDB выполняет перевыборы, а оператор следит за тем, чтобы новый под корректно вошел в кластер.
- **Vertical Scaling:** При изменении ресурсов (CPU/RAM) оператор выполняет Rolling Update, перезапуская поды по очереди, чтобы сохранить доступность.

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
    storage.wiredTiger.engineConfig.cacheSizeGB: 1.0 # 50% от лимита RAM пода
    operationProfiling.mode: slowOp
    operationProfiling.slowOpThresholdMs: 200
    net.compression.compressors: zstd
```

### 4. Резервное копирование и восстановление

В Community версии оператора бэкапы требуют настройки внешнего решения (напр., Velero или кастомных CronJobs с `mongodump`).

**Пример автоматизированного бэкапа через CronJob:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mongodb-backup
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
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

## Диагностика и решение проблем (Troubleshooting)

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pending Pods** | Нехватка ресурсов или сбой PVC. | `kubectl describe pod <name>` | Проверьте квоты и наличие свободного места в StorageClass. |
| **Webhooks Error** | cert-manager не готов или заблокирован порт 9443. | `kubectl logs deployment/mongodb-operator` | Перезагрузите оператор, проверьте `MutatingWebhookConfiguration`. |
| **Replica Not Sync** | Проблемы с сетевой связностью. | `kubectl exec -it <pod> -- mongosh` | Выполните `rs.status()` внутри БД. Проверьте Headless Service. |
| **OOM Kill** | Не настроен лимит кэша WiredTiger. | `kubectl get pod <name> -o yaml` | Убедитесь, что `cacheSizeGB` установлен в 50% от лимита RAM. |

### Полезные команды
- **Просмотр состояния кластера:** `kubectl get mongodbcommunity prod-mongodb -o yaml`
- **Логи оператора:** `kubectl logs -l app.kubernetes.io/name=mongodb-community-operator`
- **Проверка статуса репликации:**
  ```bash
  kubectl exec -it prod-mongodb-0 -- mongosh --eval "rs.status()"
  ```

## Дополнительная информация

### Ограничения Community версии
- Отсутствие Ops Manager (визуальный мониторинг и управление).
- Ручное управление шардированием (нужно создавать несколько объектов `MongoDBCommunity`).
- Упрощенный механизм бэкапов.

### Смотрите также
- **[Обзор MongoDB (SSoT)](./mongodb.md)** — глубокая теория СУБД.
- **[Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)** — основы паттерна.
- **[cert-manager](../../Security/cert-manager/overview.md)** — настройка TLS.
