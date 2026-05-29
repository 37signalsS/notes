# PostgreSQL в Kubernetes с помощью оператора CloudNativePG

## Определения

**CloudNativePG (CNPG)** — Kubernetes-оператор с открытым исходным кодом для автоматизации управления полным жизненным циклом кластеров PostgreSQL. Официальный проект CNCF (Cloud Native Computing Foundation).

**Kubernetes Operator** — программное расширение контроллера Kubernetes, которое использует Custom Resources для управления сложными приложениями. Инкапсулирует операционные знания администратора базы данных в программный код. Подробнее — **[Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md)**.

**Custom Resource Definition (CRD)** — механизм расширения API Kubernetes. CNPG определяет ресурс `Cluster` для декларативного описания желаемого состояния базы данных.

**GitOps** — методология управления инфраструктурой и приложениями, при которой Git является единственным источником истины для декларативных описаний ресурсов. Подробнее — **[GitOps Overview](../../../GitOps/GitOps_overview.md)**.

## Основные концепции

### Stateful-приложения в Kubernetes

Базы данных относятся к категории stateful-приложений, требующих сохранения состояния (данных) между перезапусками подов. В Kubernetes для таких задач используется контроллер **StatefulSet**, который обеспечивает:

- Стабильные уникальные сетевые идентификаторы.
- Упорядоченное развертывание и масштабирование.
- Сохранение данных через PersistentVolumeClaims (PVC).

Подробнее — **[StatefulSet](../../../Kubernetes/Base/statefulset.md)**.

### Роль оператора в управлении БД

Стандартный `StatefulSet` не обладает знаниями о внутреннем устройстве PostgreSQL. Оператор CloudNativePG дополняет возможности Kubernetes специфичной логикой:

- Настройка и контроль репликации (Streaming Replication).
- Автоматический failover при отказе основного узла.
- Управление резервным копированием и восстановлением на момент времени (PITR).
- Обновление версии PostgreSQL с минимальным простоем.

### Сравнение платформ для размещения БД

#### Преимущества Kubernetes

- **Масштабируемость:** Быстрое создание сотен изолированных инстансов для микросервисной архитектуры.
- **Динамические среды:** Автоматическое развертывание временных баз данных для CI/CD и тестирования.
- **Унификация:** Использование единых инструментов мониторинга, безопасности и доставки (GitOps) для всех компонентов системы.

#### Когда предпочесть виртуальные машины (ВМ)

- **Критическая производительность:** Сверхвысокие требования к IOPS и минимальным задержкам дисковой подсистемы.
- **Огромные объемы данных:** БД размером в десятки терабайт, требующие специфического тюнинга ядра ОС.
- **Сложность:** Отсутствие у команды достаточной экспертизы в администрировании Kubernetes.

### Ключевые возможности CloudNativePG

- **Автоматический failover:** Обнаружение отказа primary-узла и продвижение наиболее актуальной реплики.
- **Декларативное масштабирование:** Увеличение числа реплик или объема диска простым изменением YAML-манифеста.
- **Резервное копирование:** Нативная интеграция с объектными хранилищами (S3, Azure Blob, GCS) через `barman`.
- **Наблюдаемость:** Встроенный экспорт метрик в формате Prometheus и интеграция с Grafana.
- **Connection Pooling:** Встроенная поддержка PgBouncer для эффективного управления соединениями.

> **Примечание:** О сравнении с другими решениями читайте в разделе **[Zalando Postgres Operator](./zalando_postgres_operator.md)**.

## Практические сценарии

### Установка оператора

Оператор устанавливается как стандартное приложение Kubernetes. Рекомендуемый способ — использование Helm-чарта или прямая установка манифеста.

```bash
# Установка через манифест (пример для версии 1.26.0)
kubectl apply -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.26/releases/cnpg-1.26.0.yaml
```

### Развертывание кластера

Конфигурация кластера описывается в ресурсе `Cluster`.

**Пример манифеста `cluster-example.yaml`:**

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cluster-example
spec:
  instances: 3
  
  # Описание хранилища
  storage:
    size: "1Gi"
    storageClass: "standard"

  # Настройка мониторинга
  monitoring:
    enablePodMonitor: true

  # Инициализация первой базы данных
  bootstrap:
    initdb:
      database: app_db
      owner: app_user

  primaryUpdateStrategy: unsupervised
```

### Управление через плагин `kubectl cnpg`

Для удобства эксплуатации рекомендуется установить плагин `cnpg` для `kubectl`.

**Основные команды:**

- `kubectl cnpg status cluster-example` — детальный статус кластера и репликации.
- `kubectl cnpg psql cluster-example` — интерактивное подключение к primary-узлу.
- `kubectl cnpg promote cluster-example <pod-name>` — ручное переключение на указанную реплику.
- `kubectl cnpg hibernate cluster-example` — временная остановка кластера с сохранением данных.

### Резервное копирование в S3

CloudNativePG автоматизирует процесс выгрузки WAL-логов и создания базовых бэкапов.

**Конфигурация бэкапа:**

```yaml
spec:
  backup:
    barmanObjectStore:
      destinationPath: "s3://backups-bucket/pg-clusters/"
      endpointURL: "https://s3.amazonaws.com"
      s3Credentials:
        accessKeyId:
          name: s3-secret
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: s3-secret
          key: ACCESS_SECRET_KEY
```

Запуск создания бэкапа вручную:

```bash
kubectl cnpg backup cluster-example
```

## Дополнительная информация

### Мониторинг и метрики

При включении `monitoring.enablePodMonitor: true`, оператор автоматически создает ресурс `PodMonitor`, который обнаруживается Prometheus Operator. Метрики включают состояние репликации, размер данных на диске, количество транзакций и другие ключевые показатели. Подробнее — **[Full-Stack Observability для PostgreSQL](./observability.md)**.

### Связанные документы

- **Основы PostgreSQL:** **[PostgreSQL Overview](../overview.md)**
- **Высокая доступность:** **[High Availability](../Concepts/high_availability.md)**
- **Резервное копирование:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Архитектура StatefulSet:** **[StatefulSet](../../../Kubernetes/Base/statefulset.md)**
- **Концепция операторов:** **[Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md)**
