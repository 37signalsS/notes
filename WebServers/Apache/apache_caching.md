# Apache: Серверное кэширование (mod_cache, mod_cache_disk, mod_cache_socache)

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**mod_cache** — базовый модуль Apache HTTP Server, реализующий логику серверного HTTP-кэширования в соответствии со спецификацией RFC 9111 (ранее RFC 7234, RFC 2616). Модуль определяет правила кэшируемости ответов, валидацию свежести и взаимодействие с бэкендами хранения.

**mod_cache_disk** — модуль постоянного хранилища (storage provider) для `mod_cache`, сохраняющий тела ответов и HTTP-метаданные в виде файлов на локальную файловую систему в иерархическую структуру каталогов.

**mod_cache_socache** — модуль хранилища (storage provider) для `mod_cache`, использующий провайдеры разделяемой памяти (Shared Object Cache — memcached, redis, shmcb, dbm) для высокоскоростного кэширования ответов в оперативной памяти.

**htcacheclean** — системная утилита командной строки и фоновый демон для аудита и очистки дискового кэша `mod_cache_disk` по заданным лимитам дискового пространства (байты) и дескрипторов файлов (inodes), а также для точечной инвалидации URL.

**CacheQuickHandler** — директива, управляющая фазой перехвата запроса: при значении `on` кэш отдаёт ответ на самом раннем этапе (до обработки авторизации, `mod_rewrite` и директив доступа `Require`), при `off` — запрос проходит полную цепочку проверок безопасности перед отдачей из кэша.

**Cache Stampede (Thundering Herd / Dogpile)** — эффект лавинообразной перегрузки бэкенда одновременными запросами к ресурсу в момент истечения его TTL или при холодном кэше.

**Microcaching (Микрокэширование)** — паттерн кэширования динамических ответов на сверхкороткое время (от 1 до 5 секунд) для резкого снижения пиковой нагрузки на CPU и СУБД бэкенда при сохранении актуальности данных для пользователей.

**Conditional Revalidation (Условная валидация)** — механизм проверки свежести кэша через отправку бэкенду условных заголовков `If-Modified-Since` или `If-None-Match` с получением статуса `304 Not Modified` без повторной передачи тела ответа.

---

## Основные концепции

### Архитектура и цепочка фильтров

Кэширование в Apache реализовано через модульную архитектуру разделения логики кэша (`mod_cache`) и провайдеров хранения (`mod_cache_disk`, `mod_cache_socache`):

```
                       [ HTTP Клиент ]
                              │
                    (Входящий HTTP-запрос)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Apache HTTP Server                                          │
│                                                             │
│   [ Фаза Quick Handler ] ◄─── CacheQuickHandler on          │
│            │ (HIT)                   │ (MISS)               │
│            ├───────────────┐         ▼                      │
│            │               │  [ Фазы URL-rewrite / Auth ]   │
│            │               │         │                      │
│            ▼               │  [ Фаза Normal Handler ] ◄───── CacheQuickHandler off
│   ┌─────────────────┐      │         │                      │
│   │   mod_cache     │      │         ▼                      │
│   │ (HTTP RFC 9111) │      │  ┌───────────────────────┐     │
│   └────────┬────────┘      │  │  mod_proxy / Handler  │     │
│            │               │  └──────────┬────────────┘     │
│    (Storage Provider)      │             │                  │
│     ├── mod_cache_disk     │      (Запрос к бэкенду)        │
│     └── mod_cache_socache  │             ▼                  │
│            │               │       [ Origin App ]           │
│            ▼               │             │                  │
│     ┌──────────────┐       │      (HTTP-ответ)              │
│     │ Файлы диска /│       │             ▼                  │
│     │ Память SHM   │       │  ┌───────────────────────┐     │
│     └──────────────┘       │  │  CACHE_SAVE (Filter)  │     │
│            │ (Отдача тела) │  └──────────┬────────────┘     │
│            └───────────────┼─────────────┘                  │
│                            ▼                                │
│                   [ CACHE_OUT (Filter) ]                    │
│                            │                                │
└────────────────────────────┼────────────────────────────────┘
                             ▼
                    (HTTP-ответ клиенту)
```

Входящий запрос обрабатывается одной из двух моделей:
1. **Quick Handler (`CacheQuickHandler on`, по умолчанию):** запрос перехватывается на стадии `post_read_request`. Если ресурс найден в кэше и свеж, он возвращается немедленно. Фазы аутентификации (`mod_auth_*`), авторизации (`mod_authz_*`), трансляции URL (`mod_rewrite` в контексте Directory/Location) и обработчики заголовков безопасности игнорируются. Обеспечивает минимальный overhead и максимальный RPS.
2. **Normal Handler (`CacheQuickHandler off`):** `mod_cache` работает как стандартный фильтр контента. Запрос проходит проверку директив `Require`, аутентификацию, фильтры безопасности и переменные окружения. Ответ отдаётся из кэша только в случае успешного прохождения всех проверок.

### Правила кэшируемости по RFC 9111

`mod_cache` сохраняет ответ только в том случае, если выполнены условия спецификации:
- Метод запроса кэшируем (по умолчанию `GET` и `HEAD`).
- Код ответа сервера входит в список кэшируемых: `200 OK`, `203 Non-Authoritative Information`, `300 Multiple Choices`, `301 Moved Permanently`, `410 Gone`, либо явно разрешён заголовками для `206 Partial Content`.
- Ответ содержит явную информацию о свежести:
  - Заголовок `Cache-Control: max-age=N`, `s-maxage=N` или `public`.
  - Заголовок `Expires`.
- Ответ **без** явной свежести кэшируется только при наличии `Last-Modified` (эвристический расчет свежести по формуле `(Date - Last-Modified) * CacheLastModifiedFactor`) либо при явном включении директивы `CacheIgnoreNoLastMod on` (в этом случае применяется `CacheDefaultExpire`).
- В ответе отсутствуют запрещающие директивы: `Cache-Control: no-store` (если не переопределено `CacheStoreNoStore on`), `Cache-Control: private` (если не переопределено `CacheStorePrivate on`).
- Заголовок `Vary` не содержит значение `*`. При наличии конкретных полей (например, `Vary: Accept-Encoding`) Apache сохраняет отдельные варианты ответа для каждой комбинации значений.

### Структура дискового хранилища (mod_cache_disk)

Каждый кэшируемый ресурс преобразуется в хэш-ключ (256-битный SHA256 от канонического URL). На диске в каталоге `CacheRoot` создаются два файла с одинаковым хэш-именем:
- `.header` — бинарные метаданные (URI ответа, HTTP-статус, временные метки создания и истечения TTL, заголовки запроса и ответа).
- `.data` — точное тело HTTP-ответа без изменений.

```
/var/cache/httpd/proxy/
├── 0/
│   └── 3/
│       └── ab/
│           ├── 03ab89cdef1234567890abcdef1234567890abcdef1234567890abcdef.header
│           └── 03ab89cdef1234567890abcdef1234567890abcdef1234567890abcdef.data
```

Иерархия каталогов определяется директивами:
- `CacheDirLevels` (число уровней подкаталогов, по умолчанию 2).
- `CacheDirLength` (число символов хэша на каталог, по умолчанию 2).

Распределение каталогов предотвращает деградацию производительности файловой системы (ext4/XFS), избегая размещения сотен тысяч файлов в одной директории. При `Levels=2` и `Length=2` создается $16^2 \times 16^2 = 256 \times 256 = 65\,536$ конечных каталогов.

### Кэш в разделяемой памяти (mod_cache_socache)

В отличие от дискового хранилища, `mod_cache_socache` держит данные в RAM:
- `memcache` — через демон Memcached (пул серверов).
- `redis` — через инстанс Redis (поддерживается с Apache 2.4.39 через `mod_socache_redis`).
- `shmcb` — разделяемый циклический буфер памяти в рамках одного хоста (высокая скорость, но ограниченный объем, разделяется между всеми процессами MPM).
- `dbm` — локальный файл базы данных DBM.

Плюсы `socache`: полное отсутствие дискового I/O, устойчивость к фрагментации диска, идеален для горячих JSON API и микрокэширования. Минусы: ограниченный размер записи (`CacheSocacheMaxSize`, по умолчанию 100 КБ).

### Сравнение с Nginx proxy_cache

| Аспект | Apache `mod_cache` | Nginx `proxy_cache` |
|---|---|---|
| **Следование стандартам** | Строгое следование RFC 9111 (свежесть, ETag, 304, Vary) | Своя логика зон и принудительный override через `proxy_cache_valid` |
| **Применимость** | Локальные хэндлеры + `mod_proxy` (единый кэш-ключ) | Исключительно обратный прокси (`proxy_pass`) |
| **Очистка и размер** | Внешний демон / cron `htcacheclean` | Встроенный менеджер кэша (`cache manager process`) |
| **Формат хранилища** | Раздельные файлы `.header` и `.data` | Единый файл (заголовок + тело) с контрольной суммой |
| **Блокировка Stampede** | `CacheLock on` + `CacheLockPath` | `proxy_cache_lock on` + `proxy_cache_lock_age` |
| **Микрокэширование** | `CacheDefaultExpire` + `CacheIgnoreNoLastMod` | `proxy_cache_valid 200 1s` |
| **Хранение в RAM** | Встроенный `mod_cache_socache` (Redis/Memcached/SHM) | Только через сторонние модули или `tmpfs` |

---

## Практические сценарии

### 1. Подготовка окружения и включение модулей

В зависимости от дистрибутива Linux структура каталогов и механизм активации модулей различаются.

#### Debian / Ubuntu

```bash
# Установка Apache и утилит обслуживания
sudo apt update && sudo apt install -y apache2 apache2-utils

# Активация необходимых модулей
sudo a2enmod cache cache_disk proxy proxy_http headers

# Проверка загруженных модулей
apache2ctl -M | grep -E "cache|proxy"
# → cache_module (shared)
# → cache_disk_module (shared)
# → proxy_module (shared)
# → proxy_http_module (shared)
```

#### RHEL / Rocky Linux / AlmaLinux

```bash
# Установка Apache и утилит
sudo dnf install -y httpd httpd-tools

# Проверка наличия модулей в конфигурации
httpd -M | grep -E "cache|proxy"
# → cache_module (shared)
# → cache_disk_module (shared)

# Каталог кэша по умолчанию
sudo mkdir -p /var/cache/httpd/proxy
sudo chown -R apache:apache /var/cache/httpd/proxy
sudo chmod 700 /var/cache/httpd/proxy
```

### 2. Производственная конфигурация дискового кэша для Reverse Proxy

Полнофункциональный виртуальный хост с проксированием на бэкенд, дисковым кэшированием, защитой метаданных и подробными отладочными заголовками:

```apacheconf
# /etc/apache2/sites-available/cached-proxy.conf (Debian)
# /etc/httpd/conf.d/cached-proxy.conf (RHEL)

<VirtualHost *:80>
    ServerName app.example.internal
    ServerAdmin admin@example.internal

    # Логирование с фиксацией статуса кэша
    CustomLog /var/log/apache2/cached_access.log combined_cache
    ErrorLog /var/log/apache2/cached_error.log

    ProxyPreserveHost On
    ProxyPass /api/ http://10.10.10.50:8080/api/
    ProxyPassReverse /api/ http://10.10.10.50:8080/api/

    <IfModule mod_cache.so>
        <IfModule mod_cache_disk.so>
            # Корневой каталог кэша
            CacheRoot /var/cache/apache2/mod_cache_disk
            # Для RHEL: CacheRoot /var/cache/httpd/proxy

            # Включение дискового кэша для заданного URL-пути
            CacheEnable disk /api/

            # Структура каталогов (2 уровня по 2 символа = 65536 каталогов)
            CacheDirLevels 2
            CacheDirLength 2

            # Границы размера кэшируемых файлов (в байтах)
            CacheMinFileSize 1
            CacheMaxFileSize 10485760          # 10 МБ максимум на объект

            # Политика времени жизни (в секундах)
            CacheDefaultExpire 3600            # 1 час при отсутствии Cache-Control
            CacheMaxExpire 86400               # 24 часа — абсолютный предел
            CacheMinExpire 60                  # 1 минута — минимальный порог

            # Поведение заголовков
            CacheHeader on                     # Добавляет X-Cache: HIT|MISS from host
            CacheDetailHeader on               # Добавляет X-Cache-Detail с причиной
        </IfModule>
    </IfModule>
</VirtualHost>
```

**Проверка синтаксиса и перезагрузка:**
```bash
sudo apachectl configtest
# → Syntax OK
sudo systemctl reload apache2 # или httpd на RHEL
```

**Проверка работы кэша через curl:**
```bash
# Первый запрос — холодный кэш (MISS)
curl -s -D - -o /dev/null http://app.example.internal/api/items
# → HTTP/1.1 200 OK
# → X-Cache: MISS from app.example.internal
# → X-Cache-Detail: "cache miss: attempting entity save"

# Повторный запрос — попадание в кэш (HIT)
curl -s -D - -o /dev/null http://app.example.internal/api/items
# → HTTP/1.1 200 OK
# → X-Cache: HIT from app.example.internal
# → X-Cache-Detail: "cache hit: response freshness calculated"
```

### 3. Настройка Microcaching для высоконагруженных динамических API

Микрокэширование устраняет пиковые нагрузки на приложения, кэшируя ответы бэкенда на 2 секунды. При 5000 RPS к бэкенду будет проходить максимум 1 запрос в 2 секунды на уникальный URL:

```apacheconf
<Location "/api/v1/metrics">
    CacheEnable disk /api/v1/metrics
    
    # Кэшировать ответы, даже если бэкенд не выставил Last-Modified
    CacheIgnoreNoLastMod on
    
    # Жесткий лимит свежести: 2 секунды
    CacheDefaultExpire 2
    CacheMaxExpire 2
    CacheMinExpire 1
    
    # Игнорировать пользовательский заголовок Cache-Control: no-cache,
    # чтобы клиенты не пробивали кэш на бэкенд
    CacheIgnoreCacheControl on
</Location>
```

### 4. Защита от Cache Stampede (Dogpile Effect)

При истечении TTL у популярного ресурса сотни параллельных запросов одновременно обращаются к бэкенду. Для предотвращения сбоя включается механизм мьютексов (`CacheLock`):

```apacheconf
<IfModule mod_cache.so>
    # Включение межпроцессной блокировки
    CacheLock on
    
    # Каталог для временных lock-файлов
    CacheLockPath /var/run/apache2/cache_lock/
    # Для RHEL: CacheLockPath /var/run/httpd/cache_lock/
    
    # Максимальное время удержания блокировки первым запросом (в секундах)
    CacheLockMaxAge 5
</IfModule>
```

**Механика:** Первый воркер переводит ресурс в состояние захвата блокировки и отправляет запрос на бэкенд. Все последующие запросы ожидают ответа первого воркера либо отдают предыдущую копию, пока не истечет `CacheLockMaxAge`.

```bash
# Создание каталога блокировок с корректными правами
sudo mkdir -p /var/run/apache2/cache_lock
sudo chown www-data:www-data /var/run/apache2/cache_lock
sudo chmod 700 /var/run/apache2/cache_lock
```

### 5. Grace Mode: Отдача устаревшего кэша при сбоях бэкенда (Stale-on-Error)

Директива `CacheStaleOnError` позволяет серверу отдавать клиентам уже устаревший (stale) кэшированный ответ, если бэкенд возвращает ошибку `500 Internal Server Error`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout` или недоступен по сети:

```apacheconf
<IfModule mod_cache.so>
    # Разрешить отдачу устаревшего кэша при падении бэкенда (включено по умолчанию)
    CacheStaleOnError on
</IfModule>
```

Если в кэше есть старая копия ресурса, клиент получит `200 OK` с устаревшими данными и заголовком `Warning: 110` (Response is Stale), а сервис сохранит доступность при кратковременных авариях бэкенда.

### 6. Защита от обхода кэша и атак на исчерпание памяти (Cache Key Management)

Злоумышленники или некорректно настроенные клиенты могут исчерпать файловые дескрипторы или диск, генерируя уникальные query-параметры (`?nocache=123`, сессионные ID) или отправляя заголовки `Cache-Control: no-cache`.

```apacheconf
<IfModule mod_cache.so>
    # 1. Запретить клиентам принудительно обходить кэш
    CacheIgnoreCacheControl on

    # 2. Исключить сессионные маркеры из ключа кэша, чтобы они не дробили кэш
    CacheIgnoreURLSessionIdentifiers jsessionid phpsessid sid token

    # 3. Полное игнорирование query-string для сугубо статических разделов
    <Location "/catalog/static-thumbs">
        CacheIgnoreQueryString on
    </Location>
</IfModule>
```

### 7. Кэширование в Shared Memory через Redis / Memcached (mod_cache_socache)

Для сценариев с высоким RPS и чувствительностью к I/O задержкам диска используется разделяемая память.

```apacheconf
# Загрузка провайдеров памяти
LoadModule cache_socache_module modules/mod_cache_socache.so
LoadModule socache_redis_module modules/mod_socache_redis.so
# Либо LoadModule socache_memcache_module modules/mod_socache_memcache.so

<IfModule mod_cache_socache.so>
    # Включение кэширования в Redis для API
    CacheEnable socache /api/v2/fast/
    
    # Синтаксис подключения к Redis (Apache 2.4.39+)
    CacheSocache redis:127.0.0.1:6379
    
    # Альтернатива: Memcached пул
    # CacheSocache memcache:10.0.0.10:11211,10.0.0.11:11211:5,tcp,noremove
    
    # Ограничение размера одного объекта в памяти (в байтах, по умолчанию 102400)
    CacheSocacheMaxSize 262144        # 256 КБ
    
    # Пределы хранения по времени (сек)
    CacheSocacheMinTime 10
    CacheSocacheMaxTime 7200
</IfModule>
```

### 8. Изоляция приватного контента и безопасность (Cache Control)

Неправильное кэширование приводит к утечке сессионных cookie (`Set-Cookie`) и персональных страниц одного пользователя другому.

```apacheconf
<IfModule mod_cache.so>
    # Полное отключение кэширования для чувствительных зон
    CacheDisable /admin
    CacheDisable /user/profile
    CacheDisable /auth/
    CacheDisable /billing/

    # Безопасность: никогда не сохранять Set-Cookie в кэше
    CacheIgnoreHeaders Set-Cookie

    # Не сохранять ответы, помеченные как private
    CacheStorePrivate off

    # Не сохранять ответы, помеченные как no-store
    CacheStoreNoStore off

    # ОБЯЗАТЕЛЬНО: Если используется авторизация по IP или логину,
    # перевести кэш в Normal Handler, чтобы не отдавать защищенный контент анонимам!
    CacheQuickHandler off
</IfModule>
```

> [!WARNING]
> Если на защищенный каталог распространяется `CacheQuickHandler on`, а ресурс закэширован, Apache отдаст ответ клиенту без проверки директивы `Require valid-user` или `Require ip`. Для любых зон с авторизацией используйте либо `CacheDisable`, либо переключайте `CacheQuickHandler off`.

---

## Операции и команды

### Сводка опций утилиты htcacheclean

Утилита `htcacheclean` управляет дисковым хранилищем `mod_cache_disk`.

| Флаг | Описание |
|---|---|
| `-p path` | **Обязательный.** Путь к корневому каталогу дискового кэша (`CacheRoot`). |
| `-l limit` | Лимит общего объема кэша. Поддерживает суффиксы: `K` (килобайты), `M` (мегабайты), `G` (гигабайты). |
| `-L limit` | Лимит общего количества дескрипторов файлов (inodes) в кэше. Предотвращает исчерпание inodes. |
| `-d interval` | Запуск в режиме фонового демона с повторением очистки каждые `interval` минут. |
| `-D` | Режим демона без отсоединения от консоли (foreground). Необходим для systemd и контейнеров. |
| `-v` | Подробный вывод (verbose) в консоль или лог. |
| `-t` | Удаление пустых подкаталогов в иерархии кэша (truncate). |
| `-r` | Глубокая очистка (clean thoroughly). Должна запускаться только при **остановленном** Apache. |
| `-n` | Режим пониженной нагрузки на диск (be nice) — паузы между операциями ввода-вывода. **Внимание:** файлы при этом удаляются! |
| `-a` | Вывод списка всех URL, находящихся в кэше на текущий момент. |
| `-A` | Вывод списка всех URL вместе с метаданными (время создания, истечение срока, размер). |
| `-P file` | Путь к PID-файлу демона при запуске с ключом `-d`. |

### Ручные сценарии обслуживания

```bash
# 1. Просмотр списка закэшированных URL и их метаданных
sudo htcacheclean -p /var/cache/apache2/mod_cache_disk -A
# → http://app.example.internal:80/api/items 200 1284 3600 1718000000 1718003600

# 2. Однократная очистка кэша до лимита 2 ГБ и 200 000 inodes
sudo -u www-data htcacheclean -v -t -p /var/cache/apache2/mod_cache_disk -l 2G -L 200000
# → Cleaned: 1420 files, 312 MB freed.

# 3. Принудительная инвалидация (удаление) одного конкретного URL из кэша
sudo -u www-data htcacheclean -v -p /var/cache/apache2/mod_cache_disk "http://app.example.internal/api/items"
# → Deleting: http://app.example.internal/api/items
# → 1 entries deleted.

# 4. Аудит размера кэша и количества занятых inodes
sudo du -sh /var/cache/apache2/mod_cache_disk
# → 1.8G    /var/cache/apache2/mod_cache_disk

sudo df -i /var/cache/apache2/mod_cache_disk
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sda2      1310720 185400 1125320   15% /
```

### Настройка службы htcacheclean в systemd

В производственной среде очистка дискового пространства должна управляться через systemd.

#### Вариант для Debian / Ubuntu

В Debian пакет `apache2-utils` поставляет файл конфигурации `/etc/default/apache-htcacheclean`:

```bash
# /etc/default/apache-htcacheclean
HTCACHECLEAN_RUN=yes
HTCACHECLEAN_MODE=daemon
HTCACHECLEAN_SIZE=2048M
HTCACHECLEAN_PATH=/var/cache/apache2/mod_cache_disk
HTCACHECLEAN_INTERVAL=15
HTCACHECLEAN_OPTIONS="-t"
```

Активация и запуск службы:
```bash
sudo systemctl enable --now apache-htcacheclean
sudo systemctl status apache-htcacheclean
# → Active: active (running)
```

#### Вариант для RHEL / Rocky Linux

В RHEL параметры задаются в `/etc/sysconfig/htcacheclean`:

```bash
# /etc/sysconfig/htcacheclean
INTERVAL=15
CACHE_ROOT=/var/cache/httpd/proxy
LIMIT=2048M
OPTIONS="-t -L 300000"
```

Активация службы:
```bash
sudo systemctl enable --now htcacheclean
sudo systemctl status htcacheclean
# → Active: active (running)
```

### Настройка логирования и метрик кэша

Для отслеживания эффективности кэширования (Cache Hit Ratio) на уровне SRE/DevOps необходимо включить логирование статуса кэша в `CustomLog`:

```apacheconf
# Формат лога с фиксацией X-Cache, времени генерации (%D мкс) и байт (%B)
LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" cache:%{X-Cache}o detail:\"%{X-Cache-Detail}o\" resp_time:%D" combined_cache

# Использование формата для конкретного VirtualHost
CustomLog /var/log/apache2/cached_access.log combined_cache
```

**Анализ логов в CLI:**
```bash
# Подсчет соотношения HIT и MISS за последние 10 000 строк
tail -n 10000 /var/log/apache2/cached_access.log | \
awk '{print $11}' | sort | uniq -c
# →   7450 cache:HIT
# →   2350 cache:MISS
# →    200 cache:-

# Расчет Hit Ratio: 7450 / (7450 + 2350) = 76.0%
```

Для Prometheus парсинг логов осуществляется утилитой `mtail` или агентами `Vector`/`Fluentbit`, передающими счетчики `apache_cache_requests_total{status="HIT|MISS|REVALIDATE"}` в Grafana.

---

## Диагностика и устранение неполадок

### Таблица типичных неисправностей

| Симптом | Вероятная причина | Диагностика и устранение |
|---|---|---|
| Все запросы возвращают `X-Cache: MISS` | 1. Бэкенд не отдает `Cache-Control` и `Last-Modified`.<br>2. Присутствует заголовок `Set-Cookie`.<br>3. Ответ содержит `Pragma: no-cache`. | Проверить ответ бэкенда: `curl -sI http://backend/api`. Включить `CacheDetailHeader on`, проверить `X-Cache-Detail`. При отсутствии валидаторов добавить `CacheIgnoreNoLastMod on` и `CacheDefaultExpire`. Настроить `CacheIgnoreHeaders Set-Cookie`. |
| Ошибка `500 Internal Server Error` или запись в `error.log`: *Could not create a cache lock* | Нет прав на каталог `CacheLockPath` или переполнен `/tmp`. | Проверить права: `ls -ld $(dirname $(grep -i CacheLockPath /etc/apache2/ -r \| awk '{print $2}'))`. Каталог должен принадлежать пользователю `www-data` (`apache`) с правами `0700`. |
| Исчерпание диска (`No space left on device`), хотя объем данных мал | Исчерпаны свободные inodes из-за миллионов мелких кэш-файлов. | Проверить `df -i`. Настроить регулярную очистку по лимиту inodes через `htcacheclean -L 200000`. Увеличить `CacheMinFileSize` (не кэшировать файлы меньше 512 байт). |
| Отказ доступа или `502` при попытке записи кэша на RHEL | Запрет SELinux на запись процессов `httpd` в каталог кэша. | Проверить контекст: `ls -dZ /var/cache/httpd/proxy`. Исправить контекст: `sudo semanage fcontext -a -t httpd_cache_t "/var/cache/httpd/proxy(/.*)?" && sudo restorecon -Rv /var/cache/httpd/proxy`. |
| Анонимный пользователь видит закрытую страницу другого пользователя | 1. Бэкенд отдал закрытую страницу без `Cache-Control: private`.<br>2. Кэш сработал через `CacheQuickHandler on`. | Отключить кэширование закрытых путей через `CacheDisable /profile`. Переключить `CacheQuickHandler off`, чтобы модуль авторизации проверял токен каждого клиента. |
| При обновлении бэкенда клиенты часами видят старые данные | Слишком большой `CacheDefaultExpire` или отсутствие вызова инвалидации. | Уменьшить `CacheDefaultExpire` до 60–300 секунд. При деплое выполнять принудительное удаление устаревших данных через `htcacheclean -p <path> -r` (на остановленном сервисе) или точечное удаление URL. |
| Высокий I/O wait на сервере при работе `htcacheclean` | Демон очистки сканирует всю иерархию диска на максимальной скорости. | Добавить флаг `-n` (be nice) в параметры `htcacheclean`, чтобы утилита делала паузы при высокой утилизации диска. |

### Пошаговый алгоритм диагностики через curl

Для выяснения точной причины, почему ответ не закэшировался:

```bash
# 1. Запрос с выводом всех заголовков ответа
curl -v -s -o /dev/null http://app.example.internal/api/item/42 2>&1 | grep -E "(< HTTP|< X-Cache|< Cache-Control|< Set-Cookie|< Expires|< Last-Modified|< Vary)"
```

**Интерпретация результатов:**
- Если `X-Cache-Detail: "cache miss: entity has no expiration date"` → бэкенд не отдал ни `Expires`, ни `Cache-Control: max-age`. Решение: настроить `CacheDefaultExpire` и `CacheIgnoreNoLastMod on`.
- Если `X-Cache-Detail: "cache miss: response has Set-Cookie"` → Apache блокирует сохранение из-за cookies. Решение: `CacheIgnoreHeaders Set-Cookie` (убедившись, что контент не персонализирован).
- Если `X-Cache-Detail: "cache miss: query-string ignored but not allowed"` → в запросе есть query-string, а `CacheIgnoreQueryString` выключен.
- Если отсутствует заголовок `X-Cache` вовсе → модуль `mod_cache` не активен для данного URL-пути (проверить соответствие префикса в `CacheEnable disk <prefix>`).

---

## Лучшие практики

1. **Изолированный раздел файловой системы под кэш:** Размещайте `CacheRoot` на отдельном логическом томе (LVM или отдельный диск) либо в оперативной памяти (`tmpfs` для ультрабыстрого микрокэша). Переполнение кэша не должно приводить к отказу корневой файловой системы `/` или переполнению `/var/log`.
2. **Обязательное ограничение по inodes:** При настройке `htcacheclean` всегда указывайте не только лимит по объему (`-l`), но и лимит по дескрипторам (`-L`). На высоконагруженных API дисковое пространство может быть заполнено лишь на 20%, а свободные inodes исчерпаются полностью, вызвав отказ сервера.
3. **Безопасность авторизованных зон (`CacheQuickHandler off`):** Всегда отключайте `CacheQuickHandler` для VirtualHost, где используются директивы разграничения прав доступа (`Require ip`, `Require valid-user`, `mod_authz_*`), либо жестко исключайте такие URL через `CacheDisable`.
4. **Защита от утечки сессионных cookie:** Всегда прописывайте `CacheIgnoreHeaders Set-Cookie` в глобальной конфигурации `mod_cache`. Это предотвратит ситуацию, когда сессионный идентификатор администратора сохраняется в кэше и отдается анонимным пользователям.
5. **Исключение эндпоинтов мониторинга и healthcheck:** Системы оркестрации (Keepalived, HAProxy, балансировщики) опрашивают эндпоинты `/healthz` или `/ping` каждую секунду. Закэшированный ответ `200 OK` скроет реальное падение бэкенда. Всегда задавайте `CacheDisable /healthz`.
6. **Нормализация параметров запроса (Query String):** Клиенты могут переставлять параметры местами (`?sort=asc&page=1` и `?page=1&sort=asc`). Для Apache это два разных ключа кэша. Нормализуйте порядок аргументов с помощью `mod_rewrite` до передачи в кэш.
7. **Тестирование перед продакшеном:** Держите включенными `CacheHeader on` и `CacheDetailHeader on` в среде staging для отладки кэшируемости API до релиза.

---

## Дополнительная информация

### См. также

*   [Обзор Apache](./apache_overview.md) — клиентское кэширование (`mod_expires`, `mod_headers`), архитектура MPM и базовая конфигурация.
*   [Продвинутый Reverse Proxy в Apache](./apache-reverse-proxy-advanced.md) — балансировка, пулы соединений `mod_proxy_balancer` и таймауты.
*   [Тюнинг производительности Apache](./apache_performance_tuning.md) — параметры MPM, сокеты, TLS session cache (`SSLSessionCache`).
*   [Харденинг Apache](./apache_hardening.md) — безопасная конфигурация заголовков, ограничение методов и защита от атак.
*   [Кэширование прокси в Nginx](../Nginx/Performance/Caching/proxy_caching.md) — реализация серверного кэширования в Nginx для сравнения архитектур.
*   [Концепции веб-кэширования](../Concepts/web_performance/caching.md) — спецификация RFC 9111, заголовки свежести и валидации.