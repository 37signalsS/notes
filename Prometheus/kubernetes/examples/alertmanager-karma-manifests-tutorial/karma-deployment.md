# Karma Deployment

**`karma-deployment.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: karma
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: karma
  template:
    metadata:
      labels:
        app: karma
    spec:
      containers:
        - name: karma
          image: ghcr.io/prymitive/karma:v0.117
          args:
            - "--config.file=/etc/karma/config.yaml"
          ports:
            - name: web
              containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /etc/karma
      volumes:
        - name: config
          configMap:
            name: karma-config
```

## Смотрите также

- [Karma ConfigMap](./karma-config.md) — конфигурация
- [Сервисы](./services.md) — публикация наружу
