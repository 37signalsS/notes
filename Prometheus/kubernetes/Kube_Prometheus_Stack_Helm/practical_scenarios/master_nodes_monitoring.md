# Master Nodes Monitoring (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** сбор метрик с master/control-plane нод Kubernetes через kube-prometheus-stack.  
> **Смежные темы:** [Taints and Tolerations](../../../../Kubernetes/Scheduling/taints_and_tolerations.md) — теория taints/tolerations; [Конфигурация экспортеров](../exporters_config.md) — общие параметры Node Exporter.

## Definitions

**Master-ноды (Control Plane)** — узлы Kubernetes, на которых работают компоненты управляющей плоскости: `kube-apiserver`, `etcd`, `kube-controller-manager`, `kube-scheduler`. По умолчанию имеют `taint` `node-role.kubernetes.io/control-plane:NoSchedule`, запрещающий размещение рабочих подов.

**Taint** — механизм Kubernetes, ограничивающий размещение подов на узле. DaemonSet Node Exporter по умолчанию **не** имеет tolerations для master-нод и не запускается на них.

**Toleration** — разрешение поду работать на узле с определённым taint. Для сбора метрик со **всех** нод кластера (включая master) Node Exporter должен запускаться как DaemonSet с соответствующим toleration.

## Basic Concepts

### Почему master-ноды не мониторятся по умолчанию

```
kube-prometheus-stack (values.yaml по умолчанию)
  └── nodeExporter
        └── DaemonSet (без tolerations для control-plane)
              ├── Запускается на worker-нодах ✓
              └── НЕ запускается на master-нодах ✗ (taint NoSchedule)
```

Без явного указания tolerations Node Exporter собирает метрики только с worker-нод. Метрики master-нод (CPU, память, диски, сеть) **отсутствуют** в Prometheus.

### Контрольная плоскость vs метрики хоста

Важно различать два типа мониторинга master-нод:

| Тип | Что мониторится | Механизм | Метрики |
|---|---|---|---|
| **Метрики хоста** | CPU, память, диски, сеть узла | Node Exporter DaemonSet с tolerations | `node_*` |
| **Метрики Control Plane** | API Server, etcd, scheduler, controller-manager | ServiceMonitor (встроены в kube-prometheus-stack) | `apiserver_*`, `etcd_*`, `scheduler_*` |

kube-prometheus-stack **уже** собирает метрики Control Plane через встроенные ServiceMonitor'ы. Данный файл покрывает только **метрики хоста** master-нод через Node Exporter.

> **См. также:** [Мониторинг Control Plane (API Server, etcd)](../other_components_config.md).

## Practical Scenarios

### Сценарий 1: Включение Node Exporter на master-нодах

**Задача:** Собирать метрики хоста (CPU, память, диски) со всех нод кластера, включая master.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - operator: "Exists"
      effect: "NoSchedule"
```

**Что происходит:**

- `operator: "Exists"` — toleration срабатывает для **любого** taint с эффектом `NoSchedule` (включая `control-plane`, `master`, и любые пользовательские).
- DaemonSet Node Exporter запускается на **всех** нодах: и worker, и master.
- Метрики `node_*` появляются в Prometheus для master-нод.

**Применение:**

```bash
# Обновление через Helm
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f values.yaml

# Проверка: Node Exporter должен работать на master-нодах
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter -o wide

# Проверка targets: все master-ноды должны быть в статусе UP
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
# Открыть http://localhost:9090/targets
```

### Сценарий 2: Толерантность только к control-plane taint (строго)

**Задача:** Запускать Node Exporter только на control-plane нодах, игнорируя пользовательские taints.

```yaml
# values.yaml
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
```

**Когда использовать:** Если нужно явно ограничить scope только control-plane taint'ом, не затрагивая другие `NoSchedule` taints (например, `PreferNoSchedule` для GPU-нод).

### Сценарий 3: Verbose tolerations (совместимость со старыми версиями)

**Задача:** Поддержка кластеров с устаревшим taint `node-role.kubernetes.io/master` (Kubernetes < 1.24).

```yaml
# values.yaml — совместимость с Kubernetes 1.20–1.23
nodeExporter:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
    - key: "node-role.kubernetes.io/master"
      operator: "Exists"
      effect: "NoSchedule"
```

> **Примечание:** В Kubernetes 1.24+ taint `master` удалён; достаточно только `control-plane`.

### Сценарий 4: Проверка метрик master-нод через PromQL

**Задача:** Убедиться, что метрики с master-нод собираются.

```promql
# Все master-ноды с их метриками CPU
node_cpu_seconds_total{job="node-exporter", instance=~"master.*"}

# Сравнение worker vs master нод по памяти
node_memory_MemTotal_bytes{job="node-exporter"}
  / on(instance) group_left(label_node_role)
  node_meta_node_role{role="master"}

# Метрики etcd (control-plane компоненты, собираются через ServiceMonitor)
etcd_server_has_leader
```

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Node Exporter pod на master-ноде в статусе `Pending` | Нет tolerations для `NoSchedule` | Добавить tolerations в `values.yaml` |
| Pod в `Pending` с событием `FailedScheduling` | Nodeselector/affinity не совпадают | Проверить `nodeExporter.affinity` и `nodeSelector` |
| Target DOWN в Prometheus | Firewall блокирует порт Node Exporter | Открыть порт `9100/tcp` между pod Prometheus и master-нодой |
| Метрики `node_*` есть, но `apiserver_*` нет | ServiceMonitor API Server отключён | Проверить `kubeApiServer.enabled: true` в `values.yaml` |

### Диагностика

```bash
# Проверить, работает ли Node Exporter на master-ноде
kubectl get pods -n monitoring \
  -l app.kubernetes.io/name=prometheus-node-exporter \
  -o wide | grep master

# Проверить tolerations пода Node Exporter
kubectl get pod -n monitoring <node-exporter-pod-name> -o jsonpath='{.spec.tolerations}'

# Проверить taint master-ноды
kubectl get node <master-node-name> -o jsonpath='{.spec.taints}'

# Проверить, собираются ли метрики
kubectl exec -it -n monitoring $(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[0].metadata.name}') -- \
  wget -qO- http://<master-node-ip>:9100/metrics | head -5
```

### Best Practices

1. **`operator: "Exists"` для production** — покрывает все текущие и будущие `NoSchedule` taints без явного перечисления ключей.
2. **Мониторинг Control Plane ≠ мониторинг хоста** — ServiceMonitor'ы для API Server/etcd работают независимо от Node Exporter tolerations.
3. **Не отключайте Node Exporter на master** — метрики хоста (`node_cpu`, `node_memory`) критичны для диагностики проблем Control Plane.
4. **DaemonSet автоматически масштабируется** — при добавлении новых master-нод в кластер Node Exporter запустится на них автоматически (при наличии tolerations).

### Связанные компоненты kube-prometheus-stack

| Компонент | Мониторит | Механизм | Включён по умолчанию |
|---|---|---|---|
| **Node Exporter** | Метрики хоста (все ноды) | DaemonSet + ServiceMonitor | Да (только worker) |
| **kubeApiServer** | API Server метрики | ServiceMonitor | Да |
| **kubeControllerManager** | Controller Manager | ServiceMonitor | Да |
| **kubeScheduler** | Scheduler метрики | ServiceMonitor | Да |
| **kubeEtcd** | etcd метрики | ServiceMonitor/Endpoint | Да |

> **См. также:** [Мониторинг Control Plane](../other_components_config.md), [Конфигурация экспортеров](../exporters_config.md).
