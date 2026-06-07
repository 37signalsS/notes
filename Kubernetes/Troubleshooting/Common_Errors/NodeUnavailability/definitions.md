# Недоступность узла: Определения

## Определения

**`NodeNotReady`** — статус узла (`Node`), означающий, что `kubelet` на узле работает, но сообщает, что узел не готов принимать новые поды.

**`Node Unreachable`** — состояние, при котором `kube-apiserver` не может связаться с `kubelet` на узле через контрольный канал (health check timeout).

**Важно:** Это статусы узла, а не пода. Они влияют на все поды, размещённые на проблемном узле.

## Основные концепции

### Состояния узла (Node Conditions)

Kubernetes отслеживает следующие условия узла:

| Condition | Описание | Нормальный статус |
|-----------|----------|-------------------|
| **`Ready`** | Узел готов принимать поды | `True` |
| **`MemoryPressure`** | Нехватка оперативной памяти | `False` |
| **`DiskPressure`** | Нехватка места на диске | `False` |
| **`PIDPressure`** | Исчерпание лимита процессов (PID) | `False` |
| **`NetworkUnavailable`** | Сетевая связность отсутствует | `False` |

### Статусы узла

| Статус | Condition | Описание |
|--------|-----------|----------|
| **`Ready`** | `Ready=True` | Узел работает нормально |
| **`NotReady`** | `Ready=False` | Kubelet работает, но узел не готов |
| **`Unknown`** | `Ready=Unknown` | Kubelet не отвечает (Unreachable) |
| **`SchedulingDisabled`** | `unschedulable=true` | Узел выведен из планирования (Cordon) |

### Тайм-ауты и выселение (Eviction)

При изменении статуса узла Kubernetes применяет механизмы выселения. Контроль состояния и задержки перед выселением подов определяются параметрами `kube-controller-manager` (`--node-monitor-grace-period`, `--pod-eviction-timeout`).

Подробное описание процесса и параметров доступно в основном разделе:
**[Taints и Tolerations: Процесс выселения и параметры контроллера](../../../Scheduling/taints_and_tolerations.md#процесс-выселения-eviction-timeline)**.

| Статус узла | Влияние на поды |
|-------------|-----------------|
| **`NotReady`** | Существующие поды продолжают работать, новые не планируются |
| **`Unknown`** (>40s) | Добавляется taint `unreachable:NoExecute` |
| **`Unknown`** (>5m) | Поды без соответствующих tolerations выселяются |

## Практические сценарии

### Когда использовать этот диагностический путь

- `kubectl get nodes` показывает статус `NotReady` или `Unknown`.
- Поды на узле перестали обновляться или теряют связность.
- Сработал алерт `NodeNotReady` или `NodeUnreachable` в системе мониторинга.
- После перезагрузки или обновления узел не возвращается в кластер.

### Основные причины (Root Causes)

| Причина | Типичный статус | Ссылка на решение |
|---------|-----------------|-------------------|
| Ошибка или падение Kubelet | `NotReady` | [Проблемы Kubelet](./kubelet_issues.md) |
| Нехватка ресурсов (Resource Pressure) | `NotReady` + Pressure | [Давление ресурсов](./resource_pressure.md) |
| Потеря сетевой связности | `Unknown` | [Проблемы с сетью](./network_issues.md) |
| Сбой Container Runtime (Docker/containerd) | `NotReady` | [Проблемы рантайма](./runtime_issues.md) |
| Плановые работы | `SchedulingDisabled` | [Обслуживание узлов](./maintenance.md) |

### Точка входа в диагностику

Для пошаговой проверки используйте [чек-лист диагностики](./diagnostics.md).

## Дополнительная информация

- [Taints и Eviction при недоступности](./taints_and_eviction.md) — детали выселения подов.
- [Node Maintenance](../../../Operations/node_maintenance.md) — плановое обслуживание и вывод из эксплуатации.
- [Troubleshooting Overview](../overview.md) — общие ошибки Kubernetes.
