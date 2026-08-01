# Karma Deployment: Развёртывание дашборда

## Определения

**Karma Deployment** — ресурс Kubernetes для запуска визуального интерфейса алертов. Является полностью stateless-приложением (не требует PVC), которое агрегирует данные из одного или нескольких API Alertmanager и предоставляет удобный UI для фильтрации и управления оповещениями.

> **См. также:** [Дашборд Karma — архитектура и возможности](../../karma_dashboard.md).

---

## Основные концепции

### Характеристики пода Karma

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Образ** | `ghcr.io/prymitive/karma:v0.120` | Актуальная версия с поддержкой современных API. |
| **Порт** | `8080` | Стандартный TCP порт для веб-интерфейса. |
| **Ресурсы** | Минимальные | Приложение написано на Go, потребляет мало CPU/RAM. |
| **Хранилище** | Не требуется | Все настройки UI сохраняются локально в браузере. |

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
          image: ghcr.io/prymitive/karma:v0.120
          args:
            - "--config.file=/etc/karma/config.yaml"
          ports:
            - name: web
              containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /etc/karma
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: karma-config
```

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./karma-config.md)** — настройки подключения к Alertmanager.
- **[Сервисы и Ingress](./services.md)** — публикация интерфейса наружу кластера.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
