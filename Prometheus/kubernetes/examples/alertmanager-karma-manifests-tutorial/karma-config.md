# Конфигурация Karma (ConfigMap)

## Определения

**ConfigMap Karma** — Kubernetes ConfigMap, содержащий файл `config.yaml` с настройками Karma: адреса серверов Alertmanager, параметры фильтрации меток и отображения. Монтируется в под Karma как `--config.file`.

> **См. также:** материал [Karma Dashboard](../../karma_dashboard.md) — общие возможности и Helm-установка

## Основные концепции

### Структура конфигурационного файла Karma

| Блок | Назначение | Обязательный |
|---|---|---|
| `alertmanager.servers` | Список сервер Alertmanager для сбора алертов | Да |
| `labels.strip` | Метки, которые следует скрыть из UI | Нет |
| `labels.keep` | Метки, которые следует показать (обратная фильтрация) | Нет |
| `annotations.default` | Аннотации, отображаемые по умолчанию | Нет |
| `receivers.keep` | Получатели, отображаемые в UI | Нет |

### Формат URI Alertmanager

| Тип подключения | Формат URI | Пример |
|---|---|---|
| **Внутри кластера (ClusterIP)** | `http://<service>.<namespace>.svc.cluster.local:<port>` | `http://alertmanager.monitoring.svc.cluster.local:9093` |
| **С внешним доступом (Ingress)** | `https://<hostname>` | `https://alertmanager.example.com` |
| **Несколько серверов** | Массив в `servers: []` | См. раздел «Несколько Alertmanager» ниже |

## Практические сценарии

### Манифест ConfigMap

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

### Пояснения к конфигу

| Параметр | Значение | Описание |
|---|---|---|
| `alertmanager.servers[0].name` | `"Kubernetes"` | Отображаемое имя сервера в UI Karma |
| `alertmanager.servers[0].uri` | `http://alertmanager.monitoring.svc.cluster.local:9093` | DNS-имя сервиса Alertmanager внутри кластера |
| `labels.strip` | `["receiver"]` | Метка `receiver` техническая — скрывается из UI для чистоты |

### Несколько серверов Alertmanager

Karma поддерживает агрегацию нескольких Alertmanager в едином интерфейсе:

```yaml
alertmanager:
  servers:
    - name: "Production"
      uri: "http://alertmanager-prod.monitoring.svc.cluster.local:9093"
    - name: "Staging"
      uri: "http://alertmanager-staging.monitoring.svc.cluster.local:9093"
```

### Дополнительные настройки

Расширенный конфиг с управлением аннотациями и таймаутами:

```yaml
alertmanager:
  servers:
    - name: "Kubernetes"
      uri: "http://alertmanager.monitoring.svc.cluster.local:9093"
      timeout: "10s"

labels:
  strip: ["receiver", "namespace"]
  keep: ["alertname", "severity", "instance"]

annotations:
  default:
    - summary
    - description
    - runbook_url
```

### Монтирование в Deployment

ConfigMap монтируется в [karma-deployment.md](./karma-deployment.md) через `volumeMounts`:

```yaml
volumeMounts:
  - name: config
    mountPath: /etc/karma
    readOnly: true
```

И передаётся аргументом: `--config.file=/etc/karma/config.yaml`

## Дополнительная информация

- [Karma Deployment](./karma-deployment.md) — манифест Deployment с монтированием данного ConfigMap
- [Alertmanager StatefulSet](./alertmanager-statefulset.md) — источник алертов для Karma
- [Karma Dashboard](../../karma_dashboard.md) — общее описание Karma
