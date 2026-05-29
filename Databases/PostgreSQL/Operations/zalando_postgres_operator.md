# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — Kubernetes-оператор с открытым исходным кодом, предназначенный для автоматизации жизненного цикла кластеров PostgreSQL. Он использует Custom Resource Definitions (CRD) для декларативного описания желаемого состояния баз данных.

**Spilo** — Docker-образ от Zalando, объединяющий PostgreSQL и Patroni для обеспечения высокой доступности. Является базовым образом для кластеров, создаваемых оператором.

**Оператор Kubernetes** — специализированный контроллер, расширяющий API Kubernetes для управления сложными stateful-приложениями. Подробнее — **[Kubernetes-операторы](../../../Kubernetes/Concepts/kubernetes_operators.md)**.

## Основные концепции

### Подходы к развертыванию в Kubernetes

| Метод | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Манифесты** | Прямое описание ресурсов (StatefulSet, Service) | Максимальный контроль | Трудоемкость при большом количестве инстансов |
| **Helm Charts** | Шаблонизация через `values.yaml` | Простота установки | Статичность конфигурации после деплоя |
| **Операторы** | Интеллектуальный контроллер внутри кластера | Автоматизация failover, бэкапов и обновлений | Зависимость от реализации оператора |

Подробнее о ручном развертывании через манифесты — **[Zalando Spilo: Манифесты](./zalando_spilo_manifests.md)**.

### Особенности и возможности

Оператор разработан для управления более чем 1500 инстансами в инфраструктуре Zalando, что определяет его фокус на масштабируемость и унификацию.

- **Высокая доступность**: Автоматическая настройка кластеров (Primary + Replicas) с использованием Patroni.
- **Масштабирование**: Изменение количества узлов и объема хранилища "на лету" через правку CRD.
- **Резервное копирование**: Интеграция с S3, GCS или Azure Blob Storage для физических бэкапов и архивации WAL.
- **Управление доступом**: Поддержка командной модели (Teams) и автоматическое создание ролей и баз данных.
- **Пулы соединений**: Встроенная интеграция с PgBouncer.

## Практические сценарии

### Установка оператора через Helm

**Шаг 1: Подключение репозитория**

```bash
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo update
```

**Шаг 2: Установка в выделенный namespace**

```bash
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace
```

### Развертывание кластера PostgreSQL

Для создания кластера используется ресурс типа `postgresql`.

**Пример манифеста `minimal-cluster.yaml`:**

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: my-prod-db
  namespace: database
spec:
  teamId: "infrastructure"
  numberOfInstances: 2
  postgresql:
    version: "15"
  volume:
    size: "10Gi"
    storageClass: "standard"
  users:
    app_admin: [superuser, createdb]
  databases:
    main_app: app_admin
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi
```

**Применение манифеста:**

```bash
kubectl apply -f minimal-cluster.yaml
```

### Установка веб-интерфейса (Postgres Operator UI)

Zalando предоставляет удобный UI для визуального управления и мониторинга кластеров.

```bash
helm install postgres-operator-ui postgres-operator/postgres-operator-ui \
  --namespace postgres-operator \
  --set env.OPERATOR_API_URL=http://postgres-operator.postgres-operator.svc.cluster.local:8080
```

## Дополнительная информация

### Управление пользователями и правами

Оператор позволяет централизованно управлять правами доступа через секцию `users` в манифесте. При изменении списка пользователей оператор автоматически синхронизирует состояние в БД.

### Типовые проблемы

| Проблема | Решение |
| :--- | :--- |
| Ошибки при создании PVC | Проверить наличие и права `storageClass`, указанного в манифесте кластера. |
| Недоступность UI | Убедиться, что `OPERATOR_API_URL` в конфигурации UI указывает на корректный Service оператора. |
| Ограничения по хранилищу | Zalando Operator официально не поддерживает NFS для физических бэкапов, рекомендуется использовать S3-совместимые хранилища. |

### Связанные документы

- **Резервное копирование**: Методы и стратегии — **[Backup and Recovery](../Concepts/backup_and_recovery.md)**.
- **Альтернативный оператор**: Решение от CloudNativePG — **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**.
- **Теория Patroni**: Основы работы кластера — **[High Availability](../Concepts/high_availability.md)**.
- **Kubernetes**: Общие концепции контроллеров — **[Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md)**.
