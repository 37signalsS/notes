# SLO-алертинг на vmalert: Error Budget и Burn Rate

**Актуально для:** VictoriaMetrics v1.154.x (Community)

## Определения

**SLI (Service Level Indicator)** — измеримая характеристика сервиса (доля успешных запросов, латентность), на которой строится оценка надёжности.

**SLO (Service Level Objective)** — целевое значение SLI за период. Например: 99.9% успешных HTTP-запросов за 30 дней.

**Error Budget** — бюджет ошибок: сколько нарушений SLO допустимо за период. Для SLO 99.9% бюджет равен 0.1% запросов, что для аптайма ≈ 43 минуты простоя за 30 дней.

**Burn Rate** — скорость сжигания бюджета: отношение фактической частоты ошибок к целевой. Burn Rate 14.4 означает, что бюджет сгорает в 14.4 раза быстрее нормы и будет исчерпан задолго до конца периода.

**Multi-window burn rate alert** — алерт, сочетающий короткое и длинное окна агрегации: короткое окно быстро реагирует на всплеск ошибок, длинное фильтрует кратковременные пики и подтверждает устойчивое выгорание.

Математика SLO/SLI и расчёт бюджета — в [SRE-концепциях](../Concepts/sre_concepts_main.md). Метод многооконного алертинга, таблица окон и порогов описаны в [Рекомендациях по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#сценарий-1-многооконный-алертинг-по-скорости-выгорания-burn-rate) и [Правилах Prometheus](../Prometheus/rules.md#сценарий-7-многооконный-алертинг-по-скорости-выгорания-burn-rate). Настоящий файл теорию не дублирует — он переносит схему на стек VictoriaMetrics (vmalert + MetricsQL).

## Базовые концепции

### Пайплайн SLO-алертинга в VictoriaMetrics

```
файлы правил (recording + alerting)
        │  -rule
        ▼
     vmalert ──── -remoteWrite.url ────► VictoriaMetrics (запись job:slo:*)
        │                                        │
        │ -notifier.url                          ▼
        ▼                                 Grafana: SLO-дашборды,
 Alertmanager ──► уведомления              burn rate по запросу
```

Два типа правил решают разные задачи:

- **Recording rules** (`job:slo:*`) — вычисляются по расписанию vmalert и пишутся в хранилище через `-remoteWrite.url`. Дают стабильную метрику для дашбордов и короткие выражения в алертах.
- **Alerting rules** — сравнивают записанные burn rate с порогами и отправляют состояния в Alertmanager через `-notifier.url`.

Ключевые флаги vmalert (`-evaluationInterval`, `-rule.evalDelay`, `-remoteWrite.url`, `-notifier.url`) — в разделе [Ключевые флаги](./vmalert_overview.md#ключевые-флаги).

**Задержка видимости данных.** Недавно записанные сэмплы становятся видимыми для запросов с задержкой до 30 s (флаг `-search.latencyOffset` в vmselect/vmsingle); vmalert компенсирует это флагом `-rule.evalDelay` (30 s по умолчанию). Подробнее: [Data delay](./vmalert_overview.md#data-delay).

**HA.** Два экземпляра vmalert с уникальными `-external.label` плюс дедупликация результатов в хранилище и в Alertmanager: [HA vmalert](./vmalert_overview.md#ha-vmalert).

## Практические сценарии

### 1. Правила для SLO 99.9% (HTTP-сервис на http_requests_total)

Окна и пороги (14.4 / 6 / 3) взяты из [многооконной схемы](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#сценарий-1-многооконный-алертинг-по-скорости-выгорания-burn-rate): critical — пары окон 1 ч + 5 мин и 6 ч + 30 мин, warning — 24 ч + 2 ч.

```yaml
# slo-burn-rate.rules.yaml
groups:
  # Recording rules: результат пишется в VictoriaMetrics через -remoteWrite.url
  - name: slo.recording
    interval: 30s
    rules:
      # SLI: доля 5xx-ответов за 5 минут, в разрезе job
      - record: job:http_requests:error_rate5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)

      # Burn rate для SLO 99.9%: целевая частота ошибок = 0.1% = 0.001
      - record: job:slo:error_burn_rate_5m
        expr: job:http_requests:error_rate5m / 0.001

      - record: job:slo:error_burn_rate_30m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[30m])) by (job)
          / sum(rate(http_requests_total[30m])) by (job) / 0.001

      - record: job:slo:error_burn_rate_1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h])) by (job)
          / sum(rate(http_requests_total[1h])) by (job) / 0.001

      - record: job:slo:error_burn_rate_2h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[2h])) by (job)
          / sum(rate(http_requests_total[2h])) by (job) / 0.001

      - record: job:slo:error_burn_rate_6h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[6h])) by (job)
          / sum(rate(http_requests_total[6h])) by (job) / 0.001

      - record: job:slo:error_burn_rate_1d
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1d])) by (job)
          / sum(rate(http_requests_total[1d])) by (job) / 0.001

  # Alerting rules: сравнение burn rate с порогами, отправка в Alertmanager
  - name: slo.alerts
    rules:
      # Critical: быстрое выгорание — 2% бюджета сгорит за 1 час
      - alert: SLOErrorBudgetBurnFast
        expr: |
          job:slo:error_burn_rate_1h > 14.4
          and
          job:slo:error_burn_rate_5m > 14.4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "SLO: критическое выгорание бюджета ошибок ({{ $labels.job }})"
          description: "Burn Rate {{ $value | humanize }}x превышает 14.4x."
          runbook_url: "https://docs.internal/runbooks/slo-burn-rate"

      # Critical: устойчивое выгорание — 5% бюджета сгорит за 6 часов
      - alert: SLOErrorBudgetBurnSlow
        expr: |
          job:slo:error_burn_rate_6h > 6
          and
          job:slo:error_burn_rate_30m > 6
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "SLO: устойчивое выгорание бюджета ошибок ({{ $labels.job }})"
          description: "Burn Rate {{ $value | humanize }}x превышает 6x за 6-часовое окно."

      # Warning: 10% бюджета сгорит за 24 часа
      - alert: SLOErrorBudgetBurnWarning
        expr: |
          job:slo:error_burn_rate_1d > 3
          and
          job:slo:error_burn_rate_2h > 3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "SLO: бюджет ошибок выгорает быстрее нормы ({{ $labels.job }})"
          description: "Burn Rate {{ $value | humanize }}x превышает 3x за сутки."
```

Замечания к примеру:

- `for: 5m` для быстрого алерта повторяет пример из [Правил Prometheus](../Prometheus/rules.md#сценарий-7-многооконный-алертинг-по-скорости-выгорания-burn-rate). Значения `for` для медленных окон (15m, 30m) — производные от рекомендации `for >= 3 × scrape_interval` ([Сценарий 2: NoData и For](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#сценарий-2-настройка-параметров-nodata-и-for)): чем длиннее окно агрегации, тем больше `for` для подавления кратковременных колебаний.
- Ticket-алерт нижнего уровня (3 дня, порог 1x) строится по той же схеме с одним окном `job:slo:error_burn_rate_3d > 1` и не приведён, чтобы не раздувать пример.
- Порог делится на `0.001` — это целевая частота ошибок для SLO 99.9%. Для SLO 99% подставьте `0.01`, для 99.99% — `0.0001`.

### 2. Запуск vmalert с этими правилами

```bash
./vmalert \
  -rule=slo-burn-rate.rules.yaml \
  -datasource.url=http://vmsingle:8428 \
  -remoteWrite.url=http://vmsingle:8428 \
  -notifier.url=http://alertmanager:9093 \
  -evaluationInterval=30s \
  -httpListenAddr=:8880
# → веб-UI: http://vmalert:8880
```

- `-datasource.url` — где vmalert оценивает выражения;
- `-remoteWrite.url` — куда пишутся результаты recording rules (и состояние алертов);
- `-notifier.url` — куда отправляются firing/pending алерты.

### 3. Валидация после запуска

```bash
# 1. Правила загрузились без ошибок
curl -s http://vmalert:8880/api/v1/rules | jq -r '.status'
# → success

# 2. Recording rules действительно пишутся в хранилище
curl -s 'http://vmsingle:8428/api/v1/query?query=job:slo:error_burn_rate_5m' | jq -r '.status'
# → success

# 3. Ошибок оценки правил нет
curl -s http://vmalert:8880/metrics | grep '^vmalert_alerting_rules_errors_total'
# → vmalert_alerting_rules_errors_total 0

# 4. Активные алерты (после искусственного всплеска ошибок)
curl -s http://vmalert:8880/api/v1/alerts | jq -r '.status'
# → success
```

Сценарий искусственного теста (curl-всплеск ошибок и проверка перехода в `Firing`) описан в [Сценарии 1 рекомендаций](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#сценарий-1-многооконный-алертинг-по-скорости-выгорания-burn-rate). Unit-тесты правил на синтетических данных — [vmalert-tool test](./vmalert_rules_management_with_manifests.md#unit-тестирование-правил-vmalert-tool-test).

## Рекомендации по эксплуатации

- **`interval` recording-группы ≤ scrape_interval.** При scrape 15–20 s берите `interval: 30s` — этого достаточно для дашбордов и не создаёт лишнюю нагрузку.
- **Учитывайте data delay в порогах**, особенно для коротких окон (5m): выражение смотрит на `now - evalDelay`, окно 5m не должно граничить с ещё не видимыми сэмплами. См. [Data delay](./vmalert_overview.md#data-delay).
- **Следите за кардинальностью recording rules**: каждое окно даёт отдельную серию на каждый `job`. При сотнях job записывайте burn rate только для критичных сервисов. Диагностика: [Правила Prometheus — диагностика](../Prometheus/rules.md#диагностика-и-решение-проблем).
- **Готовьте runbook**: в аннотацию `runbook_url` ведите на страницу, где расписано, что делать при срабатывании (шаблон — [Операционная поддержка: Runbooks](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#операционная-поддержка-runbooks)).
- **Не давите выгорание заглушками**: плановые работы закрываются silences в Alertmanager ([Заглушки (Silences)](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#заглушки-silences-практические-рекомендации)), а не изменением порогов. Шаблон runbook для такого алерта — [Операционная поддержка: Runbooks](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#операционная-поддержка-runbooks).
- **Сохраняйте состояние алертов**: `-remoteWrite.url` + `-remoteRead.url` позволяют vmalert восстановить состояние после рестарта без ложного re-fire. См. [Восстановление состояния](./vmalert_rules_management_with_manifests.md#восстановление-состояния-state-recovery).

## Ограничения и особые случаи

- **vmalert не хранит историю SLO.** Сам по себе он знает только текущее состояние правила; история burn rate живёт в recording rules, записанных в VictoriaMetrics, и запрашивается из Grafana/vmui.
- **HA удваивает нагрузку на datasource**: две реплики vmalert оценивают одни и те же выражения; для кластерной конфигурации используйте выделенный `vmselect` или учитывайте нагрузку в capacity-планировании ([cluster operations](./cluster_operations.md)).
- **Дрейф меток**: если в выражении алерта появляются лейблы, которых нет в recording rule (`and` требует совпадения лейблов), пара окон разъедется и алерт не сработает. Держите `by (job)` одинаковым во всех окнах.
- **Flapping**: если burn rate колеблется около порога, увеличьте `for` и используйте `keep_firing_for` — см. [Flapping alerts](./vmalert_overview.md#flapping-alerts).
- **Пустой результат выражения не срабатывает**: если метрика `http_requests_total` пропала целиком, burn rate просто исчезнет — на это нужен отдельный алерт `absent_over_time`, см. [триаж пропажи метрик](./metrics-flow-troubleshooting.md).

## Дополнительная информация

Смотрите также:

* [SRE-концепции: SLA, SLO, SLI](../Concepts/sre_concepts_main.md) — математика надёжности;
* [Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — методология, окна, runbook;
* [Правила Prometheus: recording rules](../Prometheus/rules.md) — те же схемы для Prometheus-стека;
* [Grafana: лучшие практики алертинга](../Grafana/alerting/best_practices.md#многооконные-алерты-по-скорости-выгорания-burn-rate) — burn rate и alert budget в Grafana Alerting;
* [vmalert: обзор](./vmalert_overview.md) — флаги, data delay, HA, диагностика;
* [Управление правилами манифестами](./vmalert_rules_management_with_manifests.md) — VMRule/ConfigMap, CI/CD, vmalert-tool;
* [SRE-практики: Error Budget и Burn Rate](../Testing/performance_testing_methodology.md#7-sre-практики-error-budget-burn-rate-и-alerting-для-производительности) — применение burn rate к производительности;
* [Alerting on SLOs (Google SRE Workbook)](https://sre.google/workbook/alerting-on-slos/) — первоисточник метода.
