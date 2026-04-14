# Перенаправления и перезапись URI в Angie

> [Angie](./angie_overview.md) является форком [Nginx](../Nginx/Core/nginx_overview.md), поэтому концепции перенаправлений и перезаписи URI полностью унаследованы.
>
> **Полный справочник по директивам `rewrite`, `return`, `try_files` и `map`** с детальным разбором синтаксиса, флагов и сценариев: [Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md).

---

## Определения

Концепции идентичны Nginx. Кратко:

- **Rewrite (перезапись)** — внутреннее изменение URI запроса без уведомления клиента.
- **Redirect (редирект)** — внешнее перенаправление. Сервер возвращает `3xx` и заголовок `Location`, браузер выполняет новый запрос.

Полные определения — в [основном справочнике Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#definitions).

---

## Базовые концепции

Все директивы (`rewrite`, `return`, `try_files`, `map`) работают в Angie так же, как в Nginx. Подробный разбор синтаксиса, флагов и предостережение об `if` — в [основном справочнике Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#basic-concepts).

**Ключевые отличия Angie:**

- Основной конфигурационный файл: `/etc/angie/angie.conf` (вместо `/etc/nginx/nginx.conf`)
- Имя сервиса: `angie` (вместо `nginx`)
- Директория логов: `/var/log/angie/` (вместо `/var/log/nginx/`)

---

## Практические сценарии

### Редирект с HTTP на HTTPS

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com;
    # ... остальная конфигурация HTTPS
}
```

### Внутренняя перезапись с `last`

```nginx
location / {
    rewrite ^/test\.txt$ /test/ last;
}

location /test/ {
    # ... обработка запроса для директории /test/
}
```

При запросе `/test.txt` пользователь получит содержимое `/test/`, URL в браузере не изменится.

### Внутренняя перезапись с `break`

```nginx
location /proxy-path/ {
    rewrite ^/proxy-path/(.*)$ /index.php?q=$1 break;
    proxy_pass http://backend;
}
```

### «Красивые» URL для PHP-фреймворка

```nginx
location / {
    try_files $uri $uri/ /index.php?$args;
}
```

### Блокировка ботов по User-Agent с помощью `map`

```nginx
# /etc/angie/angie.conf
http {
    map $http_user_agent $is_bot {
        default 0;
        "~*(Googlebot|Bingbot|curl)" 1;
    }
}
```

```nginx
# /etc/angie/sites-enabled/default
server {
    if ($is_bot) {
        return 401;
    }
}
```

Конструкция с `if` безопасна, так как `return` надёжно работает внутри `if`. Подробности — в [основном справочнике Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#условная-логика-map-vs-if).

Более сложные сценарии с `map` (A/B-тестирование, выборочное логирование) — в [основном справочнике Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#practical-scenarios).

---

## Дополнительная информация

### Отладка rewrite

1. **Включите `rewrite_log`:**

    ```nginx
    server {
        rewrite_log on;
    }
    ```

2. **Установите уровень логирования `notice` для `error_log`:**

    ```nginx
    # /etc/angie/angie.conf
    error_log /var/log/angie/error.log notice;
    ```

После перезагрузки конфигурации в `/var/log/angie/error.log` появятся сообщения о работе регулярных выражений и результатах перезаписи URI. Подробнее о настройке логов: [Логирование в Angie](./angie_logging.md).

### Рекомендации по выбору директивы

| Задача | Рекомендуемая директива |
| :--- | :--- |
| Простой редирект (HTTP → HTTPS, старый URL → новый) | `return` |
| Редирект с регулярными выражениями | `rewrite ... redirect/permanent` |
| Внутренняя перезапись с поиском нового `location` | `rewrite ... last` |
| Внутренняя перезапись без смены `location` | `rewrite ... break` |
| «Красивые» URL, fallback на фронт-контроллер | `try_files` |
| Условная логика (переменные, cookie, заголовки) | `map` + `try_files`/`return` |

### Смежные темы

[Директивы `location` в Angie](./angie_location_directives.md) · [Логирование в Angie](./angie_logging.md) · [Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md)
