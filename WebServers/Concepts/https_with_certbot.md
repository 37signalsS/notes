---
reliability: 10
updated: 2026-07-31
---

# Let's Encrypt и Certbot — HTTPS для веб-серверов

## Определения

**Let's Encrypt** — некоммерческий центр сертификации (CA, Certificate Authority), предоставляющий бесплатные SSL (Secure Sockets Layer) / TLS (Transport Layer Security) сертификаты через протокол ACME (RFC, Request for Comments 8555).

**ACME (Automated Certificate Management Environment)** — протокол автоматизированного управления сертификатами: получение, обновление, отзыв TLS-сертификатов без участия человека.

**Certbot** — официальный инструмент EFF (Electronic Frontier Foundation) для автоматического получения и обновления сертификатов Let's Encrypt. Поддерживает плагины для Nginx, Apache и метод webroot.

**Webroot** — метод авторизации ACME: проверочный файл размещается в `.well-known/acme-challenge/` на веб-сервере.

### Типы ключей: ECDSA и RSA

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — ключ на основе эллиптических кривых. Быстрее для сервера, меньший размер. Certbot 2.x+: ECDSA (P-256) — тип по умолчанию. Обеспечивает высокий уровень безопасности при меньшей нагрузке на CPU.

**RSA (Rivest–Shamir–Adleman)** — классический тип ключа. Отличная совместимость с очень старыми клиентами, но требует больших ресурсов для шифрования (рекомендуется размер 2048 или 4096 бит).

> **Лучшие практики (2024–2026):** Рекомендуется использовать ECDSA. Let's Encrypt перешел на новые цепочки доверия (R10-R14 для RSA и E5-E9 для ECDSA), которые короче и быстрее. Поддержка ARI (Automated Renewal Information) позволяет Certbot автоматически обновлять сертификаты, если CA рекомендует это сделать раньше срока.

### Лимиты запросов Let's Encrypt (Rate Limits)

| Лимит | Значение |
| :--- | :--- |
| Повторные сертификаты (Duplicate Certificate Limit) | 50 сертификатов на домен в неделю |
| Регистрация аккаунтов (Registration Rate Limit) | 5 регистраций на IP (Internet Protocol) в час |
| Проверки авторизации (Verification Rate Limit) | 30 проверок на домен в час |

> **Важно:** Перед получением боевого сертификата используйте **staging** или **dry-run** (тестовое окружение). При ошибке не повторяйте команду без устранения причины — это приведёт к блокировке.

## Основные концепции

### Методы авторизации

**HTTP-01** — проверка владения доменом через размещение файла по протоколу HTTP (HyperText Transfer Protocol) в директории `.well-known/acme-challenge/`.

- Требует открытый 80 порт
- Не поддерживает wildcard (групповые сертификаты)
- Для обычных доменных сертификатов

**DNS-01** — проверка через TXT-запись `_acme-challenge.example.com` в DNS (Domain Name System).

- Поддерживает wildcard (`*.example.com`)
- Не требует доступности сервера
- Требует API DNS-провайдера

### Авторизация через Webroot

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

## Практические сценарии

### Установка Certbot (Рекомендуемый способ — Snap)

Использование **snapd** является официальной рекомендацией EFF, так как позволяет всегда иметь актуальную версию клиента и плагинов.

**Установка (Ubuntu/Debian/CentOS):**

```bash
# 1. Удаление старых версий (если были установлены через apt/dnf)
sudo apt-get remove certbot

# 2. Установка через snap
sudo snap install --classic certbot

# 3. Подготовка команды certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot

# 4. Установка плагина для Nginx (если требуется автоматическая настройка)
sudo snap set certbot trust-plugin-with-root=ok
sudo snap install certbot-dns-cloudflare # Пример плагина для DNS
```

### Альтернативная установка (Legacy)

**Debian/Ubuntu (apt):**
```bash
sudo apt update
sudo apt install certbot python3-certbot-nginx
```

**CentOS/RHEL (dnf):**
```bash
sudo dnf install epel-release
sudo dnf install certbot python3-certbot-nginx
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
# ECDSA (по умолчанию в Certbot 2.x+)
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

    # ECDSA (Основной)
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA (Для старых клиентов, если выпущен отдельно)
    # ssl_certificate /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;
}
```

> **Примечание:** При установке через Snap Certbot автоматически настраивает пути и ссылки. ECDSA является стандартом для всех современных браузеров.

### Автоматическое обновление

Сертификаты Let's Encrypt действительны 90 дней, обновление рекомендуется при остатке 30 дней.

**При установке через Snap:** таймер настраивается автоматически. Проверка:
```bash
sudo systemctl list-timers | grep certbot
```

**Классический метод (Legacy):**
- **Debian/Ubuntu:** таймер `systemd` (`certbot.timer`).
- **CentOS:** задача в `cron`.

```bash
# Проверка процесса продления вручную
sudo certbot renew --dry-run
```

## Дополнительная информация

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
