# Безопасность Secret в Kubernetes

## Определения

**Secret** — объект Kubernetes, предназначенный для хранения конфиденциальной информации, такой как пароли, OAuth-токены, SSH-ключи и API-ключи. С точки зрения безопасности, основной тип секрета — `Opaque`, используемый для произвольных данных.

**Безопасность секретов** — комплекс мер по защите данных от несанкционированного доступа, компрометации etcd и случайного раскрытия в логах или системах контроля версий.

**Классификация секретов** — систематизация конфиденциальных данных по уровню критичности для определения соответствующих мер защиты:
- **Критические:** ключи шифрования, корневые токены, credentials баз данных с правами записи
- **Высокие:** API-ключи внешних сервисов, токены аутентификации, TLS-сертификаты
- **Средние:** пароли для некритичных сервисов, конфигурационные токены
- **Низкие:** публичные ключи, несекретные конфигурации

О создании секретов см. [Создание Secret](creating_secrets.md). О принципах хранения см. [Хранение в etcd](etcd_storage.md). О доставке секретов приложениям см. [Управление секретами приложений](../../Security/application_secrets_management.md).

## Основные концепции

### Неизменяемые секреты (Immutable Secrets)

Функция перешла в статус **GA (General Availability)** в Kubernetes 1.21+. Секреты можно помечать как неизменяемые для повышения безопасности и производительности.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-immutable-secret
immutable: true
data:
  API_KEY: dmFsdWU=
```

**Преимущества:**
- **Защита от изменений:** предотвращает случайное или злонамеренное обновление данных. Для изменения данных необходимо удалить и создать секрет заново.
- **Производительность:** `kubelet` перестает опрашивать `kube-apiserver` на предмет обновлений для этих секретов, что значительно снижает нагрузку на Control Plane в больших кластерах.

**Применение:**
- Секреты, которые не меняются в течение жизненного цикла приложения (TLS-сертификаты, статические ключи API)
- Защита от случайного перезаписывания через `kubectl apply`
- Оптимизация кластеров с большим количеством подов (снижение нагрузки на API-сервер)

### Безопасность токенов ServiceAccount

Начиная с Kubernetes 1.22+ (и полной очистки в 1.24+), Kubernetes отошел от автоматической генерации бессрочных токенов в виде объектов `Secret` для каждого ServiceAccount.

**Современный подход (Bound Service Account Tokens):**
- **TokenRequest API:** токены запрашиваются динамически и имеют ограниченный срок жизни (TTL).
- **Projected Volumes:** токены монтируются непосредственно в Pod через механизм `serviceAccountToken` в Projected Volumes. Они не сохраняются в `etcd` как объекты `Secret`.
- **Привязка (Binding):** токен привязан к конкретному Pod и ServiceAccount, что делает его бесполезным при краже и использовании на другом узле или в другом контексте.
- **Минимизация привилегий:** рекомендуется использовать параметр `automountServiceAccountToken: false` в спецификации Pod или ServiceAccount, если приложению не нужен доступ к API-серверу.

**Пример использования Projected Volume для токена:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-secure-app
spec:
  serviceAccountName: my-app-sa
  automountServiceAccountToken: false
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: sa-token
      mountPath: /var/run/secrets/tokens
      readOnly: true
  volumes:
  - name: sa-token
    projected:
      sources:
      - serviceAccountToken:
          path: sa-token
          expirationSeconds: 3600
          audience: api-server
```

### Шифрование при хранении (Encryption at Rest)

По умолчанию секреты хранятся в etcd в формате base64 (незашифрованном). Для защиты данных необходимо включить шифрование на уровне `kube-apiserver` с помощью `EncryptionConfiguration`.

**KMS v2 (Key Management Service):**
Начиная с Kubernetes 1.29, **KMS v2** стал GA. Он обеспечивает значительные улучшения:
- **Иерархия ключей:**
  1. **KEK (Key Encryption Key):** Главный ключ во внешнем KMS (HashiCorp Vault).
  2. **Seed (Семя):** Плагин KMS генерирует семя, шифрует его через KEK и передает в API-сервер.
  3. **DEK (Data Encryption Key):** API-сервер локально выводит DEK из семени для шифрования объектов.
- **Производительность:** Локальная деривация DEK исключает сетевые запросы к KMS при каждой операции, что критично для больших кластеров.
- **Автоматическая ротация:** Поддержка ротации ключей без перезапуска API-сервера.

Подробнее: [Хранение в etcd (Шифрование)](etcd_storage.md#шифрование-at-rest-encryption-at-rest).

### Ограничения размера

Размер объекта Secret ограничен **1 МиБ** (лимит etcd). Это ограничение включает метаданные и все данные в формате Base64. Для хранения больших объемов конфиденциальных данных (например, сертификатов с длинными цепочками или образов) следует использовать внешние хранилища.

**Практические рекомендации:**
- Контролируйте размер секретов через `kubectl get secrets -A -o json | jq '.items[] | {name: .metadata.name, size: (.data | to_entries | map(.value | length) | add)}'`
- Для больших файлов (Keystore, certificate chains) используйте ConfigMap или внешние хранилища
- При превышении лимита вы получите ошибку `RequestEntityTooLarge`

## Практические сценарии

### Ограничение доступа через RBAC

Доступ к секретам должен быть ограничен по принципу минимальных привилегий. Особую опасность представляют права `list` и `watch` на уровне пространства имен, так как они позволяют получить содержимое всех секретов сразу.

**Базовый Role для доступа к конкретному секрету:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: prod
  name: app-secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["my-db-secret"] # Ограничение доступа к конкретному секрету
  verbs: ["get"]
```

**ClusterRole для чтения секретов во всех неймспейсах (опасно!):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-reader-global
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"] # Избегайте list/watch без resourceNames
```

**Агрегация ролей для безопасного масштабирования:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-secrets
  labels:
    rbac.example.com/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
```

**Проверка прав:**
Используйте команду для аудита прав конкретного субъекта:
```bash
kubectl auth can-i get secrets/my-db-secret --as=system:serviceaccount:prod:my-app-sa
# → yes/no

# Проверка всех доступных секретов
kubectl auth can-i list secrets --namespace=prod --as=system:serviceaccount:prod:my-app-sa

# Аудит всех прав ServiceAccount
kubectl auth can-i --list --namespace=prod --as=system:serviceaccount:prod:my-app-sa
```

### Сетевая изоляция секретов (NetworkPolicy)

NetworkPolicy не шифруют данные, но ограничивают доступ к сервисам, работающим с секретами:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-db-access-only
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 5432
```

**Связь с секретами:** NetworkPolicy не влияет на доступ к объектам `Secret` через API (это регулируется RBAC), но защищает сервисы, которые используют эти секреты, от несанкционированного доступа по сети.

### Монтирование Volume против переменных окружения

**Рекомендуемый метод:** монтирование секретов как Volume (через `tmpfs`).

- **Безопасность:** секреты монтируются в оперативную память и не записываются на диск узла.
- **Скрытость:** переменные окружения видны через `kubectl describe pod`, в логах приложения, дампах памяти и через `/proc/1/environ`.
- **Обновление:** при изменении секрета файл в Volume обновляется автоматически (kubelet обновляет симлинк), в то время как переменные окружения требуют перезапуска контейнера.
- **Ограничение:** секреты, смонтированные через `subPath`, не обновляются автоматически.

**Сравнение методов доставки:**

| Характеристика | Volume (tmpfs) | Переменные окружения |
| :--- | :--- | :--- |
| **Безопасность** | Высокая (только в RAM) | Средняя (видны через /proc) |
| **Обновление** | Автоматическое | Требует перезапуска |
| **Видимость** | Не видны через kubectl | Видны через describe pod |
| **Совместимость** | Чтение файлов | Все приложения |

### Аудит и обсервабильность (Observability)

Мониторинг доступа к секретам критичен для обнаружения аномалий:

**Audit Logs:**

Настройте логирование на уровне `RequestResponse` для ресурсов `secrets`:

```yaml
# /etc/kubernetes/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: RequestResponse
  resources:
  - group: ""
    resources: ["secrets"]
  namespaces: ["prod", "staging"]
```

**Запросы к Audit Logs через kubectl:**

```bash
# Поиск всех операций чтения секретов
kubectl logs -n kube-system kube-apiserver-master -f | jq 'select(.verb == "get" and .objectRef.resource == "secrets")'

# Поиск операций создания/изменения секретов
kubectl logs -n kube-system kube-apiserver-master -f | jq 'select(.verb in ["create", "update", "patch"] and .objectRef.resource == "secrets")'

# Аудит доступа к конкретному секрету
kubectl logs -n kube-system kube-apiserver-master -f | jq 'select(.objectRef.name == "my-db-secret")'
```

**Метрики:**
- `kms_operation_duration_seconds`: Метрика для отслеживания задержек KMS.
- `apiserver_storage_transformation_failures_total`: Счетчик ошибок дешифрования (критический алерт).
- `apiserver_storage_transformation_operations_total`: Объем операций шифрования/дешифрования.

**Примеры алертов (Prometheus):**

```yaml
groups:
- name: secrets-security
  rules:
  - alert: SecretDecryptionFailure
    expr: apiserver_storage_transformation_failures_total > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Ошибка дешифрования секрета в etcd"
      
  - alert: KMSHighLatency
    expr: histogram_quantile(0.99, rate(kms_operation_duration_seconds_bucket[5m])) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокая задержка KMS (>1s p99)"
```

### Admission Control и политики

Для принудительного исполнения стандартов безопасности используйте:

**ValidationAdmissionPolicy (1.30+):**

Позволяет декларативно описывать правила проверки секретов с помощью CEL:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "secret-size-policy"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: [""]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["secrets"]
  validations:
  - expression: "!object.data.exists(key, size(object.data[key]) > 1048576)"
    message: "Secret value cannot exceed 1MB"
```

**Pod Security Admission для секретов:**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

**Kyverno / OPA Gatekeeper:** Для сложной валидации структуры секретов.

**Пример Kyverno-политики для запрета секретов с определенными аннотациями:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-secret-encryption
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-secret-encryption
    match:
      any:
      - resources:
          kinds:
          - Secret
    validate:
      message: "Secrets must have encryption annotation"
      pattern:
        metadata:
          annotations:
            encryption: "required"
```

### Ротация секретов

Регулярная ротация критична для безопасности. Существует несколько подходов:

**Автоматическая ротация через External Secrets Operator (ESO):**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: db-credentials
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: production/db
      property: password
```

**Ротация через Reloader:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  template:
    spec:
      containers:
      - name: app
        envFrom:
        - secretRef:
            name: db-credentials
```

**Ручная ротация (если автоматизация невозможна):**

```bash
# 1. Создать новый секрет
kubectl create secret generic db-credentials \
  --from-literal=password=new-secure-password \
  -n prod \
  --dry-run=client -o yaml > new-secret.yaml

# 2. Применить новый секрет
kubectl apply -f new-secret.yaml

# 3. Перезапустить поды для применения нового секрета
kubectl rollout restart deployment/my-app -n prod

# 4. Удалить старый секрет (если был заменен)
kubectl delete secret db-credentials-old -n prod
```

### Резервное копирование и восстановление (Backup/Restore)

При создании бэкапов (Snapshot) etcd необходимо учитывать состояние шифрования:

- **Синхронизация:** Бэкап etcd бесполезен без соответствующего файла `EncryptionConfiguration` и доступа к ключам KMS.
- **Целостность:** При восстановлении на новый кластер убедитесь, что KMS плагин имеет доступ к тем же KEK, которыми были зашифрованы данные.

**Процедура безопасного бэкапа:**

```bash
# 1. Бэкап etcd
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 2. Сохранить EncryptionConfiguration
cp /etc/kubernetes/encryption-config.yaml /backup/encryption-config-$(date +%Y%m%d).yaml

# 3. Проверить целостность снапшота
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-$(date +%Y%m%d).db --write-out=table
```

**Процедура восстановления:**

```bash
# 1. Восстановить EncryptionConfiguration (тот же файл, что использовался при бэкапе)
cp /backup/encryption-config-20240101.yaml /etc/kubernetes/encryption-config.yaml

# 2. Восстановить etcd из снапшота
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-20240101.db \
  --data-dir=/var/lib/etcd-restored \
  --name=master \
  --initial-cluster=master=https://127.0.0.1:2380 \
  --initial-advertise-peer-urls=https://127.0.0.1:2380

# 3. Обновить конфигурацию etcd для использования восстановленных данных
# 4. Перезапустить etcd и kube-apiserver
```

### Сканирование секретов в CI/CD

Предотвращение утечки секретов в репозитории — критический элемент безопасности:

**Gitleaks:**

```bash
# Установка
brew install gitleaks  # macOS
# или
docker pull ghcr.io/gitleaks/gitleaks:latest

# Сканирование репозитория
gitleaks detect --source /path/to/repo --verbose

# Сканирование с указанием конфигурации
gitleaks detect --source /path/to/repo --config .gitleaks.toml
```

**Пример конфигурации .gitleaks.toml:**

```toml
[allowlist]
description = "Global Allowlist"
paths = [
  '''secret_manager\.md$''',
  '''test_.*\.go$'''
]

[[rules]]
id = "kubernetes-secret"
description = "Kubernetes Secret"
regex = '''apiVersion:\s*v1\s*\nkind:\s*Secret\s*\n.*?data:'''
tags = ["kubernetes", "secret"]
```

**detect-secrets:**

```bash
# Установка
pip install detect-secrets

# Создание бейзлайна
detect-secrets scan > .secrets.baseline

# Проверка изменений
detect-secrets scan --update .secrets.baseline

# Проверка в pre-commit хук
# .pre-commit-config.yaml
repos:
- repo: https://github.com/Yelp/detect-secrets
  rev: v1.4.0
  hooks:
  - id: detect-secrets
    args: ['--baseline', '.secrets.baseline']
```

**Интеграция в GitLab CI:**

```yaml
secret-scan:
  stage: security
  image: ghcr.io/gitleaks/gitleaks:latest
  script:
    - gitleaks detect --source . --verbose --report-format sarif --report-path gitleaks-report.sarif
  artifacts:
    reports:
      sast: gitleaks-report.sarif
  allow_failure: false
```

## Использование внешних менеджеров

Для Production-сред рекомендуется использовать внешние системы управления (HashiCorp Vault).

**Инструменты интеграции:**
- **External Secrets Operator (ESO):** синхронизирует данные из внешних систем в нативные секреты K8s. Удобно для приложений, не умеющих работать с внешними API.
- **Secrets Store CSI Driver:** монтирует данные напрямую в файловую систему Pod (tmpfs) без создания объекта `Secret` в Kubernetes API. Это наиболее безопасный метод.
- **Vault Secrets Operator (VSO):** нативный оператор от HashiCorp для интеграции с Vault.

Подробнее: [Внешние менеджеры](external_managers.md).

## Диагностика и устранение неполадок

### Типичные ошибки

**1. Ошибка "secret not found":**

```bash
# Симптом
Error: secrets "my-secret" not found

# Диагностика
kubectl get secret my-secret -n prod
kubectl get secrets -n prod | grep my

# Решение: проверить имя и неймспейс
kubectl get secret my-secret -n prod -o yaml
```

**2. Ошибка доступа (RBAC):**

```bash
# Симптом
Error from server (Forbidden): secrets "my-secret" is forbidden: User "system:serviceaccount:prod:my-app" cannot get resource "secrets"

# Диагностика
kubectl auth can-i get secret/my-secret --namespace=prod --as=system:serviceaccount:prod:my-app
kubectl auth can-i --list --namespace=prod --as=system:serviceaccount:prod:my-app

# Решение: создать Role и RoleBinding
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: prod
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["my-secret"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: secret-reader-binding
  namespace: prod
subjects:
- kind: ServiceAccount
  name: my-app
  namespace: prod
roleRef:
  kind: Role
  name: secret-reader
  apiGroup: rbac.authorization.k8s.io
EOF
```

**3. Ошибка монтирования Volume:**

```bash
# Симптом
Warning  FailedMount  Unable to attach or mount volumes

# Диагностика
kubectl describe pod my-app -n prod
kubectl get events -n prod --field-selector reason=FailedMount

# Решение: проверить права доступа и существование секрета
kubectl get secret my-secret -n prod -o jsonpath='{.data}' | jq
```

**4. Секрет не обновляется после изменения:**

```bash
# Симптом: приложение использует старое значение

# Проверка: секрет обновлен?
kubectl get secret my-secret -n prod -o jsonpath='{.data.password}' | base64 -d

# Если монтирован через subPath - обновление не произойдет
# Решение: пересоздать Pod или использовать другой метод монтирования
kubectl delete pod my-app -n prod
```

**5. Ошибка EncryptionConfiguration:**

```bash
# Симптом
Error from server: Internal error: failed to decode secret

# Диагностика: проверить EncryptionConfiguration
cat /etc/kubernetes/encryption-config.yaml

# Проверить доступность KMS
kubectl logs -n kube-system kube-apiserver-master | grep -i kms

# Решение: убедиться, что EncryptionConfiguration доступен и KMS работает
kubectl get pods -n kube-system | grep kms
```

### Команды для отладки

```bash
# Просмотр всех секретов в неймспейсе
kubectl get secrets -n prod

# Просмотр деталей секрета (без расшифровки данных)
kubectl describe secret my-secret -n prod

# Проверка использований секрета
kubectl get pods -n prod -o json | jq '.items[] | select(.spec.volumes[]?.secret.secretName == "my-secret") | .metadata.name'

# Проверка Pod, использующих секрет через env
kubectl get pods -n prod -o json | jq '.items[] | select(.spec.containers[].envFrom[]?.secretRef.name == "my-secret") | .metadata.name'

# Просмотр audit logs для секретов
kubectl logs -n kube-system kube-apiserver-master -f | jq 'select(.objectRef.resource == "secrets")'

# Проверка версии etcd и шифрования
ETCDCTL_API=3 etcdctl endpoint health --write-out=table

# Проверка размера секретов
kubectl get secrets -A -o json | jq '.items[] | {namespace: .metadata.namespace, name: .metadata.name, size: (.data | to_entries | map(.value | length) | add)}' | sort-by(.size) | reverse
```

## Дополнительная информация

### Лучшие практики

- **Принцип минимальных привилегий:** Ограничивайте доступ к секретам через `resourceNames` в RBAC.
- **automountServiceAccountToken: false:** Всегда отключайте автоматическое монтирование токена, если он не используется.
- **Включите Encryption at Rest:** Используйте KMS v2 для защиты данных в etcd.
- **Регулярная ротация:** Автоматизируйте смену паролей и ключей с помощью внешних инструментов (ESO, Reloader).
- **Аудит доступа:** Включите Kubernetes Audit Logs для отслеживания обращений к секретам.
- **Маскирование в логах:** Используйте специализированные библиотеки для маскирования конфиденциальных данных в логах приложения.
- **Безопасность в CI/CD:** Никогда не храните секреты в Git в открытом виде. Используйте [Sealed Secrets](../../Security/sealed_secrets_overview.md) или [SOPS](../../../Security/Tools/sops_overview.md).
- **NetworkPolicy:** Ограничьте сетевой доступ к сервисам, работающим с секретами.
- **Pod Security Admission:** Используйте профиль `restricted` для неймспейсов с секретами.
- **Сканирование репозиториев:** Настройте Gitleaks или detect-secrets в pre-commit хуках и CI/CD.

### Смотрите также

- [Хранение в etcd](etcd_storage.md) — детали шифрования и лимитов.
- [Внешние менеджеры](external_managers.md) — интеграция с Vault и облачными KMS.
- [RBAC](../../Security/rbac/rbac_overview.md) — настройка прав доступа.
- [Управление секретами приложений](../../Security/application_secrets_management.md) — паттерны доставки секретов.
- [Helm + секреты](helm_secrets.md) — безопасное управление секретами в Helm-чартах.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние PSA restricted на монтирование секретов.
- [Секреты в StatefulSet](statefulset_secrets.md) — паттерны для баз данных и stateful-приложений.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — шифрование секретов для Git.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование файлов через Mozilla SOPS.
- [cert-manager](../../ToolsUtilities/cert_manager/definitions.md) — автоматизация TLS-сертификатов.
- [Vault + Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — интеграция с HashiCorp Vault.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение подходов к хранению секретов в Git.
