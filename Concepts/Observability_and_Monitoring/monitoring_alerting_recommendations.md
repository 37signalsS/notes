# Рекомендации по мониторингу и алертингу

**Актуально для:** Prometheus 3.13.x (LTS) / 3.14.x, Alertmanager 0.34.x, Zabbix 7.0 LTS / 7.4, VictoriaMetrics 1.52.x, node_exporter 1.12.x, blackbox_exporter 0.28.x

## Определения

**Алерт (Alert)** -- уведомление о событии, требующем внимания оператора, генерируемое системой мониторинга при выполнении заданных условий.

**Правило алертинга (Alert Rule)** -- логическое выражение (на базе PromQL, SQL или других языков), определяющее порог или условие срабатывания оповещения.

**Действенность (Actionability)** -- ключевая характеристика качественного алерта. Каждое оповещение должно подразумевать конкретное действие со стороны человека или автоматики. Если действие не требуется -- это не алерт, а информационная метрика на дашборде.

**Шторм оповещений (Alert Storm)** -- каскадное срабатывание множества вторичных алертов, вызванное одной корневой причиной (например, падение коммутатора вызывает тысячи алертов на серверах).

**Alert Fatigue (Усталость от алертов)** -- психологический эффект, при котором избыточное количество некритичных или ложных уведомлений приводит к десенсибилизации дежурного инженера, росту MTTR и игнорированию критических инцидентов.

**Дребезг (Flapping)** -- состояние, когда метрика колеблется около порогового значения, вызывая каскад уведомлений «Alerting» и «Resolved».

**Silence (Заглушение)** -- временная приостановка доставки уведомлений по набору меток на заданный интервал. Используется при плановых работах, но не отменяет сам алерт -- он продолжает гореть в UI.

**Inhibition (Подавление)** -- механизм Alertmanager, который автоматически отключает уведомления для зависимых компонентов, если корневой компонент уже «в алерте».

**Группировка (Grouping)** -- объединение нескольких алертов с общими метками в одно уведомление. Предотвращает «лавину» сообщений при массовом отказе.

**Recording Rule** -- правило Prometheus, которое предварительно вычисляет сложный PromQL-запрос и сохраняет результат как новую метрику. Используется для ускорения дашбордов и алертов на основе тяжелых вычислений.

---

## Базовые концепции

### Золотые правила SRE для алертинга

Для обеспечения высокой надежности при минимальном шуме необходимо следовать принципам Google SRE:

1. **Действенность (Actionability):** На каждый алерт должен существовать Runbook. Если уведомление не требует немедленного действия (например, «диск заполнен на 60%»), оно должно быть метрикой, а не алертом.
2. **Детектирование симптомов, а не причин:** Алерты на симптомы (рост 5xx ошибок, Latency) надежнее алертов на причины (загрузка CPU). Причины могут меняться, симптомы -- остаются.
3. **Иерархия критичности (Severity):**
    - **Emergency (P0):** Система лежит. Звонок через PagerDuty/Opsgenie. Немедленное прерывание сна.
    - **Critical (P1):** Деградация критического функционала. Уведомление в Slack/Telegram с обязательным подтверждением (Ack).
    - **Warning (P2):** Потенциальная проблема или деградация некритичных систем. Рассматривается в рабочее время.
    - **Info (P3):** Только для записи в истории или визуализации (например, факт успешного бэкапа).

### Управление потоком уведомлений

Для предотвращения Alert Storm и снижения нагрузки используются механизмы **[Alertmanager](../../Prometheus/alertmanager.md)**:

- **Группировка (Grouping):** Объединение алертов по общим меткам (например, `cluster`, `service`). Вместо 100 сообщений об упавших подах дежурный получает одно сводное уведомление. Параметры: `group_wait` (30с-1м) -- время на сбор алертов в группу; `group_interval` (5м) -- интервал между повторными уведомлениями; `repeat_interval` (4ч) -- интервал повтора нерешенного алерта.
- **Подавление (Inhibition):** Отключение уведомлений для зависимых компонентов, если корневой компонент уже «в алерте» (например, не алертить о недоступности API, если упал весь кластер БД).
- **Заглушение (Silencing):** Временное отключение оповещений на период плановых работ. Рекомендуется автоматизировать создание сайленсов через CI/CD при проведении деплоев.
- **De-flapping (Дребезг):** Использование параметра `for` (например, `for: 5m`) для фильтрации кратковременных выбросов метрик. Рекомендуется устанавливать `for` не менее чем в 3-5 раз больше интервала оценки (например, `evaluate every 1m` -> `for: 5m`).
- **keep_firing_for:** Удерживает алерт в состоянии `Firing` в течение заданного времени даже после возвращения метрики в норму. Предотвращает каскад «resolve -> fire» при восстановлении и преждевременное закрытие инцидента.
- **Каналы уведомлений:** Четкое распределение: критические -- в системы дежурства (PagerDuty, SMS), информационные -- в тематические Slack-каналы.

### Иерархия маршрутизации

Стройте дерево политик уведомлений от общего к частному. Alertmanager поддерживает вложенность маршрутов:

1. **Корневой маршрут:** общий `receiver` для всех алертов с дефолтными таймингами.
2. **Дочерние маршруты:** фильтрация по меткам (`service`, `team`, `severity`) с переопределением `receiver` и таймингов.
3. **Продолжение сопоставления (`continue: true`):** используется только если один алерт должен попасть в несколько независимых каналов (например, в лог-систему и в мессенджер).

**Пример конфигурации маршрутизации (alertmanager.yml):**

```yaml
route:
  receiver: 'default-slack'
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
    - match:
        severity: warning
      receiver: 'slack-warnings'
    - match_re:
        service: 'payment|checkout'
      receiver: 'team-payments-slack'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['cluster', 'service']
```

### Заглушки (Silences): практические рекомендации

- **Срок действия:** ставьте сайленсы на минимально необходимый срок (1-4 часа для деплоя, а не на неделю).
- **Метки:** матчьтесь по `alertname` + `service`, а не по `severity` (иначе можно случайно заглушить критические алерты другого сервиса).
- **Автоматизация:** создавайте сайленсы через API при начале деплоя и удаляйте при завершении (CI/CD интеграция).
- **Мета-мониторинг:** отслеживайте количество активных сайленсов (`alertmanager_silences`). Аномальный рост -- повод для проверки.

---

## Recording Rules для алертинга

Recording rules позволяют предварительно вычислять тяжелые PromQL-запросы и сохранять результат как новую метрику. Это критически важно для алертов, которые используют сложные агрегации.

### Зачем нужны recording rules для алертов

1. **Производительность:** алерт не должен вычислять `histogram_quantile(rate(...[5m]))` на лету -- это нагружает Prometheus.
2. **Стабильность:** результат recording rule фиксируется в момент вычисления, что исключает гонки (race conditions) между вычислением и использованием.
3. **Переиспользование:** одна recording rule может использоваться в нескольких алертах и дашбордах.

### Пример: recording rule для Burn Rate

```yaml
groups:
  - name: slo_recording_rules
    rules:
      # Доля ошибок за 5 минут
      - record: job:http_requests:error_rate5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)

      # Burn Rate = (фактическая частота ошибок) / (целевая частота ошибок)
      - record: job:slo:error_burn_rate
        expr: |
          job:http_requests:error_rate5m / (1 - 0.999)
        # Для SLO 99.9%: целевая частота ошибок = 0.1% = 0.001

      # 1-часовой Burn Rate
      - record: job:slo:error_burn_rate_1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h])) by (job)
          /
          sum(rate(http_requests_total[1h])) by (job)
          / 0.001
```

### Пример: alerting rule с использованием recording rule

```yaml
groups:
  - name: slo_alerts
    rules:
      - alert: HighErrorBurnRate
        expr: job:slo:error_burn_rate > 14.4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO: высокая скорость выгорания бюджета ошибок ({{ $labels.job }})"
          runbook_url: "https://docs.internal/runbooks/slo-burn-rate"
          description: "Burn Rate {{ $value | humanize }}x превышает допустимый порог."
```

---

## Практические сценарии

### Сценарий 1: Многооконный алертинг по скорости выгорания (Burn Rate)

Вместо статических порогов рекомендуется использовать метод Burn Rate для контроля SLO. Это позволяет поймать как резкие всплески ошибок, так и медленные утечки.

| Тип алерта | Окно (длинное) | Окно (короткое) | Burn Rate | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **Critical** | 1 час | 5 минут | 14.4 | 2% бюджета сгорит за 1 час. |
| **Critical** | 6 часов | 30 минут | 6 | 5% бюджета сгорит за 6 часов. |
| **Warning** | 1 день | 2 часа | 3 | 10% бюджета сгорит за 24 часа. |
| **Ticket** | 3 дня | -- | 1 | Бюджет сгорает со скоростью нормы. |

**Математика:** Burn Rate = (фактическая частота ошибок) / (целевая частота). Для SLO 99.9%: целевая частота = 0.1% = 0.001. Burn Rate 14.4x означает, что ошибки происходят в 14.4 раза чаще допустимого.

**Промежуточные окна:** двухоконная система работает по принципу «короткое окно подтверждает длинное». Короткое окно (5 мин) -- быстрый триггер для резких всплесков. Длинное окно (1 час) -- фильтрация ложных срабатываний. Алерт срабатывает только когда оба окна показывают превышение порога.

**Валидация:**
1. Искусственно вызвать всплеск ошибок (например, через `curl` к тестовому эндпоинту).
2. Убедиться, что короткое окно быстро перевело алерт в состояние `Firing`.
3. Проверить расчет Burn Rate в Grafana SLO Dashboard.

### Сценарий 2: Настройка параметров NoData и For

Для повышения стабильности алертов используйте параметры оценки:

- **`for: 5m`**: Фильтрует случайные пики («иголки») на графиках. Рекомендуется: `for >= 3 * scrape_interval`.
- **`keep_firing_for: 10m`**: Удерживает алерт в состоянии Firing после нормализации метрики. Предотвращает преждевременное закрытие инцидента.
- **`NoData`**:
    - Для жизненно важных сервисов (`up == 0` или `absent`): `Alerting`.
    - Для кастомных бизнес-метрик: `OK` (чтобы не спамить при естественном отсутствии трафика ночью).

**Отличие `for` от `keep_firing_for`:**
- `for: 5m` -- алерт переходит в Firing только если условие истинно **непрерывно** 5 минут.
- `keep_firing_for: 10m` -- после того как условие стало ложным, алерт **продолжает гореть** еще 10 минут.

### Сценарий 3: Минимальный Production-мониторинг

Набор алертов «первого дня» для нового сервиса:

1. **Availability:** `up == 0` (сервис недоступен для скрейпинга).
2. **Errors (RED):** Высокая доля 5xx ответов (через Burn Rate).
3. **Latency (RED):** Рост p99 задержки выше порога (например, > 2с).
4. **Resources:** События `OOMKilled` и заполнение диска > 80% (с учетом скорости роста).

### Сценарий 4: Алерты на основе Recording Rules (динамические пороги)

Вместо жестких констант используйте recording rules для вычисления порогов на основе исторических данных:

```yaml
groups:
  - name: dynamic_thresholds
    rules:
      # Средняя задержка за неделю (rolling baseline)
      - record: job:api:p95_latency_baseline_7d
        expr: |
          quantile_over_time(0.95, http_request_duration_seconds{job="api"}[7d])

      # Алерт: текущая p95 превышает baseline более чем на 50%
      - alert: LatencyRegression
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api"}[5m]))
          > 1.5 * job:api:p95_latency_baseline_7d
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Задержка API выросла относительно недельного baseline"
          runbook_url: "https://docs.internal/runbooks/latency-regression"
```

### Сценарий 5: Автоматическое тестирование алертинга

Рекомендуется периодически проверять, что алерты реагируют на изменения:

```bash
# 1. Проверка синтаксиса правил
promtool check rules /etc/prometheus/rules/*.yml

# 2. Тестирование правил на исторических данных
promtool test rules /etc/prometheus/tests/alerting_tests.yml

# 3. Ручной тест: отправка всплеска ошибок
for i in $(seq 1 100); do
  curl -s http://app:8080/api/error-endpoint > /dev/null
done

# 4. Проверка состояния алертов
curl -s http://prometheus:9090/api/v1/alerts | jq '.data.alerts[] | {alertname: .labels.alertname, state: .state}'
```

**Пример файла тестов (alerting_tests.yml):**

```yaml
rule_files:
  - /etc/prometheus/rules/slo_alerts.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'http_requests_total{status="200", job="api"}'
        values: '0+100x10'  # 100 запросов/сек, все успешные
      - series: 'http_requests_total{status="500", job="api"}'
        values: '0+10x10'   # 10 ошибок/сек (10% -- выше SLO)

    alert_rule_test:
      - eval_time: 6m
        alertname: HighErrorBurnRate
        exp_alerts:
          - exp_labels:
              severity: critical
              job: api
```

### Сценарий 6: Алертинг на статической инфраструктуре (SNMP, СХД, Windows)

Для систем без Prometheus-экспортёров используйте SNMP-опрос, Zabbix Agent или windows_exporter:

| Компонент | Метод сбора | Пример алерта |
| :--- | :--- | :--- |
| **Сетевое оборудование** | SNMP (snmp_exporter) | `ifOperStatus != 1` -- интерфейс отключен |
| **СХД / SAN** | SNMP (snmp_exporter) | `diskStatus != 0` -- деградация массива |
| **Windows Server** | windows_exporter | `os_memory_free_bytes < 10%` -- низкая память |
| **UPS / ИБП** | SNMP (snmp_exporter) | `upsBatteryCharge < 20` -- замена батареи |
| **Температура в ЦОД** | SNMP (snmp_exporter) | `envTemperature > 35` -- перегрев |

**Zabbix-альтернатива для статической инфраструктуры:**
Вместо Prometheus + Alertmanager используйте Triggers + Actions в Zabbix для инфраструктуры, где SNMP-опрос устоен лучше, чем HTTP-экспортёры. Zabbix автоматически обнаруживает интерфейсы и OID через Low-Level Discovery (LLD), что снижает ручной труд при добавлении нового оборудования.

**Пример SNMP-алерта через snmp_exporter + Prometheus:**

```yaml
groups:
  - name: infrastructure_alerts
    rules:
      - alert: NetworkInterfaceDown
        expr: snmp_ifOperStatus{device="switch01", ifOperStatus="1"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Интерфейс {{ $labels.ifDescr }} на {{ $labels.device }} отключен"
          runbook_url: "https://docs.internal/runbooks/network-interface-down"

      - alert: StorageArrayDegraded
        expr: snmp_diskStatus{device="san01"} != 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "СХД {{ $labels.device }} в деградированном состоянии"
          runbook_url: "https://docs.internal/runbooks/storage-degraded"
```

### Сценарий 7: Алертинг в air-gapped сети (без доступа в интернет)

В изолированных сегментах (без интернета) необходимо:

1. **Self-hosted коммуникации:** Вместо SaaS-сервисов (PagerDuty, Opsgenie) используйте self-hosted решения:
   - **Grafana OnCall** (self-hosted) -- эскалации, ротации, расписание дежурств
   - **GoAlert** -- open-source альтернатива с веб-интерфейсом и API
   - **Healthchecks.io** (self-hosted) -- Dead Man's Switch для внешнего watchdog
   - **Mattermost / Rocket.Chat** (self-hosted) -- замена Slack с webhook-интеграцией

2. **Локальный DNS и хранилище образов:** Harbor (Docker Registry) + внутренний DNS для всех компонентов мониторинга.

3. **Alertmanager без внешних провайдеров:** Используйте email через внутренний SMTP-сервис или webhook на внутренний Mattermost/Zulip.

4. **Watchdog через внутреннюю инфраструктуру:**
   - Второй Prometheus в смежной зоне, опрашивающий первый
   - Внешний watchdog на dedicated-хосте с доступом к обоим сегментам

**Пример Alertmanager без интернета:**

```yaml
global:
  smtp_smarthost: 'mail.internal.example.com:25'
  smtp_from: 'alertmanager@internal.example.com'

receivers:
  - name: 'team-oncall-email'
    email_configs:
      - to: 'oncall@internal.example.com'
        send_resolved: true

  - name: 'mattermost-webhook'
    webhook_configs:
      - url: 'http://mattermost.internal.example.com/hooks/alertmanager'
        send_resolved: true

  - name: 'watchdog-internal'
    webhook_configs:
      - url: 'http://watchdog.internal.example.com/ping/uuid-here'
        send_resolved: true

route:
  receiver: 'team-oncall-email'
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'mattermost-webhook'
    - match:
        meta_target: watchdog
      receiver: 'watchdog-internal'
```

---

## Обнаружение аномалий (Anomaly Detection)

Для выявления проблем, не достигающих жестких порогов (например, плавный рост трафика), используйте статистические методы.

**1. Учет сезонности:** Сравнение текущего значения с тем же периодом неделю назад (`offset 1w`).

**2. Z-Score (PromQL):**
```promql
# Алерт, если метрика отклоняется более чем на 3 стандартных отклонения от среднего за неделю
(abs(metric - avg_over_time(metric[1w])) / stddev_over_time(metric[1w])) > 3
```

**3. Процентильное отклонение:**
```promql
# Алерт, если текущее значение превышает 95-й перцентиль за 7 дней
(metric > quantile_over_time(0.95, metric[7d]))
```

**4. Детектирование тренда ( linear regression):**
```promql
# Прогноз на 1 час вперед через линейную регрессию
deriv(metric[6h]) > 0 and predict_linear(metric[1h], 3600) > threshold
```

---

## Антипаттерны алертинга

| Антипаттерн | Описание | Решение |
| :--- | :--- | :--- |
| **Hardcoded thresholds** | Жесткие пороги (CPU > 90%) не учитывают сезонность и рост. | Используйте recording rules для динамических порогов или Burn Rate для SLO. |
| **Alerting on causes** | Алерт на загрузку CPU вместо пользовательского опыта. | Детектируйте симптомы (5xx, Latency), а не причины (CPU, RAM). |
| **Missing `for`** | Алерт срабатывает на одиночный пик без подтверждения. | Устанавливайте `for >= 3 * scrape_interval` для фильтрации шума. |
| **Noisy neighbor** | Алерт срабатывает 100 раз в день, инцидент никогда не подтверждается. | Пересмотрите порог или удалите алерт. Alert budget: не более 5-10 страниц в смену. |
| **Missing runbook** | Дежурный получает уведомление, но не знает, что делать. | Каждый алерт обязан иметь `runbook_url` с пошаговой инструкцией. |
| **Too many severities** | 5+ уровней критичности (P0-P4) путают операторов. | Используйте 3 уровня: critical (звонок), warning (Slack/Ticket), info (лог). |
| **Grouping by instance** | Группировка по `instance`/`pod` создает шум при масштабировании. | Группируйте по `alertname` + `service`/`cluster`, избегайте высокой кардинальности. |
| **Ignoring `up == 0`** | Сервис недоступен, но алерт не срабатывает. | Всегда настраивайте алерт `up == 0` для критических сервисов. |

---

## Операционная поддержка: Runbooks

Ситуация «алерт горит, но никто не знает, что делать» -- признак некачественного мониторинга.

**Требования к Runbook:**
1. **Описание:** Что именно сломалось и каков бизнес-эффект (например, «пользователи не могут войти в ЛК»).
2. **Первичная диагностика:** Ссылки на конкретные дашборды и логи (Loki query).
3. **Алгоритм действий:**
    *   Проверить недавние изменения (деплои, конфиги).
    *   Проверить ресурсы (CPU/RAM/Saturation).
    *   Инструкция по экстренному откату (Rollback).
4. **Специфика:** Контакты владельцев сервиса и внешних команд поддержки.

**Шаблон Runbook (Markdown):**

```markdown
# Runbook: HighErrorBurnRate

## Что произошло
Доля ошибок в сервисе {{ $labels.job }} превышает допустимый порог SLO.
Текущий Burn Rate: {{ $value | humanize }}x.

## Бизнес-эффект
Пользователи испытывают ошибки при обращении к сервису.
Возможна потеря транзакций.

## Первичная диагностика
1. Дашборд: [Service Overview](https://grafana.internal/d/{{ $labels.job }}-overview)
2. Логи: `{job="{{ $labels.job }}"} | json | status >= 500`
3. Трейсы: [Explore](https://grafana.internal/explore?query={service="{{ $labels.job }}", status="error"})

## Алгоритм действий
1. Проверить статус сервиса: `systemctl status <service>` или `docker ps` / `podman ps`
2. Проверить логи: `journalctl -u <service> --since "10 minutes ago"` или `docker logs <container> --tail=100`
3. Проверить ресурсы: `top`, `htop`, `free -h`, `df -h`, `iostat`
4. Проверить недавние изменения: `git log --oneline -10` в репозитории конфигураций, историю деплоев
5. Если проблема после деплоя -- откат: переключение на предыдущую версию через ваш деплойный инструмент (Ansible, deploy script, CI/CD revert)

## Контакты
- Владелец сервиса: @team-{{ $labels.job }}
- Дежурный SRE: @sre-oncall
```

---

## Версионирование и тестирование правил

### Хранение в Git

Правила алертинга и recording rules должны храниться в Git и доставляться через CI/CD:

```
monitoring-rules/
├── alerting/
│   ├── slo_rules.yml
│   ├── infrastructure_rules.yml
│   └── application_rules.yml
├── recording/
│   ├── slo_recording.yml
│   └── infrastructure_recording.yml
└── tests/
    ├── slo_tests.yml
    └── infrastructure_tests.yml
```

### Валидация в CI/CD

```bash
# Проверка синтаксиса
promtool check rules monitoring-rules/**/*.yml

# Запуск тестов
promtool test rules monitoring-rules/tests/*.yml
```

### Контроль изменений

- Используйте Pull Requests для изменения правил.
- Указывайте в комментарии PR: какой алерт меняется, почему, какой ожидаемый эффект.
- После мержа -- проверяйте, что правила загрузились в Prometheus (метрике `prometheus_rule_group_last_duration_seconds`).

---

## Диагностика и профилактика системы алертинга

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Пропущенные инциденты** | Слишком длинный `for` или жесткие Inhibition rules. | Уменьшить окно `for`, проверить иерархию подавления. |
| **Alert Storm** | Отсутствие группировки в Alertmanager. | Настроить `group_by` по `alertname` и `service`. |
| **Устаревшие Runbooks** | Ссылки ведут на 404 или неактуальные регламенты. | Автоматизировать проверку ссылок в CI пайплайне правил. |
| **Stale Silences** | Забытые заглушки после завершения работ. | Автоматическое удаление через API при деплое + мониторинг количества активных сайленсов. |
| **Flapping (дребезг)** | Метрика колеблется около порога, вызывая cascade alert/resolve. | Увеличить `for`, использовать `keep_firing_for`, сглаживать запрос (`avg_over_time`). |
| **Высокая кардинальность в group_by** | Группировка по `pod`/`instance`/`trace_id` создает тысячи групп. | Группировать по `alertname` + `service`/`cluster`. |
| **Правила не загружаются** | Синтаксическая ошибка в YAML или PromQL. | `promtool check rules`, проверка логов Prometheus (`prometheus_rule_evaluation_failures_total`). |
| **Ложные срабатывания на NoData** | Алерт `absent()` срабатывает при кратковременной недоступности. | Увеличить `for` для `absent()` алертов до 5-10 минут. |
| **Alertmanager не отправляет** | Ошибка подключения к Slack/PagerDuty, истекший токен. | Проверить `alertmanager_notifications_failed_total`, логи Alertmanager. |
| **Дублирование алертов** | Два Prometheus в HA-паре отправляют одни и те же алерты. | Дедупликация в Alertmanager (по умолчанию), проверка `--cluster.peer`. |

---

## Мета-мониторинг системы алертинга

Мониторьте саму систему оповещений -- «тихий» сбой доставки останется незамеченным.

### Ключевые метрики

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `alertmanager_notifications_failed_total` | Ошибки доставки уведомлений | > 0 за 5 минут |
| `alertmanager_notifications_queue_length` | Длина очереди уведомлений | > 100 (рост -- проблема) |
| `alertmanager_silences` | Количество активных заглушений | Аномальный рост |
| `prometheus_rule_group_last_duration_seconds` | Время выполнения группы правил | > interval группы |
| `prometheus_rule_evaluation_failures_total` | Ошибки вычисления правил | > 0 (критично) |
| `prometheus_rule_group_iterations_missed_total` | Пропущенные циклы вычисления | > 0 (перегрузка) |

### Алерты на систему алертинга

```yaml
groups:
  - name: alerting_meta
    rules:
      - alert: AlertmanagerDeliveryFailed
        expr: rate(alertmanager_notifications_failed_total[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager: ошибки доставки уведомлений"
          runbook_url: "https://docs.internal/runbooks/alertmanager-delivery"

      - alert: PrometheusRuleEvaluationSlow
        expr: prometheus_rule_group_last_duration_seconds > prometheus_rule_group_interval_seconds
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Prometheus: замедленное вычисление правил"

      - alert: TooManyActiveSilences
        expr: alertmanager_silences > 20
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Слишком много активных заглушений -- возможны забытые сайленсы"
```

---

## Best Practices

### Принципы проектирования алертинга

1. **Алерты на симптомы, а не на причины:** Пользователь не чувствует `CPU > 90%`. Он чувствует `Latency P99 > 2s` и `Error Rate > 1%`. Симптоматические алерты стабильнее, потому что причины меняются (миграция, обновление железа), а симптомы -- нет.
2. **Каждый алерт требует действия (Actionability):** Если на уведомление нельзя отреагировать конкретным действием -- это не алерт, а дашборд. У каждого алерта должен быть `runbook_url`.
3. **Один алерт -- одна проблема:** Разделяйте алерты по компонентам и Severity. Не объединяйте «память заполнена на 80%» и «память заполнена на 95%» в один алерт -- это разные действия.
4. **Используйте Severity как маршрутизацию:** Critical (звонок), Warning (Slack/Ticket), Info (лог). Не больше 3-4 уровней -- иначе дежурный путается.

### Безопасность алертинга

- **Защита Alertmanager API:** Включите базовую аутентификацию или TLS. Ограничьте доступ к порту 9093 только сетью мониторинга.
- **Защита вебхуков:** Alertmanager webhook receiver может стать вектором атаки (SSRF). Используйте whitelist URL, ограничьте исходящие соединения firewall.
- **Секреты в конфигурациях:** Токены PagerDuty, Slack, Telegram храните в Vault или environment variables, а не в plaintext в `alertmanager.yml`.
- **Аудит изменений:** Все изменения правил алертинга проходят через Git + CI/CD. Логируйте все изменения в Alertmanager silences.

### Производительность и масштабируемость

- **Recording Rules для тяжелых запросов:** `histogram_quantile(rate(...[5m]))` на лету в алерте -- это нагрузка на Prometheus. Предвычисляйте через recording rules.
- **Группировка для снижения шума:** `group_by: ['alertname', 'service', 'cluster']` вместо `group_by: ['instance', 'pod']`. Высокая кардинальность в `group_by` создает тысячи групп при массовом отказе.
- **Интервалы повторения:** `repeat_interval: 4h` для нерешенных алертов. Чаще повторения не нужно -- дежурный и так видит алерт.
- **Ограничение размера алерта:** В annotation не передавайте большие объемы данных. Если нужно -- ссылка на дашборд или runbook.

### Эксплуатационная поддержка

- **Runbook для каждого алерта SEV1/SEV2:** Без runbook алерт не сокращает MTTR, а лишь переносит нагрузку на дежурного. Шаблон: симптомы, диагностика, алгоритм действий, контакты.
- **Мета-мониторинг алертинга:** Мониторьте `alertmanager_notifications_failed_total`, `alertmanager_silences_active`, `prometheus_rule_group_last_duration_seconds`. Без этого «тихий» сбой доставки останется незамеченным.
- **Ежеквартальный аудит алертов:** Удаляйте неиспользуемые алерты, обновляйте пороги, проверяйте актуальность runbook. Alert budget: не более 5-10 страниц в смену на одного дежурного.
- **Тестирование алертинга:** `promtool check rules` в CI, `promtool test rules` на исторических данных, ручные тесты раз в квартал.

---

## Ограничения и крайние случаи

### Ограничения Pull-модели

- **Зависший target:** Если экспортёр зависает и не отвечает на scrape, Prometheus ждет `scrape_timeout`, после чего помечает target как `down`. При массовом зависании пул воркеров может быть заблокирован ожиданием. **Решение:** устанавливайте `scrape_timeout` явно (менее `scrape_interval`).
- **Фаерволы и NAT:** Pull-модель требует, чтобы Prometheus мог доставить запрос до каждого экспортёра. В сегментированных сетях (different VLAN, DMZ) нужен VPN-туннель или промежуточный шлюз.
- **Кратковременные задачи:** Для jobs, которые живут меньше интервала сбора (cron-задачи, batch-обработка), pull-модель не подходит. Используйте Push через Pushgateway или OpenTelemetry Collector.

### Ограничения Push-модели

- **Overwhelming the server:** Источники могут отправить больше данных, чем сервер может обработать. Нет естественного ограничения темпа.
- **Heartbeat vs data:** Push-агент может отправлять пустые heartbeat, когда реальных данных нет. Это скрывает проблемы.
- **Сетевая стабильность:** При потере соединения данные буферизуются на агенте. Если буфер переполняется -- данные теряются. Требуется механизм persist-and-forward.

### Ограничения Alertmanager

- **Один источник истины на кластер:** Alertmanager HA-кластер работает по протоколу consensus. При потере quorum (меньше 50% + 1) кластер перестает группировать и доставлять алерты.
- **Масштабирование:** Один Alertmanager обрабатывает до ~10k алертов/сек. При превышении нужен внешний шардинг или использование Alertmanager cluster.
- **Cardinality в group_by:** Группировка по высококардинальным лейблам (`pod`, `instance`, `trace_id`) создает тысячи групп при массовом отказе, что приводит к OOM.

### Legacy-системы и ограниченные ресурсы

- **Старые ОС без systemd:** На Solaris, AIX, HP-UX `systemctl` отсутствует. Используйте legacy init-скрипты или crontab для управления службами.
- **Микроконтроллеры и IoT:** Устройства с ограниченным CPU/RAM не могут запустить полный Prometheus-экспортёр. Используйте lightweight-агенты (Telegraf, collectd) или отправку метрик через MQTT/HTTP.
- **Старые версии Prometheus:** Prometheus < 2.40 не поддерживает Native Histograms. На старых кластерах используйте Summary или классические гистограммы с фиксированными bucket.
- **Ограничения хранилища:** На системах с малым диском (embedded, IoT) используйте короткий retention (7-14 дней) + удалённое хранилище (VictoriaMetrics, Mimir) для долгосрочного хранения.

### Ограничения Zabbix-модели алертинга

- **Масштабирование триггеров:** При >100k триггеров Zabbix Server становится bottleneck. Используйте Zabbix Proxy для распределенной обработки.
- **Сложность зависимостей:** В Zabbix нет встроенного механизма Inhibition как в Alertmanager. Подавление вторичных алертов реализуется через Linked Triggers, что менее гибко.
- **Отсутствие native histogram:** Zabbix хранит метрики как float/delta, без поддержки перцентилей на уровне хранилища. Для P95/P99 требуются предварительные вычисления или внешние инструменты.

---

### Связанные темы

- **[Методологии мониторинга](./monitoring_methodologies.md)** -- RED, USE, Golden Signals.
- **[Prometheus Alertmanager](../../Prometheus/alertmanager.md)** -- архитектура обработки алертов.
- **[Prometheus Rules](../../Prometheus/rules.md)** -- recording и alerting rules.
- **[SRE: SLO, SLI и бюджет ошибок](../sre_concepts_main.md)** -- математика надежности.
- **[Meta-Monitoring](./meta-monitoring.md)** -- мониторинг системы мониторинга.
- **[Zabbix: определения и концепции](../../Zabbix/definitions_and_concepts.md)** -- альтернативная модель алертинга для статической инфраструктуры.
- **[Лучшие практики Grafana Alerting](../../Grafana/alerting/best_practices.md)** -- рекомендации для Grafana Unified Alerting.
- **[Управление инцидентами](./incident_management.md)** -- жизненный цикл инцидента, severity taxonomy, коммуникация.
- **[Детекция аномалий](./anomaly_detection.md)** -- статистические и ML-методы, динамические пороги.
- **[Зрелость сервиса и готовность к production](./service_maturity_production_readiness.md)** -- production readiness checklist.
- **[Наблюдаемость баз данных](./database_observability.md)** -- метрики, алерты, диагностика для PostgreSQL и MySQL.

### Ресурсы

- **[SRE Book: Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)** -- детально про Burn Rate.
- **[Awesome Prometheus Alerts](https://awesome-prometheus-alerts.grep.to/rules.html)** -- библиотека готовых правил.
- **[Prometheus Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)** -- официальная документация.
