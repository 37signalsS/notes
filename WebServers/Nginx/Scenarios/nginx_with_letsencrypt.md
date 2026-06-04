# Настройка Let's Encrypt с Nginx в Docker

## 1. Определения

**Сценарий Nginx + Let's Encrypt в Docker** — метод развёртывания веб-сервера с автоматическим получением и обновлением SSL/TLS (Transport Layer Security) сертификатов в контейнеризированной среде.

* **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный веб-сервер и обратный прокси.
* **Let's Encrypt** — некоммерческий центр сертификации, предоставляющий бесплатные сертификаты.
* **Certbot** — клиент для автоматизации получения и обновления сертификатов.
* **Docker Compose** — инструмент для управления многоконтейнерными приложениями.

> **Подробная информация:** Теоретические основы протокола ACME (Automated Certificate Management Environment), лимиты и универсальные методы установки описаны в руководстве: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

## 2. Базовые концепции

### Архитектура решения

Реализация в Docker (контейнерной среде) строится на взаимодействии двух сервисов через общие **[тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md)**:

1. **Сервис Nginx**: основной веб-сервер, обслуживающий запросы по HTTP (порт 80) и HTTPS (порт 443).
2. **Сервис Certbot**: клиент, отвечающий за проверку владения доменом и управление жизненным циклом сертификатов.
3. **Общий том для верификации**: директория для временных файлов `HTTP-01 challenge` (обычно монтируется как `/var/www/certbot`).
4. **Общий том для сертификатов**: хранилище готовых сертификатов и ключей (обычно монтируется как `/etc/letsencrypt`).

### Процесс HTTP-01 проверки

Для подтверждения владения доменом Certbot размещает секретный токен в директории верификации. Nginx должен быть настроен так, чтобы отдавать этот токен по пути `/.well-known/acme-challenge/`. Центр сертификации запрашивает этот файл по HTTP, и после успешной проверки выдаёт сертификат.

## 3. Практический сценарий

### 3.1. Конфигурация Docker Compose

Файл `docker-compose.yml` описывает связку сервисов и правила их взаимодействия.

> См. также: **[Пример файла Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md)**.

```yaml
version: '3.8'

services:
  nginx:
    image: nginx:1.25-alpine
    container_name: nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./certbot/www:/var/www/certbot:ro
      - ./certbot/conf:/etc/letsencrypt:ro
    restart: unless-stopped

  certbot:
    image: certbot/certbot
    container_name: certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
```

### 3.2. Конфигурация Nginx

Конфигурация должна поддерживать как процесс получения сертификатов, так и их использование.

**Пример (`./nginx/conf.d/default.conf`):**

```nginx
server {
    listen 80;
    server_name example.com;

    # Блок для проверки Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Принудительный редирект на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Рекомендованные параметры безопасности (создаются Certbot)
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        root /usr/share/nginx/html;
        index index.html;
    }
}
```

> Настройка параметров шифрования: **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

### 3.3. Порядок развёртывания

1. **Подготовка директорий**: создать локальные папки `nginx/conf.d`, `certbot/conf` и `certbot/www`.
2. **Начальный запуск**: запустить Nginx с временной конфигурацией (без блока 443), если сертификаты ещё не получены.
3. **Получение сертификата**:

   ```bash
   docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
     --email admin@example.com -d example.com --agree-tos --no-eff-email
   ```

4. **Финальная настройка**: включить блок 443 в конфигурации Nginx и перезапустить сервис: `docker compose restart nginx`.

## 4. Дополнительная информация

### Альтернативные решения

* **[Angie](../../Angie/angie_overview.md)** — форк Nginx с **[встроенным модулем ACME](../../Angie/angie_acme_module.md)**, позволяющим обходиться без Certbot.
* **[Traefik](../../Traefik/traefik_with_docker_compose.md)** — современный прокси с автоматическим управлением сертификатами "из коробки".
* **Nginx Proxy Manager** — графический интерфейс для управления Nginx и SSL.

### См. также

* **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**
* **[Безопасность Nginx](../Security/nginx_security_guide.md)**
* **[Оптимизация производительности Nginx](../Performance/nginx_performance_tuning.md)**
* **[Тома в Docker](../../../Docker/Docker_fs/docker_volumes.md)**
