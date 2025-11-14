# Использование Let's Encrypt с Nginx в Docker

Для автоматического получения и обновления SSL-сертификатов от Let's Encrypt в связке с Nginx, работающим в Docker, удобно использовать официальный образ Certbot.

Идея заключается в запуске двух контейнеров (Nginx и Certbot), которые используют общие `volumes` для обмена сертификатами и для прохождения процедуры верификации `HTTP-01 challenge`.

## Архитектура

1.  **Контейнер Nginx**: Основной веб-сервер, который использует сертификаты для обслуживания трафика по HTTPS.
2.  **Контейнер Certbot**: Периодически запускается для проверки срока действия сертификатов, их обновления и выполнения `HTTP-01 challenge`.
3.  **Общий Volume для сертификатов**: Директория, монтируемая к обоим контейнерам, где Certbot будет сохранять сертификаты, а Nginx — читать их. Обычно это `/etc/letsencrypt`.
4.  **Общий Volume для верификации**: Директория, куда Certbot будет помещать временные файлы для прохождения `HTTP-01 challenge`, а Nginx будет раздавать их по HTTP.

## Пример с Docker Compose

Использование `docker-compose.yml` значительно упрощает управление такой связкой.

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

### Конфигурация Nginx

Ваш Nginx должен быть настроен на обработку `HTTP-01 challenge` и на использование полученных сертификатов.

**Пример конфигурации (`./nginx/conf.d/default.conf`):**

```nginx
# Сервер для HTTP и редиректа на HTTPS
server {
    listen 80;
    server_name your-domain.com;

    # Обработка HTTP-01 challenge от Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# Основной сервер для HTTPS
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Рекомендуемые параметры SSL
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        # ... ваша конфигурация проксирования или раздачи статики
    }
}
```

### Порядок действий

1.  Создайте структуру директорий: `nginx/conf.d`, `certbot/www`, `certbot/conf`.
2.  Поместите конфигурацию Nginx в `nginx/conf.d/default.conf`.
3.  **Первый запуск**:
    *   Запустите Nginx: `docker-compose up -d nginx`.
    *   Запустите Certbot для первоначального получения сертификата (используя `command` в `docker-compose.yml` или отдельной командой `docker-compose run`).
4.  **Рабочий режим**:
    *   Закомментируйте `command` в `docker-compose.yml` и используйте `entrypoint` для автоматического обновления.
    *   Перезапустите Nginx, чтобы он подхватил сгенерированные сертификаты: `docker-compose restart nginx`.

Этот подход обеспечивает полностью автоматизированное управление SSL-сертификатами для вашего Nginx-контейнера.
