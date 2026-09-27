# Кэширование прокси в Angie (Proxy Cache)

## Определения

**Proxy Cache** — кэширование ответов бэкенда на уровне HTTP-сервера: Angie сохраняет ответы в разделяемую память (индекс ключей) и на диск (тело), отдавая повторяющиеся запросы без обращения к бэкенду.

**Ключ кэша** — строка, по которой сопоставляется ответ (по умолчанию `$scheme$proxy_host$request_uri`; задаётся `proxy_cache_key`).

**HIT / MISS / STALE / REVALIDATED / EXPIRED** — статусы в переменной `$upstream_cache_status`, показывающей, отдан ли ответ из кэша.

**Microcaching** — кэширование с коротким TTL (1–60 c) для "горячих" динамических страниц без потери свежести данных.

## Теоретический блок

См. полноценную теорию, конфигурации и архитектуру в теме [Серверное кэширование (Proxy Cache) в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md) — она является единым источником истины (Single Source of Truth) и покрывает и Nginx, и Angie.

Ниже — только Angie-специфичные возможности и различия.

### Что Angie добавляет поверх "классического" proxy_cache

1. **Нативный purge** — директива `proxy_cache_purge` (аналог коммерческого `proxy_cache_purge` из nginx plus) доступна в открытой версии Angie.
2. **`file=` в `proxy_cache_path`** — персистентность индекса кэша на диск: ключи переживают перезагрузку/перезапуск без потери содержимого.
3. **Статистика в Status API** — отчёты по кэшу через `/status/http/caches/<zone>/`.
4. **Флеш зон при binary upgrade** — при обновлении на лету Angie сохраняет `keys_zone` на диск, чтобы новый мастер восстановил индекс.

## Практический блок

### Сценарий 1: Кэш с нативным purge (Angie OSS)

```nginx
http {
    proxy_cache_path /var/cache/angie/proxy levels=1:2
                     keys_zone=api_cache:10m max_size=1g inactive=60m
                     use_temp_path=off;

    server {
        listen 80;
        server_name api.example.com;

        # Служебная зона для purge (защищена ограничением по IP)
        location ~ /purge(/.*) {
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
            proxy_cache_purge api_cache "$scheme$proxy_host$1";
        }

        location / {
            proxy_pass http://backend;
            proxy_cache api_cache;
            proxy_cache_key "$scheme$proxy_host$request_uri";
            add_header X-Cache-Status $upstream_cache_status;
        }
    }
}
```

```bash
# Очистка конкретного URL из кэша
curl -s -X PURGE http://127.0.0.1/purge/resource/123
# → Ожидаемо: "Successful purge" (или лог очистки)

# Проверка статуса кэша (HIT после второго запроса)
curl -sI http://api.example.com/resource/123 | grep X-Cache-Status
# → X-Cache-Status: MISS  (первый запрос)
# → X-Cache-Status: HIT   (повторный запрос)
```

### Сценарий 2: Персистентность ключей при reload (file=)

```nginx
http {
    proxy_cache_path /var/cache/angie/proxy
                     keys_zone=api_cache:10m file=/var/cache/angie/proxy/keys.db
                     max_size=1g inactive=60m;
}
```

Индекс кэша хранится на диске, поэтому `angie -t && kill -HUP $(cat /run/angie.pid)` не "холодит" кэш: после reload ключи остаются, и кэш продолжает отдавать HIT.

### Сценарий 3: Microcaching для динамики

```nginx
server {
    location /news/ {
        proxy_pass http://backend;
        proxy_cache api_news;
        proxy_cache_valid 200 30s;      # микро-TTL 30 сек
        proxy_cache_use_stale error timeout updating;  # отдавать старое при ошибках
        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

### Мониторинг кэша через Status API

```bash
# Интеграция status_zone + API
curl -s http://127.0.0.1:8888/api/status/http/caches/api_cache/ | jq
# → { "size": ..., "cold": ..., "miss": ..., "hit": ..., "stale": ... }
```

Если в конфиге не объявлена `status_zone`, эндпоинт `/status/http/caches/<zone>/` может не выдавать число попаданий — включите зону мониторинга для сбора метрик HIT/MISS.

## Дополнительная информация

*   Очистку кэша на PURGE-запросах обязательно ограничивайте по IP/сети — открытый purge (без `allow`/`deny`) — классическая брешь.
*   `proxy_cache_purge` требует, чтобы префикс пути в `location` совпадал с `proxy_cache_key`; при разных `location` согласуйте построение ключа.
*   Для HTTP-кэша по типу "картинки/статика" с TTL используйте client-side кэширование отдельно: [Клиентское кэширование](../Nginx/Performance/Caching/client_caching.md).

## См. также

*   **[Серверное кэширование (Proxy Cache)](../Nginx/Performance/Caching/proxy_caching.md)** — полная теория и SSoT: уровни, keys_zone, инвалидация, stale.
*   **[Микрокэширование (Microcaching)](../Nginx/Performance/Caching/microcaching.md)** — практика коротких TTL для динамики.
*   **[Мониторинг кэширования](../Nginx/Performance/Caching/monitoring.md)** — метрики, Status API, Prometheus.