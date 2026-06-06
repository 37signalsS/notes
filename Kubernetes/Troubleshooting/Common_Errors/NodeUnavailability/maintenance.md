# Node Unavailability: Обслуживание узлов

## Обзор

Данный раздел описывает процедуры планового обслуживания узлов (Cordon, Drain, Uncordon). Для предотвращения дублирования информации все подробные инструкции и лучшие практики перенесены в основной раздел.

## Основная документация

Полное руководство по обслуживанию узлов, включая практические сценарии, настройку мониторинга и решение проблем (PDB, Finalizers), находится здесь:

👉 **[Обслуживание узлов Kubernetes: Cordon и Drain](../../../Operations/node_maintenance.md)**

## Краткий справочник команд

| Действие | Команда |
| :--- | :--- |
| **Запрет планирования** | `kubectl cordon <node>` |
| **Выселение подов** | `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` |
| **Возврат в работу** | `kubectl uncordon <node>` |

## Связанные темы

* [Диагностика недоступности узлов](./diagnostics.md)
* [Taints и выселение подов](./taints_and_eviction.md)
* [Pod Disruption Budget](../../../Autoscaling/pod_disruption_budget.md)
