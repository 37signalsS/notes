# CRD Alertmanager

## Определения

**`kind: Alertmanager`** — Custom Resource Definition для описания экземпляра Alertmanager.

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.31.0
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

## Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`replicas`** | Количество реплик | `3` (для кворума) |
| **`version`** | Версия Alertmanager | `v0.31.0` |
| **`storage`** | Конфигурация хранилища | `volumeClaimTemplate` |
| **`resources`** | Ресурсы CPU/memory | `requests/limits` |
| **`alertmanagerConfigSelector`** | Селектор AlertmanagerConfig | `matchLabels: {release: monitoring}` |
| **`alertmanagerConfigNamespaceSelector`** | Селектор namespace | `matchNames: [monitoring]` |
| **`secrets`** | Secrets для конфигурации | `[slack-webhook-secret]` |
| **`nodeSelector`** | Селектор нод | `{kubernetes.io/os: linux}` |
| **`tolerations`** | Толерации | `[{operator: "Exists"}]` |

## Хранилище

### VolumeClaimTemplate

```yaml
storage:
  volumeClaimTemplate:
    spec:
      storageClassName: standard
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### Ephemeral storage (без персистентности)

```yaml
storage:
  emptyDir: {}
```

## Высокая доступность

Для HA конфигурации:

```yaml
spec:
  replicas: 3  # Минимум 3 для кворума
```

**Важно:**

* Минимум 3 реплики для кворума
* Кластеризация через `--cluster.listen-address`
* Дедупликация алертов между репликами

**Подробнее:** [Alertmanager HA](../../../alertmanager.md#кластеризация)

## Конфигурация через AlertmanagerConfig

AlertmanagerConfig позволяет декларативно настраивать маршрутизацию и получателей:

```yaml
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

**Подробнее:** [AlertmanagerConfig](./alertmanagerconfig.md)

## Связанные темы

* **[Prometheus CRD](./prometheus.md)** — описание Prometheus
* **[AlertmanagerConfig](./alertmanagerconfig.md)** — маршрутизация и получатели
* **[High Availability](../high_availability.md)** — HA конфигурация
* **[Alertmanager](../../alertmanager.md)** — базовая настройка
