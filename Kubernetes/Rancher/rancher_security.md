# Безопасность в Rancher

## Определения

**Pod Security Admission (PSA)** — встроенный механизм Kubernetes (v1.25+) для контроля безопасности подов через профили: `privileged`, `baseline`, `restricted`. Заменил устаревшие Pod Security Policies (PSP).

**Pod Security Standards (PSS)** — три уровня безопасности подов, определяющие допустимые настройки SecurityContext: `privileged` (все разрешено), `baseline` (минимальные ограничения), `restricted` (строгие ограничения).

**NeuVector** — контейнерный сканер и файрвол для Kubernetes, обеспечивающий: сканирование уязвимостей (CVE), compliance-аудит, L7-сетевую защиту в реальном времени.

**CIS Benchmark** — набор проверок безопасности (Center for Internet Security) для Kubernetes и RKE2. Реализован через `rancher-cis-benchmark` и `kube-bench`.

**NetworkPolicy** — Kubernetes-ресурс для управления сетевым трафиком подов (разрешение/запрет входящего и исходящего трафика).

## Базовые концепции

### Модель безопасности Rancher (Defense in Depth)

```
Уровень 1: Cluster Security (RKE2 CIS Hardened)
Уровень 2: Rancher RBAC (Users, Roles, Projects)
Уровень 3: Pod Security Admission (PSA)
Уровень 4: NetworkPolicy (сетевая изоляция)
Уровень 5: NeuVector (сканирование + runtime защита)
```

### Pod Security Admission (PSA)

**Профили:**

| Профиль | Описание | Примеры ограничений |
| :--- | :--- | :--- |
| **privileged** | Без ограничений (системные поды) | Разрешает root, hostPID, hostNetwork |
| **baseline** | Минимальные ограничения | Запрещает hostPID, hostNetwork, privileged |
| **restricted** | Строгие ограничения | Требует nonRoot, drop ALL caps, readonlyRootFS |

**Применение к namespace:**

```bash
# Применитьprivileged к cattle-system
kubectl label namespace cattle-system \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged

# Применить restricted к production
kubectl label namespace production \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted
```

### CIS Benchmark в Rancher

Rancher интегрирован с `rancher-cis-benchmark`, который выполняет проверки CIS Kubernetes Benchmark:

- **Профили:** `rke2-cis-1.x` (строгий), `permissive` (мягкий)
- **Расписание:** можно настроить автоматическое выполнение
- **Отчеты:** доступны в Rancher UI (PDF/CSV)

### NeuVector

NeuVector обеспечивает:
- **Сканирование образов:** проверка CVE перед запуском подов.
- **Runtime защита:** мониторинг сетевого трафика, блокировка подозрительной активности.
- **Compliance:** проверка на соответствие PCI-DSS, HIPAA, NIST.

## Практические сценарии

### Шаг 1: Настройка PSA для namespace

```bash
# Для production-namespace (строгий профиль)
kubectl create namespace production
kubectl label namespace production \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/warn=restricted

# Проверка
kubectl get namespace production --show-labels
# → pod-security.kubernetes.io/enforce=restricted
```

### Шаг 2: Создание Pod с restricted-профилем

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: restricted-pod
  namespace: production
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
  containers:
    - name: app
      image: nginx:alpine
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        limits:
          cpu: "100m"
          memory: "128Mi"
        requests:
          cpu: "50m"
          memory: "64Mi"
      volumeMounts:
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir: {}
```

### Шаг 3: Настройка NetworkPolicy для изоляции

```yaml
# Запретить весь входящий трафик по умолчанию
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress
---
# Разрешить трафик только из frontend в backend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: frontend
      ports:
        - port: 8080
          protocol: TCP
```

### Шаг 4: Установка NeuVector

```bash
# Через Apps & Marketplace в Rancher UI
# Или через Helm:
helm repo add neuvector https://neuvector.github.io/neuvector-helm/
helm install neuvector neuvector/core \
  --namespace cattle-neuvector-system \
  --create-namespace \
  --set manager.svc.type=LoadBalancer
```

### Шаг 5: Запуск CIS Benchmark

```bash
# Через Rancher UI:
# Cluster Management → кластер → CIS Scan → Create Scan

# Или через kubectl:
kubectl apply -f - <<EOF
apiVersion: cis.cattle.io/v1
kind: ClusterScan
metadata:
  name: my-scan
spec:
  scanProfileName: rke2-cis-1.6
EOF

# Просмотр результатов
kubectl get clusterscan my-scan -o yaml
```

### Шаг 6: Настройка SecurityContext для Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: my-app:1.0
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          resources:
            limits:
              cpu: "500m"
              memory: "256Mi"
            requests:
              cpu: "100m"
              memory: "128Mi"
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```

### Шаг 7: Проверка Security Policies

```bash
# Проверка PSA на namespace
kubectl get namespace production -o jsonpath='{.metadata.labels}' | jq .

# Проверка SecurityContext пода
kubectl get pod <name> -n production -o jsonpath='{.spec.containers[0].securityContext}'

# Проверка NetworkPolicy
kubectl get networkpolicy -n production

# Проверка CIS Scan
kubectl get clusterscan -A
```

## Диагностика и устранение неполадок

### Pod отклонен PSA

**Симптом:** `Error: pods "xxx" is forbidden: violates PodSecurity "restricted": ...`

```bash
# Проверка PSA на namespace
kubectl get namespace <namespace> -o jsonpath='{.metadata.labels}'

# Решение: исправить SecurityContext в Pod
# Добавить: runAsNonRoot, drop ALL caps, readOnlyRootFilesystem
```

### NetworkPolicy блокирует трафик

```bash
# Просмотр политик
kubectl get networkpolicy -n <namespace>

# Временное удаление (для теста)
kubectl delete networkpolicy <name> -n <namespace>
```

### NeuVector потребляет много ресурсов

```bash
# Проверка ресурсов
kubectl top pods -n cattle-neuvector-system

# Ограничение ресурсов
helm upgrade neuvector neuvector/core \
  --namespace cattle-neuvector-system \
  --set manager.resources.limits.cpu=500m \
  --set manager.resources.limits.memory=512Mi
```

## Дополнительная информация

### Рекомендации по безопасности

1. **PSA для всех namespace:** включите `restricted` для production.
2. **NetworkPolicy:** всегда создавайте политики (deny-all + allow).
3. **CIS Benchmark:** запускайте после установки и обновления кластера.
4. **NeuVector:** включите для сред с требованиями PCI-DSS/HIPAA.
5. **RBAC:** используйте принцип минимальных привилегий.

### Связанные темы

- [RBAC в Rancher](./rancher_rbac.md) — управление доступом.
- [Установка Rancher Server](./rancher_installation.md) — PSA при установке.
- [RKE: CIS Benchmark](./rancher_rke.md) — настройка сканирования.

**Внешние ресурсы:**

- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
- [NeuVector Documentation](https://open-docs.neuvector.com/)
