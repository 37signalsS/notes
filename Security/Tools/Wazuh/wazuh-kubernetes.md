# Развертывание Wazuh на Kubernetes

## Определения

**Wazuh Kubernetes** — официальный репозиторий (`wazuh/wazuh-kubernetes`) с манифестами и Helm-чартами для развертывания полного стека Wazuh (Manager, Indexer, Dashboard) на Kubernetes. Поддерживает production-конфигурации с HA, persistent storage и network policies.

**Wazuh Agent (DaemonSet)** — способ развёртывания Wazuh-агентов на всех нодах Kubernetes через DaemonSet. Агент мониторит контейнеры,收集 логи подов и инвентаризирует ноды.

**Helm Chart** — пакет конфигурации для Kubernetes, содержащий шаблоны манифестов (Deployment, Service, ConfigMap, Secret, PVC). Wazuh предоставляет официальные чарты для Manager, Indexer и Dashboard.

**PersistentVolume (PV)** — хранилище данных, переживающее рестарт подов. Критично для Wazuh Indexer (OpenSearch) и данных менеджера.

**Wazuh Operator** — контроллер Kubernetes, управляющий жизненным циклом Wazuh-компонентов (auto-upgrade, scaling, backup).

## Основные концепции

### Архитектура Wazuh в Kubernetes

```
┌─────────────────────────────────────────────────┐
│                   Kubernetes Cluster             │
│                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────┐│
│  │ Wazuh Manager│  │ Wazuh Indexer│  │Dashboard ││
│  │ (Deployment) │  │ (StatefulSet)│  │(Deploy)  ││
│  │  replicas: 2 │  │  replicas: 3 │  │replicas:2││
│  └──────┬───────┘  └──────┬───────┘  └────┬─────┘│
│         │                  │                │      │
│  ┌──────┴──────────────────┴────────────────┴───┐ │
│  │              Services (ClusterIP/NodePort)    │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────────────────────────────────────┐ │
│  │  Wazuh Agent (DaemonSet) - на каждой ноде   │ │
│  │  Мониторинг контейнеров, логи подов          │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────────────────────────────────────┐ │
│  │  PersistentVolumeClaims (Indexer data)       │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### Требования

| Компонент | Минимум | Рекомендуется |
|:---|:---|:---|
| **Ноды** | 3 (для кворума Indexer) | 5+ |
| **RAM на ноду** | 8 GB | 16–32 GB |
| **CPU на ноду** | 4 cores | 8+ cores |
| **Disk** | 100 GB SSD | 500 GB+ NVMe |
| **K8s version** | 1.24+ | 1.28+ |
| **StorageClass** | SSD (gp3, premium) | NVMe |

### Сетевые порты

| Сервис | Порт | Тип | Назначение |
|:---|:---|:---|:---|
| Manager | 1514 | ClusterIP | Агенты → Manager |
| Manager | 1515 | ClusterIP | Регистрация агентов |
| Manager | 55000 | ClusterIP | REST API |
| Indexer | 9200 | ClusterIP | API и кластер |
| Dashboard | 443 | NodePort/Ingress | Веб-интерфейс |

## Практические сценарии

### 1. Установка через Helm

```bash
# Добавление репозитория
helm repo add wazuh https://charts.wazuh.com
helm repo update

# Клонирование репозитория для customized-установки
git clone https://github.com/wazuh/wazuh-kubernetes.git
cd wazuh-kubernetes
```

### 2. Минимальный values.yaml для All-in-one

```yaml
# wazuh-values.yaml
wazuh:
  enabled: true

  manager:
    replicaCount: 1
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
      limits:
        cpu: "4"
        memory: "8Gi"
    persistence:
      enabled: true
      storageClass: "gp3"
      size: "20Gi"

  indexer:
    replicaCount: 3
    resources:
      requests:
        cpu: "2"
        memory: "8Gi"
      limits:
        cpu: "4"
        memory: "16Gi"
    persistence:
      enabled: true
      storageClass: "gp3"
      size: "100Gi"

  dashboard:
    replicaCount: 1
    resources:
      requests:
        cpu: "1"
        memory: "2Gi"
      limits:
        cpu: "2"
        memory: "4Gi"

  agent:
    enabled: true
    daemonset:
      resources:
        requests:
          cpu: "100m"
          memory: "256Mi"
        limits:
          cpu: "500m"
          memory: "512Mi"
```

### 3. Установка

```bash
# All-in-one
helm install wazuh wazuh/wazuh -f wazuh-values.yaml -n wazuh --create-namespace

# Проверка
kubectl get pods -n wazuh
kubectl get svc -n wazuh
```

### 4. Wazuh Agent как DaemonSet

```yaml
# wazuh-agent-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: wazuh-agent
  namespace: wazuh
spec:
  selector:
    matchLabels:
      app: wazuh-agent
  template:
    metadata:
      labels:
        app: wazuh-agent
    spec:
      containers:
        - name: wazuh-agent
          image: wazuh/wazuh-agent:5.0
          env:
            - name: WAZUH_MANAGER
              value: "wazuh-manager.wazuh.svc.cluster.local"
            - name: WAZUH_MANAGER_PORT
              value: "1515"
          securityContext:
            privileged: false
            capabilities:
              add:
                - SYS_PTRACE
                - DAC_READ_SEARCH
          volumeMounts:
            - name: var-run
              mountPath: /var/run
              readOnly: true
            - name: proc
              mountPath: /host/proc
              readOnly: true
              mountPropagation: HostToContainer
            - name: sys
              mountPath: /host/sys
              readOnly: true
            - name: docker-sock
              mountPath: /var/run/docker.sock
              readOnly: true
      volumes:
        - name: var-run
          hostPath:
            path: /var/run
        - name: proc
          hostPath:
            path: /proc
        - name: sys
          hostPath:
            path: /sys
        - name: docker-sock
          hostPath:
            path: /var/run/docker.sock
```

### 5. Ingress для Dashboard

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: wazuh-dashboard
  namespace: wazuh
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - wazuh.example.com
      secretName: wazuh-dashboard-tls
  rules:
    - host: wazuh.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: wazuh-dashboard
                port:
                  number: 443
```

### 6. Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: wazuh-manager-policy
  namespace: wazuh
spec:
  podSelector:
    matchLabels:
      app: wazuh-manager
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: wazuh
      ports:
        - port: 1514
          protocol: TCP
        - port: 1515
          protocol: TCP
        - port: 55000
          protocol: TCP
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: wazuh
      ports:
        - port: 9200
          protocol: TCP
```

### 7. Масштабирование Indexer

```bash
# Вертикальное
kubectl patch statefulset wazuh-indexer -n wazuh -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"wazuh-indexer","resources":{"limits":{"memory":"32Gi","cpu":"8"}}}]}}}}'

# Горизонтальное (добавление узлов)
kubectl scale statefulset wazuh-indexer -n wazuh --replicas=5
```

### 8. Backup через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: wazuh-backup
  namespace: wazuh
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: wazuh/wazuh-manager:5.0
              command:
                - /bin/bash
                - -c
                - |
                  curl -sk -X POST "https://wazuh-manager:55000/security/user/authenticate" \
                    -d '{"username":"admin","password":"'$WAZUH_PASS'"}' | \
                    jq -r '.data.token' > /tmp/token
                  
                  TOKEN=$(cat /tmp/token)
                  curl -sk -X PUT "https://wazuh-indexer:9200/_snapshot/wazuh_backups/snapshot_$(date +%Y%m%d)" \
                    -H "Authorization: Bearer $TOKEN" \
                    -H "Content-Type: application/json" \
                    -d '{"indices":"*","ignore_unavailable":true}'
              env:
                - name: WAZUH_PASS
                  valueFrom:
                    secretKeyRef:
                      name: wazuh-admin-pass
                      key: password
          restartPolicy: OnFailure
```

## Дополнительная информация

### Best Practices

1. **Storage**: используйте SSD/NVMe для Indexer (PersistentVolumeClaim с retentionPolicy: Retain).
2. **HA**: минимум 3 узла Indexer для кворума OpenSearch.
3. **Resources**: всегда задавайте requests и limits для всех подов.
4. **Secrets**: храните пароли в Kubernetes Secrets или HashiCorp Vault.
5. **Monitoring**: мониторьте поды через Prometheus + Grafana.
6. **Updates**: обновляйте через Helm с предварительным тестированием на staging.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Indexer pod CrashLoopBackOff** | Недостаточно памяти или `vm.max_map_count` | Увеличьте limits, установите `sysctl vm.max_map_count=262144` |
| **Agent не подключается** | DNS не резолвит Manager | Проверьте CoreDNS, `nslookup wazuh-manager.wazuh.svc.cluster.local` |
| **Dashboard 503** | Indexer не healthy | Проверьте `kubectl logs wazuh-indexer-0 -n wazuh` |
| **PVC Pending** | Нет StorageClass | Создайте StorageClass или проверьте provisioner |

### См. также
- [Развертывание Wazuh](./deployment.md) — VM-based установка.
- [Container Monitoring](./container_monitoring.md) — мониторинг контейнеров.
- [Docker Deployment](./wazuh-docker-deployment.md) — Docker Compose вариант.
