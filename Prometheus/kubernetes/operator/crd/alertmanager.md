# Alertmanager — Концепции (CRD)

## Определения

**`kind: Alertmanager`** — Custom Resource Definition в Prometheus Operator для декларативного описания развёртывания экземпляра Alertmanager в Kubernetes. Определяет количество реплик, хранилище, ресурсы, селекторы для AlertmanagerConfig и параметры кластеризации.

> **См. также:** [Alertmanager](../../../alertmanager.md) — архитектура, маршрутизация, ключи запуска.

## Базовые концепции

### Назначение CRD Alertmanager

CRD `Alertmanager` управляет жизненным циклом StatefulSet Alertmanager, включая:

- Масштабирование (реплики для обеспечения кворума)
- Хранилище (PVC через `volumeClaimTemplate` или эфемерное хранилище)
- Привязку к узлам (`nodeSelector`, `tolerations`, `affinity`)
- Подключение ресурсов `AlertmanagerConfig` через селекторы
- Интеграцию с Kubernetes Secrets для работы с чувствительными данными

### Взаимосвязь с другими CRD

| CRD | Роль |
| :--- | :--- |
| **Alertmanager** | Описание развёртывания (реплики, хранилище, ресурсы) |
| [AlertmanagerConfig](./alertmanagerconfig.md) | Декларативная маршрутизация и получатели алертов |
| [Prometheus](./prometheus.md) | Prometheus-сервер, который инициирует отправку алертов в Alertmanager |
| [PrometheusRule](./prometheusrule.md) | Правила генерации алертов на стороне Prometheus |

Prometheus Operator автоматически связывает объекты `AlertmanagerConfig` с экземпляром `Alertmanager` через селекторы `alertmanagerConfigSelector` и `alertmanagerConfigNamespaceSelector`.

## Практические сценарии

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

### Основные параметры спецификации (spec)

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`replicas`** | Количество реплик (минимум 3 для обеспечения кворума) | `3` |
| **`version`** | Версия образа Alertmanager | `v0.31.0` |
| **`image`** | Кастомный образ (опционально) | `prom/alertmanager:v0.31.0` |
| **`storage`** | Настройка хранилища | `volumeClaimTemplate` или `emptyDir` |
| **`resources`** | Запросы/лимиты ресурсов (CPU, Memory) | `requests: {memory: 200Mi, cpu: 100m}` |
| **`alertmanagerConfigSelector`** | Селектор для поиска ресурсов `AlertmanagerConfig` | `matchLabels: {release: monitoring}` |
| **`alertmanagerConfigNamespaceSelector`** | Селектор namespace для `AlertmanagerConfig` | `matchNames: [monitoring]` |
| **`secrets`** | Kubernetes Secrets для монтирования в контейнер | `[slack-webhook-secret]` |
| **`nodeSelector`** | Привязка подов к узлам кластера | `{kubernetes.io/os: linux}` |
| **`tolerations`** | Толерации для узлов с taint-ами | `[{operator: "Exists"}]` |
| **`paused`** | Приостановка reconciliation (используется для отладки) | `false` |
| **`logLevel`** | Уровень логирования процесса | `info`, `debug`, `warn`, `error` |
| **`listenLocal`** | Слушать входящие подключения только на localhost | `false` |

### Настройка хранилища

#### PersistentVolumeClaim (рекомендуется для production)

Обеспечивает сохранение данных (состояние silences и уведомлений) при перезапуске подов:

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

#### Ephemeral storage (для тестов)

Данные удаляются при уничтожении пода:

```yaml
spec:
  storage:
    emptyDir: {}
```

### Высокая доступность (HA)

Для отказоустойчивой работы требуется конфигурация минимум из 3 реплик. Prometheus Operator автоматически управляет кластеризацией экземпляров с использованием gossip-протокола по порту 9094.

```yaml
spec:
  replicas: 3
```

**Особенности HA-развертывания:**

- Дедупликация алертов между репликами происходит автоматически.
- При использовании `volumeClaimTemplate` для каждой реплики создается свой отдельный PVC.
- Подробности кластеризации и работы gossip: [Alertmanager — HA](../../../alertmanager.md#высокая-доступность-ha).

### Подключение маршрутов (AlertmanagerConfig)

Для декларативного управления маршрутами и получателями используются селекторы:

```yaml
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

Любой объект `AlertmanagerConfig` в пространстве имен `monitoring` с меткой `release: monitoring` будет автоматически интегрирован. Подробности: [AlertmanagerConfig CRD](./alertmanagerconfig.md).

### Работа с секретами

Чувствительные данные, такие как URL вебхуков или учетные данные, должны храниться в Kubernetes Secrets и монтироваться через поле `secrets`:

```yaml
spec:
  secrets:
    - slack-webhook-secret
    - smtp-credentials
```

```bash
# Пример создания секрета для вебхука Slack
kubectl create secret generic slack-webhook-secret \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring
```

Смонтированный секрет будет доступен процессу Alertmanager по пути `/etc/alertmanager/secrets/slack-webhook-secret/url`.

### Лимиты и запросы ресурсов

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

### Привязка к узлам (Node Affinity/Tolerations)

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

## Дополнительная информация

### Отладка и диагностика (Troubleshooting)

| Действие | Команда |
| :--- | :--- |
| Просмотр объектов Alertmanager | `kubectl get alertmanager -n monitoring` |
| Чтение логов | `kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager` |
| Детальная информация об объекте | `kubectl describe alertmanager main -n monitoring` |
| Пауза reconciliation | `kubectl patch alertmanager main -n monitoring -p '{"spec":{"paused":true}}' --type=merge` |

### Связанные ресурсы

- [AlertmanagerConfig CRD](./alertmanagerconfig.md) — управление получателями и маршрутами алертов.
- [Prometheus CRD](./prometheus.md) — описание экземпляра Prometheus.
- [PrometheusRule CRD](./prometheusrule.md) — создание правил алертинга.
- [Alertmanager (Общая концепция)](../../../alertmanager.md) — архитектура, механизмы дедупликации и конфигурация.
- [High Availability](../high_availability.md) — HA конфигурация стека в Prometheus Operator.
