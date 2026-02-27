# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — это оператор для Kubernetes, разработанный компанией Zalando, который автоматизирует развертывание и управление кластерами PostgreSQL в Kubernetes.

## Базовые концепции

### Что такое Kubernetes Operator

Operator — это приложение внутри кластера Kubernetes, которое расширяет его API и автоматизирует управление сложными stateful-приложениями. В отличие от Helm, где манифесты обрабатываются на рабочей машине, Operator работает непосредственно в кластере:

1. Пользователь создает манифест с custom resource (например, `kind: Postgres`)
2. Operator отслеживает появление новых ресурсов
3. Operator генерирует стандартные Kubernetes-манифесты (StatefulSet, Service, PVC и др.)
4. Kubernetes развертывает созданные ресурсы

### Особенности Zalando Operator

- Написан под нужды компании Zalando (управление 1000+ кластерами PostgreSQL)
- Ограниченный функционал по сравнению с ручным развертыванием через манифесты
- Подходит для множества однотипных кластеров

### Возможности

- Развертывание кластера PostgreSQL с репликами
- Создание сервисов для доступа к master и replica
- Поддержка LoadBalancer для внешнего доступа
- Резервное копирование в S3/GCS
- Logical backup
- Standby-кластеры (read-only)
- Connection pooling через PgBouncer

## Практические сценарии

### Установка через Helm

```bash
# Добавление репозиториев
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo add postgres-operator-ui https://opensource.zalando.com/postgres-operator/charts/postgres-operator-ui

# Установка оператора
helm install postgres-operator postgres-operator/postgres-operator

# Установка UI
helm install postgres-operator-ui postgres-operator-ui/postgres-operator-ui
```

### Конфигурация через Values

```yaml
configGeneral:
  # Версия оператора
  kubernetes:
    operator_version: "1.10.0"
  
  # Версия PostgreSQL
  postgres:
    docker_image: "postgres:15"

  # Включение логов в JSON
  logging:
    log_format: "json"

  # Включение CRD
  enable_crd_registration: true

configKubernetes:
  # Включение anti-affinity для подов PostgreSQL
  enable_pod_anti_affinity: true
  
  # Включение readiness probes
  enable_readiness_probes: true
  
  # Namespace для отслеживания (* - все)
  watched_namespace: "*"

configConnectionPooler:
  # Включение PgBouncer
  enabled: true
```

### Пример манифеста Postgres

```yaml
apiVersion: postgresql.zalando.com/v1
kind: Postgres
metadata:
  name: my-postgres-cluster
  namespace: postgres-operator
spec:
  teamId: my-team
  volume:
    size: 10Gi
  numberOfInstances: 2
  users:
    admin:
      - superuser
      - createdb
  databases:
    mydb: admin
  resources:
    limits:
      cpu: 500m
      memory: 500Mi
    requests:
      cpu: 100m
      memory: 100Mi
```

## Дополнительная информация

### Ограничения

- Нет встроенной поддержки backup на NFS (только S3/GCS)
- Многие параметры задаются на уровне оператора, а не в манифесте Postgres
- Ограниченная функциональность по сравнению с ручным управлением

### Альтернативы

- **CloudNativePG** — более универсальный оператор PostgreSQL
- **Crunchy Watched PG** — еще один оператор от Crunchy Data
- Ручное развертывание через StatefulSet (максимальная гибкость)
