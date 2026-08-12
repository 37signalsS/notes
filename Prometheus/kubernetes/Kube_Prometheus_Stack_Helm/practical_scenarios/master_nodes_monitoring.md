# Мониторинг master-нод (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** сбор метрик с master/control-plane нод Kubernetes через kube-prometheus-stack.  
> **Смежные темы:** [Taints and Tolerations](../../../../Kubernetes/Scheduling/taints_and_tolerations.md) — теория ограничений размещения; [Конфигурация экспортеров](../exporters_config.md) — общие параметры Node Exporter.

## Определения

**Master-ноды (Control Plane)** — узлы Kubernetes, на которых работают компоненты управляющей плоскости: `kube-apiserver`, `etcd`, `kube-controller-manager`, `kube-scheduler`. По умолчанию имеют `taint` (запрет) `node-role.kubernetes.io/control-plane:NoSchedule`, препятствующий размещению обычных рабочих нагрузок.

**Taint (Запрет)** — механизм Kubernetes, ограничивающий размещение подов на узле. DaemonSet Node Exporter по умолчанию не имеет исключений (tolerations) для master-нод и не запускается на них.

**Toleration (Допуск)** — разрешение поду работать на узле с определённым запретом. Для сбора метрик со всех узлов кластера (включая управляющие) Node Exporter должен запускаться с соответствующим допуском.

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

> **Подробнее о компонентах:** [Конфигурация прочих компонентов](../other_components_config.md).

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

## Дополнительная информация

### Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
|:---|:---|:---|
| Pod Node Exporter в статусе `Pending` | Отсутствует допуск (toleration) | Проверьте секцию `nodeExporter.tolerations` в `values.yaml`. |
| Ошибка `FailedScheduling` | Несоответствие `nodeSelector` или `affinity` | Проверьте, не заданы ли в чарте ограничивающие правила размещения. |
| Метрики хоста есть, но компоненты DOWN | Компоненты (etcd, scheduler) слушают 127.0.0.1 | Измените `--address=0.0.0.0` в манифестах `/etc/kubernetes/manifests/`. |
| Target в статусе UNKNOWN/DOWN | Сетевая недоступность порта 9100 | Проверьте Security Groups (облако) или iptables (on-prem). |

### Диагностика

```bash
# Получение списка taints на master-ноде
kubectl get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.taints}{"\n"}{end}'

# Проверка tolerations у конкретного пода Node Exporter
kubectl get pod -n monitoring <pod-name> -o jsonpath='{.spec.tolerations}'
```

### Рекомендации (Best Practices)

1. **Используйте `operator: "Exists"`** — это наиболее надежный способ в динамических средах, где ключи taints могут меняться.
2. **Лимиты ресурсов** — Node Exporter на master-нодах не должен конкурировать за ресурсы с API Server. Всегда задавайте `requests` и `limits`.
3. **Мониторинг kubelet** — убедитесь, что `kubelet.enabled: true`. Это даст данные о состоянии контейнеров на master-нодах (не путать с метриками хоста).
4. **Безопасность** — используйте `hostNetwork: true` для Node Exporter, чтобы он имел доступ к сетевым метрикам самого узла.

### Связанные компоненты

| Компонент | Зона ответственности | Механизм |
|:---|:---|:---|
| **Node Exporter** | Железо и ОС master-ноды | DaemonSet |
| **Kubelet** | Состояние подов на master-ноде | ServiceMonitor (порт 10250) |
| **Kube Proxy** | Сетевые правила (iptables/ipvs) | ServiceMonitor (порт 10249) |
| **Static Pods** | Компоненты Control Plane | ServiceMonitor (через эндпоинты) |

> **См. также:** [Конфигурация etcd](./etcd-monitoring.md), [Конфигурация экспортеров](../exporters_config.md).
