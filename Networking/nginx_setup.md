# Установка и настройка Nginx + PHP-FPM (LEMP)

 ```bash
apt update && apt -y install nginx
```

```bash
systemctl status nginx
```

## Установка и настройка PHP-FPM

Менеджер процессов PHP-FPM необходим для работы PHP с Nginx.

```bash
apt -y install php-fpm
```

### Запуск и настройка

Запустите и добавьте в автозагрузку (версия PHP может отличаться):

*   (Версия PHP может отличаться, например, `php8.3-fpm`, `php8.4-fpm` и т.д. Используйте актуальную, поддерживаемую версию.)
    ```bash
    systemctl start php-fpm && systemctl enable php-fpm
    ```

Отредактируйте конфигурацию пула PHP-FPM, чтобы сменить пользователя с `apache` на пользователя Nginx:

*   **Debian/Ubuntu (`/etc/php/<ВЕРСИЯ_PHP>/fpm/pool.d/www.conf`):** измените `user` и `group` на `www-data`. (Замените `<ВЕРСИЯ_PHP>` на актуальную, например, `8.3` или `8.4`).
*   **CentOS (`/etc/php-fpm.d/www.conf`):** измените `user` и `group` на `nginx`.

Отредактируйте главный конфигурационный файл PHP (`php.ini`) для безопасности:

*   **Debian/Ubuntu:** `/etc/php/<ВЕРСИЯ_PHP>/fpm/php.ini` (Замените `<ВЕРСИЯ_PHP>` на актуальную).
*   **CentOS:** `/etc/php.ini`

Найдите параметр `cgi.fix_pathinfo`, раскомментируйте его и установите значение `0`:

```ini
cgi.fix_pathinfo=0
```

Перезапустите сервисы для применения настроек:

*   **Debian/Ubuntu:**
    ```bash
    systemctl reload nginx && systemctl reload php-fpm
    ```
*   **CentOS:**
    ```bash
    systemctl reload nginx && systemctl reload php-fpm
    ```

## Настройка Virtual Host (Server Block)

### Базовая конфигурация для сайта

Создайте файл конфигурации для вашего сайта.

**Ubuntu/Debian:**

1.  Удалите символическую ссылку на `default` конфиг:
    ```bash
    unlink /etc/nginx/sites-enabled/default
    ```
2.  Создайте новый файл конфигурации:
    ```bash
    touch /etc/nginx/sites-available/default.conf
    ```
3.  Создайте символическую ссылку на него:
    ```bash
    ln -s /etc/nginx/sites-available/default.conf /etc/nginx/sites-enabled/default.conf
    ```
4.  Добавьте в `/etc/nginx/sites-available/default.conf`:
    ```nginx
    server {
      listen 80;
      server_name _;
      root /var/www/html/;
      index index.php index.html index.htm;

      location / {
        try_files $uri $uri/ =404;
      }

      location ~ \.php$ {
        # Путь к сокету зависит от версии PHP. Проверьте актуальный путь в /run/php/
        # Например: unix:/run/php/php8.3-fpm.sock
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
        include snippets/fastcgi-php.conf;
      }

      location ~ /\.ht {
          deny all;
      }
    }
    ```

**CentOS:**

1.  Создайте файл `/etc/nginx/conf.d/default.conf`.
2.  Добавьте в него:
    ```nginx
    server {
      listen 80;
      server_name _;
      root /var/www/html/;
      index index.php index.html index.htm;

      location / {
        try_files $uri $uri/ =404;
      }

      location ~ \.php$ {
            fastcgi_pass unix:/var/run/php-fpm/php-fpm.sock; # Путь может отличаться
            fastcgi_index index.php;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            include fastcgi_params;
        }

      location ~ /\.ht {
          deny all;
      }
    }
    ```

### Проверка PHP

Создайте файл `/var/www/html/info.php` с содержимым `<?php phpinfo(); ?>` для проверки. Не забудьте удалить его после проверки.

### Конфигурация для нескольких сайтов

**Ubuntu/Debian:**

1.  Отключите старый конфиг: `unlink /etc/nginx/sites-enabled/default.conf`
2.  Создайте новый для сайта `example.com`: `cp /etc/nginx/sites-available/default.conf /etc/nginx/sites-available/example.com.conf`
3.  Отредактируйте `server_name` и `root` в новом файле.
4.  Создайте ссылку: `ln -s /etc/nginx/sites-available/example.com.conf /etc/nginx/sites-enabled/example.com.conf`

**CentOS:**

1.  Создайте директорию: `mkdir /etc/nginx/sites-enabled`
2.  В `/etc/nginx/nginx.conf` внутри блока `http` закомментируйте стандартный блок `server` и добавьте `include /etc/nginx/sites-enabled/*;`.
3.  Создайте файл `/etc/nginx/sites-enabled/example.com.conf` с конфигурацией вашего сайта.

### Конфигурация для WordPress

Это более продвинутая конфигурация для сайта на WordPress (`example.com`).

```nginx
server {
    server_name example.com www.example.com;
    root /var/www/example.com;

    # Security: Deny access to sensitive files
    location = /favicon.ico { log_not_found off; access_log off; }
    location = /robots.txt { allow all; log_not_found off; access_log off; }
    location ~ /\. { deny all; }
    location ~* /(?:uploads|files)/.*\.php$ { deny all; }

    # Handle requests
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # PHP-FPM processing
    location ~ \.php$ {
        include fastcgi.conf;
        fastcgi_intercept_errors on;
        # Путь к сокету зависит от версии PHP. Проверьте актуальный путь.
        # Debian/Ubuntu: unix:/run/php/php8.3-fpm.sock
        # CentOS: unix:/var/run/php-fpm/www.sock
        fastcgi_pass unix:/run/php/php-fpm.sock;
        include snippets/fastcgi-php.conf; # Debian/Ubuntu only
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Caching for static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico)$ {
        expires max;
        log_not_found off;
    }
}
```

После любых изменений проверяйте конфигурацию `nginx -t` и перезагружайте сервис `systemctl reload nginx`.

---

## Порядок обработки `server` блоков

Когда приходит HTTP-запрос, Nginx выбирает подходящий `server` блок по **двум этапам**:

### **ЭТАП 1: Выбор по `listen`**

Nginx сначала выбирает **все `server` блоки**, у которых `listen` порт совпадает с портом запроса (например, `80` или `443`).

### **ЭТАП 2: Выбор по `server_name`**

Среди выбранных на первом этапе блоков, Nginx ищет **наиболее подходящее значение `server_name`**, сравнивая его с заголовком `Host` из запроса.

**Правила приоритета:**

1.  **Точное совпадение** с `server_name` — приоритет №1.
2.  **Маска с `*` в начале** (`*.example.com`) — менее приоритетны.
3.  **Маска с `*` в конце** (`www.example.*`) — еще менее приоритетны.
4.  **Регулярные выражения (`~`)** — ещё ниже.
5.  **Если ничего не подошло** — используется **первый объявленный `server` блок** для данного порта, он считается **сервером по умолчанию**.

### `default_server`

Вы можете **вручную указать**, какой `server` использовать по умолчанию, добавив флаг `default_server` к директиве `listen`. Это полезно для "отлова" всех запросов, которые не соответствуют ни одному из доменов.

```nginx
server {
    listen 80 default_server;
    server_name _; # _ - невалидное имя, которое никогда не совпадет
    return 444; # Закрыть соединение без ответа
}
```

### HTTPS и SNI

С TLS (порт 443) выбор `server` работает так же, **но только после того, как завершено TLS-рукопожатие**. Используется **SNI (Server Name Indication)** — клиент сообщает имя хоста ещё до расшифровки HTTPS, что позволяет Nginx выбрать правильный сертификат и `server` блок.

---

## Порядок обработки `location` блоков

Внутри выбранного `server` блока Nginx ищет наиболее подходящий `location` для обработки запроса.

**Приоритет:**

1.  **`=` (Точное совпадение):** `location = /path`
    -   Срабатывает **только если URI в точности совпадает**.
    -   Пример: `location = /about` сработает для `/about`, но не для `/about/`.
    -   **Приоритет №1.** Поиск прекращается после нахождения.

2.  **`^~` (Префикс с высоким приоритетом):** `location ^~ /images/`
    -   Совпадение по **началу строки URI**.
    -   Если найден самый длинный подходящий префикс с этим модификатором, **поиск регулярных выражений не производится**.
    -   Используется, чтобы "защитить" часть URI от проверки регулярками.

3.  **`~` и `~*` (Регулярные выражения):**
    -   `~` — с учетом регистра.
    -   `~*` — без учета регистра.
    -   Проверяются **в порядке их появления в конфигурационном файле**.
    -   **Первое совпавшее** регулярное выражение используется для обработки запроса.

4.  **Префиксное совпадение (без модификатора):** `location /path/`
    -   Совпадение по **началу строки URI**.
    -   Nginx запоминает **самое длинное** совпадение.

5.  **`location /` (блок по умолчанию):**
    -   Если ничего другого не подошло, используется этот блок.

**Алгоритм выбора:**

1.  Nginx ищет точное совпадение (`=`). Если находит — использует его.
2.  Nginx проверяет все префиксные `location` и запоминает **самый длинный**.
3.  Если самый длинный префикс имел модификатор `^~`, Nginx использует его и прекращает поиск.
4.  Nginx проверяет все регулярные выражения (`~`, `~*`) **по порядку**. Если находит совпадение — использует его и прекращает поиск.
5.  Если ни одно регулярное выражение не совпало, Nginx использует **самый длинный префиксный `location`**, который он запомнил на шаге 2.

---

## Директивы `root` и `alias`

Обе директивы определяют, где на диске искать файлы, но делают это по-разному.

### `root`

-   **Как работает:** Добавляет URI запроса к пути, указанному в `root`.
-   **Пример:**
    ```nginx
    location /static/ {
        root /var/www/app;
    }
    ```
    -   Запрос: `/static/img/logo.png`
    -   Реальный путь: `/var/www/app` + `/static/img/logo.png` = `/var/www/app/static/img/logo.png`

### `alias`

-   **Как работает:** **Заменяет** часть URI, совпадающую с `location`, на путь, указанный в `alias`.
-   **Пример:**
    ```nginx
    location /static/ {
        alias /var/www/app/assets/;
    }
    ```
    -   Запрос: `/static/img/logo.png`
    -   Реальный путь: `/var/www/app/assets/` + `img/logo.png` = `/var/www/app/assets/img/logo.png`

**Ключевое отличие:** `alias` "отбрасывает" префикс `location` из пути.

**Когда использовать `alias`:**
-   Когда физический путь на диске не соответствует структуре URI.
-   Особенно полезен с регулярными выражениями и именованными группами.

**Пример с регулярным выражением:**
```nginx
location ~ ^/image1/(?<file>.+\.jpg)$ {
    alias /var/www/images/$file;
}
```
-   Запрос: `/image1/cats/kitty.jpg`
-   `$file` становится `cats/kitty.jpg`.
-   Реальный путь: `/var/www/images/cats/kitty.jpg`.

---

## Разбор регулярного выражения в `location`

Рассмотрим выражение `~ ^/image1/(?<file>.+\.jpg)$`.

1.  **`~`**
    -   Указывает, что это регулярное выражение с учетом регистра.

2.  **`^`**
    -   **Начало строки**. Указывает, что URI должен начинаться со следующего за ним шаблона.

3.  **`/image1/`**
    -   **Буквальный текст**: URI должен содержать `/image1/`.

4.  **`(?<file>.+\.jpg)`**
    -   Это **именованная группа захвата (named capture group)**.
    -   `(?<file>...)`: Все, что совпадет с шаблоном внутри скобок, будет сохранено в переменную `$file`.
    -   `.+`: Точка (`.`) означает любой символ (кроме новой строки), а плюс (`+`) — один или более раз. То есть, захватываем любую последовательность символов.
    -   `\.jpg`: Экранированная точка (`\.`) означает буквальный символ точки, за которым следует `jpg`.
    -   Вместе это означает: захватить любую последовательность символов, заканчивающуюся на `.jpg`, и сохранить ее в переменную `$file`.

5.  **`$`**
    -   **Конец строки**. Указывает, что после `.jpg` в URI больше ничего не должно быть.


