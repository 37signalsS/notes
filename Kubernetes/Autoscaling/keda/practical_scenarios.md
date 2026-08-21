# KEDA: Практические сценарии

## Определения и базовые концепции

Данный материал содержит прикладные примеры конфигурации. Смежные материалы:

* **[KEDA: Основные концепции](./keda_concepts.md)** — теоретическая база, описания компонентов (Operator, Metrics Server), глоссарий
* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)** — диагностика, алерты, типовые проблемы

## Практические сценарии

### Предварительные требования

* Кластер Kubernetes 1.27+
* Helm 3.12+
* Установленный Prometheus (для соответствующих сценариев)
* Настроенный доступ к внешним источникам событий (RabbitMQ, Kafka, AWS SQS)
* Для облачных сценариев: настроенный **Workload Identity** (замена устаревшему Pod Identity)

### Установка KEDA

Рекомендуемый способ установки — использование официального Helm-чарта.

```bash
# Добавление репозитория
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# Установка версии 2.20.0 (актуально на июнь 2026)
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.20.0 \
  --set prometheus.operator.enabled=true

# (Опционально) Установка KEDA HTTP Add-on для масштабирования HTTP-трафика
helm install http-add-on kedacore/keda-http-add-on \
  --namespace keda
```

### Проверка готовности

После установки проверьте состояние подов:

```bash
kubectl get pods -n keda
# → keda-operator-..., keda-metrics-apiserver-..., keda-admission-webhooks-...
```

### Безопасное хранение credentials

Credentials для подключения к источникам событий (RabbitMQ, Kafka, PostgreSQL) нельзя хардкодить в YAML манифестах ScaledObject.

Неправильно — credentials прямо в метаданных триггера:

```yaml
metadata:
  host: "amqp://admin:password123@rabbitmq:5672/"
```

Правильно — Kubernetes Secret + `TriggerAuthentication`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-connection
  namespace: app
type: Opaque
stringData:
  host: amqp://user:password@rabbitmq.app.svc.cluster.local:5672/
---
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: rabbitmq-auth
  namespace: app
spec:
  secretTargetRef:
    - parameter: host
      name: rabbitmq-connection
      key: host
```

Для production рекомендуется [External Secrets Operator](https://external-secrets.io/) в связке с Vault, AWS Secrets Manager или аналогами:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rabbitmq-connection
  namespace: app
spec:
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: rabbitmq-connection
  data:
    - secretKey: host
      remoteRef:
        key: prod/rabbitmq
        property: connection_string
```

Такой подход дает:

* централизованное управление секретами;
* ротацию credentials без правки YAML;
* аудит доступа к секретам;
* отсутствие паролей в Git.

Для облачных скейлеров (AWS, GCP, Azure) предпочтительнее Workload Identity вместо статических секретов (см. рекомендации по эксплуатации ниже).

### Сценарий 1: Масштабирование Deployment (RabbitMQ)

Классический сценарий для воркеров, обрабатывающих сообщения из очереди. При пустой очереди количество подов уменьшается до 0. Использование `activationValue` предотвращает запуск подов при единичных сообщениях.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-worker-scaler
  namespace: prod
spec:
  scaleTargetRef:
    name: worker-deployment
  minReplicaCount: 0 
  maxReplicaCount: 50
  pollingInterval: 10
  cooldownPeriod: 300
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: task-queue
        mode: QueueLength       # Порог по числу сообщений в очереди
        value: "5"              # 1 под на каждые 5 сообщений
        activationValue: "3"    # Не масштабировать из 0, пока в очереди < 3 сообщений
      authenticationRef:
        name: rabbitmq-auth     # Credentials через TriggerAuthentication (см. раздел ниже)
```

Начиная с KEDA v2.20 параметр `queueLength` объявлен устаревшим — используйте связку `mode: QueueLength` + `value`. Помимо длины очереди скейлер поддерживает режимы `MessageRate` (темп публикации), `DeliverGetRate` (темп доставки), `PublishedToDeliveredRatio` (баланс публикации и потребления) и `ExpectedQueueConsumptionTime` (оценка времени опустошения очереди); режимы кроме `QueueLength` требуют протокола `http`. При нескольких триггерах HPA масштабирует по максимальному результату каждого из них независимо.

### Сценарий 2: Масштабирование задач (ScaledJob)

Используется для тяжелых задач, где один запуск Job соответствует одному событию. Параметр `idleReplicaCount: 0` гарантирует отсутствие ресурсов в простое.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledJob
metadata:
  name: video-transcoder-job
spec:
  jobTargetRef:
    parallelism: 1
    completions: 1
    template:
      spec:
        containers:
          - name: transcoder
            image: my-registry/video-tool:latest
        restartPolicy: OnFailure
  pollingInterval: 30
  maxReplicaCount: 100
  idleReplicaCount: 0 # Явно указываем отсутствие Job при отсутствии событий
  triggers:
    - type: aws-sqs
      metadata:
        queueURL: https://sqs.us-east-1.amazonaws.com/12345678/video-tasks
        queueLength: "1"
      authenticationRef:
        name: aws-workload-identity-auth # Рекомендуется использовать IAM Roles for Service Accounts
```

### Сценарий 3: Глобальная аутентификация (ClusterTriggerAuthentication)

Позволяет переиспользовать учетные данные Kafka во всех пространствах имен.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ClusterTriggerAuthentication
metadata:
  name: global-kafka-auth
spec:
  secretTargetRef:
    - parameter: sasl
      name: kafka-global-secret
      key: sasl-config
---
# Использование в ScaledObject
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-scaler
spec:
  triggers:
    - type: kafka
      metadata:
        bootstrapServers: kafka:9092
        topic: telemetry
        lagThreshold: "100"
      authenticationRef:
        name: global-kafka-auth
        kind: ClusterTriggerAuthentication # Обязательно указать тип
```

### Сценарий 4: Применение модификаторов (Scaling Modifiers)

Пример использования `scalingModifiers` (v2.20+) для коррекции метрики Prometheus перед масштабированием.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: modified-prometheus-scaler
spec:
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        threshold: "100"
        query: sum(rate(http_requests_total[1m]))
  # Умножение полученной метрики на коэффициент 1.5 для агрессивного старта
  scalingModifiers:
    formula: "metricValue * 1.5"
    targetMetricName: "boosted_requests"
```

### Сценарий 5: Смешанное масштабирование (Prometheus + Cron)

Масштабирование по нагрузке, но с гарантированным минимумом в рабочие часы.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hybrid-scaler
spec:
  minReplicaCount: 0
  triggers:
    # Триггер 1: Нагрузка
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        threshold: "50"
        query: avg(http_requests_per_second)
    # Триггер 2: Расписание (пн-пт, 09:00-18:00)
    - type: cron
      metadata:
        timezone: UTC
        start: 0 9 * * 1-5
        end: 0 18 * * 1-5
        desiredReplicas: "10" # В рабочее время всегда минимум 10
```

### Сценарий 6: Масштабирование HTTP до нуля (KEDA HTTP Add-on)

Требует установленного `keda-http-add-on`. Позволяет масштабировать приложение на основе входящего HTTP-трафика: Interceptor перехватывает запросы, и если подов нет — удерживает их в очереди, пока KEDA поднимает первый под.

Начиная с HTTP Add-on v0.15 ресурс `HTTPScaledObject` (v1alpha1) объявлен устаревшим; актуальный API — `InterceptorRoute` (v1beta1), который разделяет маршрутизацию и масштабирование. Пример на текущей схеме `HTTPScaledObject`:

```yaml
apiVersion: http.keda.sh/v1alpha1
kind: HTTPScaledObject
metadata:
  name: web-app-scaler
spec:
  hosts:
    - my-service.example.com
  scaleTargetRef:
    name: web-app-deployment
    service: web-app-svc        # Service для маршрутизации — обязательное поле
    port: 8080
  replicas:
    min: 0
    max: 20
  scalingMetric:
    requestRate:                # Взаимоисключающе с concurrency
      targetValue: 100          # Целевой RPS на один под
      window: 1m                # Окно расчета темпа
  scaledownPeriod: 300
```

Если `scalingMetric` не задана, используется масштабирование по concurrency (целевое число одновременных запросов на под, по умолчанию 100). Миграция с `HTTPScaledObject` на `InterceptorRoute` описана в [документации HTTP Add-on](https://keda.sh/http-add-on/latest/operations/migrate-httpscaledobject-to-interceptorroute/).

#### Production checklist для HTTP Add-on

**1. Cold start**

* Сколько времени требуется от 0 до первого ready-пода?
* Укладывается ли в timeout клиентов?
* Настроен ли `initialDelaySeconds` в readiness probe?

**2. Таймауты**

Должны быть согласованы по цепочке: client > interceptor > ingress > pod. Проверить timeout на Ingress, timeout на HTTP Interceptor и timeout клиента.

**3. Readiness probes**

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 3
  failureThreshold: 2
```

**4. Лимиты соединений**

* Проверить connection pool базы данных.
* Проверить rate limits внешних API.
* Настроить `replicas.max` с учетом этих лимитов.

**5. План отката**

```bash
# Быстрый откат: поднимаем минимум реплик
kubectl patch httpscaledobject api-http-scaler -n app \
  --type='json' -p='[{"op": "replace", "path": "/spec/replicas/min", "value": 2}]'

# Или полное отключение KEDA для этого workload
kubectl delete httpscaledobject api-http-scaler -n app
kubectl scale deployment/api-service --replicas=3 -n app
```

### Сценарий 7: Масштабирование на основе ресурсов K8s (ConfigMap)

Используется, когда внешняя система записывает текущий уровень нагрузки в ConfigMap кластера.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: configmap-scaler
spec:
  triggers:
    - type: kubernetes-resource
      metadata:
        resourceKind: "ConfigMap"
        resourceName: "external-load-metrics"
        key: "current_rps"
        format: "number"
        targetValue: "100"
        activationTargetValue: "10" # Масштабировать из 0 только если RPS > 10
```

### Сценарий 8: Выключение dev-окружений и сервисов с рабочими часами (cron)

Не вся нагрузка приходит из очереди — иногда расписание известно заранее: ночные ETL-процессы, утренние отчеты, рабочие часы B2B-сервиса, внутренние сервисы, dev- и staging-окружения.

Пример: B2B-сервис должен работать в рабочие дни с 08:50 до 19:00 с тремя репликами, вне окна — масштабироваться до 0.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: b2b-api-office-hours
  namespace: app
spec:
  scaleTargetRef:
    name: b2b-api
  minReplicaCount: 0
  maxReplicaCount: 5
  cooldownPeriod: 300
  triggers:
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: "50 8 * * 1-5"
        end: "0 19 * * 1-5"
        desiredReplicas: "3"
```

Для масштабирования до 0 вне рабочего окна указывается `minReplicaCount: 0`, а в рабочее время количество реплик задается через `desiredReplicas`. Фактическое масштабирование вниз произойдет после `cooldownPeriod` — по умолчанию через 5 минут после `end`.

#### Почему это лучше bash-скриптов

Ранее для таких сценариев писали скрипты вида:

```bash
#!/bin/bash
# /opt/scripts/scale-dev-env.sh
if [ $(date +%H) -ge 19 ] || [ $(date +%H) -lt 9 ]; then
  kubectl scale deployment/api --replicas=0 -n dev
else
  kubectl scale deployment/api --replicas=3 -n dev
fi
```

и запускали их через cron на каком-нибудь сервере. Проблемы такого подхода:

* **Ownership:** скрипт может работать годами, пока не сломается; тогда выясняется, что автор уволился два года назад.
* **Документация:** почему 3 реплики? Почему 19:00? Почему этот namespace?
* **Версионность:** скрипт лежит на сервере, а не в Git.
* **Observability:** упал скрипт или отработал — непонятно без ручной проверки.
* **Боязнь трогать:** «работает — не трожь» превращается в technical debt.

Cron scaler не отменяет необходимость нормального ownership, но переносит расписание в декларативную Kubernetes-конфигурацию: конфигурация в Git, стандартный lifecycle через kubectl/GitOps, события в Kubernetes Events, метрики KEDA в Prometheus.

### Сценарий 9: Масштабирование по метрикам Prometheus

Масштабирование API по количеству HTTP-запросов в секунду:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-rps-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: api-service
  minReplicaCount: 1
  maxReplicaCount: 20
  pollingInterval: 30
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc.cluster.local:9090
        query: sum(rate(http_requests_total{deployment="api-service"}[2m]))
        threshold: "100"
```

Prometheus scaler масштабирует workload по результату запроса; `query` должен возвращать scalar или vector с одним элементом, `threshold` задает порог масштабирования.

#### Проверки перед production

1. **Query должен возвращать один результат** — scalar или vector с одним элементом. Если возвращается несколько элементов (например, по одному на под), KEDA не сможет использовать метрику — добавьте агрегацию (`sum`, `avg`).
2. **Метрика должна быть стабильной** — без провалов и дублирования серий.
3. **Окно `rate` должно соответствовать характеру нагрузки:** `[2m]` для быстрой реакции на пики, `[5m]` для более плавного масштабирования.
4. **Threshold подбирается нагрузочным тестом**, а не «на глаз»: замерить RPS, который выдерживает 1 под, и поставить threshold с запасом (например, 70–80% от максимума).
5. **maxReplicaCount должен учитывать лимиты:** пропускную способность базы данных, rate limits внешних API, лимиты connection pool.

Примеры других метрик для масштабирования:

```yaml
# По задержкам (latency p95)
query: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="api"}[5m]))
threshold: "0.5"   # 500ms на p95

# По количеству активных соединений
query: sum(nginx_connections_active{deployment="nginx"})
threshold: "1000"

# По длине очереди в Redis
query: redis_list_length{list="tasks"}
threshold: "50"

# По custom business-метрике
query: sum(rate(orders_created_total[5m]))
threshold: "10"    # 10 заказов/сек на реплику
```

С точки зрения FinOps этот сценарий важен тем, что масштабирование привязывается ближе к бизнес-нагрузке — RPS, конверсия, количество активных пользователей, — а не только к CPU.

### Сценарий 10: Тонкая настройка поведения масштабирования (HPA behavior)

Финансово и технически оптимальное поведение автоскейлера асимметрично: быстрый рост под нагрузкой (защита SLA) и плавное сжатие при спаде (защита от flapping и лишних холодных стартов). Настраивается через `advanced.horizontalPodAutoscalerConfig.behavior`:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-rps-scaler
  namespace: app
spec:
  scaleTargetRef:
    name: api-service
  minReplicaCount: 1
  maxReplicaCount: 20
  cooldownPeriod: 300
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 300   # Смотреть на метрики за последние 5 минут
          policies:
            - type: Percent
              value: 50                     # Уменьшать максимум на 50%...
              periodSeconds: 60             # ...в минуту
            - type: Pods
              value: 2                      # ...или на 2 пода в минуту
          selectPolicy: Min                 # Выбирать более консервативную политику
        scaleUp:
          stabilizationWindowSeconds: 0     # Реагировать мгновенно
          policies:
            - type: Percent
              value: 100                    # Увеличивать максимум вдвое...
              periodSeconds: 15             # ...каждые 15 секунд
            - type: Pods
              value: 4                      # ...или на 4 пода за 15 секунд
          selectPolicy: Max                 # Выбирать более агрессивную политику
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc.cluster.local:9090
        query: sum(rate(http_requests_total{deployment="api-service"}[2m]))
        threshold: "100"
```

Что здесь происходит:

* **Scale Down (консервативный):** stabilization window 300 секунд; уменьшение либо на 50%, либо на 2 пода в минуту — что меньше; `selectPolicy: Min` выбирает более осторожный вариант.
* **Scale Up (агрессивный):** без стабилизации; увеличение либо на 100%, либо на 4 пода каждые 15 секунд — что больше; `selectPolicy: Max` выбирает более быструю реакцию.

Такая конфигурация готова к production: быстро растет под нагрузкой, медленно сжимается при спаде. Отдельно `cooldownPeriod` управляет только уходом в 0 после прекращения активности триггеров; поведением 1 ↔ N управляет HPA.

## Дополнительная информация

Диагностика, мониторинг с алертами и решения типовых проблем (cold start, flapping, недоступность метрик, упор в лимиты) вынесены в отдельный материал:

* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)**

### Наблюдаемость через OpenTelemetry

Для включения выгрузки метрик и трейсов в формате OTLP при установке через Helm:

```bash
helm upgrade keda kedacore/keda \
  --set otel.enabled=true \
  --set otel.collectorUri="otel-collector.monitoring.svc:4317" \
  --set otel.protocol="grpc"
```
После включения становятся доступны метрики задержки масштабирования (`scaling_latency`), что позволяет отследить время от появления события в очереди до запуска пода.

### Рекомендации по эксплуатации

1.  **Безопасный Scale Down:** Для критичных Stateful нагрузок используйте `cooldownPeriod` не менее 600 секунд (10 минут), чтобы избежать частого перезапуска подов при колебаниях трафика.
2.  **Pod Disruption Budget (PDB):** Всегда настраивайте PDB для масштабируемых нагрузок. При резком падении нагрузки KEDA может попытаться удалить слишком много подов одновременно, что может нарушить доступность.
3.  **Борьба с Cold Start:** Если приложение запускается долго (>30 сек), избегайте `minReplicaCount: 0`. Используйте `minReplicaCount: 1`, если бизнес-логика требует мгновенной реакции.
4.  **Валидация триггеров:** Перед применением в Prod проверяйте запросы PromQL в интерфейсе Prometheus. KEDA не проверяет корректность самой логики запроса.
5.  **Лимиты для ScaledJob:** Всегда устанавливайте `maxReplicaCount` для `ScaledJob`, чтобы избежать исчерпания ресурсов кластера (например, при внезапном наплыве миллионов сообщений в очередь).
6.  **Аутентификация:** Предпочитайте использование **Workload Identity** (IAM-роли) вместо явных секретов в `TriggerAuthentication` для облачных скейлеров (AWS, GCP, Azure).

## См. также

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура и определения
* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)** — диагностика, алерты, типовые проблемы
* **[KEDA: FinOps-гардрейлы и измерение экономии](./keda-finops.md)** — scale-to-zero, выбор лимитов, пилот и замер эффекта
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — проектирование систем обработки очередей
* **[Horizontal Pod Autoscaler (HPA): Практические сценарии](../HPA/hpa_scenarios.md)** — стандартное масштабирование
