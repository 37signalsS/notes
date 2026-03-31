# Horizontal Pod Autoscaler (HPA)

Горизонтальное автомасштабирование подов в Kubernetes на основе метрик загрузки.

## Определения

**Horizontal Pod Autoscaler (HPA)** — механизм Kubernetes для автоматического изменения количества реплик подов в Deployment, ReplicaSet или StatefulSet на основе метрик (CPU, memory, custom, external). Работает по принципу термостата с периодичностью опроса 15 секунд (по умолчанию).

**Масштабирование по горизонтали** — увеличение количества экземпляров приложения (подов) в отличие от вертикального масштабирования (увеличение ресурсов отдельных экземпляров).

## Базовые концепции

### Алгоритм принятия решений

```
желаемыеРеплики = ceil(текущиеРеплики × (текущаяМетрика / желаемаяМетрика))
```

**Пример:** При 3 репликах, целевой утилизации CPU 50% и текущей нагрузке 90%: `ceil(3 × (90 / 50)) = 6 реплик`.

### Типы метрик

| Тип | Источник | Примеры |
| :--- | :--- | :--- |
| **Resource Metrics** | Metrics Server (`metrics.k8s.io`) | `cpu`, `memory` |
| **Custom Metrics** | Prometheus Adapter (`custom.metrics.k8s.io`) | `http_requests_per_second`, `latency` |
| **External Metrics** | KEDA, внешние системы (`external.metrics.k8s.io`) | `kafka_lag`, `sqs_messages` |

### Компоненты архитектуры

- **HPA Controller** — контроллер в `kube-controller-manager`, управляющий объектами HPA
- **Metrics Server** — предоставляет ресурсные метрики через Metrics API
- **Custom Metrics API** — адаптер (Prometheus Adapter) для кастомных метрик
- **External Metrics API** — для внешних метрик (KEDA)

### Конфигурация поведения (Behavior)

Параметры `behavior` позволяют настроить скорость и агрессивность масштабирования:

| Параметр | Описание | Типичные значения |
| :--- | :--- | :--- |
| `stabilizationWindowSeconds` | Задержка перед масштабированием | 0-600 секунд |
| `policies.type` | Тип политики | `Percent`, `Pods` |
| `policies.value` | Величина изменения | Процент или количество подов |
| `policies.periodSeconds` | Период применения | 15-300 секунд |
| `selectPolicy` | Выбор политики при нескольких | `Max`, `Min`, `Disabled` |

## Практические сценарии

### Выбор типа метрики

- **CPU-bound приложения** (вычисления, обработка данных) — Resource Metrics (CPU)
- **I/O-bound приложения** (веб-сервисы, API) — Custom Metrics (RPS, latency)
- **Очереди и воркеры** — External Metrics (длина очереди, lag)

### Настройка stabilizationWindowSeconds

- **Scale-up:** `0` секунд для мгновенного масштабирования при росте нагрузки
- **Scale-down:** `300` секунд (5 минут) для предотвращения «флаппинга» при временных спадах

### Предварительные требования

1. **Metrics Server** — обязателен для работы с базовыми метриками (`cpu`, `memory`)
2. **Requests у контейнеров** — должны быть установлены для корректного расчёта утилизации:
   ```yaml
   resources:
     requests:
       cpu: "200m"
       memory: "256Mi"
   ```

## Дополнительная информация

### Ограничения

- **Не масштабирует ниже minReplicas** — даже при нулевой нагрузке (для масштабирования до нуля используйте KEDA)
- **Интервал метрик** — 15 секунд (настройка Metrics Server)
- **Конфликт с VPA** — не используйте HPA по CPU/memory одновременно с VPA в активных режимах
- **Только Deployment/StatefulSet/ReplicaSet** — не работает с DaemonSet, Job, CronJob

### Лучшие практики

- **Readiness Probe** — критически важна для исключения «холодных» подов из балансировки
- **Pod Disruption Budget** — всегда создавайте PDB для критических приложений
- **Behavior для scale-down** — настройте `stabilizationWindowSeconds: 300` для предотвращения частого уменьшения
- **Тестирование** — проверяйте масштабирование в staging перед production

### Диагностика

```bash
# Список всех HPA
kubectl get hpa -A

# Детальная информация
kubectl describe hpa my-app-hpa -n default

# Проверка метрик
kubectl top pods -n default
kubectl top nodes
```

### Интеграции

- **[KEDA](../keda/basic_concepts.md)** — событийное масштабирование на основе внешних метрик (очереди, расписания), поддерживает масштабирование до нуля
- **[VPA](../vpa_detailed.md)** — вертикальное масштабирование (используйте в режиме `Off` для рекомендаций совместно с HPA)
- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — источник ресурсных метрик для HPA
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — HPA учитывает PDB при масштабировании вниз

### Связанные документы

- **[Основные концепции](./hpa_concepts.md)** — подробные определения, алгоритм принятия решений, типы метрик, компоненты архитектуры
- **[Практические сценарии](./hpa_scenarios.md)** — предварительные требования, сценарии использования (CPU, память, внешние метрики, Prometheus)
- **[Дополнительные темы](./hpa_advanced.md)** — диагностика, распространённые проблемы, best practices, ограничения, интеграции
- **[Обзор автомасштабирования](../overview_concepts.md)** — общая концепция, синергия компонентов (HPA, VPA, Cluster Autoscaler, KEDA, Karpenter)
