# Upstream Keepalive и Connection Pooling для веб-производительности

## Определения

**Keepalive Connection Pool** — пул долгоживущих HTTP/1.1 соединений между прокси (Nginx/Angie) и бэкендом, сохраняемых в открытом состоянии между запросами для повторного использования. Каждый пул создаётся на одного воркера прокси и изолирован от других воркеров.

**Keepalive Timeout** — время ожидания запроса на уже установленном соединении перед принудительным закрытием. По протоколу HTTP/1.1 keepalive включён по умолчанию, но прокси должен явно указать его через `Connection: keep-alive` или очистить заголовок `Connection`.

**Connection Migration** — в контексте HTTP/3 (QUIC) способность соединения сохраняться при смене клиентом сети (Wi-Fi → LTE). В upstream-пуле Nginx/Angie connection migration не применим, так как прокси управляет только своей стороны соединения.

**Time Wait (TIME_WAIT)** — состояние завершённого TCP-соединения, в котором оно ожидает истечения 2MSL (Maximum Segment Lifetime). На прокси с большим числом исходящих соединений TIME_WAIT может исчерпать ephemereal порты, если `tcp_tw_reuse` отключён.

**Origin Latency** — время ответа бэкенда, измеренное прокси. Включает обработку запроса приложением, доступ к БД и сетевую задержку между прокси и бэкендом. Keepalive напрямую сокращает Origin Latency за счёт исключения TCP и TLS хендшейка.

**Reuse Ratio** — доля запросов, обслуженных по уже открытому keepalive-соединению. Рассчитывается как `1 - (новые соединения / общее число запросов)`. Целевое значение >95% для высоконагруженных прокси.

## Основные концепции

### Зачем keepalive критичен для веб-производительности

Каждый новый запрос к бэкенду без keepalive проходит через:

1. TCP Handshake (1 RTT)
2. TLS Handshake (1-2 RTT для TLS 1.3, 2-3 RTT для TLS 1.2)
3. HTTP Request/Response

С keepalive шаги 1 и 2 исключаются для повторных запросов. На высоконагруженных прокси это экономит 20-100 мс на каждый запрос и снижает нагрузку на CPU бэкенда и прокси.

### Архитектура пула

```
Воркер прокси (Nginx/Angie)
├── Keepalive Connection 1 → бэкенд:8080 (idle)
├── Keepalive Connection 2 → бэкенд:8080 (active)
├── Keepalive Connection 3 → бэкенд:8080 (idle)
└── ... (limit: keepalive N)
```

Каждый воркер держит свой пул. При `keepalive 16` в конфигурации максимальное число idle-соединений с одним бэкендом — 16 на воркер. При 4 воркерах общий лимит — 64 idle-соединения.

### Директивы конфигурации

| Директива | Контекст | Назначение | Значение по умолчанию |
| :--- | :--- | :--- | :--- |
| `keepalive` | `upstream` | Максимальное число idle-соединений в пуле на воркер | (не активирован) |
| `keepalive_requests` | `http`, `server`, `location` | Максимальное число запросов через одно соединение | `1000` |
| `keepalive_time` | `http`, `server`, `location` | Максимальное время жизни соединения в пуле | `1h` |
| `keepalive_timeout` | `http`, `server`, `location` | Время ожидания запроса перед закрытием idle-соединения | `60s` |

### Обязательные заголовки для работы keepalive

По умолчанию Nginx/Angie использует HTTP/1.0 с заголовком `Connection: close`. Для активации keepalive необходимо:

```nginx
location / {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

Заголовок `Connection ""` очищает значение, позволяя бэкенду и прокси использовать HTTP/1.1 keepalive.

### Влияние на Core Web Vitals

| Метрика | Влияние keepalive | Объяснение |
| :--- | :--- | :--- |
| **LCP** | Прямое | Снижение TTFB за счёт исключения TCP/TLS хендшейка для повторных запросов к бэкенду. Эффект: 20-100 мс на запрос. |
| **INP** | Прямое | Меньше времени на установку соединения = быстрее первый байт ответа на действия пользователя, требующие обращения к бэкенду. |
| **CLS** | Косвенное | При стабильном TTFB меньше вероятности появления динамического контента с задержкой, вызывающего сдвиги макета. |

### Ограничения и edge cases

1. **Изоляция по воркерам:** `keepalive 32` не означает 32 глобальных idle-соединения. При 4 воркерах общий лимит — 128.
2. **Матчинг по адресу:** idle-соединения матчатся с серверами по IP:порту. При использовании `resolve` или динамическом удалении сервера cached-соединения не закрываются — они занимают слоты до истечения `keepalive_timeout`.
3. **TIME_WAIT на прокси:** При очень высоком RPS прокси может исчерпать ephemereal порты. Решение: `tcp_tw_reuse = 1` в sysctl.
4. **Совместимость с бэкендом:** Не все бэкенды корректно поддерживают keepalive. При проблемах (502/504) проверяйте логи бэкенда на предмет закрытых соединений.

## Практические сценарии

### Сценарий 1: Базовая конфигурация keepalive для высоконагруженного API

```nginx
upstream api_backend {
    zone api_backend 64k;
    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;

    keepalive 32;
}

server {
    listen 443 ssl http2;

    location /api/ {
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Tune для high-load
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
}
```

**Валидация:**
```bash
# Проверка, что соединения переиспользуются
curl -s -o /dev/null -w "%{time_starttransfer}s\n" https://example.com/api/data
# → 0.045s (первый запрос, хендшейк)

curl -s -o /dev/null -w "%{time_starttransfer}s\n" https://example.com/api/data
# → 0.012s (повторный запрос, keepalive)
```

### Сценарий 2: Мониторинг эффективности пула через Status API (Angie)

```bash
# Проверка keepalive-соединений для upstream
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '{
    peers: [.peers[] | {server, keepalive, selected: .selected.current}],
    total_keepalive: .keepalive
}'
# → {
# →   "peers": [
# →     {"server": "10.0.0.1:8080", "keepalive": 28, "selected": 4},
# →     {"server": "10.0.0.2:8080", "keepalive": 31, "selected": 2}
# →   ],
# →   "total_keepalive": 59
# → }
```

**Индикаторы проблем:**
- `keepalive = 0` на всех пирах при наличии `keepalive N` — соединения не кэшируются (проверьте `proxy_http_version 1.1` и `proxy_set_header Connection ""`).
- `keepalive` близок к `keepalive` в конфигурации — пул работает эффективно.
- `selected.current` растёт, а `keepalive` падает — возможно, `keepalive_timeout` слишком короткий.

### Сценарий 3: Диагностика проблемы TIME_WAIT exhaustion

```bash
# Подсчёт соединений в TIME_WAIT
ss -s
# → 4521 time-wait

# Проверка дропов в слушателе
nstat -az | grep -E "ListenOverflows|ListenDrops"
# → TcpExtListenOverflows 89
# → TcpExtListenDrops 45
```

**Решение:**
```bash
# Включение reuse TIME_WAIT
echo 'net.ipv4.tcp_tw_reuse = 1' >> /etc/sysctl.d/99-web-performance.conf
sysctl --system

# Расширение диапазона эфемерных портов
echo 'net.ipv4.ip_local_port_range = 1024 65535' >> /etc/sysctl.d/99-web-performance.conf
sysctl --system
```

### Сценарий 4: Tuning keepalive для gRPC/WebSocket бэкендов

Для долгоживущих соединений (gRPC streams, WebSocket) стандартный `keepalive_timeout 60s` может закрывать активные соединения prematurely.

```nginx
upstream grpc_backend {
    zone grpc_backend 64k;
    server 10.0.0.1:50051;

    keepalive 16;
    keepalive_time 10m;    # Увеличить время жизни
    keepalive_timeout 120s; # Увеличить timeout для long-poll
}
```

## Операции и команды

### Проверка active соединений

```bash
# Активные и idle соединения
ss -tnp | grep :8080 | wc -l
# → 59 (активные + idle)

# Соединения в TIME_WAIT
ss -s | grep time-wait
# → 4521 time-wait

# Дропы в слушателе
nstat -az | grep -E "ListenOverflows|ListenDrops"
# → TcpExtListenOverflows 89
# → TcpExtListenDrops 45
```

### Stress-test keepalive pool

```bash
# wrk с поддержкой HTTP/2 и keepalive
wrk -t4 -c100 -d30s https://example.com/api/data
# → Requests/sec: 45678.90

# Проверка, что соединения переиспользуются
ss -tnp | grep nginx | wc -l
# → Должно быть стабильно, без роста новых соединений
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Keepalive не работает** | TTFB растёт на 20-100 мс, новые соединения в логах | `ss -tnp` — нет idle соединений; `curl -v` — `Connection: close` | Проверить `proxy_http_version 1.1` и `proxy_set_header Connection ""` |
| **TIME_WAIT exhaustion** | `nstat -az | grep -E ListenOverflows` растёт | `ss -s | grep time-wait` — тысячи TIME_WAIT | `tcp_tw_reuse = 1`, расширить `ip_local_port_range` |
| **Premature connection close** | 502/504 при долгих запросах | Логи бэкенда: `Connection reset by peer` | Увеличить `keepalive_time` и `keepalive_timeout` |
| **Pool saturation** | Высокий P95 latency при пиковых нагрузках | `keepalive` в Status API = лимиту | Увеличить `keepalive` или добавить бэкенды |
| **Stale connections в пуле** | Рост 5xx ошибок после деплоя бэкенда | `keepalive` не падает после reload | Уменьшить `keepalive_time` или использовать `max_fails` + `fail_timeout` |

## Рекомендации

### Базовые правила

1. **Всегда включайте keepalive для проксирования:** `proxy_http_version 1.1;` + `proxy_set_header Connection "";`
2. **Начинайте с `keepalive 32` на воркер:** При 4 воркерах это даёт 128 idle-соединений, достаточно для большинства high-load прокси.
3. **Tune `keepalive_timeout` под тип трафика:** 60s для обычного API, 120s для gRPC/WebSocket.
4. **Мониторьте Reuse Ratio:** `1 - (новые соединения / общее число запросов)`. Цель >95%.
5. **Включите `tcp_tw_reuse = 1` на прокси:** Исключает пор exhaustion при высоком RPS.
6. **Используйте `max_fails` + `fail_timeout`:** Автоматически исключает unhealthy-бэкенды из пула.

### Для DevOps/SRE/SysAdmin

- **Мониторинг пула:** Отслеживайте `keepalive` в Status API (Angie) или через `ss -tnp`. Алерт при `keepalive = 0` на всех пирах.
- **Корреляция с TTFB:** Сопоставляйте рост TTFB с падением Reuse Ratio. Если Reuse Ratio <90%, вероятна проблема с keepalive.
- **Capacity Planning:** При росте RPS увеличивайте `keepalive` или добавляйте бэкенды. Мониторьте `selected.current` в upstream.
- **Graceful deployment:** При деплое бэкендов уменьшите `keepalive_time` на 5-10 минут до деплоя, чтобы старые соединения закрылись быстрее.

## Дополнительная информация

### См. также

- [Обзор кэширования в Nginx/Angie](./caching.md) — как кэширование работает совместно с keepalive.
- [Оптимизация TLS для производительности](./tls_optimization.md) — как keepalive взаимодействует с TLS session resumption.
- [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — connection pooling в QUIC.
- [Оптимизация веб-серверов Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md) — детальный тюнинг keepalive.
- [Мониторинг Angie через API](../../WebServers/Angie/angie_monitoring/angie_monitoring_api.md) — отслеживание keepalive пула в реальном времени.

### RFC и спецификации

- **RFC 7230** — HTTP/1.1: keepalive по умолчанию, заголовок `Connection`.
- **RFC 7540** — HTTP/2: connection pooling не требуется (один мультиплексированный поток).
- **RFC 9000** — QUIC: connection migration вместо keepalive.
