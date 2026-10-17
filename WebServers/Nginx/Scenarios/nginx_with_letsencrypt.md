# Настройка Let's Encrypt с Nginx

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Certbot 5.x+ (совместимо с Certbot 2.x+)

## Определения

**ACME (Automated Certificate Management Environment, RFC 8555)** — сетевой протокол для полной автоматизации процедур подтверждения владения доменами, выпуска, обновления и отзыва сертификатов X.509 между клиентским ПО и удостоверяющим центром (CA). Работает исключительно через ACME v2 API.

**Let's Encrypt** — некоммерческий общественный центр сертификации (CA) под управлением ISRG (Internet Security Research Group), предоставляющий бесплатные TLS-сертификаты Domain Validation (DV) со стандартным сроком действия 90 дней.

**Certbot** — официальный консольный ACME-клиент от Electronic Frontier Foundation (EFF). Поддерживает методы аутентификации (authenticators: webroot, standalone, dns) и плагины интеграции с веб-серверами (installers: nginx, apache).

**Webroot (HTTP-01)** — протокольный метод валидации, при котором ACME-клиент размещает проверочный токен в файловой системе локального сервера по пути `/.well-known/acme-challenge/<TOKEN>`. Веб-сервер Nginx обслуживает этот путь по протоколу HTTP (порт 80), не прерывая обработку пользовательского трафика.

**DNS-01 Challenge** — метод валидации владения доменом через публикацию одноразовой криптографической TXT-записи `_acme-challenge.<DOMAIN>` в авторитетной DNS-зоне. Необходим для выпуска wildcard-сертификатов (`*.example.com`) и для изолированных серверов без входящего доступа по порту 80.

**Renewal Hook** — триггерные сценарии Certbot, выполняемые на этапах жизненного цикла продления:
- `pre-hook` — запускается перед выполнением попытки обновления;
- `deploy-hook` — выполняется строго после успешного выпуска или продления конкретного сертификата (используется для `nginx -s reload`);
- `post-hook` — выполняется после завершения сессии `certbot renew` независимо от её результата.

**ARI (Automated Renewal Information, RFC 9773)** — протокольное расширение ACME, позволяющее центру сертификации сообщать клиенту оптимальное временное окно для плановой или экстренной (при досрочном отзыве ключей CA) ротации сертификата.

**Multi-Perspective Validation** — механизм проверки Let's Encrypt, при котором валидационные запросы HTTP-01 и DNS-01 направляются одновременно из нескольких географически распределенных дата-центров для предотвращения атак с подменой DNS и перехватом BGP-маршрутов.

**Dual-Stack сертификация (ECDSA + RSA)** — схема развертывания двух цепочек сертификатов на одном виртуальном хосте Nginx (современный ECDSA P-256 для 99% клиентов и legacy RSA 2048/4096 для устаревших систем). Nginx согласует нужный сертификат на этапе TLS Handshake в зависимости от поддерживаемых клиентом наборов шифров.

**Graceful Reload (`SIGHUP`)** — перечитывание конфигурации и TLS-контекстов мастер-процессом Nginx без разрыва существующих соединений (`nginx -s reload`).

> Теоретические основы ACME, лимиты запросов, устройство цепочек доверия и параметры криптографических ключей описаны в **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)**. Общие параметры безопасности TLS описаны в **[Обзор TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

---

## Архитектура и базовые концепции

### Жизненный цикл и механизм работы HTTP-01 в Nginx

Процесс валидации и ротации сертификатов строится на взаимодействии ACME-клиента, веб-сервера и удостоверяющего центра:

```text
[ Let's Encrypt CA ] 
   │  (Multi-Perspective Validation)
   │  1. Запрос на выпуск (POST /acme/new-order)
   │◄──────────────────────────────────────────────── Certbot
   │  2. Выдача токена валидации                      │
   ├─────────────────────────────────────────────────►│
   │                                                  │ 3. Запись файла
   │                                                  ▼
   │                                      [/var/www/certbot/.well-known/acme-challenge/<token>]
   │                                                  ▲
   │  4. HTTP GET /.well-known/acme-challenge/<token> │
   ├────────────────────────────────────────►[ Nginx (Port 80) ]
   │                                                  │
   │  5. 200 OK + Payload токена                      │
   │◄─────────────────────────────────────────────────┘
   │
   │  6. Подпись и отдача fullchain.pem
   ├─────────────────────────────────────────────────► Certbot
                                                      │
                                                      │ 7. Deploy Hook: nginx -t && nginx -s reload
                                                      ▼
                                              [ Nginx Worker Pools ]
```

1. **Инициализация**: Certbot формирует приватный ключ (по умолчанию ECDSA `secp256r1`), запрос на сертификат (CSR) и запрашивает у CA задачу HTTP-01.
2. **Публикация токена**: Certbot сохраняет проверочный файл в каталог `webroot` по пути `/.well-known/acme-challenge/<token>`.
3. **Верификация**: Серверы валидации Let's Encrypt отправляют входящие HTTP-запросы на порт 80 домена. Nginx направляет запрос в указанную директорию и возвращает тело токена.
4. **Хранение в файловой системе**: При успешной проверке CA генерирует сертификат. Certbot сохраняет его в версионируемый каталог `/etc/letsencrypt/archive/<domain>/` и обновляет символические ссылки в `/etc/letsencrypt/live/<domain>/`:
   - `privkey.pem` — закрытый ключ сертификата;
   - `fullchain.pem` — серверный сертификат и промежуточные сертификаты CA (Leaf + Intermediate);
   - `chain.pem` — только промежуточные сертификаты;
   - `cert.pem` — только серверный сертификат (не используется в директивах `ssl_certificate` Nginx).
5. **Активация в Nginx**: Nginx читает сертификаты в память (`SSL_CTX`) только во время старта или выполнения `reload`. Изменение файлов и symlink на диске **не влияет** на работающие процессы Nginx до отправки сигнала `SIGHUP` (`nginx -s reload`).

### Архитектура каталогов Certbot и Inode-структура

Certbot организует хранилище с защитой от повреждения при сбоях:

```text
/etc/letsencrypt/
├── archive/                   # Физические файлы всех версий
│   └── example.com/
│       ├── cert1.pem
│       ├── chain1.pem
│       ├── fullchain1.pem
│       └── privkey1.pem
├── live/                      # Стабильные симлинки для сервисов
│   └── example.com/
│       ├── cert.pem      -> ../../archive/example.com/cert1.pem
│       ├── chain.pem     -> ../../archive/example.com/chain1.pem
│       ├── fullchain.pem -> ../../archive/example.com/fullchain1.pem
│       └── privkey.pem   -> ../../archive/example.com/privkey1.pem
├── renewal/                   # Конфигурационные файлы продления (.conf)
│   └── example.com.conf
└── renewal-hooks/             # Глобальные хуки
    ├── deploy/                # Выполняются при успешном обновлении
    ├── post/
    └── pre/
```

> **Важно для SRE:** Директивы Nginx `ssl_certificate` и `ssl_certificate_key` обязаны ссылаться строго на путь `/etc/letsencrypt/live/<domain>/fullchain.pem`, а не на физические файлы в `archive/`. Символические ссылки позволяют обновлять сертификаты атомарно.

### Проблема «курицы и яйца» (Bootstrap Trap) и стратегии решения

Если в конфигурации Nginx активирован блок `server { listen 443 ssl; }` с директивами `ssl_certificate`, ссылающимися на отсутствующие файлы `/etc/letsencrypt/live/...`, Nginx завершится с критической ошибкой синтаксиса:

```text
nginx: [emerg] cannot load certificate "/etc/letsencrypt/live/example.com/fullchain.pem": BIO_new_file() failed (SSL: error:02001002:system library:fopen:No such file or directory)
```

В инфраструктурном коде (Ansible, CI/CD, Docker Compose) ручное комментирование блоков недопустимо. Применяются три инженерных паттерна:

1. **Bootstrap-генерация самоподписанного сертификата-заглушки (Рекомендуемый для Docker и IaC):** Скрипт инициализации перед запуском Nginx проверяет наличие сертификата на диске. Если сертификат отсутствует, генерируется временный self-signed сертификат по целевым путям `live/`. Nginx успешно запускается на портах 80 и 443. После этого Certbot выпускает боевой сертификат через webroot (порт 80 доступен) и атомарно перезаписывает файлы, после чего выполняется `nginx -s reload`.
2. **Выпуск через временный standalone-сервер Certbot:** Порт 80 временно слушается Certbot (`certbot certonly --standalone`) до первого старта Nginx. Не подходит, если хост уже обслуживает рабочий трафик на 80 порту.
3. **Раздельные конфигурационные файлы (HTTP Bootstrap Config):** Nginx стартует с минимальным конфигом без SSL, выпускает сертификаты, затем переключается на рабочий конфиг с HTTPS через `include` или подмену symlink.

---

## Практические сценарии

### Предварительные требования

Перед развертыванием убедитесь в выполнении условий:
1. **Сетевая доступность:** Порты TCP 80 и 443 открыты во внешнюю сеть на аппаратном и программном файрволах (`iptables`, `nftables`, `ufw`).
2. **DNS-записи:** Доменные имена (A-запись для IPv4, AAAA-запись для IPv6) указывают на публичный IP-адрес хоста.
3. **Маршрутизация IPv6:** Если у домена настроена AAAA-запись, входящий трафик по IPv6 обязан корректно достигать Nginx. При сбое IPv6 Let's Encrypt вернет ошибку таймаута, даже если IPv4 настроен правильно.

---

### Сценарий 1: Docker Compose с автоматическим Bootstrap и ротацией

Полностью автономный стек Nginx + Certbot без необходимости вручную комментировать и раскомментировать конфигурацию при первом развертывании.

#### 1. Структура каталогов проекта

```text
/opt/nginx-certbot/
├── docker-compose.yaml
├── init-letsencrypt.sh
├── nginx/
│   ├── conf.d/
│   │   └── default.conf
│   └── snippets/
│       └── ssl-params.conf
└── certbot/
    ├── conf/
    └── www/
```

#### 2. Файл `docker-compose.yaml`

```yaml
services:
  nginx:
    image: nginx:1.26-alpine
    container_name: production_nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/snippets:/etc/nginx/snippets:ro
      - certbot_conf:/etc/letsencrypt:ro
      - certbot_www:/var/www/certbot:ro
    # Фоновый цикл каждые 12 часов выполняет безопасный reload для применения обновленных сертификатов
    command: >
      /bin/sh -c "while :; do sleep 12h & wait $${!}; nginx -t && nginx -s reload; done & nginx -g 'daemon off;'"

  certbot:
    image: certbot/certbot:v5.8.0
    container_name: production_certbot
    restart: unless-stopped
    volumes:
      - certbot_conf:/etc/letsencrypt:rw
      - certbot_www:/var/www/certbot:rw
    # Проверка обновлений каждые 12 часов (стандартная рекомендация EFF/ACME)
    entrypoint: >
      /bin/sh -c "trap exit TERM; while :; do certbot renew --webroot -w /var/www/certbot --quiet; sleep 12h & wait $${!}; done;"

volumes:
  certbot_conf:
    name: nginx_certbot_conf
  certbot_www:
    name: nginx_certbot_www
```

#### 3. Конфигурация Nginx (`./nginx/conf.d/default.conf`)

Используется модификатор `^~` для защиты эндпоинта валидации ACME от перехвата регулярными выражениями:

```nginx
# Перенаправление HTTP -> HTTPS с сохранением ACME-challenge
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Изолированная локация для ACME HTTP-01 challenge
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# Основной защищенный виртуальный хост
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com www.example.com;

    http2 on;

    # Пути к сертификатам Let's Encrypt
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Подключение оптимизированных параметров TLS
    include /etc/nginx/snippets/ssl-params.conf;

    location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
    }
}
```

#### 4. Общие параметры TLS (`./nginx/snippets/ssl-params.conf`)

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;

# Оптимальные наборы шифров для TLS 1.2 (TLS 1.3 настраивается библиотекой автоматически)
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;

# Кэширование TLS-сессий (10m = ~40 000 сессий)
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;

# OCSP Stapling (ускоряет TLS-handshake)
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
resolver 127.0.0.1 1.1.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;

# HSTS (63072000 сек = 2 года)
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options DENY always;
add_header X-Content-Type-Options nosniff always;
```

#### 5. Скрипт автоматического bootstrap (`init-letsencrypt.sh`)

Скрипт решает проблему отсутствующих файлов, создавая временный dummy-сертификат, запуская Nginx, выпуская реальный сертификат и удаляя временные артефакты:

```bash
#!/usr/bin/env bash
set -euo pipefail

DOMAINS=("example.com" "www.example.com")
RSA_KEY_SIZE=4096
DATA_PATH="./certbot"
EMAIL="admin@example.com"
STAGING=0 # Переключите на 1 для отладки лимитов Let's Encrypt

PRIMARY_DOMAIN="${DOMAINS[0]}"
CERT_DIR="${DATA_PATH}/conf/live/${PRIMARY_DOMAIN}"

if [ -d "${CERT_DIR}" ]; then
  read -rp "Сертификаты для ${PRIMARY_DOMAIN} уже существуют. Перевыпустить? (y/N) " DECISION
  if [ "${DECISION}" != "y" ] && [ "${DECISION}" != "Y" ]; then
    exit 0
  fi
fi

echo "==> Создание каталогов..."
mkdir -p "${DATA_PATH}/conf/live/${PRIMARY_DOMAIN}"
mkdir -p "${DATA_PATH}/www"

echo "==> Генерация временного самоподписанного сертификата..."
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "${CERT_DIR}/privkey.pem" \
  -out "${CERT_DIR}/fullchain.pem" \
  -subj "/CN=localhost" 2>/dev/null

echo "==> Запуск Nginx..."
docker compose up -d nginx

echo "==> Удаление временного сертификата перед запросом..."
rm -rf "${DATA_PATH}/conf/live/${PRIMARY_DOMAIN}"
rm -rf "${DATA_PATH}/conf/archive/${PRIMARY_DOMAIN}"
rm -rf "${DATA_PATH}/conf/renewal/${PRIMARY_DOMAIN}.conf"

echo "==> Запрос сертификата в Let's Encrypt..."
DOMAIN_ARGS=()
for DOMAIN in "${DOMAINS[@]}"; do
  DOMAIN_ARGS+=("-d" "${DOMAIN}")
done

STAGING_ARG=""
if [ "${STAGING}" != "0" ]; then
  STAGING_ARG="--staging"
fi

docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  ${STAGING_ARG} \
  "${DOMAIN_ARGS[@]}" \
  --email "${EMAIL}" \
  --rsa-key-size "${RSA_KEY_SIZE}" \
  --agree-tos \
  --force-renewal

echo "==> Применение новых сертификатов в Nginx..."
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload

echo "==> Запуск фонового контейнера Certbot..."
docker compose up -d certbot
echo "Готово. HTTPS успешно настроен."
```

---

### Сценарий 2: Bare metal и виртуальные машины (systemd + Deploy Hook)

При классическом развертывании Nginx работает как системный демон, а обновление контролируется системным таймером `systemd`.

#### 1. Установка пакетов

```bash
# Debian / Ubuntu (официальные репозитории)
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

# RHEL 9 / Rocky Linux 9 / AlmaLinux 9
sudo dnf install -y epel-release
sudo dnf install -y certbot python3-certbot-nginx
```

#### 2. Подготовка каталога webroot и прав доступа

Nginx-воркеры запускаются от непривилегированного пользователя (`www-data` или `nginx`). Certbot сохраняет приватные ключи в `/etc/letsencrypt/` с правами `0700` для пользователя `root`.

Настройка доступа без ослабления безопасности:

```bash
# Создание выделенного каталога под ACME-токены
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot
sudo chmod 755 /var/www/certbot

# Разрешение группе читать публичные каталоги live и archive
sudo chmod 755 /etc/letsencrypt/live
sudo chmod 755 /etc/letsencrypt/archive
```

> **SELinux (RHEL / Rocky / AlmaLinux):** При активном SELinux назначьте контексты файловой системы, иначе Nginx вернет `403 Forbidden` при обращении к токенам:
> ```bash
> sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/certbot(/.*)?"
> sudo restorecon -Rv /var/www/certbot
> # Разрешение Nginx отправлять исходящие запросы для OCSP stapling
> sudo setsebool -P httpd_can_network_connect 1
> ```

#### 3. Настройка переиспользуемого сниппета Nginx

Создайте сниппет `/etc/nginx/snippets/acme-challenge.conf`:

```nginx
location ^~ /.well-known/acme-challenge/ {
    root /var/www/certbot;
    default_type "text/plain";
    try_files $uri =404;
}
```

Подключите его в HTTP-блок `/etc/nginx/sites-available/example.com`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    include /etc/nginx/snippets/acme-challenge.conf;

    location / {
        return 301 https://$host$request_uri;
    }
}
```

Примените базовую конфигурацию:
```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
sudo systemctl reload nginx
```

#### 4. Первичный выпуск сертификата через Certbot

Выполните выпуск в режиме `certonly` с указанием webroot:

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  -d example.com -d www.example.com \
  --email admin@example.com \
  --agree-tos \
  --no-eff-email
```

Ожидаемый результат:
```text
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/example.com/fullchain.pem
# → Key is saved at:         /etc/letsencrypt/live/example.com/privkey.pem
```

#### 5. Настройка HTTPS в Nginx

Создайте SSL-блок в `/etc/nginx/sites-available/example.com`:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com www.example.com;

    http2 on;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/example.com/chain.pem;
    resolver 127.0.0.1 1.1.1.1 valid=300s;
    resolver_timeout 5s;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    location / {
        root /var/www/html;
        index index.html;
    }
}
```

Проверьте и примените:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

#### 6. Автоматизация ротации через Deploy Hook

Certbot сканирует каталог `/etc/letsencrypt/renewal-hooks/deploy/` и запускает расположенные там исполняемые файлы после каждого успешного обновления сертификата:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/01-nginx-reload.sh <<'EOF'
#!/bin/bash
set -euo pipefail

# Логирование события ротации
logger -t certbot-deploy-hook "Certificate updated for domains: ${RENEWED_DOMAINS:-unknown}. Validating and reloading Nginx..."

# Валидация синтаксиса перед перезагрузкой
if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx
    logger -t certbot-deploy-hook "Nginx reloaded successfully."
else
    logger -t certbot-deploy-hook "CRITICAL: Nginx configuration test failed! Reload aborted."
    exit 1
fi
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/01-nginx-reload.sh
```

#### 7. Контроль таймера systemd

Проверьте активность фонового таймера:

```bash
sudo systemctl status certbot.timer
# → Active: active (waiting)
sudo systemctl list-timers | grep certbot
# → certbot.timer    certbot.service
```

---

### Сценарий 3: Мультидоменные сертификаты (SAN) и добавление новых доменов

Сертификат Subject Alternative Name (SAN) объединяет несколько доменных имен в едином файле. Это снижает накладные расходы на TLS-сессии и упрощает администрирование.

#### Выпуск общего сертификата для нескольких сервисов

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  --cert-name company-services \
  -d example.com \
  -d www.example.com \
  -d api.example.com \
  -d static.example.com
```

#### Конфигурация Nginx с разделяемым сертификатом

```nginx
# Виртуальный хост API
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/letsencrypt/live/company-services/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/company-services/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Виртуальный хост статики
server {
    listen 443 ssl;
    server_name static.example.com;

    ssl_certificate /etc/letsencrypt/live/company-services/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/company-services/privkey.pem;

    location / {
        root /var/www/static;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

#### Добавление домена в существующий сертификат (Расширение)

Для расширения списка доменов используйте флаг `--expand` совместно с `--cert-name`:

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  --cert-name company-services \
  --expand \
  -d example.com \
  -d www.example.com \
  -d api.example.com \
  -d static.example.com \
  -d billing.example.com
```

---

### Сценарий 4: Wildcard-сертификат через DNS-01 на on-premise инфраструктуре (RFC 2136 / BIND9)

Для выпуска wildcard-сертификатов (`*.example.com`) метод HTTP-01 неприменим (запрещен спецификацией Let's Encrypt). В закрытых корпоративных сетях или на собственном оборудовании проверка выполняется через динамическое обновление локального DNS-сервера (BIND9, PowerDNS, Knot DNS) по протоколу **RFC 2136** с аутентификацией по ключу TSIG.

#### 1. Генерация ключа TSIG на DNS-сервере (BIND9)

```bash
tsig-keygen -a HMAC-SHA512 certbot-bind-key
```

Вывод команды добавляется в конфигурацию BIND (`/etc/bind/named.conf.local`):

```named
key "certbot-bind-key" {
    algorithm hmac-sha512;
    secret "V4B...k9L==";
};

zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    # Разрешить Certbot изменять только проверочную TXT-запись
    update-policy {
        grant certbot-bind-key name _acme-challenge.example.com. txt;
    };
};
```

Примените изменения в BIND:
```bash
sudo rndc reload
```

#### 2. Настройка плагина RFC 2136 на сервере с Nginx

Установите плагин:
```bash
# Ubuntu / Debian
sudo apt install -y python3-certbot-dns-rfc2136
```

Создайте защищенный файл конфигурации `/etc/letsencrypt/rfc2136.ini`:

```ini
# IP-адрес авторитетного DNS-сервера (Master)
dns_rfc2136_server = 192.168.1.53
dns_rfc2136_port = 53
dns_rfc2136_name = certbot-bind-key
dns_rfc2136_secret = V4B...k9L==
dns_rfc2136_algorithm = HMAC-SHA512
```

Защитите файл ключа:
```bash
sudo chmod 600 /etc/letsencrypt/rfc2136.ini
```

#### 3. Выпуск Wildcard-сертификата

```bash
sudo certbot certonly \
  --dns-rfc2136 \
  --dns-rfc2136-credentials /etc/letsencrypt/rfc2136.ini \
  --dns-rfc2136-propagation-seconds 15 \
  -d example.com \
  -d "*.example.com" \
  --email admin@example.com \
  --agree-tos
```

#### 4. Использование в конфигурации Nginx

```nginx
server {
    listen 443 ssl;
    server_name example.com *.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # Nginx обрабатывает любые поддомены первого уровня единым сертификатом
    location / {
        proxy_pass http://internal_app;
    }
}
```

---

### Сценарий 5: Настройка Dual-Stack сертификатов (ECDSA + RSA)

Dual-Stack архитектура гарантирует максимальную производительность для современных устройств (ECDSA P-256 требует меньше CPU при handshake) при сохранении совместимости со старыми корпоративными клиентами (RSA 4096).

#### 1. Выпуск сертификатов двух типов ключей

Certbot выпускает каждый тип в отдельный lineage (`--cert-name`):

```bash
# 1. Выпуск современного ECDSA сертификата
sudo certbot certonly --webroot -w /var/www/certbot \
  --cert-name example.com-ecdsa \
  --key-type ecdsa \
  --elliptic-curve secp256r1 \
  -d example.com -d www.example.com

# 2. Выпуск совместимого RSA сертификата
sudo certbot certonly --webroot -w /var/www/certbot \
  --cert-name example.com-rsa \
  --key-type rsa \
  --rsa-key-size 4096 \
  -d example.com -d www.example.com
```

#### 2. Конфигурация Nginx с двумя парами ключей

Nginx поддерживает одновременное указание директив `ssl_certificate` для RSA и ECDSA внутри одного контекста `server`:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name example.com www.example.com;

    http2 on;

    # ECDSA (отдается клиентам с поддержкой эллиптических кривых)
    ssl_certificate     /etc/letsencrypt/live/example.com-ecdsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-ecdsa/privkey.pem;

    # RSA (отдается устаревшим клиентам в качестве fallback)
    ssl_certificate     /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Шифры отсортированы с приоритетом ECDSA
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;

    location / {
        root /var/www/html;
        index index.html;
    }
}
```

---

## Операции и команды

### Валидация и проверка состояния

| Команда | Назначение | Ожидаемый результат / Контекст |
| :--- | :--- | :--- |
| `sudo nginx -t` | Синтаксическая проверка файлов конфигурации | `syntax is ok`<br>`test is successful` |
| `sudo certbot certificates` | Инспекция локального хранилища сертификатов | Список доменов, путей к `live/` и количества дней до истечения |
| `sudo certbot renew --dry-run` | Симуляция цикла автообновления всех сертификатов | `Congratulations, all simulated renewals succeeded` |
| `openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -dates` | Проверка точных дат `notBefore` и `notAfter` на диске | `notBefore=Oct 10 00:00:00 2026 GMT`<br>`notAfter=Jan  8 00:00:00 2027 GMT` |
| `openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -text \| grep -A1 "Subject Alternative Name"` | Проверка списка доменов (SAN) в теле сертификата | `DNS:example.com, DNS:www.example.com` |
| `openssl s_client -connect 127.0.0.1:443 -servername example.com </dev/null 2>/dev/null \| openssl x509 -noout -dates` | Проверка активного сертификата в памяти воркеров Nginx | Выводит даты сертификата, который Nginx отдает клиентам в текущий момент |
| `openssl s_client -connect example.com:443 -status -servername example.com </dev/null 2>&1 \| grep -A 17 "OCSP Response Data:"` | Проверка работы OCSP Stapling | `OCSP Response Status: successful (0x0)` |

### Управление жизненным циклом

| Команда | Назначение | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| `sudo certbot renew` | Немедленная проверка необходимости обновления | Пропускает сертификаты со сроком >30 дней, обновляет устаревающие |
| `sudo certbot renew --force-renewal --cert-name example.com` | Принудительное обновление конкретного сертификата | Игнорирует дату истечения (не использовать часто во избежание лимитов CA) |
| `sudo certbot delete --cert-name example.com` | Полное удаление сертификата и конфигурации renewal | Удаляет директории в `live/`, `archive/` и файл `renewal/` |
| `sudo certbot revoke --cert-path /etc/letsencrypt/live/example.com/cert.pem --reason keycompromise` | Немедленный отзыв сертификата в базе CA | Отправляет запрос на отзыв (причины: `unspecified`, `keycompromise`, `affiliationchanged`, `superseded`) |
| `sudo systemctl reload nginx` | Грациозная перезагрузка Nginx на хосте | Применяет обновленные файлы сертификатов без разрыва сессий |
| `docker compose exec nginx nginx -s reload` | Грациозная перезагрузка внутри контейнера | Сигнал `HUP` рабочим процессам в Docker |

### SRE-мониторинг истечения сертификатов в Prometheus

Для предотвращения инцидентов с истечением сертификатов применяются два уровня мониторинга:

#### 1. Blackbox Exporter (Синтетический L7-мониторинг)

Проверяет реальный ответ Nginx по сети с алертингом за 14 дней до истечения:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'blackbox_ssl'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://example.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115 # Blackbox exporter
```

Правило Prometheus Alertmanager:
```yaml
groups:
  - name: ssl_alerts
    rules:
      - alert: SSLCertExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "TLS-сертификат для {{ $labels.instance }} истекает через {{ $value | printf '%.1f' }} дней"
      - alert: SSLCertExpiringCritical
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 3
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "КРИТИЧЕСКИЙ СБОЙ: TLS-сертификат {{ $labels.instance }} истекает менее чем через 3 дня!"
```

#### 2. Node Exporter Textfile Collector (Мониторинг файлов на диске)

Скрипт `/usr/local/bin/certbot-exporter.sh` экспортирует точное количество дней до истечения локальных файлов для каждого домена:

```bash
#!/bin/bash
set -euo pipefail

TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
TEMP_FILE="${TEXTFILE_DIR}/certbot_metrics.prom.$$"

echo "# HELP certbot_cert_expires_in_days Days until TLS certificate expires" > "${TEMP_FILE}"
echo "# TYPE certbot_cert_expires_in_days gauge" >> "${TEMP_FILE}"

for CERT in /etc/letsencrypt/live/*/fullchain.pem; do
    [ -f "${CERT}" ] || continue
    DOMAIN=$(basename "$(dirname "${CERT}")")
    EXPIRY_DATE=$(openssl x509 -in "${CERT}" -enddate -noout | cut -d= -f2)
    EXPIRY_EPOCH=$(date -d "${EXPIRY_DATE}" +%s)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    echo "certbot_cert_expires_in_days{domain=\"${DOMAIN}\"} ${DAYS_LEFT}" >> "${TEMP_FILE}"
done

mv "${TEMP_FILE}" "${TEXTFILE_DIR}/certbot_metrics.prom"
```

---

## Устранение неисправностей

| Неисправность / Симптом | Причина сбоя | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **HTTP-01: `Invalid response: 404 Not Found`** | Nginx перехватывает путь `/.well-known/acme-challenge/` регулярным выражением (`location ~`), либо указан неверный `root`. | 1. Выполните `nginx -T \| grep -B2 -A10 "acme-challenge"`.<br>2. Создайте проверочный файл: `echo "test" > /var/www/certbot/.well-known/acme-challenge/probe`<br>3. Проверьте: `curl -i http://example.com/.well-known/acme-challenge/probe`. | 1. Задайте локацию строго с модификатором `^~`: `location ^~ /.well-known/acme-challenge/ { root /var/www/certbot; }`.<br>2. Убедитесь, что параметр `-w` в команде Certbot указывает на каталог `/var/www/certbot`, а не на `/var/www/certbot/.well-known`. |
| **HTTP-01: `Connection refused` или `Timeout`** | Порт 80 TCP закрыт на файрволе, либо провайдер блокирует входящий трафик, либо неверный DNS. | `curl -Iv -m 5 http://example.com:80`<br>`nc -zvw3 example.com 80`<br>`dig +short example.com A` | 1. Откройте порт 80: `ufw allow 80/tcp` или `firewall-cmd --add-port=80/tcp --permanent`.<br>2. Убедитесь, что Nginx слушает внешний интерфейс: `ss -tulpn \| grep :80`. |
| **HTTP-01 сбой по IPv6 при рабочем IPv4** | У домена настроена AAAA-запись, но Nginx не слушает IPv6, либо IPv6 заблокирован на шлюзе. Let's Encrypt по стандарту отдает **приоритет IPv6**. | `dig +short example.com AAAA`<br>`curl -6 -Iv http://example.com` | 1. Добавьте директиву `listen [::]:80;` во все блоки `server`.<br>2. Если поддержка IPv6 на хосте отсутствует, удалите некорректную AAAA-запись из DNS. |
| **`403 Forbidden` при обращении к токену** | Недостаточные права на каталоги, либо блокировка SELinux. | Проверьте лог Nginx:<br>`tail -n 20 /var/log/nginx/error.log`<br>Проверьте аудит SELinux:<br>`ausearch -m avc -ts recent` | 1. Назначьте права: `chmod -R 755 /var/www/certbot`.<br>2. Исправьте SELinux: `restorecon -Rv /var/www/certbot`. |
| **Nginx не запускается: `cannot load certificate ... No such file`** | «Проблема курицы и яйца»: Nginx пытается загрузить отсутствующие сертификаты при холодном старте. | `nginx -t`<br>Лог: `BIO_new_file() failed ... No such file or directory` | Сгенерируйте временный самоподписанный сертификат по целевому пути (см. Сценарий 1) либо временно закомментируйте директивы `ssl_*`. |
| **Сертификат продлился на диске, но браузер видит старый** | После выполнения `certbot renew` не был выполнен reload Nginx, либо reload завершился ошибкой синтаксиса. | 1. Проверьте диск: `openssl x509 -in /etc/letsencrypt/live/.../fullchain.pem -noout -enddate`<br>2. Проверьте память Nginx: `echo \| openssl s_client -connect 127.0.0.1:443 2>/dev/null \| openssl x509 -noout -enddate` | 1. Проверьте наличие и права deploy-hook: `/etc/letsencrypt/renewal-hooks/deploy/01-nginx-reload.sh`.<br>2. Выполните ручную перезагрузку: `nginx -t && nginx -s reload`. |
| **`429 Too Many Requests` (Rate Limits)** | Превышен лимит Let's Encrypt (максимум 5 одинаковых выпусков за 7 дней, либо 5 сбоев валидации за 1 час). | В логе Certbot: `too many failed authorizations recently` или `too many certificates already issued` | 1. Переключитесь на тестовую среду: добавьте параметр `--staging` для отладки.<br>2. Для временного обхода недельного лимита добавьте в запрос дополнительный поддомен (создается новый order) либо дождитесь сброса скользящего окна. |
| **Ошибка OCSP Stapling: `responder could not be reached`** | Nginx не может разрешить DNS-имя OCSP-сервера Let's Encrypt или исходящий UDP 53 закрыт. | `tail -f /var/log/nginx/error.log \| grep -i ocsp` | 1. Добавьте директиву `resolver 1.1.1.1 8.8.8.8 valid=300s;` в конфигурацию Nginx.<br>2. Проверьте доступность: `curl -Iv http://r10.o.lencr.org`. |

---

## Лучшие практики

### Безопасность (Security Hardening)

1. **Никогда не закрывайте порт 80:** Попытка закрыть порт 80 нарушает работу автоматического обновления Let's Encrypt и лишает клиентов возможности перейти на защищенное соединение через HTTP 301. Порт 80 должен быть постоянно открыт и отдавать безусловный редирект на HTTPS для всего трафика, кроме `/.well-known/acme-challenge/`.
2. **Изоляция приватных ключей:** Файлы `privkey.pem` должны иметь права `0600` (чтение только root). Не копируйте приватные ключи в сторонние общедоступные каталоги и не передавайте их по незащищенным каналам.
3. **Используйте алгоритм ECDSA:** Для всех новых инсталляций используйте кривую `secp256r1` (P-256). Это уменьшает размер TLS-пакетов, ускоряет Handshake и экономит ресурсы процессора под высокой нагрузкой.
4. **Конфигурация HSTS:** Включайте заголовок HSTS со сроком действия не менее одного года (`max-age=31536000`). Флаг `preload` добавляйте только после полной стабилизации инфраструктуры, так как вывод домена из глобального preload-списка браузеров занимает месяцы.

### Эксплуатационная надежность (SRE & Production Reliability)

1. **Обязательная валидация синтаксиса перед перезагрузкой:** Любой автоматизированный скрипт или хук обновления обязан проверять корректность конфигурации:
   ```bash
   nginx -t && nginx -s reload
   ```
   Если администратор допустил синтаксическую ошибку в другом файле виртуального хоста, неконтролируемый `systemctl reload` не сломает работающие процессы, но deploy-hook зафиксирует ошибку и предотвратит инцидент.
2. **Рандомизация времени запуска таймеров (Jitter):** Встроенные таймеры systemd для Certbot используют директиву `RandomizedDelaySec=43200` (разброс до 12 часов). Это предотвращает лавинообразную нагрузку на API Let's Encrypt ровно в 00:00. Не отключайте рандомизацию в cron/systemd.
3. **Использование `--deploy-hook` вместо `--post-hook`:** Параметр `--post-hook` выполняется при каждом запуске `certbot renew` (дважды в сутки), что приводит к бессмысленным перезагрузкам Nginx. Параметр `--deploy-hook` вызывается **только** в момент фактической успешной замены файлов сертификата на диске.

### Резервное копирование и Disaster Recovery

При аварии сервера или миграции на новый хост восстановить инфраструктуру без риска исчерпания лимитов Let's Encrypt позволяет резервное копирование конфигурации:

```bash
# Создание резервной копии конфигурации и ключей
sudo tar -czf certbot-backup-$(date +%F).tar.gz \
  /etc/letsencrypt/live \
  /etc/letsencrypt/archive \
  /etc/letsencrypt/renewal \
  /etc/letsencrypt/renewal-hooks
```

> **Правило восстановления:** При распаковке архива на новом сервере сохраняйте символические ссылки (`tar -xzf ...`). Если распаковать симлинки как обычные файлы, Certbot при следующей ротации потеряет связь между `live` и `archive` и создаст дублирующий lineage `example.com-0001`.

---

## См. также

- **[Настройка HTTPS с помощью Let's Encrypt и Certbot](../../Concepts/https_with_certbot.md)** — архитектурные принципы ACME, лимиты запросов, устройство цепочек доверия.
- **[Обзор TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)** — архитектура TLS в Nginx, фазы рукопожатия, кэш сессий и kTLS.
- **[Конфигурация виртуальных хостов TLS в Nginx](../Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — детальная настройка директив `ssl_*`, ALPN, HTTP/2 и HTTP/3.
- **[Nginx в Docker: Архитектура и эксплуатация](nginx_in_docker.md)** — развертывание Nginx в контейнерах, проброс портов и монтирование томов.
- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — структура конфигурационных файлов, директивы include и управление демоном.
- **[Модуль ACME в Angie](../../Angie/angie_acme_module.md)** — встроенная нативная поддержка ACME в форке Angie без необходимости запуска Certbot.
