# Пример: Развертывание Alertmanager и Karma в Kubernetes с помощью манифестов

В данном руководстве подробно рассматривается пример развертывания **Alertmanager** и его UI-дашборда **Karma** в Kubernetes с использованием стандартных манифестов.

Этот подход, в отличие от использования готовых Helm-чартов, предоставляет полный контроль над конфигурацией и является хорошим способом изучения взаимодействия компонентов.

**Ключевые особенности данного подхода:**
- **Alertmanager в `StatefulSet`**: для стабильного сетевого идентификатора и хранения состояния.
- **Безопасное управление секретами**: `init-container` используется для динамической подстановки секретов (токенов, паролей) в конфигурационный файл Alertmanager во время запуска пода.
- **Конфигурация через `ConfigMap`**: все конфигурационные файлы и шаблоны управляются через `ConfigMap`.
- **Интеграция с Telegram**: Настройка получателя для отправки алертов в Telegram, используя встроенную поддержку в новых версиях Alertmanager (0.24+).

---

## 1. Подготовка: Секреты

Перед развертыванием необходимо создать `Secret` в Kubernetes, который будет содержать все чувствительные данные.

**`alertmanager-secret.yaml`**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-secret
  namespace: monitoring # Укажите ваш namespace
type: Opaque
stringData:
  # -- Данные для SMTP (почта) --
  smtp.user: "your-email@example.com"
  smtp.password: "your-app-password"

  # -- Данные для Telegram --
  telegram.token: "bot-token-from-botfather"
  telegram.chat_id: "your-chat-id" # ID чата или канала
```
> **Важно:** Замените плейсхолдеры на реальные значения.

---

## 2. Alertmanager

### 2.1. Шаблон конфигурации (`ConfigMap`)

Создадим `ConfigMap`, содержащий **шаблон** конфигурации `alertmanager.yml`. Вместо реальных секретов в нем используются переменные-заглушки (например, `##SMTP_USER##`), которые `init-container` заменит на значения из `Secret`.

**`alertmanager-config-template.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config-template
  namespace: monitoring
data:
  alertmanager.yml.tpl: |
    global:
      # Заменится на значения из секрета
      smtp_smarthost: 'smtp.example.com:587'
      smtp_from: '##SMTP_USER##'
      smtp_auth_username: '##SMTP_USER##'
      smtp_auth_password: '##SMTP_PASSWORD##'

    route:
      group_by: ['job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'default-receiver'
      routes:
        - receiver: 'telegram-receiver'
          matchers:
            - severity =~ "critical|warning"
          continue: true
        - receiver: 'email-receiver'
          matchers:
            - severity =~ "critical|warning"

    receivers:
      - name: 'default-receiver'
        # Черная дыра для алертов без маршрута
        blackhole_configs:
          - {}

      - name: 'email-receiver'
        email_configs:
          - to: 'admin@example.com'
            headers:
              subject: 'K8s-Alert: {{ .GroupLabels.alertname }}'

      - name: 'telegram-receiver'
        telegram_configs:
          - bot_token: '##TELEGRAM_TOKEN##'
            chat_id: ##TELEGRAM_CHAT_ID##
            parse_mode: 'HTML' # Режим форматирования
            message: '{{ template "telegram.default.html" . }}'

    # Подключаем шаблоны для сообщений
    templates:
      - '/etc/alertmanager/templates/*.tmpl'

```

### 2.2. Шаблоны сообщений (`ConfigMap`)

Создадим отдельный `ConfigMap` для Go-шаблонов, которые форматируют сообщения для Telegram и почты.

**`alertmanager-templates.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-templates
  namespace: monitoring
data:
  telegram.default.html.tmpl: |
    {{ define "telegram.default.html" }}
    <b>{{ .Status | toUpper }}</b>
    {{ range .Alerts }}
    <b>Alert:</b> {{ .Annotations.summary }}
    <b>Description:</b> {{ .Annotations.description }}
    <b>Severity:</b> {{ .Labels.severity }}
    {{ end }}
    {{ end }}
```

### 2.3. Развертывание (`StatefulSet`)

Манифест `StatefulSet` для Alertmanager.
- **`initContainers`**: Секция, где происходит магия. Контейнер `config-init` читает шаблон из `alertmanager-config-template`, подставляет в него секреты из `alertmanager-secret` и записывает готовый `alertmanager.yml` в `emptyDir` volume.
- **Основной контейнер `alertmanager`**: Запускается уже с готовым конфигурационным файлом.
- **Volumes**:
    - `config-template`: монтирует шаблон.
    - `config`: `emptyDir` для обмена готовым конфигом между `init-container` и основным контейнером.
    - `templates`: монтирует шаблоны сообщений.

**`alertmanager-statefulset.yaml`**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  serviceName: alertmanager
  replicas: 1
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      # === Init Container для генерации конфига ===
      initContainers:
        - name: config-init
          image: busybox:1.36
          command: ['/bin/sh', '-c']
          args:
            - |
              #!/bin/sh
              set -e
              # Читаем шаблон и подставляем переменные окружения
              cat /config-template/alertmanager.yml.tpl | 
              sed "s/##SMTP_USER##/$SMTP_USER/g" | 
              sed "s/##SMTP_PASSWORD##/$SMTP_PASSWORD/g" | 
              sed "s/##TELEGRAM_TOKEN##/$TELEGRAM_TOKEN/g" | 
              sed "s/##TELEGRAM_CHAT_ID##/$TELEGRAM_CHAT_ID/g" 
              > /config/alertmanager.yml
          # Переменные окружения, извлеченные из секрета
          env:
            - name: SMTP_USER
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: smtp.user } }
            - name: SMTP_PASSWORD
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: smtp.password } }
            - name: TELEGRAM_TOKEN
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.token } }
            - name: TELEGRAM_CHAT_ID
              valueFrom: { secretKeyRef: { name: alertmanager-secret, key: telegram.chat_id } }
          volumeMounts:
            - name: config-template
              mountPath: /config-template
            - name: config
              mountPath: /config
      # === Основной контейнер Alertmanager ===
      containers:
        - name: alertmanager
          image: prom/alertmanager:v0.26.0
          args:
            - "--config.file=/etc/alertmanager/alertmanager.yml"
            - "--storage.path=/alertmanager"
          ports:
            - name: web
              containerPort: 9093
          volumeMounts:
            - name: config
              mountPath: /etc/alertmanager
            - name: templates
              mountPath: /etc/alertmanager/templates
              readOnly: true
            - name: alertmanager-data
              mountPath: /alertmanager
      volumes:
        - name: config-template
          configMap: { name: alertmanager-config-template }
        - name: templates
          configMap: { name: alertmanager-templates }
        - name: config
          emptyDir: {}
  volumeClaimTemplates:
    - metadata:
        name: alertmanager-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 1Gi } }
```
---

## 3. Karma

### 3.1. Конфигурация (`ConfigMap`)

Конфигурация для Karma очень проста. Нужно лишь указать адрес Alertmanager.

**`karma-config.yaml`**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: karma-config
  namespace: monitoring
data:
  config.yaml: |
    alertmanager:
      servers:
        - name: "Kubernetes"
          uri: "http://alertmanager.monitoring.svc.cluster.local:9093"
          
    # Фильтрация и отображение
    labels:
      # Не показывать эту метку в UI
      strip: ["receiver"] 
```

### 3.2. Развертывание (`Deployment`)

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
          image: ghcr.io/prymitive/karma:v0.117
          args:
            - "--config.file=/etc/karma/config.yaml"
          ports:
            - name: web
              containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /etc/karma
      volumes:
        - name: config
          configMap:
            name: karma-config
```
---

## 4. Сетевые сервисы (`Service` и `Ingress`)

Осталось опубликовать сервисы вовне.

- **`alertmanager-svc.yaml`**
- **`karma-svc.yaml`**
- **`ingress.yaml`**

```yaml
# alertmanager-svc.yaml
apiVersion: v1
kind: Service
metadata:
  name: alertmanager
  namespace: monitoring
spec:
  selector:
    app: alertmanager
  ports:
    - name: web
      port: 9093
      targetPort: web

---
# karma-svc.yaml
apiVersion: v1
kind: Service
metadata:
  name: karma
  namespace: monitoring
spec:
  selector:
    app: karma
  ports:
    - name: web
      port: 8080
      targetPort: web

---
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: monitoring-ingress
  namespace: monitoring
spec:
  rules:
    - host: alertmanager.k8s.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alertmanager
                port:
                  number: 9093
    - host: karma.k8s.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: karma
                port:
                  number: 8080
```

После применения всех этих манифестов у вас будет полностью рабочая связка Alertmanager + Karma.
