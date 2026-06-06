# Reloader — Практические сценарии использования

## Определения

**Сценарии использования Reloader** — типовые конфигурации и примеры применения контроллера Reloader для автоматического обновления подов (Pods) при изменении ConfigMap и Secret.

**Основные источники:** [Обзор и концепции Reloader](./reloader_overview.md) · [Мониторинг и отладка](./reloader_monitoring_and_best_practices.md)

---

## Основные концепции

### Конфигурация через аннотации

Reloader управляется с помощью аннотаций в метаданных объектов `Deployment`, `StatefulSet` или `DaemonSet`. Контроллер поддерживает как автоматическое обнаружение всех зависимых ресурсов, так и явное указание конкретных файлов конфигурации или секретов.

Полный список доступных аннотаций и способов подключения ресурсов (Volumes, ENV) приведён в основном файле:
[Обзор Reloader: Аннотации и механизмы](./reloader_overview.md#основные-концепции)

---

## Практические сценарии

### Сценарий 1: Веб-сервер с конфигурацией в ConfigMap

**Задача:** Автоматический перезапуск OpenResty при обновлении HTML (HyperText Markup Language) контента, хранящегося в ConfigMap.

**Шаг 1: Создание ресурсов**

Ниже представлен пример манифеста в формате YAML (язык разметки данных):

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
        <p>Последнее обновление: 2026-06-01</p>
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

После внесения изменений в файл `openresty-app-v2.yaml` примените его:

```bash
kubectl apply -f openresty-app-v2.yaml
```

**Шаг 3: Наблюдение за результатом**

```bash
# Отслеживание состояния подов в реальном времени
kubectl get pods -w
```

Ожидаемый результат: старый под завершается (`Terminating`), новый запускается с обновлённым контентом. Подробнее о мониторинге: [Мониторинг и отладка](./reloader_monitoring_and_best_practices.md).

---

### Сценарий 2: TLS-сертификаты через Secret

**Задача:** Перезапуск nginx-ingress при обновлении TLS (Transport Layer Security — протокол защиты транспортного уровня) сертификата.

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

**Задача:** Использование режима `auto`, при котором Reloader самостоятельно находит все ConfigMap и Secret, используемые подом.

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

**Предупреждение:** Режим `auto: "true"` менее предсказуем, так как любое изменение любого связанного ресурса вызовет перезапуск всего приложения.

---

## Дополнительная информация

### Ограничения и особенности

При использовании Reloader важно учитывать специфику работы с `subPath` и масштабируемость в больших кластерах. Подробное описание ограничений доступно в разделе:
[Обзор Reloader: Ограничения](./reloader_overview.md#ограничения)

**См. также:**

- [Мониторинг и отладка Reloader](./reloader_monitoring_and_best_practices.md)
- [Установка и настройка Reloader](./reloader_installation.md)
