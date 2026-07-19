# Kubernetes Deployment: Манифест и лучшие практики

## 1. Определения

**Deployment** — объект Kubernetes для декларативного управления stateless-приложениями.

Общее описание и концепции см. в основном разделе: **[Kubernetes Deployment](./index.md)**.

## 2. Базовые концепции

### Базовый манифест

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: nginx
spec:
  replicas: 3
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.28.0
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "250m"
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 15
          periodSeconds: 20
```

### Ключевые поля манифеста

| Поле | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `replicas` | Количество реплик | Минимум 2 для высокой доступности |
| `revisionHistoryLimit` | История версий для отката | 3–5 для production |
| `selector.matchLabels` | Селектор для поиска подов | Должен совпадать с `template.metadata.labels` |
| `image` | Образ контейнера | Использовать конкретную версию (не `:latest`) |
| `resources` | Запросы и лимиты ресурсов | Обязательно для всех контейнеров |
| `readinessProbe` | Проверка готовности к трафику | Обязательно. Подробнее: [Probes](../probes.md) |
| `livenessProbe` | Проверка жизнеспособности | Обязательно. Подробнее: [Probes](../probes.md) |

### Поле containerPort

Поле `containerPort` в спецификации контейнера — это **мета-информация**, а не инструкция для открытия порта. Оно служит для документации и не влияет на сетевое поведение пода. Реальное управление трафиком осуществляется через объект [`Service`](../../Networking/Service/service_type_nodeport.md), который направляет трафик на фактический порт приложения через `targetPort`.

## 3. Практические сценарии

### Настройка стратегии обновления

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0  # Недоступных подов не должно быть
      maxSurge: 1        # Один дополнительный под при обновлении
```

**Варианты настройки параметров:**

| Конфигурация | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `maxUnavailable: 0`, `maxSurge: >0` | Сначала создаются новые поды, потом удаляются старые | Критичные приложения, есть запас ресурсов |
| `maxUnavailable: >0`, `maxSurge: 0` | Сначала удаляются старые поды, потом создаются новые | Ограниченные ресурсы, допустимы кратковременные деградации |
| `maxUnavailable: >0`, `maxSurge: >0` | Гибкое управление (по умолчанию) | Стандартный вариант |

### Многоконтейнерный Deployment (Sidecar-паттерн)

Sidecar используется для расширения функциональности основного контейнера (например, проксирование трафика через Envoy или сбор логов через Fluent Bit). Контейнеры в одном поде разделяют сетевое пространство (`localhost`) и тома.

Подробно паттерны описаны в [Sidecar Patterns](../Pod/pod_sidecar_patterns.md).

## 4. Дополнительная информация

### Лучшие практики

- **Образы:** используйте конкретные версии или хэши и `imagePullPolicy: IfNotPresent`.
- **Проверки здоровья:** всегда настраивайте `readinessProbe` и `livenessProbe` для предотвращения направления трафика на неисправные поды.
- **Ресурсы:** установка `requests` и `limits` критична для планировщика (scheduler) и предотвращения OOM (Out Of Memory).
- **Безопасность:** запускайте процессы от непривилегированного пользователя. Подробнее: [Security Context](../../Security/pod_security_context.md).

### См. также

- Основной раздел: [Kubernetes Deployment](./index.md)
- Управление жизненным циклом: [lifecycle_management.md](./lifecycle_management.md)
- Сравнение стратегий: [Сравнение стратегий развертывания](../../../CI-CD/Deployment_Strategies/comparison.md)
