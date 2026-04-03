# Pod Evicted: QoS и Eviction Manager

## Definitions

**Eviction Manager** — компонент kubelet, который мониторит ресурсы узла и принимает решения о выселении подов при достижении eviction thresholds.

**QoS-класс** — категория пода, определяющая приоритет при выселении. Присваивается при создании пода на основе `requests` и `limits`.

**Working set memory** — RSS + unevictable cache, используемая Eviction Manager для принятия решений, а не общее потребление памяти.

## Basic Concepts

### QoS и порядок выселения

При активации Eviction Manager поды выселяются в строгом порядке:

```
MemoryPressure / DiskPressure
    ↓
1. BestEffort — по working set (больше потребляет → первый)
    ↓
2. Burstable — по % превышения requests (больше超额 → первый)
    ↓
3. Guaranteed — только если 1 и 2 не освободили ресурсы
```

| QoS Класс | Условия | Приоритет вытеснения | Ограничение OOM |
|-----------|---------|---------------------|-----------------|
| **`BestEffort`** | Нет `requests`/`limits` | **Первые** | Нет защиты |
| **`Burstable`** | `requests` < `limits` | **Вторые** | OOMKill при `limits.memory` |
| **`Guaranteed`** | `requests` == `limits` | **Последние** | OOMKill при `limits.memory` |

> Полное описание QoS: [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md)

### Как Eviction Manager ранжирует поды внутри QoS

**BestEffort:**
```
Сортировка: working set memory (по убыванию)
→ Под с наибольшим потреблением → первый на eviction
```

**Burstable:**
```
Сортировка: (current_usage - requests) / (limits - requests)  (по убыванию)
→ Под с наибольшим превышением requests → первый на eviction
```

**Guaranteed:**
```
Выселяются только если BestEffort + Burstable не освободили достаточно ресурсов
→ Сортировка по working set (как BestEffort)
```

### Workflow Eviction Manager

```
kubelet проверяет ресурсы каждые 10s
    ↓
Доступная память/disk < evictionHard threshold
    ↓
Eviction Manager активируется
    ↓
1. Сортировка подов по QoS + потреблению
2. Graceful termination самого «дорогого» пода
3. Ожидание освобождения ресурсов
4. Повторная проверка
    ↓
Ресурсы освобождены → Stop
Или
Все поды класса выселены → следующий QoS класс
```

### Grace period при eviction

| Параметр | Описание | Значение по умолчанию |
|----------|----------|----------------------|
| `evictionMaxPodGracePeriod` | Максимальный grace period для выселяемых подов | 120s |
| `terminationGracePeriodSeconds` | Grace period пода (из spec) | 30s |
| **Итоговый grace** | `min(pod.grace, evictionMaxPodGracePeriod)` | min(30s, 120s) = 30s |

## Practical Scenarios

### Диагностика QoS-класса пода

```bash
# Проверка QoS-класса
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'

# Все поды с BestEffort (кандидаты на eviction)
kubectl get pods --all-namespaces -o json | jq '.items[] | select(.status.qosClass=="BestEffort") | {name: .metadata.name, ns: .metadata.namespace}'

# Распределение подов по QoS в кластере
kubectl get pods --all-namespaces -o json | jq '[.items[].status.qosClass] | group_by(.) | map({class: .[0], count: length})'
```

### Анализ: почему под был выселен

**Шаг 1: Проверка QoS-класса**

```bash
kubectl describe pod <evicted-pod>
# В разделе Events:
# Reason: Evicted
# Message: The node was low on resource: memory.
```

**Шаг 2: Проверка, был ли под BestEffort**

```bash
kubectl get pod <evicted-pod> -o jsonpath='{.spec.containers[*].resources}'
# Пустой вывод → BestEffort → первый кандидат на eviction
```

**Шаг 3: Проверка потребления памяти**

```bash
# Метрика working set (если доступна через metrics-server)
kubectl top pod --all-namespaces --sort-by=memory | head -20
```

### Предотвращение через Guaranteed QoS

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-app
spec:
  containers:
  - name: app
    image: critical-app:latest
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "512Mi"   # == requests → Guaranteed
        cpu: "500m"       # == requests → Guaranteed
```

> **Важно:** Guaranteed защищает только от Node Pressure Eviction. От OOMKilled не защищает — при превышении `limits.memory` контейнер будет убит OOM Killer.

### Настройка kubelet для мягкой eviction

```yaml
# /var/lib/kubelet/config.yaml
evictionHard:
  memory.available: "200Mi"      # Жёсткий порог
evictionSoft:
  memory.available: "500Mi"      # Мягкий порог — раньше предупреждаем
evictionSoftGracePeriod:
  memory.available: 2m           # 2 минуты до начала eviction
evictionMaxPodGracePeriod: 120   # Максимальный grace для подов
```

> Soft thresholds дают подам время на graceful shutdown до начала принудительной eviction.

## Additional Information

### Сравнение защиты QoS

| Угроза | BestEffort | Burstable | Guaranteed |
|--------|-----------|-----------|------------|
| **Node Pressure Eviction** | ❌ Первые на вылет | ⚠️ Вторые | ✅ Последние |
| **OOMKilled** | ❌ Нет limits → реже | ⚠️ При превышении limits | ⚠️ При превышении limits |
| **Taint-based Eviction** | ❌ Без toleration | ❌ Без toleration | ❌ Без toleration |
| **Drain (Eviction API)** | ❌ Без PDB | ❌ Без PDB | ✅ С PDB |

### Best Practices

| Практика | Описание |
|----------|----------|
| **Избегайте BestEffort в production** | Всегда указывайте requests/limits |
| **Burstable для большинства приложений** | requests на минимуме, limits с запасом |
| **Guaranteed для критичных сервисов** | Базы данных, очереди сообщений |
| **Мониторьте распределение QoS** | Алерт на % BestEffort подов |
| **Используйте LimitRange** | Автоматические defaults для namespace |

### Связанные файлы

- **Определения:** [definitions.md](./definitions.md) — типы eviction, thresholds
- **Memory eviction:** [memory_eviction.md](./memory_eviction.md) — нехватка памяти
- **Disk eviction:** [disk_eviction.md](./disk_eviction.md) — нехватка диска
- **QoS SSoT:** [qos_limit_and_requests.md](../../../Scheduling/qos_limit_and_requests.md) — полное руководство по QoS
- **Профилактика:** [prevention.md](./prevention.md) — monitoring, best practices
- **Kubelet:** [kubelet.md](../../../Concepts/kubelet.md) — конфигурация kubelet
