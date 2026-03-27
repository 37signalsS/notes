# Zalando Postgres Operator

## Определения

**Zalando Postgres Operator** — приложение для Kubernetes, автоматизирующее создание и управление кластерами PostgreSQL через Custom Resource Definitions (CRD).

**Оператор Kubernetes** — контроллер, расширяющий API Kubernetes для автоматизации управления stateful-приложениями. Подробнее — **[Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md)**.

## Основные концепции

### Способы развёртывания в Kubernetes

| Способ | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Манифесты** | Прямое описание ресурсов (Deployment, Service) | Полный контроль | Неудобно для множества однотипных приложений |
| **Helm Charts** | Шаблонизация манифестов через `values.yaml` | Упрощает установку/обновление | Логика управления вне кластера |
| **Операторы** | Приложение в кластере следит за CRD | Автоматизация жизненного цикла, бэкапы, восстановление | Функционал ограничен разработчиком |

### Особенности Zalando Operator

**Цель:** Управление 1500+ кластерами PostgreSQL в Zalando.

**Философия:** Упрощение развёртывания множества однотипных кластеров за счёт сокращения вариативности.

**Ограничения:** Меньше гибкости, чем ручные манифесты, но достаточно для 95% типовых задач.

### Возможности

- **Кластеризация:** Мастер + реплики
- **Доступ:** Сервисы `-master` и `-replica`, внешний доступ через `LoadBalancer`
- **Резервное копирование:**
  - Физическое: base backup + WAL в S3/GCS (NFS не поддерживается)
  - Логическое: SQL-дампы
- **Восстановление и клонирование:** Из бэкапов
- **Standby-кластеры:** Read-only реплики из основного кластера
- **Connection Pooling:** Интеграция с PgBouncer

## Практические сценарии

### Установка оператора

**Шаг 1: Добавление репозиториев**

```bash
helm repo add postgres-operator https://opensource.zalando.com/postgres-operator/charts/postgres-operator
helm repo add postgres-operator-ui https://opensource.zalando.com/postgres-operator/charts/postgres-operator-ui
helm repo update
```

**Шаг 2: Подготовка values.yaml**

```bash
helm show values postgres-operator/postgres-operator > operator-values.yaml
```

**Шаг 3: Конфигурация**

```yaml
# operator-values.yaml

# Логирование в JSON
logging:
  logFormat: json

# Регистрация CRD
enableCrdRegistration: true

# Образ Spilo (PostgreSQL)
configGeneral:
  spilo_docker_image: "registry.opensource.zalan.do/acid/spilo-15:3.2-p1"

configKubernetes:
  cluster_domain: cluster.local
  
  # Anti-affinity для распределения подов по нодам
  enable_pod_anti_affinity: true
  
  # Readiness probe
  readiness_probe_initial_delay_seconds: 5
  readiness_probe_period_seconds: 10
  
  # Следить за всеми неймспейсами
  watched_namespace: '*'
```

**Шаг 4: Установка**

```bash
helm install postgres-operator postgres-operator/postgres-operator \
  --namespace postgres-operator \
  --create-namespace \
  -f operator-values.yaml
```

### Установка UI

**Шаг 1: Подготовка values.yaml**

```bash
helm show values postgres-operator-ui/postgres-operator-ui > ui-values.yaml
```

**Шаг 2: Конфигурация**

```yaml
# ui-values.yaml

image:
  tag: 1.14.0

env:
  - name: "OPERATOR_API_URL"
    value: "http://postgres-operator.postgres-operator.svc.cluster.local:8080"
  - name: "TARGET_NAMESPACE"
    value: "postgres-operator"

ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - host: pg-operator.your.domain
      paths:
        - path: /
          pathType: ImplementationSpecific
```

**Шаг 3: Установка**

```bash
helm install postgres-operator-ui postgres-operator-ui/postgres-operator-ui \
  --namespace postgres-operator \
  -f ui-values.yaml
```

### Пример манифеста кластера

```yaml
# my-cluster.yaml
apiVersion: "postgresql.zalando.com/v1"
kind: postgresql
metadata:
  name: my-first-cluster
  namespace: postgres-operator
spec:
  teamId: "acid"
  volume:
    size: "5Gi"
  numberOfInstances: 2
  users:
    zalando:
      - superuser
      - createdb
  databases:
    mydatabase: zalando
  postgresql:
    version: "15"
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

**Развёртывание:**

```bash
kubectl apply -f my-cluster.yaml
```

## Дополнительная информация

### Управление пользователями

- `enable_admin_role_for_users` в `values.yaml` даёт права администратора по умолчанию
- CRD `postgresql-team` для централизованного управления командами

### Проблемы и решения

| Проблема | Решение |
| :--- | :--- |
| UI нестабилен | Использовать версию `1.14.0` вместо `1.15.0` |
| Нет поддержки NFS для бэкапов | Использовать S3/GCS или другой оператор |
| Ограниченный функционал | Форкнуть оператор или использовать CloudNativePG |

### Связанные документы

- **Бэкапы:** **[Backup and Recovery](../Concepts/backup_and_recovery.md)**
- **Альтернатива:** **[CloudNativePG](./kubernetes_deployment.md)**
- **Операторы:** **[Kubernetes Operators](../../../Kubernetes/Concepts/kubernetes_operators.md)**
