# Конфигурация Karma: ConfigMap и настройки UI

## Определения

**ConfigMap конфигурации Karma** — ресурс Kubernetes, содержащий файл `config.yaml`. Karma является stateless-приложением, поэтому все параметры подключения к Alertmanager и правила фильтрации меток передаются через этот манифест.

> **См. также:** [Дашборд Karma — общая информация](../../karma_dashboard.md).

---

## Основные концепции

### Структура конфигурации

| Секция | Назначение |
| :--- | :--- |
| `alertmanager.servers` | Список инстансов Alertmanager, с которых Karma собирает данные. |
| `labels.strip` | Метки, которые будут скрыты в интерфейсе (для уменьшения визуального шума). |
| `annotations.default` | Список аннотаций, развернутых по умолчанию при просмотре алерта. |

---

## Практические сценарии

### Манифест ConfigMap для Karma

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
      interval: 1m
      servers:
        - name: "Kubernetes Cluster"
          uri: "http://alertmanager.monitoring.svc.cluster.local:9093"
          timeout: 10s
          proxy: true

    labels:
      # Технические метки, которые не нужны в UI
      strip: ["receiver", "deployment", "replicaset"]
      keep: ["alertname", "severity", "instance", "pod"]
```

---

## Дополнительная информация

- **[Развёртывание Karma (Deployment)](./karma-deployment.md)** — описание пода и монтирования томов.
- **[Alertmanager StatefulSet](./alertmanager-statefulset.md)** — источник данных для дашборда.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
