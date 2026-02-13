# Мониторинг и оценка трафика при Canary-развертывании

## Определения

**Мониторинг при поэтапном выпуске** предполагает сравнение поведения новой (canary) версии с эталонной (stable) при ограниченной доле реального трафика. Задача — обнаруживать регрессии достаточно рано, чтобы остановить раскатку до массового влияния на пользователей, опираясь на измеримые сигналы и воспроизводимую методику оценки.

## Основные концепции

### Атрибуция и качество трафика

Чтобы корректно отделить запросы канареечной версии от стабильной, применяются:

*   **Метки маршрутизации** на уровне балансировщика или service mesh (например, заголовок, cookie, поле версии).
*   **"Липкие" сессии (Sticky sessions)**: один пользователь в течение окна оценки всегда попадает в один и тот же вариант.
*   **Равномерная выборка**: доля трафика 1–5% для старта, затем ступенчатое увеличение.

Важно включать в метрики признак версии (например, `version="canary" | "stable"`) и прокидывать корреляционные идентификаторы для сквозной трассировки.

### Ключевые сигналы и срезы

Сигналы делятся на **пользовательские** и **системные**. Для оценки применяются окна 5–15 минут с защитой от флуктуаций.

| Сигнал | Описание | Пример запроса (Prometheus) |
| :--- | :--- | :--- |
| **Ошибки (Error rate)** | Доля 5xx/4xx к общим запросам | `sum(rate(http_requests_total{version="canary",code=~"5.."}[5m])) / sum(rate(http_requests_total{version="canary"}[5m]))` |
| **Задержка (p95/p99)** | Квантили по гистограммам времени ответа | `histogram_quantile(0.95, sum by (le,version) (rate(http_request_duration_seconds_bucket[5m])))` |
| **Успех транзакций** | Уровень выполнения бизнес-операций | `sum(rate(orders_created_total{version="canary"}[5m])) / sum(rate(orders_attempted_total{version="canary"}[5m]))` |
| **Насыщение (Saturation)**| Утилизация CPU/Memory, длина очередей | `avg(node_cpu_seconds_total{mode="idle",version="canary"})` |

Сравнение всегда относительное: **«канарейка против стабильной версии»** по одним и тем же срезам и временным окнам.

## Практические сценарии

### Примеры сравнения и алертинга (Prometheus)

*   **Сопоставление долей ошибок:**
    ```promql
    # Вычисляем долю ошибок для canary
    canary_err = sum(rate(http_requests_total{version="canary",code=~"5.."}[5m])) 
                 / sum(rate(http_requests_total{version="canary"}[5m]))
    
    # Вычисляем долю ошибок для stable
    stable_err = sum(rate(http_requests_total{version="stable",code=~"5.."}[5m])) 
                 / sum(rate(http_requests_total{version="stable"}[5m]))

    # Условие для алерта: ошибка на canary на 20% выше, чем на stable, И при этом абсолютное значение выше 1%
    (canary_err - stable_err) > 0.2 * stable_err and canary_err > 0.01
    ```

*   **Сравнение задержки p95:**
    ```promql
    canary_p95 = histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{version="canary"}[5m])))
    stable_p95 = histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{version="stable"}[5m])))

    # Условие для алерта: p95 на canary в 1.25 раза выше, чем на stable
    (canary_p95 / stable_p95) > 1.25
    ```

*   **Пример алерта на деградацию:**
    ```yaml
    alert: CanaryDegradation
    expr: |
      (
        (sum(rate(http_requests_total{version="canary",code=~"5.."}[5m])) / sum(rate(http_requests_total{version="canary"}[5m]))) > 
        2 * 
        (sum(rate(http_requests_total{version="stable",code=~"5.."}[5m])) / sum(rate(http_requests_total{version="stable"}[5m])))
        and
        (sum(rate(http_requests_total{version="canary",code=~"5.."}[5m])) / sum(rate(http_requests_total{version="canary"}[5m]))) > 0.02
      )
      or
      (
        histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{version="canary"}[5m]))) >
        1.3 *
        histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{version="stable"}[5m])))
      )
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Канарейка деградирует по качеству"
    ```

### Автоматизация оценки и "ворота" раскатки (Gating)

**Алгоритм в CI/CD pipeline:**

1.  Применить трафик (например, 5%) и прогреть кэш (2–3 минуты) без принятия решений.
2.  Собрать метрики за окно `T` и вычислить риск-скор (ошибки, задержка, нагрузка, бизнес-конверсия).
3.  Принять решение: **продолжить**, **подержать** или **откатить**.

**Пример декларативного «гейта»:**
```yaml
canary_gate:
  window: 10m
  hold_before_decision: 3m
  require_samples: 1000
  thresholds:
    error_rate:
      rel_increase: 0.5  # относительное увеличение не более 50%
      abs: 0.02          # абсолютное значение не более 2%
    latency_p95:
      ratio: 1.25        # не более чем в 1.25 раза медленнее stable
    business_success:
      drop_ratio: 0.1    # падение не более 10%
  actions:
    pass: increase_traffic: 5% -> 20%
    hold: keep_traffic: current
    fail: rollback: immediate
```

## Дополнительная информация

### Логи и трассировки для причинного анализа

При срабатывании порогов метрик рекомендуется включать повышенную выборку логов и трейсов только для канареечной версии. Используйте метки `version` и `correlation_id` для связывания событий. Это помогает подтвердить, что рост ошибок обусловлен конкретными эндпойнтами или зависимостями, а не случайной дисперсией.

### Связанные документы
- **[Canary Deployments: Пошаговое внедрение](./canary_deployment.md)** — основной документ, описывающий процесс канареечного развертывания.
