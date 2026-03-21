# Horizontal Pod Autoscaler (HPA): Дополнительные темы

## 1. Диагностика и мониторинг

### 1.1. Проверка статуса HPA

```bash
# Список всех HPA
kubectl get hpa -A

# Детальная информация
kubectl describe hpa my-app-hpa -n default

# Текущие метрики
kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/default/pods

# Проверка Metrics Server
kubectl top pods -n default
kubectl top nodes
```

### 1.2. Распространённые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Waiting for metrics` | Metrics Server не работает | Проверить статус `kubectl get pods -n kube-system \| grep metrics-server` |
| `unable to get metrics` | Нет requests у контейнеров | Добавить `resources.requests` в Deployment |
| `scaling inactive` | Достигнут minReplicas/maxReplicas | Проверить границы масштабирования |
| `flapping` | Частое масштабирование | Увеличить `stabilizationWindowSeconds` |

### 1.3. Метрики для мониторинга

| Метрика | Описание |
| :--- | :--- |
| `kube_horizontalpodautoscaler_status_current_replicas` | Текущее количество реплик |
| `kube_horizontalpodautoscaler_status_desired_replicas` | Желаемое количество реплик |
| `kube_horizontalpodautoscaler_status_condition` | Статус условий HPA |
| `kube_horizontalpodautoscaler_spec_min_replicas` | Минимальные реплики |
| `kube_horizontalpodautoscaler_spec_max_replicas` | Максимальные реплики |

## 2. Лучшие практики

- **Readiness Probe** — критически важна для исключения «холодных» подов из балансировки.
- **minReadySeconds** — уменьшает «флаппинг» подов, гарантирует стабильность перед включением в балансировку.
- **Корректные requests** — адекватные запросы позволяют планировщику резервировать ресурсы.
- **Behavior для scale-down** — настройте `stabilizationWindowSeconds: 300` для предотвращения частого уменьшения.
- **Выбор метрики** — для I/O-bound приложений используйте кастомные метрики (RPS), а не CPU.
- **PDB** — всегда создавайте [PodDisruptionBudget](../pod_disruption_budget.md) для критических приложений.
- **Тестирование** — проверяйте масштабирование в staging перед production.

## 3. Ограничения

- **Не масштабирует ниже minReplicas** — даже при нулевой нагрузке; для масштабирования до нуля используйте KEDA.
- **Интервал метрик** — метрики собираются с интервалом 15 секунд (настройка Metrics Server).
- **Конфликт с VPA** — не используйте HPA по CPU/memory одновременно с [VPA](../vpa_detailed.md) в активных режимах (`Initial`, `Recreate`, `Auto`).
- **Только Deployment/StatefulSet/ReplicaSet** — не работает с DaemonSet, Job, CronJob.
- **Требует Metrics Server** — без Metrics Server работают только кастомные/внешние метрики.

## 4. Интеграции

| Интеграция | Описание |
| :--- | :--- |
| **[Pod Disruption Budget](../pod_disruption_budget.md)** | HPA учитывает PDB при масштабировании вниз |
| **[Pod Distribution](../pod_distribution.md)** | Созданные HPA поды распределяются согласно правилам распределения |
| **[Scaling Patterns](../scaling_patterns.md)** | Для масштабирования workers по длине очереди используйте внешние метрики |
| **[VPA](../vpa_detailed.md)** | Используйте VPA в режиме `Off` для получения рекомендаций, HPA — для горизонтального масштабирования |
| **[KEDA](../Autoscaling/keda_detailed.md)** | KEDA создаёт HPA для событийного масштабирования (очереди, расписания) |
| **[Metrics Server](../MonitoringLogging/metrics-server.md)** | Источник ресурсных метрик для HPA |

## 5. Ресурсы

- [Официальная документация Kubernetes: HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Kubernetes Autoscaling SIG](https://github.com/kubernetes/autoscaler)
- [Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)

## Связанные документы

- **[Основные концепции](./hpa_concepts.md)** — определения, алгоритм, типы метрик
- **[Практические сценарии](./hpa_scenarios.md)** — предварительные требования, сценарии использования
- **[VPA](../vpa_detailed.md)** — вертикальное масштабирование
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — защита от недоступности
