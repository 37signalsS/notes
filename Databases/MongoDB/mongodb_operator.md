# MongoDB Operator (Community) для Kubernetes

## Определения

**MongoDB Kubernetes Operator** — это контроллер, который позволяет автоматизировать управление жизненным циклом MongoDB в кластерах Kubernetes. Он предоставляет декларативный способ развертывания, масштабирования и обслуживания баз данных MongoDB, используя нативные инструменты Kubernetes.

*   **Репозиторий:** [github.com/mongodb/mongodb-kubernetes-operator](https://github.com/mongodb/mongodb-kubernetes-operator)
*   **Назначение:** Упрощение эксплуатации MongoDB Replica Sets и Sharded Clusters в облачных средах.

## Основные возможности

Оператор реализует логику управления данными, специфичную для MongoDB:

*   **Развертывание различных топологий:** Упрощенное создание наборов реплик (Replica Sets) и сегментированных кластеров (Sharded Clusters).
*   **Автоматизация обслуживания:** Обработка обновлений версий, изменений конфигурации и перезапусков.
*   **Резервное копирование и восстановление:** Поддержка автоматических бэкапов для обеспечения сохранности данных.
*   **Мониторинг и оповещение:** Предоставление метрик для мониторинга состояния инстансов MongoDB и оповещение о проблемах.
*   **Безопасность:** Интеграция с [Kubernetes Secrets](../Kubernetes/Base/secrets/secrets_overview.md) для управления учетными данными и TLS-сертификатами.
*   **Масштабирование:** Возможность горизонтального масштабирования (добавление новых реплик или шардов) через изменение манифеста.

## Архитектура и компоненты

### Основные Custom Resources (CR)

| Ресурс | Описание |
| :--- | :--- |
| **MongoDB** | Описание инстанса MongoDB (версия, топология, ресурсы, пользователи). |
| **MongoDBUser** | Управление пользователями и ролями внутри БД. |
| **MongoDBBackup** | Настройка расписания и мест хранения резервных копий. |

### Жизненный цикл управления

Оператор отслеживает изменения в ресурсе `MongoDB` и взаимодействует с API Kubernetes для создания StatefulSets, Services и PersistentVolumeClaims. Он также выполняет команды внутри контейнеров MongoDB (например, `rs.initiate()` или `rs.reconfig()`), чтобы обеспечить консистентность топологии на уровне самой СУБД.

## Практические сценарии

### Пример Replica Set

```yaml
apiVersion: mongodbcommunity.mongodb.com/v1
kind: MongoDBCommunity
metadata:
  name: my-mongodb
spec:
  members: 3
  type: ReplicaSet
  version: "6.0.5"
  security:
    authentication:
      modes: ["SCRAM"]
  users:
    - name: my-user
      db: admin
      passwordSecretRef:
        name: my-user-password
      roles:
        - name: readWrite
          db: my-database
      scramCredentialsSecretName: my-scram
  additionalMongodConfig:
    storage.wiredTiger.engineConfig.cacheSizeGB: 1
```

## Дополнительная информация

*   **[Официальный репозиторий и документация](https://github.com/mongodb/mongodb-kubernetes-operator)**
*   **[MongoDB Overview](./mongodb.md)** — базовые концепции MongoDB.
*   **[Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)** — общая информация о паттерне Оператор.
