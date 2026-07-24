# Профилактика выселения подов (Pod Evicted)

## Определения

**Профилактика выселения (Eviction Prevention)** — комплекс архитектурных и конфигурационных мер, направленных на обеспечение стабильности подов и предотвращение их принудительного завершения компонентом kubelet при дефиците ресурсов узла.

**Цели профилактики:**

1. Исключение состояний давления на ресурсы (MemoryPressure, DiskPressure, PIDPressure).
2. Обеспечение доступности критических сервисов при плановом обслуживании узлов.
3. Своевременное реагирование на деградацию инфраструктуры через автоматизацию и мониторинг.

## Основные концепции

### Уровни защиты от выселения

| Уровень | Механизм защиты | Тип угрозы |
|:---|:---|:---|
| **Приоритезация** | `PriorityClass` | Выселение менее важных подов вместо критических |
| **Ресурсы (QoS)** | `requests` == `limits` (Guaranteed) | Дефицит памяти/CPU на узле |
| **Хранилище** | Лимиты `ephemeral-storage` | DiskPressure (переполнение диска) |
| **Доступность** | `PodDisruptionBudget` (PDB) | Массовый `kubectl drain` или `eviction` |
| **Узел** | `kubeReserved` + пороги выселения | Краш системных компонентов (System Starvation) |
| **Кластер** | Cluster Autoscaler / Karpenter | Исчерпание общей емкости кластера |

### Приоритеты подов (PriorityClass)

`PriorityClass` позволяет явно указать планировщику и kubelet, какие поды являются наиболее важными. При нехватке ресурсов поды с низким приоритетом будут выселены (preempted) первыми для освобождения места под высокоприоритетные задачи.

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: critical-service
value: 1000000
globalDefault: false
description: "Для критически важных сервисов кластера"
```

> Подробнее: **[Приоритеты подов (PriorityClass)](../../../Concepts/priorityclass.md)**.

### Классы QoS как фундамент стабильности

QoS (Quality of Service) напрямую определяет порядок выселения при дефиците памяти.

1. **Guaranteed (requests == limits)** — выселяются в последнюю очередь.
2. **Burstable (requests < limits)** — выселяются, если их потребление превышает `requests`.
3. **BestEffort (нет лимитов)** — первые кандидаты на удаление.

> Детали: **[QoS и выселение](./qos_and_eviction.md)**, **[Requests и Limits в Kubernetes](../../../Scheduling/qos_limit_and_requests.md)**.

## Практические сценарии

### 1. Настройка Guaranteed QoS для критичных приложений

Для защиты от `MemoryPressure` необходимо выровнять запросы и лимиты для ВСЕХ контейнеров в поде.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: stable-app
spec:
  containers:
  - name: app
    image: my-app:v1
    resources:
      requests:
        memory: "1Gi"
        cpu: "1"
      limits:
        memory: "1Gi"    # Guaranteed QoS
        cpu: "1"         # Guaranteed QoS
```

### 2. Ограничение эфемерного хранилища

Для предотвращения `DiskPressure` из-за разросшихся логов или томов `emptyDir` используйте лимиты хранилища.

```yaml
resources:
  requests:
    ephemeral-storage: "1Gi"
  limits:
    ephemeral-storage: "2Gi" # Под будет выселен сразу при превышении этого порога
```

> Подробнее о выселении по диску: **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**.

### 3. Использование Pod Disruption Budget (PDB)

PDB гарантирует, что определенное количество подов останется в сети при выполнении `kubectl drain` или выселении по порогам.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: app-pdb
spec:
  minAvailable: 80%              # Минимум 80% подов должны быть Ready
  selector:
    matchLabels:
      app: my-app
```

> **Важно:** PDB не защищает от "жестких" сбоев узла, только от добровольных прерываний. Детали: **[Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md)**.

### 4. Настройка алертов в Prometheus

Для проактивного реагирования необходимо настроить уведомления до того, как kubelet начнет убивать поды.

```yaml
# Пример алертов для Prometheus
- alert: KubernetesNodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} сообщает о нехватке памяти (MemoryPressure)"

- alert: KubernetesNodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Узел {{ $labels.node }} переполнен (DiskPressure). Ожидается выселение подов."

- alert: HighEvictionRate
  expr: rate(kube_pod_status_reason{reason="Evicted"}[15m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Массовое выселение подов в кластере"
```

### 5. Очистка и мониторинг завершенных подов

Выселенные поды занимают место в API и могут мешать анализу статусов.

```bash
# Просмотр всех выселенных подов в кластере
kubectl get pods -A --field-selector status.reason=Evicted
# → NAMESPACE  NAME      READY  STATUS   RESTARTS  AGE
# → default    my-pod-1  0/1    Evicted  0         2h

# Массовое удаление всех выселенных подов
kubectl delete pods --field-selector status.reason=Evicted -A
# → pod "my-pod-1" deleted (чистка завершена)
```

## Дополнительная информация

### Резюме лучших практик

| Практика | Описание |
|:---|:---|
| **Всегда указывайте requests** | Планировщик не сможет корректно распределить нагрузку без запросов. |
| **PriorityClass для критических сервисов** | DNS, Ingress, CNI должны иметь более высокий приоритет, чем приложения. |
| **kubeReserved** | Обязательно резервируйте 10-20% ресурсов узла под системные нужды. |
| **Вертикальное масштабирование (VPA)** | Помогает автоматически выставить корректные лимиты на основе истории. |

### Смотрите также

- **[Подробный разбор QoS и выселения](./qos_and_eviction.md)**
- **[Выселение по памяти (Memory Eviction)](./memory_eviction.md)**
- **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**
- **[Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md)**
- **[Приоритеты подов (PriorityClass)](../../../Concepts/priorityclass.md)**
