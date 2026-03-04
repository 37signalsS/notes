# KEDA (Kubernetes Event-driven Autoscaling)

## Определения

**KEDA (Kubernetes Event-driven Autoscaling)** — легковесный оператор Kubernetes для автоматического масштабирования подов на основе событий из внешних источников (очереди сообщений, метрики, расписание).

**ScaledObject** — кастомный ресурс KEDA, определяющий правила масштабирования для Deployment.

**Scaler** — компонент KEDA, подключающийся к внешнему источнику событий и предоставляющий метрики для масштабирования.

**Trigger** — условие в ScaledObject, определяющее пороговое значение для активации масштабирования.

## Основные концепции

### Ключевые возможности

* **Масштабирование до нуля** — KEDA может уменьшить количество реплик до 0 при отсутствии событий.
* **Событийное масштабирование** — реакция на события из 60+ источников (Kafka, RabbitMQ, Prometheus, Cron и др.).
* **Управление HPA** — KEDA создаёт и управляет нативным объектом HPA на основе конфигурации ScaledObject.
* **Внешние метрики** — использование метрик, недоступных в стандартном Metrics Server.

### Архитектура KEDA

1. **KEDA Operator** — оператор, работающий как Deployment в namespace `keda`.
2. **Metrics Server** — компонент KEDA, предоставляющий внешние метрики через Kubernetes Metrics API.
3. **Admission Webhook** — валидация ресурсов KEDA при создании.
4. **Scalers** — плагины для подключения к источникам событий.

### Принцип работы

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐
│   Источник  │───▶│ KEDA Scaler  │───▶│   KEDA     │───▶│   HPA    │
│   событий   │    │ (сбор метрик)│    │  Operator  │    │          │
└─────────────┘    └──────────────┘    └─────────────┘    └────┬─────┘
                                                               │
                                                               ▼
                                                        ┌─────────────┐
                                                        │ Deployment  │
                                                        │   (scale)   │
                                                        └─────────────┘
```

### Типы scaler'ов

| Категория | Примеры scaler'ов |
|-----------|-------------------|
| **Очереди сообщений** | Kafka, RabbitMQ, AWS SQS, Azure Service Bus, Google Pub/Sub |
| **Метрики и мониторинг** | Prometheus, Datadog, New Relic, Grafana Loki |
| **Хранилища и базы данных** | MySQL, PostgreSQL, MongoDB, Redis, Elasticsearch |
| **Облачные события** | AWS CloudWatch, Azure Monitor, Google Cloud Monitoring |
| **Расписание и время** | Cron, Azure Event Hubs |
| **Другие** | HTTP requests, GitHub Actions, GitLab, Jenkins |

## Практические сценарии

### Установка KEDA

```bash
# Установка через Helm (рекомендуется)
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.15.0

# Проверка установки
kubectl get pods -n keda
kubectl get apiservice v1beta1.external.metrics.k8s.io
```

### Сценарий 1: Масштабирование по очереди RabbitMQ

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-consumer-scaledobject
  namespace: default
spec:
  # Целевой Deployment
  scaleTargetRef:
    name: rabbitmq-consumer
  
  # Границы масштабирования
  minReplicaCount: 0
  maxReplicaCount: 30
  
  # Период опроса метрик (секунды)
  pollingInterval: 15
  
  # Период стабилизации после масштабирования вниз
  cooldownPeriod: 300
  
  # Триггеры масштабирования
  triggers:
    - type: rabbitmq
      metadata:
        queueName: orders
        host: amqp://rabbitmq:5672
        queueLength: "10"  # Целевое значение: 10 сообщений на под
```

### Сценарий 2: Масштабирование по очереди Kafka

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaledobject
spec:
  scaleTargetRef:
    name: kafka-consumer
  
  minReplicaCount: 1
  maxReplicaCount: 50
  
  pollingInterval: 10
  
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka-broker:9092
        consumerGroup: my-consumer-group
        topic: orders
        lagThreshold: "100"  # Масштабирование при отставании >100 сообщений
      authenticationRef:
        name: kafka-trigger-auth
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: kafka-trigger-auth
spec:
  secretTargetRef:
    - parameter: sasl
      name: kafka-secret
      key: sasl
    - parameter: username
      name: kafka-secret
      key: username
    - parameter: password
      name: kafka-secret
      key: password
```

### Сценарий 3: Масштабирование по метрикам Prometheus

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: prometheus-scaledobject
spec:
  scaleTargetRef:
    name: web-api
  
  minReplicaCount: 2
  maxReplicaCount: 20
  
  pollingInterval: 30
  
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: http_requests_per_second
        threshold: "100"
        query: |
          sum(rate(http_requests_total{service="web-api"}[1m]))
```

### Сценарий 4: Масштабирование по расписанию (Cron)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: cron-scaledobject
spec:
  scaleTargetRef:
    name: batch-processor
  
  minReplicaCount: 0
  maxReplicaCount: 10
  
  triggers:
    # Активно в рабочие часы (9:00-18:00, пн-пт)
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 9 * * mon-fri
        end: 0 18 * * mon-fri
        desiredReplicas: "5"
    
    # Ночью и в выходные — 0 реплик
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 18 * * mon-fri
        end: 0 9 * * mon-fri
        desiredReplicas: "0"
```

### Сценарий 5: Несколько триггеров (логика ИЛИ)

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger-scaledobject
spec:
  scaleTargetRef:
    name: order-processor
  
  minReplicaCount: 0
  maxReplicaCount: 50
  
  # Логика триггеров: ИЛИ (масштабирование при срабатывании любого)
  fallback:
    failureThreshold: 3
    replicas: 5
  
  triggers:
    # Триггер 1: очередь RabbitMQ
    - type: rabbitmq
      metadata:
        queueName: orders
        host: amqp://rabbitmq:5672
        queueLength: "20"
    
    # Триггер 2: метрика CPU от Prometheus
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: cpu_utilization
        threshold: "80"
        query: |
          avg(rate(container_cpu_usage_seconds_total{pod=~"order-processor.*"}[1m])) * 100
```

### Сценарий 6: Продвинутое поведение масштабирования

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: advanced-behavior-scaledobject
spec:
  scaleTargetRef:
    name: api-server
  
  minReplicaCount: 2
  maxReplicaCount: 100
  
  pollingInterval: 10
  cooldownPeriod: 300
  
  # Продвинутое поведение
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
            - type: Percent
              value: 100
              periodSeconds: 15
            - type: Pods
              value: 10
              periodSeconds: 15
          selectPolicy: Max
        scaleDown:
          stabilizationWindowSeconds: 600  # 10 минут для стабильности
          policies:
            - type: Percent
              value: 50
              periodSeconds: 60
          selectPolicy: Min
```

### Диагностика и мониторинг

#### Проверка статуса KEDA

```bash
# Просмотр ScaledObject
kubectl get scaledobject -n default

# Детальная информация
kubectl describe scaledobject rabbitmq-consumer-scaledobject -n default

# Проверка HPA, созданного KEDA
kubectl get hpa -n default

# Метрики KEDA
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1

# Логи KEDA Operator
kubectl logs -n keda -l app=keda-operator --tail=100
```

#### Метрики для мониторинга

| Метрика | Описание |
|---------|----------|
| `keda_scaledobject_status` | Статус ScaledObject (0=error, 1=ready) |
| `keda_scaledobject_ready` | Готовность к масштабированию |
| `keda_external_metrics` | Количество внешних метрик |
| `keda_scaler_active` | Активность scaler'ов |
| `keda_scaling_operations_total` | Количество операций масштабирования |

### Лучшие практики

* **Начните с minReplicaCount > 0** — для production избегайте масштабирования до нуля, если не требуется.
* **Настройте cooldownPeriod** — предотвратите «флаппинг» при частых изменениях нагрузки.
* **Используйте fallback** — для обработки ошибок подключения к источнику метрик.
* **Мониторьте External Metrics** — проверяйте доступность метрик через `kubectl get --raw`.
* **Тестируйте сценарии** — проверяйте масштабирование вверх/вниз перед production.
* **Оптимизируйте pollingInterval** — баланс между реактивностью и нагрузкой на scaler.
* **Используйте TriggerAuthentication** — храните учётные данные в Secret, не в ScaledObject.

## Дополнительная информация

### Интеграции

* **[HPA](hpa_detailed.md)** — KEDA создаёт и управляет HPA, не используйте одновременно для одного Deployment.
* **[Cluster Autoscaler](cluster_autoscaler_detailed.md)** — CA реагирует на поды, созданные KEDA.
* **[Karpenter](karpenter_detailed.md)** — Karpenter создаёт узлы для подов, масштабированных KEDA.
* **[Prometheus](../../Prometheus/overview.md)** — Prometheus как источник метрик для KEDA.

### Ограничения

* **Один ScaledObject на Deployment** — нельзя применить несколько ScaledObject к одному ресурсу.
* **Только Deployment/StatefulSet** — не работает с DaemonSet, Job, CronJob.
* **Задержка масштабирования** — зависит от `pollingInterval` (минимум 5 секунд).
* **Внешние зависимости** — требует доступности источника метрик (RabbitMQ, Kafka, Prometheus).

### Сравнение с нативным HPA

| Характеристика | HPA | KEDA |
|----------------|-----|------|
| Источники метрик | CPU, Memory, Custom, External | 60+ scaler'ов |
| Масштабирование до 0 | Нет | Да |
| Событийное масштабирование | Нет | Да |
| Расписание (Cron) | Нет | Да |
| Сложность настройки | Низкая | Средняя |
| Управление | Прямое | Через HPA |

### Ресурсы

* [Официальная документация KEDA](https://keda.sh/)
* [GitHub репозиторий](https://github.com/kedacore/keda)
* [Список поддерживаемых scaler'ов](https://keda.sh/docs/latest/scalers/)
