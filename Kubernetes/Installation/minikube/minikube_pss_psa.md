# Minikube: Pod Security Standards (PSS) и Pod Security Admission (PSA)

## Определения

**Pod Security Standards (PSS)** — набор стандартов безопасности, определяющих, какие настройки `SecurityContext` допустимы для подов. Реализуются через механизм PSA. Подробнее: [Pod Security Context](../../../Security/pod_security_context.md).

**Pod Security Admission (PSA)** — встроенный admission controller в Kubernetes (GA с 1.25+), применяющий PSS через метки Namespace. Поддерживает три режима:
- `enforce` — блокировка нарушений (под не создаётся).
- `audit` — логирование нарушений (под создаётся, но в аудит-лог попадает запись).
- `warn` — предупреждение (под создаётся, но клиент получает предупреждение).

**Три профиля PSS:**
- `privileged` — без ограничений (по умолчанию в большинстве namespace).
- `baseline` — запрещает явно небезопасные настройки (hostNetwork, privileged containers).
- `restricted` — максимальная изоляция (запрет hostPath, runAsRoot, privilege escalation).

---

## Базовые концепции

### PSA в Minikube

| Параметр | Значение |
| :--- | :--- |
| **Версия K8s** | v1.25+ (PSA GA) |
| **По умолчанию** | namespace `default` имеет профиль `privileged` |
| **Включение** | Через метки на Namespace |
| **Проверка** | `kubectl get ns -o json` или `kubectl describe ns <name>` |

### Зачем тестировать PSA в Minikube

- Проверка, что манифесты совместимы с `restricted` профилем перед деплоем в production.
- Отладка ошибок `violates PodSecurity "restricted:latest"`.
- Настройка PSA для namespace с секретами (Secret volumes).
- Тестирование `securityContext` контейнеров.

---

## Практические сценарии

### Шаг 1: Проверка текущего PSA

```bash
# Просмотр PSA-меток на namespace
kubectl get ns default -o jsonpath='{.metadata.labels}' | python3 -m json.tool
# → {}   ← нет PSA-меток = privileged (всё разрешено)

# Проверка PSA через kubectl
kubectl get ns -o custom-columns=\
NAME:.metadata.name,\
ENFORCE:.metadata.labels.pod-security\.kubernetes\.io/enforce,\
WARN:.metadata.labels.pod-security\.kubernetes\.io/warn,\
AUDIT:.metadata.labels.pod-security\.kubernetes\.io/audit
# → NAME              ENFORCE      WARN         AUDIT
# → default           <none>       <none>       <none>
# → kube-system       <none>       <none>       <none>
```

### Шаг 2: Включение PSA в режиме warn (безопасно для тестов)

```bash
# Добавление метки PSA: warn=restricted
kubectl label namespace default \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/warn-version=latest

# Проверка
kubectl get ns default -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/warn}'
# → restricted
```

### Шаг 3: Тестирование запрещённого пода

```yaml
# privileged-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: privileged-pod
spec:
  containers:
  - name: app
    image: nginx:1.27
    securityContext:
      privileged: true  # ← нарушение restricted PSS
```

```bash
kubectl apply -f privileged-pod.yaml

# Режим warn: под создаётся, но с предупреждением
# WARNING: ... violates PodSecurity "restricted:latest":
#   privileged: Forbidden (disallow by default)

# Включение enforce (блокировка)
kubectl label namespace default \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest

# Повторная попытка — под БЛОКИРУЕТСЯ
kubectl apply -f privileged-pod.yaml
# → Error from server (Forbidden): pods "privileged-pod" is forbidden:
# violates PodSecurity "restricted:latest":
#   privileged: Forbidden (disallow by default)

# Очистка enforce (чтобы не ломать существующие поды)
kubectl label namespace default pod-security.kubernetes.io/enforce-
```

### Шаг 4: Правильный под для restricted PSS

```yaml
# restricted-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: restricted-pod
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: nginx:1.27
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: cache
      mountPath: /var/cache/nginx
    - name: run
      mountPath: /var/run
  volumes:
  - name: tmp
    emptyDir: {}
  - name: cache
    emptyDir: {}
  - name: run
    emptyDir: {}
```

```bash
# Проверка через dry-run (с учётом PSA)
kubectl apply -f restricted-pod.yaml --dry-run=server
# → pod/restricted-pod created (no errors = compliant)

# Реальное применение
kubectl apply -f restricted-pod.yaml
# → pod/restricted-pod created

kubectl get pod restricted-pod
# → NAME             READY   STATUS    RESTARTS   AGE
# → restricted-pod   1/1     Running   0          10s
```

### Шаг 5: Настройка PSA для Namespace с секретами

```yaml
# secure-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: secure-app
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
```

```bash
kubectl apply -f secure-namespace.yaml

# Проверка меток
kubectl describe ns secure-app
# → Name:         secure-app
# → Labels:       pod-security.kubernetes.io/enforce=baseline
#                 pod-security.kubernetes.io/warn=restricted
#                 pod-security.kubernetes.io/audit=restricted

# Под в restricted-стиле работает
kubectl apply -f restricted-pod.yaml -n secure-app
# → pod/restricted-pod created

# Под с hostPath — предупреждение (warn) + аудит
kubectl apply -f hostpath-pod.yaml -n secure-app
# WARNING: ... violates PodSecurity "restricted:latest":
#   hostPath volumes ( forbidden )
# Pod создаётся, но в аудит-лог попадает запись
```

### Шаг 6: Диагностика PSA-ошибок

```bash
# Типичные ошибки PSA и их решения

# Ошибка 1: hostPath запрещён
# → violates PodSecurity "restricted:latest": hostPath (forbidden)
# Решение: использовать emptyDir или PVC

# Ошибка 2: привилегированный контейнер
# → violates PodSecurity "restricted:latest": privileged (forbidden)
# Решение: убрать privileged: true, использовать capabilities

# Ошибка 3: запуск от root
# → violates PodSecurity "restricted:latest": runAsNonRoot != true
# Решение: добавить runAsNonRoot: true и runAsUser: 1000

# Ошибка 4: allowancePrivilegeEscalation
# → violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false
# Решение: добавить allowPrivilegeEscalation: false

# Просмотр всех ошибок PSA в кластере
kubectl get events --field-selector reason=FailedCreate -A | grep -i podsecurity
```

### Очистка

```bash
kubectl label namespace default pod-security.kubernetes.io/warn-
kubectl label namespace default pod-security.kubernetes.io/enforce-
kubectl label namespace default pod-security.kubernetes.io/audit-
kubectl delete namespace secure-app
kubectl delete pod restricted-pod --ignore-not-found
```

---

## Дополнительная информация

### См. также

- [Pod Security Context](../../../Security/pod_security_context.md) — полная теория PSS/PSA
- [Pod Security Standards и Secret](../../../Base/secrets/pod_security_and_secrets.md) — влияние PSA на монтирование секретов
- [Ephemeral Containers](../../../Base/Pod/ephemeral_containers.md) — профили отладки PSA
- [Namespace](../../../Base/namespace.md) — PSA и Labeling

### Полезные ссылки

- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/) — официальная документация
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/) — профили PSS
