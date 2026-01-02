# PostgreSQL в Kubernetes с помощью оператора CloudNativePG

## 1. Определения

*   **Kubernetes Operator:** "Виртуальный администратор" внутри кластера. Это контроллер, который расширяет API Kubernetes для автоматизации управления жизненным циклом сложных stateful-приложений, таких как PostgreSQL.
*   **Custom Resource Definition (CRD):** Механизм для создания собственных типов ресурсов в Kubernetes. Оператор определяет CRD (например, `kind: Cluster`), чтобы пользователи могли декларативно описывать желаемое состояние приложения.
*   **GitOps:** Подход к управлению инфраструктурой и приложениями, при котором Git является единым источником правды. Вся конфигурация (в виде YAML-манифестов) хранится в Git, а автоматизированные агенты (например, ArgoCD + оператор БД) приводят состояние кластера в соответствие с репозиторием.

## 2. Основные концепции

### Зачем нужен оператор?
При ручном развертывании PostgreSQL в Kubernetes администратору необходимо самостоятельно управлять `StatefulSet`, `PVC`, `Service`, настраивать репликацию, обрабатывать сбои, организовывать бэкапы. Оператор автоматизирует все эти задачи. Он работает в цикле сверки (reconciliation loop): постоянно сравнивает желаемое состояние (описанное в CRD) с текущим и выполняет необходимые действия для устранения расхождений.

### Преимущества и недостатки запуска PostgreSQL в Kubernetes

#### Преимущества
1.  **Автоматизация жизненного цикла:** Автоматический failover, самовосстановление, масштабирование и обновления без простоя.
2.  **Стандартизация и GitOps:** Вся конфигурация кластера описывается как код, версионируется и хранится в Git. Это гарантирует идентичность окружений.
3.  **Унификация экосистемы:** Единые подходы к мониторингу, логированию и резервному копированию для всех приложений в кластере.

#### Недостатки
1.  **Высокий порог входа:** Требует глубоких знаний как в администрировании БД, так и в Kubernetes.
2.  **Сложность отладки:** Множество слоев абстракции (Pod, PVC, Operator) усложняют поиск причин проблем.
3.  **Не для всех сценариев:** Для небольших проектов или команд без DevOps-экспертизы сложность внедрения может перевесить преимущества.

## 3. Практические сценарии с CloudNativePG

CloudNativePG управляет кластером PostgreSQL, автоматически создавая и настраивая все необходимые ресурсы Kubernetes: `StatefulSet`, `Services`, `Pods`, `PVC`, `Secrets` и др.

### Ключевые возможности:
*   **Автоматический Failover:** При сбое ведущего узла (primary) оператор автоматически выполняет переключение, реализуя на практике [концепции высокой доступности](../Concepts/high_availability.md).
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

CloudNativePG использует `barman` для управления бэкапами, автоматизируя многие [стратегии резервного копирования](../Concepts/backup_and_recovery.md), включая создание базовых копий и восстановление на момент времени (Point-in-Time Recovery). Необходимо настроить `backup` секцию в спецификации кластера.

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

## 4. Продвинутые детали

### 4.1. Мониторинг
CloudNativePG "из коробки" интегрируется с Prometheus. Если в манифесте указать `monitoring: { enablePodMonitor: true }`, оператор создаст ресурс `PodMonitor`, который будет автоматически обнаружен Prometheus Operator'ом для сбора сотен метрик о состоянии PostgreSQL.
