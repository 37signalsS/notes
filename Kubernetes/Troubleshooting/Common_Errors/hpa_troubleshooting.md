# Устранение неполадок HPA (Horizontal Pod Autoscaler)

## Определения

**HPA Troubleshooting** — процесс выявления и устранения сбоев в работе горизонтального автомасштабировщика подов. HPA работает как «петля управления» (Control Loop), и сбой обычно происходит в конвейере передачи метрик или из-за конфликтов конфигурации.

**`<unknown>` в метриках** — состояние, при котором контроллер HPA не может получить текущее значение метрики от API-сервера.

**Дребезг (Flapping/Thrashing)** — ситуация частого создания и удаления подов из-за резких колебаний метрик или некорректно настроенных окон стабилизации.

## Алгоритм диагностики

### Шаг 1: Проверка статуса и условий (Conditions)

Это основной источник данных. Изучите секцию `Conditions` в выводе describe:
```bash
kubectl describe hpa <hpa-name>
```

| Условие | Статус: Значение | Что означает |
|:---|:---|:---|
| **`AbleToScale`** | `False`: `FailedGetScale` | HPA не может найти целевой объект (Deployment/StatefulSet) или нет прав RBAC. |
| **`ScalingActive`** | `False`: `FailedGetResourceMetric` | Проблема сбора метрик (Metrics API недоступен или пуст). |
| **`ScalingLimited`** | `True`: `TooManyReplicas` | Достигнут `maxReplicas`. Масштабирование выше невозможно. |

### Шаг 2: Проверка конвейера метрик

HPA запрашивает данные через Aggregated API. 

1. **Базовые метрики (CPU/Memory):**
   ```bash
   # Проверка доступности Metrics API
   kubectl get apiservice v1beta1.metrics.k8s.io
   # Проверка данных
   kubectl top pods
   ```
2. **Кастомные/Внешние метрики (Prometheus, KEDA):**
   ```bash
   # Проверка регистрации API
   kubectl get apiservice | grep custom.metrics
   # Ручной запрос сырых данных метрик
   kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq .
   ```

### Шаг 3: Проверка спецификации Pod (Resources Requests)

**Если у контейнера не задан `resources.requests.cpu` (или memory), HPA не сможет рассчитать процент утилизации.**
- HPA рассчитывает: `(текущее потребление / request) * 100%`.
- Если `request` отсутствует, формула выдает ошибку, и вы видите `<unknown> / 70%`.

### Шаг 4: Проверка логики и лимитов

1. **Толерантность (Tolerance):** По умолчанию HPA не реагирует, если изменение метрики составляет менее 10% (0.1).
2. **Ready Pods:** HPA учитывает только поды в состоянии `Ready`. Если поды долго стартуют или падают (CrashLoop), расчеты будут неточными.
3. **Cluster Autoscaler:** Если HPA увеличил `desiredReplicas`, но поды в `Pending` — проверяйте наличие свободных ресурсов на узлах и работу Cluster Autoscaler.

## Практические сценарии

### Сценарий 1: Статус <unknown> при работающем metrics-server
- **Проблема:** `kubectl top pods` показывает данные, но HPA пишет `<unknown>`.
- **Причина:** В Deployment несколько контейнеров (например, sidecar), и у одного из них не указаны `requests`. HPA требует `requests` для **всех** контейнеров пода, если используется тип метрики `Resource`.
- **Решение:** Укажите `requests` для всех контейнеров или используйте `ContainerResource` (v2 API) для масштабирования только по основному контейнеру.

### Сценарий 2: HPA не масштабирует вниз (Scale Down)
- **Причина 1 (Behavior):** По умолчанию окно стабилизации для scaleDown составляет **300 секунд (5 минут)**. HPA ждет подтверждения стабильности низкой нагрузки.
- **Причина 2 (Memory):** Приложение (особенно Java/Go) не возвращает память ОС после Garbage Collection. Метрика `working_set_bytes` остается высокой, и HPA «видит» нагрузку.
- **Причина 3 (ArgoCD):** Если в Git указано `replicas: 3` и включен `selfHeal`, ArgoCD будет мгновенно возвращать количество реплик назад, конфликтуя с HPA.
- **Решение:** Настройте `behavior.scaleDown.stabilizationWindowSeconds` или добавьте `ignoreDifferences` в ArgoCD.

### Сценарий 3: Дребезг (Flapping)
- **Симптом:** Поды создаются и удаляются каждые пару минут.
- **Причина:** Слишком узкий диапазон реплик или отсутствие окна стабилизации при резких всплесках трафика.
- **Решение:** Настройте политики в секции `behavior`:
```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 600 # Увеличить до 10 минут
    policies:
    - type: Percent
      value: 10
      periodSeconds: 60 # Удалять не более 10% в минуту
```

### Сценарий 4: Конфликт HPA и VPA
- **Проблема:** Бесконечный цикл изменения количества подов и их ресурсов.
- **Причина:** Использование HPA и VPA на одной и той же метрике (CPU/Memory).
- **Решение:** Используйте VPA только в режиме `Off` (для рекомендаций) или разделите метрики: HPA по RPS (через KEDA/Prometheus), VPA по CPU/Memory.

## Дополнительная информация

### Совет для собеседования
**Вопрос:** Почему HPA может показывать `<unknown>`?
**Ответ:** Я проверю три фактора:
1. **Инфраструктура:** Работает ли `metrics-server` и зарегистрирован ли API Service.
2. **Манифест:** Указаны ли `resources.requests` для **всех** контейнеров в поде.
3. **Сеть/RBAC:** Имеет ли контроллер HPA доступ к эндпоинту метрик (проверка логов `kube-controller-manager`).

### Схема прохождения данных
`Container (cgroups) → Kubelet (cAdvisor) → Metrics Server → Metrics API Server → HPA Controller → Scale Subresource → Deployment`

### См. также
- [HPA: Продвинутая настройка](../../Autoscaling/HPA/hpa_advanced.md) — детали `behavior` и типов метрик.
- [Metrics Server](../../MonitoringLogging/metrics-server.md) — установка и отладка.
- [KEDA (Event-driven Autoscaling)](../../Autoscaling/keda/keda_concepts.md) — масштабирование по внешним метрикам.
- [QoS, Requests и Limits](../../Scheduling/qos_limit_and_requests.md) — базовая настройка ресурсов.
