# Ошибки доступа к API: лучшие практики и превентивные меры

## Определения

**Лучшие практики безопасности API** — комплекс архитектурных и эксплуатационных мер, направленных на минимизацию рисков возникновения ошибок 401 (Аутентификация) и 403 (Авторизация/Admission), а также на ограничение "радиуса поражения" при компрометации субъектов.

**Принцип наименьших привилегий (Principle of Least Privilege, PoLP)** — базовый стандарт безопасности, требующий предоставления субъекту (пользователю или приложению) только того набора прав, который минимально необходим для выполнения его функций.

**Defense in Depth (Глубокая оборона)** — строение нескольких уровней защиты, где каждый уровень независимо ограничивает доступ. При компрометации одного уровня другие продолжают работать.

> Общий обзор безопасности RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

## Основные концепции

### Стратегия предотвращения ошибок доступа

Эффективная защита строится на четырех уровнях, каждый из которых предотвращает определенный класс ошибок 401/403.

| Уровень | Технология | Предотвращаемая проблема |
|---------|------------|--------------------------|
| **Аутентификация** | TokenRequest API / OIDC | Утечка бессрочных токенов, ошибки 401 из-за ротации. |
| **Авторизация** | Гранулярный RBAC | Ошибки 403 из-за избыточных прав или опечаток в ресурсах. |
| **Политики (Admission)** | ValidatingAdmissionPolicy (CEL) | Нарушение стандартов безопасности (PSA), блокировки 403. |
| **Сеть** | NetworkPolicy | Доступ к API-серверу только из разрешенных подсетей/подов. |

### Почему традиционные секреты SA (Static Tokens) опасны

До версии 1.22 Kubernetes автоматически создавал бессрочный JWT-токен в объекте `Secret` для каждого ServiceAccount. 
1. **Риск 401:** При компрометации токен сложно отозвать без удаления SA.
2. **Риск 403:** Автоматическое монтирование токена (`automountServiceAccountToken: true`) предоставляет подам права доступа к API "по умолчанию", что противоречит принципу PoLP.

**Диагностика текущего состояния:**
```bash
# Проверка automountServiceAccountToken для SA
kubectl get sa <sa-name> -n <ns> -o jsonpath='{.automountServiceAccountToken}'

# Просмотр всех SA с включенным automount
kubectl get sa -n <ns> -o json | jq '.items[] | select(.automountServiceAccountToken != false) | .metadata.name'

# Проверка, какие_SA используются в подах
kubectl get pods -n <ns> -o json | jq '.items[] | {name: .metadata.name, sa: .spec.serviceAccountName}'
```

**Ожидаемый результат:**
```text
# SA с включенным automount (опасно):
default
build-robot

# SA с выключенным automount (безопасно):
app-sa
monitoring-sa
```

## Практические сценарии

### Сценарий 1: Переход на проецируемые токены (Bound Tokens)

Используйте механизм `ServiceAccountTokenProjection` для получения кратковременных токенов, привязанных к жизненному циклу пода.

**Эталонная конфигурация (YAML):**
```yaml
spec:
  automountServiceAccountToken: false # Отключение стандартного токена
  containers:
  - name: secure-app
    volumeMounts:
    - mountPath: /var/run/secrets/tokens
      name: bound-token
  serviceAccountName: app-sa
  volumes:
  - name: bound-token
    projected:
      sources:
      - serviceAccountToken:
          audience: api-server
          expirationSeconds: 3600 # Токен действителен 1 час
          path: bound-token
```

**Диагностика проецированных токенов:**
```bash
# Проверка, что SA не использует стандартный токен
kubectl get sa app-sa -n <ns> -o jsonpath='{.automountServiceAccountToken}'

# Просмотр проецированных томов в поде
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.volumes[*].projected}'

# Проверка доступности audience
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.containers[*].env}' | jq '.[] | select(.name == "KUBERNETES_SERVICE_HOST")'
```

**Ожидаемый результат:**
```text
# automountServiceAccountToken должен быть false или отсутствовать:
false

# Том должен содержать projected volume:
{"sources":[{"serviceAccountToken":{"audience":"api-server","expirationSeconds":3600,"path":"bound-token"}}]}
```

### Сценарий 2: Использование нативных политик CEL (ValidatingAdmissionPolicy)

Вместо сложных внешних вебхуков (которые могут возвращать 403 из-за сетевых таймаутов), используйте нативные политики Kubernetes (1.30+).

**Пример политики (запрет удаления критических ConfigMap):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: protect-critical-configs
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["DELETE"]
      resources: ["configmaps"]
  validations:
    - expression: "object.metadata.name != 'core-config'"
      message: "Удаление core-config запрещено политикой безопасности."
```

**Диагностика политик:**
```bash
# Просмотр всех политических правил
kubectl get validatingadmissionpolicies -o custom-columns=NAME:.metadata.name,FAILURE:.spec.failurePolicy

# Проверка привязки политики к ресурсу
kubectl get validatingadmissionpolicybindings -o custom-columns=NAME:.metadata.name,POLICY:.spec.policyName,PARAMS:.spec.params

# Тестирование политики через dry-run
kubectl delete configmap core-config -n <ns> --dry-run=server 2>&1 | head -5

# Просмотр ошибок политики
kubectl get events -n <ns> --field-selector reason=FailedCreate
```

**Ожидаемый результат:**
```text
# При попытке удаления защищенного ConfigMap:
Error from server (Forbidden): validatingadmissionpolicy.admissionregistration.k8s.io "protect-critical-configs" denied request: Удаление core-config запрещено политикой безопасности.
```

### Сценарий 3: Автоматизация аудита RBAC в CI/CD

Предотвращайте попадание некорректных RBAC-манифестов в кластер с помощью статического анализа.

**Инструменты:**
*   **Kube-bench:** Проверка кластера на соответствие CIS Benchmark.
*   **Checkov / Terrascan:** Сканирование YAML на наличие `ClusterRoleBinding` с избыточными правами.
*   **Krane:** Визуализация графа RBAC и поиск опасных связей.

```bash
# Пример проверки манифестов перед деплоем
checkov -d ./kubernetes-manifests/ --check CKV_K8S_1,CKV_K8S_49

# Проверка всех ролей на наличие wildcard прав
kubectl get clusterroles -o json | jq '.items[] | select(.rules[]? | .verbs[] == "*" or .resources[] == "*") | .metadata.name'

# Просмотр всех ClusterRoleBinding с избыточными правами
kubectl get clusterrolebindings -o json | jq '.items[] | select(.roleRef.name == "cluster-admin") | {name: .metadata.name, subjects: .subjects}'
```

**Ожидаемый результат:**
```text
# Роли с wildcard правами (опасно):
cluster-admin
system:controller:deployment-controller

# ClusterRoleBinding на cluster-admin (опасно):
{"name":"custom-admin","subjects":[{"kind":"ServiceAccount","name":"my-sa","namespace":"default"}]}
```

### Сценарий 4: Мониторинг и алертинг ошибок 401/403

Настройте обнаружение аномалий в поведении приложений через метрики API-сервера.

**Prometheus Rule:**
```yaml
- alert: HighRateOfRBACForbidden
  # Отслеживание всплеска 403 ошибок для конкретных ServiceAccounts
  expr: sum(rate(apiserver_request_total{code="403"}[5m])) by (username, resource) > 1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Подозрительная активность субъекта {{ $labels.username }}"
    description: "Субъект пытается получить доступ к {{ $labels.resource }}, но получает отказ."
```

**Диагностика метрик:**
```bash
# Просмотр метрик 403 ошибок
kubectl get --raw /metrics | grep apiserver_request_total | grep code="403" | head -5

# Просмотр метрик по субъектам
kubectl get --raw /metrics | grep apiserver_request_total | grep username | head -10

# Проверка API Priority and Fairness
kubectl get flowschemas -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priorityLevelConfiguration.name

# Просмотр запросов в очереди APF
kubectl get --raw /metrics | grep apiserver_flowcontrol | head -10
```

**Ожидаемый результат:**
```text
# Метрики 403 ошибок:
apiserver_request_total{code="403",resource="deployments",verb="create",username="system:serviceaccount:default:my-sa"} 15.0

# FlowSchema с низким приоритетом (может вызывать 429/403):
low-priority-updates
exempt-flowschema
```

### Сценарий 5: Настройка NetworkPolicy для API-сервера

Ограничьте доступ к API-серверу только из разрешенных подов и подсетей.

**Пример NetworkPolicy:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-server-access
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    - podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 6443
```

**Диагностика NetworkPolicy:**
```bash
# Просмотр всех NetworkPolicy в namespace
kubectl get networkpolicy -n kube-system

# Просмотр правил конкретной политики
kubectl get networkpolicy allow-api-server-access -n kube-system -o yaml

# Проверка, какие поды попадают под политику
kubectl get pods -n kube-system -l component=kube-apiserver

# Тестирование доступа из пода
kubectl run test-pod --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 https://kubernetes.default.svc:6443/healthz
```

**Ожидаемый результат:**
```text
# Доступ разрешен из monitoring namespace:
ok

# Доступ запрещен из другого namespace:
wget: couldn't connect to server
```

### Сценарий 6: Управление секретами через External Secrets Operator

Используйте ESO для безопасного хранения секретов вне кластера (Vault, AWS SSM, GCP Secret Manager).

**Пример конфигурации:**
```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: app-secrets
    creationPolicy: Owner
  data:
  - secretKey: db-password
    remoteRef:
      key: secret/data/app/db
      property: password
```

**Диагностика ESO:**
```bash
# Просмотр статуса ExternalSecret
kubectl get externalsecret app-secrets -n default

# Просмотр ошибок синхронизации
kubectl describe externalsecret app-secrets -n default

# Просмотр всех SecretStore
kubectl get secretstore -A

# Проверка доступности Vault
kubectl get secretstore vault-backend -n default -o jsonpath='{.status.conditions[*].message}'
```

**Ожидаемый résultat:**
```text
# Статус синхронизации:
Refreshed

# Ошибки отсутствуют:
Status: Ready
Message: Secret was synced
```

### Сценарий 7: Ротация CA-сертификатов

Предотвращайте ошибки 401 из-за просроченных сертификатов управляющего слоя.

**Процедура ротации:**
```bash
# Проверка срока действия текущего CA
kubeadm certs check-expiration

# Ротация сертификатов
kubeadm certs renew all

# Перезапуск control plane
systemctl restart kubelet

# Проверка нового CA
kubectl get --raw /healthz
```

**Диагностика сертификатов:**
```bash
# Просмотр всех сертификатов
kubeadm certs check-expiration

# Проверка CA сертификата
openssl x509 -in /etc/kubernetes/pki/ca.crt -noout -dates

# Просмотр SAN сертификата API-сервера
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -text | grep -A1 "Subject Alternative Name"
```

**Ожидаемый результат:**
```text
CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
admin.conf                 Dec 30, 2025 23:59 UTC   364d
apiserver                  Dec 30, 2025 23:59 UTC   364d
apiserver-etcd-client      Dec 30, 2025 23:59 UTC   364d
ca                         Dec 28, 2030 23:59 UTC   5y
```

### Сценарий 8: Настройка OIDC аутентификации

Используйте внешний OIDC-провайдер для централизованного управления пользователями.

**Конфигурация API-сервера:**
```yaml
# /etc/kubernetes/manifests/kube-apiserver.yaml
- --oidc-issuer-url=https://accounts.google.com
- --oidc-client-id=kubernetes
- --oidc-username-claim=email
- --oidc-groups-claim=groups
- --oidc-required-claim=hd=example.com
```

**Диагностика OIDC:**
```bash
# Проверка OIDC конфигурации
kubectl get --raw /.well-known/openid-configuration | jq '.issuer, .authorization_endpoint, .token_endpoint'

# Просмотр OIDC токена
kubectl config view --minify -o jsonpath='{.users[*].user.auth-provider.config}'

# Проверка OIDC groups
kubectl auth can-i --list --as=oidc-user@example.com --as-group=oidc-group

# Просмотр всех OIDC привязок
kubectl get clusterrolebindings -o json | jq '.items[] | select(.subjects[]?.name == "oidc-user@example.com") | {name: .metadata.name, role: .roleRef.name}'
```

**Ожидаемый результат:**
```text
# OIDC конфигурация:
"https://accounts.google.com"
"https://accounts.google.com/o/oauth2/auth"
"https://oauth2.googleapis.com/token"

# OIDC groups доступны:
True
```

## Дополнительная информация

### Чек-лист превентивных мер

1.  **Принудительный отказ от default:** Устанавливайте `automountServiceAccountToken: false` на уровне `default` ServiceAccount в каждом неймспейсе.
    ```bash
    # Проверка default SA
    kubectl get sa default -n <ns> -o jsonpath='{.automountServiceAccountToken}'
    ```

2.  **Изоляция через ResourceNames:** Для критических секретов всегда указывайте список разрешенных имен объектов.
    ```bash
    # Просмотр секретов с ограничениями
    kubectl get rolebindings -A -o json | jq '.items[] | select(.roleRef.name == "secret-reader") | {namespace: .metadata.namespace, name: .metadata.name}'
    ```

3.  **Namespace-scoping:** Избегайте `ClusterRoleBinding` для приложений. Используйте `RoleBinding` даже при ссылке на `ClusterRole`.
    ```bash
    # Просмотр всех ClusterRoleBinding (опасные привязки)
    kubectl get clusterrolebindings -o json | jq '.items[] | select(.roleRef.name != "cluster-admin" and .roleRef.name != "system:controller:deployment-controller") | {name: .metadata.name, role: .roleRef.name}'
    ```

4.  **Регулярная ротация CA:** Используйте `kubeadm certs renew` для предотвращения ошибок 401 из-за просроченных сертификатов управляющего слоя.
    ```bash
    # Проверка срока действия сертификатов
    kubeadm certs check-expiration
    ```

5.  **Контроль API Priority and Fairness:** Настройте лимиты для "шумных" потребителей, чтобы предотвратить 429/403 ошибки при перегрузке API.
    ```bash
    # Просмотр FlowSchema
    kubectl get flowschemas -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priorityLevelConfiguration.name
    ```

6.  **Audit Logging:** Включите аудит API-запросов для отслеживания подозрительной активности.
    ```bash
    # Проверка аудит политики
    kubectl get --raw /audit/v1/policies | jq '.rules[] | {level: .level, verbs: .verbs, resources: .resources}'
    ```

7.  **NetworkPolicy для API-сервера:** Ограничьте доступ к API-серверу только из разрешенных подов/подсетей.
    ```bash
    # Просмотр NetworkPolicy в kube-system
    kubectl get networkpolicy -n kube-system
    ```

8.  **Валидация манифестов в CI/CD:** Используйте static analysis для проверки RBAC перед деплоем.
    ```bash
    # Проверка манифестов
    checkov -d ./kubernetes-manifests/ --check CKV_K8S_1,CKV_K8S_49
    ```

### Команды быстрой диагностики

```bash
# Просмотр всех разрешений для субъекта
kubectl auth can-i --list --as=system:serviceaccount:default:my-sa -n default

# Проверка конкретного действия
kubectl auth can-i create deployments --as=system:serviceaccount:default:my-sa -n default

# Просмотр всех RoleBinding в namespace
kubectl get rolebindings -n <ns> -o custom-columns=NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name

# Просмотр всех ClusterRoleBinding
kubectl get clusterrolebindings -o custom-columns=NAME:.metadata.name,ROLE:.roleRef.name,SUBJECTS:.subjects[*].name

# Поиск всех привязок для конкретного SA
kubectl get rolebindings,clusterrolebindings -A -o json | jq '.items[] | select(.subjects[]? | .kind == "ServiceAccount" and .name == "my-sa") | {kind: .kind, name: .metadata.name, namespace: .metadata.namespace, role: .roleRef.name}'

# Просмотр метрик 403 ошибок
kubectl get --raw /metrics | grep apiserver_request_total | grep code="403" | head -5

# Просмотр FlowSchema
kubectl get flowschemas -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priorityLevelConfiguration.name
```

### Распространенные ошибки и решения

| Ошибка | Симптомы | Причина | Решение |
|--------|----------|---------|---------|
| **403 Forbidden из-за automount** | Под не может получить доступ к API | `automountServiceAccountToken: true` по умолчанию | Установить `automountServiceAccountToken: false` для SA |
| **403 Forbidden из-за ClusterRoleBinding** | Приложение получает доступ ко всем namespace | `ClusterRoleBinding` вместо `RoleBinding` | Использовать `RoleBinding` с `ClusterRole` |
| **401 Unauthorized из-за просроченного CA** | Все запросы к API возвращают 401 | Просроченный CA-сертификат | Выполнить `kubeadm certs renew all` |
| **403 Forbidden из-за NetworkPolicy** | Под не может подключиться к API-серверу | NetworkPolicy блокирует доступ | Добавить разрешающие правила в NetworkPolicy |
| **403 Forbidden из-за APF** | Запросы отклоняются с 429/403 | API Priority and Fairness блокирует "шумных" потребителей | Настроить FlowSchema с правильным приоритетом |
| **403 Forbidden из-за OIDC** | Пользователь не может аутентифицироваться | Неверная конфигурация OIDC | Проверить `--oidc-*` флаги API-сервера |

### Типичные RBAC-антипаттерны и их последствия

| Антипаттерн | Риск | Как обнаружить | Решение |
|-------------|------|----------------|---------|
| **Wildcard `verbs: ["*"]` + `resources: ["*"]`** | Любое действие с любым ресурсом. Аналог cluster-admin, но без аудита | `kubectl get clusterroles -o json \| jq '.items[] \| select(.rules[]? \| .verbs[] == "*" and .resources[] == "*") \| .metadata.name'` | Перечислить конкретные ресурсы и глаголы |
| **ClusterRoleBinding SA на `cluster-admin`** | Приложение получает полный доступ ко всему кластеру | `kubectl get clusterrolebindings -o json \| jq '.items[] \| select(.roleRef.name == "cluster-admin") \| {name: .metadata.name, subjects: .subjects}'` | Использовать RoleBinding с минимальной Role |
| **default SA с `automountServiceAccountToken: true`** | Все поды без явного SA получают доступ к API | `kubectl get sa default -n <ns> -o jsonpath='{.automountServiceAccountToken}'` | Установить `automountServiceAccountToken: false` |
| **Доступ ко всем secrets** | Чтение любых секретов в namespace | `kubectl auth can-i list secrets --as=system:serviceaccount:<ns>:<sa> -n <ns>` → yes | Ограничить через `resourceNames` |
| **ClusterRoleBinding вместо RoleBinding** | Приложение видит ресурсы во всех namespace | `kubectl get clusterrolebindings -o json \| jq '.items[] \| select(.subjects[]?.kind == "ServiceAccount") \| {name: .metadata.name, role: .roleRef.name}'` | Использовать RoleBinding (ClusterRole + RoleBinding = локальная привязка) |
| **`impersonate` + `bind` в одной роли** | Полная компрометация кластера | Анализ прав через `kubectl auth can-i --list` | Никогда не объединять эти глаголы в одной роли |

**Как найти все опасные привязки в кластере:**
```bash
# Все ClusterRoleBinding на cluster-admin (кроме системных)
kubectl get clusterrolebindings -o json | jq '.items[] | select(.roleRef.name == "cluster-admin" and (.subjects[]?.name | test("^system:") | not)) | {name: .metadata.name, subjects: .subjects}'

# Все SA с доступом к secrets
kubectl get clusterrolebindings,rolebindings -A -o json | jq '.items[] | select(.subjects[]?.kind == "ServiceAccount") | select(.roleRef.name | test("admin|secret|cluster-admin")) | {kind: .kind, name: .metadata.name, namespace: .metadata.namespace, role: .roleRef.name}'

# Все роли с wildcard
kubectl get clusterroles,roles -A -o json | jq '.items[] | select(.rules[]? | .verbs[] == "*") | {kind: .kind, name: .metadata.name, namespace: .metadata.namespace}'
```

> Подробнее о векторах атак через эскалацию привилегий: [../../../Security/rbac/privilege_escalation.md](../../../Security/rbac/privilege_escalation.md)

### Откат RBAC-изменений в production

Ошибка в RBAC-манифесте может заблокировать работу контроллеров или приложений. Пошаговый workflow отката:

**Шаг 1: Быстрая идентификация проблемы**
```bash
# Определить, когда появились 403 ошибки
kubectl get --raw /metrics | grep apiserver_request_total | grep code="403"

# Найти Audit-Id последнего отказа
kubectl <failing-command> -v=8 2>&1 | grep -E "Audit-Id|HTTP/"

# Проверить, какие RoleBinding изменились недавно
kubectl get rolebindings -A -o json | jq '.items[] | select(.metadata.creationTimestamp > "2026-01-01T00:00:00Z") | {name: .metadata.name, namespace: .metadata.namespace, role: .roleRef.name, created: .metadata.creationTimestamp}'
```

**Шаг 2: Восстановление из Git (GitOps rollback)**
```bash
# Если RBAC управляется через GitOps — откат через Git
git revert <commit-with-broken-rbac>
git push origin main
# ArgoCD/Flux автоматически применит предыдущую версию

# Или ручной откат через kubectl
kubectl delete -f broken-rbac.yaml
kubectl apply -f previous-working-rbac.yaml
```

**Шаг 3: Временное восстановление (если Git-репозиторий недоступен)**
```bash
# Создать временный ClusterRoleBinding для восстановления доступа
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: emergency-admin-$(date +%s)
subjects:
- kind: User
  name: emergency-admin
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
EOF

# После восстановления доступа — удалить временный биндинг
kubectl delete clusterrolebinding emergency-admin-*
```

**Шаг 4: Валидация после отката**
```bash
# Проверить, что права восстановлены
kubectl auth can-i <verb> <resource> --as=<subject> -n <ns>

# Проверить, что контроллеры работают
kubectl get pods -n kube-system | grep -E "controller|scheduler"

# Проверить, что 403 ошибки прекратились
kubectl get --raw /metrics | grep apiserver_request_total | grep code="403"
```

> Подробнее о `kubectl auth reconcile` для обнаружения drift'а: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)

### RBAC через GitOps: версионирование и аудит

Хранение RBAC-манифестов в Git обеспечивает полный аудит-трейл, версионирование и автоматический rollback.

**Рекомендуемая структура репозитория:**
```
rbac/
├── base/
│   ├── cluster-admin-binding.yaml      # ClusterRoleBinding на cluster-admin
│   ├── monitoring-rbac.yaml            # RBAC для Prometheus/Grafana
│   ├── ci-cd-rbac.yaml                 # RBAC для CI/CD пайплайнов
│   └── app-rbac.yaml                   # RBAC для прикладных сервисов
├── overlays/
│   ├── prod/
│   │   ├── kustomization.yaml
│   │   └── namespace-labels.yaml
│   └── staging/
│       ├── kustomization.yaml
│       └── relaxed-rbac.yaml
└── audit/
    └── rbac-review.sh                  # Скрипт проверки прав
```

**Интеграция с ArgoCD:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-rbac
  namespace: argocd
spec:
  source:
    repoURL: https://git.example.com/rbac-manifests.git
    path: overlays/prod
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
  ignoreDifferences:
  - group: rbac.authorization.k8s.io
    kind: RoleBinding
    jsonPointers:
    - /subjects                    # Игнорировать ручные изменения subjects
```

**Скрипт аудита RBAC для CI/CD:**
```bash
#!/bin/bash
# rbac-audit.sh — проверка RBAC-манифестов перед деплоем

set -euo pipefail

echo "=== RBAC Audit ==="

# 1. Проверка на wildcard
WILDCARD=$(kubectl get clusterroles,roles -A -o json | jq '[.items[] | select(.rules[]? | .verbs[] == "*") | .metadata.name] | length')
if [ "$WILDCARD" -gt 0 ]; then
    echo "WARNING: Найдены роли с wildcard verbs:"
    kubectl get clusterroles,roles -A -o json | jq '.items[] | select(.rules[]? | .verbs[] == "*") | .metadata.name'
fi

# 2. Проверка ClusterRoleBinding на cluster-admin
ADMIN_BINDINGS=$(kubectl get clusterrolebindings -o json | jq '[.items[] | select(.roleRef.name == "cluster-admin" and (.subjects[]?.name | test("^system:") | not))] | length')
if [ "$ADMIN_BINDINGS" -gt 0 ]; then
    echo "WARNING: Найдены не-системные ClusterRoleBinding на cluster-admin:"
    kubectl get clusterrolebindings -o json | jq '.items[] | select(.roleRef.name == "cluster-admin" and (.subjects[]?.name | test("^system:") | not)) | {name: .metadata.name, subjects: .subjects}'
fi

# 3. Проверка SA с доступом к secrets
SECRET_ACCESS=$(kubectl auth can-i --list --as=system:serviceaccount:default:default -A 2>/dev/null | grep -c "secrets" || true)
if [ "$SECRET_ACCESS" -gt 0 ]; then
    echo "WARNING: default SA имеет доступ к secrets"
fi

echo "=== Audit завершён ==="
```

**Преимущества GitOps для RBAC:**
- **Аудит-трейл:** каждое изменение фиксируется в Git с указанием автора и времени
- **Rollback:** откат к предыдущей версии за секунды через `git revert`
- **Валидация:** PR-процесс с обязательным ревью перед применением
- **Drift detection:** GitOps-оператор автоматически обнаруживает и исправляет расхождения
- **Multi-environment:** overlays для prod/staging/dev с общим base

> Подробнее о GitOps и RBAC: [../../../Security/rbac/rbac_overview.md](../../../Security/rbac/rbac_overview.md)
> ArgoCD RBAC конфигурация: [../../../GitOps/ArgoCD/argocd_rbac_deep.md](../../../GitOps/ArgoCD/argocd_rbac_deep.md)

### Связанные ресурсы

- [Алгоритм диагностики 401/403](diagnostics.md)
- [Практические примеры RBAC для 403](common.md)
- [Расширенные сценарии (Admission)](advanced.md)
- [Определения и модель безопасности API](definitions.md)
- [Объекты RBAC: структура и типичные ошибки](rbac_objects.md)
- [Субъекты доступа (Subjects)](../../../Security/rbac/subjects.md)
- [Аудит и логирование](../../../Security/audit.md)
- [NetworkPolicy](../../../Security/network_policies.md)
- [Управление секретами](../../../Security/application_secrets_management.md)
- [Pod Security Context](../../../Security/pod_security_context.md)
- [Эскалация привилегий](../../../Security/rbac/privilege_escalation.md) — векторы атак через bind/escalate/impersonate
- [API Priority and Fairness](../../../Concepts/api_priority_and_fairness.md) — защита API от перегрузки
- [Multi-cluster RBAC](../../../Security/rbac/multi_cluster_rbac.md) — управление RBAC в мультикластерных средах
- [Официальный гайд по безопасности Kubernetes](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
