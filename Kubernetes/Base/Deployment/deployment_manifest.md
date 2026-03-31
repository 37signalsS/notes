# Kubernetes Deployment: Манифест и лучшие практики

## 1. Определения

**Deployment** — объект Kubernetes для декларативного управления stateless-приложениями. Этот документ описывает структуру манифеста и рекомендации по его составлению.

Полная информация о полях манифеста — в [Deployment Concepts](./deployment_concepts.md).

## 2. Базовые концепции

### 2.1. Базовый манифест

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

### 2.2. Ключевые поля

| Поле | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `replicas` | Количество реплик | Минимум 2 для HA |
| `revisionHistoryLimit` | История версий для отката | 3-5 для production |
| `selector.matchLabels` | Селектор для поиска подов | Должен совпадать с `template.metadata.labels` |
| `image` | Образ контейнера | Использовать конкретную версию (не `:latest`) |
| `resources` | Запросы и лимиты ресурсов | Обязательно для production |
| `readinessProbe` | Проверка готовности к трафику | Обязательно |
| `livenessProbe` | Проверка жизнеспособности | Обязательно |

## 3. Практические сценарии

### 3.1. Настройка стратегии обновления

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0  # Недоступных подов не должно быть
      maxSurge: 1        # Один дополнительный под при обновлении
```

**Варианты настройки:**

| Конфигурация | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `maxUnavailable: 0`, `maxSurge: >0` | Сначала создаются новые поды, потом удаляются старые | Критичные приложения, есть запас ресурсов |
| `maxUnavailable: >0`, `maxSurge: 0` | Сначала удаляются старые поды, потом создаются новые | Ограниченные ресурсы, допустимы кратковременные деградации |
| `maxUnavailable: >0`, `maxSurge: >0` | Гибкое управление (по умолчанию) | Стандартный вариант |

Подробнее о стратегиях — в [Rolling Update](../../../CI-CD/Deployment_Strategies/rolling_update.md).

### 3.2. Многоконтейнерный Deployment (Sidecar-паттерн)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app-with-nginx
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      volumes:
      - name: static-files
        emptyDir: {}

      containers:
      # Основное приложение
      - name: app
        image: myapp:1.0
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: static-files
          mountPath: /app/static

      # Nginx sidecar для раздачи статики и проксирования
      - name: nginx
        image: nginx:1.27.0
        ports:
        - containerPort: 80
        volumeMounts:
        - name: static-files
          mountPath: /usr/share/nginx/html/static
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "200m"
```

**Ключевые моменты:**

- Оба контейнера работают в одном поде и разделяют volume `static-files`
- Nginx слушает порт `80`, приложение — порт `8080`
- Service должен направлять трафик на порт Nginx (`targetPort: 80`)

> **Подробно:** Паттерны многоконтейнерных подов описаны в [Sidecar Pattern](../Pod/pod_sidecar_pattern.md).

## 4. Дополнительная информация

### 4.1. Лучшие практики

**Образы контейнеров:**

- Используйте конкретные версии образов (`nginx:1.28.0`) или digest (`sha256:...`)
- Никогда не используйте `:latest` в production
- Установите `imagePullPolicy: IfNotPresent` для версионированных образов

**Проверки здоровья:**

- `readinessProbe` — обязательно: без него Kubernetes не знает, готов ли под принимать трафик
- `livenessProbe` — обязательно для автоматического восстановления при сбоях
- Подробнее — в [Probes](../probes.md) и [Высокая доступность](../high_availability.md)

**Ресурсы:**

- Всегда указывайте `requests` и `limits` для CPU и memory
- Используйте [Horizontal Pod Autoscaler](../../Autoscaling/overview_concepts.md) для автомасштабирования

**Безопасность:**

- Запускайте контейнеры от непривилегированного пользователя (`securityContext.runAsNonRoot: true`)
- Избегайте `privileged: true`

### 4.2. Расширенные стратегии развертывания

Для минимизации рисков при выкатке критичных изменений:

- [Blue-Green Deployment](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md)
- [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md)
- [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)

### 4.3. Связанные темы

- Концепции Deployment: [deployment_concepts.md](./deployment_concepts.md)
- Управление жизненным циклом: [lifecycle_management.md](./lifecycle_management.md)
- Конфигурация: [`ConfigMap`](../configmap.md), [`Secret`](../secrets/secrets_basics.md)
- Stateful-приложения: [`StatefulSet`](../statefulset.md)
- Отказоустойчивость: [`Высокая доступность`](../high_availability.md)
