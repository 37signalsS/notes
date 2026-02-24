# Nginx location: Отдача статических файлов

## Редирект для старого адреса (с использованием `=`)

Точное совпадение идеально подходит для перенаправления конкретных, устаревших URL.

```nginx
location = /old-contacts {
    return 301 /contacts;
}

```

* Этот блок сработает **только** для запроса `http://site.local/old-contacts`.
* Директива `return 301` немедленно останавливает обработку и отправляет браузеру и поисковым системам сигнал, что страница навсегда переехала на новый адрес `/contacts`. Подробнее о редиректах в файле о **[правилах rewrite и redirect](../nginx_rewrite_rules_and_try_files.md)**.

## Работа с файловой системой: `root` и `alias`

Директивы `root` и `alias` определяют, как Nginx сопоставляет URI запроса с файлами на диске.

### Директива `root`

`root` определяет корневой каталог для запросов. Nginx добавляет полный URI запроса к значению `root` для формирования пути к файлу.

* **Пример:**

    ```nginx
    server {
        root /var/www/html;
        location /images/ {
            # Запрос /images/pic.jpg будет искать файл по пути /var/www/html/images/pic.jpg
        }
        location = /test.html {
            root /var/www/special_tests;
            # Запрос /test.html будет искать файл по пути /var/www/special_tests/test.html
            # Это позволяет отдавать специфические файлы из других директорий.
        }
    }
    ```

* `root` может быть определен на уровне `http`, `server` или `location`. Если `root` не указан в `location`, он наследуется от родительского блока.

### Директива `alias`

`alias` используется для замены части URI запроса на указанный путь в файловой системе. `alias` может использоваться только внутри `location`.

* **Пример:**

    ```nginx
    location /static/ {
        alias /opt/data/static_files/;
        # Запрос /static/css/style.css будет искать файл по пути /opt/data/static_files/css/style.css
        # Часть "/static/" из URI заменяется на "/opt/data/static_files/"
    }
    location /foot/ {
        alias /var/www/special_content/;
        # Запрос /foot/test.html будет искать файл по пути /var/www/special_content/test.html
        # Здесь "/foot/" из URI заменяется на "/var/www/special_content/".
        # Важно: если location заканчивается слэшем, alias также должен заканчиваться слэшем.
    }
    location /images/ {
        alias /var/www/site1.local/images/;
        # Этот блок "ловит" все запросы, URI которых начинается с /images/.
        # Директива alias говорит Nginx: "возьми ту часть запроса, которая совпала с location (/images/),
        # отбрось её и вместо неё используй указанный путь (/var/www/site1.local/images/)".
    }
    ```

* **Важное отличие от `root`:** `alias` заменяет префикс URI, соответствующий `location`, тогда как `root` добавляет весь URI к корневому пути.
* При использовании `alias` важно, чтобы путь `alias` заканчивался слэшем, если `location` также заканчивается слэшем, чтобы избежать некорректного формирования пути.

## Обработка статических файлов и `try_files`

Директива `try_files` позволяет Nginx проверять существование файлов или директорий в указанном порядке и выполнять внутреннее перенаправление, если ни один из них не найден. Более подробно о `try_files`, а также о правилах rewrite и redirect можно узнать в [Nginx: Правила Rewrite, Redirect и Директива try_files](../nginx_rewrite_rules_and_try_files.md).

* **Синтаксис:** `try_files file ... uri;` или `try_files file ... =code;`
* **Пример:**

    ```nginx
    location / {
        root /var/www/html;
        try_files $uri $uri/ /index.html =404;
        # 1. Пробует найти файл, соответствующий URI ($uri).
        # 2. Если не найден, пробует найти директорию ($uri/).
        # 3. Если и директория не найдена, делает внутреннее перенаправление на /index.html.
        # 4. Если /index.html также не найден, возвращает ошибку 404.
    }
    ```

* `try_files` часто используется для обработки "красивых" URL (pretty URLs) в CMS, где все запросы, не соответствующие существующим файлам или директориям, перенаправляются на основной скрипт (например, `index.php`).
