# PostgreSQL в Kubernetes с помощью оператора CloudNativePG

## Определения

**CloudNativePG (CNPG)** — Kubernetes-оператор для автоматизации управления кластерами PostgreSQL. Официальный проект CNCF.

**Kubernetes Operator** — контроллер, расширяющий API Kubernetes для автоматизации управления stateful-приложениями. Инкапсулирует операционные знания администратора БД. Подробнее — **[Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md)**.

**Custom Resource Definition (CRD)** — механизм расширения API Kubernetes. CNPG определяет ресурс `Cluster` для декларативного описания желаемого состояния PostgreSQL.

**GitOps** — подход к управлению инфраструктурой, при котором конфигурация хранится в Git, а операторы приводят состояние кластера в соответствие с репозиторием. Подробнее — **[GitOps Overview](../../../GitOps/GitOps_overview.md)**.

## Основные концепции

### Stateful-приложения в Kubernetes

Базы данных — stateful-приложения, требующие сохранения состояния между перезапусками. Для них непригоден `Deployment`, используется **`StatefulSet`**, обеспечивающий:

- Стабильные уникальные сетевые идентификаторы
- Упорядоченное развертывание и масштабирование
- Сохранение данных через `PersistentVolumeClaim`

Подробнее — **[StatefulSet](../../../Kubernetes/Base/statefulset.md)**.

### Зачем нужен оператор?

`StatefulSet` не умеет выполнять специфичные для БД задачи:

- Настройка и управление репликацией
- Автоматический failover
- Резервное копирование и восстановление
- Обновление версии без простоя

Оператор автоматизирует эти задачи через цикл согласования (reconciliation loop), сравнивая желаемое состояние (CRD) с текущим.

### Когда использовать Kubernetes для БД

#### Сценарии для Kubernetes

- **"Фабрика" БД:** Сотни микросервисов с изолированными базами данных
- **Динамические окружения:** Временные БД для тестирования в CI/CD
- **Унификация:** Единые подходы к мониторингу, логированию, безопасности

#### Сценарии для ВМ

- **Высоконагруженные БД:** Терабайты данных с высокими требованиями к IOPS
- **Предсказуемость производительности:** Эксклюзивный доступ к ресурсам, тюнинг ядра
- **Недостаток экспертизы:** Команда не имеет опыта работы с Kubernetes

**Гибридный подход:** Критические БД на ВМ, вспомогательные и тестовые — в Kubernetes.

### Особенности CloudNativePG

- **Автоматический failover:** Переключение при сбое primary
- **Масштабирование:** Изменение количества реплик и размера дисков через YAML
- **Резервное копирование и PITR:** Интеграция с `barman`, object storage (S3), volume snapshots
- **Мониторинг:** Экспорт метрик в формате Prometheus
- **Обновления:** Управляемые обновления PostgreSQL с минимальным простоем
- **Connection Pooling:** Встроенная поддержка PgBouncer через CRD `Pooler`
- **Декларативное управление:** Пользователи, БД и роли описываются в манифесте

> **Примечание:** Существуют и другие операторы PostgreSQL. Сравнение — **[Zalando Postgres Operator](./zalando_postgres_operator.md)**.

## Практические сценарии

### Установка оператора

Оператор устанавливается в кластер с помощью одного манифеста, регистрирующего CRD и запускающего контроллер.

```bash
# Установка актуальной версии (1.26.0)
kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.26/releases/cnpg-1.26.0.yaml
```

После установки в пространстве имён `cnpg-system` запустится контроллер.

### Создание кластера

Кластер описывается ресурсом `Cluster`.

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

  monitoring:
    enablePodMonitor: true

  bootstrap:
    initdb:
      database: app
      owner: app

  primaryUpdateStrategy: unsupervised
```

После применения (`kubectl apply -f cluster-example.yaml`) оператор создаст:

- `StatefulSet` с 3 подами PostgreSQL
- `PersistentVolumeClaim` для каждого пода
- `Service` для доступа к кластеру

### Сервисы для доступа

Оператор автоматически создаёт три сервиса:

- `<cluster-name>-rw` — указывает на primary (для записи)
- `<cluster-name>-ro` — указывает на все реплики (для чтения)
- `<cluster-name>-r` — указывает на все узлы кластера

### Плагин `kubectl cnpg`

Для управления кластером существует плагин `kubectl cnpg`.

**Просмотр статуса:**

```bash
kubectl cnpg status cluster-example
```

**Подключение через `psql`:**

```bash
# К primary
kubectl cnpg psql cluster-example

# К реплике
kubectl cnpg psql cluster-example --replica
```

**Другие команды:**

- `kubectl cnpg hibernate cluster-example` — остановка подов с сохранением дисков
- `kubectl cnpg fence <pod-name>` — изоляция узла
- `kubectl cnpg promote <pod-name>` — повышение реплики до primary
- `kubectl cnpg destroy <cluster-name>` — удаление кластера

### Автоматический failover

При удалении пода с primary:

```bash
kubectl delete pod cluster-example-1
```

Оператор повысит реплику до primary, Kubernetes пересоздаст под. Сервис `-rw` автоматически переключится на новый primary.

### Резервное копирование и восстановление

CloudNativePG использует `barman` для управления бэкапами, автоматизируя [стратегии резервного копирования](../Concepts/backup_and_recovery.md).

#### Резервное копирование в Object Storage (S3)

**Пример конфигурации:**

```yaml
spec:
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

**Создание бэкапа:**

```bash
kubectl cnpg backup cluster-example --method barmanObjectStore
```

#### Резервное копирование через Volume Snapshots

При поддержке CSI Volume Snapshots:

```yaml
spec:
  backup:
    volumeSnapshot:
      className: <your-volume-snapshot-class>
```

**Создание бэкапа:**

```bash
kubectl cnpg backup cluster-example --method volumeSnapshot
```

#### Восстановление (Recovery)

Восстановление происходит при создании нового кластера с указанием источника в секции `bootstrap.recovery`.

**Пример восстановления из бэкапа:**

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-restored
spec:
  instances: 3

  bootstrap:
    recovery:
      source: "cluster-example"
```

CloudNativePG найдёт последний бэкап от `cluster-example` и инициализирует новый кластер. Для PITR можно указать `recovery_target`.

## Дополнительная информация

### Мониторинг

CloudNativePG интегрируется с Prometheus. При указании `monitoring: { enablePodMonitor: true }` оператор создаст ресурс `PodMonitor` для сбора метрик.

### Связанные документы

- **Мониторинг:** **[Full-Stack Observability для PostgreSQL](./observability.md)**
- **Высокая доступность:** **[High Availability](../Concepts/high_availability.md)**
- **Резервное копирование:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Альтернативный оператор:** **[Zalando Postgres Operator](./zalando_postgres_operator.md)**
- **StatefulSet:** **[StatefulSet](../../../Kubernetes/Base/statefulset.md)**
- **Kubernetes-операторы:** **[Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md)**
