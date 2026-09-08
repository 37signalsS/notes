# NetworkPolicy для разных типов Workload

## Определения

**DaemonSet** — ресурс Kubernetes, обеспечивающий запуск копии пода на каждом узле кластера (или на выбранных узлах через `nodeSelector`/`tolerations`). Используется для системных компонентов: CNI-плагины, мониторинг (node_exporter), логирование (Fluentd), прокси (kube-proxy). NetworkPolicy для DaemonSet должен учитывать, что поды работают на ВСЕХ узлах.

**StatefulSet** — ресурс для управления Stateless-приложений с сетевой идентичностью (стабильные DNS-имена вида `<pod-name>.<headless-service>.<namespace>.svc.cluster.local`). Поды имеют стабильные имена (`pod-0`, `pod-1`) и стабильные hostname. NetworkPolicy для StatefulSet часто требует разрешения трафика между репликами.

**Job/CronJob** — ресурсы для эфемерных вычислений. Job создает один или несколько подов для выполнения задачи и завершается. CronJob запускает Job по расписанию. NetworkPolicy для Job/CronJob должен учитывать: короткое время жизни подов, необходимость доступа к внешним ресурсам (API, БД) иephemeralность IP.

**Headless Service** — Service без ClusterIP (`clusterIP: None`), возвращающий список IP-адресов подов напрямую через DNS A-записи. Используется с StatefulSet для обеспечения стабильной сетевой идентичности. NetworkPolicy должен разрешать трафик по hostname, который резолвится в IP конкретного пода.

## Базовые Концепции

### Особенности NetworkPolicy для каждого типа workload

| Тип workload | Ключевые особенности | Типичные проблемы |
| :--- | :--- | :--- |
| **DaemonSet** | Под на каждом узле; нужен доступ к Metrics Server, API | Трафик от monitoring, нужен egress наружу |
| **StatefulSet** | Стабильные имена; трафик между репликами; headless DNS | replication traffic, DNS резолвинг |
| **Job** | Эфемерные поды; besoin внешний доступ (API, БД) | Временные IP, egress к внешним API |
| **CronJob** | Периодический запуск; besoin egress | Интермитентные проблемы с DNS |

### Трафик DaemonSet

```
┌─────────────────────────────────────────────────────┐
│ Узел 1                    │ Узел 2                    │
│ ┌─────────────────────┐   │ ┌─────────────────────┐   │
│ │ DaemonSet Pod       │   │ │ DaemonSet Pod       │   │
│ │ (node_exporter)     │   │ │ (node_exporter)     │   │
│ └─────────┬───────────┘   │ └─────────┬───────────┘   │
│           │               │           │               │
│           ▼               │           ▼               │
│  Metrics Server/         │  Metrics Server/         │
│  Prometheus scraping     │  Prometheus scraping     │
└─────────────────────────────────────────────────────┘
```

### Трафик StatefulSet

```
┌─────────────────────────────────────────────────────┐
│ Namespace: database                                  │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│ │ postgres-0  │←→│ postgres-1  │←→│ postgres-2  │  │
│ │ (primary)   │  │ (replica)   │  │ (replica)   │  │
│ └─────────────┘  └─────────────┘  └─────────────┘  │
│       ↑               ↑               ↑             │
│       └───────────────┴───────────────┘             │
│              replication traffic                     │
└─────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: DaemonSet (node_exporter) + NetworkPolicy

node_exporter работает на каждом узле и должен быть доступен для Prometheus scraping:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape-node-exporter
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: node-exporter
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9100
  # DNS
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

### Сценарий 2: StatefulSet (PostgreSQL) + NetworkPolicy

Полная изоляция с разрешением replication и доступа от приложений:

```yaml
# 1. Default Deny
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: database
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# 2. Разрешить replication между репликами
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-postgres-replication
  namespace: database
spec:
  podSelector:
    matchLabels:
      app: postgresql
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  - protocol: TCP
    port: 5433  # replication port
---
# 3. Разрешить доступ от приложений
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-app-to-db
  namespace: database
spec:
  podSelector:
    matchLabels:
      app: postgresql
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: production
    ports:
    - protocol: TCP
      port: 5432
---
# 4. DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: database
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 3: Job (backup) + NetworkPolicy

Бэкап-задача, подключающаяся к БД и внешнему S3:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backup-job
  namespace: database
spec:
  podSelector:
    matchLabels:
      app: backup
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # PostgreSQL
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: database
      podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  # S3-compatible storage
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 443
```

### Сценарий 4: CronJob (ETL) + NetworkPolicy

Периодическая ETL-задача с доступом к API и БД:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-etl-cronjob
  namespace: data
spec:
  podSelector:
    matchLabels:
      app: etl-processor
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # External API
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 169.254.169.254/32
    ports:
    - protocol: TCP
      port: 443
  # Internal DB
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: database
    ports:
    - protocol: TCP
      port: 5432
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| DaemonSet pod не может подключиться к API | Egress не разрешает порт 6443 | Добавить Egress для API Server |
| StatefulSet реплики не синхронизируются | Ingress не разрешает трафик между pod'ами | Добавить Ingress с `podSelector: {app: postgresql}` |
| Job завершается с ошибкой timeout | Egress DNS не разрешает внешние домены | Добавить Egress для DNS и целевых API |
| CronJob работает интермитентно | DNS-кеш устарел, conntrack race | Установить NodeLocal DNSCache |
| Headless Service не резолвится | Egress DNS не разрешает A-записи | Разрешить DNS + проверить headless Service |

### Рекомендации

| Тип workload | Рекомендация |
| :--- | :--- |
| **DaemonSet** | Всегда разрешайте egress к Metrics Server (порт 4443) и API Server (6443) |
| **StatefulSet** | Разрешайте Ingress/Egress между репликами (podSelector с тем же label) |
| **Job/CronJob** | Используйте `networkPolicySelector` для привязки политики к конкретному Job |
| **Headless Service** | Убедитесь, что DNS-правила разрешают A-записи для headless Service |

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины
* [NetworkPolicy: Логика правил](./rule_logic.md) — аддитивность и И/ИЛИ
* [NetworkPolicy: Практические сценарии](./practical_scenarios.md) — базовые сценарии
