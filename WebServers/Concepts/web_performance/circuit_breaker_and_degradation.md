# Circuit Breaker и Degradation Patterns для веб-производительности

## Определения

**Circuit Breaker (Прерыватель цепи)** — паттерн отказоустойчивости, при котором прокси перестаёт отправлять запросы на неработающий бэкенд и сразу возвращает fallback-ответ (кэш, статику, 503). Защищает бэкенд от шторма запросов при сбое и скрывает проблему от конечных пользователей.

**Degradation (Деградация)** — стратегия принудительного снижения функциональности при перегрузке или сбое бэкенда. Примеры: отдача устаревшего кэша вместо динамического контента, отключение не критичных сторонних скриптов, возврат skeleton-страницы.

**Fallback (Запасной вариант)** — ответ, возвращаемый прокси при недоступности бэкенда. Может быть: устаревший кэш (`stale-if-error`), статическая страница, заглушка с кодом 503.

**Retry amplification (Усиление ретраев)** — эффект, при котором один клиентский запрос генерирует несколько запросов к бэкенду из-за ретраев. Без ограничения `proxy_next_upstream_tries` 1 запрос = 10+ запросов к бэкенду.

**Failover (Автоматическое переключение)** — прозрачное для клиента перенаправление запроса на резервный бэкенд при недоступности основного.

**Thundering Herd (Стадо бизонов)** — одновременный всплеск запросов к бэкенду после восстановления после сбоя. Противодействие: `proxy_cache_lock`, Jitter TTL.

## Основные концепции

### Circuit Breaker в контексте веб-производительности

Классический Circuit Breaker работает на уровне сервисов (microservices). В контексте веб-серверов (Nginx/Angie) он реализуется через комбинацию директив:

```nginx
upstream backend {
    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
}

server {
    location / {
        proxy_pass http://backend;

        # Circuit Breaker: failover на другой бэкенд
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 10s;

        # Degradation: fallback на кэш при ошибках бэкенда
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;
    }
}
```

### Влияние на Core Web Vitals

| Сценарий | Влияние на LCP | Влияние на INP | Влияние на CLS |
| :--- | :--- | :--- | :--- |
| **Без Circuit Breaker** | Рост TTFB до 5-30 сек при сбое бэкенда | Полная недоступность интерфейса | Нет прямого влияния |
| **С Circuit Breaker + stale-if-error** | TTFB остаётся <200 мс (кэш) | Интерфейс остаётся отзывчивым | Нет прямого влияния |
| **С proxy_next_upstream** | Рост TTFB на 50-150 мс (failover) | Небольшой рост задержки | Нет прямого влияния |
| **С Degradation (skeleton)** | LCP = 0 мс (skeleton сразу) | Интерфейс работает, но без данных | CLS может вырасти (skeleton ≠ контент) |

### Паттерны degradation для фронтенда

1. **Cache-first fallback:** При недоступности бэкенда отдавать устаревший кэш. LCP остаётся в пределах SLO.
2. **Skeleton page:** Возврат lightweight-страницы с заглушками вместо динамического контента. CLS может вырасти — требуется явное резервирование места.
3. **Static fallback:** Отдача предварительно сгенерированной статической версии страницы. Подходит для SSR-приложений.
4. **Feature disable:** Отключение не критичных функций (рекомендации, виджеты) через feature flags при падении Availability.

### Retry amplification и защита

Без ограничения количества попыток один клиентский запрос может генерировать десятки upstream-запросов:

```nginx
# Ограничение количества попыток
proxy_next_upstream_tries 3;

# Ограничение по времени (включая все попытки)
proxy_next_upstream_timeout 10s;

# Не ретраить при идемпотентных методах
proxy_next_upstream error timeout http_500;
```

## Практические сценарии

### Сценарий 1: Circuit Breaker для API

```nginx
upstream api_backend {
    zone api_backend 64k;
    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.3:8080 backup;  # Резервный для emergency
}

server {
    location /api/ {
        proxy_pass http://api_backend;

        # Автоматический failover
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 10s;

        # Fallback на кэш при ошибках
        proxy_cache api_cache;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_cache_background_update on;
        proxy_cache_valid 200 5m;
        proxy_cache_valid 404 10s;
    }
}
```

**Валидация:**
```bash
# Имитация сбоя бэкенда
systemctl stop api@10.0.0.1

# Проверка fallback
curl -s https://example.com/api/data -H "Cache-Control: no-cache"
# → Устаревший кэш (200 OK) или резервный бэкенд

# Проверка заголовка
curl -sI https://example.com/api/data | grep -i x-cache
# → X-Cache-Status: STALE
```

### Сценарий 2: Degradation для SSR-приложения

```nginx
upstream ssr_backend {
    zone ssr_backend 64k;
    server 10.0.0.1:3000 max_fails=3 fail_timeout=10s;
}

server {
    # Основной SSR
    location / {
        proxy_pass http://ssr_backend;

        # Fallback на статику при ошибке
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 2;
        proxy_next_upstream_timeout 5s;

        # Если и резервный упал — статическая страница
        error_page 502 503 504 = /static/offline.html;
    }

    location = /static/offline.html {
        root /var/www/fallback;
        internal;
    }
}
```

### Сценарий 3: Monitoring Circuit Breaker state

```bash
# Angie: проверка состояния upstream
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '.peers[] | {server, state, fails}'
# → {
# →   "server": "10.0.0.1:8080",
# →   "state": "unhealthy",
# →   "fails": 3
# → }

# Nginx: проверка логов
tail -f /var/log/nginx/error.log | grep "upstream"
# → 2026/09/23 12:00:00 [error] 1234#1234: *5678 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 10.0.0.1, server: example.com, request: "GET /api/data HTTP/1.1", upstream: "http://10.0.0.1:8080/api/data", host: "example.com"
```

## Операции и команды

### Проверка конфигурации Circuit Breaker

```bash
# Проверка директив
nginx -T 2>&1 | grep -E "proxy_next_upstream|proxy_cache_use_stale|max_fails|fail_timeout"
# → proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
# → proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
# → proxy_next_upstream_tries 3;
# → max_fails=3 fail_timeout=10s;
```

### Stress-test Circuit Breaker

```bash
# Имитация сбоя бэкенда
iptables -A INPUT -s 10.0.0.1 -j DROP

# Проверка fallback
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code}\n" https://example.com/api/data
done | sort | uniq -c
# → 100 200 (fallback работает)

# Очистка
iptables -D INPUT -s 10.0.0.1 -j DROP
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Retry amplification** | RPS на бэкенд в 3-5x выше, чем у прокси | Логи бэкенда vs access.log прокси | Установить `proxy_next_upstream_tries 3` |
| **Circuit Breaker не срабатывает** | При сбое бэкенда клиенты получают 502 | `max_fails` не достигнут или `fail_timeout` истёк | Настроить `max_fails=3 fail_timeout=10s` |
| **Stale content после восстановления** | Клиенты видят старый кэш после деплоя | `Cache-Control: max-age` слишком большой | Использовать Cache Busting или уменьшить TTL |
| **Thundering Herd после сбоя** | Рост RPS на Origin в 10x после восстановления | Нет `proxy_cache_lock` или Jitter TTL | Включить `proxy_cache_lock on; proxy_cache_lock_timeout 5s;` |
| **Degradation CLS** | Сдвиги макета при fallback на skeleton | Отсутствие `aspect-ratio` в skeleton | Явное резервирование места в skeleton-странице |
| **Fallback не работает** | При сбое бэкенда возвращается 502 | `proxy_next_upstream` не настроен на нужные коды | Добавить `http_500 http_502 http_503 http_504` |

## Рекомендации

### Базовые правила

1. **Всегда настраивайте `proxy_next_upstream` для критичных API:** `error timeout http_500 http_502 http_503 http_504`.
2. **Ограничьте количество попыток:** `proxy_next_upstream_tries 3` предотвращает retry amplification.
3. **Используйте `proxy_cache_use_stale` для деградации:** Клиенты не видят 502 при сбое бэкенда.
4. **Включите `proxy_cache_background_update`:** Ускоряет обновление кэша после сбоя.
5. **Настройте `max_fails` + `fail_timeout`:** Автоматически исключает unhealthy-бэкенды из балансировки.
6. **Подготовьте fallback-страницы:** Статическая `offline.html` для SSR-приложений.

### Для DevOps/SRE/SysAdmin

- **Monitoring Circuit Breaker state:** Алерт при `state=unhealthy` или `fails > 0` в upstream.
- **Capacity Planning:** При росте RPS увеличивайте количество бэкендов или уменьшайте `proxy_next_upstream_tries`.
- **Runbook:** Для каждого Circuit Breaker алерта должен быть runbook с шагами: проверить health check, логи бэкенда, переключить на backup.
- **GameDay:** Регулярно проводите Chaos Engineering: отключайте бэкенды, проверяйте, что Circuit Breaker срабатывает и клиенты не видят 502.

## Дополнительная информация

### См. также

- [Паттерны микросервисной архитектуры](../../Concepts/microservice_patterns.md) — отказоустойчивость и масштабируемость.
- [Кэширование и Web Vitals](./caching.md) — `stale-while-revalidate` и `stale-if-error`.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — как пул соединений взаимодействует с Circuit Breaker.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — деплой без прерывания обслуживания.
- [HTTP Rate Limiting и Circuit Breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md) — общие паттерны.
- [HTTP Health Checks и Readiness](../../Networking/Protocols/HTTP/http_health_checks_readiness.md) — proactive обнаружение сбоев.

### RFC и спецификации

- **RFC 7231** — HTTP: 5xx ошибки, retry-after.
- **RFC 5861** — `stale-while-revalidate`, `stale-if-error`.
- **RFC 9213** — CDN-Cache-Control для degradation.
