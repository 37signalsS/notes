# Let's Encrypt и Certbot — HTTPS для веб-серверов

**Актуально для:** Certbot 5.8.x

## Определения

**Let's Encrypt** — некоммерческий общественный центр сертификации (CA, Certificate Authority) под управлением Internet Security Research Group (ISRG). Предоставляет бесплатные сертификаты X.509 Domain Validation (DV) со стандартным сроком действия 90 дней через протокол ACME (RFC 8555).

**ACME (Automated Certificate Management Environment, RFC 8555)** — стандарт протокола клиент-серверного взаимодействия, предназначенный для полной автоматизации жизненного цикла TLS-сертификатов: проверки владения идентификаторами (доменными именами и IP-адресами), выпуска, ротации и отзыва сертификатов без ручного вмешательства администратора. Используется исключительно ACME v2 API; протокол ACME v1 признан устаревшим и отключен.

**ACME v2 Directory Endpoints:**
* **Production:** `https://acme-v02.api.letsencrypt.org/directory` — рабочий удостоверяющий центр с жесткими лимитами запросов.
* **Staging:** `https://acme-staging-v02.api.letsencrypt.org/directory` — изолированная среда для отладки конфигураций, выпускающая недоверенные (fake) сертификаты с повышенными квотами.

**Certbot** — официальный консольный ACME-клиент, разрабатываемый Electronic Frontier Foundation (EFF) на Python 3. Поддерживает модульную архитектуру плагинов: аутентификаторы (authenticators) для прохождения проверок владения, установщики (installers) для автоматической модификации конфигураций веб-серверов, а также гибридные решения.

**Webroot (HTTP-01)** — метод аутентификации, при котором Certbot сохраняет одноразовые валидационные токены в файловую систему существующего веб-сервера по пути `/.well-known/acme-challenge/`. Не требует остановки веб-сервера.

**Standalone** — метод аутентификации, при котором Certbot временно запускает встроенный веб-сервер на TCP-порту 80 (или 443 для TLS-ALPN-01). Применяется на серверах без постоянного веб-демона или во время инициализации хоста.

**Manual** — метод аутентификации, при котором операции подтверждения выполняются вручную либо через пользовательские скрипты-обработчики (`--manual-auth-hook` и `--manual-cleanup-hook`).

**ARI (Automated Renewal Information, RFC 9773)** — стандартизированное расширение протокола ACME, посредством которого CA сообщает клиенту рекомендованный временной интервал ротации сертификата. Позволяет заблаговременно и плавно обновлять сертификаты при аварийном отзыве промежуточных центров или технических инцидентах. В современных версиях Certbot опрос ARI включен по умолчанию.

**CT (Certificate Transparency, RFC 6962 / RFC 9162)** — механизм публичного аудита выдачи сертификатов через открытые append-only журналы (logs). CA обязан внедрять метки Signed Certificate Timestamp (SCT) в выпускаемые сертификаты.

**Renewal Hooks** — точки расширения жизненного цикла продления:
* **Pre-hook (`--pre-hook`):** выполняется перед запуском попыток обновления (например, временное отключение файрвола).
* **Deploy-hook (`--deploy-hook`):** выполняется строго после успешного выпуска или продления конкретного сертификата. Принимает системные переменные окружения `$RENEWED_LINEAGE` (путь к каталогу с сертификатами) и `$RENEWED_DOMAINS` (список доменов).
* **Post-hook (`--post-hook`):** выполняется после завершения сессии `renew` независимо от результата.

### Типы криптографических ключей: ECDSA и RSA

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — асимметричный алгоритм на основе эллиптических кривых. В Certbot алгоритм ECDSA с кривой P-256 (`secp256r1`) используется по умолчанию. Обеспечивает высокий уровень криптографической стойкости (эквивалент RSA-3072) при минимальном размере ключа и подписи, что снижает нагрузку на CPU и ускоряет TLS-рукопожатие.

**RSA (Rivest–Shamir–Adleman)** — классический криптографический алгоритм. Поддерживаемые размеры: 2048 бит (минимально допустимый стандарт) и 4096 бит. Используется в dual-stack конфигурациях для обслуживания устаревших клиентов, не поддерживающих ECDSA.

### Лимиты запросов Let's Encrypt (Rate Limits)

Центр сертификации Let's Encrypt защищает свою инфраструктуру скользящими лимитами (sliding window):

| Тип лимита | Значение | Интервал | Описание и стратегия обхода |
| :--- | :--- | :--- | :--- |
| **Certificates per Registered Domain** | 50 сертификатов | 7 дней | Сумма сертификатов на базовый домен (eTLD+1). Объединяйте несколько поддоменов в один SAN-сертификат. |
| **Duplicate Certificate Limit** | 5 сертификатов | 7 дней | Сертификаты с абсолютно идентичным набором доменных имен. Избегайте частых перевыпусков; для тестирования используйте `--staging`. |
| **Failed Validation Limit** | 5 сбоев на аккаунт/хост | 1 час | Блокировка при 5 последовательных ошибках проверки. Тестируйте доступность через `--dry-run`. |
| **New Orders Limit** | 300 заказов | 3 часа | Создание новых заказов на один аккаунт. Предотвращает перегрузку базы ACME. |
| **Registration Rate Limit** | 10 аккаунтов на IP | 3 часа | Создание учетных записей ACME. Используйте единый аккаунт для всех узлов инфраструктуры. |

### Сертификаты для IP-адресов (Профиль shortlived)

Certbot поддерживает выпуск сертификатов для публичных IPv4/IPv6-адресов через профиль **shortlived**:
* **Срок действия:** 6–10 дней (требует непрерывного автообновления).
* **Ограничение:** Не поддерживает приватные диапазоны RFC 1918 / RFC 4193.
* **Синтаксис:**
```bash
sudo certbot certonly \
  --preferred-profile shortlived \
  --ip-address 203.0.113.10 \
  --standalone
```

### Цепочки доверия Let's Encrypt

Путь доверия (trust path) строится от корневого центра до конечного сертификата:
* **ISRG Root X1 (RSA)** — основной самоподписанный корневой сертификат, предустановленный во всех доверенных хранилищах современных ОС.
* **ISRG Root X2 (ECDSA)** — корневой сертификат на эллиптических кривых для коротких цепочек.
* **R10–R14 (RSA)** — промежуточные сертификаты (Intermediates) для подписи RSA-сертификатов (заменили устаревший R3).
* **E5–E9 (ECDSA)** — промежуточные сертификаты для подписи ECDSA-сертификатов (заменили устаревший E1).

### CAA-записи (RFC 8657)

**CAA (Certification Authority Authorization)** — запись в DNS, позволяющая владельцу домена явно указать центры сертификации, имеющие право выпускать сертификаты:

```dns
example.com.  IN  CAA  0 issue "letsencrypt.org"
example.com.  IN  CAA  0 issuewild "letsencrypt.org; validationmethods=dns-01"
example.com.  IN  CAA  0 iodef "mailto:security@example.com"
```

## Архитектура и принцип работы

### Жизненный цикл ACME-заказа

Взаимодействие между клиентом Certbot и удостоверяющим центром Let's Encrypt строго регламентировано стандартом RFC 8555:

```
+---------+              +---------------+              +-------------------+
| Certbot |              |  ACME Server  |              | Validation Server |
+----+----+              +-------+-------+              +---------+---------+
     |                           |                                |
     | 1. POST /acme/new-order   |                                |
     |-------------------------->|                                |
     | 2. Challenges & Authz URLs|                                |
     |<--------------------------|                                |
     |                           |                                |
     | 3. Provision Token        |                                |
     |    (webroot/DNS/ALPN)     |                                |
     |                           |                                |
     | 4. POST /acme/chall/<id>  |                                |
     |-------------------------->|                                |
     |                           | 5. Multi-Perspective Check     |
     |                           |------------------------------->|
     |                           | 6. Validation OK               |
     |                           |<-------------------------------|
     | 7. Order Status: 'valid'  |                                |
     |<--------------------------|                                |
     |                           |                                |
     | 8. POST /finalize (CSR)   |                                |
     |-------------------------->|                                |
     | 9. Download Certificate   |                                |
     |<--------------------------|                                |
```

1. **New Order (Создание заказа):** Certbot отправляет список доменных имен (SAN) на эндпоинт `/acme/new-order`.
2. **Authorizations (Авторизации):** CA возвращает список объектов авторизации с доступными типами проверок (HTTP-01, DNS-01, TLS-ALPN-01).
3. **Provisioning (Размещение секрета):** Certbot размещает валидационный токен в файловой системе (`webroot`), обновляет DNS-зону либо настраивает TLS-ответ.
4. **Challenge Trigger (Уведомление):** Certbot отправляет подписанный запрос CA, сигнализируя о готовности к проверке.
5. **Multi-Perspective Validation:** Серверы Let's Encrypt выполняют параллельные запросы из нескольких географически распределенных дата-центров (vantage points), исключая атаки с перехватом локального BGP/DNS-трафика.
6. **Finalize (Финализация):** После успешной проверки статуса Certbot генерирует закрытый ключ на стороне хоста, формирует CSR (Certificate Signing Request) и передает его на `/acme/order/<id>/finalize`.
7. **Certificate Retrieval:** CA подписывает сертификат и отдает цепочку `fullchain.pem`.

### Внутреннее устройство файловой структуры `/etc/letsencrypt/`

Certbot разделяет версионированное хранилище артефактов и стабильные точки монтирования через символические ссылки:

```
/etc/letsencrypt/
├── accounts/
│   └── acme-v02.api.letsencrypt.org/
│       └── directory/
│           └── <account_hash>/
│               ├── meta.json         # Метаданные аккаунта
│               ├── private_key.json  # Приватный ключ учетной записи ACME
│               └── regr.json         # Данные регистрации
├── archive/                          # Физическое хранилище ключей и сертификатов
│   └── example.com/
│       ├── cert1.pem                 # Сертификат сервера (версия 1)
│       ├── chain1.pem                # Промежуточные сертификаты (версия 1)
│       ├── fullchain1.pem            # Сертификат + цепочка (версия 1)
│       └── privkey1.pem              # Приватный ключ (версия 1)
├── live/                             # Символические ссылки на текущие версии в archive/
│   └── example.com/
│       ├── cert.pem -> ../../archive/example.com/cert1.pem
│       ├── chain.pem -> ../../archive/example.com/chain1.pem
│       ├── fullchain.pem -> ../../archive/example.com/fullchain1.pem
│       ├── privkey.pem -> ../../archive/example.com/privkey1.pem
│       └── README
├── renewal/                          # Файлы конфигурации продления для каждого домена
│   └── example.com.conf
└── renewal-hooks/                    # Скрипты автоматизации жизненного цикла
    ├── deploy/                       # Скрипты, исполняемые при успешном продлении
    ├── post/                         # Скрипты, исполняемые после завершения certbot renew
    └── pre/                          # Скрипты, исполняемые перед запуском проверки
```

> **Важно:** Веб-серверы и балансировщики должны конфигурироваться исключительно на пути в каталоге `/etc/letsencrypt/live/<domain>/`. Прямое указание файлов из каталога `archive/` нарушает механизм автоматической ротации.

### Сравнение методов валидации ACME

| Метод | Сетевой порт | Поддержка Wildcard | Требования к сетевому контуру | Применимость в инфраструктуре |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP-01** | TCP 80 (HTTP) | Нет | Порт 80 должен быть открыт в интернет. Допустим редирект 301/302 на HTTPS. | Стандарт для веб-серверов (Nginx, Apache, Angie). Не требует доступа к DNS. |
| **DNS-01** | Любой (исходящий DNS/HTTPS) | **Да** (`*.example.com`) | Не требует входящих подключений на сервер. Требует API DNS или RFC 2136. | Изолированные контуры, DMZ, внутренние сервисы, балансировщики нагрузки. |
| **TLS-ALPN-01** | TCP 443 (HTTPS) | Нет | Порт 443 должен быть напрямую направлен на процесс ACME. | Reverse-прокси, Edge-балансировщики, где порт 80 строго заблокирован. |

### Механизм автоматического продления (Renewal Logic)

Команда `certbot renew` работает по следующему алгоритму:
1. Сканирует конфигурационные файлы в каталоге `/etc/letsencrypt/renewal/*.conf`.
2. Опрашивает эндпоинт ARI (RFC 9773). Если CA передал окно обновления — использует его.
3. При отсутствии данных ARI проверяет срок действия локального сертификата: если до истечения остается **менее 30 дней** (параметр `renew_before_expiry`), инициируется процесс перевыпуска.
4. Выполняет аутентификацию с использованием параметров, сохраненных в `.conf`.
5. При успешном получении новых файлов обновляет симлинки в `/etc/letsencrypt/live/<domain>/` на новую версию в `archive/`.
6. Вызывает скрипты из каталога `/etc/letsencrypt/renewal-hooks/deploy/` или переданные через директиву `deploy_hook`.

## Практические сценарии

### Сценарий 1: Установка и инициализация Certbot

EFF официально рекомендует установку Certbot через **snapd**, гарантирующий получение актуальных сборок и криптографических библиотек.

#### Вариант A: Установка через Snap (Основной способ)

```bash
# 1. Проверка и установка snapd (Debian/Ubuntu)
sudo apt update && sudo apt install -y snapd
# Для RHEL/Rocky Linux: sudo dnf install -y epel-release && sudo dnf install -y snapd

# 2. Удаление legacy-пакетов certbot
sudo apt remove -y certbot python3-certbot-nginx python3-certbot-apache 2>/dev/null || true

# 3. Установка ядра snap и классического пакета certbot
sudo snap install core && sudo snap refresh core
sudo snap install --classic certbot

# 4. Создание системной символической ссылки
sudo ln -sf /snap/bin/certbot /usr/bin/certbot

# 5. Проверка установленной версии
certbot --version
# → certbot 5.8.0
```

#### Вариант B: Установка через системный пакетный менеджер (Для систем без snapd)

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y certbot python3-certbot-nginx python3-certbot-apache

# RHEL / Rocky Linux 9 / AlmaLinux 9
sudo dnf install -y epel-release
sudo dnf install -y certbot python3-certbot-nginx python3-certbot-apache
```

### Сценарий 2: Получение и интеграция сертификатов в Nginx

#### Метод Webroot (Рекомендуемый для Production)

Метод `webroot` полностью изолирует процесс валидации от внутренней маршрутизации Nginx и исключает необходимость вмешательства Certbot в системные файлы конфигурации.

**Шаг 1. Создание каталога для проверки владения:**

```bash
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot
sudo chmod -R 755 /var/www/certbot
```

**Шаг 2. Конфигурация Nginx для прохождения HTTP-01:**

В конфигурации виртуального хоста `/etc/nginx/conf.d/example.com.conf`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Обработка ACME-валидации Let's Encrypt
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        try_files $uri =404;
    }

    # Принудительный редирект всего остального трафика на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}
```

Проверка синтаксиса и применение настроек:

```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
```

**Шаг 3. Запрос сертификата в режиме certonly:**

```bash
sudo certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d example.com \
  -d www.example.com \
  --agree-tos \
  --email admin@example.com \
  --no-eff-email \
  --key-type ecdsa
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/example.com/fullchain.pem
# → Key is saved at:         /etc/letsencrypt/live/example.com/privkey.pem
```

**Шаг 4. Настройка TLS-блока с Dual-Stack (ECDSA + RSA):**

Для обеспечения максимальной производительности современных клиентов и совместимости со старыми системами выпускается два сертификата:

```bash
# Выпуск дополнительного RSA-сертификата в отдельный каталог
sudo certbot certonly \
  --webroot \
  -w /var/www/certbot \
  --cert-name example.com-rsa \
  -d example.com -d www.example.com \
  --key-type rsa \
  --rsa-key-size 2048 \
  --agree-tos \
  --email admin@example.com
```

Итоговый HTTPS-блок в `/etc/nginx/conf.d/example.com.conf`:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name example.com www.example.com;

    # ECDSA (Первичный, высокий приоритет)
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA (Вторичный, для устаревших клиентов)
    ssl_certificate /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    # Оптимизация параметров TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;

    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
    resolver 127.0.0.53 1.1.1.1 valid=300s;
    resolver_timeout 5s;

    # HSTS (Strict-Transport-Security)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    location / {
        root /var/www/html;
        index index.html;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Сценарий 3: Настройка для Apache HTTP Server

```bash
# Получение сертификата через webroot для Apache
sudo certbot certonly \
  --webroot \
  -w /var/www/html \
  -d example.com -d www.example.com \
  --agree-tos \
  --email admin@example.com
```

Конфигурация VirtualHost в `/etc/apache2/sites-available/example.com-ssl.conf`:

```apache
<VirtualHost *:443>
    ServerName example.com
    ServerAlias www.example.com
    DocumentRoot /var/www/html

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/example.com/privkey.pem

    # Безопасные протоколы и шифры
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
    SSLCipherSuite ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
    SSLHonorCipherOrder off

    # Включение OCSP Stapling
    SSLUseStapling on
</VirtualHost>

<IfModule mod_ssl.c>
    SSLStaplingCache shmcb:/var/run/apache2/stapling_cache(512000)
</IfModule>
```

Проверка конфигурации и применение:

```bash
sudo apachectl configtest
# → Syntax OK

sudo systemctl reload apache2
```

### Сценарий 4: Интеграция с HAProxy через объединенный PEM-файл

Балансировщик HAProxy требует объединения закрытого ключа и сертификата с промежуточными центрами в единый файл формата `.pem`.

**Шаг 1. Создание скрипта-обработчика Deploy Hook:**

`/etc/letsencrypt/renewal-hooks/deploy/haproxy-concat.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Каталог для сертификатов HAProxy
HAPROXY_CERT_DIR="/etc/haproxy/certs"
mkdir -p "$HAPROXY_CERT_DIR"

for DOMAIN in $RENEWED_DOMAINS; do
    # Проверяем наличие каталога live
    if [ -d "$RENEWED_LINEAGE" ]; then
        TARGET_FILE="${HAPROXY_CERT_DIR}/$(basename "$RENEWED_LINEAGE").pem"
        cat "${RENEWED_LINEAGE}/fullchain.pem" "${RENEWED_LINEAGE}/privkey.pem" > "$TARGET_FILE"
        chmod 600 "$TARGET_FILE"
        chown haproxy:haproxy "$TARGET_FILE"
    fi
done

# Валидация и перезагрузка конфигурации HAProxy
haproxy -c -f /etc/haproxy/haproxy.cfg
systemctl reload haproxy
```

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/haproxy-concat.sh
```

**Шаг 2. Первичный выпуск с ручным вызовом сборки:**

```bash
sudo certbot certonly \
  --standalone \
  --http-01-port 8888 \
  -d lb.example.com \
  --agree-tos \
  --email admin@example.com

# Ручное выполнение хука для создания первого pem-файла
RENEWED_DOMAINS="lb.example.com" \
RENEWED_LINEAGE="/etc/letsencrypt/live/lb.example.com" \
sudo /etc/letsencrypt/renewal-hooks/deploy/haproxy-concat.sh
```

### Сценарий 5: Standalone-режим (Для изолированных узлов)

Если на хосте отсутствует запущенный веб-сервер, Certbot поднимает собственный слушающий сокет:

```bash
# Получение сертификата на чистом сервере
sudo certbot certonly \
  --standalone \
  --preferred-challenges http \
  -d service.example.com \
  --agree-tos \
  --email admin@example.com
```

Если порт 80 уже занят сторонним сервисом (не поддерживающим webroot), используются pre-hook и post-hook для кратковременной остановки:

```bash
sudo certbot certonly \
  --standalone \
  --pre-hook "systemctl stop my-custom-daemon" \
  --post-hook "systemctl start my-custom-daemon" \
  -d service.example.com
```

### Сценарий 6: On-Premise Wildcard через DNS-01 и RFC 2136 (BIND9)

Для выпуска wildcard-сертификатов (`*.example.com`) в изолированных корпоративных инфраструктурах без обращения к публичным облачным API используется протокол динамических обновлений DNS (RFC 2136).

**Шаг 1. Установка плагина:**

```bash
# Для snap
sudo snap install certbot-dns-rfc2136
sudo snap set certbot trust-plugin-with-root=ok
sudo snap connect certbot:plugin certbot-dns-rfc2136

# Для apt
# sudo apt install -y python3-certbot-dns-rfc2136
```

**Шаг 2. Генерация TSIG-ключа на DNS-сервере (BIND9):**

```bash
tsig-keygen -a HMAC-SHA512 certbot-key
```

Добавление ключа и политики обновления в `named.conf.local`:

```named
key "certbot-key" {
    algorithm hmac-sha512;
    secret "hP4mQ6J...==";
};

zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    update-policy {
        grant certbot-key name _acme-challenge.example.com. txt;
    };
};
```

**Шаг 3. Настройка конфигурационного файла на хосте Certbot:**

Создание защищенного файла `/etc/letsencrypt/rfc2136.ini`:

```ini
# IP-адрес первичного DNS-сервера (Master)
dns_rfc2136_server = 192.168.10.53
# Сетевой порт DNS
dns_rfc2136_port = 53
# Имя ключа TSIG
dns_rfc2136_name = certbot-key
# Секретный ключ
dns_rfc2136_secret = hP4mQ6J...==
# Алгоритм подписи
dns_rfc2136_algorithm = HMAC-SHA512
```

```bash
sudo chmod 600 /etc/letsencrypt/rfc2136.ini
```

**Шаг 4. Выпуск Wildcard-сертификата:**

```bash
sudo certbot certonly \
  --dns-rfc2136 \
  --dns-rfc2136-credentials /etc/letsencrypt/rfc2136.ini \
  --dns-rfc2136-propagation-seconds 30 \
  -d example.com \
  -d "*.example.com" \
  --agree-tos \
  --email admin@example.com
```

### Сценарий 7: Выпуск сертификата для публичного IP-адреса

Выпуск сертификата для хостов, доступных исключительно по IP-адресу (без DNS-имени), через профиль `shortlived`:

```bash
sudo certbot certonly \
  --preferred-profile shortlived \
  --ip-address 198.51.100.25 \
  --webroot \
  -w /var/www/certbot \
  --agree-tos \
  --email admin@example.com
```

Проверка сертификата утилитой OpenSSL:

```bash
openssl x509 -in /etc/letsencrypt/live/198.51.100.25/cert.pem -noout -text | grep -A1 "Subject Alternative Name"
# → X509v3 Subject Alternative Name:
# →     IP Address:198.51.100.25
```

### Сценарий 8: Автоматизация продления через systemd-таймеры и Deploy-Hooks

#### Управление таймером systemd

При установке через Snap Certbot автоматически регистрирует таймер `snap.certbot.renew.timer`. При установке из DEB/RPM пакетов создается `certbot.timer`.

Проверка статуса таймеров:

```bash
sudo systemctl list-timers | grep certbot
# → snap.certbot.renew.timer  Tue 2026-10-14 23:45:00 UTC  1h 12min left

sudo systemctl status snap.certbot.renew.timer
# → Active: active (waiting)
```

Инспекция юнита таймера:

```bash
systemctl cat snap.certbot.renew.timer
```

Обратите внимание на параметр `RandomizedDelaySec`: он распределяет время запуска службы по случайному интервалу, исключая одновременную нагрузку на серверы Let's Encrypt.

#### Создание отказоустойчивого Deploy Hook

Скрипты, размещенные в `/etc/letsencrypt/renewal-hooks/deploy/`, выполняются автоматически только при фактическом обновлении сертификатов.

Создание скрипта `/etc/letsencrypt/renewal-hooks/deploy/01-reload-webservers.sh`:

```bash
#!/bin/bash
set -euo pipefail

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploy hook triggered for domains: $RENEWED_DOMAINS" >> /var/log/letsencrypt/deploy-hook.log

# 1. Перезагрузка Nginx при его наличии и успешном тесте синтаксиса
if systemctl is-active --quiet nginx; then
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nginx successfully reloaded" >> /var/log/letsencrypt/deploy-hook.log
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] CRITICAL: Nginx config test failed! Reload aborted." >> /var/log/letsencrypt/deploy-hook.log
    fi
fi

# 2. Перезагрузка Apache при его наличии
if systemctl is-active --quiet apache2; then
    if apachectl configtest >/dev/null 2>&1; then
        systemctl reload apache2
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Apache2 successfully reloaded" >> /var/log/letsencrypt/deploy-hook.log
    fi
fi
```

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/01-reload-webservers.sh
```

#### Настройка оповещения администраторов при сбое обновления (OnFailure)

Для отслеживания сбоев продления создается служебный юнит аварийного оповещения.

Создание обработчика `/etc/systemd/system/alert-failed-renewal@.service`:

```ini
[Unit]
Description=Alert on Certbot Renewal Failure (%I)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/send-alert.sh "CERTBOT CRITICAL: Service %I failed on %H. Check journalctl -u %I"
```

Переопределение сервиса через drop-in конфигурацию:

```bash
sudo mkdir -p /etc/systemd/system/snap.certbot.renew.service.d/
sudo tee /etc/systemd/system/snap.certbot.renew.service.d/override.conf << 'EOF'
[Unit]
OnFailure=alert-failed-renewal@%n.service
EOF

sudo systemctl daemon-reload
```

### Сценарий 9: Настройка прав доступа, POSIX ACL и SELinux/AppArmor

По умолчанию каталог `/etc/letsencrypt/live/` и закрытые ключи в `archive/` доступны только пользователю `root` (права `0700` / `0600`). Веб-серверы (Nginx, Lighttpd, Angie), запускаемые от имени непривилегированных пользователей (`www-data`, `nginx`), требуют гранулярного доступа.

#### Вариант A: Использование POSIX ACL (Рекомендуемый)

```bash
# Предоставление прав на чтение каталогов live и archive
sudo setfacl -R -m u:www-data:rX /etc/letsencrypt/live/
sudo setfacl -R -m u:www-data:rX /etc/letsencrypt/archive/

# Установка прав по умолчанию для вновь создаваемых файлов в archive/
sudo setfacl -R -d -m u:www-data:rX /etc/letsencrypt/archive/
```

#### Вариант B: Групповые права через chgrp

```bash
sudo groupadd -f ssl-cert
sudo usermod -aG ssl-cert www-data

sudo chgrp -R ssl-cert /etc/letsencrypt/live /etc/letsencrypt/archive
sudo chmod 750 /etc/letsencrypt/live /etc/letsencrypt/archive
sudo chmod 640 /etc/letsencrypt/archive/*/*.pem
```

#### SELinux (RHEL, Rocky Linux, AlmaLinux)

Если SELinux работает в режиме `Enforcing`, веб-сервер `httpd`/`nginx` может получить отказ `Permission denied` при попытке прочитать сертификаты:

```bash
# Проверка текущего контекста безопасности
sudo ls -lZ /etc/letsencrypt/live/example.com/
# → lrwxrwxrwx. root root system_u:object_r:cert_t:s0 fullchain.pem -> ../../archive/example.com/fullchain1.pem

# Восстановление стандартного контекста cert_t
sudo semanage fcontext -a -t cert_t "/etc/letsencrypt/(live|archive)(/.*)?" 2>/dev/null || true
sudo restorecon -Rv /etc/letsencrypt/

# Разрешение Nginx сетевых подключений для проксирования и валидации
sudo setsebool -P httpd_can_network_connect 1
```

#### AppArmor (Ubuntu / Debian)

Если профиль Nginx в AppArmor блокирует доступ к каталогу сертификатов:

```bash
# Проверка блокировок в аудит-логе
sudo dmesg | grep -i apparmor | grep -i letsencrypt

# Добавление локального правила в /etc/apparmor.d/local/usr.sbin.nginx:
echo "/etc/letsencrypt/archive/** r," | sudo tee -a /etc/apparmor.d/local/usr.sbin.nginx
echo "/etc/letsencrypt/live/** r," | sudo tee -a /etc/apparmor.d/local/usr.sbin.nginx

# Перезагрузка профиля AppArmor
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.nginx
```

### Сценарий 10: Резервное копирование и Disaster Recovery

При резервном копировании критически важно сохранить симлинки и каталог `accounts/`. Утрата приватного ключа аккаунта лишает возможности отзывать или изменять параметры существующих сертификатов через старую учетную запись.

#### Создание резервной копии:

```bash
# Архивирование с сохранением относительных символических ссылок
sudo tar -czpf /var/backups/letsencrypt-backup-$(date +%F).tar.gz \
  -C /etc letsencrypt

# Проверка содержимого архива
tar -ztvf /var/backups/letsencrypt-backup-$(date +%F).tar.gz | grep live/
```

#### Аварийное восстановление:

```bash
# Остановка сервисов, зависящих от сертификатов
sudo systemctl stop nginx

# Восстановление каталога
sudo tar -xzpf /var/backups/letsencrypt-backup-2026-10-14.tar.gz -C /etc/

# Проверка целостности символических ссылок
ls -l /etc/letsencrypt/live/*/
# Если симлинки указывают на существующие файлы в ../../archive/<domain>/ — структура корректна

sudo systemctl start nginx
```

### Сценарий 11: Мониторинг срока действия TLS-сертификатов

#### Интеграция с Prometheus через blackbox_exporter

Стандартным SRE-подходом к мониторингу публичных TLS-сертификатов является blackbox-тестирование из внешней сети.

Конфигурация модуля в `blackbox.yml`:

```yaml
modules:
  tls_connect:
    prober: tcp
    timeout: 5s
    tcp:
      tls: true
      tls_config:
        insecure_skip_verify: false
```

Конфигурация сбора метрик в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'blackbox-ssl'
    metrics_path: /probe
    params:
      module: [tls_connect]
    static_configs:
      - targets:
          - example.com:443
          - www.example.com:443
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115  # Адрес blackbox-экспортера
```

Prometheus Alerting Rule (`alert-rules.yml`):

```yaml
groups:
  - name: ssl_expiry_alerts
    rules:
      - alert: SSLCertificateExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 14
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "TLS certificate for {{ $labels.instance }} expires in {{ $value | printf \"%.1f\" }} days"
          description: "Certbot renewal might have failed. Check journalctl -u snap.certbot.renew.service on the host."

      - alert: SSLCertificateCriticalExpiry
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 3
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "CRITICAL: TLS certificate for {{ $labels.instance }} expires in less than 3 days!"
```

#### Локальный Bash-скрипт мониторинга (для Nagios / Zabbix / Cron)

Скрипт проверяет сертификаты непосредственно на хосте и возвращает стандартные коды завершения (0 — OK, 1 — Warning, 2 — Critical):

```bash
#!/bin/bash
# /usr/local/bin/check-cert-expiry.sh
set -euo pipefail

WARN_DAYS=21
CRIT_DAYS=7
EXIT_CODE=0

for CERT in /etc/letsencrypt/live/*/cert.pem; do
    [ -f "$CERT" ] || continue
    DOMAIN=$(basename "$(dirname "$CERT")")
    END_DATE=$(openssl x509 -enddate -noout -in "$CERT" | cut -d= -f2)
    END_EPOCH=$(date -d "$END_DATE" +%s)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (END_EPOCH - NOW_EPOCH) / 86400 ))

    if [ "$DAYS_LEFT" -le "$CRIT_DAYS" ]; then
        echo "CRITICAL: Certificate for $DOMAIN expires in $DAYS_LEFT days ($END_DATE)"
        EXIT_CODE=2
    elif [ "$DAYS_LEFT" -le "$WARN_DAYS" ]; then
        echo "WARNING: Certificate for $DOMAIN expires in $DAYS_LEFT days ($END_DATE)"
        [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1
    else
        echo "OK: Certificate for $DOMAIN valid for $DAYS_LEFT days"
    fi
done

exit "$EXIT_CODE"
```

```bash
sudo chmod +x /usr/local/bin/check-cert-expiry.sh
sudo /usr/local/bin/check-cert-expiry.sh
# → OK: Certificate for example.com valid for 88 days
```

### Сценарий 12: Тестирование TLS-конфигурации и OCSP Stapling

```bash
# 1. Проверка валидности цепочки и протокола TLS 1.3
echo | openssl s_client -connect example.com:443 -servername example.com 2>&1 | \
  grep -E "Protocol|Cipher|Verify return code"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → Verify return code: 0 (ok)

# 2. Проверка работы OCSP Stapling
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | \
  grep -A 17 "OCSP response:" | head -n 10
# → OCSP Response Status: successful (0x0)
# → Cert Status: good

# 3. Проверка срока действия удаленного сертификата без браузера
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -dates
# → notBefore=Oct 14 18:00:00 2026 GMT
# → notAfter=Jan 12 18:00:00 2027 GMT
```

## Операции и команды

### Команды управления сертификатами

| Команда | Назначение | Пояснение и контекст использования |
| :--- | :--- | :--- |
| `certbot certificates` | Инспекция сертификатов | Выводит список всех зарегистрированных сертификатов, пути к файлам и оставшийся срок действия. |
| `certbot renew` | Обновление сертификатов | Продлевает все сертификаты, у которых до истечения осталось менее 30 дней (или по ARI). |
| `certbot renew --dry-run` | Тестирование продления | Симулирует процесс обновления через Staging API без изменения локальных файлов. |
| `certbot renew --force-renewal` | Принудительный перевыпуск | Заставляет обновить все сертификаты немедленно. Применять с осторожностью из-за Rate Limits. |
| `certbot delete --cert-name <name>` | Удаление сертификата | Полностью удаляет сертификат, архивные файлы, симлинки и файл `.conf` из базы Certbot. |
| `certbot revoke --cert-path <path>` | Отзыв сертификата | Отправляет запрос на отзыв сертификата в CA (при компрометации приватного ключа). |
| `certbot update_account` | Обновление контактов | Позволяет изменить контактный email учетной записи ACME. |
| `certbot plugins` | Список плагинов | Отображает установленные аутентификаторы и установщики. |
| `certbot reconfigure --cert-name <name>` | Изменение настроек | Позволяет перенастроить тип ключа, параметры аутентификатора без полного перевыпуска. |

### Диагностические команды

```bash
# Тестирование продления с выводом детального лога
sudo certbot renew --dry-run -v

# Проверка содержимого сертификата X.509
openssl x509 -in /etc/letsencrypt/live/example.com/cert.pem -noout -text

# Проверка соответствия открытого ключа в сертификате и приватного ключа
# (Хеши MD5 должны строго совпадать)
openssl x509 -noout -modulus -in /etc/letsencrypt/live/example.com/cert.pem | openssl md5
openssl rsa -noout -modulus -in /etc/letsencrypt/live/example.com/privkey.pem | openssl md5

# Просмотр логов Certbot
sudo tail -n 100 /var/log/letsencrypt/letsencrypt.log

# Просмотр журнала системного таймера продления
journalctl -u snap.certbot.renew.service -n 50 --no-pager
```

## Диагностика и устранение неисправностей

### Типичные ошибки и методы их устранения

| Симптом / Ошибка | Первопричина | Пошаговое решение |
| :--- | :--- | :--- |
| **Invalid response: 404 Not Found** при HTTP-01 | Webroot указан неверно либо Nginx перехватывает путь `/.well-known/acme-challenge/` другим `location` или редиректом. | 1. Убедитесь, что каталог совпадает: `certbot ... -w /var/www/certbot`.<br>2. Проверьте `nginx -T \| grep -A5 "acme-challenge"`.<br>3. Создайте проверочный файл `echo "ok" > /var/www/certbot/.well-known/acme-challenge/test` и проверьте `curl -Iv http://example.com/.well-known/acme-challenge/test`. |
| **Connection refused (Port 80)** | Закрыт TCP-порт 80 в брандмауэре (UFW, firewalld, nftables) либо веб-сервер не слушает порт 80. | 1. Проверьте сокеты: `sudo ss -tlpn \| grep ':80'`.<br>2. Проверьте правила: `sudo ufw status` или `sudo firewall-cmd --list-ports`.<br>3. Разрешите входящий трафик: `sudo ufw allow 80/tcp`. |
| **Rate limit exceeded: 5 failures per hour** | Превышен лимит неудачных попыток валидации на стороне Let's Encrypt. | 1. Немедленно прекратите повторные запуски команды.<br>2. Добавьте флаг `--staging` для отладки конфигурации.<br>3. Дождитесь истечения скользящего окна (ровно 60 минут с момента первой ошибки). |
| **DNS problem: NXDOMAIN / SERVFAIL** | DNS-записи домена не успели распространиться, либо DNS-сервер блокирует рекурсивные запросы от CA. | 1. Проверьте резолвинг через публичные DNS: `dig +trace example.com` и `dig @8.8.8.8 example.com A`.<br>2. Для DNS-01 увеличьте тайм-аут распространения флагом `--<plugin>-propagation-seconds 60`. |
| **CAA record prevents issuance** | В DNS домена присутствует CAA-запись, не разрешающая выпуск центру Let's Encrypt. | 1. Проверьте записи: `dig CAA example.com +short`.<br>2. Добавьте разрешение: `example.com. IN CAA 0 issue "letsencrypt.org"`. |
| **Broken symlinks in `/etc/letsencrypt/live/`** | Ручное удаление или перемещение файлов в каталоге `archive/`. | 1. Проверьте целостность: `ls -la /etc/letsencrypt/live/<domain>/`.<br>2. Пересоздайте ссылки на актуальные версии файлов `certN.pem`, `privkeyN.pem` в `archive/`.<br>3. Либо полностью удалите поврежденную конфигурацию через `certbot delete --cert-name <domain>` и выпустите сертификат заново. |
| **Permission denied (Nginx/Apache)** | Веб-сервер не может прочитать `privkey.pem` из-за строгих прав доступа (`0600 root:root`) или ограничений SELinux. | 1. Настройте POSIX ACL: `sudo setfacl -R -m u:www-data:rX /etc/letsencrypt/archive/`.<br>2. Примените контекст SELinux: `sudo restorecon -Rv /etc/letsencrypt/`. |

### Методология диагностики SRE

1. **Сетевой уровень:** Убедитесь, что внешний IP-адрес сервера совпадает с A/AAAA записями в DNS (`curl -4 icanhazip.com` и `dig +short A example.com`).
2. **Маршрутизация HTTP:** Проверьте доступность файла-маркера без браузерного кэша:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" http://example.com/.well-known/acme-challenge/test
   # Ожидаемый ответ: 200 (или 404, если файл отсутствует, но НЕ 301 на внешний ресурс и НЕ 502/503)
   ```
3. **Анализ логов Certbot:**
   ```bash
   grep -E "ERROR|FAILED" /var/log/letsencrypt/letsencrypt.log | tail -n 20
   ```
4. **Проверка Multi-Perspective Validation:** Если запрос с локального сервера проходит, но CA возвращает ошибку, проверьте доступность порта 80 из внешних сетей (например, через Looking Glass или мобильную сеть), исключая гео-блокировки по GeoIP в WAF/Nginx.

## Рекомендации и Best Practices

### Чеклист SRE / SysAdmin по управлению TLS-сертификатами

- [ ] **Staging-first подход:** Любое изменение структуры сертификата (добавление доменов, слияние SAN, смена плагина) предварительно тестируется флагом `--staging` или `--dry-run`.
- [ ] **Выделенный Webroot:** Метод `webroot` предпочтительнее автоматических плагинов `--nginx`/`--apache`, так как он не перезаписывает системные конфигурационные файлы веб-серверов сторонним Python-кодом.
- [ ] **Deploy Hooks вместо Post Hooks:** Для перезагрузки веб-сервисов используйте исключительно `--deploy-hook` или каталоги `/etc/letsencrypt/renewal-hooks/deploy/`. Это исключает бессмысленные reload веб-серверов при фоновых проверках каждые 12 часов.
- [ ] **Предварительная проверка синтаксиса:** В скриптах deploy-hook всегда вызывайте `nginx -t` или `apachectl configtest` перед выполнением команды `reload`.
- [ ] **Сохранение симлинков:** Никогда не копируйте отдельные файлы из каталога `live/` без сохранения относительных связей. При необходимости передачи сертификатов в Docker или chroot используйте Deploy Hook.
- [ ] **Мониторинг:** Настройте внешний blackbox-мониторинг истечения сертификатов за 21 и 7 дней до окончания срока.
- [ ] **Резервное копирование:** Каталог `/etc/letsencrypt` должен включаться в план регулярного резервного копирования инфраструктуры с обязательным сохранением прав доступа `tar -p`.

### Безопасность приватных ключей

* **Минимальные привилегии:** Приватные ключи в `/etc/letsencrypt/archive/<domain>/privkey*.pem` должны иметь маску `0600` или `0640` с доверенной группой.
* **Отзыв при компрометации:**
  ```bash
  sudo certbot revoke \
    --cert-path /etc/letsencrypt/live/example.com/cert.pem \
    --reason keycompromise
  ```
* **Ротация ключей:** Certbot по умолчанию генерирует новую ключевую пару при каждом успешном продлении сертификата, что соответствует требованиям Forward Secrecy.

### Сравнение Certbot с альтернативными ACME-клиентами

* **acme.sh** — легковесный ACME-клиент на чистом POSIX Shell без сторонних зависимостей (Python/Snap). Идеален для встраиваемых систем, серверов с дефицитом памяти и интеграции со 110+ DNS API. Детали: [acme.sh — ACME-клиент для TLS-сертификатов](./acme_sh.md).
* **Встроенный ACME в Angie** — веб-сервер со штатным модулем `angie_acme`, выполняющий выпуск и ротацию сертификатов в памяти без внешних cron-задач и перезагрузок рабочих процессов. Детали: [Автоматические TLS-сертификаты в Angie: модуль ACME](../Angie/angie_acme_module.md).
* **Traefik** — Edge-маршрутизатор со встроенной нативной поддержкой ACME Let's Encrypt и автоматическим управлением сертификатами в контейнерных средах. Детали: [Traefik — управление TLS и опциями](../Traefik/traefik-tls-options.md).

## Дополнительная информация

**См. также:**
* [acme.sh — ACME-клиент для TLS-сертификатов](./acme_sh.md) — обзор Shell-клиента и интеграции с DNS
* [Автоматические TLS-сертификаты в Angie: модуль ACME](../Angie/angie_acme_module.md) — нативный ACME без внешних утилит
* [Настройка Let's Encrypt с Nginx](../Nginx/Scenarios/nginx_with_letsencrypt.md) — сценарии интеграции Nginx в Docker и bare metal
* [Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md) — параметры шифрования, протоколы и оптимизация
* [Терминация SSL/TLS в сетевой инфраструктуре](../../Networking/Protocols/ssl_tls_termination.md) — HAProxy, балансировщики и сквозное шифрование
* [Traefik — конфигурация TLS](../Traefik/traefik-tls-options.md) — управление сертификатами в Traefik

**Официальные спецификации и ресурсы:**
* [RFC 8555 — Automatic Certificate Management Environment (ACME)](https://datatracker.ietf.org/doc/rfc8555/)
* [RFC 8737 — ACME TLS with Application Layer Protocol Negotiation (TLS-ALPN-01)](https://datatracker.ietf.org/doc/rfc8737/)
* [RFC 8657 — Certification Authority Authorization (CAA) Processing for ACME](https://datatracker.ietf.org/doc/rfc8657/)
* [RFC 9773 — Automated Certificate Management Environment (ACME) Renewal Information (ARI)](https://datatracker.ietf.org/doc/rfc9773/)
* [Документация Let's Encrypt](https://letsencrypt.org/docs/)
* [Официальная документация Certbot (EFF)](https://certbot.eff.org/docs/)
