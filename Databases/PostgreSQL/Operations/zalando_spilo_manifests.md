# Zalando Spilo: Развертывание кластера PostgreSQL через манифесты

## Определения

* **Spilo** — Docker-образ от Zalando, объединяющий PostgreSQL, Patroni для обеспечения высокой доступности и инструменты для резервного копирования (WAL-G).
* **Patroni** — шаблонное решение для создания отказоустойчивых кластеров PostgreSQL. Автоматизирует управление ролями (Primary/Replica) и процесс переключения при сбоях (failover). Подробнее — **[High Availability](../Concepts/high_availability.md#patroni-отраслевой-стандарт)**.
* **DCS (Distributed Configuration Store)** — распределенное хранилище конфигурации. В Kubernetes Patroni обычно использует K8s API (Endpoints и ConfigMaps) для хранения состояния кластера и выбора лидера.

## Базовые концепции

### Подход к развертыванию через манифесты

Развертывание через прямые манифесты Kubernetes (StatefulSet, Service, RBAC) обеспечивает максимальный контроль над конфигурацией. Это необходимо, когда возможности **[Zalando Postgres Operator](./zalando_postgres_operator.md)** недостаточны (например, требуется специфический тюнинг системных параметров нод или сложные Sidecar-контейнеры).

### Механизм выбора лидера (Leader Election)

При использовании `DCS_ENABLE_KUBERNETES_API` Patroni взаимодействует с Kubernetes API:
1. **ConfigMaps**: Используются для хранения глобальной конфигурации и истории кластера.
2. **Endpoints**: Используются для реализации Leader Lock. Тот инстанс, который удерживает Endpoint, считается Primary.
3. **RBAC**: Поды должны иметь права на `get`, `patch`, `update` этих ресурсов в своем пространстве имен.

### Управление трафиком

Для разделения трафика на чтение и запись создаются два сервиса:
* **Master Service**: Без селектора. Patroni сам обновляет IP-адрес в связанном объекте Endpoints, указывая на текущего лидера.
* **Replica Service**: С селектором `spilo-role: replica` (добавляется Patroni динамически) или на основе проверки `/replica` в Readiness Probe.

## Практические сценарии

### Настройка прав доступа (RBAC)

Для работы Patroni необходим ServiceAccount с правами на управление ресурсами кластера.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: spilo-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: spilo-role
rules:
- apiGroups: [""]
  resources: ["configmaps", "endpoints", "pods", "services"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: spilo-rb
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: spilo-role
subjects:
- kind: ServiceAccount
  name: spilo-sa
```

### Спецификация StatefulSet

Пример настройки с использованием Spilo 16 и проверками состояния.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: pg-cluster
spec:
  replicas: 3
  serviceName: "pg-cluster-config"
  selector:
    matchLabels:
      spilo-cluster: pg-prod
  template:
    metadata:
      labels:
        spilo-cluster: pg-prod
    spec:
      serviceAccountName: spilo-sa
      terminationGracePeriodSeconds: 60
      containers:
      - name: postgres
        image: "registry.opensource.zalan.do/acid/spilo-16:3.3-p1"
        ports:
        - containerPort: 5432
        - containerPort: 8008 # Patroni API
        env:
          - name: SCOPE
            value: "pg-prod"
          - name: DCS_ENABLE_KUBERNETES_API
            value: "true"
          - name: KUBERNETES_SCOPE_LABEL
            value: "spilo-cluster"
          - name: POD_NAMESPACE
            valueFrom:
              fieldRef:
                fieldPath: metadata.namespace
        # Проверки состояния через API Patroni
        readinessProbe:
          httpGet:
            path: /readiness
            port: 8008
        livenessProbe:
          httpGet:
            path: /liveness
            port: 8008
        # Грациозное завершение для минимизации простоя при Switchover
        lifecycle:
          preStop:
            exec:
              command: ["/usr/bin/python3", "-c", "import requests; requests.post('http://localhost:8008/failover')"]
```

### Настройка сетевых сервисов

```yaml
# Сервис для записи (Master)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod
spec:
  ports:
  - port: 5432
---
# Пустой Endpoint для мастера (обновляется Patroni)
apiVersion: v1
kind: Endpoints
metadata:
  name: pg-prod
subsets: []
---
# Сервис для чтения (Replicas)
apiVersion: v1
kind: Service
metadata:
  name: pg-prod-repl
spec:
  selector:
    spilo-cluster: pg-prod
  ports:
  - port: 5432
```

## Дополнительная информация

### Диагностика кластера

Проверка ролей и отставания реплик выполняется утилитой `patroni_ctl`:

```bash
# Список всех узлов
kubectl exec -it pg-cluster-0 -- patroni_ctl list

# Переключение мастера вручную (Switchover)
kubectl exec -it pg-cluster-0 -- patroni_ctl switchover
```

### Рекомендации по эксплуатации

* **Anti-Affinity**: Всегда используйте `podAntiAffinity`, чтобы поды одной базы не оказались на одной ноде.
* **Ресурсы**: Устанавливайте `requests` и `limits` для RAM одинаковыми, чтобы избежать OOM Killer на мастере.
* **Бэкапы**: Настраивайте WAL-G через переменные окружения `WALG_S3_PREFIX` и секреты с ключами доступа.

### Смотрите также

* **[Отказоустойчивость PostgreSQL](../Concepts/high_availability.md)** — архитектура Patroni.
* **[Zalando Postgres Operator](./zalando_postgres_operator.md)** — автоматизированное управление.
* **[Backup and Recovery](../Concepts/backup_and_recovery.md)** — стратегии восстановления данных.
