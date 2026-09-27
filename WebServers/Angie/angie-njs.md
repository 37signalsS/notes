# Скриптование на njs в Angie

## Определения

**njs (Nginx JavaScript)** — подмножество языка JavaScript, встроенное в Angie для реализации обработчиков запросов и переменных без потери производительности основного событийного цикла. Код исполняется в виртуальной машине внутри воркера, не блокируя обработку других соединений.

**ngx_http_js_module** — модуль Angie (пакет `angie-module-njs` / `angie-pro-module-njs`), добавляющий директивы `js_content`, `js_set`, `js_import` и др. для HTTP-контекста.

**ngx_stream_js_module** — аналогичный модуль для TCP/UDP-потоков.

**Хэндлер (location handler)** — функция njs, назначенная через `js_content` на `location` и полностью формирующая ответ.

**Переменная njs (js_set)** — переменная конфигурации, значение которой вычисляет JS-функция при каждом обращении.

**Свойство `r` (request object)** — объект запроса в njs: `r.uri`, `r.method`, `r.headersIn`, `r.headersOut`, `r.args`; методы `r.return()`, `r.subrequest()`, `r.fetch()`, `r.internalRedirect()`.

## Базовые концепции

### Как njs работает внутри Angie

1. Модуль загружается один раз на старте: `load_module modules/ngx_http_js_module.so;`.
2. Скрипты импортируются директивой `js_import` в `http` (реже в `server`/`location`) и компилируются один раз при запуске. **Код, пришедший из сети, не исполняется никогда** — это критическое отличие от многих «скриптовых» прокси.
3. Во время запроса Angie создаёт объект `r` для конкретного соединения и вызывает нужную функцию на соответствующем этапе обработки (см. ниже).
4. Функция выполняется асинхронно в событийном цикле воркера. Долгие блокирующие операции (диск, внешние вызовы) запрещены; для сетевых взаимодействий используется `r.fetch()` или `r.subrequest()` с неблокирующими callbacks.

### Этапы подключения

| Директива | Этап | Назначение |
| :--- | :--- | :--- |
| `js_set $var func;` | Pre-read / rewrite / access / logging | Вычисление переменной при обращении (часто для `map`-подобной логики) |
| `js_content func;` | Content | Формирование ответа целиком |
| `js_access func;` | Access | Проверка доступа перед передачей в обработчик |
| `js_header_filter func;` | Header filter | Модификация/добавление заголовков ответа |
| `js_body_filter func;` | Body filter | Потоковая модификация тела ответа |

### Возможности и ограничения vs Nginx

njs в Angie совместим с одноимённым модулем Nginx (модуль изначально создан для Nginx). Практические различия минимальны: в Angie модуль поставляется готовым динамическим пакетом и управляется стандартным `load_module`. Синтаксис директив и API `r`/`ngx` совпадают.

## Практические сценарии

### Сценарий 1: Проверка API-ключа на njs (auth via subrequest)

Альтернатива `auth_request` с внешним авторизатором — проверка прямо в Angie. Код компилируется при старте и не обращается к сети, поэтому быстрее и устойчивее.

**`/etc/angie/scripts/auth.js`:**
```javascript
function check_api_key(r) {
    var key = r.headersIn['X-Api-Key'] || '';
    if (key === 'secret-token-2026') {
        r.return(204);           // 204 = pass
    } else {
        r.return(403, 'Forbidden');
    }
}
export default { check_api_key };
```

**`/etc/angie/angie.conf`:** (фрагмент)
```nginx
load_module modules/ngx_http_js_module.so;

http {
    js_import auth from /etc/angie/scripts/auth.js;

    server {
        location /api/ {
            auth_request /_validate_key;
            proxy_pass http://backend;
        }

        location = /_validate_key {
            internal;
            js_content auth.check_api_key;
        }
    }
}
```

### Сценарий 2: Переменная через js_set (динамический заголовок)

**`/etc/angie/scripts/custom.js`:**
```javascript
function build_hostname(r) {
    return r.variables.host + ':' + r.headersIn['X-Forwarded-For'] || '';
}
export default { build_hostname };
```

**Конфиг:**
```nginx
js_import custom from /etc/angie/scripts/custom.js;
js_set $custom_host custom.build_hostname;

server {
    add_header X-Host-Label $custom_host always;
}
```

### Сценарий 3: Ручной ответ (health check / заглушка)

```nginx
location = /ping {
    js_content r => r.return(200, 'pong\n');
}
```
Функция-стрелка поддерживается njs; в production-конфигурациях обычно используют именованные экспорты из модуля (рекомендуемый стиль — как в сценарии 1).

### Сценарий 4: Асинхронный внешний вызов (r.fetch)

Для обращения к внешнему сервису (например, профиль пользователя) — не блокируя воркер:

```javascript
async function enrich(r) {
    var res = await r.fetch('http://auth-service:8080/u/' + r.args.id);
    if (res.status !== 200) {
        r.return(502, 'Upstream error');
        return;
    }
    var body = await res.text();
    r.return(200, body);
}
export default { enrich };
```

```nginx
location /profile {
    js_content enrich;
}
```

## Операции и команды

### Установка модуля

```bash
sudo apt install angie-module-njs        # или angie-pro-module-njs
sudo angie -t && sudo systemctl reload angie
```

### Проверка подключения модуля

```bash
angie -V 2>&1 | grep -o "ngx_http_js_module\|ngx_stream_js_module"
```

### Проверка синтаксиса JS

До перезапуска проверьте скрипт локально (доступен в дистрибутивах как `njs`):

```bash
njs -c "console.log('ok')"        # проверка работоспособности
njs -c "$(cat /etc/angie/scripts/auth.js)"   # компиляция файла
```

### Быстрый тест эндпоинта

```bash
curl -i http://localhost/ping                      # js_content
curl -i -H "X-Api-Key: secret-token-2026" http://localhost/api/x   # auth через njs
curl -i http://localhost/api/x                     # → 403
```

## Устранение неисправностей

### 500 Internal Server Error при js_content

**Причина:** исключение в скрипте (Division by zero, обращение к несуществующему свойству) либо ошибка компиляции.
**Диагностика:**
```bash
grep -i "js\|njs" /var/log/angie/error.log | tail -n 20
```
**Решение:** исправить скрипт, прогнать его через `njs -c`, перезагрузить `angie`.

### Переменная js_set не обновляется

**Причина:** `js_set` вычисляется при обращении к переменной; в `log_format` она может вычисляться позже ожидаемого, либо в контексте нет обращения к ней.
**Решение:** убедиться, что переменная упоминается в нужном контексте (например, в `add_header`, `proxy_set_header` или `log_format`) и что функция экспортирована и импортирована.

### Синхронные вызовы блокируют воркер

**Причина:** использование блокирующих операций (например, `ngx.fetch` без `await` или обработка гигантского тела в цикле).
**Решение:** применять только асинхронный API из сценария 4; для тяжёлого парсинга тела — подумать о выводе логики наружу (контейнерный сайдкар).

### Модуль не найден после установки пакета

**Причина:** модуль не подключён директивой `load_module` или установлен не тот пакет (часть модулей собирается отдельно).
**Диагностика:**
```bash
dpkg -L angie-module-njs | grep -i js_module   # проверить наличие .so
```
**Решение:** добавить `load_module modules/ngx_http_js_module.so;` в самое начало `angie.conf`.

## Лучшие практики

1. **Не исполняйте произвольный код:** конфигурация, меняющая `js_import`, — привилегированная операция; защищайте файлы скриптов правами (владелец `root`, без записи извне).
2. **Держите скрипты асинхронными:** ни один блокирующий вызов в функции `js_content`/`js_access` не должен превышать микросекунды.
3. **Выносите тяжёлую логику из воркера:** анализ больших тел, ML-проверки, рекурсивные правила — во внешний сервис, вызываемый через `r.fetch`.
4. **Переиспользуйте модули:** `export default` позволяет импортировать один файл в разные контексты с одним пространством имён.
5. **Тестируйте локально:** `njs -c` и офлайн-юнит-тесты экономят рестарты в production.
6. **Журналируйте ошибки:** в `error_log` уровня `info` njs пишет трассировку исключений — настраивайте формат заранее.
7. **Минимизируйте поверхность:** отключайте njs там, где он не нужен (нет `js_import` — модуль не исполняет никакой JS).

## Дополнительная информация

- Готовая конфигурация авторизации на njs — в [Контроль доступа в Angie](./angie_access_control.md) (сценарий «Вариант Б»).
- Интеграция OIDC-потока с JS-обработчиком — [Аутентификация через OIDC в Angie](./angie-oidc.md).
- Общие принципы ограничения доступа по IP, `satisfy`, `auth_request` — [Контроль доступа](./angie_access_control.md).
- Официальная документация: [HTTP JS (внешние модули Angie)](https://en.angie.software/angie/docs/configuration/modules/external-modules/http_js.md), [NJS overview](https://en.angie.software/angie/docs/configuration/modules/external-modules/njs.md), [njs на nginx.org](https://nginx.org/en/docs/njs/index.html).

## См. также

- [Контроль доступа в Angie](./angie_access_control.md)
- [Аутентификация через OIDC в Angie](./angie-oidc.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)