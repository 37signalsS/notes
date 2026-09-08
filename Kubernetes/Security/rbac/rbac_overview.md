# Обзор управления доступом на основе ролей (RBAC)

## Определения

**RBAC (Role-Based Access Control — управление доступом на основе ролей)** — основной механизм авторизации в Kubernetes, обеспечивающий гранулярное управление доступом субъектов к ресурсам кластера через декларативные правила.

Ключевые сущности:

- **Субъект (Subject)** — "Кто" запрашивает доступ: [User, Group или ServiceAccount](./subjects.md).
- **Роль (Role)** — "Что" разрешено: набор правил и глаголов ([Role](./roles.md) или [ClusterRole](./roles.md)).
- **Привязка (Binding)** — "Связь": сопоставление субъекта с ролью ([RoleBinding](./bindings.md) или [ClusterRoleBinding](./bindings.md)).

Подробное описание каждой сущности приведено в соответствующих разделах. Данный документ описывает общую архитектуру и логику работы системы.

---

## Основные концепции

### Полный конвейер обработки запроса (Request Pipeline)

Каждый запрос к API-серверу проходит через четыре последовательных этапа контроля:

```text
ЗАПРОС КЛИЕНТА
     ↓
1. АУТЕНТИФИКАЦИЯ (Authentication)
   ├── Успешно → определена личность (User/SA/Anonymous)
   └── Неудача → 401 Unauthorized (запрос отклонён, в etcd не идёт)
     ↓
2. АВТОРИЗАЦИЯ (Authorization) — RBAC проверяет права
   ├── Allow → запрос передаётся дальше
   ├── No Opinion → переход к следующему модулю
   └── Deny (все модули отказали) → 403 Forbidden
     ↓
3. КОНТРОЛЬ ДОПУСКА (Admission Control)
   ├── Mutating: модификация объекта (инъекция sidecar, default values)
   ├── Validating: проверка политик (PSA, квоты, OPA)
   └── Отклонение любого контроллера → 403 Forbidden
     ↓
4. СОХРАНЕНИЕ В etcd
```

- **Аутентификация (Authentication):** Идентификация личности. Устанавливается, кто отправляет запрос. Подробнее: **[Аутентификация в Kubernetes](../authentication.md)**.
- **Авторизация (Authorization):** Проверка прав. Система проверяет, разрешено ли установленному субъекту выполнить конкретное действие над ресурсом. Детали алгоритма — см. ниже.
- **Контроль допуска (Admission Control):** Финальная проверка и модификация запроса (например, проверка лимитов, применение политик безопасности). Важным компонентом здесь является плагин `NodeRestriction`, ограничивающий права Kubelet. Подробнее: **[Контроллеры допуска](../Concepts/admission_controllers.md)**.

### Цепочка модулей авторизации

Запросы проверяются модулями авторизации последовательно. Если один из модулей разрешает запрос (`Allow`), проверка прекращается, и запрос передается дальше. Если модуль не может принять решение (`No Opinion`), запрос переходит к следующему. Если все модули отказали — возвращается ошибка `403 Forbidden`.

Типовой порядок (флаг `--authorization-mode`):
`Node -> RBAC -> Webhook`

- **Node:** Специализированный модуль для узлов (Kubelet). Разрешает Kubelet доступ только к тем ресурсам (Pods, Secrets, ConfigMaps), которые запущены на данном узле.
- **RBAC:** Основной декларативный механизм управления доступом.
- **Webhook:** Вызов внешней системы (например, OPA Gatekeeper или кастомный сервис) для принятия решения.
- **[ABAC](./abac.md):** Устаревший механизм на основе локального JSON-файла. Не рекомендуется для динамических сред.

**Настройка цепочки:**
```bash
# Классический способ (флаг --authorization-mode)
--authorization-mode=Node,RBAC

# Современный способ (v1.30+, файл конфигурации)
--authorization-config=/etc/kubernetes/authorization-config.yaml
```

Файл конфигурации (`AuthorizationConfiguration` v1):
```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: AuthorizationConfiguration
authorizationModes:
- type: Node
- type: RBAC
- type: Webhook
  webhook:
    authorizedTTL: 5m0s
    failedTTL: 30s
    connectionInfo:
      insecure: false
      caBundle: ""
      url: https://external-authz.example.com/authorize
```

### Алгоритм проверки RBAC

Когда запрос доходит до модуля RBAC, выполняется следующий процесс:

1. **Сбор атрибутов запроса:**
   - Субъект: `user.username`, `user.groups`
   - Действие: HTTP-метод (`GET` → `get`, `POST` → `create`, `PUT` → `update`, `DELETE` → `delete`)
   - Ресурс: тип ресурса и API-группа из URL (`/api/v1/namespaces/{ns}/pods` → resource=pods, apiGroup="", namespace={ns})
   - Namespace: из URL или пустой (для кластерных ресурсов)

2. **Поиск подходящих RoleBinding/ClusterRoleBinding:**
   - Для namespace-ресурсов: ищутся RoleBinding в этом namespace + все ClusterRoleBinding
   - Для кластерных ресурсов: ищутся только ClusterRoleBinding

3. **Проверка each binding:**
   - Если субъект (User/Group/SA) упомянут в `subjects` привязки → извлекается `roleRef.name`
   - Загружается соответствующая Role/ClusterRole
   - Проверяется, есть ли среди `rules` роли правило, совпадающее с атрибутами запроса (apiGroup, resource, verb, resourceNames)

4. **Принятие решения:**
   - Если **хотя бы одно** правило в **хотя бы одной** роли совпало → `Allow`
   - Если ни одно правило не совпало → `No Opinion` (запрос передаётся следующему модулю)
   - Если все модули вернули `No Opinion` → `403 Forbidden`

**Важно:** RBAC не имеет механизма запрета (deny). Если хотя бы одна привязка разрешает действие — оно разрешено. Нельзя «перекрыть» широкую роль более узкой.

### Модель разрешений

RBAC в Kubernetes основан на двух фундаментальных принципах:

1. **Аддитивность (Additive only):** Права только суммируются. Нельзя создать правило, которое явно "запрещает" доступ. Если субъекту выданы права администратора через одну привязку, вы не сможете "отобрать" право на удаление секретов через другую привязку.
2. **Закрытый мир (Deny by default):** Всё, что явно не разрешено — запрещено. При отсутствии подходящего правила API-сервер всегда отклоняет запрос.

Логика доступа строится по схеме:
**Субъект + Действие (Verb) + Ресурс + Область видимости (Namespace/Cluster)**.

### Основные объекты RBAC

| Объект | Уровень | Назначение | SSoT |
|--------|---------|------------|------|
| **Role** | Namespace | Права на ресурсы внутри одного пространства имён. | [Детально](./roles.md) |
| **ClusterRole** | Cluster | Права на кластерные ресурсы (Nodes, PV) или все Namespace. | [Детально](./roles.md) |
| **RoleBinding** | Namespace | Локальная привязка Role/ClusterRole к субъекту. | [Детально](./bindings.md) |
| **ClusterRoleBinding** | Cluster | Глобальная привязка ClusterRole на весь кластер. | [Детально](./bindings.md) |

#### Подресурсы (Subresources)
Для тонкого управления используются подресурсы, указываемые через `/`: `pods/log`, `pods/exec`, `nodes/metrics`. Права на основной ресурс (например, `pods`) **не дают** автоматического доступа к его подресурсам.

#### Соответствие HTTP-методов и RBAC-глаголов

| HTTP-метод | RBAC-глагол | Пример URL |
|-----------|-------------|-----------|
| `GET` | `get` | `/api/v1/namespaces/{ns}/pods/{name}` |
| `GET` (список) | `list` | `/api/v1/namespaces/{ns}/pods` |
| `WATCH` | `watch` | `/api/v1/namespaces/{ns}/pods?watch=true` |
| `POST` | `create` | `/api/v1/namespaces/{ns}/pods` |
| `PUT` | `update` | `/api/v1/namespaces/{ns}/pods/{name}` |
| `PATCH` | `patch` | `/api/v1/namespaces/{ns}/pods/{name}` |
| `DELETE` | `delete` | `/api/v1/namespaces/{ns}/pods/{name}` |
| `DELETE` (коллекция) | `deletecollection` | `/api/v1/namespaces/{ns}/pods` |

---

## Практические сценарии

### Проверка прав и Discovery API

RBAC напрямую влияет на то, что пользователь видит через `kubectl`.

1. **Проверка прав через CLI:**
   ```bash
   # Могу ли я создавать деплойменты?
   kubectl auth can-i create deployments

   # Проверка прав другого пользователя (требуются права администратора)
   kubectl auth can-i get secrets --as=dev-user -n staging

   # Проверка доступа к конкретному ресурсу по имени
   kubectl auth can-i get configmaps/app-config -n production

   # Проверка прав ServiceAccount
   kubectl auth can-i list pods \
     --as=system:serviceaccount:production:my-app-sa \
     -n production

   # Просмотр всех разрешений субъекта
   kubectl auth can-i --list \
     --as=system:serviceaccount:production:my-app-sa \
     -n production

   # Проверка с группами (OIDC/LDAP)
   kubectl auth can-i get pods --as=jane@example.com --as-group=developers -n dev

   # Проверка доступа к нересурсному URL
   kubectl auth can-i get /healthz

   # Тихий режим для скриптов (exit code 0/1)
   kubectl auth can-i create secrets --quiet && echo "yes" || echo "no"
   ```

2. **Влияние на Discovery:**
   Если у пользователя нет прав на `list` или `get` для определенного типа ресурса, API-сервер может скрыть информацию о существовании этого ресурса в Discovery API. Это приводит к ошибкам вида `the server doesn't have a resource type "X"`, хотя ресурс в кластере присутствует.

### Типовая изоляция (Namespacing)

Для изоляции команд в мультитенантных средах используется стратегия **«Минимально необходимых прав»** с разделением на три уровня:

1.  **Уровень 1 — Платформенная команда (Cluster Admin):**
    *   Полный доступ к API (`verbs: ["*"]` в `ClusterRoleBinding`).
    *   Управление инфраструктурой, узлами, PV и общими сервисами кластера.
2.  **Уровень 2 — Тимлиды (Namespace Admin):**
    *   Права администратора внутри конкретного Namespace (`RoleBinding` к стандартной роли `admin`).
    *   Возможность управлять всеми ресурсами команды, но без доступа к ресурсам уровня кластера и чужим Namespace.
3.  **Уровень 3 — Разработчики (Namespace Developer):**
    *   Ограниченные права на деплой и отладку (`get`, `list`, `watch`, `create`, `update`, `patch`).
    *   Запрет на изменение RBAC-правил, квот ресурсов и создание PersistentVolumes.

#### Пример Role для разработчика (Namespace Developer):
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: namespace-developer
  namespace: payments-production
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets", "statefulsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["pods", "pods/log", "pods/exec", "services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"] # Только чтение, без создания/удаления
```

### RBAC для разных рабочих нагрузок

#### RBAC для операторов и контроллеров

Операторы и контроллеры обычно работают от имени ServiceAccount и требуют доступа к watched-ресурсам:

```yaml
# Роль для оператора, управляющего деплойментами
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-operator
  namespace: operator-ns
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "deployments/status"]
  verbs: ["get", "list", "watch", "update", "patch"]
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

#### RBAC для CI/CD пайплайнов

CI/CD система (GitLab Runner, Jenkins) нуждается в правах на деплой, но не на управление RBAC:

```yaml
# ClusterRole для CI/CD (ограниченный edit)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ci-deployer
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
# RoleBinding для CI/CD в production namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deployer
  namespace: production
subjects:
- kind: ServiceAccount
  name: ci-deployer
  namespace: ci-system
roleRef:
  kind: ClusterRole
  name: ci-deployer
  apiGroup: rbac.authorization.k8s.io
```

#### RBAC для систем мониторинга (Prometheus)

Prometheus требует доступа к метрикам из всех namespace:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-metrics
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/metrics", "services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get"]
- nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-binding
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: prometheus-metrics
  apiGroup: rbac.authorization.k8s.io
```

#### RBAC для Ingress-контроллеров

Ingress-контроллеры (NGINX, Traefik) требуют доступа к specific ресурсам:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ingress-controller
rules:
- apiGroups: [""]
  resources: ["services", "endpoints", "pods", "secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses/status"]
  verbs: ["update"]
```

### RBAC для Custom Resource Definitions (CRD)

Для работы с кастомными ресурсами необходимо указывать их API-группу:

```yaml
# Роль для пользователя cert-manager
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cert-manager-viewer
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers"]
  verbs: ["get", "list", "watch"]
---
# Роль для администратора CRD
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: my-crd-admin
rules:
- apiGroups: ["mycompany.com"]
  resources: ["myresources", "myresources/status"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["mycompany.com"]
  resources: ["myresources/finalizers"]
  verbs: ["update"]
```

### RBAC для Admission Webhooks

Вебхук-контроллеры требуют доступа к specific ресурсам для проверки:

```yaml
# RBAC для OPA Gatekeeper
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gatekeeper-manager
rules:
- apiGroups: ["templates.gatekeeper.sh"]
  resources: ["constrainttemplates", "constrainttemplates/status"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["constraints.gatekeeper.sh"]
  resources: ["*"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods", "services", "configmaps"]
  verbs: ["get", "list", "watch"]
```

### Диагностика и аудит RBAC

#### Полный рабочий процесс аудита

```bash
# 1. Найти все привязки для субъекта
kubectl get rolebindings,clusterrolebindings -A -o wide | grep my-app-sa

# 2. Просмотреть детали привязки
kubectl get rolebinding <name> -n <ns> -o yaml

# 3. Проверить фактические права субъекта
kubectl auth can-i --list --as=system:serviceaccount:production:my-app-sa -n production

# 4. Проверить конкретное действие
kubectl auth can-i get secrets/my-secret \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# 5. Найти все RoleBinding в конкретном namespace
kubectl get rolebindings -n <ns> -o custom-columns=\
'NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name'

# 6. Найти ClusterRoleBinding для конкретной ClusterRole
kubectl get clusterrolebindings -o json | \
  jq -r '.items[] | select(.roleRef.name=="cluster-admin") | .subjects'

# 7. Проверить, какие SA используются в подах
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: {.spec.serviceAccountName}{"\n"}{end}'

# 8. Найти "осиротевшие" привязки (roleRef указывает на несуществующую роль)
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r '.items[] | select(.roleRef.kind=="Role") | select(.roleRef.name as $r | [roles[] | .metadata.name] | index($r) | not) | "\(.metadata.namespace)/\(.metadata.name) -> \(.roleRef.name)"'
```

#### Выявление избыточных привилегий

```bash
# Найти все cluster-admin привязки (кроме системных)
kubectl get clusterrolebindings -o json | \
  jq -r '.items[] | select(.roleRef.name=="cluster-admin" and (.subjects[]?.name | test("^system:") | not)) | "\(.metadata.name): \(.subjects[].name)"'

# Найти RoleBinding с wildcard-ролями
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r '.items[] | select(.roleRef.name | test("\\*")) | "\(.metadata.namespace)/\(.metadata.name) -> \(.roleRef.name)"'

# Найти SA с доступом ко всем секретам
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r '.items[] | select(.roleRef.name=="cluster-admin") | "\(.metadata.namespace)/\(.metadata.name): \(.subjects[] | "\(.kind)/\(.name)")"'
```

#### Исправление расхождений (Drift Detection)

```bash
# kubectl auth reconcile — применяет манифест и удаляет лишние правила
# Полезно для GitOps: сравнивает текущее состояние с файлом
kubectl auth reconcile -f rbac-manifests.yaml

# Применение с выводом изменений
kubectl auth reconcile -f rbac-manifests.yaml --dry-run=client

# Применение только RoleBinding (без Role)
kubectl auth reconcile -f rolebinding.yaml --output=roles=false
```

### RBAC и OIDC-интеграция

При использовании OIDC группы из токена автоматически становятся субъектами RBAC:

```yaml
# OIDC-группа "platform-admins" → ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: oidc-platform-admins
subjects:
- kind: Group
  name: platform-admins  # Имя группы из OIDC-токена
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: admin
  apiGroup: rbac.authorization.k8s.io
---
# OIDC-группа "developers" → RoleBinding в dev namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: oidc-developers
  namespace: development
subjects:
- kind: Group
  name: developers  # Имя группы из OIDC-токена
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
```

### Масштабирование и производительность

#### Ограничения по масштабу

| Ресурс | Ограничение | Рекомендация |
|--------|-------------|--------------|
| Roles/ClusterRoles | ~10,000 объектов | Используйте агрегацию для группировки |
| RoleBindings/ClusterRoleBindings | ~10,000 объектов | Привязывайте к группам, а не к пользователям |
| Правил на Role | ~1,000 правил | Используйте `*` для общих правил (осторожно) |
| Время проверки | ~1мс на запрос | При 10K+ привязках может вырасти |

#### Оптимизации

1. **Агрегация ClusterRole:** Вместо создания тысяч RoleBinding используйте агрегацию ClusterRole для группировки правил.
2. **Группы вместо пользователей:** Привязывайте роли к группам (OIDC/LDAP), а не к отдельным пользователям.
3. **Namespace-scoped привязки:** Используйте RoleBinding вместо ClusterRoleBinding, где это возможно.
4. **Кэширование:** API-сервер кэширует результаты проверки RBAC (TTL ~5-30 секунд). Избегайте частых изменений привязок.

---

## Дополнительная информация

### Ограничения RBAC

Несмотря на гибкость, RBAC имеет ряд ограничений, которые необходимо учитывать при проектировании безопасности:

- **Отсутствие условий (Conditions):** Нельзя разрешить доступ "только в рабочее время" или "только если IP-адрес входит в белый список". Для этих сценариев используют Admission Webhooks.
- **Слепота к контенту (Payload Blindness):** RBAC проверяет право на `create pods`, но не может проверить, что в этом поде не используется `privileged: true`. Эти задачи решаются через **[Admission Controllers](../../Concepts/admission_controllers.md)** или **[OPA/Kyverno](./limitations_opa.md)**.
- **Масштабируемость:** Большое количество RoleBindings может замедлять работу API-сервера при проверке прав (см. раздел «Масштабирование» выше).
- **Отсутствие deny-правил:** Нельзя явно запретить действие. Если хотя бы одна привязка разрешает — оно разрешено.
- **Фиксированные глаголы:** Нельзя определить собственные глаголы (например, `deploy` или `rollback`). RBAC работает только с предопределенным набором.

### Безопасность и Hardening

- **Переход к PSA:** Механизм PodSecurityPolicy (PSP) удален. Используйте **Pod Security Admission (PSA)** на уровне меток Namespace. Подробнее: **[Контроллеры допуска](../../Concepts/admission_controllers.md)** и **[Pod Security Context](../pod_security_context.md)**.
- **Безопасные токены:** С версии v1.24 используются `Bound Tokens` с ограниченным TTL. Избегайте использования статических секретов ServiceAccount.
- **Принцип наименьших привилегий:** Избегайте использования `*` в правилах. Всегда ограничивайте доступ конкретными API-группами и ресурсами.
- **Не используйте `system:masters`:** Членство в этой группе обходит все проверки RBAC. Используйте привязку к `cluster-admin`.
- **Аудит:** Регулярно проверяйте права инструментами `rakkess`, [kubescape](../kubescape_overview.md) или `kor`.
- **GitOps для RBAC:** Храните манифесты Role/RoleBinding в Git и применяйте через CD-пайплайн. Используйте `kubectl auth reconcile` для выявления расхождений.

### Советы для собеседования

> **Вопрос:** Как работает проверка RBAC в Kubernetes?
> **Ответ:** API-сервер собирает атрибуты запроса (субъект, действие, ресурс, namespace), ищет все RoleBinding в namespace + все ClusterRoleBinding, проверяет каждую привязку. Если хотя бы одно правило в хотя бы одной роли совпало с атрибутами запроса — разрешено. Если ни одно не совпало — запрещено.

> **Вопрос:** Можно ли запретить действие через RBAC?
> **Ответ:** Нет. RBAC работает по принципу «аддитивности» — права только суммируются. Нет механизма deny. Если одна привязка разрешает `delete pods`, а другая — нет, пользователь сможет удалять поды.

> **Вопрос:** Чем ClusterRole + RoleBinding отличается от Role + RoleBinding?
> **Ответ:** ClusterRole + RoleBinding: роль определяет правила (включая кластерные ресурсы), но привязка ограничивает область действия одним namespace. Role + RoleBinding: роль и привязка работают только в одном namespace. ClusterRole + RoleBinding — это способ «превратить» глобальную роль в локальную.

> **Вопрос:** Что такое `kubectl auth reconcile`?
> **Ответ:** Инструмент для приведения фактических RBAC-прав к ожидаемым из манифеста. Сравнивает текущее состояние с файлом, применяет изменения и удаляет лишние правила. Полезен для GitOps и обнаружения drift'а.

> **Вопрос:** Как проверить, почему субъект не имеет доступа?
> **Ответ:** Пошагово: (1) `kubectl get rolebindings,clusterrolebindings -A | grep <subject>` — есть ли привязка? (2) `kubectl auth can-i --list --as=<subject>` — какие права? (3) `kubectl auth can-i <verb> <resource> --as=<subject>` — конкретное действие? (4) Проверить, что SA пода совпадает с SA в привязке.

### Связанные темы

- **[Роли и ClusterRole (Детально)](./roles.md)**
- **[Привязки ролей (Детально)](./bindings.md)**
- **[Субъекты доступа (Детально)](./subjects.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
- **[Ограничения RBAC и OPA Gatekeeper](./limitations_opa.md)**
- **[Программная проверка прав: AccessReview API](./authorization_review_api.md)**
- **[Атаки через эскалацию привилегий](./privilege_escalation.md)**
- **[RBAC для ResourceQuota и LimitRange](./resource_quota_rbac.md)**
- **[Multi-cluster RBAC](./multi_cluster_rbac.md)**
- **[Аудит событий API](../audit.md)**
- **[Аутентификация в Kubernetes](../authentication.md)**
- **[Контроллеры допуска](../../Concepts/admission_controllers.md)**
- **[Диагностика ошибок доступа](../../Troubleshooting/Common_Errors/ApiAccessForbidden/diagnostics.md)**
