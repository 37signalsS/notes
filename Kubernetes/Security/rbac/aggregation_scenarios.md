# Агрегируемые кластерные роли (ClusterRole)

## Определения

**Агрегация ролей (Role Aggregation)** — высокоуровневый механизм в системе **RBAC (Role-Based Access Control)** Kubernetes, предназначенный для динамического и автоматического объединения наборов разрешений из нескольких [ClusterRole](./roles.md) в одну итоговую роль. Этот механизм позволяет реализовать модульную и расширяемую архитектуру управления доступом.

**Агрегирующая ClusterRole** — объект ClusterRole, определяющий логику сборки через поле `aggregationRule`. Она не содержит правил `rules` напрямую (или содержит только базовый набор), а делегирует их формирование контроллеру.

**Субъект агрегации** — любая ClusterRole в кластере, имеющая метки (labels), соответствующие селекторам агрегирующей роли.

---

## Основные концепции

### Механизм работы контроллера (Control Plane)

Процесс агрегации управляется встроенным в `kube-controller-manager` контроллером RBAC:
1. **Обнаружение (Discovery):** Контроллер постоянно отслеживает изменения всех объектов `ClusterRole`.
2. **Селекция (Selection):** При обнаружении роли с заполненным `aggregationRule`, контроллер выполняет поиск всех существующих ClusterRole, чьи метки удовлетворяют условиям `clusterRoleSelectors`.
3. **Объединение (Union):** Контроллер вычисляет логическое объединение (OR) всех списков `rules`. Поскольку RBAC является аддитивным, права просто суммируются.
4. **Синхронизация (Synchronization):** Результат записывается в поле `rules` агрегирующей роли. Любое изменение в "дочерних" ролях (добавление/удаление правил или изменение меток) инициирует немедленное обновление итоговой роли.

> **Архитектурное ограничение:** Агрегация поддерживается **только на уровне ClusterRole**. Обычные [роли (Role)](./roles.md) не имеют поля `aggregationRule`. Это связано с тем, что Role привязаны к конкретному Namespace, в то время как агрегация предназначена для формирования глобальных или кросс-пространственных шаблонов доступа.

### Структура и синтаксис aggregationRule

Поле `aggregationRule` использует стандартный механизм `LabelSelector`, поддерживающий как простые равенства, так и сложные выражения:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: system:aggregated-manager
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:          # Селектор по точному совпадению
      rbac.example.io/aggregate-to-manager: "true"
  - matchExpressions:     # Селектор по сложным условиям
    - key: rbac.example.io/tier
      operator: In
      values: ["infra", "security"]
rules: []  # Рекомендуется оставлять пустым, так как контроллер перезапишет это поле
```

**Порядок вычисления правил:**
1. Контроллер собирает все `ClusterRole`, удовлетворяющие **любому** из селекторов в `clusterRoleSelectors` (логическое ИЛИ между селекторами).
2. Из каждой найденной роли берётся список `rules`.
3. Все списки `rules` объединяются в один (логическое ИЛИ).
4. Итоговый список записывается в `rules` агрегирующей роли.

> **Важно:** Если ни одна ClusterRole не удовлетворяет селекторам, `rules` агрегирующей роли будет пустым (`[]`). Это не является ошибкой — это значит, что нет модулей, которые нужно агрегировать.

### Встроенные роли и системная агрегация

Kubernetes поставляется с набором стандартных ролей, которые уже настроены на агрегацию. Это позволяет администраторам расширять права `admin`, `edit` и `view` для новых типов ресурсов (например, CRD), просто помечая свои роли соответствующими метками.

| Системная метка (Label) | Целевая роль | Назначение |
|-------------------------|--------------|------------|
| `rbac.authorization.k8s.io/aggregate-to-admin: "true"` | `admin` | Расширение прав администратора пространства имен. |
| `rbac.authorization.k8s.io/aggregate-to-edit: "true"` | `edit` | Добавление прав на редактирование ресурсов. |
| `rbac.authorization.k8s.io/aggregate-to-view: "true"` | `view` | Добавление прав на просмотр ресурсов. |

**Важно:** Агрегация работает только для ClusterRole. Namespace-роли (Role) не поддерживают `aggregationRule`. Однако ClusterRole с системными метками автоматически расширяют RoleBinding в namespace, где эти RoleBinding ссылаются на агрегированную ClusterRole.

### Типичные ошибки и их диагностика

**Частые проблемы при работе с агрегацией:**

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| Права не появились в итоговой роли | Метки модуля не соответствуют селектору агрегирующей роли | Проверьте `kubectl get clusterrole -l <label>` |
| Права появились, но не работают | RoleBinding ссылается на Role вместо ClusterRole | Убедитесь, что RoleBinding использует `kind: ClusterRole` |
| Права избыточные | Селектор слишком широкий (например, `Exists` без фильтра) | Сужайте селекторы через `matchLabels` или `matchExpressions` с `NotIn` |
| Конфликт меток | Несколько агрегирующих ролей используют одинаковые метки модулей | Используйте уникальные префиксы для меток (`rbac.company.io/aggregate-to-*`) |
| Агрегация не обновляется после изменения модуля | Кэширование контроллера (редко) | Подождите 1-2 минуты или перезапустите `kube-controller-manager` |

---

## Практические сценарии

### Сценарий 1: Модульное управление доступом (Hierarchy)

Разделение ответственности между командами при формировании итоговой роли разработчика.

```yaml
# 1. Корневая агрегирующая роль (создается один раз)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-base
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.company.io/aggregate-to-developer: "true"
rules: []
---
# 2. Модуль от Infra-команды: доступ к логам и чтению подов
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-logs-module
  labels:
    rbac.company.io/aggregate-to-developer: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
---
# 3. Модуль от CI/CD-команды: управление деплойментами
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: developer-deploy-module
  labels:
    rbac.company.io/aggregate-to-developer: "true"
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["create", "update", "patch", "delete", "get", "list", "watch"]
```

**Диагностика (проверка что модули подхватились):**
```bash
# Проверка итогового набора правил
kubectl get clusterrole developer-base -o jsonpath='{.rules}' | jq .

# Проверка какие модули участвуют в агрегации
kubectl get clusterrole -l rbac.company.io/aggregate-to-developer=true -o name
```

### Сценарий 2: Расширение стандартной роли edit для отладки

Предоставление возможности выполнять `kubectl exec` всем пользователям с ролью `edit` через дополняющую роль.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-exec-access
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
```

**Важно:** Это расширяет права **всех** пользователей с ролью `edit` во **всех** namespace. Если нужно ограничить действие модуля конкретным namespace, используйте Role вместо ClusterRole и RoleBinding с appropriate namespace.

### Сценарий 3: Агрегация по сложным условиям (matchExpressions)

Использование выражений для фильтрации ролей, относящихся к разным средам или командам.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: team-security-auditor
aggregationRule:
  clusterRoleSelectors:
  - matchExpressions:
    - key: rbac.company.io/scope
      operator: In
      values: ["security", "audit"]
    - key: rbac.company.io/team
      operator: Exists
rules: []
```

**Селекторы `matchExpressions`:**

| Оператор | Описание | Пример |
|:---|:---|:---|
| `In` | Ключ присутствует в списке значений | `values: ["security", "audit"]` |
| `NotIn` | Ключ отсутствует в списке значений | `values: ["deprecated"]` |
| `Exists` | Ключ существует (любое значение) | — |
| `DoesNotExist` | Ключ отсутствует | — |

### Сценарий 4: Исправление совместимости и безопасности (CVE-2021-25740)

В Kubernetes v1.22+ из стандартных ролей `admin`/`edit` были удалены права на запись в `endpoints` из-за рисков безопасности. Если ваше приложение (например, старый Ingress-контроллер) требует этого:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fix:aggregate-to-edit:endpoints
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: [""]
  resources: ["endpoints"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

> **Внимание:** Это действие снижает безопасность кластера. Используйте его только как временную меру при миграции.

### Сценарий 5: Расширение стандартных ролей для CRD

Автоматическое предоставление прав на чтение/запись custom-ресурсов (CRD) через расширение стандартных ролей `admin`/`edit`/`view`.

**Пример: CRD `Certificate` от cert-manager:**

```yaml
# Модуль для роли view (только чтение)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-certs-view
  labels:
    rbac.authorization.k8s.io/aggregate-to-view: "true"
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers", "clusterissuers"]
  verbs: ["get", "list", "watch"]
---
# Модуль для роли edit (чтение + запись)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-certs-edit
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# Модуль для роли admin (полный доступ + управление IAM)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-certs-admin
  labels:
    rbac.authorization.k8s.io/aggregate-to-admin: "true"
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers", "clusterissuers"]
  verbs: ["*"]
- apiGroups: ["cert-manager.io"]
  resources: ["certificates/status"]
  verbs: ["get", "patch", "update"]
```

**Результат:** Любой пользователь с ролью `view` в любом namespace автоматически получает право на чтение `Certificate`. Пользователь с ролью `edit` — на создание/удаление.

**Популярные CRD, требующие расширения стандартных ролей:**

| CRD | API Group | Типичные права для edit |
|:---|:---|:---|
| cert-manager | `cert-manager.io` | create/delete Certificate, Issuer |
| External Secrets | `external-secrets.io` | create/delete ExternalSecret, SecretStore |
| Prometheus Operator | `monitoring.coreos.com` | create/delete ServiceMonitor, PrometheusRule |
| Argo CD | `argoproj.io` | create/delete Application, AppProject |
| Knative | `serving.knative.dev` | create/delete Service, Route |

### Сценарий 6: Мульти-тенантная агрегация для Organizational Units

Создание иерархической системы доступа для Organization → Team → Individual. Каждый уровень расширяет предыдущий.

```yaml
# 1. Базовая роль для всех разработчиков организации
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: org-developer-base
  labels:
    rbac.company.io/aggregate-to-org-developer: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "services", "configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets", "statefulsets"]
  verbs: ["get", "list", "watch"]
---
# 2. Модуль от Backend-команды (расширение для API-ресурсов)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: org-developer-backend
  labels:
    rbac.company.io/aggregate-to-org-developer: "true"
rules:
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses", "networkpolicies"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
---
# 3. Модуль от Data-команды (расширение для CRD от Prometheus)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: org-developer-data
  labels:
    rbac.company.io/aggregate-to-org-developer: "true"
rules:
- apiGroups: ["monitoring.coreos.com"]
  resources: ["servicemonitors", "prometheusrules", "prometheus"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
---
# 4. Агрегирующая роль (сборка всех модулей)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: org-developer-full
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.company.io/aggregate-to-org-developer: "true"
rules: []
```

**Назначение через RoleBinding в конкретном namespace:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: backend-team-dev
  namespace: development
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: org-developer-full
subjects:
- kind: Group
  name: backend-team
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 7: Агрегация для Observability-стека (Prometheus, Grafana, Alertmanager)

Создание модульных ролей для мониторинга: базовый доступ к метрикам + расширение для каждого компонента стека.

```yaml
# 1. Базовый доступ к метрикам (для всех операторов мониторинга)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-base
  labels:
    rbac.company.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "services", "endpoints", "nodes", "namespaces"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["extensions", "networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch"]
---
# 2. Модуль для Prometheus Operator
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-prometheus-operator
  labels:
    rbac.company.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: ["monitoring.coreos.com"]
  resources: ["prometheuses", "servicemonitors", "prometheusrules", "alertmanagers", "thanosrulers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# 3. Модуль для Grafana (Dashboards через CRD)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-grafana-dashboards
  labels:
    rbac.company.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: ["grafana.integreatly.org"]
  resources: ["grafanadashboards", "grafanas"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# 4. Модуль для Alertmanager
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-alertmanager
  labels:
    rbac.company.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: ["monitoring.coreos.com"]
  resources: ["alertmanagerconfigs"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

**Применение:** Назначьте RoleBinding с ролью `monitoring-base` + агрегирующей ролью в namespace мониторинга.

### Сценарий 8: Агрегация для Ingress-контроллеров

Расширение стандартных ролей для доступа к ресурсам Ingress-контроллеров (NGINX, Traefik, HAProxy).

```yaml
# Модуль для NGINX Ingress Controller
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-nginx-ingress
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses", "ingressclasses"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["services", "endpoints"]
  verbs: ["get", "list", "watch"]
---
# Модуль для CRD NGINX Ingress (configmaps, custom annotations)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-nginx-config
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["nginx-configuration", "udp-services", "tcp-services"]
  verbs: ["get", "update", "patch"]
```

**Различия по Ingress-контроллерам:**

| Контроллер | API Group для CRD | Типичные CRD |
|:---|:---|:---|
| NGINX Ingress | `networking.k8s.io` (стандартные) | Ingress, IngressClass |
| Traefik | `traefik.io/v1alpha1` | IngressRoute, Middleware, TLSOption |
| HAProxy | `haproxy.org/v1` | HAProxyBackend, HAProxyLB |
| Istio | `networking.istio.io` | VirtualService, Gateway, DestinationRule |

### Сценарий 9: Агрегация для CI/CD-систем (GitHub Actions, GitLab CI)

Предоставление минимальных прав для ServiceAccount CI/CD-пайплин с динамическим расширением по этапам.

```yaml
# 1. Базовый доступ для CI/CD (только чтение + создание подов)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cicd-base
  labels:
    rbac.company.io/aggregate-to-cicd: "true"
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec", "services", "configmaps", "secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["create", "delete"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["get", "list", "watch", "create", "delete"]
---
# 2. Модуль для деплоя (GitHub Actions продвигает в staging)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cicd-deploy-staging
  labels:
    rbac.company.io/aggregate-to-cicd: "true"
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["services", "configmaps", "secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# 3. Модуль для базы данных (создание/удаление PostgreSQL операторов)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cicd-database
  labels:
    rbac.company.io/aggregate-to-cicd: "true"
rules:
- apiGroups: ["acid.zalan.do"]
  resources: ["postgresqls", "postgresqls/status"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

**Назначение в namespace CI/CD:**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cicd
  labels:
    purpose: ci-cd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: github-actions-deployer
  namespace: cicd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cicd-base
subjects:
- kind: ServiceAccount
  name: github-actions
  namespace: cicd
```

### Сценарий 10: Диагностика проблем агрегации

Пошаговый алгоритм поиска причин, по которым права из агрегации не работают.

**Симптом:** Пользователь с ролью `edit` не может создавать `Certificate` (cert-manager CRD), хотя модуль `aggregate-certs-edit` создан.

```bash
# Шаг 1: Проверка существования модуля
kubectl get clusterrole aggregate-certs-edit -o yaml
# → Убедитесь, что labels содержит rbac.authorization.k8s.io/aggregate-to-edit: "true"

# Шаг 2: Проверка rules модуля
kubectl get clusterrole aggregate-certs-edit -o jsonpath='{.rules}'
# → Убедитесь, что rules не пустой и содержит нужные apiGroups/resources/verbs

# Шаг 3: Проверка что агрегирующая роль "видит" модуль
kubectl get clusterrole edit -o jsonpath='{.aggregationRule}' | jq .
# → Убедитесь, что clusterRoleSelectors содержит нужный label

# Шаг 4: Проверка rules агрегирующей роли (должна содержать правила из модуля)
kubectl get clusterrole edit -o jsonpath='{.rules}' | jq '.[] | select(.resources[] | contains("certificates"))'
# → Если вывод пустой — модуль не подхватился

# Шаг 5: Проверка RoleBinding
kubectl get rolebinding -A -o json | jq -r '.items[] | select(.roleRef.name=="edit") | "\(.namespace)/\(.metadata.name)"'
# → Убедитесь, что RoleBinding ссылается на ClusterRole "edit", а не на Role

# Шаг 6: Проверка пользователя в группах
kubectl auth can-i create certificates.cert-manager.io --as=jane@example.com --as-group=developers -n myproject
# → Если "no" — проблема в RoleBinding или группах

# Шаг 7: Проверка SubjectAccessReview
kubectl auth can-i --list --as=jane@example.com --as-group=developers -n myproject | grep certificate
# → Если нет строки с certificate — проблема в агрегации

# Шаг 8: Проверка логов контроллера (если нужна детальная отладка)
kubectl logs -n kube-system -l component=kube-controller-manager --tail=50 | grep -i "rbac"
```

### Сценарий 11: Агрегация и Helm

Интеграция агрегируемых ролей в Helm-чарты для автоматического развёртывания.

**Структура Helm-чарта:**

```
cert-manager-aggregation/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── clusterrole-view.yaml
    ├── clusterrole-edit.yaml
    └── clusterrole-admin.yaml
```

**Шаблон `clusterrole-view.yaml`:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ .Release.Name }}-certs-view
  labels:
    rbac.authorization.k8s.io/aggregate-to-view: "true"
    app.kubernetes.io/name: {{ .Chart.Name }}
    app.kubernetes.io/instance: {{ .Release.Name }}
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers"]
  verbs: ["get", "list", "watch"]
```

**Установка:**

```bash
helm install cert-manager-aggregation ./cert-manager-aggregation \
  --namespace cert-manager \
  --create-namespace
```

**Проверка после установки:**

```bash
# Проверка что метки установлены
kubectl get clusterrole cert-manager-agcerts-view -o jsonpath='{.labels}'
# → {"rbac.authorization.k8s.io/aggregate-to-view":"true","app.kubernetes.io/name":"cert-manager-aggregation",...}

# Проверка что rules агрегирующей роли расширены
kubectl get clusterrole view -o jsonpath='{.rules}' | jq '.[] | select(.resources[] | contains("certificate"))'
```

### Сценарий 12: Агрегация и Kustomize

Использование Kustomize для.overlaying агрегируемых ролей поверх стандартных.

**`kustomization.yaml`:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- clusterrole-certs-view.yaml
- clusterrole-certs-edit.yaml

commonLabels:
  rbac.company.io/managed-by: kustomize
```

**`clusterrole-certs-view.yaml`:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: custom-certs-view
  labels:
    rbac.authorization.k8s.io/aggregate-to-view: "true"
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests"]
  verbs: ["get", "list", "watch"]
```

**Применение:**

```bash
kubectl apply -k .
# или
kustomize build . | kubectl apply -f -
```

### Сценарий 13: Агрегация для Service Mesh (Istio, Linkerd)

Расширение стандартных ролей для доступа к ресурсам service mesh.

```yaml
# Модуль для Istio (VirtualService, Gateway, DestinationRule)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-istio
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["networking.istio.io"]
  resources: ["virtualservices", "destinationrules", "gateways", "serviceentries"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["security.istio.io"]
  resources: ["peerauthentications", "authorizationpolicies", "requestauthentications"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
---
# Модуль для Linkerd (ServiceProfile, TrafficSplit)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-linkerd
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["linkerd.io"]
  resources: ["serviceprofiles", "meshedauthentications"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["split.smi-spec.io"]
  resources: ["trafficsplits"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

### Сценарий 14: Агрегация для Secrets Management (External Secrets Operator)

Расширение стандартных ролей для доступа к CRD от External Secrets Operator.

```yaml
# Модуль для External Secrets Operator
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-edit-external-secrets
  labels:
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
- apiGroups: ["external-secrets.io"]
  resources: ["externalsecrets", "secretstores", "clustersecretstores"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["external-secrets.io"]
  resources: ["externalsecrets/status"]
  verbs: ["get", "patch", "update"]
---
# Модуль для чтения (для операторов, которые только читают секреты)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-view-external-secrets
  labels:
    rbac.authorization.k8s.io/aggregate-to-view: "true"
rules:
- apiGroups: ["external-secrets.io"]
  resources: ["externalsecrets", "secretstores", "clustersecretstores"]
  verbs: ["get", "list", "watch"]
```

---

## Дополнительная информация

### Проверка и диагностика

Для проверки того, как контроллер собрал итоговую роль, используйте `kubectl describe` или вывод в YAML:

```bash
# Проверка итогового набора правил (поле rules должно быть заполнено контроллером)
kubectl get clusterrole developer-base -o yaml

# Поиск всех ролей, участвующих в агрегации для конкретной метки
kubectl get clusterrole -l rbac.company.io/aggregate-to-developer=true

# Проверка прав доступа конкретного пользователя (с учетом агрегации)
kubectl auth can-i create deployments --as=system:serviceaccount:dev:default -n dev

# Полнотекстовый поиск по rules агрегирующей роли
kubectl get clusterrole edit -o json | jq '.rules[] | select(.resources[] | contains("certificate"))'

# Проверка что RoleBinding ссылается на ClusterRole (а не на Role)
kubectl get rolebinding -A -o json | jq '.items[] | select(.roleRef.kind=="ClusterRole") | "\(.namespace)/\(.metadata.name) -> \(.roleRef.name)"'
```

### Автоматическое восстановление (Auto-reconciliation)

Kubernetes защищает свои встроенные роли от случайного изменения. Если вы вручную отредактируете `ClusterRole/view`, контроллер вернет её к исходному состоянию при следующем цикле.

**Как вносить изменения:**
1. **Рекомендуемый способ:** Всегда используйте агрегацию (создание новой роли с меткой `aggregate-to-...`).
2. **Принудительный способ:** Чтобы остановить автоматическое восстановление системной роли (не рекомендуется), добавьте аннотацию:

```yaml
metadata:
  annotations:
    rbac.authorization.kubernetes.io/autoupdate: "false"
```

### Производительность и масштабируемость

- **Нагрузка на API-сервер:** Каждое изменение любой ClusterRole заставляет контроллер пересчитывать все агрегирующие роли. В кластерах с тысячами ролей это может вызвать кратковременные всплески нагрузки.
- **Вложенность:** Избегайте глубоких цепочек агрегации (роль А собирает роль Б, которая собирает роль В). Это может привести к неопределенному состоянию при обновлении правил.
- **Оптимизация:** Для кластеров с >50 агрегирующих ролей рекомендуется мониторить latency API-сервера и при необходимости выносить kube-controller-manager на выделенные ноды.

### Лучшие практики (Best Practices)

1. **Имена-префиксы:** Используйте префиксы в именах агрегируемых ролей (например, `ext:`, `custom:`, `fix:`), чтобы легко отличать их от системных в выводе `kubectl`.
2. **Минимализм matchExpressions:** Избегайте слишком широких селекторов. Ошибка в одной метке может привести к тому, что в роль администратора попадут права от неавторизованной роли.
3. **Пустые `rules`:** В агрегирующих ролях оставляйте поле `rules: []` пустым. Это делает манифест чище и предотвращает путаницу между тем, что задано статически, а что пришло динамически.
4. **Документирование меток:** Ведите внутренний реестр используемых меток агрегации, чтобы избежать конфликтов между разными командами или Helm-чартами.
5. **Защита от Label Squatting (Захват меток):** Любой пользователь с правами `create clusterrole` может добавить системную метку (например, `aggregate-to-admin: "true"`) и расширить права всех администраторов кластера. Ограничивайте права на создание ClusterRole только для доверенных лиц.
6. **Версионирование модулей:** Используйте Git для хранения манифестов агрегируемых ролей. Это обеспечивает аудит изменений и упрощает откат.
7. **Тестирование в CI/CD:** Добавьте проверку агрегации в пайплайны (например, `kubectl get clusterrole <aggregator> -o json | jq '.rules' | grep -q "target-resource"`).
8. **Мониторинг агрегации:** Регулярно проверяйте, что итоговые роли содержат ожидаемые правила. Используйте `kubectl auth can-i --list` для валидации.

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)** — архитектура управления доступом.
- **[Определение ролей (Role и ClusterRole)](./roles.md)** — описание базовых объектов.
- **[Привязки ролей (RoleBinding)](./bindings.md)** — назначение прав субъектам.
- **[RBAC-паттерны: per-namespace роли в GitOps](./gitops_rbac_patterns.md)** — иерархическая модель ролей (view → developer → devops) с развёртыванием через GitOps и Kustomize.
- **[Kyverno: Агрегированные роли](../kyverno/additional.md)** — практическое применение агрегации в контроллерах.
- **[OPA Gatekeeper: RBAC для контроллеров](./rbac_overview.md#rbac-для-opa-gatekeeper)** — назначение прав Gatekeeper/Kyverno.
