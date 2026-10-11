# Logstash: Мониторинг, алерты, валидация конфигов

**Актуально для:** Logstash 8.19 (LTS) / 9.5.x

> Эта заметка сосредоточена на **операционных аспектах мониторинга и валидации** конфигурации Logstash: как читать метрики, на что ставить алерты, как диагностировать проблемы и как проверять конфигурацию перед деплоем. Архитектура конвейеров, модель исполнения и flow-метрики подробно разобраны в [заметке о конвейерах](./logstash_pipelines.md), а основы установки, настройки очередей и перезагрузки — в [общем обзоре](./logstash_overview.md) и [заметке о production-эксплуатации](./logstash_production.md).

## Определения

- **Monitoring API** — встроенный HTTP API Logstash на порту `9600` (по умолчанию `127.0.0.1:9600` или первый свободный из диапазона `9600–9700`). Основные эндпоинты: `/_node/stats`, `/_node/stats/pipelines`, `/_node/stats/pipelines/<id>`, `/_node/hot_threads`, `/_health_report`.
- **Flow Metrics** — метрики потока обработки (flow control) из секции `flow` ответа Node Stats API: `worker_utilization`, `worker_concurrency`, `queue_backpressure`, `input_throughput`, `filter_throughput`, `output_throughput`. Позволяют находить узкое место без слепого угадывания.
- **Config test (`-t`)** — проверка синтаксиса конфигурации без запуска: `logstash --config.test_and_exit` (или `-t`). Стоп-фактор перед деплоем в CI/production.
- **Smoke-test пайплайна** — быстрая проверка работоспособности конвейера на репрезентативных тестовых событиях (обычно `stdin → filter → stdout { codec => rubydebug }`).
- **Persistent Queue (PQ)** — дисковая очередь событий между input и output; при включённой PQ рост `queue_persisted_growth_events > 0` сигнализирует о backpressure от output.
- **Dead Letter Queue (DLQ)** — очередь событий, которые не удалось записать в целевую систему (ошибки маппинга, формат). Устойчивый рост DLQ означает системную проблему, а не одиночный битый батч.

## Предпосылки и предварительная настройка (Prerequisites)

Перед настройкой мониторинга и валидации конфигурации:

1. **Доступ к Monitoring API.** Logstash слушает API на `127.0.0.1:9600` по умолчанию. Для внешнего мониторинга (с других хостов) измените `api.http.host: 0.0.0.0` в `logstash.yml` и ограничьте доступ сетевыми ACL/фаерволом.
2. **Безопасность API.** Не оставляйте API открытым в production без аутентификации. Включите Basic auth и TLS:

```yaml
# logstash.yml
api.enabled: true
api.http.host: 0.0.0.0
api.http.port: 9600
api.auth.type: basic
api.auth.basic.username: "monitoring"
api.auth.basic.password: "${LS_API_PASSWORD}"
api.ssl.enabled: true
api.ssl.keystore.path: /etc/logstash/certs/api.p12
api.ssl.keystore.password: "${LS_API_KEYSTORE_PASSWORD}"
```

3. **Persistent Queue включена** (`queue.type: persisted`) — без неё backpressure от output приводит к потере событий, а метрики очереди не отражают реальную задержку.
4. **Dead Letter Queue включена** (`dead_letter_queue.enable: true`) — события с ошибками не теряются, их можно переиграть.
5. **Среда для валидации.** CI-контур или staging-узел с тем же конфигом, где можно запускать `logstash -t` и smoke-тесты без влияния на production.

## Основные концепции

### Monitoring API: что и зачем

Logstash предоставляет self-monitoring без обязательных внешних агентов (хотя Elastic Agent Integration также собирает те же поля). Ключевые эндпоинты:

| Эндпоинт | Назначение |
|---|---|
| `GET /_node/stats` | Общая статистика: JVM, события (`events.in/out/filtered`, `duration_in_millis`), очереди, плагины, версия. |
| `GET /_node/stats/pipelines` | Статистика по всем пайплайнам. |
| `GET /_node/stats/pipelines/<id>` | Детальная статистика конкретного пайплайна: `events`, `flow`, `queue`, `plugins`. |
| `GET /_node/hot_threads?human=true` | Самые нагруженные Java-потоки в текстовом виде. Помогает выявить CPU-hotspots. |
| `GET /_health_report` | Сводка состояния (`green/yellow/red/unknown`) с indicators (symptom, details, impacts, diagnosis). |

Полный выпад JSON-структуры pipeline stats (ключевые ветви):

```bash
curl -s 'localhost:9600/_node/stats/pipelines/main?pretty' | jq '{
  events: .pipelines.main.events,
  flow: .pipelines.main.flow,
  queue: .pipelines.main.queue
}'
# → {
# →   "events": {"in": 10526691, "filtered": 10525882, "out": 10525882,
#                 "duration_in_millis": 123456, "queue_push_duration_in_millis": 789},
# →   "flow": {"worker_utilization": {"current": 93.09, "lifetime": 92.18, ...},
# →            "queue_backpressure": {"current": 0.001, ...},
# →            "input_throughput": {"current": 1500, ...}, ...},
# →   "queue": {"size": {"bytes": 1048576, "events": 500, "max_bytes": 1073741824},
# →             "persisted": {"growth": {"events": 0, "bytes": 0}}}
# → }
```

### Что именно НЕ проверяет `logstash -t`

`--config.test_and_exit` — критически важен, но **не является** полной функциональной проверкой. Официальная документация гласит: *«grok patterns are not checked for correctness with this flag»*:

- **Grok-паттерны** — синтаксис шаблонов проверяется частично, но корректность матчей на реальных данных не тестируется.
- **Обращения к полям** — не проверяет наличие полей в условиях на этапе компиляции (Ruby-выражения вычисляются в рантайме).
- **Lookup-плагины** (`elasticsearch`, `redis`, `memcached`, др.) — внешние зависимости недоступны при статической валидации.
- **Условная логика ветвлений** — корректность веток проверяется синтаксически, но поведение на реальных событиях — нет.
- **Производительность/утечки** — не проверяет.
- **ECS-совместимость/маппинг ES** — выходная сторона (ES output) не валидируется на корректность маппинга.

**Вывод:** `-t` — обязательный gate (pre-deploy), но **недостаточный** без smoke-теста на staging с репрезентативными данными.

### Интерпретация ключевых метрик

| Метрика (JSON-путь) | Что измеряет | Норма |
|---|---|---|
| `flow.worker_utilization.current` | Доля времени, когда все воркеры заняты обработкой текущего пайплайна (0–100) | < 80% в пик; рост к 100 = насыщение |
| `flow.worker_concurrency.current` | Среднее число активных воркеров в данный момент | ≤ `pipeline.workers` |
| `flow.queue_backpressure.current` | Единичная метрика: доля времени, когда inputs блокированы очередью | Близко к 0; рост = output не успевает |
| `flow.input_throughput.last_15_minutes` | Событий/с на входе | Должно совпадать с output (см. ниже) |
| `flow.output_throughput.last_15_minutes` | Событий/с на выходе | input ≈ output ± погрешность |
| `queue.persisted.growth.events` | Скорость накопления событий в PQ (+ = растёт, − = сокращается) | → 0 или отрицательная в стабильном состоянии |
| `queue.size.bytes / queue.max_bytes` | Заполненность PQ | < 80% длительно |
| `events.duration_in_millis` | Суммарное время обработки всех событий (накопительно) | Смотрите рост при фиксированном throughput |
| `jvm.mem.heap_used_percent` | Использование heap JVM | < 85% (источник OOM) |

> **Примечание:** метрики flow-секции (`worker_utilization`, `queue_backpressure`, `_throughput`) доступны и на уровне отдельных плагинов (`plugins.filters[].flow.*`), что позволяет точно локализовать узкое место ([детали в заметке о конвейерах](./logstash_pipelines.md#диагностика-узкого-места-через-flow-metrics)).

### Чек-лист алертов (prod-ready)

Ниже — минимальный, практический набор триггеров. Значения — ориентиры, подстраивайте под пиковую нагрузку и базовый профиль вашего пайплайна.

| Метрика | Условие (триггер) | Уровень | Пояснение | Первичные действия |
|---|---|---|---|---|
| **Queue growth (PQ)** | `queue_persisted_growth_events` > 0 **более 10–15 минут** (устойчивый тренд) | **Critical** | Output не успевает, очередь копит лаг. Ключевой индикатор backpressure. | Проверить ES/Kafka/выходную систему, `worker_utilization`, логи output. |
| **Queue fill % (PQ)** | `queue.size.bytes / queue.max_bytes * 100` > **80%** (длительно) | **High** | Риск быстрого заполнения PQ. | Снизить вход, проверить bottleneck, рассмотреть масштабирование. |
| **Queue size (spike)** | `queue.size.events` резко растёт без возврата к 0 в течение 5–10 мин | **High** | Входящий пик превышает пропускную способность. | Оценить причину пика, проверить output health. |
| **Worker utilization** | `flow.worker_utilization.current` > **0.90** (дольше 15–20 мин) | **High** | Конвейер близок к пределу. Риск лавинообразного backpressure. | Мониторить рост очереди. При устойчивом >0.95 — планировать увеличение workers (только если CPU/IO позволяют). |
| **Worker underutilized** | `flow.worker_utilization.current` < **0.40** (стабильно, нет пиков) | **Low/Info** | Избыточные ресурсы (можно оптимизировать). | Оценить целесообразность снижения workers (экономия памяти Heap). |
| **Output lag divergence** | `input_throughput` − `output_throughput` > 0 длительно, `queue_persisted_growth_events` > 0 | **High** | Явный разрыв вход/выход. | Фокус на output-плагине, целевой системе (latency/errors). |
| **DLQ growth** | Объём DLQ растёт **> X МБ/ч** или превышает **пороговое значение** (например 500МБ) | **Medium–High** | Постоянные ошибки обработки/вывода (mapping, формат). | Найти причину (логи LS), исправить конфиг/маппинг, запланировать переобработку DLQ. |
| **DLQ sustained growth** | DLQ растёт **>30–60 мин** без остановки | **High** | Ошибка системная, а не единичный битый батч. | Обязательно расследовать (не игнорировать). |
| **Queue push duration (PQ I/O)** | `events.queue_push_duration_in_millis` растёт **в 2–3×** выше базового значения | **Medium** | Замедление диска под PQ (IOPS/latency). | Проверить нагрузку на диск, I/O wait, тип диска. |
| **Event duration growth** | `events.duration_in_millis` при фиксированном throughput растёт | **Medium–High** | Фильтры/плагины стали медленнее (CPU-bound или тяжёлые regex/grok/lookup). | Найти узкое место (Flow Metrics + hot_threads), оптимизировать парсинг («Dissect first, Grok last»). |
| **JVM Heap pressure** | `jvm.mem.heap_used_percent` близко к max (GC часто, Old Gen растёт) | **High** | Риск OOM. Связано с `inflight count` (workers×batch.size). | Снизить `pipeline.batch.size`/`pipeline.workers`, проверить большие события. |

> **Правило:** алертить по **устойчивому тренду** (5–15 минут), а не по единичному спайку. Исключение — критические (DLQ лавинообразно растёт, PQ заполняется очень быстро).

### Как интерпретировать комбинации метрик

| Комбинация | Диагноз | Действие |
|---|---|---|
| `worker_utilization ~0.7–0.8`, `queue_persisted_growth == 0`, `queue.size ~0` | **Здорово, с запасом** | Нормальное состояние. |
| `worker_utilization >0.9`, `queue_persisted_growth_events>0`, `queue.size растёт` | **Output bottleneck** | Сосредоточить поиск на output (ES health, bulk latency, throttling). |
| `worker_utilization >0.9`, `queue.size ~0`, `events.in/out стабильны` | **CPU-bound в фильтрах** | Оптимизировать grok/dissect, убрать тяжёлые regex, проверить hot_threads. |
| `worker_utilization низкий (<0.5)`, `queue.size растёт`, `events.queue_push_duration растёт` | **Disk I/O bottleneck (PQ)** | Диск под PQ не справляется (IOPS/latency). |
| `DLQ устойчиво растёт, queue стабилен` | **Проблема с событиями/маппингом** | Анализировать ошибки в логах, исправить фильтры/mapping, повторно обработать DLQ. |

## Практические сценарии

### Smoke-тест пайплайна (stdin → stdout)

Быстрый способ проверить изменения `.conf` до деплоя (особенно grok/условия):

```bash
echo '2026-08-23T10:00:00 ERROR [payments] Reason: connection failed after 30s' | \
  /usr/share/logstash/bin/logstash \
    -e 'input { stdin{} } filter { ...здесь ваш фильтр... } output { stdout { codec => rubydebug } }'
# → событие обработано через весь конвейер; проверьте выходные поля
```

Или с полным конфигом ветки (быстрый локальный прогон):

```bash
/usr/share/logstash/bin/logstash \
  -f /etc/logstash/conf.d/10-test.conf \
  --config.test_and_exit
# → Configuration OK
# затем без -t для прогона с тестовыми данными
```

### CI CD пайплайн (минимальный практический)

Рекомендуемая последовательность в CI:

```bash
# 1. Синтаксическая валидация
logstash --path.settings config/ci-settings -t
# → Configuration OK

# 2. (опц.) Линтер/проверка grok-паттернов, если есть кастомные
# 3. Smoke-тест на репрезентативных образцах (если позволяют ресурсы)
# 4. Деплой в staging → smoke-тест → мониторинг метрик 5–10 минут
# 5. Деплой в prod (по узлам), HUP/reload, пост-проверка _node/stats
```

**Важно:** `-t` обязателен перед **любым** деплоем. Запускать в изолированном окружении (CI) без доступа к внешним сервисам — корректно (lookup-плагины недоступны, но синтаксис проверяется).

### Проверка после деплоя (post-deploy checklist)

1. **Логи**: нет `[ERROR]`/критических ошибок после reload/SIGHUP (`journalctl -u logstash -f` 1–2 мин)

```bash
journalctl -u logstash -f --since "1 min ago" | grep -i error
# → пустой вывод (нет ошибок)
```

2. **Валидация reload**: успешный переход конвейера (Pipeline started) в логах

```bash
journalctl -u logstash -f | grep "Pipeline started"
# → [INFO ][logstash.pipeline] Pipeline started {"pipeline.id"=>"main"}
```

3. **Метрики**: `curl -s localhost:9600/_node/stats/pipelines | jq '.pipelines.main | {events, queue, flow}'`

```bash
curl -s localhost:9600/_node/stats/pipelines/main | \
  jq '{in:.events.in, out:.events.out, q:.queue.size, wu:.flow.worker_utilization}'
# → {"in":10526691,"out":10525882,"q":{"bytes":0,"events":0},"wu":{"current":45.2}}
```

4. **Баланс вход/выход**: `events.in` растёт, `events.out` догоняет, `queue_persisted_growth_events == 0` в течение 5–10 минут

```bash
watch -n 30 'curl -s localhost:9600/_node/stats/pipelines/main | \
  jq -r "\(.events.in) → \(.events.out) | growth: \(.queue.persisted.growth.events)"'
# → 10526691 → 10525882 | growth: 0
```

5. **DLQ**: не растёт

```bash
du -sh /var/lib/logstash/dead_letter_queue/main/
# → 0B (или растёт только при известных проблемах)
```

6. **Hot threads** (опц., при подозрении на CPU-узкое место): `curl -s 'localhost:9600/_node/hot_threads?human=true' | head -40`

```bash
curl -s 'localhost:9600/_node/hot_threads?human=true' | head -10
# → 29.56% (7.39 ms) ... [java.lang.Thread.State: RUNNABLE] ...
```

### Быстрый мониторинг в shell

Однострочные команды для оперативной диагностики:

```bash
# Worker utilization по всем пайплайнам
curl -s 'localhost:9600/_node/stats/pipelines' | \
  jq '.pipelines[] | {id: .id, wu: .flow.worker_utilization, qgrowth: .queue.persisted.growth.events}'

# Краткое состояние main-пайплайна
curl -s 'localhost:9600/_node/stats/pipelines/main' | \
  jq '{in:.events.in, out:.events.out, q:.queue.size, wu:.flow.worker_utilization}'

# Сводка по всем узлам кластера (при наличии балансировщика)
for host in ls-node-01 ls-node-02 ls-node-03; do
  echo -n "$host: "
  curl -s "http://$host:9600/_node/stats/pipelines/main" | \
    jq -r '"in=\(.events.in) out=\(.events.out) wu=\(.flow.worker_utilization.current)"'
done
```

### Скрипт проверки здоровья (health check)

Для readiness/liveness probe или cron-проверки на узле:

```bash
#!/bin/bash
# health_check.sh — проверка состояния Logstash
set -euo pipefail

API_HOST="${LS_API_HOST:-localhost}"
API_PORT="${LS_API_PORT:-9600}"

# 1. API отвечает
curl -sf "http://${API_HOST}:${API_PORT}/" >/dev/null 2>&1 || {
  echo "CRITICAL: Logstash API недоступен"
  exit 2
}

# 2. Health report — статус узла
status=$(curl -sf "http://${API_HOST}:${API_PORT}/_health_report" | \
  jq -r '.status')
if [ "$status" != "green" ]; then
  echo "CRITICAL: health_report = ${status}"
  exit 2
fi

# 3. На всех пайплайнах: events.in примерно == events.out, нет роста PQ
curl -sf "http://${API_HOST}:${API_PORT}/_node/stats/pipelines" | \
  jq -r '.pipelines | to_entries[] | 
    select(.value.queue.persisted.growth.events > 0) | 
    "WARNING: \(.key) queue growth = \(.value.queue.persisted.growth.events)"' | head -5

# 4. Heap < 85%
heap=$(curl -sf "http://${API_HOST}:${API_PORT}/_node/stats/jvm" | \
  jq -r '.jvm.mem.heap_used_percent')
if [ "$heap" -gt 85 ]; then
  echo "CRITICAL: heap usage = ${heap}%"
  exit 2
fi

echo "OK: all checks passed"
exit 0
```

Сохранить как `/usr/local/bin/logstash-health-check.sh`, добавить в cron каждые 5 минут, интегрировать с системой мониторинга (Nagios/Icinga/Zabbix через `check_command`).

## Операции и команды

### Сбор метрик для алертинга (скрипты)

Для интеграции с внешними системами мониторинга (Nagios, Icinga, Zabbix) используйте однострочки или скрипты:

```bash
# Проверка: есть ли backpressure на любом пайплайне (>0 10 минут)
curl -s 'localhost:9600/_node/stats/pipelines' | \
  jq '.pipelines | to_entries[] | select(.value.queue.persisted.growth.events > 0) | .key'

# Проверка: worker_utilization > 90% на main-пайплайне
curl -s 'localhost:9600/_node/stats/pipelines/main' | \
  jq '.flow.worker_utilization.current'
# → 93.09

# Проверка: DLQ растёт
curl -s 'localhost:9600/_node/stats/pipelines/main' | \
  jq '.dead_letter_queue'

# Health report — статус и детали
curl -s 'localhost:9600/_health_report?pretty' | \
  jq '{status: .status, indicators: (.indicators | keys)}'
```

### Удалённый сбор метрик (по узлам кластера)

Для мониторинга нескольких узлов Logstash без Elastic Agent:

```bash
#!/bin/bash
# remote_stats.sh — сбор stats с нескольких узлов
HOSTS=("ls-node-01" "ls-node-02" "ls-node-03")
for host in "${HOSTS[@]}"; do
  echo "=== $host ==="
  curl -sf "http://$host:9600/_node/stats/pipelines/main" | \
    jq '{
      version: .version,
      events: .pipelines.main.events,
      flow: .pipelines.main.flow,
      queue: .pipelines.main.queue
    }' 2>/dev/null || echo "ERROR: $host unreachable"
done
```

## Типичные проблемы и их решение (Troubleshooting)

1. **Monitoring API недоступен с другого хоста.**
   Причина: по умолчанию `api.http.host: 127.0.0.1` — слушается только loopback.
   Решение: установите `api.http.host: 0.0.0.0` в `logstash.yml` и ограничьте доступ по IP через firewall. Перезапустите Logstash (изменение `logstash.yml` требует рестарта, а не reload).

2. **Алерт срабатывает, но конвейер работает нормально.**
   Причина: алерт по единичному спайку (например, momentary spike `worker_utilization` из-за GC пауз).
   Решение: переключите алерт на **устойчивый тренд** (10–15 минутное окно). Используйте `last_15_minutes` вместо `current`.

3. **`logstash -t` проходит, но конвейер падает в production.**
   Причина: `-t` не проверяет grok-паттерны на реальных данных, lookup-плагины недоступны в CI, не проверяет маппинг ES.
   Решение: добавьте smoke-тест на staging с репрезентативными событиями после каждого изменения конфигурации. См. [CI/CD пайплайн](#ci-cd-пайплайн-минимальный-практический).

4. **Алерт на рост `queue_persisted_growth_events`, но очередь сильно не заполняется.**
   Причина: кратковременный пик входящей нагрузки, который output обрабатывает через несколько минут.
   Решение: увеличьте пороговое окно с 5 минут до 10–15. Если рост устойчив — проверьте статус Elasticsearch (`_cluster/health`), bulk latency и retry-счетчики output-плагина.

5. **Health report показывает `yellow`, но метрики в норме.**
   Причина: `_health_report` проверяет наличие datafeed/источников, настройки security и т.д. — не только performance.
   Решение: изучите indicators в ответе: `curl -s 'localhost:9600/_health_report?pretty' | jq '.indicators'`. Исправляйте конкретный symptom, а не глобальный статус.

6. **DLQ растёт, но события в нём не переобрабатываются.**
   Причина: перечитывающий конвейер с `commit_offsets => true` продвигает позицию чтения, но output-плагин с теми же событиями снова пишет их в DLQ (цикл ошибки).
   Решение: анализируйте `[@metadata][dead_letter_queue].reason` в событиях из DLQ, исправляйте root-cause (маппинг/формат), используйте `commit_offsets => false` для многократного просмотра. См. [управление DLQ](./logstash_pipelines.md#управление-dead-letter-queue).

7. **Алерт на heap не срабатывает, хотя heap растёт.**
   Причина: алерт опрашивает `_node/stats` с интервалом, который слишком велик для быстрых пиков.
   Решение: уменьшите интервал опроса алёрта до 1 минуты; добавьте проверку GC pause time через `_node/hot_threads`.

8. **Метрика `queue_persisted_growth_events` всегда 0, хотя есть подозрение на backpressure.**
   Причина: `queue.type: memory` вместо `persisted` — PQ не ведётся, метрика недоступна.
   Решение: включите `queue.type: persisted` в production. См. [Persistent Queue в обзоре](./logstash_overview.md#настройка-persistent-queue-для-защиты-от-потери-данных).

## Лучшие практики и очистка окружения

* **Алерты по тренду, а не по спайку.** Используйте окна `last_15_minutes` в алертах; минимальное окно — 5 минут. Исключение: критические условия (PQ заполняется > 90%, DLQ растёт лавинообразно).
* **`logstash -t` перед каждым деплоем.** Это стоп-фактор для сломанных конфигов. Не заменяет smoke-тест на staging, но ловит опечатки и синтаксические ошибки.
* **PQ + DLQ на каждом production-узле.** Размер PQ рассчитан по формуле `поток_байт/сек × часы_простоя × 3600 × 1.10` (см. [обзор](./logstash_overview.md#настройка-persistent-queue-для-защиты-от-потери-данных)). DLQ включена и мониторится по объёму.
* **Безопасность API.** В production включайте Basic auth (`api.auth.type: basic`) и TLS (`api.ssl.enabled: true`); не оставляйте API на `0.0.0.0` без аутентификации.
* **Связка узлов в кластере.** Мониторьте каждый узел отдельно через `/_node/stats` — агрегация через балансировщик скрывает проблемы на отдельных узлах.
* **Деплой поштучно.** Применяйте изменения конфигурации на один узел, проверяйте метрики (`events.in/out`, рост DLQ), затем переходите к следующему.
* **Очистка тестового окружения** после экспериментов:

```bash
# Остановить сервис
sudo systemctl stop logstash

# Удалить тестовые конфиги
sudo rm /etc/logstash/conf.d/test-pipeline.conf

# Очистить состояние очередей и DLQ (осторожно: невыгруженные события будут потеряны)
sudo rm -rf /var/lib/logstash/queue/* /var/lib/logstash/dead_letter_queue/*

# Проверить освобождение портов
ss -tlnp | grep -E '5044|9600'
# → пустой вывод
```

## Дополнительная информация

### См. также

- **[Logstash: Обзор](./logstash_overview.md)** — архитектура стадий, настройка Persistent Queue, Monitoring API, post-deploy checklist.
- **[Logstash: Конвейеры, фильтры и производительность](./logstash_pipelines.md)** — Flow Metrics (детальная методика диагностики), тюнинг, управление DLQ, P2P.
- **[Logstash: Production-эксплуатация](./logstash_production.md)** — горизонтальное масштабирование, rolling update, capacity planning, CI/CD.
- **[Logstash: Конфигурация, перезагрузка и zero-downtime](./logstash_config_reload.md)** — hot-reload, SIGHUP, `config.reload.automatic`, `pipeline.recoverable`.
- **[Logstash: Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)** — конфигурации input/output-плагинов, retry-семантика, валидация конфигурации.
- **[Logstash: Backpressure, batching и поведение Input](./logstash_backpressure_batching.md)** — интерпретация метрик queue/flow.
- **[Stack Monitoring: Мониторинг Elastic Stack](../Elasticsearch/elasticsearch_stack_monitoring.md)** — архитектура сбора метрик через Elastic Agent/Metricbeat, настройка retention, алертинг через Kibana Alerting и Watcher.
- **[Logstash: Обзор](https://www.elastic.co/docs/reference/logstash/monitoring-logstash)** — официальная документация по Monitoring API и endpoints.
- **[Logstash Node Stats API](https://www.elastic.co/docs/api/doc/logstash/group/endpoint-node-stats)** — справочник эндпоинтов Node Stats (pipelines, flow, events).
- **[Logstash Health Report API](https://www.elastic.co/docs/api/doc/logstash/group/endpoint-health)** — справочник `_health_report` и indicators.
- **[Logstash command-line flags](https://www.elastic.co/docs/reference/logstash/running-logstash-command-line)** — `-t`, `--api.http.port`, `--pipeline.workers` и другие флаги.
