# PostgreSQL в Kubernetes с помощью оператора CloudNativePG

Запуск PostgreSQL в Kubernetes с использованием операторов — это современный подход к созданию отказоустойчивых, масштабируемых и легко управляемых кластеров баз данных. Оператор [CloudNativePG](https://cloudnative-pg.io/) является одним из ведущих решений в этой области.

## 1. Зачем нужен оператор?

При развертывании stateful-приложений, таких как PostgreSQL, в Kubernetes вручную (с помощью `Deployment`, `StatefulSet`, `Service` и `PVC`), администратор сталкивается с множеством сложностей:
*   **Ручное управление жизненным циклом:** Настройка репликации, обработка сбоев мастера, масштабирование, обновление версий — все это требует ручного вмешательства.
*   **Сложность конфигурации:** Необходимо управлять множеством YAML-файлов, ConfigMap'ов и секретов.
*   **Резервное копирование и восстановление:** Требуется отдельная система для создания бэкапов и их восстановления.

**Оператор** — это специальное приложение в Kubernetes, которое автоматизирует управление сложными приложениями. Он вводит новые типы ресурсов (`Custom Resource Definitions` или `CRD`), например, ресурс `Cluster`, и берет на себя всю рутинную работу. Администратору достаточно декларативно описать желаемое состояние кластера в одном YAML-файле.

Другие известные операторы для PostgreSQL:
*   **Zalando Operator:** Один из первых и наиболее известных операторов, основанный на Patroni.
*   **CrunchyData Operator:** Мощный оператор с фокусом на enterprise-возможности.

CloudNativePG выделяется тесной интеграцией с Kubernetes, простотой использования и активным развитием.

## 2. Архитектура и возможности CloudNativePG

CloudNativePG управляет кластером PostgreSQL, автоматически создавая и настраивая все необходимые ресурсы Kubernetes: `StatefulSet`, `Services`, `Pods`, `PVC`, `Secrets` и др.

### Ключевые возможности:
*   **Автоматический Failover:** При сбое ведущего узла (primary) оператор автоматически выбирает наиболее подходящую реплику и повышает ее до новой ведущей.
*   **Масштабирование:** Изменение количества реплик или размеров дисков выполняется изменением одного поля в YAML-файле кластера.
*   **Резервное копирование и PITR:** Встроенная интеграция с `barman` для создания резервных копий в object storage (S3-совместимые хранилища) и восстановления на определенный момент времени (Point-in-Time Recovery). Поддерживаются также бэкапы через снимки томов (`Volume Snapshots`).
*   **Мониторинг:** Автоматический экспорт метрик в формате Prometheus.
*   **Обновления:** Управляемые обновления версии PostgreSQL с минимальным простоем.
*   **Connection Pooling:** Встроенная поддержка `PgBouncer` через отдельный CRD `Pooler`.
*   **Декларативное управление:** Пользователи, базы данных и роли могут быть описаны прямо в манифесте кластера.

## 3. Практическое использование

### Установка оператора
Оператор устанавливается в кластер с помощью одного манифеста, который регистрирует все необходимые CRD и запускает сам контроллер.

```bash
# Установка последней версии (пример для 1.23.0)
kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.23/releases/cnpg-1.23.0.yaml
```

После установки в кластере появится пространство имен `cnpg-system` с работающим контроллером.

### Создание кластера
Кластер описывается с помощью ресурса `Cluster`.

**Пример `cluster-example.yaml`:**
```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-example
spec:
  instances: 3
  
  storage:
    size: "1Gi"
    storageClass: "standard-rwx" # Укажите ваш storage class

  # Включение мониторинга для Prometheus Operator
  monitoring:
    enablePodMonitor: true

  # Настройки начальной инициализации
  bootstrap:
    initdb:
      database: app
      owner: app

  # Стратегия обновления primary-узла
  # 'unsupervised' доверяет Kubernetes, 'switchover' делает это управляемо
  primaryUpdateStrategy: unsupervised 
```

После применения этого манифеста (`kubectl apply -f cluster-example.yaml`) оператор создаст:
*   `StatefulSet` с 3 подами PostgreSQL.
*   `PersistentVolumeClaim` для каждого пода.
*   Несколько `Service` для доступа к кластеру.

### Сервисы (Services) для доступа
Оператор автоматически создает три сервиса для разных сценариев доступа:
*   `<cluster-name>-rw` (read-write): Всегда указывает на **единственный ведущий узел (primary)**. Используется для операций записи.
*   `<cluster-name>-ro` (read-only): Указывает на **все реплики (standby)**. Используется для масштабирования нагрузки на чтение.
*   `<cluster-name>-r` (read): Указывает на **все узлы кластера** (и primary, и standby).

### Плагин `kubectl cnpg`
Для удобного управления кластером существует плагин `kubectl cnpg`.

*   **Просмотр статуса:**
    ```bash
    kubectl cnpg status cluster-example
    ```
    Команда показывает текущий primary, список реплик, их задержку и общее состояние кластера.

*   **Подключение через `psql`:**
    ```bash
    # Подключиться к primary
    kubectl cnpg psql cluster-example

    # Подключиться к одной из реплик
    kubectl cnpg psql cluster-example --replica
    ```

*   **Другие полезные команды:**
    *   `kubectl cnpg hibernate cluster-example`: "Усыпляет" кластер (останавливает поды, сохраняя диски).
    *   `kubectl cnpg fence <pod-name>`: Изолирует узел от кластера для обслуживания.
    *   `kubectl cnpg promote <pod-name>`: Вручную повышает реплику до primary.
    *   `kubectl cnpg destroy <cluster-name>`: Корректно удаляет кластер и все связанные ресурсы.

### Автоматический Failover в действии
Если вручную удалить под, на котором работает primary:
```bash
kubectl delete pod cluster-example-1
```
Оператор обнаружит это, повысит одну из оставшихся реплик (например, `cluster-example-2`) до нового primary, а Kubernetes автоматически пересоздаст удаленный под, который затем подключится к кластеру уже в качестве реплики. Сервис `<cluster-name>-rw` будет автоматически перенаправлен на новый primary, обеспечивая непрерывность операций записи.

## 4. Резервное копирование и восстановление

CloudNativePG использует `barman` для управления бэкапами. Необходимо настроить `backup` секцию в спецификации кластера.

### Резервное копирование в Object Storage (S3)

**Пример конфигурации:**
```yaml
spec:
  # ...
  backup:
    barmanObjectStore:
      destinationPath: "s3://your-bucket/path-to-backups/"
      endpointURL: "https://s3.your-provider.com"
      s3Credentials:
        accessKeyId:
          name: my-s3-credentials
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: my-s3-credentials
          key: ACCESS_SECRET_KEY
```
После этого можно создавать бэкапы вручную или настроить автоматическое резервное копирование по расписанию с помощью ресурса `ScheduledBackup`.

*   **Создание бэкапа вручную:**
    ```bash
    kubectl cnpg backup cluster-example --method barmanObjectStore
    ```

### Резервное копирование через Volume Snapshots

Если ваш Storage Class поддерживает CSI Volume Snapshots, это более быстрый способ создания бэкапов.

**Пример конфигурации:**
```yaml
spec:
  # ...
  backup:
    volumeSnapshot:
      className: <your-volume-snapshot-class>
```
*   **Создание бэкапа вручную:**
    ```bash
    kubectl cnpg backup cluster-example --method volumeSnapshot
    ```

### Восстановление (Recovery)

Восстановление происходит при создании нового кластера, где в секции `bootstrap` указывается источник.

**Пример восстановления из бэкапа:**
```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-restored
spec:
  instances: 3
  # ... (storage, etc) ...

  bootstrap:
    recovery:
      source: "cluster-example" # Имя кластера, с которого был снят бэкап
```
CloudNativePG найдет последний доступный бэкап от `cluster-example` и использует его для инициализации нового кластера. Для Point-in-Time Recovery (PITR) можно дополнительно указать `recovery_target`.

## 5. Мониторинг

CloudNativePG "из коробки" интегрируется с Prometheus. Если в манифесте кластера указать `monitoring: { enablePodMonitor: true }`, оператор создаст ресурс `PodMonitor`, который будет автоматически обнаружен Prometheus Operator'ом.

Это позволяет собирать сотни метрик о состоянии PostgreSQL, включая статистику транзакций, блокировок, использования кэша, задержки репликации и многое другое, без необходимости разворачивать отдельный exporter.

---
См. также:
- [Развертывание PostgreSQL в Docker](./postgresql_in_docker.md)
- [Концепции высокой доступности](./high_availability_concepts.md)
- [Стратегии резервного копирования](./backup_strategies.md)
