# Kubernetes Deployment: Манифест и лучшие практики

## Пример манифеста

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
        image: nginx:1.28.0 # Используйте конкретную версию, а не :latest
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

## Лучшие практики

- **Всегда используйте `readinessProbe`:** Без него Kubernetes не знает, готов ли ваш под принимать трафик, что может привести к ошибкам у пользователей во время `Rolling Update`. Подробнее см. [Высокая доступность](../high_availability.md).

- **Используйте иммутабельные теги или digest для образов:** Никогда не используйте тег `:latest` в продакшене. Всегда указывайте конкретную версию (например, `nginx:1.28.0`) или `digest` (`sha256:...`).

- **Настройте `maxSurge` и `maxUnavailable`:**
  - `maxUnavailable: 0` — более безопасный вариант, гарантирующий отсутствие потери мощности, но требующий больше ресурсов (`maxSurge` должен быть > 0).
  - `maxSurge: 0` — экономит ресурсы, но может снизить производительность во время обновления.

- **Настройте авто-масштабирование:** Для динамического управления количеством реплик используйте [Horizontal Pod Autoscaler](../../Autoscaling/overview_concepts.md).

- **Используйте `imagePullPolicy: IfNotPresent`:** Политика `Always` может привести к избыточной нагрузке на registry и проблемам с rate-лимитами, в то время как `IfNotPresent` является более предсказуемой для версионированных образов.

- **Продвинутые стратегии:** Для минимизации рисков при выкатке критичных изменений используйте [расширенные стратегии развертывания](../../Operations/Advanced_Deployment_Strategies.md), такие как Blue/Green и Canary.

## Многоконтейнерные Deployment

В некоторых сценариях требуется запуск нескольких контейнеров в одном поде. Типичные случаи:

| Сценарий | Описание | Пример |
| :--- | :--- | :--- |
| **Sidecar-паттерн** | Вспомогательный контейнер дополняет основное приложение | Nginx для раздачи статики + Go-приложение |
| **Сбор логов** | Агент логирования собирает логи основного приложения | Fluent Bit + приложение |
| **Service Mesh** | Прокси перехватывает сетевой трафик | Envoy (Istio) + сервис |
| **Адаптер** | Преобразование данных для внешних систем | Форматирование метрик для Prometheus |

### Пример: Deployment с Nginx Sidecar

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

## Когда использовать Deployment vs StatefulSet

> Подробнее о различиях и особенностях работы с приложениями, требующими сохранения состояния, читайте в документе [StatefulSet](../statefulset.md).

## Связанные темы

- [ConfigMap](../configmap.md) — внешняя конфигурация
- [Secret](../secrets/secrets_basics.md) — конфиденциальные данные
- [StatefulSet](../statefulset.md) — управление stateful-приложениями
- [Высокая доступность](../high_availability.md) — обеспечение отказоустойчивости
- [Pod](../Pod/pod_overview.md) — базовый объект развертывания
- [ReplicaSet](../replicaset.md) — управление репликами
- [Horizontal Pod Autoscaler](../../Autoscaling/overview_concepts.md) — автоматическое масштабирование
- [Расширенные стратегии развертывания](../../Operations/Advanced_Deployment_Strategies.md) — Blue/Green, Canary
