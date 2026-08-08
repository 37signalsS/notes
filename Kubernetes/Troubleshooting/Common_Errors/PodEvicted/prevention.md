# Профилактика выселения подов (Pod Evicted)

## Определения

**Профилактика выселения (Eviction Prevention)** — комплекс архитектурных и конфигурационных мер, направленных на обеспечение стабильности подов и предотвращение их принудительного завершения компонентом `kubelet` при дефиците ресурсов узла.

**Цели профилактики:**
1. **Исключение resource starvation:** Предотвращение состояний `MemoryPressure`, `DiskPressure` и `PIDPressure`.
2. **Гарантия доступности:** Обеспечение работы критических сервисов даже при плановом обслуживании или частичной деградации узлов.
3. **Автоматизация управления:** Переход от ручного исправления последствий к автоматическому масштабированию и перераспределению ресурсов.

## Основные концепции

### Уровни защиты от выселения

| Уровень | Механизм защиты | Тип угрозы |
|:---|:---|:---|
| **Приоритезация** | `PriorityClass` | Вытеснение менее важных подов вместо критических |
| **Ресурсы (QoS)** | `requests` == `limits` (Guaranteed) | Дефицит памяти/CPU на узле |
| **Хранилище** | Лимиты `ephemeral-storage` | `DiskPressure` (переполнение разделов) |
| **Доступность** | `PodDisruptionBudget` (PDB) | Массовый `kubectl drain` или API-выселение |
| **Конфигурация узла** | `kubeReserved` + `systemReserved` | Краш системных компонентов (System Starvation) |
| **Балансировка** | `Descheduler` | Перекосы нагрузки между узлами |
| **Кластер** | Cluster Autoscaler / Karpenter | Исчерпание общей емкости кластера |

### Конфигурация Kubelet: Пороги выселения

`kubelet` инициирует выселение подов на основе заданных порогов. Правильная настройка этих параметров позволяет создать "буфер безопасности".

*   **Hard Eviction (`--eviction-hard`)**: Немедленное выселение подов при достижении порога. По умолчанию: `memory.available<100Mi`, `nodefs.available<10%`.
*   **Soft Eviction (`--eviction-soft`)**: Выселение начинается только если порог превышен в течение заданного времени (`--eviction-soft-grace-period`). Позволяет игнорировать кратковременные всплески нагрузки.

Пример конфигурации `/var/lib/kubelet/config.yaml`:
```yaml
evictionHard:
  memory.available: "500Mi"
  nodefs.available: "10%"
  nodefs.inodesFree: "5%"
  pid.available: "10%"
evictionSoft:
  memory.available: "1Gi"
evictionSoftGracePeriod:
  memory.available: "2m"
```

### Node Allocatable: Резервирование ресурсов

Для защиты самого `kubelet` и системных демонов (sshd, systemd, docker) необходимо резервировать ресурсы, которые **не будут** доступны подам.

**Формула:**
`[Allocatable] = [Capacity] - [kube-reserved] - [system-reserved] - [eviction-threshold]`

*   **`kube-reserved`**: Для компонентов K8s (`kubelet`, `container runtime`).
*   **`system-reserved`**: Для ОС (`kernel`, `systemd`).
*   **`eviction-threshold`**: Запас для срабатывания порогов выселения.

> Подробнее: **[Kubelet — агент Kubernetes на узле](../../../Concepts/kubelet.md)**.

### Классы QoS и PriorityClass

*   **QoS (Quality of Service)**: Определяет очередность выселения при дефиците памяти. Поды `Guaranteed` имеют наивысшую выживаемость.
*   **PriorityClass**: Позволяет планировщику вытеснять менее важные поды при нехватке места для высокоприоритетных.

> Детали: **[QoS и выселение](./qos_and_eviction.md)**, **[Приоритеты подов (PriorityClass)](../../../Concepts/priorityclass.md)**.

## Практические сценарии

### 1. Настройка Guaranteed QoS для критичных приложений

Для предотвращения `MemoryPressure` необходимо выровнять `requests` и `limits` для всех контейнеров в поде. Это гарантирует, что `kubelet` не выберет этот под как кандидата на выселение, пока есть поды других классов.

```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "2Gi"
    cpu: "1000m"
```

### 2. Изоляция и лимиты эфемерного хранилища

Для защиты от `DiskPressure` используйте два подхода:
1.  **Лимиты в манифестах**: Ограничивайте `ephemeral-storage` для `emptyDir` и логов.
2.  **Разделение дисков**: Рекомендуется выносить `/var/lib/kubelet` (основная ФС) и `/var/lib/docker` или `/var/lib/containerd` (ФС образов) на разные физические диски или логические разделы.

```yaml
resources:
  limits:
    ephemeral-storage: "2Gi" # Под выселяется при превышении
```

> Подробнее: **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**.

### 3. Защита доступности через PDB

`PodDisruptionBudget` предотвращает массовое выселение подов одного сервиса при операциях обслуживания (например, обновлении узлов).

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: my-service
```

> **Важно:** PDB игнорируется при `Hard Eviction`, если узел находится в критическом состоянии. Детали: **[Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md)**.

### 4. Проактивное перераспределение (Descheduler)

`Descheduler` помогает избежать выселений, обнаруживая узлы с избыточной нагрузкой и аккуратно перенося поды на более свободные узлы **до** того, как сработают пороги `kubelet`.

**Полезные стратегии:**
*   `RemoveDuplicates`: Убирает лишние реплики с одного узла.
*   `LowNodeUtilization`: Переносит поды с перегруженных узлов на недогруженные.
*   `RemovePodsViolatingInterPodAntiAffinity`: Исправляет нарушения правил анти-аффинити.

### 5. Автоматизация лимитов (VPA)

Часто выселения происходят из-за некорректно настроенных `requests/limits`. `Vertical Pod Autoscaler` (VPA) в режиме `Auto` или `Initial` помогает автоматически выставлять значения на основе реального потребления.

> Подробнее: **[VPA: Вертикальное масштабирование подов](../../../Autoscaling/vpa_detailed.md)**.

## Дополнительная информация

### Мониторинг и алертинг

Настраивайте алерты в Prometheus с упреждением (до достижения Hard thresholds).

```yaml
# Предупреждение о росте использования памяти на узле
- alert: NodeMemoryUsageApproachingEviction
  expr: (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 15
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Узел {{ $labels.node }} близок к MemoryPressure (свободно < 15%)"
```

### Очистка завершенных подов

Выселенные поды остаются в API в статусе `Failed` (Reason: `Evicted`). Это полезно для диагностики, но замусоривает вывод.

```bash
# Удаление выселенных подов старше 24 часов (пример через custom-columns)
kubectl get pods -A | grep Evicted | awk '{print $1 " " $2}' | xargs -L1 kubectl delete pod -n
```

### Резюме лучших практик

| Практика | Описание | Приоритет |
|:---|:---|:---|
| **Requests == Limits** | Используйте для всех production-нагрузок (Guaranteed QoS). | Critical |
| **PriorityClass** | Разделяйте системные (high) и пользовательские (low) приоритеты. | High |
| **Kube-reserved** | Всегда настраивайте резервирование ресурсов на уровне Kubelet. | High |
| **Логирование** | Используйте внешние системы сбора логов (Loki, ELK), чтобы не забивать диск узла. | Medium |

### Смотрите также
- **[Подробный разбор QoS и выселения](./qos_and_eviction.md)**
- **[Выселение по памяти (Memory Eviction)](./memory_eviction.md)**
- **[Выселение по диску (Disk Eviction)](./disk_eviction.md)**
- **[Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md)**
- **[VPA: Вертикальное масштабирование подов](../../../Autoscaling/vpa_detailed.md)**
- **[Kubelet: Основные концепции](../../../Concepts/kubelet.md)**
