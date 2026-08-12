# Конфигурация Karma: ConfigMap и настройки UI

## Определения

**ConfigMap конфигурации Karma** — ресурс Kubernetes, содержащий файл `config.yaml`. Karma является stateless-приложением, поэтому все параметры подключения к Alertmanager, правила агрегации и визуализации передаются через этот манифест.

> **См. также:** [Дашборд Karma — общая информация](../../../karma_dashboard.md).

---

## Основные концепции

### Структура конфигурации

| Секция | Назначение |
| :--- | :--- |
| `alertmanager.servers` | Список инстансов Alertmanager. Параметр `proxy: true` обязателен для возможности создания/редактирования silences через UI Karma. |
| `filters.default` | Список фильтров, применяемых при загрузке страницы (например, скрытие подтвержденных алертов). |
| `labels.strip` | Список меток, которые будут скрыты в UI для уменьшения визуального шума (например, служебные метки Kubernetes). |
| `grouping` | Настройка логики объединения алертов в группы по общим признакам (по умолчанию — `alertname`). |

---

## Практические сценарии

### Расширенный манифест ConfigMap для Karma

Пример конфигурации с агрегацией по Severity и фильтрацией служебных меток.

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
          proxy: true  # Разрешает управление silences из Karma

    # Настройки фильтрации при загрузке UI
    filters:
      default:
        - "@state=active"  # По умолчанию показывать только активные алерты

    labels:
      # Скрываем неинформативные метки
      strip: 
        - "receiver"
        - "deployment"
        - "replicaset"
        - "controller-revision-hash"
        - "pod-template-hash"
      keep: ["alertname", "severity", "instance", "pod", "namespace"]

    # Группировка алертов в интерфейсе
    grouping:
      by: ["alertname", "severity", "namespace"]
      groupClusterBy: ["alertname"]
```

---

## Дополнительная информация

- **[Развёртывание Karma (Deployment)](./karma-deployment.md)** — описание пода и процесса монтирования ConfigMap.
- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — настройка Ingress Auth для защиты интерфейса Karma.
- **[Alertmanager StatefulSet](./alertmanager-statefulset.md)** — описание бэкенд-составляющей стека.
