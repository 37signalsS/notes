# MongoDB Operator (Community) для Kubernetes

## Определения

**MongoDB Kubernetes Operator (Community)** — это специализированный контроллер (Operator pattern), предназначенный для автоматизации жизненного цикла MongoDB Community Edition в кластерах Kubernetes. Он позволяет управлять базами данных декларативно, используя нативные ресурсы Kubernetes.

- **Репозиторий:** [github.com/mongodb/mongodb-kubernetes-operator](https://github.com/mongodb/mongodb-kubernetes-operator)
- **Custom Resource Definition (CRD):** Расширения API Kubernetes, которые позволяют описывать кластеры MongoDB как объекты `MongoDBCommunity`.
- **Контроллер:** Процесс, который отслеживает состояние ресурсов `MongoDBCommunity` и приводит текущее состояние кластера к желаемому (Reconciliation Loop).

## Базовые концепции

### Архитектура
Оператор работает в пространстве имен (namespace) и управляет следующими компонентами:
1.  **StatefulSet:** Используется для обеспечения стабильных сетевых идентификаторов и постоянного хранилища для узлов MongoDB.
2.  **Service:** Создает Headless Service для взаимодействия узлов внутри Replica Set и стандартный Service для доступа клиентов.
3.  **Secrets:** Хранение паролей (SCRAM), ключевых файлов (keyFile) и TLS-сертификатов.

### Основные ресурсы (CRD)
| Ресурс | Описание |
| :--- | :--- |
| **`MongoDBCommunity`** | Основной ресурс кластера. Описывает версию СУБД, количество реплик, конфигурацию WiredTiger и ресурсы (CPU/RAM). |
| **`MongoDBUser`** | (Встроено в `MongoDBCommunity`) Управление пользователями и их ролями. |
| **`MongoDBBackup`** | Настройка расписания бэкапов (требует дополнительной конфигурации хранилища). |

### Требования и зависимости (White Spots)
- **cert-manager:** Является **обязательным** предусловием для работы оператора, так как используется для генерации внутренних сертификатов и обеспечения безопасности соединений (TLS/mTLS) между узлами.
- **Admission Webhooks:** Оператор использует вебхуки для валидации манифестов перед их применением.
- **Хранилище (StorageClass):** Для каждого узла требуется Persistent Volume (PV) с поддержкой динамического выделения.

## Практические сценарии

### 1. Установка оператора через Helm
```bash
helm repo add mongodb https://mongodb.github.io/helm-charts
helm repo update
helm install mongodb-operator mongodb/mongodb-community-operator
```

### 2. Развертывание Replica Set (v8.0)
Пример манифеста для создания отказоустойчивого кластера из 3-х узлов.

```yaml
apiVersion: mongodbcommunity.mongodb.com/v1
kind: MongoDBCommunity
metadata:
  name: example-mongodb
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
      passwordSecretRef: # Секрет должен быть создан заранее
        name: mongo-admin-password
      roles:
        - name: root
          db: admin
  statefulSet:
    spec:
      volumeClaimTemplates:
        - metadata:
            name: data-volume
          spec:
            accessModes: [ "ReadWriteOnce" ]
            resources:
              requests:
                storage: 20Gi
```

### 3. Настройка параметров WiredTiger
Через раздел `additionalMongodConfig` можно передавать любые параметры конфигурации `mongod.conf`.
```yaml
spec:
  additionalMongodConfig:
    storage.wiredTiger.engineConfig.cacheSizeGB: 0.5
    net.compression.compressors: zstd
```

### 4. Масштабирование и обновление
- **Масштабирование:** Увеличение поля `members` в манифесте инициирует автоматическое добавление нового пода, его включение в Replica Set (`rs.add()`) и синхронизацию данных.
- **Обновление версии:** Изменение поля `version` запускает **Rolling Update**. Поды перезапускаются по одному, начиная с вторичных узлов (Secondaries), затем Primary уступает роль (Step down) и обновляется последним.

## Дополнительная информация

### Ограничения Community версии
- Не поддерживает продвинутые фичи Enterprise оператора (Ops Manager, сложные политики резервного копирования).
- Шардирование требует более сложной ручной настройки манифестов (создание нескольких `MongoDBCommunity` для шардов и конфиг-серверов).

### Смотрите также
- **[Обзор MongoDB (SSoT)](./mongodb.md)** — глубокая теория СУБД и агрегации.
- **[Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)** — общие принципы работы операторов.
- **[cert-manager](../../Security/cert-manager/overview.md)** — управление TLS-сертификатами в K8s.
