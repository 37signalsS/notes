# Metrics Server: Мониторинг ресурсов кластера

## Определения

**Metrics Server** — масштабируемый, эффективный источник метрик использования ресурсов контейнеров для Kubernetes. Работает в оперативной памяти (in-memory) и не хранит исторические данные. Является реализацией **Resource Metrics API** (`metrics.k8s.io`). Собирает метрики с частотой по умолчанию 15 секунд и предоставляет их в реальном времени для автоматического масштабирования.

**cAdvisor (Container Advisor)** — встроенный в `kubelet` компонент, который читает метрики напрямую из `cgroups` (control groups) ядра Linux. cAdvisor собирает данные об использовании ресурсов (CPU, память, сеть, дисковый I/O) с уровня контейнеров и предоставляет их Metrics Server через Kubelet Summary API (порт 10250). В современных версиях Kubernetes (1.16+) cAdvisor полностью интегрирован в kubelet и не требует отдельного развертывания.

**Resource Metrics API (`metrics.k8s.io`)** — стандартный API Kubernetes, через который Metrics Server отдает данные агрегатору (Aggregation Layer). Этот API критичен для работы механизмов автоскейлинга. Поддерживает версию `v1beta1` (стабильная) и `v1` (в разработке). Доступен по пути `/apis/metrics.k8s.io/v1beta1`.

**Kubelet Summary API** — внутренний API kubelet (порт 10250), предоставляющий агрегированные метрики по узлу и подам. Metrics Server опрашивает этот API для получения данных от cAdvisor. Доступен по пути `/stats/summary`.

**Aggregation Layer** — компонент kube-apiserver, который позволяет регистрировать дополнительные API-серверы (如 metrics-server) и маршрутизировать запросы к ним. Metrics Server регистрируется как APIService для `metrics.k8s.io`.

**Область применения:**
- Обеспечение работы команд CLI `kubectl top nodes` и `kubectl top pods`
- Основной, "нативный" источник данных для **[Horizontal Pod Autoscaler (HPA)](../Autoscaling/HPA/index.md)** при масштабировании по CPU и RAM
- Предоставление данных для **[Vertical Pod Autoscaler (VPA)](../Autoscaling/vpa_detailed.md)** в режимах `Off` и `Initial`
- Предоставление данных для планировщика (Scheduler) при принятии решений о размещении подов
- Мониторинг текущего потребления ресурсов в реальном времени

> **Важно:** Metrics Server собирает метрики _только_ по CPU и Memory. Для масштабирования по кастомным метрикам (RPS, длина очереди, HTTP-задержки) требуется **Prometheus Adapter** или **KEDA**.

## Основные концепции

### Место в конвейере данных (Pipeline)

Поток данных телеметрии выглядит следующим образом:

```
Linux cgroups (v1/v2) → kubelet (cAdvisor) → Kubelet Summary API → Metrics Server → kube-apiserver (Aggregation Layer) → HPA / VPA / kubectl top
```

**Детальный поток данных:**

1. **Сбор на узле**: cAdvisor читает метрики из виртуальной файловой системы cgroups (`/sys/fs/cgroup/`)
2. **Агрегация в kubelet**: kubelet собирает метрики от cAdvisor и формирует Summary API
3. **Опрос Metrics Server**: Metrics Server опрашивает kubelet на каждом узле каждые 15 секунд (настраивается через `--metric-resolution`)
4. **Агрегация в API**: Metrics Server агрегирует данные и предоставляет их через Resource Metrics API
5. **Потребление**: HPA, VPA и kubectl получают данные через kube-apiserver

**Сравнение с Prometheus:**

| Характеристика | Metrics Server | Prometheus |
|:---|:---|:---|
| **Частота сбора** | 15 секунд (по умолчанию) | 15–60 секунд (настраивается) |
| **Хранение данных** | In-memory (нет истории) | TSDB (долгосрочное хранение) |
| **Задержка (latency)** | <1 секунды | 5–30 секунд |
| **Назначение** | HPA, VPA, kubectl top | Визуализация, алерты, аналитика |
| **Метрики** | CPU, Memory | Произвольные метрики |
| **Нагрузка на сеть** | Минимальная | Зависит от количества метрик |

В отличие от Prometheus, который собирает метрики раз в 15-60 секунд и добавляет задержку на индексацию, Metrics Server оптимизирован для **минимальной задержки (Low Latency)**. Именно поэтому HPA по умолчанию использует его — это предотвращает эффект staleness (устаревания) при принятии решений об экстренном масштабировании.

### Архитектура и компоненты

Metrics Server состоит из следующих компонентов:

| Компонент | Функция | Ресурсы (по умолчанию) |
|:---|:---|:---|
| **Metrics Server** | Основной сервис, агрегирующий метрики | 100m CPU, 200Mi RAM |
| **APIService** | Регистрация metrics.k8s.io в kube-apiserver | 0 CPU, 0 RAM |
| **Heapster** (deprecated) | Устаревший компонент, заменен Metrics Server | — |

**Схема взаимодействия:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Node 1   │  │  Node 2   │  │  Node 3   │  │  Node N   │  │
│  │  kubelet  │  │  kubelet  │  │  kubelet  │  │  kubelet  │  │
│  │  cAdvisor │  │  cAdvisor │  │  cAdvisor │  │  cAdvisor │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  Metrics Server │                         │
│                   │  (In-Memory)    │                         │
│                   └────────┬───────┘                         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  kube-apiserver │                         │
│                   │  Aggregation    │                         │
│                   │  Layer          │                         │
│                   └────────┬───────┘                         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  HPA / VPA /    │                         │
│                   │  kubectl top    │                         │
│                   └────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### Сбор метрик: cAdvisor и cgroups

cAdvisor собирает метрики из виртуальной файловой системы cgroups. В зависимости от версии ядра Linux, используются cgroups v1 или v2:

| Версия cgroups | Путь к метрикам | Kubernetes версия |
|:---|:---|:---|
| **cgroups v1** | `/sys/fs/cgroup/cpu/`, `/sys/fs/cgroup/memory/` | < 1.25 |
| **cgroups v2** | `/sys/fs/cgroup/` | >= 1.25 (рекомендуется) |

**Метрики, собираемые cAdvisor:**

| Метрика | Описание | Источник |
|:---|:---|:---|
| `container_cpu_usage_seconds_total` | Использование CPU в секундах | cgroups cpuacct |
| `container_memory_working_set_bytes` | Использование RAM (working set) | cgroups memory |
| `container_network_receive_bytes_total` | Входящий сетевой трафик | cgroups net_cls |
| `container_network_transmit_bytes_total` | Исходящий сетевой трафик | cgroups net_cls |
| `container_fs_usage_bytes` | Использование файловой системы | cgroups blkio |
| `container_blkio_device_usage_total` | I/O операции на устройствах | cgroups blkio |

**Важно для понимания:**
- `working_set_bytes` — это используется память + turf (кэш), который может быть вытеснен. Это основная метрика для OOM-решений
- `rss_bytes` — резидентный набор страниц (physical memory), не включает turf
- CPU измеряется в секундах (не в процентах), поэтому для процентов нужно делить на `cpu_cfs_periods_total`

### Архитектура и отказоустойчивость (HA)

Metrics Server разворачивается как `Deployment` в пространстве имен `kube-system`. В крупных (Production) кластерах рекомендуется использовать режим высокой доступности:

**Рекомендации по HA:**

| Параметр | Рекомендация | Обоснование |
|:---|:---|:---|
| **Количество реплик** | 2 (оптимально) | Большее количество не дает преимуществ, так как _каждая_ реплика опрашивает все узлы кластера независимо |
| **Aggregator Routing** | `--enable-aggregator-routing=true` | Балансировка запросов между репликами |
| **Pod Disruption Budget** | `maxUnavailable: 1` | Гарантия доступности Metrics API во время обновления узлов |
| **Anti-Affinity** | `requiredDuringSchedulingIgnoredDuringExecution` | Размещение реплик на разных узлах |
| **Priority Class** | `system-cluster-critical` | Приоритет при вытеснении подов |

**Пример PDB:**
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: metrics-server
  namespace: kube-system
spec:
  minAvailable: 1
  selector:
    matchLabels:
      k8s-app: metrics-server
```

**Пример Anti-Affinity:**
```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: k8s-app
          operator: In
          values:
          - metrics-server
      topologyKey: kubernetes.io/hostname
```

### Масштабирование ресурсов (VPA)

Потребление ресурсов Metrics Server растет пропорционально количеству узлов и подов в кластере.

**Формула расчета (на каждые 100 узлов):**
- **CPU**: Базовые 100m + 1m на каждый узел
- **Memory**: Базовые 200Mi + 2Mi на каждый узел

**Примеры расчета:**

| Кластер | CPU Request | Memory Request | Memory Limit |
|:---|:---|:---|:---|
| 10 узлов, 100 подов | 110m | 220Mi | 500Mi |
| 50 узлов, 500 подов | 150m | 300Mi | 500Mi |
| 100 узлов, 1000 подов | 200m | 400Mi | 500Mi |
| 500 узлов, 5000 подов | 600m | 1.2Gi | 2Gi |

**Важно:** Если кластер может динамически расти, рекомендуется использовать [VPA](../Autoscaling/vpa_detailed.md) в режиме `Auto` или `Initial` исключительно для пода Metrics Server, чтобы он автоматически получал больше RAM и не падал по OOM (Out Of Memory).

**Пример VPA для Metrics Server:**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: metrics-server-vpa
  namespace: kube-system
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: metrics-server
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: metrics-server
      minAllowed:
        cpu: 100m
        memory: 200Mi
      maxAllowed:
        cpu: 2000m
        memory: 4Gi
      controlledResources: ["cpu", "memory"]
```

### Безопасность и RBAC

Metrics Server требует определенных разрешений для работы. Вот минимальные RBAC-права:

**ClusterRole:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: system:metrics-server
rules:
- apiGroups:
  - ""
  resources:
  - nodes/metrics
  verbs:
  - get
- apiGroups:
  - ""
  resources:
  - nodes/stats
  verbs:
  - get
- apiGroups:
  - ""
  resources:
  - nodes/proxy
  verbs:
  - get
- apiGroups:
  - ""
  resources:
  - nodes/log
  verbs:
  - get
```

**ClusterRoleBinding:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: system:metrics-server
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:metrics-server
subjects:
- kind: ServiceAccount
  name: metrics-server
  namespace: kube-system
```

**NetworkPolicy (рекомендуется):**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: metrics-server-network-policy
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      k8s-app: metrics-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: kube-system
    ports:
    - protocol: TCP
      port: 4443
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 10250
```

### Требования к сети

**Порты Metrics Server:**

| Порт | Протокол | Назначение | Направление |
|:---|:---|:---|:---|
| 4443 | TCP | API метрик | Ingress (от kube-apiserver) |
| 8443 | TCP | Webhook (если включен) | Ingress |

**Требования к сетевой связности:**
- kube-apiserver → Metrics Server: порт 4443
- Metrics Server → kubelet на всех узлах: порт 10250
- DNS: Metrics Server должен разрешать имена всех узлов кластера

**Рекомендации по полосе пропускания:**
- Metrics Server → kubelet: 10–100 Kbps на узел (зависит от количества подов)
- kube-apiserver → Metrics Server: 100–500 Kbps (зависит от количества HPA)
- Рекомендуется выделить отдельный VLAN для управления

## Практические сценарии

### 1. Установка и настройка (Helm)

Рекомендуется использовать Helm-чарт, так как он позволяет легко настроить параметры высокой доступности и разрешения метрик.

**Предварительные требования:**
- Kubernetes кластер версии 1.20+
- Helm 3.x установлен
- Доступ к кластеру через kubectl
- Доступ к порту 4443 для API метрик

**Шаг 1: Подготовка репозитория**
```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
# → "metrics-server" has been added to your repositories
helm repo update
# → ...Successfully got an update from the "metrics-server" chart repository
```

**Шаг 2: Создание конфигурации (values.yaml)**
```yaml
# values.yaml для Production
replicas: 2

apiService:
  create: true

args:
  # Частота опроса kubelet (влияет на скорость HPA)
  - --metric-resolution=15s
  # Приоритет IP-адресов узлов (важно для стабильности)
  - --kubelet-preferred-address-types=InternalIP
  # Включение метрик через Kubelet Summary API
  - --kubelet-use-node-status-port
  # Размер окна для агрегации метрик
  - --metric-window=1m
  # - --kubelet-insecure-tls # Раскомментируйте ТОЛЬКО для Dev/Minikube!

resources:
  requests:
    cpu: 100m
    memory: 200Mi
  limits:
    memory: 500Mi  # Защита узла от утечек

# Настройка Pod Disruption Budget
podDisruptionBudget:
  enabled: true
  minAvailable: 1

# Настройка Anti-Affinity
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: k8s-app
          operator: In
          values:
          - metrics-server
      topologyKey: kubernetes.io/hostname

# Приоритет пода
priorityClassName: system-cluster-critical

# Настройка tolerations для control plane nodes
tolerations:
- key: node-role.kubernetes.io/control-plane
  effect: NoSchedule
```

**Шаг 3: Установка**
```bash
helm install metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  --create-namespace \
  -f values.yaml
# → NAME: metrics-server
# → STATUS: deployed
```

**Шаг 4: Валидация установки**
```bash
# Проверка статуса подов
kubectl get pods -n kube-system -l k8s-app=metrics-server
# → NAME                              READY   STATUS    RESTARTS   AGE
# → metrics-server-xxxxx-xxxxx        1/1     Running   0          5m

# Проверка регистрации API
kubectl get apiservice v1beta1.metrics.k8s.io
# → NAME                      SERVICE                       AVAILABLE   AGE
# → v1beta1.metrics.k8s.io    kube-system/metrics-server    True        5m

# Проверка метрик узлов
kubectl top nodes
# → NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → control-1   150m         7%     1400Mi          36%
# → worker-1    250m         12%    2048Mi          51%

# Проверка метриков подов
kubectl top pods -A --sort-by=cpu
# → NAME                              CPU(cores)   MEMORY(bytes)
# → kube-system/kube-dns-xxxxx        25m          20Mi
# → kube-system/metrics-server-xxxxx  50m          150Mi
```

### 2. Обновление Metrics Server

**Процедура обновления:**
```bash
# 1. Проверка текущей версии
kubectl get deployment metrics-server -n kube-system -o jsonpath='{.spec.template.spec.containers[0].image}'
# → registry.k8s.io/metrics-server/metrics-server:v0.7.0

# 2. Обновление через Helm
helm repo update
helm upgrade metrics-server metrics-server/metrics-server \
  --namespace kube-system \
  -f values.yaml

# 3. Валидация после обновления
kubectl rollout status deployment metrics-server -n kube-system
# → deployment "metrics-server" successfully rolled out

# 4. Проверка работы HPA после обновления
kubectl get hpa -A
# → NAMESPACE     NAME          REFERENCE                     TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → production    api-hpa       Deployment/api-gateway        45%/70%   2         10        3          1h
```

**Откат при проблемах:**
```bash
# Откат на предыдущую версию
helm rollback metrics-server 1 --namespace kube-system

# Проверка статуса отката
kubectl rollout status deployment metrics-server -n kube-system
```

### 3. Проверка статуса и мониторинг

**Диагностические команды:**

```bash
# 1. Проверка регистрации API (самый важный шаг)
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml
# → status:
# →   conditions:
# →   - type: Available
# →     status: "True"
# →     lastTransitionTime: "2026-09-01T10:00:00Z"

# 2. Просмотр логов Metrics Server
kubectl logs -n kube-system -l k8s-app=metrics-server --tail=100

# 3. Проверка использования ресурсов
kubectl top pods -n kube-system -l k8s-app=metrics-server
# → NAME                              CPU(cores)   MEMORY(bytes)
# → metrics-server-xxxxx-xxxxx        50m          150Mi

# 4. Проверка сетевой доступности
kubectl exec -it -n kube-system deploy/metrics-server -- \
  curl -s https://localhost:4443/metrics --insecure

# 5. Проверка метрик через API
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/nodes" | jq .
```

**Мониторинг Metrics Server через Prometheus:**

```yaml
# ServiceMonitor для Metrics Server
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: metrics-server
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      k8s-app: metrics-server
  namespaceSelector:
    matchNames:
    - kube-system
  endpoints:
  - port: https
    scheme: https
    tlsConfig:
      insecureSkipVerify: true
    path: /metrics
    interval: 30s
```

**Ключевые метрики для мониторинга:**

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `apiserver_request_total{resource="nodes",subresource="metrics"}` | Количество запросов к Metrics API | > 100 req/s |
| `apiserver_request_duration_seconds{resource="nodes",subresource="metrics"}` | Задержка ответов Metrics API | > 1s |
| `container_memory_working_set_bytes{container="metrics-server"}` | Потребление памяти Metrics Server | > 400Mi |
| `container_cpu_usage_seconds_total{container="metrics-server"}` | Потребление CPU Metrics Server | > 100m持续 5 минут |

### 4. Интеграция с HPA

**Пример HPA с Metrics Server:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-gateway-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

**Валидация работы HPA:**
```bash
# Проверка статуса HPA
kubectl get hpa api-gateway-hpa -n production
# → NAME              REFERENCE                     TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → api-gateway-hpa   Deployment/api-gateway        45%/70%   2         10        3          1h

# Детали HPA
kubectl describe hpa api-gateway-hpa -n production
# → Events:
# →   Type    Reason             Age   From                       Message
# →   ----    ------             ----  ----                       -------
# →   Normal  SuccessfulRescale  5m    horizontal-pod-autoscaler  New size: 3; reason: cpu resource utilization (percentage of request) above target

# Мониторинг масштабирования
kubectl get events -n production --field-selector reason=SuccessfulRescale --watch
```

### 5. Решение проблем

#### Ошибка "ScalingActive: False" в HPA

Если `kubectl describe hpa <name>` показывает причину `failed to get CPU utilization`:

**Диагностика:**
```bash
# 1. Проверка наличия resources.requests у подов
kubectl get deployment <name> -o yaml | grep -A 10 resources
# → containers:
# → - name: app
# →   resources:
# →     requests:
# →       cpu: 100m
# →       memory: 128Mi

# 2. Проверка статуса APIService
kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}'
# → True

# 3. Проверка логов Metrics Server
kubectl logs -n kube-system -l k8s-app=metrics-server --tail=50 | grep -i error

# 4. Проверка доступности Metrics API
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/pods?namespace=production"
```

**Решения:**
1. Убедитесь, что `resources.requests` заданы у контейнеров целевого приложения
2. Проверьте статус APIService (`kubectl get apiservice v1beta1.metrics.k8s.io`)
3. Если APIService недоступен, проверьте логи Metrics Server
4. Убедитесь, что Metrics Server имеет доступ к kubelet на всех узлах

#### Metrics Server не запускается (CrashLoopBackOff / TLS errors)

**Диагностика:**
```bash
# 1. Проверка логов
kubectl logs -n kube-system -l k8s-app=metrics-server --previous
# → E0901 10:00:00.000000 1 main.go:xxx] Failed to probe endpoints: x509: cannot validate certificate

# 2. Проверка сертификатов
kubectl get secret -n kube-system metrics-server-certs -o yaml

# 3. Проверка конфигурации
kubectl get configmap -n kube-system metrics-server-config -o yaml
```

**Решения:**
- **Причина**: Kubelet использует самоподписанные сертификаты (типично для `kubeadm`, k3s или локальных сред)
- **Решение 1**: Добавить флаг `--kubelet-insecure-tls` в `args` Helm-чарта (ТОЛЬКО для Dev/Minikube!)
- **Решение 2**: Настроить доверие к CA узлов или использовать валидные сертификаты Kubelet
- **Решение 3**: Использовать `--kubelet-preferred-address-types=InternalIP` для использования внутренних IP

#### Ошибки таймаутов (Timeout) от Aggregator

Если `kubectl top` зависает и падает с Timeout:

**Диагностика:**
```bash
# 1. Проверка сетевой доступности
kubectl exec -it -n kube-system deploy/metrics-server -- \
  curl -s https://worker-1:10250/stats/summary --insecure --connect-timeout 5

# 2. Проверка DNS
kubectl exec -it -n kube-system deploy/metrics-server -- \
  nslookup kubernetes.default.svc.cluster.local

# 3. Проверка прав доступа
kubectl auth can-i get nodes/stats --as=system:serviceaccount:kube-system:metrics-server
# → yes
```

**Решения:**
- Проверьте правила брандмауэра (NetworkPolicy, Security Groups)
- Убедитесь, что kube-apiserver имеет доступ к порту 4443 Metrics Server
- Проверьте DNS-резолвинг имен узлов
- Увеличьте таймауты в конфигурации Metrics Server

#### Metrics Server не видит поды в других namespace

**Диагностика:**
```bash
# 1. Проверка RBAC прав
kubectl auth can-i list pods --as=system:serviceaccount:kube-system:metrics-server -n production
# → yes

# 2. Проверка NetworkPolicy
kubectl get networkpolicy -n kube-system -o yaml | grep -A 20 metrics-server

# 3. Проверка доступа к конкретному поду
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/production/pods" | jq .
```

**Решения:**
- Убедитесь, что Metrics Server имеет ClusterRole с правами на чтение pods
- Проверьте NetworkPolicy, если он блокирует трафик между namespace
- Убедитесь, что поды не используют hostNetwork (требует дополнительной настройки)

### 6. Оптимизация производительности

**Рекомендации по ресурсам для разных размеров кластеров:**

| Размер кластера | CPU Request | CPU Limit | Memory Request | Memory Limit | Replicas |
|:---|:---|:---|:---|:---|:---|
| До 50 узлов | 100m | 300m | 200Mi | 500Mi | 1 |
| 50–200 узлов | 200m | 500m | 400Mi | 1Gi | 2 |
| 200–500 узлов | 500m | 1000m | 1Gi | 2Gi | 2 |
| Более 500 узлов | 1000m | 2000m | 2Gi | 4Gi | 3 |

**Оптимизация частоты сбора:**
```yaml
# values.yaml
args:
  # Уменьшение частоты для экономии ресурсов (по умолчанию 15s)
  - --metric-resolution=30s
  # Увеличение окна агрегации для стабильности
  - --metric-window=2m
```

**Мониторинг производительности Metrics Server:**
```promql
# Потребление CPU Metrics Server
rate(container_cpu_usage_seconds_total{container="metrics-server"}[5m]) * 100

# Потребление памяти Metrics Server
container_memory_working_set_bytes{container="metrics-server"} / 1024 / 1024

# Количество запросов к Metrics API
sum(rate(apiserver_request_total{resource="nodes",subresource="metrics"}[5m])) by (verb)

# Задержка ответов Metrics API
histogram_quantile(0.99, sum(rate(apiserver_request_duration_seconds_bucket{resource="nodes",subresource="metrics"}[5m])) by (le))
```

### 7. Диагностика и устранение неполадок

**Типичные ошибки и их решения:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `No metrics available` | Metrics Server не зарегистрирован | Проверьте `kubectl get apiservice v1beta1.metrics.k8s.io` |
| `HPA shows <unknown>` | Metrics API недоступен | Проверьте логи Metrics Server и RBAC права |
| `kubectl top hangs` | Проблемы с сетью | Проверьте NetworkPolicy и DNS |
| `CrashLoopBackOff` | TLS ошибки | Добавьте `--kubelet-insecure-tls` для Dev |
| `OOMKilled` | Недостаточно памяти | Увеличьте `limits.memory` |
| `High latency` | Перегрузка Metrics Server | Увеличьте ресурсы или количество реплик |

**Диагностические команды:**
```bash
# Полная диагностика Metrics Server
kubectl get pods -n kube-system -l k8s-app=metrics-server -o wide
kubectl describe pods -n kube-system -l k8s-app=metrics-server
kubectl logs -n kube-system -l k8s-app=metrics-server --tail=100
kubectl top pods -n kube-system -l k8s-app=metrics-server

# Проверка API
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml
kubectl get --raw "/apis/metrics.k8s.io/v1beta1" | jq .

# Проверка сетевой доступности
kubectl exec -it -n kube-system deploy/metrics-server -- curl -s https://localhost:4443/metrics --insecure
kubectl exec -it -n kube-system deploy/metrics-server -- nslookup kubernetes.default.svc.cluster.local

# Проверка RBAC
kubectl auth can-i get nodes/stats --as=system:serviceaccount:kube-system:metrics-server
kubectl auth can-i list pods --as=system:serviceaccount:kube-system:metrics-server --all-namespaces
```

## Дополнительная информация

### Сравнение Metrics Server с другими решениями

| Характеристика | Metrics Server | Prometheus Adapter | KEDA | Custom Metrics API |
|:---|:---|:---|:---|:---|
| **Назначение** | HPA по CPU/RAM | HPA по кастомным метрикам | HPA по кастомным метрикам | HPA по кастомным метрикам |
| **Метрики** | CPU, Memory | Произвольные | Произвольные | Произвольные |
| **Источник данных** | cAdvisor/kubelet | Prometheus | Prometheus, Kafka, etc. | Любые |
| **Задержка** | <1 секунды | 5–30 секунд | 5–30 секунд | Зависит от источника |
| **Хранение данных** | In-memory | TSDB (Prometheus) | Зависит от адаптера | Зависит от адаптера |
| **Сложность настройки** | Низкая | Средняя | Высокая | Очень высокая |
| **Рекомендуется для** | Простые HPA | Сложные HPA | Масштабирование на основе очередей | Специфичные требования |

**Когда использовать Metrics Server:**
- HPA масштабируется по CPU или Memory
- Нужна минимальная задержка для принятия решений
- Простая конфигурация без внешних зависимостей

**Когда использовать Prometheus Adapter:**
- HPA масштабируется по кастомным метрикам (RPS, latency, queue length)
- Уже есть Prometheus в кластере
- Нужна долгосрочная аналитика метрик

**Когда использовать KEDA:**
- Масштабирование на основе очередей (Kafka, RabbitMQ, SQS)
- Масштабирование по расписанию (cron-based)
- Нужны продвинутые триггеры масштабирования

### Интеграция с kube-state-metrics

**kube-state-metrics (KSM)** — компонент, который генерирует метрики состояния объектов Kubernetes (Deployments, Pods, Nodes, etc.). Важно понимать разницу:

| Характеристика | Metrics Server | kube-state-metrics |
|:---|:---|:---|
| **Тип метрик** | Usage (потребление ресурсов) | State (состояние объектов) |
| **Примеры** | `container_cpu_usage_seconds_total` | `kube_pod_status_phase` |
| **Назначение** | HPA, VPA, kubectl top | Алерты, дашборды |
| **Источник данных** | cAdvisor/kubelet | Kubernetes API |
| **Частота сбора** | 15 секунд | 30 секунд |

**Важно:** KSM не заменяет Metrics Server и наоборот. Они дополняют друг друга:
- Metrics Server: "Сколько ресурсов потребляет под?" (для HPA)
- KSM: "В каком состоянии находится под?" (для алертов и дашбордов)

### Интеграция с Prometheus Operator

Если в кластере используется Prometheus Operator, Metrics Server может быть мониторингован через ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: metrics-server
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      k8s-app: metrics-server
  namespaceSelector:
    matchNames:
    - kube-system
  endpoints:
  - port: https
    scheme: https
    tlsConfig:
      insecureSkipVerify: true
    path: /metrics
    interval: 30s
    scrapeTimeout: 10s
```

### Резервное копирование и восстановление

Metrics Server не хранит постоянных данных, поэтому отдельный бэкап не требуется. Однако важно сохранять конфигурацию:

**Бэкап конфигурации:**
```bash
# Экспорт Helm-значений
helm get values metrics-server -n kube-system -o yaml > metrics-server-values-backup.yaml

# Бэкап Deployment
kubectl get deployment metrics-server -n kube-system -o yaml > metrics-server-deployment-backup.yaml

# Бэкап RBAC
kubectl get clusterrole system:metrics-server -o yaml > metrics-server-rbac-backup.yaml
kubectl get clusterrolebinding system:metrics-server -o yaml > metrics-server-rbac-binding-backup.yaml
```

**Восстановление после сбоя:**
1. Восстановите конфигурацию: `kubectl apply -f metrics-server-deployment-backup.yaml`
2. Восстановите RBAC: `kubectl apply -f metrics-server-rbac-backup.yaml`
3. Перезапустите Metrics Server: `kubectl rollout restart deployment metrics-server -n kube-system`

### Производительность и масштабирование

**Пороговые значения для масштабирования:**

| Метрика | Порог | Действие |
|:---|:---|:---|
| CPU Metrics Server | >70%持续 5 минут | Увеличьте ресурсы или добавьте реплики |
| Memory Metrics Server | >80% | Увеличьте limits.memory |
| API latency | >1s | Оптимизируйте retention или отключите метрики |
| Количество узлов | >500 | Рассмотрите федеративный подход |

**Рекомендации по масштабированию:**
- До 50 узлов: 1 Metrics Server (100m CPU, 200Mi RAM)
- 50–200 узлов: 2 Metrics Server (200m CPU, 400Mi RAM каждый)
- 200–500 узлов: 2 Metrics Server (500m CPU, 1Gi RAM каждый)
- Более 500 узлов: федеративный подход с отдельными Metrics Server на кластер

### Интерфейсы управления

**CLI-команды для Metrics Server:**
```bash
# Проверка статуса Metrics Server
kubectl get pods -n kube-system -l k8s-app=metrics-server

# Просмотр логов Metrics Server
kubectl logs -n kube-system -l k8s-app=metrics-server --tail=100

# Проверка использования ресурсов
kubectl top pods -n kube-system -l k8s-app=metrics-server

# Проверка API
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml

# Проверка метрик узлов
kubectl top nodes

# Проверка метриков подов
kubectl top pods -A --sort-by=cpu
```

**API-эндпоинты:**
```bash
# Метрики узлов
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/nodes" | jq .

# Метрики подов в namespace
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/production/pods" | jq .

# Метрики конкретного пода
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/production/pods/api-gateway-xxxxx" | jq .

# Метрики контейнера в поде
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/production/pods/api-gateway-xxxxx/containers/api-gateway" | jq .
```

### Устранение неполадок

**Диагностические команды:**
```bash
# Проверка состояния Metrics Server
kubectl get pods -n kube-system -l k8s-app=metrics-server
kubectl describe pods -n kube-system -l k8s-app=metrics-server
kubectl logs -n kube-system -l k8s-app=metrics-server --tail=100

# Проверка использования ресурсов
kubectl top pods -n kube-system -l k8s-app=metrics-server
kubectl top nodes

# Проверка API
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml
kubectl get --raw "/apis/metrics.k8s.io/v1beta1" | jq .

# Проверка сетевой доступности
kubectl exec -it -n kube-system deploy/metrics-server -- curl -s https://localhost:4443/metrics --insecure
kubectl exec -it -n kube-system deploy/metrics-server -- nslookup kubernetes.default.svc.cluster.local

# Проверка RBAC
kubectl auth can-i get nodes/stats --as=system:serviceaccount:kube-system:metrics-server
kubectl auth can-i list pods --as=system:serviceaccount:kube-system:metrics-server --all-namespaces
```

**Частые проблемы и решения:**

| Симптом | Вероятная причина | Решение |
|:---|:---|:---|
| Metrics Server не запускается | Недостаточно ресурсов | Увеличьте limits в values.yaml |
| kubectl top не работает | APIService не зарегистрирован | Проверьте `kubectl get apiservice v1beta1.metrics.k8s.io` |
| HPA показывает <unknown> | Metrics API недоступен | Проверьте логи Metrics Server и RBAC права |
| Высокое потребление CPU | Слишком много узлов | Увеличьте ресурсы или количество реплик |
| Таймауты в kubectl top | Проблемы с сетью | Проверьте NetworkPolicy и DNS |
| OOMKilled | Недостаточно памяти | Увеличьте limits.memory |

### Смежные темы

- **[HPA: Автомасштабирование подов](../Autoscaling/HPA/index.md)** — глубокое погружение в горизонтальное масштабирование
- **[Monitoring Architecture](./kubernetes-monitoring-logging-architecture.md)** — обзор архитектуры мониторинга и интеграция с Prometheus
- **[Troubleshooting HPA](../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — детальный разбор ошибок `ScalingActive`
