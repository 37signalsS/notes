# Мониторинг master-нод (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** сбор метрик с master/control-plane нод Kubernetes через kube-prometheus-stack.
> **Смежные темы:** [Taints and Tolerations](../../../../Kubernetes/Scheduling/taints_and_tolerations.md) — теория ограничений размещения; [Конфигурация экспортеров](../exporters_config.md) — общие параметры Node Exporter; [Конфигурация прочих компонентов](../other_components_config.md) — RBAC, defaultRules, kubelet.

## Определения

**Master-ноды (Control Plane)** — узлы Kubernetes, на которых работают компоненты управляющей плоскости: `kube-apiserver`, `etcd`, `kube-controller-manager`, `kube-scheduler`. По умолчанию имеют `taint` (запрет) `node-role.kubernetes.io/control-plane:NoSchedule`, препятствующий размещению обычных рабочих нагрузок.

**Taint (Запрет)** — механизм Kubernetes, ограничивающий размещение подов на узле. DaemonSet Node Exporter по умолчанию не имеет исключений (tolerations) для master-нод и не запускается на них.

**Toleration (Допуск)** — разрешение поду работать на узле с определённым запретом. Для сбора метрик со всех узлов кластера (включая управляющие) Node Exporter должен запускаться с соответствующим допуском.

**DaemonSet** — контроллер Kubernetes, гарантирующий запуск ровно одного экземпляра пода на каждом узле кластера (или на выбранной подмножестве). Node Exporter развёртывается именно как DaemonSet.

**Static Pod** — под, управляемый напрямую kubelet'ом на узле, без involvement планировщика. Компоненты Control Plane (apiserver, etcd, scheduler, controller-manager) по умолчанию запускаются как Static Pods в namespace `kube-system`.

**PodMonitor** — Custom Resource Definition (CRD) Prometheus Operator, описывающая способ скрейпинга пода по его лейблам. В kube-prometheus-stack используется для Node Exporter вместо ServiceMonitor.

**ServiceMonitor** — CRD Prometheus Operator, описывающая способ скрейпинга сервиса Kubernetes. Используется для компонентов Control Plane (kubelet, kube-proxy, API Server).

**hostNetwork / hostPID / hostRootfsMount** — параметры безопасности DaemonSet Node Exporter, позволяющие использовать сеть, PID namespace и корневую ФС хоста для доступа к системным метрикам.

## Основные концепции

### Причины отсутствия метрик по умолчанию

Стандартная конфигурация Helm-чарта ориентирована на безопасность и экономию ресурсов, поэтому Node Exporter запускается только на worker-нодах:

```
kube-prometheus-stack (values.yaml)
  └── nodeExporter
        └── DaemonSet (без tolerations для control-plane)
              ├── Запускается на worker-нодах: OK
              └── НЕ запускается на master-нодах: Пропуск (taint NoSchedule)
```

Без явной настройки в `values.yaml` метрики уровня ОС (CPU, RAM, диски) для master-нод не будут поступать в Prometheus.

### Разделение метрик хоста и компонентов Control Plane

Критически важно разделять сбор данных о «железе» (ОС) и сбор данных о работе сервисов Kubernetes:

| Тип | Что мониторится | Механизм | Метрики |
|:---|:---|:---|:---|
| **Метрики хоста** | CPU, RAM, диски, сеть узла | Node Exporter (DaemonSet + Tolerations) | `node_*` |
| **Метрики Control Plane** | Состояние API Server, etcd, scheduler | ServiceMonitor (встроены в чарт) | `apiserver_*`, `etcd_*` |

Данный документ фокусируется на обеспечении работы **Node Exporter** на master-нодах.

### Архитектура сбора метрик с master-нод

```
master-1 (control-plane)
  ├── Static Pods: kube-apiserver, etcd, controller-manager, scheduler
  ├── DaemonSet: prometheus-node-exporter (требует tolerations)
  │     ├── hostNetwork: true
  │     ├── hostPID: true
  │     └── hostPath: /proc, /sys, /rootfs
  └── Port 9100 (Node Exporter metrics)
       ↓
Prometheus Operator (ServiceDiscovery)
       ↓
Prometheus Server (scrape & TSDB)
```

**Важные нюансы:**
- DaemonSet Controller автоматически добавляет tolerations для `node.kubernetes.io/unreachable` и `node.kubernetes.io/not-ready`, но **не** для `node-role.kubernetes.io/control-plane` — последний нужно указывать явно.
- Компоненты Control Plane по умолчанию слушают `127.0.0.1`. Для сбора их метрик через ServiceMonitor необходимо изменить на `0.0.0.0` в манифестах `/etc/kubernetes/manifests/`.

> **Подробнее о компонентах:** [Конфигурация прочих компонентов](../other_components_config.md), [Конфигурация экспортеров](../exporters_config.md).

## Практические сценарии

### Сценарий 1: Включение Node Exporter на master-нодах (Production-стандарт)

**Задача:** Обеспечить сбор системных метрик со всех узлов кластера, включая управляющие.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - operator: "Exists"
      effect: "NoSchedule"
  # Рекомендуемые ресурсы для Node Exporter в Prod
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi
```

**Результат:**
- `operator: "Exists"` обеспечивает допуск к любому запрету с эффектом `NoSchedule` (универсальный способ для master-нод и специализированных групп узлов).
- Node Exporter запускается на всех доступных узлах.

### Сценарий 2: Строгая толерантность только для Control Plane

**Задача:** Разрешить запуск только на управляющих узлах, не затрагивая другие узлы с пользовательскими taints (например, GPU-узлы).

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
```

### Сценарий 3: Обеспечение совместимости с устаревшими версиями Kubernetes

**Задача:** Поддержка кластеров (Kubernetes < 1.24), где использовался лейбл `node-role.kubernetes.io/master`.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
    - key: "node-role.kubernetes.io/master"
      operator: "Exists"
      effect: "NoSchedule"
```

### Сценарий 4: Настройка сетевых политик для мониторинга master-нод

В кластерах с жесткими правилами сетевой изоляции необходимо разрешить трафик от подов Prometheus к порту 9100 на master-нодах.

```yaml
# values.yaml
prometheus:
  networkPolicy:
    enabled: true
# Дополнительно убедитесь, что Firewall на самих нодах разрешает 9100/tcp
```

### Сценарий 5: Проверка и валидация сбора метрик

После применения конфигурации (`helm upgrade`) выполните проверку:

```bash
# 1. Проверка запуска подов на master-нодах
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -o wide | grep master

# 2. Проверка статуса Target в Prometheus
# Порт-форвард к Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# Перейдите в Status -> Targets, найдите job="node-exporter"
```

**Запрос в Prometheus (PromQL):**
```promql
# Проверка наличия метрик CPU для master-нод
node_cpu_seconds_total{instance=~"master.*|control-plane.*"}
```

### Сценарий 6: Кастомные лимиты ресурсов для master-нод

**Задача:** Установить увеличенные лимиты ресурсов для Node Exporter на master-нодах, где конкуренция за CPU/RAM выше из-за работы Control Plane.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
  resources:
    requests:
      cpu: 150m
      memory: 192Mi
    limits:
      cpu: 300m
      memory: 384Mi
```

**Валидация:**
```bash
# Проверка ресурсов пода Node Exporter на master-ноде
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -o wide | grep master
kubectl top pod -n monitoring <pod-name> --containers
# → node-exporter  100m   80Mi  (в пределах лимитов)
```

### Сценарий 7: Фильтрация метрик через metricRelabelings

**Задача:** Убрать лишние высококардинальные метрики с master-нод, чтобы снизить нагрузку на TSDB.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
  podMonitor:
    metricRelabelings:
      - sourceLabels: [__name__]
        regex: 'node_network_(transmit|receive)_bytes_total'
        action: drop
      - sourceLabels: [__name__]
        regex: 'node_disk_(read|write)_time_seconds_total'
        action: drop
```

**Запрос в Prometheus (PromQL):**
```promql
# Проверка, что метрики удалены
count by(__name__)(node_network_transmit_bytes_total{instance=~"master.*"})
# → 0 (или пустой результат)
```

### Сценарий 8: Отдельный DaemonSet для master-нод с кастомными коллекторами

**Задача:** Запустить отдельный DaemonSet Node Exporter на master-нодах с дополнительными коллекторами (systemd, ntp), не затрагивая worker-ноды.

```yaml
# values.yaml
nodeExporter:
  enabled: true
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
  extraArgs:
    - --collector.systemd
    - --collector.ntp
    - --no-collector.wifi
```

**Валидация:**
```bash
# Проверка доступных коллекторов
kubectl exec -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -c node-exporter -- \
  wget -qO- http://localhost:9100/metrics | grep "# HELP" | head -20

# Проверка метрик systemd
node_systemd_unit_state{instance=~"master.*", name="kubelet.service", state="active"}
```

### Сценарий 9: Проверка доступности порта 9100 через Blackbox Exporter

**Задача:** Настроить активную проверку доступности Node Exporter на master-нодах через Blackbox Exporter.

```yaml
# values.yaml
prometheus-blackbox-exporter:
  enabled: true
  config:
    modules:
      http_2xx:
        prober: http
        timeout: 5s

# Probe CRD
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: node-exporter-master
  namespace: monitoring
spec:
  module: http_2xx
  prober:
    url: prometheus-blackbox-exporter.monitoring.svc:9115
  targets:
    staticConfig:
      static:
        - http://master-1:9100/metrics
        - http://master-2:9100/metrics
        - http://master-3:9100/metrics
```

### Сценарий 10: Апгрейд и откат конфигурации

**Задача:** Безопасно обновить конфигурацию Node Exporter на master-нодах с возможностью отката.

```bash
# 1. Создание резервной копии текущих значений
helm get values monitoring -n monitoring > values-backup.yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values-backup.yaml \
  -f values.yaml

# 3. Проверка rollout DaemonSet
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m

# 4. Проверка новых targets в Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# → http://localhost:9090/targets
```

**При проблемах — откат:**
```bash
helm rollback monitoring -n monitoring
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m
```

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
|:---|:|:---|
| Pod Node Exporter в статусе `Pending` | Отсутствует допуск (toleration) | Проверьте секцию `nodeExporter.tolerations` в `values.yaml`. |
| Ошибка `FailedScheduling` | Несоответствие `nodeSelector` или `affinity` | Проверьте, не заданы ли в чарте ограничивающие правила размещения. |
| Метрики хоста есть, но компоненты DOWN | Компоненты (etcd, scheduler) слушают 127.0.0.1 | Измените `--address=0.0.0.0` в манифестах `/etc/kubernetes/manifests/`. |
| Target в статусе UNKNOWN/DOWN | Сетевая недоступность порта 9100 | Проверьте firewall на master-нодах и NetworkPolicy. |
| Pod Node Exporter CrashLoopBackOff | Конфликт `hostNetwork` или `hostPID` | Проверьте SecurityContext DaemonSet и наличие конфликующих сервисов на порту 9100. |
| Метрики master-нод отсутствуют в Grafana | Неправильный `job` или `instance` в запросе | Проверьте labels в дашборде: `job="node-exporter"`, `instance=~"master.*"`. |
| Высокое потребление CPU Node Exporter | Слишком частый скрейпинг | Увеличьте `scrape_interval` до 30s в PodMonitor. |
| Дашборд пустой для master-нод | Метрики еще не накопились | Подождите 5-10 минут после применения конфигурации (retention + aggregation). |

### Диагностика

```bash
# Получение списка taints на master-ноде
kubectl get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.taints}{"\n"}{end}'

# Проверка tolerations у конкретного пода Node Exporter
kubectl get pod -n monitoring <pod-name> -o jsonpath='{.spec.tolerations}'

# Проверка events DaemonSet на master-нодах
kubectl get events -n monitoring --field-selector reason=FailedScheduling,involvedObject.name=<pod-name>

# Проверка, что порт 9100 открыт на master-ноде
kubectl debug node/master-1 -n default --image=busybox -- sh -c "nc -zv master-1 9100"

# Проверка метрик kubelet на master-ноде
kubectl get --raw /api/v1/nodes/master-1/proxy/metrics/cadvisor | head -20

# Проверка, что Static Pods Control Plane слушают на 0.0.0.0
kubectl get pods -n kube-system -o wide | grep -E "kube-apiserver|etcd|kube-controller-manager|kube-scheduler"
kubectl describe node master-1 | grep -A 5 "Addresses"
```

### Рекомендации (Best Practices)

1. **Используйте `operator: "Exists"`** — это наиболее надежный способ в динамических средах, где ключи taints могут меняться.
2. **Лимиты ресурсов** — Node Exporter на master-нодах не должен конкурировать за ресурсы с API Server. Всегда задавайте `requests` и `limits`.
3. **Мониторинг kubelet** — для сбора метрик давления на ресурсы и состояния контейнеров на master-нодах убедитесь, что kubelet экспонирует метрики (порт 10250). Это не заменяет метрики хоста от Node Exporter.
4. **Безопасность** — используйте `hostNetwork: true` для Node Exporter, чтобы он имел доступ к сетевым метрикам самого узла.
5. **Фильтрация метрик** — при большом количестве master-нод (>5) используйте `metricRelabelings` для удаления лишних сетевых и дисковых метрик.
6. **Сетевая изоляция** — при включенном NetworkPolicy явно разрешите трафик от Prometheus к порту 9100 на master-нодах.
7. **Версионирование** — храните `values.yaml` в Git. Используйте `helm diff upgrade` для просмотра изменений перед применением.
8. **Совместимость** — для смешанных кластеров (K8s <1.24 и >=1.24) указывайте оба toleration: `control-plane` и `master`.
9. **Разделение метрик** — не смешивайте метрики хоста (`node_*`) и метрики Control Plane (`apiserver_*`, `etcd_*`). Используйте разные дашборды и алерты.
10. **Проверка перед изменением** — всегда проверяйте rollout DaemonSet и статус targets в Prometheus UI после `helm upgrade`.

### Граничные случаи (Edge Cases)

1. **Смешанные роли узлов:** В некоторых дистрибутивах (k0s, k3s) master-ноды могут не иметь стандартного taint `control-plane`. Проверяйте taints через `kubectl describe node`.
2. **hostNetwork конфликты:** Если на master-ноде уже работает сервис на порту 9100, Node Exporter не запустится. Освободите порт 9100 на узле или используйте отдельный DaemonSet с изменённым портом.
3. **Кластеры без master-нод:** В управляемых сервисах (EKS, GKE, AKS) master-ноды скрыты. Данный сценарий применим только к self-hosted кластерам.
4. **Статические поды и listen-адреса:** Компоненты Control Plane слушают `127.0.0.1` по умолчанию. Prometheus Operator не может собрать их метрики через ServiceMonitor без изменения на `0.0.0.0`.
5. **Высокое давление на master-ноды:** При интенсивной нагрузке на API Server Node Exporter может быть вытеснен (OOMKilled). Увеличивайте `limits.memory` и используйте PriorityClass.
6. **Обновление kubelet:** При обновлении kubelet DaemonSet Node Exporter может быть перезапущен. Убедитесь, что у него есть `terminationGracePeriodSeconds`.
7. **NetworkPolicy и hostNetwork:** При `hostNetwork: true` стандартные NetworkPolicy не работают. Используйте `iptables` или `nftables` на самих узлах.
8. **Ротация сертификатов etcd:** При автоматической ротации сертификатов Control Plane метрики могут временно исчезнуть. Настройте `metricRelabelings` с `action: keep` для критичных метрик.
9. **Несколько namespaces мониторинга:** Если Prometheus Operator ограничен `namespaceSelector`, убедитесь, что PodMonitor Node Exporter попадает в выбранный namespace.
10. **Снижение кардинальности:** При >50 master-нод в кластере (например, гиперконвергентные инфраструктуры) агрегируйте метрики через PrometheusRule, чтобы не перегружать TSDB.

### Очистка и откат

```bash
# Откат к предыдущей конфигурации
helm rollback monitoring -n monitoring

# Удаление только tolerations (возврат к worker-only)
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set nodeExporter.tolerations="[]"

# Полное удаление DaemonSet Node Exporter
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set nodeExporter.enabled=false
```

### Полезные команды для диагностики

```bash
# Rollout status DaemonSet
kubectl rollout status daemonset/prometheus-node-exporter -n monitoring --timeout=5m

# Список подов Node Exporter с указанием узла
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -o wide

# Проверка labels и tolerations пода
kubectl get pod -n monitoring <pod-name> -o jsonpath='{.spec}{"\n"}{.spec.tolerations}{"\n"}'

# Логи Node Exporter
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -c node-exporter --tail=100

# Проверка PodMonitor Node Exporter
kubectl get podmonitor -n monitoring prometheus-node-exporter -o yaml

# Проверка ServiceMonitor для Control Plane компонентов
kubectl get servicemonitor -n monitoring
```

### Связанные компоненты

| Компонент | Зона ответственности | Механизм |
|:---|:---|:---|
| **Node Exporter** | Железо и ОС master-ноды | DaemonSet |
| **Kubelet** | Состояние подов на master-ноде | ServiceMonitor (порт 10250) |
| **Kube Proxy** | Сетевые правила (iptables/ipvs) | ServiceMonitor (порт 10249) |
| **Static Pods** | Компоненты Control Plane | ServiceMonitor (через эндпоинты) |

> **См. также:** [Конфигурация etcd](../etcd-monitoring.md), [Конфигурация экспортеров](../exporters_config.md).
