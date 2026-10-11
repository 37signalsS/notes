# Argo CD: Удаление, каскадное удаление и очистка ресурсов

> **Актуальность (2026):** Argo CD v3.x предоставляет три основных механизма управления удалением: Prune (удаление ресурсов, отсутствующих в Git), Cascading Deletion (каскадное удаление зависимых ресурсов через Propagation Policy) и Orphaning (сохранение ресурсов при удалении приложения). Ключевые sync options: `Prune=true`, `PruneLast=true`, `PrunePropagationPolicy=foreground|background|orphan`. Удаление приложения через `argocd app delete` поддерживает флаги `--cascade` и `--no-cascade`.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к кластеру.
3. **Понимание синхронизации** (см. [Synchronization](./synchronization.md)).
4. **Понимание Resource Tracking** (см. [Resource Tracking](./argocd_resource_tracking.md)).

## Определения

**Prune (Обрезка)** — механизм удаления Kubernetes-ресурсов в кластере, которые больше не определены в Git-репозитории. Активируется опцией `Prune=true` в sync options.

**PruneLast (Обрезка в конце)** — опция, при которой удаление старых ресурсов происходит только после успешного применения новых. Гарантирует, что деплой завершится перед очисткой.

**Propagation Policy (Политика распространения)** — определяет порядок удаления dependent-ресурсов (с OwnerReferences) относительно основного ресурса. Три варианта: `foreground`, `background`, `orphan`.

**Foreground Deletion (Переднее удаление)** — dependent-ресурсы удаляются ПЕРЕД основным ресурсом. Гарантирует, что все зависимости будут удалены до завершения операции.

**Background Deletion (Заднее удаление)** — dependent-ресурсы удаляются ПОСЛЕ основного ресурса. Основной ресурс удаляется немедленно, dependent — асинхронно.

**Orphan Deletion (Удаление с осиротением)** — dependent-ресурсы НЕ удаляются, а становятся "осиротевшими" (orphaned). Остаются в кластере без владельца.

**Cascading Deletion (Каскадное удаление)** — удаление ресурса вместе со всеми dependent-ресурсами. Реализуется через Kubernetes Propagation Policy.

**Finalizer (Финализатор)** — строка в `metadata.finalizers`, предотвращающая удаление ресурса до завершения определенной операции. Argo CD использует `resources-finalizer.argocd.argoproj.io`.

**Cleanup (Очистка)** — общий термин для удаления ресурсов, оставшихся после удаления приложения или при несоответствии Git и кластера.

## Базовые концепции

### Механизмы удаления в Argo CD

```text
Приложение удалено из Git
    │
    ▼
┌─────────────────────────────────────────┐
│  Sync с Prune=true                      │
│  Ресурсы в кластере, которых нет в Git  │
│  → Удаляются                            │
└─────────────────────────────────────────┘

Приложение удалено (argocd app delete)
    │
    ▼
┌─────────────────────────────────────────┐
│  --cascade (по умолчанию)               │
│  Все ресурсы приложения → УДАЛЯЮТСЯ     │
│  Dependent-ресурсы → каскадно           │
└─────────────────────────────────────────┘

    или

┌─────────────────────────────────────────┐
│  --no-cascade                           │
│  Ресурсы приложения → ОСТАЮТСЯ          │
│  (orphaned, без владельца)              │
└─────────────────────────────────────────┘
```

### Propagation Policy в Kubernetes

| Policy | Порядок удаления | Использование |
| :--- | :--- | :--- |
| `foreground` | Dependent → Owner | Безопасное удаление с зависимостями (DB, PVC) |
| `background` | Owner → Dependent | Стандартное удаление (по умолчанию в K8s) |
| `orphan` | Owner удаляется, Dependent остаются | Сохранение данных после удаления сервиса |

### Sync Options для удаления

| Опция | Описание | По умолчанию |
| :--- | :--- | :--- |
| `Prune=true` | Удалять ресурсы, отсутствующие в Git | `false` |
| `PruneLast=true` | Удалять после успешного деплоя новых ресурсов | `false` |
| `PrunePropagationPolicy=foreground` | Каскадное удаление dependent перед owner | `foreground` |
| `PrunePropagationPolicy=background` | Каскадное удаление dependent после owner | — |
| `PrunePropagationPolicy=orphan` | Dependent остаются (orphaned) | — |

### Финализаторы Argo CD

```yaml
metadata:
  finalizers:
    - resources-finalizer.argocd.argoproj.io
```

**Поведение:**
- При удалении AppProject/Application финализатор блокирует удаление Kubernetes-объекта.
- Argo CD выполняет cleanup (удаление managed ресурсов) перед снятием финализатора.
- Если cleanup не завершается — финализатор остаётся, ресурс не удаляется.

## Практические сценарии

### Сценарий 1: Prune при синхронизации

Удаление ресурсов, которые были удалены из Git.

**1. Настройка:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  syncPolicy:
    automated:
      prune: true         # Включить удаление отсутствующих ресурсов
      selfHeal: true
    syncOptions:
      - PruneLast=true    # Удалять после деплоя
      - PrunePropagationPolicy=foreground  # Безопасное каскадное удаление
```

**2. Пример:**
```bash
# Удаление ConfigMap из Git
git rm configmap-old.yaml
git commit -m "Remove old configmap"
git push

# Argo CD автоматически:
# 1. Применит новые ресурсы
# 2. Удалит configmap-old из кластера (Prune)
# 3. Удаление произойдет после успешного деплоя (PruneLast)
# 4. Dependent-ресурсы будут удалены перед основными (foreground)
```

### Сценарий 2: Каскадное удаление приложения

Удаление приложения со всеми зависимостями.

**1. Стандартное удаление (каскадное):**
```bash
argocd app delete my-app --cascade
# → Удаляет Application И все managed ресурсы
# → Dependent-ресурсы удаляются каскадно (foreground)
```

**2. Удаление без каскада (orphaning):**
```bash
argocd app delete my-app --no-cascade
# → Удаляет только объект Application
# → Managed ресурсы ОСТАЮТСЯ в кластере (orphaned)
# → Ресурсы потеряют tracking ID
```

**3. Просмотр orphaned ресурсов:**
```bash
# Поиск deployments без tracking ID
kubectl get deployments -A -o json | \
  jq '.items[] | select(.metadata.annotations["argocd.argoproj.io/instance"] == null) | 
  {name: .metadata.name, namespace: .metadata.namespace}'
```

### Сценарий 3: Безопасное удаление namespaces с dependent ресурсами

Удаление namespace, содержащего Deployment, Service, PVC и другое.

**1. Настройка с foreground:**
```yaml
syncOptions:
  - PrunePropagationPolicy=foreground
  - PruneLast=true
```

**2. Порядок удаления:**
```text
1. Argo CD удаляет Dependent-ресурсы:
   ├── Pods
   ├── Services
   ├── ConfigMaps
   ├── Secrets
   └── PVC

2. После удаления всех dependent:
   └── Argo CD удаляет Owner (Deployment/Namespace)

3. Namespace удаляется последним
```

### Сценарий 4: Сохранение данных при удалении сервиса

Orphaning PVC при удалении StatefulSet.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-database
spec:
  syncPolicy:
    automated:
      prune: true
    syncOptions:
      # Не удалять PVC при удалении StatefulSet
      - PrunePropagationPolicy=orphan
```

**Валидация:**
```bash
# Удаление приложения
argocd app delete my-database --cascade

# PVC остаются
kubectl get pvc -n database
# → data-my-database-0   Bound   10Gi   standard   5m
# → data-my-database-1   Bound   10Gi   standard   5m
```

### Сценарий 5: Diagnostics при "застрявшем" удалении

Если удаление не завершается (resource stuck in Terminating).

**1. Проверка финализаторов:**
```bash
kubectl get deployment my-app -o jsonpath='{.metadata.finalizers}'
# → ["resources-finalizer.argocd.argoproj.io"]
```

**2. Проверка dependent-ресурсов:**
```bash
kubectl get deployment my-app -o jsonpath='{.status.conditions}'
# → {"type":"Progressing","status":"False","reason":"ProgressDeadlineExceeded"}
```

**3. Принудительное удаление (если backup выполнен):**
```bash
# Удаление финализатора (опасно!)
kubectl patch deployment my-app -p '{"metadata":{"finalizers":null}}'

# Или через каскадное удаление
kubectl delete deployment my-app --cascade=foreground
```

### Сценарий 6: Prune для CRD и Operator ресурсов

Особенности удаления Custom Resource Definitions.

**Проблема:** При удалении CRD Kubernetes автоматически удалит все Custom Resources этого типа.

**Решение:**
```yaml
syncOptions:
  # Не удалять CRD через Prune (только вручную)
  - RespectIgnoreDifferences=true
  # Или через AppProject
namespaceResourceBlacklist:
  - group: apiextensions.k8s.io
    kind: CustomResourceDefinition
```

### Сценарий 7: Очистка orphaned ресурсов после миграции

После миграции приложения между кластерами.

```bash
# 1. Экспорт orphaned ресурсов
kubectl get deployment -n my-app -o yaml > orphaned-resources.yaml

# 2. Проверка
cat orphaned-resources.yaml | grep "argocd.argoproj.io/instance"
# → Пусто (orphaned)

# 3. Удаление
kubectl delete -f orphaned-resources.yaml

# Или ручное удаление
kubectl delete deployment -n my-app -l app.kubernetes.io/name=my-app
```

## Диагностика

### Базовые команды

```bash
# Проверка sync options приложения
argocd app get my-app -o yaml | grep -A10 "syncPolicy"

# Просмотр Prune статуса
argocd app get my-app -o json | jq '.status.sync'
argocd app get my-app -o json | jq '.status.operationState'

# Поиск orphaned ресурсов
kubectl get all -A -o json | jq '.items[] | select(.metadata.annotations["argocd.argoproj.io/instance"] == null) | {kind: .kind, name: .metadata.name, namespace: .metadata.namespace}'

# Проверка финализаторов
kubectl get deployment my-app -o jsonpath='{.metadata.finalizers}'

# Просмотр событий удаления
kubectl get events -n my-app --field-selector reason=Killing --sort-by='.lastTimestamp'
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `resource is not deleted` | Финализатор блокирует удаление | Проверьте cleanup манифестов |
| `orphaned resources detected` | `Prune=true` не настроен | Включите `prune: true` в syncPolicy |
| `dependent resources not deleted` | Owner deleted before dependent | Используйте `PrunePropagationPolicy=foreground` |
| `PVC remaining after StatefulSet delete` | `PrunePropagationPolicy=orphan` | Ожидаемое поведение для orphaning |

## Лучшие практики

- **Для Production:** Всегда используйте `PruneLast=true` и `PrunePropagationPolicy=foreground`.
- **Для данных (PVC):** Используйте `PrunePropagationPolicy=orphan` чтобы сохранить данные.
- **Для CRD:** Не включайте CRD в Prune — удаляйте вручную после проверки зависимостей.
- **Backup перед удалением:** Экспортируйте ресурсы перед `argocd app delete`.
- **Мониторинг orphaned:** Регулярно проверяйте наличие orphaned ресурсов.

## Ограничения и edge cases

### Ограничения

- **Prune не работает с OwnerReferences:** Dependent-ресурсы удаляются через Kubernetes API, а не через Argo CD.
- **Нет условия "если dependent удалены":** Argo CD не может условно удалять ресурсы на основе статуса dependent.
- **Finalizer cleanup timeout:** Если cleanup не завершается — финализатор остаётся навсегда.

### Edge Cases

- **Удаление AppProject с финализатором:** При удалении проекта Argo CD пытается удалить все приложения. Если хотя бы одно не удаляется — проект остаётся.
- **Concurrent deletion:** При одновременном удалении приложения и синхронизации — возможны конфликты.
- **Namespace deletion с active pods:** Kubernetes ждет завершения всех pods (terminationGracePeriodSeconds).
- **Prune + ApplicationSet:** ApplicationSet не поддерживает `PruneLast=true` для автоматических синхронизаций.

## Дополнительная информация

### См. также

- [Synchronization](./synchronization.md)
- [Resource Tracking](./argocd_resource_tracking.md)
- [Ignore Differences](./synchronization/ignore_differences.md)
- [Auto Sync](./synchronization/scenarios/auto_sync.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Ссылки

- [Deleting Applications](https://argo-cd.readthedocs.io/en/stable/user-guide/app_deletion/)
- [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Orphaned Resources](https://argo-cd.readthedocs.io/en/stable/user-guide/orphaned-resources/)
- [Propagation Policy](https://kubernetes.io/docs/concepts/workloads/controllers/garbage-collection/#propagation-policy)
