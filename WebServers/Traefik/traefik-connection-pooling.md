# Connection Pooling, Keep-Alive и File Descriptors в Traefik

## Определения

**Connection pool** — набор переиспользуемых TCP-соединений к бэкенду, уменьшающий накладные расходы на TLS handshake и TCP установку.

**Keep-alive** — механизм удержания соединения открытым после завершения запроса для повторного использования.

**maxIdleConnsPerHost** — максимальное количество idle соединений в пуле на один бэкенд.

**maxIdleConns** — глобальный лимит idle соединений на все бэкенды.

**keepAliveMaxRequests** — максимальное количество запросов через одно соединение, после которого оно закрывается.

**keepAliveMaxTime** — максимальное время жизни соединения в пуле.

**File descriptor (FD)** — дескриптор открытого файла/сокета в Linux. Каждое соединение потребляет один FD.

**LimitNOFILE** — лимит открытых файловых дескрипторов для процесса в systemd.

**HTTP/2 connection limit** — максимальное количество multiplexed streams на одном HTTP/2 соединении.

## Базовые концепции

### Как Traefik управляет соединениями

Traefik использует стандартный Go `net/http` transport с следующими ключевыми параметрами:

```yaml
serversTransport:
  maxIdleConnsPerHost: 200      # пул на бэкенд
  maxIdleConns: 0               # глобальный пул (0 = без лимита)
  forwardingTimeouts:
    dialTimeout: 30s
    responseHeaderTimeout: 0s   # 0 = без лимита (опасно!)
    idleConnTimeout: 90s
```

### Connection pool exhaustion

При высокой нагрузке Traefik может исчерпать:
1. **Локальный пул на бэкенд** (`maxIdleConnsPerHost`) — новые запросы открывают новые соединения
2. **Глобальный пул** (`maxIdleConns`) — распределение между бэкендами
3. **File descriptors** (`LimitNOFILE`) — каждое соединение = 1 FD

Симптомы exhaustion:
- Рост latency (открытие новых соединений)
- Ошибки `too many open files`
- Рост ephemeral ports на бэкенде

### HTTP/2 connection limits

HTTP/2 multiplexes множественные streams на одном соединении:

```yaml
entryPoints:
  websecure:
    http2:
      maxConcurrentStreams: 250   # параллельные streams на соединение
```

Рекомендации:
- `maxConcurrentStreams`: 100-250 (default 250)
- `keepAliveMaxRequests`: 1000-10000 (закрыть соединение после N запросов)
- `keepAliveMaxTime`: 5m (максимальное время жизни соединения)

### File Descriptor Limits

Linux лимиты:
- **Soft limit** (`ulimit -n`) — текущий лимит, можно увеличить до hard
- **Hard limit** (`ulimit -Hn`) — максимальный возможный soft limit
- **systemd LimitNOFILE** — переопределяет для сервиса

Проверка:

```bash
# Текущий лимит процесса
cat /proc/$(pgrep -f traefik)/limits | grep 'Max open files'
# → Max open files            65536                65536                files

# systemd лимит
systemctl show traefik | grep LimitNOFILE
# → LimitNOFILE=65536
```

### Sizing connection pools

Формула для sizing:

```
total_connections = (requests_per_second * average_latency_seconds) + safety_margin

maxIdleConnsPerHost = total_connections / number_of_backends
maxIdleConns = total_connections
LimitNOFILE = maxIdleConns + overhead_for_other_sockets
```

Пример:
- 1000 RPS, latency 100ms = 100 одновременных соединений
- 4 бэкенда = 25 на бэкенд
- С запасом: `maxIdleConnsPerHost: 50`, `maxIdleConns: 200`
- `LimitNOFILE: 65536` (с запасом)

## Практические сценарии

### Сценарий 1: Базовая конфигурация для production

```yaml
serversTransport:
  maxIdleConnsPerHost: 200
  maxIdleConns: 0  # без глобального лимита
  forwardingTimeouts:
    dialTimeout: 30s
    responseHeaderTimeout: 30s  # важно: не 0!
    idleConnTimeout: 90s

entryPoints:
  websecure:
    address: ":443"
    transport:
      lifeCycle:
        requestAcceptGraceTimeout: 5s
        graceTimeout: 30s
      keepAliveMaxRequests: 1000
      keepAliveMaxTime: 5m
    http2:
      maxConcurrentStreams: 250
```

### Сценарий 2: systemd с увеличенными лимитами

```ini
# /etc/systemd/system/traefik.service
[Service]
Type=simple
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml

# File descriptors
LimitNOFILE=65536
LimitNPROC=10000

# Memory
LimitMEMLOCK=infinity

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik /var/log/traefik

[Install]
WantedBy=multi-user.target
```

Применение:

```bash
sudo systemctl daemon-reload
sudo systemctl restart traefik
sudo systemctl status traefik | grep LimitNOFILE
# → LimitNOFILE=65536
```

### Сценарий 3: Docker Compose с лимитами

```yaml
services:
  traefik:
    image: traefik:v3.4
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
    environment:
      GOMAXPROCS: "2"    # соответствует CPU лимиту
```

### Сценарий 4: Monitoring file descriptors

```bash
# Проверка текущего использования FD
ls /proc/$(pgrep -f traefik)/fd | wc -l
# → 1234

# Проверка лимита
cat /proc/$(pgrep -f traefik)/limits | grep 'Max open files'
# → Max open files            65536                65536                files

# Мониторинг через Prometheus (если установлен)
curl -s localhost:9100/metrics | grep traefik_open_connections
# → traefik_entrypoint_open_connections{entrypoint="websecure"} 42
```

### Сценарий 5: HTTP/2 tuning для высоконагруженных сред

```yaml
entryPoints:
  websecure:
    address: ":443"
    http2:
      maxConcurrentStreams: 100    # снизить для защиты бэкендов
      # maxConcurrentStreamsPerConnection: 100  # v3.4+

transport:
  respondingTimeouts:
    readTimeout: 30s
    writeTimeout: 30s
    idleTimeout: 180s
  keepAliveMaxRequests: 5000        # закрыть соединение после 5000 запросов
  keepAliveMaxTime: 10m             # или через 10 минут
```

### Сценарий 6: GOMAXPROCS в контейнере

```yaml
services:
  traefik:
    image: traefik:v3.4
    deploy:
      resources:
        limits:
          cpus: '1.5'
    environment:
      GOMAXPROCS: "2"    # ceil(CPU limit) или exact
```

Проверка:

```bash
docker exec traefik cat /proc/1/limits | grep 'Max open files'
# → Max open files            65536                65536                files
```

## Операции и команды

```bash
# Проверка открытых соединений
ss -tnp | grep traefik | wc -l
# → 42

# Проверка FD usage
ls /proc/$(pgrep -f traefik)/fd | wc -l
# → 1234

# Проверка лимитов
cat /proc/$(pgrep -f traefik)/limits | grep 'Max open files'

# Systemd лимит
systemctl show traefik | grep -E 'LimitNOFILE|LimitNPROC'

# Мониторинг метрик
curl -s localhost:9100/metrics | grep -E 'traefik_entrypoint_open_connections|traefik_service_open_connections'

# Проверка HTTP/2 соединений
curl -sI https://app.example.com/ -o /dev/null -w '%{http_version}\n'
# → HTTP/2

# Проверка keep-alive
curl -sv https://app.example.com/ 2>&1 | grep -i 'connection'
# → Connection: keep-alive

# Проверка GOMAXPROCS
cat /proc/$(pgrep -f traefik)/environ | tr '\0' '\n' | grep GOMAXPROCS
# → GOMAXPROCS=2
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`too many open files`** | `LimitNOFILE` исчерпан | Увеличьте `LimitNOFILE` в systemd или `ulimit` в Docker |
| **Высокая latency при нагрузке** | `maxIdleConnsPerHost` исчерпан, новые соединения открываются | Увеличьте пул, проверьте keep-alive |
| **Много TIME_WAIT соединений** | `keepAliveMaxRequests` слишком высокий, соединения не переиспользуются | Уменьшите `keepAliveMaxRequests` |
| **HTTP/2 streams зависают** | `maxConcurrentStreams` слишком высокий | Снизьте до 100-150 |
| **FD растет бесконтрольно** | Утечка соединений (плагин, middleware) | pprof heap/goroutine dump |
| **GOMAXPROCS не соответствует CPU** | В контейнере с лимитом 1 CPU, GOMAXPROCS=8 | Установите GOMAXPROCS по CPU лимиту |
| **Connection refused на бэкенд** | `maxIdleConnsPerHost` исчерпан, новые соединения не открываются | Увеличьте пул, проверьте лимиты бэкенда |

## Рекомендации

- `LimitNOFILE`: минимум 65536 для production
- `maxIdleConnsPerHost`: 100-200 (зависит от нагрузки)
- `responseHeaderTimeout`: всегда указывайте (не 0) для production
- `keepAliveMaxRequests`: 1000-10000 (защита от несбалансированных соединений)
- `keepAliveMaxTime`: 5-10m
- `GOMAXPROCS` = CPU limit в контейнере
- Мониторьте `traefik_entrypoint_open_connections` и `traefik_service_open_connections`
- Мониторьте FD usage: алерт если > 80% от лимита
- Для HTTP/2: `maxConcurrentStreams` 100-250

## Дополнительная информация

- [Отладка и производительность Traefik](./traefik-debugging-performance.md) — таймауты, pprof, GOMAXPROCS
- [Traefik на bare-metal](./traefik-bare-metal.md) — systemd, LimitNOFILE
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — deploy ресурсы
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — HTTP/2, gRPC draining
