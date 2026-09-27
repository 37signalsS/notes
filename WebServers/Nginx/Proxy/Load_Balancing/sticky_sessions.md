# Балансировка нагрузки Nginx: Sticky Sessions (Прилипание сессий)

## Определения

**Sticky Sessions (Прилипание сессий, Session Affinity)** — механизм балансировщика, обеспечивающий направление всех запросов от одного клиента на один и тот же бэкенд в течение всей сессии. Применяется для stateful-приложений, хранящих данные сессии (корзины, авторизацию) в локальной памяти конкретного экземпляра.

**Cookie-based affinity** — метод, при котором балансировщик устанавливает или читает HTTP-куку для идентификации сервера, назначенного клиенту.

**Learn mode** — метод, при котором Nginx извлекает идентификатор сессии из ответа бэкенда (например, `PHPSESSID`, `JSESSIONID`) и запоминает соответствие «сессия → сервер» в разделяемой памяти.

**Route-based affinity** — метод привязки по значению переменной (URI-параметр, заголовок), когда клиент или фронтенд явно указывает целевой сервер.

**Zone (разделяемая память)** — участок shared memory в блоке `upstream`, в котором хранятся таблицы сессий и состояния серверов. Обязательна для работы `sticky` в Nginx Plus и Angie.

## Основные концепции и архитектура

### Жизненный цикл sticky-запроса

1. **Первый запрос клиента** (кука отсутствует или сессия не найдена):
   - Nginx выбирает бэкенд по configured balancing method (Round Robin, Least Conn и т.д.).
   - Если метод `sticky cookie` — Nginx генерирует куку со значением, соответствующим выбранному серверу.
   - Если метод `sticky learn` — Nginx ждет ответа бэкенда, извлекает ID сессии из заголовка `Set-Cookie` и сохраняет пару «ID → сервер» в zone.

2. **Последующие запросы**:
   - Nginx ищет сессию в zone по значению куки (`lookup`) или переменной (`route`).
   - Если сессия найдена и сервер доступен — запрос направляется именно на него.
   - Если сессия найдена, но сервер недоступен — поведение зависит от режима:
     - По умолчанию: запрос передается другому серверу (сессия сбрасывается).
     - С параметром `strict`: возвращается `502 Bad Gateway`.

3. **Истечение сессии**:
   - Запись удаляется из zone по таймауту неактивности (`timeout` в `learn` или `expires` в `cookie`).

### Сравнение методов прилипания

| Метод | Механизм | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **cookie** | Nginx сам вставляет куку с идентификатором сервера. | Не зависит от логики приложения; не требует зоны для самого cookie (требуется для `learn`). | Требует поддержки кук на клиенте; дополнительный размер ответа. |
| **learn** | Nginx «изучает» ID сессии из кук приложения (PHPSESSID, JSESSIONID). | Прозрачен для приложения; не вносит лишних кук. | Требует выделенной zone; зависит от совпадения имен cookie. |
| **route** | Привязка к серверу по идентификатору в URI или заголовке. | Клиент или фронтенд может явно выбирать сервер. | Риск DoS-на конкретный узел без защиты; требует валидации входных данных. |

### Взаимодействие с другими директивами

- **Keepalive:** `sticky` работает поверх keepalive-соединений с бэкендами. Привязка гарантирует логическую связность сессии даже при переподключениях на уровне TCP.
- **Failover:** При недоступности «прилипшего» сервера Nginx может переключиться на другой бэкенд, если параметр `strict` не установлен.
- **Ограничения совместимости:** `sticky` несовместим с методами `hash`, `ip_hash` и `random` в рамках одного блока `upstream`.

### Доступность по версиям

| Функция | Nginx OSS | Nginx Plus | Angie |
| :--- | :--- | :--- | :--- |
| `sticky cookie` | Нет | Да | Да |
| `sticky learn` | Нет | Да | Да |
| `sticky route` | Нет | Да | Да |
| Параметр `strict` | Нет | Да | Да |
| Параметр `secret` / `hmac` | Нет | Нет | Зависит от версии |
| Режим `drain` для серверов | Нет | Да | Да |

Для Nginx OSS прилипание сессий доступно только через:
- `ip_hash` — привязка по IP-адресу клиента.
- `hash` — привязка по произвольной переменной (URI, cookie, заголовок).
- Сторонние модули: `nginx-sticky-module-ng`, `ngx_http_upstream_session_sticky_module`.

## Практические сценарии

### Настройка через метод cookie

Nginx создает собственную куку для отслеживания сессии.

```nginx
upstream backend_cluster {
    zone backend_zone 64k;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    sticky cookie srv_id expires=1h domain=.example.com path=/ secure httponly samesite=lax;
}
```

**Проверка:**

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
curl -I http://app.example.com/
# → Set-Cookie: srv_id=a; Expires=...; Path=/; Secure; HttpOnly; SameSite=Lax
```

**Ключевые параметры:**
- `expires`: Время жизни куки. Если не указано — сессионная кука (удаляется при закрытии браузера).
- `secure` / `httponly` / `samesite`: Флаги безопасности. `samesite=lax` или `strict` защищают от CSRF.
- `domain` / `path`: Область видимости куки.

### Настройка через метод learn (отслеживание сессий приложения)

Используется, когда приложение уже генерирует идентификатор сессии. Nginx запоминает соответствие «ID сессии → IP сервера» в таблице разделяемой памяти.

```nginx
upstream php_app {
    zone sessions_zone 1m;
    server 10.1.1.10:9000;
    server 10.1.1.11:9000;

    sticky learn
        zone=client_sessions:2m
        create=$upstream_cookie_phpsessid
        lookup=$cookie_phpsessid
        timeout=1h;
}
```

**Проверка:**

```bash
curl -I http://php.example.com/
# → Set-Cookie: PHPSESSID=abc123... (от бэкенда)
# Nginx запомнил: PHPSESSID=abc123 → 10.1.1.10:9000
curl -I http://php.example.com/ --cookie "PHPSESSID=abc123"
# → запрос направлен на 10.1.1.10:9000
```

**Особенности метода learn:**
- `create`: Переменная, из которой извлекается ID сессии при первом ответе бэкенда (обычно из `Set-Cookie`).
- `lookup`: Переменная, по которой ищется сессия в последующих запросах клиента (обычно из `Cookie`).
- `timeout`: Время неактивности сессии, после которого запись удаляется из памяти.
- `header` (Angie/Nginx Plus): Если указан, сессия создается при получении заголовков, а не при завершении ответа.

### Настройка через метод route (маршрутизация по переменной)

Обычно используется, когда идентификатор бэкенда передается в параметрах URL или в кастомном заголовке.

```nginx
map $request_uri $route_uri {
    ~jsessionid=.+\.(?P<route>\w+)$ $route;
}

upstream dynamic_route {
    sticky route $route_uri;
    server 127.0.0.1:9000 route=a;
    server 127.0.0.1:9001 route=b;
}
```

### Плавный вывод сервера (drain)

В Nginx Plus и Angie поддерживается режим `drain`, который позволяет плавно вывести сервер из эксплуатации. Сервер перестает принимать новых клиентов, но продолжает обслуживать существующие sticky-сессии.

```nginx
upstream backend {
    zone b_zone 64k;
    server 10.0.0.1:8080 drain;
    server 10.0.0.2:8080;
}
```

### Обработка отказов (strict)

По умолчанию, если сервер, к которому «прилип» клиент, становится недоступным, Nginx перенаправляет запрос на другой живой сервер. Параметр `strict` изменяет это поведение:

```nginx
sticky cookie srv_id expires=1h strict;
```

С `strict` Nginx вернет `502 Bad Gateway`, если целевой сервер недоступен, вместо сброса сессии.

## Операции и команды

### Валидация конфигурации

```bash
# Проверка синтаксиса перед применением
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Грациозная перезагрузка без потери соединений
nginx -s reload
# → signal reload started
```

### Отладка sticky-сессий

```bash
# Включение debug-лога для sticky-модуля (Angie/Nginx Plus)
# В конфигурации:
# upstream backend {
#     sticky cookie srv_id expires=1h;
#     # ...
# }
# server {
#     error_log /var/log/nginx/sticky_debug.log debug;
# }

# Проверка заголовков Set-Cookie от Nginx
curl -I http://app.example.com/
# → Set-Cookie: srv_id=a; Expires=...

# Проверка, что сессия сохраняется при повторных запросах
curl -v http://app.example.com/ -c /tmp/cookies.txt
# В логах access.log с upstream_debug:
# 10.0.0.10 - [22/Sep/2026:12:00:00] 10.0.0.1:8080 200 0.005
```

### Мониторинг распределения сессий

```bash
# Анализ распределения по бэкендам (требует $upstream_addr в логе)
awk '{print $NF}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10

# Подсчет 502/504 ошибок (возможный признак проблем с strict или недоступностью бэкендов)
grep -E "\" 502 |\" 504 " /var/log/nginx/access.log | tail -n 20

# Проверка состояния zone в логах (Angie)
curl http://localhost:8000/api/http/upstreams 2>/dev/null | jq .
```

### Диагностика с curl

```bash
# Проверка установки sticky-куки
curl -I http://app.example.com/ -c /tmp/cookies.txt
# Искать Set-Cookie: srv_id=...

# Проверка повторного использования сессии
curl -I http://app.example.com/ -b /tmp/cookies.txt
# Запрос должен попасть на тот же бэкенд

# Проверка workera sticky-сессий для stateful API
for i in $(seq 1 10); do curl -s http://app.example.com/api/host; done | sort | uniq -c
```

## Диагностика и устранение неполадок

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `502 Bad Gateway` при `strict` | Целевой бэкенд недоступен | Убедиться, что сервер доступен; проверить `max_fails` и `fail_timeout`; временно отключить `strict` |
| Сессия не сохраняется (кука отсутствует) | Клиент блокирует куки или `path`/`domain` некорректны | Проверить браузерные DevTools → Application → Cookies; убедиться, что `path=/` и `domain` корректны |
| Дисбаланс после добавления серверов | Используется `ip_hash` без `consistent` | Для Nginx OSS: перейти на `hash $variable consistent`; для sticky: добавить серверы вручную и сбросить сессии |
| Высокое потребление shared memory | Слишком маленький размер `zone` для `learn` | Увеличить `zone=...:10m`; мониторить `error.log` на `could not allocate` |
| Потеря сессий при перезагрузке Nginx | `zone` не сохранена (по умолчанию in-memory) | Для Nginx Plus/Angie можно использовать `state` директиву для персистентности зоны |
| Все запросы идут на один бэкенд | `backup`-серверы неправильно настроены или `weight=0` | Проверить конфигурацию `upstream`; убедиться, что `backup` используется только для резерва |
| `sticky` не работает с keepalive | Отсутствует `proxy_http_version 1.1` или `Connection ""` | Добавить в `location`: `proxy_http_version 1.1; proxy_set_header Connection "";` |

### Диагностические команды

```bash
# Поиск ошибок sticky и upstream в логе
grep -iE "sticky|upstream|502|504" /var/log/nginx/error.log | tail -n 50

# Анализ распределения запросов по бэкендам
awk '{print $NF}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10

# Проверка заголовков Set-Cookie в ответах
curl -I http://app.example.com/ 2>/dev/null | grep -i "set-cookie"

# Проверка, что запросы с кукой попадают на правильный бэкенд
curl -v http://app.example.com/ -c /tmp/cookies.txt -b /tmp/cookies.txt 2>&1 | grep -E "< HTTP|X-Upstream"

# Поиск переполнения shared memory zone
grep "could not allocate" /var/log/nginx/error.log

# Просмотр конфигурации upstream
nginx -T | grep -A 20 "upstream"
```

## Лучшие практики

### Производительность

1. **Используйте `zone` адекватного размера.** Для `learn` рассчитайте размер на основе ожидаемого количества одновременных сессий: примерно 1MB на 80 000–100 000 записей.
2. **Включайте `keepalive` в `upstream`.** Без keepalive Nginx использует HTTP/1.0 и закрывает соединение после каждого запроса, создавая избыточную нагрузку.
3. **Избегайте `sticky` без необходимости.** Sticky-сессии нарушают балансировку и усложняют масштабирование. Для stateless-приложений используйте общие хранилища сессий (Redis, Memcached).
4. **Используйте `samesite=lax` или `strict`** для кук sticky-сессий, чтобы минимизировать поверхность атаки CSRF.

### Безопасность

1. **Никогда не полагайтесь на sticky как на механизм контроля доступа.** Sticky-сессии обеспечивают маршрутизацию, но не аутентификацию.
2. **Явно указывайте `max_fails` и `fail_timeout`** для каждого сервера. Без этих параметров Nginx по умолчанию использует `max_fails=1` и `fail_timeout=10s`, что может привести к частым переключениям при временных сбоях.
3. **Ограничьте область действия куки:** Используйте `path=/app` вместо `path=/`, если приложение занимает один префикс.
4. **Не используйте `backup`-серверы для активной нагрузки с sticky.** Backup-серверы имеют более низкий приоритет и не участвуют в стандартном распределении.
5. **Изолируйте management-интерфейсы.** Если используете `status_zone` или API Angie/Nginx Plus, ограничьте доступ через `allow/deny` или firewall.

### Эксплуатация (SRE)

1. **Логирование upstream-переменных:** Добавьте в `log_format` переменные `$upstream_addr`, `$upstream_status`, `$upstream_response_time`:

    ```nginx
    log_format upstream_debug '$remote_addr - [$time_local] '
                              '$upstream_addr $upstream_status $upstream_response_time';
    ```

2. **Мониторинг дисбаланса sticky-нагрузки:** Регулярно проверяйте распределение запросов по бэкендам. Дисбаланс более чем на 20% при использовании `sticky cookie` или `learn` указывает на некорректный размер zone, утечку сессий или падающий бэкенд.
3. **Алертинг на 502/504 при strict:** Если используется `strict`, настройте оповещение на `502 Bad Gateway` — это означает, что клиент потерял сессию из-за недоступности целевого бэкенда.
4. **Плановое изменение состава upstream:** При добавлении/удалении серверов из группы с `sticky` ожидайте каскадный сброс сессий. Для `learn` убедитесь, что zone имеет достаточный размер для новых записей.
5. **Тестирование failover:** Периодически проверяйте поведение sticky при отключении бэкенда:

    ```bash
    systemctl stop app@node1
    curl -I http://app.example.com/ -b /tmp/cookies.txt
    # С strict: 502; без strict: 200 с нового бэкенда
    systemctl start app@node1
    ```

6. **Резервное копирование конфигурации:** Перед изменением параметров `sticky` или `zone` создайте бэкап и проверяйте конфигурацию через `nginx -t`.

## Дополнительная информация

### Связанные документы

- **[Обзор и концепции балансировки](./overview_concepts.md)** — базовые принципы распределения трафика и архитектура upstream.
- **[Алгоритмы балансировки](./algorithms.md)** — разбор методов `round-robin`, `least_conn`, `ip_hash` и их взаимодействие с sticky.
- **[Практическая конфигурация балансировки](./practical_configuration.md)** — настройка `upstream`, `proxy_pass`, failover и keepalive.

### Примечания

- В Nginx Open Source базовый набор алгоритмов (Round Robin, Least Connections, Hash, IP Hash, Random) доступен без дополнительных модулей. Для sticky-сессий используйте `ip_hash` или `hash`, либо сторонние модули.
- В Nginx Plus и Angie sticky-сессии являются встроенной функцией upstream. Angie с версии 1.2.0 поддерживает `cookie`, `learn` и `route`, а с более поздних версий — режим `drain` и переменную `$upstream_sticky_status`.
- `sticky` несовместим с `hash`, `ip_hash` и `random` в одном блоке `upstream`. При необходимости комбинации методов используйте внешнее хранилище сессий (Redis/Memcached) для по-настоящему stateless-архитектуры.
