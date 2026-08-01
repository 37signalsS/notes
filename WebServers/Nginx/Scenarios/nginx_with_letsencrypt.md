# Настройка Let's Encrypt с Nginx в Docker

## 1. Определения

**Сценарий Nginx + Let's Encrypt в Docker** — метод развёртывания веб-сервера с автоматическим получением и обновлением SSL/TLS (Transport Layer Security) сертификатов в контейнеризированной среде.

*   **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный веб-сервер и обратный прокси. В данном сценарии используется версия 1.27+ для поддержки современных протоколов.
*   **Let's Encrypt** — некоммерческий центр сертификации (CA), предоставляющий бесплатные сертификаты.
*   **Certbot** — официальный клиент для автоматизации получения и продления сертификатов через протокол ACME.
*   **Docker Compose** — инструмент для управления многоконтейнерными приложениями, обеспечивающий связь между веб-сервером и клиентом сертификации.

> **Подробная информация:** Теоретические основы протокола ACME (Automated Certificate Management Environment), лимиты и универсальные методы установки описаны в руководстве: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

## 2. Базовые концепции

### Архитектура решения

Реализация в Docker строится на взаимодействии двух сервисов через общие **[тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md)**:

1.  **Сервис Nginx**: основной веб-сервер. Монтирует сертификаты в режиме "только чтение" (`ro`).
2.  **Сервис Certbot**: клиент, отвечающий за проверку владения доменом и обновление сертификатов. Имеет права на запись в общие тома.
3.  **Общий том для верификации** (`webroot`): директория для временных файлов `HTTP-01 challenge` (обычно `/var/www/certbot`).
4.  **Общий том для сертификатов**: хранилище готовых ключей и цепочек сертификатов (`/etc/letsencrypt`).

### Процесс автоматизации

*   **Валидация**: Certbot размещает токен в `webroot`. Let's Encrypt проверяет его через HTTP (порт 80).
*   **Обновление**: Certbot запускается по расписанию (раз в 12 часов) и проверяет срок действия.
*   **Перезагрузка**: После успешного обновления Nginx должен перечитать файлы с диска. В контейнерной среде это реализуется через фоновый цикл `nginx -s reload` или внешние триггеры.

## 3. Практический сценарий

### 3.1. Конфигурация Docker Compose

Современный подход исключает использование ключа `version`. Используется Nginx 1.27 на базе Alpine для минимизации размера образа.

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    container_name: nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    # Цикл для автоматической перезагрузки Nginx каждые 6 часов
    command: "/bin/sh -c 'while :; do sleep 6h & wait $${!}; nginx -s reload; done & nginx -g \"daemon off;\"'"

  certbot:
    image: certbot/certbot
    container_name: certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    # Проверка обновлений каждые 12 часов
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
```

### 3.2. Конфигурация Nginx

В Nginx 1.27+ параметр `http2` в директиве `listen` является устаревшим. Необходимо использовать отдельную директиву `http2 on;`.

**Пример (`./nginx/conf.d/default.conf`):**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com;

    # Блок для проверки Let's Encrypt (ACME Challenge)
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Редирект всех HTTP запросов на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com;

    # Включение HTTP/2 (актуальный синтаксис 1.27+)
    http2 on;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Настройки безопасности (Mozilla Modern Profile)
    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # HSTS (Strict Transport Security)
    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        root   /usr/share/nginx/html;
        index  index.html;
    }
}
```

> Настройка параметров шифрования: **[Оптимальная настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

### 3.3. Решение проблемы «курицы и яйца» (Первый запуск)

Nginx не запустится, если файлы сертификатов, указанные в конфиге, отсутствуют.

1.  **Холодный старт**: Временно закомментируйте блок `443` в `default.conf`.
2.  **Запуск HTTP**: Выполните `docker compose up -d nginx`.
3.  **Запрос сертификата**:
    ```bash
    docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
      --email admin@example.com -d example.com --agree-tos --no-eff-email
    ```
4.  **Активация HTTPS**: Раскомментируйте блок `443` и перезапустите Nginx: `docker compose restart nginx`.

## 4. Дополнительная информация

### Рекомендации по эксплуатации

*   **Wildcard сертификаты**: Для получения сертификатов вида `*.example.com` необходимо использовать `DNS-01 challenge`, что потребует API-ключей вашего DNS-провайдера и специализированных плагинов для Certbot.
*   **Безопасность**: Используйте [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/) для генерации актуальных настроек TLS под конкретные нужды проекта.
*   **Мониторинг**: Следите за логами сервиса `certbot` для раннего обнаружения проблем с продлением (например, при изменении правил Firewall на порту 80).

### Альтернативные решения

*   **[Angie](../../Angie/angie_overview.md)** — форк Nginx с **[встроенным модулем ACME](../../Angie/angie_acme_module.md)**, позволяющим получать сертификаты без внешних утилит.
*   **[Traefik](../../Traefik/traefik_with_docker_compose.md)** — современный Edge Router с нативной поддержкой Let's Encrypt и Docker.
*   **Nginx Proxy Manager** — решение с веб-интерфейсом для управления проксированием и SSL.

### См. также

*   **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**
*   **[Безопасность Nginx](../Security/nginx_security_guide.md)**
*   **[Оптимизация производительности Nginx](../Performance/nginx_performance_tuning.md)**

---
**Достоверность:** 10 (Внутренняя верификация + Web) | **Актуальность:** Nginx 1.27 (Mainline), Docker Compose V2
