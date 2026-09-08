# Программная проверка прав: AccessReview API

## Определения

**AccessReview API** — семейство ресурсов Kubernetes API, позволяющих программно проверять права доступа субъектов к ресурсам кластера. Используются для аудита, отладки и построения кастомных систем авторизации.

Три основных типа запросов:

- **SelfSubjectAccessReview** — проверяет, разрешено ли **текущему пользователю** (аутентифицированному субъекту) выполнять указанное действие над ресурсом. Не требует специальных прав. Используется для быстрой проверки «могу ли я?».
- **SelfSubjectRulesReview** — возвращает **полный список** разрешений текущего пользователя в указанном namespace. Полезен для отображения пользователю его прав (аналог `kubectl auth can-i --list`).
- **SubjectAccessReview** — проверяет, разрешено ли **указанному пользователю/группе/ServiceAccount** выполнять действие. Требует特权 прав (обычно `system:basic-user` или `cluster-admin`). Используется для аудита и отладки прав других субъектов.

**Ключевое отличие от `kubectl auth can-i`:** `can-i` — это CLI-обёртка над этими API. Программный доступ через API позволяет строить автоматизированные системы аудита, веб-интерфейсы и интеграции с CI/CD.

---

## Основные концепции

### Структура запроса и ответа

Все три типа используют одинаковую структуру Spec:

```yaml
apiVersion: authorization.k8s.io/v1
kind: SelfSubjectAccessReview  # или SubjectAccessReview, SelfSubjectRulesReview
spec:
  # Для SelfSubjectAccessReview и SubjectAccessReview:
  resourceAttributes:
    namespace: "production"     # Namespace ресурса (пусто для кластерных)
    verb: "get"                 # Действие: get, list, watch, create, update, patch, delete
    group: ""                   # API-группа (пусто для core)
    resource: "pods"            # Тип ресурса (во множественном числе)
    name: "my-pod"              # Имя конкретного ресурса (опционально)
    subresource: "log"          # Подресурс (опционально)

  # Только для SubjectAccessReview:
  user: "alice@example.com"     # Имя пользователя
  groups:
    - "developers"              # Группы
  # или
  # serviceAccount:
  #   name: "my-sa"
  #   namespace: "production"
```

Структура ответа:

```yaml
status:
  allowed: true          # true/false — разрешено или запрещено
  denied: false          # true если явно отказано (встречается редко)
  reason: "..."          # Текстовое описание решения (для аудита)
  evaluationError: ""    # Ошибка при проверке (если была)
```

Для `SelfSubjectRulesReview` ответ содержит список правил:

```yaml
status:
  resourceRules:         # Правила для ресурсов
  - verbs: ["get", "list", "watch"]
    apiGroups: [""]
    resources: ["pods", "services"]
    resourceNames: []
    namespaces: ["production"]
  nonResourceRules:      # Правила для non-resource URLs
  - verbs: ["get"]
    nonResourceURLs: ["/healthz", "/version"]
```

### Сравнение трёх типов

| Критерий | SelfSubjectAccessReview | SelfSubjectRulesReview | SubjectAccessReview |
|----------|------------------------|----------------------|-------------------|
| **Кто проверяется** | Текущий субъект | Текущий субъект | Любой указанный субъект |
| **Формат ответа** | allowed: true/false | Список всех правил | allowed: true/false |
| **Требуемые права** | Нет (базовые) | `system:basic-user` | `system:basic-user` или `cluster-admin` |
| **Типичное использование** | Проверка конкретного действия | Отображение прав пользователю | Аудит прав других субъектов |
| **Аналог CLI** | `kubectl auth can-i <verb> <resource>` | `kubectl auth can-i --list` | `kubectl auth can-i <verb> <resource> --as=<user>` |

### Флаги kube-apiserver

Для работы AccessReview API необходимы соответствующие флаги аутентификации:

| Флаг | Назначение |
|------|-----------|
| `--anonymous-auth=true/false` | Включает/выключает анонимную аутентификацию. Анонимные субъекты получают UID `system:anonymous` и группу `system:unauthenticated`. |
| `--authorization-mode=RBAC` | Активирует модуль RBAC для проверки прав. |

---

## Практические сценарии

### Проверка своих прав (SelfSubjectAccessReview)

```bash
# 1. Can-I через API (программный аналог kubectl auth can-i)
kubectl create --raw /apis/authorization.k8s.io/v1/selfsubjectaccessreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SelfSubjectAccessReview
spec:
  resourceAttributes:
    namespace: production
    verb: get
    resource: pods
EOF
# → {"status":{"allowed":true,"reason":""}}
```

### Проверка прав другого пользователя (SubjectAccessReview)

```bash
# Проверка: может ли alice создавать деплойменты в production?
kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
spec:
  resourceAttributes:
    namespace: production
    verb: create
    group: apps
    resource: deployments
  user: alice@example.com
  groups:
    - developers
EOF
# → {"status":{"allowed":false,"reason":"denied by RBAC"}}
```

### Полный список прав текущего пользователя (SelfSubjectRulesReview)

```bash
# Все разрешения в namespace production
kubectl create --raw /apis/authorization.k8s.io/v1/selfsubjectrulesreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SelfSubjectRulesReview
spec:
  namespace: production
EOF
```

Ответ содержит массив `resourceRules` и `nonResourceRules`. Для анализа в скриптах:

```bash
# Извлечь все разрешенные ресурсы
kubectl create --raw /apis/authorization.k8s.io/v1/selfsubjectrulesreviews \
  -f - <<EOF | jq -r '.status.resourceRules[] | "\(.verbs) \(.apiGroups)/\(.resources)"'
apiVersion: authorization.k8s.io/v1
kind: SelfSubjectRulesReview
spec:
  namespace: production
EOF
```

### Аудит прав ServiceAccount (SubjectAccessReview)

```bash
# Проверка: может ли SA "ci-deployer" в namespace "ci" удалять секреты в production?
kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
spec:
  resourceAttributes:
    namespace: production
    verb: delete
    resource: secrets
  user: system:serviceaccount:ci:ci-deployer
EOF
```

### Автоматический аудит через скрипт

```bash
#!/bin/bash
# audit_sa_permissions.sh — проверка избыточных прав SA
NAMESPACE="${1:-production}"
SA_NAME="${2:-default}"

# Получить список всех ClusterRoleBinding, содержащих этот SA
echo "=== ClusterRoleBinding для SA $SA_NAME ==="
kubectl get clusterrolebindings -o json | \
  jq -r --arg sa "$SA_NAME" --arg ns "$NAMESPACE" \
  '.items[] | select(.subjects[]? | .kind=="ServiceAccount" and .name==$sa and .namespace==$ns) |
   "\(.metadata.name) -> \(.roleRef.name)"'

# Проверить конкретные опасные действия
DANGEROUS_VERBS=("delete" "create" "update" "patch" "impersonate" "bind" "escalate")
DANGEROUS_RESOURCES=("secrets" "clusterroles" "clusterrolebindings" "roles" "rolebindings" "namespaces")

for verb in "${DANGEROUS_VERBS[@]}"; do
  for resource in "${DANGEROUS_RESOURCES[@]}"; do
    RESULT=$(kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews -f - <<EOF 2>/dev/null | jq -r '.status.allowed'
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
spec:
  resourceAttributes:
    verb: $verb
    resource: $resource
  user: system:serviceaccount:${NAMESPACE}:${SA_NAME}
EOF
    )
    if [ "$RESULT" = "true" ]; then
      echo "[DANGER] SA $SA_NAME has: $verb $resource"
    fi
  done
done
```

### Проверка доступа к конкретному имени ресурса

```bash
# Разрешен ли доступ к конкретному Secret по имени?
kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
spec:
  resourceAttributes:
    namespace: production
    verb: get
    resource: secrets
    name: database-password
  user: system:serviceaccount:myapp:my-sa
EOF
```

### Проверка non-resource URLs

```bash
# Разрешен ли доступ к /healthz для неаутентифицированных пользователей?
kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews \
  -f - <<EOF
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
spec:
  nonResourceAttributes:
    path: /healthz
    verb: get
  user: system:anonymous
  groups:
    - system:unauthenticated
EOF
```

### Интеграция с Prometheus (метрики доступа)

```yaml
# Пример ServiceMonitor для сбора метрик RBAC
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kube-apiserver-rbac
  namespace: monitoring
spec:
  selector:
    matchLabels:
      component: kube-apiserver
  endpoints:
  - port: https
    scheme: https
    tlsConfig:
      caFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    path: /metrics
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: 'apiserver_authorization_(.*)'
      action: keep
```

---

## Дополнительная информация

### Ограничения

- **Нет механизма отзыв:** если пользователь имеет права через RBAC, они действуют до тех пор, пока привязка не будет удалена. AccessReview не может «отозвать» доступ — он только проверяет текущее состояние.
- **Кэширование:** API-сервер кэширует RBAC-данные (TTL ~5-30 секунд). Результаты AccessReview могут быть «свежими» с задержкой.
- **SubjectAccessReview требует特权:** обычный пользователь не может проверить права другого пользователя (это раскроет информацию о правах). Только `system:basic-user` и выше.

### Используемые API-группы

| API-группа | Ресурс | Назначение |
|-----------|--------|-----------|
| `authorization.k8s.io/v1` | `selfsubjectaccessreviews` | Проверка своих прав |
| `authorization.k8s.io/v1` | `selfsubjectrulesreviews` | Список всех своих правил |
| `authorization.k8s.io/v1` | `subjectaccessreviews` | Проверка прав других субъектов |

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — общий алгоритм проверки прав
- **[Субъекты доступа](./subjects.md)** — типы субъектов (Users, Groups, ServiceAccount)
- **[Роли и ClusterRole](./roles.md)** — структура разрешений
