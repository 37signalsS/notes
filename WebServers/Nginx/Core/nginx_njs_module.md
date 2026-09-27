# njs — скриптовый модуль Nginx (Nginx JavaScript)

## Определения

**njs (Nginx JavaScript)** — подмножество ECMAScript (JavaScript), выполняемое внутри Nginx. Позволяет реализовывать обработку запросов на уровне Nginx без пересборки бинарника: проверка токенов, формирование заголовков, ограничение доступа, асинхронные HTTP-вызовы.

**Отличие от Lua (OpenResty):** njs — официальный модуль Nginx (и Angie). Работает в событийной модели Nginx и не блокирует воркеры при асинхронных операциях (через `Promise`/`r.subrequest`).

**Отличие от `location`/`rewrite`:** njs даёт произвольную логику там, где директивы Nginx ограничены декларативным синтаксисом (сложные условия, циклы, работа с JSON).

## Основные концепции

### Архитектура

njs распространяется как **динамический модуль** (`ngx_http_js_module.so`): подключается через `load_module`, после чего в конфиге доступны директивы `js_import`, `js_set`, `js_content`.

```nginx
load_module modules/ngx_http_js_module.so;
```

Типовые точки интеграции:

- **`js_set $var ...`** — вычислить переменную из JS-функции (используется в `proxy_set_header`, `map`, логике).
- **`js_content ...`** — сформировать ответ целиком в JS (healthcheck, JSON-заглушка, обработка ошибок).
- **`js_access ...`** — фаза проверки доступа (до выбора location).

### Модель выполнения

- Код выполняется синхронно за исключением `await`/`Promise` для `r.subrequest()` и `r.fetch()` — асинхронные вызовы не блокируют nginx-воркер.
- JS-функции определяются через `js_import` из файла `.js` (обычно `/etc/nginx/conf.d/js/*.js`).
- Хранить состояние между запросами нельзя гарантированно без shared-зоны; для счётчиков используйте директивы Nginx.

### Возможности и ограничения по сравнению с Lua/OpenResty

| Аспект | njs | Lua (OpenResty) |
| :--- | :--- | :--- |
| Официальность | Входит в экосистему Nginx | Форк OpenResty |
| Асинхронность | `r.subrequest`, `r.fetch` | `ngx.location.capture`, cosocket |
| Экосистема библиотек | Ограничена стандартным JS + API njs | Богатая (resty.*) |
| Версии JS | ES2021+ | 5.1/LuaJIT |
| Использование | Простые сценарии, маскировка, auth | Тяжёлая логика |

## Практические сценарии

### Предварительные требования

Установка njs как динамического модуля для сборки Nginx из официального репозитория nginx.org:

```bash
# Debian/Ubuntu (после подключения репозитория nginx.org)
sudo apt install -y nginx-module-njs

# RHEL/Rocky
sudo dnf install -y nginx-module-njs
```

Проверка доступности модуля:

```bash
ls /usr/share/nginx/modules/ | grep js
# → ngx_http_js_module.so (путь к модулю зависит от ОС)
```

Подключение в конфиге:

```nginx
load_module /usr/share/nginx/modules/ngx_http_js_module.so;
```

### Сценарий 1: Динамический заголовок через js_set

```javascript
// /etc/nginx/conf.d/js/headers.js
function add_request_id(r) {
    return r.variables.request_id || 'unknown';
}
export default { add_request_id };
```

```nginx
js_import headers from conf.d/js/headers.js;

server {
    location / {
        js_set $req_id headers.add_request_id;
        proxy_set_header X-Request-Id $req_id;
        proxy_pass http://app_backend;
    }
}
```

### Сценарий 2: Healthcheck / JSON-заглушка через js_content

```javascript
function health(r) {
    r.return(200, JSON.stringify({ status: 'ok', ts: Date.now() }));
}
```

```nginx
location = /healthz {
    default_type application/json;
    js_content health;
}
```

Проверка:

```bash
curl -s http://127.0.0.1/healthz
# → {"status":"ok","ts":1730000000000}
```

### Сценарий 3: Проверка API-ключа с асинхронной валидацией

```javascript
function validate(r) {
    const token = r.headersIn['X-API-Key'] || '';
    const allowed = ['abc123', 'def456'];
    if (allowed.includes(token)) {
        r.internalRedirect('/api/backend');
    } else {
        r.return(401, 'unauthorized');
    }
}
```

```nginx
js_import auth from conf.d/js/auth.js;

location = /api/protected {
    js_content auth.validate;
}
location /api/backend {
    internal;
    proxy_pass http://api_upstream;
}
```

### Проверка синтаксиса JS

Прямого `nginx -t`-степчика для файлов `.js` нет; команда `node` недоступна в среде Nginx. Рекомендуемый способ — использовать `njs` CLI:

```bash
# Тестовый запуск функции
# (при наличии njs в системе) — валидация через запуск скрипта
node --check /etc/nginx/conf.d/js/headers.js || echo "Ошибка синтаксиса JS"
```

Если `node` отсутствует — проверяйте на stage через реальный запрос с отладкой в error.log (`error_log ... debug;`).

## Операции и команды

| Команда/Директива | Назначение |
| :--- | :--- |
| `load_module modules/ngx_http_js_module.so;` | Подключение модуля |
| `js_import <name> from <file>;` | Импорт JS-модуля с функциями |
| `js_set $var <name>.<fn>;` | Вычисление переменной |
| `js_content <name>.<fn>;` | Формирование ответа |
| `js_access <name>.<fn>;` | Контроль доступа |
| `nginx -t` | Проверка конфигурации с модулем |
| `nginx -s reload` | Применение изменений |

## Устранение неполадок

### `unknown directive "js_set"` / модуль не загружен

**Причина:** модуль не установлен либо `load_module` не в начале конфига.

**Решение:** установите `nginx-module-njs`, разместите `load_module` перед остальными директивами вне `http`/`events`.

### 500 Internal Server Error при js_content

**Причина:** исключение в JS (обращение к несуществующему полю, синтаксическая ошибка).

**Решение:** проверьте error.log (`error_log ... debug;`), выполните `node --check` для файла, упростите логику и добавьте обработку ошибок в JS (`try/catch`).

### Асинхронный вызов блокирует воркер

**Причина:** синхронный `r.fetch`/`r.subrequest` без `await` или использование не-асинхронного API.

**Решение:** используйте `await r.subrequest(...)` в `async`-функции; для тяжёлых зависимостей убедитесь, что библиотеки не выполняют блокирующий I/O на воркере.

### Модуль установлен, но в `nginx -V` его нет

**Причина:** njs — динамический модуль; в `configure arguments` он не перечисляется.

**Решение:** проверяйте наличие через `ls` модуля и успешный `nginx -t` с `load_module`, а не через `nginx -V`.

## Лучшие практики

- **Используйте njs для простых сценариев**, тяжёлую логику — на бэкенде или OpenResty.
- Держите JS-файлы в отдельном каталоге (`/etc/nginx/conf.d/js/`) и версионируйте вместе с конфигом.
- Оборачивайте код в обработку ошибок и логируйте причину (`r.log(...)`).
- Для авторизации используйте `js_access` на ранней фазе, чтобы не отдавать лишние запросы на бэкенд.
- Помните о производительности: лишняя работа JS на каждый запрос добавляет latency; профилируйте перцентили после внедрения.

## Дополнительная информация

### Взаимосвязи

- **[Angie: njs-модуль](../../Angie/angie-njs.md)** — те же принципы в Angie, включая сценарии auth через subrequest и `r.fetch`.
- **[Сборка Nginx из исходников](./nginx_build_from_source.md)** — установка динамических модулей при кастомной сборке.
- **[Контроль доступа в Angie](../../Angie/angie_access_control.md)** — альтернативы auth (JWT, LDAP, PAM) без программирования.

### См. также

- [Обзор Nginx](./nginx_overview.md) — роли и модули Nginx.