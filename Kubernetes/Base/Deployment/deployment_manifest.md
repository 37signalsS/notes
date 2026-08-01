# Манифест Kubernetes Deployment и лучшие практики

## 1. Определения

**Deployment** — объект Kubernetes для декларативного управления stateless-приложениями. Он обеспечивает автоматическое развертывание, масштабирование и обновление групп идентичных подов.

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
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: nginx
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app: nginx
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 101
        fsGroup: 101
      terminationGracePeriodSeconds: 30
      containers:
      - name: nginx
        image: nginx:1.28.1-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "250m"
        startupProbe:
          httpGet:
            path: /
            port: 80
          failureThreshold: 30
          periodSeconds: 10
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
| `revisionHistoryLimit` | История версий для отката | 3–5 для баланса между откатами и чистотой API |
| `selector.matchLabels` | Селектор для поиска подов | Должен строго совпадать с `template.metadata.labels` |
| `image` | Образ контейнера | Использовать конкретную версию и легкие образы (например, `-alpine`) |
| `resources` | Запросы и лимиты ресурсов | Обязательно для всех контейнеров. `requests` для планировщика, `limits` для стабильности узла |
| `startupProbe` | Проверка начального запуска | Использовать для медленно стартующих приложений, чтобы liveness не убил их раньше времени |
| `readinessProbe` | Проверка готовности к трафику | Обязательно. Исключает неготовую реплику из Service |
| `livenessProbe` | Проверка жизнеспособности | Обязательно. Перезапускает зависший контейнер |
| `securityContext` | Настройки безопасности | Запуск от не-root пользователя, ограничение прав. Подробнее: **[Security Context](../../Security/pod_security_context.md)** |

### Поле containerPort

Поле `containerPort` в спецификации контейнера — это **мета-информация**, а не инструкция для открытия порта. Оно служит для документации и позволяет инструментам (например, Service или Ingress) ссылаться на порт по имени. Реальное управление трафиком осуществляется через объект [`Service`](../../Networking/Service/service_type_nodeport.md).

## 3. Практические сценарии

### Обеспечение высокой доступности (Topology Spread Constraints)

Для равномерного распределения подов по разным зонам доступности (Availability Zones) или узлам в современных кластерах рекомендуется использовать `topologySpreadConstraints` вместо сложной настройки `affinity`.

```yaml
spec:
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: "topology.kubernetes.io/zone"
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: nginx
```

### Настройка стратегии RollingUpdate

Стратегия `RollingUpdate` позволяет обновлять приложение без простоя.

| Конфигурация | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `maxUnavailable: 0`, `maxSurge: 1` | Сначала создается новый под, затем удаляется старый | **Рекомендуется.** Гарантирует наличие 100% мощности во время обновления |
| `maxUnavailable: 1`, `maxSurge: 0` | Сначала удаляется один старый под, затем создается новый | Ограниченные ресурсы в кластере, допустима кратковременная деградация |

### Многоконтейнерный Deployment (Sidecar-паттерн)

Sidecar используется для расширения функциональности основного контейнера (логирование, проксирование, сбор метрик). Начиная с Kubernetes 1.29, sidecar-контейнеры могут быть объявлены как `initContainers` с `restartPolicy: Always`.

Подробно паттерны описаны в [Sidecar Patterns](../Pod/pod_sidecar_patterns.md).

## 4. Дополнительная информация

### Лучшие практики

1.  **Immutability (Неизменяемость):** Никогда не используйте тег `:latest`. Всегда указывайте конкретную версию образа.
2.  **Graceful Termination:** Настраивайте `terminationGracePeriodSeconds` (по умолчанию 30с) в зависимости от того, как быстро ваше приложение может завершить текущие запросы.
3.  **Probes:** Настраивайте триаду проверок (`startup`, `readiness`, `liveness`) с разумными таймаутами.
4.  **Безопасность:** Минимизируйте привилегии контейнера через `securityContext`. Используйте `readOnlyRootFilesystem: true`, если приложение не пишет на диск.
5.  **Affinity vs Spreading:** Предпочитайте `topologySpreadConstraints` для обеспечения отказоустойчивости на уровне дата-центров.

### См. также

- [Управление жизненным циклом (Rollout/Rollback)](./lifecycle_management.md)
- [Проверки состояния (Probes)](../probes.md)
- [Стратегии развертывания](../../../CI-CD/Deployment_Strategies/comparison.md)
