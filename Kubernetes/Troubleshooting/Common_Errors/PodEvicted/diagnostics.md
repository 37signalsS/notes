# Pod Evicted: Диагностика

## Определения

**Диагностика выселения (eviction)** — процесс выявления первопричины удаления пода с узла через анализ статуса объекта, состояния ресурсов узла, системных событий и метрик потребления.

Основные термины и типы выселения описаны в файле **[Pod Evicted: Определения](./definitions.md)**.

**Ключевые признаки (артефакты):**

- **`Reason: Evicted`** — основное поле в статусе пода, указывающее на факт выселения.
- **`Message`** — детальное пояснение причины (например, нехватка памяти или дискового пространства).
- **Node Conditions** — состояния узла (`MemoryPressure`, `DiskPressure`, `PIDPressure`), сигнализирующие о критическом дефиците ресурсов.

## Основные концепции

### Источники диагностических данных

| Источник | Назначение | Команда |
|----------|---------------|---------|
| **Статус пода** | Определение первичной причины | `kubectl describe pod <pod_name>` |
| **Состояние узла** | Проверка давления на ресурсы | `kubectl describe node <node_name>` |
| **События (Events)** | Хронология процесса выселения | `kubectl get events --field-selector reason=Eviction` |
| **Метрики** | Оценка текущего потребления | `kubectl top node`, `kubectl top pod` |
| **Логи узла** | Детали на уровне OS (Operating System — операционная система) | `dmesg`, `journalctl`, `df -h` |

### Алгоритм поиска неисправности

1. **Анализ пода:** получение сообщения об ошибке из описания пода.
2. **Анализ узла:** проверка наличия флагов Pressure (давление) на узле.
3. **Анализ событий:** восстановление последовательности действий Eviction Manager (Менеджера выселения).
4. **Углубленный анализ:** проверка ресурсов RAM (Random Access Memory — оперативная память), диска или PID (Process ID — идентификатор процесса) на узле.

## Практические сценарии

### 1. Первичный анализ статуса пода

Необходимо получить подробную информацию о завершенном поде:

```bash
kubectl describe pod <pod_name>
# → Reason: Evicted
# → Message: The node was low on resource: memory.
```

**Интерпретация поля Message:**

| Сообщение | Вероятная причина | Дальнейшие действия |
|-----------|-------------------|---------------------|
| `low on resource: memory` | `MemoryPressure` | Анализ потребления RAM на узле |
| `low on resource: ephemeral-storage` | `DiskPressure` | Проверка объема логов и временных файлов |
| `evicted by user request` | Drain (вывод узла) | См. **[Maintenance Eviction](../NodeUnavailability/maintenance.md)** |
| `Marking for deletion Pod` | Taint `NoExecute` | См. **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)** |

### 2. Проверка состояния узла

Если под выселен из-за нехватки ресурсов, это отразится в условиях (Conditions) узла:

```bash
kubectl describe node <node_name> | grep -A 5 "Conditions:"
# → MemoryPressure   False
# → DiskPressure     True
# → PIDPressure      False
```

### 3. Анализ конкретных ресурсов

#### А. Оперативная память (RAM)

При возникновении `MemoryPressure` необходимо выявить наиболее ресурсоемкие поды:

```bash
# Проверка потребления узлом
kubectl top node <node_name>

# Сортировка подов по использованию памяти
kubectl top pod --all-namespaces --sort-by=memory | head -10

# Поиск OOM (Out of Memory — нехватка памяти) в системном журнале (через SSH — Secure Shell)
ssh <node_name> "dmesg -T | grep -i 'oom' | tail -5"
```

Подробная диагностика памяти: **[Memory Eviction](./memory_eviction.md)**.

#### Б. Дисковое пространство

Для `DiskPressure` важно определить, что занимает место в разделе `/var/lib/kubelet`:

```bash
# Проверка свободного места
ssh <node_name> "df -h /var/lib/kubelet"

# Поиск самых объемных директорий подов
ssh <node_name> "du -sh /var/lib/kubelet/pods/* | sort -rh | head -10"
```

Подробная диагностика диска: **[Disk Eviction](./disk_eviction.md)**.

### 4. Хронология событий (Events)

События позволяют восстановить последовательность принятия решения о выселении:

```bash
kubectl get events --field-selector reason=Eviction --sort-by='.lastTimestamp'
# → 2m15s   Warning   Evicted   pod/nginx-6799fc88d8-7sq9h   The node was low on resource: memory.
```

### 5. Очистка выселенных подов

Выселенные поды не удаляются автоматически и могут накапливаться в системе.

```bash
# Удаление всех выселенных подов в конкретном namespace
kubectl delete pods --field-selector status.reason=Evicted -n <namespace>
# → pod "nginx-6799fc88d8-7sq9h" deleted

# Удаление всех выселенных подов во всем кластере
kubectl delete pods --field-selector status.reason=Evicted --all-namespaces
```

## Дополнительная информация

### Полезные команды для быстрой проверки

| Задача | Команда |
|--------|---------|
| **Все выселенные поды** | `kubectl get pods -A --field-selector status.reason=Evicted` |
| **Количество выселений по узлам** | `kubectl get pods -A --field-selector status.reason=Evicted -o json \| jq '.items[].spec.nodeName' \| sort \| uniq -c` |
| **Узлы в состоянии Pressure** | `kubectl get nodes -o jsonpath='{range .items[?(@.status.conditions[?(@.status=="True")])].metadata.name}{"\n"}{end}'` |

### Смотрите также

- [Pod Evicted: Определения](./definitions.md) — типы выселения и классы QoS.
- [Профилактика выселения](./prevention.md) — настройка мониторинга и алертов.
- [Node Resource Pressure](../NodeUnavailability/resource_pressure.md) — диагностика на уровне узла.
