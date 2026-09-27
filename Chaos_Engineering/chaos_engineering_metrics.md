# Метрики в Chaos Engineering

## Определения

**Метрики в Chaos Engineering** — это количественные показатели, используемые для валидации гипотез об устойчивости системы. Они позволяют объективно оценить поведение сервиса в условиях контролируемого сбоя, сравнивая его с **устойчивым состоянием (Steady State)**.

Основная цель измерений — подтвердить, что при инъекции сбоя ключевые индикаторы качества (**SLI**) остаются в рамках целевых уровней (**SLO**), а механизмы самовосстановления отрабатывают за регламентированное время, не исчерпывая критическую долю **бюджета ошибок (Error Budget)**.

## Основные концепции

### Иерархия метрик по уровням воздействия

Для полной картины эксперимента необходимо отслеживать метрики на разных уровнях:

| Уровень | Категория | Примеры показателей | Техническая ценность |
|:---|:---|:---|:---|
| **L0** | Бизнес-метрики | Заказы в минуту, транзакции, активные сессии | Главный индикатор: если L0 падает, эксперимент провален. |
| **L1** | Пользовательский опыт | p99 Latency, Error Rate (5xx), Apdex | Показывает, заметил ли пользователь деградацию системы. |
| **L2** | Системные ресурсы | CPU Steal, Disk I/O Wait, Network Drop | Выявление узких мест инфраструктуры при перераспределении нагрузки. |
| **L3** | Рантайм приложения | Thread Pool exhaustion, GC Pause, DB Pool stats | Обнаружение внутренних блокировок и утечек при отказах зависимостей. |

### Классификация по типу

**Golden Signals (4 ключевых сигнала):**
- **Latency:** Время обработки запроса. Измеряется в перцентилях (p50, p95, p99, p999). В Chaos Engineering важно использовать p99/p999, а не average, так как среднее скрывает «хвосты», которые разрушают пользовательский опыт.
- **Traffic:** Объем запросов к системе (RPS, пропускная способность). Позволяет отличить плановый всплеск от инцидента.
- **Errors:** Доля запросов, завершившихся с ошибкой (5xx, таймауты). Ratio-метрика надежнее, чем абсолютное число ошибок.
- **Saturation:** Уровень utilization ресурсов (CPU, память, диск, соединения). Позволяет выявить узкие места до отказа.

**SRE-метрики надежности:**
- **SLI (Service Level Indicator):** Измеримый показатель (latency, availability, throughput). В Chaos Engineering SLI используются для определения steady state и stop conditions.
- **SLO (Service Level Objective):** Целевое значение SLI за период (например, 99.9% запросов < 500ms). Задаёт порог для stop-switch.
- **Error Budget:** Допустимое количество нарушений SLO = 100% − SLO. Если эксперимент «съедает» бюджет — система недостаточно устойчивая.
- **Burn Rate:** Скорость расходования Error Budget при текущем уровне нарушений. Burn Rate > 1 означает, что если сбой продлится, SLO на месяц будет нарушен. Burn Rate = 0 при отсутствии ошибок.

**Метрики эффективности хаоса:**

| Метрика | Определение | Целевое значение |
|:---|:---|:---|
| **Blast Radius** | Процент затронутых ресурсов или пользователей | Минимум, достаточный для статистической значимости |
| **MTTD (Mean Time to Detect)** | Время от начала инъекции до срабатывания первого алерта | < 60 секунд |
| **MTTR (Mean Time to Recovery)** | Время от прекращения инъекции до возвращения в Steady State | Зависит от SLO |
| **Time to Signal** | Время, через которое команда понимает, что эксперимент вышел из-под контроля | < 30 секунд |
| **Confidence Score** | Интегральный показатель уверенности в устойчивости системы | Растет с количеством успешных экспериментов |

### Методология определения Steady State

Steady State (устойчивое состояние) — это не статичное число, а диапазон нормального поведения.
- **Исторический Baseline:** Сравнение текущих метрик с показателями за аналогичный период прошлого дня или недели (`offset 1w` в PromQL) для учета циклической нагрузки.
- **Seasonality (Сезонность):** Учет пиков (маркетинговые акции, праздники). В эти периоды хаос-эксперименты обычно запрещены.
- **Confidence Score:** Интегральный показатель уверенности. Если при росте нагрузки или небольших сбоях метрики L1 остаются стабильными, Confidence Score растет.
- **Multi-metric Correlation:** Steady State проверяется не одной метрикой, а корзиной (latency + error rate + saturation). Одиночное значение может быть обманчиво.

### Принципы выбора метрик для эксперимента

1. **Измеримость:** Метрика должна быть доступна в реальном времени (push или pull).
2. **Релевантность:** Прямо связана с пользовательским опытом или бизнес-процессом.
3. **Стабильность baseline:** Достаточно данных за 7–14 дней для расчета нормального диапазона.
4. **Детерминированность:** При повторном эксперименте метрика должна вести себя предсказуемо.
5. **Достаточность:** Минимум 3 метрики из разных уровней (L0/L1/L2) для кросс-валидации.

## Практические сценарии

### Вычисление коэффициента замедления (Slowdown Factor)

Сравнение текущего p99 с историческим значением (час назад).

```promql
# Отношение текущей задержки к исторической
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
/
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1h)))
```
*Интерпретация:* Значение > 1.5 может быть поводом для срабатывания Stop-switch.

### Мониторинг выгорания бюджета ошибок (Error Budget Burn Rate)

Позволяет понять, насколько быстро эксперимент «съедает» надежность системы.

```promql
# Скорость выгорания относительно SLO (99.9%)
sum(rate(http_requests_total{status=~"5.."}[5m]))
/
(sum(rate(http_requests_total[5m])) * (1 - 0.999))
```
*Интерпретация:* Значение > 1 означает, что если сбой продлится, SLO на месяц будет нарушен.

### Обнаружение "зомби-соединений" при сетевом хаосе

Следим за ростом открытых соединений при имитации потери пакетов.

```promql
# Рост числа соединений, ожидающих ответа
sum(node_netstat_Tcp_ActiveOpens) - sum(node_netstat_Tcp_PassiveOpens)
```

### Расчет исторического baseline

```promql
# Медианная задержка за прошлую неделю
histogram_quantile(0.5, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1w)))

# p99 за прошлую неделю
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1w)))
```

### Мониторинг saturation (насыщение ресурсов)

```promql
# Утилизация CPU (container)
rate(container_cpu_usage_seconds_total[5m]) / rate(container_cpu_cfs_quota_total[5m]) * 100

# Утилизация памяти (container)
container_memory_working_set_bytes / container_spec_memory_limit_bytes * 100

# Доступные дескрипторы
node_filefd_allocated / node_filefd_maximum * 100
```

## Операции и команды

### PromQL — типовые запросы для экспериментов

| Операция | Запрос / Команда |
|:---|:---|
| **Текущий p99 latency** | `histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` |
| **Исторический p99 (1 час назад)** | `histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1h)))` |
| **Burn Rate (SLO 99.9%)** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / (sum(rate(http_requests_total[5m])) * (1 - 0.999))` |
| **Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` |
| **CPU utilization** | `rate(container_cpu_usage_seconds_total[5m]) / rate(container_cpu_cfs_quota_total[5m]) * 100` |
| **Memory utilization** | `container_memory_working_set_bytes / container_spec_memory_limit_bytes * 100` |
| **File descriptors saturation** | `node_filefd_allocated / node_filefd_maximum * 100` |
| **Active vs Passive connections** | `sum(node_netstat_Tcp_ActiveOpens) - sum(node_netstat_Tcp_PassiveOpens)` |

### Alertmanager — правила для Stop-switch

```yaml
groups:
  - name: chaos_experiment_alerts
    rules:
      - alert: ChaosExperimentCriticalErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.05
        for: 30s
        labels:
          severity: critical
          experiment: "{{ $labels.experiment }}"
        annotations:
          summary: "Error rate превысил 5%"
          description: "Текущий error rate: {{ $value | humanizePercentage }}"

      - alert: ChaosExperimentLatencyDegradation
        expr: |
          histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
          /
          histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m] offset 1h))) > 1.5
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "p99 latency вырос в 1.5+ раза"

      - alert: ChaosExperimentConnectivityLoss
        expr: |
          (up{job="service-a"} == 0)
          /
          count(up{job="service-a"}) > 0.2
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Потеря связности > 20% реплик"

      - alert: ChaosExperimentBusinessStop
        expr: |
          rate(orders_total[5m]) < (histogram_quantile(0.5, rate(orders_total[1d] offset 1d)) * 0.8)
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Бизнес-метрика упала ниже 80% baseline"
```

### Grafana — панели для наблюдения за экспериментом

| Панель | Запрос / Настройка |
|:---|:---|
| **Latency p50/p95/p99** | `histogram_quantile(0.5, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))` |
| **Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` |
| **Burn Rate gauge** | Burn Rate формула из Alertmanager, визуализация gauge |
| **Throughput (RPS)** | `sum(rate(http_requests_total[5m]))` |
| **CPU saturation** | `rate(container_cpu_usage_seconds_total[5m]) / rate(container_cpu_cfs_quota_total[5m]) * 100` |
| **Memory saturation** | `container_memory_working_set_bytes / container_spec_memory_limit_bytes * 100` |
| **File descriptors** | `node_filefd_allocated / node_filefd_maximum * 100` |

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Алерты не срабатывают во время эксперимента** | Метрика не существует или label mismatch | Проверьте `up` и availability probe для целевого сервиса. Убедитесь, что job в Prometheus активен. |
| **False positive: алерт сработал без хаоса** | Сезонный пик или соседний эксперимент | Добавьте `without (instance)` агрегацию, настройте `for:` длительность. Используйте `offset` для сравнения с baseline. |
| **Burn Rate всегда 0** | SLO слишком мягкий или метрика 5xx отсутствует | Проверьте, что `http_requests_total` имеет label `status`. Убедитесь в правильности порога SLO. |
| **Latency p99 скачет без хаоса** | GC pause или cold start | Добавьте `jitter` к baseline, используйте `avg_over_time()` вместо `rate()` для сглаживания. |
| **Error Budget расходуется слишком быстро** | SLO нереалистично низкий или реальный деградация | Пересмотрите SLO. Если деградация реальная — эксперимент корректен, остановите его и разберитесь с проблемой. |
| **Steady State смещается во время эксперимента** | Наличие другого трафика (боты, фоновые задания) | Изолируйте трафик эксперимента (separate path или label). Используйте `sum without (job)` для фильтрации. |
| **Метрики L3 не собираются** | Exporter не настроен или метрики неэкспортируются | Проверьте JMX exporter (Java), pg_stat_statements (PostgreSQL), custom metrics (App). |
| **PromQL возвращает no data** | Интервал сбора слишком большой | Уменьшите `scrape_interval` в Prometheus. Для коротких экспериментов используйте `[1m]` вместо `[5m]`. |

## Лучшие практики

### Выбор и проектирование метрик

1. **Начинайте с Golden Signals** — latency, traffic, errors, saturation покрывают 80% сценариев.
2. **Используйте перцентили, а не среднее** — p99/p999 показывают «хвосты», которые разрушают пользовательский опыт.
3. **Группируйте метрики в корзину** — минимум 3 метрики из разных уровней (L0, L1, L2) для кросс-валидации.
4. **Версионируйте SLO** — храните SLO в Git рядом с кодом. Изменение SLO = изменение контракта с пользователем.
5. **Автоматизируйте baseline** — baseline должен пересчитываться каждую неделю, а не задаваться вручную один раз.

### Измерение и интерпретация

6. **Сравнивайте с baseline, а не с абсолютными порогами** — 100ms latency приемлемы для одного сервиса и неприемлемы для другого.
7. **Учитывайте seasonality** — исключайте из baseline дни распродаж, релизов и патч-вторников.
8. **Используйте ratio-метрики вместо absolute** — error rate (ошибки/все запросы) надежнее, чем абсолютное число ошибок.
9. **Коррелируйте метрики во времени** — latency spike + error rate spike + saturation spike = деградация. Одиночный спред — возможно, шум.
10. **Фиксируйте confidence score** — ведите историю успешных экспериментов. 10+ успешных runs дают high confidence для production.

### Автоматизация и governance

11. **Stop-switch — обязателен** — автоматическая остановка по метрикам, а не по таймауту. Таймаут — fallback, а не основной механизм.
12. **Alert fatigue — враг** — настройте `for:` длительность, используйте severity tiers, дедуплицируйте алерты.
13. **Экспериментируйте в staging с production-метриками** — если staging не имеет того же уровня мониторинга, что и production, выводы будут неточными.
14. **Ведите runbook для каждого эксперимента** — цель, гипотеза, метрики, baseline, критерии успеха, критерии остановки.
15. **После эксперимента — post-mortem метрики** — фиксируйте MTTD, MTTR, Time to Signal, blast radius фактический. Это данные для улучшения следующих экспериментов.

### Избегайте ошибок

16. **Не полагайтесь на одно метрику** — если latency выросла, но error rate и traffic стабильны, это может бытьplanned maintenance, а не деградация.
17. **Не игнорируйте L2/L3 при положительных L0/L1** — бизнес-метрики могут не упасть, если кэш работает, а база данных уже мертва.
18. **Не забывайте про retry storm** — error rate может выглядеть нормальной, если клиент ретраит. Смотрите RPS вместе с error rate.
19. **Не используйте average latency** — среднее скрывает хвосты. Используйте p99/p999.
20. **Не оставляйте эксперимент без cleanup** — после остановки убедитесь, что все CRD/политики удалены, метрики вернулись к baseline.

## Дополнительная информация

### Типичные ошибки интерпретации

- **Парадокс среднего:** Средняя задержка (average) остается в норме, но p99.9 вырастает в 10 раз. Хаос-инженерия всегда работает с «хвостами» распределения.
- **Retry Storm (Шторм повторов):** Метрика Error Rate может выглядеть стабильной, если клиент делает много попыток, но при этом резко растет RPS и задержка. Необходимо анализировать эти метрики в связке.
- **Маскировка сбоя кэшем:** Если при отключении БД сервис продолжает отдавать 200 OK из кэша, эксперимент может показаться успешным. Важно проверять метрику `cache_hit_ratio` и `db_query_duration`.
- **Baseline drift:** Если baseline считается за 7 дней, а в этот период был релиз, то «норма» уже искажена. Пересчитывайте baseline после значимых изменений.

### Интеграция с DORA

Хаос-эксперименты напрямую влияют на метрики DORA:
- **Change Failure Rate (CFR):** Снижается за счет выявления багов конфигурации до деплоя в Prod.
- **MTTR:** Улучшается за счет отработки сценариев восстановления и настройки качественного алертинга.

### См. также

* [SRE: SLA, SLO, SLI и метрики надежности](../Concepts/sre_concepts_main.md) — теория SLI/SLO/Error Budget
* [Инструменты Chaos Engineering](chaos_engineering_tools.md) — пайплайн эксперимента, stop-switch, blast radius
* [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days, диагностика, runbook
* [Chaos Engineering — тестирование resilience-паттернов](chaos_resilience_patterns_testing.md) — метрики Circuit Breaker, Bulkhead.
* [Chaos Engineering — observability](chaos_observability.md) — traces, logs, audit trail.
* [Chaos Engineering — maturity model](chaos_maturity_and_governance.md) — KPIs для программы.
