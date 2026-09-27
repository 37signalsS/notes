# Балансировка нагрузки HTTP

## Определения

**Балансировка нагрузки (Load Balancing)** — распределение входящего трафика между несколькими серверами (backends) для повышения отказоустойчивости, масштабируемости и производительности. В контексте HTTP балансировка происходит на **L7 (Application Layer)** и использует семантику HTTP-запросов (URI, заголовки, cookies) для принятия решений о маршрутизации.

**Health Check (Проверка здоровья)** — активный или пассивный механизм определения работоспособности бэкенда. Активные checks: балансировщик периодически опрашивает бэкенд (например, `GET /healthz`). Пассивные checks: анализ ошибок в реальном трафике (5xx, таймауты).

**Session Affinity (Sticky Sessions)** — механизм привязки сессии клиента к конкретному бэкенду. Используется, когда состояние хранится в локальной памяти сервера (in-memory session).

**Graceful Shutdown (Бережное отключение)** — процесс остановки бэкенда, при котором текущие запросы завершаются, а новые перенаправляются на другие бэкенды.

**Connection Draining** — процесс «вытекания» соединений при отключении бэкенда из пула. Балансировщик перестаёт направлять новые соединения, но ждёт завершения текущих.

## Основные концепции

### Алгоритмы балансировки

| Алгоритм | Лучший сценарий | Недостатки |
| :--- | :--- | :--- |
| **Round-robin** | Бэкенды с одинаковой производительностью | Игнорирует текущую нагрузку на сервер |
| **Weighted round-robin** | Разнородные бэкенды (разная мощность) | Требует ручной настройки весов |
| **Least-conn** | Долгие соединения (WebSocket, gRPC streaming) | Менее эффективен для коротких запросов |
| **Least-time** (HAProxy) | Минимальная задержка + минимальные соединения | Доступен только в HAProxy Enterprise и community v2.2+ |
| **IP-hash** | Sticky sessions без cookie | Неравномерное распределение при асимметричном трафике |
| **URL-hash** | Кэширующие прокси (один URL → один бэкенд) | При падении бэкенда его часть кэша недоступна |
| **Random** | Простая и равномерная балансировка | Нет sticky sessions |
| **Consistent Hashing** | Кэширующие прокси, stateful-сервисы | Неравномерная нагрузка при small pool |

### Consistent Hashing: алгоритм

**Consistent Hashing** — алгоритм хэширования, при котором добавление/удаление элемента из пула влияет только на邻接ные элементы (minimizes key remapping). Используется в CDN (кэш-серверы), распределённых базах данных (sharding), и load balancers (sticky sessions без state).

**Проблема простого хэширования:** При добавлении/удалении сервера из пула, хэш-пространство перемешивается, и большинство запросов перенаправляется на другие серверы (кэш-промах). Consistent hashing решает это через virtual nodes.

```text
                 Consistent Hash Ring (160 бит)
                          ┌─────────┐
                          │  0      │
                     ┌────┤ Server1 ├────┐
                     │    │ hash=15 │    │
                     │    └─────────┘    │
               ┌─────┤                   ├─────┐
               │     │                   │     │
          ┌────┴───┐ │                   │ ┌───┴────┐
          │Server3 │ │                   │ │Server2 │
          │hash=120│ │                   │ │hash=60 │
          └────────┘ │                   │ └────────┘
                     │    ┌─────────┐    │
                     │    │ Virtual │    │
                     │    │ Nodes   │    │
                     └────┤ (Vnodes)├────┘
                          └─────────┘

Запрос с hash=50 → Server2 (ближайший clockwise)
Запрос с hash=100 → Server3 (ближайший clockwise)
```

**Virtual Nodes (Vnodes):** Каждый физический сервер представляется несколькими "виртуальными нодами" на ring. Это обеспечивает равномерное распределение при малом количестве серверов.

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| **K (replicas)** | Количество виртуальных нод на сервер | 100-200 (больше = равномернее) |
| **Hash function** | Алгоритм хэширования | MurmurHash3, xxHash |
| **Ring size** | Размер хэш-кольца | 2^32 (4 млрд значений) |

**Когда использовать:**
- Кэширующие прокси (один URL → один backend, для максимизации hit rate)
- Распределённые KeyValue-хранилища (sharding)
- WebSocket (sticky sessions по session ID)
- gRPC streaming (привязка клиента к потоку)

**Когда НЕ использовать:**
- Stateless HTTP (лучше round-robin или least-conn)
- Малый пул backend (<5 серверов, нестабильное распределение)
- Ситуации, где важна равномерная нагрузка (не кэш)

**Реализация:**
- **Nginx:** `hash $request_uri consistent;` в блоке `upstream`
- **HAProxy:** `balance uri` (isto как consistent hash по URI)
- **Envoy:** `RING_HASH` load balancing policy

### Типы health checks

| Тип | Описание | Параметры |
| :--- | :--- | :--- |
| **TCP check** | Проверка открытого порта (SYN/ACK) | `check port 8080` |
| **HTTP check** | Проверка HTTP-ответа (код, тело) | `option httpchk GET /healthz` |
| **SSL check** | Проверка валидности сертификата | `ssl-check` (HAProxy) |
| **Ping check** | ICMP ping (редко, ненадёжно) | `check` с `inter` |

### Параметры health checks

| Параметр | Назначение | Значение |
| :--- | :--- | :--- |
| `inter` | Интервал проверок | `2s`–`10s` |
| `rise` | Количество успешных проверок для `UP` | `2`–`3` |
| `fall` | Количество неудачных проверок для `DOWN` | `2`–`3` |
| `timeout` | Таймаут одной проверки | `2s`–`5s` |
| `port` | Порт для TCP-проверки | `8080` |
| `uri` | URI для HTTP-проверки | `/healthz` |
| `method` | HTTP-метод | `GET`, `POST` |

### Привязка сессий (Session Affinity / Sticky Sessions)

| Метод | Механизм | Инструменты |
| :--- | :--- | :--- |
| **Source IP** | Хэш от IP клиента | Nginx `ip_hash`, HAProxy `balance source` |
| **Cookie-based** | Балансировщик устанавливает cookie | HAProxy `cookie SERVERID insert` |
| **URL-based** | Хэш от URL или path | HAProxy `balance uri`, Nginx `hash $request_uri` |
| **Header-based** | Хэш от заголовка (API key, JWT) | HAProxy `balance hdr(Auth-Token)` |

### Graceful shutdown (бережное отключение)

Последовательность graceful shutdown:

1. **Stop accepting new connections:** Приложение перестаёт принимать новые соединения (обычно через pre-stop hook или SIGTERM handler).
2. **Drain existing connections:** Балансировщик завершает `health check` до `DOWN`, перестаёт направлять новые запросы.
3. **Wait for active requests:** Приложение дожидается завершения текущих запросов (обычно 10–30 секунд).
4. **Kill remaining:** Принудительное завершение (`SIGKILL`) неоконченных соединений после таймаута.

## Практические сценарии

### Сценарий 1: Weighted round-robin в Nginx

Разные мощности бэкендов (2xCPU и 4xCPU):

```nginx
upstream api_backend {
    server 10.0.1.10:8080 weight=1;
    server 10.0.1.11:8080 weight=2;
    keepalive 32;
}
```

**Валидация:**
- `for i in $(seq 1 100); do curl -s http://localhost/api/host; done | sort | uniq -c` — соотношение запросов ~1:2.

### Сценарий 2: HAProxy с HTTP health checks и fall

Активные проверки `/healthz` каждые 3 секунды, `fall=3`:

```haproxy
backend api_servers
    balance roundrobin
    option httpchk GET /healthz HTTP/1.0\r\n\r\n
    http-check expect status 200

    server app1 10.0.1.10:8080 check inter 3s rise 2 fall 3
    server app2 10.0.1.11:8080 check inter 3s rise 2 fall 3
    server app3 10.0.1.12:8080 check inter 3s rise 2 fall 3
```

**Валидация:**
- `echo "show stat" | socat /var/run/haproxy.sock stdio | grep api_servers` — `status` = `UP`/`DOWN`.
- `watch -n1 'echo "show stat" | socat /var/run/haproxy.sock stdio | grep api_servers'` — при остановке бэкенда статус меняется через ~9 секунд (`3 проверки × 3 секунды`).

### Сценарий 3: Cookie-based sticky sessions в HAProxy

Сессии привязываются через cookie `SERVERID`:

```haproxy
backend app_servers
    balance roundrobin
    cookie SERVERID insert indirect nocache

    server app1 10.0.1.10:8080 check cookie app1
    server app2 10.0.1.11:8080 check cookie app2
```

**Валидация:**
- `curl -I http://haproxy/app` — заголовок `Set-Cookie: SERVERID=app1` присутствует.
- Повторный запрос с cookie: `curl --cookie "SERVERID=app1" http://haproxy/app` — попадает на `app1`.

### Сценарий 4: URL-hash для кэширующего прокси

Один и тот же URL всегда идёт на один бэкенд (повышение Cache Hit Ratio):

```haproxy
backend cache_servers
    balance uri
    hash-type consistent
    server cache1 10.0.1.20:8080 check
    server cache2 10.0.1.21:8080 check
    server cache3 10.0.1.22:8080 check
```

**Валидация:**
- `for i in $(seq 1 20); do curl -s http://haproxy/api/products/123; done | sort | uniq -c` — все запросы на один сервер.

### Сценарий 5: Graceful shutdown бэкенда

Остановка приложения без потери запросов:

```bash
# Бэкенд на systemd с KillSignal=SIGTERM
systemctl stop api-app

# Или через API graceful shutdown
curl -X POST http://localhost:8080/admin/graceful-shutdown
# Приложение завершает приём новых соединений и дожидается текущих
```

На стороне балансировщика:
```haproxy
backend api_servers
    server app1 10.0.1.10:8080 check inter 3s rise 2 fall 3
```

**Валидация:**
- До остановки: все запросы на `app1`.
- После остановки: Nginx/HAProxy помечает `app1` как `DOWN` после `fall=3`, трафик перетекает.
- В логах приложения: все PID завершились через SIGTERM, core dump отсутствует.

### Сценарий 6: Least-conn для WebSocket/gRPC

Долгие соединения требуют least-conn:

```nginx
upstream ws_backend {
    least_conn;
    server 10.0.1.30:8080 max_fails=3 fail_timeout=30s;
    server 10.0.1.31:8080 max_fails=3 fail_timeout=30s;
    keepalive 16;
}

server {
    listen 80;
    server_name ws.example.com;

    location / {
        proxy_pass http://ws_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

**Валидация:**
- Открываем 100 WebSocket-соединений.
- `ss -tn state established '( dport = :8080 or dport = :8081 )' | wc -l` — соединения распределяются пропорционально нагрузке.

### Сценарий 7: Traffic splitting (canary) в HAProxy

5% трафика на canary-версию:

```haproxy
frontend http-in
    bind *:80
    acl is_canary path_beg /canary
    use_backend canary_backend if is_canary
    default_backend stable_backend

backend stable_backend
    balance roundrobin
    server app1 10.0.1.10:8080 check
    server app2 10.0.1.11:8080 check

backend canary_backend
    balance roundrobin
    server canary1 10.0.1.20:8080 check
```

**Валидация:**
- `for i in $(seq 1 100); do curl -s http://haproxy/api; done | sort | uniq -c` — ~95 на stable, ~5 на canary.
- Увеличение доли: добавьте `weight` в backend или используйте `http-request set-src` для percentage-based routing.

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Uneven load distribution** | Один бэкенд перегружен, другой свободен | `watch 'ss -s'` или прометей `upstream_requests_total` | Выбрать правильный алгоритм (least-conn для WebSocket) |
| **Sticky session broken** | Сессия теряется при рестарте бэкенда | Логи приложения: `session not found` | Использовать внешнее хранение сессий (Redis) вместо sticky sessions |
| **Health check flapping** | Бэкенд постоянно переключается UP/DOWN | `tcpdump` на health check порту | Увеличить `rise`/`fall`, проверить сетевую стабильность |
| **DNS resolution stale** | Upstream IP не обновляется после изменения DNS | `dig upstream-host` — IP устарел | Добавить `resolver 127.0.0.1 valid=30s;` в Nginx |
| **Slow drain** | Бэкенд завершается долго, клиенты получают 502 | `tcpdump` — соединения закрыты балансировщиком | Увеличить `proxy_read_timeout`, настроить pre-stop hook |
| **Session migration** | При падении бэкенда все его sticky-сессии теряются | Логи: всплеск 401/403 | Использовать shared session storage (Redis, DB) |
| **Canary not receiving traffic** | Canary-версия не получает запросы | `curl -I http://host/canary` — проверка ACL | Проверить `acl` и `use_backend` логику |

## Лучшие практики

1. **Least-conn для stateful протоколов:** WebSocket, gRPC streaming, SSE — используйте `least_conn`, а не round-robin.
2. **Health checks на отдельном порту:** Если возможно, настройте отдельный порт/endpoint для health checks, чтобы не смешивать трафик.
3. **`rise` ≥ 2 для избежания flapping:** Одна успешная проверка — ненадёжно. Используйте `rise 2` или `rise 3`.
4. **`fall` ≥ 2 для избежания flapping:** То же для перевода в `DOWN`.
5. **Cookie-based affinity вместо IP-hash:** IP-hash ломается за NAT/CDN. Cookie affinity сохраняется на клиенте.
6. **Shared session storage вместо sticky sessions:** Redis или БД для сессий. Sticky sessions — временное решение для legacy.
7. **График draining:** При массовом redeploy drain по одному бэкенду, а не всем сразу.
8. **`proxy_next_upstream` на все ошибки:** `error timeout http_500 http_502 http_503 http_504` — автоматический failover.
9. **Собственный health endpoint:** `/healthz` должен проверять критичные зависимости (БД, кэш, внешние API), а не только `200 OK`.
10. **Мониторинг queue depth:** В HAProxy отслеживайте `QUEUE` в `show stat` — рост очереди означает нехваткуcapacity.
11. **Circuit breaker на уровне приложения:** Балансировщик отключает бэкенд при ошибках, но circuit breaker (Hystrix, Resilience4j) защищает от каскадных отказов.
12. **Canary с постепенным ростом:** Начинайте с 1% трафика, мониторьте ошибки и latency, затем линейно увеличивайте.

## Граничные случаи и ограничения

1. **IP-hash и CDN:** За CDN все клиенты имеют IP edge-сервера. `ip_hash` распределит весь трафик на один бэкенд. Используйте cookie-based affinity.
2. **DNS TTL и upstream:** Nginx кэширует DNS на 5 минут. При быстром изменении DNS записи часть запросов уйдёт на старый IP. Используйте `resolver` с `valid=30s`.
3. **Large number of backends:** При >100 бэкендах в upstream Nginx может потреблять много памяти. Используйте DNS-based upstream с `resolver`.
4. **Health check amplification:** Частые HTTP health checks (`inter 1s`) создают нагрузку на бэкенд. Увеличьте интервал или используйте TCP checks.
5. **Canary и cookies:** Если приложение устанавливает session cookie, canary-запросы могут быть перенаправлены на stable из-за cookie affinity.
6. **Graceful shutdown и websocket:** При shutdown WebSocket-соединения не завершаются мгновенно. Балансировщик должен ждать `proxy_read_timeout`.
7. **Consistent hashing и uneven distribution:** При добавлении/удалении бэкенда consistent hashing перераспределяет только часть ключей, но может давать неравномерное распределение.
8. **`least_conn` и keepalive:** Один keepalive-соединение может обрабатывать много запросов. `least_conn` считает соединения, а не запросы.
9. **HAProxy `option httpchk` и POST body:** `httpchk` отправляет только заголовки. Для POST с телом используйте `http-check send-buf`.
10. **Session affinity и container orchestration:** В Kubernetes `ip_hash` нестабильна из-за динамического изменения IP пода. Используйте `service.kubernetes.io/topology-aware-hints` или sticky sessions через cookie.

## L4 Load Balancing: IPVS и/macvlan

### L4 vs L7: когда что использовать

| Характеристика | L4 (Transport) | L7 (Application) |
|:---|:---|:---|
| **Уровень OSI** | TCP/UDP | HTTP/gRPC/WebSocket |
| **Информация для принятия решений** | IP, порт, протокол | URL, заголовки, cookies, метод |
| **Производительность** | Выше (нет разбора payload) | Ниже (разбор HTTP) |
| **Алгоритмы** | Round-robin, LC, hash | Все + URL-based, header-based |
| **Health checks** | TCP (порт открыт) | HTTP (код ответа, тело) |
| **Session affinity** | Source IP hash | Cookie, header, URL |
| **Примеры инструментов** | IPVS, LVS, MetalLB, cloud LB | Nginx, HAProxy, Traefik, Envoy |

### IPVS (IP Virtual Server)

IPVS — встроенная в ядро Linux подсистема L4-балансировки. Используется в Kubernetes (kube-proxy в IPVS-режиме) и Docker Swarm.

```bash
# Проверка наличия IPVS
modprobe ip_vs
ipvsadm -Ln

# Добавление виртуального сервера (VIP: порт)
ipvsadm -A -t 10.0.0.100:80 -s rr

# Добавление бэкенд-серверов
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.1:80 -g    # -g = NAT (gateway)
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.2:80 -g
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.3:80 -g

# Просмотр таблицы
ipvsadm -Ln
# → TCP  10.0.0.100:80 rr
#   -> 10.0.0.1:80     Masq    1      0          0
#   -> 10.0.0.2:80     Masq    1      0          0
#   -> 10.0.0.3:80     Masq    1      0          0

# Статистика
ipvsadm -Ln --stats
```

**Алгоритмы IPVS:**

| Алгоритм | Флаг | Описание |
|:---|:---|:---|
| `rr` | Round-Robin | Поочерёдное распределение |
| `wrr` | Weighted Round-Robin | С весами |
| `lc` | Least Connections | Меньше активных соединений |
| `wlc` | Weighted Least Connections | С весами (по умолчанию) |
| `sh` | Source Hashing | Хэш по IP источника |
| `dh` | Destination Hashing | Хэш по IP назначения |
| `lblc` | Locality-Based Least Connections | С учётом локальности |
| `sed` | Shortest Expected Delay | Минимальная задержка |
| `nq` | Never Queue | Без очередей |

**Production-пример с health checks:**
```bash
# Виртуальный сервер с активными проверками
ipvsadm -A -t 10.0.0.100:80 -s wlc -p 300  # -p = persistence (sticky, секунды)

# Бэкенды с весами и проверками
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.1:80 -g -w 3
ipvsadm -a -t 10.0.0.100:80 -r 10.0.0.2:80 -g -w 1

# Мониторинг активных соединений
watch -n 1 ipvsadm -Ln --stats
```

### MetalLB (bare-metal L4)

MetalLB предоставляет LoadBalancer-type Service в bare-metal Kubernetes кластерах. Два режима:

| Режим | Механизм | Плюсы | Минусы |
|:---|:---|:---|:---|
| **Layer 2 (ARP)** | Один узел анонсирует VIP через ARP | Простота | Failover через watchdog (до 10с), нет ECMP |
| **BGP** | Маршрутизаторы получают маршруты через BGP | ECMP, балансировка на уровне маршрутизатора | Требует BGP-поддержки на маршрутизаторе |

```yaml
# MetalLB Layer 2 конфигурация
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: production-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.200-192.168.1.250
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: production-l2
  namespace: metallb-system
```

## Дополнительная информация

### PROXY Protocol в деталях

PROXY Protocol v1 (текстовый) и v2 (бинарный) передают информацию о клиенте перед HTTP-данными:

```
# PROXY Protocol v1
PROXY TCP4 192.168.1.1 10.0.0.1 56324 80\r\n

# PROXY Protocol v2 (бинарный)
\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A...  (13-byte signature + header + address info)
```

Nginx stream-модуль для PROXY Protocol:
```nginx
stream {
    upstream backend_tcp {
        server 10.0.1.10:8080;
    }

    server {
        listen 80;
        proxy_protocol on;
        proxy_pass backend_tcp;
        real_ip_header proxy protocol v2;
        set_real_ip_from 10.0.0.0/8;
    }
}
```

### Traffic Splitting и Blue/Green deployment

| Стратегия | Описание | Риски |
| :--- | :--- | :--- |
| **Blue/Green** | Две идентичные среды; переключение 100% | Дорого, требует дублирования инфраструктуры |
| **Canary** | Постепенный рост трафика на новую версию | Сложность управления несколькими версиями |
| **A/B Testing** | Разные версии для разных сегментов | Требует маркетинговой аналитики |
| **Shadow** | Трафик дублируется на новую версию, ответ игнорируется | Высокая нагрузка, сложность отладки |

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — конфигурация Nginx и HAProxy.
- **[Управление соединениями](./http_connection_management.md)** — keepalive, таймауты, лимиты.
- **[Наблюдаемость HTTP-сервисов](./http_monitoring_observability.md)** — RED, Golden Signals.
- **[Rate Limiting и устойчивость](./http_rate_limiting_circuit_breakers.md)** — ограничение нагрузки.
- **[Конфигурация Nginx](../../../WebServers/Nginx/Core/nginx_overview.md)** — архитектура и модули.
- **[Диагностика Nginx](../../../WebServers/Nginx/Operations/nginx_troubleshooting.md)** — устранение ошибок балансировщика.
