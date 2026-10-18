# Фазы обработки HTTP-запроса и порядок выполнения директив в Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x+ (Mainline), Angie 1.6+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по фазам обработки HTTP-запросов (11 HTTP Processing Phases) и внутренней логике очередности исполнения директив в архитектуре Nginx:
- [nginx_overview.md](./nginx_overview.md) — описывает общую событийно-ориентированную модель процессов (Master-Worker, epoll), перечисляя фазы лишь в виде краткого обзорного списка.
- [Location/basics.md](./Location/basics.md) — рассматривает алгоритм сопоставления префиксов и регулярных выражений на фазе `FIND_CONFIG`, не затрагивая сквозной конвейер остальных 10 фаз.
- [nginx_rewrite_rules_and_try_files.md](./nginx_rewrite_rules_and_try_files.md) — фокусируется на директивах модуля `ngx_http_rewrite_module` (`set`, `rewrite`, `if`), исполняемых на фазах `SERVER_REWRITE` и `REWRITE`.
- [Location/best_practices.md](./Location/best_practices.md) — приводит прикладные архитектурные паттерны и антипаттерны без детальной декомпозиции фазовой диаграммы.

---

## 1. Определения

- **Фаза обработки HTTP-запроса (HTTP Processing Phase)** — этап внутреннего конвейера Nginx, на котором модули регистрируют свои функции-обработчики (phase handlers). Ядро Nginx последовательно переводит клиентский запрос из одной фазы в следующую.
- **Фазовый обработчик (Phase Handler)** — C-функция модуля ядра или стороннего модуля, зарегистрированная в массиве обработчиков конкретной фазы и возвращающая код состояния (`NGX_OK`, `NGX_DECLINED`, `NGX_AGAIN`, `NGX_DONE` или HTTP-ошибку).
- **Порядок выполнения директив (Directive Execution Order)** — фундаментальный принцип работы Nginx: директивы выполняются **не в порядке их написания в конфигурационном файле**, а строго в порядке вызова тех фаз конвейера, к которым эти директивы привязаны в исходном коде модулей.
- **Фазовые модули со многими обработчиками (Multi-handler Phases)** — фазы конвейера, позволяющие регистрировать цепочки функций нескольких независимых модулей (например, `ACCESS_PHASE`, где работают и `allow/deny`, и `auth_basic`, и `auth_request`).
- **Контентный обработчик (Content Handler)** — эксклюзивный обработчик генерации ответа на фазе `CONTENT_PHASE`. В рамках одного `location` может выполняться только один генератор контента (`proxy_pass`, `fastcgi_pass`, `static file serving`, `return` или `autoindex`).

---

## 2. Основные концепции и архитектура

### 2.1 Архитектурная проблема: конфигурация vs конвейер исполнения

Распространенная ошибка инженеров — восприятие конфигурационного файла Nginx как процедурного скрипта (по аналогии с Python, Bash или кодом веб-приложений), выполняющегося сверху вниз.

В действительности Nginx при старте или `reload` компилирует текстовый конфигурационный файл в древовидные C-структуры. Каждая директива привязывается к соответствующему модулю ядра. Когда рабочий процесс (`worker`) принимает HTTP-запрос, он прогоняет структуру `ngx_http_request_t` через строго детерминированный цикл из 11 фаз.

```text
Входящий HTTP-запрос (TCP Socket / epoll read)
       │
       ▼
 1. NGX_HTTP_POST_READ_PHASE        ──► Чтение заголовков, realip, ssl_preread L7
       │
       ▼
 2. NGX_HTTP_SERVER_REWRITE_PHASE  ──► rewrite / set на уровне блока server
       │
       ▼
 3. NGX_HTTP_FIND_CONFIG_PHASE     ──► Поиск подходящего location (=, ^~, ~, prefix)
       │
       ▼
 4. NGX_HTTP_REWRITE_PHASE         ──► rewrite / set / if внутри выбранного location
       │
       ▼
 5. NGX_HTTP_POST_REWRITE_PHASE    ──► Обработка внутреннего редиректа после rewrite
       │
       ▼
 6. NGX_HTTP_PREACCESS_PHASE       ──► limit_conn, limit_req (Rate Limiting)
       │
       ▼
 7. NGX_HTTP_ACCESS_PHASE          ──► allow/deny, auth_basic, auth_request
       │
       ▼
 8. NGX_HTTP_POST_ACCESS_PHASE     ──► Проверка директивы satisfy (all / any)
       │
       ▼
 9. NGX_HTTP_PRECONTENT_PHASE      ──► mirror (теневой трафик), try_files
       │
       ▼
10. NGX_HTTP_CONTENT_PHASE         ──► proxy_pass, fastcgi_pass, static file, return
       │
       ▼
11. NGX_HTTP_LOG_PHASE             ──► access_log, log_by_lua, экспорт метрик VTS
```

---

### 2.2 Детальный разбор 11 фаз обработки

| № | Название фазы | Назначение и логика работы | Ключевые директивы и модули |
|---|---|---|---|
| 1 | **`NGX_HTTP_POST_READ_PHASE`** | Первичная обработка после парсинга заголовков запроса из сокета. Модули могут переопределить IP клиента до маршрутизации. | `set_real_ip_from`, `real_ip_header` (`ngx_http_realip_module`). |
| 2 | **`NGX_HTTP_SERVER_REWRITE_PHASE`** | Исполнение правил модификации URI, объявленных непосредственно в блоке `server` (вне любых `location`). | `rewrite`, `set`, `if` (на уровне `server`). |
| 3 | **`NGX_HTTP_FIND_CONFIG_PHASE`** | Поиск наиболее подходящего блока `location` по нормализованному URI. Ядро не позволяет сторонним модулям регистрировать обработчики на этой фазе. | Алгоритм: exact (`=`) → prefix non-regex (`^~`) → regex (`~`, `~*`) → longest prefix. |
| 4 | **`NGX_HTTP_REWRITE_PHASE`** | Вычисление переменных и модификация URI внутри выбранного блока `location`. | `set`, `rewrite`, `if`, `break`, `return` (`ngx_http_rewrite_module`). |
| 5 | **`NGX_HTTP_POST_REWRITE_PHASE`** | Служебная фаза ядра. Если на предыдущей фазе директива `rewrite ... last` изменила URI, инициируется внутренний переход назад на фазу `FIND_CONFIG`. Для предотвращения зависания лимит циклов равен 10 (иначе `500 Internal Server Error: rewrite or internal redirection cycle`). | Внутренняя логика ядра Nginx. |
| 6 | **`NGX_HTTP_PREACCESS_PHASE`** | Предварительный контроль доступа до проверки авторизации. Здесь отсекаются запросы, превышающие лимиты соединений и RPS. | `limit_req`, `limit_conn`, `ngx_http_degradation_module`. |
| 7 | **`NGX_HTTP_ACCESS_PHASE`** | Основная проверка прав доступа. Обработчики вызываются последовательно. Поведение группы определяется директивой `satisfy`. | `allow`, `deny`, `auth_basic`, `auth_request`, `jwt_verify`. |
| 8 | **`NGX_HTTP_POST_ACCESS_PHASE`** | Проверка результата работы фазы `ACCESS`. Если `satisfy all;` и хотя бы один модуль отклонил запрос — возвращается `401/403`. Если `satisfy any;` — достаточно одобрения одного модуля. | Директива `satisfy all \| any;`. |
| 9 | **`NGX_HTTP_PRECONTENT_PHASE`** | Подготовка к генерации контента: дублирование трафика, проверка существования файлов на диске до передачи контентному генератору. | `mirror`, `try_files` (до передачи в именованный location). |
| 10 | **`NGX_HTTP_CONTENT_PHASE`** | Генерация тела ответа и заголовков. В локации побеждает ровно один обработчик. | `proxy_pass`, `fastcgi_pass`, `grpc_pass`, `uwsgi_pass`, `root`/`alias` (static), `autoindex`. |
| 11 | **`NGX_HTTP_LOG_PHASE`** | Вызывается после того, как все байты ответа переданы в клиентский сокет (или соединение оборвалось). Запись метрик и журналов. | `access_log`, `log_subrequest`, `open_log_file_cache`. |

---

## 3. Практические сценарии и ловушки порядка директив

### Сценарий 1: Директива `set` выполняется раньше `auth_request` и `allow/deny`

Классический вопрос на собеседованиях:
```nginx
location /secured-api/ {
    # Кажется, что запрос сначала проверяется по IP, затем по auth_request,
    # и только в конце задается заголовок для бэкенда:
    deny 198.51.100.14;
    allow all;

    auth_request /auth-validator;

    set $tracking_token "$http_x_token-calculated";
    proxy_pass http://backend_cluster;
}
```

**Реальный порядок исполнения Nginx:**
1. Фаза 4 (`REWRITE`): выполняется директива `set $tracking_token ...`.
2. Фаза 7 (`ACCESS`): выполняется `deny/allow`, а затем подзапрос `auth_request`.
3. Фаза 10 (`CONTENT`): выполняется `proxy_pass http://backend_cluster;`.

> **Вывод:** Переменные через `set` вычисляются **всегда до** того, как Nginx проверит права доступа через `auth_request` или `allow/deny`. Если вычисление `$variable` производит тяжелые операции в njs/Lua или зависит от заголовков авторизации, порядок строк в блоке не защитит от его досрочного выполнения.

---

### Сценарий 2: Ловушка `try_files` и `proxy_pass` в одном блоке

```nginx
# ОШИБКА ПРОЕКТИРОВАНИЯ
location /api/ {
    try_files $uri $uri/ /index.html;
    proxy_pass http://api_backend;
}
```

**Почему `proxy_pass` игнорируется:**
1. Директива `try_files` выполняется на фазе `PRECONTENT_PHASE` (фаза 9).
2. Если файл или каталог найден на диске, Nginx завершает обработку и отдает статику.
3. Если файл не найден, `try_files` выполняет внутренний редирект на `/index.html`, перезапуская конвейер с фазы `FIND_CONFIG` (фаза 3).
4. Директива `proxy_pass` (фаза 10, `CONTENT`) в данном блоке **не выполнится никогда**, так как управление будет перехвачено раньше.

**Корректное решение с именованной локацией:**
```nginx
location /api/ {
    try_files $uri @proxy_api;
}

location @proxy_api {
    proxy_pass http://api_backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

### Сценарий 3: Переопределение кода ответа директивой `return`

Директива `return` модуля `ngx_http_rewrite_module` работает на фазе `REWRITE` (фаза 4). 

```nginx
location /download/ {
    auth_basic "Closed Area";
    auth_basic_user_file /etc/nginx/.htpasswd;

    limit_req zone=req_limit_per_ip burst=5;

    return 301 https://archive.company.com$request_uri;

    proxy_pass http://storage_upstream;
}
```

**Что произойдет в действительности:**
- Клиент запросит `/download/file.zip`.
- На фазе 4 (`REWRITE`) сработает `return 301`.
- Запрос **мгновенно завершится с кодом 301**.
- Ни `limit_req` (фаза 6), ни `auth_basic` (фаза 7), ни `proxy_pass` (фаза 10) **не будут вызваны**. Nginx не будет запрашивать пароль у пользователя перед редиректом.

---

### Сценарий 4: Разделение директивы `satisfy` (`all` vs `any`)

При совмещении ограничения по IP-адресу и аутентификации директива `satisfy` на фазе `POST_ACCESS_PHASE` управляет результирующим доступом:

```nginx
location /admin/ {
    satisfy any;

    # Проверка 1: Доступ из офисной подсети без пароля
    allow 10.0.0.0/8;
    allow 192.168.10.0/24;
    deny all;

    # Проверка 2: Доступ из внешнего мира только по паролю
    auth_basic "Admin Access";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://admin_internal;
}
```

- При `satisfy any;`: клиенту из `10.0.0.0/8` доступ открывается немедленно без вызова окна ввода пароля `auth_basic`. Внешний клиент получит запрос `401 Unauthorized`.
- При `satisfy all;` (дефолт Nginx): клиент из доверенной подсети обязан дополнительно ввести логин и пароль.

---

## 4. Диагностика и проверка прохождения фаз

Для глубокого анализа очередности выполнения модулей используется точечная отладка `debug_connection` в связке с Nginx, скомпилированным с флагом `--with-debug`.

### 4.1 Включение фазовой трассировки в `nginx.conf`

```nginx
events {
    worker_connections 1024;
    # Отладка включается СТРОГО для тестового IP инженера
    debug_connection 192.168.1.100;
}

http {
    error_log /var/log/nginx/error.log debug;
    # ...
}
```

### 4.2 Анализ лога прохождения фаз

Выполняем запрос с тестового IP:
```bash
curl -i http://api.company.local/secured-api/
```

Фрагмент журнала `/var/log/nginx/error.log` с маркерами фаз ядра:
```text
# Фаза 1: чтение заголовков и realip
[debug] *1 post-read phase: 0
# Фаза 2: rewrite на уровне сервера
[debug] *1 server-rewrite phase: 1
# Фаза 3: выбор location
[debug] *1 test location: "/"
[debug] *1 test location: "/secured-api/"
[debug] *1 using configuration "/secured-api/"
# Фаза 4: rewrite и set внутри location
[debug] *1 rewrite phase: 3
[debug] *1 http script var: "token-abc-123"
# Фаза 6: лимиты соединений и RPS
[debug] *1 preaccess phase: 5
[debug] *1 limit_req: 0 0.000
# Фаза 7: проверка прав доступа
[debug] *1 access phase: 6
[debug] *1 access: allow 192.168.1.100
# Фаза 9: подготовка контента
[debug] *1 precontent phase: 8
# Фаза 10: контентный генератор
[debug] *1 content phase: 9
[debug] *1 http proxy handler
# Фаза 11: логирование
[debug] *1 log phase: 10
```

---

## 5. Типичные ошибки и траблшутинг

| Проблема / Симптом | Причина в архитектуре фаз | Диагностика | Решение |
|---|---|---|---|
| **`rewrite or internal redirection cycle while internally redirecting to ...` (код 500)** | Директива `rewrite ... last` или цикличный `try_files` на фазах `REWRITE`/`PRECONTENT` более 10 раз возвращают запрос на фазу `FIND_CONFIG`. | В `error.log`: `rewrite or internal redirection cycle`. | Заменить `rewrite ... last;` на `rewrite ... break;` внутри префиксного location либо исправить fallback-цепочку `try_files`. |
| **Пароль `auth_basic` не запрашивается при наличии `return`** | `return` выполняется на фазе `REWRITE` (фаза 4), полностью отсекая последующие фазы `PREACCESS`, `ACCESS` и `CONTENT`. | Запрос возвращает редирект/статус без окна базовой авторизации. | Если авторизация обязательна перед редиректом, перенести редирект на контентный уровень или использовать `map`. |
| **`limit_req` не защищает от перегрузки при тяжелых правилах `rewrite`** | `rewrite` и вычисление регулярных выражений выполняются на фазе 4, тогда как `limit_req` проверяется на фазе 6 (`PREACCESS`). | Высокая утилизация CPU регулярными выражениями при DDoS-атаке. | Выносить тяжелый `rewrite` под конкретные точные `location`, минимизируя нагрузку до фазы rate-limiting. |
| **Подзапрос `mirror` блокирует или дублирует авторизацию** | Директива `mirror` работает на фазе 9 (`PRECONTENT`). К этому моменту основной запрос уже успешно прошел фазу `ACCESS` (авторизован). | Теневой бэкенд получает запросы без повторной валидации сессии. | Принимать теневой трафик на изолированный endpoint внутреннего upstream без клиентской валидации. |

---

## 6. Лучшие практики (Best Practices)

1. **Не полагайтесь на визуальный порядок строк в конфигурационном файле.** Группируйте директивы внутри `location` логически по фазам их выполнения:
   * Сначала переменные и модификации URI (`set`, `rewrite`).
   * Затем ограничения скорости (`limit_req`, `limit_conn`).
   * Затем контроль доступа (`allow`, `deny`, `auth_basic`, `auth_request`).
   * В конце — контентные обработчики (`proxy_pass`, `fastcgi_pass`, `root`).
2. **Помните о правиле одного контентного обработчика:** В рамках одного `location` директивы `proxy_pass`, `fastcgi_pass`, `return`, `try_files` и отдача статики конкурируют за фазу `CONTENT`. Не размещайте несколько генераторов в одном блоке — используйте именованные локации (`@name`).
3. **Используйте `rewrite ... break;` для сохранения контекста location:** Если необходимо изменить URI при проксировании, флаг `break` завершает обработку правил rewrite внутри текущей фазы и оставляет запрос в текущем `location`, не инициируя повторный `FIND_CONFIG`.
4. **Минимизируйте логику на фазе `SERVER_REWRITE`:** Обработка правил rewrite на уровне блока `server` выполняется для абсолютно каждого входящего запроса до выбора `location`, создавая лишние накладные расходы на регулярные выражения.

---

## 7. Дополнительная информация

- [Архитектура ядра и процессов Nginx](./nginx_overview.md) — событийная модель worker-процессов и epoll.
- [Основы директивы Location и алгоритм сопоставления](./Location/basics.md) — детальный разбор работы фазы `FIND_CONFIG`.
- [Правила Rewrite и директива try_files](./nginx_rewrite_rules_and_try_files.md) — детальный синтаксис фазы `REWRITE`.
- [Теневое зеркалирование и разделение трафика](../Proxy/nginx_traffic_mirroring_and_splitting.md) — работа модуля `mirror` на фазе `PRECONTENT`.
- [Шлюз сквозной аутентификации auth_request](../Scenarios/nginx_forward_auth_sso_gateway.md) — интеграция фазы `ACCESS` с внешними SSO-провайдерами.
