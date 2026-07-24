# Pod Evicted: Выселение по памяти

## Определения

**Выселение при давлении на память (MemoryPressure Eviction)** — принудительное завершение подов компонентом kubelet для защиты стабильности узла при критическом исчерпании оперативной памяти. В отличие от OOMKilled, выселение является предиктивным механизмом: kubelet убивает поды до того, как ядро Linux начнет хаотично завершать процессы.

**Состояние узла MemoryPressure** — флаг, который устанавливается в `True`, когда доступная память узла падает ниже заданных порогов.
# → Message: The node was low on resource: memory.

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Расчет доступной памяти в kubelet

Kubelet принимает решение о выселении на основе показателя **Working Set** (рабочий набор). Это не просто занятая память, а объем, который реально необходим приложению для работы прямо сейчас.

**Формула расчета:**
`Доступная память = Общий объем - (working_set всех подов + системные процессы)`

**Что входит в Working Set:**
- **RSS (Resident Set Size)** — страницы в физической памяти.
- **Cache (Page Cache)** — кэш файлов.
- **Минус Inactive File** — часть кэша, которую ядро может безболезненно сбросить (reclaimable).

> **Нюанс:** Если приложение активно использует `mmap` или дисковый кэш, его Working Set будет расти, что может привести к выселению, даже если RSS невелик.

### Пороги выселения (Thresholds)

Настройки задаются в конфигурации kubelet (`/var/lib/kubelet/config.yaml`):

| Параметр | Описание | Типичное значение |
|:---|:---|:---|
| `evictionHard.memory.available` | Мгновенное выселение (SIGKILL) | `100Mi` или `5%` |
| `evictionSoft.memory.available` | Выселение после ожидания (SIGTERM) | `500Mi` |
| `evictionSoftGracePeriod` | Сколько времени порог может быть превышен | `2m` |

### Приоритет выселения и QoS

Kubelet выбирает "жертву" на основе класса качества обслуживания (QoS) и того, насколько под превысил свои запросы (`requests`):

1. **BestEffort**: Выселяются первыми. У них нет гарантированной памяти.
2. **Burstable**: Выселяются, если их потребление выше `requests`.
3. **Guaranteed**: Выселяются последними, только когда на узле не осталось других кандидатов.

Kubelet настраивает `oom_score_adj` для процессов, чтобы ядро Linux при возникновении OOM (Out Of Memory) следовало этой же логике.

## Практические сценарии

### Диагностика

#### Шаг 1: Проверка состояния узла

```bash
kubectl describe node <node-name> | grep -A 5 "Conditions:"
# → Type             Status  Reason
# → MemoryPressure   True    KubeletHasInsufficientMemory
```

#### Шаг 2: Анализ на уровне операционной системы

Необходимо понять, куда уходит память на самом узле (требуется SSH):

```bash
# Общий статус памяти
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           31Gi        28Gi       1.2Gi       1.0Gi       2.1Gi       1.8Gi

# Топ процессов по памяти
ps aux --sort=-%mem | head -10
# → USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
# → root      1234  5.0 12.5 4500000 4000000 ?     Ssl  10:00   5:00 java -jar app.jar

# Статистика контейнеров через CRI
crictl stats
# → CONTAINER           CPU %    MEM       DISK      INODES
# → app-container       2.50     4.2Gi     10Mi      5
```

#### Шаг 3: Выявление подов-нарушителей

```bash
# Текущее потребление через Metrics Server
kubectl top pod -A --sort-by=memory | head -10
# → NAMESPACE     NAME             CPU(cores)   MEMORY(bytes)
# → prod          java-api-789     150m         4100Mi

# Поиск подов без лимитов (BestEffort)
kubectl get pods -A -o jsonpath='{range .items[?(@.spec.containers[*].resources.limits.memory=="")]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}'
```

### Решение проблемы

#### 1. Оперативные меры (Short-term)

- **Очистка кэша ОС:** `sync && echo 3 > /proc/sys/vm/drop_caches` (поможет временно, если много Inactive File).
- **Удаление выселенных подов:** `kubectl delete pods --field-selector status.reason=Evicted -A`.
- **Рестарт kubelet:** В редких случаях помогает при утечках памяти в самом рантайме.

#### 2. Долгосрочные меры (Best Practices)

- **Настройка Reserveds:** Установите `kube-reserved` и `system-reserved`, чтобы kubelet знал, сколько памяти оставить для ОС и самого себя.
  ```yaml
  # Пример параметров kubelet
  kubeReserved:
    memory: "1Gi"
  systemReserved:
    memory: "500Mi"
  ```
- **Лимиты и запросы:** Все критические поды должны быть в классе **Guaranteed** (`requests == limits`).
- **VPA (Vertical Pod Autoscaler):** Автоматическая подстройка ресурсов на основе реального потребления.

## Дополнительная информация

### Различия между MemoryPressure и OOMKilled

| Признак | MemoryPressure (Eviction) | OOMKilled |
|:---|:---|:---|
| **Кто убил** | Kubelet (превентивно) | Kernel OOM Killer (вынужденно) |
| **Сигнал** | SIGTERM (Soft) / SIGKILL (Hard) | SIGKILL (всегда) |
| **Причина** | Узел почти пуст | Контейнер съел больше своего лимита |
| **Статус** | `Evicted` | `OOMKilled` |

### Смотрите также

- **[Разбор ошибки OOMKilled](../oomkilled_pods.md)** — когда память кончается внутри лимита контейнера.
- **[Диагностика выселения](./diagnostics.md)** — общий алгоритм поиска причин.
- **[QoS и выселение](./qos_and_eviction.md)** — детальное описание очередей на вылет.
- **[Node Resource Pressure](../NodeUnavailability/resource_pressure.md)** — проблемы на уровне железа.
