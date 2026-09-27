# Loki Operator для Kubernetes: альтернатива Helm

## Определения

**Loki Operator (Оператор Loki)** — Kubernetes Operator, управляемый Grafana Labs, для автоматического развертывания и управления кластером Loki в Kubernetes. Автоматизирует создание StatefulSet, Service, ConfigMap и других ресурсов, а также управление жизненным циклом кластера (обновления, масштабирование, откаты).

**LokiStack (CRD)** — Custom Resource Definition, определяющая желаемое состояние кластера Loki. Operator reconciliates текущее состояние кластера с описанным в LokiStack. Поддерживает режимы: SimpleScalable, Distributed.

**LokiStack Gateway (Шлюз LokiStack)** — компонент, предоставляющий unified API для доступа к данным Loki. Обеспечивает аутентификацию, авторизацию и маршрутизацию запросов к Read/Write компонентам.

**Mode (Режим)** — конфигурация режима работы кластера:
- **SimpleScalable:** Все компоненты (Read, Write, Backend) в одном кластере. Подходит для средних нагрузок.
- **Развернутый:** Отдельные компоненты для каждого типа. Подходит для высоких нагрузок.

**Microservices (Микросервисы)** — режим, в котором каждый компонент Loki (Ingester, Querier, Distributor, Compactor и др.) развернут отдельно. Максимальная гибкость, но сложнее управление.

---

## Основные концепции

### Архитектура Loki Operator

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌─────────────┐     ┌─────────────────────────────────┐   │
│  │ LokiStack   │────▶│       Loki Operator             │   │
│  │ (CRD)       │     │  (controller-runtime)           │   │
│  └─────────────┘     └─────────────────┬───────────────┘   │
│                                        │                    │
│                                        ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Loki Cluster                        │   │
│  │                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │   Write     │  │    Read     │  │   Backend   │ │   │
│  │  │ (Ingester)  │  │ (Querier)   │  │ (Compactor) │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │                                                     │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │              Object Storage                  │   │   │
│  │  │              (S3/MinIO/GCS)                  │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Alloy / Promtail                    │   │
│  │              (агенты сбора логов)                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Operator vs Helm

| Критерий | Loki Operator | Helm-чарт |
| :--- | :--- | :--- |
| **Управление жизненным циклом** | Автоматическое (reconcile) | Ручное (helm upgrade) |
| **Обновления** | Rolling update с контролем | Ручное обновление через helm upgrade |
| **Откаты** | Автоматический при ошибке | Ручной (helm rollback) |
| **Конфигурация** | LokiStack CRD (Declarative) | values.yaml (Imperative) |
| **Масштабирование** | Изменение replicas в CRD | Изменение values + helm upgrade |
| **Мониторинг** | Встроенные метрики Operator | Нужны дополнительные дашборды |
| **Сложность** | Выше (нужно знать CRD) | Ниже (простой YAML) |
| **Рекомендация** | Production с высокой нагрузкой | Dev/test, средняя нагрузка |

### Когда использовать Operator

| Сценарий | Рекомендация |
| :--- | :--- |
| Dev/test cluster | Helm (проще) |
| Production с средней нагрузкой | Helm или Operator |
| Production с высокой нагрузкой | Operator (автоматизация) |
| Multi-tenant кластер | Operator (встроенная поддержка) |
| Нужен control plane для Loki | Operator |
| Нет Kubernetes опыта | Helm |

### CRD: LokiStack

```yaml
apiVersion: loki.grafana.com/v1
kind: LokiStack
metadata:
  name: loki
  namespace: logging
spec:
  size: 3medium          # small, 1x-medium, 3x-small, 3medium, 3large
  storage:
    schemas:
      - version: v13
        effectiveDate: "2024-01-01"
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
    type: s3
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
  template:
    compactor:
      replicas: 2
    distributor:
      replicas: 3
    ingester:
      replicas: 3
    querier:
      replicas: 3
    queryFrontend:
      replicas: 2
    gateway:
      replicas: 2
  rulesSelector: {}
  tenants: {}
```

---

## Практические сценарии

### Сценарий 1: Установка Loki Operator

```bash
# 1. Добавление Helm-репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# 2. Установка Loki Operator
helm install loki-operator grafana/loki-operator \
  --namespace logging \
  --create-namespace \
  --set manageRsrcs=true

# 3. Проверка установки
kubectl get pods -n logging -l app.kubernetes.io/name=loki-operator

# 4. Проверка CRD
kubectl get crd | grep loki
# → lokistack.loki.grafana.com
```

**Установка через kustomize (альтернатива):**

```bash
# Установка через kustomize
kubectl apply -k https://github.com/grafana/loki/production/kustomize/loki-operator

# Или локально
git clone https://github.com/grafana/loki.git
cd loki/production/kustomize/loki-operator
kubectl apply -k .
```

### Сценарий 2: Создание LokiStack (SimpleScalable)

```yaml
# loki-stack.yaml
apiVersion: loki.grafana.com/v1
kind: LokiStack
metadata:
  name: loki
  namespace: logging
spec:
  size: 3medium
  storage:
    schemas:
      - version: v13
        effectiveDate: "2024-01-01"
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
    type: s3
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
  template:
    compactor:
      replicas: 2
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 2
          memory: 2Gi
    distributor:
      replicas: 3
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 1
          memory: 1Gi
    ingester:
      replicas: 3
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 1
          memory: 2Gi
    querier:
      replicas: 3
      resources:
        requests:
          cpu: 500m
          memory: 512Mi
        limits:
          cpu: 1
          memory: 1Gi
    queryFrontend:
      replicas: 2
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
    gateway:
      replicas: 2
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
  rulesSelector: {}
```

```bash
# Применение
kubectl apply -f loki-stack.yaml

# Проверка статуса
kubectl get lokistack -n logging
kubectl describe lokistack loki -n logging

# Проверка подов
kubectl get pods -n logging -l app.kubernetes.io/instance=loki
```

### Сценарий 3: Создание LokiStack (Distributed)

```yaml
# loki-stack-distributed.yaml
apiVersion: loki.grafana.com/v1
kind: LokiStack
metadata:
  name: loki
  namespace: logging
spec:
  size: 3x-small
  storage:
    schemas:
      - version: v13
        effectiveDate: "2024-01-01"
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
    type: s3
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
  template:
    distributor:
      replicas: 3
    ingester:
      replicas: 3
    querier:
      replicas: 3
    queryFrontend:
      replicas: 2
    compactor:
      replicas: 2
    ruler:
      replicas: 2
    gateway:
      replicas: 2
```

### Сценарий 4: Обновление LokiStack

```bash
# 1. Измените loki-stack.yaml (увеличьте replicas)
#    ingester: replicas: 3 → 5

# 2. Применение
kubectl apply -f loki-stack.yaml

# 3. Мониторинг обновления
kubectl get lokistack loki -n logging -w
kubectl rollout status statefulset/loki-ingester -n logging

# 4. Откат при ошибке
kubectl rollout undo statefulset/loki-ingester -n logging
```

### Сценарий 5: Удаление LokiStack

```bash
# 1. Удаление LokiStack (УДАЛИТ ВСЕ ДАННЫЕ!)
kubectl delete lokistack loki -n logging

# 2. Проверка удаления
kubectl get lokistack -n logging

# 3. Очистка PVC (опционально)
kubectl delete pvc -n logging -l app.kubernetes.io/instance=loki

# 4. Удаление Operator
helm uninstall loki-operator -n logging
```

### Сценарий 6: Мониторинг Loki Operator

**Ключевые метрики Operator:**

| Метрика | Описание |
| :--- | :--- |
| `loki_operator_reconcile_total` | Количество reconcile операций |
| `loki_operator_reconcile_errors_total` | Количество ошибок reconcile |
| `loki_operator_reconcile_duration_seconds` | Время reconcile операции |

**Прометеус-правила:**

```yaml
groups:
  - name: loki-operator
    rules:
      - alert: LokiOperatorReconcileErrors
        expr: |
          rate(loki_operator_reconcile_errors_total[5m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Loki Operator has reconcile errors"
          description: "Error rate: {{ $value | humanize }}/s"

      - alert: LokiOperatorDown
        expr: |
          up{job="loki-operator"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Loki Operator is down"
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **LokiStack не создается** | Operator не запущен или нет прав | Проверьте pod operator, RBAC permissions |
| **Operator reconcile errors** | Неверная конфигурация CRD | Проверьте `kubectl describe lokistack`, исправьте spec |
| **Components не масштабируются** | Operator не applied changes | Проверьте `kubectl get events`, перезапустите operator |
| **Storage errors** | Неверные credentials для S3 | Проверьте Secret с credentials, policy bucket |
| **Operator OOM** | Слишком много ресурсов | Увеличьте RAM для operator pod |
| **Update stuck** | Operator не может обновить под | Проверьте PDB (PodDisruptionBudget), PVC |
| **CRD conflicts** | Несовместимые версии CRD | Обновите CRD: `kubectl apply -k` |

---

## Дополнительная информация

### Лучшие практики

1. **Начинайте с Helm:** Если нет опыта с Operator, начните с Helm-чарта.
2. **Используйте фиксированные версии:** Не обновляйте Operator/CRD без проверки changelog.
3. **Мониторьте reconcile:** Алерты на `loki_operator_reconcile_errors_total`.
4. **Тестируйте обновления:** Сначала в dev/test, затем в production.
5. **Используйте PDB:** PodDisruptionBudget для безопасности при обновлениях.
6. **Резервные копии CRD:** Храните CRD в Git для восстановления.
7. **Не удаляйте Operator в production:** Только после полного удаления LokiStack.
8. **Версионируйте конфигурацию:** LokiStack spec в Git.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-альтернатива
- [Установка Alloy](./loki_stack_setup/alloy_installation.md) — агент сбора логов
- [Backup и восстановление LGTM](../Kubernetes/Installation/LGTM_Stack/lgtm_backup_disaster_recovery.md) — стратегии бэкапа
