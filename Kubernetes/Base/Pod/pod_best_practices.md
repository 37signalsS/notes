# Лучшие практики написания манифестов Pod в Kubernetes

## Определения

**Декларативный манифест** — YAML-файл, описывающий желаемое состояние объекта Kubernetes. Хранится в системе контроля версий, обеспечивает воспроизводимость и отслеживаемость изменений.

**Immutable тег образа** — конкретный, неизменяемый тег версии контейнера (например, `nginx:1.28.0`), в отличие от плавающего тега `:latest`.

---

## Базовые концепции

### Структура манифеста

Любой манифест Pod состоит из четырёх полей верхнего уровня:

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `apiVersion` | Версия Kubernetes API | `v1` для Pod |
| `kind` | Тип объекта | `Pod` |
| `metadata` | Метаданные объекта | `name`, `namespace`, `labels`, `annotations` |
| `spec` | Спецификация желаемого состояния | Контейнеры, тома, сетевые настройки |

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-first-pod
  namespace: work
  labels:
    app: my-app
    version: "1.27.5"
spec:
  # Спецификация пода
```

### Декларативный подход

Всегда используйте декларативные YAML-файлы вместо императивных команд (`kubectl run`).

| Преимущество | Описание |
| :--- | :--- |
| Воспроизводимость | Манифесты хранятся в Git, можно отслеживать изменения и откатываться |
| Наглядность | Сложную конфигурацию проще описать и прочитать в YAML |
| Стабильность | API Kubernetes меняется реже, чем флаги `kubectl` |

### Избегайте тега `:latest`

Никогда не используйте тег `:latest` для контейнеров в production.

| Проблема | Решение |
| :--- | :--- |
| Тег `:latest` плавающий — при обновлении образа в реестре под может скачать несовместимую версию | Всегда указывайте конкретный тег: `nginx:1.28.0` или `my-app:v1.2.3-commit-af85a7` |

```yaml
# ПЛОХО
image: nginx
image: nginx:latest

# ХОРОШО
image: nginx:1.28.0
```

### Requests и Limits

Всегда указывайте `requests` и `limits` по CPU и памяти для каждого контейнера.

| Параметр | Описание |
| :--- | :--- |
| `requests` | Гарантированное количество ресурсов, резервируемое для контейнера. Используется планировщиком для выбора узла |
| `limits` | Максимальное количество ресурсов, которое контейнер может потреблять |

**Последствия отсутствия лимитов:**

1. **Стабильность узла:** Контейнер может занять все ресурсы узла, вызвав сбои других подов и `kubelet`
2. **Предсказуемое планирование:** `requests` позволяют планировщику эффективно распределять поды
3. **QoS классы:** На основе `requests` и `limits` Kubernetes присваивает подам классы QoS ([Guaranteed](../../Scheduling/qos_limit_and_requests.md), [Burstable](../../Scheduling/qos_limit_and_requests.md), [BestEffort](../../Scheduling/qos_limit_and_requests.md)), влияющие на порядок вытеснения при нехватке ресурсов

```yaml
resources:
  requests:
    memory: "64Mi"
    cpu: "250m"
  limits:
    memory: "128Mi"
    cpu: "500m"
```

**При превышении:**

- `limits.memory` — контейнер будет завершен OOM-киллером
- `limits.cpu` — потребление CPU будет ограничено (throttled)

### Probes (Пробы)

Пробы — механизм автоматического контроля состояния приложения.

| Тип пробы | Назначение | Реакция на сбой |
| :--- | :--- | :--- |
| [livenessProbe](../probes.md) | Проверка, "живо" ли приложение | Перезапуск контейнера |
| [readinessProbe](../probes.md) | Проверка готовности принимать трафик | Исключение пода из Service |
| [startupProbe](../probes.md) | Проверка запуска для медленно стартующих приложений | Отключение других проб до успешного завершения |

### Метки (Labels)

Метки — основной способ организации и выборки объектов в Kubernetes.

**Рекомендуемый минимум:**

| Метка | Описание | Пример |
| :--- | :--- | :--- |
| `app` или `app.kubernetes.io/name` | Название приложения | `frontend`, `api-gateway` |
| `version` или `app.kubernetes.io/version` | Версия приложения | `v1.2.3` |

```yaml
metadata:
  labels:
    app: web-server
    version: "1.27.5"
```

### Immutability (Неизменяемость)

Многие поля спецификации пода неизменяемы после создания (например, `image` контейнера нельзя изменить через `kubectl apply`).

**Правильный подход:** Для изменения неизменяемого поля удалите старый под и создайте новый с обновлённым манифестом. На практике этим управляют контроллеры (например, [Deployment](../Deployment/deployment.md)), реализующие стратегии обновления (`RollingUpdate`).

### Security Context

[Security Context](../../Security/pod_security_context.md) ограничивает привилегии контейнера.

```yaml
spec:
  containers:
  - name: my-container
    image: ...
    securityContext:
      allowPrivilegeEscalation: false
      runAsNonRoot: true
      runAsUser: 1001
```

---

## Практические сценарии

### Пример 1: Полный манифест пода с лучшими практиками

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-ready-pod
  namespace: production
  labels:
    app: web-server
    version: "1.28.0"
spec:
  containers:
  - name: nginx
    image: docker.io/library/nginx:1.28.0
    ports:
    - containerPort: 8080
    resources:
      requests:
        memory: "64Mi"
        cpu: "250m"
      limits:
        memory: "128Mi"
        cpu: "500m"
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
    securityContext:
      allowPrivilegeEscalation: false
      runAsNonRoot: true
      runAsUser: 1001
      readOnlyRootFilesystem: true
```

### Пример 2: Манифест для медленно стартующего приложения

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: slow-start-app
  labels:
    app: java-app
    version: "2.0.0"
spec:
  containers:
  - name: app
    image: registry.example.com/java-app:2.0.0
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "1Gi"
        cpu: "1000m"
    startupProbe:
      httpGet:
        path: /health
        port: 8080
      failureThreshold: 30
      periodSeconds: 10
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
```

---

## Дополнительная информация

**Связанные темы:** [Probes](../probes.md), [QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md), [Security Context](../../Security/pod_security_context.md), [Deployment](../Deployment/deployment.md).
