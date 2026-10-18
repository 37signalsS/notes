# Nginx и OpenResty: разработка и эксплуатация логики на Lua (lua-nginx-module)

**Актуально для:** OpenResty 1.25+ / 1.27+, Nginx 1.26+ с `ngx_http_lua_module` (LuaJIT 2.1), Redis 7.x+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по интеграции языка Lua и платформы OpenResty с веб-сервером Nginx для решения задач высокопроизводительной динамической маршрутизации, валидации токенов и распределенного троттлинга:
- [nginx_njs_module.md](./nginx_njs_module.md) — рассматривает модуль NJS (Nginx JavaScript), являющийся нативным решением F5/Nginx, но обладающий меньшей экосистемой библиотек и отличающийся по модели выполнения от LuaJIT.
- [nginx_http_phases_and_directive_order.md](./nginx_http_phases_and_directive_order.md) — описывает базовые 11 фаз конвейера Nginx, в которые встраиваются хуки `_by_lua`.
- [Security/nginx_security_guide.md](../Security/nginx_security_guide.md) — описывает общие механизмы WAF и ограничения скорости без привязки к внешним хранилищам типа Redis.

---

## 1. Определения

- **OpenResty** — полнофункциональная веб-платформа на базе ядра Nginx, оптимизированного интерпретатора LuaJIT и набора высокопроизводительных библиотек `lua-resty-*`, предназначенная для создания быстрых API-шлюзов и микросервисов.
- **`lua-nginx-module` (`ngx_http_lua_module`)** — модуль Nginx, интегрирующий виртуальную машину LuaJIT непосредственно в цикл обработки событий (event loop) веб-сервера.
- **Cosocket (Корутинный сокет)** — ключевая технология OpenResty: неблокирующий сетевой сокет (TCP, UDP, SSL), управляемый сопрограммами Lua (coroutines). Для разработчика код выглядит как синхронный процедурный вызов (без callback hell), но под капотом исполняется полностью асинхронно через epoll.
- **`lua_shared_dict`** — сегмент разделяемой памяти (shared memory) между всеми рабочими процессами Nginx, используемый для потокобезопасного хранения кэша, состояний и счетчиков rate limiting со сверхвысокой скоростью доступа O(1).
- **`balancer_by_lua_block`** — директива OpenResty, позволяющая программно выбирать целевой IP-адрес и порт бэкенда для каждого HTTP-запроса в рантайме без перезагрузки конфигурации (`reload`).

---

## 2. Архитектура: точки внедрения Lua в конвейер Nginx

Модуль `lua-nginx-module` предоставляет специальные директивы-хуки, встраивающиеся в стандартные фазы конвейера обработки запросов Nginx:

```text
Жизненный цикл мастер-процесса Nginx:
[ init_by_lua ]          ──► Инициализация библиотек при старте / reload
[ init_worker_by_lua ]   ──► Запуск фоновых таймеров в каждом worker

Жизненный цикл HTTP-запроса:
 1. NGX_HTTP_SERVER_REWRITE_PHASE  ──► [ rewrite_by_lua ] (модификация URI до выбора location)
 2. NGX_HTTP_REWRITE_PHASE         ──► [ rewrite_by_lua ] (внутри выбранного location)
 3. NGX_HTTP_ACCESS_PHASE          ──► [ access_by_lua ]  (проверка JWT, ACL, Rate Limit в Redis)
 4. NGX_HTTP_CONTENT_PHASE         ──► [ content_by_lua ] (генерация ответа без бэкенда)
                                    ИЛИ [ proxy_pass ] ──► [ balancer_by_lua ] (выбор пира)
 5. ФИЛЬТРАЦИЯ ОТВЕТА:
    - Заголовки бэкенда            ──► [ header_filter_by_lua ] (модификация/добавление headers)
    - Тело ответа (потоково)       ──► [ body_filter_by_lua ]   (модификация payload на лету)
 6. NGX_HTTP_LOG_PHASE             ──► [ log_by_lua ]           (асинхронный экспорт телеметрии)
```

### Сравнение OpenResty (LuaJIT) и Nginx NJS

| Критерий | OpenResty (LuaJIT) | Nginx NJS (JavaScript) |
|---|---|---|
| **Среда исполнения** | Высокооптимизированный JIT-компилятор (LuaJIT) | Легковесный интерпретатор ECMAScript без JIT |
| **Производительность CPU** | **Экстремальная** (близка к чистому Си) | Высокая (но уступает JIT при сложных циклах) |
| **Работа с сетью (I/O)** | Полноценные cosockets (Redis, MySQL, PG, Kafka) | HTTP-подзапросы (`r.subrequest`), fetch |
| **Экосистема библиотек** | Огромная (`lua-resty-jwt`, `lua-resty-openidc`, `lua-resty-redis`, Kong) | Развивающаяся (базовый крипто-стек, парсеры) |
| **Динамический upstream** | Да (`balancer_by_lua`) | Ограниченно (в связке с Angie / Nginx Plus) |
| **Сложность внедрения** | Требует OpenResty или сборку динамического модуля | Поставляется официальным пакетом Nginx |

---

## 3. Практические сценарии

### Сценарий 1: Проверка и валидация JWT-токена «на лету» без похода в бэкенд

Nginx валидирует подпись JWT (HMAC-SHA256 или RSA) прямо на фазе `ACCESS`. Неавторизованные запросы отсекаются с кодом 401 за доли миллисекунды, снимая паразитную нагрузку с бэкенд-серверов.

```nginx
# /etc/nginx/conf.d/jwt_gateway.conf
lua_package_path "/usr/local/openresty/lualib/?.lua;;";

server {
    listen 80;
    server_name api.company.internal;

    location /api/private/ {
        # Точка входа авторизации
        access_by_lua_block {
            local jwt = require("resty.jwt")
            local auth_header = ngx.var.http_Authorization

            if not auth_header then
                ngx.status = ngx.HTTP_UNAUTHORIZED
                ngx.header.content_type = "application/json"
                ngx.say('{"error": "Missing Authorization header"}')
                return ngx.exit(ngx.HTTP_UNAUTHORIZED)
            end

            -- Извлечение Bearer токена
            local _, _, token = string.find(auth_header, "Bearer%s+(.+)")
            if not token then
                ngx.status = ngx.HTTP_UNAUTHORIZED
                ngx.header.content_type = "application/json"
                ngx.say('{"error": "Invalid Bearer format"}')
                return ngx.exit(ngx.HTTP_UNAUTHORIZED)
            end

            -- Проверка подписи токена секретным ключом
            local secret = "MyUltraSecureSharedSecretKey2026"
            local jwt_obj = jwt:verify(secret, token)

            if not jwt_obj.verified then
                ngx.log(ngx.WARN, "JWT verification failed: ", jwt_obj.reason)
                ngx.status = ngx.HTTP_UNAUTHORIZED
                ngx.header.content_type = "application/json"
                ngx.say('{"error": "Invalid token: ' .. tostring(jwt_obj.reason) .. '"}')
                return ngx.exit(ngx.HTTP_UNAUTHORIZED)
            end

            -- Передача извлеченного userId в заголовок бэкенду
            ngx.req.set_header("X-User-ID", jwt_obj.payload.sub)
            ngx.req.set_header("X-User-Role", jwt_obj.payload.role)
        }

        proxy_pass http://backend_app_cluster;
        proxy_set_header Host $host;
    }
}
```

---

### Сценарий 2: Распределенный Rate Limiting через Redis (`lua-resty-redis`)

Стандартный `limit_req` работает строго в памяти одной ноды Nginx. Если перед сервисом стоит кластер из нескольких балансировщиков, клиент может обойти лимиты. Решение — атомарный счетчик в общем Redis:

```nginx
# Выделение разделяемой памяти для локального кэша ответов Redis
lua_shared_dict redis_cache 10m;

server {
    listen 80;
    server_name api.company.internal;

    location /api/throttled/ {
        access_by_lua_block {
            local redis = require("resty.redis")
            local red = redis:new()

            red:set_timeout(200) -- Таймаут 200 мс, чтобы не тормозить трафик

            local ok, err = red:connect("127.0.0.1", 6379)
            if not ok then
                -- При недоступности Redis пропускаем запрос (Fail-Open паттерн), чтобы не ломать сервис
                ngx.log(ngx.ERR, "Failed to connect to Redis: ", err)
                return
            end

            local client_ip = ngx.var.remote_addr
            local key = "rate:" .. client_ip

            -- Атомарный конвейер Redis: INCR + EXPIRE (лимит 100 запросов в минуту)
            red:init_pipeline()
            red:incr(key)
            red:expire(key, 60)
            local res, err = red:commit_pipeline()

            if not res then
                ngx.log(ngx.ERR, "Redis pipeline error: ", err)
                return
            end

            local current_rps = res[1]
            if current_rps > 100 then
                ngx.status = 429
                ngx.header["Retry-After"] = "60"
                ngx.header.content_type = "application/json"
                ngx.say('{"error": "Too Many Requests. Limit: 100 req/min"}')
                return ngx.exit(429)
            end

            -- Возврат соединения в пул keepalive OpenResty
            red:set_keepalive(10000, 100)
        }

        proxy_pass http://backend_app_cluster;
    }
}
```

---

### Сценарий 3: Динамическая балансировка в runtime (`balancer_by_lua_block`)

Маршрутизация запроса на конкретный инстанс бэкенда без перезагрузки Nginx (Service Discovery из разделяемой памяти или локального кэша):

```nginx
upstream dynamic_cluster {
    server 0.0.0.1; # Плейсхолдер ядра
    balancer_by_lua_block {
        local balancer = require("ngx.balancer")
        
        -- Выбор бэкенда на основе логики Lua (хеш, round-robin или проверка доступности)
        local backend_ip = "10.0.2.15"
        local backend_port = 8080

        -- Атомарная подмена адреса сокета для текущей сессии
        local ok, err = balancer.set_current_peer(backend_ip, backend_port)
        if not ok then
            ngx.log(ngx.ERR, "Failed to set balancer peer: ", err)
            return ngx.exit(500)
        end
    }
    keepalive 32;
}

server {
    listen 80;
    location / {
        proxy_pass http://dynamic_cluster;
    }
}
```

---

## 4. Диагностика и профилирование

### 4.1 Проверка компиляции Lua и синтаксиса

```bash
# Проверка конфигурации Nginx/OpenResty
openresty -t
# или
nginx -t
```

### 4.2 Мониторинг использования shared_dict

```nginx
location /lua-status {
    allow 127.0.0.1;
    deny all;
    content_by_lua_block {
        local cjson = require("cjson")
        local dict = ngx.shared.redis_cache
        local info = {
            capacity = dict:capacity(),
            free_space = dict:free_space()
        }
        ngx.say(cjson.encode(info))
    }
}
```

---

## 5. Типичные проблемы и фатальные ошибки

| Ошибка / Антипаттерн | Почему это происходит | Последствия | Правильное решение |
|---|---|---|---|
| **Использование стандартных библиотек Lua сокетов (`socket.http`, `luasocket`)** | Стандартные библиотеки используют блокирующие системные вызовы операционной системы (`connect(2)`, `read(2)`). | **Блокировка всего worker-процесса Nginx.** Обработка сотен параллельных клиентских запросов полностью замирает на время сетевого вызова. | Использовать **исключительно** неблокирующие cosocket-библиотеки OpenResty (`resty.http`, `resty.redis`). |
| **Утечка памяти в глобальных переменных (`_G`)** | Переменная объявлена без ключевого слова `local` внутри `_by_lua_block`. | Переменная становится глобальной для worker-процесса LuaJIT, накапливая ссылки и вызывая неконтролируемую утечку RAM. | Всегда использовать строгий `local`: `local my_var = ...`. Включать линтер `luacheck`. |
| **Исчерпание памяти `no memory` в `lua_shared_dict`** | Размер словаря разделяемой памяти задан слишком малым, либо не настроена очистка устаревших ключей (TTL). | Ошибки добавления записей, деградация авторизации. | Задавать адекватный объем `lua_shared_dict`, использовать TTL в методе `dict:set(key, val, ttl)`. |
| **Отключение JIT-компиляции (NYI — Not Yet Implemented)** | Вызов в высоконагруженном цикле функций, которые LuaJIT не умеет компилировать в машинный код (например, `string.dump`, `pairs()`). | Падение производительности до уровня стандартного интерпретатора. | Использовать итератор `ipairs()` вместо `pairs()`, профилировать трассировку LuaJIT утилитой `stapxx` или `lj-trace`. |

---

## 6. Лучшие практики (Best Practices)

1. **Применяйте паттерн Fail-Open для внешних вспомогательных хранилищ (Redis/Memcached):** Если Redis для Rate Limiting упал или не отвечает по таймауту, безопаснее временно пропустить запрос клиента к бэкенду, зафиксировав предупреждение в `error.log`, чем отдавать клиентам ошибку 500.
2. **Всегда используйте пул постоянных соединений cosockets:** После работы с Redis или базами данных вызывайте метод `set_keepalive`:
   ```lua
   -- Таймаут простоя 10 секунд, размер пула на воркер 100 сокетов
   red:set_keepalive(10000, 100)
   ```
3. **Кэшируйте скомпилированные регулярные выражения:** При использовании модуля `ngx.re` всегда передавайте флаг `"jo"` (JIT + Once-compile):
   ```lua
   local m, err = ngx.re.match(uri, "^/api/v[0-9]+/", "jo")
   ```
4. **Не выполняйте тяжелых криптографических вычислений в блокирующем потоке:** Для длинных хешей используйте аппаратное ускорение OpenSSL через FFI-биндинги `resty.openssl`.

---

## 7. Дополнительная информация

- [Модуль Nginx NJS](./nginx_njs_module.md) — нативная альтернатива на JavaScript от команды Nginx.
- [Фазы обработки HTTP-запроса и порядок директив](./nginx_http_phases_and_directive_order.md) — теория точек внедрения хуков `_by_lua`.
- [Руководство по безопасности Nginx](../Security/nginx_security_guide.md) — защита периметра L7 и заголовки безопасности.
- [Шлюз централизованной аутентификации](../Scenarios/nginx_forward_auth_sso_gateway.md) — альтернатива через стандартный `auth_request`.
