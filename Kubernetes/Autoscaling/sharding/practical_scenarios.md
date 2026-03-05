# Паттерны шардирования: Практические сценарии

## Сценарий 1: Шардирование по региону

```yaml
# Deployment для шарда A (US)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-us
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: us
  template:
    metadata:
      labels:
        app: webapp
        shard: us
    spec:
      containers:
        - name: app
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "us"
            - name: ALLOWED_REGIONS
              value: "us-west,us-east"
---
apiVersion: v1
kind: Service
metadata:
  name: service-us
spec:
  selector:
    app: webapp
    shard: us
  ports:
    - port: 80
      targetPort: 8080
---
# Deployment для шарда B (EU)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp-shard-eu
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
      shard: eu
  template:
    metadata:
      labels:
        app: webapp
        shard: eu
    spec:
      containers:
        - name: app
          image: myapp:latest
          env:
            - name: SHARD_ID
              value: "eu"
            - name: ALLOWED_REGIONS
              value: "eu-west,eu-central"
---
apiVersion: v1
kind: Service
metadata:
  name: service-eu
spec:
  selector:
    app: webapp
    shard: eu
  ports:
    - port: 80
      targetPort: 8080
```

### Маршрутизация на уровне Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shard-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: us.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-us
                port:
                  number: 80
    - host: eu.api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service-eu
                port:
                  number: 80
```

---

## Сценарий 2: Шардирование с независимым масштабированием

```yaml
# HPA для каждого шарда
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-us-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-us
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shard-eu-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webapp-shard-eu
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## Сценарий 3: Priority Queue с несколькими очередями

```yaml
# Workers для критических задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: priority-workers
spec:
  replicas: 5
  selector:
    matchLabels:
      app: priority-workers
      priority: high
  template:
    metadata:
      labels:
        app: priority-workers
        priority: high
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "priority-tasks"
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
---
# Workers для обычных задач
apiVersion: apps/v1
kind: Deployment
metadata:
  name: standard-workers
spec:
  replicas: 3
  selector:
    matchLabels:
      app: standard-workers
      priority: normal
  template:
    metadata:
      labels:
        app: standard-workers
        priority: normal
    spec:
      containers:
        - name: worker
          image: task-processor:latest
          env:
            - name: QUEUE_NAME
              value: "standard-tasks"
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
```

---

## Ссылки

- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
- **[Мониторинг и best practices](./monitoring_and_best_practices.md)** — наблюдение за шардами
