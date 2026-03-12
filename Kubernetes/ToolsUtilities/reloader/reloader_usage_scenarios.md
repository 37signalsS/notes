# Reloader — Практические сценарии использования

## 1. Веб-сервер с конфигурацией в ConfigMap

### Шаг 1: Создание ConfigMap и Deployment

```yaml
# openresty-app.yaml

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: openresty-index-html
  namespace: default
data:
  index.html: |
    <html>
      <body>
        <h1>Версия 1</h1>
        <p>Последнее обновление: 2025-01-01</p>
      </body>
    </html>

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openresty-deployment
  namespace: default
  annotations:
    # Reloader будет следить за этим ConfigMap
    configmap.reloader.stakater.com/reload: "openresty-index-html"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: openresty
  template:
    metadata:
      labels:
        app: openresty
    spec:
      containers:
        - name: openresty
          image: openresty/openresty:latest
          ports:
            - containerPort: 80
          volumeMounts:
            - name: index-volume
              mountPath: /usr/local/openresty/nginx/html/index.html
              subPath: index.html
      volumes:
        - name: index-volume
          configMap:
            name: openresty-index-html
```

### Шаг 2: Обновление ConfigMap

```bash
# Обновляем ConfigMap с новой версией
kubectl apply -f openresty-app-v2.yaml
```

### Шаг 3: Наблюдение за результатом

```bash
# Watch за подами
kubectl get pods -w

# Вывод:
# NAME                                    READY   STATUS        RESTARTS   AGE
# openresty-deployment-5f8b9d6f6f-abcde   1/1     Running       0          2m
# openresty-deployment-5f8b9d6f6f-abcde   1/1     Terminating   0          3m
# openresty-deployment-c79f8f49d-fghij    1/1     Running       0          10s
```

---

## 2. Использование с Secret (TLS-сертификаты)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress
  annotations:
    # Перезапуск при обновлении TLS-секрета
    secret.reloader.stakater.com/reload: "nginx-tls-secret"
spec:
  template:
    spec:
      containers:
        - name: nginx
          image: nginx:latest
          volumeMounts:
            - name: tls
              mountPath: /etc/nginx/ssl
              readOnly: true
      volumes:
        - name: tls
          secret:
            secretName: nginx-tls-secret
```

---

## 3. Автоматическое обнаружение для всех ресурсов

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  annotations:
    # Автоматически следить за ВСЕМИ ConfigMap и Secret
    reloader.stakater.com/auto: "true"
spec:
  template:
    spec:
      containers:
        - name: myapp
          image: myapp:latest
          envFrom:
            - configMapRef:
                name: app-config
            - secretRef:
                name: app-secrets
```

---

## 4. Мониторинг и отладка

### Просмотр логов Reloader

```bash
kubectl logs -f deployment/reloader -n monitoring
```

### Пример вывода логов

```
time="2025-01-15T10:30:45Z" level=info msg="Reloader started"
time="2025-01-15T10:30:46Z" level=info msg="Watching for changes in namespace: default"
time="2025-01-15T10:31:00Z" level=info msg="ConfigMap 'openresty-index-html' updated in namespace 'default'"
time="2025-01-15T10:31:01Z" level=info msg="Triggering rolling upgrade for Deployment 'openresty-deployment'"
```

### Проверка статуса

```bash
kubectl get deployment reloader -n monitoring
kubectl describe deployment reloader -n monitoring
```

---

## 5. Связанные документы

- **[Обзор и концепции](./reloader_overview.md)** — базовые определения
- **[Установка Reloader](./reloader_installation.md)** — установка через Helm и манифесты
- **[Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)** — дополнительные рекомендации
- **[ConfigMap](../../Base/ConfigMap/update_and_rollout.md)** — обновление ConfigMap и rollout
- **[Deployment](../Base/Deployment/index.md)** — rolling update стратегия
