# Apache: Настройка производительности (tuning)

---

## Определения

**Производительность Apache** — совокупность директив, определяющих количество одновременных соединений, время жизни воркеров, эффективность TLS/handshake, кэширование и сетевое поведение. Ключевая цель — сбалансировать использование памяти и CPU при допустимой задержке ответа.

**MPM (Multi-Processing Module)** — модель обработки соединений; определяет, как Apache выделяет процессы/потоки под запросы (`event`, `prefork`, `worker`).

**Scoreboard** — внутренняя структура Apache, отражающая текущее состояние каждого воркера (idle, busy, keepalive, read, send и т.д.). Доступна через `mod_status`.

**MaxRequestWorkers** — максимальное число одновременно обрабатываемых запросов (количество воркеров/потоков).

**SSLSessionCache** — кэш параметров возобновления TLS-сессий (список сессий/shared memory).

---

## Основные концепции

### MPM и модели обработки

| MPM | Процессы | Потоки | 1 запрос | Когда применять |
|---|---|---|---|---|
| `event` | да | да (включая async keep-alive) | поток | По умолчанию RHEL 9+/Ubuntu 22.04+/Debian 12+; PHP-FPM, чистый HTTP |
| `prefork` | да | нет | процесс | Только legacy `mod_php` |
| `worker` | да | да | поток | Устаревает; обратная совместимость |

**Ключевые директивы event MPM:**

| Директива | Назначение |
|---|---|
| `StartServers` | Число процессов при старте |
| `ServerLimit` | Верхняя граница числа процессов (жёсткий лимит; менять только до старта) |
| `ThreadsPerChild` | Число потоков на процесс |
| `MinSpareThreads` / `MaxSpareThreads` | Резерв простаивающих потоков |
| `MaxRequestWorkers` | `= ServerLimit × ThreadsPerChild` — максимум одновременных запросов |
| `MaxConnectionsPerChild` | Перезапуск воркера после N соединений (защита от утечек памяти, 0 = бесконечно) |
| `ListenBacklog` | Очередь входящих подключений (default 511) |

### Формула расчёта MaxRequestWorkers

1.  Определить пиковое число одновременных запросов (observability/Benchmark/наблюдение через `mod_status`).
2.  Целевая загрузка — **60–70 %** от `MaxRequestWorkers` (свободный запас на всплески).
3.  $\text{MaxRequestWorkers} = \text{PeakConcurrent} / 0{,}65$ (округлить вверх).
4.  Память: `event/worker` — на поток приходится малый статический объём + память на соединение; `prefork` — на процесс приходится вся память запроса (правило: оценить RSS процесса при средней нагрузке и умножить на MaxRequestWorkers).

**Правило для быстрого измерения:**
```bash
# Пиковое число воркеров из status (снимать в момент максимальной нагрузки)
curl -s http://localhost/server-status?auto | grep -E "BusyWorkers|IdleWorkers"
# → BusyWorkers: 812
# → IdleWorkers: 212

# RSS воркера (prefork) → память на процесс
ps -o rss=,cmd= --sort=-rss | grep httpd | head -3
```

**Пример для event:** пик 700 соединений → `MaxRequestWorkers = 700 / 0,65 ≈ 1077` → установить `ServerLimit 16` и `ThreadsPerChild 67` (или иные целые кратные), целевой `MaxRequestWorkers 1072`.

### Keep-Alive и таймауты

| Директива | По умолчанию | Рекомендация |
|---|---|---|
| `Timeout` | 60 | 30–60 для HTTP; больше для API/proxy |
| `KeepAlive` | On | On (снижает повторные handshake) |
| `MaxKeepAliveRequests` | 100 | 100–500 (больше полезных запросов на соединение) |
| `KeepAliveTimeout` | 5 | 2–5 (меньше — быстрее освобождение воркера) |
| `RequestReadTimeout` | — | Лимит на приём заголовков/тела (см. hardening) |

### Scoreboard (mod_status)

Состояния в scoreboard (`server-status`):

| Символ | Значение |
|---|---|
| `.` | Ожидание (idle) |
| `S` | Начало работы |
| `R` | Чтение запроса |
| `W` | Отправка ответа |
| `K` | Keep-Alive чтение |
| `D` | DNS-запрос |
| `C` | Закрытие соединения |
| `L` | Логирование |
| `G` | Graceful shutdown |
| `I` | Idle cleanup |
| `_` | Завершено/ожидает |

**Метрики `?auto`:**

```bash
curl -s "http://localhost/server-status?auto"
# → BusyWorkers: 812
# → IdleWorkers: 212
# → Scoreboard: ...
# → Total Accesses: 1234567
# → Total kBytes: ...
```

Эти значения читает `apache_exporter` (Prometheus) — метрики `apache_workers_busy`, `apache_workers_idle`, `apache_scoreboard_waiting` и др. (см. «См. также»).

**Интерпретация:** если `BusyWorkers` стабильно близко к `MaxRequestWorkers`, а в логах появляются `503 Resource temporarily unavailable` — пора увеличивать ёмкость или разносить нагрузку. Обратная картина (много IdleWorkers при низкой нагрузке) — признак избыточного резервирования.

**Доступ к `mod_status`/`mod_info` Для диагностики:**

```apacheconf
LoadModule status_module modules/mod_status.so
LoadModule info_module modules/mod_info.so

<Location /server-status>
    SetHandler server-status
    Require ip 127.0.0.1   # только локально или через trust-cidr
    ExtendedStatus On      # детальный статус каждого воркера (обязательно для mod_status)
</Location>

<Location /server-info>
    SetHandler server-info
    Require ip 127.0.0.1   # не публиковать наружу: раскрывает конфиг и модули
</Location>
```

`server-status?auto` — машинночитаемый вывод для `/metrics`/apache_exporter. `mod_info` (модуль включён обязательно только во время диагностики) позволяет понять, какие директики реально активны после слияния.

### TLS-производительность

**Кэширование сессий** — снижает задержку повторных handshake (аналогово Nginx `ssl_session_cache`):

```apacheconf
SSLSessionCache shmcb:/run/httpd/sslcache(512000)   # RHEL
# Debian: shmcb:/var/run/apache2/ssl_scache(512000)
SSLSessionCacheTimeout 300
SSLSessionTickets on      # session tickets (RFC 5077) — возобновление 0-RTT для TLS 1.3
```

Концепции 0-RTT/session tickets/OCSP stapling — см. [`tls_optimization.md`](../Concepts/web_performance/tls_optimization.md); здесь только Apache-директивы.

### HTTP/2

```apacheconf
Protocols h2 http/1.1
H2MaxSessionStreams 100        # максимум потоков на одно h2-соединение
H2MaxWorkers 64                # максимум обработчиков h2-запросов (воркеров на поток)
H2MinWorkers 1
# H2StreamMaxMemSize 65536     # защита от неограниченного буфера
```

*   HTTP/2 обязателен поверх TLS; `h2c` (без TLS) — только для внутреннего периметра.
*   Server Push **удалён** и не поддерживается браузерами — использовать `preload`/103 Early Hints. Концепции — см. [`http2_http3.md`](../Concepts/web_performance/http2_http3.md).

### Системные параметры

```apacheconf
EnableSendfile On     # отдавать статику через sendfile(2) (не для NFS!)
EnableMMAP On         # mmap статических файлов
```

Сетевой уровень (совместно с `ListenBacklog`):

```bash
sudo sysctl -w net.core.somaxconn=65535     # размер очереди accept (согласуется с ListenBacklog)
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=8192
sudo sysctl -w net.ipv4.tcp_fin_timeout=30
# (постоянно: /etc/sysctl.d/99-web.conf)
```

Компрессия `mod_deflate`/`mod_brotli` подробно описана в [`server_compression.md`](../Concepts/web_performance/server_compression.md) — не дублируется здесь.

---

## Практические сценарии

### 1. Базовый production-конфиг event MPM

```apacheconf
<IfModule mpm_event_module>
    StartServers            4
    ServerLimit             16
    MinSpareThreads         75
    MaxSpareThreads         150
    ThreadsPerChild         64
    MaxRequestWorkers       1024
    MaxConnectionsPerChild  10000
    ListenBacklog           1024
</IfModule>
```

### 2. Тюнинг под высокую нагрузку/долгие запросы

```apacheconf
# Долгие запросы (SSE, загрузка файлов) — увеличить таймауты, но ограничить воркеры
Timeout 120
ProxyTimeout 120
KeepAliveTimeout 5
MaxRequestWorkers 512        # не давать потокам утекать в долгие соединения
```

### 3. Проверка конфигурации и активных значений

```bash
apachectl -V | grep "Server MPM"
# → Server MPM: event

# Проверка достигнутых значений после reload (активные параметры MPM)
httpd -t -D DUMP_VHOSTS >/dev/null && echo "config OK"
# → config OK
```

---

## Операции и команды

| Команда | Назначение | Пример вывода |
|---|---|---|
| `curl -s "http://localhost/server-status?auto"` | Текущие воркеры и accesses | `BusyWorkers: 812` |
| `ab -n 1000 -c 50 http://localhost/` | Нагрузочный smoke-тест | `Requests per second: 5234` |
| `ps -o rss=,cmd= -C httpd \| sort -rn` | Память на воркер | `RSS 24532` |
| `ss -tnp \| grep:80 \| wc -l` | Количество соединений | `1340` |
| `openssl s_client -connect localhost:443` | Проверка handshake/сессий | `New, TLSv1.3` |
| `sudo systemctl reload httpd` | Применить изменения без разрыва | — |

**Проверка возобновления TLS-сессии:**
```bash
# Повторное соединение с reuse session id
openssl s_client -connect localhost:443 -reconnect 2>&1 | grep -c "Reused"
# → >0 (если кэш сессий работает)
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `503 Resource temporarily unavailable` | `BusyWorkers` достиг `MaxRequestWorkers` | Увеличить ёмкость; снизить `KeepAliveTimeout`; проверить бэкенды |
| «Падение» handshake (TLS) | Отсутствует/сброшен `SSLSessionCache` | Включить shmcb, проверить права на `/run` |
| Высокий RSS (prefork) | `prefork` держит всю память запроса | Перейти на `event`+PHP-FPM |
| Медленная отдача статики | `EnableSendfile On` на NFS/монтированиях | Выключить для таких ФС (`EnableSendfile Off` в `<Directory>`) |
| Много R/W-воркеров (>80 % всей Scoreboard) | Нехватка `ListenBacklog`/системной очереди | `ListenBacklog 1024` + `net.core.somaxconn` |
| Ожидание при `curl` (TTFB) | `ProxyTimeout`/`Timeout` мал для бэкенда | Согласовать таймауты с бэкендом |

---

## Лучшие практики

1.  Мониторинг: `mod_status` + `apache_exporter` (Prometheus) — алерты на `BusyWorkers ≈ MaxRequestWorkers` и 5xx.
2.  Расчёт ёмкости по формуле (пик ÷ 0,65) с запасом под всплески.
3.  Keep-Alive: сбалансированный `KeepAliveTimeout 5` и `MaxKeepAliveRequests ≥ 100`.
4.  TLS: shmcb-кэш сессий обязателен; `SSLHonorCipherOrder on`; минимум современных шифров.
5.  Менять MPM — только при остановленном сервисе (`systemctl reload` не меняет модель).
6.  Снимать метрики до/после изменений (`ab`, `wrk`) для объективной оценки.

---

## Дополнительная информация

### См. также

*   [Обзор Apache](./apache_overview.md) — MPM и базовый конфиг, HTTP/2, мониторинг.
*   [Оптимизация TLS для производительности](../Concepts/web_performance/tls_optimization.md) — OCSP, session tickets, 0-RTT (концепции).
*   [Экспортёры Prometheus для веб-серверов](../../Prometheus/Exporters/other_exporters.md) — `apache_exporter`, метрики scoreboard.
*   [Сжатие веб-контента](../Concepts/web_performance/server_compression.md) — mod_deflate/mod_brotli.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — гRPC, WebSocket, ProxyErrorOverride (совместимость с H2).
*   [Сборка из исходников](./apache-install-from-source.md) — тюнинг флагов компиляции (GCC, PGO) для больших нагрузок.