# Использование Let's Encrypt с Nginx в Docker

## 1. Определения

### Let's Encrypt и Certbot

**Let's Encrypt** — некоммерческий центр сертификации, предоставляющий бесплатные SSL/TLS сертификаты через протокол **ACME**.

**Certbot** — клиент для автоматического получения и обновления сертификатов от Let's Encrypt.

> **Основной источник:** Подробное описание работы ACME, рейтлимитинга и методов установки на хост-систему находится в основных заметках:
> - **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)** (универсальное руководство)
> - **[Автоматические TLS-сертификаты в Angie](../../Angie/angie_acme_module.md)** (встроенный ACME-модуль в Angie)

## 2. Базовые концепции

### Архитектура решения в Docker

Идея заключается в запуске двух контейнеров ([Nginx](../Core/nginx_overview.md) и Certbot), которые используют общие **[тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md)** для обмена данными:

1. **Контейнер Nginx**: Основной веб-сервер, который использует сертификаты для обслуживания трафика по HTTPS.
2. **Контейнер Certbot**: Периодически запускается для проверки срока действия сертификатов, их обновления и выполнения верификации `HTTP-01 challenge`.
3. **Общий Volume для сертификатов**: Директория, монтируемая к обоим контейнерам (обычно `/etc/letsencrypt`), где Certbot сохраняет сертификаты, а Nginx их читает.
4. **Общий Volume для верификации**: Директория, куда Certbot помещает временные файлы для верификации, а Nginx раздает их по HTTP.

## 3. Практический сценарий

### 3.1. Конфигурация Docker Compose

Использование `docker-compose.yml` значительно упрощает управление связкой Nginx и Certbot.

> Для детального понимания синтаксиса и директив Docker Compose обратитесь к руководству: **[Обзор Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md)**.

```yaml
# docker-compose.yml
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

**Пояснения к `docker-compose.yml`**:

* **`nginx.volumes`**:
  * `./nginx/conf.d`: Директория с вашей конфигурацией Nginx.
  * `./certbot/www`: Общая директория для `HTTP-01 challenge`. Nginx должен быть настроен на раздачу контента из `/var/www/certbot/.well-known/acme-challenge`.
  * `./certbot/conf`: Директория, где будут храниться полученные сертификаты.
* **`certbot.entrypoint`**: Эта команда запускает бесконечный цикл, который раз в 12 часов пытается обновить сертификаты (`certbot renew`).

---

### 3.2. Конфигурация Nginx

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

* `listen 80;`: Указывает Nginx слушать входящие соединения на порту 80 (стандартный порт для HTTP).
* `location /.well-known/acme-challenge/ { ... }`: Этот блок необходим для прохождения верификации Let's Encrypt. Он указывает, что файлы для проверки домена нужно искать в директории `/var/www/certbot`.
* `location / { ... }`: Перехватывает все остальные запросы и принудительно перенаправляет их на `https://`.

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

* `listen 443 ssl http2;`: Указывает Nginx слушать порт 443 (стандартный для HTTPS), использовать `SSL/TLS` для шифрования и, если возможно, `HTTP/2`.
* `ssl_certificate ...` и `ssl_certificate_key ...`: Пути к файлам сертификата и приватного ключа.
* `include ...` и `ssl_dhparam ...`: Подключение рекомендованных параметров безопасности от Certbot.

> Для глубокой настройки всех параметров TLS/SSL, выбора шифров и оптимизации производительности обратитесь к основному руководству: **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

---

### 3.3. Порядок действий

1. **Подготовка**: Создайте структуру директорий: `nginx/conf.d`, `certbot/www`, `certbot/conf`. Поместите конфигурацию Nginx в `nginx/conf.d/default.conf`.
2. **Первый запуск (получение сертификата)**:
    * Запустите Nginx: `docker-compose up -d nginx`.
    * Запустите Certbot для первоначального получения сертификата (используя `command` в `docker-compose.yml` или отдельной командой `docker-compose run`).
3. **Рабочий режим**:
    * Убедитесь, что в `docker-compose.yml` для `certbot` используется `entrypoint` для автоматического обновления, а `command` закомментирован.
    * Перезапустите Nginx, чтобы он подхватил сгенерированные сертификаты: `docker-compose restart nginx`.

## 4. Дополнительная информация

### Альтернативные подходы

* **Установка на хост-систему (без Docker)**: Если Nginx установлен непосредственно на сервере, используйте стандартный метод, описанный в руководстве: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

* **Обратный прокси Traefik**: Для тех, кто использует Docker, **[Traefik](../../Traefik/traefik_with_docker_compose.md)** является популярной альтернативой Nginx, предлагая полностью автоматизированное управление SSL-сертификатами "из коробки".

* **Встроенный ACME-клиент в Angie**: Форк Nginx **[Angie](../../Angie/angie_overview.md)** имеет **[встроенный модуль ACME](../../Angie/angie_acme_module.md)**, который позволяет получать сертификаты без использования внешних клиентов вроде Certbot.
