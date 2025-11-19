# Перенаправления и перезапись URI в Angie (Nginx)

В этом документе рассматриваются способы настройки перенаправлений (редиректов) и изменения URI запросов в Angie с использованием модуля `rewrite`.

## 1. Директива `rewrite`

Директива `rewrite` позволяет изменять URI запроса с помощью регулярных выражений.

**Синтаксис:** `rewrite regex replacement [flag];`

-   `regex`: Регулярное выражение, с которым сопоставляется URI запроса (без GET-параметров).
-   `replacement`: Строка, на которую заменяется совпавшая часть URI.
-   `flag`: Флаг, определяющий дальнейшее поведение.

### 1.1. Флаги `permanent` и `redirect` (Внешние редиректы)

Эти флаги отправляют клиенту HTTP-ответ с кодом перенаправления и заголовком `Location`.

-   **`permanent`**: Возвращает код `301 Moved Permanently`. Этот редирект активно кэшируется браузерами.
-   **`redirect`**: Возвращает код `302 Found` (временный редирект).

**Пример:**
```nginx
server {
    listen 81;
    root /path/to/static/site;

    # 301 редирект
    rewrite ^/bg.jpg$ /images/pic01.jpg permanent;

    # 302 редирект
    rewrite ^/old-page$ /new-page redirect;
}
```

**Проверка с помощью `curl`:**
```bash
# Проверка 301 редиректа
curl -I http://localhost:81/bg.jpg
# HTTP/1.1 301 Moved Permanently
# Location: /images/pic01.jpg

# Проверка 302 редиректа
curl -I http://localhost:81/old-page
# HTTP/1.1 302 Found
# Location: /new-page
```

**Важно:** Внешние редиректы создают дополнительные запросы от клиента, что может увеличивать задержки при загрузке.

### 1.2. Флаги `last` и `break` (Внутренние перезаписи)

Эти флаги изменяют URI запроса внутри Angie, не отправляя редирект клиенту. Адрес в браузере пользователя не меняется.

-   **`last`**: Прекращает обработку текущего набора директив `rewrite` и начинает новый цикл поиска `location` с измененным URI.
-   **`break`**: Прекращает обработку директив `rewrite` и обрабатывает запрос в *текущем* `location` с измененным URI. Поиск нового `location` не производится.

**Пример с `last`:**
```nginx
location / {
    # Запрос к /test.txt будет внутренне переписан на /test/
    # и Angie начнет искать location, который соответствует /test/
    rewrite ^/test\.txt$ /test/ last;
}

location /test/ {
    # ... обработка запроса для директории /test/
}
```
При запросе `http://localhost/test.txt` пользователь увидит содержимое директории `/test/`, но URL в браузере останется прежним.

**Пример с `break`:**
```nginx
location /proxy-path/ {
    # Перезаписываем URI, но остаемся в этом же location
    rewrite ^/proxy-path/(.*)$ /index.php?q=$1 break;
    proxy_pass http://backend;
}
```
Здесь запрос к `/proxy-path/some-page` будет переписан в `/index.php?q=some-page` и отправлен на `http://backend` в рамках того же `location`.

## 2. Директива `return`

Для простых перенаправлений, не требующих регулярных выражений, эффективнее использовать директиву `return`.

**Синтаксис:** `return code [text | URL];`

**Пример: редирект с HTTP на HTTPS**
Это стандартная практика для обеспечения безопасности.
```nginx
server {
    listen 80;
    server_name example.com www.example.com;
    
    # Возвращаем 301 редирект на HTTPS-версию сайта, сохраняя URI
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com;
    # ... остальная конфигурация HTTPS
}
```
- `$host`: Имя хоста из запроса.
- `$request_uri`: Полный URI запроса, включая GET-параметры.

## 3. Условная обработка с `if` и `map`

Директива `if` позволяет выполнять действия при выполнении определенного условия. Однако ее использование сопряжено с рядом ограничений (см. [If Is Evil](https://www.nginx.com/resources/wiki/start/topics/depth/ifisevil/)). Более безопасной и гибкой альтернативой является использование директивы `map`.

### 3.1. Директива `map`

`map` позволяет создавать переменные, значения которых зависят от значений других переменных. Блок `map` должен находиться на уровне `http`.

**Пример: блокировка ботов по User-Agent**

1.  **Создаем `map` в `angie.conf`:**
    ```nginx
    # /etc/angie/angie.conf
    http {
        # ...
        map $http_user_agent $is_bot {
            default 0;
            "~*(Googlebot|Bingbot|curl)" 1;
        }
        # ...
    }
    ```
    - Если `$http_user_agent` совпадает с регулярным выражением, переменная `$is_bot` устанавливается в `1`, иначе — в `0`.

2.  **Используем переменную в `server` блоке:**
    ```nginx
    # /etc/angie/sites-enabled/default
    server {
        # ...
        if ($is_bot) {
            return 401; # Возвращаем ошибку 401 Unauthorized для ботов
        }
        # ...
    }
    ```
    Такая конструкция с `if` считается безопасной, так как `return` является одной из немногих директив, которые надежно работают внутри `if`.

## 4. Отладка `rewrite`

Для отладки правил перезаписи можно включить специальное логирование.

1.  **Включите `rewrite_log`:**
    ```nginx
    server {
        # ...
        rewrite_log on;
        # ...
    }
    ```

2.  **Установите уровень логирования для `error_log`:**
    Правила `rewrite` логируются на уровне `notice`.
    ```nginx
    # /etc/angie/angie.conf
    error_log /var/log/angie/error.log notice;
    ```

После перезагрузки конфигурации в `error.log` появятся подробные сообщения о работе регулярных выражений и результатах перезаписи URI.

## 5. См. также

*   [Директивы `location` в Angie](./angie_location_directives.md)
*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)
*   [Установка Angie из пакетов](./angie_installation.md)
*   [Почему стоит переходить на Angie](./angie_why_migrate.md)
