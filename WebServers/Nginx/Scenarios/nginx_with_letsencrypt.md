# Настройка Let's Encrypt с Nginx

## 1. Определения

**ACME (Automated Certificate Management Environment)** — протокол автоматизированного управления TLS-сертификатами (RFC 8555), используемый Let's Encrypt для выдачи, обновления и отзыва сертификатов без ручного участия.

**Let's Encrypt** — некоммерческий центр сертификации (CA), предоставляющий бесплатные TLS-сертификаты с 90-дневным сроком действия через ACME-протокол.

**Certbot** — официальный клиент EFF (Electronic Frontier Foundation) для автоматизации взаимодействия с CA. Поддерживает плагины для Nginx/Apache и метод webroot.

**Webroot** — метод авторизации ACME HTTP-01: проверочный файл размещается в `.well-known/acme-challenge/` на веб-сервере.

**ACME Challenge** — проверка владения доменом:
- **HTTP-01** — через размещение файла по HTTP (порт 80). Не поддерживает wildcard.
- **DNS-01** — через TXT-запись `_acme-challenge.example.com` в DNS. Поддерживает wildcard, требует API DNS-провайдера.

**Renewal Hook** — скрипт или команда, выполняемая Certbot после успешного обновления сертификата. Используется для перезагрузки Nginx (`nginx -s reload`).

**Dual Stack (ECDSA + RSA)** — одновременное использование двух типов ключей для одного домена. Nginx автоматически выбирает подходящий сертификат по возможностям клиента.

> Теоретические основы ACME, лимиты запросов, ECDSA vs RSA и универсальные методы установки Certbot описаны в **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

## 2. Базовые концепции

### Жизненный цикл сертификата

1. **Выдача**: Certbot размещает токен в `webroot`, CA проверяет его доступность по HTTP.
2. **Хранение**: Сертификаты сохраняются в `/etc/letsencrypt/live/<domain>/` (symlink на `/etc/letsencrypt/archive/<domain>/`).
3. **Обновление**: Certbot запускается по расписанию (раз в 12 часов) и проверяет срок действия. При остатке ~30 дней выполняет обновление.
4. **Активация**: После обновления файлов на диске Nginx должен перечитать конфигурацию (`nginx -s reload`). В Docker это реализуется через фоновый цикл; на bare metal — через renewal hook или systemd.

### Архитектура решения

#### Docker

Реализация строится на взаимодействии двух сервисов через общие **[тома (volumes)](../../../Docker/Docker_fs/docker_volumes.md)**:

1. **Сервис Nginx** — основной веб-сервер. Монтирует сертификаты в режиме `ro`.
2. **Сервис Certbot** — клиент, отвечающий за проверку владения доменом и обновление сертификатов. Имеет права на запись в общие тома.
3. **Общий том для верификации** (`webroot`): директория для временных файлов `HTTP-01 challenge` (обычно `/var/www/certbot`).
4. **Общий том для сертификатов**: хранилище готовых ключей и цепочек сертификатов (`/etc/letsencrypt`).

#### Bare metal / systemd

На физическом сервере или виртуальной машине:
1. **Nginx** — работает как systemd-сервис (`nginx.service`).
2. **Certbot** — работает как systemd-таймер (`certbot.timer`) или cron-задача.
3. **Renewal hook** — скрипт в `/etc/letsencrypt/renewal-hooks/deploy/`, вызываемый после успешного обновления.

### Принцип работы renewal hook

Certbot вызывает hook после записи новых файлов в `/etc/letsencrypt/archive/`. Рекомендуемый алгоритм:
1. Выполнить `nginx -t` для проверки синтаксиса.
2. Выполнить `nginx -s reload` для подхвата новых сертификатов.
3. Возвращать `0` при успехе. При ошибке reload Certbot повторит попытку при следующем запуске таймера.

## 3. Практические сценарии

### Сценарий 1: Docker Compose

Использование переменных окружения позволяет легко переиспользовать конфиг для разных доменов.

**Пример `docker-compose.yaml`:**

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
    command: "/bin/sh -c 'while :; do sleep 6h & wait $${!}; nginx -s reload; done & nginx -g \"daemon off;\"'"

  certbot:
    image: certbot/certbot
    container_name: certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
```

> **Примечание:** Цикл `sleep 6h && nginx -s reload` в контейнере Nginx обеспечивает подхват обновленных сертификатов без остановки сервиса. Certbot обновляет файлы на shared volume; Nginx перечитывает их через reload. `trap exit TERM` гарантирует корректное завершение контейнера при остановке.

**Конфигурация Nginx (`./nginx/conf.d/default.conf`):**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com;

    http2 on;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        root   /usr/share/nginx/html;
        index  index.html;
    }
}
```

#### Решение проблемы «курицы и яйца» (Первый запуск)

Nginx не запустится, если файлы сертификатов, указанные в конфиге, отсутствуют.

1. **Холодный старт**: Временно закомментируйте блок `443` и директивы `ssl_*` в `default.conf`.
2. **Запуск HTTP**: Выполните `docker compose up -d nginx`.
3. **Запрос тестового сертификата (Staging)**:
   Используйте `--staging` для проверки связи, чтобы не исчерпать лимиты Let's Encrypt.
   ```bash
   docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
     --staging --email admin@example.com -d example.com --agree-tos
   ```
4. **Получение боевого сертификата**:
   Если staging прошел успешно, удалите папку `./certbot/conf/live/example.com` и выполните команду без `--staging`.
   ```bash
   docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
     --email admin@example.com -d example.com --agree-tos
   ```
5. **Активация HTTPS**: Раскомментируйте блок `443` и перезапустите Nginx: `docker compose restart nginx`.

### Сценарий 2: Bare metal / systemd

Подходит для физических серверов и виртуальных машин. Certbot устанавливается через пакетный менеджер, обновление — через systemd-таймер.

**Предварительные требования:**
- Nginx установлен и запущен (`systemctl status nginx`).
- Порты 80 и 443 открыты.
- Домен указывает на IP сервера (A-запись).

**Установка Certbot:**

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install certbot python3-certbot-nginx

# CentOS / RHEL
sudo dnf install epel-release
sudo dnf install certbot python3-certbot-nginx
```

> **Примечание:** Snap-установка является официальной рекомендацией EFF для гарантии актуальности версии. Актуальные инструкции: **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**.

**Получение сертификата с автоматической настройкой Nginx:**

```bash
sudo certbot --nginx -d example.com -d www.example.com
```

Certbot автоматически:
- Создаст сертификаты в `/etc/letsencrypt/live/example.com/`.
- Обновит конфигурацию Nginx (добавит `ssl_certificate`, `ssl_certificate_key`, редирект HTTP → HTTPS).
- Включит таймер автоматического обновления.

**Проверка таймера:**

```bash
sudo systemctl list-timers | grep certbot
# → certbot.timer    ...    /usr/bin/certbot renew
```

**Ручная настройка (webroot) + renewal hook:**

Если `--nginx` плагин недоступен или требуется полный контроль над конфигурацией:

```bash
# 1. Получение сертификата
sudo certbot certonly --webroot -w /var/www/html \
  -d example.com -d www.example.com

# 2. Создание renewal hook
sudo tee /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh <<'EOF'
#!/bin/sh
nginx -t && systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh

# 3. Тестовый запуск hook
sudo /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

**Конфигурация Nginx (bare metal):**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com www.example.com;

    http2 on;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        root /usr/share/nginx/html;
        index index.html;
    }
}
```

### Сценарий 3: Многодоменный сертификат (SAN)

Один сертификат для нескольких доменов (Subject Alternative Name). Уменьшает количество файлов и операций обновления.

**Получение:**

```bash
sudo certbot certonly --webroot -w /var/www/html \
  -d example.com -d www.example.com -d api.example.com
```

**Nginx конфигурация:**

```nginx
server {
    listen 443 ssl;
    server_name example.com www.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # ... остальные параметры TLS
}

server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # ... остальные параметры TLS
}
```

> **Важно:** Все домены в SAN должны указывать на один и тот же `webroot` (или использоваться DNS-01). При добавлении нового домена требуется перевыпуск сертификата.

### Сценарий 4: Wildcard-сертификат (DNS-01)

Защищает основной домен и все поддомены первого уровня (`*.example.com`). Требует проверки через DNS-01.

**Получение (пример с Cloudflare):**

```bash
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d example.com -d '*.example.com'
```

Файл `/etc/letsencrypt/cloudflare.ini`:
```ini
dns_cloudflare_api_token = <ВАШ_API_ТОКЕН>
```

**Nginx конфигурация:**

```nginx
server {
    listen 443 ssl;
    server_name example.com '*.example.com';

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # ... остальные параметры TLS
}
```

> **Примечание:** Для wildcard-сертификатов нельзя использовать метод webroot (HTTP-01). Обязательно требуется DNS-01 с плагином `certbot-dns-<provider>`. Список поддерживаемых плагинов: `certbot-dns-*`.

## 4. Операции и команды

### Валидация и проверка

| Команда | Назначение |
| :--- | :--- |
| `nginx -t` | Проверка синтаксиса конфигурации Nginx перед reload. |
| `sudo certbot certificates` | Список всех выданных сертификатов и сроков действия. |
| `sudo certbot renew --dry-run` | Тестовое обновление без фактической выдачи. |
| `sudo systemctl list-timers \| grep certbot` | Проверка статуса systemd-таймера (bare metal). |
| `openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -dates` | Проверка сроков действия конкретного сертификата. |
| `openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -text` | Детальная информация о сертификате (алгоритм, издатель, SAN). |
| `openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null \| openssl x509 -noout -subject -issuer -dates` | Проверка цепочки и сроков по живому соединению. |

### Управление

| Команда | Назначение |
| :--- | :--- |
| `sudo certbot renew` | Принудительная проверка и обновление всех сертификатов. |
| `sudo systemctl reload nginx` | Graceful reload Nginx для подхвата новых сертификатов (bare metal). |
| `docker compose exec nginx nginx -s reload` | Reload внутри контейнера (Docker). |
| `sudo certbot revoke --cert-path /etc/letsencrypt/live/example.com/fullchain.pem` | Отзыв скомпрометированного сертификата. |

### Диагностика

| Команда | Назначение |
| :--- | :--- |
| `docker compose logs -f certbot` | Логи процесса продления (Docker). |
| `docker compose logs -f nginx` | Ошибки доступа Nginx к файлам (Docker). |
| `journalctl -u certbot.timer -f` | Логи systemd-таймера (bare metal). |
| `sudo cat /var/log/letsencrypt/letsencrypt.log` | Подробный лог Certbot. |
| `nginx -T` | Полный дамп конфигурации Nginx (для проверки путей к сертификатам). |

## 5. Устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `nginx: [emerg] unknown directive "http2"` | Устаревшая версия Nginx (< 1.25.1) | Обновите Nginx или замените на `listen 443 ssl http2;` (deprecated, но работает в старых версиях). |
| `Permission denied` при чтении сертификатов | Неправильные права на `/etc/letsencrypt/` | Убедитесь, что пользователь Nginx (обычно `www-data` или `nginx`) имеет права на чтение. На bare metal Certbot создаёт файлы от `root`; проверьте `chmod` на директорию. |
| Сертификат не обновляется | Таймер не активен | `sudo systemctl enable --now certbot.timer`; проверьте `systemctl list-timers \| grep certbot`. |
| `400 Bad Request` при HTTP-01 challenge | Неправильный `location` или порт 80 закрыт | Проверьте конфигурацию `location /.well-known/acme-challenge/`, убедитесь что порт 80 доступен из интернета. |
| Цепочка сертификатов невалидна | В `fullchain.pem` отсутствует промежуточный CA | Перевыпустите сертификат; убедитесь что Certbot версии 2.x+ (новые цепочки R10-R14 / E5-E9). |
| Nginx не подхватывает обновленный сертификат | Отсутствует reload после обновления | Проверьте renewal hook, убедитесь что `nginx -t && nginx -s reload` выполняется после `certbot renew`. |
| `Too Many Requests` | Превышен rate limit Let's Encrypt | Используйте `--staging` для тестов; дождитесь сброса лимита (обычно 1 неделя). |
| Wildcard не выдается | Используется HTTP-01 вместо DNS-01 | Переключитесь на DNS-01 с плагином `certbot-dns-<provider>`. |

## 6. Лучшие практики

- **Используйте ECDSA по умолчанию.** Certbot 2.x+ выдает ECDSA (P-256) сертификаты. Они меньше, быстрее и обеспечивают ту же безопасность, что и RSA 2048. Для совместимости со старыми клиентами можно использовать dual stack (ECDSA + RSA).
- **Тестируйте в staging перед боевым запуском.** Используйте `--staging` или `certbot renew --dry-run`, чтобы проверить конфигурацию без риска исчерпания rate limits.
- **Всегда проверяйте `nginx -t` перед reload.** Ошибка в синтаксисе не сломает работающий Nginx, но reload с ошибкой приведёт к падению новых соединений.
- **Настраивайте renewal hook для bare metal.** В Docker цикл reload встроен в команду контейнера. На bare metal используйте `/etc/letsencrypt/renewal-hooks/deploy/` для автоматического reload.
- **Мониторинг сроков действия.** Добавьте алерт в мониторинг (Prometheus, Zabbix, Nagios) при остатке < 14 дней. Для экспорта метрик используйте `certbot certificates` + node_exporter textfile collector.
- **Включайте OCSP Stapling.** Добавьте в конфигурацию Nginx:
  ```nginx
  ssl_stapling on;
  ssl_stapling_verify on;
  resolver 8.8.8.8 1.1.1.1 valid=300s;
  resolver_timeout 5s;
  ```
  Это ускоряет TLS-рукопожатие, позволяя Nginx подписывать ответ OCSP от CA.
- **Настраивайте HSTS с `includeSubDomains` и `preload`.** Для публичных сервисов отправляйте:
  ```nginx
  add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
  ```
  После этого отправьте домен в **[HSTS preload list](https://hstspreload.org/)**.
- **Ограничьте права на `/etc/letsencrypt/`.** Приватные ключи должны быть доступны только для чтения пользователю `root` (или группе `ssl-cert`). Никогда не выкладывайте директорию в публичные репозитории.
- **Используйте DNS-01 для wildcard.** HTTP-01 не поддерживает wildcard. Настройте API DNS-провайдера в плагине Certbot.
- **Документируйте процедуры.** Для каждой среды (dev, staging, prod) должен быть регламент: кто отвечает за SSL, как получать сертификаты, как действовать при проблемах с обновлением.
- **Верифицируйте цепочку после обновления.** После перевыпуска проверьте:
  ```bash
  openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | openssl x509 -noout -text
  ```

## 7. См. также

- **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)** — теоретические основы ACME, лимиты, ECDSA vs RSA, установка Certbot.
- **[Модуль ACME в Angie](../../Angie/angie_acme_module.md)** — встроенный ACME-модуль в форке Nginx, позволяющий получать сертификаты без внешних утилит.
- **[Traefik с Docker Compose](../../Traefik/traefik_with_docker_compose.md)** — Edge Router с нативной поддержкой Let's Encrypt и автоматическим управлением сертификатами.
