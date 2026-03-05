# Pod в состоянии `Pending`: Определения и концепции

## Определения

**Pending** — состояние пода в Kubernetes, означающее, что планировщик не может разместить под на каком-либо узле кластера. Под находится в очереди на планирование.

**Планировщик (Scheduler)** — компонент Kubernetes, который определяет, на каком узле будет запущен под, на основе доступных ресурсов, политик и ограничений.

## Причины состояния Pending

Под переходит в состояние `Pending` когда:

1. **Недостаточно ресурсов** — CPU, память, ephemeral storage
2. **Не выполнены ограничения планирования** — nodeSelector, affinity/anti-affinity
3. **Taints и tolerations** — узлы имеют taints, которые под не tolerates
4. **PVC не удовлетворен** — нет доступного PV или StorageClass
5. **ResourceQuota превышен** — лимиты namespace исчерпаны
6. **PriorityClass** — под с высоким приоритетом не может вытеснить другие поды

## Архитектура планирования

```
┌─────────────────┐
│   Pod Created   │
│   (Pending)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Scheduler     │
│   Watch Queue   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Filter Nodes   │
│  (Predicates)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Score Nodes    │
│  (Priorities)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Bind Pod to   │
│   Best Node     │
└─────────────────┘
```

## Диагностика

Основной инструмент диагностики — команда `kubectl describe pod`, которая показывает:

- Текущее состояние пода
- Причины ожидания (в разделе Events)
- Требования к ресурсам
- Ограничения планирования

## Связанные концепции

- **[Resource Requests/Limits](../../Scheduling/qos_limit_and_requests.md)** — запросы ресурсов
- **[Node Affinity](../../Scheduling/affinity.md)** — привязка к узлам
- **[Taints and Tolerations](../../Scheduling/taints_and_tolerations.md)** — изоляция узлов
- **[PVC/PV](../../Storage/pv_and_pvc.md)** — постоянное хранилище
- **[ResourceQuota](../../Scheduling/resource_quota.md)** — квоты namespace

---

## Ссылки

- **[Диагностика](./diagnostics.md)** — пошаговый чек-лист
- **[Распространенные случаи](./common_cases_and_solutions.md)** — решения проблем
