# KEDA: Основные концепции

## Определения

**KEDA (Kubernetes Event-driven Autoscaling)** — легковесный оператор Kubernetes для автоматического масштабирования рабочих нагрузок на основе событий из внешних источников. Работает как дополнение к стандартному HPA (Horizontal Pod Autoscaler), расширяя его возможности за счёт поддержки масштабирования до нуля и использования внешних метрик через собственный Metrics API Server.

**ScaledObject** — кастомный ресурс (CRD), определяющий правила масштабирования для долгоживущих объектов: `Deployment`, `StatefulSet` или любого ресурса, реализующего подресурс `/scale` (например, Custom Resources). Содержит ссылку на цель, границы репликации (`minReplicaCount`, `maxReplicaCount`), интервалы опроса и список триггеров.

**ScaledJob** — кастомный ресурс для масштабирования задач типа `Job`. Вместо изменения количества реплик в существующем поде, KEDA создаёт новую Kubernetes Job для каждого поступившего события. Позволяет эффективно обрабатывать длительные задачи, где один под обрабатывает ровно одно сообщение/событие.

**Scaler** — специализированный компонент (адаптер) внутри KEDA, отвечающий за интеграцию с конкретным источником событий (Kafka, RabbitMQ, Prometheus и более 60 других). Скейлер опрашивает источник и возвращает метрики, на основе которых принимается решение о масштабировании.

**Trigger** — описание конкретного условия внутри `ScaledObject` или `ScaledJob`, при котором должно произойти масштабирование. Включает тип скейлера и параметры (например, имя очереди, пороговое значение `triggerThreshold`).

**TriggerAuthentication** — ресурс для безопасного хранения и переиспользования параметров аутентификации (секреты, токены, IAM-роли) при подключении к источникам событий.
- **TriggerAuthentication:** уровень пространства имён (Namespace).
- **ClusterTriggerAuthentication:** глобальный уровень кластера, доступен для всех ресурсов.
*Примечание по безопасности:* Начиная с KEDA v2.15, устаревшие методы аутентификации (например, Azure Pod Identity) полностью удалены. Современным стандартом является использование **Workload Identity** (для AWS, Azure, GCP) и поддержка современных протоколов, таких как OAuth2 (например, для RabbitMQ).

**Fallback** — механизм аварийного переключения. Если источник метрик недоступен, KEDA переводит ресурс в состояние fallback с фиксированным количеством реплик, предотвращая деградацию сервиса. Поведение при срабатывании настраивается через `fallback.behavior`: `static` (всегда `fallback.replicas`), `currentReplicas` (текущее количество реплик), `currentReplicasIfHigher` / `currentReplicasIfLower` (текущее значение, если оно больше/меньше `fallback.replicas`), а начиная с v2.20 — `scalingModifiers` (fallback вычисляется на уровне отдельных триггеров внутри формулы).

**activationThreshold** — порог активации триггера. Определяет минимальное значение метрики, необходимое для «пробуждения» ресурса (перехода 0 -> 1). Позволяет избежать запуска подов при незначительной нагрузке. У конкретных скейлеров параметр может называться иначе (например, `activationValue` у RabbitMQ).

**idleReplicaCount** — количество реплик, которое KEDA удерживает, когда триггеры неактивны. Если нагрузка появляется, KEDA сразу масштабирует объект до `minReplicaCount` (что позволяет реализовать быстрый старт в несколько потоков), а при исчезновении нагрузки возвращается к `idleReplicaCount`. Значение должно быть меньше `minReplicaCount`; из-за ограничений контроллера HPA единственное корректно поддерживаемое значение — 0.

**initialCooldownPeriod** — задержка перед началом отсчета `cooldownPeriod` после создания `ScaledObject` (по умолчанию 0 секунд). Полезна как grace-период, чтобы freshly созданный объект не был немедленно масштабирован до нуля.

### Значения по умолчанию в спецификации ScaledObject

Согласно [официальной спецификации](https://keda.sh/docs/2.20/reference/scaledobject-spec/) (v2.20):

| Параметр | По умолчанию | Комментарий |
| :--- | :--- | :--- |
| `pollingInterval` | 30 секунд | Интервал опроса триггеров, пока реплик 0; от 1 до N реплик опросом управляет также HPA (`--horizontal-pod-autoscaler-sync-period`, по умолчанию 15 сек) |
| `cooldownPeriod` | 300 секунд | Применяется только при масштабировании до 0; масштабированием 1 ↔ N управляет HPA |
| `initialCooldownPeriod` | 0 секунд | Задержка старта cooldown после создания объекта |
| `idleReplicaCount` | игнорируется | Должно быть меньше `minReplicaCount`; поддерживается только значение 0 |
| `minReplicaCount` | 0 | То есть scale-to-zero включен по умолчанию |
| `maxReplicaCount` | 100 | Передается в создаваемый HPA |
| Имя создаваемого HPA | `keda-hpa-{scaled-object-name}` | Переопределяется через `advanced.horizontalPodAutoscalerConfig.name` |

Полезные сопутствующие поля спецификации:

* `advanced.restoreToOriginalReplicaCount` — при удалении `ScaledObject` вернуть Deployment исходное количество реплик (по умолчанию `false` — текущее количество сохраняется);
* аннотация `autoscaling.keda.sh/paused-replicas` и поле `cooldownPeriod` проверяются admission webhooks на корректность (v2.20 добавил валидацию значений `cooldownPeriod` и `pollingInterval`).

**Scaling Modifiers** (новое в v2.20) — логические надстройки над триггерами, позволяющие изменять финальное значение метрики перед передачей в HPA (например, применение формул или объединение нескольких источников с весами).

**Приостановка масштабирования (Pausing)** — возможность временно отключить автоматику KEDA с помощью аннотации `autoscaling.keda.sh/paused: "true"` на объекте `ScaledObject`. Это полезно при проведении технических работ.

## Базовые принципы

### Ключевые возможности

* **Масштабирование до нуля (Scale-to-Zero)** — полная остановка подов при отсутствии нагрузки и автоматический «холодный старт» при появлении первого события.
* **Событийно-ориентированный подход** — реакция не на загрузку ресурсов (CPU/RAM), а на бизнес-события (длина очереди, количество запросов, расписание).
* **Автоматическое управление HPA** — KEDA сама создаёт, настраивает и обновляет объект HPA для каждого `ScaledObject`.
* **Поддержка сложных архитектур** — возможность комбинировать несколько триггеров в одном объекте (логика «MAX» — выбирается наибольшее количество реплик).

### KEDA HTTP Add-on

Отдельным расширением является **HTTP Add-on**, который позволяет масштабировать до нуля рабочие нагрузки на основе входящего HTTP-трафика. 
- **Intercepter:** Перехватывает входящие запросы. Если подов нет (реплик 0), он удерживает запрос в очереди, пока оператор не поднимет первый под.
- **Scaler:** Отправляет метрики о количестве ожидающих запросов в KEDA.
- **Преимущество:** В отличие от стандартных скейлеров, работающих по принципу опроса (polling), HTTP Add-on обеспечивает быструю реакцию на веб-трафик без необходимости использования Service Mesh.

### Архитектура KEDA

Система состоит из трёх основных компонентов:

1. **Operator (Agent)** — отслеживает создание ресурсов KEDA, управляет жизненным циклом HPA и активирует/деактивирует масштабирование. Начиная с версии **v2.18**, оператор использует современный API `events.k8s.io` для записи событий масштабирования, что улучшает диагностику и снижает нагрузку на кластер.
2. **Metrics API Server** — реализует интерфейс `external.metrics.k8s.io`. Транслирует метрики от внешних источников (через скейлеры) в формат, понятный стандартному контроллеру HPA.
3. **Admission Webhooks** — выполняет валидацию конфигураций при применении YAML (проверка синтаксиса триггеров, конфликтов и прав доступа).

### Принцип работы

Процесс масштабирования проходит через следующие этапы:

1. **Мониторинг:** Скейлер опрашивает внешний источник с интервалом `pollingInterval`.
2. **Активация (0 ↔ 1):** Если реплик 0 и появились события, Оператор напрямую обновляет `scale` подресурс цели, создавая первый под.
3. **Горизонтальное масштабирование (1 ↔ N):** Когда запущен хотя бы один под, в дело вступает нативный HPA. Он запрашивает метрики у KEDA Metrics Server и принимает решение о репликации.
4. **Стабилизация:** После исчезновения нагрузки KEDA ожидает в течение `cooldownPeriod` перед тем, как снова уменьшить количество реплик до `minReplicaCount` (включая 0).

```text
┌──────────────┐      ┌─────────────┐      ┌─────────────┐      ┌──────────┐
│   Внешний    │ ◀─── │ KEDA Scaler │ ───▶ │   KEDA     │ ───▶ │   HPA    │
│   источник   │      │ (метрики)   │      │  Operator  │      │          │
└──────────────┘      └─────────────┘      └─────────────┘      └────┬─────┘
                                                                     │
                                                                     ▼
                                                              ┌─────────────┐
                                                              │ Workload    │
                                                              │ (Pod/Job)   │
                                                              └─────────────┘
```

## Типы скейлеров

KEDA поддерживает более 60 типов источников, разделенных по категориям:

* **Очереди и стриминг:** Kafka, RabbitMQ, NATS, AWS SQS, Azure Service Bus, Google Pub/Sub.
* **Базы данных:** PostgreSQL, MySQL, Redis, MongoDB, Cassandra.
* **Мониторинг и логи:** Prometheus, Datadog, Grafana Loki, OpenSearch, AWS CloudWatch.
* **Облачные ресурсы:** Скейлинг на основе состояния других ресурсов K8s (**Kubernetes Resource Scaler**) или специфичных API облачных провайдеров.
* **Расписание:** Cron (масштабирование в заданные временные окна).

Полный актуальный список доступен в [официальной документации](https://keda.sh/docs/latest/scalers/).

## Практические сценарии

### Базовые примеры конфигурации

Прикладные материалы вынесены в отдельные файлы:

* [KEDA: Практические сценарии](./practical_scenarios.md) — примеры конфигурации для различных сценариев (RabbitMQ, Prometheus, cron, StatefulSet)
* [KEDA + Kafka](./kafka-keda-scaler.md) — масштабирование по consumer lag, аутентификация (SASL, mTLS)
* [KEDA + Redis](./redis-keda-scaler.md) — масштабирование по длине списка/стрима
* [KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md) — диагностика, алерты, типовые проблемы
* [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md) — финансовая сторона: scale-to-zero, лимиты, пилот и замер эффекта
* [KEDA: Тестирование и валидация](./keda-testing-validation.md) — проверка масштабирования, chaos-тестирование, cold start
* [KEDA: Вопросы для собеседования](./keda-interview-questions.md) — систематизация вопросов по KEDA

### Минимальный ScaledObject

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-worker
  namespace: app
spec:
  scaleTargetRef:
    name: orders-worker  # Deployment для масштабирования
  minReplicaCount: 0     # scale-to-zero
  maxReplicaCount: 10    # финансовый лимит
  triggers:
    - type: rabbitmq
      metadata:
        host: amqp://user:pass@rabbitmq:5672/
        queueName: orders
        queueLength: "10"  # масштабировать при 10+ сообщениях
```

### ScaledJob для batch-задач

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: batch-processor
  namespace: app
spec:
  jobTargetRef:
    template:
      spec:
        containers:
          - name: processor
            image: batch-processor:latest
            command: ["python", "process.py"]
        restartPolicy: Never
  triggers:
    - type: rabbitmq
      metadata:
        host: amqp://user:pass@rabbitmq:5672/
        queueName: batch-tasks
        queueLength: "5"
```

## Дополнительная информация

### Наблюдаемость (Observability)

* **OpenTelemetry:** KEDA поддерживает нативную выгрузку собственных метрик и трейсов через протокол OTLP, что позволяет детально анализировать задержки масштабирования.
* **Prometheus Metrics:** Оператор предоставляет эндпоинт `/metrics` с показателями состояния ScaledObjects, активных скейлеров и ошибок подключения.

### Интеграции с экосистемой

* **Cluster Autoscaler / Karpenter:** KEDA инициирует создание подов, а автоскейлеры узлов (особенно Karpenter) оперативно подготавливают инфраструктуру. Это критически важно для **AI/ML нагрузок**, где использование дорогих GPU-ресурсов должно быть строго лимитировано временем фактической обработки задач из очереди.
* **Service Mesh:** При использовании KEDA с Istio или Linkerd необходимо учитывать особенности работы `scale-to-zero` (например, время готовности sidecar-контейнеров).

### Ограничения и рекомендации

* **Конфликты HPA:** Никогда не создавайте вручную объект HPA для ресурса, который уже управляется KEDA.
* **Polling Interval:** Слишком частые опросы (менее 5-10 сек) могут создать избыточную нагрузку на внешний источник (например, на базу данных).
* **Cold Start:** Учитывайте время запуска приложения при масштабировании из нуля. Если задержка критична, установите `minReplicaCount: 1`.
* **Scale-to-zero не обнуляет счет:** при отсутствии реплик перестают потребляться только вычислительные ресурсы самого workload. Control plane, системные компоненты, ноды, диски, логи и сеть продолжают стоить денег. Экономия касается конкретного workload, а не кластера целиком.

### Когда KEDA не нужен

KEDA — не универсальное решение. Сценарии, где он избыточен:

* **Стабильная нагрузка 24/7.** Если сервис всегда держит 10 реплик и нагрузка не меняется — достаточно HPA по CPU.
* **Stateful workloads (базы данных).** Scale-to-zero для PostgreSQL — плохая идея (долгий startup, потеря кеша, state). Часто лучше вертикальное масштабирование (VPA, более крупные ноды).
* **Очень короткие задачи (< 1 секунды).** Если задача выполняется за 100 мс, overhead на создание пода (5–15 сек) слишком велик. Лучше держать `minReplicaCount` или использовать serverless-платформы (Knative, Lambda).
* **Критичные сервисы с SLA < 1 секунды.** Cold start не укладывается в такие SLA — нужен постоянный warm pool.

### KEDA в on-premise / bare-metal окружениях

KEDA полностью cloud-agnostic и работает в любом Kubernetes: on-premise (kubeadm, Kubespray, RKE2), bare-metal, edge. Ключевое требование — доступность источника метрик.

**Скейлеры, работающие без облака:**

| Скейлер | Источник метрик | Примечание |
|:---|:---|:---|
| `rabbitmq` | RabbitMQ Management API | Прямое подключение, AMQP/HTTP |
| `kafka` | Kafka Broker | Прямое подключение, SASL/TLS |
| `prometheus` | Prometheus | Любой Prometheus (внутренний) |
| `cron` | Расписание | Не требует внешних источников |
| `redis` / `redis-streams` | Redis | Прямое подключение |
| `kubernetes-resource` | ConfigMap/Secret | K8s API |

**Скейлеры, требующие облако (НЕ работают в on-prem):**

| Скейлер | Провайдер |
|:---|:---|
| `aws-sqs` | AWS |
| `aws-cloudwatch` | AWS |
| `azure-servicebus` | Azure |
| `azure-queue` | Azure |
| `gcp-pubsub` | GCP |

**Особенности on-premise развёртывания:**

1. **Prometheus как центральный источник метрик:** в on-prem рекомендуется использовать Prometheus scaler вместо прямых подключений к Kafka/RabbitMQ — это упрощает аутентификацию и centralizes метрики.

2. **Сетевая доступность:** `serverAddress` Prometheus scaler должен быть доступен с подов KEDA Operator. В on-prem это通常 решается через ClusterIP Service.

3. **Отсутствие Workload Identity:** в on-prem нет IAM-ролей, поэтому аутентификация через Kubernetes Secrets + TriggerAuthentication.

4. **Cluster Autoscaler:** в on-prem используется Cluster Cluster Autoscaler с Cluster API или Metal3 вместо Karpenter (Karpenter только для EKS/AKS).

```yaml
# Пример on-premise: KEDA + RabbitMQ + Prometheus (без облака)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: onprem-worker-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring:9090   # ClusterIP Service
        query: sum(rabbitmq_queue_messages{queue="tasks"})
        threshold: "10"
```

### Поддержка версий

По [release policy](https://github.com/kedacore/governance/blob/main/RELEASES.md) проекта одновременно поддерживаются две последние минорные версии. На август 2026 актуальны ветки 2.20 (последний патч 2.20.2) и 2.19; ветка 2.18 достигла EOL в июне 2026. При обновлении с версий < 2.20 необходимо учитывать upgrade notes релиза 2.20.0.

### Когда стандартного HPA недостаточно

Horizontal Pod Autoscaler обычно воспринимается как базовый ответ на вопрос «как масштабировать поды». В типовом сценарии он принимает решения по CPU и памяти, но не вся нагрузка проявляется через эти метрики.

Пример: воркер, который разбирает сообщения из очереди, может почти не грузить CPU, потому что ждет новые сообщения или ответа от внешнего API. При этом очередь уже растет, время обработки увеличивается, SLA начинает проседать:

```text
CPU: 2%          Queue length: 3250 messages
Memory: stable   Oldest message age: 18 minutes
Replicas: 2      SLA: at risk
```

Если в этот момент масштабироваться только по CPU, реакция будет запаздывать. Если держать большой резерв подов постоянно, команда платит за мощность, которая большую часть времени простаивает (over-provisioning).

Финансовая сторона этого вопроса (scale-to-zero как механика экономии, выбор `maxReplicaCount`, методика замера эффекта) подробно разобрана в материале [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md).

### Сравнение KEDA и стандартного HPA

| Характеристика | Стандартный HPA | KEDA |
| :--- | :--- | :--- |
| **Масштабирование до 0** | Не поддерживается (минимум 1) | Полноценная поддержка |
| **Источники метрик** | В основном CPU/RAM кластера | 60+ внешних источников + кастомные |
| **Механизм работы** | Опрос Metrics API | Реакция на события + External Metrics API |
| **Типы нагрузок** | Deployment, StatefulSet | + Jobs, Custom Resources |
| **Сложная логика** | Ограничена базовыми порогами | Scaling Modifiers, Fallback, Multiple Triggers |

## Жизненный цикл ScaledObject

### Этапы работы

```text
1. Создание ScaledObject
   → Admission Webhook валидирует конфигурацию
   → KEDA Operator создаёт HPA
   → HPA запрашивает метрики у Metrics Server

2. Ожидание событий (replicas = 0)
   → Scaler опрашивает источник с pollingInterval
   → Если метрика < activationThreshold → нет масштабирования
   → Если метрика >= activationThreshold → переход к шагу 3

3. Масштабирование 0 → 1
   → KEDA Operator напрямую обновляет scale deployment
   → Первый под запускается
   → HPA начинает управление

4. Масштабирование 1 ↔ N
   → HPA запрашивает метрики у Metrics Server
   → Рассчитывает desired replicas: ceil(currentReplicas * (targetValue / currentMetricValue))
   → Масштабирует workload

5. Scale-down
   → После исчезновения нагрузки
   → Ожидание cooldownPeriod (по умолчанию 300 сек)
   → Возврат к minReplicaCount (включая 0)
```

### Обработка ошибок скейлеров

KEDA реализует механизм fallback для обработки ошибок получения метрик:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: resilient-worker
spec:
  scaleTargetRef:
    name: worker
  fallback:
    failureThreshold: 3      # количество ошибок до fallback
    replicas: 3              # количество реплик в fallback-режиме
    behavior: static         # статическое количество реплик
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        query: rate(http_requests_total[5m])
        threshold: "100"
```

**Поведение при fallback:**

```text
1. Scaler возвращает ошибку 3 раза подряд (failureThreshold)
2. KEDA переключается в fallback-режим
3. Устанавливает количество реплик = fallback.replicas
4. Продолжает опрашивать источник
5. При восстановлении связи — возврат к нормальной работе
```

**Варианты поведения fallback:**

```text
static            — всегда fallback.replicas
currentReplicas   — текущее количество реплик
currentReplicasIfHigher — текущее, если оно больше fallback.replicas
currentReplicasIfLower  — текущее, если оно меньше fallback.replicas
```

### Обработка нескольких триггеров

KEDA поддерживает несколько триггеров в одном ScaledObject. Логика масштабирования — MAX (максимальное значение среди всех триггеров):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: multi-trigger-worker
spec:
  scaleTargetRef:
    name: worker
  minReplicaCount: 0
  maxReplicaCount: 20
  triggers:
    - type: rabbitmq
      metadata:
        host: amqp://user:pass@rabbitmq:5672/
        queueName: orders
        queueLength: "10"
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 9 * * 1-5
        end: 0 18 * * 1-5
        desiredReplicas: "5"
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        query: sum(rate(http_requests_total[5m]))
        threshold: "100"
```

**Пример расчёта:**

```text
RabbitMQ триггер: 25 сообщений / 10 = 2.5 → 3 реплики
Cron триггер: 5 реплик (активен)
Prometheus триггер: 200 RPS / 100 = 2 реплики

Итого: MAX(3, 5, 2) = 5 реплик
```

## Ресурсы и производительность KEDA

### Требования к ресурсам компонентов

| Компонент | CPU (requests) | Memory (requests) | CPU (limits) | Memory (limits) |
| :--- | :--- | :--- | :--- | :--- |
| keda-operator | 100m | 128Mi | 500m | 512Mi |
| keda-metrics-apiserver | 100m | 128Mi | 500m | 512Mi |
| keda-admission-webhooks | 50m | 64Mi | 250m | 256Mi |

### Влияние pollingInterval на нагрузку

```text
При pollingInterval = 30 сек (по умолчанию):
  100 ScaledObject × 30 сек = 3.3 опроса/сек
  Нагрузка на внешние источники: минимальная

При pollingInterval = 5 сек:
  100 ScaledObject × 5 сек = 20 опросов/сек
  Нагрузка на внешние источники: значительная

Рекомендация:
  - Для большинства сценариев: 15-30 сек
  - Для критичных сервисов: 5-10 сек (с осторожностью)
  - Для batch-задач: 30-60 сек
```

### Оптимизация производительности

```yaml
# Оптимизация для высоконагруженных кластеров
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: high-load-worker
  annotations:
    autoscaling.keda.sh/polling-interval: "15"  # увеличенный интервал
spec:
  scaleTargetRef:
    name: worker
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 600
          policies:
          - type: Pods
            value: 1
            periodSeconds: 60
        scaleUp:
          stabilizationWindowSeconds: 0
          policies:
          - type: Percent
            value: 100
            periodSeconds: 15
```

## Безопасность и сетевая политика

### RBAC для KEDA

KEDA требует определённые разрешения для работы:

```yaml
# ClusterRole для KEDA Operator
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: keda-operator
rules:
  - apiGroups: ["keda.sh"]
    resources: ["scaledobjects", "scaledjobs", "triggerauthentications", "clustertriggerauthentications"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
```

### Сетевая политика для KEDA

```yaml
# Разрешить доступ KEDA к Prometheus
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: keda-to-prometheus
  namespace: keda
spec:
  podSelector:
    matchLabels:
      app: keda-operator
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
```

### Безопасное хранение секретов

```yaml
# Использование Vault через External Secrets Operator
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keda-rabbitmq-credentials
  namespace: app
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: rabbitmq-credentials
    creationPolicy: Owner
  data:
    - secretKey: host
      remoteRef:
        key: secret/data/rabbitmq
        property: host
    - secretKey: password
      remoteRef:
        key: secret/data/rabbitmq
        property: password
```

## Интеграция с другими контроллерами Kubernetes

### KEDA + Cluster Autoscaler

```text
Взаимодействие:
1. KEDA масштабирует поды (HPA)
2. Cluster Autoscaler видит pending поды
3. Cluster Autoscaler добавляет ноды
4. При scale-to-zero: KEDA удаляет поды
5. Cluster Autoscaler видит пустые ноды
6. Cluster Autoscaler удаляет ноды

Важно:
- Настройте --scale-down-delay-after-add для избежания "пинг-понга"
- Используйте --max-node-provision-time для долгих cloud-инстансов
```

### KEDA + Karpenter

```yaml
# Karpenter NodePool для KEDA workload
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: keda-optimized
spec:
  template:
    spec:
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["on-demand", "spot"]
        - key: "node.kubernetes.io/instance-type"
          operator: In
          values: ["m5.large", "m5.xlarge", "m5.2xlarge"]
      nodeClassRef:
        name: default
  limits:
    cpu: 100
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 30s
```

### KEDA + Pod Disruption Budget

```yaml
# PDB для защиты availability при scale-down
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: worker-pdb
  namespace: app
spec:
  minAvailable: 1  # или maxUnavailable: 1
  selector:
    matchLabels:
      app: orders-worker
```

## Частые вопросы

**KEDA заменяет HPA?**

Нет, дополняет. KEDA создает HPA под капотом и передает ему external metrics через собственный Metrics API Server. HPA управляет количеством реплик, KEDA — источником метрик.

**Что будет, если KEDA упадет?**

HPA продолжит работать с последней известной метрикой. При этом новые ScaledObject не создадутся, метрики перестанут обновляться, а workload останется на текущем количестве реплик до восстановления KEDA. Поэтому состояние подов `keda-operator` и `keda-metrics-apiserver` должно быть под мониторингом.

**Можно ли использовать на stateful workloads (базы данных)?**

С осторожностью. Scale-to-zero для production-мастера БД — плохая идея. При этом масштабирование read-replica по нагрузке или опускание dev-окружений с БД на ночь — допустимые сценарии.

**Работает ли в on-premise Kubernetes?**

Да, KEDA не привязан к облаку и работает в любом Kubernetes (on-premise, cloud, edge). Главное требование — доступность источника метрик (RabbitMQ, Prometheus и т.д.).

**Сколько стоит KEDA?**

Open source, бесплатно (лицензия Apache 2.0). Платить приходится только за инфраструктуру (compute, storage, network), на которой он работает.

**Можно ли комбинировать несколько триггеров?**

Да, ScaledObject поддерживает несколько triggers — например, масштабирование по очереди и по расписанию одновременно. HPA масштабирует по максимальному результату среди всех триггеров.

**Как откатиться, если KEDA сломал работу сервиса?**

```bash
# 1. Удалить ScaledObject (созданный им HPA удалится тоже)
kubectl delete scaledobject <name> -n <namespace>

# 2. Вернуть фиксированное количество реплик
kubectl scale deployment/<name> --replicas=5 -n <namespace>

# 3. Или применить старый манифест Deployment
kubectl apply -f deployment-before-keda.yaml
```

Важно держать backup манифестов до внедрения KEDA.

## См. также

* [KEDA: Практические сценарии](./practical_scenarios.md) — установка, триггеры, мониторинг, troubleshooting
* [KEDA + Kafka](./kafka-keda-scaler.md) — масштабирование по consumer lag
* [KEDA + Redis](./redis-keda-scaler.md) — масштабирование по длине очереди/стрима
* [KEDA: Эксплуатация](./keda-operations.md) — диагностика и алерты
* [KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md) — scale-to-zero, maxReplicaCount, замер эффекта
* [KEDA: Тестирование и валидация](./keda-testing-validation.md) — проверка масштабирования
* [KEDA: Вопросы для собеседования](./keda-interview-questions.md) — систематизация вопросов
* [HPA: Горизонтальное масштабирование](../HPA/index.md)
* [Cluster Autoscaler: Масштабирование кластера](../cluster_autoscaler_detailed.md)
* [Обзор и концепции Karpenter](../Karpenter/overview.md)
