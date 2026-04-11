# Let's Encrypt и Certbot — HTTPS для веб-серверов

## Definitions

**Let's Encrypt** — некоммерческий центр сертификации, предоставляющий бесплатные SSL/TLS сертификаты через протокол ACME (RFC 8555).

**ACME (Automated Certificate Management Environment)** — протокол автоматизированного управления сертификатами: получение, обновление, отзыв TLS-сертификатов без участия человека.

**Certbot** — инструмент для автоматического получения и обновления сертификатов Let's Encrypt. Поддерживает плагины для Nginx, Apache и метод webroot.

**Webroot** — метод авторизации ACME: проверочный файл размещается в `.well-known/acme-challenge/` на веб-сервере.

### Типы ключей: ECDSA vs RSA

**ECDSA** — ключ на основе эллиптических кривых. Быстрее для сервера, меньший размер. Certbot 3.x: ECDSA — тип по умолчанию. Совместимость ниже на устаревших клиентах.

**RSA** — классический тип. Отличная совместимость, быстрее для клиента при рукопожатии, но медленнее для сервера и больший размер ключа.

> **Best Practice:** Параллельное развёртывание ECDSA + RSA — ECDSA для современных клиентов, RSA для обратной совместимости.

### Рейтлимиты Let's Encrypt

| Лимит | Значение |
| :--- | :--- |
| Duplicate Certificate Limit | 50 сертификатов на домен в неделю |
| Registration Rate Limit | 5 регистраций аккаунта на IP в час |
| Verification Rate Limit | 30 проверок авторизации на домен в час |

> **Важно:** Перед получением боевого сертификата используйте **staging** или **dry-run**. При ошибке не повторяйте команду без устранения причины — это приведёт к блокировке.

## Basic Concepts

### Методы авторизации

**HTTP-01** — проверочный файл в `.well-known/acme-challenge/`.

- Требует открытый 80 порт
- Не поддерживает wildcard
- Для обычных доменных сертификатов

**DNS-01** — TXT-запись `_acme-challenge.example.com` в DNS.

- Поддерживает wildcard (`*.example.com`)
- Не требует доступности сервера
- Требует API DNS-провайдера

### Webroot-авторизация

Необходимо настроить веб-сервер для обработки запросов к `.well-known`:

```nginx
server {
    listen 80;
    server_name example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        # Основная конфигурация сайта
    }
}
```

Certbot создаёт проверочный файл, CA проверяет доступность по HTTP.

### Диагностика ошибок

- **DNS ошибка:** Дождаться обновления DNS (несколько минут)
- **404 Not Found:** Проверить конфигурацию location для `.well-known`, убедиться что конфиг перезапущен
- **Rate limit exceeded:** Прекратить попытки, устранить причину, дождаться сброса лимита

**Тестирование перед боевым запуском:**

```bash
certbot --staging --nginx -d example.com    # staging
certbot renew --dry-run                      # dry-run обновления
certbot --nginx -d example.com               # боевой запуск
```

## Practical Scenarios

### Установка Certbot

**Debian/Ubuntu:**

```bash
apt install -y certbot python3-certbot-nginx
```

**CentOS/RHEL:**

```bash
dnf install -y epel-release
dnf install -y certbot-nginx
```

### Предварительная настройка Nginx

Certbot ищет `server_name` в конфигурации Nginx для автоматической настройки SSL. Подробности: [Установка и базовая настройка Nginx](../Nginx/Core/nginx_setup.md).

```nginx
server_name example.com www.example.com;
```

После проверки синтаксиса (`nginx -t`):

```bash
systemctl reload nginx
```

### Получение SSL-сертификата

**Базовый сценарий:**

```bash
certbot --nginx -d example.com -d www.example.com
```

Certbot запросит email, согласование условий и предложит редирект HTTP → HTTPS (рекомендуется `Redirect`). Сертификаты сохраняются в `/etc/letsencrypt/live/example.com/`, конфигурация Nginx обновляется автоматически.

**Продвинутый сценарий (ECDSA + RSA):**

```bash
# ECDSA (по умолчанию в Certbot 3.x)
certbot certonly --webroot -w /var/www/certbot \
    --key-type ecdsa \
    -d example.com -d www.example.com

# RSA
certbot certonly --webroot -w /var/www/certbot \
    --key-type rsa --rsa-key-size 2048 \
    -d example.com -d www.example.com
```

**Nginx для двух сертификатов:**

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain-ecdsa.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey-ecdsa.pem;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain-rsa.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey-rsa.pem;
}
```

> **Примечание:** Certbot создаёт файлы с суффиксами `-ecdsa`/`-rsa`. Символические ссылки в `live/` указывают на актуальные версии.

### Автоматическое обновление

Сертификаты Let's Encrypt действительны 45 дней.

**Debian/Ubuntu:** таймер `systemd` (`certbot.timer`) — дважды в день, обновление при остатке < 30 дней:

```bash
systemctl status certbot.timer
```

**CentOS:** задача в `cron`:

```bash
crontab -e
# 10 4 * * * /usr/bin/certbot renew --quiet
```

## Additional Information

**Wildcard-сертификаты:** `*.example.com` защищает основной домен и все поддомены первого уровня. Certbot поддерживает wildcard только через DNS-01, что требует API DNS-провайдера. Для wildcard рекомендуется **[acme.sh](./acme_sh.md)** с поддержкой 100+ DNS API.

**Альтернативы:** Встроенный ACME-модуль в [Angie](../Angie/angie_acme_module.md), обратный прокси [Traefik](../Traefik/traefik_overview.md) с автоматическим Let's Encrypt.

**Диагностика:**

```bash
certbot renew --dry-run             # Проверка обновления
systemctl status certbot.timer      # Статус автообновления
certbot certificates                  # Список сертификатов
openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -text -noout  # Детали
```

> **Важно:** Certbot отвечает за *получение* сертификатов. За *оптимальное использование* отвечает Nginx — убедитесь, что TLS/SSL-конфигурация соответствует лучшим практикам: [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md).
