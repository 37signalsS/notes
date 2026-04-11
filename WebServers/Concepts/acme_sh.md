# acme.sh — ACME-клиент для TLS-сертификатов

## Definitions

**acme.sh** — легковесный ACME-клиент, написанный на shell (bash). Предназначен для автоматического получения и обновления SSL/TLS сертификатов от центров сертификации, поддерживающих протокол ACME (Let's Encrypt, ZeroSSL, и др.).

**Ключевые особенности:**

- Написан на bash (зависимости: curl, openssl)
- Поддерживает 100+ DNS API провайдеров
- Автоматическая поддержка wildcard-сертификатов
- Встроенная поддержка ECDSA и RSA ключей
- Автоматическое обновление через cron

**Преимущества перед Certbot:**

- Меньше зависимостей (не требует Python)
- Шире поддержка DNS API провайдеров
- Гибкая настройка hook-скриптов
- Параллельная поддержка нескольких типов ключей

## Basic Concepts

### Методы авторизации

**HTTP-01** — проверка через HTTP.

- Требует доступный 80 порт
- Не поддерживает wildcard
- Автоматическая обработка через веб-сервер

**DNS-01** — проверка через DNS TXT-запись.

- Поддерживает wildcard (`*.example.com`)
- Не требует доступности сервера
- Требует API ключ DNS-провайдера

### Типы ключей

**ECDSA:**

```bash
acme.sh --issue -d example.com --keylength ec-256
```

**RSA:**

```bash
acme.sh --issue -d example.com --keylength 2048
```

**Параллельное использование:** acme.sh позволяет получить два сертификата (ECDSA + RSA) для одного домена. Сертификаты хранятся в отдельных директориях и могут быть установлены в веб-сервер одновременно.

### Структура хранения

```
~/.acme.sh/
├── example.com/
│   ├── example.com.cer      # Сертификат
│   ├── example.com.key      # Приватный ключ
│   ├── ca.cer               # Промежуточный CA
│   └── fullchain.cer        # Полная цепочка
├── account.conf             # Конфигурация аккаунта
└── acme.sh.env              # Переменные окружения
```

> **Важно:** Файлы в `~/.acme.sh/` предназначены для внутреннего использования. Для установки в веб-сервер используйте команду `--install-cert`.

## Practical Scenarios

### Сценарий 1: Установка acme.sh

**От обычного пользователя:**

```bash
curl https://get.acme.sh | sh
source ~/.bashrc
~/.acme.sh/acme.sh --version
```

**От root (для системных задач — cron, DNS API):**

```bash
sudo -i
curl https://get.acme.sh | sh
source ~/.bashrc
```

### Сценарий 2: Получение сертификата (HTTP-01)

```bash
# Предварительная проверка (dry-run)
acme.sh --issue -d example.com -w /var/www/html --test

# Получение сертификата
acme.sh --issue -d example.com -w /var/www/html

# Несколько доменов
acme.sh --issue -d example.com -d www.example.com -w /var/www/html
```

**Настройка веб-сервера:**

```nginx
server {
    listen 80;
    server_name example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        # Основная конфигурация
    }
}
```

### Сценарий 3: Wildcard-сертификат через DNS API

**Подготовка API ключа (Cloudflare):**

```bash
export CF_Key="your_cloudflare_api_key"
export CF_Email="your_cloudflare_email"
```

**Получение wildcard-сертификата:**

```bash
# ECDSA
acme.sh --issue --dns dns_cf \
    -d example.com \
    -d "*.example.com" \
    --keylength ec-256

# RSA (отдельно)
acme.sh --issue --dns dns_cf \
    -d example.com \
    -d "*.example.com" \
    --keylength 2048
```

**Поддерживаемые DNS провайдеры:** Cloudflare (`dns_cf`), AWS Route53 (`dns_aws`), DigitalOcean (`dns_do`), GoDaddy (`dns_gd`), Яндекс.Облако (`dns_yandex`) и 90+ других. Полный список: [acme.sh DNS API wiki](https://github.com/acmesh-official/acme.sh/wiki/dnsapi).

### Сценарий 4: Установка сертификата в Nginx

**Одиночный сертификат:**

```bash
acme.sh --install-cert -d example.com \
    --key-file       /etc/nginx/ssl/example.com.key  \
    --fullchain-file /etc/nginx/ssl/example.com.crt \
    --reloadcmd     "systemctl reload nginx"
```

**Два сертификата (ECDSA + RSA):**

```bash
# ECDSA
acme.sh --install-cert -d example.com \
    --key-file       /etc/nginx/ssl/example.com.ecdsa.key  \
    --fullchain-file /etc/nginx/ssl/example.com.ecdsa.crt \
    --reloadcmd     "systemctl reload nginx"

# RSA
acme.sh --install-cert -d example.com \
    --key-file       /etc/nginx/ssl/example.com.rsa.key  \
    --fullchain-file /etc/nginx/ssl/example.com.rsa.crt \
    --reloadcmd     "systemctl reload nginx"
```

**Конфигурация Nginx:**

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # ECDSA (приоритет)
    ssl_certificate /etc/nginx/ssl/example.com.ecdsa.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.ecdsa.key;

    # RSA (резерв)
    ssl_certificate /etc/nginx/ssl/example.com.rsa.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.rsa.key;
}
```

> **Примечание:** Nginx автоматически выберет подходящий сертификат в зависимости от клиента.

### Сценарий 5: Автоматическое обновление

**Cron:** acme.sh автоматически добавляет задачу в cron при установке:

```bash
crontab -l
# 0 0 * * * "/root/.acme.sh"/acme.sh --cron --home "/root/.acme.sh" > /dev/null
```

**Ручное обновление:**

```bash
acme.sh --renew -d example.com               # Обновление
acme.sh --renew -d example.com --force       # Принудительное
```

**Мониторинг:**

```bash
acme.sh --list                                # Список сертификатов
openssl x509 -in ~/.acme.sh/example.com/fullchain.cer -text -noout  # Детали
```

### Сценарий 6: Диагностика ошибок

```bash
acme.sh --issue -d example.com --dns dns_cf --debug
```

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| DNS error | DNS-запись не обновилась | Подождать 1-5 минут, проверить TTL |
| Rate limit | Превышен лимит Let's Encrypt | Устранить причину, ждать |
| API error | Неверный API ключ | Проверить переменные окружения |
| 404 Not Found | Неправильный webroot | Проверить путь, конфиг nginx |

> **Важно:** При ошибке не повторяйте команду сразу — это приведёт к rate limit.

## Additional Information

**Сравнение с Certbot:** acme.sh требует только bash/curl/openssl (против Python у Certbot), поддерживает 100+ DNS API (против ~50), занимает ~200 KB (против ~10 MB). Подробности о Certbot: [Настройка HTTPS с Certbot](./https_with_certbot.md).

**Альтернативы:** Встроенный ACME-модуль в [Angie](../Angie/angie_acme_module.md) не требует внешних клиентов.

**Дополнительно:** [Настройка TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md), [Официальная документация acme.sh](https://github.com/acmesh-official/acme.sh).
