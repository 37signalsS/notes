# acme.sh — ACME-клиент для TLS-сертификатов

## Определения

**acme.sh** — легковесный ACME-клиент, написанный на bash. Предназначен для автоматического получения, обновления и отзыва SSL/TLS-сертификатов от центров сертификации (CA, Certificate Authority), поддерживающих протокол ACME (Let's Encrypt, ZeroSSL, Buypass, SSL.com и др.).

**ACME (Automated Certificate Management Environment)** — протокол автоматизированного управления сертификатами. Базовые принципы ACME, методы авторизации и rate limits Let's Encrypt описаны в [Let's Encrypt и Certbot — HTTPS для веб-серверов](./https_with_certbot.md).

**ZeroSSL** — центр сертификации, используемый по умолчанию в acme.sh начиная с версии 3.0. В отличие от Let's Encrypt, требует обязательной регистрации аккаунта через email, но предоставляет неограниченное количество 90-дневных сертификатов через ACME без жестких лимитов на домен.

**Let's Encrypt** — некоммерческий CA, предоставляющий бесплатные TLS-сертификаты через ACME. Используется в acme.sh после явного переключения.

**Wildcard-сертификат** — сертификат, покрывающий основной домен и все поддомены первого уровня через `*.example.com`. Получается только через метод авторизации DNS-01.

**Webroot** — метод авторизации ACME, при котором проверочный файл размещается в `.well-known/acme-challenge/` на веб-сервере.

**Stateless mode** — режим работы acme.sh без сохранения состояния на диске. Проверочный ответ генерируется динамически на основе отпечатка открытого ключа аккаунта (thumbprint). Используется в контейнеризированных средах и CI/CD пайплайнах.

**DNS persist (dns-persist-01)** — метод авторизации, при котором одна TXT-запись публикуется в DNS и используется для всех последующих обновлений без обращения к API DNS-провайдера. Реализует draft-ietf-acme-dns-persist-01.

**ARI (Automated Renewal Information, RFC 9773)** — механизм, при котором CA рекомендует обновить сертификат раньше срока действия (например, при массовом отзыве). В acme.sh 3.1.4+ включен по умолчанию.

**Deploy hook** — скрипт или команда, выполняемая после успешного получения или обновления сертификата. Используется для установки сертификата в веб-сервер, перезагрузки сервиса или деплоя в инфраструктуру.

**Notify hook** — скрипт или встроенный коннектор для отправки уведомлений о статусе обновления сертификатов (Telegram, Slack, mail, customscript).

### Ключевые особенности acme.sh

- Написан на bash (зависимости: bash, curl, openssl). Опционально: socat (standalone/TLS-ALPN режим), oath-toolkit (OTP для некоторых DNS-провайдеров)
- Поддерживает 110+ DNS API провайдеров
- Автоматическая поддержка wildcard-сертификатов через DNS-01
- Встроенная поддержка ECDSA (P-256, P-384) и RSA (2048, 4096) ключей
- Параллельная поддержка нескольких типов ключей для одного домена (ECDSA + RSA)
- Стандартный cron обновляет сертификаты каждые 6 часов (с версии 3.1.4) для своевременной реакции на ARI
- Поддержка bash-completion (устанавливается через `acme.sh --install`)
- Официальные Docker-образы публикуются в Docker Hub и ghcr.io
- Не требует root-прав для установки (хотя для системных hook-скриптов и cron рекомендуется запуск от root)

### Сравнение с Certbot

| Критерий | acme.sh | Certbot |
| :--- | :--- | :--- |
| Язык реализации | bash | Python |
| Зависимости | curl, openssl, bash | python3, certbot, плагины |
| Размер | ~200 KB | ~10 MB |
| DNS API провайдеры | 110+ | ~50 |
| Поддержка wildcard | Да (DNS-01) | Да (DNS-01) |
| Хранилище | `~/.acme.sh/` | `/etc/letsencrypt/` |
| CA по умолчанию | ZeroSSL (v3.0+) | Let's Encrypt |

## Основные концепции

### Методы авторизации

**HTTP-01** — проверка владения доменом через размещение файла по протоколу HTTP в директории `.well-known/acme-challenge/` на веб-сервере.

- Требует открытый 80 порт (или 8080 в standalone-режиме)
- Не поддерживает wildcard-сертификаты
- Подходит для обычных доменных имен
- Для работы веб-сервер должен обслуживать проверочный файл до завершения валидации

**DNS-01** — проверка через TXT-запись `_acme-challenge.example.com` в DNS.

- Поддерживает wildcard (`*.example.com`)
- Не требует доступности веб-сервера во время валидации
- Требует API ключ DNS-провайдера или ручное редактирование зоны
- Подходит для серверов за файрволом, в DMZ или при отсутствии открытого 80 порта

**DNS persist (dns-persist-01)** — модификация DNS-01, при которой одна TXT-запись публикуется один раз и используется для всех последующих обновлений без обращения к API DNS-провайдера.

- Указывается параметром `--dns-persist-days N`
- Подходит для инфраструктур, где DNS API недоступен или нежелателен
- Требует поддержки на стороне DNS-провайдера или ручного создания записи

**TLS-ALPN-01** — проверка через TLS-соединение на 443 порту с расширением ALPN `acme-tls/1`.

- Требует открытый 443 порт
- Подходит для CDN и reverse-proxy, где 80 порт закрыт
- Не поддерживает wildcard
- Используется в standalone-режиме с socat

### Stateless-режим

Режим, в котором acme.sh не сохраняет файлы сертификатов и состояние на локальный диск. Проверочный ответ генерируется динамически из отпечатка открытого ключа аккаунта.

```nginx
# Пример для Nginx (замените ACCOUNT_THUMBPRINT на реальное значение)
location ~ ^/.well-known/acme-challenge/([-_a-zA-Z0-9]+)$ {
    default_type text/plain;
    return 200 "$1.ACCOUNT_THUMBPRINT";
}
```

```haproxy
# Пример для HAProxy
global
    setenv ACCOUNT_THUMBPRINT '6fXAG9VyG0IahirPEU2ZerUtItW2DHzDzD9wZaEKpqd'

frontend web
    http-request return status 200 content-type text/plain lf-string \
        "%[path,field(-1,/)].${ACCOUNT_THUMBPRINT}\n" \
        if { path_reg '^/.well-known/acme-challenge/[-_a-zA-Z0-9]+$' }
```

Использование:
```bash
acme.sh --issue -d example.com --stateless
```

Подходит для:
- Контейнеризированных сред (Docker, Kubernetes)
- CI/CD пайплайнов, где сохраняемое состояние нежелательно
- Immutable-инфраструктуры

### Типы ключей

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — ключ на основе эллиптических кривых. В acme.sh поддерживаются кривые P-256 (`ec-256`) и P-384 (`ec-384`).

- Меньший размер ключа и сертификата
- Быстрее операция подписи на стороне сервера
- Меньшая нагрузка на CPU
- Рекомендуется для большинства современных сценариев

```bash
acme.sh --issue -d example.com --keylength ec-256
```

**RSA (Rivest–Shamir–Adleman)** — классический тип ключа. Рекомендуемые размеры: 2048 бит (минимальный), 4096 бит (высокая безопасность).

- Лучшая совместимость с очень старыми клиентами и корпоративными браузерами
- Больший размер ключа и сертификата
- Больше ресурсов CPU для операций подписи

```bash
acme.sh --issue -d example.com --keylength 2048
```

**Параллельное использование:** acme.sh позволяет получить два сертификата (ECDSA + RSA) для одного домена. Сертификаты хранятся в отдельных директориях и могут быть установлены в веб-сервер одновременно. Nginx/Angie автоматически выберут подходящий сертификат в зависимости от возможностей клиента.

### Структура хранения

```
~/.acme.sh/
├── example.com_ecc/
│   ├── example.com.cer      # Сертификат ECDSA
│   ├── example.com.key      # Приватный ключ ECDSA
│   ├── ca.cer               # Промежуточный CA
│   └── fullchain.cer        # Полная цепочка ECDSA
├── example.com/
│   ├── example.com.cer      # Сертификат RSA
│   ├── example.com.key      # Приватный ключ RSA
│   ├── ca.cer               # Промежуточный CA
│   └── fullchain.cer        # Полная цепочка RSA
├── account.conf             # Конфигурация ACME-аккаунта
└── acme.sh.env              # Переменные окружения
```

> **Важно:** Файлы в `~/.acme.sh/` предназначены для внутреннего использования acme.sh. Для установки в веб-сервер используйте команду `--install-cert` или `--deploy`. Не редактируйте файлы сертификатов вручную.

### Выбор CA и цепочки доверия

acme.sh 3.0+ использует ZeroSSL как CA по умолчанию. При необходимости переключения:

```bash
# Переключиться на Let's Encrypt
acme.sh --set-default-ca --server letsencrypt

# Переключиться на Buypass
acme.sh --set-default-ca --server buypass

# Вернуться к ZeroSSL
acme.sh --set-default-ca --server zerossl
```

Выбор предпочитаемой цепочки (если CA предлагает несколько вариантов):

```bash
acme.sh --set-default-chain --chain "ISRG Root X1"
```

### Жизненный цикл сертификата

1. **Получение:** `acme.sh --issue` запрашивает сертификат у CA через ACME-протокол.
2. **Валидация:** CA проверявает контроль над доменом через HTTP-01, DNS-01 или другой метод.
3. **Установка:** `acme.sh --install-cert` копирует сертификат и ключ в целевую директорию, запускает reloadcmd.
4. **Автообновление:** cron (каждые 6 часов) проверяет срок действия. ARI позволяет CA рекомендовать досрочное обновление.
5. **Отзыв:** `acme.sh --revoke` отзывает сертификат (если ключ скомпрометирован или сертификат больше не нужен).

## Практические сценарии

### Сценарий 1: Установка acme.sh и регистрация аккаунта

**Требования:**
- bash, curl, openssl
- Открытый 80 порт (для HTTP-01) или доступ к DNS API (для DNS-01)
- Для standalone/TLS-ALPN режима: socat

**От обычного пользователя (установка в `~/.acme.sh/`):**

```bash
curl https://get.acme.sh | sh
source ~/.bashrc
acme.sh --version
# → acme.sh v3.1.4
```

**От root (для системных задач — cron, hook-скрипты, DNS API):**

```bash
sudo -i
curl https://get.acme.sh | sh
source ~/.bashrc
acme.sh --version
```

**Регистрация аккаунта (обязательна для ZeroSSL и Let's Encrypt):**

```bash
acme.sh --register-account -m myemail@example.com
# → Registering account
# → Already registered
# → Register success!
```

Для ZeroSSL требуется email для регистрации аккаунта. Let's Encrypt также рекомендует указать email для уведомлений о проблемах с сертификатом.

**Обновление acme.sh до последней версии:**

```bash
acme.sh --upgrade
# → Downloading new version...
# → Installed: /root/.acme.sh/acme.sh

# Включить автоматическое обновление
acme.sh --upgrade --auto-upgrade
```

### Сценарий 2: Получение сертификата (HTTP-01)

**Предварительная проверка (staging):**

```bash
acme.sh --issue -d example.com -w /var/www/html --test
# → Creating domain key
# → Creating domain csr
# → Single domain='example.com'
# → Standalone mode
# → Please update the following record in your DNS:
# → _acme-challenge.example.com. 300 IN TXT "g23F..."
# → Please be sure to add this TXT record and wait until the DNS takes effect
# → Your cert is already expired, renewing
# → Skip verifying domain
# → Verifying: example.com
# → Success
# → done
```

**Получение боевого сертификата:**

```bash
acme.sh --issue -d example.com -w /var/www/html
```

**Несколько доменов (SAN):**

```bash
acme.sh --issue -d example.com -d www.example.com -d cp.example.com -w /var/www/html
```

Все домены должны указывать на один и тот же webroot.

**Настройка веб-сервера (Nginx):**

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
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

# RSA (отдельно, для совместимости)
acme.sh --issue --dns dns_cf \
    -d example.com \
    -d "*.example.com" \
    --keylength 2048
```

**Поддерживаемые DNS провайдеры:** Cloudflare (`dns_cf`), AWS Route53 (`dns_aws`), DigitalOcean (`dns_do`), GoDaddy (`dns_gd`), Яндекс.Облако (`dns_yandex`), Namecheap, OVH, Gandi, Linode и 100+ других. Полный список: [acme.sh DNS API wiki](https://github.com/acmesh-official/acme.sh/wiki/dnsapi).

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

**Конфигурация Nginx с двумя сертификатами:**

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # ECDSA (приоритет для современных клиентов)
    ssl_certificate /etc/nginx/ssl/example.com.ecdsa.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.ecdsa.key;

    # RSA (резерв для старых клиентов)
    ssl_certificate /etc/nginx/ssl/example.com.rsa.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.rsa.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
}
```

> **Примечание:** Nginx/Angie автоматически выберут подходящий сертификат в зависимости от возможностей клиента. ECDSA используется по умолчанию для TLS 1.2+.

### Сценарий 5: Docker-контейнер (DevOps/SRE)

**Официальный Docker-образ:**

```bash
docker run -it --rm \
    -e CF_Key="your_cloudflare_api_key" \
    -e CF_Email="your_cloudflare_email" \
    -v /root/.acme.sh:/acme.sh \
    acmesh-official/acme.sh \
    --issue --dns dns_cf -d example.com -d "*.example.com"
```

Или с кастомным Dockerfile:

```dockerfile
FROM alpine:3.19

RUN apk add --no-cache \
    openssl \
    curl \
    socat \
    bash \
    coreutils \
    bind-tools \
    tzdata

ENV LE_CONFIG_HOME /acme.sh
ENV AUTO_UPGRADE=1

RUN curl https://get.acme.sh | sh

ENTRYPOINT ["/acme.sh/acme.sh"]
CMD ["--help"]
```

**Использование в docker-compose (Certificates as a Service):**

```yaml
version: "3.8"
services:
  cert-manager:
    image: acmesh-official/acme.sh:latest
    environment:
      - CF_Key=${CF_KEY}
      - CF_Email=${CF_EMAIL}
    volumes:
      - acme-data:/acme.sh
      - ./certs:/etc/nginx/ssl:ro
    entrypoint: >
      sh -c "acme.sh --issue --dns dns_cf -d example.com -d '*.example.com'
             && acme.sh --install-cert -d example.com
               --key-file /etc/nginx/ssl/example.com.key
               --fullchain-file /etc/nginx/ssl/example.com.crt
               --reloadcmd 'nginx -s reload'"

volumes:
  acme-data:
```

### Сценарий 6: Автоматическое обновление и ARI

**Cron:** acme.sh автоматически добавляет задачу в cron при установке:

```bash
crontab -l
# → 0 */6 * * * "/root/.acme.sh"/acme.sh --cron --home "/root/.acme.sh"
```

С версии 3.1.4 cron запускается каждые 6 часов для своевременной реакции на ARI-рекомендации CA.

**Ручное обновление:**

```bash
acme.sh --renew -d example.com               # Обновление
acme.sh --renew -d example.com --force       # Принудительное
```

**Относительное планирование обновления (negative --days):**

```bash
# Обновлять за 7 дней до истечения срока
acme.sh --renew -d example.com --days -7

# Комбинация с --valid-to для графика обновления
acme.sh --issue -d example.com --days -7 --valid-to +90
```

**Мониторинг:**

```bash
acme.sh --list                                # Список всех сертификатов
acme.sh --info -d example.com                 # Просмотр конфигурации домена
openssl x509 -in ~/.acme.sh/example.com/fullchain.cer -text -noout  # Детали сертификата
```

**Проверка ARI:**

```bash
acme.sh --cron --debug 2 | grep "Renewal Info"
# → Renewal Info: recommended renewal window is 2026-06-15 to 2026-06-22
```

> **Важно:** ARI включен по умолчанию. Для отключения установите `NO_ARI=1` в окружении.

### Сценарий 7: Deploy-хуки

Deploy hook — скрипт или команда, выполняемая после успешного получения или обновления сертификата.

```bash
# Пример: деплой в Docker-контейнер
acme.sh --deploy -d example.com \
    --deploy-hook docker \
    --docker-container nginx-prod

# Пример: деплой в FortiGate
acme.sh --install-cert -d example.com \
    --key-file       /etc/nginx/ssl/example.com.key \
    --fullchain-file /etc/nginx/ssl/example.com.crt \
    --deploy-hook    fortigate \
    --fortigate-addr 192.168.1.1 \
    --fortigate-adom root
```

### Сценарий 8: Уведомления

acme.sh поддерживает уведомления о статусе обновления через встроенные hook-и.

**Telegram:**

```bash
export TELEGRAM_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
export TELEGRAM_CHATID="12345678"

acme.sh --set-notify --notify-hook telegram
```

**Почта (через mail/sendmail):**

```bash
acme.sh --set-notify --notify-level 2 --notify-hook mail
# Уровни: 0 — тихо, 1 — только ошибки, 2 — все события
```

**Кастомный скрипт:**

```bash
acme.sh --set-notify --notify-hook customscript --notify-script /usr/local/bin/cert-notify.sh
```

## Операции и команды

### Основные команды

| Команда | Назначение |
| :--- | :--- |
| `acme.sh --issue` | Получение нового сертификата |
| `acme.sh --renew` | Продление сертификата |
| `acme.sh --renew-all` | Продление всех сертификатов |
| `acme.sh --install-cert` | Установка сертификата в веб-сервер (с reloadcmd) |
| `acme.sh --deploy` | Деплой сертификата через deploy hook |
| `acme.sh --revoke` | Отзыв сертификата |
| `acme.sh --remove` | Удаление сертификата из базы acme.sh |
| `acme.sh --list` | Список всех сертификатов |
| `acme.sh --info` | Просмотр конфигурации домена |
| `acme.sh --register-account` | Регистрация ACME-аккаунта |
| `acme.sh --upgrade` | Обновление acme.sh до последней версии |
| `acme.sh --install` | Установка (alias, bash-completion, cron) |
| `acme.sh --uninstall` | Удаление acme.sh и cron-задачи |
| `acme.sh --set-default-ca` | Смена CA по умолчанию |
| `acme.sh --set-notify` | Настройка уведомлений |
| `acme.sh --cron` | Запуск проверки обновлений (используется в cron) |
| `acme.sh --create-domain-key` | Создание приватного ключа |
| `acme.sh --signcsr` | Выпуск сертификата из существующего CSR |

### Ключевые параметры

| Параметр | Назначение |
| :--- | :--- |
| `-d, --domain` | Доменное имя (можно указать несколько) |
| `--keylength` | Тип и размер ключа: `ec-256`, `ec-384`, `2048`, `4096` |
| `-w, --webroot` | Путь к webroot для HTTP-01 |
| `--dns` | DNS API провайдер (например, `dns_cf`) или ручной режим |
| `--dns-persist-days` | Интервал повторной публикации TXT-записи (dns-persist-01) |
| `--stateless` | Статлесс режим без сохранения на диск |
| `--staging, --test` | Использовать staging-сервер CA |
| `--debug [0-3]` | Уровень отладки |
| `--force` | Принудительное действие (обновление, переустановка) |
| `--days N` | Порог обновления (N дней до истечения). Отрицательное значение — относительно срока действия |
| `--reloadcmd` | Команда после установки сертификата (например, `systemctl reload nginx`) |
| `--key-file` | Путь для приватного ключа |
| `--fullchain-file` | Путь для полной цепочки сертификатов |
| `--ca-file` | Путь для промежуточного CA (опционально) |
| `--preferred-chain` | Предпочтительная цепочка CA |
| `--cert-profile` | Профиль сертификата (если CA поддерживает) |
| `--valid-to` | Запросить конкретный срок действия (NotAfter) |
| `--valid-from` | Запросить конкретную дату начала действия (NotBefore) |

### Переключение CA

```bash
acme.sh --set-default-ca --server letsencrypt
acme.sh --set-default-ca --server zerossl
acme.sh --set-default-ca --server buypass
```

### Статлесс-режим

```bash
acme.sh --issue -d example.com --stateless
```

## Диагностика ошибок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `DNS error` | DNS-запись не обновилась | Подождать 1–5 минут (учитывая TTL), проверить запрос `dig TXT _acme-challenge.example.com` |
| `Rate limit` | Превышен лимит CA | Использовать staging-сервер для тестов, дождаться сброса лимита. Duplicate limit: 50 сертификатов/домен/неделю |
| `API error` | Неверный API ключ | Проверить переменные окружения, права на API ключ DNS-провайдера |
| `404 Not Found` | Неправильный webroot | Проверить путь, конфигурацию location у веб-сервера, права доступа |
| `Connection refused` | 80 порт закрыт | Открыть 80 порт или использовать DNS-01 |
| `Invalid response` | CA не может получить доступ к проверочному файлу | Проверить файрвол, CDN, WAF; убедиться что запрос `http://example.com/.well-known/acme-challenge/` возвращает 200 |
| `Skip verify` | CA пропустил проверку (обычно в --test) | Нормальное поведение staging-режима |

### Диагностические команды

```bash
# Подробная отладка выпуска
acme.sh --issue -d example.com --dns dns_cf --debug 2

# Проверка DNS-записи
dig +short TXT _acme-challenge.example.com

# Проверка доступности проверочного URL
curl -I http://example.com/.well-known/acme-challenge/test

# Проверка статуса cron
crontab -l | grep acme.sh
systemctl status cron    # или crond

# Проверка ARI-рекомендаций
acme.sh --cron --debug 2 | grep "Renewal Info"

# Просмотр логов
journalctl -u cron --since "1 hour ago"
```

> **Важно:** При ошибке не повторяйте команду сразу — это приведет к rate limit. Сначала устраните причину, затем запустите с `--debug` для детального вывода.

## Рекомендации

### Выбор метода авторизации

| Сценарий | Метод | Обоснование |
| :--- | :--- | :--- |
| Public-facing веб-сервер с открытым 80 портом | HTTP-01 | Простота настройки, не требует DNS API |
| Wildcard-сертификат | DNS-01 | Единственный метод поддерживающий `*.example.com` |
| Сервер за файрволом / DMZ | DNS-01 | Не требует доступности сервера во время валидации |
| Контейнеризированная среда | DNS-01 или stateless | Идентичность хостов, отсутствие持久ного хранилища |
| HTTPS-only инфраструктура (без 80 порта) | TLS-ALPN-01 | Валидация через 443 порт |
| DNS API недоступен | dns-persist-01 | Одна TXT-запись на все обновления |

### Безопасность

- Храните API ключи DNS-провайдеров в переменных окружения или секрет-менеджере, не коммитьте в репозиторий.
- Права на `~/.acme.sh/`: `700` на директорию, `600` на приватные ключи.
- Используйте `--staging` для тестирования конфигурации перед боевым запуском.
- Включите уведомления (`--set-notify`) для отслеживания ошибок обновления.
- Для внутренних сервисов рассмотрите Private CA (HashiCorp Vault, step-ca) вместо публичных CA.

### Интеграция с инфраструктурой

- Для автоматического обновления сертификатов в контейнерах используйте deploy hooks (`--deploy-hook docker`).
- В Kubernetes используйте deploy hooks для обновления Secret или перезагрузки Ingress Controller.
- При использовании systemd вместо cron, настройте таймер:

```ini
# /etc/systemd/system/acme-sh.timer
[Unit]
Description=acme.sh certificate renewal timer

[Timer]
OnCalendar=*:00/6
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/acme-sh.service
[Unit]
Description=acme.sh certificate renewal

[Service]
Type=oneshot
ExecStart=/root/.acme.sh/acme.sh --cron --home /root/.acme.sh
```

### Очистка и ротация

```bash
# Просмотр списка сертификатов
acme.sh --list

# Просмотр деталей конкретного сертификата
acme.sh --info -d example.com

# Проверка срока действия
openssl x509 -in ~/.acme.sh/example.com/fullchain.cer -enddate -noout

# Отзыв сертификата
acme.sh --revoke -d example.com

# Удаление из базы acme.sh
acme.sh --remove -d example.com
```

## Дополнительная информация

**Связанные технологии:**
- [Let's Encrypt и Certbot — HTTPS для веб-серверов](./https_with_certbot.md) — общий обзор ACME, rate limits, методы авторизации
- [Angie — встроенный ACME-модуль](../Angie/angie_acme_module.md) — альтернатива внешним клиентам
- [Traefik — ACME и автоматические сертификаты](../Traefik/traefik_overview.md) — reverse proxy с встроенным ACME
- [HAProxy — SSL/TLS Termination](../../Networking/Protocols/ssl_tls_termination.md) — паттерны терминации TLS
- [HashiCorp Vault — внутренний CA](../../Vault/concepts.md) — Private CA для внутренних сервисов
- [Настройка TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md) — оптимальная конфигурация TLS

**Официальные ресурсы:**
- [Репозиторий acme.sh](https://github.com/acmesh-official/acme.sh)
- [acme.sh Wiki](https://github.com/acmesh-official/acme.sh/wiki)
- [Официальный сайт](https://acme.sh)
