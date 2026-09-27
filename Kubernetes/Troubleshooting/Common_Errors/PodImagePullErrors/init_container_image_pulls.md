# Ошибки загрузки образов (Image Pull Errors): Init-контейнеры

## Определения

**Init Container** — контейнер, выполняющийся **до** запуска основных контейнеров пода. Инициализирующие контейнеры выполняются последовательно; каждый успешный запуск — условие для следующего. Если init-container завершается с ошибкой — Pod перезапускается (если `restartPolicy: Always`) или останавливается (если `restartPolicy: Never`).

**restartPolicy** — политика перезапуска пода. `Always` (по умолчанию) — перезапуск при любом завершении. `OnFailure` — перезапуск только при ошибке. `Never` — без перезапуска. Для init-контейнеров `restartPolicy: Never` означает, что ошибка init-контейнера = Pod в `CrashLoopBackOff`.

**Init Container Image Pull** — процесс загрузки образа для init-контейнера. Выполняется **отдельно** от основных контейнеров. Если init-container использует `imagePullPolicy: Always` — каждый перезапуск пода требует обращения к реестру.

**ImagePullBackOff в init-контейнере** — состояние, когда init-container не может загрузить образ. Pod остаётся в `Init:ImagePullBackOff` until следующей попытки. Основные контейнеры **не запускаются** до успешного завершения всех init-контейнеров.

---

## Основные концепции

### Жизненный цикл Pod с init-контейнером

```
Pod Created
  ↓
Init Container 1
  ├─ Pull Image → ErrImagePull → ImagePullBackOff → Pod в Init:ImagePullBackOff
  ├─ Pull Image → Success
  ├─ Run Init Container → Success
  ↓
Init Container 2
  ├─ Pull Image → ErrImagePull → Pod в Init:ImagePullBackOff
  ├─ Pull Image → Success
  ├─ Run Init Container → Success
  ↓
All Init Containers Complete
  ↓
Main Containers Start
  ├─ Pull Image → ErrImagePull → ImagePullBackOff
  ├─ Pull Image → Success
  └─ Run Main Container
```

**Ключевой момент:** Ошибки pull в init-контейнерах блокируют запуск **всех** основных контейнеров. Это делает их критичными для availability.

### Типичные ошибки pull в init-контейнерах

| Ошибка | Симптом | Корневая причина |
| :--- | :--- | :--- |
| `ErrImagePull` в init-container | Pod в `Init:ErrImagePull` | Образ не существует, неверный тег, неверный registry |
| `ImagePullBackOff` в init-container | Pod в `Init:ImagePullBackOff` | Серия неудачных попыток pull |
| `CrashLoopBackOff` в init-container | Pod в `Init:CrashLoopBackOff` | Init-container завершился с ошибкой (не pull) |
| `init-container-error` | Pod в `Init:Error` | Init-container завершился с ненулевым кодом |

### Сравнение ошибок pull в init-контейнерах и основных контейнерах

| Параметр | Init Container | Main Container |
| :--- | :--- | :--- |
| **Когда выполняется pull** | До запуска основных контейнеров | После успешного завершения init-контейнеров |
| **Влияние на Pod** | Блокирует запуск основных контейнеров | Под перезапускается (restartPolicy) |
| **Статус пода** | `Init:ImagePullBackOff`, `Init:Error` | `ImagePullBackOff`, `CrashLoopBackOff` |
| **Количество попыток** | Ограничено `restartPolicy` | Без ограничений (при `restartPolicy: Always`) |
| **Параллелизм** | Последовательно (каждый init-container) | Параллельно (все основные контейнеры) |

---

## Практические сценарии

### Сценарий 1: Init-container не может загрузить образ из приватного реестра

**Симптом:** Pod в `Init:ImagePullBackOff`. Events: `Failed to pull image "harbor.local/init-tools:v1": unauthorized: authentication required`.

**Причина:** Init-container не имеет `imagePullSecrets`. Основные контейнеры используют ServiceAccount с secrets, но init-контейнер — нет.

**Диагностика:**
```bash
# Проверить init-container
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].image}'
# → harbor.local/init-tools:v1

# Проверить imagePullSecrets
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].imagePullSecrets}'
# → []

# Проверить ServiceAccount
kubectl get sa <sa-name> -o jsonpath='{.imagePullSecrets}'
# → [{"name": "regcred"}]  # Есть для SA, но init-container не использует SA
```

**Решение:**

1. **Добавить imagePullSecrets в init-container:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1
      imagePullSecrets:
        - name: regcred  # Явное указание
```

2. **Использовать ServiceAccount с imagePullSecrets:**
```yaml
spec:
  serviceAccountName: app-sa  # SA с imagePullSecrets
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1
      # imagePullSecrets наследуются от SA
```

3. **Патч ServiceAccount (глобально):**
```bash
kubectl patch serviceaccount app-sa -n production -p '
{
  "imagePullSecrets": [
    {"name": "regcred"}
  ]
}'
```

### Сценарий 2: Init-container с `imagePullPolicy: Always` → массовый pull при каждом restart

**Симптом:** Pod с init-container использует `imagePullPolicy: Always`. При каждом перезапуске Pod'а init-container обращается к реестру. При высоком `restartPolicy` (OnFailure) — лавина pull-запросов.

**Диагностика:**
```bash
# Проверить imagePullPolicy
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].imagePullPolicy}'
# → Always

# Проверить количество restarts
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].restartCount}'
# → 50

# Проверить rate limit
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 0
```

**Решение:**

1. **Использовать digest-пиннинг:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1@sha256:abc123...
      imagePullPolicy: IfNotPresent  # Pull только при первом запуске
```

2. **Использовать версионный тег:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:1.0.0
      imagePullPolicy: IfNotPresent
```

3. **Ограничить количество restarts:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1
      imagePullPolicy: Always
  restartPolicy: Never  # Не перезапускать Pod при ошибке init-container
```

### Сценарий 3: Init-container с networking → ImagePullBackOff из-за DNS

**Симптом:** Init-container пытается выполнить DNS-запрос (например, `nslookup registry.example.com`). DNS не работает из-за NetworkPolicy. Pod в `Init:ImagePullBackOff`.

**Диагностика:**
```bash
# Проверить init-container
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].name}'
# → init-dns

# Проверить init-container logs
kubectl logs <pod> -c init-dns
# → nslookup: can't resolve 'registry.example.com'

# Проверить NetworkPolicy
kubectl get networkpolicy -n <namespace>
# → allow-dns-egress (не разрешает DNS к внешнему реестру)
```

**Решение:**

1. **Добавить egress для DNS в NetworkPolicy:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

2. **Использовать init-container с другим образом ( без networking):**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: busybox:1.36@sha256:abc123...
      command: ["sh", "-c", "echo 'Init complete'"]
      imagePullPolicy: IfNotPresent
```

### Сценарий 4: Init-container и PSP/PSA блокируют образ

**Симптом:** Pod не создаётся с ошибкой:
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
kubectl get namespace <namespace> -o jsonpath='{.metadata.labels.pod-security.kubernetes.io/enforce}'
# → restricted
```

**Решение:**

1. **Digest-пиннинг для init-container:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: busybox:1.36@sha256:abc123...
      imagePullPolicy: IfNotPresent
```

2. **Версионный тег:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: busybox:1.36
      imagePullPolicy: IfNotPresent
```

### Сценарий 5: Init-container и HPA → burst pull при масштабировании

**Симптом:** HPA масштабирует с 10 до 100 реплик. 90 подов с init-контейнерами получают `ImagePullBackOff` с `429 Too Many Requests`.

**Диагностика:**
```bash
# Проверить количество подов
kubectl get pods -l app=<name> | wc -l
# → 100

# Проверить init-container
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.initContainers[*].image}{"\n"}{end}' | head -10
# → app-abc123    harbor.local/init-tools:v1
# → app-def456    harbor.local/init-tools:v1

# Проверить rate limit
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 0
```

**Решение:**

1. **Использовать pull-through cache:**
```bash
# Harbor proxy cache → Docker Hub
cat > /etc/containerd/certs.d/docker.io/hosts.toml <<EOF
server = "https://registry-1.docker.io"
[host."https://harbor.local/docker-hub-proxy"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
EOF
```

2. **Использовать digest-пиннинг:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1@sha256:abc123...
      imagePullPolicy: IfNotPresent
```

3. **Ограничить масштабирование HPA:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app
spec:
  maxReplicas: 50  # Ограничить burst
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 10
          periodSeconds: 60
```

### Сценарий 6: Init-container с multiple images → pull风暴

**Симптом:** Init-container загружает 5+ образов. При каждом перезапуске Pod'а — 5+ pull-запросов. При `imagePullPolicy: Always` — лавина.

**Диагностика:**
```bash
# Проверить init-container
kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].image}'
# → harbor.local/init-tools:v1
# → harbor.local/init-db:v1
# → harbor.local/init-cache:v1
# → harbor.local/init-migrate:v1
# → harbor.local/init-check:v1

# Проверить количество restarts
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].restartCount}'
# → 20 20 20 20 20
```

**Решение:**

1. **Использовать digest-пиннинг для всех init-контейнеров:**
```yaml
spec:
  initContainers:
    - name: init-tools
      image: harbor.local/init-tools:v1@sha256:abc123...
      imagePullPolicy: IfNotPresent
    - name: init-db
      image: harbor.local/init-db:v1@sha256:def456...
      imagePullPolicy: IfNotPresent
    - name: init-cache
      image: harbor.local/init-cache:v1@sha256:ghi789...
      imagePullPolicy: IfNotPresent
```

2. **Объединить init-контейнеры в один:**
```yaml
spec:
  initContainers:
    - name: init-all
      image: harbor.local/init-tools:v1@sha256:abc123...
      command: ["sh", "-c", "/init-tools.sh && /init-db.sh && /init-cache.sh"]
      imagePullPolicy: IfNotPresent
```

3. **Использовать DaemonSet Image Puller:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: image-puller
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: image-puller
  template:
    metadata:
      labels:
        app: image-puller
    spec:
      initContainers:
        - name: pull-init-tools
          image: harbor.local/init-tools:v1@sha256:abc123...
          command: ["sh", "-c", "echo 'Image pulled'"]
        - name: pull-init-db
          image: harbor.local/init-db:v1@sha256:def456...
          command: ["sh", "-c", "echo 'Image pulled'"]
        - name: pull-init-cache
          image: harbor.local/init-cache:v1@sha256:ghi789...
          command: ["sh", "-c", "echo 'Image pulled'"]
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.9
```

---

## Дополнительная информация

### Связанные темы

- [Распространённые ошибки](./common_errors.md) — разбор ошибок реестров (401, 403, 429).
- [Сетевые проблемы](./network_issues.md) — диагностика DNS, MTU и прокси.
- [Лучшие практики](./best_practices.md) — рекомендации по стабильности и безопасности.
- [Init Containers (теория)](../../../../Kubernetes/Base/Pod/pod_init_containers.md) — полное описание init-контейнеров и их использования.
- [Pod Security Standards](./pod_security_standards.md) — PSS/PSA и их влияние на image pull.
- [HPA и автоскейлинг](./hpa_and_scaling.md) — влияние масштабирования на image pull.
- [DaemonSet Image Puller](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/best_practices.md#сценарий-2-оптимизация-запуска-через-prefetching-образов) — префетчинг образов через DaemonSet.
