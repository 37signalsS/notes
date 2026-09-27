# Мониторинг и оценка трафика при Canary-развертывании

## Определения

**Мониторинг при поэтапном выпуске** — процесс непрерывного сравнения технических и продуктовых метрик новой версии (**Canary**) с эталонной версией (**Stable** или **Baseline**) в режиме реального времени.

- **Гейтинг (Gating)** — механизм автоматизированного принятия решения о продолжении раскатки или немедленном откате на основе анализа данных.
- **Анализ канарейки (Canary Analysis)** — статистический метод сравнения двух выборок трафика для определения того, является ли разница в показателях значимой или случайной.
- **Автоматический судья (Judge / Analysis Engine)** — программный компонент, который выполняет вычисления и блокирует раскатку при отклонениях. В облачной среде это Argo Rollouts Analysis / Flagger; в традиционной (Bare Metal / VM) — скрипт на базе Prometheus, вызываемый из Ansible/CI, или внешний webhook от Alertmanager (см. практические сценарии ниже).
- **Прогрев (Warm-up)** — период после старта инстанса, в течение которого метрики искажены (JIT-компиляция, кэши, пулы соединений, прогрев страничного кэша). Анализ, начатый до завершения прогрева, даёт ложные срабатывания, поэтому в окно оценки вводят `initialDelay`.
- **Корреляция с деплоем (Deploy Correlation)** — привязка аномалий метрик к конкретному релизу по меткам времени и аннотациям (версия, commit, дата раскатки). Позволяет отличать баги свежего кода от «шума» инфраструктуры (фоновая нагрузка, соседние сервисы), не прибегая к ИИ-анализу, а через простое совмещение временных рядов релиза и графика инцидентов.
- **Fail-Closed (Безопасный отказ)** — принцип гейтинга: при недоступности системы мониторинга, отсутствии данных или ошибке самого «судьи» раскатка **останавливается** (и, по возможности, инициирует откат), а не продолжается автоматически.

## Основные концепции

### Архитектура мониторинга Canary

Мониторинг Canary-развертывания строится вокруг трёх компонентов:
1. **Сбор метрик:** Prometheus / VictoriaMetrics скребут метрики с Canary, Baseline и Stable узлов с лейблом `version`.
2. **Анализ (Judge):** скрипт, AnalysisTemplate или webhook, который вычисляет отношения (ratio) к Baseline и применяет скоринг.
3. **Действие (Act):** пайплайн принимает решение — увеличить вес, остановиться для ручного анализа или выполнить откат.

В традиционной среде (Bare Metal / VM) все три компонента работают без Kubernetes-контроллеров: Prometheus развёрнут на отдельном VM, Judge — это Python/Bash-скрипт, вызываемый из Ansible или CI, а действие — это обновление конфига балансировщика через Ansible/ssh/сокет.

### Использование контрольной группы (Baseline)

При сравнении 5% Canary-трафика со стабильной версией (95%) возникает проблема статистической недостоверности. Стабильный пул слишком велик и инертен.

**Паттерн Baseline:**
- **Baseline** — небольшая группа инстансов (того же размера, что и Canary), на которых запущена текущая стабильная версия. В традиционной среде это выделенный хост/VM с той же версией кода и тем же профилем оборудования (CPU/RAM/диск), что и Canary-узел.
- **Canary** — группа инстансов с новой версией кода.
- **Принцип:** Сравнение Canary с Baseline исключает влияние «возраста» инстансов, фрагментации памяти и прогрева JIT-компиляторов, так как обе группы запускаются одновременно в идентичных условиях. Общий стабильный пул (Stable) остаётся резервом для продукта, но для анализа качества релиза используется именно Baseline.

### Скоринг и гейтинг (Scoring)

В современных системах (Spinnaker/Argo) используется система баллов:
1.  Каждая метрика оценивается отдельно (Pass/Fail) либо как отношение к Baseline (Ratio).
2.  Результаты суммируются с учетом весов (например, Errors — вес 0.5, Latency — 0.3, Saturation — 0.2).
3.  **Thresholds (Пороги):**
    - **Pass Score** (например, 95%): Раскатка продолжается автоматически.
    - **Marginal Score** (например, 70%): Раскатка приостанавливается для ручного анализа.
    - **Fail Score** (менее 70%): Немедленный автоматический откат.

**Скользящее окно (moving window).** Оценка производится не за весь период, а за последнее окно (например, 5 минут с шагом 1 минута). Это позволяет реагировать на свежие деградации, а не на усреднённую историю за час. В on-prem «судье» (см. практические сценарии) окно задаётся параметром запроса `rate(...[5m])` и интервалом опроса.

### Ключевые сигналы (SRE Golden Signals)

| Сигнал | Роль в Gating | Типовой порог отката |
| :--- | :--- | :--- |
| **Errors (Ошибки)** | Главный блокиратор. | Рост доли 5xx на > 1% относительно Baseline. |
| **Latency (Задержка)** | Индикатор производительности. | Увеличение p95 на > 10% или p99 на > 20%. |
| **Traffic (Трафик)** | Проверка маршрутизации. | Отклонение веса трафика от заданного на > 5%. |
| **Saturation (Насыщение)** | Детекция утечек ресурсов. | Рост потребления RAM/CPU на > 15% за 10 мин. |

**Откуда берутся сигналы вне Kubernetes (Bare Metal / VM):**
- **Errors / Latency / Traffic** — метрики самого приложения (через экспортёр в формате Prometheus, либо агрегация из access-логов балансировщика: Nginx `stub_status` / `log_subrequest`, HAProxy `show stat`).
- **Saturation** — `node_exporter` (CPU, память, диск, сеть) плюс прикладные лимиты: количество открытых file descriptors, число потоков/воркеров, длина очереди соединений, utilisation диска (`%util` в `iostat`).
- Критично: метрики должны нести **лейбл версии** (`version="canary|baseline|stable"`), иначе невозможно разделить выборки — см. раздел «Инструментация».

> Методология Golden Signals, RED и USE подробно разобрана в **[Методологиях мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**; готовые запросы — в **[Шаблонах PromQL](../../Prometheus/concepts/promql/query_patterns.md)**.

### Инструментация: разделение метрик по версиям

Главное требование к мониторингу Canary — возможность отфильтровать ряд новой версии от старой. Без этого сравнение `version="canary"` с `version="baseline"` невозможно, и метрики «отравляются» (см. Troubleshooting).

Способы проставить лейбл версии в традиционной среде:
1.  **На стороне приложения:** клиент метрик (Prometheus client, OpenTelemetry SDK) добавляет `version` из переменной окружения/`VERSION` файла при старте. Это самый надёжный способ — лейбл «приклеен» к процессу. Инструментирование описано в **[OpenTelemetry: инструментация и SDK](../../OpenTelemetry/instrumentation_sdk.md)**.
2.  **На стороне Prometheus (relabel):** статические метки цели (`static_configs[].labels.version`), либо динамические через `file_sd_configs` с меткой версии в файле инвентаря. Не требует правки кода, но зависит от аккуратности инвентаря.
3.  **Через отдельные job'ы:** Canary и Baseline скребутся разными `job_name` (например, `app-canary` и `app-baseline`), и лейбл версии добавляется на уровне scrape-конфигурации.

Важно: имена самих метрик (`http_requests_total`, `http_request_duration_seconds`) должны оставаться **стабильными между версиями**. Смена имени метрики между релизами разрушает относительное сравнение (Ratio) — придерживайтесь единых семантических конвенций именования.

## Практические сценарии

### Инструментация и разделение метрик по версиям на Bare Metal

Минимальная конфигурация Prometheus, разделяющая Canary и Baseline по лейблу `version` на уровне scrape. Это основа всего последующего анализа.

```yaml
# prometheus.yml (фрагмент)
scrape_configs:
  - job_name: app-canary
    metrics_path: /metrics
    static_configs:
      - targets: ['10.0.1.20:8080']
        labels:
          version: canary

  - job_name: app-baseline
    static_configs:
      - targets: ['10.0.1.23:8080']
        labels:
          version: baseline

  - job_name: app-stable
    static_configs:
      - targets: ['10.0.1.21:8080', '10.0.1.22:8080']
        labels:
          version: stable
```

**Валидация:** запрос в Prometheus UI `count by (version) (http_requests_total)` должен вернуть три серии с лейблами `canary`, `baseline`, `stable`. Если лейбла `version` нет — метрики «отравлены» и анализ невозможен (см. Troubleshooting).

Для динамических сред используйте `file_sd_configs` с файлом инвентаря, где каждому хосту прописан `version`; при смене версии достаточно обновить файл и Prometheus перечитает его (`--config.file` перезагружается сигналом `SIGHUP`).

### Продвинутые PromQL-запросы (VictoriaMetrics/Prometheus)

**1. Проверка статистической значимости (Исключение шума):**
Игнорируем всплески ошибок, если общий объем трафика слишком мал для выводов.

```promql
# Отношение ошибок, только если трафик > 50 запросов в минуту
(
  sum(rate(http_requests_total{version="canary", status=~"5.."}[5m]))
  /
  sum(rate(http_requests_total{version="canary"}[5m]))
)
/
(
  sum(rate(http_requests_total{version="baseline", status=~"5.."}[5m]))
  /
  sum(rate(http_requests_total{version="baseline"}[5m]))
) > 1.5 
and 
sum(rate(http_requests_total{version="canary"}[5m])) > 0.8 # Трафик > 50 rpm (0.8 rps)
```

**2. Детекция утечек памяти через темп роста (Rate of Change):**
Анализ производной (derivative) потребления памяти для выявления медленных утечек.

```promql
# Сравнение скорости роста памяти (canary vs baseline)
predict_linear(container_memory_working_set_bytes{version="canary"}[30m], 3600) 
> 
predict_linear(container_memory_working_set_bytes{version="baseline"}[30m], 3600) * 1.5
```

**3. Относительное сравнение задержки (p95 Latency Ratio):**
Дополняет таблицу Golden Signals — сравниваем не абсолютную задержку, а отношение к Baseline, чтобы исключить влияние фоновой нагрузки.

```promql
# ratio p95 latency canary/baseline; срабатывает при росте > 10%
(
  histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{version="canary"}[5m])) by (le))
  /
  histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{version="baseline"}[5m])) by (le))
) > 1.1
```

### Автоматизация через Argo Rollouts (Multi-step Analysis)

Пример с использованием внешнего "судьи" и поэтапной проверкой.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: advanced-canary-check
spec:
  args:
  - name: service-name
  metrics:
  - name: error-rate
    interval: 5m
    successCondition: result[0] <= 0.01 # < 1% ошибок
    failureLimit: 2
    provider:
      prometheus:
        address: http://victoria-metrics:8428
        query: |
          sum(rate(http_requests_total{app="{{args.service-name}}", version="canary", status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total{app="{{args.service-name}}", version="canary"}[5m]))
  - name: business-conversion
    interval: 10m
    # Проверка, что конверсия не упала более чем на 5%
    successCondition: result[0] >= 0.95
    provider:
      web: # Пример обращения к системе бизнес-аналитики
        url: https://analytics.internal/api/v1/compare?v1=baseline&v2=canary
```

> Детали реализации Analysis в Kubernetes — в [Argo Rollouts: Analysis](https://argoproj.github.io/argo-rollouts/features/analysis/). Маршрутизация Canary (Nginx/HAProxy/Ansible) и неcloud-анализ описаны в **[Канареечном развертывании](./canary_deployment.md)**.

### Кастомный «судья» (Judge) для on-prem гейтинга (Python)

В традиционной среде роль Analysis Engine выполняет скрипт, запускаемый из CI/Ansible между шагами веса (10% → 25% → 50%). Он реализует концепцию Scoring (Pass/Marginal/Fail) из раздела выше: опрашивает Prometheus, считает отношения к Baseline и принимает решение.

```python
#!/usr/bin/env python3
"""Canary judge для Bare Metal/VM. Запускается между шагами веса.
Возвращает exit code: 0=Pass, 1=Marginal(стоп), 2=Fail(откат)."""
import sys, json, urllib.request, urllib.parse

PROM = "http://victoria-metrics:8428"
APP  = "my-service"
WIN  = "[5m]"

def ratio(metric, op, thr):
    q = (
        f"("
        f"sum(rate({metric}{{app='{APP}',version='canary'}{WIN}))"
        f" / sum(rate({metric}{{app='{APP}',version='canary',status=~'2..'}}{WIN}))"
        f")"
        f" / "
        f"("
        f"sum(rate({metric}{{app='{APP}',version='baseline'}}{WIN}))"
        f" / sum(rate({metric}{{app='{APP}',version='baseline',status=~'2..'}}{WIN}))"
        f")"
    )
    url = f"{PROM}/api/v1/query?query={urllib.parse.quote(q)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            res = json.load(r)["data"]["result"]
    except Exception as e:
        print(f"JUDGE_ERROR: monitoring unavailable -> Fail-Closed ({e})")
        sys.exit(2)   # Fail-Closed: при сбое системы мониторинга — откат
    if not res:
        print("JUDGE_WARN: no data yet (low traffic) -> Marginal")
        sys.exit(1)
    val = float(res[0]["value"][1])
    print(f"{metric}: ratio={val:.3f} (gate {op} {thr})")
    if op == ">" and val > thr: return False
    if op == "<" and val < thr: return False
    return True

# Скоринг: Errors + Latency(p95) + Saturation
score = 0
total = 3

# 1) Errors: рост доли 5xx > 1% относительно baseline — провал
score += 1 if ratio("http_requests_total{status=~'5..'}", ">", 1.01) else 0

# 2) Latency p95 (относительное сравнение histogram_quantile)
lp = (
    f"(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket"
    f"{{app='{APP}',version='canary'}}{WIN})) by (le)))"
    f"/(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket"
    f"{{app='{APP}',version='baseline'}}{WIN})) by (le)))"
)
try:
    with urllib.request.urlopen(f"{PROM}/api/v1/query?query={urllib.parse.quote(lp)}", timeout=10) as r:
        lr = json.load(r)["data"]["result"]
    lat = float(lr[0]["value"][1]) if lr else 1.0
    print(f"latency_p95_ratio={lat:.3f} (gate > 1.10)")
    score += 1 if lat <= 1.10 else 0
except Exception as e:
    print(f"JUDGE_ERROR latency query failed -> Fail-Closed ({e})"); sys.exit(2)

# 3) Saturation: рост потребления CPU/RAM canary > 15% к baseline
sat = (
    f"(avg(rate(node_cpu_seconds_total{{instance=~'canary.*'}}[5m])))"
    f"/(avg(rate(node_cpu_seconds_total{{instance=~'baseline.*'}}[5m])))"
)
# (упрощено: в реальности сравнивайте node_exporter по лейблу version/instance)
score += 1  # заглушка: подставить реальный запрос с порогом 1.15

pct = score / total * 100
print(f"CANARY_SCORE={pct:.0f}%")
if pct >= 95:   sys.exit(0)   # Pass  -> продолжить раскатку
elif pct >= 70: sys.exit(1)   # Marginal -> пауза на ручной анализ
else:           sys.exit(2)   # Fail  -> автооткат
```

**Применение в пайплайне (Ansible/CI):**
```bash
python3 canary_judge.py
rc=$?
case $rc in
  0) echo "PASS: увеличиваем вес Canary (HAProxy socket)";;
  1) echo "MARGINAL: пауза, ждём решения инженера"; exit 1;;
  2) echo "FAIL: откат (ansible-playbook rollback.yml)"; ansible-playbook rollback.yml; exit 2;;
esac
```

**Валидация:** при росте ошибок скрипт печатает `CANARY_SCORE` и возвращает ненулевой код; пайплайн останавливается. При недоступности Prometheus — гарантированно `Fail-Closed` (exit 2).

### Лог-ориентированный гейтинг (Log-based Canary Analysis)

Когда метрики ещё не настроены, агрегация access-логов балансировщика даёт быстрый канал оценки. Направьте трафик Canary в отдельный лог-файл, чтобы сравнивать доли ошибок между пулами.

Способы разделения логов по версиям описаны в **[Канареечном развертывании](./canary_deployment.md)**. После того как логи разделены, сравнение ведётся так:

```bash
# Доля 5xx в canary-логе vs stable-логе (awk)
calc_err() { awk 'BEGIN{s=0;e=0} {s++} $9 ~ /^5/{e++} END{printf "%.4f", (s?e/s:0)}' "$1"; }
C=$(calc_err /var/log/nginx/canary.access.log)
S=$(calc_err /var/log/nginx/stable.access.log)
echo "canary_5xx=$C baseline_5xx=$S"
# Решение: если ratio > 1.01 и трафика достаточно — стоп/откат
awk -v c="$C" -v s="$S" 'BEGIN{ if (s>0 && c/s > 1.01) {print "FAIL"; exit 2} else {print "PASS"; exit 0}}'
```

**Альтернатива (централизованно):** Promtail собирает логи с лейблом `version` в Loki, и сравнение ведётся запросом LogQL (`sum by (status) (rate({app="my-service",version="canary"} |= "5" [5m]))`). Подход ценен для legacy-приложений, не отдающих метрики.

### Alertmanager как гейт: webhook → отмена пайплайна

Prometheus-алерт может выступать «судьёй»: при пробитии порога отношения ошибок Alertmanager шлёт webhook, который отменяет активный pipeline (GitLab/GitHub Actions) или запускает откат.

```yaml
# prometheus rule (fragment)
groups:
  - name: canary-gate
    rules:
      - alert: CanaryErrorRatioHigh
        expr: |
          (
            sum(rate(http_requests_total{version="canary",status=~"5.."}[5m]))
            / sum(rate(http_requests_total{version="canary"}[5m]))
          )
          /
          (
            sum(rate(http_requests_total{version="baseline",status=~"5.."}[5m]))
            / sum(rate(http_requests_total{version="baseline"}[5m]))
          ) > 1.5
        for: 5m
        labels:
          severity: critical
          gate: canary
        annotations:
          summary: "Canary error ratio > 1.5x baseline"
```

```yaml
# alertmanager.yml (fragment)
route:
  receiver: canary-gate-webhook
receivers:
  - name: canary-gate-webhook
    webhook_configs:
      - url: http://gate-listener.internal:9099/canary-abort
```

```bash
# gate-listener (минимальный обработчик): отменяет pipeline при алерте
# Пример для GitLab CI (curl к API отмены)
cat > /opt/gate/canary-abort.sh <<'EOF'
#!/bin/bash
read -r json
pipeline=$(echo "$json" | jq -r '.commonLabels.gate // empty')
if [ "$pipeline" = "canary" ]; then
  curl -s -X POST "https://gitlab.internal/api/v4/projects/1/pipelines/$CI_PIPELINE_ID/cancel" \
       --header "PRIVATE-TOKEN: $GITLAB_TOKEN"
fi
EOF
```

**Валидация:** `amtool alert query` должен показывать активный `CanaryErrorRatioHigh` при искусственной подаче 5xx на canary; webhook-приёмник логирует вызов отмены.

### Синтетический мониторинг и smoke-тесты как gate

После каждого сдвига веса Canary обязан пройти функциональную проверку, прежде чем получить больше трафика. Это дешевле, чем ждать накопления продуктовых метрик.

```bash
# Smoke-проверка эндпоинта Canary (через opt-in заголовок)
for i in 1 2 3; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Canary: true" http://lb/healthz)
  [ "$code" = "200" ] || { echo "SMOKE_FAIL"; exit 1; }
done
echo "SMOKE_PASS"
```

Для инфраструктурных проверок (порты, файлы, конфиги) используйте **goss**:
```bash
goss validate --format tap   # декларативная проверка состояния хоста Canary
```
При падении smoke/goss — пайплайн останавливается на текущем весе (Marginal) и инициирует откат, если порог Failed-проверок превышен.

### SLO / Burn-Rate гейтинг

Вместо (или вместе с) мгновенными порогами используйте бюджет ошибок (Error Budget). Canary продолжается, только если скорость «прожига» бюджета (burn rate) ниже порога; превышение — остановка и откат. Метод устойчив к кратковременным всплескам.

```promql
# Multi-window burn rate (упрощённо, окна 1h/5m)
(
  sum(rate(http_requests_total{version="canary",status=~"5.."}[1h]))
  / sum(rate(http_requests_total{version="canary"}[1h]))
)
/
(
  (1 - 0.999)   # SLO 99.9%
) > 14.4   # burn rate > 14.4 за 1h — критично
```

Подробнее о многооконных правилах burn rate и SLO — в **[Методологиях мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**; применение к автооткату — в **[Health Checks и Rollback](./deployment_health_checks_and_rollback.md)**.

## Операции и команды

### Prometheus / VictoriaMetrics API

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Немедленный запрос** | `curl -s 'http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{version="canary",status=~"5.."}[5m]))' \| jq .data.result` | Возвращает текущее значение метрики. |
| **Диапазонный запрос** | `curl -s 'http://prometheus:9090/api/v1/query_range?query=...&start=...&end=...&step=15s' \| jq .data.result` | Возвращает временной ряд для построения графика. |
| **Очистка метрик** | `curl -X POST http://prometheus:9090/api/v1/admin/tsdb/cleanTombstones` | Удаляет удалённые серии после отката версии. |
| **Reload конфига** | `kill -HUP $(pidof prometheus)` | Перечитывает `prometheus.yml` без даунтима. |

### Alertmanager CLI (amtool)

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Активные алерты** | `amtool alert query` | Список текущих алертов с метками. |
| **Тихое подавление** | `amtool silence add --duration=1h --comment="canary maintenance" alertname=CanaryErrorRatioHigh` | Подавляет алерт на 1 час. |
| **Удаление silence** | `amtool silence expire $(amtool silence query -q)` | Удаляет все активные silence. |

### systemd: управление Judge-сервисом

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **ЗапускJudge** | `systemctl start canary-judge` | Запускает скрипт судьи как сервис. |
| **Статус** | `systemctl status canary-judge` | Показывает последние логи и exit code. |
| **Логи** | `journalctl -u canary-judge -n 50 --no-pager` | Последние 50 строк stdout/stderr. |
| **Автозапуск** | `systemctl enable canary-judge` | Включает сервис на загрузку ОС. |

### HAProxy: динамическое управление весами

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Установка веса** | `echo "set server app_canary/canary1 weight 25" \| socat - UNIX-CONNECT:/var/run/haproxy.sock` | Устанавливает вес 25% без reload. |
| **Текущие веса** | `echo "show stat" \| socat - UNIX-CONNECT:/var/run/haproxy.sock \| grep app_canary` | Выводит текущие веса и статус. |
| **Дрейин серверов** | `echo "set server app_stable/stable1 state drain" \| socat - UNIX-CONNECT:/var/run/haproxy.sock` | Перевод сервера в режим drain. |

### Nginx: проверка конфигурации

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `nginx -t` | `test is successful` или ошибка. |
| **Reload** | `nginx -s reload` | Graceful reload без отрыва соединений. |
| **Версия** | `nginx -v 2>&1 \| awk -F/ '{print $2}'` | Выводит версию бинарника. |

### Артефакты: доставка и проверка

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Rsync с проверкой** | `rsync -av --checksum-choice=xxh3 --compress-choice=zstd deploy@repo:/opt/app/2.4.0/ /opt/app/2.4.0/` | Синхронизирует каталог с проверкой целостности. |
| **Проверка healthz** | `curl -sf http://10.0.1.20:8080/healthz` | Возвращает 200 или падает с ненулевым кодом. |
| **goss-валидация** | `goss validate --format tap` | Декларативная проверка состояния хоста. |

### Синтетические проверки (Smoke)

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **HTTP smoke** | `for i in 1 2 3; do curl -s -o /dev/null -w "%{http_code}" -H "X-Canary: true" http://lb/healthz; done` | Три подряд успешных проверки. |
| **Latency probe** | `curl -s -o /dev/null -w "%{time_total}" http://10.0.1.20:8080/api/health` | Выводит общее время запроса в секундах. |
| **TCP port check** | `nc -zv 10.0.1.20 8080 </dev/null 2>&1` | `Connection succeeded` или `Connection refused`. |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ложный откат (False Negative)** | Анализ начался до завершения прогрева (Warm-up). | Добавить `initialDelay` (например, 2-3 минуты) в AnalysisTemplate либо паузу в on-prem «судье». |
| **Анализ застрял (Timeout)** | Слишком малый объем трафика для сбора данных. | Увеличить окно анализа (window) или использовать синтетические Smoke-тесты / генератор нагрузки против обоих пулов. |
| **"Отравление" метрик** | Метрики Canary и Stable смешиваются в общем `job`. | Использовать `Relabeling` в Prometheus для разделения подов/узлов по версиям (лейбл `version`), либо отдельные `job_name`/`file_sd` с меткой версии. |
| **Лаг данных (Data Lag)** | Задержка записи в VictoriaMetrics/Prometheus. | Согласовать интервал анализа (interval) с периодом сбора метрик (scrape interval). |
| **Нет лейбла `version` у метрик приложения** | Код не экспортирует версию, и scrape-конфиг не проставляет метку. | Добавить `version` через переменную окружения в клиенте метрик ИЛИ проставить `labels.version` в `static_configs`/`file_sd`. Без лейбла относительное сравнение невозможно. |
| **Судья-скрипт падает / Prometheus недоступен** | Сбой сети к VM мониторинга или таймаут запроса. | Реализовать Fail-Closed: любая ошибка скрипта = откат, а не продолжение. Ограничить таймаут запроса (например, 10с). |
| **Взрыв кардинальности метрик** | Лейблы содержат высококардинальные значения (user_id, request_id, IP). | Не метить ряды по пользователям/запросам; ограничить набор лейблов версией, эндпоинтом, кодом ответа. |
| **Рассинхронизация часов узлов** | У Canary и Baseline разное время (drift NTP). | Настроить `chrony`/`ntpd`; иначе временные ряды смещены и отношение `rate()[5m]` считается некорректно. |
| **Дрейф имён метрик между версиями** | Новая версия переименовала `http_requests_total` → `app_requests`. | Зафиксировать единые семантические конвенции именования метрик (см. [инструментацию OTel](../../OpenTelemetry/instrumentation_sdk.md)); при переименовании поддерживать алиас минимум один релиз. |
| **Низкий трафик → нерепрезентативная выборка** | Canary получает < 10 rpm, соотношение шум/сигнал слишком высокое. | Ввести порог минимального трафика в PromQL (`sum(rate(...[5m])) > 0.2`) или подключить синтетический генератор нагрузки (`k6`, `vegeta`). |
| **Окно прогрева слишком короткое** | JIT-компиляция или прогрев кэша длятся дольше `initialDelay`. | Увеличить `initialDelay` до покрытия worst-case прогрева; валидировать по перцентилям latency (p99 должен стабилизироваться). |
| **Alertmanager не шлёт webhook** | Маршрут (`route`) не совпадает сseverity/лейблом алерта. | Проверить `amtool alert query` и селектор `match` в `route:`; убедиться, что алерт активен и не suppressed. |
| **Judge возвращает Marginal при нормальных метриках** | Пороги слишком агрессивны для фоновой нагрузки. | Калибровать пороги под реальный Baseline в production; использовать относительные, а не абсолютные значения. |

## Лучшие практики

1.  **Синтетический трафик:** Если в ночное время трафика нет, автоматический анализ может быть недостоверен. Настройте генератор нагрузки для поддержания Baseline-уровня (например, `k6`/`vegeta` против обоих пулов) — иначе «анализ застрял» не отличить от реального отсутствия регрессии.
2.  **Дифференциальный анализ:** Не используйте абсолютные пороги (например, "ошибок < 5"). Всегда используйте относительное сравнение с Baseline (Ratio), так как нагрузка на кластер постоянно меняется.
3.  **Логика "Safe Fail":** Если система мониторинга недоступна, раскатка должна останавливаться (Fail-Closed), а не продолжаться автоматически.
4.  **Калибровка размера Baseline:** Контрольная группа должна быть сопоставима с Canary по объёму (1:1 по инстансам) и профилю железа, иначе отношение Ratio будет смещено аппаратной разницей, а не кодом.
5.  **Окно анализа vs частота деплоев:** Длительность окна (например, 5–10 мин) должна быть меньше среднего интервала между релизами. При частых деплоях сокращайте окно и используйте скользящее среднее, чтобы не блокировать конвейер.
6.  **Retention данных Canary:** Сохраняйте метрики и логи Canary-периода минимум на сутки после полной раскатки — для пост-анализа инцидентов, которые проявляются с задержкой (утечки памяти, деградация кэша).
7.  **Единые семантические конвенции метрик:** Фиксируйте имена метрик и лейблы в style guide для команды. Любое переименование требует поддержки алиасов минимум один релиз.
8.  **Автоматизация отката:** Откат при Fail/Marginal должен быть one-click (ansible-playbook rollback.yml, `kubectl rollout undo`). Не оставляйте ручные шаги на критическом пути.
9.  **Canary в isolation:** Если Canary и Baseline делят общее железо (диск, сеть), убедитесь, что нагрузка одного пула не подавляет метрики другого (cgroups, `ionice`, отдельный NIC для мониторинга).

## Граничные случаи и ограничения

- **Нет трафика для статистики.** Canary не получает запросов из-за ошибки балансировщика или сетевого сегмента. Gating не может принять решение — применяется Fail-Closed: откат или пауза с алертом в Slack/PagerDuty.
- **Двойной деплой (Stale Canary + New Canary).** Если предыдущий Canary не был полностью откачен, метки `version` начинают конфликтовать. Используйте уникальные имена metric jobs или добавляйте `deploy_id` в лейблы.
- **Повышение кардинальности при частых деплоях.** Каждый релиз добавляет новые временные ряды. Если retention Prometheus ограничен (например, 7 дней), при высокой частоте деплоев возможен `out-of-order samples` или `too many open files`. Увеличите retention или используйте `max_cardinality` в VictoriaMetrics.
- **Смешанный трафик из разных источников.** Если Canary получает трафик не только из LB, но и из кэшей/CDN, доля 5xx искажается. Gating должно учитывать только «прямой» трафик (через заголовок `X-Forwarded-For` или source IP).
- **Частичная недоступность Baseline.** Если Baseline-узел упал, ratio считается по единственному источнику — это ненадёжно. Реализуйте проверку доступности Baseline (`up{version="baseline"} == 1`) перед запуском анализа.
- **Метрики приложения vs инфраструктуры.** Деградация может быть вызвана не кодом Canary, а соседним сервисом на том же хосте (disk I/O, network bandwidth). Saturation-пороги помогают, но не всегда. Используйте Baseline на отдельном хосте для изоляции.
- **Clock drift между Canary и Baseline.** Если время на узлах отличается > scrape interval, `rate()` считает отрицательные или нулевые значения. Настройте `chrony` с `makestep` и проверяйте `ntpq -p` перед деплоем.

## Дополнительная информация

### Рекомендованные ссылки

- **[Канареечное развертывание](./canary_deployment.md)** — архитектура, маршрутизация (Nginx/HAProxy/Ansible) и неcloud-анализ.
- **[Health Checks и Rollback](./deployment_health_checks_and_rollback.md)** — автоматический откат по метрикам и SLO.
- **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — RED, USE, Four Golden Signals, Burn Rate.
