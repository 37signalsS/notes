# GitOps для EFK в Kubernetes

## Определения

**GitOps** — методология управления инфраструктурой и приложениями, где Git репозиторий является единственным источником правды (Single Source of Truth). Все изменения инфраструктуры совершаются через pull requests, а автоматические процессы синхронизируют состояние кластера с Git.

**ArgoCD** — континуативная доставка (CD) для Kubernetes, реализующая принципы GitOps. Автоматически синхронизирует желаемое состояние из Git с текущим состоянием кластера.

**Application** — CRD в Argo CD, описывающий приложение: источник (Git/Helm), destination (кластер/namespace), sync policy.

**AppProject** — CRD в ArgoCD для группировки приложений с общими ограничениями (источники, назначения, кластеры).

**Source** — источник конфигурации в GitOps: Git репозиторий, Helm registry, S3 bucket.

**Sync** — процесс синхронизации желаемого состояния (из Git) с текущим состоянием (в кластере).

**Drift** — расхождение между желаемым состоянием (Git) и текущим состоянием (кластер).

## Теоретический блок

### Архитектура GitOps для EFK

```
┌─────────────────────────────────────────────────────────────┐
│                   GitOps для EFK                             │
├─────────────────────────────────────────────────────────────┤
│  Git Repository (SSoT)                                      │
│  └─ kubernetes/efk/                                         │
│     ├─ base/                                                │
│     │  ├─ elasticsearch/                                    │
│     │  ├─ fluent-bit/                                       │
│     │  └─ kibana/                                           │
│     └─ overlays/                                            │
│        ├─ dev/                                              │
│        ├─ staging/                                          │
│        └─ production/                                       │
│              │                                              │
│              ▼                                              │
│  Argo CD                                                      │
│  └─ Автоматическая синхронизация                            │
│       │                                                     │
│       ▼                                                     │
│  Kubernetes Cluster                                         │
│  └─ Namespace: logging                                      │
│     ├─ Elasticsearch StatefulSet                            │
│     ├─ Fluent Bit DaemonSet                                 │
│     └─ Kibana Deployment                                   │
└─────────────────────────────────────────────────────────────┘
```

### Преимущества GitOps для EFK

1. **Версионность**: каждое изменение версионируется в Git.
2. **Воспроизводимость**: легко развернуть идентичную среду.
3. **Аудит**: все изменения отслеживаются через Git history.
4. **Откат**: быстрый откат к предыдущей версии через Git revert.
5. **Автоматизация**: автоматическая синхронизация и доставка.
6. **Безопасность**: pull request workflow для изменений.

### Структура репозитория

```
kubernetes/efk/
├─ base/
│  ├─ kustomization.yaml
│  ├─ namespace.yaml
│  ├─ elasticsearch/
│  │  ├─ kustomization.yaml
│  │  ├─ statefulset.yaml
│  │  ├─ service.yaml
│  │  ├─ configmap.yaml
│  │  └─ pdb.yaml
│  ├─ fluent-bit/
│  │  ├─ kustomization.yaml
│  │  ├─ daemonset.yaml
│  │  ├─ service.yaml
│  │  ├─ configmap.yaml
│  │  └─ rbac.yaml
│  └─ kibana/
│     ├─ kustomization.yaml
│     ├─ deployment.yaml
│     ├─ service.yaml
│     └─ pdb.yaml
└─ overlays/
   ├─ dev/
   │  ├─ kustomization.yaml
   │  └─ patches/
   ├─ staging/
   │  ├─ kustomization.yaml
   │  └─ patches/
   └─ production/
      ├─ kustomization.yaml
      └─ patches/
```

## Практический блок

### 1. Структура базовой конфигурации (Kustomize)

```yaml
# base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- namespace.yaml
- elasticsearch
- fluent-bit
- kibana

commonLabels:
  app.kubernetes.io/part-of: efk-stack
  app.kubernetes.io/managed-by: kustomize
```

```yaml
# base/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: logging
  labels:
    name: logging
```

### 2. Elasticsearch Kustomize конфигурация

```yaml
# base/elasticsearch/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- statefulset.yaml
- service.yaml
- service-headless.yaml
- configmap.yaml
- pdb.yaml
- rbac.yaml

commonLabels:
  app: elasticsearch
  app.kubernetes.io/component: elasticsearch
```

```yaml
# base/elasticsearch/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
spec:
  serviceName: elasticsearch
  replicas: 3
  selector:
    matchLabels:
      app: elasticsearch
  template:
    metadata:
      labels:
        app: elasticsearch
    spec:
      serviceAccountName: elasticsearch
      containers:
      - name: elasticsearch
        image: docker.elastic.co/elasticsearch/elasticsearch:8.19.0
        ports:
        - containerPort: 9200
        - containerPort: 9300
        env:
        - name: cluster.name
          value: "elasticsearch-cluster"
        - name: node.name
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: discovery.seed_hosts
          value: "elasticsearch-0.elasticsearch,elasticsearch-1.elasticsearch,elasticsearch-2.elasticsearch"
        - name: cluster.initial_master_nodes
          value: "elasticsearch-0,elasticsearch-1,elasticsearch-2"
        - name: ES_JAVA_OPTS
          value: "-Xms4g -Xmx4g"
        resources:
          requests:
            cpu: "2"
            memory: "8Gi"
          limits:
            cpu: "4"
            memory: "16Gi"
        readinessProbe:
          httpGet:
            path: /_cluster/health?local=true
            port: 9200
          initialDelaySeconds: 30
          periodSeconds: 10
        volumeMounts:
        - name: data
          mountPath: /usr/share/elasticsearch/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### 3. Overlays для разных сред

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../base

patches:
- path: patches/elasticsearch-replicas.yaml
- path: patches/elasticsearch-resources.yaml
- path: patches/fluent-bit-resources.yaml
- path: patches/kibana-replicas.yaml

commonLabels:
  environment: production
```

```yaml
# overlays/production/patches/elasticsearch-replicas.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
spec:
  replicas: 5
```

```yaml
# overlays/production/patches/elasticsearch-resources.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
spec:
  template:
    spec:
      containers:
      - name: elasticsearch
        resources:
          requests:
            cpu: "4"
            memory: "16Gi"
          limits:
            cpu: "8"
            memory: "32Gi"
```

### 4. ArgoCD Application

```yaml
# argocd/efk-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: efk-stack
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  
  source:
    repoURL: https://github.com/your-org/kubernetes.git
    targetRevision: HEAD
    path: kubernetes/efk/overlays/production
  
  destination:
    server: https://kubernetes.default.svc
    namespace: logging
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
    - CreateNamespace=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  
  ignoreDifferences:
  - group: apps
    kind: StatefulSet
    jsonPointers:
    - /spec/replicas
```

### 5. ArgoCD AppProject

```yaml
# argocd/efk-project.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: efk
  namespace: argocd
spec:
  description: "EFK Stack (Elasticsearch, Fluent Bit, Kibana)"
  
  sourceRepos:
  - 'https://github.com/your-org/kubernetes.git'
  
  destinations:
  - namespace: logging
    server: https://kubernetes.default.svc
  - namespace: monitoring
    server: https://kubernetes.default.svc
  
  clusterResourceWhitelist:
  - group: ''
    kind: Namespace
  
  namespaceResourceWhitelist:
  - group: ''
    kind: '*'
  - group: apps
    kind: '*'
  - group: batch
    kind: '*'
  - group: networking.k8s.io
    kind: '*'
  - group: policy
    kind: '*'
  - group: monitoring.coreos.com
    kind: '*'
  
  orphanedResources:
    warn: true
```

### 7. Автоматический скрытый деплой (Helm + Argo CD)

```yaml
# argocd/efk-helm-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: efk-helm
  namespace: argocd
spec:
  project: default
  
  source:
    repoURL: https://helm.elastic.co
    chart: elasticsearch
    targetRevision: 8.19.0
    helm:
      releaseName: elasticsearch
      valuesObject:
        replicas: 3
        minimumMasterNodes: 2
        esJavaOpts: "-Xmx4g -Xms4g"
        resources:
          requests:
            cpu: "2"
            memory: "8Gi"
          limits:
            cpu: "4"
            memory: "16Gi"
        volumeClaimTemplate:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi
  
  destination:
    server: https://kubernetes.default.svc
    namespace: logging
  
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 8. Мониторинг GitOps

```yaml
# monitoring/gitops-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gitops-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
  - name: gitops
    rules:
    # Алерт на drift
    - alert: ArgoCDApplicationDrift
      expr: argocd_app_info{sync_status="OutOfSync"} == 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "ArgoCD: обнаружен drift"
        description: "Приложение {{ $labels.name }} находится в состоянии OutOfSync"
    
    # Алерт на неудачную синхронизацию
    - alert: ArgoCDApplicationSyncFailed
      expr: argocd_app_sync_total{phase="Error"} > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "ArgoCD: ошибка синхронизации"
        description: "Приложение {{ $labels.name }} не синхронизируется"
    
    # Алерт на health
    - alert: ArgoCDApplicationDegraded
      expr: argocd_app_info{health_status="Degraded"} == 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "ArgoCD: приложение degraded"
        description: "Приложение {{ $labels.name }} в состоянии Degraded"
```

## Дополнительная информация

### Проверка GitOps

```bash
# Проверка ArgoCD приложений
kubectl get applications -n argocd

# Проверка статуса синхронизации
argocd app list
argocd app get efk-stack

# Просмотр логов ArgoCD
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server
```

### Частые проблемы

1. **Drift detected**: Проверьте, кто изменил ресурсы в кластере.
2. **Sync failed**: Проверьте логи ArgoCD и исправьте конфигурацию.
3. **Health degraded**: Проверьте состояние подов и их готовность.
4. **Permission denied**: Убедитесь, что ServiceAccount имеет достаточные права.

### Рекомендации

1. Используйте Kustomize или Helm для управления конфигурацией.
2. Разделяйте конфигурацию по средам (dev/staging/production).
3. Используйте automated sync с selfHeal для автоматического исправления drift.
4. Настройте алерты на sync status и health status.
5. Регулярно проверяйте и обновляйте зависимости.
6. Используйте AppProjects для группировки приложений и ограничений.

### Полезные ссылки

- [Argo CD Documentation](https://argo-cd.readthedocs.io/)
- [Kustomize Documentation](https://kubectl.docs.kubernetes.io/)
- [GitOps Best Practices](https://opengitops.dev/)
- [Elastic Cloud on Kubernetes](https://www.elastic.co/guide/en/cloud-on-k8s/current/index.html)