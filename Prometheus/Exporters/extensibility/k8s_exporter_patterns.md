# Паттерны развертывания экспортеров в Kubernetes

## Определения

**Deployment (Реплики)** — паттерн для централизованных экспортеров, обслуживающих множество целей через внешние API (Blackbox Exporter, SNMP Exporter). Обеспечивает HA через несколько реплик за балансировщиком.

**DaemonSet** — паттерн для экспортеров, которые должны работать на каждом узле кластера (Node Exporter, smartctl_exporter). Один Pod на ноду, автоматически развертывается при добавлении узлов.

**Sidecar** — паттерн для экспортеров, опрашивающих локальную систему внутри того же Pod (postgres_exporter рядом с PostgreSQL, mysqld_exporter рядом с MySQL). Обеспечивает доступ к localhost и shared volume.

**ServiceMonitor** — CRD Prometheus Operator, описывающий как Prometheus должен скрейпить эндпоинты сервиса. Генерирует `scrape_config` автоматически.

**PodMonitor** — CRD Prometheus Operator для скрапинга Pod-ов напрямую, без создания Service. Используется для DaemonSet и Sidecar экспортеров.

**См. также:** [Создание собственных экспортеров](./custom_exporters.md), [ServiceMonitor CRD](../../kubernetes/operator/crd/servicemonitor.md), [PodMonitor CRD](../../kubernetes/operator/crd/podmonitor.md).

## Основные концепции

### Выбор паттерна

| Паттерн | Когда использовать | Примеры | Присвоение Pod-ов |
|:---|:---|:---|:---|
| **Deployment** | Централизованный сбор с внешних систем | Blackbox, SNMP, json_exporter | Один инстанс, несколько реплик |
| **DaemonSet** | Метрики уровня узла | Node Exporter, smartctl, process_exporter | Один Pod на ноду |
| **Sidecar** | Метрики из локальной БД/сервиса | postgres_exporter, mysqld_exporter, redis_exporter | Вместе с целевым Pod-ом |
| **In-process** | Метрики приложения (не экспортер) | Кастомный Go/Python сервис | В основном контейнере |

### Deployment паттерн

Deployment подходит для экспортеров, которые опрашивают внешние системы по сети и не привязаны к конкретной ноде.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blackbox-exporter
  namespace: monitoring
  labels:
    app.kubernetes.io/name: blackbox-exporter
    app.kubernetes.io/component: exporter
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: blackbox-exporter
  template:
    metadata:
      labels:
        app.kubernetes.io/name: blackbox-exporter
    spec:
      containers:
        - name: blackbox-exporter
          image: prom/blackbox-exporter:v0.25.0
          ports:
            - containerPort: 9115
              name: http
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
          livenessProbe:
            httpGet:
              path: /-/healthy
              port: 9115
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /-/ready
              port: 9115
            initialDelaySeconds: 3
            periodSeconds: 5
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: blackbox-exporter
                topologyKey: kubernetes.io/hostname
```

**Service для Deployment:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: blackbox-exporter
  namespace: monitoring
spec:
  selector:
    app.kubernetes.io/name: blackbox-exporter
  ports:
    - port: 9115
      targetPort: http
      protocol: TCP
      name: http
```

### DaemonSet паттерн

DaemonSet гарантирует один Pod на каждую ноду. Используется для сбора метрик уровня узла.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
  labels:
    app.kubernetes.io/name: node-exporter
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter
  template:
    metadata:
      labels:
        app.kubernetes.io/name: node-exporter
    spec:
      hostNetwork: true
      hostPID: true
      hostPID: true
      tolerations:
        - operator: Exists
          effect: NoSchedule
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.8.0
          args:
            - '--path.procfs=/host/proc'
            - '--path.sysfs=/host/sys'
            - '--path.rootfs=/host/root'
            - '--collector.textfile.directory=/var/lib/node_exporter/textfile'
          ports:
            - containerPort: 9100
              hostPort: 9100
              name: http
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 150m
              memory: 128Mi
          livenessProbe:
            httpGet:
              path: /metrics
              port: 9100
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /metrics
              port: 9100
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: proc
              mountPath: /host/proc
              readOnly: true
            - name: sys
              mountPath: /host/sys
              readOnly: true
            - name: root
              mountPath: /host/root
              mountPropagation: HostToContainer
              readOnly: true
            - name: textfile
              mountPath: /var/lib/node_exporter/textfile
              readOnly: true
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
      volumes:
        - name: proc
          hostPath:
            path: /proc
        - name: sys
          hostPath:
            path: /sys
        - name: root
          hostPath:
            path: /
        - name: textfile
          hostPath:
            path: /var/lib/node_exporter/textfile
            type: DirectoryOrCreate
```

**Важно:** Для DaemonSet используйте `PodMonitor` вместо `ServiceMonitor`, так как Pod-ы не обязаны иметь<Service>. См. пример ниже.

### Sidecar паттерн

Sidecar-контейнер с экспортером развертывается в том же Pod-е, что и целевая система. Экспортер обращается к БД через `localhost`.

> **Подробнее:** Полный гайд с ConfigMap для кастомных запросов, Native Sidecar и Passport интеграцией: [Exporter Sidecar в StatefulSet](../../../Kubernetes/Base/StatefulSet/statefulset_exporter_sidecar.md).

**Упрощенный пример (PostgreSQL + postgres-exporter):**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: databases
spec:
  serviceName: postgresql
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
        - name: postgresql
          image: postgres:16
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data

        - name: postgres-exporter
          image: prometheuscommunity/postgres-exporter:v0.15.0
          ports:
            - containerPort: 9187
              name: http
          env:
            - name: DATA_SOURCE_NAME
              value: "exporter:$(POSTGRES_EXPORTER_PASSWORD)@(localhost:5432)/?sslmode=disable"
            - name: POSTGRES_EXPORTER_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: password
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
          livenessProbe:
            httpGet:
              path: /metrics
              port: 9187
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /metrics
              port: 9187
            initialDelaySeconds: 5
            periodSeconds: 10
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: postgresql-data
```

### ServiceMonitor для Deployment

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: blackbox-exporter
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: blackbox-exporter
  endpoints:
    - port: http
      interval: 30s
      scrapeTimeout: 25s
```

### PodMonitor для DaemonSet

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: node-exporter
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter
  podMetricsEndpoints:
    - port: http
      interval: 30s
      scrapeTimeout: 25s
```

### PodMonitor для Sidecar

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: postgres-exporter
  namespace: databases
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: postgresql
  podMetricsEndpoints:
    - port: http
      path: /metrics
      interval: 30s
      scrapeTimeout: 25s
```

### Probes (Liveness / Readiness / Startup)

Правильная настройка probes критична для availability экспортера и предотвращения циклических restart'ов.

| Probe | Что проверяет | Рекомендации | Ошибка приводит к |
|:---|:---|:---|:---|
| **livenessProbe** | Жив ли процесс | `httpGet` на `/metrics` или `/-/healthy` | Kill Pod → restart |
| **readinessProbe** | Готов ли принимать трафик | `httpGet` на `/metrics` | Убрать из Service endpoints |
| **startupProbe** | Запустился ли процесс | `httpGet` на `/metrics` с увеличенным `failureThreshold` | Kill Pod (до готовности liveness) |

**Startup Probe для медленно стартующих экспортеров:**
```yaml
startupProbe:
  httpGet:
    path: /metrics
    port: 9187
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 30  # 5 * 30 = 150 секунд на старт
```

**Важно:** `livenessProbe` не должен зависеть от внешней системы. Если экспортер опрашивает БД, `livenessProbe` должен проверять только эндпоинт `/metrics`, а не доступность БД. Иначе при падении БД все Pod-ы экспортера будут рестартоваться бесконечно.

### Resource Requests и Limits

| Тип экспортера | CPU req | CPU lim | Memory req | Memory lim | Примечание |
|:---|:---|:---|:---|:---|:---|
| **Deployment (легкий)** | 50m | 100m | 64Mi | 128Mi | Blackbox, json_exporter |
| **Deployment (кэширующий)** | 100m | 500m | 128Mi | 512Mi | SNMP, с кэшированием |
| **DaemonSet** | 50m | 150m | 64Mi | 128Mi | Node Exporter |
| **Sidecar (БД)** | 50m | 100m | 64Mi | 128Mi | postgres/mysql_exporter |
| **Sidecar (кэширующий)** | 100m | 250m | 128Mi | 256Mi | Redis exporter |

### Security Context

Все экспортеры должны запускаться с минимальными привилегиями. Базовый шаблон:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 65534          # nobody
  runAsGroup: 65534
  fsGroup: 65534
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
```

**Исключения для экспортеров:**
- Node Exporter: требует `hostPID: true`, `hostNetwork: true` и доступ к `/proc`, `/sys` (read-only)
- SNMP Exporter: может не нуждаться в `runAsNonRoot` при использовании привилегированных портов

> **Подробнее:** Полное руководство по Security Context в Kubernetes: [Pod Security Context](../../../Kubernetes/Security/pod_security_context.md), [CIS Benchmark](../../../Kubernetes/Security/kube-bench.md).

## Практические сценарии

### Сценарий 1: Полный цикл Deployment + ServiceMonitor

1. Развертывание Blackbox Exporter
2. Настройка ServiceMonitor
3. Валидация скрапинга

```bash
# 1. Развертывание
kubectl apply -f blackbox-deployment.yml
kubectl apply -f blackbox-service.yml
kubectl apply -f blackbox-servicemonitor.yml

# 2. Проверка Pod-ов
kubectl get pods -n monitoring -l app.kubernetes.io/name=blackbox-exporter
# → NAME                                  READY   STATUS    RESTARTS   AGE
# → blackbox-exporter-6d4f5b7c9-abc12    1/1     Running   0          30s
# → blackbox-exporter-6d4f5b7c9-def34    1/1     Running   0          30s

# 3. Проверка Service
kubectl get svc -n monitoring blackbox-exporter
# → NAME              TYPE        CLUSTER-IP     PORT(S)   AGE
# → blackbox-exporter ClusterIP   10.96.45.123   9115/TCP  30s

# 4. Проверка targets в Prometheus UI
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="blackbox-http") | .health'
# → "up"

# 5. Валидация метрик
kubectl port-forward -n monitoring svc/blackbox-exporter 9115:9115 &
curl -s http://localhost:9115/metrics | promtool check metrics
```

### Сценарий 2: Обновление DaemonSet с rolling update

```bash
# Обновление образа Node Exporter
kubectl set image daemonset/node-exporter \
  -n monitoring \
  node-exporter=prom/node-exporter:v1.9.0

# Мониторинг rollout
kubectl rollout status daemonset/node-exporter -n monitoring --timeout=5m

# Проверка версии на всех нодах
kubectl get pods -n monitoring -l app.kubernetes.io/name=node-exporter -o wide

# Откат при проблемах
kubectl rollout undo daemonset/node-exporter -n monitoring
```

### Сценарий 3: HPA для Deployment-экспортера

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: blackbox-exporter
  namespace: monitoring
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: blackbox-exporter
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: exporter_scrape_duration_seconds
        target:
          type: AverageValue
          averageValue: "5"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

### Сценарий 4: Topology Spread Constraints для HA

```yaml
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: blackbox-exporter
```

### Сценарий 5: Валидация PodMonitor через Prometheus Operator

```bash
# Проверка, что Operator создал scrape_config
kubectl get servicemonitor -n monitoring blackbox-exporter -o yaml

# Проверка логов Operator на ошибки
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator | grep -i error

# Проверка targets
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.scrapePool | startswith("ServiceMonitor/blackbox")) | {health, lastError}'
```

## Дополнительная информация

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Target showing `Connection Refused` | PodSelector не матчит Pod-ы экспортера | Проверьте labels в ServiceMonitor/PodMonitor и Pod-ах |
| `scrape_timeout_exceeded` | Скрапинг занимает больше `scrapeTimeout` | Увеличьте `scrapeTimeout` или оптимизируйте экспортер |
| Pod CrashLoopBackOff | livenessProbe падает | Проверьте, что `/metrics` доступен; увеличьте `initialDelaySeconds` |
| Target `DOWN` после обновления | Изменились порты или метрики | Проверьте `kubectl describe pod` и логи |
| DaemonSet не развертывается на нодах | Tolerations не совпадают с taints | Добавьте `tolerations: [{operator: Exists, effect: NoSchedule}]` |
| Sidecar не видит localhost БД | Контейнеры в разных Pod-ах | Убедитесь, что sidecar и БД в одном Pod-е |
| Operator не создает scrape_config | ServiceMonitor/PodMonitor в wrong namespace | Разместите CRD в том же namespace, что и Prometheus |

### Сравнение ServiceMonitor vs PodMonitor

| Критерий | ServiceMonitor | PodMonitor |
|:---|:---|:---|
| Требует Service | Да | Нет |
| Используется для | Deployment, StatefulSet | DaemonSet, Sidecar, Pod без Service |
| Selectors | `spec.selector` (labels Service) | `spec.selector` (labels Pod) |
| Автообнаружение | Через Service → Endpoints | Напрямую по labels Pod-ов |
| Multi-port | Через `endpoints[].port` | Через `podMetricsEndpoints[].port` |

### CIS Benchmark для экспортеров

| Параметр | Значение | Обоснование |
|:---|:---|:---|
| `runAsNonRoot: true` | Обязательно | Запрет запуска от root |
| `readOnlyRootFilesystem: true` | Обязательно | Предотвращение записи в файловая система |
| `allowPrivilegeEscalation: false` | Обязательно | Запрет повышения привилегий |
| `capabilities.drop: ["ALL"]` | Обязательно | Сброс всех capability |
| `seccompProfile: RuntimeDefault` | Рекомендуется | Ограничение системных вызовов |
| Network Policy | Рекомендуется | Ограничение сетевого доступа |
| Non-default namespace | Рекомендуется | Изоляция от других компонентов |

**См. также:**
- [Kubernetes — ServiceMonitor CRD](../../kubernetes/operator/crd/servicemonitor.md) — полная спецификация
- [Kubernetes — PodMonitor CRD](../../kubernetes/operator/crd/podmonitor.md) — полная спецификация
- [kube-prometheus-stack — exporters config](../../kubernetes/Kube_Prometheus_Stack_Helm/exporters_config.md) — конфигурация встроенных экспортеров
- [Exporter Sidecar паттерн](../../../Kubernetes/Base/StatefulSet/statefulset_exporter_sidecar.md) — подробный гайд по Sidecar
- [Security](./exporter_security.md) — безопасность экспортеров
- [Reliability](./exporter_reliability.md) — надежность и HA
