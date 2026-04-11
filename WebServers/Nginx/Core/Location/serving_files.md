# Nginx: Отдача статических файлов

## Definitions

Директивы `root` и `alias` определяют, как Nginx сопоставляет URI запроса с файлами на диске. Это основа конфигурирования отдачи статики (изображения, CSS, JavaScript, документы).

Концепции `try_files` и редиректов описаны в SSoT: [Nginx: Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md).

---

## Basic Concepts

### Директива `root`

`root` задаёт корневой каталог для запросов. Nginx добавляет полный URI запроса к пути `root` для формирования абсолютного пути к файлу.

**Синтаксис:** `root /path/to/directory;`

**Пример:**

```nginx
server {
    root /var/www/html;

    location /images/ {
        # Запрос /images/pic.jpg → /var/www/html/images/pic.jpg
    }

    location = /test.html {
        root /var/www/special_tests;
        # Запрос /test.html → /var/www/special_tests/test.html
        # Переопределение root на уровне location для специфических файлов
    }
}
```

**Уровни наследования:** `root` может быть определён на уровне `http`, `server` или `location`. Если `root` не указан в `location`, он наследуется от родительского блока.

### Директива `alias`

`alias` заменяет часть URI, совпавшую с `location`, на указанный путь. Может использоваться только внутри `location`.

**Синтаксис:** `alias /path/to/directory/;`

**Пример:**

```nginx
location /static/ {
    alias /opt/data/static_files/;
    # Запрос /static/css/style.css → /opt/data/static_files/css/style.css
    # Префикс "/static/" заменяется на "/opt/data/static_files/"
}

location /documents/ {
    alias /var/www/shared/docs/;
    # Запрос /documents/report.pdf → /var/www/shared/docs/report.pdf
    # Важно: если location заканчивается слэшем, alias тоже должен
}
```

### Ключевое отличие `root` vs `alias`

| Директива | Как формируется путь |
|:----------|:---------------------|
| `root` | `root` + **полный URI** (`/var/www/html` + `/images/pic.jpg`) |
| `alias` | `alias` + **остаток URI после location** (`/opt/data/static_files/` + `css/style.css`) |

**Правило:** если `location` заканчивается слэшем, `alias` тоже должен заканчиваться слэшем — иначе путь сформируется некорректно.

---

## Practical Scenarios

### Отдача статики с `root`

Стандартный сценарий — статические файлы лежат в подкаталогах корневого каталога сайта:

```nginx
server {
    root /var/www/mysite;

    location /images/ {
        # /images/logo.png → /var/www/mysite/images/logo.png
    }

    location ~* \.(css|js|woff2)$ {
        # Регулярный location для кэширования (см. ниже)
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Разделение контента через `alias`

Когда статика хранится вне корня сайта (например, на отдельном томе или в общей директории):

```nginx
server {
    root /var/www/mysite;

    location /uploads/ {
        alias /mnt/storage/user-uploads/;
        # /uploads/avatar.jpg → /mnt/storage/user-uploads/avatar.jpg
    }

    location /shared-assets/ {
        alias /opt/shared-assets/;
        # /shared-assets/logo.svg → /opt/shared-assets/logo.svg
    }
}
```

### Редирект конкретного URL через точное совпадение

Точный `location =` эффективен для перенаправления устаревших страниц:

```nginx
location = /old-contacts {
    return 301 /contacts;
}
```

- Срабатывает **только** для `/old-contacts`
- `return 301` отправляет браузер и поисковые системы на `/contacts`
- Подробности о редиректах: [Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md#редирект-на-https--новый-url)

### try_files для fallback-маршрутизации

Проверка существования файлов с fallback на фронт-контроллер:

```nginx
location / {
    root /var/www/html;
    try_files $uri $uri/ /index.html =404;
    # 1. Ищет файл по URI
    # 2. Если нет — ищет директорию
    # 3. Если нет — внутреннее перенаправление на /index.html
    # 4. Если /index.html не найден — возвращает 404
}
```

Полное описание `try_files`, включая работу с переменными и сложные сценарии: [Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md#директива-try_files).

---

## Additional Information

### Рекомендации по выбору директивы

| Сценарий | Директива |
|:---------|:----------|
| Статика в подкаталогах корня сайта | `root` |
| Статика вне корня сайта (отдельный том, общий ресурс) | `alias` |
| Переопределение корня для специфических запросов | `root` внутри `location` |
| Fallback на фронт-контроллер | `try_files` |
| Редирект конкретного URL | `location =` + `return` |

### Ограничения

- `alias` не поддерживается внутри `location` с регулярным выражением (`location ~`) — используйте `root` или `rewrite`
- При использовании переменных в пути (`alias /data/$variable/`) требуется осторожность — см. документацию Nginx

### См. также

- [Nginx: Rewrite, Redirect и try_files](../nginx_rewrite_rules_and_try_files.md) — SSoT по `try_files`, `rewrite`, `return`
- [Директива `location`: основы](./basics.md) — типы matching, приоритет
- [Кэширование статических файлов](../../Performance/nginx_static_file_caching.md) — заголовки `Cache-Control`, `expires`
