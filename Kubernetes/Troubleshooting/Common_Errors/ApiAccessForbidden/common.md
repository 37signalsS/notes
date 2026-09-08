# Ошибка 403 Forbidden (Доступ запрещен): распространенные случаи

## Определения

**403 Forbidden (RBAC)** — состояние, при котором API-сервер успешно идентифицировал субъекта (аутентификация пройдена), но отклонил запрос, так как в системе **RBAC (Role-Based Access Control)** отсутствуют правила, разрешающие данному субъекту выполнение конкретного действия (`verb`) над указанным ресурсом (`resource`).

**403 Forbidden (Admission Control)** — отказ, возникающий на этапе контроля допуска. Даже если RBAC разрешает действие, запрос может быть заблокирован политиками безопасности (например, **Pod Security Admission**), квотами (**ResourceQuotas**) или внешними вебхуками.

**NonResourceURLs** — отдельный класс правил RBAC, действующий только в `ClusterRole`. Определяет доступ к URL-путям, не являющимся ресурсами Kubernetes (например, `/healthz`, `/metrics`, `/version`, `/openapi/v2`). Отсутствие правила для `nonResourceURLs` приводит к 403 Forbidden даже при наличии прав на все ресурсы.

**Wildcard-подстановки (`*`)** — символ `*` в полях `apiGroups`, `resources`, `verbs` означает «любое значение» этого поля. Позволяет создавать максимально широкие роли (например, аналог `cluster-admin`) и автоматически покрывать новые ресурсы и глаголы будущих версий Kubernetes. В `nonResourceURLs` звёздочка работает как суффиксный glob-шаблон: `/foo/*` соответствует всем подпутям `/foo/`.

> Подробное сравнение 401 vs 403: [definitions.md](definitions.md)
> Теория и архитектура RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)
> Детали wildcard и resourceNames: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)

## Основные концепции

### Структура сообщения об ошибке

Сообщение об ошибке от API-сервера является самодокументированным и содержит пять критических параметров для отладки:

```text
Error from server (Forbidden): <resource> is forbidden:
User "<subject>" cannot <verb> resource "<resource>"
in API group "<group>" in the namespace "<namespace>"
```

1.  **Subject:** Кто пытается выполнить действие (User, Group или ServiceAccount).
2.  **Verb:** Какое действие выполняется (`get`, `list`, `create`, `update`, `patch`, `delete`, `watch`).
3.  **Resource:** Тип объекта (`pods`, `secrets`, `deployments`, `pods/log`).
4.  **API Group:** Группа, к которой принадлежит ресурс (например, `apps`, `networking.k8s.io` или `""` для core).
5.  **Namespace:** Пространство имен, в котором запрашивается доступ (актуально для RoleBinding).

### Инструментарий для быстрой проверки

Основным инструментом является `kubectl auth can-i`. Использование флага `--as` (impersonation) позволяет проверить права от имени другого пользователя или ServiceAccount без переключения контекста `kubeconfig`.

```bash
# Проверка прав конкретного ServiceAccount
kubectl auth can-i <verb> <resource> \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Пример: может ли приложение читать логи своих подов
kubectl auth can-i get pods/log \
  --as=system:serviceaccount:prod-ns:app-sa \
  -n prod-ns
# → yes / no
```

> **Важно (ложное «да» от can-i):** команда `kubectl auth can-i create configmap/fluentd-extra-config` может вернуть `yes`, хотя фактический `kubectl create` завершится `403 Forbidden`. Причина — `can-i` проверяет разрешение на «именованный» эндпоинт (с указанием имени объекта в URL), а реальный `POST`-запрос идёт на коллекцию без имени. При отладке всегда проверяйте реальное действие, а не только `can-i`. Подробнее: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md).

### Справочник команд диагностики RBAC

| Задача | Команда |
|--------|---------|
| Проверка конкретного права SA | `kubectl auth can-i <verb> <resource> --as=system:serviceaccount:<ns>:<sa> -n <ns>` |
| Полный список прав SA | `kubectl auth can-i --list --as=system:serviceaccount:<ns>:<sa> -n <ns>` |
| Проверка nonResourceURL | `kubectl auth can-i get /healthz --as=<user>` |
| Проверка с группой | `kubectl auth can-i create deployments --as=<user> --as-group=<group> -n <ns>` |
| Определение API-группы ресурса | `kubectl api-resources -o wide \| grep <resource>` |
| Список всех RoleBinding в NS | `kubectl get rolebindings -n <ns> -o wide` |
| Список всех ClusterRoleBinding | `kubectl get clusterrolebindings -o wide` |
| Сырой HTTP-ответ с Audit-Id | `kubectl get <resource> -v=8 2>&1 \| grep -E "Audit-Id\|HTTP/"` |

### Пошаговый workflow диагностики 403

```text
Получен 403 Forbidden
    ↓
Шаг 1: Извлечь код и Audit-Id
    kubectl <command> -v=8 2>&1 | grep -E "Audit-Id|HTTP/"
    ↓
Шаг 2: Проверить, является ли проблема RBAC
    kubectl auth can-i <verb> <resource> --as=<subject> -n <ns>
    ├── NO  → проблема в RBAC (Шаг 3)
    └── YES → проблема в Admission Control (см. advanced.md)
    ↓
Шаг 3: Локализация RBAC-проблемы
    3a. Проверить API-группу: kubectl api-resources -o wide | grep <resource>
    3b. Проверить все привязки SA:
        kubectl get rolebindings,clusterrolebindings -A -o wide | grep <sa-name>
    3c. Проверить наличие кросс-неймспейс привязки:
        kubectl get rolebinding <name> -n <ns> -o jsonpath='{.subjects}'
    3d. Проверить ClusterRole vs Role (кластерные ресурсы требуют ClusterRole)
    ↓
Шаг 4: Применить исправление и валидировать
    kubectl apply -f < corrected-rbac.yaml
    kubectl auth can-i <verb> <resource> --as=<subject> -n <ns>  # → yes
```

> Полный алгоритм и пошаговая диагностика: [diagnostics.md](diagnostics.md)

## Практические сценарии

### Сценарий 1: Чтение подов (отсутствует RoleBinding)

**Контекст:** Приложение (например, Prometheus или Service Discovery) пытается получить список подов в своем пространстве имен.

**Ошибка:** `User "system:serviceaccount:my-ns:my-sa" cannot list resource "pods" in API group ""`

**Решение:** Необходимо создать пару `Role` и `RoleBinding`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: my-ns
rules:
- apiGroups: [""] # Core API group
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-sa-pod-reader
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: Доступ к секретам (Least Privilege)

**Контекст:** Приложению требуется доступ к конкретному секрету с конфигурацией.

**Проблема:** Предоставление доступа ко всем секретам в namespace (`resources: ["secrets"]`) нарушает принцип наименьших привилегий.

**Решение:** Использование `resourceNames` для ограничения доступа.

```yaml
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["db-credentials", "api-keys"] # Доступ только к этим объектам
  verbs: ["get"]
```

### Сценарий 3: Управление ресурсами группы apps (Deployments)

**Контекст:** CI/CD конвейер или оператор пытается обновить `Deployment`.

**Ошибка:** `cannot patch resource "deployments" in API group "apps"`

**Особенность:** Ресурсы `deployments`, `statefulsets`, `daemonsets` и `replicasets` находятся в группе `apps`. Указание пустой группы `""` приведет к ошибке 403.

**Решение:**
```yaml
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Сценарий 4: Доступ к подресурсам (logs, exec, status)

**Контекст:** Администратору или инструменту автоматизации требуется доступ к логам или возможность выполнения команд внутри контейнера.

**Ошибка:** `cannot create resource "pods/exec" in API group ""`

**Особенность:** Права на `pods` не дают автоматического доступа к `pods/log` или `pods/exec`. Подресурсы указываются через слэш.

**Решение:**
```yaml
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec"]
  verbs: ["get", "list", "create"] # exec требует 'create'
```

### Сценарий 5: Работа с Custom Resource Definitions (CRDs)

**Контекст:** Использование внешних контроллеров (Cert-Manager, Istio, Prometheus Operator).

**Ошибка:** `cannot list resource "certificates" in API group "cert-manager.io"`

**Решение:** Всегда проверяйте `apiGroup` кастомного ресурса через `kubectl get crd <name> -o yaml`.

```yaml
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "issuers"]
  verbs: ["*"]
```

### Сценарий 6: Доступ к кластерным ресурсам через Role (Ошибочно)

**Контекст:** Попытка разрешить чтение списка `Namespaces` или `Nodes` с помощью объекта `Role`.

**Проблема:** `Role` и `RoleBinding` действуют только внутри одного пространства имен. Кластерные ресурсы (Nodes, Namespaces, PV, ClusterRoles) требуют использования `ClusterRole` и `ClusterRoleBinding`.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: read-nodes-global
subjects:
- kind: User
  name: monitor-user
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 7: Wildcard-подстановки и ловушки с `resourceNames`

**Контекст:** Использование `*` в правилах RBAC для автоматического покрытия будущих ресурсов.

**Правило с wildcard:**
```yaml
rules:
- apiGroups: ["apps"]
  resources: ["*"]
  verbs: ["*"]
```

**Ловушка:** Wildcard `verbs: ["*"]` покрывает все текущие и будущие глаголы, но **не** работает как «любое действие для конкретного resourceNames». Если указан `resourceNames`, глаголы `create` и `deletecollection` **игнорируют** ограничение по именам (объект не существует на момент авторизации). Также `list`/`watch` с `resourceNames` требуют указания field selector:

```bash
# Ошибка — вернёт 403, хотя get разрешён:
kubectl get configmaps

# Правильно — с field selector:
kubectl get configmaps --field-selector=metadata.name=my-configmap
```

> Подробнее о поведении `resourceNames`: [../../../Security/rbac/roles.md](../../../Security/rbac/roles.md)

### Сценарий 8: Доступ к нересурсным URL (nonResourceURLs)

**Контекст:** Мониторинг, health-check агенты или внешние инструменты обращаются к `/healthz`, `/metrics`, `/version` и получают 403.

**Ошибка:** `User "system:serviceaccount:monitoring:prometheus" is forbidden: User "..." cannot get path "/metrics"`

**Особенность:** `nonResourceURLs` доступны **только** в `ClusterRole` и не зависят от namespace. Role не поддерживает этот тип правил.

**Решение:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: metrics-reader
rules:
- nonResourceURLs: ["/metrics", "/healthz", "/version"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-metrics
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: metrics-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 9: Интеграция с Prometheus Operator (системы мониторинга)

**Контекст:** Prometheus Operator или Geneva DaemonSet не может собирать метрики с подов или узлов.

**Типичные ошибки:**
- `cannot list resource "pods" in API group ""` — нет прав на Service Discovery.
- `cannot list resource "endpointslices" in API group "discovery.k8s.io"` — устаревшие правила без endpointslices.
- `cannot get resource "nodes/metrics" in API group "metrics.k8s.io"` — нет доступа к агрегированному API.

**Решение — минимальный набор прав для Prometheus:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-server
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/proxy", "nodes/metrics", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["discovery.k8s.io"]
  resources: ["endpointslices"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch"]
- nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
  verbs: ["get"]
```

**Валидация:**
```bash
# Проверка прав Prometheus SA на скрапинг
kubectl auth can-i list pods --as=system:serviceaccount:monitoring:prometheus-server
# → yes
kubectl auth can-i list endpointslices --as=system:serviceaccount:monitoring:prometheus-server
# → yes
```

### Сценарий 10: CI/CD пайплайн и деплой через ServiceAccount

**Контекст:** GitLab Agent, ArgoCD Application Controller или другой CD-инструмент пытается применить манифесты.

**Ошибка:** `deployments.apps "my-app" is forbidden: User "system:serviceaccount:argocd:argocd-application-controller" cannot patch resource "deployments" in API group "apps" in the namespace "prod"`

**Типичная причина:** RoleBinding ссылается на Role с правами `get`/`list`/`watch`, но не включает `create`/`update`/`patch`/`delete`.

**Решение для CD-контроллера:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cd-deployer
  namespace: prod
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["configmaps", "secrets", "services"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

### Сводная таблица типичных ошибок 403 (RBAC)

| Сообщение об ошибке | Вероятная причина | Решение |
|----------------------|-------------------|---------|
| `cannot list resource "pods" in API group ""` | Отсутствует RoleBinding для SA | Создать Role + RoleBinding с `verbs: ["get", "list", "watch"]` |
| `cannot patch resource "deployments" in API group "apps"` | Неверная API-группа (`""` вместо `"apps"`) | Исправить `apiGroups: ["apps"]` |
| `cannot create resource "pods/exec" in API group ""` | Нет глагола `create` для подресурса | Добавить `resources: ["pods/exec"]` с `verbs: ["create"]` |
| `cannot get resource "nodes/metrics" in API group "metrics.k8s.io"` | Нет прав на агрегированное API | ClusterRoleBinding на `system:metrics-server` или свой ClusterRole |
| `secrets "my-secret" is forbidden: ... resourceNames` | `list` без field selector | Использовать `get` или `--field-selector=metadata.name=...` |
| `User "system:anonymous" cannot ...` | Анонимный доступ без прав | Включить аутентификацию или предоставить права `system:unauthenticated` |
| `namespaces "prod" is forbidden` | Role вместо ClusterRole для кластерного ресурса | Использовать ClusterRole + ClusterRoleBinding |

## Дополнительная информация

### Справочник API-групп и ресурсов

| Ресурс | API Group | Тип привязки (обычно) |
|--------|-----------|-----------------------|
| pods, services, configmaps, secrets, events | `""` (core) | Role |
| deployments, daemonsets, statefulsets | `apps` | Role |
| ingress, networkpolicies | `networking.k8s.io` | Role |
| jobs, cronjobs | `batch` | Role |
| horizontalpodautoscalers | `autoscaling` | Role |
| nodes, namespaces, persistentvolumes | `""` (core) | ClusterRole |
| storageclasses | `storage.k8s.io` | ClusterRole |
| certificates, issuers | `cert-manager.io` | Role / ClusterRole |

### Чек-лист для устранения 403 Forbidden

1.  **Множественное число:** Ресурсы в правилах ВСЕГДА во множественном числе (`pods`, а не `pod`).
2.  **API Group:** Проверьте группу через `kubectl api-resources`. Для ядра — `""`, для деплоев — `"apps"`, для сетевых политик — `"networking.k8s.io"`.
3.  **Namespace Match:** Убедитесь, что `ServiceAccount`, `Role` и `RoleBinding` находятся в одном пространстве имен (если не используется ClusterRole).
4.  **Verbs для подресурсов:** Помните, что `exec` и `portforward` требуют глагола `create`.
5.  **Impersonation:** Всегда проверяйте гипотезу через `kubectl auth can-i --as=...`.
6.  **Admission Control:** Если RBAC настроен верно, но ошибка сохраняется — проверьте события неймспейса (`kubectl get events`) на предмет блокировок PSA или квот.
7.  **automountServiceAccountToken:** Проверьте, что ServiceAccount не монтирует токен «по умолчанию» (`automountServiceAccountToken: false`), если приложению не нужен доступ к API.
8.  **Кросс-неймспейс доступ:** `RoleBinding` в namespace A может ссылаться на `ServiceAccount` из namespace B — это валидный паттерн, но его легко пропустить при аудите.
9.  **roleRef immutable:** Поле `roleRef` в RoleBinding/ClusterRoleBinding неизменяемо. Для смены роли необходимо удалить и пересоздать биндинг.
10. **nonResourceURLs:** Для доступа к `/healthz`, `/metrics`, `/version` требуется `ClusterRole` с полем `nonResourceURLs` (Role не поддерживает).

### Сторонние инструменты для анализа RBAC

| Инструмент | Назначение | Установка |
|------------|-----------|-----------|
| **kubectl-who-can** | Интерактивный вывод всех субъектов, имеющих право на действие | `kubectl krew install who-can` |
| **rbac-lookup** | Визуализация графа связей Role→Subject, поиск по SA/User/Group | `brew install FairwindsOps/tap/rbac-lookup` |
| **police** | Статический анализ RBAC-политик на наличие опасных связей | `go install github.com/elek/rbac-police@latest` |
| **kubectl-access-matrix** | Вывод полной матрицы доступа для SA/пользователя | `kubectl krew install access-matrix` |

```bash
# Пример: кто имеет доступ к secrets в namespace prod?
kubectl who-can list secrets -n prod

# Пример: полная матрица прав SA
kubectl access-matrix serviceaccount/prometheus -n monitoring
```

### Связанные ресурсы

- [Алгоритмы диагностики 401/403](diagnostics.md)
- [Определения и модель безопасности API](definitions.md)
- [Расширенные сценарии (Admission, NodeRestriction)](advanced.md)
- [Объекты RBAC: детальный разбор](rbac_objects.md)
- [Лучшие практики и превентивные меры](best_practices.md)
- [Детали wildcard и resourceNames](../../../Security/rbac/roles.md)
