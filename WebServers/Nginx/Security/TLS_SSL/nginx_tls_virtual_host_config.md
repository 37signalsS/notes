# Конфигурация виртуальных хостов TLS в Nginx

## Определения

**Виртуальный хост TLS (`server`)** — блок конфигурации Nginx, описывающий настройки безопасности и логику обработки запросов для конкретного доменного имени или IP-адреса. Параметры, заданные внутри `server`, имеют приоритет над глобальными настройками из блока `http`, что позволяет гибко настраивать разные уровни защиты для разных сайтов на одном физическом сервере.

**Server Name Indication (SNI)** — расширение TLS, позволяющее клиенту передавать имя хоста в ClientHello до завершения рукопожатия. Это критично для корректного выбора виртуального хоста на одном IP-адресе. Без SNI сервер может предъявить только один сертификат, что приводит к ошибкам доверия при доступе к остальным доменам. Теория и архитектура: **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)**.

**Scope (область видимости директивы)** — уровень конфигурации, на котором директива может быть объявлена:
- **`http`** (глобальный): применяется ко всем `server`. Примеры: `ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `ssl_ecdh_curve`, `ssl_stapling`.
- **`server`** (уровень хоста): переопределяет глобальные значения для конкретного домена. Примеры: `ssl_certificate`, `ssl_certificate_key`, `ssl_early_data`, `ssl_ech_file`, `ssl_stapling` (с индивидуальным `resolver`).
- **`location`** (локальный): может переопределять отдельные параметры в контексте обработки запроса.

**Двойной стек сертификатов (Dual Certificate Stack)** — одновременное использование ECDSA- и RSA-сертификатов для одного домена. Nginx автоматически выбирает наиболее подходящий сертификат в зависимости от возможностей клиента. В 2026 году ECDSA является предпочтительным стандартом.

**Encrypted Client Hello (ECH)** — расширение TLS 1.3, шифрующее всё сообщение ClientHello, включая SNI. Нативная поддержка в Nginx 1.30+ с OpenSSL 4.0+. Требует директивы `ssl_ech_file` и DNS-записей HTTPS/SVCB. Подробнее: **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)**.

**0-RTT Early Data** — механизм TLS 1.3, позволяющий клиенту отправить данные первого запроса вместе с ClientHello, экономя один RTT. Включается директивой `ssl_early_data on`. Риск: уязвимость к Replay-атакам. Требует обработки заголовка `Early-Data` на бэкенде.

**default_server** — специальный флаг в `listen`, указывающий, что данный `server` блок используется по умолчанию для всех запросов, которые не совпали ни с одним другим `server_name`. Критически важен для безопасности: должен обрывать рукопожатие через `ssl_reject_handshake on`.

## Основные концепции

### Иерархия наследования TLS-параметров

TLS-параметры в Nginx наследуются сверху вниз. Чем ближе директива к клиенту (ниже по иерархии), тем выше её приоритет:

1. **Блок `http`** — глобальные политики по умолчанию (`ssl_protocols`, `ssl_ciphers`, `ssl_ecdh_curve`, `ssl_session_cache`, `ssl_stapling`).
2. **Блок `server`** — переопределяет глобальные параметры для конкретного домена. Здесь задаются сертификаты, ключи, `ssl_early_data`, `ssl_ech_file`.
3. **Блок `location`** — может переопределять `ssl_verify_client` в потоковых контекстах (например, для API).

**Правило:** глобальные параметры являются базовой линией hardening; локальные могут только ослабить политику, но не усилить её относительно глобальных.

### Модель рабочих процессов и TLS-handshake

Nginx использует многопроцессную архитектуру: master-процесс управляет worker-процессами, каждый из которых обрабатывает соединения независимо. TLS-handshake выполняется в контексте воркера:

```
Клиент → [TCP SYN] → Nginx worker → [TLS ClientHello] → Nginx worker → [TLS ServerHello + Certificate] → Клиент
```

- **SNI выбор:** на основе `server_name` из ClientHello Nginx выбирает соответствующий `server` блок и его сертификат.
- **ECDHE обмен:** эфемерные ключи генерируются заново для каждого соединения, обеспечивая PFS.
- **Сессия:** после успешного handshake сессия кэшируется в `shared:SSL:...` для последующего возобновления.

### Требования к окружению (2026)

Для использования всех директив, описанных в этом документе:

- **Nginx 1.30+ (Stable)** или **1.29+ (Mainline)**: поддержка TLS 1.3, нативный ECH, QUIC.
- **OpenSSL 3.5 LTS+**: поддержка **ML-KEM-768** в гибридных схемах по умолчанию.
- **OpenSSL 4.0+**: необходима для нативной поддержки **ECH**.
- **Ядро Linux 5.10+**: требуется для kTLS (offload шифрования в ядро).

**Проверка версий:**
```bash
# Версия Nginx и библиотека OpenSSL
nginx -V 2>&1 | grep -o 'built with OpenSSL [0-9.]\+'
# → built with OpenSSL 3.5.1

# Наличие модулей HTTP/3 и kTLS
nginx -V 2>&1 | grep -o 'http_v3_module\|ktls'

# Версия ядра (для kTLS)
uname -r
# → 5.15.0-105-generic
```

### Директивы уровня `server` — обзор

| Директива | Уровень | Описание |
| :--- | :--- | :--- |
| `listen` | `server` | Указывает IP:PORT и флаги (`ssl`, `http2`, `quic`, `default_server`, `reuseport`). |
| `server_name` | `server` | Имя хоста или имена (через пробел) для сопоставления с SNI/Host. |
| `ssl_certificate` | `server` | Путь к PEM-файлу с полной цепочкой сертификатов (Leaf + Intermediate). |
| `ssl_certificate_key` | `server` | Путь к приватному ключу сервера. |
| `ssl_ech_file` | `server` | Путь к конфигурации ECH (OpenSSL 4.0+). |
| `ssl_early_data` | `server` | Включает 0-RTT Early Data (требует обработки на бэкенде). |
| `ssl_ocsp` | `server` | Включает OCSP-проверку клиентских сертификатов (mTLS). |
| `ssl_verify_client` | `server` | Режим проверки клиентского сертификата (`off`, `on`, `optional`). |
| `ssl_reject_handshake` | `server` | Обрывает handshake без отправки сертификата (для `default_server`). |

### Dual Stack и multiprotocol слушатели

В 2026 году production-серверы должны поддерживать одновременный прием TCP (HTTP/1.1, HTTP/2) и UDP (HTTP/3) на одном порту 443:

```nginx
server {
    # TCP IPv4 + IPv6 (HTTP/1.1 и HTTP/2)
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # UDP IPv4 + IPv6 (HTTP/3 QUIC)
    listen 443 quic;
    listen [::]:443 quic;
    http3 on;

    server_name example.com www.example.com;
    # ...
}
```

**Важно для SRE:**
- `reuseport` включается один раз на IP:PORT в основном конфиге `http`, а не в каждом `server`.
- Для QUIC обязателен `quic_retry on` для защиты от UDP-амплификации.
- Заголовок `Alt-Svc` информирует клиентов о поддержке HTTP/3 дляMigration.

### Управление сессиями на уровне `server`

Глобальные параметры сессий (`ssl_session_cache`, `ssl_session_timeout`, `ssl_session_tickets`) задаются в блоке `http` и наследуются всеми `server`. Однако на уровне хоста можно включать 0-RTT:

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    # 0-RTT только для идемпотентных операций
    ssl_early_data on;

    location / {
        # Обязательно передаем статус Early Data на бэкенд
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://api_backend;
    }
}
```

**Риски и защита:** без проверки `Early-Data` на бэкенде злоумышленник может повторить финансовый запрос. Используйте 0-RTT только для GET-запросов или если бэкенд проверяет идемпотентность.

### HSTS и security headers

Заголовки безопасности задаются на уровне `server` или `location`:

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # HSTS: 2 года + поддомены + preload
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Информирование о поддержке HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # Защита от MIME-type sniffing
    add_header X-Content-Type-Options "nosniff" always;

    # Запрет встраивания в iframe (защита от clickjacking)
    add_header X-Frame-Options "SAMEORIGIN" always;
}
```

## Практические сценарии

### 1. Базовый HTTPS виртуальный хост (ECDSA + RSA)

Минимальный production-конфиг для `/etc/nginx/conf.d/example.com.conf`:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name example.com www.example.com;

    # ECDSA (приоритетный, P-256)
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # RSA (резервный, 4096 бит)
    ssl_certificate     /etc/letsencrypt/live/example.com-rsa/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com-rsa/privkey.pem;

    # Глобальные параметры TLS наследуются из блока http

    location / {
        proxy_pass http://backend_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. Безопасный редирект HTTP → HTTPS

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # ACME HTTP-01 challenge
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    # Весь остальной трафик — на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}
```

### 3. Защита от сканирования SNI (`ssl_reject_handshake`)

Критически важная настройка для `default_server`. Обрывает соединение на стадии TLS-handshake, если клиент запрашивает неизвестный домен или обращается напрямую по IP:

```nginx
# /etc/nginx/conf.d/default.conf
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Обрыв handshake без передачи сертификата (Nginx 1.19.4+)
    ssl_reject_handshake on;
}
```

### 4. Включение ECH (Encrypted Client Hello)

Требует OpenSSL 4.0+ и Nginx 1.30+:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    server_name example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # ECH конфигурация (путь к ключам ECH)
    ssl_ech_file /etc/nginx/ech/example_com.config;

    # В глобальном блоке http должна быть гибридная кривая:
    # ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
}
```

**Требования:**
- DNS-записи HTTPS/SVCB, указывающие на публичный ключ ECH.
- Конфигурация ECH, сгенерированная через `openssl genpkey` и `openssl pkey`.
- Гибридная кривая `X25519MLKEM768` в глобальном блоке `http`.

### 5. Оптимизация производительности (0-RTT и OCSP)

```nginx
server {
    listen 443 ssl http2;
    server_name fast.example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    # TLS 1.3 0-RTT (только для идемпотентных методов)
    ssl_early_data on;

    # OCSP Stapling (индивидуальный резолвер для хоста)
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    location / {
        # Передаем бэкенду статус Early Data для предотвращения Replay атак
        proxy_set_header Early-Data $ssl_early_data;
        proxy_pass http://app;
    }
}
```

### 6. Настройка QUIC и HTTP/3

В 2026 году QUIC является основным протоколом для мобильного трафика:

```nginx
server {
    # TCP-слушатели (HTTP/1.1 и HTTP/2)
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # UDP-слушатели (HTTP/3 QUIC)
    listen 443 quic;
    listen [::]:443 quic;
    http3 on;

    server_name example.com;

    # Защита от UDP-амплификации и атак с подменой IP
    quic_retry on;

    # Реклама протокола клиенту (переключение с TCP на UDP)
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://backend;
    }
}
```

Детальная настройка QUIC: **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Performance/nginx_http_versions.md)**.

### 7. Разделение Health Check и внешнего трафика

При `ssl_verify_client on` (mTLS) локальные проверки завершаются ошибкой. Выделите отдельный слушатель без mTLS, ограниченный `localhost`:

```nginx
# Внутренний порт для Health Checks
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /healthz {
        access_log off;
        return 200 "healthy\n";
    }
}

# Внешний HTTPS порт с полной TLS-защитой
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';

    ssl_early_data on;
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    location / {
        proxy_pass http://internal_app;
        proxy_set_header Early-Data $ssl_early_data;
    }
}
```

### 8. Валидация и применение конфигурации

```bash
# Проверка синтаксиса (обязательно перед reload)
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload без разрыва соединений
sudo systemctl reload nginx

# Проверка активных слушающих портов (TCP)
sudo ss -tlpn | grep ':443'

# Проверка UDP-порта для HTTP/3
sudo ss -ulpn | grep ':443'

# Проверка TLS 1.3 и шифра
openssl s_client -connect domain.com:443 -servername domain.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful

# Проверка поддержки HTTP/3
curl --http3 -v -I https://example.com 2>&1 | grep -i "alt-svc"
```

### Логирование TLS для аудита

```nginx
log_format tls_audit '$remote_addr [$time_local] "$request" '
                     'proto:$ssl_protocol cipher:$ssl_cipher '
                     'curve:$ssl_curves reused:$ssl_session_reused '
                     'ech:$ssl_ech_status earlydata:$ssl_early_data';

server {
    access_log /var/log/nginx/tls_audit.log tls_audit;
}
```

## Операции и команды

### Управление службой Nginx

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `nginx -t` | Обязательно перед каждым reload |
| **Graceful reload** | `nginx -s reload` | Без разрыва активных соединений |
| **Переоткрытие логов** | `nginx -s reopen` | Ротация лог-файлов |
| **Остановка** | `nginx -s stop` | Быстрая остановка |
| **Корректное завершение** | `nginx -s quit` | Ожидание завершения запросов |
| **Статус systemd** | `systemctl status nginx` | Проверка активного статуса |

### Диагностика виртуальных хостов

```bash
# Проверка активных TLS-сессий
sudo ss -tnp | grep :443 | grep ESTAB

# Проверка UDP-порта для HTTP/3
sudo ss -ulpn | grep :443

# Проверка модуля HTTP/3
nginx -V 2>&1 | grep -o 'http_v3_module'

# Валидация конкретного server блока
sudo nginx -T 2>/dev/null | grep -A20 "server_name example.com"

# Проверка сертификата и цепочки
openssl s_client -connect domain.com:443 -servername domain.com -showcerts 2>&1 | \
  openssl x509 -noout -subject -issuer -dates -ext subjectAltName

# Проверка OCSP Stapling
openssl s_client -connect domain.com:443 -servername domain.com -status 2>&1 | \
  grep "OCSP Response Status"
# → OCSP Response Status: successful (0x0)

# Проверка поддержки ECH (OpenSSL 4.0+)
openssl s_client -connect domain.com:443 -servername domain.com -ech 2>&1 | \
  grep "ECH"
```

### Мониторинг TLS-сессий

```bash
# Активные TLS-сессии (требует ngx_http_stub_status_module)
curl -s http://127.0.0.1/nginx_status | grep "server accepts handled requests"
# → 12345 12345 67890

# Статистика шифров из audit-лога
awk '{print $8}' /var/log/nginx/tls_audit.log | sort | uniq -c | sort -rn | head -10
# →    5432 TLS_AES_256_GCM_SHA384
# →    3211 TLS_AES_128_GCM_SHA256

# Проверка истечения сертификатов
echo | openssl s_client -connect domain.com:443 -servername domain.com 2>/dev/null | \
  openssl x509 -noout -dates
# → notBefore=Sep 22 00:00:00 2025 GMT
# → notAfter=Dec 22 23:59:59 2025 GMT
```

## Устранение неполадок

### Типичные ошибки виртуальных хостов

| Ошибка в логе / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат при `ssl_verify_client on`. | Проверьте, что клиент имеет валидный сертификат с EKU Client Auth. |
| `alert handshake failure (40)` | Клиент не передал SNI, несовместимая версия TLS или неверные шифры. | Проверьте `ssl_protocols` и `ssl_ciphers`. Убедитесь, что клиент отправляет SNI. |
| `certificate verify failed` | Ошибка в `ssl_certificate` или просроченный сертификат. | Убедитесь, что файл содержит полную цепочку (Leaf + Intermediate). Проверьте срок: `openssl x509 -in cert.pem -noout -dates`. |
| `no shared cipher` | Нет пересечения в поддерживаемых шифрах. | Добавьте AES-GCM или ChaCha20 в `ssl_ciphers`. Проверьте: `openssl ciphers -v`. |
| `ssl_stapling: no data` | Сертификат не содержит AIA (Authority Information Access). | Проверьте: `openssl x509 -in cert.pem -noout -text | grep -A1 "Authority Information Access"`. |
| `0-RTT early data rejected` | Бэкенд не обрабатывает `Early-Data` заголовок. | Добавьте `proxy_set_header Early-Data $ssl_early_data;` или отключите `ssl_early_data`. |
| `ECH decryption failed` | Отсутствует `ssl_ech_file` или DNS-записи HTTPS/SVCB не настроены. | Настройте ECH на уровне `server` и добавьте DNS-записи. |
| `shared zone "SSL" too small` | `ssl_session_cache` переполнен. | Увеличьте SIZE (например, `shared:SSL:20m`). Выполните `nginx -s reload`. |

### Проверка конфигурации после изменений

```bash
# 1. Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
systemctl reload nginx

# 3. Внешняя проверка
openssl s_client -connect domain.com:443 -servername domain.com -alpn h2 -status

# 4. Проверка HTTP/3
curl --http3 -v -I https://example.com

# 5. Проверка ECH (если включен)
openssl s_client -connect domain.com:443 -servername domain.com -ech 2>&1 | grep "ECH"
```

## Рекомендации и лучшие практики

### Чеклист безопасности виртуальных хостов (2026)

- [ ] **Протоколы:** `ssl_protocols TLSv1.2 TLSv1.3;` — TLS 1.0/1.1 отключены.
- [ ] **Шифры:** Только AEAD (AES-GCM, ChaCha20-Poly1305). Отсутствуют 3DES, RC4, DES.
- [ ] **PFS:** Включены ECDHE-шифры с гибридными кривыми (`ssl_ecdh_curve X25519MLKEM768:X25519:...`).
- [ ] **Двойной стек:** ECDSA (приоритет) + RSA (резерв) для совместимости.
- [ ] **HSTS:** `max-age=63072000; includeSubDomains; preload` для публичных сервисов.
- [ ] **Default Server:** `ssl_reject_handshake on;` для защиты от сканирования SNI.
- [ ] **0-RTT:** `ssl_early_data on;` только с обработкой `Early-Data` на бэкенде.
- [ ] **OCSP Stapling:** Включен с индивидуальным `resolver` для хоста.
- [ ] **ECH:** Настроен `ssl_ech_file` и DNS-записи HTTPS/SVCB для приватности SNI.
- [ ] **HTTP/3:** `listen 443 quic;`, `http3 on;`, `quic_retry on;`, `Alt-Svc` заголовок.
- [ ] **Версия сервера:** `server_tokens off;` скрывает версию Nginx.
- [ ] **Права доступа:** Ключи `600`, сертификаты `644`, директория с SSL — `750 root:www-data`.

### Процедуры операционной поддержки

**Ротация сертификатов:**
1. Получите новый сертификат через Certbot или внутренний CA.
2. Скопируйте файлы в `/etc/letsencrypt/live/example.com/` (или `/etc/nginx/ssl/`).
3. Выполните `nginx -t`.
4. Выполните `systemctl reload nginx`.
5. Проверьте: `openssl s_client -connect domain.com:443 -servername domain.com -status`.

**Валидация после изменений:**
```bash
# 1. Проверка синтаксиса
nginx -t

# 2. Применение
systemctl reload nginx

# 3. Логи
journalctl -u nginx --since "1 minute ago"

# 4. Audit-лог
tail -100 /var/log/nginx/tls_audit.log
```

**Откат изменений:**
```bash
# Если reload вызвал проблемы
git checkout /etc/nginx/conf.d/example.com.conf  # или восстановите из бэкапа
systemctl reload nginx
```

**Резервное копирование:**
```bash
# Бэкап конфигурации виртуальных хостов
tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Бэкап сертификатов (если не используются Let's Encrypt)
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Производительность

| Параметр | Влияние | Рекомендация |
| :--- | :--- | :--- |
| Двойной стек (ECDSA + RSA) | Более медленный handshake, но максимальная совместимость | Используйте для публичных сервисов |
| `ssl_early_data on` | Снижает TTFB на 1-RTT | Только при обработке `Early-Data` на бэкенде |
| `http2 on` | Мультиплексирование запросов | Обязателен для production |
| `http3 on` + `quic_retry on` | Улучшение производительности на мобильных сетях | Включайте для публичных сайтов |
| `ssl_stapling on` | Ускорение валидации сертификата | Обязателен с индивидуальным `resolver` |
| HSTS `preload` | Убирает первый HTTPS-запрос из цепочки | Только для стабильных публичных доменов |

### Совместимость клиентов (Baseline 2026)

| Категория | Поддержка | Рекомендация |
| :--- | :--- | :--- |
| **Современные (Chrome 125+, FF 125+)** | TLS 1.3, HTTP/3, ECH, Hybrid PQC | Полная поддержка всех функций. |
| **Apple (iOS 18+, macOS 15+)** | TLS 1.3, HTTP/3, Hybrid PQC | ECH при наличии DNS HTTPS-записей. |
| **Legacy Android (8.0 - 11.0)** | TLS 1.2 / 1.3 | Требуют ECDHE-AES-GCM шифров. |
| **Инфраструктурные (Java 11, Go 1.22+)** | TLS 1.3 | Поддерживают современный TLS, ECH может отсутствовать. |

**Важно:** TLS 1.0 и 1.1 полностью выведены из эксплуатации (RFC 8996). В Nginx 1.30+ поддержка этих протоколов может быть удалена на уровне сборки.

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура, ECH, PQC, kTLS и жизненный цикл соединения.
*   **[Глобальные параметры TLS в Nginx](./nginx_tls_global_parameters.md)** — настройка `http`-блока: шифры, сессии, OCSP, kTLS.
*   **[Конфигурация HTTP/2 и HTTP/3](../../Performance/nginx_http_versions.md)** — детальная настройка QUIC и HTTP/3.
