# Ошибки загрузки образов (Image Pull Errors): Pod Security Standards и Pod Security Admission

## Определения

**Pod Security Standards (PSS)** — набор стандартов безопасности подов, определяющих три уровня: `privileged`, `baseline`, `restricted`. Каждый уровень задаёт список разрешённых и запрещённых полей в манифесте пода, включая `securityContext`, `volumes` и `containers`.

**Pod Security Admission (PSA)** — встроенный Admission Controller Kubernetes 1.25+, блокирующий создание подов, не соответствующих PSS. Работает на уровне namespace через labels: `pod-security.kubernetes.io/enforce`, `pod-security.kubernetes.io/audit`, `pod-security.kubernetes.io/warn`.

**PodSecurityPolicy (PSP)** — устаревший (deprecated) механизм валидации подов (до Kubernetes 1.25). Заменён на PSA. В новых кластерах не используется.

**imagePullPolicy: Always** — политика загрузки образа, требующая обращения к реестру при каждом запуске контейнера. В контексте PSS — одна из рекомендаций для уровня `restricted`.

---

## Основные концепции

### Как PSS/PSA влияет на image pull

Pod Security Standards влияют на image pull **косвенно** — через ограничения на source registry, теги и image pull policy:

| PSS уровень | Ограничение image pull | Влияние на ошибки |
| :--- | :--- | :--- |
| `privileged` | Нет ограничений | Любые образы из любого источника |
| `baseline` | Запрещены некоторые volume types и capabilities | Минимальное влияние на image pull |
| `restricted` | Требуется `imagePullPolicy: Always` или digest-пиннинг | Запрещает `IfNotPresent` для `:latest` без digest |

### Связь PSS/PSA с типичными ошибками image pull

| Ошибка PSS/PSA | Симптом | Корневая причина |
| :--- | :--- | :--- |
| `forbidden: violates PodSecurity "restricted:latest"` | Pod не создаётся, Events: `Error from server (Forbidden)` | `imagePullPolicy: IfNotPresent` для образа без digest |
| `forbidden:ISTRY: allows running containers from the latest tag` | Pod не создаётся | Использование `:latest` тега без digest-пиннинга |
| `forbidden:ISTRY: allows running images from unknown registries` | Pod не создаётся | Источник образа не входит в whitelist реестров |
| `forbidden:ISTRY: allows running images from untrusted registries` | Pod не создаётся | Образ не подписан (Cosign/Notation) |

### PSS/PSA Labels для namespace

| Label | Значение | Поведение |
| :--- | :--- | :--- |
| `pod-security.kubernetes.io/enforce: restricted` | Enforce | Pod **блокируется** при нарушении |
| `pod-security.kubernetes.io/audit: restricted` | Audit | Pod создаётся, но событие в Audit Log |
| `pod-security.kubernetes.io/warn: restricted` | Warn | Pod создаётся, но с предупреждением |

**Важно:** PSA работает на уровне **namespace**. Если namespace без label — PSA не применяется. Для production рекомендуется `enforce: restricted` или `baseline`.

---

## Практические сценарии

### Сценарий 1: PSS блокирует `imagePullPolicy: IfNotPresent` для `:latest`

**Симптом:** Pod не создаётся с ошибкой:
```
forbidden:ISTRY:latest allows running images from latest tag or without a tag (use "imagePullPolicy: Always" or pin to a digest)
```

**Причина:** PSS `restricted` требует:
- `imagePullPolicy: Always` для `:latest`, ИЛИ
- Digest-пиннинг (`@sha256:...`), ИЛИ
- Версионный тег без `:latest`

**Диагностика:**
```bash
# Проверить PSA labels на namespace
kubectl get namespace production -o jsonpath='{.metadata.labels}'
# → {"pod-security.kubernetes.io/enforce": "restricted"}

# Проверить imagePullPolicy в манифесте
kubectl get pod <pod> -o jsonpath='{.spec.containers[*].imagePullPolicy}'
# → IfNotPresent (нарушение для :latest)
```

**Решение (выбрать одно):**

1. **Digest-пиннинг (рекомендуется):**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:latest@sha256:45b23dee...
      imagePullPolicy: IfNotPresent  # OK для digest
```

2. **Использование imagePullPolicy: Always:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:latest
      imagePullPolicy: Always  # Разрешено PSS restricted
```

3. **Версионный тег:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:1.2.3
      imagePullPolicy: IfNotPresent  # OK для версионного тега
```

### Сценарий 2: Kyverno Policy блокирует образы из Docker Hub

**Симптом:** Pod не создаётся с ошибкой:
```
resource Pod was blocked due to the following policies:
  restrict-image-registries:
    image 'docker.io/library/nginx:latest' is not allowed:
      registry 'docker.io' is not in the allowed list: ['harbor.local', 'registry.k8s.io']
```

**Причина:** Kyverno ClusterPolicy валидирует источник образа. Docker Hub не входит в whitelist.

**Диагностика:**
```bash
# Получить причину отказа
kubectl describe pod <pod> | grep -A 20 Events
kubectl get events --field-selector reason=FailedCreate

# Для Kyverno — посмотреть политику
kubectl get cpol restrict-image-registries -o yaml
```

**Решение:**

1. **Добавить реестр в whitelist политики:**
```yaml
# Kyverno ClusterPolicy
spec:
  validationFailureAction: Enforce
  rules:
    - name: allowed-registries
      match:
        any:
          - resources:
              kinds: ["Pod"]
      validate:
        message: "registry 'docker.io' is not allowed"
        pattern:
          spec:
            containers:
              - image: "harbor.local/* | registry.k8s.io/* | quay.io/*"
```

2. **Использовать исключение для конкретного namespace:**
```yaml
match:
  any:
    - resources:
        kinds: ["Pod"]
        namespaces: ["kube-system", "monitoring"]
```

3. **Для ImagePolicyWebhook:** отредактировать `/etc/kubernetes/admission-config.yaml` на API Server и перезапустить `kube-apiserver`.

### Сценарий 3: OPA Gatekeeper блокирует образы без подписи

**Симптом:** Pod не создаётся с ошибкой:
```
admission webhook "constrainttemplate.enforcement.gatekeeper.sh" denied the request:
[image-not-signed] Image harbor.local/my-app:1.0 is not signed
```

**Причина:** OPA Gatekeeper ConstraintTemplate требует подписи образов (Cosign/Notation). Образ не прошёл проверку.

**Диагностика:**
```bash
# Получить ConstraintTemplate
kubectl get constrainttemplate verify-image-signature -o yaml

# Проверить, какие образы подписанны
cosign verify --key cosign.pub harbor.local/my-app:1.0
```

**Решение:**

1. **Подписать образ в CI/CD:**
```bash
cosign sign --key cosign.key harbor.local/my-app:1.0
```

2. **Добавить исключение для dev/test namespace:**
```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: VerifyImageSignature
metadata:
  name: verify-image-signature
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    excludedNamespaces:
      - "development"
      - "testing"
```

### Сценарий 4: PSA блокирует init-container с образом из публичного реестра

**Симптом:** Pod с init-container не создаётся:
```
forbidden:ISTRY:latest allows running images from latest tag or without a tag (use "imagePullPolicy: Always" or pin to a digest)
```

**Причина:** Init-container использует `image: busybox:latest` без digest-пиннинга. PSS `restricted` блокирует.

**Диагностика:**
```bash
# Проверить init-container
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].image}'
# → busybox:latest

# Проверить PSA на namespace
kubectl get namespace <ns> -o jsonpath='{.metadata.labels.pod-security.kubernetes.io/enforce}'
# → restricted
```

**Решение:**

1. **Digest-пиннинг для init-container:**
```yaml
spec:
  initContainers:
    - name: init
      image: busybox:latest@sha256:abc123...
      imagePullPolicy: IfNotPresent
```

2. **Версионный тег:**
```yaml
spec:
  initContainers:
    - name: init
      image: busybox:1.36
      imagePullPolicy: IfNotPresent
```

### Сценарий 5: PSA блокирует `hostNetwork: true` с image pull

**Симптом:** Pod с `hostNetwork: true` не создаётся:
```
forbidden:ISTRY:hostNetwork allows setting hostNetwork to true
```

**Причина:** PSS `restricted` запрещает `hostNetwork: true`. Если под с `hostNetwork: true` пытается выполнить pull через host network — PSA блокирует.

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.spec.hostNetwork}'
# → true
```

**Решение:**

1. **Использовать `hostNetwork: false` (рекомендуется):**
```yaml
spec:
  hostNetwork: false  # По умолчанию
```

2. **Для特权 подов (kube-system):** использовать `enforce: privileged` в namespace `kube-system`:
```bash
kubectl label namespace kube-system pod-security.kubernetes.io/enforce=privileged
```

### Сценарий 6: PSS/PSA и SecurityContext (securityContext)

**Симптом:** Pod не создаётся с ошибкой:
```
forbidden:ISTRY:allows running containers with the following restricted securityContext fields: runAsNonRoot, seccompProfile
```

**Причина:** PSS `restricted` требует:
- `runAsNonRoot: true`
- `seccompProfile: RuntimeDefault` или `Localhost`
- Нет привилегированных контейнеров

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.spec.containers[*].securityContext}'
# → {} (пустой = нарушение)
```

**Решение:**
```yaml
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: harbor.local/my-app:1.0
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
```

---

## Дополнительная информация

### Связанные темы

- [Распространённые ошибки](./common_errors.md) — разбор ошибок реестров (401, 403, 429).
- [Лучшие практики](./best_practices.md) — рекомендации по стабильности и безопасности.
- [Pod Security Standards (теория)](../../../../Kubernetes/Security/pod_security_standards.md) — полное описание PSS, PSA и PSP.
- [Kyverno Policies](../../../../Kubernetes/Security/kyverno_policies.md) — политики валидации образов через Kyverno.
- [OPA Gatekeeper](../../../../Kubernetes/Security/opa_gatekeeper.md) — политики валидации образов через OPA.
- [Cosign и Notation](../../../../Security/Supply_Chain_Security/artifact_signing.md) — подпись образов для PSS `restricted`.
