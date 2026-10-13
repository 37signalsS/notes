# Архитектурный паттерн «Воркеры + Очередь» (Workers + Queue)

**Актуально для:** Kubernetes 1.28–1.35, KEDA 2.14–2.20+, RabbitMQ 3.12–4.x, Apache Kafka 3.x+

Паттерн «Воркеры + Очередь» (Workers + Queue / Competing Consumers) — фундаментальный шаблон [событийно-ориентированной архитектуры (EDA)](../../Concepts/event-driven-architecture.md) и фоновой пакетной обработки в распределенных системах. Паттерн изолирует (decouples) процесс генерации задач (Producer) от процесса их фактического выполнения (Consumer / Worker), обеспечивая буферизацию пиковых всплесков нагрузки, устойчивость к сбоям downstream-инфраструктуры и эластичное динамическое масштабирование вычислительных мощностей.

## Определения

*   **Workers + Queue (Competing Consumers)** — архитектурный паттерн, в котором множество параллельных обработчиков (воркеров) конкурируют за получение сообщений из общей очереди задач, гарантируя обработку каждого сообщения одним консьюмером.
*   **Producer (Производитель)** — сервис или API-шлюз, формирующий вычислительные задачи и публикующий их в брокер сообщений.
*   **Consumer (Потребитель / Worker)** — вычислительный процесс (Pod или однократная Job в Kubernetes), извлекающий задачи из брокера, исполняющий бизнес-логику и подтверждающий успешное выполнение (ACK).
*   **Идемпотентность (Idempotency)** — свойство операции, гарантирующее одинаковый результат состояния системы независимо от количества повторных выполнений одного и того же сообщения (критично при гарантиях доставки At-least-once).
*   **Visibility Timeout / Consumer Lock** — интервал времени, в течение которого взятое консьюмером сообщение временно скрывается от других воркеров. Если за это время подтверждение (ACK) не получено, брокер возвращает сообщение в очередь (Requeue).
*   **Prefetch Count (QoS Limit)** — максимальное число неподтвержденных (Unacknowledged) сообщений, которое брокер отправляет одному воркеру до получения ACK. Предотвращает захват всех сообщений одним подом и исчерпание памяти.
*   **Poison Pill (Отравленная таблетка)** — дефектное сообщение (некорректный JSON, нарушенный контракт), вызывающее аварийное падение воркера при каждой попытке обработки и блокирующее очередь.
*   **Dead Letter Queue (DLQ)** — выделенная очередь для изоляции сообщений, превысивших максимальный лимит попыток обработки (Delivery Limit / Max Retries).
*   **Consumer Lag (Отставание консьюмера)** — разница между объемом опубликованных сообщений и объемом обработанных сообщений (глубина очереди в RabbitMQ или смещение offset в Kafka). Главная метрика для автоскейлинга.
*   **Scale-to-Zero** — способность инфраструктуры уменьшать число реплик воркеров до 0 при отсутствии сообщений в очереди, высвобождая CPU и RAM узлов кластера.
*   **Graceful Shutdown** — механизм перехвата сигнала завершения (`SIGTERM`), позволяющий воркеру корректно завершить текущую задачу, отправить ACK/NACK и закрыть соединения перед остановкой контейнера.
*   **Backpressure (Обратное давление)** — совокупность механизмов ограничения входящей нагрузки при исчерпании емкости воркеров или downstream-ресурсов (БД, диски, внешние API).

## Основные концепции и архитектура

### Назначение и решаемые задачи

1.  **Сглаживание пиковых нагрузок (Load Leveling / Buffering):** Очередь принимает лавинообразный трафик (Thundering Herd), позволяя пулу воркеров обрабатывать сообщения в стабильном темпе, защищая базы данных и внутренние сервисы от перегрузки.
2.  **Асинхронность и отзывчивость API:** Синхронный HTTP-запрос не блокируется длительными операциями (генерация тяжелых отчетов, кодирование видео, отправка транзакционных рассылок). Producer мгновенно возвращает клиенту `202 Accepted` с идентификатором задачи.
3.  **Эластичное масштабирование по событиям:** В отличие от стандартного масштабирования по CPU/памяти, где реакция запаздывает, воркеры масштабируются строго по глубине очереди (Consumer Lag) и могут опускаться в 0 при простое.
4.  **Отказоустойчивость и семантика At-least-once:** В случае падения пода воркера (OOMKilled, падение ноды, сетевой сбой) неподтвержденное сообщение возвращается в брокер и переназначается здоровому поду.

### Архитектурная модель: Producer ➔ Broker ➔ Consumer

```text
[ Клиент / Браузер ]
         │ HTTP POST /tasks
         ▼
[ API Service (Producer) ]
         │ 1. Публикация задачи (Publish)
         │ 2. Ответ: 202 Accepted {task_id}
         ▼
[ Брокер сообщений ] ── (Ready Queue: Consumer Lag) ──┐
         │                                            │
         │ Опрос метрик глубины (Polling)             │ Извлечение задач (Pull / Push)
         ▼                                            ▼
[ KEDA Operator ] ─── Scale ───► [ Worker Pod 1 ] [ Worker Pod 2 ] ... [ Worker Pod N ]
         │                               │                │                    │
         ▼                               └────────────────┼────────────────────┘
[ HPA Controller ]                                        ▼
                                             [ База данных / MinIO / S3 ]
```

### Жизненный цикл сообщения (State Machine)

1.  **Enqueued (В очереди / Ready):** Сообщение находится в брокере и ожидает свободного консьюмера.
2.  **In-Flight (В обработке / Unacknowledged):** Воркер забрал сообщение. Брокер скрывает его по Visibility Timeout или ожидает подтверждения по открытому TCP-каналу.
3.  **Acknowledged (ACK):** Воркер успешно выполнил бизнес-логику и отправил сигнал подтверждения. Брокер навсегда удаляет сообщение из очереди.
4.  **Negative Acknowledged (NACK / Reject with Requeue):** Произошел временный сбой (например, короткая недоступность БД). Воркер отвергает сообщение, брокер немедленно возвращает его в статус `Enqueued`.
5.  **Dead-Lettered (Изоляция в DLQ):** Превышен лимит попыток доставки (`x-delivery-limit`) либо сообщение отвергнуто без повторной очереди (`requeue: false`). Сообщение маршрутизируется в DLQ для ручного разбора SRE.

### Модели параллелизма брокеров: RabbitMQ vs Apache Kafka vs Redis

Выбор брокера определяет архитектурные возможности горизонтального масштабирования:

| Характеристика | RabbitMQ (AMQP / Quorum Queues) | Apache Kafka (Partition-based Log) | Redis (Lists / Streams) |
| :--- | :--- | :--- | :--- |
| **Модель доставки** | **Competing Consumers:** Воркеры разбирают одну очередь независимо. | **Partition Consumer:** Каждую партицию читает строго один воркер из Consumer Group. | **Competing Consumers:** Команды `BLPOP` / `XREADGROUP`. |
| **Лимит параллелизма** | Ограничен только ресурсами брокера и числом воркеров. | **Жестко ограничен числом партиций.** Воркеры сверх числа партиций простаивают. | Ограничен однопоточностью Redis и пропускной способностью сети. |
| **Обработка сбоев** | Гибкий NACK, встроенный DLQ на уровне очередей. | Смещение смещается только вперед; DLQ требует отдельного топика. | Требует явной обработки через вспомогательные структуры. |
| **Применение** | Дискретные задачи разной длительности, сложная маршрутизация. | Высокопроизводительные потоки событий, строгий порядок по ключу. | Быстрые короткие задачи (вебхуки, кеш, время < 1 сек). |

Подробнее о внутренних механизмах см. **[Принципы работы систем сообщений](../../Kafka/message_queues_principles.md)** и **[Сравнение RabbitMQ и Kafka](../../Kafka/rabbitmq_vs_kafka.md)**.

### Защита зависимых сервисов и обратное давление (Backpressure)

Горизонтальное масштабирование воркеров несет скрытую угрозу для downstream-инфраструктуры (баз данных, внешних API):

*   **Исчерпание пула соединений БД:** Если `maxReplicaCount = 100`, а каждый под открывает пул из 20 соединений к PostgreSQL, суммарно потребуется 2000 соединений. Это приведет к отказу СУБД (`FATAL: remaining connection slots are reserved`).
    *   *Решение SRE:* Внедрение connection pooler (PgBouncer) в режиме `transaction pooling`, жесткое ограничение `maxReplicaCount` на уровне KEDA и использование семафоров в коде воркера.
*   **Лавинообразное накопление памяти (Unacked Flooding):** При высоком `Prefetch Count` один быстрый под может забрать 10 000 сообщений в локальную память и упасть по `OOMKilled`.
    *   *Решение SRE:* Значение `prefetch_count = 1` для тяжелых задач длительностью > 1 секунды.

---

## Практические сценарии и конфигурация

### Предварительные требования и системные зависимости

| Компонент | Минимальная версия | Рекомендуемая версия | Назначение |
| :--- | :--- | :--- | :--- |
| Kubernetes | 1.28+ | 1.30–1.35 | Стабильная поддержка HPA autoscaling/v2, PDB policy/v1 |
| KEDA | 2.14+ | 2.16–2.20+ | Контроллер очередей, поддержка Scale-to-Zero, trigger authentication |
| RabbitMQ | 3.12+ (Quorum) | 3.13–4.x | Поддержка кворумных очередей, `x-delivery-limit` и нативного Prometheus |

Перед развертыванием воркеров проверьте готовность кластера:

```bash
# 1. Проверка оператора KEDA
kubectl get pods -n keda -l app.kubernetes.io/name=keda-operator
# → keda-operator-76c8c6f78f-v8m4b              1/1  Running   0  5d
# → keda-operator-metrics-apiserver-85db976-7x   1/1  Running   0  5d

# 2. Проверка доступности брокера RabbitMQ из сети подов
kubectl run -it --rm amqp-ping --image=curlimages/curl --restart=Never -- \
  curl -s -u guest:guest http://rabbitmq.rabbitmq.svc.cluster.local:15672/api/healthchecks/node
# → {"status":"ok"}

# 3. Проверка квот неймспейса (чтобы maxReplicaCount помещался в лимиты)
kubectl get resourcequota -n app
# → NAME       AGE   REQUESTS-CPU   REQUESTS-MEMORY   PODS
# → app-quota  12d   8/32           16Gi/64Gi         12/100
```

### Сценарий 1: Корректное завершение работы (Graceful Shutdown) и PDB

Для воркеров долгоживущих задач корректное завершение критично: при деплое или выселении (Eviction) под не должен обрывать выполнение задачи.

1.  Под получает `SIGTERM` от kubelet.
2.  Воркер прекращает опрос очереди (отзывает регистрацию Consumer в брокере через `basic.cancel`).
3.  Воркер завершает обработку уже взятых сообщений, отправляет `ACK` в брокер.
4.  Воркер корректно закрывает соединения с брокером и СУБД, после чего процесс завершается (`exit 0`).
5.  Если процесс не завершился за `terminationGracePeriodSeconds`, kubelet принудительно посылает `SIGKILL`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: heavy-worker
  namespace: app
  labels:
    app: heavy-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: heavy-worker
  template:
    metadata:
      labels:
        app: heavy-worker
    spec:
      # Запас времени: максимальная длительность задачи (4 мин) + 60 сек на закрытие ресурсов
      terminationGracePeriodSeconds: 300
      containers:
        - name: worker
          image: internal-registry.local/workers/heavy-processor:v1.8.2
          imagePullPolicy: IfNotPresent
          lifecycle:
            preStop:
              exec:
                # Сигнал приложению о начале дренажа задач до отправки SIGTERM (если рантайм требует)
                command: ["/bin/sh", "-c", "touch /tmp/draining && sleep 5"]
          env:
            - name: WORKER_CONCURRENCY
              value: "2"
            - name: PREFETCH_COUNT
              value: "2"
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2000m"
              memory: "2Gi"
---
# Защита от потери воркеров при обслуживании узлов кластера (drain)
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: heavy-worker-pdb
  namespace: app
spec:
  # При scale-to-zero PDB не должен блокировать сжатие: minAvailable 1 реплика при наличии нагрузки
  maxUnavailable: 1
  selector:
    matchLabels:
      app: heavy-worker
```

Подробнее о механизмах эвикции см. **[Pod Disruption Budget](./pod_disruption_budget.md)** и **[Жизненный цикл Pod](../Base/Pod/pod_lifecycle_and_state.md)**.

### Сценарий 2: Горизонтальное масштабирование через KEDA ScaledObject (RabbitMQ)

Масштабирование воркеров на базе `ScaledObject`. Масштабирование происходит от 0 до 50 реплик в зависимости от глубины очереди `tasks-queue`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credentials
  namespace: app
type: Opaque
stringData:
  amqp-host: amqp://app-user:ComplexPass123@rabbitmq.rabbitmq.svc.cluster.local:5672/app-vhost
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: host
      name: rabbitmq-credentials
      key: amqp-host
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: worker-scaler
  namespace: app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: heavy-worker
  pollingInterval: 15     # Интервал опроса метрик брокера (секунды)
  cooldownPeriod:  300    # Период стабилизации перед масштабированием в 0 (секунды)
  minReplicaCount: 0      # Полный Scale-to-Zero при пустой очереди
  maxReplicaCount: 50     # Жесткий гардрейл емкости кластера
  fallback:
    failureThreshold: 3   # Число сбоев опроса брокера подряд
    replicas: 5           # Количество реплик в аварийном режиме
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300 # Защита от флаппинга при кратковременных просадках очереди
          policies:
            - type: Percent
              value: 20
              periodSeconds: 60
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: tasks-queue
        mode: QueueLength     # Режим расчета по длине очереди
        value: "10"           # 1 под на каждые 10 сообщений в очереди
        activationValue: "1"  # Масштабировать из 0 в 1 при появлении хотя бы 1 сообщения
      authenticationRef:
        name: rabbitmq-auth
```

Проверка применения:

```bash
kubectl get scaledobject worker-scaler -n app
# → NAME            TARGET         TRIGGERS   AUTHENTICATION   READY   ACTIVE   FALLBACK   AGE
# → worker-scaler   heavy-worker   rabbitmq   rabbitmq-auth    True    False               1m
```

Подробнее о внутренней механике контроллера см. **[KEDA: Основные концепции](./keda/keda_concepts.md)**.

### Сценарий 3: Изолированная пакетная обработка через KEDA ScaledJob

Если задача выполняется длительное время (от нескольких минут до часов), потребляет нестабильный объем памяти (риск утечек памяти в сторонних C-библиотеках типа FFmpeg) или требует жесткой изоляции — используется `ScaledJob`. KEDA создает однократный Kubernetes `Job` на каждое поступившее сообщение (или пачку сообщений).

> [!IMPORTANT]
> Для предотвращения засорения etcd кластера сотнями тысяч завершенных подов обязательно задавайте `successfulJobsHistoryLimit`, `failedJobsHistoryLimit` и `ttlSecondsAfterFinished`.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: media-transcoder-scaler
  namespace: app
spec:
  jobTargetRef:
    parallelism: 1
    completions: 1
    activeDeadlineSeconds: 1800       # Прерывание зависшей задачи через 30 минут
    ttlSecondsAfterFinished: 300      # Автоматическое удаление Job через 5 минут после финиша
    template:
      spec:
        restartPolicy: Never          # При падении не перезапускать pod внутри Job (сообщение вернется в брокер)
        containers:
          - name: transcoder
            image: internal-registry.local/media/ffmpeg-worker:v2.1.0
            env:
              - name: QUEUE_NAME
                value: "transcode-jobs"
            resources:
              requests:
                cpu: "1000m"
                memory: "2Gi"
              limits:
                cpu: "4000m"
                memory: "6Gi"
  pollingInterval: 30
  maxReplicaCount: 20                 # Максимум 20 параллельных Job в кластере!
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: transcode-jobs
        mode: QueueLength
        value: "1"                    # Ровно 1 Job на каждое сообщение
      authenticationRef:
        name: rabbitmq-auth
```

### Сценарий 4: Асинхронная обработка тяжелых задач с уведомлением пользователя

Схема реализации долгих задач (1–15 минут) без обрыва HTTP-соединений через связку API, брокера, объектного хранилища MinIO/Ceph и воркеров:

```text
1. Клиент ── POST /reports ──► API Gateway (Producer)
                                 │
                                 ├─ Сохраняет метаданные задачи (Status: PENDING) ──► PostgreSQL
                                 ├─ Публикует задачу {task_id, payload} ──► RabbitMQ
                                 └─ Отвечает клиенту 202 Accepted {id: "task-99", status_url: "/reports/task-99"}

2. Воркер (Consumer) ── Извлекает сообщение из RabbitMQ
                          ├─ Обновляет статус: PROCESSING
                          ├─ Генерирует отчет
                          ├─ Загружает готовый файл ──► MinIO / Ceph (S3 API)
                          ├─ Обновляет статус в БД: COMPLETED, s3_key: "reports/task-99.pdf"
                          ├─ Отправляет событие "task-completed" ──► Notification Service
                          └─ Отправляет ACK ──► RabbitMQ

3. Уведомление: Клиент получает WebSocket-событие или опрашивает (Polling) GET /reports/task-99.
```

Такая архитектура устраняет риск сбоев по таймаутам Ingress (`proxy_read_timeout 60s`) и позволяет масштабировать генерацию отчетов отдельно от веб-шлюза.

### Сценарий 5: Обработка сбойных сообщений (Poison Pills), DLQ и повторы (Retries)

В распределенной системе сообщения с нарушенным форматом данных способны вызвать бесконечный цикл падений воркеров.
Для RabbitMQ с кворумными очередями (Quorum Queues) настройка лимита повторных доставок (`x-delivery-limit`) и перенаправления в DLQ настраивается декларативно через манифест очереди:

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: Queue
metadata:
  name: orders-main-queue
  namespace: app
spec:
  name: orders-main-queue
  type: quorum
  durable: true
  arguments:
    # При превышении лимита брокер направляет сообщение на обменник DLX
    x-dead-letter-exchange: "dlx.direct"
    x-dead-letter-routing-key: "orders-poison"
    # Максимум 5 попыток обработки
    x-delivery-limit: 5
---
apiVersion: rabbitmq.com/v1beta1
kind: Queue
metadata:
  name: orders-dlq
  namespace: app
spec:
  name: orders-dlq
  type: quorum
  durable: true
```

Стратегия повторной обработки с экспоненциальной задержкой (Exponential Backoff with Jitter):

```python
import time
import random
import logging

def execute_with_retry(task_id, payload, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            return process_business_logic(payload)
        except TransientDatabaseError as err:
            attempt += 1
            if attempt >= max_retries:
                logging.error(f"Task {task_id} exhausted retries: {err}")
                raise  # Сообщение уйдет в NACK / DLQ
            
            # Экспоненциальная задержка: 2^attempt + случайный шум (Jitter)
            sleep_sec = (2 ** attempt) + random.uniform(0.1, 1.0)
            logging.warning(f"Retry {attempt}/{max_retries} for task {task_id} in {sleep_sec:.2f}s")
            time.sleep(sleep_sec)
```

### Сценарий 6: Обеспечение идемпотентности обработки (Deduplication и Outbox)

Гарантия доставки брокеров `At-least-once` означает, что сообщение **может быть доставлено более одного раза** (например, воркер упал ровно в момент отправки ACK). Воркер обязан гарантировать идемпотентность.

#### Паттерн 1: Атомарная проверка уникальности в PostgreSQL (Transactional Inbox)

```sql
-- Таблица входящих сообщений (Inbox Table)
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id VARCHAR(64) PRIMARY KEY,
    consumer_name VARCHAR(64) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Атомарная обработка в одной транзакции
BEGIN;

-- Попытка зафиксировать обработку сообщения
INSERT INTO processed_messages (message_id, consumer_name)
VALUES ('msg-uuid-9874', 'order-worker')
ON CONFLICT (message_id) DO NOTHING;

-- Проверяем, выполнилась ли вставка
-- Если xmax != 0, значит запись уже существовала, прерываем выполнение
SELECT (xmax = 0) AS is_new_message 
FROM processed_messages 
WHERE message_id = 'msg-uuid-9874';

-- Если is_new_message == TRUE, выполняем бизнес-операцию:
UPDATE accounts SET balance = balance - 100 WHERE id = 42;

COMMIT;
```

#### Паттерн 2: Быстрая дедупликация через Redis

```python
import redis

r = redis.Redis(host='redis.app.svc.cluster.local', port=6379, decode_responses=True)

def handle_message(message_id: str, payload: dict):
    lock_key = f"dedup:{message_id}"
    
    # Атомарная установка ключа с TTL 86400 (24 часа) только если его еще нет (NX)
    is_acquired = r.set(name=lock_key, value="processing", nx=True, ex=86400)
    
    if not is_acquired:
        # Сообщение уже в обработке или было обработано ранее
        print(f"Duplicate message {message_id} detected. Skipping with ACK.")
        return True
        
    try:
        process_task(payload)
        r.set(name=lock_key, value="completed", ex=86400)
        return True
    except Exception as exc:
        # В случае сбоя удаляем ключ, чтобы дать возможность повтора
        r.delete(lock_key)
        raise exc
```

### Сценарий 7: Проверки состояния (Health Checks) для фоновых воркеров

Воркеры очередей не имеют входящего HTTP-трафика, поэтому типовая конфигурация проверок через `httpGet` неприменима. 

> [!CAUTION]
> **Опасный антипаттерн SRE:** Проверка времени последней обработанной задачи (`time_since_last_task < 300s`). Если очередь пуста в течение 5 минут, воркер не обрабатывает задач и livenessProbe принудительно убивает здоровый под, загоняя Deployment в CrashLoopBackOff!

Корректная реализация Health Check для воркера очередей:
*   **Startup Probe:** Дает время на инициализацию соединений с брокером и СУБД.
*   **Readiness Probe:** Проверяет активное состояние TCP-сессии с брокером сообщений и зависимой СУБД.
*   **Liveness Probe:** Проверяет, что внутренний цикл событий (Event Loop / Heartbeat Thread) воркера жив и не завис в deadlock.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: queue-consumer
  namespace: app
spec:
  template:
    spec:
      containers:
        - name: consumer
          image: internal-registry.local/app/consumer:v1.2.0
          # Startup: До 60 секунд на инициализацию пулов и соединений
          startupProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - "test -f /tmp/worker_started"
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 12
          # Readiness: Проверка доступности брокера и готовности потреблять
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - "test -f /tmp/broker_connected && test ! -f /tmp/draining"
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 2
          # Liveness: Проверка активности фонового heartbeat-треда
          livenessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - |
                  # Проверяем, что heartbeat обновлялся процессом не более 30 секунд назад
                  LAST_BEAT=$(cat /tmp/worker_heartbeat 2>/dev/null || echo 0)
                  NOW=$(date +%s)
                  if [ $((NOW - LAST_BEAT)) -gt 30 ]; then
                    exit 1
                  fi
                  exit 0
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
```

### Сценарий 8: Управление параллелизмом и лимитами выборки (Prefetch)

Значение `Prefetch Count` (QoS) определяет, сколько сообщений брокер передает воркеру без подтверждения (ACK).

*   **Для долгих и тяжелых задач (> 2–5 секунд):** Устанавливайте `prefetch = 1`. Это гарантирует равномерное распределение задач между подами. Если один под выполняет сложную задачу, брокер сразу отдаст следующую задачу параллельному поду, а не будет копить ее в буфере первого.
*   **Для сверхбыстрых задач (< 50 мс):** Устанавливайте `prefetch = 20–100` для снижения задержки на сетевой round-trip (RTT) между брокером и воркером.

Пример настройки на Python (Pika):

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq.rabbitmq.svc.cluster.local'))
channel = connection.channel()

# 1. Объявляем кворумную очередь
channel.queue_declare(queue='heavy-tasks', durable=True, arguments={'x-queue-type': 'quorum'})

# 2. ВАЖНО: Устанавливаем prefetch_count ровно в 1 на консьюмера
channel.basic_qos(prefetch_count=1)

def on_message(ch, method, properties, body):
    try:
        process_task(body)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        # При критической ошибке отправляем NACK с возвратом в очередь (requeue=True)
        # или requeue=False для ухода в DLQ
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

channel.basic_consume(queue='heavy-tasks', on_message_callback=on_message)
channel.start_consuming()
```

---

## Операции и команды

### Диагностика брокеров и очередей

```bash
# 1. Проверка состояния очереди RabbitMQ (число сообщений, неacks, консьюмеры)
kubectl exec -it rabbitmq-server-0 -n rabbitmq -- \
  rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers --vhost app-vhost
# → Timeout: 60.0 seconds ...
# → Listing queues for vhost app-vhost ...
# → name                 messages_ready  messages_unacknowledged  consumers
# → tasks-queue          142             10                       10
# → tasks-queue-dlq      3               0                        0

# 2. Проверка задержки и смещения потребителей в Apache Kafka
kubectl exec -it kafka-cluster-kafka-0 -n kafka -- \
  bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group order-processors
# → GROUP            TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID
# → order-processors order-events  0          104523          104550          27              consumer-1-pod
# → order-processors order-events  1          109812          109815          3               consumer-2-pod
```

### Мониторинг и управление объектами KEDA

```bash
# 1. Просмотр всех объектов автоскейлинга KEDA в кластере
kubectl get scaledobject,scaledjob -A -o wide
# → NAMESPACE   NAME            SCALETARGETKIND      SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION   READY   ACTIVE   AGE
# → app         worker-scaler   apps/v1.Deployment   heavy-worker      0     50    rabbitmq   rabbitmq-auth    True    True     4d

# 2. Детальная диагностика триггеров и ошибок опроса
kubectl describe scaledobject worker-scaler -n app
# → Status:
# →   Conditions:
# →     Type:            Ready
# →     Status:          True
# →     Type:            Active
# →     Status:          True
# → Events:
# →   Type    Reason             Age    From           Message
# →   ----    ------             ----   ----           -------
# →   Normal  KEDAScalersStarted 5m     keda-operator  Started scalers watch for heavy-worker
# →   Normal  ScaledObjectReady  5m     keda-operator  ScaledObject is ready for target heavy-worker

# 3. Проверка журналов KEDA Operator на предмет сетевых сбоев и ошибок авторизации
kubectl logs -n keda deployment/keda-operator --tail=50 | grep -E "ERROR|warning"
# → (Вывод пуст при штатной работе)
```

### Ручной возврат сообщений из DLQ (Reprocessing)

Когда причина падений воркеров устранена (исправлен баг в коде или поднялась зависимая БД), сообщения из DLQ возвращаются в основную очередь:

```bash
# Использование плагина Shovel в RabbitMQ для перемещения всех сообщений из DLQ в рабочую очередь
kubectl exec -it rabbitmq-server-0 -n rabbitmq -- rabbitmqctl set_parameter shovel move-from-dlq \
  '{"src-uri": "amqp://", "src-queue": "tasks-queue-dlq", "dest-uri": "amqp://", "dest-queue": "tasks-queue"}'
# → Setting runtime parameter "move-from-dlq" for component "shovel" ...
# → success

# Проверка опустошения DLQ
kubectl exec -it rabbitmq-server-0 -n rabbitmq -- rabbitmqctl list_queues name messages --vhost app-vhost | grep dlq
# → tasks-queue-dlq    0

# Удаление конфигурации Shovel после перемещения сообщений
kubectl exec -it rabbitmq-server-0 -n rabbitmq -- rabbitmqctl clear_parameter shovel move-from-dlq
# → Clearing runtime parameter "move-from-dlq" for component "shovel" ...
# → success
```

---

## Мониторинг и метрики (SRE)

### Ключевые метрики (Golden Signals для очередей)

1.  **Queue Backlog / Consumer Lag (Traffic / Saturation):**
    *   RabbitMQ: `rabbitmq_queue_messages_ready` (сообщения, ждущие обработки).
    *   Kafka: `kafka_consumergroup_lag` (отставание по партициям).
2.  **Processing Latency (Latency):**
    *   Время нахождения задачи в очереди (Wait Time) + время исполнения консьюмером (Execution Duration p95 / p99).
3.  **Unacknowledged Messages (Saturation / Hazard):**
    *   `rabbitmq_queue_messages_unacknowledged`. Рост при стабильном числе консьюмеров сигнализирует о зависании процессов или утечке соединений.
4.  **Error Rate & Dead Letter Activity (Errors):**
    *   Скорость попадания сообщений в DLQ: `rate(rabbitmq_queue_messages_published_total{queue=~".*-dlq"}[5m])`.
5.  **KEDA Autoscaling Saturation (Saturation):**
    *   Отношение текущих реплик к максимуму: `keda_scaledobject_replicas / keda_scaledobject_max_replicas`.

### Правила алертинга Prometheus

```yaml
groups:
  - name: workers_queue_alerts
    rules:
      # Очередь не разбирается, реплики уперлись в максимальный лимит
      - alert: QueueBacklogAtMaxScale
        expr: |
          (rabbitmq_queue_messages_ready > 100)
          and on(namespace, scaledobject)
          (keda_scaledobject_replicas >= on(namespace, scaledobject) keda_scaledobject_max_replicas)
        for: 10m
        labels:
          severity: critical
          tier: autoscaling
        annotations:
          summary: "Очередь {{ $labels.queue }} растет, пул воркеров достиг maxReplicaCount"
          description: "Текущая глубина очереди {{ $value }}. Все реплики заняты. Риск срыва SLA."

      # Появление сообщений в очереди Poison Pills (DLQ)
      - alert: DLQMessagesDetected
        expr: rabbitmq_queue_messages_ready{queue=~".*-dlq"} > 0
        for: 2m
        labels:
          severity: warning
          tier: backend
        annotations:
          summary: "Обнаружены сообщения в Dead Letter Queue {{ $labels.queue }}"
          description: "В очереди {{ $labels.queue }} находится {{ $value }} необработанных сообщений."

      # Воркеры зависли: растут Unacknowledged сообщения без роста завершенных
      - alert: WorkerUnacknowledgedSpike
        expr: |
          deriv(rabbitmq_queue_messages_unacknowledged[5m]) > 5
          and rate(rabbitmq_queue_messages_delivered_total[5m]) == 0
        for: 5m
        labels:
          severity: critical
          tier: backend
        annotations:
          summary: "Воркеры удерживают сообщения без отправки подтверждений (Unacked Spike)"
          description: "Возможен deadlock, сетевой обрыв или исчерпание соединений к СУБД."

      # Активация аварийного режима Fallback в KEDA
      - alert: KEDAScalerFallbackActive
        expr: keda_scaledobject_fallback_activity == 1
        for: 3m
        labels:
          severity: warning
          tier: platform
        annotations:
          summary: "KEDA ScaledObject {{ $labels.scaledobject }} перешел в аварийный Fallback-режим"
          description: "Скейлер не может связаться с брокером сообщений. Активировано фиксированное число реплик."
```

Подробнее о мониторинге брокеров см. **[RabbitMQ: Мониторинг и алерты](../../rabbitmq/monitoring_and_alerting.md)** и **[Метрики и алертинг Kubernetes Autoscaling](./alerting_monitoring.md)**.

---

## Диагностика и устранение неполадок

### Матрица типовых неисправностей

| Симптом | Вероятная причина | Инструмент диагностики | Метод устранения |
| :--- | :--- | :--- | :--- |
| **Задачи обрываются при деплое воркеров** | `terminationGracePeriodSeconds` меньше времени исполнения задачи; отсутствие перехвата `SIGTERM`. | `kubectl get events`, логи воркера | Увеличить `terminationGracePeriodSeconds`, перехватывать `SIGTERM`, добавить `PDB`. |
| **Дублирование обработки задач** | Длительность выполнения задачи превышает `Visibility Timeout`; сетевые разрывы до ACK. | Логи с таймингами выполнения, метрики БД | Увеличить `Visibility Timeout`, настроить `Prefetch = 1`, внедрить идемпотентность (Inbox). |
| **KEDA ScaledObject: READY=False** | Неверные реквизиты в `TriggerAuthentication`, брокер недоступен по DNS или заблокирован `NetworkPolicy`. | `kubectl describe scaledobject`, логи `keda-operator` | Проверить сетевой доступ к порту брокера (5672/15672), скорректировать Secret. |
| **Утечки завершенных подов в etcd** | В `ScaledJob` не заданы параметры ротации истории выполненных задач. | `kubectl get jobs,pods -n app` | Задать `successfulJobsHistoryLimit: 3`, `ttlSecondsAfterFinished: 300`. |
| **Падение воркеров по OOMKilled** | Высокий `Prefetch Count`, воркер выкачивает тысячи сообщений в оперативную память. | `kubectl describe pod` (`OOMKilled`) | Уменьшить `prefetch_count` до 1–5, увеличить `resources.limits.memory`. |
| **СУБД отклоняет подключения** | Лавинообразное масштабирование воркеров исчерпало пул соединений СУБД. | Логи PostgreSQL (`remaining connection slots`) | Ограничить `maxReplicaCount`, внедрить PgBouncer, уменьшить размер пула в воркере. |

### Разбор критических инцидентов

#### Инцидент 1: Thundering Herd и лавина переотправки при падении воркера

*   **Контекст:** Воркер с настройкой `prefetch_count: 5000` вычитал из брокера 5000 задач. При обработке 45-й задачи под падает по OOMKilled.
*   **Следствие:** Брокер фиксирует разрыв TCP-соединения и мгновенно возвращает все 4955 необработанных сообщений обратно в очередь со статусом `Ready`. Новый запущенный под снова выкачивает всю пачку, падает по OOMKilled, вызывая бесконечный шторм.
*   **Решение:**
    1. Немедленно снизить `prefetch_count` до `10` (или `1` для тяжелых задач) в коде приложения или конфигурации консьюмера.
    2. Установить в брокере лимит памяти для очередей и настроить кворумную очередь с `x-delivery-limit`.

#### Инцидент 2: Зависание воркеров из-за отсутствия сетевых таймаутов

*   **Контекст:** Воркер забирает задачу и обращается к внешней СУБД. Происходит тихий разрыв соединения (drop пакетов файрволом без RST/FIN).
*   **Следствие:** Поток воркера навечно блокируется на операции `socket.read()`. Так как процесс формально жив, Kubernetes Liveness Probe не срабатывает. Сообщение висит в статусе `Unacknowledged`, воркер не берет новых задач и не освобождает ресурсы.
*   **Решение:**
    1. Обязательная настройка `socket_timeout`, `connect_timeout` и TCP Keepalive во всех клиентских библиотеках БД и брокеров.
    2. Внедрение независимого Heartbeat-потока в воркере, сигнализирующего о зависании основного цикла обработки для Liveness Probe.

---

## Лучшие практики (Best Practices)

1.  **Декларативное ограничение емкости (Guardrails):**
    Ни один `ScaledObject` или `ScaledJob` не должен разворачиваться в production без явно заданного `maxReplicaCount`. Лимит должен быть рассчитан исходя из емкости downstream-хранилищ (IOPS дисков, соединений СУБД, пропускной способности сети).
2.  **Защита от флаппинга при сжатии (Scale-Down Stabilization):**
    Всегда настраивайте `advanced.horizontalPodAutoscalerConfig.behavior.scaleDown.stabilizationWindowSeconds` (минимум 300 секунд). Это предотвращает постоянные циклы убийства и создания подов при волнообразном поступлении пачек сообщений.
3.  **Изоляция и отказоустойчивость планирования (Scheduling):**
    Воркеры должны распределяться по разным физическим нодам и зонам доступности через `topologySpreadConstraints` или `podAntiAffinity`. Для критичных очередей назначайте `priorityClassName`, предотвращающий выселение воркеров планировщиком при нехватке ресурсов.
4.  **Синхронизация таймаутов:**
    Должно строго соблюдаться правило неравенства:
    $$\text{Socket Timeout} < \text{Task Max Duration} < \text{Visibility Timeout} < \text{terminationGracePeriodSeconds}$$
5.  **Архитектура очередей Quorum:**
    В RabbitMQ используйте только Quorum Queues (`type: quorum`) для production-очередей. Они реплицируются через алгоритм Raft, устойчивы к сетевым разделениям (Network Partition) и аппаратно поддерживают `x-delivery-limit`.
6.  **Надежность Scale-to-Zero:**
    Используйте `minReplicaCount: 0` только если бизнес-процесс толерантен к задержке «холодного старта» (10–30 секунд на создание пода, выделение IP в CNI и инициализацию библиотек). Для околореального времени (near real-time) задавайте `minReplicaCount: 1` или `2`.
7.  **Настройка аварийного режима (Fallback):**
    Всегда указывайте блок `fallback` в `ScaledObject`. Если брокер сообщений испытывает проблемы с сетью или перегружен, KEDA не должна сжимать воркеры в 0: fallback-реплики позволят продолжить обработку локально буферизованных задач.

---

## Дополнительная информация

*   **[KEDA: Основные концепции](./keda/keda_concepts.md)** — архитектура KEDA, компоненты оператора и метрик-сервера.
*   **[KEDA: Практические сценарии](./keda/practical_scenarios.md)** — глубокая настройка скейлеров для RabbitMQ, Kafka, PostgreSQL.
*   **[KEDA: Эксплуатация и траблшутинг](./keda/keda-operations.md)** — операционные чек-листы и устранение сбоев KEDA.
*   **[KEDA: Оптимизация затрат (FinOps)](./keda/keda-finops.md)** — предотвращение перерасхода ресурсов при автомасштабировании.
*   **[RabbitMQ: Архитектурные паттерны](../../rabbitmq/message_patterns.md)** — топологии обмена сообщениями, AMQP-маршрутизация.
*   **[RabbitMQ: Мониторинг и алерты](../../rabbitmq/monitoring_and_alerting.md)** — метрики экспортера, PromQL и правила оповещений.
*   **[RabbitMQ: Руководство по устранению неполадок](../../rabbitmq/troubleshooting.md)** — диагностика очередей, сплит-брейнов и нехватки памяти.
*   **[Kafka: Принципы систем сообщений](../../Kafka/message_queues_principles.md)** — сравнительный анализ моделей брокеров.
*   **[Kafka: Гарантии доставки](../../Kafka/delivery_guarantees.md)** — семантика At-least-once, Exactly-once и дедупликация.
*   **[Pod Disruption Budget (PDB)](./pod_disruption_budget.md)** — защита воркеров от выселения при обслуживании нод.
*   **[Жизненный цикл Pod](../Base/Pod/pod_lifecycle_and_state.md)** — фазы Pod, сигналы завершения и хуки жизненного цикла.
*   **[Шардирование очередей и воркеров](./sharding.md)** — разделение пулов обработчиков по классам приоритетов.
