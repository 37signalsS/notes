# Перенаправления и перезапись URI в Angie

## Определения

Концепции перенаправлений и перезаписи URI в [Angie](./angie_overview.md) полностью унаследованы от [Nginx](../Nginx/Core/nginx_overview.md).

- **Rewrite (перезапись)** — внутреннее изменение URI запроса сервером без уведомления клиента.
- **Redirect (редирект)** — внешнее перенаправление, при котором сервер возвращает код `3xx` и заголовок `Location`, инициируя новый запрос от браузера.

Полные определения и разбор типов редиректов приведены в основном справочнике: [Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#definitions).

## Основные концепции

Все директивы управления URI (`rewrite`, `return`, `try_files`, `map`) работают в Angie идентично Nginx. Подробный разбор синтаксиса, флагов и рекомендации по использованию приведены в [справочнике Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md#basic-concepts).

**Инфраструктурные особенности Angie:**

| Параметр | Путь / Значение |
| :--- | :--- |
| Основной конфиг | `/etc/angie/angie.conf` |
| Имя сервиса | `angie` |
| Директория логов | `/var/log/angie/` |

Для Angie также актуально предостережение об использовании `if` (сценарий «If is Evil»). Рекомендуется отдавать приоритет директивам `try_files` и `map`.

## Практические сценарии

Ниже приведены примеры конфигурации с использованием путей и переменных, актуальных для Angie.

### Редирект с HTTP на HTTPS

```nginx
server {
    listen 80;
    server_name example.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;
    # Настройки SSL...
}
```

### «Красивые» URL для современных фреймворков

Использование `try_files` для направления всех запросов на фронт-контроллер:

```nginx
location / {
    try_files $uri $uri/ /index.php?$args;
}
```

### Внутренняя перезапись с флагом `last`

```nginx
location / {
    rewrite ^/old-page\.html$ /new-page/ last;
}

location /new-page/ {
    # Обработка нового URI
}
```

### Блокировка ботов через `map`

Объявление в блоке `http` (обычно в `/etc/angie/angie.conf`):

```nginx
http {
    map $http_user_agent $is_bot {
        default 0;
        "~*(Googlebot|Bingbot|curl)" 1;
    }
}
```

Применение в блоке `server`:

```nginx
server {
    if ($is_bot) {
        return 403;
    }
}
```

## Дополнительная информация

### Отладка правил rewrite

Для диагностики регулярных выражений и логики перезаписи:

1. **Включите логирование:**

    ```nginx
    server {
        rewrite_log on;
    }
    ```

2. **Настройте уровень логов в `angie.conf`:**

    ```nginx
    error_log /var/log/angie/error.log notice;
    ```

После применения настроек (`angie -s reload`) подробности перезаписи будут доступны в `/var/log/angie/error.log`. Подробнее см. [Логирование в Angie](./angie_logging.md).

### Рекомендации по выбору директивы

| Задача | Директива |
| :--- | :--- |
| Простой редирект (301/302) | `return` |
| Сложный редирект с Regex | `rewrite ... permanent/redirect` |
| Скрытая замена URI | `rewrite ... last/break` |
| Fallback на файл/директорию | `try_files` |
| Условная логика | `map` |

### См. также

- [Директивы location в Angie](./angie_location_directives.md)
- [Логирование в Angie](./angie_logging.md)
- [Nginx: Rewrite, Redirect и try_files](../Nginx/Core/nginx_rewrite_rules_and_try_files.md) — основной справочник
