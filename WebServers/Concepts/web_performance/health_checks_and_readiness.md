# Health Checks и Readiness для веб-производительности

## Определения

**Health Check** — автоматизированная проверка доступности и готовности компонента системы. В контексте веб-серверов: проверка доступности upstream-бэкендов, состояния кэша и CDN.

**Readiness Probe** — проверка, готова ли система принимать трафик. В Nginx/Angie реализуется через `max_fails` + `fail_timeout` или внешний скрипт, возвращающий `x-accel-redirect`.

**Liveness Probe** — проверка, жив ли процесс. В Nginx/Angie — это `systemctl status nginx` или внешний мониторинг через `curl http://localhost/nginx_status`.

**Passive Health Check** — проверка по результатам реальных запросов. Nginx/Angie помечает бэкенд как unhealthy после `max_fails` неудач подряд.

**Active Health Check** — периодическая проверка бэкенда независимо от трафика. В Nginx/Angie требует стороннего модуля (`nginx-upstream-fair` или `nginx-healthcheck`). В Angie есть встроенный модуль `healthcheck`.

**Graceful Drain** — процесс прекращения отправки новых запросов на бэкенд перед его отключением. В Nginx/Angie реализуется через `drain` состояние в upstream.

## Основные концепции

### Passive vs Active Health Checks

| Тип | Преимущества | Недостатки | Влияние на производительность |
| :--- | :--- | :--- | :--- |
| **Passive** | Без дополнительных запросов; zero overhead | Обнаруживает сбой только после `max_fails` неудач | Рост 5xx на 3-5 запросов до отключения бэкенда |
| **Active** | Быстрое обнаружение (секунды); не ждёт реального трафика | Дополнительная нагрузка на бэкенд | Минимально: 1 запрос/сек на бэкенд |

### Влияние на Core Web Vitals

При отсутствии или некорректной настройке health checks:

1. **LCP:** Рост TTFB на 200-500 мс при сбое бэкенда. Прокси продолжает слать запросы на unhealthy-бэкенд.
2. **INP:** Полная недоступность интерфейса при 5xx ошибках.
3. **CLS:** Нет прямого влияния, но при fallback на skeleton-page CLS может вырасти.

### Директивы конфигурации

| Директива | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `max_fails` | Количество неудач перед помечанием бэкенда как unhealthy | `3` |
| `fail_timeout` | Время, в течение которого учитываются неудачи | `10s` |
| `proxy_next_upstream` | Когда переключать на другой бэкенд | `error timeout http_500 http_502 http_503 http_504` |
| `slow_start` | Постепенное увеличение веса бэкенда после восстановления | `10s` для cache warming |

### Graceful Drain при деплое

При обновлении бэкенда важно прекратить отправку новых запросов перед остановкой:

```nginx
upstream backend {
    zone backend 64k;
    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
}

server {
    location / {
        proxy_pass http://backend;

        # Не ретраить при drain-состоянии
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 2;
    }
}
```

## Практические сценарии

### Сценарий 1: Базовая passive health check

```nginx
upstream api_backend {
    zone api_backend 64k;
    server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;
}

server {
    location /api/ {
        proxy_pass http://api_backend;

        # Failover при ошибках
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 2;
        proxy_next_upstream_timeout 10s;

        # Fallback на кэш
        proxy_cache api_cache;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    }
}
```

**Валидация:**
```bash
# Имитация сбоя бэкенда
systemctl stop api@10.0.0.1

# Проверка failover (должны идти запросы на 10.0.0.2)
curl -s https://example.com/api/data -H "Cache-Control: no-cache"
# → 200 OK (с 10.0.0.2)

# Проверка состояния upstream (Angie)
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '.peers[] | {server, state}'
# → {"server": "10.0.0.1:8080", "state": "unhealthy"}
# → {"server": "10.0.0.2:8080", "state": "up"}
```

### Сценарий 2: Active health check (Angie)

```nginx
http {
    upstream api_backend {
        zone api_backend 64k;
        server 10.0.0.1:8080 max_fails=3 fail_timeout=10s;
        server 10.0.0.2:8080 max_fails=3 fail_timeout=10s;

        # Active health check
        health_check;
        health_check_timeout 5s;
        health_check_interval 10s;
        health_check_fails 3;
        health_check_success 2;
    }

    server {
        location / {
            proxy_pass http://api_backend;
        }

        # Endpoint для health check
        location /health {
            access_log off;
            return 200 "OK";
        }
    }
}
```

**Валидация:**
```bash
# Проверка состояния health check
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '.peers[] | {server, state, health}'
# → {"server": "10.0.0.1:8080", "state": "up", "health": {"fails": 0, "unavailable": 0}}
```

### Сценарий 3: Graceful drain при деплое

```bash
# 1. Перевести бэкенд в drain (Angie)
curl -X POST http://localhost:8888/api/status/http/upstreams/api_backend/10.0.0.1:8080/drain

# 2. Дождаться завершения активных соединений
sleep 10

# 3. Остановить старый бэкенд
systemctl stop api@10.0.0.1

# 4. Деплой новой версии
systemctl start api@10.0.0.1

# 5. Убрать drain
curl -X POST http://localhost:8888/api/status/http/upstreams/api_backend/10.0.0.1:8080/up
```

## Операции и команды

### Проверка состояния upstream

```bash
# Angie
curl -s http://localhost:8888/api/status/http/upstreams/api_backend/ | jq '.peers[] | {server, state, fails}'
# → {"server": "10.0.0.1:8080", "state": "up", "fails": 0}
# → {"server": "10.0.0.2:8080", "state": "unhealthy", "fails": 3}
```

### Имитация сбоя бэкенда

```bash
# Блокировка трафика к бэкенду
iptables -A INPUT -s 10.0.0.1 -j DROP

# Проверка failover
curl -s https://example.com/api/data -H "Cache-Control: no-cache"
# → 200 OK (резервный бэкенд)

# Очистка
iptables -D INPUT -s 10.0.0.1 -j DROP
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Бэкенд не отключается** | Прокси продолжает слать запросы на unhealthy-бэкенд | `state` в upstream = `up` при проблемах | Проверить `max_fails` и `fail_timeout` |
| **Рост 5xx при деплое** | Клиенты получают 502/503 | Логи: `upstream prematurely closed connection` | Настроить `proxy_next_upstream` на нужные коды |
| **Health check не работает** | Active HC не обнаруживает сбой | Проверить endpoint `/health` на бэкенде | Убедиться, что endpoint возвращает 200 и доступен |
| **Drain не работает** | Новые запросы продолжают идти на draining-бэкенд | Проверить состояние `draining` | Убедиться, что прокси поддерживает drain (Angie да, Nginx OSS — частично) |

## Рекомендации

### Базовые правила

1. **Всегда настраивайте passive health checks:** `max_fails=3 fail_timeout=10s` для всех upstream.
2. **Настройте `proxy_next_upstream` на ошибки:** `error timeout http_500 http_502 http_503 http_504`.
3. **Ограничьте количество попыток:** `proxy_next_upstream_tries 2`-`3`.
4. **Используйте active health checks для критичных бэкендов:** Angie имеет встроенный модуль.
5. **Проводите graceful drain при деплое:** Не останавливайте бэкенд резко — дайте завершить активные соединения.
6. **Мониторьте состояние upstream:** Алерт при `state=unhealthy` или `fails > 0`.

### Для DevOps/SRE/SysAdmin

- **Runbook:** Для каждого upstream должен быть runbook с шагами: проверить health check endpoint, логи бэкенда, переключить на backup.
- **Monitoring:** Отслеживайте `state` и `fails` в upstream. Алерт при `state=unhealthy`.
- **Chaos Engineering:** Регулярно отключайте бэкенды, проверяйте, что failover работает за <1 сек.

## Дополнительная информация

### См. также

- [Circuit Breaker и Degradation Patterns](./circuit_breaker_and_degradation.md) — fallback стратегии при сбоях.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload и drain.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — как пул соединений взаимодействует с health checks.
- [HTTP Health Checks и Readiness](../../Networking/Protocols/HTTP/http_health_checks_readiness.md) — общая методология.

### RFC и спецификации

- **RFC 7231** — HTTP: 5xx ошибки, retry-after.
- **RFC 6921** — Health Check для HTTP/2.
