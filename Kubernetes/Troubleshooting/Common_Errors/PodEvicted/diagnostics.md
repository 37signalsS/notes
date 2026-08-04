# Pod Evicted: Диагностика и поиск первопричин

## Определения

**Диагностика выселения (Eviction Diagnostics)** — процесс выявления факторов, приведших к принудительному завершению пода, через анализ состояний узла, системных событий и метрик потребления ресурсов.

**Основные артефакты для анализа:**
- **`status.reason: Evicted`** — основной признак в манифесте пода.
- **`status.message`** — текстовое пояснение (например, какой ресурс был в дефиците).
- **Node Conditions** — флаги узла (`MemoryPressure`, `DiskPressure`), указывающие на глобальный дефицит ресурсов.

Общие понятия и типы выселения описаны в файле **[Pod Evicted: Определения](./definitions.md)**.

## Основные концепции

### Источники диагностических данных

| Источник | Назначение | Основной инструмент |
|:---|:---|:---|
| **Манифест пода** | Первичная причина и сообщение от kubelet | `kubectl describe pod` |
| **События (Events)** | Хронология срабатывания порогов | `kubectl get events` |
| **Состояние узла** | Определение типа давления (Pressure) | `kubectl describe node` |
| **Рантайм (CRI)** | Состояние контейнеров на уровне ОС | `crictl stats`, `crictl ps` |
| **Системные логи** | Ошибки ядра и рантайма (OOM, Disk errors) | `journalctl`, `dmesg` |

### Алгоритм поиска неисправности

При возникновении постоянного выселения подов (Pod Eviction) важно следовать методическому подходу, так как простой перезапуск пода или проверка логов приложения часто не решают корень проблемы (нехватку ресурсов).

1.  **Идентификация:** Найти поды со статусом `Evicted`.
2.  **Анализ сообщения:** Извлечь тип ресурса из `status.message`.
3.  **Локализация (Нагрузка на узел):** Проверить использование ресурсов узла с помощью `kubectl describe node <node-name>` или через Prometheus/Grafana, чтобы подтвердить перенапряжение ресурсов (CPU/Memory Pressure).
4.  **Проверка лимитов Pod:** Изучить `requests` и `limits` выселенного пода. Если под запрашивает слишком много ресурсов или узел переподписан (overcommitted), может потребоваться корректировка лимитов или перенос пода на менее загруженный узел.
5.  **Системные квоты и условия:** Проверить лимиты `ResourceQuota` в namespace и общие условия узла (DiskPressure, MemoryPressure).
6.  **Масштабирование:** Если проблема носит системный характер, рассмотреть использование **Cluster Autoscaler** или **Karpenter** для автоматического добавления узлов при нехватке ресурсов.

## Практические сценарии

### 1. Первичный анализ через kubectl

Первым делом необходимо получить список всех выселенных подов и причину их завершения.

```bash
# Поиск всех выселенных подов в кластере
kubectl get pods -A --field-selector status.reason=Evicted
# → NAMESPACE  NAME      READY  STATUS   RESTARTS  AGE
# → default    nginx-app  0/1    Evicted  0         1h

# Получение подробного сообщения о причине
kubectl get pod <pod-name> -o jsonpath='{.status.message}'
# → The node was low on resource: memory. Container nginx was using 1024Ki...
```

**Интерпретация сообщений:**
- `low on resource: memory` → См. **[Выселение по памяти](./memory_eviction.md)**.
- `low on resource: ephemeral-storage` → См. **[Выселение по диску](./disk_eviction.md)**.
- `evicted by user request` (или аналогичное при drain) → См. **[Бюджет прерывания подов (PDB)](../../../Autoscaling/pod_disruption_budget.md)**.

### 2. Анализ состояния инфраструктуры узла

Если под выселен по ресурсам, узел должен находиться в состоянии **Pressure**.

```bash
# Проверка состояний узла
kubectl describe node <node-name> | grep -A 5 "Conditions:"
# → MemoryPressure   False   ...
# → DiskPressure     True    KubeletHasDiskPressure
# → PIDPressure      False   ...
```

Если все флаги `False`, но выселение произошло, возможно, имел место кратковременный всплеск потребления, который уже купирован выселением пода. Проверьте **Events**.

### 3. Хронология событий (Events)

События позволяют увидеть, как kubelet принимал решение.

```bash
# Получение событий выселения, отсортированных по времени
kubectl get events -A --field-selector reason=Evicted --sort-by='.lastTimestamp'
# → 5m   Warning   Evicted   pod/db-app   The node was low on resource: memory.
```

### 4. Низкоуровневая диагностика на узле

Если у вас есть SSH-доступ к узлу, используйте `crictl` для проверки реальной нагрузки, которую видит рантайм.

```bash
# Статистика контейнеров по памяти и CPU
crictl stats
# → CONTAINER  CPU %  MEM     DISK  INODES
# → db-container  0.50   1.2Gi   100Mi 10

# Проверка логов ядра на предмет OOM Killer (может работать параллельно с Eviction)
dmesg -T | grep -i "out of memory"
```

### 5. Анализ распределения выселений по кластеру

Используйте `jq` для понимания масштаба проблемы на разных узлах.

```bash
# Группировка выселенных подов по узлам
kubectl get pods -A --field-selector status.reason=Evicted -o json | \
  jq -r '.items[] | .spec.nodeName' | sort | uniq -c | sort -nr
# → 15 node-worker-1  (критическая нагрузка на узле)
# → 2  node-worker-2
```

## Устранение последствий

### Очистка выселенных подов

Выселенные поды остаются в API-сервере до ручного удаления. Это может мешать мониторингу и работе CI/CD.

```bash
# Удаление всех выселенных подов во всем кластере
kubectl delete pods --field-selector status.reason=Evicted -A
# → pod "nginx-app" deleted
```

## Дополнительная информация

### Сводная таблица действий

| Ситуация | Основной шаг диагностики | Файл-руководство |
|:---|:---|:---|
| **MemoryPressure** | `kubectl top node` + `dmesg` | **[Выселение по памяти](./memory_eviction.md)** |
| **DiskPressure** | `df -h` + `du -sh` на узле | **[Выселение по диску](./disk_eviction.md)** |
| **API Eviction** | Проверка PDB и `kubectl drain` | **[PDB и Taint Eviction](./pdb_and_taint_eviction.md)** |
| **PIDPressure** | `sysctl kernel.pid_max` | **[Node Resource Pressure](../NodeUnavailability/resource_pressure.md)** |

### Смотрите также

- **[Pod Evicted: Определения](./definitions.md)** — база по типам выселений.
- **[Профилактика выселения](./prevention.md)** — как не допустить повторения.
- **[QoS и выселение](./qos_and_eviction.md)** — влияние лимитов на выбор жертвы.
