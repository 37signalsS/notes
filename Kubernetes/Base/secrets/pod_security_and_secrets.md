# Pod Security Standards и Secret

## Определения

**Pod Security Standards (PSS)** — набор правил безопасности, определяющих, какие настройки `SecurityContext` допустимы для Pod в конкретном Namespace. Реализуются через механизм **Pod Security Admission (PSA)**, пришедший на смену устаревшему Pod Security Policy (PSP).

**Pod Security Admission (PSA)** — встроенный admission controller в Kubernetes (GA с 1.25+), применяющий Pod Security Standards через метки Namespace. Поддерживает три режима: `enforce` (блокировка), `audit` (логирование), `warn` (предупреждение).

**Три профиля PSS:**

| Профиль | Описание | Примеры ограничений |
| :--- | :--- | :--- |
| **privileged** | Без ограничений (по умолчанию) | Все разрешено, включая `privileged: true`, `hostNetwork` |
| **baseline** | Минимальные ограничения | Запрещает `privileged`, `hostPID`, `hostIPC`, `hostNetwork`, `hostPath` |
| **restricted** | Строгие ограничения | Требует `runAsNonRoot`, `allowPrivilegeEscalation: false`, `drop: ALL` capabilities, `seccompProfile`, запрещает `hostPath` |

## Основные концепции

### Как PSS влияет на монтирование секретов

Секреты в Kubernetes монтируются через **Volume** (tmpfs) или **переменные окружения**. PSS (особенно `restricted`) оказывает прямое и косвенное влияние на оба метода.

#### Volume mount (tmpfs)

| Параметр PSS | Влияние на Secret Volume |
| :--- | :--- |
| `hostPath: restricted` | **Критично:** запрещает `hostPath`, но Secret volume — это **не** `hostPath`. Стандартные Secret/ConfigMap/Projected volume разрешены во всех профилях |
| `volumes: restricted` | Разрешены только: `configMap`, `downwardAPI`, `emptyDir`, `ephemeral`, `persistentVolumeClaim`, `projected`, `secret` |
| `readOnlyRootFilesystem` | Рекомендуется; Secret volume можно монтировать как `readOnly: true` без конфликтов |
| `runAsNonRoot: true` | Secret volume монтируется с UID/GID из `fsGroup`; приложение должно иметь права на чтение |
| `allowPrivilegeEscalation: false` | Не влияет напрямую на Volume; влияет на процессы, читающие файлы |
| `capabilities: drop: ALL` | Не влияет на Volume; влияет на способность процесса работать с файлами |

**Важно:** стандартные Volume типы (`secret`, `configMap`, `projected`) **не запрещены** даже в профиле `restricted`. Ограничения PSS.apply к `hostPath`, `privileged` и другим небезопасным Volume.

#### Переменные окружения

| Параметр PSS | Влияние на Secret ENV |
| :--- | :--- |
| `hostPath: restricted` | Не влияет (ENV — не Volume) |
| `runAsNonRoot: true` | Не влияет (ENV доступен любому процессу) |
| `automountServiceAccountToken: false` | Рекомендуется; отключает автомонтирование токена SA в `/var/run/secrets/kubernetes.io` |

#### Projected Volume (ServiceAccount токены)

| Параметр PSS | Влияние на Projected Volume |
| :--- | :--- |
| `restricted` | **Требует** использования projected volume для SA токенов вместо автоматического монтирования |
| `automountServiceAccountToken: false` | Рекомендуется в `restricted`; токен монтируется только через явный projected volume |
| `serviceAccountToken` в projected | Разрешен во всех профилях; рекомендуется для bound tokens |

### Совместимость secret volume с Pod Security Standards

**Volume type `secret` разрешен во всех профилях PSS:**

```yaml
# Этот манифест совместим со всеми профилями (privileged, baseline, restricted)
apiVersion: v1
kind: Pod
metadata:
  name: app
  namespace: production
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: myapp:latest
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: secret-vol
      mountPath: /etc/secrets
      readOnly: true
    - name: tmp
      mountPath: /tmp
  volumes:
  - name: secret-vol
    secret:
      secretName: my-secret
      defaultMode: 0400
  - name: tmp
    emptyDir: {}
```

**Volume type `hostPath` запрещен в `baseline` и `restricted`:**

```yaml
# ❌ ОШИБКА: hostPath запрещен в baseline/restricted
volumes:
- name: secret-host
  hostPath:
    path: /etc/secrets
    type: Directory

# ✅ ПРАВИЛЬНО: используйте secret volume
volumes:
- name: secret-vol
  secret:
    secretName: my-secret
```

## Практические сценарии

### Настройка PSA для namespace с секретами

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Enforce: блокирует Pod, не соответствующие restricted
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    # Audit: логирует нарушения (не блокирует)
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    # Warn: предупреждает приubectl apply (не блокирует)
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
```

### Полный манифест Deployment с секретами (restricted)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-app
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: secure-app
  template:
    metadata:
      labels:
        app: secure-app
    spec:
      serviceAccountName: secure-app-sa
      automountServiceAccountToken: false  # отключаем автомонтирование
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: app
        image: myapp:latest
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: password
              optional: false
        volumeMounts:
        - name: secret-vol
          mountPath: /etc/secrets
          readOnly: true
        - name: tls-vol
          mountPath: /etc/tls
          readOnly: true
        - name: tmp
          mountPath: /tmp
        - name: app-cache
          mountPath: /app/cache
      volumes:
      - name: secret-vol
        secret:
          secretName: db-credentials
          defaultMode: 0400
      - name: tls-vol
        secret:
          secretName: app-tls-cert
          defaultMode: 0400
          items:
          - key: tls.crt
            path: server.crt
          - key: tls.key
            path: server.key
      - name: tmp
        emptyDir: {}
      - name: app-cache
        emptyDir: {}
```

### Монтирование ServiceAccount токена (restricted)

```yaml
# Рекомендуемый подход: projected volume с bound token
apiVersion: v1
kind: Pod
metadata:
  name: api-client
  namespace: production
spec:
  automountServiceAccountToken: false  # отключаем автоматическое монтирование
  serviceAccountName: api-client-sa
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: sa-token
      mountPath: /var/run/secrets/tokens
      readOnly: true
  volumes:
  - name: sa-token
    projected:
      sources:
      - serviceAccountToken:
          path: api-token
          expirationSeconds: 3600
          audience: "https://kubernetes.default.svc"
```

### Обработка ошибок PSA при деплое секретов

```bash
# Ошибка: Pod заблокирован PSA
Error: pods "my-pod" is forbidden: violates PodSecurity "restricted:latest":
  hostPath volumes (hostPath "", path "/etc/secrets")

# Решение: замените hostPath на secret volume
kubectl apply -f fixed-manifest.yaml

# Проверка: какие метки PSA на namespace
kubectl get namespace production -o jsonpath='{.metadata.labels}' | jq .

# Тест: проверка без фактического создания Pod
kubectl apply -f pod.yaml --dry-run=server --as=system:serviceaccount:prod:my-sa
```

## Диагностика и типичные ошибки

### Типичные ошибки PSA + Secret

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `violates PodSecurity "restricted:latest"` | Используется `hostPath` вместо Secret volume | Замените `hostPath` на `secret` volume |
| `privileged containers are forbidden` | Контейнер запущен с `privileged: true` | Уберите `privileged: true`, используйте `capabilities` |
| `runAsNonRoot: pod must set securityContext.runAsNonRoot=true` | Pod не задал `runAsNonRoot` | Добавьте `runAsNonRoot: true` в `securityContext` |
| `allowPrivilegeEscalation is not false` | Не установлен `allowPrivilegeEscalation: false` | Добавьте в `securityContext` контейнера |
| `capabilities may not be added` | Контейнер добавляет capabilities | Используйте только `drop: ["ALL"]` |
| `hostPath volumes are forbidden` | Используется `hostPath` для секретов | Замените на `secret` volume |

### Проверка совместимости

```bash
# Проверка манифеста через dry-run=server (с учетом PSA)
kubectl apply -f manifest.yaml --dry-run=server -n production

# Просмотр аудит-логов PSA
kubectl get events -n production --field-selector reason=FailedCreate

# Проверка меток PSA на namespace
kubectl get ns production -o json | jq '.metadata.labels | with_entries(select(.key | startswith("pod-security")))'
```

## Best Practices

1. **Используйте restricted профиль** для production namespace с секретами.
2. **Отключайте automountServiceAccountToken:** `automountServiceAccountToken: false` в Pod/Deployment spec.
3. **Монтируйте SA токены через projected volume:** С `expirationSeconds` и `audience` для bound tokens.
4. **Всегда `readOnly: true`** для Secret volume: предотвращает случайную запись.
5. **Устанавливайте `fsGroup`:** Для non-root контейнеров, чтобы приложение могло читать Secret файлы.
6. **Используйте `fsGroupChangePolicy: OnRootMismatch`:** Ускоряет монтирование томов.
7. **Не используйте hostPath** для секретов — это запрещено в baseline/restricted.
8. **Валидируйте через `--dry-run=server`** перед деплоем в production.

## Дополнительная информация

### Migrация с Pod Security Policy на Pod Security Admission

Pod Security Policy (PSP) удалена в Kubernetes 1.25. Если использовались PSP для контроля секретов:

1. Включите PSA через метки Namespace (см. выше).
2. Проверьте, что все манифесты совместимы с `restricted`.
3. Используйте `--dry-run=server` для тестирования перед включением `enforce`.

### Kyverno / OPA Gatekeeper для секретов

Для более тонкого контроля (например, запрет секретов без аннотаций) используйте Policy Engine. Примеры Kyverno-политик для секретов см. в [Безопасность Secret](security.md) (раздел "Admission Control и политики").

### Смотрите также

- [Pod Security Context](../../Security/pod_security_context.md) — полное описание Security Context.
- [Безопасность Secret](security.md) — общие принципы защиты.
- [RBAC](../../Security/rbac/rbac_overview.md) — настройка прав доступа.
- [NetworkPolicy](../../Security/network_policies.md) — сетевая изоляция.
- [Using Secret](using_secrets.md) — способы доставки секретов в Pod.
- [External Secrets](external_managers.md) — интеграция с внешними хранилищами.
