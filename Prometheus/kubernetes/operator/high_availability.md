# Высокая доступность Prometheus Operator

## Prometheus HA

### Конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  resources:
    requests:
      memory: 400Mi
      cpu: 200m
    limits:
      memory: 2Gi
      cpu: 1000m
  retention: 15d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

### Важные замечания

* **Минимум 2 реплики** для HA
* **StatefulSet** не перезапускается при падении ноды
* **Используйте external storage** для долгосрочных данных
* **Одинаковая конфигурация** на всех репликах

### Шардирование

Для распределения нагрузки:

```yaml
spec:
  replicas: 2
  shards: 2  # Разделение целей между 2 StatefulSet
```

## Alertmanager HA

### Конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.31.0
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### Важные замечания

* **Минимум 3 реплики** для кворума
* **Кластеризация** через `--cluster.listen-address`
* **Дедупликация алертов** между репликами
* **Gossip-протокол** для синхронизации состояния

### Проверка кластера

```bash
# Проверка статуса кластера Alertmanager
kubectl exec -it alertmanager-main-0 -n monitoring -- /bin/alertmanager --version

# Логи кластеризации
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager | grep cluster
```

## Storage HA

### External Storage

Для долгосрочного хранения используйте external storage:

* **Thanos** — долгосрочное хранение, глобальный query
* **Cortex** — масштабируемое хранилище
* **Mimir** — масштабируемый Prometheus от Grafana Labs

### Thanos Sidecar

```yaml
spec:
  replicas: 2
  thanos:
    version: v0.37.0
    image: quay.io/thanos/thanos:v0.37.0
    resources:
      requests:
        memory: 128Mi
        cpu: 100m
```

## Network Policies

### Ограничение доступа к Prometheus

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
        - podSelector:
            matchLabels:
              app: grafana
      ports:
        - port: 9090
          protocol: TCP
```

## Load Balancing

### Service для Prometheus

```yaml
apiVersion: v1
kind: Service
metadata:
  name: prometheus
  namespace: monitoring
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: prometheus
  ports:
    - name: web
      port: 9090
      targetPort: web
```

### Ingress с TLS

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: prometheus
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: prometheus-auth
spec:
  tls:
    - hosts:
        - prometheus.example.com
      secretName: prometheus-tls
  rules:
    - host: prometheus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: prometheus
                port:
                  number: 9090
```

## Метрики для мониторинга HA

| Метрика | Описание |
| :--- | :--- |
| `prometheus_operator_reconcile_duration_seconds` | Длительность reconciliation |
| `prometheus_operator_reconcile_errors_total` | Ошибки reconciliation |
| `prometheus_operator_spec_replicas` | Количество реплик из spec |
| `alertmanager_cluster_members` | Количество членов кластера |
| `alertmanager_cluster_alive_members` | Количество активных членов |

## Связанные темы

* **[Prometheus CRD](./crd/prometheus.md)** — описание Prometheus
* **[Alertmanager CRD](./crd/alertmanager.md)** — описание Alertmanager
* **[Security](./security.md)** — безопасность
* **[Alertmanager кластеризация](../alertmanager.md#кластеризация)** — базовая настройка
