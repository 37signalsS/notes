# Отладка и производительность Traefik: pprof, таймауты, HTTP/2 тюнинг

## Определения

**pprof** — встроенный профилировщик Go-рантайма: heap-dump, CPU-профиль, goroutine trace. Включается через `api.debug: true`.

**Горутины (goroutines)** — легковесные потоки Go; утечка горутин (незакрытые соединения/стойкие хелс-чеки/долгие запросы) проявляется как рост памяти и латентности.

**GOMAXPROCS** — переменная Go-рантайма, ограничивающая число параллельно исполняемых CPU-потоков. По умолчанию = число ядер хоста; в контейнере с CPU-квотой требует ручной настройки.

**504 Gateway Timeout** — ответ «истёк лимит ожидания ответа вышестоящего сервера». В Traefik возникает при исчерпании таймаутов на диалог с бэкендом или клиентом.

**Keep-alive после N запросов** — завершение HTTP/1.1 и HTTP/2 соединения `Connection: Close`/`GOAWAY` после обработки заданного числа запросов (`transport.keepAliveMaxRequests`) — защита от неограниченного жизненного цикла подключения.

## Базовые концепции

### Таймауты: где и какие бывают

В Traefik **две независимые группы таймаутов**:

1. **`serversTransport.forwardingTimeouts`** — таймауты клиентского пула соединений с бэкендом:

```yaml
serversTransport:
  forwardingTimeouts:
    dialTimeout: 30s            # установка TCP-соединения с бэкендом
    responseHeaderTimeout: 0s   # ожидание заголовков ответа; 0 = нет лимита (по умолчанию!)
    idleConnTimeout: 90s        # idle-соединение в пуле
  maxIdleConnsPerHost: 200      # размер пула keep-alive на бэкенд
```

2. **`entryPoints.<name>.transport.respondingTimeouts`** — таймауты приема/выдачи на entrypoint (сторона клиента):

```yaml
entryPoints:
  websecure:
    transport:
      respondingTimeouts:
        readTimeout: 0s     # чтение запроса клиента; 0 = нет (по умолчанию)
        writeTimeout: 0s    # запись ответа клиенту; 0 = нет (по умолчанию!)
        idleTimeout: 180s   # idle между запросами в keep-alive (default 180)
      keepAliveMaxRequests: 0   # закрыть соединение после N запросов (0 = выключено)
      keepAliveMaxTime: 0s
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 15s
    http2:
      maxConcurrentStreams: 250   # параллельные H2-стримы на одно соединение
```

Важно: по умолчанию **оба** `readTimeout` и `writeTimeout` = `0` (отключены). Значит, «зависший» бэкенд не породит 504 сам по себе — клиенты будут висеть. Поэтому в прод-конфигурации выставляйте `writeTimeout` осознанно.

### Куда уходит 504

Цепочка возникновения `504`:

```
клиент ──62x большие запросы не проходят──▶ entrypoint ──serversTransport──▶ бэкенд(завис/медленный)
                                              │                                   │
                                              └── respondingTimeouts          dialTimeout / responseHeaderTimeout / backend itself
```

Типичные сценарии, когда появляется 504:

- backend не отвечает в пределах `dialTimeout` (адрес не резолвится, порт закрыт, бэкенд в состоянии watchdog);
- `responseHeaderTimeout` установлен, а приложение шлёт первые байты дольше лимита;
- бэкенд сам выходит по своему таймауту/закрывает соединение — Traefik возвращает 5xx.

**Практическое наблюдение**: `responseHeaderTimeout: 0` (по умолчанию) значит «ждать бесконечно». Если 504 всё же появляется при `0` — это почти всегда определяется на стороне бэкенда (закрыл соединение) или в `writeTimeout` на клиентскую сторону.

### Профилирование (pprof)

Включение (только для доверенных сетей!):

```yaml
api:
  insecure: false       # dashboard НЕ выставлять наружу
  debug: true           # включает /debug/pprof/*
```

Доступные точки на API-entrypoint:

| Endpoint | Что показывает |
| :--- | :--- |
| `GET /debug/pprof/heap?debug=1` | текстовый heap-профиль |
| `GET /debug/pprof/%zzz/...` | |
| `GET /debug/pprof/goroutine?debug=1` | стеки всех горутин (утечки!) |
| `GET /debug/pprof/profile?seconds=30` | CPU-профиль за 30с |
| `GET /debug/pprof/allocs` | профиль выделений |

Разбор:

```bash
# Снять сообщество CPU-профиля в файл и открыть интерактивно
go tool pprof http://127.0.0.1:8080/debug/pprof/profile?seconds=30
# → (pprof) top
# → (pprof) list <функция>

# Heap в текстовом виде
curl -s "http://127.0.0.1:8080/debug/pprof/heap?debug=1" | grep -i "inuse_space"
```

### GOMAXPROCS и CPU-квоты в контейнерах

Go по умолчанию использует все ядра хоста. Если контейнеру ограничена CPU-квота (`cpus: 1` на 8-ядерном хосте), рантайм всё равно может распараллеливать сборку мусора на 8 «потоков» — лишняя конкуренция и нестабильность. Рекомендация (для контейнерного Traefik):

```yaml
environment:
  GOMAXPROCS: "1"   # = CPU-лимиту контейнера, а не числу ядер хоста
```

## Практические сценарии

### Сценарий 1: Диагностика 504

```bash
# 1) Понять, где висит: время по фазам
curl -sS -o /dev/null -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://app.example.com/
# ttfb >> total — бэкенд не отдает первые байты

# 2) Проверить бэкенд напрямую (мимо Traefik)
curl -v --max-time 10 http://backend.internal:8080/health

# 3) Проверить забитые порты/ждет ли бэкенд
ss -tnp | rg '8080|8411'

# 4) Включить debug/темпорарные таймауты и повторить — лог/метрика «Gateway Timeout»
```

Шаги исправления, по мере вероятности:

1. бэкенд медленно/не отвечает → настраивать его таймауты и ретраи; поднять `forwardingTimeouts.dialTimeout`;
2. длинная обработка (загрузка файла) → поднять `respondingTimeouts.writeTimeout` на entrypoint;
3. стриминг больших ответов → убедиться, что `writeTimeout` достаточно большой (иначе режется середина), рассматривать `bufferingMiddleware` не нужен — просто лимиты.

### Сценарий 2: Профилирование утечки памяти

```bash
# 1) Снять heap дважды с интервалом и сравнить
curl -s "http://127.0.0.1:8080/debug/pprof/heap?debug=1" > heap1.txt
sleep 120
curl -s "http://127.0.0.1:8080/debug/pprof/heap?debug=1" > heap2.txt
diff <(grep -E 'inuse_space|go[0-9]' heap1.txt) <(grep -E 'inuse_space|go[0-9]' heap2.txt)

# 2) Посмотреть трудно завершающиеся горутины
curl -s "http://127.0.0.1:8080/debug/pprof/goroutine?debug=1" | rg -A3 'goroutine [0-9]+ \[|net/http'

# Признак утечки: однотипные горутины с [chan receive]/[select] навечно
# в комбинации с ростом RSS контейнера
```

### Сценарий 3: Тюнинг keep-alive под потоковые бэкенды

```yaml
serversTransport:
  maxIdleConnsPerHost: 200
  forwardingTimeouts:
    idleConnTimeout: 120s

entryPoints:
  websecure:
    transport:
      keepAliveMaxRequests: 1000   # переупорядочить соединения, раздавать через клиентские LB
      keepAliveMaxTime: 5m
    http2:
      maxConcurrentStreams: 250
```

Пояснение: `keepAliveMaxRequests: 1000` означает, что после 1000 запросов по соединению Traefik отдаст `Connection: Close` (H1) или `GOAWAY` (H2) — предотвращает несбалансированные долгоживущие соединения перед промежуточными LB и уменьшает взрывной рост числа подключений на бэкендах.

## Операции и команды

```bash
# Быстрая проверка здоровья/производительности
time curl -sS -o /dev/null "http://127.0.0.1:8080/api/version"   # API-эндпоинт
curl -s "http://127.0.0.1:8080/api/http/routers" | jq 'length'   # число роутеров

# Метрики Prometheus (если активирован entry point metrics)
curl -s "http://127.0.0.1:8080/metrics" | rg 'traefik_service_open_connections|traefik_entrypoint_requests_total'

# ФД-лимит (для bare-metal: LimitNOFILE)
sysctl fs.nr_open
cat /proc/$(pgrep -f 'traefik --configfile')/limits | rg 'open files'
```

## Практические сценарии

### Сценарий 4: Load testing и benchmarking

Цель — найти точку насыщения Traefik до того, как она коснется продакшена.

#### Инструменты

- **wrk** — Lua-скрипты, многопоточный, подходит для HTTP/1.1 и HTTP/2.
- **autocannon** — Node.js, простой синтаксис, похож на wrk.
- **hey** — Go, простой, поддерживает HTTP/2.

#### Протокол

1. **Базовый прогон (cold):**

```bash
wrk -t4 -c100 -d30s --latency https://app.example.com/
# → Latency p50/p95/p99, Requests/sec, Transfer
```

2. **Рост до saturation:**

```bash
for c in 50 100 200 400 800; do
  echo "=== concurrency=$c ==="
  wrk -t4 -c$c -d30s https://app.example.com/ | grep -E 'Latency|Requests/sec|errors'
done
```

3. **Критерии остановки:**
   - p99 latency превышает SLA (например, 200 ms).
   - Доля ошибок 5xx > 0.1%.
   - CPU Traefik > 75% sustained (смотреть `docker stats` или `top`).
   - FD exhaustion approaching (`cat /proc/$(pgrep traefik)/limits`).

#### Метрики для сбора во время теста

```bash
# В отдельном терминале
watch -n 1 'curl -s localhost:8080/metrics | rg "traefik_service_open_connections|traefik_entrypoint_requests_total|traefik_entrypoint_request_duration_seconds"'
```

#### Анализ pprof под нагрузкой

```bash
# CPU-профиль 30 секунд под нагрузкой
curl -s "http://127.0.0.1:8080/debug/pprof/profile?seconds=30" -o cpu_load.prof
go tool pprof -http=:8081 cpu_load.prof

# Goroutine count под нагрузкой
watch -n 1 'curl -s "http://127.0.0.1:8080/debug/pprof/goroutine?debug=1" | wc -l'
```

Норма: < 500 горутин на инстанс при 10 000 RPS. Резкий рост — утечка.

#### Ограничения

- **Не тестируйте** Traefik без бэкенда (только `200` от `api@internal`) — это не отражает реальную латентность.
- Тестируйте **с настоящим TLS** (если в проде есть ACME/TLS termination).
- Для HTTP/2: используйте `wrk -t4 -c200 -d30s --latency --h2 https://app.example.com/`.
- При использовании CDN/WAF перед Traefik — тестируйте **Traefik отдельно** (минуя CDN), чтобы отделить его contribution к латентности.

## Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **504 при `autoTimeout = 0`** | бэкенд закрыл соединение/не отвечает | Настроить бэкенд; поднять `dialTimeout`; проверить хелс-чеки сервиса |
| **Зависшие клиенты при медленном бэкенде** | `writeTimeout: 0` (нет лимита) | Выставить конечный `writeTimeout`/`responseHeaderTimeout` и SLA-границы |
| **Рост памяти, много горутин `[chan receive]`** | утечка через соединения/плагин | pprof heap ×2 и goroutine dump (см. выше) |
| **Латентность прыгает при нагрузке** | GOMAXPROCS > CPU-квоты контейнера | Установить `GOMAXPROCS` по CPU-лимиту |
| **HTTP/2 соединения копятся на бэкенде** | нет лимита числа запросов на соединение | `keepAliveMaxRequests`, `maxIdleConnsPerHost` |
| **pprof недоступен** | `api.debug: false` или API на закрытом entrypoint | Включить `debug: true`, доступ только из доверенной сети |

## Рекомендации

- Выставляйте конечные таймауты осознанно: полагаться на «по умолчанию = без лимита» приводит к бесконечным висениям клиентов.
- `api.debug: true` в проде — только на внутреннем/listed entrypoint с auth (или вообще только при расследовании).
- pprof — стандартный инструмент для ответа на «почему память растет»; делайте heap-профили в спокойный период и при пике.
- Для контейнерных деплоев всегда связывайте `GOMAXPROCS` с CPU-лимитом; для bare-metal снятие лимита — по ядрам хоста.
- Мониторинг таймаутов стройте на метриках `traefik_entrypoint_requests_total` (код 5xx) и SLO — см. [Наблюдаемость Traefik](./traefik-observability.md).

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — `serversTransport`, entrypoint-transport, HTTP/2.
- [Наблюдаемость Traefik](./traefik-observability.md) — Prometheus-метрики, SLO/алерты на таймауты.
- [Профилирование приложений (CI-CD)](../../CI-CD/Core_Concepts/performance_profiling.md) — общий флоу профилирования.
- [Разбор CPU-потребления процессов (Linux)](../../Linux/Diagnostics/Processes/thread_cpu_troubleshooting.md) — диагностика загрузки CPU процесса.
- [Profiling deep-dive (наблюдаемость)](../../Concepts/Observability_and_Monitoring/profiling_deep_dive.md) — теория профилирования Go/иных рантаймов.