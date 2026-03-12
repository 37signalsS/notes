# Alertmanager StatefulSet

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

## Смотрите также

- [Секреты](./secrets.md) — исходные данные
- [Конфигурация](./alertmanager-config.md) — шаблон конфига
- [Шаблоны сообщений](./alertmanager-templates.md) — форматирование уведомлений
- [Сервисы](./services.md) — публикация наружу
