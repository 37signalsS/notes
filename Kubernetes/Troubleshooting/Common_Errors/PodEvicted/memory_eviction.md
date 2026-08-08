# Pod Evicted: Выселение по памяти (Memory Eviction)

## Определения

**MemoryPressure Eviction** — защитный механизм `kubelet`, который принудительно завершает поды при критической нехватке оперативной памяти на узле. В отличие от системного OOM Killer, выселение является предиктивным: `kubelet` убивает поды до того, как память закончится полностью, чтобы сохранить стабильность системных компонентов.

**Состояние узла MemoryPressure** — флаг в `status.conditions`, который переходит в `True`, когда доступная память узла падает ниже заданных порогов выселения.

**Рабочий набор (Working Set Size, WSS)** — основная метрика памяти, используемая Kubernetes для принятия решения о выселении. Включает в себя резидентную память (RSS) и активный дисковый кэш.

Общие определения и типы выселения: **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Расчет доступной памяти в kubelet

Kubelet не использует метрику `free` из вывода команды `free -h`. Вместо этого он рассчитывает доступную память на основе данных из `cgroups`.

**Формула расчета доступной памяти:**
`memory.available = node.capacity - node.workingSet`

**Что входит в Working Set (WSS):**
1.  **RSS (Resident Set Size):** Анонимная память процесса (стек, куча).
2.  **Cache (Page Cache):** Данные файлов, прочитанные с диска.
3.  **Минус Inactive File:** Часть дискового кэша, которую ядро Linux помечает как "неактивную" и может мгновенно переиспользовать без ущерба для производительности.

**Почему это важно:** Если приложение активно работает с файлами (например, база данных или лог-агрегатор), его `workingSet` будет расти за счет кэша. Если ядро не успевает вовремя сбрасывать неактивные страницы, `kubelet` может инициировать выселение, даже если анонимной памяти (RSS) достаточно.

### Пороги выселения (Thresholds)

Настройки задаются в `KubeletConfiguration` (`/var/lib/kubelet/config.yaml`):

| Параметр | Тип | Описание | Типичное значение |
|:---|:---|:---|:---|
| `evictionHard.memory.available` | Hard | Немедленное выселение (SIGKILL) | `100Mi` или `5%` |
| `evictionSoft.memory.available` | Soft | Выселение после grace period (SIGTERM) | `500Mi` |
| `evictionSoftGracePeriod` | Time | Время удержания порога до начала выселения | `2m` |

**Рекомендация для больших узлов:** На узлах с 128ГБ+ RAM порог в 5% (6.4ГБ) может быть избыточным. Используйте абсолютные значения (например, `2Gi`).

### Влияние Swap на выселение

Исторически Kubernetes требовал отключения Swap. Начиная с версии 1.22 (alpha) и 1.28 (beta), поддержка Swap стала доступна.
*   **Swap отключен:** При нехватке памяти `kubelet` сразу переходит к выселению или срабатывает OOM Killer.
*   **Swap включен:** Система может выгружать неактивные страницы на диск. Это дает "запас времени", но `kubelet` все равно будет ориентироваться на `memory.available`. Если Swap заполнен, риск жесткого OOM Killer возрастает.

### Taints и планирование

При переходе узла в состояние `MemoryPressure=True` на него автоматически накладывается taint:
`node.kubernetes.io/memory-pressure:NoSchedule`
Это запрещает планировщику (`kube-scheduler`) назначать новые поды на этот узел, пока ситуация не стабилизируется.

## Практические сценарии

### 1. Диагностика через kubectl

Если под выселен с причиной `Evicted`, проверьте сообщение в его статусе:

```bash
kubectl describe pod <pod-name>
# Результат: Message: The node was low on resource: memory. 
# Container app was using 1500Mi, which is over its request of 1Gi.
```

Проверьте состояние узла:
```bash
kubectl get nodes -o custom-columns="NAME:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=='MemoryPressure')].status"
```

### 2. Глубокий анализ на узле (SSH)

Если `kubectl top` не дает полной картины (метрики усреднены), используйте инструменты узла.

**Проверка через crictl (runtime):**
```bash
crictl stats
# Показывает MEM (WSS) для каждого контейнера в реальном времени
```

**Анализ oom_score_adj:**
Kubernetes выставляет приоритеты выживания процессов через `oom_score_adj`.
*   **Guaranteed:** `-997` (выживают почти всегда).
*   **BestEffort:** `1000` (убиваются первыми).
Детали: **[QoS и выселение](./qos_and_eviction.md)**.

**Просмотр Working Set конкретного контейнера (cgroup v2):**
```bash
# Путь может варьироваться от дистрибутива
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod<UID>.slice/memory.current
# И детализация кэша
cat /sys/fs/cgroup/.../memory.stat | grep -E "inactive_file|active_file"
```

### 3. Решение проблемы

#### Краткосрочные меры
1.  **Очистка завершенных подов:** `kubectl delete pods --field-selector status.reason=Evicted -A`.
2.  **Ручной сброс кэша ОС (Опасно!):** `echo 3 > /proc/sys/vm/drop_caches`. Поможет только если `Inactive File` аномально велик, но вызовет всплеск Disk I/O.

#### Долгосрочные меры
1.  **Настройка Resource Reserved:** Всегда резервируйте память для системы и `kubelet`.
    ```yaml
    kubeReserved:
      memory: "1Gi"
    systemReserved:
      memory: "500Mi"
    ```
2.  **Переход на Guaranteed QoS:** Для критических нагрузок выставляйте `requests == limits`.
3.  **Использование Descheduler:** Установите `Descheduler` для автоматического переноса подов с перегруженных узлов до срабатывания критических порогов.

## Дополнительная информация

### Различия между MemoryPressure и OOMKilled

| Характеристика | MemoryPressure (Eviction) | OOMKilled |
|:---|:---|:---|
| **Инициатор** | `kubelet` (превентивно) | Ядро Linux (вынужденно) |
| **Сигнал** | SIGTERM/SIGKILL | SIGKILL |
| **Логика** | Предиктивная (запас на узле) | Реактивная (лимит контейнера превышен) |
| **Статус** | `Reason: Evicted` | `Reason: OOMKilled` |
| **Уровень** | Весь под целиком | Конкретный контейнер |

Подробный разбор OOM: **[OOMKilled в Kubernetes](../oomkilled_pods.md)**.

### Смотрите также

- **[QoS и выселение](./qos_and_eviction.md)** — влияние классов на приоритеты.
- **[Диагностика выселения](./diagnostics.md)** — общий алгоритм поиска.
- **[Профилактика выселения](./prevention.md)** — как избежать MemoryPressure.
- **[Метрики памяти процесса](../../../../Linux/Core/memory/process_memory_metrics.md)** — RSS, WSS, PSS.
