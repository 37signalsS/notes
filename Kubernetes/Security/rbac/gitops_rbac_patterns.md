# RBAC-паттерны Kubernetes: per-namespace роли в GitOps

## Определения

**GitOps RBAC** — подход к управлению ролями доступа в Kubernetes, при котором все манифесты RBAC (ClusterRole, Role, RoleBinding, ClusterRoleBinding) хранятся в Git-репозитории и применяются в кластер декларативно через GitOps-контроллер (Argo CD). Обеспечивает аудит изменений, peer review и воспроизводимость.

**Иерархическая модель ролей** — паттерн, при котором кастомные ClusterRole построены в виде иерархии через механизм агрегации: каждая роль наследует права родительской (например, `view` → `developer` → `devops`). Наследование работает через метки `aggregate-to-*` и поле `aggregationRule`. Подробнее о механизме агрегации: [Агрегируемые ClusterRole](./aggregation_scenarios.md).

**Per-namespace роли** — развёртывание RoleBinding в каждом пространстве имён отдельно, что ограничивает права субъектов пределами namespace. Для переиспользования ClusterRole в разных namespace используется Kustomize-трансформер `namespace`.

**Argo CD ServiceAccount Isolation** — механизм, при котором контроллер приложений Argo CD выполняет запросы от имени указанного `ServiceAccount` (через `spec.destination.serviceAccountName` в манифесте `Application`). Позволяет ограничить права контроллера до прав тенанта, не выдавая `cluster-admin` для всех приложений. Подробнее: [Сценарий 5 в сравнении Argo CD и Flux](../../../GitOps/argo_vs_flux_manifests.md).

---

## Архитектура иерархии ролей

### Модель трёх уровней

Иерархия ролей строится через два механизма:

1. **Механизм агрегации Kubernetes** — встроенный контроллер `kube-controller-manager` объединяет правила из нескольких ClusterRole в одну роль через `aggregationRule`. Подробно: [Агрегируемые ClusterRole](./aggregation_scenarios.md).
2. **Метка-уровень** — каждая кастомная роль помечается меткой своего родительского уровня (`rbac.example.com/aggregate-to-devops: "true"`), что позволяет автоматически включать её правила в агрегирующую роль.

```text
┌─────────────────────────────────────────────────────────────────┐
│  cluster-admin  (build-in)                                      │
│  └─ только ServiceAccount Argo CD                                │
├─────────────────────────────────────────────────────────────────┤
│  devops  (агрегирует aggregate-to-devops:"true")               │
│  └─ developer  (aggregate-to-devops:"true")                     │
│     └─ developer-tools  (aggregate-to-developer:"true")        │
│     └─ view (встроенная, aggregate-to-view:"true")              │
├─────────────────────────────────────────────────────────────────┤
│  developer  (RoleBinding по namespace)                          │
│  └─ Group: example/dev-team                                      │
├─────────────────────────────────────────────────────────────────┤
│  devops  (RoleBinding по namespace)                             │
│  └─ Group: example/platform-team                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Принцип наследования:**

| Роль | Наследует от | Дополнительные права | Метка для агрегации родителя |
|------|-------------|---------------------|------------------------------|
| `view` (встроенная) | — | Read-only: pods, pods/log, events, services, configmaps | `aggregate-to-view: "true"` (системная) |
| `developer` (кастомная) | `view` (через агрегацию) | `pods/exec`, `pods/portforward` | `rbac.example.com/aggregate-to-devops: "true"` |
| `devops` (кастомная) | `developer` (через агрегацию) | deployments, statefulsets, daemonsets, configmaps, secrets, serviceaccounts, applications | не применяется (агрегирующая роль) |
| `cluster-admin` (встроенная) | — | Всё | — |

### Критическое ограничение: aggregationRule и правила

Когда на ClusterRole установлен `aggregationRule`, контроллер делает поле `rules` **управляемым контроллером**. Любые явно прописанные правила в `rules` будут **перезаписаны** контроллером при следующем цикле реконсиляции. Подробности в `aggregation_scenarios.md` (раздел «Типичные ошибки») и в [Kubernetes API reference](https://v1-34.docs.kubernetes.io/docs/reference/kubernetes-api/authorization-resources/cluster-role-v1).

**Последствие для иерархии:** агрегирующая роль (например, `developer`) не может одновременно содержать `aggregationRule` и собственные правила `rules`. Дополнительные права должны быть вынесены в отдельные модульные ClusterRole с соответствующей меткой.

---

## Практические сценарии

### Сценарий 1: Определение иерархичных ClusterRole

#### Модуль: developer-tools (правила для developer)

```yaml
# Модуль с правами exec/portforward/log.
# Метка aggregate-to-developer делает эти правила доступными
# для агрегирующей роли developer.
# Метка aggregate-to-view НЕ установлена — view не получает exec.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-tools
  labels:
    rbac.example.com/aggregate-to-developer: "true"
rules:
  - apiGroups: [""]
    resources: ["pods/exec", "pods/portforward"]
    verbs: ["create"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
```

> **Примечание:** право `pods/log` уже включено во встроенную роль `view` через агрегируемые модули Kubernetes. Дублирование в `developer-tools` не ошибка — контроллер выполняет объединение правил (union), а не замену.

#### Агрегирующая роль: developer

```yaml
# developer наследует все правила view (через aggregate-to-view)
# и все правила developer-tools (через aggregate-to-developer).
# Поле rules пустое — контроллер заполняет его автоматически.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer
  labels:
    rbac.example.com/aggregate-to-devops: "true"  # участвует в агрегации devops
aggregationRule:
  clusterRoleSelectors:
    - matchLabels:
        rbac.authorization.k8s.io/aggregate-to-view: "true"
    - matchLabels:
        rbac.example.com/aggregate-to-developer: "true"
rules: []
```

#### Модуль: devops-deploy (правила для devops)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: devops-deploy
  labels:
    rbac.example.com/aggregate-to-devops: "true"
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["configmaps", "secrets", "serviceaccounts"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

#### Модуль: devops-argoproj (правила для работы с Argo CD Application)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: devops-argoproj
  labels:
    rbac.example.com/aggregate-to-devops: "true"
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["applications", "appprojects"]
    verbs: ["get", "list", "watch", "patch"]
```

> **Проверка:** API-группа `argoproj.io` и ресурсы `applications`, `appprojects` являются стандартными CRD Argo CD. Справка: `kubectl api-resources --api-group=argoproj.io`.

#### Агрегирующая роль: devops

```yaml
# devops наследует правила developer (через aggregate-to-devops:"true")
# и все модули с меткой aggregate-to-devops:"true".
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: devops
aggregationRule:
  clusterRoleSelectors:
    - matchLabels:
        rbac.example.com/aggregate-to-devops: "true"
rules: []
```

#### ClusterRoleBinding для ServiceAccount Argo CD

```yaml
# Только ServiceAccount Argo CD Application Controller получает cluster-admin.
# Люди никогда не получают cluster-admin интерактивно.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-manager-cluster-admin
subjects:
  - kind: ServiceAccount
    name: argocd-manager
    namespace: kube-system
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: RoleBinding по namespace с Kustomize

#### База (base/rbac)

```yaml
# base/rbac/dev-bindings.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-team-developer
subjects:
  - kind: Group
    name: "example/dev-team"
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: developer
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: platform-team-devops
subjects:
  - kind: Group
    name: "example/platform-team"
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: devops
  apiGroup: rbac.authorization.k8s.io
```

> **Важно:** `RoleBinding` (не `ClusterRoleBinding`) ограничивает права одним namespace. Даже если `roleRef` указывает на `ClusterRole`, действие привязки распростреляется только на тот namespace, где создан `RoleBinding`. Подробности: [Привязки ролей](./bindings.md).

#### Kustomize-трансформер namespace

```yaml
# overlays/test/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base/rbac
namespace: test

# overlays/staging/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base/rbac
namespace: staging
```

Kustomize `namespace`-трансформер перезаписывает поле `metadata.namespace` во всех именованных ресурсах. Одни и те же манифесты применяются в разных namespace без дублирования файлов. Справка: [Kustomize — обзор](../../ToolsUtilities/kustomize/kustomize_overview.md), [Kustomize — наложения и патчи](../../ToolsUtilities/kustomize/kustomize_overlays_and_patches.md).

### Сценарий 3: Read-only доступ ко всему кластеру

Namespace мониторинга (Prometheus, Grafana) должен быть доступен всем командам на чтение через `ClusterRoleBinding`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: all-teams-view-observability
subjects:
  - kind: Group
    name: "example/dev-team"
    apiGroup: rbac.authorization.k8s.io
  - kind: Group
    name: "example/platform-team"
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```

`ClusterRoleBinding` + встроенная роль `view` позволяет инженерам читать ресурсы во всех namespace, но не писать за пределами своих.

### Сценарий 4: Структура файлов RBAC в GitOps-репозитории

```
spoke/rbac/
├── clusterroles.yaml        # Агрегирующие роли (developer, devops) + модули
├── dev-bindings.yaml        # RoleBinding для namespace dev
├── monitoring-binding.yaml  # ClusterRoleBinding для чтения observability
└── kustomization.yaml
```

Добавление нового окружения (test, staging) без копирования binding-файлов:

```yaml
# overlays/test/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../../spoke/rbac
  - ../../../spoke/rbac/dev-bindings.yaml
namespace: test
```

---

## Операции и команды

### Аудит прав доступа

Проверить, какие права имеет пользователь в конкретном namespace:

```bash
# Список всех разрешений пользователя в namespace dev
kubectl auth can-i --list -n dev --as=developer-user
# → pods/exec                create
# → pods/log                 get
# → pods/portforward         create
# → services                 get, list, watch
# → ...

# Проверка конкретного действия
kubectl auth can-i create deployments -n dev --as=developer-user
# → yes

# Проверка через SubjectAccessReview (программный аудит)
kubectl auth can-i patch applications -n dev --as=group:example/platform-team
# → yes
```

Просмотр всех binding в namespace:

```bash
kubectl get rolebindings,clusterrolebindings -n dev -o wide
# → NAME                                            ROLE                           AGE   SUSPENDED
# → rolebinding/dev-team-developer                  ClusterRole/developer          5d    <none>
# → rolebinding/platform-team-devops                ClusterRole/devops             5d    <none>
```

Проверка, что агрегирующая роль корректно собрала правила:

```bash
# Проверка итогового набора правил developer
kubectl get clusterrole developer -o jsonpath='{.rules}' | jq .
# → [ ... объединённые правила view + developer-tools ... ]

# Проверка какие модули участвуют в агрегации
kubectl get clusterrole -l rbac.example.com/aggregate-to-developer=true -o name
# → clusterrole/developer-tools

# Проверка итогового набора правил devops
kubectl get clusterrole devops -o jsonpath='{.rules}' | jq .
# → [ ... объединённые правила developer + devops-deploy + devops-helmrelease ... ]
```

---

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `rules` в агрегирующей роли перезаписываются контроллером | `aggregationRule` + явные `rules` в одной ClusterRole | Вынесите правила в отдельный модульный ClusterRole с меткой агрегации. См. [Сценарий 1](#сценарий-1-определение-иерархичных-clusterrole) |
| `ClusterRoleBinding` вместо `RoleBinding` | Права выдаются во все namespace | Используйте `RoleBinding` для per-namespace доступа, даже если `roleRef` ссылается на `ClusterRole` |
| `cluster-admin` для CI/CD | Избыточные права | CI/CD получает только те ресурсы, которые он управляет (см. [RBAC для CI/CD](./aggregation_scenarios.md#сценарий-9-агрегация-для-cicd-систем-github-actions-gitlab-ci)) |
| Ручной `kubectl create rolebinding` | Не отслеживается в Git, перезатирается Argo CD | Управляйте всеми RBAC-манифестами через GitOps |
| `view` + `pods/exec` | `pods/exec` не входит во встроенную `view` | Добавьте отдельный модуль с меткой `aggregate-to-view: "true"` (как в [Сценарий 2](./aggregation_scenarios.md#сценарий-2-расширение-стандартной-роли-edit-для-отладки)) |

---

## Лучшие практики

1. **Не смешивайте `aggregationRule` и `rules`:** агрегирующая ClusterRole должна иметь `rules: []` или не иметь поле `rules` вовсе. Все дополнительные правила выносите в модульные ClusterRole с соответствующей меткой.

2. **Используйте `RoleBinding` для per-namespace:** даже если он ссылается на `ClusterRole`, `RoleBinding` ограничивает область действия одним namespace. `ClusterRoleBinding` даёт доступ во все namespace — используйте только для глобально-только-чтения ролей (например, `view` для observability).

3. **Иерархия меток:** используйте иерархию меток (`aggregate-to-view` → `aggregate-to-developer` → `aggregate-to-devops`) для построения чёткой цепочки наследования. Избегайте одинаковых меток для разных уровней.

4. **Argo CD ServiceAccount:** Argo CD Application Controller должен работать с `ServiceAccount`, имеющим минимальные права для управляемых namespace (через `spec.destination.serviceAccountName` в `Application`). `cluster-admin` для Argo CD нужен только для установки самого контроллера, а не для daily-синхронизации.

5. **RBAC в Git:** все манифесты RBAC хранятся в Git и применяются через GitOps. Никогда не выдаёте права через ручной `kubectl create rolebinding` — изменения не отслеживаются и будут перезаписаны при следующем reconcile.

6. **Аудит после изменений:** после любого изменения RBAC проверяйте права через `kubectl auth can-i` и `kubectl get clusterrole <name> -o yaml`.

---

## Дополнительная информация

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — архитектура управления доступом, request pipeline, алгоритм авторизации
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)** — механизм агрегации, синтаксис `aggregationRule`, типовые ошибки и диагностика
- **[Привязки ролей (RoleBinding)](./bindings.md)** — структура `roleRef`, субъекты, поведение при ссылке на агрегируемую ClusterRole
- **[Роли (Role и ClusterRole)](./roles.md)** — структура правил, субресурсы (`pods/exec`, `pods/portforward`), ограничения `resourceNames`
- **[RBAC в мультикластерных средах](./multi_cluster_rbac.md)** — синхронизация RBAC между кластерами, hub-and-spoke топология
- **[Сценарий 5: Мультитенантность во Flux vs Argo CD](../../../GitOps/argo_vs_flux_manifests.md)** — ServiceAccount Impersonation (Flux) vs ServiceAccount Isolation (Argo CD) для изоляции прав команд
- **[Обзор Argo CD](../../../GitOps/ArgoCD/argocd_overview.md)** — архитектура Argo CD, мультитенантность, ServiceAccount Isolation

### Внешние ресурсы

- [Using RBAC Authorization — Kubernetes Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [ClusterRole API reference](https://v1-34.docs.kubernetes.io/docs/reference/kubernetes-api/authorization-resources/cluster-role-v1/)
- [Argo CD — Multi-tenancy and RBAC](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/rbac/)
- [Kustomize — Namespace Transformer](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/namespace)