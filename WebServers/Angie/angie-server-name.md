# Виртуальные хосты и server_name в Angie

## Определения

**Виртуальный хост (virtual host)** — независимый `server`-блок, обслуживающий свои домены и/или порты на одном экземпляре Angie.

**`server_name`** — директива, задающая имена, по которым запрос маршрутизируется к конкретному `server`-блоку. Определяет выбор виртуального хоста по заголовку `Host` (HTTP) или SNI (TLS).

**`default_server`** — параметр директивы `listen`, помечающий сервер как "по умолчанию": к нему попадают запросы, не совпавшие с `server_name` ни одного другого хоста на данном порту.

**`$server_name`** — переменная, хранящая имя хоста, совпавшее с запросом (в отличие от `$host`, берётся из `server_name`, а не из заголовка).

## Теоретический блок

### Алгоритм выбора server-блока

Angie выбирает виртуальный хост по приоритету (первое совпадение выигрывает):

1. Точное совпадение имени.
2. Самый длинный wildcard-префикс, например `*.example.com`.
3. Самый длинный wildcard-суффикс, например `www.example.*`.
4. Первое совпадение регулярного выражения (в порядке объявления в конфиге).
5. Если совпадений нет — блок `default_server` (или первый `server`-блок на порту, если `default_server` не задан).

### Специфика wildcard и regex

*   Wildcard работает только в начале (`*.example.com`) или в конце имени (`www.example.*`), но не в середине.
*   Имена, начинающиеся с `~`, трактуются как регулярные выражения (синтаксис PCRE). Точки в regex нужно экранировать (`~^www\.`).
*   Регулярные выражения проверяются в порядке появления, поэтому специфичный regex ставьте первым.
*   Совпадением считается только полное совпадение имени: `server_name example.com` не перехватит `www.example.com`.

### Наследование и области действия

*   `server_name` задаётся в контексте `server`, наследования из `http` нет (в `http` его нет вообще).
*   Директива `listen` задаёт порт/адрес; `default_server` может быть указан только в одном `server`-блоке на каждую пару адрес:порт.

## Практический блок

### Сценарий 1: Классическая настройка виртуальных хостов

```nginx
http {
    # Обработчик по умолчанию для порта 80 (неизвестные Host)
    server {
        listen 80 default_server;
        server_name _;
        return 444;              # закрыть соединение без ответа
    }

    # Основной домен
    server {
        listen 80;
        listen 443 ssl default_server;
        server_name example.com www.example.com;
        # ... ssl_certificate, root, proxy_pass
    }

    # Wildcard-поддомены
    server {
        listen 80;
        server_name *.example.com;
        # ...
    }

    # Регулярное выражение: только цифровые поддомены
    server {
        listen 80;
        server_name ~^api[0-9]+\.example\.com$;
        # ...
    }
}
```

### Сценарий 2: TLS-виртуальные хосты и SNI

На порту 443 выбор хоста выполняется в два этапа: сначала по SNI выбирается сертификат, затем внутри TLS-соединения по HTTP Host — сам `server`-блок.

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    ssl_certificate     /etc/angie/ssl/example.com.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.key;
}

server {
    listen 443 ssl;
    server_name admin.example.com;
    ssl_certificate     /etc/angie/ssl/admin.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/admin.example.com.key;
}
```

### Сценарий 3: default_server для "несуществующих" доменов

```nginx
# Отдаёт заглушку вместо секретной информации чужого домена
server {
    listen 443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;     # не показывать сертификат и не выполнять handshake
    return 444;
}
```

`ssl_reject_handshake on` возвращает ошибку TLS без выдачи сертификата — хорошая защита от сканеров.

### Верификация

```bash
angie -t
# → syntax is ok / test is successful

# Какой server-блок выбран для запроса (по содержимому ответа)
curl -sI https://example.com/ | grep -E "^(HTTP|Server)"
# → HTTP/2 200

# Проверка, что default_server перехватывает чужие Host
curl -s -H "Host: nonexistent.example" http://127.0.0.1/ -o /dev/null -w "%{http_code}\n"
# → 444 (или код заглушки)

# Список всех server_name в конфигурации
angie -T | grep -E "server_name|listen"
```

### Решение проблем (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| Все запросы обрабатывает один хост | `default_server` не задан, срабатывает первый блок | Указать `default_server` для заглушки |
| Regex-имя не совпадает | Синтаксис regex без `~` или точки не экранированы | `server_name ~^www\.example\.com$;` |
| HTTPS-предупреждение о сертификате | Выбран неверный сертификат по SNI | Проверить `listen 443 ssl` и совпадение `server_name` с CN/SAN |
| Запрос уходит в неожиданный hosts | Wildcard/точное имя конфликтуют | Уточнить приоритет: точное имя сильнее wildcard |
| Домен уходит в заглушку 444 | `server_name` самого домена не совпадает с Host | `angie -T \| grep server_name` и сверка написания |

## Дополнительная информация

*   Переменная `$host` берётся из заголовка `Host` и подрезает порт, а `$server_name` — из директивы; на проксирующих схемах они могут отличаться.
*   При перенаправлении HTTP→HTTPS лучше использовать `server_name` + `return 301 https://$host$request_uri;`, чтобы имя хоста сохранялось корректно.
*   Детали конфигурирования HTTPS-хостов, включая `ssl_reject_handshake`, см. в [Настройке TLS в Angie](./angie_tls_setup.md).

## См. также

*   **[Установка и базовая настройка Nginx](../Nginx/Core/nginx_setup.md)** — базовый `server_name`/`default_server` (общий для Nginx и Angie).
*   **[TLS-виртуальные хосты в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — SNI, несколько сертификатов на порту 443.
*   **[Минимальная продакшен-конфигурация Angie](./angie-baseline-config.md)** — готовый каркас с виртуальными хостами.