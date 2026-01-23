# Использование Let's Encrypt с Nginx в Docker

## 1. Определения и Основные концепции

### Let's Encrypt и Certbot

**Let's Encrypt** — это бесплатный автоматизированный и открытый центр сертификации. **Certbot** — это клиент, который используется для автоматического получения и обновления сертификатов от Let's Encrypt.

> Подробное описание их работы и методов установки на хост-систему (без Docker) находится в основной заметке: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

### Архитектура решения в Docker

Идея заключается в запуске двух контейнеров ([Nginx](../Core/nginx_overview.md) и Certbot), которые используют общие **[тома (volumes)](../../Docker/Docker_fs/docker_volumes.md)** для обмена данными:

1.  **Контейнер Nginx**: Основной веб-сервер, который использует сертификаты для обслуживания трафика по HTTPS.
2.  **Контейнер Certbot**: Периодически запускается для проверки срока действия сертификатов, их обновления и выполнения верификации `HTTP-01 challenge`.
3.  **Общий Volume для сертификатов**: Директория, монтируемая к обоим контейнерам (обычно `/etc/letsencrypt`), где Certbot сохраняет сертификаты, а Nginx их читает.
4.  **Общий Volume для верификации**: Директория, куда Certbot помещает временные файлы для верификации, а Nginx раздает их по HTTP.

## 2. Практический сценарий: Docker Compose

Использование `docker-compose.yml` значительно упрощает управление такой связкой.

> Для детального понимания синтаксиса и директив Docker Compose обратитесь к руководству: **[Обзор Docker Compose](../../Docker/Docker_compose/docker_compose_overview.md)**.

```yaml
version: '3.7'

services:
  nginx:
    image: nginx:1.25.5
    container_name: nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      # Конфигурация Nginx
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      # Общая директория для верификации
      - ./certbot/www:/var/www/certbot:ro
      # Директория с сертификатами
      - ./certbot/conf:/etc/letsencrypt:ro
    restart: unless-stopped

  certbot:
    image: certbot/certbot:v2.10.0
    container_name: certbot
    volumes:
      # Директория с сертификатами
      - ./certbot/conf:/etc/letsencrypt
      # Общая директория для верификации
      - ./certbot/www:/var/www/certbot
    # Команда на получение сертификата
    # Запускается только при первом старте, затем комментируется
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
    # Для первого запуска можно использовать:
    # command: certonly --webroot -w /var/www/certbot --email your-email@example.com -d your-domain.com --agree-tos --no-eff-email -n
```

### Пояснения к `docker-compose.yml`

*   **`nginx.volumes`**:
    *   `./nginx/conf.d`: Директория с вашей конфигурацией Nginx.
    *   `./certbot/www`: Общая директория для `HTTP-01 challenge`. Nginx должен быть настроен на раздачу контента из `/var/www/certbot/.well-known/acme-challenge`.
    *   `./certbot/conf`: Директория, где будут храниться полученные сертификаты.

*   **`certbot.entrypoint`**: Эта команда запускает бесконечный цикл, который раз в 12 часов пытается обновить сертификаты (`certbot renew`).

## 3. Продвинутые детали

### Конфигурация Nginx

Ваш Nginx должен быть настроен на обработку `HTTP-01 challenge` и на использование полученных сертификатов.

**Пример конфигурации (`./nginx/conf.d/default.conf`):**

#### Блок 1: Обработка HTTP (порт 80) и перенаправление на HTTPS

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Обработка HTTP-01 challenge от Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Перенаправление всего остального трафика на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}
```

**Пояснения к блоку:**

*   `listen 80;`: Указывает Nginx слушать входящие соединения на порту 80 (стандартный порт для HTTP).
*   `server_name your-domain.com;`: Определяет, что данный блок `server` должен обрабатывать запросы, предназначенные для `your-domain.com`.
*   `location /.well-known/acme-challenge/ { ... }`: Этот блок необходим для прохождения верификации Let's Encrypt. Он указывает, что файлы для проверки домена нужно искать в директории `/var/www/certbot`.
*   `location / { ... }`: Перехватывает все остальные запросы.
    *   `return 301 https://$host$request_uri;`: Ключевая директива для перенаправления. Nginx немедленно отправляет клиенту ответ с кодом `301 Moved Permanently` (ресурс навсегда перемещен) на тот же URI, но с протоколом `https://`.

**Итог по блоку:** Любой запрос, приходящий на `http://your-domain.com`, будет принудительно и навсегда перенаправлен на `https://your-domain.com` с сохранением исходного пути. Исключение составляют запросы для верификации сертификата.

---

#### Блок 2: Обработка HTTPS (порт 443)

```nginx
# Основной сервер для HTTPS
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # Пути к сертификатам
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Рекомендуемые параметры SSL от Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Корень сайта и индексный файл
    root /var/www/html;
    index index.html;

    location / {
        # ... ваша конфигурация проксирования или раздачи статики
        # Например: proxy_pass http://my-backend;
    }
}
```

**Пояснения к блоку:**

*   `listen 443 ssl http2;`: Указывает Nginx слушать порт 443 (стандартный для HTTPS), использовать `SSL/TLS` для шифрования и, если возможно, `HTTP/2` для улучшения производительности.
*   `ssl_certificate ...`: Путь к файлу публичного сертификата, который Nginx отправляет клиенту.
*   `ssl_certificate_key ...`: Путь к файлу приватного ключа, который используется для расшифровки данных. **Этот файл должен быть строго защищен**.
*   `include /etc/letsencrypt/options-ssl-nginx.conf;`: Подключает файл с рекомендованными настройками безопасности TLS, сгенерированный Certbot.
*   `ssl_dhparam ...`: Указывает путь к файлу с параметрами Диффи-Хеллмана для усиления безопасности.
*   `root /var/www/html;`: "Корень сайта". Директория, в которой Nginx ищет файлы для отдачи клиенту.
*   `index index.html;`: Файл, который будет отдан по умолчанию, если в запросе не указан конкретный.

**Итог по блоку:** Этот блок принимает зашифрованные соединения для `your-domain.com`, обрабатывает их с помощью указанных сертификатов и отдает статические файлы из директории `/var/www/html`.

> Для глубокой настройки всех параметров TLS/SSL, выбора шифров и оптимизации производительности обратитесь к основному руководству: **[Оптимальная настройка TLS/SSL в Nginx](../Security/nginx_tls_ssl_configuration.md)**.

### Порядок действий

1.  Создайте структуру директорий: `nginx/conf.d`, `certbot/www`, `certbot/conf`.
2.  Поместите конфигурацию Nginx в `nginx/conf.d/default.conf`.
3.  **Первый запуск**:
    *   Запустите Nginx: `docker-compose up -d nginx`.
    *   Запустите Certbot для первоначального получения сертификата (используя `command` в `docker-compose.yml` или отдельной командой `docker-compose run`).
4.  **Рабочий режим**:
    *   Закомментируйте `command` в `docker-compose.yml` и используйте `entrypoint` для автоматического обновления.
    *   Перезапустите Nginx, чтобы он подхватил сгенерированные сертификаты: `docker-compose restart nginx`.

## 4. Альтернативные подходы

- **Установка на хост-систему (без Docker)**: Если Nginx установлен непосредственно на сервере, используйте стандартный метод, описанный в руководстве: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

- **Обратный прокси Traefik**: Для тех, кто использует Docker, **[Traefik](../../Traefik/traefik_with_docker_compose.md)** является популярной альтернативой Nginx, предлагая полностью автоматизированное управление SSL-сертификатами "из коробки".

- **Встроенный ACME-клиент в Angie**: Форк Nginx **[Angie](../../Angie/angie_overview.md)** имеет **[встроенный модуль ACME](../../Angie/angie_acme_module.md)**, который позволяет получать сертификаты без использования внешних клиентов вроде Certbot.
