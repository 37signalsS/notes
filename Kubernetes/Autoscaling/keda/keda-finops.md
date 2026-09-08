# KEDA: FinOps-гардрейлы и измерение экономии

## Определения и базовые концепции

Данный материал рассматривает KEDA как инженерный инструмент управления затратами в Kubernetes: где возможностей стандартного HPA уже недостаточно, как устроена механика scale-to-zero, зачем ограничивать верхнюю границу масштабирования и как доказать эффект от внедрения цифрами.

Теоретическая база и прикладная конфигурация представлены в смежных материалах:

* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура, компоненты, глоссарий
* **[KEDA: Практические сценарии](./practical_scenarios.md)** — установка, триггеры
* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)** — диагностика, алерты, типовые проблемы

## Финансовая проблема over-provisioning

В Kubernetes легко привыкнуть к мысли, что автоскейлинг уже есть, значит проблема с динамической нагрузкой решена. Стандартный HPA хорошо работает там, где нагрузка выражается через CPU и память. Но часть сервисов живет по другой логике: ждет сообщения в очереди, включается по расписанию, получает краткие пики HTTP-трафика или обрабатывает задачи пачками.

Для таких нагрузок картина ресурсов и картина бизнес-нагрузки расходятся. Для HPA ситуация может выглядеть спокойно:

```text
CPU: 2%
Memory: stable
Replicas: 2
```

А фактическая бизнес-нагрузка в тот же момент:

```text
Queue length: 3250 messages
Oldest message age: 18 minutes
SLA: at risk
```

Если масштабироваться только по CPU, реакция будет запаздывать. Если держать большой резерв подов постоянно, команда платит за мощность, которая большую часть времени простаивает. Это классический over-provisioning: ресурсы заняты, счет растет, полезной работы в этот момент нет.

KEDA сдвигает масштабирование ближе к фактической нагрузке: событиям, очередям, расписанию, HTTP-трафику и внешним метрикам. Это не замена управлению затратами (аллокация, ownership, бюджетные алерты), но рабочий инженерный гардрейл, который помогает не держать ресурсы включенными без необходимости и заранее ограничивать верхнюю границу масштабирования.

FinOps-эффект дают три механизма:

* **Scale-to-zero** — 0 подов, когда нагрузки нет, то есть отсутствие расходов на холостой простой.
* **maxReplicaCount** — финансовый предохранитель от бесконтрольного разгона масштабирования.
* **Экономия 40–70%** на workloads с непостоянной нагрузкой (воркеры, batch-задачи, dev-окружения).

## Кейс: фоновый воркер обработки заказов

Типовой сценарий — воркер, который обрабатывает заказы из RabbitMQ. Нагрузка сосредоточена в рабочие часы, остальное время очередь пуста.

### До внедрения KEDA

Конфигурация:

* Deployment с фиксированным количеством реплик: 5
* Режим работы: 24/7
* Пиковая нагрузка: рабочие дни 10:00–18:00
* Ночью и в выходные: очередь пустая

Метрики:

* Постоянно: 5 реплик × 24 часа = **120 pod-hours/день**
* Средняя утилизация CPU: **8%** (большую часть времени воркеры простаивают)
* Очередь пустая **~18 часов в сутки**
* Стоимость compute для workload: **~$180/месяц** (из расчета $0.05/pod-hour)

Проблема: платим за 5 подов круглосуточно, хотя реальная работа происходит 6–8 часов в день.

### После внедрения KEDA

Конфигурация:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-worker-scaler
spec:
  scaleTargetRef:
    name: orders-worker
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
    - type: rabbitmq
      metadata:
        queueName: orders
        mode: QueueLength
        value: "20"
```

Поведение по времени суток:

* **10:00–18:00 (пик):** очередь 150–200 сообщений → **8–10 реплик**
* **18:00–22:00 (спад):** очередь 20–40 сообщений → **1–2 реплики**
* **22:00–10:00 + выходные:** очередь пустая → **0 реплик**

Метрики:

* Среднее за день: **~40 pod-hours/день**
* Утилизация CPU в активное время: **45–60%** (поды заняты работой)
* Cold start при появлении первого сообщения: **~12 секунд**
* SLA на обработку сообщения (5 минут): **не нарушен**
* Стоимость compute для workload: **~$60/месяц**

### Результат

* **Экономия: 67%** на этом workload ($120/месяц)
* **Утилизация выросла** с 8% до 45–60%
* **SLA не пострадал** — cold start укладывается в допустимые рамки
* **maxReplicaCount: 10** защищает от бесконтрольного роста при аномалиях

Профиль реплик изменился следующим образом: до KEDA — горизонтальная линия на уровне 5 реплик круглосуточно; после KEDA — пилообразный профиль с пиками 8–10 реплик в рабочие часы и нулями ночью и в выходные.

Этот кейс типичен для:

* воркеров обработки заказов, уведомлений, email-рассылок;
* batch-задач по расписанию;
* внутренних сервисов с рабочими часами;
* dev/staging окружений.

## Scale-to-zero как FinOps-механика

Scale-to-zero — одна из главных функций KEDA с точки зрения FinOps. Если событий нет, очередь пуста, расписание не наступило или трафика нет, KEDA уменьшает количество реплик приложения до 0. Сервис не держит вычислительные ресурсы только потому, что «вдруг пригодится».

В обычной инфраструктурной логике часто появляется постоянный резерв:

```text
min replicas: 2
traffic: 0
queue: 0
cost: continues
```

С scale-to-zero логика меняется:

```text
min replicas: 0
traffic: 0
queue: 0
cost for workload compute: reduced
```

Здесь важно не переобещать. Scale-to-zero не означает, что счет за весь кластер станет нулевым. Control plane, системные компоненты, ноды, диски, логи, сеть и другие ресурсы могут продолжать стоить денег. Но для конкретного workload это снижает холостой простой.

FinOps-смысл простой: платить не за ожидание, а за обработку нагрузки.

Технические детали активации из нуля описаны в [KEDA: Основные концепции](./keda_concepts.md), риски холодного старта и способы их устранения — в [KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md).

## maxReplicaCount как финансовый предохранитель

FinOps — это не только экономия в простое, но и ограничение расходов сверху. Автоскейлинг без верхней границы может разогнать счет, если:

1. в коде появился баг (бесконечный retry, memory leak);
2. очередь начала расти из-за деградации внешнего сервиса;
3. метрика настроена слишком агрессивно;
4. приложение попало под аномальную нагрузку (DDoS, scraping);
5. downstream-система стала отвечать медленнее → воркеры висят дольше → KEDA поднимает еще воркеров.

`maxReplicaCount` задает максимальное количество реплик, выше которого workload не поднимется:

```yaml
spec:
  minReplicaCount: 0
  maxReplicaCount: 10
```

### Как правильно выбрать maxReplicaCount

Здесь важно смотреть на систему целиком.

**Слишком низкое значение:**

* счет защищен;
* но получены растущая очередь, задержки, нарушение SLA;
* downstream-системы в порядке, а сообщения не обрабатываются.

**Слишком высокое значение:**

* SLA защищен;
* но увеличен финансовый риск;
* есть опасность задавить базу или внешний API.

**Правильный подход:**

1. **Замерить пропускную способность сервиса** через нагрузочное тестирование:

```text
# Сколько RPS выдерживает 1 под?
# Сколько сообщений/сек обрабатывает 1 воркер?
```

2. **Проверить лимиты зависимостей:**

```text
PostgreSQL connection pool: 100
Если каждый под держит 10 connections
→ максимум 10 подов
```

3. **Добавить запас на пики:**

```text
Обычная нагрузка: 5 подов
Пиковая нагрузка: 8 подов
→ maxReplicaCount: 12 (50% запас)
```

4. **Настроить алерт на приближение к лимиту:**

```yaml
# Prometheus alert
- alert: KEDANearMaxReplicas
  expr: keda_scaledobject_replicas / keda_scaledobject_max_replicas > 0.8
  for: 5m
  annotations:
    summary: "ScaledObject {{ $labels.scaledobject }} at 80% of maxReplicaCount"
```

Нормальный подход — не «поставить красивое число», а связать лимит с реальными возможностями инфраструктуры: пропускной способностью пода, лимитами базы данных, rate limits внешних API.

## Баланс скорости scale-up и scale-down

Финансово оптимальное поведение автоскейлера асимметрично: реагировать на рост нагрузки мгновенно (защита SLA), а сжиматься плавно (защита от flapping и повторных холодных стартов, каждый из которых стоит времени и денег).

Такая асимметрия настраивается через `cooldownPeriod` и секцию `advanced.horizontalPodAutoscalerConfig.behavior`: консервативный `scaleDown` со стабилизационным окном и ограничением скорости, агрессивный `scaleUp` без задержек. Полная рабочая конфигурация приведена в разделе тонкой настройки [KEDA: Практические сценарии](./practical_scenarios.md).

## Доказываем экономию: какие метрики собирать до и после

Самая частая ошибка — внедрить автоскейлинг и считать, что экономия появилась сама. Для FinOps этого недостаточно: нужно заранее договориться, что именно сравниваем до и после.

### Технические метрики

```text
Утилизация ресурсов:
  - pod-hours (реплик × часов работы)
  - replica count over time
  - CPU utilization (среднее, p50, p95)
  - memory utilization (среднее, p50, p95)

Бизнес-нагрузка:
  - queue length (среднее, max)
  - oldest message age
  - request rate (RPS)
  - throughput (сообщений/сек, заказов/час)

Производительность:
  - latency (p50, p95, p99)
  - error rate
  - success rate
  - cold start time (p95, p99)
  - time to scale (0 -> N реплик)

События масштабирования:
  - scale up events count
  - scale down events count
  - time at 0 replicas
  - time at max replicas
```

### Финансовые метрики

Важно заранее договориться, какой тип cost view используется. Если одна команда смотрит blended cost, другая unblended, а третья amortized, обсуждение быстро превращается в спор о цифрах вместо анализа решения.

```text
Cost dimensions:
  - Стоимость namespace (до/после)
  - Стоимость workload (до/после)
  - Стоимость node pool (до/после)
  - Стоимость idle capacity
  - Стоимость за единицу работы (cost per order, cost per message)

Cost types (выбрать один):
  - Blended cost (смешанная: on-demand + spot + savings plans)
  - Unblended cost (чистая: без учета скидок)
  - Amortized cost (амортизированная: распределение reserved instances)
  - Net cost (с учетом всех скидок и кредитов)

Time periods:
  - 1 неделя до внедрения
  - 1 месяц до внедрения
  - 1 неделя после внедрения
  - 1 месяц после внедрения
```

### Операционные метрики

```text
Stability:
  - количество инцидентов
  - количество нарушений SLA
  - MTTR (mean time to recovery)

Toil:
  - количество ручных вмешательств
  - количество manual scale операций
  - время на troubleshooting autoscaling

Reaction time:
  - время реакции на пик нагрузки
  - стабильность scale up
  - стабильность scale down
  - количество flapping events
```

### Пример итогового отчета

```text
Before KEDA (week 1-2)
- Pod-hours: 336/week (5 pods × 24h × 7d)
- Avg CPU utilization: 8%
- Cost: $168/week
- Manual interventions: 3 (weekend scale-down)

After KEDA (week 3-4)
- Pod-hours: 112/week
- Avg CPU utilization: 52%
- Cost: $56/week
- Manual interventions: 0
- Cold start p95: 12 seconds
- SLA violations: 0

Result
- Cost savings: 67% ($112/week, $5824/year for this workload)
- Utilization improvement: 8% -> 52%
- Toil reduction: 3 manual ops -> 0
- SLA: no impact
```

## План пилота

KEDA не нужно внедрять сразу во всю архитектуру. Безопаснее идти по шагам.

### Шаг 1. Найти подходящий workload

Хорошие кандидаты для первого пилота:

1. **Фоновые воркеры** — обработка очередей (email, уведомления, отчеты), batch-задачи, ETL-процессы.
2. **Dev/staging окружения** — не нужны ночью и в выходные, низкий риск для production, быстро покажут экономию.
3. **Сервисы с рабочими часами** — B2B API (9:00–18:00), внутренние инструменты, admin-панели.
4. **Внутренние API с понятным профилем нагрузки** — стабильная метрика (RPS, queue length), известные пиковые окна, нет жестких SLA.

Плохие кандидаты для первого пилота:

1. Критичный production с жестким SLA.
2. Stateful workloads (базы данных).
3. Сервисы с долгим cold start (>30 сек).
4. Сервисы с множеством внешних зависимостей.
5. Монолит с shared state.

### Шаг 2. Проверить источник событий

Перед настройкой нужно ответить на вопросы:

```text
Источник метрики:
  - Есть ли стабильная метрика нагрузки?
  - Кто владеет этой метрикой?
  - Можно ли ей доверять?
  - Что будет, если источник метрики недоступен?
  - Какой лаг между событием и реакцией?

Для очередей (RabbitMQ, Kafka, SQS):
  - Можем получить длину очереди?
  - Есть credentials для подключения?
  - Есть ли мониторинг очереди?

Для Prometheus:
  - Query возвращает один скаляр?
  - Метрика не проваливается?
  - Есть алерт на отсутствие метрики?

Для cron:
  - Расписание согласовано с командой?
  - Timezone корректный?
```

Если метрика нестабильна, KEDA будет честно масштабироваться по плохому сигналу.

### Шаг 3. Задать границы

Для пилота нужно явно указать базовые параметры масштабирования:

```yaml
minReplicaCount: 0      # или 1 если cold start критичен
maxReplicaCount: 10     # выбрать по capacity planning
pollingInterval: 30     # как часто проверять
cooldownPeriod: 300     # пауза перед scale-to-zero
```

Рекомендации по выбору значений:

```text
minReplicaCount:
  # 0   -> если cold start < 15 сек и SLA позволяет
  # 1   -> если нужна мгновенная реакция
  # 2+  -> если нужна redundancy

maxReplicaCount:
  # capacity = max_expected_load / throughput_per_pod
  # + 20-50% запас
  # Пример: 1000 msg/sec, 100 msg/sec на под -> 10 подов + 50% = 15

pollingInterval:
  # 30 сек    -> для плавной нагрузки
  # 10-15 сек -> для быстрых пиков
  # 5 сек     -> для critical workloads (но больше нагрузки на источник метрик)

cooldownPeriod:
  # 300 сек (5 мин)  -> стандарт
  # 600 сек (10 мин) -> для workloads с частыми колебаниями
  # 120 сек (2 мин)  -> для dev-окружений
```

### Шаг 4. Настроить observability

До запуска подготовить дашборд.

Обязательные панели:

* replicas over time;
* scaler metric value (queue length / RPS и т.д.);
* latency (p50, p95, p99);
* error rate;
* CPU / memory utilization.

FinOps панели:

* pod-hours per day;
* cost per day (если есть cost allocation);
* cost per message/request.

KEDA-специфичные панели:

* `keda_scaler_errors_total`;
* distance to max replicas;
* time at 0 replicas;
* time at max replicas.

Алерты:

* **Critical:** KEDA scaler errors; max replicas reached + queue growing; cold start > SLA threshold.
* **Warning:** distance to max replicas < 20%; flapping (scale up/down каждые 5 мин); queue age > SLA threshold.

PromQL-запросы и готовые выражения алертов приведены в разделе мониторинга [KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md).

Без такого дашборда будет сложно понять: KEDA действительно снизил простой или просто перенес проблему в задержки.

### Шаги 5–6. Запустить пилот и собрать данные

Запустить пилот на 1–2 недели, затем собрать данные и сравнить:

| Metric | Before | After | Change |
| :--- | :--- | :--- | :--- |
| Pod-hours/week | 336 | 112 | -67% |
| Avg CPU util | 8% | 52% | +44pp |
| Cost/week | $168 | $56 | -$112 |
| P95 latency | 120ms | 150ms | +30ms |
| Error rate | 0.01% | 0.01% | - |
| SLA violations | 0 | 0 | - |
| Manual ops | 3 | 0 | -3 |

### Шаг 7. Решить: раскатывать дальше или откатить

Раскатывать дальше, если:

* экономия подтверждена цифрами;
* SLA не пострадал;
* команда понимает, как это работает;
* observability настроена;
* нет блокирующих проблем.

Доработать, если:

* cold start слишком долгий → оптимизировать образ;
* flapping → настроить behavior;
* упираемся в max replicas → capacity planning.

Откатить, если:

* SLA нарушен;
* проблемы с источником метрик;
* команда не может troubleshoot;
* экономика не подтвердилась.

Процедура отката описана в разделе FAQ материала [KEDA: Основные концепции](./keda_concepts.md).

## Чек-лист перед production

```text
Application readiness:
  - Сервис можно безопасно опускать до 0?
  - Cold start укладывается в SLA?
  - Приложение stateless?
  - Нет in-memory state между запросами?
  - Нет dependency на конкретный pod IP?

Kubernetes configuration:
  - Readiness probe настроен корректно?
  - Liveness probe не убивает pod во время cold start?
  - Resource requests и limits заданы?
  - PodDisruptionBudget настроен?
  - Anti-affinity rules учтены?

KEDA configuration:
  - minReplicaCount выбран обоснованно?
  - maxReplicaCount учитывает лимиты downstream?
  - pollingInterval адекватен скорости нагрузки?
  - cooldownPeriod не слишком агрессивный?
  - Trigger метрика стабильна?

Dependencies:
  - Понятны лимиты базы данных?
  - Понятны лимиты брокера сообщений?
  - Понятны rate limits внешних API?
  - Connection pools настроены с запасом?

Observability:
  - Дашборд для workload готов?
  - Алерты настроены и протестированы?
  - Логи агрегируются корректно?
  - Distributed tracing работает?

Ownership:
  - Известно, кто владеет ScaledObject?
  - Есть runbook для troubleshooting?
  - Команда понимает, как откатиться?
  - Есть алерт на рост очереди?
  - Есть алерт на упор в maxReplicaCount?

FinOps:
  - Cost allocation tags проставлены?
  - Договорились, какой cost view используем?
  - Baseline метрики собраны?
  - План замера эффекта через месяц?

Rollback plan:
  - Известен план отката?
  - Протестирован откат на staging?
  - Команда знает, как быстро вернуть fixed replicas?
```

Если хотя бы часть ответов неизвестна, это не значит, что KEDA нельзя внедрять. Это значит, что пилот нужно запускать на менее критичном участке.

## Формулы расчёта экономии и ROI

Для обоснования внедрения KEDA перед руководством необходимы точные формулы расчёта, а не абстрактные обещания «сэкономим».

### Базовая формула экономии на workload

```text
Экономия = (Cost_before - Cost_after) × Период

Где:
  Cost_before = Pods_fixed × Hours_per_day × Days × Price_per_pod_hour
  Cost_after  = Σ(Pods_active × Hours_active) × Price_per_pod_hour
```

**Пример расчёта для воркера заказов:**

```text
До KEDA:
  5 подов × 24 часа × 30 дней × $0.05/pod-hour = $180/месяц

После KEDA:
  Рабочие часы (10:00-18:00): 8 подов × 8 часов × 22 дня × $0.05 = $70.40
  Вечер (18:00-22:00): 2 пода × 4 часа × 22 дня × $0.05 = $8.80
  Итого: $79.20/месяц

  Ночь + выходные: 0 подов × $0 = $0

  Экономия: $180 - $79.20 = $100.80/месяц (56%)
```

### Формула ROI (Return on Investment)

```text
ROI = (Годовая_экономия - Стоимость_внедрения) / Стоимость_внедрения × 100%

Годовая_экономия = Месячная_экономия × 12
Стоимость_внедрения = Часы_инженера × Ставка_инженера + Стоимость_инструментов
```

**Пример:**

```text
Годовая экономия: $100.80 × 12 = $1,209.60
Стоимость внедрения: 16 часов × $75/час + $0 (KEDA open-source) = $1,200
ROI = ($1,209.60 - $1,200) / $1,200 × 100% = 0.8%

Примечание: ROI положительный, но низкий. Для одного workload.
При масштабировании на 10+ workload ROI вырастет пропорционально.
```

### Формула cost-per-unit

```text
Cost_per_order = Total_workload_cost / Orders_processed
Cost_per_message = Total_workload_cost / Messages_processed
Cost_per_API_call = Total_workload_cost / Requests_handled
```

**Пример для воркера заказов:**

```text
До KEDA:
  $180 / 10,000 заказов = $0.018 за заказ

После KEDA:
  $79.20 / 10,000 заказов = $0.00792 за заказ

  Экономия на единицу: 56%
```

### Формула idle cost

```text
Idle_cost = (Pods_total - Pods_active) × Hours × Price_per_pod_hour
Idle_percentage = Idle_cost / Total_cost × 100%
```

**Пример:**

```text
До KEDA:
  (5 - 0.4) подов в среднем × 24 часа × $0.05 = $5.28/день idle
  Idle percentage: 92% (поды простаивают 92% времени)

После KEDA:
  (10 - 8) подов в среднем × 8 часов × $0.05 = $0.80/день idle
  Idle percentage: 10%
```

## Интеграция с Kubecost/OpenCost

Kubecost и OpenCost — инструменты для мониторинга затрат в Kubernetes. Они дополняют KEDA, предоставляя видимость стоимости на уровне namespace, deployment и pod.

### Архитектура интеграции

```text
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   KEDA       │      │   Kubecost   │      │  Prometheus  │
│ (autoscaling)│      │ (cost alloc) │      │  (metrics)   │
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Cost Dashboard│
                    │ (per namespace, │
                    │  per workload)  │
                    └─────────────────┘
```

### Настройка cost allocation для KEDA workload

Для корректного отображения стоимости в Kubecost необходимо правильно настроить labels:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-worker
  labels:
    app: orders-worker
    team: platform
    cost-center: cc-12345
    environment: production
    finops/managed-by: keda  # специальный label для FinOps
```

### PromQL запросы для cost monitoring

```text
# Стоимость конкретного workload (если настроена цена за pod-hour)
sum(rate(container_cpu_usage_seconds_total{namespace="app", pod=~"orders-worker.*"}[1h])) * 3600 * $0.02

# Стоимость по namespace
sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"}) * $0.02

# Сравнение стоимости до/после KEDA
# (требует исторических данных Kubecost)
```

### Метрики Kubecost для KEDA

Kubecost предоставляет следующие метрики, полезные для FinOps-анализа KEDA:

```text
# Стоимость по deployment
kubecost_cluster_costs_hourly
kubecost_deployment_cost_hourly

# Утилизация vs requests
kubecost_container_cpu_utilization
kubecost_container_memory_utilization

# Idle cost
kubecost_cluster_idle_cost
kubecost_namespace_idle_cost
```

### Настройка алертов на стоимость

```yaml
# Prometheus alert: превышение бюджета по namespace
- alert: NamespaceBudgetExceeded
  expr: |
    kubecost_namespace_cost_hourly{namespace="app"} 
    * 24 * 30 > 500  # бюджет $500/месяц
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "Namespace {{ $labels.namespace }} превышает бюджет"

# Prometheus alert: рост стоимости workload
- alert: WorkloadCostSpike
  expr: |
    rate(kubecost_deployment_cost_hourly{deployment="orders-worker"}[1h])
    > 2 * avg_over_time(kubecost_deployment_cost_hourly{deployment="orders-worker"}[7d])
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "Стоимость orders-worker выросла в 2 раза"
```

## Оптимизация node pool с KEDA

KEDA влияет не только на количество подов, но и на утилизацию нод. Правильная настройка node pool может усилить FinOps-эффект.

### Проблема: фрагментация нод

При scale-to-zero KEDA удаляет поды, но ноды остаются. Если на нодах есть системные компоненты или другие workload, ноды не могут быть удалены Cluster Autoscaler.

```text
Ситуация:
  3 ноды × 4 CPU = 12 CPU доступно
  Системные поды: 2 CPU
  Orders-worker: 0 подов (scale-to-zero)
  Остальные workload: 3 CPU

  Утилизация: 5/12 = 42%
  Idle: 7 CPU (58%)
```

### Решение: правильные resource requests

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-worker
spec:
  template:
    spec:
      containers:
      - name: worker
        resources:
          requests:
            cpu: "0.5"      # минимальный запрос
            memory: "256Mi"
          limits:
            cpu: "2"
            memory: "512Mi"
```

**Эффект:**

```text
При cpu: "0.5":
  Orders-worker занимает 0.5 CPU на ноде
  Cluster Autoscaler может плотнее упаковывать поды
  Ноды используются эффективнее
```

### Интеграция с Karpenter

Karpenter (вместо Cluster Autoscaler) может динамически добавлять и удалять ноды. В связке с KEDA:

```yaml
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
          values: ["on-demand", "spot"]  #混合ная стратегия
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

**FinOps-эффект Karpenter + KEDA:**

```text
1. KEDA scale-to-zero → поды удаляются
2. Karpenter видит пустые ноды → удаляет их
3. При scale-up KEDA → Karpenter добавляет ноды
4. Результат: оплата только за используемые ноды
```

## Spot/Preemptible instances с KEDA

Использование spot-инстансов может усилить FinOps-эффект, но требует осторожности.

### Когда можно использовать spot с KEDA

```text
Подходит:
  - Batch-задачи (можно перезапустить)
  - Воркеры очередей (сохраняются в брокере)
  - Dev/staging окружения
  - Не критичные сервисы

Не подходит:
  - Критичные production сервисы
  - Сервисы с state
  - Сервисы с долгим cold start
```

### Конфигурация KEDA + Spot

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-worker
spec:
  template:
    spec:
      tolerations:
      - key: "kubernetes.azure.com/scalesetpriority"
        operator: "Equal"
        value: "spot"
        effect: "NoSchedule"
      nodeSelector:
        kubernetes.azure.com/scalesetpriority: spot
      containers:
      - name: worker
        resources:
          requests:
            cpu: "0.5"
            memory: "256Mi"
          limits:
            cpu: "2"
            memory: "512Mi"
```

### FinOps-эффект spot + KEDA

```text
On-demand: $0.05/pod-hour
Spot: $0.015/pod-hour (70% скидка)

Экономия spot + KEDA:
  До KEDA (on-demand): 5 подов × 24 часа × $0.05 = $180/месяц
  После KEDA (spot): 8 подов × 8 часов × $0.015 = $28.80/месяц
  Итого: $28.80/месяц (84% экономия)
```

### Обработка прерываний spot

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-worker-scaler
spec:
  scaleTargetRef:
    name: orders-worker
  minReplicaCount: 0
  maxReplicaCount: 10
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 600  # дольше ждем перед scale-down
          policies:
          - type: Pods
            value: 1
            periodSeconds: 60
```

## FinOps-специфичные PromQL запросы

Для глубокого FinOps-анализа KEDA необходимы специфичные запросы.

### Метрики KEDA для FinOps

```text
# Текущее количество реплик vs максимальное
keda_scaledobject_replicas / keda_scaledobject_max_replicas

# Время на нулевых репликах (доля времени в idle)
1 - (avg_over_time(keda_scaledobject_replicas[1h]) > 0)

# Частота масштабирования (scale-up/down events)
rate(keda_scaledobject_replicas[5m])

# Ошибки скейлера (влияют на доступность и FinOps)
rate(keda_scaler_errors_total[5m])
```

### Метрики утилизации ресурсов

```text
# CPU utilization vs requests (для right-sizing)
sum(rate(container_cpu_usage_seconds_total{namespace="app"}[5m])) by (pod)
/
sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"}) by (pod)

# Memory utilization vs requests
sum(container_memory_working_set_bytes{namespace="app"}) by (pod)
/
sum(kube_pod_container_resource_requests{namespace="app", resource="memory"}) by (pod)

# Pod-hours за период
count(kube_pod_info{namespace="app"}) * 24  # подов в день
```

### Метрики стоимости

```text
# Стоимость по namespace (если известна цена за CPU-hour)
sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"}) * $0.02 * 24 * 30

# Стоимость idle (неиспользуемые ресурсы)
sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"})
- sum(rate(container_cpu_usage_seconds_total{namespace="app"}[1h])) * 3600

# Стоимость cold start (влияние на SLA и стоимость)
histogram_quantile(0.95, rate(keda_scaler_latency_seconds_bucket[5m]))
```

### Алерты для FinOps

```yaml
# Алерт на высокую стоимость idle
- alert: HighIdleCost
  expr: |
    (
      sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"})
      - sum(rate(container_cpu_usage_seconds_total{namespace="app"}[1h])) * 3600
    ) * $0.02 * 24 * 30 > 100  # idle > $100/месяц
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "High idle cost in namespace {{ $labels.namespace }}"

# Алерт на низкую утилизацию
- alert: LowCPUUtilization
  expr: |
    avg(
      sum(rate(container_cpu_usage_seconds_total{namespace="app"}[5m])) by (pod)
      /
      sum(kube_pod_container_resource_requests{namespace="app", resource="cpu"}) by (pod)
    ) < 0.2  # утилизация < 20%
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "CPU utilization below 20% - consider right-sizing"
```

## Мульти-тенантная оптимизация затрат

В кластерах с несколькими командами KEDA помогает атрибутировать затраты и оптимизировать расходы по tenants.

### Стратегии cost attribution

```yaml
# Labels для атрибуции затрат
metadata:
  labels:
    team: platform
    cost-center: cc-12345
    environment: production
    service: orders-worker
    finops/tier: critical  # critical, standard, best-effort
```

### ResourceQuota с FinOps ограничениями

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-platform-quota
  namespace: app
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    pods: "50"
    # FinOps ограничения
    count/deployments.apps: "10"
    count/scaledobjects.keda.sh: "5"  # лимит на количество ScaledObject
```

### Kubecost для multi-tenant

```text
Kubecost позволяет:
1. Разделять затраты по namespace (team ownership)
2. Настраивать budget alerts per team
3. Генерировать отчёты по cost allocation
4. Сравнивать стоимость между командами

Настройка:
  - Label team: автоматическое разделение по командам
  - Label cost-center: привязка к центрам затрат
  - Label environment: разделение dev/staging/prod
```

### Алерты для мульти-тенантных кластеров

```yaml
# Алерт на приближение к лимиту ResourceQuota
- alert: TeamQuotaAlmostExhausted
  expr: |
    kube_resourcequota{type="used"} 
    / kube_resourcequota{type="hard"} > 0.85
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Team {{ $labels.namespace }} quota at {{ $value | humanizePercentage }}"

# Алерт на превышение бюджета
- alert: TeamBudgetExceeded
  expr: |
    kubecost_namespace_cost_hourly{namespace=~"app-.*"} 
    * 24 * 30 > 1000  # бюджет $1000/месяц на команду
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Team {{ $labels.namespace }} exceeded budget"
```

## Анализ стоимости cold start

Cold start — это время между появлением события и запуском первого пода. Это время имеет FinOps-implications.

### Стоимость cold start

```text
Cold start time: 12 секунд (typical)
Стоимость одного cold start: $0.00002 (при $0.05/pod-hour)

Пример:
  100 cold starts в день × $0.00002 = $0.002/день
  За месяц: $0.06 — пренебрежимо мало

Но есть скрытыеコスト:
  1. Время обработки сообщения увеличивается на 12 секунд
  2. Если SLA = 5 минут, cold start съедает 4% времени
  3. При высокой частоте cold starts может нарушиться SLA
```

### Формула Total Cost of Cold Start

```text
TCS = (Cold_start_time × Cost_per_second × Events_per_day × Days) 
      + (SLA_violation_penalty × Probability_of_violation)

Где:
  Cost_per_second = Price_per_pod_hour / 3600
  Probability_of_violation = Cold_start_time / SLA_threshold
```

**Пример:**

```text
Cold start time: 12 сек
Price per pod-hour: $0.05
Events per day: 100
SLA threshold: 300 сек (5 мин)
Penalty for SLA violation: $50

TCS = (12 × $0.0000139 × 100 × 30) + ($50 × 0.04)
    = $0.05 + $2.00 = $2.05/месяц

Вывод: стоимость cold start мала, но риск SLA violation значителен.
```

### Оптимизация cold start для FinOps

```yaml
# Оптимизация образа контейнера
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-worker
spec:
  template:
    spec:
      containers:
      - name: worker
        image: orders-worker:alpine  # alpine вместо full image
        resources:
          requests:
            cpu: "0.1"    # минимальный CPU для быстрого старта
            memory: "128Mi"
```

**Эффект оптимизации:**

```text
До оптимизации:
  Image: 800 MB (ubuntu-based)
  Cold start: 18 сек
  Cost per cold start: $0.000025

После оптимизации:
  Image: 50 MB (alpine-based)
  Cold start: 6 сек
  Cost per cold start: $0.0000083

  Экономия: 67% на cold start cost
```

## Практические примеры с реальными метриками

### Пример 1: Batch-задачи по расписанию

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: daily-report-generator
spec:
  scaleTargetRef:
    name: report-generator
  minReplicaCount: 0
  maxReplicaCount: 5
  triggers:
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 2 * * *  # 02:00 каждый день
        end: 0 4 * * *    # 04:00 каждый день
        desiredReplicas: "3"
```

**Метрики:**

```text
До KEDA:
  3 пода × 24 часа × 30 дней = 2,160 pod-hours
  Стоимость: $108/месяц

После KEDA:
  3 пода × 2 часа × 30 дней = 180 pod-hours
  Стоимость: $9/месяц

  Экономия: 92% ($99/месяц)
```

### Пример 2: Dev/staging окружение

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: dev-environment-scaler
spec:
  scaleTargetRef:
    name: dev-frontend
  minReplicaCount: 0
  maxReplicaCount: 3
  triggers:
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 9 * * 1-5  # 09:00 пн-пт
        end: 0 19 * * 1-5   # 19:00 пн-пт
        desiredReplicas: "2"
```

**Метрики:**

```text
До KEDA:
  2 пода × 24 часа × 30 дней = 1,440 pod-hours
  Стоимость: $72/месяц

После KEDA:
  2 пода × 10 часов × 22 дня = 440 pod-hours
  Стоимость: $22/месяц

  Экономия: 69% ($50/месяц)
```

### Пример 3: API с переменной нагрузкой

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: api-gateway-scaler
spec:
  scaleTargetRef:
    name: api-gateway
  minReplicaCount: 1  # не опускать до 0 (SLA)
  maxReplicaCount: 20
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring:9090
        metricName: http_requests_per_second
        query: sum(rate(http_requests_total{service="api-gateway"}[1m]))
        threshold: "100"  # масштабировать при > 100 RPS
        activationThreshold: "10"
```

**Метрики:**

```text
До KEDA:
  5 подов × 24 часа × 30 дней = 3,600 pod-hours
  Стоимость: $180/месяц

После KEDA:
  Ночь (00:00-08:00): 1 под × 8 часов × 30 дней = 240 pod-hours
  День (08:00-20:00): 8 подов × 12 часов × 30 дней = 2,880 pod-hours
  Вечер (20:00-24:00): 3 пода × 4 часа × 30 дней = 360 pod-hours
  Итого: 3,480 pod-hours
  Стоимость: $174/месяц

  Экономия: 3% ($6/месяц)

  Примечание: экономия минимальна, но утилизация выросла с 15% до 65%.
  Главный FinOps-эффект: нет idle capacity, ресурсы используются эффективно.
```

## Чек-лист FinOps-аудита KEDA

Перед запуском production пилота проведите аудит:

```text
Cost baseline:
  - Собраны метрики за 2 недели до внедрения?
  - Известна стоимость workload (cost per pod-hour)?
  - Определены cost dimensions (namespace, deployment, pod)?
  - Договорились cost view (blended, unblended, amortized)?

KEDA configuration:
  - minReplicaCount обоснован?
  - maxReplicaCount связан с capacity planning?
  - cooldownPeriod настроен для FinOps?
  - Trigger метрика стабильна?

Observability:
  - Kubecost/OpenCost настроен?
  - Cost allocation labels проставлены?
  - Dashboard для FinOps готов?
  - Алерты на стоимость настроены?

Node optimization:
  - Resource requests оптимизированы?
  - Node pool настроен для KEDA workload?
  - Spot instances рассмотрены?
  - Cluster Autoscaler / Karpenter интегрированы?

Validation:
  - ROI рассчитан?
  - Cost-per-unit определена?
  - Idle cost измерена?
  - План замера эффекта готов?
```

## См. также

* **[KEDA: Практические сценарии](./practical_scenarios.md)** — триггеры и их конфигурация
* **[KEDA + Kafka](./kafka-keda-scaler.md)** — масштабирование по consumer lag
* **[KEDA + Redis](./redis-keda-scaler.md)** — масштабирование по длине очереди/стрима
* **[KEDA: Эксплуатация — мониторинг и troubleshooting](./keda-operations.md)** — мониторинг, алерты, типовые проблемы
* **[KEDA: Основные концепции](./keda_concepts.md)** — архитектура, ограничения, сравнение с HPA
* **[KEDA: Тестирование и валидация](./keda-testing-validation.md)** — проверка масштабирования
* **[KEDA: Вопросы для собеседования](./keda-interview-questions.md)** — систематизация вопросов
* **[Паттерн Workers + Queue](../workers_queue_pattern.md)** — проектирование систем обработки очередей
* **[Kubecost/OpenCost](../../MonitoringLogging/kubecost.md)** — мониторинг затрат в Kubernetes
