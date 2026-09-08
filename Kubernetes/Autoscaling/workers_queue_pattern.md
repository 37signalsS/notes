# Архитектурный паттерн «Воркеры + Очередь»

Паттерн «Воркеры + Очередь» (Workers + Queue) является фундаментальным решением для реализации [событийно-ориентированной архитектуры (EDA)](../../Concepts/event-driven-architecture.md) в распределенных системах. Он позволяет изолировать (decouple) процесс генерации задач от процесса их выполнения, обеспечивая эластичность, отказоустойчивость и защиту системы от лавинообразных всплесков нагрузки (Thundering Herd).

## Определения

*   **Workers + Queue** — архитектурный паттерн, в котором количество вычислительных узлов (воркеров) динамически масштабируется в зависимости от глубины (количества сообщений) очереди.
*   **Producer (Производитель)** — сервис, генерирующий задачи и помещающий их в брокер сообщений.
*   **Consumer (Потребитель / Worker)** — под (Pod) в Kubernetes, который извлекает сообщения из очереди, выполняет бизнес-логику и возвращает подтверждение (ACK).
*   **Идемпотентность** — свойство операции, гарантирующее, что многократная обработка одной и той же задачи (например, из-за сетевого сбоя при ACK) не приведет к дублированию или искажению данных.
*   **Dead Letter Queue (DLQ)** — специализированная "очередь мертвых писем", куда маршрутизируются сообщения, которые не удалось обработать после `N` попыток (Poison Pills).
*   **Graceful Shutdown** — механизм перехвата сигнала завершения (`SIGTERM`), позволяющий воркеру закончить обработку текущей задачи и корректно освободить ресурсы перед физическим уничтожением контейнера.
*   **Visibility Timeout** — время, в течение которого сообщение остается "невидимым" для других консьюмеров после извлечения одним из них. Если ACK не получен за это время, сообщение снова становится доступным для обработки.
*   **Poison Pill (Отравленная таблетка)** — сообщение, которое стабильно вызывает ошибку при обработке (ошибка десериализации, нарушение контракта), блокируя обработку очереди.

## Предварительные требования

### Версии и компоненты

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
|:---|:---|:---|:---|
| Kubernetes | 1.23+ | 1.28+ | Для стабильной работы KEDA и HPA v2 |
| KEDA | 2.10+ | 2.12+ | Для ScaledObject и Scale-to-Zero |
| Metrics Server | 0.6+ | 0.7+ | Для стандартного HPA (если используется) |

### Требования к окружению

Перед внедрением паттерна убедитесь в наличии:

1. **KEDA установлен в кластере:**
   ```bash
   kubectl get pods -n keda
   # → keda-operator-xxx   1/1  Running
   # → keda-operator-metrics-apiserver-xxx  1/1  Running
   ```

2. **Брокер сообщений доступен из подов:**
   ```bash
   # Проверка доступности RabbitMQ
   kubectl run -it --rm debug --image=alpine/curl --restart=Never -- \
     curl -s http://rabbitmq-service:15672/api/healthchecks/memory
   ```

3. **ResourceQuota не блокирует создание подов:**
   ```bash
   kubectl describe resourcequota -n <namespace>
   # Проверьте, что лимиты позволяют масштабирование до maxReplicaCount
   ```

### Интеграция с ResourceQuota

При использовании KEDA с `minReplicaCount: 0` учитывайте:

*   При масштабировании ResourceQuota с `request.cpu` и `request.memory` должна позволять запуск подов до `maxReplicaCount`.
*   `LimitRange` может устанавливать дефолтные лимиты, которые могут конфликтовать с ресурсами воркеров.

## Основные концепции

### Задачи, решаемые паттерном

1.  **Сглаживание пиковых нагрузок (Buffering):** Очередь принимает на себя ударный трафик, позволяя воркерам разбирать его в предсказуемом темпе без перегрузки баз данных.
2.  **Асинхронность:** Producer не ждет завершения тяжелой задачи (например, генерации отчета или транскодинга видео), а сразу отвечает клиенту `202 Accepted`.
3.  **Эластичное масштабирование:** В ночные часы количество воркеров может падать до нуля (Scale-to-Zero), экономя ресурсы.
4.  **Гарантированная обработка (At-least-once):** Если воркер падает (OOMKilled, Evicted), сообщение возвращается в очередь по таймауту (Visibility Timeout) и подхватывается другим подом.

### Жизненный цикл задачи (State Machine)

1.  **Enqueued** (В очереди) — сообщение ждет обработки.
2.  **In-Flight** (В обработке) — воркер забрал сообщение. Оно становится "невидимым" для других на время таймаута (Visibility Timeout / Lock).
3.  **Acknowledged (ACK)** — задача успешно выполнена, сообщение удаляется из брокера.
4.  **Negative Acknowledged (NACK)** — воркер явно сообщил об ошибке (например, БД временно недоступна). Сообщение мгновенно возвращается в очередь (Enqueued).
5.  **Dead-Lettered** — превышен лимит попыток обработки (Max Delivery Attempts). Сообщение перемещается в DLQ.

### Проблематика и требования к Worker'ам

| Проблема | Решение |
| :--- | :--- |
| **Poison Pill** (задача, вызывающая краш) | Обязательная настройка DLQ и лимита попыток (Max Retries). |
| **Зомби-воркеры** (зависание процесса) | Внутренние Timeout в коде приложения + Liveness Probes. |
| **Дублирование задач** | Идемпотентность логики + дедупликация на стороне брокера. |
| **Потеря задач при деплое** | Обработка SIGTERM и настройка `terminationGracePeriodSeconds`. |

---

## Интеграция с инфраструктурой Kubernetes

Для надежной работы паттерна в K8s требуется комплексная настройка оркестрации:

*   **Автоскейлинг:** Используется **[KEDA (Kubernetes Event-driven Autoscaling)](./keda/keda_concepts.md)**, так как стандартный HPA плохо работает с внешними метриками (очередями) и не умеет масштабировать до нуля.
*   **Отказоустойчивость:** [Pod Disruption Budget (PDB)](./pod_disruption_budget.md) защищает от потери всех воркеров при плановом обслуживании узлов.
*   **Изоляция:** [Topology Spread Constraints](../Scheduling/affinity.md) размазывает воркеры по разным стойкам/зонам доступности.
*   **Приоритизация:** Для критических воркеров (например, обработка платежей) используются [PriorityClasses](../Scheduling/qos_limit_and_requests.md), чтобы Cluster Autoscaler выселял менее важные поды при нехватке места.

---

## Практические сценарии

### Сценарий 1: Корректное завершение (Graceful Shutdown)

Это **критически важный** манифест. Если воркер обрабатывает задачу 2 минуты, а K8s убьет его через стандартные 30 секунд, задача прервется и будет обрабатываться заново.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: heavy-report-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: report-worker
  template:
    metadata:
      labels:
        app: report-worker
    spec:
      # ВАЖНО: Даем поду 5 минут на завершение текущей генерации отчета
      terminationGracePeriodSeconds: 300 
      containers:
        - name: worker
          image: my-worker:1.2.0
          # ВАЖНО: Приложение должно перехватывать SIGTERM и перестать 
          # брать новые задачи из очереди, доделывая текущую.
          lifecycle:
            preStop:
              exec:
                # Fallback, если приложение не умеет корректно обрабатывать SIGTERM
                command: ["/bin/sh", "-c", "sleep 10 && ./stop-worker-gracefully.sh"]
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
```

**Важно:** `terminationGracePeriodSeconds` должен учитывать:
*   Максимальное время обработки одной задачи
*   Visibility Timeout брокера (чтобы задача не ушла другому консьюмеру до завершения текущего)
*   Время на освобождение ресурсов (закрытие соединений с БД, запись чекпоинтов)

### Сценарий 2: Эластичное масштабирование через KEDA (RabbitMQ)

Рекомендуемый подход для микросервисов. Масштабирование происходит на основе длины очереди, а не нагрузки на CPU.

```yaml
# 1. Задаем лимиты и базовые настройки воркера
apiVersion: apps/v1
kind: Deployment
metadata:
  name: image-processor
spec:
  replicas: 0 # Базовое значение, KEDA переопределит его
  selector:
    matchLabels:
      app: image-processor
  template:
    metadata:
      labels:
        app: image-processor
    spec:
      containers:
      - name: processor
        image: image-processor:v2
---
# 2. Настраиваем объект KEDA
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-processor-scaler
spec:
  scaleTargetRef:
    name: image-processor
  pollingInterval: 15     # Как часто KEDA проверяет очередь
  cooldownPeriod:  300    # Ждем 5 минут перед сжатием в 0
  minReplicaCount: 0      # Scale-to-Zero (экономия ресурсов)
  maxReplicaCount: 50     # Лимит масштабирования
  triggers:
    - type: rabbitmq
      metadata:
        queueName: process-images
        mode: QueueLength
        value: "20"       # 1 новый под на каждые 20 сообщений в очереди
        hostFromEnv: RABBITMQ_URI # Берет URL из ENV пода
```

**Проверка работы:**
```bash
# Проверить статус ScaledObject
kubectl get scaledobject rabbitmq-processor-scaler
# → NAME                           TARGET       TRIGGERS   AUTHENTICATION   READY   ACTIVE   FALLBACK   AGE
# → rabbitmq-processor-scaler      Deployment   rabbitmq                    True    True                5m

# Проверить текущее количество реплик
kubectl get deployment image-processor
```

### Сценарий 3: ScaledJob для изолированных/длительных задач

Для задач, которые требуют жесткой изоляции (утечки памяти в legacy коде) или выполняются часами (рендер 3D), используется `ScaledJob` из арсенала KEDA. Одна задача = один Pod, который умирает после завершения.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: video-transcoder
spec:
  jobTargetRef:
    parallelism: 1
    template:
      spec:
        containers:
        - name: ffmpeg
          image: transcoder:v4
        restartPolicy: Never # В случае падения задача вернется в очередь по таймауту
  pollingInterval: 30
  successfulJobsHistoryLimit: 5 # Хранить 5 успешных логов
  failedJobsHistoryLimit: 5     # Хранить 5 упавших логов
  triggers:
  - type: rabbitmq
    metadata:
      queueName: transcode-tasks
      mode: QueueLength
      value: "1" # Одна Job на каждое сообщение
```

### Сценарий 4: Долгая задача с уведомлением пользователя

Типовая ситуация: пользователь загружает файл (книгу, отчёт, датасет), а обработка занимает 10–15 минут. Синхронно отдать результат невозможно в принципе: HTTP-соединение рвётся по таймаутам балансировщиков и прокси (обычно 30–60 секунд), а заставлять пользователя обновлять страницу вручную (F5) — плохой UX и лишняя нагрузка.

Решение: API принимает файл, ставит задачу в очередь и немедленно отвечает `202 Accepted` с идентификатором задачи. О готовности пользователь узнаёт через отдельный канал:

*   **WebSocket / SSE** — если пользователь ждёт результат на странице: статус задачи пушится в браузер;
*   **Email / push** — если результат забирают позже: ссылка на готовый файл в объектном хранилище;
*   **Личный кабинет / список задач** — состояние проверяется повторным запросом `GET /tasks/{id}`.

Итоговая композиция сервиса «текст → электронная книга» (обработка ~15 минут на книгу):

```text
Браузер ──> Веб-фронтенд + API (Producer)
                │  файлы пользователя и результаты ──> S3
                │  метаданные задач и учётные записи ──> БД
                │  задача ──> Брокер сообщений ──> Воркеры (Consumer, тяжёлый процессинг)
                └──> Сервис уведомлений (WebSocket/email) <── событие "задача готова"
```

Масштабирование воркеров — по глубине очереди через KEDA (см. Сценарий 2), для изоляции падучих задач — ScaledJob (см. Сценарий 3). Отказоустойчивость обеспечивается идемпотентностью обработки и возвратом задачи в очередь при падении воркера.

### Сценарий 5: Обработка Poison Pills и настройка DLQ

**Проблема:** Сообщение с невалидными данными вызывает ошибку при каждой попытке обработки. Без DLQ оно будет бесконечно возвращаться в очередь, блокируя обработку других сообщений.

**Решение для RabbitMQ:**

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: Queue
metadata:
  name: orders-processing
spec:
  name: orders-processing
  type: quorum
  durable: true
  arguments:
    # Настройка DLQ
    x-dead-letter-exchange: ""
    x-dead-letter-routing-key: "orders-processing-dlq"
    # Максимальное количество попыток до перемещения в DLQ
    x-delivery-limit: 5
---
apiVersion: rabbitmq.com/v1beta1
kind: Queue
metadata:
  name: orders-processing-dlq
spec:
  name: orders-processing-dlq
  type: quorum
  durable: true
```

**Мониторинг DLQ:**
```bash
# Проверка количества сообщений в DLQ
kubectl exec -it rabbitmq-server-0 -- \
  rabbitmqctl list_queues name messages | grep dlq
# → orders-processing-dlq  15

# Извлечение и анализ Poison Pill (без обработки)
kubectl exec -it rabbitmq-server-0 -- \
  rabbitmqctl get_queue orders-processing-dlq count=1 ackmode=requeue_true
```

**Рекомендации:**
*   Настройте алерт при появлении сообщений в DLQ (`DLQ Message Count > 0`)
*   Регулярно анализируйте содержимое DLQ для выявления системных проблем в коде
*   При необходимости реализуйте "ручную обработку" — возможность повторно отправить сообщение из DLQ в основную очередь после исправления ошибки

### Сценарий 6: Идемпотентность обработки

Поскольку гарантия доставки — at-least-once, задача может быть обработана несколько раз (при падении воркера до ACK, при сетевых сбоях). Реализация идемпотентности:

**Подход 1: Дедупликация по ID сообщения**

```python
import redis

redis_client = redis.Redis(host='redis-service', port=6379)

def process_message(message_id, payload):
    # Проверяем, была ли задача уже обработана
    if redis_client.get(f"processed:{message_id}"):
        print(f"Task {message_id} already processed, skipping")
        return  # ACK будет отправлен, задача не вернется
    
    # Обработка задачи
    result = do_work(payload)
    
    # Сохраняем результат и помечаем как обработанное
    redis_client.setex(
        f"processed:{message_id}",
        86400 * 7,  # TTL 7 дней
        "done"
    )
```

**Подход 2: Идемпотентные операции в БД**

```sql
-- INSERT с проверкой уникальности
INSERT INTO orders (external_id, data, status)
VALUES (%s, %s, 'processing')
ON CONFLICT (external_id) DO NOTHING;

-- Проверка, была ли вставка
SELECT xmax = 0 AS is_inserted FROM orders WHERE external_id = %s;
```

### Сценарий 7: Health Checks для воркеров

**Проблема:** Воркер "зав" (зомби-процесс), K8s не знает об этом и не перезапускает под.

**Решение: Комбинация Liveness и Readiness Probes**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-worker
spec:
  template:
    spec:
      containers:
      - name: worker
        image: worker:latest
        # Liveness: Перезапуск зависшего пода
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "worker-healthcheck.sh"
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3
        # Readiness: Не принимать сообщения, если БД недоступна
        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "check-db-connection.sh"
          initialDelaySeconds: 5
          periodSeconds: 5
        # Startup: Для медленного старта (загрузка моделей, миграции)
        startupProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - "check-worker-ready.sh"
          failureThreshold: 30
          periodSeconds: 10
```

**Скрипт healthcheck (`worker-healthcheck.sh`):**
```bash
#!/bin/sh
# Проверяем, что воркер обрабатывает задачи (не завис)
LAST_ACTIVITY=$(cat /tmp/last_activity_timestamp 2>/dev/null || echo 0)
NOW=$(date +%s)
DIFF=$((NOW - LAST_ACTIVITY))

# Если нет активности больше 10 минут — воркер завис
if [ $DIFF -gt 600 ]; then
  echo "Worker stuck, last activity: $LAST_ACTIVITY"
  exit 1
fi
exit 0
```

### Сценарий 8: Backpressure и ограничение нагрузки

**Проблема:** Воркер не справляется с нагрузкой, что приводит к:
*   Исчерпанию соединений с БД
*   Росту задержки обработки
*   OOMKilled

**Решение 1: Ограничение Prefetch (RabbitMQ)**

```python
import pika

channel = connection.channel()
# Ограничиваем количество неподтвержденных сообщений
channel.basic_qos(prefetch_count=10)
```

**Решение 2: Fallback в KEDA**

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: safe-worker-scaler
spec:
  scaleTargetRef:
    name: worker
  minReplicaCount: 1
  maxReplicaCount: 20
  fallback:
    failureThreshold: 3
    replicas: 5  # При ошибке получения метрик держим минимум 5 реплик
  triggers:
    - type: rabbitmq
      metadata:
        queueName: tasks
        mode: QueueLength
        value: "20"
```

**Решение 3: Внутренняя очередь в воркере**

```python
import asyncio

# Ограничиваем параллельную обработку внутри одного пода
semaphore = asyncio.Semaphore(5)  # Максимум 5 задач параллельно

async def process_with_semaphore(message):
    async with semaphore:
        await process_message(message)
```

---

## Мониторинг и метрики (SRE Опыт)

Для надежной работы паттерна необходимо настроить алерты по следующим метрикам:

1.  **Consumer Lag / Queue Depth:** Основной индикатор здоровья. Если очередь растет, а `maxReplicaCount` достигнут, система не справляется (Under-provisioned).
2.  **Processing Latency (Duration):** Время от взятия задачи до ACK (p95, p99). Рост задержки говорит о деградации БД или внешнего API.
3.  **DLQ Message Count:** Метрика качества данных/кода. Рост DLQ означает появление задач, которые стабильно вызывают ошибки (Poison Pills).
4.  **Worker Restart Rate:** Если поды часто перезапускаются (`OOMKilled`), это приводит к постоянным возвратам задач в очередь и дублированию усилий.

### Пrometheus-метрики и алерты

```yaml
# Правила алертов
groups:
  - name: workers_queue_alerts
    rules:
      # Очередь растет, воркеры не справляются
      - alert: QueueBacklogGrowing
        expr: rate(rabbitmq_queue_messages[5m]) > 0 and keda_scaledobject_replicas == keda_scaledobject_max_replicas
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Queue {{ $labels.queue }} backlog growing, max replicas reached"
          
      # Воркер уперся в maxReplicaCount
      - alert: KEDAMaxReplicasReached
        expr: keda_scaledobject_replicas >= keda_scaledobject_max_replicas
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "ScaledObject {{ $labels.scaledobject }} reached maxReplicaCount"
          
      # Появились сообщения в DLQ
      - alert: DLQMessagesDetected
        expr: rabbitmq_queue_messages{queue=~".*-dlq"} > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Messages in DLQ {{ $labels.queue }}: {{ $value }}"
          
      # Высокий rate перезапусков подов
      - alert: WorkerHighRestartRate
        expr: rate(kube_pod_container_status_restarts_total{container="worker"}[15m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Worker {{ $labels.pod }} restarting frequently"
```

### Команды для диагностики

```bash
# Проверка текущей глубины очереди (RabbitMQ)
kubectl exec -it rabbitmq-server-0 -- rabbitmqctl list_queues name messages consumers

# Проверка статуса ScaledObject
kubectl describe scaledobject <name> -n <namespace>
# Обратить внимание на:
# - Status.Ready
# - Status.Active (если False — KEDA не может получить метрики)
# - Events (ошибки скейлера)

# Проверка логов KEDA
kubectl logs -n keda deployment/keda-operator --tail=100 | grep ERROR

# Проверка лагов Kafka (если используется)
kubectl exec -it kafka-0 -- kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --describe --group worker-group
```

---

## Типичные ошибки и их решения

### Ошибка 1: Задачи теряются при деплое

**Симптом:** При обновлении Deployment задачи, которые обрабатывались в момент деплоя, не возвращаются в очередь.

**Причины:**
*   `terminationGracePeriodSeconds` слишком мал
*   Приложение не перехватывает SIGTERM
*   Visibility Timeout меньше времени Graceful Shutdown

**Решение:**
```yaml
# Увеличить terminationGracePeriodSeconds
terminationGracePeriodSeconds: 600  # 10 минут

# Добавить preStop hook для надежности
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "kill -TERM 1 && sleep 30"]
```

### Ошибка 2: Дублирование обработки

**Симптом:** Одна задача обрабатывается несколько раз.

**Причины:**
*   Сетевой сбой между обработкой и ACK
*   Воркер упал после обработки, но до ACK
*   Visibility Timeout истек до завершения обработки

**Решение:**
1. Реализовать идемпотентность обработки (см. Сценарий 6)
2. Настроить Visibility Timeout > максимальное время обработки
3. Использовать транзакционную обработку (Outbox Pattern)

### Ошибка 3: KEDA не масштабирует

**Симптом:** `ScaledObject` в статусе `READY=False` или `ACTIVE=False`.

**Диагностика:**
```bash
kubectl describe scaledobject <name>
# Проверить Events на ошибки подключения к брокеру
```

**Возможные причины:**
*   Неверные credentials для брокера
*   Брокер недоступен из подов KEDA
*   NetworkPolicy блокирует доступ

**Решение:**
```yaml
# Проверить triggerAuthentication
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-auth
spec:
  secretTargetRef:
    - parameter: host
      name: rabbitmq-secret
      key: amqp-url
```

### Ошибка 4: Зомби-воркеры

**Симптом:** Под "жив" по Liveness Probe, но не обрабатывает сообщения.

**Причины:**
*   Зависшие потоки в приложении
*   Таймауты соединений с внешними сервисами
*   Deadlock в коде

**Решение:**
1. Реализовать внутренние таймауты в коде
2. Добавить health check на основе активности (см. Сценарий 7)
3. Мониторить Processing Latency

---

## Дополнительная информация

### Выбор брокера сообщений

Выбор брокера определяет архитектуру консьюмеров:
*   **RabbitMQ:** Классические очереди. Идеален для `Competing Consumers` (множество воркеров разбирают одну очередь балансируя нагрузку). Поддерживает DLQ из коробки.
*   **Apache Kafka:** Потоковая лог-система. Ограничивает параллелизм количеством партиций (Partitions). Масштабировать воркеры свыше количества партиций бессмысленно (лишние поды будут простаивать). Подробнее: **[Принципы работы систем сообщений](../../Kafka/message_queues_principles.md)**.
*   **Redis (Bull/RQ):** Простое in-memory решение для быстрых задач (веб-хуки, email).

### Сравнение ScaledObject vs ScaledJob

| Характеристика | ScaledObject | ScaledJob |
|:---|:---|:---|
| Ресурс Kubernetes | Deployment/StatefulSet | Job |
| Время жизни пода | Длительное (пока есть задачи) | Доолнительное (одна задача = один Pod) |
| Изоляция | Общая среда | Полная изоляция |
| Утечки памяти | Накопление | Не накапливаются |
| Подходит для | Короткие задачи, потоковая обработка | Длительные задачи, legacy с утечками |
| Параллелизм | Много задач на один Pod | Строго одна задача на Pod |

### Ссылки
*   **[KEDA: Основные концепции](./keda/keda_concepts.md)** — архитектура и конфигурация KEDA.
*   **[KEDA: Практические сценарии](./keda/practical_scenarios.md)** — глубокое погружение в настройку триггеров.
*   **[Жизненный цикл Pod](../Base/Pod/pod_lifecycle_and_state.md)** — теория Graceful Shutdown и фаз пода.
*   **[Шардирование в Kubernetes](./sharding.md)** — как разделить очереди на приоритетные (Premium/Free).
*   **[Cluster Autoscaler](./cluster_autoscaler_detailed.md)** — добавление физических узлов под растущее количество воркеров.
*   **[PDB — Pod Disruption Budget](./pod_disruption_budget.md)** — защита воркеров при обслуживании узлов.
