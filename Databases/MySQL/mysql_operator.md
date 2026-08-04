# MySQL Operator для Kubernetes

## Определения

**MySQL Operator for Kubernetes** — это специализированный контроллер (Operator Pattern), автоматизирующий жизненный цикл кластеров MySQL (InnoDB Cluster) в среде Kubernetes. Он преобразует сложные задачи администрирования (репликация, failover, бэкапы) в декларативные операции через Custom Resource Definitions (CRD).

**InnoDB Cluster** — высокодоступное решение MySQL, объединяющее Group Replication, MySQL Router и MySQL Shell. Оператор является официальным инструментом Oracle для управления этой технологией в K8s.

## Базовые концепции

### 1. Архитектура и Custom Resources (CRD)

Оператор расширяет API Kubernetes следующими ресурсами:

*   **`InnoDBCluster`**: Описывает желаемое состояние кластера (количество узлов, версия, ресурсы, топология).
*   **`MySQLRouter`**: Управляет развертыванием прокси-слоя для маршрутизации трафика (Read/Write Split).
*   **`MySQLBackup` / `MySQLRestore`**: Управляет процессом создания резервных копий и восстановления данных.

### 2. Высокая доступность и самовосстановление
Оператор обеспечивает автоматический **Failover**:
1.  **Group Replication** внутри подов обнаруживает сбой мастера.
2.  Выбирается новый лидер (Primary).
3.  **MySQL Router** автоматически перенаправляет трафик на новый Primary.
4.  Оператор перезапускает упавший под и возвращает его в кластер в качестве реплики (Secondary).

### 3. Безопасность
*   **mTLS**: Оператор автоматически генерирует и обновляет сертификаты для шифрования трафика между узлами кластера и роутерами.
*   **Secrets Integration**: Пароли `root` и системных пользователей хранятся в [Kubernetes Secrets](../../Kubernetes/Base/secrets/secrets_overview.md).

## Практические сценарии

### 1. Установка Оператора через Helm

Рекомендуемый способ развертывания в 2026 году.

```bash
# Добавление репозитория
helm repo add mysql-operator https://mysql.github.io/mysql-operator/
helm repo update

# Установка оператора в отдельный namespace
helm install my-operator mysql-operator/mysql-operator \
  --namespace mysql-operator \
  --create-namespace
```

### 2. Развертывание кластера (8.4 LTS)

Пример манифеста для создания отказоустойчивого кластера из 3 узлов.

```yaml
apiVersion: mysql.oracle.com/v2
kind: InnoDBCluster
metadata:
  name: prod-db
spec:
  instances: 3
  # Использование актуальной LTS версии
  version: "8.4.10"
  secretName: mysql-root-password
  tlsUseSelfSigned: true
  router:
    instances: 2
  datadirVolumeClaimTemplate:
    storageClassName: premium-rwo
    accessModes: [ "ReadWriteOnce" ]
    resources:
      requests:
        storage: 100Gi
```

### 3. Настройка бэкапов в S3-хранилище

Оператор поддерживает выгрузку дампов во внешние объектные хранилища.

```yaml
apiVersion: mysql.oracle.com/v2
kind: MySQLBackup
metadata:
  name: daily-backup
spec:
  clusterName: prod-db
  destination:
    s3:
      endpoint: https://s3.yandexcloud.net
      bucket: my-mysql-backups
      credentials: s3-credentials-secret
      config: s3-config-secret
```

### 4. Мониторинг через Prometheus

Для сбора метрик оператор может экспортировать данные в формате Prometheus.

```yaml
spec:
  # Включение экспортера внутри подов InnoDBCluster
  metrics:
    enabled: true
    image: prom/mysqld-exporter:latest
```
*Примечание: После включения необходимо создать `ServiceMonitor` для автоматического обнаружения целей Prometheus Operator.*

## Диагностика и устранение проблем

Основные команды для проверки состояния:

```bash
# Проверка статуса кластера (уровни ONLINE, RECOVERING, OFFLINE)
kubectl get innodbcluster prod-db

# Просмотр событий оператора при ошибках развертывания
kubectl describe innodbcluster prod-db

# Логи контроллера оператора
kubectl logs -n mysql-operator -l app.kubernetes.io/name=mysql-operator
```

## Дополнительная информация

*   **[Официальная документация MySQL Operator](https://dev.mysql.com/doc/mysql-operator/en/)**
*   **[MySQL: Обзор и сравнение форков](./overview.md)** — архитектура InnoDB и Group Replication.
*   **[StatefulSet: Лучшие практики](../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md)** — почему оператор лучше "голых" манифестов.
*   **[Kubernetes Operators](../../Kubernetes/Concepts/kubernetes_operators.md)** — общие принципы работы паттерна.
