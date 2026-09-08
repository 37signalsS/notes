# CreateContainerConfigError: Проблемы с RBAC и ServiceAccount

## Определения

**RBAC-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки конфигурации, когда `kubelet` не может получить доступ к необходимым ресурсам (Secret, ConfigMap) или подготовить токены аутентификации из-за ограничений безопасности или ошибок конфигурации прав доступа.

Хотя `kubelet` обладает собственной системной идентичностью, современные механизмы безопасности (NodeRestriction, Bound Service Account Tokens) делают процесс разрешения зависимостей пода чувствительным к настройкам **RBAC (Role-Based Access Control)** и **ServiceAccount**.

### Связь с другими файлами серии

| Файл | Фокус |
| :--- | :--- |
| [definitions.md](./definitions.md) | Общие определения CreateContainerConfigError, жизненный цикл, таймауты |
| [diagnostics.md](./diagnostics.md) | Общий алгоритм диагностики всех причин CreateContainerConfigError |
| [prevention.md](./prevention.md) | Профилактика, CI/CD валидация, Admission-политики |
| **Данный файл** | RBAC-специфичные причины, диагностика, исправление |

---

## Основные концепции

### Архитектура RBAC и его влияние на поды

RBAC в Kubernetes работает по принципу **аддитивности** (права только суммируются) и **закрытого мира** (всё, что явно не разрешено — запрещено). Каждый запрос к API-серверу проходит три модуля авторизации: `Node → RBAC → Webhook`. Если хотя бы один модуль разрешает запрос (`Allow`), проверка прекращается. Если все модули вернули `No Opinion` — возвращается `403 Forbidden`.

**Ключевой нюанс для CreateContainerConfigError:** `kubelet` при разрешении зависимостей пода использует свою системную идентичность, но при этом ограничен правами ServiceAccount пода для доступа к Secret/ConfigMap. Это создает situation, когда даже технически корректная RoleBinding может не работать из-за несовпадения namespace, имени ServiceAccount или отсутствия конкретного глагола `get`.

### Механизмы ограничения доступа

1.  **Admission-контроллер NodeRestriction:**
    Ограничивает возможности `kubelet` по получению объектов `Secret` и `ConfigMap`. `kubelet` может прочитать только те ресурсы, которые используются подами, **запланированными на данный конкретный узел**. Если планировщик или API-сервер имеют несогласованность, `kubelet` получит отказ в доступе (403 Forbidden), что приведет к `CreateContainerConfigError`.

    ```text
    kubelet → API-сервер → NodeRestriction проверяет:
    ├── Под назначен на этот узел? → Да → доступ разрешен
    └── Под НЕ на этом узле? → 403 Forbidden
    ```

2.  **Проекция токенов (ServiceAccountToken Projection):**
    Начиная с K8s 1.22+, токены ServiceAccount не хранятся в вечных секретах, а генерируются динамически через проецируемые тома через **TokenRequest API**. Ошибки в настройках API-сервера (`--service-account-issuer`, `--service-account-key-file`) или отсутствие прав на создание `TokenReview` могут заблокировать формирование конфигурации контейнера.

    ```yaml
    # Пример projected volume для токена ServiceAccount
    volumes:
    - name: kube-api-access
      projected:
        sources:
        - serviceAccountToken:
            path: token
            expirationSeconds: 3607
            audience: api
    ```

    **Важно:** Начиная с K8s 1.24+ автоматическое создание Secret-объектов для ServiceAccount токенов отключено. Если приложению нужен долгоживущий токен, его необходимо создавать явно через манифест с аннотацией `kubernetes.io/service-account.name`.

3.  **Изоляция через Namespace:**
    Ресурсы (Secret, ConfigMap, PVC) и ServiceAccount **всегда** должны находиться в одном и том же Namespace. RBAC-роли (`Role`) также ограничиваются пространством имен, если не используются `ClusterRole`.

4.  **Aggregated ClusterRoles:**
    Механизм группировки правил через метки (labels). Если ваш ServiceAccount использует агрегированную роль, убедитесь, что метки агрегации корректны и базовая роль существует.

    ```yaml
    # Пример: агрегированная ClusterRole для мониторинга
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
      name: monitoring-endpoints
      labels:
        rbac.example.com/aggregate-to-monitoring: "true"
    rules:
    - apiGroups: [""]
      resources: ["services", "endpoints", "pods"]
      verbs: ["get", "list", "watch"]
    ```

### Типичные причины возникновения ошибки

| Причина | Механизм | Результат | Частота |
| :--- | :--- | :--- | :--- |
| **Отсутствие SA** | Под ссылается на `serviceAccountName`, которого нет в API | Ошибка генерации токена в `projected volume` | Высокая |
| **Namespace mismatch** | Secret/ConfigMap в другом Namespace, чем SA пода | 403 Forbidden при чтении | Очень высокая |
| **NodeRestriction** | Попытка прочитать Secret, не «привязанный» к узлу | Ошибка 403 от API-сервера для `kubelet` | Средняя |
| **CSI RBAC** | Нехватка прав у SA пода для работы с CSI-драйвером | Сбой монтирования внешнего секрета (Vault) | Средняя |
| **Automount disabled** | `automountServiceAccountToken: false` при необходимости доступа к API | Ошибка приложения (но не `CreateContainerConfigError`) | Низкая |
| **Default SA с ограничениями** | `default` SA в production namespace с `automountServiceAccountToken: false` | Под не может прочитать собственные секреты | Высокая |
| **Helm chart без SA** | Чарт не создает SA, но манифест пода ссылается на него | Токен не может быть сгенерирован | Высокая |
| **ClusterRole без RoleBinding** | SA привязан к ClusterRole, но RoleBinding отсутствует в namespace | Права не действуют в конкретном namespace | Средняя |

### Каталог типичных RBAC-ошибок

| Сообщение в Events | Категория | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `forbidden: user "system:serviceaccount:ns:sa" cannot get resource "secrets"` | RBAC | SA не имеет права `get` на secrets | Создайте Role с `verbs: ["get"]` на `secrets` и RoleBinding |
| `forbidden: user "system:serviceaccount:ns:sa" cannot list resource "configmaps"` | RBAC | SA не имеет права `list` | Добавьте `list` в Role |
| `serviceaccounts "x" not found` | Missing | ServiceAccount не существует | Создайте ServiceAccount |
| `secrets "x" is forbidden: User "system:serviceaccount:ns:sa" cannot get resource "secrets" in API group ""` | RBAC | Полный отказ в доступе к секретам | Проверьте RoleBinding и namespace |
| `error: You must be logged in to the server (Unauthorized)` | Auth | Токен SA истек или невалиден | Проверьте TokenRequest API и настройки API-сервера |
| `unable to go against TokenRequest` | Token | Ошибка генерации Bound Token | Проверьте `--service-account-issuer` на API-сервере |

## Практические сценарии

### Сценарий 1: ServiceAccount не найден или удален

Часто возникает при использовании Helm-чартов, где создание SA отключено, но имя указано вручную.

**Диагностика:**
```bash
# Проверка имени SA в поде
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'
# Проверка существования объекта
kubectl get sa <sa-name>
# → Error from server (NotFound): serviceaccounts "<sa-name>" not found

# Проверка всех SA в namespace
kubectl get sa -n <namespace>
```

**Типичная ошибка в Helm-чарте:**
```yaml
# values.yaml —-SA отключен, но имя указано
serviceAccount:
  create: false
  name: "my-custom-sa"  # Этот SA не существует в кластере
```

**Решение:**
```yaml
# Вариант 1: Включить создание SA в Helm
serviceAccount:
  create: true
  name: "my-custom-sa"

# Вариант 2: Создать SA вручную перед установкой чарта
kubectl create sa my-custom-sa -n <namespace>
```

### Сценарий 2: Namespace mismatch — Secret/ConfigMap в другом namespace

Самая частая причина RBAC-ошибок: ресурс существует, но в другом namespace, чем под.

**Диагностика:**
```bash
# Проверка namespace пода
kubectl get pod <pod-name> -o jsonpath='{.metadata.namespace}'

# Проверка existence Secret в том же namespace
kubectl get secret <secret-name> -n $(kubectl get pod <pod-name> -o jsonpath='{.metadata.namespace}')

# Проверка existence Secret во всех namespace
kubectl get secret <secret-name> -A
```

**Пример ошибки:**
```text
Events:
  Warning  Failed  5s  kubelet  Error: secret "db-creds" is forbidden: User "system:serviceaccount:production:my-app" cannot get resource "secrets" in API group "" in the namespace "production"
```

**Решение:** Убедитесь, что Secret/ConfigMap созданы в том же namespace, что и под. Если ресурс нужен из другого namespace, используйте кросс-неймспейс доступ через ClusterRole (см. Сценарий 7).

### Сценарий 3: Ошибки прав в CSI Secret Store (Vault)

При интеграции с HashiCorp Vault через CSI Secret Store Driver, права ServiceAccount критичны для этапа монтирования.

**Диагностика через impersonation (имитация прав):**
```bash
# Может ли SA "читать" секреты в своем пространстве имен?
kubectl auth can-i get secrets --as=system:serviceaccount:<namespace>:<sa-name>
# → no  <-- Если ответ 'no', монтирование тома через CSI может не сработать.

# Просмотр всех доступных действий для SA
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:<sa-name>
```

**Дополнительная проверка для Vault CSI:**
```bash
# Проверка SecretProviderClass
kubectl get secretproviderclass -n <namespace>
kubectl describe secretproviderclass <name> -n <namespace>

# Проверка логов CSI-драйвера
kubectl logs -n kube-system -l app=secrets-store-csi-driver --tail=50
```

**Типичная конфигурация RoleBinding для Vault CSI:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: vault-secrets-binding
  namespace: production
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: production
roleRef:
  kind: ClusterRole  # или Role, если Vault работает в одном namespace
  name: secret-creator  # Должен включать права на secrets
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 4: Проблемы с ServiceAccountToken в защищенных кластерах

В кластерах с жестким аудитом (PSP/Admission Policies) создание токенов может быть ограничено.

**Симптом в событиях:**
```text
Events:
  Warning  FailedMount  ...  MountVolume.SetUp failed for volume "kube-api-access-xxxx" : failed to generate token: secrets "default-token-xxxx" not found
```

**Диагностика:**
```bash
# Проверка версии кластера
kubectl version --short

# Проверка настроек API-сервера (требуется доступ к control plane)
# Ищите флаги:
#   --service-account-issuer
#   --service-account-key-file
#   --service-account-signing-key-file

# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 10 "Events:"
```

**Важно:** В версиях 1.24+ ищите ошибки, связанные с `TokenRequest` API, а не с объектами `Secret`. Автоматическое создание Secret для SA-токенов отключено.

**Решение:**
```bash
# Для K8s 1.24+ — создайте долгоживущий токен явно (если нужен)
kubectl create token <sa-name> --namespace=<namespace> --duration=24h

# Или создайте Secret с токеном декларативно
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: <sa-name>-token
  namespace: <namespace>
  annotations:
    kubernetes.io/service-account.name: <sa-name>
type: kubernetes.io/service-account-token
EOF
```

### Сценарий 5: Ограничения NodeRestriction (Для администраторов)

Если под застрял в `CreateContainerConfigError` с ошибкой `Forbidden` для `kubelet`, проверьте, что под действительно назначен на этот узел.

**Диагностика:**
```bash
# Проверка соответствия узла
kubectl get pod <pod-name> -o wide
# → NODE: node-01

# Проверка, что под действительно на этом узле
kubectl get pods -o wide | grep <pod-name>
# → pod-name   0/1   CreateContainerConfigError   0   <age>   node-01   <none>

# Проверка логов kubelet на ошибки
ssh <node-01> 'journalctl -u kubelet --since "5 min ago" | grep -i "forbidden\|rbac\|secret"'

# Проверка Event на типичные сообщения
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
```

**Если узел верный, но ошибка сохраняется:**
```bash
# Проверьте, что kubelet может читать Secret для этого пода
# (от имени системной идентичности узла)
kubectl auth can-i get secrets/<secret-name> \
  --as=system:node:<node-name> \
  --as-group=system:nodes \
  -n <namespace>
```

### Сценарий 6: Проблемы с default ServiceAccount

В production namespace `default` SA часто имеет `automountServiceAccountToken: false`, что блокирует доступ подов к API.

**Диагностика:**
```bash
# Проверка automount для default SA
kubectl get sa default -n <namespace> -o jsonpath='{.automountServiceAccountToken}'
# → false (или nil, что означает true)

# Проверка, какой SA использует под
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'
# → default (если не указан явно)

# Проверка всех SA с automount=true в namespace
kubectl get sa -n <namespace> -o json | \
  jq '.items[] | select(.automountServiceAccountToken != false) | .metadata.name'
```

**Решение:**
```bash
# Вариант 1: Включить automount для default SA
kubectl patch sa default -n <namespace> -p '{"automountServiceAccountToken": true}'

# Вариант 2 (рекомендуется): Создать отдельный SA с минимальными правами
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: <namespace>
automountServiceAccountToken: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-app-role
  namespace: <namespace>
rules:
- apiGroups: [""]
  resources: ["secrets", "configmaps"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-app-binding
  namespace: <namespace>
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: <namespace>
roleRef:
  kind: Role
  name: my-app-role
  apiGroup: rbac.authorization.k8s.io
EOF
```

### Сценарий 7: Кросс-неймспейс доступ к секретам (Cross-Namespace)

Когда приложению в namespace `production` нужны секреты из namespace `shared-config`.

**Диагностика:**
```bash
# Проверка прав в целевом namespace
kubectl auth can-i get secrets/<secret-name> \
  --as=system:serviceaccount:production:my-app-sa \
  -n shared-config
# → no (если RoleBinding не настроен)
```

**Решение — ClusterRole + RoleBinding в целевом namespace:**
```yaml
# 1. ClusterRole (общий для всех namespace)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-reader-cross-ns
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
  resourceNames: ["db-creds", "api-key"]  # Ограничьте конкретными именами!
---
# 2. RoleBinding в целевом namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cross-ns-secret-binding
  namespace: shared-config  # Целевой namespace с секретами
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: production  # Namespace пода
roleRef:
  kind: ClusterRole
  name: secret-reader-cross-ns
  apiGroup: rbac.authorization.k8s.io
```

**Важно:** `ClusterRole` без `ClusterRoleBinding` + `RoleBinding` = права только в том namespace, где создан `RoleBinding`. Это безопасный способ кросс-неймспейс доступа.

### Сценарий 8: Aggregated ClusterRoles и CreateContainerConfigError

Если ServiceAccount использует агрегированную ClusterRole, отсутствие базовой роли может блокировать доступ.

**Диагностика:**
```bash
# Проверка, какие роли агрегируются в целевую роль
kubectl get clusterrole <aggregated-role> -o jsonpath='{.metadata.labels}'

# Проверка базовых ролей с соответствующими метками
kubectl get clusterroles -l rbac.example.com/aggregate-to-monitoring=true

# Просмотр итоговых прав (включая агрегацию)
kubectl auth can-i --list --as=system:serviceaccount:<ns>:<sa-name>
```

**Типичная ошибка:**
```text
# Базовая роль удалена или метка изменена
# → Итоговая роль не содержит прав → 403 Forbidden
```

**Решение:** Убедитесь, что все базовые роли с соответствующими метками агрегации существуют и содержат необходимые правила.

## Алгоритм диагностики RBAC-ошибок

```text
CreateContainerConfigError + Forbidden/not found
│
├── 1. Проверить Events пода
│   ├── "serviceaccounts 'x' not found" → Создать ServiceAccount
│   ├── "secrets 'x' not found" → Проверить existence Secret в namespace пода
│   ├── "forbidden: ... cannot get resource 'secrets'" → RBAC (шаг 2)
│   └── "failed to generate token" → TokenRequest API (шаг 4)
│
├── 2. Проверить RBAC
│   ├── kubectl get sa <sa-name> -n <ns> → SA существует?
│   ├── kubectl get rolebindings,clusterrolebindings -A | grep <sa-name> → Binding есть?
│   ├── kubectl auth can-i get secrets --as=system:serviceaccount:<ns>:<sa> → yes/no?
│   └── Если no → создать Role + RoleBinding
│
├── 3. Проверить Namespace
│   ├── kubectl get pod <pod-name> -o jsonpath='{.metadata.namespace}'
│   ├── kubectl get secret <name> -n <pod-namespace> → существует?
│   └── Если нет → создать Secret в правильном namespace
│
├── 4. Проверить TokenRequest API (K8s 1.24+)
│   ├── kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[*].projected.sources}'
│   └── Проверить настройки API-сервера (service-account-issuer)
│
└── 5. Проверить NodeRestriction (если kubelet)
    ├── kubectl get pod <pod-name> -o wide → на каком узле?
    └── kubectl auth can-i get secrets/<name> --as=system:node:<node> -n <ns>
```

## Список проверок (Checklist)

### ServiceAccount
- [ ] ServiceAccount существует в том же Namespace, что и Pod
- [ ] Нет опечаток в поле `serviceAccountName` в PodSpec
- [ ] `automountServiceAccountToken` установлен корректно (true если нужен доступ к API)
- [ ] Default SA не используется для приложений в production

### Namespace
- [ ] Все ресурсы (Secrets, ConfigMaps) находятся в одном Namespace с Подом
- [ ] Если нужен кросс-неймспейс доступ — созданы ClusterRole + RoleBinding

### RBAC
- [ ] Role/ClusterRole существует и содержит необходимые глаголы (`get`, `list`, `watch`)
- [ ] RoleBinding привязывает Role к правильному ServiceAccount
- [ ] Для ClusterRole используется RoleBinding в конкретном namespace (не ClusterRoleBinding)
- [ ] Aggregated ClusterRoles корректно настроены (базовые роли существуют)

### Токены
- [ ] Для K8s 1.24+ — долгоживущие токены созданы явно (если необходимы)
- [ ] TokenRequest API настроен на API-сервере (`--service-account-issuer`)
- [ ] Для CSI-драйверов — SA имеет права на создание TokenReview (если требуется)

### Helm / GitOps
- [ ] В Helm-чарте включено создание ServiceAccount (`serviceAccount.create: true`)
- [ ] Имя ServiceAccount в values.yaml совпадает с тем, что создано в кластере
- [ ] При удалении/пересоздании namespace — ServiceAccount пересоздается

## Расширенная диагностика

### SubjectAccessReview — глубокая проверка прав

`SubjectAccessReview` — API-запрос, который проверяет, разрешено ли конкретному субъекту выполнить действие над ресурсом. Используется для отладки сложных RBAC-сценариев, когда `kubectl auth can-i` недостаточно.

**Сценарий использования:** Под не может прочитать Secret, но `kubectl auth can-i` возвращает `yes`. Причина — проверка идет от имени пользователя, а не от имени kubelet.

```bash
# Проверка от имени ServiceAccount (имитация)
kubectl auth can-i get secrets/db-creds \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# Просмотр всех разрешений SA
kubectl auth can-i --list \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# Проверка доступа к конкретному ресурсу по имени
kubectl auth can-i get configmaps/app-config \
  --as=system:serviceaccount:production:my-app-sa \
  -n production
```

**SubjectAccessReview через API (для скриптов):**
```yaml
# Пример запроса SubjectAccessReview
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
metadata:
  name: check-sa-access
spec:
  resourceAttributes:
    namespace: production
    verb: get
    resource: secrets
    name: db-creds
  user: system:serviceaccount:production:my-app-sa
  groups:
  - system:serviceaccounts
  - system:serviceaccounts:production
```

### TokenRequest API — современный механизм токенов

Начиная с Kubernetes 1.24+, автоматическое создание Secret для ServiceAccount токенов отключено. Токены генерируются динамически через **TokenRequest API** с ограниченным сроком жизни (TTL).

**Как это работает:**
1. `kubelet` запрашивает токен через API-сервер
2. API-сервер проверяет права SA через RBAC
3. Генерируется Bound Token с `expirationSeconds`
4. Токен монтируется в projected volume

**Типичные ошибки TokenRequest API:**
```text
# Ошибка: API-сервер не настроен для TokenRequest
Error: failed to generate token: tokenrequest: failed to create token

# Ошибка: SA не имеет права на создание TokenReview
Error: serviceaccounts "x" is forbidden: User "system:serviceaccount:ns:sa" cannot create resource "tokenreviews"
```

**Диагностика:**
```bash
# Проверка настроек API-сервера (требуется доступ к control plane)
# Ищите флаги:
#   --service-account-issuer=https://kubernetes.default.svc
#   --service-account-key-file=/etc/kubernetes/pki/sa.pub
#   --service-account-signing-key-file=/etc/kubernetes/pki/sa.key

# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 5 "Events:"

# Проверка, может ли SA создавать TokenReview
kubectl auth can-i create tokenreviews \
  --as=system:serviceaccount:<namespace>:<sa-name>
```

**Решение:**
```bash
# Для Kubernetes 1.24+ — создайте долгоживущий токен явно
kubectl create token <sa-name> --namespace=<namespace> --duration=24h

# Или создайте Secret с токеном декларативно
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: <sa-name>-token
  namespace: <namespace>
  annotations:
    kubernetes.io/service-account.name: <sa-name>
type: kubernetes.io/service-account-token
EOF
```

### Диагностика через логи kubelet

Если стандартные инструменты не помогают, проверьте логи kubelet на узле:

```bash
# SSH на узел, где запущен под
ssh <node-name>

# Проверка логов kubelet
journalctl -u kubelet --since "10 min ago" | grep -i "rbac\|forbidden\|secret\|serviceaccount"

# Типичные сообщения об ошибках:
# - "forbidden: User 'system:node:<node>' cannot get resource 'secrets'"
# - "failed to get ServiceAccount token: serviceaccounts '<sa>' not found"
# - "unable to create token for ServiceAccount: tokenrequest: failed"

# Проверка сертификатов kubelet
ls -la /var/lib/kubelet/pki/
# → kubelet.crt, kubelet.key

# Проверка конфигурации kubelet
cat /var/lib/kubelet/config.yaml | grep -i "service"
```

## Команды для быстрой диагностики

```bash
# 1. Быстрая проверка всех зависимостей пода
kubectl get pod <pod-name> -o json | jq -r '
  .spec.serviceAccountName,
  .spec.containers[].env[].valueFrom.secretKeyRef.name,
  .spec.containers[].env[].valueFrom.configMapKeyRef.name,
  .spec.volumes[]?.secret?.secretName,
  .spec.volumes[]?.configMap?.name
' | sort -u | while read -r res; do
  kubectl get "$res" -n <namespace> &>/dev/null && echo "OK: $res" || echo "MISSING: $res"
done

# 2. Проверка RBAC для ServiceAccount
SA=$(kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}')
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:$SA

# 3. Проверка RoleBinding в namespace
kubectl get rolebindings -n <namespace> -o custom-columns=\
  'NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name'

# 4. Поиск всех RoleBinding для конкретного SA
kubectl get rolebindings,clusterrolebindings -A -o json | \
  jq -r ".items[] | select(.subjects[]?.name == \"$SA\") | \
  \(.metadata.namespace)/\(.metadata.name) -> \(.roleRef.name)"
```

### Типичные ошибки в Helm-чартах

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| SA не создан | `serviceaccounts "x" not found` | Установить `serviceAccount.create: true` |
| Несовпадение имени | SA создан с суффиксом чарта | Проверить `{{ include "chart.fullname" . }}` |
| RoleBinding в другом namespace | 403 Forbidden | Убедиться, что RoleBinding в том же namespace, что и под |
| automount отключен | Под не может прочитать секреты | Проверить `automountServiceAccountToken` на SA |

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика CreateContainerConfigError](./prevention.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Безопасность ServiceAccount и токенов](../../../Base/secrets/security.md)
- [Концепции RBAC: Роли и привязки](../../../Security/rbac/rbac_overview.md)
- [Субъекты доступа](../../../Security/rbac/subjects.md)
- [Обзор CSI Driver](../../../Storage/CSI/csi_overview.md)
