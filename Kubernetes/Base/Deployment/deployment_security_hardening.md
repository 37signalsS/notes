# Безопасность Deployment в Kubernetes

Практическое руководство по hardening манифестов Deployment для production-среды: изоляция контейнеров, защита от эскалации привилегий, контроль доступа и защита секретов.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.25+ для стабильных Pod Security Standards).
- Установленный и настроенный `kubectl` с доступом к кластеру.
- Базовое понимание объектов [Deployment](./index.md), [Pod Security Context](../../Security/pod_security_context.md) и [Secrets](../secrets/secrets_basics.md).
- Для admission-контроля: установленный [Kyverno](../../Security/kyverno/concepts.md) или [OPA Gatekeeper](../../Security/rbac/limitations_opa.md).

## 1. Определения

**Security Hardening** — процесс ужесточения конфигурации безопасности Deployment до уровня, соответствующего требованиям production-среды и стандартам (CIS Benchmark, NIST, PCI DSS).

**Defense in Depth** — многоуровневая стратегия безопасности, при которой каждый слой защищает независимо от других: Security Context контейнера, Pod Security Standards неймспейса, NetworkPolicy, RBAC и admission-контроллеры.

> Общая теория SecurityContext, PSS и best practices см. в [Pod Security Context](../../Security/pod_security_context.md), [Pod Best Practices](../Pod/pod_best_practices.md) и [Secrets Management](../../Security/secrets/security.md).

## 2. Базовые концепции

### Многоуровневая модель защиты

```
Уровень 1: Pod Security Standards (namespace)
    ↓
Уровень 2: SecurityContext (Pod + Container)
    ↓
Уровень 3: Admission Controllers (Kyverno/OPA Gatekeeper)
    ↓
Уровень 4: NetworkPolicy (изоляция трафика)
    ↓
Уровень 5: RBAC (доступ к API)
```

> Подробное описание каждого уровня см. в [Pod Security Context](../../Security/pod_security_context.md#pod-security-standards), [Kyverno](../../Security/kyverno/concepts.md) и [NetworkPolicy](../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md).

## 3. Практические сценарии

### Минимальный hardened Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-app
  namespace: production
  labels:
    app.kubernetes.io/name: secure-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app.kubernetes.io/name: secure-app
  template:
    metadata:
      labels:
        app.kubernetes.io/name: secure-app
    spec:
      # Уровень 1: Pod-level security
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 2000
        fsGroup: 2000
        seccompProfile:
          type: RuntimeDefault

      # Отключение автомонтирования токена
      automountServiceAccountToken: false

      # Приоритет для предотвращения вытеснения
      priorityClassName: production-high

      containers:
      - name: app
        image: my-registry.com/app:1.4.2
        imagePullPolicy: IfNotPresent

        # Уровень 2: Container-level security
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop: ["ALL"]

        ports:
        - name: http
          containerPort: 8080

        resources:
          requests:
            cpu: "250m"
            memory: "512Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"

        # Триада проб
        startupProbe:
          httpGet:
            path: /healthz
            port: http
          failureThreshold: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: http
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /live
            port: http
          initialDelaySeconds: 15
          periodSeconds: 20

        # Записываемые каталоги для read-only rootfs
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: app-cache
          mountPath: /var/cache/app

      volumes:
      - name: tmp
        emptyDir:
          sizeLimit: 50Mi
      - name: app-cache
        emptyDir:
          sizeLimit: 100Mi
```

### Типичные векторы атак и защита Deployment

| Вектор | Описание | Защита в Deployment |
|:-------|:---------|:--------------------|
| **Привилегированный контейнер** | Доступ к хост-системе | `allowPrivilegeEscalation: false`, `privileged: false` |
| **Root в контейнере** | Полный контроль над процессами | `runAsNonRoot: true`, `runAsUser: 1000` |
| **Запись в файловую систему** | Подмена кода, логов | `readOnlyRootFilesystem: true` + `emptyDir` |
| **Доступ к API Kubernetes** | Кража токенов | `automountServiceAccountToken: false` |
| **Небезопасный образ** | CVE в зависимостях | Trivy/Grype сканирование в CI/CD |

### NetworkPolicy для изоляции Deployment

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-only-frontend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: secure-app
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: database
    ports:
    - protocol: TCP
      port: 5432
  - to:  # DNS
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
```

> Полные сценарии NetworkPolicy см. в [NetworkPolicy practical scenarios](../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md).

### Kyverno policies для Deployment

```yaml
# Запрет привилегированных контейнеров
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-privileged-containers
spec:
  validationFailureAction: Enforce
  rules:
  - name: validate-privileged
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Привилегированные контейнеры запрещены"
      pattern:
        spec:
          containers:
          - securityContext:
              privileged: "false"
              allowPrivilegeEscalation: "false"
```

> Полные сценарии Kyverno см. в [Kyverno policies](../../Security/kyverno/concepts.md).

### Sigstore/Cosign проверка образов

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signatures
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-image-signature
    match:
      any:
      - resources:
          kinds:
          - Pod
    verifyImages:
    - imageReferences:
      - "my-registry.com/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              ...
              -----END PUBLIC KEY-----
```

### Security Context для разных типов приложений

| Тип приложения | Рекомендации |
|:---------------|:-------------|
| **Web-сервер (Nginx, Apache)** | `readOnlyRootFilesystem: true`, `runAsUser: 101` (nginx), `drop: ["ALL"]`, `emptyDir` для `/tmp` |
| **Приложение на Go** | `readOnlyRootFilesystem: true`, `runAsUser: 1000`, `drop: ["ALL"]`, `seccompProfile: RuntimeDefault` |
| **Приложение на Java** | `readOnlyRootFilesystem: true`, `runAsUser: 1000`, `drop: ["ALL"]`, больше `memory` для JVM |
| **База данных (PostgreSQL)** | `runAsUser: 999` (postgres), `fsGroup: 999`, `emptyDir` для `/var/run/postgresql` |

### Проверка безопасности перед деплоем

```bash
# 1. Валидация манифеста
kubeconform -strict -summary deployment.yaml

# 2. Dry-run с проверкой admission-контроллеров
kubectl apply -f deployment.yaml --dry-run=server

# 3. Проверка с Kyverno CLI
kyverno apply policy.yaml --resource deployment.yaml

# 4. Сканирование образа на CVE
trivy image my-registry.com/app:1.4.2

# 5. Проверка текущих подов на проблемы безопасности
kubectl get pods -n production -o json | jq '.items[] | {
  name: .metadata.name,
  privileged: .spec.containers[].securityContext.privileged,
  readOnlyRootFilesystem: .spec.containers[].securityContext.readOnlyRootFilesystem,
  runAsNonRoot: .spec.securityContext.runAsNonRoot,
  capabilities: .spec.containers[].securityContext.capabilities
}'
```

## 4. Дополнительная информация

### См. также
- [Pod Security Context](../../Security/pod_security_context.md) — детальный разбор всех полей securityContext.
- [Pod Best Practices](../Pod/pod_best_practices.md) — best practices для Pod.
- [Pod Security Standards](../../Security/pod_security_context.md#pod-security-standards) — профили PSS (privileged, baseline, restricted).
- [Kyverno](../../Security/kyverno/concepts.md) — policy engine для Kubernetes.
- [OPA Gatekeeper](../../Security/rbac/limitations_opa.md) — альтернативный policy engine.
- [Trivy](../../Docker/Docker_security/vulnerability_scanning.md) — сканирование образов на CVE.
- [Secrets Management](../../Security/secrets/security.md) — управление секретами.
- [NetworkPolicy](../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md) — сетевая изоляция (12 сценариев).
