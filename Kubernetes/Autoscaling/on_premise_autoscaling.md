# Autoscaling в On-Premise / Bare-Metal средах

## Определения

**On-Premise (on-prem)** — модель развёртывания инфраструктуры на собственных серверах организации, без использования облачных провайдеров. Включает bare-metal (физические серверы) и виртуализированные среды (VMware, KVM).

**Cluster API (CAPI)** — фреймворк Kubernetes для управления жизненным циклом кластеров. В on-premise средах используется через провайдеры: Metal3 (bare-metal), vSphere (VMware), KubeVirt (виртуализация).

**Metal3** — реализация Cluster API для bare-metal серверов. Использует Ironic ( setOpenStack Ironic) для управления физическими серверами через PXE/IPMI/Redfish.

**Volcano** — планировщик для пакетных (batch) и HPC-нагрузок в Kubernetes. Подходит для on-premise сред, где нет облачных скейлеров.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| Kubernetes | 1.27 | 1.31+ | Стабильный Cluster API |
| Cluster Autoscaler | 1.27+ | 1.31+ | С `cluster-api` expander |
| Cluster API | v1.5+ | v1.7+ | Для on-premise |
| Metal3 | v1.5+ | v1.7+ | Для bare-metal |
| Ironic | 21.0+ | 23.0+ | Управление физическими серверами |

---

## Теоретический блок

### Отличия on-premise autoscaling от cloud

| Фактор | Cloud (AWS/Azure) | On-Premise |
|--------|-------------------|------------|
| **Источник узлов** | EC2, Spot, Reserved | Физические серверы, VM |
| **Скорость добавления** | 45–90 сек (Karpenter) | 5–30 минут (PXE boot) |
| **Стоимость** | Pay-per-use | Capital expense (железо) |
| **Гибкость типов** | Динамический выбор | Фиксированные конфигурации |
| **Управление** | API провайдера | Ironic, MAAS, vSphere API |
| **Сеть** | VPC, Subnets | VLAN, BGP, MetalLB |

### Архитектура on-premise autoscaling

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ HPA/KEDA    │  │ Cluster      │  │ Cluster API      │  │
│  │ (Workload)  │→ │ Autoscaler   │→ │ Controller       │  │
│  └─────────────┘  └──────────────┘  └──────────────────┘  │
│                                               │             │
└───────────────────────────────────────────────┼─────────────┘
                                                │
                                    ┌───────────▼───────────┐
                                    │   Metal3 / vSphere    │
                                    │   (Ironic / CAPI)     │
                                    └───────────┬───────────┘
                                                │
                                    ┌───────────▼───────────┐
                                    │   Physical Servers    │
                                    │   (PXE / IPMI)        │
                                    └───────────────────────┘
```

### Варианты autoscaling для on-premise

| Решение | Уровень | Поддержка on-prem | Скорость | Сложность |
|---------|---------|-------------------|----------|-----------|
| **Cluster Autoscaler + CAPI** | Нода | Да | 5–15 мин | Высокая |
| **Cluster Autoscaler + Metal3** | Нода | Bare-metal | 10–30 мин | Очень высокая |
| **Volcano** | Workload (batch) | Да | Быстро (планирование) | Средняя |
| **Descheduler** | Workload (rebalance) | Да | Быстро (eviction) | Низкая |
| **Ручное масштабирование** | Нода | Да | Немедленно | Низкая |

### Cluster Autoscaler + Cluster API

```yaml
# CA с CAPI expander
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: cluster-autoscaler
          image: registry.k8s.io/autoscaling/cluster-autoscaler:v1.31.0
          command:
            - ./cluster-autoscaler
            - --cloud-provider=clusterapi
            - --v=4
            - --expander=clusterapi
            - --balance-similar-node-groups
            - --scale-down-delay-after-add=10m
            - --scale-down-unneeded-time=15m
            - --max-node-provision-time=20m
```

### Metal3 + Ironic

```yaml
# BareMetalHost для Metal3
apiVersion: metal3.io/v1alpha1
kind: BareMetalHost
metadata:
  name: worker-01
  namespace: metal3-system
spec:
  online: true
  bootMACAddress: 00:11:22:33:44:55
  bootMethod: pxelinux
  image:
    url: http://image-server/ubuntu-22.04-server-cloudimg-amd64.img
    checksum: ""
  bmc:
    address: ipmi://192.168.1.100
    credentialsName: worker-01-bmc-credentials
  consumerRef:
    name: worker-01
    namespace: metal3-system
  automation:
    poweredOn: true
    reboot: true
```

### Volcano для batch-нагрузок

```yaml
# Volcano Queue для batch-задач
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: batch-queue
spec:
  weight: 1
  reclaimable: true
  deserved: 4
---
# Volcano Job
apiVersion: batch.volcano.sh/v1beta1
kind: Job
metadata:
  name: ml-training
spec:
  queue: batch-queue
  minAvailable: 3
  schedulerName: volcano
  policies:
    - event: PodEvicted
      action: RestartJob
  plugins:
    single: []
    priority: []
  tasks:
    - replicas: 5
      name: worker
      template:
        spec:
          containers:
            - name: worker
              image: my-ml-worker:latest
              resources:
                requests:
                  cpu: "4"
                  memory: 8Gi
                limits:
                  cpu: "4"
                  memory: 8Gi
```

---

## Практический блок

### Установка CA с CAPI

```bash
# 1. Установите Cluster API
clusterctl init --infrastructure metal3

# 2. Проверьте CAPI компоненты
kubectl get pods -n capi-system
kubectl get pods -n capm3-system

# 3. Установите CA с CAPI expander
helm install cluster-autoscaler autoscaler/cluster-autoscaler \
  --namespace kube-system \
  --set autoDiscovery.clusterName=my-cluster \
  --set cloudProvider=clusterapi \
  --set expander=clusterapi \
  --set "rbac.clusterRole.name=cluster-autoscaler"
```

### Настройка Metal3

```bash
# 1. Установите Metal3
kubectl apply -f https://github.com/metal3-io/metal3/releases/latest/download/metal3-release.yaml

# 2. Создайте BareMetalHost
kubectl apply -f baremetalhost.yaml

# 3. Проверьте статус
kubectl get baremetalhost -n metal3-system
# → NAME        STATUS       PROVISIONING STATE   DESIRED STATE   HOST
# → worker-01   available    none                 empty           192.168.1.100

# 4. Присоедините узел к кластеру
kubectl annotate baremetalhost worker-01 -n metal3-system \
  metal3.io/cluster-api-cluster="my-cluster" \
  metal3.io/cluster-api-worker-group="workers"
```

### Мониторинг on-premise autoscaling

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: onprem-autoscaling-alerts
spec:
  groups:
    - name: onprem.rules
      rules:
        - alert: BareMetalHostProvisioningTimeout
          expr: |
            time() - metal3_baremetalhost_provisioning_started_timestamp > 1800
            and
            metal3_baremetalhost_provisioning_state != "provisioned"
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "BareMetalHost {{ $labels.baremetalhost }}: provisioning >30 минут"
            description: |
              PXE boot или Ironic не может provision узел.
              Проверьте сеть, Ironic, DHCP.

        - alert: CAOnPremNoCapacity
          expr: |
            increase(cluster_autoscaler_failed_scale_ups_total[10m]) > 0
            and
            cluster_autoscaler_cloud_provider == "clusterapi"
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "CA не может добавить узлы (on-prem)"
            description: |
              Cluster Autoscaler не может provision новые узлы.
              Проверьте Metal3/Ironic, доступность физических серверов.
```

---

## Дополнительная информация

### Ограничения on-premise autoscaling

1. **Скорость:** PXE boot и provisioning занимают 5–30 минут (vs 45–90 сек в cloud)
2. **Фиксированные ресурсы:** Нельзя динамически изменять тип сервера
3. **Стоимость:** Капитальные затраты на железо, нет pay-per-use
4. **Сеть:** Требуется настройка PXE/DHCP/TFTP
5. **Отказоустойчивость:** Запасные серверы должны быть готовы заранее

### Best Practices

1. **Over-provisioning:** Держите 2–3 запасных сервера для быстрого provisioning
2. **PXE boot:** Настройте быстрый PXE boot с SSD или NFS
3. **MetalLB:** Используйте MetalLB для LoadBalancer сервисов
4. **Descheduler:** Добавьте Descheduler для ребалансировки после provisioning
5. **Volcano:** Используйте для batch-нагрузок (ML, ETL) вместо CA

### См. также

- [Cluster Autoscaler: Глубокое погружение](cluster_autoscaler_detailed.md) — полная документация CA
- [Karpenter vs CA](cluster_autoscaler_vs_karpenter.md) — сравнение решений
- [Descheduler](descheduler.md) — ребалансировка кластера
- [Overview: On-Premise specifics](overview_concepts.md#предварительные-требования-технический-чек-лист) — требования к on-premise
- [MetalLB](../Networking/metallb.md) — LoadBalancer для bare-metal
- [Kubespray](../Installation/Kubespray/overview.md) — установка Kubernetes на bare-metal
