# Протоколы и потоки данных: gRPC, HTTP/2, HTTP/3, TCP, UDP

## Определения

**h2c** — HTTP/2 cleartext (без TLS), используется при общении Traefik с внутренним сервисом, который не умеет TLS.

**gRPC** — RPC-фреймворк поверх HTTP/2; Traefik проксирует его как обычный HTTP (специальный middleware не нужен).

**gRPC-Web** — надстройка для доступа к gRPC из браузеров; переводится настоящим middleware `grpcWeb`.

**PROXY protocol (TCP)** — передача реального IP клиента на L4, включается также при взаимодействии Traefik с бэкендом (через TCP ServersTransport).

**UDP-роутер** — «просто балансировщик» на уровне сессий (датаграммы одной сессии идут на один сервер), правил-матчеров для UDP нет.

## Базовые концепции

### gRPC и HTTP/2 в тракт

Traefik v3 проксирует gRPC нативно. Достаточно обычного HTTP-роутера; протокол определяется **схемой в адресе сервиса**:

| Схема в `servers[].url` | Что за транспорт к бэкенду |
| :--- | :--- |
| `http://` | HTTP/1.1 (по умолчанию) |
| `h2c://` | HTTP/2 без TLS (схема = cleartext) |
| `https://` | HTTP/2 над TLS (при включенном TLS на роутере и сертификате бэкенда) |

gRPC требует HTTP/2, поэтому для gRPC используются `h2c://` (внутренние сети) или `https://` (когда у бэкенда есть TLS-сертификат). Статус-коды gRPC передаются заголовком `grpc-status` (и именно им логирует Traefik).

Для браузеров поверх gRPC применяется middleware `grpcWeb` (единственный параметр — `allowOrigins`), который переводит gRPC-Web в настоящий gRPC перед отправкой в бэкенд.

### Client-side HTTP/2 и HTTP/3

- **HTTP/2 на entrypoint** включается неявно при TLS (ALPN `h2`); для cleartext-слушателя включайте опцию `http: { http2: true }` (или через `--entryPoints.<name>.http.http2=true`). Тонкая настройка: `http2.maxConcurrentStreams` (default 250).
- **HTTP/3 (QUIC)** включается на **TCP-слушателе** с опцией `http3`, требует открытого UDP-порта и ядра 4.19+.

```yaml
entryPoints:
  websecure:
    address: ":443"
    http3: {}
```

`http3.advertisedPort` задает скоростной UDP-порт, если публичный порт отличается от слушающего.

### WebSocket и SSE

WebSocket и SSE проксируются прозрачно (без специальных конфигов). Важно: middleware, ломающие стрим (например, `buffering`), отключают upgrade-механику. Для SSE-потоков исключайте `compress`/`buffering` (см. [Middleware для управления трафиком](./traefik-middlewares-traffic.md)).

### TCP

TCP-роутеры способны маршрутизировать произвольный L4-трафик (PostgreSQL, SSH, SMTP, Redis) по `HostSNI` и/или `ClientIP`. TCP-сервис поддерживает health check на уровне соединения (успешный TCP-connect = healthy; при необходимости — обменом пейлоадом `send`/`expect`).

Реальный IP клиента в TCP-режиме передается PROXY protocol — на TCP-слушателе Traefik (входящий трафик) или при соединении с бэкендом (внутри TCP ServersTransport через `proxyProtocol.version`).

### UDP

UDP-роутеры не имеют правил: только `entryPoints` (опционально, по умолчанию все UDP-слушатели) и сервис. Сессионно-привязка: пакеты одной UDP-"сессии" направляются на один бэкенд. Таймаут холостой сессии задается в статике: `entryPoints.<name>.udp.timeout` (default 3s). Healthcheck для UDP-сервисов в v3 отсутствует.

## Практические сценарии

### Сценарий 1: gRPC (h2c)

```yaml
http:
  routers:
    grpc-router:
      rule: "Host(`grpc.example.com`)"
      service: grpc-service
      entryPoints: [websecure]
      tls: {}
  services:
    grpc-service:
      loadBalancer:
        servers:
          - url: "h2c://grpc-backend:50051"
```

### Сценарий 2: gRPC с TLS между Traefik и бэкендом

```yaml
http:
  services:
    grpc-tls-service:
      loadBalancer:
        serversTransport: grpc-transport
        servers:
          - url: "https://grpc-backend:8443"
  serversTransports:
    grpc-transport:
      rootCAs:
        - /etc/traefik/backend-ca.crt
```

### Сценарий 3: gRPC-Web (браузерные клиенты)

```yaml
http:
  routers:
    grpcweb-router:
      rule: "Host(`gw.example.com`) && PathPrefix(`/grpc`)"
      service: grpc-service
      entryPoints: [websecure]
      tls: {}
      middlewares:
        - grpc-web
  middlewares:
    grpc-web:
      grpcWeb:
        allowOrigins:
          - "https://app.example.com"
```

### Сценарий 4: TCP-сервис PostgreSQL с health check

```yaml
tcp:
  routers:
    pg-router:
      rule: "HostSNI(`db.example.com`)"
      service: pg-service
      entryPoints: [postgres]
      tls:
        passthrough: true
  services:
    pg-service:
      loadBalancer:
        servers:
          - address: "10.0.0.10:5432"
        healthCheck:
          send: "SELECT 1;"
          interval: "10s"
          timeout: "3s"
```

### Сценарий 5: UDP (например, DNS/DOH-forward)

```yaml
udp:
  routers:
    dns-router:
      entryPoints: [dns-udp]
      service: dns-service
  services:
    dns-service:
      loadBalancer:
        servers:
          - address: "10.0.0.20:53"
```

Статическая часть:

```yaml
entryPoints:
  dns-udp:
    address: ":53/udp"
    udp:
      timeout: 5s
```

### Production паттерны TCP/UDP

**TCP: PostgreSQL с TLS passthrough:**

```yaml
tcp:
  routers:
    pg:
      rule: "HostSNI(`db.example.com`)"
      service: pg-service
      entryPoints: [postgres]
      tls:
        passthrough: true
  services:
    pg-service:
      loadBalancer:
        healthCheck:
          send: "SELECT 1;"
          interval: "10s"
          timeout: "3s"
        servers:
        - address: "10.0.0.10:5432"
```

**TCP: Redis с TLS:**

```yaml
tcp:
  routers:
    redis:
      rule: "HostSNI(`redis.example.com`)"
      service: redis-service
      entryPoints: [redis]
      tls:
        passthrough: true
  services:
    redis-service:
      loadBalancer:
        healthCheck:
          send: "PING\r\n"
          expect: "PONG"
          interval: "5s"
          timeout: "2s"
        servers:
        - address: "10.0.0.20:6379"
```

**UDP: DNS с несколькими серверами:**

```yaml
udp:
  routers:
    dns:
      entryPoints: [dns-udp]
      service: dns-service
  services:
    dns-service:
      loadBalancer:
        servers:
        - address: "10.0.0.30:53"
        - address: "10.0.0.31:53"
```

**UDP: Session affinity для DoH:**

```yaml
entryPoints:
  doh-udp:
    address: ":8053/udp"
    udp:
      timeout: 3s
```

## Операции и команды

```bash
# Проверка HTTP/2 на клиенте
curl -sI https://app.example.com/ -o /dev/null -w '%{http_version}\n'

# Проверка h2c к gRPC-бэкенду
grpcurl -plaintext grpc-backend:50051 list

# Состояние TCP-роутеров через API
curl -s http://localhost:8080/api/tcp/routers | jq '.[] | {name, rule, service}'
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **gRPC-клиент получает `Unimplemented`/EOF** | Бэкенд слушает HTTP/1.1 или схема не `h2c://`/`https://` | Исправьте схему сервиса; проверьте ALPN бэкенда |
| **HTTP/2 не согласуется** | Нет TLS/ALPN или `http2` не включен на cleartext-роутере | Включите `http: { http2: true }` |
| **UDP-запросы уходят на разные бэкенды** | Таймаут сессии маленький/потеря клиентского IP | Увеличьте `udp.timeout`, включите PROXY protocol |
| **TCP health check бьет по бэкенду лишним трафиком** | Слишком частые интервалы | Увеличьте `interval`, настройте `send`/`expect` |
| **WebSocket рвется** | `buffering`/`compress` стоит в цепочке | Исключите стриминговые middleware на потоковых путях |

## Рекомендации

- Для gRPC в закрытом контуре используйте `h2c://`; для произвольного доверия — TLS между Traefik и бэкеном (`https://` + `serversTransport.rootCAs`).
- HTTP/3 включайте только на роутеры с реальной клиентской базой — он требует сопутствующих UDP-портов и тюнинга сети.
- TCP health check с `send`/`expect` — единственный способ проверить «логическую» доступность протокола поверх TCP.
- В UDP-контурах обязательно решайте вопрос реального IP клиента (PROXY protocol) до авторизации/лимитов.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — роутеры, сервисы, PROXY protocol в общих чертах.
- [TLS Options и mTLS](./traefik-tls-options.md) — TLS termination/passthrough на TCP.
- [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md) — IP клиента на L7.
- [gRPC (обзор)](../../Networking/ServicesAndTools/grpc_overview.md) — глобальная картина gRPC.