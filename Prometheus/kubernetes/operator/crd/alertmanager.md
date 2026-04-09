# CRD Alertmanager

## Definitions

**`kind: Alertmanager`** — Custom Resource Definition в Prometheus Operator для декларативного описания развёртывания экземпляра Alertmanager в Kubernetes. Определяет количество реплик, хранилище, ресурсы, селекторы для AlertmanagerConfig и параметры кластеризации.

> **SSoT по концепции Alertmanager:** [Alertmanager](../../../alertmanager.md) — архитектура, маршрутизация, HA, ключи запуска.

## Basic Concepts

### Назначение CRD Alertmanager

CRD `Alertmanager` управляет жизненным циклом StatefulSet Alertmanager, включая:
- Масштабирование (реплики для кворума)
- Хранилище (PVC через `volumeClaimTemplate` или ephemeral)
- Привязку к нодам (`nodeSelector`, `tolerations`, `affinity`)
- Подключение AlertmanagerConfig через селекторы
- Интеграцию с Secrets для чувствительных данных

### Взаимосвязь с другими CRD

| CRD | Роль |
| :--- | :--- |
| **Alertmanager** | Описание развёртывания (реплики, storage, resources) |
| [AlertmanagerConfig](./alertmanagerconfig.md) | Маршрутизация и получатели алертов (декларативно) |
| [Prometheus](./prometheus.md) | Prometheus-сервер, указывающий на Alertmanager для отправки алертов |
| [PrometheusRule](./prometheusrule.md) | Правила генерации алертов |

Prometheus Operator автоматически связывает AlertmanagerConfig с Alertmanager через селекторы `alertmanagerConfigSelector` и `alertmanagerConfigNamespaceSelector`.

## Practical Scenarios

### Базовая конфигурация

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

### Основные параметры spec

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`replicas`** | Количество реплик (минимум 3 для кворума) | `3` |
| **`version`** | Версия Alertmanager | `v0.31.0` |
| **`image`** | Кастомный образ (опционально) | `prom/alertmanager:v0.31.0` |
| **`storage`** | Конфигурация хранилища | `volumeClaimTemplate` или `emptyDir` |
| **`resources`** | Запросы/лимиты CPU и memory | `requests: {memory: 200Mi, cpu: 100m}` |
| **`alertmanagerConfigSelector`** | Селектор AlertmanagerConfig | `matchLabels: {release: monitoring}` |
| **`alertmanagerConfigNamespaceSelector`** | Селектор namespace для AlertmanagerConfig | `matchNames: [monitoring]` |
| **`secrets`** | Secrets для монтирования в контейнер | `[slack-webhook-secret]` |
| **`nodeSelector`** | Селектор нод | `{kubernetes.io/os: linux}` |
| **`tolerations`** | Толерации для tainted-нод | `[{operator: "Exists"}]` |
| **`paused`** | Приостановка рекозилиации (для отладки) | `false` |
| **`logLevel`** | Уровень логирования | `info`, `debug`, `warn`, `error` |
| **`listenLocal`** | Слушать только localhost | `false` |

### Конфигурация хранилища

#### PersistentVolumeClaim (рекомендуется для production)

```yaml
spec:
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

#### Ephemeral storage (без персистентности, для тестов)

```yaml
spec:
  storage:
    emptyDir: {}
```

### Высокая доступность

Для HA требуется минимум 3 реплики. Prometheus Operator автоматически настраивает кластеризацию через gossip-протол на порту 9094:

```yaml
spec:
  replicas: 3
```

**Важно:**
- Дедупликация алертов между репликами работает автоматически
- При использовании `volumeClaimTemplate` каждая реплика получает собственный PVC
- Подробнее о механизме кластеризации: [Alertmanager — HA](../../../alertmanager.md#высокая-доступность-ha)

### Подключение AlertmanagerConfig

Для использования декларативных конфигураций маршрутизации:

```yaml
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

AlertmanagerConfig с меткой `release: monitoring` в namespace `monitoring` будет автоматически применён. Подробнее: [AlertmanagerConfig CRD](./alertmanagerconfig.md).

### Секреты для получателей

Чувствительные данные (webhook URL, пароли) хранятся в Kubernetes Secrets и монтируются через поле `secrets`:

```yaml
spec:
  secrets:
    - slack-webhook-secret
    - smtp-credentials
```

```bash
# Создание секрета
kubectl create secret generic slack-webhook-secret \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring
```

Секрет доступен внутри контейнера Alertmanager по пути `/etc/alertmanager/secrets/slack-webhook-secret/url`.

### Ресурсы CPU и памяти

```yaml
spec:
  resources:
    requests:
      memory: 200Mi
      cpu: 100m
    limits:
      memory: 500Mi
      cpu: 500m
```

### Привязка к нодам

```yaml
spec:
  nodeSelector:
    kubernetes.io/os: linux
    monitoring: "true"
  tolerations:
    - key: "monitoring"
      operator: "Equal"
      value: "true"
      effect: "NoSchedule"
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchExpressions:
                - key: app.kubernetes.io/name
                  operator: In
                  values:
                    - alertmanager
            topologyKey: kubernetes.io/hostname
```

## Additional Information

### Отладка и troubleshooting

| Действие | Команда |
| :--- | :--- |
| Проверка статуса CRD | `kubectl get alertmanager -n monitoring` |
| Логи Alertmanager | `kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager` |
| Описание объекта | `kubectl describe alertmanager main -n monitoring` |
| Пауза рекозилиации | `kubectl patch alertmanager main -n monitoring -p '{"spec":{"paused":true}}' --type=merge` |

### Связанные темы

- [AlertmanagerConfig CRD](./alertmanagerconfig.md) — маршрутизация и получатели через CRD
- [Prometheus CRD](./prometheus.md) — описание Prometheus-сервера
- [PrometheusRule CRD](./prometheusrule.md) — правила генерации алертов
- [Alertmanager — общая концепция](../../../alertmanager.md) — архитектура, маршрутизация, HA, ключи запуска
- [High Availability](../high_availability.md) — HA конфигурация в Prometheus Operator
