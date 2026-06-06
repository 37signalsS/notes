# Pod Evicted: Maintenance Eviction (Drain)

## Обзор

**Maintenance Eviction** — выселение подов в результате выполнения команды `kubectl drain` для планового обслуживания узла. Это штатный процесс, инициируемый администратором через Eviction API.

## Основная документация

Все детали процесса выселения, отличия от Node Pressure Eviction, диагностика PDB-блокировок и зависших подов находятся в основном SSoT-файле:

👉 **[Обслуживание узлов Kubernetes: Cordon и Drain](../../../Operations/node_maintenance.md)**

## Диагностика выселения

Если под был выселен в ходе обслуживания, в его событиях (Events) будет сообщение:

```text
pod evicted from node <node-name> by user request
```

## Связанные файлы

- [Типы выселения и QoS](./definitions.md)
- [Диагностика выселенных подов](./diagnostics.md)
- [Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md)
