# Horizontal Pod Autoscaler (HPA)

Индекс документов по горизонтальному автомасштабированию подов в Kubernetes.

## Документы

| Документ | Описание |
| :--- | :--- |
| **[Основные концепции](./hpa_concepts.md)** | Определения, алгоритм принятия решений, типы метрик, компоненты архитектуры |
| **[Практические сценарии](./hpa_scenarios.md)** | Предварительные требования, сценарии (CPU, память, внешние метрики, Prometheus) |
| **[Дополнительные темы](./hpa_advanced.md)** | Диагностика, распространённые проблемы, best practices, ограничения, интеграции |

## Связанные документы

- **[KEDA](../keda_detailed.md)** — событийное масштабирование
- **[VPA](../vpa_detailed.md)** — вертикальное масштабирование
- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — источник ресурсных метрик
- **[Pod Disruption Budget](../../PodDisruptionBudget/pod_disruption_budget.md)** — защита от недоступности
- **[Scaling Patterns](../scaling_patterns.md)** — паттерны масштабирования

## Ресурсы

- [Официальная документация Kubernetes: HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Kubernetes Autoscaling SIG](https://github.com/kubernetes/autoscaler)
- [Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)
