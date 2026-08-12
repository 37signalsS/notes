# Конфигурация прочих компонентов в kube-prometheus-stack

## Определения

**Прочие компоненты kube-prometheus-stack** — вспомогательные элементы Helm-чарта, обеспечивающие работу стека мониторинга: управление доступом (RBAC), автоматическая перезагрузка конфигураций, стандартные правила алертов, агрегация алертов через Thanos Ruler, сбор метрик через Pushgateway и мониторинг системных компонентов Kubernetes.

> **См. также:** [Pushgateway — общая информация](../../pushgateway.md), [Prometheus Operator CRD](../operator/concepts.md).

## Основные концепции

### RBAC и Service Account

Управление правами доступа критично для работы Оператора, так как ему необходим доступ к API Kubernetes для обнаружения целей (Service Discovery).

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `rbac.create` | Создание ClusterRole и ClusterRoleBinding для Prometheus Operator. | `true` |
| `serviceAccount.create` | Создание ServiceAccount для каждого компонента. | `true` |
| `serviceAccount.name` | Имя существующего ServiceAccount (если `create: false`). | `""` |
| `global.rbac.create` | Глобальный переключатель RBAC для всех компонентов чарта. | `true` |

**Рекомендация:** Оставляйте `true`. При использовании существующих ServiceAccount (например, созданных через Terraform) укажите `name` и установите `create: false`.

### ConfigMap Reload (Sidecar)

Механизм автоматической перезагрузки конфигурации без перезапуска Pod.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `configmapReload.prometheus.enabled` | Sidecar для автоперезагрузки Prometheus. | `true` |
| `configmapReload.alertmanager.enabled` | Sidecar для автоперезагрузки Alertmanager. | `true` |
| `configmapReload.container.image` | Образ `ghcr.io/prometheus-operator/prometheus-config-reloader`. | Актуальная версия |
| `configmapReload.resources` | Requests/limits для reload-контейнера. | `{}` |

**Принцип работы:** Sidecar отслеживает изменения ConfigMap/Secret и отправляет HTTP POST запрос на `//-/reload` основному контейнеру. С версии Оператора v0.70+ многие функции релоадера встроены в основной бинарный файл Оператора, но sidecar всё ещё используется для обеспечения совместимости.

### Правила алертов по умолчанию (defaultRules)

Это набор преднастроенных `PrometheusRule`. В версиях 2024–2025 группы правил стали более гранулярными, разделившись на **Alerting** и **Recording**.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `defaultRules.create` | Создание стандартных правил алертов. | `true` |
| `defaultRules.rules.*` | Включение/отключение отдельных групп правил. | `true` |
| `defaultRules.additionalRuleLabels` | Добавление лейблов ко всем правилам. | `{}` |
| `defaultRules.additionalRuleAnnotations` | Добавление аннотаций ко всем правилам. | `{}` |

**Группы правил (Актуальный список 2024-2025):**

| Группа | Описание | Когда отключать |
| :--- | :--- | :--- |
| `alertmanager` | Состояние Alertmanager. | При использовании кастомных правил. |
| `etcd` | Мониторинг etcd. | Если etcd не управляется вами (облачные кластеры). |
| `general` | Общие алерты (TargetDown, Watchdog). | Редко. |
| `k8s` | Базовые правила Kubernetes. | Редко — полезно для всех. |
| `kubeApiserverAvailability` | Доступность API-сервера. | В облачных кластерах (EKS/GKE). |
| `kubeApiserverBurnrate` | Error Burnrate для API-сервера. | При использовании кастомных SLO. |
| `kubelet` | Алерты для kubelet. | При внешнем мониторинге узлов. |
| `nodeExporterAlerting` | Алерты Node Exporter (CPU, Disk, Mem). | При использовании своих порогов. |
| `nodeExporterRecording` | Правила записи (агрегаты для дашбордов). | Для экономии ресурсов (редко). |
| `prometheus` | Мониторинг самого Prometheus. | Редко. |
| `windows` | Алерты для Windows-узлов. | Если в кластере нет Windows-нод. |

### Thanos Ruler

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `thanosRuler.enabled` | Включение Thanos Ruler для агрегации алертов. | `false` |
| `thanosRuler.replicas` | Количество реплик (рекомендуется 2 для HA). | `1` |
| `thanosRuler.resources` | Requests/limits CPU/memory. | `{}` |
| `thanosRuler.thanosRulerSpec.ruleSelector` | Селектор для PrometheusRule. | `{}` |

**Когда использовать:** Позволяет вычислять правила алертов над данными из нескольких Prometheus (например, в мульти-кластерной архитектуре с Thanos Querier).

### Push Gateway

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `pushgateway.enabled` | Включение Push Gateway. | `false` |
| `pushgateway.replicaCount` | Количество реплик. | `1` |
| `pushgateway.resources` | Requests/limits CPU/memory. | `{}` |
| `pushgateway.persistentVolume.enabled` | Сохранение метрик между перезапусками. | `false` |

**Важно:** Используйте только для задач, которые нельзя опросить по pull-модели (batch jobs). Не используйте для обычных сервисов.

### Мониторинг Control Plane

| Параметр | Описание | Cloud (EKS/GKE/AKS) | On-prem (kubeadm) |
| :--- | :--- | :--- | :--- |
| `kubeApiServer.enabled` | Мониторинг API Server. | Включен (через внутренний IP). | Требует настройки. |
| `kubeControllerManager.enabled` | Мониторинг Controller Manager. | **Недоступен** | Требует `--address=0.0.0.0`. |
| `kubeScheduler.enabled` | Мониторинг Scheduler. | **Недоступен** | Требует `--address=0.0.0.0`. |
| `kubeEtcd.enabled` | Мониторинг etcd. | **Недоступен** | Требует TLS сертификаты. |
| `kubeProxy.enabled` | Мониторинг kube-proxy. | Зависит от провайдера. | Обычно включен. |

**Важные нюансы:**

- **kube-controller-manager / kube-scheduler:** По умолчанию слушают `127.0.0.1`. Нужно изменить на `0.0.0.0` в `/etc/kubernetes/manifests/` на мастер-нодах.
- **etcd:** Требует доступа к сертификатам. Можно прокинуть секрет с сертификатами в под Prometheus или использовать `insecureSkipVerify: true` (не рекомендуется).

## Практические сценарии

### Production-конфигурация (Пример)

```yaml
rbac:
  create: true

configmapReload:
  prometheus:
    resources:
      requests: { cpu: 10m, memory: 16Mi }
      limits: { cpu: 50m, memory: 64Mi }

defaultRules:
  create: true
  rules:
    etcd: false # Отключено для EKS
    kubeApiserverAvailability: true
    nodeExporterAlerting: true
    nodeExporterRecording: true
  additionalRuleLabels:
    cluster: "prod-main"

pushgateway:
  enabled: true
  persistentVolume:
    enabled: true
    size: 2Gi
```

### Настройка etcd (On-prem кластер)

```yaml
kubeEtcd:
  enabled: true
  service:
    enabled: true
    port: 2381
    targetPort: 2381
  serviceMonitor:
    scheme: https
    caFile: /etc/prometheus/secrets/etcd-certs/ca.crt
    certFile: /etc/prometheus/secrets/etcd-certs/client.crt
    keyFile: /etc/prometheus/secrets/etcd-certs/client.key
```

### Проверка работы ConfigMap Reload

```bash
# Список контейнеров в поде Prometheus
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[*].spec.containers[*].name}'
# → prometheus configmap-reload (или prometheus-config-reloader)

# Логи релоадера
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c configmap-reload

# Тест: измените любой PrometheusRule и проверьте логи
kubectl patch prometheusrule <name> --type merge -p '{"metadata":{"labels":{"test":"reload"}}}'
```

### Использование Push Gateway в CI/CD (Bash)

```bash
#!/bin/bash
JOB_NAME="backup-db"
START=$(date +%s)

# Команда бэкапа
./backup.sh
STATUS=$?

END=$(date +%s)
DURATION=$((END - START))

# Отправка в Pushgateway
cat <<EOF | curl --data-binary @- http://pushgateway.monitoring.svc:9091/metrics/job/$JOB_NAME
# HELP backup_duration_seconds Время выполнения бэкапа
# TYPE backup_duration_seconds gauge
backup_duration_seconds $DURATION
# HELP backup_status Статус бэкапа (0 - успех)
# TYPE backup_status gauge
backup_status $STATUS
EOF
```

### Thanos Ruler для мульти-кластера

```yaml
thanosRuler:
  enabled: true
  replicas: 2
  thanosRulerSpec:
    ruleSelector:
      matchLabels:
        thanos-ruler: "true"
    alertmanagersConfig:
      secret:
        name: alertmanager-main-db # Секрет с конфигом Alertmanager
        key: alertmanager.yaml
```

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Компонент | Параметр | Значение (базовое) | Метрика |
| :--- | :--- | :--- | :--- |
| configmapReload | `requests.memory` | `16Mi` | `container_memory_usage_bytes` |
| configmapReload | `requests.cpu` | `10m` | `rate(container_cpu_usage_seconds_total)` |
| pushgateway | `requests.memory` | `64Mi` | `container_memory_usage_bytes` |
| pushgateway | `retention` | `15d` | Размер PVC |

### Связанные темы

* [Prometheus Operator — архитектура](../operator/concepts.md)
* [Конфигурация Alertmanager](./alertmanager_config.md)
* [Thanos — общее описание](../../scaling/thanos_overview.md)
* [Экспортеры — настройка](./exporters_config.md)
