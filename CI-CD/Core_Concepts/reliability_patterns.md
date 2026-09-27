# Паттерны надёжности (SRE/DevOps)

> Комплексный обзор паттернов отказоустойчивости и масштабируемости микросервисной архитектуры — в **[Паттерны микросервисной архитектуры](../../Concepts/microservice_patterns.md)**. Ниже — краткий справочник с примерами.

## Определения

- **Идемпотентность (Idempotency)** — фундамент надёжности, на котором строится безопасный повтор операций. Подробно с примерами (Idempotency-Key, UPSERT, Inbox/Outbox, IaC) — в специализированной заметке **[Идемпотентность](../../Concepts/idempotency.md)**.
- **Retry (Повтор)** — автоматический повтор неудачной операции.
- **Exponential Backoff + Jitter** — увеличение паузы между попытками по экспоненте с случайной задержкой (jitter), чтобы избежать «шторма повторов».
- **Circuit Breaker (Предохранитель)** — прерыватель: после N ошибок открывается и блокирует вызовы, давая зависимости восстановиться (полуоткрытое состояние для проверки).
- **Bulkhead (Перегородка)** — изоляция ресурсов в пулы, чтобы сбой одного не исчерпал все соединения/потоки.
- **Graceful Degradation (Плавная деградация)** — при деградации зависимости сервис продолжает работу в урезанном режиме (кэш вместо БД, заглушки вместо второстепенных функций), а не падает целиком.
- **Load Shedding (Сброс нагрузки)** — намеренный отказ части входящих запросов при исчерпании собственной ёмкости; см. отдельную заметку **[Load Shedding](./load_shedding.md)**. Отличается от Circuit Breaker: breaker защищает от сломанной зависимости, shedding — от перегрузки самого сервиса.
- **Timeout / Deadline** — ограничение времени ожидания ответа; deadline — сквозной бюджет на цепочку вызовов.
- **Chaos Engineering** — контролируемые эксперименты по разрушению компонентов для выявления слабых мест (см. [Обзор Chaos Engineering](../../Chaos_Engineering/chaos_engineering_overview.md)).

## Основные концепции

### Идемпотентность как основа Retry

Повторять можно только **идемпотентные** операции. Без идемпотентности retry удваивает побочные эффекты (двойное списание, дубли записей). Детальное описание, типы операций и практические реализации (Idempotency-Key, транзакционный UPSERT, паттерны Inbox/Outbox, идемпотентность в IaC) вынесены в **[Идемпотентность](../../Concepts/idempotency.md)**, чтобы не дублировать материал.

### Retry и Backoff

Без backoff+Jitter повторы при массовом сбое создают синхронную волну нагрузки (retry storm). Правило: ограниченный лимит попыток, экспоненциальная задержка, jitter, и отказ после исчерпания с передачей ошибки выше.

### Timeout и Deadline budgeting

Отсутствие таймаута = бесконечное зависание. В цепочке сервисов каждый узел должен получить часть общего deadline, а не свой максимум — иначе суммарная задержка превысит ожидаемое.

### Circuit Breaker и Bulkhead

- **Breaker**: `Closed` (норма) → `Open` (ошибки превысили порог, вызовы блокируются) → `Half-Open` (пропускает пробную долю, решает восстановление).
- **Bulkhead**: отдельные пулы соединений для критичных и фоновых вызовов; падение фонового не «съедает» лимит критичного. В [Стратегиях развёртывания](./deployment_strategies.md) эти паттерны применяются на уровне трафика.

### Graceful Degradation

Вместо полного отказа при деградации зависимости сервис отдаёт ослабленный, но рабочий ответ: закэшированные/устаревшие данные (stale-while-unavailable), статические заглушки, отключение некритичных функций (рекомендации, счётчики, персонализация). Это сохраняет базовый путь (просмотр каталога, оформление заказа) при падении второстепенного. Деградация тесно связана со сбросом нагрузки: когда shedding решает «не тянем», degradation решает «вернём урезанный результат вместо ошибки». Вопрос «что отключать» фиксируется заранее через feature flags (см. **[Feature Toggles](../../CI-CD/Testing/feature_toggles/types.md)**).

### Chaos Engineering

Регулярные эксперименты (убить под, отрезать сеть до реестра, задержка диска) в непроде доказывают, что паттерны выше работают. Инструменты и метрики — в [Chaos Engineering: инструменты](../../Chaos_Engineering/chaos_engineering_tools.md).

### Контекст SRE / DevOps / Sysadmin

#### SRE

- **SLO-бюджет:** каждый паттерн — инструмент защиты бюджета ошибок; при росте shed-rate или ошибок retry-цепочки алерт должен fires до исчерпания бюджета.
- **Burn Rate:** Circuit Breaker открывается не по абсолютному числу ошибок, а по скорости их появления относительно допустимого бюджета.
- **Инцидент-менеджмент:** при расследовании нужно отличать retry storm от штатного surge, shedding от отказа backend, timeout от deadlock.

#### DevOps

- **CI/CD:** пайплайн должен проверять идемпотентность миграций и скриптов; артефакты — иммутабельные; деплой — повторяемый.
- **Observability:** метрики breaker state, shed-rate, timeout histogram, retry count — обязательны в пайплайн и дашборд.
- **Automation:** настройка паттернов через IaC, а не вручную; drift-детекция на конфиги circuit breaker и timeout.

#### Sysadmin

- **ОС/сети:** настройка `ulimit -n`, `somaxconn`, `tcp_syncookies`, `nf_conntrack_max` — это инфраструктурная часть bulkhead и timeout.
- **Базы данных:** пулы соединений (PgBouncer), `statement_timeout`, `idle_in_transaction_session_timeout` — первые линии защиты от каскадного отказа.
- **Load Balancer:** настройка очередей, health check, circuit breaker на边缘 (например, HAProxy `errorfile` + `monitor fail`).

## Практические сценарии

### Сценарий 1: Retry с exponential backoff + jitter (bash)

```bash
retry() {
  local n=0; local max=5; local delay=1
  until "$@"; do
    n=$((n+1)); [ $n -ge $max ] && { echo "failed after $max"; return 1; }
    sleep "$(awk -v d=$delay -v j=$RANDOM 'BEGIN{srand(j); print d*(2^(n-1))+rand()*d}')"
  done
}
retry curl -fsS http://registry.internal/healthz
```

### Сценарий 2: Circuit breaker (пример на nginx/limit, концептуально)

```nginx
# Ограничение и «открытие» при сбоях upstream (upstream с health-check)
upstream api {
  server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
  server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
}
# При исчерпании fail_timeout nginx перестаёт слать трафик (аналог Open)
```

### Сценарий 3: Deadline budgeting (Go, концепт)

```go
ctx, cancel := context.WithTimeout(parent, 200*time.Millisecond)
defer cancel()
// каждый вложенный вызов наследует сокращающийся ctx.Deadline()
resp, err := downstream.Do(ctx, req)
```

### Сценарий 4: Graceful Degradation (фоллбэк на кэш/заглушку)

```python
def get_recommendations(user_id):
    try:
        return ml_service.recommend(user_id)   # второстепенная функция
    except DependencyError:
        return []                               # деградация: пустой список, не 500
```

Критичный путь (корзина, оплата) продолжает работать; рекомендации тихо отключаются. Связь со сбросом нагрузки — в **[Load Shedding](./load_shedding.md)**.

### Сценарий 5: Bulkhead (изоляция пулов соединений)

```python
from concurrent.futures import ThreadPoolExecutor

# отдельные пулы: сбой фонового не съедает ёмкость критичного
critical_pool   = ThreadPoolExecutor(max_workers=20, thread_name_prefix="critical")
background_pool = ThreadPoolExecutor(max_workers=5,  thread_name_prefix="bg")

def handle(req):
    pool = critical_pool if req.is_critical else background_pool
    return pool.submit(process, req)
```

На уровне БД аналогично: разные `default_pool_size` в **[PgBouncer](../../Databases/PostgreSQL/Operations/pgbouncer_setup.md)** для критичных и фоновых пользователей.

> Идемпотентный пример миграции БД (CREATE IF NOT EXISTS / UPSERT) и другие реализации — в **[Идемпотентность](../../Concepts/idempotency.md)**.

## Операции и команды

### Circuit Breaker: мониторинг состояния

```bash
# Проверка статуса circuit breaker в Consul (если используется Consul для service mesh)
curl -s http://localhost:8500/v1/kv/circuit-breaker/api/service | jq .
# → {"Value":"eyJyZXN0cmljdGlvbiI6ICJvcGVuIiwgInN0YXR1cyI6ICJvcGVuIn0="}
```

```bash
# Проверка состояния upstream в nginx через stub_status + grep
curl -s http://localhost:8080/nginx_status | grep -E 'Active connections|Reading|Writing|Waiting'
# → Active connections: 25
# → Reading: 2 Writing: 3 Waiting: 20
```

### Timeout: диагностика и отладка

```bash
# curl с таймаутом и ожидаемым кодом ответа
curl -o /dev/null -s -w "time_total=%{time_total}\nhttp_code=%{http_code}\n" --max-time 2 http://api.internal/endpoint
# → time_total=0.184
# → http_code=200
```

```bash
# Проверка TCP timeout на уровне ядра (sysctl)
sysctl net.ipv4.tcp_syn_retries net.ipv4.tcp_synack_retries
# → net.ipv4.tcp_syn_retries = 6
# → net.ipv4.tcp_synack_retries = 5
```

### Bulkhead: ограничение пулов

```bash
# Проверка лимитов файловых дескрипторов (ulimit) — часть bulkhead на уровне ОС
ulimit -n
# → 65536

# Проверка текущих открытых дескрипторов процесса
ls /proc/$(pgrep -f myapp)/fd | wc -l
# → 1243
```

```bash
# Настройка statement_timeout для PostgreSQL (bash через psql)
psql "postgresql://app_user@db.internal:5432/prod" -c "ALTER ROLE app_user SET statement_timeout = '5s';"
# → ALTER ROLE
```

```bash
# Проверка текущего statement_timeout
psql "postgresql://app_user@db.internal:5432/prod" -c "SHOW statement_timeout;"
# → statement_timeout
# → 5s
```

### Graceful Degradation: проверка fallback

```bash
# Имитация отказа зависимости и проверка fallback через curl
curl -s http://app.internal/api/recommendations | jq .
# → []

# Проверка заглушек (static fallback) через HTTP-код
curl -o /dev/null -s -w "%{http_code}\n" http://app.internal/api/recommendations
# → 200
```

### Monitoring: алерты и метрики

```bash
# Проверка метрик Prometheus для Circuit Breaker (если используется prometheus-ipmi или custom exporter)
curl -s http://localhost:9090/api/v1/query?query=circuit_breaker_state{service="api"} | jq .
# → {"status":"success","data":{"resultType":"vector","result":[]}}
```

```bash
# Burn rate через PromQL (пример для 99.9% SLO за 1 час)
curl -s 'http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[1h]) / rate(http_requests_total[1h]) > 14.4'
# → {"status":"success","data":{"resultType":"vector","result":[]}}
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
| :--- | :--- | :--- | :--- |
| Retry storm: всплеск нагрузки при массовом сбое | Retry без backoff+jitter или слишком агрессивный `max` | Добавить exponential backoff + jitter, уменьшить `max`, использовать circuit breaker | DevOps, SRE |
| Circuit breaker всегда в состоянии Open | Порог ошибок слишком низкий, unhealthy upstream не removed | Выровнять порог по реальному SLO; настроить health check и `fail_timeout` | SRE, Sysadmin |
| Timeout = 0 / отсутствует | Настройка не перенесена в конфиг или переопределена дефолтом | Установить явный timeout на всех уровнях: клиент, прокси, БД | Sysadmin, DevOps |
| Каскадный отказ: один сервис тянет всю цепочку | Нет bulkhead: общий пул потоков/соединений | Разделить пулы по критичности, настроить `ulimit`, `max_connections` | Sysadmin, SRE |
| Graceful degradation не включается | Отсутствуют feature flags или fallback-логика | Ввести feature flags, покрыть fallback тестами, документация | DevOps |
| Deadline violation: запрос зависает в середине цепочки | Сумма таймаутов звеньев превышает общий deadline | Распределить бюджет по цепочке: каждый узел получает `deadline * 0.7` | SRE, DevOps |
| Load shedding срабатывает слишком рано / поздно | Порог настроен статично, не учитывает профиль нагрузки | Использовать adaptive shedding по live-метрикам (queue length, in-flight) | SRE |
| Повторяющиеся инциденты после фикса | Нет postmortem, паттерн не зафиксирован в runbook | Провести безвиновный постмортем, обновить runbook, добавить тест | SRE, DevOps |
| Идемпотентность нарушена при повторном запуске | Нет idempotency-key или UPSERT в критических операциях | Внести ключи идемпотентности, покрыть интеграционными тестами | DevOps |
| Shedding/breakers не видны в observability | Нет метрик, алертов, дашбордов | Добавить shed-rate, breaker-state, timeout-histogram в стек мониторинга | SRE |

## Лучшие практики

### Архитектура и проектирование

- **Идемпотентность по умолчанию:** все внешние API, очереди, хуки должны допускать безопасный повтор.
- **Слой отказов:** для каждой внешней зависимости опишите fallback-поведение и уровень деградации заранее.
- **Разделение по критичности:** критичный путь (оплата, auth) изолирован от фонового (рекомендации, аналитика) на уровне пулов, очередей и бюджетов.
- **Budget propagation:** deadline передаётся по цепочке, а не дублируется; каждый узел знает свой лимит.

### Надёжность

- **Breaker до интеграции:** circuit breaker настраивается на этапе проектирования, а не после первого инцидента.
- **Backpressure:** shedding и bulkhead — не временные меры, а постоянная защита.
- **Toil budget:** автоматизируйте настройку паттернов через IaC; конфиги breaker/timeout — код, а не ручная настройка.

### Безопасность

- **Ограничения ОС:** `ulimit -n`, `somaxconn`, `nf_conntrack_max` — часть инфраструктурного bulkhead.
- **Таймауты на всех уровнях:** клиент, прокси, приложение, БД — все должны иметь явный timeout.
- **Аудит конфигов:** drift-детекция для circuit breaker, timeout, pool size — обязательна.

### Производительность

- **Перцентили вместо средних:** для timeout и latency ориентируйтесь на p95/p99, а не на среднее значение.
- **Jitter в backoff:** всегда добавляйте случайность, чтобы избежать синхронизации повторов.
- **Графики shed-rate:** визуализируйте долю сброшенных запросов для быстрого принятия решений.

### Организация процессов

- **Runbook для каждого паттерна:** алерт на breaker open должен иметь пошаговый план действий.
- **Chaos Days:** регулярные эксперименты в непроде для проверки работоспособности паттернов.
- **Безвиновный постмортем:** каждый инцидент, связанный с отсутствием паттерна, фиксируется и преобразуется в задачу.
- **Обучение:** паттерны надёжности — часть онбординга DevOps/SRE/Sysadmin.

## Дополнительная информация

### Антипаттерны

- **Retry без идемпотентности** — повтор удваивает побочные эффекты.
- **Timeout = 0 / отсутствует** — зависание навсегда при сбое зависимости.
- **Breaker всегда Open** — из-за слишком агрессивного порога нормальный трафик блокируется.
- **Один общий пул соединений** — без bulkhead сбой одного вызова исчерпывает все.
- **Shedding без observability** — отказы без метрик превращаются в «чёрный ящик».
- **Hardcoded пороги** — статические лимиты без адаптации под профиль нагрузки.

- [Стратегии развёртывания](./deployment_strategies.md) — breaker/bulkhead на трафике.
- [Наблюдаемость пайплайнов](./pipeline_observability.md) — метрики для решений о breaker.
- [Chaos Engineering: обзор](../../Chaos_Engineering/chaos_engineering_overview.md) — проверка паттернов на практике.
