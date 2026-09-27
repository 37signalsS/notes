# Ошибки загрузки образов (Image Pull Errors): HPA и автоскейлинг

## Определения

**HPA (Horizontal Pod Autoscaler)** — контроллер Kubernetes, автоматически масштабирующий количество реплик Deployment/ReplicaSet на основе метрик (CPU, Memory, Custom Metrics). При масштабировании вверх создаёт новые поды, каждый из которых требует pull-операции.

**Cluster Autoscaler** — компонент, автоматически добавляющий/удаляющий узлы в кластере в зависимости от потребностей подов. При добавлении узлов — все поды на новом узле требуют pull-операций.

**Rate Limiting (ограничение частоты запросов)** — политика реестра, ограничивающая количество pull/push операций за период. Docker Hub: 100 pull/6h для анонимных, 200 pull/6h для авторизованных. При превышении — ответ `429 Too Many Requests`.

**Pull-through Cache (кэш с проксированием)** — режим реестра (Harbor, Nexus), при котором запросы к публичным образам проксируются на upstream-реестр, а результат кэшируется локально. Снижает задержку и экономит трафик.

---

## Основные концепции

### Механизм влияния HPA на image pull

```
HPA triggers scale-up
  ↓
New Pods created
  ↓
Each Pod needs image
  ↓
Parallel pull requests to registry
  ↓
Rate limit exceeded → 429 Too Many Requests
  ↓
Pods in ImagePullBackOff
  ↓
HPA tries to scale again → more pods → more pulls → vicious cycle
```

**Ключевые параметры, влияющие на pull при масштабировании:**

| Параметр | Дефолт | Влияние |
| :--- | :--- | :--- |
| `--registry-pull-qps` (kubelet) | `5` | QPS на каждый реестр с одного узла |
| `--registry-burst` (kubelet) | `10` | Пиковый burst сверх QPS |
| `serializeImagePulls` (kubelet) | `true` | Сериализация pull (один за другим) |
| `maxParallelImagePulls` (kubelet) | `nil` (без ограничения) | Параллельные pull на одном узле |
| `imagePullPolicy` (Pod) | `IfNotPresent` | Влияет на количество обращений к реестру |

### Характерные сценарии возникновения ошибок при масштабировании

| Сценарий | Корневая причина | Типичная ошибка |
| :--- | :--- | :--- |
| **HPA burst (100+ реплик)** | Массовый pull с одного узла/IP | `429 Too Many Requests` |
| **Cluster Autoscaler** | Pull на 10+ новых узлах одновременно | `429` + `i/o timeout` |
| **Rolling update + HPA** | Pull новых образов + старые поды | `ImagePullBackOff` на части подов |
| **DaemonSet + HPA** | Pull на всех узлах одновременно | `429` + `conntrack full` |
| **Pull-through cache miss** | Первый pull нового образа через cache | `429` + `i/o timeout` |

### Связь HPA с Rate Limiting Docker Hub

| Количество подов | `imagePullPolicy` | Pull в час | Лимит Docker Hub | Результат |
| :--- | :--- | :--- | :--- | :--- |
| 10 | `IfNotPresent` | 10 (первый pull) | 100–200 | OK |
| 10 | `Always` | 10 × N restarts | 100–200 | `429` при частых restart |
| 100 | `IfNotPresent` | 100 (первый pull) | 100–200 | OK |
| 100 | `Always` | 100 × N restarts | 100–200 | `429` при rollout |
| 500 | `IfNotPresent` | 500 (первый pull) | 100–200 | `429` на части подов |
| 1000 | `IfNotPresent` | 1000 (первый pull) | 100–200 | `429` на 80%+ подов |

---

## Практические сценарии

### Сценарий 1: HPA burst → 429 Too Many Requests

**Симптом:** При масштабировании HPA с 10 до 100 реплик часть подов получает `ImagePullBackOff` с ошибкой `toomanyrequests: You have reached your pull rate limit`.

**Диагностика:**
```bash
# Проверить текущее количество реплик
kubectl get deploy app -o jsonpath='{.status.replicas}'

# Проверить Events
kubectl get events --field-selector reason=Failed --sort-by='.lastTimestamp' | tail -20

# Проверить HPA status
kubectl get hpa app
# → NAME   REFERENCE         TARGETS   MINPODS   MAXPODS   REPLICAS
# → app    Deployment/app    80%/50%   10        200       100

# Проверить rate limit на Docker Hub
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 0   (лимит исчерпан)
```

**Решение:**

1. **Использовать pull-through cache (Harbor):**
```bash
# Создать proxy cache project в Harbor
# → harbor.local/docker-hub-proxy → upstream: https://registry-1.docker.io

# Настроить containerd
cat > /etc/containerd/certs.d/docker.io/hosts.toml <<EOF
server = "https://registry-1.docker.io"
[host."https://harbor.local/docker-hub-proxy"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
EOF

systemctl restart containerd
```

2. **Увеличить registry-pull-qps и burst:**
```yaml
# /var/lib/kubelet/config.yaml
registryPullQPS: 20
registryBurst: 40
```

3. **Использовать imagePullPolicy: IfNotPresent:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:1.0@sha256:abc123...
      imagePullPolicy: IfNotPresent  # Pull только при первом запуске
```

### Сценарий 2: Cluster Autoscaler → pull на 10+ новых узлах

**Симптом:** Cluster Autoscaler добавил 10 новых узлов. Поды на новых узлах получают `ImagePullBackOff` с `connection timed out`. Поды на старых узлах работают нормально.

**Диагностика:**
```bash
# Проверить, какие узлы новые
kubectl get nodes --sort-by='.metadata.creationTimestamp' | tail -10

# Проверить conntrack на новом узле
ssh <new-node> "sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max"
# → net.netfilter.nf_conntrack_count = 65532
# → net.netfilter.nf_conntrack_max = 65536    # 99.99% заполнен

# Проверить dmesg
ssh <new-node> "dmesg | grep -i conntrack"
# → nf_conntrack: table full, dropping packet
```

**Решение:**

1. **Увеличить conntrack на всех узлах:**
```bash
cat > /etc/sysctl.d/99-conntrack-tuning.conf <<EOF
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_buckets = 131072
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
EOF
sysctl --system
```

2. **Использовать DaemonSet Image Puller:**
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
        - name: pull-nginx
          image: harbor.local/library/nginx:1.25@sha256:abc123...
          command: ["sh", "-c", "echo 'Image pulled'"]
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.9
```

3. **Настроить pull-through cache:**
```bash
# Harbor proxy cache → первый pull идет на Docker Hub, последующие из кэша
# После прогрева cache → pull на новых узлах идет из Harbor (быстро)
```

### Сценарий 3: Rolling update + HPA → разные образы на разных подах

**Симптом:** При rolling update Deployment с `imagePullPolicy: Always` часть подов получает новый образ, часть — старый. HPA масштабирует поды со старым образом.

**Диагностика:**
```bash
# Проверить, какие поды с каким образом
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}'
# → app-v1-abc123    harbor.local/my-app:1.0
# → app-v2-def456    harbor.local/my-app:2.0

# Проверить HPA
kubectl get hpa app -o yaml | grep -A 5 currentMetrics
```

**Решение:**

1. **Использовать digest-пиннинг:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:2.0@sha256:abc123...
      imagePullPolicy: IfNotPresent  # Pull только при первом запуске
```

2. **Использовать immutable Deployment (Kubernetes 1.16+):**
```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  revisionHistoryLimit: 5  # Хранить 5 последних версий
```

3. **Настроить HPA на конкретную версию:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app  # HPA масштабирует только текущую версию
```

### Сценарий 4: DaemonSet + HPA → pull на всех узлах

**Симптом:** DaemonSet обновляется на всех узлах одновременно. Поды на части узлов получают `ImagePullBackOff`.

**Диагностика:**
```bash
# Проверить DaemonSet rollout status
kubectl rollout status daemonset/<name>

# Проверить, какие узлы обновлены
kubectl get pods -l app=<name> -o wide | grep -v "Running"
# → app-xyz789    0/1     ImagePullBackOff   0         node-15
```

**Решение:**

1. **Настроить maxUnavailable для DaemonSet:**
```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1  # Обновлять по одному узлу
```

2. **Использовать pre-pull DaemonSet:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: image-puller
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
        - name: pull-image
          image: harbor.local/my-app:2.0@sha256:abc123...
          command: ["sh", "-c", "echo 'Image pulled'"]
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.9
```

### Сценарий 5: HPA с Custom Metrics → burst pull при достижении порога

**Симптом:** HPA использует Custom Metrics (например, queue depth). При резком росте очереди HPA масштабирует с 10 до 200 реплик за минуту. 190 подов получают `ImagePullBackOff`.

**Диагностика:**
```bash
# Проверить HPA metrics
kubectl get hpa app -o yaml | grep -A 10 metrics

# Проверить scaling events
kubectl get events --field-selector reason=ScalingActive --sort-by='.lastTimestamp'

# Проверить rate limit
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 0
```

**Решение:**

1. **Ограничить максимальное масштабирование:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app
spec:
  maxReplicas: 50  # Ограничить burst
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60  # Стабилизация
      policies:
        - type: Pods
          value: 10
          periodSeconds: 60  # Не более 10 подов в минуту
    scaleDown:
      stabilizationWindowSeconds: 300
```

2. **Использовать pull-through cache:**
```bash
# Harbor proxy cache → первый pull идет на Docker Hub, последующие из кэша
# После прогрева cache → pull из Harbor (без rate limit)
```

3. **Использовать digest-пиннинг:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:1.0@sha256:abc123...
      imagePullPolicy: IfNotPresent
```

### Сценарий 6: Cluster Autoscaler + multiple registries → 429 на одном из реестров

**Симптом:** Cluster Autoscaler добавляет узлы. Поды с образами из Docker Hub получают `429`, поды с образами из Harbor — нет.

**Диагностика:**
```bash
# Проверить, какие образы используют поды
kubectl get pods -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | sort -u
# → docker.io/library/nginx:1.25
# → docker.io/library/busybox:1.36
# → harbor.local/my-app:1.0

# Проверить rate limit для Docker Hub
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 0

# Проверить Harbor
curl -s https://harbor.local/v2/ | jq .
# → {} (пустой JSON = OK)
```

**Решение:**

1. **Настроить pull-through cache для Docker Hub:**
```bash
# Harbor proxy cache → Docker Hub
cat > /etc/containerd/certs.d/docker.io/hosts.toml <<EOF
server = "https://registry-1.docker.io"
[host."https://harbor.local/docker-hub-proxy"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
EOF
```

2. **Использовать imagePullPolicy: IfNotPresent:**
```yaml
spec:
  containers:
    - name: app
      image: harbor.local/my-app:1.0@sha256:abc123...
      imagePullPolicy: IfNotPresent
```

3. **Настроить imagePullSecrets для Docker Hub:**
```bash
kubectl create secret docker-registry dockerhub-creds \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<username> \
  --docker-password=<password> \
  -n production

kubectl patch serviceaccount default -n production \
  -p '{"imagePullSecrets": [{"name": "dockerhub-creds"}]}'
```

---

## Дополнительная информация

### Связанные темы

- [Распространённые ошибки](./common_errors.md) — разбор ошибок реестров (401, 403, 429).
- [Сетевые проблемы](./network_issues.md) — диагностика conntrack, ephemeral ports и MTU.
- [Лучшие практики](./best_practices.md) — рекомендации по стабильности и безопасности.
- [HPA (теория)](../../../../Kubernetes/Autoscaling/HPA/hpa_concepts.md) — полное описание HPA, метрик и поведения.
- [Cluster Autoscaler](../../../../Kubernetes/Autoscaling/cluster_autoscaler_detailed.md) — настройка и диагностика.
- [On-Premise Autoscaling](../../../../Kubernetes/Autoscaling/on_premise_autoscaling.md) — autoscaling без облачных провайдеров.
- [Pod Disruption Budget](../../../../Kubernetes/Autoscaling/pod_disruption_budget.md) — защита от mass eviction при масштабировании.
