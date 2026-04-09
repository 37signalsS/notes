# Alertmanager StatefulSet (манифест)

## Definitions

**Alertmanager StatefulSet** — Kubernetes StatefulSet для развёртывания Alertmanager с инициализацией конфигурации через init-container. Паттерн обеспечивает безопасную подстановку секретов (токены, пароли) из Kubernetes Secret в шаблон `alertmanager.yml` во время запуска пода.

> **См. также:** [Паттерн безопасного управления конфигурацией](../../alertmanager.md#развёртывание-в-kubernetes-через-манифесты) (SSoT)

## Basic Concepts

### Архитектура подов

| Компонент | Описание |
|---|---|
| **Init Container (`config-init`)** | Образ `busybox:1.36`, читает шаблон из ConfigMap, подставляет секреты через `sed`, записывает готовый `alertmanager.yml` в `emptyDir` |
| **Основной контейнер (`alertmanager`)** | Образ `prom/alertmanager:v0.26.0`, монтирует готовый конфиг из `emptyDir`, запускается с `--config.file` и `--storage.path` |

### Схема volumes

| Volume | Тип | Назначение |
|---|---|---|
| `config-template` | ConfigMap | Шаблон `alertmanager.yml.tpl` с плейсхолдерами |
| `config` | emptyDir | Временный том для готового конфига (init-container → основной контейнер) |
| `templates` | ConfigMap | Go-шаблоны для форматирования уведомлений |
| `alertmanager-data` | PersistentVolumeClaim | Постоянное хранение silences и данных (1Gi, ReadWriteOnce) |

### Ключевые параметры запуска

| Параметр | Значение | Описание |
|---|---|---|
| `--config.file` | `/etc/alertmanager/alertmanager.yml` | Путь к сгенерированному конфигу |
| `--storage.path` | `/alertmanager` | Путь к PVC для данных |
| `containerPort` | `9093` | Порт веб-интерфейса и API |

## Practical Scenarios

### Манифест StatefulSet

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

### Пояснения к манифесту

**Init Container:**
- Образ `busybox:1.36` — минимальный, быстрый, содержит `sed` и `cat`
- Команда читает шаблон из `/config-template/alertmanager.yml.tpl`, подставляет 4 переменные окружения из Secret, записывает результат в `/config/alertmanager.yml`
- `set -e` — аварийное завершение при ошибке подстановки (под не запустится без валидного конфига)

**Основной контейнер:**
- `prom/alertmanager:v0.26.0` — проверяйте актуальность версии в [Alertmanager Installation](../../installation/alertmanager_installation.md#актуальная-версия)
- Монтирует готовый конфиг из `emptyDir` (путь `/etc/alertmanager`)
- Данные хранятся на PVC (`alertmanager-data`, 1Gi) — silences и состояние сохраняются при перезапусках

**StatefulSet vs Deployment:**
- StatefulSet выбран для стабильного сетевого идентификатора (`alertmanager-0`) и возможности масштабирования в HA-кластер с gossip-протоколем
- `serviceName: alertmanager` — требуется для DNS-разрешения пода

## Additional Information

- [Секреты](./secrets.md) — Kubernetes Secret с токенами SMTP и Telegram
- [ConfigMap-шаблон](./alertmanager-config.md) — шаблон `alertmanager.yml.tpl` с плейсхолдерами
- [Шаблоны сообщений](./alertmanager-templates.md) — Go-шаблоны для форматирования уведомлений
- [Сервисы](./services.md) — публикация Alertmanager и Karma наружу
