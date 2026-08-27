# Argo CD: Методы отслеживания ресурсов (Resource Tracking)

> **Актуальность (2026):** Argo CD v3.x поддерживает три метода отслеживания ресурсов: `label` (метки), `annotation` (аннотации) и `annotation+label` (комбинированный). Метод выбирается параметром `resourceTrackingMethod` в ConfigMap `argocd-cm`. По умолчанию используется `annotation`. Метод отслеживания определяет, как Argo CD идентифицирует ресурсы, управляемые конкретным приложением, и влияет на orphaning, cleanup и multi-cluster миграции.

## Предварительные требования

1. **Argo CD установлен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к кластеру.
3. **Понимание синхронизации** (см. [Synchronization](./synchronization.md)).
4. **Понимание AppProject** (см. [AppProject](./argocd_appproject_deep.md)).

## Определения

**Resource Tracking (Отслеживание ресурсов)** — механизм, с помощью которого Argo CD определяет, какие Kubernetes-ресурсы принадлежат конкретному приложению. Используется для контроля orphaning (осиротевших ресурсов), cleanup (очистки) и каскадного удаления.

**Label (Метка)** — Kubernetes-метка `app.kubernetes.io/instance: <app-name>`, добавляемая ко всем управляемым ресурсам. Метод `label` ищет ресурсы по этой метке.

**Annotation (Аннотация)** — Kubernetes-аннотация `argocd.argoproj.io/instance: <app-name>`, добавляемая ко всем управляемым ресурсам. Метод `annotation` ищет ресурсы по этой аннотации.

**Annotation+Label (Комбинированный)** — метод, который одновременно проверяет наличие аннотации `argocd.argoproj.io/instance` И метки `app.kubernetes.io/instance`. Оба должны совпадать для идентификации ресурса.

**Orphaning (Осиротение)** — ситуация, когда ресурс был управляемым приложением, но приложение было удалено (или переназначено), а ресурс остался в кластере без владельца.

**Tracking ID (Идентификатор отслеживания)** — уникальная строка, формируемая из имени приложения, проекта и (опционально) кластера. Записывается в label/annotation для идентификации.

## Базовые концепции

### Механизм работы Resource Tracking

```text
Приложение: my-app (проект: production)
    │
    ▼
Argo CD добавляет к каждому ресурсу:
    │
    ├─ Метод "label":
    │   labels:
    │     app.kubernetes.io/instance: my-app
    │
    ├─ Метод "annotation":
    │   annotations:
    │     argocd.argoproj.io/instance: my-app
    │
    └─ Метод "annotation+label":
        labels:
          app.kubernetes.io/instance: my-app
        annotations:
          argocd.argoproj.io/instance: my-app
    │
    ▼
При синхронизации Argo CD ищет ресурсы:
    │
    ├─ label:         ищет по app.kubernetes.io/instance
    ├─ annotation:    ищет по argocd.argoproj.io/instance
    └─ annotation+label: ищет по обоим
```

### Три метода отслеживания

| Метод | Ключ идентификации | Где искать | Особенности |
| :--- | :--- | :--- | :--- |
| `label` | `app.kubernetes.io/instance` | labels | Быстрый поиск (index), но конфликтует с другими инструментами |
| `annotation` | `argocd.argoproj.io/instance` | annotations | Нет конфликтов с label, но поиск медленнее (scan) |
| `annotation+label` | Оба ключа | labels + annotations | Максимальная надежность, двойная проверка |

### Настройка метода

```yaml
# argocd-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Доступные значения: label, annotation, annotation+label
  resourceTrackingMethod: "annotation"
```

### Tracking ID и multi-cluster

В multi-cluster сценариях tracking ID расширяется:

```text
Простой случай (один кластер):
  trackingID = "my-app"

Multi-cluster:
  trackingID = "my-app | https://cluster1.example.com"
  (имя приложения + URL кластера через разделитель "|")
```

Это позволяет Argo CD различать ресурсы с одинаковыми именами в разных кластерах.

### Влияние на поведение

| Аспект | label | annotation | annotation+label |
| :--- | :--- | :--- | :--- |
| **Скорость поиска** | Быстрая (indexed) | Медленная (scan) | Медленная (scan) |
| **Конфликты с Helm** | Возможны (Helm также ставит labels) | Нет | Нет |
| **Конфликты с Kustomize** | Возможны | Нет | Нет |
| **Multi-cluster** | Ограничено | Поддерживается | Поддерживается |
| **Orphaning** | Работает | Работает | Работает |

## Практические сценарии

### Сценарий 1: Базовая настройка — annotation (по умолчанию)

Рекомендуемый метод для большинства случаев.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resourceTrackingMethod: "annotation"
```

**Проверка:**
```bash
# Просмотр аннотаций ресурса
kubectl get deployment my-app -o jsonpath='{.metadata.annotations}'
# → {"argocd.argoproj.io/instance": "my-app"}

# Просмотр меток
kubectl get deployment my-app -o jsonpath='{.metadata.labels}'
# → {"app.kubernetes.io/name": "my-app", ...}  (метки от Helm/Kustomize)
```

### Сценарий 2: Конфликт меток с Helm

Helm автоматически ставит `app.kubernetes.io/instance` при установке чарта. Если Argo CD использует метод `label` — возникает конфликт.

**Проблема:**
```bash
# Helm ставит:
app.kubernetes.io/instance: RELEASE-NAME

# Argo CD ожидает:
app.kubernetes.io/instance: my-app

# Результат: Argo CD не находит ресурс, считает его orphan
```

**Решение:** Переключиться на `annotation`:
```yaml
data:
  resourceTrackingMethod: "annotation"
```

### Сценарий 3: Миграция между методами

Смена метода отслеживания требует обновления всех существующих ресурсов.

**1. Настройка нового метода:**
```yaml
data:
  resourceTrackingMethod: "annotation+label"
```

**2. Принудительное обновление приложений:**
```bash
# Для каждого приложения
argocd app get <app-name> --refresh

# Или через API для массового обновления
for app in $(argocd app list -o name); do
  argocd app get "$app" --refresh
done
```

**3. Проверка:**
```bash
# Убедитесь, что ресурсы имеют оба ключа
kubectl get deployment my-app -o jsonpath='{.metadata.labels.app.kubernetes.io/instance}'
kubectl get deployment my-app -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/instance}'
```

### Сценарий 4: Orphaned ресурсы и cleanup

При удалении приложения Argo CD может удалить или "осиротить" управляемые ресурсы.

**Удаление с orphaning (по умолчанию):**
```bash
argocd app delete my-app --cascade
# → Ресурсы УДАЛЯЮТСЯ (каскадно)
```

**Удаление с сохранением ресурсов (orphan):**
```bash
argocd app delete my-app --no-cascade
# → Ресурсы ОСТАЮТСЯ в кластере без владельца
```

**Обнаружение orphaned ресурсов:**
```bash
# Ресурсы без привязки к приложению
kubectl get deployments -A -o json | jq '.items[] | select(.metadata.annotations["argocd.argoproj.io/instance"] == null) | .metadata.name'
```

### Сценарий 5: Multi-cluster отслеживание

В multi-cluster среде tracking ID включает URL кластера.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-east
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/apps
    path: my-app
    targetRevision: main
  destination:
    server: https://cluster-east.example.com  # URL кластера
    namespace: my-app
```

**Tracking ID:** `my-app-east | https://cluster-east.example.com`

**Проверка в multi-cluster:**
```bash
# На central cluster
argocd app get my-app-east -o json | jq '.status.sync.revision'

# На target cluster
kubectl get deployment my-app -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/instance}'
# → my-app-east | https://cluster-east.example.com
```

### Сценарий 6: Ignoring differences с Resource Tracking

При конфликтах отслеживания с HPA или operator-ами используйте `ignoreDifferences` (см. [Ignore Differences](./synchronization/ignore_differences.md)).

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jqPathExpressions:
        - .spec.replicas  # HPA управляет этим полем
  syncOptions:
    - RespectIgnoreDifferences=true
    - CreateNamespace=true
```

## Диагностика

### Базовые команды

```bash
# Текущий метод отслеживания
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.resourceTrackingMethod}'
# → annotation

# Просмотр tracking ID на ресурсе
kubectl get deployment <name> -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/instance}'

# Просмотр tracking ID на приложении
argocd app get <app-name> -o json | jq '.status.sync.revision'

# Поиск orphaned ресурсов
kubectl get deployments -A -o json | jq '.items[] | select(.metadata.annotations["argocd.argoproj.io/instance"] == null) | {name: .metadata.name, namespace: .metadata.namespace}'
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `resource not found` | Метод `label` конфликтует с Helm | Переключитесь на `annotation` |
| `orphaned resource detected` | Ресурс потерял tracking ID | Проверьте annotations/labels |
| `multi-cluster conflict` | Одинаковые tracking ID в разных кластерах | Убедитесь, что имена приложений уникальны |

## Лучшие практики

- **Используйте `annotation`:** Рекомендуемый метод для большинства случаев — нет конфликтов с Helm/Kustomize.
- **Для multi-cluster используйте `annotation+label`:** Максимальная надежность идентификации.
- **Избегайте смены метода в production:** Миграция требует обновления всех ресурсов.
- **Мониторьте orphaned ресурсы:** Регулярно проверяйте наличие ресурсов без tracking ID.
- **Не используйте `label` с Helm:** Возможны конфликты меток.

## Ограничения и edge cases

### Ограничения

- **Поиск по annotation медленнее:** Арго CD должен сканировать все ресурсы вместо использования индекса.
- **Миграция болезненна:** Смена метода требует обновления каждого ресурса.
- **Multi-cluster tracking ограничен:** URL кластера в tracking ID может быть длинным.

### Edge Cases

- **Удаление tracking ID:** Если ручным образом удалить аннотацию/метку, Argo CD потеряет ресурс.
- **Два Argo CD кластера:** При работе двух независимых кластеров Argo CD tracking ID могут конфликтовать.
- **CRD без support annotations:** Некоторые CRD не поддерживают аннотации — используйте `label`.
- **Ресурс создан вручную:** Ресурс, созданный не через Argo CD, не имеет tracking ID и не будет обнаружен.

## Дополнительная информация

### См. также

- [Synchronization](./synchronization.md)
- [Ignore Differences](./synchronization/ignore_differences.md)
- [Deletion and Cleanup](./argocd_deletion_and_cleanup.md)
- [Установка и настройка](./argocd_installation_and_setup.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Ссылки

- [Resource Tracking Methods](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/)
- [Tracking ID Format](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#resource-tracking-method)
- [Orphaned Resources](https://argo-cd.readthedocs.io/en/stable/user-guide/orphaned-resources/)
