# Horizontal Pod Autoscaler (HPA): Дополнительные темы

## 1. Определения

**Диагностика HPA** — процесс анализа состояния и метрик Horizontal Pod Autoscaler для выявления проблем масштабирования.

**Flapping (дребезг)** — частое циклическое масштабирование вверх/вниз из-за нестабильных метрик или неправильной настройки `stabilizationWindowSeconds`.

**kube-state-metrics** — источник метрик о состоянии объектов Kubernetes, включая HPA, для мониторинга в Prometheus.

## 2. Базовые концепции

### 2.1. Диагностика и мониторинг

#### Проверка статуса HPA

```bash
# Список всех HPA в кластере
kubectl get hpa -A

# Детальная информация по конкретному HPA
kubectl describe hpa my-app-hpa -n default

# Текущие метрики подов
kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/default/pods

# Проверка Metrics Server
kubectl top pods -n default
kubectl top nodes
```

#### Распространённые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Waiting for metrics` | Metrics Server не работает | Проверить статус: `kubectl get pods -n kube-system \| grep metrics-server` |
| `unable to get metrics` | Отсутствуют `requests` у контейнеров | Добавить `resources.requests` в Deployment |
| `scaling inactive` | Достигнут `minReplicas`/`maxReplicas` | Проверить границы масштабирования |
| `flapping` | Частое масштабирование | Увеличить `stabilizationWindowSeconds` |

#### Метрики для мониторинга (kube-state-metrics)

| Метрика | Описание |
| :--- | :--- |
| `kube_horizontalpodautoscaler_status_current_replicas` | Текущее количество реплик |
| `kube_horizontalpodautoscaler_status_desired_replicas` | Желаемое количество реплик |
| `kube_horizontalpodautoscaler_status_condition` | Статус условий HPA |
| `kube_horizontalpodautoscaler_spec_min_replicas` | Минимальные реплики |
| `kube_horizontalpodautoscaler_spec_max_replicas` | Максимальные реплики |

### 2.2. Лучшие практики

- **Readiness Probe** — критически важна для исключения «холодных» подов из балансировки.
- **minReadySeconds** — уменьшает «флаппинг» подов, гарантирует стабильность перед включением в балансировку.
- **Корректные requests** — адекватные запросы позволяют планировщику резервировать ресурсы.
- **Behavior для scale-down** — настройте `stabilizationWindowSeconds: 300` для предотвращения частого уменьшения.
- **Выбор метрики** — для I/O-bound приложений используйте кастомные метрики (RPS), а не CPU.
- **PDB** — всегда создавайте [PodDisruptionBudget](../pod_disruption_budget.md) для критических приложений.
- **Тестирование** — проверяйте масштабирование в staging перед production.

### 2.3. Ограничения

- **Не масштабирует ниже minReplicas** — даже при нулевой нагрузке; для масштабирования до нуля используйте KEDA.
- **Интервал метрик** — метрики собираются с интервалом 15 секунд (настройка Metrics Server).
- **Конфликт с VPA** — не используйте HPA по CPU/memory одновременно с [VPA](../vpa_detailed.md) в активных режимах (`Initial`, `Recreate`, `Auto`).
- **Только Deployment/StatefulSet/ReplicaSet** — не работает с DaemonSet, Job, CronJob.
- **Требует Metrics Server** — без Metrics Server работают только кастомные/внешние метрики.

## 3. Практические сценарии

### 3.1. Диагностика проблем масштабирования

1. **Проверка статуса HPA:**
   ```bash
   kubectl describe hpa <hpa-name> -n <namespace>
   ```

2. **Анализ событий:**
   ```bash
   kubectl get events -n <namespace> --field-selector involvedObject.kind=HorizontalPodAutoscaler
   ```

3. **Проверка Metrics Server:**
   ```bash
   kubectl logs -n kube-system deployment/metrics-server
   ```

4. **Валидация requests:**
   ```bash
   kubectl get deployment <deployment-name> -o jsonpath='{.spec.template.spec.containers[*].resources.requests}'
   ```

### 3.2. Настройка мониторинга HPA

Интеграция с Prometheus через kube-state-metrics:

```yaml
# Пример alert для Prometheus
- alert: HPAScalingInactive
  expr: kube_horizontalpodautoscaler_status_condition{condition="ScalingActive",status="false"} == 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "HPA не активен"
```

## 4. Дополнительная информация

### 4.1. Интеграции

- **[Pod Disruption Budget](../pod_disruption_budget.md)** — HPA учитывает PDB при масштабировании вниз.
- **[VPA](../vpa_detailed.md)** — используйте VPA в режиме `Off` для получения рекомендаций, HPA — для горизонтального масштабирования.
- **[KEDA](../keda/basic_concepts.md)** — KEDA создаёт HPA для событийного масштабирования (очереди, расписания).
- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — источник ресурсных метрик для HPA.

### 4.2. Ресурсы

- [Официальная документация Kubernetes: HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Kubernetes Autoscaling SIG](https://github.com/kubernetes/autoscaler)
- [Prometheus Adapter](https://github.com/kubernetes-sigs/prometheus-adapter)

---

**Связанные документы:**

- **[Основные концепции](./hpa_concepts.md)** — определения, алгоритм, типы метрик
- **[Практические сценарии](./hpa_scenarios.md)** — предварительные требования, сценарии использования
- **[VPA](../vpa_detailed.md)** — вертикальное масштабирование
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — защита от недоступности
