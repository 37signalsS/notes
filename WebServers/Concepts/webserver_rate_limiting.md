# Rate Limiting и защита от ботов в веб-серверах

## Определения

**Rate Limiting** — механизм ограничения числа запросов с одного IP/сессии/ключа за определенный интервал времени.

**Key** — идентификатор, по которому применяется ограничение (IP, пользователь, API ключ, заголовок).

**Burst** — разрешенное число запросов сверх установленной ставки, буферизуемое в очереди.

**Delay** — задержка обработки запроса при превышении burst.

**Reject** — отклонение запроса с кодом 429 (Too Many Requests) при превышении burst.

**Stick Table** — структура данных в оперативной памяти HAProxy для хранения счетчиков, IP, session persistence.

**Token Bucket / Leaky Bucket** — алгоритмы rate limiting, моделирующие «ведро с токенами» или «протекающее ведро».

**Circuit Breaker (Предохранитель)** — автоматическое размыкание цепи запросов при превышении порога ошибок или таймаутов от зависимости.

**Brute-force Protection** — защита от перебора паролей путем ограничения числа попыток аутентификации.

**Bot Protection** — защита от автоматизированных скриптов и ботов путем анализа User-Agent, поведения, IP репутации.

---

## Основные концепции

### Алгоритмы rate limiting

| Алгоритм | Описание | Пример |
| :--- | :--- | :--- |
| **Token Bucket** | Запросы потребляют токены. Токены восстанавливаются со скоростью R. | 10 токенов, скорость 1 токен/сек. 10 burst запросов. |
| **Leaky Bucket** | Запросы «протекают» с постоянной скоростью. | 5 запросов/сек, очередь 10. |
| **Fixed Window** | Ограничение за фиксированный интервал времени (минута, час). | 100 запросов в минуту. |
| **Sliding Window** | Ограничение за скользящий интервал. | 100 запросов за последние 60 секунд. |

### Уровни применения rate limiting

| Уровень | Описание | Пример |
| :--- | :--- | :--- |
| **IP-based** | Ограничение по IP клиента. | Защита от DDoS, brute-force. |
| **User-based** | Ограничение по идентификатору пользователя. | Защита API. |
| **Key-based** | Ограничение по произвольному ключу (API ключ, session ID). | Защита публичных API. |
| **Path-based** | Ограничение по пути запроса. | Защита `/login` от brute-force. |
| **Global** | Общее ограничение на все запросы. | Защита от DDoS. |

### Rate limiting в стеке прокси

| Прокси | Механизм rate limiting | Примечание |
| :--- | :--- | :--- |
| **Nginx** | `ngx_http_limit_req_module`, `ngx_http_limit_conn_module` | Требует `zone`. Fixed window. |
| **Angie** | `limit_req`, `limit_conn`, REST API для управления | Drop-in замена Nginx. |
| **HAProxy** | `stick-table`, `http-request track-sc`, `http-request deny` | Sliding window, высокоточный. |
| **Traefik** | Middleware `rateLimit` | Требует встроенного или внешнего rate limiter. |
| **Apache** | `mod_ratelimit`, `mod_reqtimeout`, `mod_evasive` | `mod_evasive` — популярный модуль. |

---

## Практические сценарии

### Сценарий 1: Rate limiting в Nginx

```nginx
http {
    # Зона для хранения состояния (10 MB = ~160 000 состояний)
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    server {
        listen 80;
        server_name api.example.com;

        location / {
            # Burst 20 запросов, reject с кодом 429
            limit_req zone=api burst=20 nodelay;

            proxy_pass http://api_backend;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

**Ключевые моменты:**
- `limit_req_zone` задает зону и скорость.
- `burst` — размер очереди.
- `nodelay` — отклонять запросы сразу при превышении burst, без задержки.
- `zone` задает ключ (`$binary_remote_addr` — IP клиента).

### Сценарий 2: Rate limiting на /login в Nginx

```nginx
http {
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;

    server {
        listen 80;
        server_name example.com;

        location /login {
            limit_req zone=login burst=5 nodelay;
            limit_req_status 429;

            proxy_pass http://auth_backend;
        }
    }
}
```

**Ключевые моменты:**
- 1 запрос в секунду, burst 5.
- `limit_req_status 429` — код при превышении.
- Защита от brute-force.

### Сценарий 3: Connection limiting в Nginx

```nginx
http {
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    server {
        listen 80;
        server_name example.com;

        location / {
            limit_conn addr 10;
            proxy_pass http://backend;
        }
    }
}
```

**Ключевые моменты:**
- `limit_conn` ограничивает число одновременных соединений.
- 10 соединений с одного IP.
- Защита от одно IP с большим числом соединений.

### Сценарий 4: Rate limiting в Apache (mod_evasive)

```apacheconf
# Загрузка модуля
LoadModule evasive20_module modules/mod_evasive.so

<IfModule mod_evasive.c>
    DOSHashTableSize 3097
    DOSPageCount 2
    DOSSiteCount 50
    DOSPageInterval 1
    DOSSiteInterval 1
    DOSBlockingPeriod 10
    DOSEmailNotify admin@example.com
    DOSLogDir /var/log/mod_evasive
</IfModule>
```

**Ключевые моменты:**
- `DOSPageCount` — число запросов на страницу за интервал.
- `DOSSiteCount` — число запросов на сайт за интервал.
- `DOSBlockingPeriod` — время блокировки в секундах.
- Защита от brute-force и DDoS.

### Сценарий 5: Rate limiting в HAProxy

```haproxy
backend http_backend
    mode http
    balance roundrobin

    # Stick table для отслеживания запросов
    stick-table type ip size 100k expire 1m store http_req_rate(10s)

    # Отслеживание запросов по IP
    http-request track-sc src table http_backend

    # Ограничение 10 запросов в секунду
    http-request deny if { sc_http_req_rate(10s) gt 10 }

    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

**Ключевые моменты:**
- `stick-table` хранит счетчики.
- `http-request track-sc` отслеживает запросы.
- `sc_http_req_rate(10s)` — скорость за последние 10 секунд.
- `http-request deny` — отклонение запроса с кодом 403.

### Сценарий 6: Rate limiting на /login в HAProxy

```haproxy
frontend http_frontend
    bind *:80
    mode http

    # Stick table для отслеживания попыток входа
    stick-table type ip size 50k expire 30s store http_req_rate(10s)

    # Отслеживание запросов к /login
    acl is_login path_beg /login
    http-request track-sc src if is_login

    # Ограничение 1 запрос в секунду на /login
    http-request deny if is_login { sc_http_req_rate(10s) gt 1 }

    default_backend http_backend
```

**Ключевые моменты:**
- Burst 1 запрос в секунду.
- `stick-table` expire 30 секунд.
- Защита от brute-force на `/login`.

### Сценарий 7: Circuit Breaker в Traefik

```yaml
http:
  middlewares:
    circuit-breaker:
      circuitBreaker:
        expression: "NetworkErrorRatio() > 0.5"
        checkPeriodInSeconds: 5
        fallbackDurationInSeconds: 30
        recoveryDurationInSeconds: 30
        routingPolicy:
          strategy: "first"
```

**Ключевые моменты:**
- `NetworkErrorRatio() > 0.5` — более 50% ошибок сети.
- `fallbackDurationInSeconds` — время отключения circuit breaker.
- `recoveryDurationInSeconds` — время восстановления.
- Защита от каскадных отказов.

### Сценарий 8: Bot protection в Nginx

```nginx
http {
    # Блокировка известных ботов
    map $http_user_agent $is_bad_bot {
        default 0;
        ~*curl 1;
        ~*scrapy 1;
        ~*nikto 1;
        ~*sqlmap 1;
        ~*hydra 1;
    }

    # Ограничение по IP
    geo $is_bad_ip {
        default 0;
        192.0.2.0/24 1;  # известный ботнет
    }

    server {
        listen 80;
        server_name example.com;

        if ($is_bad_bot) {
            return 403;
        }

        if ($is_bad_ip) {
            return 403;
        }

        location / {
            proxy_pass http://backend;
        }
    }
}
```

**Ключевые моменты:**
- `map` создает переменную на основе User-Agent.
- `geo` создает переменную на основе IP.
- Блокировка ботов по сигнатурам и IP.

### Сценарий 9: Защита от brute-force в Nginx

```nginx
http {
    limit_req_zone $binary_remote_addr zone=bruteforce:10m rate=1r/s;

    server {
        listen 80;
        server_name example.com;

        location /login {
            limit_req zone=bruteforce burst=3 nodelay;

            proxy_pass http://auth_backend;
            proxy_intercept_errors on;
            error_page 429 /429.html;
        }
    }
}
```

**Ключевые моменты:**
- 1 запрос в секунду, burst 3.
- `error_page 429` — кастомная страница при превышении.
- Защита от brute-force на `/login`.

### Сценарий 10: Rate limiting в Traefik

```yaml
http:
  routers:
    api-router:
      rule: "PathPrefix(`/api`)"
      service: api-service
      middlewares:
        - rate-limit

  middlewares:
    rate-limit:
      rateLimit:
        average: 10
        period: 1s
        burst: 20

  services:
    api-service:
      loadBalancer:
        servers:
          - url: http://backend:8080
```

**Ключевые моменты:**
- `average` — средняя ставка запросов.
- `period` — интервал времени.
- `burst` — размер очереди.
- Защита API от перегрузки.

---

## Дополнительная информация

### Рекомендации по настройке rate limiting

1. **Начинайте с мягких ограничений:** burst > average, чтобы не блокировать легитимных пользователей.
2. **Используйте ключи, чувствительные к нагрузке:** IP для Edge, API ключ для публичных API.
3. **Применяйте path-based ограничения:** `/login`, `/api` — частые цели для brute-force.
4. **Мониторьте 429 коды:** рост 429 может указывать на слишком жесткие ограничения.
5. **Используйте circuit breaker вместе с rate limiting:** rate limiting защищает от перегрузки, circuit breaker — от каскадных отказов.

### Чек-лист защиты веб-серверов

- [ ] **Rate limiting:** настроен для всех публичных endpoints.
- [ ] **Connection limiting:** настроен для защиты от DDoS.
- [ ] **Bot protection:** блокировка известных ботов по User-Agent.
- [ ] **Brute-force protection:** ограничение на `/login`, `/signup`.
- [ ] **Circuit breaker:** настроен для критичных внешних зависимостей.
- [ ] **Monitoring:** алерты на рост 429, рост 5xx.
- [ ] **Logging:** логи rate limiting событий.

### См. также

- **[Rate Limiting и Circuit Breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md) — теория и алгоритмы.
- **[DDoS Protection](../../Security/ApplicationSecurity/ddos_overview.md) — защита от DDoS.
- **[Bot Protection](../../Concepts/bot_protection.md) — защита от ботов.
- **[Circuit Breaker в Traefik](../Traefik/traefik-circuit-breaker-retry.md) — практические сценарии.
- **[Rate Limiting в Traefik](../Traefik/traefik-rate-limiting-deep.md) — углубленное руководство.
- **[Load Balancing в HAProxy](../HAProxy/haproxy-load-balancing.md) — практические сценарии.
- **[Nginx Rate Limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html) — документация Nginx.
- **[Apache mod_evasive](https://github.com/jzdziarski/mod_evasive) — документация mod_evasive.
- **[HAProxy Stick Tables](https://www.haproxy.org/doc/3.4/configuration.html#stick-tables) — документация HAProxy.
