# Reloader

## 1. Определения

**Reloader** — это контроллер для Kubernetes от Stakater, который отслеживает изменения в `ConfigMap` и `Secret` и автоматически выполняет rolling upgrade для связанных с ними `Deployment`, `StatefulSet` или `DaemonSet`.

**Проблема:** По умолчанию Kubernetes не перезапускает поды при изменении ConfigMap или Secret, что требует ручного вмешательства (`kubectl rollout restart`).

## 2. Основные концепции

### Принцип работы

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  ConfigMap /    │ ──> │    Reloader      │ ──> │  Rolling Upgrade│
│    Secret       │     │   (watch API)    │     │   подов         │
│   (изменение)   │     │                  │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

1. **Отслеживание (Watch):** Reloader следит за событиями обновления ConfigMap и Secret через Kubernetes Watch API
2. **Поиск зависимостей:** При изменении ресурса ищет workload'ы, использующие этот ресурс
3. **Инициирование rollout:** Выполняет `rollout restart` для найденных workload'ов

### Механизм обнаружения зависимостей

Reloader определяет зависимости по:
- **volumeMounts** — монтирование ConfigMap/Secret как тома
- **envFrom** — загрузка переменных окружения из ConfigMap/Secret
- **env.valueFrom** — отдельные переменные из ConfigMap/Secret

### Аннотации для конфигурации

**Автоматическое обнаружение (`auto`):**

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```

В этом режиме Reloader автоматически следит за всеми ConfigMap и Secret, используемыми в поде.

**Явное указание ресурсов:**

```yaml
metadata:
  annotations:
    # Следить за одним ConfigMap
    configmap.reloader.stakater.com/reload: "my-app-config"
    
    # Следить за несколькими ConfigMap (через запятую)
    configmap.reloader.stakater.com/reload: "config-1,config-2"
    
    # Следить за Secret
    secret.reloader.stakater.com/reload: "my-app-tls"
    
    # Следить за несколькими Secret
    secret.reloader.stakater.com/reload: "tls-secret,db-creds"
```

**Префикс для search-by-prefix (опционально):**

```yaml
metadata:
  annotations:
    reloader.stakater.com/search: "true"
```

### Режимы работы

| Режим | Описание |
| :--- | :--- |
| **Default** | Перезапуск подов при изменении ресурсов |
| **Strategy: Rename** | Переименование ресурса для принудительного обновления (enterprise) |
| **Ignore** | Игнорирование определённых namespace'ов или ресурсов |

## 3. Практические сценарии

### 3.1. Установка через Helm

**Добавление репозитория:**

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
```

**Установка Reloader:**

```bash
helm install reloader stakater/reloader \
  --namespace monitoring \
  --create-namespace \
  --set reloader.watchGlobally=true \
  --set reloader.deployment.resources.requests.cpu=100m \
  --set reloader.deployment.resources.requests.memory=128Mi
```

**Основные параметры Helm:**

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `reloader.watchGlobally` | `true` | Следить во всех namespace'ах |
| `reloader.namespace` | `default` | Namespace для установки |
| `reloader.replicas` | `1` | Количество реплик |
| `reloader.resources` | `{}` | Ресурсы контроллера |

### 3.2. Установка через манифесты

**Полный манифест установки:**

```yaml
# reloader-setup.yaml

---
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reloader
  namespace: monitoring
  labels:
    app: reloader

---
# ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
  labels:
    app: reloader
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["list", "get", "watch"]

---
# ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: reloader-role-binding
  labels:
    app: reloader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: reloader-role
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: monitoring

---
# Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: monitoring
  labels:
    app: reloader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: reloader
  template:
    metadata:
      labels:
        app: reloader
    spec:
      serviceAccountName: reloader
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.0.118  # Актуальная версия
          imagePullPolicy: IfNotPresent
          args:
            - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
            - --log-level=info
          ports:
            - containerPort: 9090
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 300m
              memory: 256Mi
          livenessProbe:
            httpGet:
              path: /healthz
              port: 9090
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /readyz
              port: 9090
            initialDelaySeconds: 5
            periodSeconds: 5
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL

---
# Service (для мониторинга)
apiVersion: v1
kind: Service
metadata:
  name: reloader
  namespace: monitoring
  labels:
    app: reloader
spec:
  ports:
    - port: 9090
      targetPort: 9090
      protocol: TCP
      name: http
  selector:
    app: reloader
```

### 3.3. Использование с приложением

**Пример: веб-сервер с конфигурацией в ConfigMap**

**Шаг 1: Создание ConfigMap и Deployment**

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

**Шаг 2: Обновление ConfigMap**

```bash
# Обновляем ConfigMap с новой версией
kubectl apply -f openresty-app-v2.yaml
```

**Шаг 3: Наблюдение за результатом**

```bash
# Watch за подами
kubectl get pods -w

# Вывод:
# NAME                                    READY   STATUS        RESTARTS   AGE
# openresty-deployment-5f8b9d6f6f-abcde   1/1     Running       0          2m
# openresty-deployment-5f8b9d6f6f-abcde   1/1     Terminating   0          3m
# openresty-deployment-c79f8f49d-fghij    1/1     Running       0          10s
```

### 3.4. Использование с Secret (TLS-сертификаты)

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

### 3.5. Автоматическое обнаружение для всех ресурсов

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

### 3.6. Исключение namespace'ов

**При установке через Helm:**

```yaml
# values.yaml
reloader:
  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --namespaces-to-select=default,production,staging
```

**При установке через манифесты:**

```yaml
spec:
  containers:
    - args:
        - --namespaces-to-ignore=kube-system
        - --log-level=info
```

### 3.7. Мониторинг и отладка

**Просмотр логов Reloader:**

```bash
kubectl logs -f deployment/reloader -n monitoring
```

**Пример вывода логов:**

```
time="2025-01-15T10:30:45Z" level=info msg="Reloader started"
time="2025-01-15T10:30:46Z" level=info msg="Watching for changes in namespace: default"
time="2025-01-15T10:31:00Z" level=info msg="ConfigMap 'openresty-index-html' updated in namespace 'default'"
time="2025-01-15T10:31:01Z" level=info msg="Triggering rolling upgrade for Deployment 'openresty-deployment'"
```

**Проверка статуса:**

```bash
kubectl get deployment reloader -n monitoring
kubectl describe deployment reloader -n monitoring
```

## 4. Дополнительная информация

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.19+ | Проверено до 1.32 |
| Helm | 3.0+ | Для установки через Helm |

### Ресурсы контроллера

| Ресурс | Request | Limit |
| :--- | :--- | :--- |
| **CPU** | 100m | 300m |
| **Memory** | 128Mi | 256Mi |

### Сравнение с альтернативами

| Инструмент | Подход | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Reloader** | Аннотации | Простота, гибкость | Требует аннотаций |
| **Checksum-аннотация** | Хеш в манифесте | Работает без контроллера | Требует настройки CI/CD |
| **ArgoCD** | GitOps | Полный контроль | Сложнее в настройке |

**Подробнее:** [Обновление ConfigMap и его влияние на поды](../Base/ConfigMap/update_and_rollout.md)

### Лучшие практики

1. **Игнорируйте системные namespace'ы** — `kube-system`, `kube-public`
2. **Используйте явные аннотации** — предсказуемее чем `auto: "true"`
3. **Настройте мониторинг** — отслеживайте логи Reloader
4. **Тестируйте в staging** — перед применением в production
5. **Задавайте ресурсы** — limits и requests для контроллера

### Ограничения

- **Не работает с `subPath` по умолчанию** — требуется явная аннотация
- **Только rolling restart** — не обновляет поды in-place
- **Один контроллер на кластер** — может быть bottleneck в больших кластерах

### Связанные документы

- **[ConfigMap](../Base/ConfigMap/update_and_rollout.md)** — обновление ConfigMap и rollout
- **[Secrets](../Security/application_secrets_management.md)** — управление секретами
- **[Deployment](../Base/deployment.md)** — rolling update стратегия
- **[Helm](./Helm/helm_overview.md)** — установка через Helm

### Репозиторий и документация

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Документация Stakater](https://github.com/stakater/Reloader#readme)
- [Helm Chart](https://github.com/stakater/stakater-charts/tree/master/charts/reloader)
