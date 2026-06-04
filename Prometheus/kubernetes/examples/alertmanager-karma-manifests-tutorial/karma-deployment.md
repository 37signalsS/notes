# Karma Deployment (манифест)

## Определения

**Karma Deployment** — Kubernetes Deployment для развёртывания Karma (дашборд Alertmanager). Stateless-приложение, не требует постоянного хранилища (PVC), конфигурация монтируется из ConfigMap.

> **См. также:** материал [Karma Dashboard](../../karma_dashboard.md) — общие возможности и архитектура

## Основные концепции

### Характеристики пода Karma

| Параметр | Значение | Описание |
|---|---|---|
| **Образ** | `ghcr.io/prymitive/karma:v0.117` | Официальный образ Karma из GitHub Container Registry |
| **Порт** | `8080` (TCP) | Веб-интерфейс Karma |
| **Реплики** | `1` | Stateless — можно масштабировать, но обычно достаточно одной реплики |
| **Конфигурация** | ConfigMap → `/etc/karma/config.yaml` | Файл конфигурации Karma |
| **PVC** | Не требуется | Karma не хранит данные — настройки UI сохраняются в браузере |

### Схема volumes

| Volume | Тип | Назначение |
|---|---|---|
| `config` | ConfigMap | Монтирует `config.yaml` из [karma-config.md](./karma-config.md) |

### Ключевые аргументы запуска

| Аргумент | Значение | Описание |
|---|---|---|
| `--config.file` | `/etc/karma/config.yaml` | Путь к файлу конфигурации Karma |

## Практические сценарии

### Манифест Deployment

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

### Пояснения к манифесту

**Контейнер:**

- Образ `ghcr.io/prymitive/karma:v0.117` — проверяйте актуальность версии в [официальном репозитории](https://github.com/prymitive/karma/releases)
- Аргумент `--config.file=/etc/karma/config.yaml` — указывает путь к конфигурации, смонтированной из ConfigMap
- Порт `8080` — стандартный порт Karma, используется Service для маршрутизации

**Volume:**

- ConfigMap `karma-config` монтируется в `/etc/karma` — содержит `config.yaml` с адресом Alertmanager и настройками отображения
- `readOnly: true` не указан явно — по умолчанию ConfigMap монтируется как read-only

**Stateless-архитектура:**

- Karma не требует PVC — все настройки (фильтры, темы) хранятся в `localStorage` браузера
- При перезапуске пода конфигурация восстанавливается из ConfigMap автоматически

### Проверка работоспособности

```bash
# Проверка пода
kubectl get pods -n monitoring -l app=karma

# Проверка логов
kubectl logs -n monitoring deploy/karma

# Проверка доступности (из кластера)
kubectl run test --rm -it --image=curlimages/curl --restart=Never \
  -- curl -s -o /dev/null -w "%{http_code}" http://karma:8080
# Ожидаемый ответ: 200
```

## Дополнительная информация

- [Karma ConfigMap](./karma-config.md) — конфигурация Karma (URL Alertmanager, фильтрация меток)
- [Сервисы](./services.md) — публикация Karma наружу через Service и Ingress
- [Karma Dashboard](../../karma_dashboard.md) — общее описание Karma
