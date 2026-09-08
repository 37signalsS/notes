# CreateContainerConfigError: Проблемы с Secret

## Определения

**Secret-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки среды выполнения контейнера, когда `kubelet` не может сформировать полную конфигурацию из-за проблем с объектами `Secret`. Это блокирует создание контейнера в рантайме (container runtime), так как внешние зависимости для переменных окружения или томов недоступны или некорректны.

В отличие от ошибок времени выполнения приложения (CrashLoopBackOff), эта проблема возникает до запуска контейнера, поэтому логи приложения отсутствуют и диагностика полностью полагается на события API-сервера (`kubectl describe pod`).

### Связь с другими файлами серии

| Файл | Фокус |
| :--- | :--- |
| [definitions.md](./definitions.md) | Общие определения CreateContainerConfigError, жизненный цикл, таймауты |
| [diagnostics.md](./diagnostics.md) | Общий алгоритм диагностики всех причин CreateContainerConfigError |
| [configmap_issues.md](./configmap_issues.md) | Проблемы с ConfigMap |
| [rbac_issues.md](./rbac_issues.md) | Проблемы с RBAC и ServiceAccount |
| [prevention.md](./prevention.md) | Профилактика, CI/CD валидация, Admission-политики |
| **Данный файл** | Secret-специфичные причины, диагностика, исправление |

## Основные концепции

### Архитектура Secret в Kubernetes

**Secret** — объект Kubernetes, предназначенный для хранения конфиденциальной информации: паролей, OAuth-токенов, SSH-ключей, API-ключей и сертификатов. В отличие от ConfigMap, Secret предназначена для данных, требующих защиты, хотя по умолчанию хранится в Base64 без шифрования.

**Хранение в etcd:**
```
API-сервер → etcd (хранилище)
    ├── Secret объект (метаданные + данные в Base64)
    ├── Опционально: Encryption at Rest (AES-CBC, AES-GCM, KMS)
    └── Лимит: 1 MiB на объект
```

**Ключевой момент:** Base64-кодирование — это **НЕ** шифрование. Данные в Secret доступны любому, кто имеет право чтения в namespace. Для реальной защиты необходимо включать шифрование хранилища (Encryption at Rest).

### Типы Secret

| Тип | Назначение | Формат данных | Типичное использование |
| :--- | :--- | :--- | :--- |
| `Opaque` | Произвольные данные | Base64 в поле `data` | Пароли, API-ключи, токены |
| `kubernetes.io/tls` | TLS-сертификаты | Ключи `tls.crt` и `tls.key` | Ingress, API-сервер |
| `kubernetes.io/dockerconfigjson` | Docker-креды | JSON в поле `.dockerconfigjson` | Доступ к приватным реестрам |
| `kubernetes.io/ssh-auth` | SSH-ключи | Ключ в поле `ssh-privatekey` | SSH-доступ к серверам |
| `kubernetes.io/service-account-token` | Токены SA | JWT в поле `token` | Автоматическое (K8s < 1.24) |
| `bootstrap.kubernetes.io/token` | Bootstrap-токены | JWT для API-сервера | Join узлов в кластер |

### Механизм возникновения ошибки (SyncPod Workflow)

1.  **SyncPod Loop:** `kubelet` получает команду на запуск пода и начинает резолвить зависимости.
2.  **Dependency Resolution:** `kubelet` идентифицирует все ссылки на Secret в разделах `env`, `envFrom` и `volumes`.
3.  **API Fetch:** `kubelet` запрашивает содержимое всех Secret через API-сервер.
4.  **Data Processing:**
    *   **env/envFrom:** `kubelet` декодирует Base64 и сопоставляет ключи с переменными окружения.
    *   **volumes:** Агент подготавливает локальную директорию на узле и записывает данные.
5.  **Validation:** Проверяется тип Secret (если ожидается TLS, но данные не валидны — ошибка).
6.  **Блокировка:** При любой неудаче на этих этапах под переходит в `CreateContainerConfigError`.

**Важный нюанс:** `kubelet` не кэширует Secret между попытками. Каждый цикл синхронизации запрашивает данные заново через API-сервер.

### Способы использования Secret и риски

1.  **Переменные окружения (`env`, `envFrom`):**
    *   Secret декодируется из Base64 и передается как переменная окружения.
    *   **Риск:** Данные видны в `kubectl describe pod`, в логах kubelet, в `/proc/<pid>/environ` на узле.
    *   Обновление Secret **не подхватывается** работающим процессом (требуется рестарт).

2.  **Монтирование как тома (`volumes`):**
    *   Secret монтируется как файловая система (tmpfs по умолчанию).
    *   **Преимущество:** Данные не попадают в логи и `/proc`.
    *   Обновление файлов происходит через `kubelet` sync (~60 сек).

3.  **Projected Volumes:**
    *   Secret может быть частью aggregated volume с ConfigMap, Downward API, ServiceAccountToken.
    *   **Риск:** Сбой одного источника блокирует весь том.

4.  **imagePullSecrets:**
    *   Secret типа `dockerconfigjson` для доступа к приватным реестрам.
    *   Ошибка блокирует pull образа → `ImagePullBackOff` или `CreateContainerConfigError`.

### Типичные причины возникновения ошибки

| Сообщение в Events | Причина | Статус ресурса | Частота |
| :--- | :--- | :--- | :--- |
| `secret "x" not found` | Секрет не существует в данном Namespace | **Missing** | Очень высокая |
| `secret "x" not found: key "y" not found` | Секрет существует, но в нем нет требуемого ключа | **Key Missing** | Высокая |
| `Error: Secret "x" is not a valid secret type` | Несоответствие типа (например, ожидался TLS) | **Invalid Type** | Средняя |
| `forbidden: user "x" cannot get resource "secrets"` | У ServiceAccount пода нет прав на чтение секрета | **RBAC Error** | Высокая |
| `secret "x" is not valid base64 data` | Повреждены данные в поле `data` | **Corrupt Data** | Низкая |
| `secret "x" exceeds maximum size` | Превышен лимит 1 MiB | **Size Limit** | Низкая |
| `failed to mount secret: ...` | Ошибка монтирования TOM (CSI, SELinux) | **Mount Error** | Средняя |

### Лимиты и параметры управления

*   **Размер:** Максимальный размер одного объекта Secret — **1 MiB** (включая метаданные и данные в Base64). Превышение лимита приведет к ошибке при создании самого секрета или его чтении.
*   **Количество ключей:** Kubernetes не накладывает жестких лимитов на количество ключей в Secret, но слишком большое количество может замедлить запуск пода (каждый ключ — отдельный файл или переменная).
*   **Иммутабельность (`immutable: true`):** С K8s 1.21 позволяет отключить отслеживание изменений `kubelet`-ом. Это снижает нагрузку на API-сервер (убирает Watch-запросы), но требует пересоздания пода или Secret при необходимости обновления данных.
*   **Base64:** Данные в поле `data` должны быть валидным Base64. Невалидные данные приведут к ошибке чтения.

## Алгоритм диагностики Secret-ошибок

```text
CreateContainerConfigError + secret-related
│
├── 1. Проверить Events пода
│   ├── "secret 'x' not found" → Проверить existence Secret в namespace пода (шаг 2)
│   ├── "key 'y' not found" → Проверить ключи в Secret (шаг 3)
│   ├── "forbidden: ... cannot get resource 'secrets'" → RBAC (см. rbac_issues.md)
│   ├── "not a valid base64 data" → Повреждены данные в Secret
│   └── "exceeds maximum size" → Превышен лимит 1 MiB
│
├── 2. Проверить Existence Secret
│   ├── kubectl get secret <name> -n <pod-namespace> → существует?
│   ├── Если нет → проверить во всех namespace: kubectl get secret <name> -A
│   ├── Если есть, но в другом namespace → исправить манифест пода
│   └── Если нет нигде → создать Secret
│
├── 3. Проверить Ключи в Secret
│   ├── kubectl get secret <name> -o jsonpath='{.data}' | jq 'keys'
│   ├── Сравнить с ключами в манифесте пода (secretKeyRef.key)
│   └── Если ключ отсутствует → добавить ключ или исправить манифест
│
├── 4. Проверить Тип Secret
│   ├── kubectl get secret <name> -o jsonpath='{.type}'
│   ├── Если ожидается kubernetes.io/tls → проверить наличие tls.crt и tls.key
│   └── Если ожидается dockerconfigjson → проверить формат JSON
│
├── 5. Проверить Размер
│   └── kubectl get secret <name> -o json | wc -c → не более 1 MiB (1048576)
│
└── 6. Проверить Проекцию Тома (если используется projected volume)
    ├── Проверить все источники в projected volume
    └── Для необязательных источников использовать optional: true
```

## Практические сценарии

### Сценарий 1: Секрет отсутствует (Namespace mismatch)

Самая частая причина — манифест пода ссылается на секрет, который создан в другом Namespace.

**Диагностика:**
```bash
# Проверка наличия в Namespace пода
kubectl get secret <secret-name> -n <namespace>
# → Error from server (NotFound): secrets "<secret-name>" not found

# Проверка всех namespace (где может быть секрет)
kubectl get secret <secret-name> -A
# → NAME          TYPE     DATA   AGE
# → my-secret     Opaque   3      2d   <-- в другом namespace

# Проверка namespace пода
kubectl get pod <pod-name> -o jsonpath='{.metadata.namespace}'
```

**Типичные причины:**
- Манифест пода создан для `production`, а Secret — в `dev`
- Опечатка в имени namespace в Helm values
- Secret создается отдельным манифестом, но Applied в другой namespace

**Решение:** Убедитесь, что Secret и Pod находятся в одном namespace. Если нужен кросс-неймспейс доступ, используйте ClusterRole + RoleBinding (см. [rbac_issues.md](./rbac_issues.md)).

### Сценарий 2: Отсутствие ключа в Secret (Key mismatch)

Секрет существует, но в нем нет ключа, указанного в манифесте пода.

**Диагностика:**
```bash
# Просмотр всех ключей в Secret
kubectl get secret <secret-name> -o jsonpath='{.data}' | jq 'keys'
# → ["password", "username"]  # ключа "api-key" нет

# Проверка ключей в манифесте пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].env[*].valueFrom.secretKeyRef.key}'
```

**Типичная ошибка:**
```yaml
# Манифест пода ссылается на ключ "api-key"
env:
- name: API_KEY
  valueFrom:
    secretKeyRef:
      name: app-secrets
      key: api-key  # Этого ключа нет в Secret
```

**Решение:** Добавьте недостающий ключ в Secret или исправьте манифест пода.

### Сценарий 3: Невалидный тип Secret

Ожидается определенный тип Secret (например, TLS), но данные не соответствуют формату.

**Пример ошибки:**
```text
Events:
  Warning  Failed  kubelet  Error: secret "my-tls" is not a valid Secret type for TLS: expected "kubernetes.io/tls", got "Opaque"
```

**Диагностика:**
```bash
# Проверка типа Secret
kubectl get secret <secret-name> -o jsonpath='{.type}'
# → Opaque  <-- ожидается kubernetes.io/tls

# Проверка наличия обязательных ключей для TLS
kubectl get secret <secret-name> -o jsonpath='{.data}' | jq 'keys'
# → ["ca.crt", "tls.crt", "tls.key"]  <-- если есть лишние ключи или отсутствуют обязательные
```

**Решение:**
```bash
# Создайте Secret правильного типа
kubectl create secret tls my-tls \
  --cert=tls.crt \
  --key=tls.key \
  -n <namespace>
```

### Сценарий 4: Внешние менеджеры секретов (CSI Secret Store)

При использовании **Secrets Store CSI Driver** (Vault, AWS Secrets Manager), секреты не существуют в K8s как нативные объекты до момента монтирования.

**Диагностика:**
```bash
# Проверка SecretProviderClass
kubectl get secretproviderclass -n <namespace>
kubectl describe secretproviderclass <name> -n <namespace>

# Проверка событий пода на ошибки CSI
kubectl describe pod <pod-name> | grep -A 10 "Events:"
# → Warning  FailedMount  ...  MountVolume.SetUp failed for volume "xxx" : rpc error: code = Unknown desc = ...

# Проверка логов CSI-драйвера
kubectl logs -n kube-system -l app=secrets-store-csi-driver --tail=100
```

**Типичные ошибки:**
- Vault недоступен или истек токен аутентификации
- `SecretProviderClass` ссылается на несуществующий секрет в Vault
- У ServiceAccount нет прав на чтение из Vault

**Решение:** Проверьте доступность Vault, корректность `Role` в Vault и привязку `ServiceAccount`.

### Сценарий 5: Ошибки в Projected Volumes

Если Secret используется в составе `projected` тома вместе с другими источниками (ConfigMap, Downward API, ServiceAccountToken).

**Симптом:** Ошибка в одном источнике блокирует весь том и старт контейнера.

**Пример манифеста:**
```yaml
volumes:
- name: combined-config
  projected:
    sources:
    - secret:
        name: app-secrets
        items:
        - key: password
          path: db/password
    - configMap:
        name: app-config  # Этот ConfigMap не существует!
        items:
        - key: host
          path: db/host
```

**Ошибка:**
```text
Events:
  Warning  Failed  kubelet  Error: projected volume "combined-config": configmap "app-config" not found
```

**Диагностика:**
```bash
# Проверка всех источников в projected volume
kubectl get secret app-secrets,configmap app-config -n <namespace>
```

**Решение:** Убедитесь, что все источники в projected volume существуют. Для необязательных источников используйте `optional: true`.

### Сценарий 6: Использование опциональных секретов (Optional)

Позволяет избежать `CreateContainerConfigError`, если секрет не является критическим (например, для локальной отладки или development).

```yaml
env:
- name: OPTIONAL_SECRET
  valueFrom:
    secretKeyRef:
      name: my-secret
      key: api-key
      optional: true  # Под запустится, даже если секрета нет или ключ отсутствует
```

**Поведение:**
- `optional: true` + Secret не существует → переменная не установлена, под запускается
- `optional: true` + ключ не существует → переменная не установлена, под запускается
- `optional: false` (по умолчанию) + Secret не существует → `CreateContainerConfigError`
- `optional: false` + ключ не существует → `CreateContainerConfigError`

### Сценарий 7: Ошибки с imagePullSecrets

Если Secret типа `dockerconfigjson` отсутствует или некорректен, `kubelet` не может скачать образ из приватного реестра.

**Диагностика:**
```bash
# Проверка imagePullSecrets в Pod
kubectl get pod <pod-name> -o jsonpath='{.spec.imagePullSecrets}'

# Проверка существования Secret
kubectl get secret <secret-name> -n <namespace>

# Проверка типа Secret
kubectl get secret <secret-name> -o jsonpath='{.type}'
# → kubernetes.io/dockerconfigjson

# Проверка валидности JSON
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
```

**Типичная ошибка:**
```text
Events:
  Warning  Failed  kubelet  Error: secret "regcred" not found
```

**Решение:**
```bash
# Создание Secret для Docker-реестра
kubectl create secret docker-registry regcred \
  --docker-server=<your-registry-server> \
  --docker-username=<your-name> \
  --docker-password=<your-pword> \
  --docker-email=<your-email> \
  -n <namespace>
```

### Сценарий 8: Невалидные Base64-данные

Если данные в поле `data` не являются валидным Base64, Secret не может быть прочитан.

**Диагностика:**
```bash
# Проверка данных Secret
kubectl get secret <secret-name> -o jsonpath='{.data.password}' | base64 -d
# → 如果输出乱码或报错，说明Base64数据无效

# Проверка создания Secret
kubectl get secret <secret-name> -o json | jq '.data | to_entries[] | "\(.key): \(.value | length) chars"'
```

**Решение:** Пересоздайте Secret с валидными Base64-данными. Используйте `echo -n "value" | base64` для кодирования.

## Список проверок (Checklist)

### Existence и Namespace
- [ ] Secret существует: `kubectl get secret <name> -n <namespace>`
- [ ] Secret находится в том же namespace, что и Pod
- [ ] Нет опечаток в имени Secret в манифесте пода

### Ключи и данные
- [ ] Все ключи, указанные в `secretKeyRef`, существуют в Secret
- [ ] Ключи не пустые (проверка: `kubectl get secret <name> -o jsonpath='{.data}' | jq 'to_entries[] | select(.value == "" or .value == null)'`)
- [ ] Данные валидны как Base64 (проверка декодирования)

### Тип Secret
- [ ] Тип Secret соответствует ожидаемому (Opaque, kubernetes.io/tls, и т.д.)
- [ ] Для TLS: наличие ключей `tls.crt` и `tls.key`
- [ ] Для Docker-реестра: наличие ключа `.dockerconfigjson`

### Размер и лимиты
- [ ] Размер Secret не превышает 1 MiB: `kubectl get secret <name> -o json | wc -c`
- [ ] Количество ключей приемлемо для производительности пода

### RBAC и безопасность
- [ ] ServiceAccount пода имеет права `get` на Secret: `kubectl auth can-i get secret/<name> --as=system:serviceaccount:<ns>:<sa>`
- [ ] Для кросс-неймспейс доступа: настроен ClusterRole + RoleBinding

### Тома и монтирование
- [ ] Для CSI Secret Store: SecretProviderClass существует и корректен
- [ ] Для projected volumes: все источники существуют (или используются `optional: true`)
- [ ] Для imagePullSecrets: Secret типа `dockerconfigjson` создан и привязан к SA

### Helm / GitOps
- [ ] В Helm-чарте Secret создается корректно (с правильными данными)
- [ ] Secret не хранится в открытом виде в Git (используйте Sealed Secrets, SOPS, или External Secrets)
- [ ] При удалении/пересоздании namespace — Secret пересоздается

## Расширенная диагностика

### Проверка целостности данных Secret

```bash
# Быстрая проверка всех ключей в Secret
kubectl get secret <name> -o json | jq -r '.data | to_entries[] | "\(.key): \(.value | length) chars"'

# Проверка валидности Base64 для каждого ключа
kubectl get secret <name> -o json | jq -r '.data | to_entries[] | "\(.key): \(echo -n "\(.value)" | base64 -d 2>&1 | head -c 50)"'

# Проверка наличия пустых ключей
kubectl get secret <name> -o json | jq '.data | to_entries[] | select(.value == "" or .value == null) | .key'
```

### Проверка доступа через impersonation

```bash
# Может ли SA "читать" секреты в своем namespace?
kubectl auth can-i get secrets --as=system:serviceaccount:<namespace>:<sa-name>

# Просмотр всех разрешений SA для secrets
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:<sa-name> | grep secret

# Проверка доступа к конкретному секрету по имени
kubectl auth can-i get secrets/<secret-name> --as=system:serviceaccount:<namespace>:<sa-name>
```

### Диагностика через логи kubelet

```bash
# SSH на узел, где запущен под
ssh <node-name>

# Проверка логов kubelet на ошибки, связанные с Secret
journalctl -u kubelet --since "10 min ago" | grep -i "secret\|forbidden\|not found"

# Типичные сообщения об ошибках:
# - "secret 'x' not found"
# - "forbidden: User 'system:node:<node>' cannot get resource 'secrets'"
# - "failed to decode secret data: illegal base64 data"
# - "secret 'x' exceeds maximum size"

# Проверка, что kubelet может читать Secret для этого пода
kubectl auth can-i get secrets/<secret-name> \
  --as=system:node:<node-name> \
  --as-group=system:nodes \
  -n <namespace>
```

### SubjectAccessReview — глубокая проверка прав

`SubjectAccessReview` — API-запрос, который проверяет, разрешено ли конкретному субъекту выполнить действие над ресурсом.

```yaml
# Пример запроса SubjectAccessReview
apiVersion: authorization.k8s.io/v1
kind: SubjectAccessReview
metadata:
  name: check-sa-secret-access
spec:
  resourceAttributes:
    namespace: production
    verb: get
    resource: secrets
    name: db-credentials
  user: system:serviceaccount:production:my-app-sa
  groups:
  - system:serviceaccounts
  - system:serviceaccounts:production
```

### Команды для быстрой диагностики

```bash
# 1. Быстрая проверка всех зависимостей Secret в Pod
kubectl get pod <pod-name> -o json | jq -r '
  .spec.containers[].env[].valueFrom.secretKeyRef.name // empty,
  .spec.containers[].envFrom[].secretRef.name // empty,
  .spec.volumes[]?.secret?.secretName // empty
' | grep -v '^$' | sort -u | while read -r secret; do
  kubectl get secret "$secret" -n <namespace> &>/dev/null && echo "OK: $secret" || echo "MISSING: $secret"
done

# 2. Проверка RBAC для ServiceAccount
SA=$(kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}')
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:$SA | grep secret

# 3. Поиск всех Secret в namespace
kubectl get secrets -n <namespace> -o custom-columns=\
  'NAME:.metadata.name,TYPE:.type,DATA:.data|length,AGE:.metadata.creationTimestamp'

# 4. Проверка Secret, используемых в конкретном Deployment
kubectl get deployment <name> -o json | jq -r '
  .spec.template.spec.containers[].env[].valueFrom.secretKeyRef.name,
  .spec.template.spec.containers[].envFrom[].secretRef.name,
  .spec.template.spec.volumes[]?.secret?.secretName
' | grep -v '^$' | sort -u | xargs -I {} kubectl get secret {} -n <namespace> 2>/dev/null
```

## Типичные ошибки в Helm-чартах

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| Secret не создан | `secrets "x" not found` | Установить `secret.create: true` в values.yaml |
| Невалидные данные | Secret создан, но с пустыми данными | Проверить `secret.data` в values.yaml |
| Опечатка в имени | Secret создан, но Pod ссылается на другой | Проверить `{{ include "chart.fullname" . }}-secret` |
| Secret в другом namespace | 403 Forbidden | Убедиться, что Secret в том же namespace, что и Pod |
| Base64 не применен | Невалидные данные в Secret | Использовать `b64enc` в Helm шаблоне: `{{ .Values.password | b64enc }}` |
| Secret хранится в Git | Утечка конфиденциальных данных | Использовать Sealed Secrets, SOPS, или External Secrets |

## Дополнительная информация

### Сравнение Secret и ConfigMap

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Назначение** | Конфигурационные данные | Конфиденциальные данные |
| **Формат данных** | UTF-8 текст | Base64 (бинарные данные) |
| **Безопасность** | Открытый текст, не шифруется | Base64 (требуется шифрование в etcd) |
| **Типы** | Один тип | Несколько типов (Opaque, TLS, Docker-registry) |
| **Лимит размера** | 1 MiB | 1 MiB |
| **Обновление томов** | Автоматически (~60 сек) | Автоматически (~60 сек) |
| **Обновление ENV** | Требуется рестарт Pod | Требуется рестарт Pod |
| **Immutable** | K8s 1.21+ | K8s 1.21+ |

### Шифрование Secret в etcd

По умолчанию Secret хранятся в Base64 без шифрования. Для защиты необходимо включать Encryption at Rest:

```bash
# Проверка, включено ли шифрование
kubectl get --raw /api/v1/namespaces/default/secrets | jq '.items[0].type'
# → Opaque (если включено шифрование, данные будут зашифрованы)

# Проверка encryption provider config на API-сервере
# Файл /etc/kubernetes/encryption-config.yaml должен содержать:
# resources:
#   - resources: ["secrets"]
#     providers:
#       - aescbc:
#           keys:
#             - name: key1
#               secret: <base64-encoded-key>
#       - identity: {}
```

### Best Practices для Secret

1. **Не храните Secret в Git** — используйте Sealed Secrets, SOPS, или External Secrets Operator
2. **Включайте Encryption at Rest** — шифрование данных в etcd
3. **Используйте RBAC** — ограничьте доступ к Secret на уровне namespace
4. **Монтируйте как том, а не ENV** — данные не попадают в логи и `/proc`
5. **Используйте immutable** — для production секретов, которые не меняются
6. **Ротируйте регулярно** — обновляйте пароли и токены

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика CreateContainerConfigError](./prevention.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [Безопасность секретов (Encryption at Rest)](../../../Base/secrets/security.md)
- [Создание Secret](../../../Base/secrets/creating_secrets.md)
- [Хранение в etcd](../../../Base/secrets/etcd_storage.md)
- [Внешние менеджеры секретов](../../../Base/secrets/external_managers.md)
