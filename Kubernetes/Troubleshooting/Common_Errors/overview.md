# Диагностика и решение распространенных ошибок в Kubernetes

## Определения

**Распространенные ошибки Kubernetes** — типичные состояния подов и узлов, указывающие на проблемы с планированием, конфигурацией, ресурсами или доступностью компонентов кластера.

> - Общие инструменты диагностики: [`troubleshooting_overview.md`](../troubleshooting_overview.md)
> - QoS и управление ресурсами: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
> - Taints и tolerations: [`taints_and_tolerations.md`](../../Scheduling/taints_and_tolerations.md)
> - RBAC: [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)
> - Обслуживание узлов: [`node_maintenance.md`](../../Operations/node_maintenance.md)

## Основные концепции

### Классификация ошибок по уровням

| Уровень | Ошибки | SSoT |
|---------|--------|------|
| **Планирование** | `Pending` | [pod_pending.md](./pod_pending.md) |
| **Конфигурация** | `ImagePullBackOff`, `CreateContainerConfigError` | [pod_image_pull_errors.md](./pod_image_pull_errors.md), [create_container_config_error.md](./create_container_config_error.md) |
| **Запуск приложения** | `CrashLoopBackOff`, `OOMKilled` | [pod_crash_loop_back_off.md](./pod_crash_loop_back_off.md), [oomkilled_pods.md](./oomkilled_pods.md) |
| **Ресурсы узла** | `Evicted`, `NodeNotReady` | [pod_evicted.md](./pod_evicted.md), [node_unavailability.md](./node_unavailability.md) |
| **Безопасность** | `Forbidden`, `Unauthorized` | [api_access_forbidden.md](./api_access_forbidden.md) |
| **Завершение** | `Terminating` | [pod_terminating_issues.md](./pod_terminating_issues.md) |

### Базовый workflow диагностики

```
1. kubectl get pods --show-labels
   ↓
2. kubectl describe pod <pod-name>  → Events section
   ↓
3. kubectl logs <pod-name> [--previous]
   ↓
4. kubectl auth can-i [...]  (для RBAC)
   ↓
5. kubectl top pod/node  (для ресурсов)
```

> **Важно:** Всегда начинайте с `kubectl describe` — раздел `Events` содержит хронологию событий и часто указывает на корневую причину.

## Практические сценарии

### Быстрая диагностика по статусу

| Статус пода | Первая команда | Вероятная причина |
|-------------|----------------|-------------------|
| `Pending` | `kubectl describe pod` | Нехватка ресурсов, taints, affinity |
| `ContainerCreating` | `kubectl describe pod` | Проблемы с образом, PV, сетью |
| `ImagePullBackOff` | `kubectl describe pod` | Ошибка имени образа, нет доступа к registry |
| `CrashLoopBackOff` | `kubectl logs --previous` | Ошибка приложения, конфигурации, зависимостей |
| `OOMKilled` | `kubectl describe pod` + `kubectl top pod` | Превышен limits.memory, утечка памяти |
| `Evicted` | `kubectl describe node` | Node Pressure (memory/disk) |
| `Terminating` | `kubectl get pod -o yaml` | Finalizers, volume unmount |

### Связь с QoS классами

При нехватке ресурсов на узле Kubernetes выселяет поды на основе [QoS класса](../../Scheduling/qos_limit_and_requests.md):

1. **`BestEffort`** — выселяются первыми (нет requests/limits)
2. **`Burstable`** — выселяются вторыми (requests < limits)
3. **`Guaranteed`** — выселяются последними (requests == limits)

> **Best Practice:** Всегда указывайте `requests` и `limits` для production-приложений.

## Дополнительная информация

### Инструменты диагностики

| Инструмент | Назначение | Пример |
|------------|------------|--------|
| `kubectl describe` | Детальная информация + Events | `kubectl describe pod <name>` |
| `kubectl logs` | Логи контейнера | `kubectl logs <name> --previous` |
| `kubectl auth can-i` | Проверка RBAC прав | `kubectl auth can-i get pods --as=system:serviceaccount:ns:sa` |
| `kubectl top` | Мониторинг ресурсов | `kubectl top pod`, `kubectl top node` |
| `kubectl debug` | Эфемерные контейнеры для отладки | `kubectl debug -it <pod> --image=nicolaka/netshoot` |

### Связанные разделы

- [Общий обзор troubleshooting](../troubleshooting_overview.md) — инструменты, методы, sleep-паттерн
- [Pod Lifecycle](../../Base/Pod/pod_lifecycle_and_state.md) — состояния пода, probe
- [Deployment](../../Base/deployment.md) — стратегии развертывания, rollback
- [High Availability](../../Base/high_availability.md) — PDB, eviction timeout
- [Pod Distribution](../../Autoscaling/pod_distribution.md) — affinity, topologySpreadConstraints
