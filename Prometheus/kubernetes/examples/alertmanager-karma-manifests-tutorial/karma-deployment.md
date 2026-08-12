# Karma Deployment: Развёртывание дашборда

## Определения

**Karma Deployment** — ресурс Kubernetes для запуска визуального интерфейса алертов. Является полностью stateless-приложением (не требует PVC), которое агрегирует данные из одного или нескольких API Alertmanager и предоставляет удобный UI для фильтрации и управления оповещениями.

> **См. также:** [Дашборд Karma — архитектура и возможности](../../../karma_dashboard.md).

---

## Основные концепции

### Характеристики пода Karma

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Образ** | `ghcr.io/prymitive/karma:v0.131` | Стабильная версия (2026) с поддержкой Vite и React 19. |
| **Порт** | `8080` | Стандартный TCP порт для веб-интерфейса. |
| **Пробы** | HTTP GET `/health` | Механизмы проверки готовности и живучести контейнера. |
| **Безопасность** | Non-root | Запуск от не привилегированного пользователя для защиты кластера. |

---

## Практические сценарии

### Манифест Deployment для Karma

**`karma-deployment.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: karma
  namespace: monitoring
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: karma
  template:
    metadata:
      labels:
        app: karma
    spec:
      securityContext:
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      containers:
        - name: karma
          image: ghcr.io/prymitive/karma:v0.131
          args:
            - "--config.file=/etc/karma/config.yaml"
          ports:
            - name: web
              containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 200m
              memory: 256Mi
          livenessProbe:
            httpGet:
              path: /health
              port: web
            initialDelaySeconds: 10
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /health
              port: web
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /etc/karma
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: karma-config
      terminationGracePeriodSeconds: 30
```

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./karma-config.md)** — настройки подключения к Alertmanager и фильтрация.
- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — публикация интерфейса с SSL и Auth.
- **[Дашборд Karma — Безопасность](../../../karma_dashboard.md#безопасность-и-ingress)** — SSoT по защите UI.
