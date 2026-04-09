# Конфигурация Alertmanager в kube-prometheus-stack

## Определения

**Alertmanager в kube-prometheus-stack** — компонент Helm-чарта, развёртывающий Alertmanager как StatefulSet с декларативным управлением через `values.yaml`. Конфигурация делится на два уровня:

1. **Helm-параметры** (`alertmanager.*`) — управление инфраструктурой (реплики, ресурсы, хранилище, ingress).
2. **Конфигурация Alertmanager** (`alertmanager.config`) — маршрутизация, получатели, правила подавления (генерирует `alertmanager.yaml` в Secret).

> **См. также:** [Alertmanager — общая конфигурация](../../alertmanager.md), [Alertmanager CRD](../operator/crd/alertmanager.md).

## Основные концепции

### Структура Helm-параметров

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `alertmanager.enabled` | Включение компонента | `true` |
| `alertmanager.replicaCount` | Количество реплик | `1` |
| `alertmanager.alertmanagerSpec` | Спецификация Pod (ресурсы, tolerations, affinity) | `{}` |
| `alertmanager.config` | Конфигурация `alertmanager.yml` (глобальные параметры, маршруты, получатели) | `{}` |
| `alertmanager.ingress.enabled` | Создание Ingress-ресурса | `false` |
| `alertmanager.persistentVolume.enabled` | PersistentVolume для silences и данных | `false` |

### Реплики и высокая доступность

| Реплики | Поведение |
| :--- | :--- |
| `1` | Одиночный экземпёр, без HA |
| `3` | Минимум для кворума — дедупликация алертов через gossip-протокол |
| `>3` | Нечётное число (5, 7) для устойчивости к отказам |

> **Важно:** При `replicaCount > 1` Alertmanager автоматически настраивает кластеризацию через `--cluster.peer`.

### Хранилище

Alertmanager хранит silences и данные кластера. Без PersistentVolume данные теряются при перезапуске Pod.

| Режим | Описание | Когда использовать |
| :--- | :--- | :--- |
| `persistentVolume.enabled: true` | Dynamic provisioning через StorageClass | Production, кластеры с CSI |
| `volumeClaimTemplate` (через `alertmanagerSpec`) | Явный PVC | Тонкий контроль параметров хранилища |
| `emptyDir` (по умолчанию без PV) | Эфемерное хранилище | Тестовые среды |

### Конфигурация через `alertmanager.config`

Блок `alertmanager.config` в `values.yaml` генерирует Kubernetes Secret с `alertmanager.yaml`. Поддерживает полный синтаксис Alertmanager:

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
      smtp_smarthost: 'smtp.example.com:587'
      smtp_from: 'alerts@example.com'
    route:
      receiver: 'default-receiver'
      group_by: ['alertname', 'cluster']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:
        - match:
            severity: critical
          receiver: 'pagerduty'
    receivers:
      - name: 'default-receiver'
        email_configs:
          - to: 'ops-team@example.com'
            send_resolved: true
    inhibit_rules:
      - source_match:
          severity: 'critical'
        target_match:
          severity: 'warning'
        equal: ['alertname', 'instance']
```

> **См. также:** [Полная конфигурация Alertmanager](../../alertmanager.md#конфигурация-alertmanageryml).

## Практические сценарии

### Production-конфигурация с HA и PersistentVolume

```yaml
alertmanager:
  enabled: true
  replicaCount: 3

  alertmanagerSpec:
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 250m
        memory: 256Mi
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 2Gi

  config:
    global:
      resolve_timeout: 5m
      smtp_smarthost: 'smtp.yandex.ru:465'
      smtp_from: 'alerts@edu-prom.example.com'
      smtp_auth_username: 'alerts@edu-prom.example.com'
      smtp_auth_password: '<Password>'
    route:
      group_by: ['alertname', 'service']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 1h
      receiver: 'team-monitoring'
      routes:
        - match:
            service: prom
          receiver: 'team-ops'
        - match:
            severity: critical
          receiver: 'pagerduty-critical'
    receivers:
      - name: 'team-ops'
        email_configs:
          - to: 'ops-team@example.com'
            send_resolved: true
      - name: 'team-monitoring'
        email_configs:
          - to: 'monitoring-team@example.com'
            send_resolved: true
      - name: 'pagerduty-critical'
        pagerdutyConfigs:
          - routingKey: '<PAGERDUTY_KEY>'
            severity: critical
    inhibit_rules:
      - source_match:
          alertname: 'DatacenterDown'
        target_match:
          alertname: 'ServerDown'
        equal: ['cluster']
```

### Минимальная конфигурация для тестовой среды

```yaml
alertmanager:
  enabled: true
  replicaCount: 1

  config:
    global:
      resolve_timeout: 5m
    route:
      receiver: 'null'
    receivers:
      - name: 'null'
```

> **Примечание:** Receiver `null` отбрасывает все алерты — полезно для тестов без уведомлений.

### Отключение Alertmanager

```yaml
alertmanager:
  enabled: false
```

> **Важно:** При отключении Alertmanager Prometheus не сможет отправлять оповещения. Алерты будут видны в UI Prometheus, но уведомления не доставляются.

### Доступ через Ingress

```yaml
alertmanager:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - alertmanager.example.com
    paths:
      - /
    tls:
      - secretName: alertmanager-tls
        hosts:
          - alertmanager.example.com
```

### Проверка конфигурации

```bash
# Проверка Pod Alertmanager
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager

# Проверка Secret с конфигурацией
kubectl get secret alertmonitoring-kube-prometheus-stack-alertmanager -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d

# Валидация через amtool (внутри Pod)
kubectl exec -n monitoring alertmonitoring-kube-prometheus-stack-alertmanager-0 -- \
  amtool check-config /etc/alertmanager/config/alertmanager.yaml
```

### Установка и обновление

```bash
# Установка с файлом значений
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f values.yaml

# Обновление конфигурации Alertmanager
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values.yaml

# Проверка истории
helm history monitoring -n monitoring
```

> **Подробные инструкции:** [Онлайн установка](./practical_scenarios/online_installation.md), [Оффлайн установка](./practical_scenarios/offline_airgapped_installation.md).

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Параметр | Начальное значение | Метрика для наблюдения |
| :--- | :--- | :--- |
| `requests.memory` | `128Mi` | `container_memory_usage_bytes` |
| `requests.cpu` | `100m` | `rate(container_cpu_usage_seconds_total[5m])` |
| `storage` | `2Gi` | `alertmanager_notifications_failed_total` |
| `retention` silences | `120h` (default) | Размер PVC |

### Связанные темы

* [Alertmanager — общая конфигурация](../../alertmanager.md) — маршрутизация, HA, CLI
* [Alertmanager CRD](../operator/crd/alertmanager.md) — декларативное управление
* [AlertmanagerConfig CRD](../operator/crd/alertmanagerconfig.md) — маршруты и получатели через CRD
* [Практические сценарии установки](./practical_scenarios.md) — онлайн/оффлайн установка
* [Karma Dashboard](../../karma_dashboard.md) — расширенный UI для Alertmanager
