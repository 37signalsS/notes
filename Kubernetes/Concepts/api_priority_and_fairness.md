# API Priority and Fairness (APF)

## Определение

**API Priority and Fairness (APF)** — механизм контроля нагрузки на API-сервер Kubernetes, который обеспечивает эшелонирование (throttling) и справедливое распределение ресурсов между запросами разных приоритетов. APF заменил устаревшие флаги `--max-requests-inflight` и `--max-mutating-requests-inflight` и работает стабильно с Kubernetes 1.29+.

Без APF один «шумный» клиент (например, контроллер с ошибкой) может исчерпать всю пропускную способность API-сервера, блокируя запросы от всех остальных компонентов (kubelet, scheduler, другие контроллеры).

---

## Архитектура

### Компоненты APF

```
API-сервер
├── Authentication (кто?)
├── Authorization (что можно?)
├── APF (какой приоритет и сколько ресурсов?)
│   ├── FlowSchema (какие запросы к какому уровню?)
│   └── PriorityLevelConfiguration (сколько ресурсов?)
├── Admission Control (валидация/мутирование)
└── etcd
```

### Два ключевых ресурса

1. **FlowSchema** — определяет, какие запросы относятся к какому уровню приоритета (по аналогии с «сигналом на светофоре»)
2. **PriorityLevelConfiguration** — определяет, сколько ресурсов выделяется каждому уровню приоритета (по аналогии с «ширины полосы для каждого сигнала»)

---

## FlowSchema

FlowSchema определяет **matching** (сопоставление) входящих запросов с уровнями приоритета. Каждый запрос API-сервера проверяется против FlowSchema **сверху вниз** — первый совпавший определяет уровень приоритета.

### Структура манифеста

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: my-app-schema
spec:
  matchingPrecedence: 1000        # Чем меньше число, тем выше приоритет matching
  priorityLevelConfiguration:
    name: my-app-level            # Ссылка на PriorityLevelConfiguration
  rules:
  - subjects:
    - kind: User
      name: "app-controller"
    - kind: ServiceAccount
      name: "my-app-sa"
      namespace: "production"
    resourceRules:
    - verbs: ["get", "list", "watch"]
      apiGroups: [""]
      resources: ["pods", "services"]
      namespaces: ["production"]
      clusterScope: false
```

### Поля FlowSchema

| Поле | Описание |
|:---|:---|
| `matchingPrecedence` | Число от 1 до 1000000000. Чем меньше — тем выше приоритет matching. При совпадении нескольких FlowSchema используется тот, у которого меньшее `matchingPrecedence` |
| `rules[].subjects` | Кто: User, Group, ServiceAccount |
| `rules[].resourceRules` | Что: verbs, apiGroups, resources, namespaces, clusterScope |
| `rules[].nonResourceRules` | Non-resource URLs (например, `/healthz`, `/metrics`) |
| `distinguisherMethod.type` | Как разделять запросы внутри уровня: `ByUser` (по умолчанию) или `ByNamespace` |

### Порядок matching

```
Входящий запрос
    ↓
FlowSchema #1 (matchingPrecedence: 100) — не совпал
    ↓
FlowSchema #2 (matchingPrecedence: 500) — совпал!
    ↓
Запрос отнесён к PriorityLevel из FlowSchema #2
    ↓
Если ни одна FlowSchema не совпала → используется "catch-all" схема
```

---

## PriorityLevelConfiguration

Определяет количество ресурсов (concurrency shares) и политику очереди для уровня приоритета.

### Структура манифеста

```yaml
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: my-app-level
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 30    # Доля от общей пропускной способности
    limitResponse:
      type: Queue                    # Очередь при превышении лимита
      queuing:
        queues: 16                   # Количество очередей (для fairness)
        handSize: 4                  # Размер «на руки» для shuffled sharding
        queueLengthLimit: 50         # Максимальный размер очереди
```

### Поля PriorityLevelConfiguration

| Поле | Описание |
|:---|:---|
| `type` | `Limited` (ограниченный) или `Exempt` (неограниченный, для системных компонентов) |
| `nominalConcurrencyShares` | Весовая доля от общего количества concurrency. Сумма всех shares = denominator. Значение по умолчанию 30意味着 этот уровень получает 30/(30+другие) от общей пропускной способности |
| `limitResponse.type` | `Queue` (очередь при превышении) или `Reject` (отклонение при превышении) |
| `limitResponse.queuing.queues` | Количество очередей (1-256). Больше очередей = лучше fairness, но больше overhead |
| `limitResponse.queuing.handSize` | Размер «порции» для алгоритма shuffled sharding (1-128) |
| `limitResponse.queuing.queueLengthLimit` | Максимальный размер очереди. Запросы сверх лимита отклоняются |

### Типы PriorityLevelConfiguration

| Тип | Описание | Использование |
|:---|:---|:---|
| **Exempt** | Неограниченный доступ, запросы не в очереди | Системные компоненты (kubelet, scheduler) |
| **Limited** | Ограниченная пропускная способность + очередь | Пользовательские приложения, контроллеры |

---

## Алгоритм справедливости (Fairness)

APF использует алгоритм **shuffled sharding** для обеспечения справедливого распределения ресурсов внутри уровня приоритета:

### Как это работает

1. Каждый запрос хешируется (по user, namespace или другой distinguisher)
2. Хеш определяет, в какие «карманы» (queues) попадает запрос
3. Запрос обслуживается из наименее загруженного «кармана»
4. Если все «карманы» полны — запрос отклоняется или ставится в очередь

### Преимущества

- **Справедливость**: Ни один клиент не может забрать все ресурсы внутри уровня
- **Предсказуемость**: Каждый клиент получает гарантированную долю
- **Отсутствие starvation**: Даже при высокой нагрузке все клиенты получают обслуживание

---

## Встроенные FlowSchema и PriorityLevelConfiguration

Kubernetes создаёт набор системных FlowSchema и PriorityLevelConfiguration по умолчанию:

### Системные PriorityLevelConfiguration

| Имя | Тип | Shares | Назначение |
|:---|:---|:---|:---|
| `system-critical` | Exempt | ∞ | Критические компоненты Control Plane |
| `leader-election` | Limited | 10 | Leader election для контроллеров |
| `node-high` | Limited | 40 | Kubelet, kube-proxy |
| `system` | Limited | 30 | Системные сервисы |
| `user-readonly` | Limited | 100 | Read-only запросы пользователей |
| `user-high` | Limited | 40 | Высокоприоритетные пользовательские запросы |
| `user-low` | Limited | 20 | Низкоприоритетные пользовательские запросы |
| `catch-all` | Limited | 10 | Все остальные запросы |

### Системные FlowSchema (упрощённо)

| Имя | matchingPrecedence | PriorityLevel |
|:---|:---|:---|
| `catch-all` | 1000000 | `catch-all` |
| `endpoints-traffic` | 9900 | `user-readonly` |
| `service-accounts` | 9000 | `system` |
| `kube-*` | 500-2000 | `system-critical`, `leader-election`, `node-high` |

---

## Замена устаревших флагов

APF заменил два флага API-сервера:

| Флаг | Замена через APF |
|:---|:---|
| `--max-requests-inflight` | `user-readonly` PriorityLevel с `nominalConcurrencyShares` |
| `--max-mutating-requests-inflight` | `user-high` PriorityLevel с `nominalConcurrencyShares` |

При включении APF эти флаги **игнорируются**. Рекомендуется использовать APF вместо флагов для более гибкой настройки.

---

## Практические сценарии

### Просмотр текущих FlowSchema и PriorityLevel

```bash
# Все FlowSchema
kubectl get flowschemas
# → NAME                          MATCHINGPRECEDENCE   PRIORITYLEVEL            AGE
# → catch-all                     1000000              catch-all                30d
# → kube-apiserver-...            200                  system-critical          30d
# → service-accounts-in-...       9000                 system                   30d

# Детали конкретной FlowSchema
kubectl get flowschema catch-all -o yaml

# Все PriorityLevelConfiguration
kubectl get prioritylevelconfigurations
# → NAME              TYPE        NOMIN...   AGE
# → catch-all         Limited     10         30d
# → leader-election   Limited     10         30d
# → node-high         Limited     40         30d
# → system            Limited     30         30d
# → system-critical   Exempt      <none>     30d

# Проверить, какая FlowSchema matчит конкретный запрос
kubectl get flowschemas -o yaml | yq '.items[] | select(.spec.rules != null) | .metadata.name'
```

### Мониторинг APF

```bash
# Количество отклонённых запросов по уровням
kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total

# Количество выполняющихся запросов по уровням
kubectl get --raw /metrics | grep apiserver_flowcontrol_current_executing_requests

# Количество запросов в очереди
kubectl get --raw /metrics | grep apiserver_flowcontrol_current_inqueue_requests

# Время ожидания в очереди (гистограмма)
kubectl get --raw /metrics | grep apiserver_flowcontrol_request_wait_duration_seconds
```

### Создание пользовательской FlowSchema

```yaml
# Ограничить запросы от конкретного ServiceAccount
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: my-background-jobs
spec:
  matchingPrecedence: 8000
  priorityLevelConfiguration:
    name: background-low
  rules:
  - subjects:
    - kind: ServiceAccount
      name: "batch-processor"
      namespace: "jobs"
    resourceRules:
    - verbs: ["*"]
      apiGroups: ["*"]
      resources: ["*"]
      namespaces: ["jobs"]
      clusterScope: false
---
# Уровень приоритета для фоновых задач
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: background-low
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 10
    limitResponse:
      type: Reject
```

### Защита API-сервера от шумного контроллера

```yaml
# Ограничить контроллер, который делает слишком много list/watch
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: noisy-controller
spec:
  matchingPrecedence: 3000
  priorityLevelConfiguration:
    name: throttled
  rules:
  - subjects:
    - kind: ServiceAccount
      name: "noisy-operator"
      namespace: "operators"
    resourceRules:
    - verbs: ["list", "watch"]
      apiGroups: ["*"]
      resources: ["*"]
      clusterScope: true
---
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: PriorityLevelConfiguration
metadata:
  name: throttled
spec:
  type: Limited
  limited:
    nominalConcurrencyShares: 5
    limitResponse:
      type: Queue
      queuing:
        queues: 4
        handSize: 2
        queueLengthLimit: 10
```

---

## Диагностика

### Симптомы проблем с APF

| Симптом | Вероятная причина | Диагностика |
|:---|:---|:---|
| `429 Too Many Requests` | Запрос отклонён APF | `kubectl get --raw /metrics \| grep rejected_requests` |
| `503 Service Unavailable` | API-сервер перегружен, APF не справляется | Проверить `apiserver_current_inflight_requests` |
| Медленные ответы API | Запросы застряли в очереди APF | Проверить `request_wait_duration_seconds` |
| Контроллер не работает | FlowSchema matчит его запросы на низкий приоритет | Проверить `kubectl get flowschemas -o yaml` |

### Пошаговая диагностика

```bash
# 1. Определить, какие FlowSchema матчат запросы
kubectl get flowschemas -o json | jq -r '.items[] | "\(.metadata.name) -> \(.spec.priorityLevelConfiguration.name)"'

# 2. Проверить количество отклонённых запросов
kubectl get --raw /metrics | grep 'apiserver_flowcontrol_rejected_requests_total{flow_schema="<name>"}'

# 3. Проверить размер очереди
kubectl get --raw /metrics | grep 'apiserver_flowcontrol_current_inqueue_requests{priority_level="<name>"}'

# 4. Проверить время ожидания
kubectl get --raw /metrics | grep 'apiserver_flowcontrol_request_wait_duration_seconds_bucket{priority_level="<name>"}'

# 5. Проверить общую нагрузку на API
kubectl get --raw /metrics | grep 'apiserver_current_inflight_requests'
```

### Prometheus алерты

```yaml
groups:
- name: apf-alerts
  rules:
  - alert: APFHighRejectionRate
    expr: |
      sum(rate(apiserver_flowcontrol_rejected_requests_total[5m])) by (flow_schema)
      / sum(rate(apiserver_flowcontrol_dispatched_requests_total[5m])) by (flow_schema)
      > 0.05
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "APF rejection rate > 5% for {{ $labels.flow_schema }}"

  - alert: APFHighQueueWait
    expr: |
      histogram_quantile(0.99, sum(rate(apiserver_flowcontrol_request_wait_duration_seconds_bucket[5m])) by (le, priority_level))
      > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "APF p99 wait time > 10s for {{ $labels.priority_level }}"
```

---

## Лучшие практики

1. **Не создавайте FlowSchema без необходимости** — каждая FlowSchema добавляет overhead на проверку каждого запроса
2. **Используйте `ByNamespace`** как distinguisher для multi-tenant кластеров — это обеспечивает справедливость между namespace
3. **Не устанавливайте `nominalConcurrencyShares` слишком низко** — запросы будут отклоняться даже при умеренной нагрузке
4. **Мониторьте APF метрики** — особенно `rejected_requests_total` и `request_wait_duration_seconds`
5. **Не полагайтесь на APF как на единственный механизм защиты** — используйте в связке с Network Policies, RBAC и ResourceQuota
6. **Проверяйте FlowSchema после изменений** — убедитесь, что системные запросы попадают в `system-critical` (Exempt)

---

## Дополнительная информация

*   **[Control Plane Architecture](control_plane_architecture.md)** — место APF в pipeline запроса к API
*   **[Multi-tenancy](multi-tenancy.md)** — использование APF для изоляции тенантов
*   **[High Load Preparation](high_load_preparation.md)** — APF как механизм защиты от DDoS
*   **[API Interaction](api_interaction.md)** — жизненный цикл запроса к API-серверу
*   **[Kube API Server Monitoring](../MonitoringLogging/kube_apiserver_monitoring.md)** — метрики и алерты для APF
