# Reloader

## 1. Определения

**Reloader** — это контроллер для Kubernetes от Stakater, который отслеживает изменения в `ConfigMap` и `Secret` и автоматически выполняет rolling upgrade для ассоциированных с ними `Deployment`, `StatefulSet` или `DaemonSet`.

Это решает распространенную проблему, когда после обновления конфигурации (например, файла `nginx.conf` в `ConfigMap`) или секрета (например, TLS-сертификата) требуется вручную перезапускать поды, чтобы они подхватили изменения. Reloader автоматизирует этот процесс.

## 2. Основные концепции

### Принцип работы

1.  **Отслеживание:** Reloader с помощью `watch` API Kubernetes следит за событиями обновления `ConfigMap` и `Secret` во всем кластере.
2.  **Поиск зависимостей:** Когда `ConfigMap` или `Secret` изменяется, Reloader ищет `Deployment`, `StatefulSet` и `DaemonSet`, которые используют этот ресурс. Связь определяется по тому, как ресурс монтируется в под (`volumes`, `envFrom`).
3.  **Инициирование rollout:** Если найдена зависимая рабочая нагрузка, у которой есть специальная аннотация, Reloader выполняет `rollout restart` (для `Deployment`) или аналогичное действие для других типов, что приводит к плавному обновлению подов.

### Аннотации для конфигурации

Reloader настраивается с помощью аннотаций в метаданных рабочей нагрузки:

*   **Автоматический поиск (`auto: "true"`)**:
    ```yaml
    reloader.stakater.com/auto: "true"
    ```
    В этом режиме Reloader автоматически обнаружит все `ConfigMap` и `Secret`, используемые в поде, и будет следить за ними.

*   **Указание конкретных ресурсов**:
    Можно явно указать, за какими ресурсами нужно следить. Это предпочтительный способ, так как он более предсказуем.
    ```yaml
    # Следить за одним ConfigMap
    configmap.reloader.stakater.com/reload: "my-app-config"
    
    # Следить за несколькими Secret'ами (через запятую)
    secret.reloader.stakater.com/reload: "my-app-tls, my-app-db-creds"
    ```

## 3. Практические сценарии

### 3.1. Установка Reloader

Reloader устанавливается как `Deployment` в кластер. Ему требуются права на чтение `ConfigMap` и `Secret` и на обновление `Deployment`, `StatefulSet` и `DaemonSet` в масштабе всего кластера.

**Пример манифеста для установки (сокращенный):**

```yaml
# reloader-setup.yaml

# 1. ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reloader
  namespace: monitoring # Рекомендуется ставить в отдельный или общий namespace для утилит

---
# 2. ClusterRole с необходимыми правами
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
rules:
- apiGroups: [""]
  resources: ["secrets", "configmaps"]
  verbs: ["list", "get", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "daemonsets", "statefulsets"]
  verbs: ["list", "get", "watch", "update", "patch"]
# ... и другие binding'и

---
# 3. Deployment самого Reloader'а
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: monitoring
spec:
  replicas: 1
  template:
    metadata:
      labels:
        app: reloader
    spec:
      serviceAccountName: reloader
      containers:
      - image: stakater/reloader:v0.0.85 # Используйте актуальную версию
        name: reloader
        args:
        - --namespaces-to-ignore=kube-system # Игнорировать системный namespace
        resources:
          limits:
            cpu: 400m
            memory: 400Mi
          requests:
            cpu: 100m
            memory: 100Mi
```

### 3.2. Использование с приложением

Рассмотрим пример с `Deployment` веб-сервера `OpenResty`, конфигурация которого хранится в `ConfigMap`.

**Шаг 1: Создание `ConfigMap` и `Deployment`**

```yaml
# openresty-app.yaml

apiVersion: v1
kind: ConfigMap
metadata:
  name: openresty-index-html
data:
  index.html: |
    <html><body><h1>Версия 1</h1></body></html>
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openresty-deployment
  annotations:
    # Указываем Reloader следить за этим Deployment'ом
    # и реагировать на изменения в ConfigMap 'openresty-index-html'
    configmap.reloader.stakater.com/reload: "openresty-index-html"
spec:
  replicas: 1
  template:
    # ...
    spec:
      containers:
      - name: openresty
        image: openresty/openresty:latest
        volumeMounts:
        - name: index-volume
          mountPath: /usr/local/openresty/nginx/html/index.html
          subPath: index.html
      volumes:
      - name: index-volume
        configMap:
          name: openresty-index-html
```
> Обратите внимание на аннотацию `configmap.reloader.stakater.com/reload`.

**Шаг 2: Обновление `ConfigMap`**

Изменим `ConfigMap`, например, обновив `index.html` на "Версия 2".

```bash
# Обновляем ConfigMap
kubectl apply -f openresty-app-v2.yaml
```

**Шаг 3: Наблюдение за результатом**

Сразу после применения изменений можно отследить поды:
```bash
kubectl get pods -w
```
Вы увидите, что Reloader обнаружил изменение и инициировал `rollout`. Старый под будет терминирован, а новый — создан с обновленной конфигурацией.

```
NAME                                    READY   STATUS        RESTARTS   AGE
openresty-deployment-5f8b9d6f6f-abcde   1/1     Running       0          2m
openresty-deployment-5f8b9d6f6f-abcde   1/1     Terminating   0          3m
openresty-deployment-c79f8f49d-fghij    1/1     Running       0          10s
```

Это избавляет от необходимости выполнять `kubectl rollout restart deployment/openresty-deployment` вручную.

## 4. Дополнительная информация

*   **Игнорирование namespace'ов:** Рекомендуется всегда игнорировать `kube-system` с помощью аргумента `--namespaces-to-ignore=kube-system`, чтобы избежать случайных перезагрузок системных компонентов.
*   **Ресурсы:** Reloader — легковесное приложение, но для него все равно следует задавать `requests` и `limits`.
*   [Официальный репозиторий Stakater Reloader](https://github.com/stakater/Reloader)
