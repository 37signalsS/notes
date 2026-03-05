# Pod в состоянии `Pending`: Определения и концепции

## Определения

**`Pending`** — статус пода, означающий, что API-сервер принял спецификацию пода, но планировщик (`kube-scheduler`) не может разместить его на одном из узлов. Под ожидает решения планировщика.

## Основные концепции

### Workflow планировщика

```
Pod создан (Pending)
    ↓
kube-scheduler обнаруживает под
    ↓
Фильтрация узлов (Predicate)
    ↓
Оценка узлов (Priority)
    ↓
Выбор лучшего узла
    ↓
Binding → Pod запускается
```

### Причины Pending по категориям

| Категория | Причины | % случаев |
|-----------|---------|-----------|
| **Ресурсы** | Insufficient cpu/memory | ~40% |
| **Taints** | Узлы имеют taints без tolerations | ~25% |
| **Affinity** | Не выполнены правила affinity | ~20% |
| **PVC** | PVC в Pending (нет PV/StorageClass) | ~10% |
| **Другие** | NodeSelector, PodSecurityPolicy, Quota | ~5% |

### Механизмы ограничения планирования

| Механизм | Описание | Ссылка |
|----------|----------|--------|
| **`requests`/`limits`** | Планировщик ищет узлы с достаточными ресурсами | [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md) |
| **`nodeSelector`** | Простой выбор узлов по меткам | [`affinity.md`](../../Scheduling/affinity.md) |
| **`nodeAffinity`** | Продвинутое правило выбора узлов | [`affinity.md`](../../Scheduling/affinity.md) |
| **`podAffinity`/`podAntiAffinity`** | Размещение относительно других подов | [`affinity.md`](../../Scheduling/affinity.md) |
| **`taints`/`tolerations`** | "Отталкивание" подов от узлов | [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md) |
| **`topologySpreadConstraints`** | Равномерное распределение по топологии | [`pod_distribution.md`](../../Autoscaling/pod_distribution.md) |
| **`PriorityClass`** | Приоритет планирования | [`priorityclass.md`](../../Concepts/priorityclass.md) |

### Связанные концепты

- Taints и tolerations: [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)
- Affinity: [`affinity.md`](../../Scheduling/affinity.md)
- QoS и ресурсы: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
- PV/PVC: [`pv_and_pvc.md`](../../Storage/pv_and_pvc.md)
- PriorityClass: [`priorityclass.md`](../../Concepts/priorityclass.md)

---

## Ссылки

- [Практические сценарии](./practical_scenarios.md) — диагностика и решения
- [Дополнительная информация](./advanced_topics.md) — мониторинг и best practices
