# Apache: Серверное кэширование (mod_cache, mod_cache_disk, mod_cache_socache)

---

## Определения

**mod_cache** — каркасный модуль Apache, реализующий серверный HTTP-кэш по стандарту RFC 9111. Кэширует ответы как локальных статических ресурсов (обычно не нужно — Apache отдаёт их напрямую), так и — что важнее — ответы, полученные через `mod_proxy` (кэш на уровне обратного прокси).

**mod_cache_disk** — персистентный диск-кэш (хранилище для `mod_cache`). Ответ сохраняется в каталог с иерархией по хэшу URL.

**mod_cache_socache** — кэш в общей памяти (shared object cache) через memcached/redis/leveldb — быстрее диска, полезен для горячих данных.

**htcacheclean** — утилита обслуживания дискового кэша: очистка по лимиту объёма, по TTL, демон-режим.

**Cache Stampede (Thundering Herd)** — всплеск запросов к Origin при одновременном истечении TTL популярного ресурса.

---

## Основные концепции

### Архитектура

```
Client ─► Apache (mod_cache) ──► mod_proxy ─► Backend (application)
            │  └── кэш копия ──┘ (CacheEnable disk /)
            │
            └── hits отдаются без обращения к Backend
```

*   Разрешается кэширование таких ответов, которые по HTTP-семантике кэшируемы: наличие `Expires`, `Cache-Control: max-age/s-maxage/public`, корректные `Last-Modified`/`ETag` для валидации.
*   Ключ кэша: схема + Host + URL-путь + query-string + учитываемые `Vary`-заголовки.
*   Управление политикой — рядом директив; политика по умолчанию следует RFC 9111.

### Когда применять

| Сценарий | Что использовать |
|---|---|
| Статика (JS/CSS/images), отдаваемая самим Apache | Клиентский кэш (`mod_expires`/`mod_headers`) — см. «Обзор Apache» (Кэширование статики) |
| Проксируемый HTML-контент/API с параметрами | `mod_cache_disk` (microcaching) |
| Горячие данные, высокий RPS, чувствительность к диску | `mod_cache_socache` (memcached/redis) |
| Внутренний кэш для SSL/балансировки | НЕ задача mod_cache — см. `apache_performance_tuning.md` |

### Отличия от Nginx proxy_cache

| Аспект | Apache mod_cache | Nginx `proxy_cache` |
|---|---|---|
| Концепция | Следует RFC 9111 (HTTP-свежесть) | Свои зоны и `proxy_cache_valid` |
| Направленность | proxy- и локальный кэш, единый ключ | строго proxy-кэш |
| Обслуживание размера | `htcacheclean` | `proxy_cache_path max_size` |
| Microcaching | `CacheDefaultExpire` + `CacheIgnoreNoLastMod` | `proxy_cache_valid 200 1s` |
| Иерархия на диске | Хэш-директории (CacheDirLevels/Length) | Файлы с суффиксами в зоне |

---

## Практические сценарии

### 1. Базовый дисковый кэш для проксируемых ответов

```apacheconf
LoadModule cache_module modules/mod_cache.so
LoadModule cache_disk_module modules/mod_cache_disk.so

<IfModule cache_disk_module>
    CacheEnable disk /
    CacheRoot /var/cache/httpd/proxy     # RHEL: /var/cache/httpd/proxy, Debian: /var/cache/apache2/mod_cache_disk
    CacheDirLevels 3
    CacheDirLength 2
    CacheDefaultExpire 3600              # TTL по умолчанию (без Expires/Cache-Control)
    CacheMaxExpire 86400                 # верхний предел свежести
    CacheMaxFileSize 10000000            # 10 МБ — не кэшировать большие файлы
    CacheMinFileSize 128
    CacheIgnoreNoLastMod on              # кэшировать даже без Last-Modified
    CacheHeader on                       # заголовок X-Cache: HIT/MISS
    CacheDetailHeader on                 # подробности X-Cache-Detail
</IfModule>
```

### 2. Microcaching для API через mod_proxy

Кэширование динамических ответов на 1–5 секунд срезает нагрузку на бэкенд кратными повторными запросами (статус страницы, агрегированные данные):

```apacheconf
ProxyPass /api/ http://127.0.0.1:8080/api/

<IfModule cache_disk_module>
    CacheEnable disk /api/
    CacheRoot /var/cache/httpd/proxy
    CacheDefaultExpire 5
    CacheIgnoreNoLastMod on
    CacheHeader on
</IfModule>
```

**Проверка:**
```bash
curl -sI http://localhost/api/summary
# → X-Cache: MISS
curl -sI http://localhost/api/summary
# → X-Cache: HIT
```

### 3. Защита от Cache Stampede (кэш-локи)

```apacheconf
CacheLock on
CacheLockMaxAge 5          # сек., ждать ответ первого запроса
CacheLockPath /var/lock/httpd/
```

### 4. Кэш в shared memory (memcached)

```apacheconf
LoadModule cache_socache_module modules/mod_cache_socache.so

<IfModule cache_socache_module>
    CacheEnable socache /hot/
    CacheSocache memcache:memcached=127.0.0.1:11211:5,tcp,noremove
    CacheDefaultExpire 120
</IfModule>
```

Требуется модуль SOCache backend (`mod_socache_memcache`). Решает проблему постоянного перестроения индекса после перезапуска Apache в отличие от диска.

### 5. Исключение приватного контента

```apacheconf
CacheDisable /admin
CacheDisable /checkout

# Не хранить Set-Cookie в кэшированных ответах
CacheIgnoreHeaders Set-Cookie
CacheStorePrivate off          # не кэшировать ответы с private
CacheStoreNoStore on           # принудительно отдавать no-store-ответы без кэша
```

---

## Операции и команды

### Обслуживание кэша (htcacheclean)

```bash
# Разовые проверки (dry-run, ничего не удаляет)
htcacheclean -n -p /var/cache/httpd/proxy -l 2G
# → (список потенциально удаляемых файлов)

# Приведение к лимиту 2 ГБ
htcacheclean -p /var/cache/httpd/proxy -l 2G

# Демон (каждые 30 минут), с правами веб-пользователя
sudo -u apache htcacheclean -d 30 -p /var/cache/httpd/proxy -l 2G
# или через systemd (unit поставляется в пакете httpd-tools на RHEL)
sudo systemctl enable --now htcacheclean
```

### Диагностика ключей кэша

```bash
# Размер кэша на диске
sudo du -sh /var/cache/httpd/proxy
# → 1.8G    /var/cache/httpd/proxy

# Просмотр структуры (двухуровневые хэш-директории)
find /var/cache/httpd/proxy -type f | head -20
# → /var/cache/httpd/proxy/03/ab/03ab12cd...header

# Проверка распределения ключей (нет ли «взрыва» по query-параметрам)
sudo du -sh /var/cache/httpd/proxy/* 2>/dev/null | sort -h | tail -5
```

### Проверка зоопарка заголовков

```bash
curl -sI https://example.com/api/data
# → x-cache: HIT
# → x-cache-detail: "stored: 1, ttl: 300, hop count: 1, lock: 0"
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Все ответы `X-Cache: MISS` | Ответы бэкенда не имеют свежести, `CacheIgnoreNoLastMod off` | Включить `CacheIgnoreNoLastMod on` и задать `CacheDefaultExpire` |
| Кэш не используется для `/admin` | `CacheDisable /admin` или `CacheStorePrivate off` | Проверить политику, `Cache-Control` бэкенда |
| `502/503` после включения кэша | Права на `CacheRoot` не у веб-пользователя; SELinux контекст | `chown apache:apache`, `restorecon -R`, контекст типа `httpd_cache_t` |
| Диск заполнен | Записи по уникальным query-строкам; нет лимита | `CacheMaxFileSize`, регулярная `htcacheclean`, нормализация query |
| Утечка конфиденциальных ответов | Кэшируются cookie/личные данные | `CacheIgnoreHeaders Set-Cookie`, `CacheDisable` для приватных путей, `CacheStorePrivate off` |
| Медленные запросы при первом попадании | Хэш-иерархия мелкая, много файлов на каталог | Увеличить `CacheDirLevels`/`CacheDirLength` |
| Содержимое меняется не мгновенно | TTL по умолчанию/`CacheIgnoreNoLastMod` перекрывает лимит времени | Снизить `CacheDefaultExpire`/`CacheMaxExpire` для микрокэша |

---

## Лучшие практики

1.  Держать кэш на отдельном диске/разделе и контролировать через `htcacheclean` (или systemd timer) — без лимита Apache не освобождает диск сам.
2.  Обязателен флаг `CacheHeader on` в staging для аудита HIT/MISS перед внедрением.
3.  Не кэшировать ответы с `Authorization`, cookies или динамические страницы пользователя — использовать `CacheDisable`.
4.  Нормализовать query-string на бэкенде или в `RewriteRule` для предотвращения «взрыва» ключей кэша.
5.  Для статики на самом vhost эффективнее клиентский кэш (`mod_expires`) — серверный кэш для proxy-контента/API.

---

## Дополнительная информация

### См. также

*   [Кэширование как инструмент веб-производительности](../Concepts/web_performance/caching.md) — RFC 9111, Cache-Control, Vary, CDN (концепции).
*   [Кэширование прокси в Nginx](../Nginx/Performance/Caching/proxy_caching.md) — аналог `proxy_cache_*` для сравнения.
*   [Обзор Apache](./apache_overview.md) — клиентское кэширование (mod_expires/mod_headers) и проксирование.