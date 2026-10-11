# Предикатные локейшены и продвинутая маршрутизация API-трафика

**Актуально для:** NGINX 1.31.5+

## Определения

**Предикатный локейшен (predicate location)** — блок `location`, в котором вместо статического URI в качестве модификатора трафика используется переменная Nginx. Блок срабатывает, когда переменная принимает истинное значение (любая непустая строка или ненулевое число). Введён в NGINX 1.31.5.

**`client_body_early_read`** — директива Nginx, принудительно буферизирующая тело HTTP-запроса до выбора `location`. Без неё тело читается только после того, как выбран блок `location`. С включённой директивой тело становится доступно на раннем этапе обработки.

**`json_set`** — директива модуля `ngx_http_json_module`, извлекающая значение из JSON-пейлоуда по JSONPath-выражению и присваивающая его переменной Nginx.

**JSONPath** — язык запросов для обхода и извлечения значений из JSON-документов (аналогично XPath для XML). В контексте Nginx используется в `json_set` для указания пути к полю внутри тела запроса.

**`map`** — директива контекста `http`, отображающая значение одной переменной на значение другой. Используется для преобразования произвольных данных (метод, заголовок, поле JSON) в булево предикат для `location`.

**`js_set` / njs** — механизм вычисления переменной через JavaScript-функцию модуля njs (Nginx JavaScript). Позволяет реализовать произвольную логику маршрутизации без внешних скриптов.

## Базовые концепции

### Ограничение классических локейшенов

Классические блоки `location` проектировались вокруг URI. Директива сопоставляет нормализованный URI запроса с паттерном и выбирает блок по алгоритму, описанному в **[Директива location: основы и приоритеты](./basics.md)**. Это исключает маршрутизацию по содержимому заголовков, тела запроса или бизнес-полям внутри JSON-пейлоуда.

Для обхода этого ограничения использовались внешние скрипты (njs, Lua), сложные цепочки `rewrite` или отдельные сервисы. Все эти подходы добавляли задержку, сложность отладки и зависимость от дополнительных модулей.

### Предикатные локейшены

В NGINX 1.31.5 ограничение снято: любой переменной можно назначить роль модификатора трафика для блока `location`. Если переменная принимает истинное значение (непустая строка или ненулевое число), запрос направляется в соответствующий блок.

```nginx
http {
    server {
        location / { ... }
        location /images { ... }
        location $post_requests { ... }
        location $bot_traffic { ... }
        location $internal_tests { ... }
        location $ai_mcp_queries { ... }
    }
}
```

Переменные вычисляются в тот момент, когда Nginx готов к сопоставлению `location`. Это означает, что предикат может быть построен на:
- HTTP-заголовках (`$http_x_api_key`, `$http_content_type`);
- результате директива `map`;
- значении, извлечённом из тела запроса через `json_set`;
- результате вычисления njs-функции через `js_set`.

### Вложенность предикатов

Предикатные локейшены поддерживают вложенность вместе с классическими URI-блоками. Структура должна отражать паттерн трафика приложения:

```nginx
http {
    server {
        location /images { ... }
        location /api/v1 {
            location $restricted_requests {
                location $post_requests { ... }
                location $bot_traffic { ... }
            }
            location $internal_tests { ... }
            location $ai_mcp_queries { ... }
        }
    }
}
```

Альтернативный подход — сначала предикат, потом URI:

```nginx
http {
    server {
        location $public_methods { ... }
        location $restricted_methods {
            location /api/v1/private {
                location $internal_ips { ... }
                location $bot_traffic { ... }
            }
            location /api { ... }
            location /wp-admin { ... }
        }
    }
}
```

### Раннее чтение тела запроса (`client_body_early_read`)

По умолчанию Nginx читает тело запроса только после выбора `location`. Директива `client_body_early_read` меняет порядок: тело буферизируется и становится доступно до сопоставления.

```nginx
http {
    client_body_early_read on;
}
```

Директива поддерживает переменные, что позволяет включать раннее чтение выборочно:

```nginx
http {
    map $http_content_type $is_json {
        application/json 1;
    }

    server {
        client_body_early_read $is_json;
        ...
    }
}
```

В этом примере тело читается заранее только для запросов с `Content-Type: application/json`. Для остальных запросов поведение остаётся штатным.

### Встроенный разбор JSON (`ngx_http_json_module`)

Модуль `ngx_http_json_module` добавляет директиву `json_set`, которая извлекает значение из JSON по JSONPath и присваивает его переменной.

```nginx
json_set $vip $request_body user.params.vip;
```

Извлечённое значение может использоваться:
- напрямую в `location` как предикат;
- в директиве `map` для построения булевой логики;
- в заголовках, логировании илиRate limiting.

## Практические сценарии

### Сценарий 1: Маршрутизация по полю JSON без скриптов

Маршрутизация запросов на основе поля `vip` в теле JSON:

```nginx
events { }
http {
    client_body_early_read on;
    json_set $vip $request_body user.params.vip;

    server {
        listen 8085;

        location $vip {
            return 200 "VIP user\n";
        }

        location / {
            return 200 "Regular user, applying restrictions\n";
            # limit_req ...;
        }
    }
}
```

Тело запроса:

```json
{
  "order_id": "1042",
  "item": "latte",
  "size": "medium",
  "user": {
    "name": "Nick",
    "params": {
      "vip": 1
    }
  }
}
```

Верификация:

```bash
# Обычный пользователь
curl -X POST -d '{"order_id":"1042","item":"latte","size":"medium","user":{"name":"Somebody","params":{"vip":0}}}' 127.0.0.1:8085
# → Regular user, applying restrictions

# VIP-пользователь
curl -X POST -d '{"order_id":"1042","item":"latte","size":"medium","user":{"name":"Nick","params":{"vip":1}}}' 127.0.0.1:8085
# → VIP user
```

### Сценарий 2: Сложная маршрутизация через `map` + JSON

Комбинация `json_set`, `map` и предикатного локейшена для ограничения методов:

```nginx
http {
    client_body_early_read on;

    json_set $coffee_method $request_body "method";

    map $coffee_method $restricted_methods {
        "~createOrder" 1;
        "~deleteOrder" 1;
        default        0;
    }

    limit_req_zone $remote_addr zone=restricted:7m rate=3r/s;

    server {
        location $restricted_methods {
            limit_req zone=restricted;
            allow 127.0.0.1;
            deny  all;
            proxy_pass http://api.coffeeshop.local;
        }

        location /api/v1/ {
            proxy_pass http://api.coffeeshop.local;
        }
    }
}
```

### Сценарий 3: Интеграция с NJS для сложной логики

NJS выполняет произвольный JavaScript для вычисления предиката. Используется для подсчёта токенов в теле запроса:

```javascript
// /etc/nginx/conf.d/http.js
function counter(r) {
  const words = r.variables['request_body'].trim().split(/\s+/).length;
  if (words > 10) {
    return 1;
  }
  return 0;
}
export default {counter};
```

```nginx
events { }
http {
    client_body_early_read on;
    js_import /path/to/conf/http.js;
    js_engine qjs;
    js_set $many_tokens http.counter;

    server {
        location $many_tokens {
            return 413 "Request body has too many tokens\n";
        }

        location / {
            return 200 "Request is small, OK\n";
        }
    }
}
```

Верификация:

```bash
# Слишком много токенов
curl -X POST -d "a b c d e f g h j k l" 127.0.0.1:80
# → Request body has too many tokens

# Нормальный запрос
curl -X POST -d "a b c d" 127.0.0.1:80
# → Request is small, OK
```

### Сценарий 4: Выборочное включение раннего чтения по заголовку

```nginx
http {
    map $http_content_type $is_json {
        application/json 1;
    }

    server {
        client_body_early_read $is_json;

        json_set $vip $request_body user.params.vip;

        location $vip {
            proxy_pass http://vip_backend;
        }

        location / {
            proxy_pass http://default_backend;
        }
    }
}
```

### Сценарий 5: Выборочное включение по URI

```nginx
http {
    map $uri $is_upload_endpoint {
        /api/v1/uploads 1;
    }

    server {
        client_body_early_read $is_upload_endpoint;

        location /api/v1/uploads {
            client_body_temp_path /var/tmp/nginx 10m;
            client_max_body_size 100M;
            proxy_pass http://upload_service;
        }

        location / {
            proxy_pass http://default_backend;
        }
    }
}
```

## Операции и команды

### Верификация конфигурации

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

nginx -s reload
# → signal processed
```

### Диагностика предикатных локейшенов

```bash
# Включение debug-лога
error_log /var/log/nginx/error.log debug;

# После reload в логе:
# → *12345 using location "$vip" for "/api/v1/coffee"
# → *12345 http script var: "$vip" = "1"
```

### Проверка через curl

```bash
# Проверка маршрутизации по JSON-полю
curl -X POST -d '{"user":{"params":{"vip":1}}}' http://nginx-host:8085 -v
# → HTTP/1.1 200 OK
# → VIP user

# Проверка выборочного раннего чтения
curl -X POST -H "Content-Type: application/json" -d '{"test":1}' http://nginx-host/api/v1/uploads -v
# → тело прочитано на раннем этапе
```

## Устранение неполадок

### Проблема 1: Предикатный локейшен не срабатывает

**Диагностика:**
- Проверьте, что переменная непустая и не `0`. Любое непустое значение считается истинным.
- Убедитесь, что `client_body_early_read` включён на уровне `http` или `server`, если предикат зависит от тела запроса.
- Проверьте синтаксис `json_set`: JSONPath должен быть корректным.

**Решение:** Используйте `return 200 "$vip\n";` для отладки значения переменной.

### Проблема 2: Высокое потребление памяти при раннем чтении тела

**Причина:** `client_body_early_read` буферизирует всё тело запроса в памяти. Для больших пейлоудов это приводит к росту потребления RAM.

**Решение:**
- Включайте `client_body_early_read` выборочно через `map`.
- Установите `client_max_body_size` для ограничения размера буфера.
- Используйте `client_body_temp_path` для вынесения временных файлов на диск.

### Проблема 3: `json_set` возвращает пустую строку

**Причины:**
- Тело запроса не было прочитано (`client_body_early_read off`).
- JSON содержит синтаксическую ошибку.
- JSONPath указывает на несуществующий путь.

**Решение:** Включите `client_body_early_read on;` и проверьте JSON через `jq` или онлайн-валидатор.

### Проблема 4: NJS-функция не вычисляется

**Причины:**
- Модуль njs не загружен (`load_module` или пакет `nginx-module-njs` не установлен).
- Ошибка в JS-коде (синтаксис, обращение к несуществующему свойству).
- `js_engine` не указан или указан неверно.

**Решение:**
```bash
# Проверка загруженных модулей
nginx -V 2>&1 | grep -o "http_js_module"

# Проверка синтаксиса JS
node --check /path/to/conf/http.js
```

### Проблема 5: Циклические внутренние перенаправления

**Симптом:** `rewrite or internal redirection cycle while internal redirection to "/index.html"`

**Причина:** Предикатный локейшен вызывает внутренний редирект в тот же блок.

**Решение:** Используйте именованный `location` или проверьте условия, при которых блок возвращает ответ напрямую.

## Лучшие практики

### Производительность

1. **Размещайте простые и часто срабатывающие предикаты выше сложных.** Из соображений производительности простые проверки (заголовки, метод) должны быть объявлены ранее, чем логика, читающая тело запроса.

2. **Включайте `client_body_early_read` выборочно.** Используйте `map` по заголовку `Content-Type` или URI, чтобы ограничить раннее чтение только теми эндпоинтами, где оно необходимо. Большие тела запросов потребляют память и CPU.

3. **Используйте catch-all локейшен на каждом уровне вложенности.** С предикатами блок `location /` имеет смысл не только на верхнем уровне, но и как fallback внутри вложенных структур. Размещайте его в конце блока.

### Безопасность

1. **Ограничивайте `client_max_body_size`** для эндпоинтов с ранним чтением тела. Это предотвращает DoS через гигантские пейлоуды.

2. **Не парсите неподтверждённый JSON без ограничения размера.** `json_set` обрабатывает всё тело; нечитаемые или повреждённые пейлоуды могут привести к ошибкам.

3. **Используйте `limit_req` и `limit_except`** в предикатных блоках для защиты чувствительных эндпоинтов.

### Эксплуатация (SRE)

1. **Называйте предикаты осмысленно.** Имена переменных вроде `$restricted_methods`, `$vip_users`, `$bot_traffic` упрощают отладку и чтение логов.

2. **Используйте специальные форматы логов.** Добавьте в `log_format` значения ключевых переменных для отслеживания предикатов:

    ```nginx
    log_format with_predicates '$remote_addr - $remote_user [$time_local] '
                               '"$request" $status $body_bytes_sent '
                               '"$http_referer" "$http_user_agent" '
                               'vip="$vip" method="$coffee_method"';
    ```

3. **Валидируйте конфигурацию перед reload:**

    ```bash
    nginx -t
    nginx -s reload
    ```

4. **Храните JS-файлы njs в конфигурационном репозитории.** Это обеспечивает версионирование и аудит изменений логики маршрутизации.

## Дополнительная информация

### См. также

- **[Директива location: основы и приоритеты](./basics.md)** — алгоритмы выбора, модификаторы и приоритеты.
- **[Nginx location: лучшие практики и отладка](./best_practices.md)** — оптимизация производительности, безопасность, отладка сопоставления.
- **[Nginx: внутренняя маршрутизация](./internal_routing.md)** — `internal`, `X-Accel-Redirect`, именованные локации.
- **[njs — скриптовый модуль Nginx](../nginx_njs_module.md)** — JavaScript-интеграция, `js_set`, `js_content`, асинхронные операции.
- **[Отладка Nginx](../../Operations/nginx_troubleshooting.md)** — общие методы устранения ошибок.

### Ссылки

- [NGINX Location Blocks](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)
- [NGINX JSON Module](https://nginx.org/en/docs/http/ngx_http_json_module.html)
- [NGINX `client_body_early_read` Directive](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_body_early_read)
- [NGINX 1.31.5 Release Blog](https://blog.nginx.org/blog/nginx-1-31-5-control-api-predicate-locations-early-body-inspection-and-more)
- [Change Log for NGINX](https://nginx.org/en/CHANGES)
