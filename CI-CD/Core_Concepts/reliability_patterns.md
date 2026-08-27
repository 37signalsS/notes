# Паттерны надёжности (SRE/DevOps)

## Определения

- **Идемпотентность (Idempotency)** — фундамент надёжности, на котором строится безопасный повтор операций. Подробно с примерами (Idempotency-Key, UPSERT, Inbox/Outbox, IaC) — в специализированной заметке **[Идемпотентность](../../Concepts/idempotency.md)**.
- **Retry (Повтор)** — автоматический повтор неудачной операции.
- **Exponential Backoff + Jitter** — увеличение паузы между попытками по экспоненте с случайной задержкой (jitter), чтобы избежать «шторма повторов».
- **Circuit Breaker** — прерыватель: после N ошибок открывается и блокирует вызовы, давая зависимости восстановиться (полуоткрытое состояние для проверки).
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

## Дополнительная информация

### Антипаттерны

- **Retry без идемпотентности** — повтор удваивает побочные эффекты.
- **Timeout = 0 / отсутствует** — зависание навсегда при сбое зависимости.
- **Breaker всегда Open** — из-за слишком агрессивного порога нормальный трафик блокируется.
- **Один общий пул соединений** — без bulkhead сбой одного вызова исчерпывает все.

### См. также

- [Стратегии развёртывания](./deployment_strategies.md) — breaker/bulkhead на трафике.
- [Наблюдаемость пайплайнов](./pipeline_observability.md) — метрики для решений о breaker.
- [Chaos Engineering: обзор](../../Chaos_Engineering/chaos_engineering_overview.md) — проверка паттернов на практике.
