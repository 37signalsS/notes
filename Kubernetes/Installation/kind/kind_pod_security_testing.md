# kind — тестирование Pod Security Standards

## Определения

**Pod Security Standards (PSS)** — набор из трёх профилей безопасности, определяющих допустимые конфигурации подов в Kubernetes: `privileged` (все разрешено), `baseline` (минимальные ограничения), `restricted` (строгие ограничения).

**Pod Security Admission (PSA)** — встроенный admission-контроллер (GA с Kubernetes 1.25+), применяющий Pod Security Standards через метки на Namespace. Поддерживает три режима: `enforce` (блокировка нарушений), `audit` (логирование), `warn` (предупреждение).

**SecurityContext** — поле в манифесте Pod/контейнера, задающее параметры безопасности: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation`, `seccompProfile`, `capabilities`.

---

## Основные концепции

### Зачем тестировать Pod Security в kind

kind позволяет безопасно тестировать политики безопасности перед их применением в production:

- Проверить, что манифесты подов проходят `restricted`-профиль
- Отработать ошибки `violates PodSecurity` и их исправление
- Настроить `warn`/`audit` режимы перед включением `enforce`
- Протестировать взаимодействие PSA с admission-плагинами (PodSecurity в kind_configuration.md)

### Уровни Pod Security Standards

| Уровень | Описание | Типичные ограничения |
|:---|:---|:---|
| **privileged** | Без ограничений | Разрешены все конфигурации |
| **baseline** | Минимальные ограничения | Запрещены привилегированные поды, hostPath, hostNetwork |
| **restricted** | Строгие ограничения | Требуется `runAsNonRoot`, `readOnlyRootFilesystem`, запрещены capabilities |

### Режимы PSA

| Режим | Поведение | Использование |
|:---|:---|:---|
| `enforce` | Блокирует поды, нарушающие профиль | Production (после тестирования) |
| `audit` | Логирует нарушения, но не блокирует | Мониторинг, сбор метрик |
| `warn` | Возвращает предупреждение, но не блокирует | Тестирование, CI/CD |

---

## Практические сценарии

### Создание кластера для тестирования PSA

```bash
kind create cluster --name psa-test
```

### Сценарий 1: Включение PSA на Namespace с warn-режимом

```yaml
# psa-warn-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: secure-app
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
```

```bash
kubectl apply -f psa-warn-namespace.yaml

# Попытка запуска привилегированного пода (должна быть заблокирована)
kubectl run privileged-pod --image=nginx --namespace=secure-app --overrides='{"spec":{"securityContext":{"privileged":true}}}'
# → Error: pods "privileged-pod" is forbidden: violates PodSecurity "restricted:latest": privileged (container "privileged-pod" must not set securityContext.privileged=true)

# Попытка запуска пода без securityContext (должна быть заблокирована)
kubectl run insecure-pod --image=nginx --namespace=secure-app
# → Error: violates PodSecurity "restricted:latest": runAsNonRoot (pod must not run as root)
```

### Сценарий 2: Безопасный манифест для restricted-профиля

```yaml
# secure-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-nginx
  namespace: secure-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: secure-nginx
  template:
    metadata:
      labels:
        app: secure-nginx
    spec:
      # Отключение автоматического монтирования ServiceAccount токена
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 8080
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
        # Монтирование tmpfs для записи nginx
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: nginx-cache
          mountPath: /var/cache/nginx
        - name: nginx-run
          mountPath: /var/run
      volumes:
      - name: tmp
        emptyDir: {}
      - name: nginx-cache
        emptyDir: {}
      - name: nginx-run
        emptyDir: {}
```

```bash
kubectl apply -f secure-deployment.yaml

# Проверка: поды запускаются без ошибок
kubectl get pods -n secure-app
# → NAME                          READY   STATUS    RESTARTS   AGE
# → secure-nginx-xxxxx-yyyyy      1/1     Running   0          30s
# → secure-nginx-xxxxx-zzzzz      1/1     Running   0          30s

# Проверка: поды работают от непривилегированного пользователя
kubectl exec -n secure-app secure-nginx-xxxxx-yyyyy -- id
# → uid=1000 gid=1000 groups=1000
```

### Сценарий 3: Исправление манифеста для restricted-профиля

**Исходный манифест (нарушает restricted):**

```yaml
# insecure-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: insecure-app
  namespace: secure-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: insecure
  template:
    metadata:
      labels:
        app: insecure
    spec:
      containers:
      - name: app
        image: nginx
```

```bash
kubectl apply -f insecure-deployment.yaml
# → Error: violates PodSecurity "restricted:latest":
#   runAsNonRoot (pod must not run as root)
#   allowPrivilegeEscalation (container "app" must not set securityContext.allowPrivilegeEscalation=true)
#   seccompProfile (pod must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")
```

**Исправленный манифест:**

```yaml
# secure-deployment-fixed.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: insecure-app
  namespace: secure-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: insecure
  template:
    metadata:
      labels:
        app: insecure
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: app
        image: nginx
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: tmp
          mountPath: /tmp
      volumes:
      - name: tmp
        emptyDir: {}
```

### Сценарий 4: Проверка PSA через kubectl auth can-i

```bash
# Проверка: может ли под запуститься от root
kubectl auth can-i create pods --as=system:serviceaccount:secure-app:default -n secure-app

# Просмотр событий PSA
kubectl get events -n secure-app --field-selector reason=FailedCreate
# → LAST SEEN   TYPE      REASON             OBJECT                MESSAGE
# → 5s          Warning   FailedCreate       pod/insecure-pod      Error: violates PodSecurity "restricted:latest"

# Просмотр аудит-логов PSA
kubectl get events -n secure-app --field-selector reason=PodSecurityViolation
```

### Сценарий 5: Тестирование baseline-профиля

```yaml
# baseline-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: baseline-test
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/enforce-version: latest
```

```bash
kubectl apply -f baseline-namespace.yaml

# Baseline разрешает: непривилегированные поды с hostPath
kubectl run baseline-pod --image=nginx --namespace=baseline-test
# → pod/baseline-pod created (baseline разрешает)

# Baseline запрещает: привилегированные поды
kubectl run priv-pod --image=nginx --namespace=baseline-test --overrides='{"spec":{"securityContext":{"privileged":true}}}'
# → Error: violates PodSecurity "baseline:latest": privileged
```

### Сценарий 6: CI/CD интеграция с PSA

**Проверка манифестов перед деплоем:**

```yaml
# .github/workflows/psa-check.yml
name: PSA Check
on: [push, pull_request]
jobs:
  psa-check:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Create kind cluster with PSA
      uses: helm/kind-action@v1
      with:
        cluster_name: psa-ci
    - name: Apply namespace with enforce
      run: |
        kubectl apply -f - <<EOF
        apiVersion: v1
        kind: Namespace
        metadata:
          name: ci-test
          labels:
            pod-security.kubernetes.io/enforce: restricted
            pod-security.kubernetes.io/enforce-version: latest
        EOF
    - name: Deploy and verify
      run: |
        kubectl apply -f k8s/ -n ci-test
        kubectl wait --for=condition=Ready pods --all -n ci-test --timeout=60s
```

---

## Дополнительная информация

### Ссылки

- [kind — конфигурация кластера](./kind_configuration.md) — настройка PodSecurity admission plugin
- [Pod Security Standards](../../Security/pod_security_context.md) — полная теория PSS/PSA
- [Pod Security и Secret](../../Base/secrets/pod_security_and_secrets.md) — взаимодействие PSA с секретами
- [Официальная документация Pod Security](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
