# Zalando Postgres Operator

## Определения

* **Zalando Postgres Operator** — Kubernetes-оператор с открытым исходным кодом для автоматизации полного жизненного цикла кластеров PostgreSQL. Использует Custom Resource Definitions (CRD) для декларативного управления базами данных.
* **Spilo** — базовый Docker-образ кластера, объединяющий PostgreSQL и Patroni. Обеспечивает консистентность среды и инструментов управления.
* **Patroni** — шаблонное решение для обеспечения высокой доступности (HA), управляющее процессами выбора лидера и автоматического failover внутри подов Spilo.
* **Postgres Operator UI** — опциональный веб-интерфейс для визуального управления кластерами и мониторинга их состояния.

## Базовые концепции

### Архитектура и компоненты

Оператор работает как контроллер в кластере Kubernetes, отслеживая изменения объектов типа `postgresql`. Основные функции включают:

1. **Высокая доступность (HA)**: Автоматическое развертывание топологии Master-Replica. Patroni внутри подов управляет состоянием, а оператор обеспечивает корректность ресурсов Kubernetes (Services, Endpoints).
2. **Управление томами**: Поддержка динамического выделения PVC и автоматического расширения томов при изменении `size` в манифесте (если StorageClass поддерживает `allowVolumeExpansion`).
3. **Резервное копирование и PITR**: Интеграция с WAL-E/WAL-G для выгрузки WAL-логов и базовых бэкапов в S3-совместимые хранилища.
4. **Мониторинг**: Встроенная поддержка экспорта метрик в формате Prometheus через Sidecar-контейнеры или напрямую из Spilo.

### Сравнение с CloudNativePG (CNPG)

| Характеристика | Zalando Operator | CloudNativePG |
| :--- | :--- | :--- |
| **Управление HA** | Patroni (внутри подов) | Native K8s API (через оператор) |
| **Сложность** | Выше (требует понимания Patroni) | Ниже (нативный K8s подход) |
| **История** | Проверен временем (1500+ инстансов) | Современный, активно развивающийся |
| **Особенности** | Богатый UI, управление командами | Отсутствие внешних зависимостей (etcd) |

## Практические сценарии

### Установка оператора через Helm

```bash
# Подключение репозитория
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo update

# Установка
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace
```

### Развертывание отказоустойчивого кластера

Пример манифеста для создания кластера с PostgreSQL 17 и базовыми настройками ресурсов.

```yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: pg-prod-cluster
  namespace: database
spec:
  teamId: "infrastructure"
  numberOfInstances: 3
  postgresql:
    version: "17"
    parameters:
      shared_buffers: "256MB"
      max_connections: "100"
  volume:
    size: "20Gi"
    storageClass: "gp3"
  # Определение пользователей и их прав
  users:
    api_user: []
    admin_user: [superuser, createdb]
  databases:
    production_db: api_user
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "1"
      memory: 2Gi
```

### Включение логических бэкапов

Оператор может создавать логические бэкапы (dump) по расписанию через CronJob. Для этого в конфигурации оператора (ConfigMap) или через Helm-values необходимо включить:

```yaml
logical_backup_schedule: "30 00 * * *"
logical_backup_docker_image: "postgres:17"
logical_backup_s3_bucket: "my-postgres-backups"
```

## Дополнительная информация

### Диагностика и отладка

При возникновении проблем со синхронизацией кластера проверяйте логи пода оператора:
```bash
kubectl logs -l app.kubernetes.io/name=postgres-operator -n postgres-operator
```
Состояние конкретного кластера можно увидеть в `status` объекта:
```bash
kubectl get postgresql pg-prod-cluster -o yaml
```

### Смотрите также

* **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)** — обзор CloudNativePG.
* **[Zalando Spilo: Манифесты](./zalando_spilo_manifests.md)** — ручное управление без оператора.
* **[High Availability](../Concepts/high_availability.md)** — теория работы Patroni.
