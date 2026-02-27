# Nginx location: Примеры интеграции

## Обработка PHP-скриптов

Для обработки PHP-скриптов Nginx обычно использует FastCGI-протокол, взаимодействуя с PHP-FPM.

* **Пример конфигурации для PHP:**

    ```nginx
    location ~ \.php$ {
        root           /var/www/html;
        fastcgi_pass   unix:/var/run/php/php7.4-fpm.sock; # Путь к сокету PHP-FPM
        fastcgi_index  index.php;
        include        fastcgi_params; # Включает стандартные параметры FastCGI
        fastcgi_param  SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
    ```

* Здесь используется регулярное выражение `~ \.php$` для сопоставления всех запросов, заканчивающихся на `.php`.
* `fastcgi_pass` указывает адрес FastCGI-сервера (часто Unix-сокет).
* `fastcgi_param SCRIPT_FILENAME` передает PHP-FPM полный путь к исполняемому скрипту.

## Примеры конфигурации (WordPress)

Типичная конфигурация `location` для WordPress часто включает:

* Перенаправление HTTP на HTTPS. Подробная информация доступна в [Настройка TLS в Nginx: безопасность и скорость](../../../Angie/angie_tls_setup.md). (Ссылка адаптирована под Nginx)
* `location /` с `try_files` для обработки статики и перенаправления на `index.php` для динамического контента.
* `location ~ \.php$` для обработки PHP-скриптов через FastCGI.
* `location` для защиты конфиденциальных файлов (например, `.htaccess`, `wp-config.php`).
* Специальные `location` для статических ресурсов WordPress (например, `/wp-content/`).

```nginx
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name example.com;
    root /var/www/wordpress;
    index index.php index.html index.htm;

    # Защита конфиденциальных файлов начинающиейся с точки (запрет всех файлов с точки кроме .well-known - location ~ /\.(?!well-known).* например /.well-known/acme-challenge/...)
    location ~ /\. {
        deny all; # запрещает доступ все клиентам
    }
    location ~ /(wp-config\.php|wp-trackback\.php|xmlrpc\.php) {
        deny all;
    }

    # Обработка статических файлов и перенаправление на index.php
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # Обработка PHP-скриптов
    location ~ \.php$ {
        include snippets/fastcgi-php.conf; # Или полный набор fastcgi_params
        fastcgi_pass unix:/var/run/php/php7.4-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Специальный location для статики wp-content
    location ~* \.(js|css|png|jpg|jpeg|gif|ico)$ {
        expires max;
        log_not_found off; # Не писать ошибки “файл не найден”
    }
}
```
