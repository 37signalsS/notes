# Конфигурация прочих компонентов в kube-prometheus-stack

## Определения

**Прочие компоненты kube-prometheus-stack** — дополнительные компоненты Helm-чарта, обеспечивающие работу стека мониторинга: RBAC, автоматическая перезагрузка конфигурации, правила алертов по умолчанию, Push Gateway, Thanos Ruler.

> **См. также:** [Pushgateway — общая информация](../../pushgateway.md), [Prometheus Operator CRD](../operator/concepts.md).

## Основные концепции

### RBAC и Service Account

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `rbac.create` | Создание ClusterRole, ClusterRoleBinding для Prometheus Operator | `true` |
| `serviceAccount.create` | Создание ServiceAccount для каждого компонента | `true` |
| `serviceAccount.name` | Имя существующего ServiceAccount (если `create: false`) | `""` |
| `global.rbac.create` | Глобальный RBAC для всех компонентов | `true` |

**Рекомендация:** Оставить `true`. При использовании существующих ServiceAccount — указать `name` и `create: false`.

### ConfigMap Reload

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `configmapReload.prometheus.enabled` | Sidecar для автоперезагрузки Prometheus при изменении ConfigMap | `true` |
| `configmapReload.alertmanager.enabled` | Sidecar для автоперезагрузки Alertmanager при изменении ConfigMap | `true` |
| `configmapReload.container.image` | Образ контейнера reload | `ghcr.io/prometheus-operator/prometheus-config-reloader` |
| `configmapReload.resources` | Requests/limits для reload-контейнера | `{}` |

**Принцип работы:** Sidecar отслеживает изменения ConfigMap и отправляет сигнал HUP основному контейнеру для перечитки конфигурации без перезапуска Pod.

### Правила алертов по умолчанию (defaultRules)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `defaultRules.create` | Создание стандартных правил алертов (K8s, node, Prometheus) | `true` |
| `defaultRules.rules.*` | Включение/отключение отдельных групп правил | См. ниже |
| `defaultRules.additionalRuleLabels` | Добавление лейблов ко всем правилам | `{}` |
| `defaultRules.additionalRuleAnnotations` | Добавление аннотаций ко всем правилам | `{}` |

**Группы правил:**

| Группа | Описание | Когда отключать |
| :--- | :--- | :--- |
| `defaultRules.rules.alertmanager` | Алерты для Alertmanager | При использовании кастомных правил |
| `defaultRules.rules.etcd` | Алерты для ETCD | При отсутствии ETCD в кластере |
| `defaultRules.rules.general` | Общие алерты (HighCPU, HighMemory, DiskSpace) | При использовании внешних систем алертов |
| `defaultRules.rules.k8s` | Алерты для Kubernetes (PodCrashLooping, NodeNotReady) | Редко — полезно для всех |
| `defaultRules.rules.kubeApiserver` | Алерты для API Server | При внешнем API Server |
| `defaultRules.rules.kubelet` | Алерты для kubelet | При внешнем мониторинге |
| `defaultRules.rules.node` | Алерты для Node (Disk, Memory, CPU) | При использовании node-exporter правил |
| `defaultRules.rules.prometheus` | Алерты для Prometheus (ConfigReload, TargetDown) | Редко — полезно для всех |

### Thanos Ruler

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `thanosRuler.enabled` | Включение Thanos Ruler для агрегации алертов | `false` |
| `thanosRuler.replicas` | Количество реплик Thanos Ruler | `1` |
| `thanosRuler.resources` | Requests/limits CPU/memory | `{}` |

**Когда использовать:** Thanos Ruler позволяет выполнять правила алертов поверх нескольких Prometheus-инстансов (федерация, мульти-кластер).

### Push Gateway

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `pushgateway.enabled` | Включение Push Gateway | `false` |
| `pushgateway.replicaCount` | Количество реплик | `1` |
| `pushgateway.resources` | Requests/limits CPU/memory | `{}` |
| `pushgateway.persistentVolume.enabled` | PersistentVolume для метрик | `false` |

**Когда использовать:** Только для short-lived/batch задач, которые не могут быть опрошены Prometheus напрямую.

> **См. также:** [Pushgateway — общая информация](../../pushgateway.md).

### Мониторинг Control Plane

Компоненты Kubernetes Control Plane (API Server, Controller Manager, Scheduler, etcd) могут быть опрошены через встроенные ServiceMonitor'ы чарта.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `kubeApiServer.enabled` | Включение ServiceMonitor для API Server | `true` |
| `kubeApiServer.tlsConfig.insecureSkipVerify` | Пропуск проверки TLS для API Server | `false` |
| `kubeControllerManager.enabled` | Включение ServiceMonitor для Controller Manager | `true` |
| `kubeControllerManager.endpoints` | Список endpoints Controller Manager (если не на стандартном порту) | `[]` |
| `kubeScheduler.enabled` | Включение ServiceMonitor для Scheduler | `true` |
| `kubeScheduler.endpoints` | Список endpoints Scheduler | `[]` |
| `kubeEtcd.enabled` | Включение ServiceMonitor для etcd | `true` |
| `kubeEtcd.service.https` | Использовать HTTPS для etcd | `true` |
| `kubeEtcd.service.targetPort` | Порт etcd | `2381` |
| `kubeProxy.enabled` | Включение ServiceMonitor для kube-proxy | `true` |

**Важные нюансы:**

- **kube-controller-manager** и **kube-scheduler** по умолчанию привязаны к `127.0.0.1`. Для скрейпинга из Pod требуется изменить флаг `--address=0.0.0.0` в манифестах static Pod на каждой master-ноде.
- **etcd** требует TLS-сертификаты. Указываются через `kubeEtcd.serviceMonitor.scheme` и `kubeEtcd.serviceMonitor.caFile`/`certFile`/`keyFile` либо через `secret`.
- **kube-apiserver** доступен по умолчанию через внутренний Kubernetes Service `kubernetes.default.svc`.

**Пример конфигурации для kubeadm-кластера с TLS для etcd:**

```yaml
kubeEtcd:
  enabled: true
  service:
    enabled: true
    port: 2381
    targetPort: 2381
    scheme: https
    caFile: /etc/kubernetes/pki/etcd/ca.crt
    certFile: /etc/kubernetes/pki/etcd/server.crt
    keyFile: /etc/kubernetes/pki/etcd/server.key
```

## Практические сценарии

### Production-конфигурация

```yaml
# RBAC — оставить включенным
rbac:
  create: true
serviceAccount:
  create: true

# ConfigMap Reload — автоматическая перезагрузка при изменениях
configmapReload:
  prometheus:
    enabled: true
    resources:
      requests:
        cpu: 10m
        memory: 16Mi
      limits:
        cpu: 50m
        memory: 64Mi
  alertmanager:
    enabled: true
    resources:
      requests:
        cpu: 10m
        memory: 16Mi
      limits:
        cpu: 50m
        memory: 64Mi

# Правила алертов — включить основные, отключить неиспользуемые
defaultRules:
  create: true
  rules:
    alertmanager: true
    etcd: false          # ETCD не в кластере
    general: true
    k8s: true
    kubeApiserver: true
    kubelet: true
    node: true
    prometheus: true
  additionalRuleLabels:
    cluster: "production"

# Push Gateway — включить для batch-задач
pushgateway:
  enabled: true
  replicaCount: 1
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 128Mi
  persistentVolume:
    enabled: true
    storageClassName: longhorn
    size: 2Gi
```

### Минимальная конфигурация для тестовой среды

```yaml
# Отключить неиспользуемые компоненты
defaultRules:
  create: true
  rules:
    etcd: false
    kubeApiserver: false
    kubelet: false

pushgateway:
  enabled: false

thanosRuler:
  enabled: false
```

### Проверка работы ConfigMap Reload

```bash
# Проверка sidecar-контейнеров
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[*].spec.containers[*].name}'

# Ожидаемый вывод: prometheus configmap-reload

# Проверка логов reload-контейнера
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload

# Тестирование: изменить ConfigMap и проверить перезагрузку
kubectl edit configmap -n monitoring monitoring-kube-prometheus-stack-alertmanager
# В логах configmap-reload должно появиться: "Reloading configuration..."
```

### Настройка Push Gateway для batch-задач

После включения `pushgateway.enabled: true`, Prometheus автоматически начнёт скрейпить Push Gateway. Отправка метрик из cron-задачи:

```bash
#!/bin/bash
# Пример cron-задачи с отправкой метрик в Push Gateway

START_TIME=$(date +%s)

# Выполнение задачи
backup_result=0
mysqldump -u root mydb > /backup/mydb.sql || backup_result=1

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Отправка метрик в Push Gateway
cat <<EOF | curl --data-binary @- http://pushgateway.monitoring.svc:9091/metrics/job/mysql-backup/instance/db-primary
# HELP mysql_backup_duration_seconds Duration of MySQL backup
# TYPE mysql_backup_duration_seconds gauge
mysql_backup_duration_seconds ${DURATION}
# HELP mysql_backup_status Status of MySQL backup (1=success, 0=failure)
# TYPE mysql_backup_status gauge
mysql_backup_status ${backup_result}
EOF
```

> **Важно:** Push Gateway не удаляет метрики автоматически. Удаление группы метрик:

```bash
curl -X DELETE http://pushgateway.monitoring.svc:9091/metrics/job/mysql-backup/instance/db-primary
```

### Отключение правил алертов по умолчанию

```yaml
defaultRules:
  create: true
  rules:
    general: false       # Отключить все общие алерты
    k8s: false           # Отключить K8s-алерты
    node: false          # Отключить node-алерты
    prometheus: false    # Отключить prometheus-алерты
```

> **Примечание:** При отключении `defaultRules` необходимо предоставить собственные правила через PrometheusRule CRD.

### Thanos Ruler для мульти-кластерного мониторинга

```yaml
thanosRuler:
  enabled: true
  replicas: 2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi
  thanosRulerSpec:
    ruleSelector:
      matchLabels:
        thanos-ruler: "true"
    alertmanagersConfig:
      secret:
        name: alertmanager-config
        key: alertmanager.yaml
```

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Компонент | Параметр | Начальное значение | Метрика для наблюдения |
| :--- | :--- | :--- | :--- |
| configmapReload | `requests.memory` | `16Mi` | `container_memory_usage_bytes` |
| configmapReload | `requests.cpu` | `10m` | `rate(container_cpu_usage_seconds_total[5m])` |
| pushgateway | `requests.memory` | `64Mi` | `container_memory_usage_bytes` |
| pushgateway | `requests.cpu` | `50m` | `rate(container_cpu_usage_seconds_total[5m])` |
| pushgateway | `storage` | `2Gi` | `kubelet_volume_stats_capacity_bytes` |
