# Reloader — Практические сценарии использования

## Definitions

**Сценарии использования Reloader** — типовые конфигурации и примеры применения контроллера Reloader для автоматического обновления подов при изменении ConfigMap и Secret.

**SSoT:** [Обзор и концепции Reloader](./reloader_overview.md) · [Мониторинг и отладка](./reloader_monitoring_and_best_practices.md)

---

## Basic Concepts

### Типы аннотаций

| Аннотация | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `configmap.reloader.stakater.com/reload` | Явное указание ConfigMap | Контроль над конкретными ресурсами |
| `secret.reloader.stakater.com/reload` | Явное указание Secret | TLS-сертификаты, учётные данные |
| `reloader.stakater.com/auto: "true"` | Автоматическое обнаружение | Простые конфигурации, все ресурсы |

### Способы подключения ресурсов

- **volumeMounts** — ConfigMap/Secret как файл в поде
- **envFrom** — все ключи ConfigMap/Secret как переменные окружения
- **env.valueFrom** — отдельные ключи как переменные окружения

---

## Practical Scenarios

### Сценарий 1: Веб-сервер с конфигурацией в ConfigMap

**Задача:** Автоматический перезапуск OpenResty при обновлении HTML-контента через ConfigMap.

**Шаг 1: Создание ресурсов**

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
kubectl apply -f openresty-app-v2.yaml
```

**Шаг 3: Наблюдение за результатом**

```bash
# Watch за подами
kubectl get pods -w
```

Ожидаемый результат: старый pod завершается (`Terminating`), новый запускается с обновлённым контентом. Подробнее о мониторинге: [Мониторинг и отладка](./reloader_monitoring_and_best_practices.md).

---

### Сценарий 2: TLS-сертификаты через Secret

**Задача:** Перезапуск nginx-ingress при обновлении TLS-сертификата.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-ingress
  annotations:
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

### Сценарий 3: Автоматическое обнаружение всех ресурсов

**Задача:** Не перечислять ресурсы вручную — Reloader сам найдёт все ConfigMap и Secret, используемые подом.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  annotations:
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

**Предупреждение:** `auto: "true"` менее предсказуем — любое изменение любого ConfigMap/Secret в поде вызовет перезапуск.

---

## Additional Information

### Ограничения при использовании subPath

При монтировании через `subPath` Reloader может не отследить изменения. В этом случае рекомендуется:

- Использовать монтирование всей директории вместо `subPath`
- Или добавить явную аннотацию `configmap.reloader.stakater.com/reload`

Подробнее об ограничениях: [Обзор и концепции](./reloader_overview.md)
