# Pod Evicted: QoS и Eviction Manager

## Связь с QoS классами

При нехватке ресурсов Kubernetes выселяет поды в порядке приоритета:

```
1. BestEffort (нет requests/limits)
   ↓
2. Burstable (requests < limits)
   ↓
3. Guaranteed (requests == limits)
```

| QoS Класс | Условия | Приоритет вытеснения |
|-----------|---------|---------------------|
| **`BestEffort`** | Нет `requests`/`limits` | **Первые** |
| **`Burstable`** | `requests` < `limits` | **Вторые** |
| **`Guaranteed`** | `requests` == `limits` | **Последние** |

## Eviction Manager

Компонент `kubelet`, который мониторит ресурсы узла и принимает решения о выселении подов.

**Workflow:**

```
Ресурсы узла < threshold
    ↓
Eviction Manager активируется
    ↓
Сортировка подов по QoS и потреблению
    ↓
Выселение подов (начиная с BestEffort)
    ↓
Ресурсы освобождены → Stop
```
