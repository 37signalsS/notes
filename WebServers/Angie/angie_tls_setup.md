# Настройка TLS в Angie

## Определения

**Настройка TLS в Angie** — процесс конфигурации протоколов TLS (Transport Layer Security) и QUIC для обеспечения безопасности передачи данных (конфиденциальность, целостность и аутентификация).

Angie, являясь современным форком Nginx, не только поддерживает стандартные механизмы шифрования, но и предоставляет встроенные инструменты для упрощения эксплуатации: нативный HTTP/3, автоматизацию сертификатов (модуль ACME) и динамическое управление параметрами SSL без перезагрузки сервера.

Общие принципы TLS/SSL, шифры, HSTS и OCSP Stapling описаны в базовом документе:
> **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**

## Базовые концепции

### Совместимость с Nginx

Angie сохраняет полную обратную совместимость с директивами Nginx. Общие рекомендации по выбору шифров (ciphers), настройке HSTS и OCSP Stapling являются общими для обоих серверов.

### Ключевые преимущества Angie в TLS

*   **Встроенный ACME:** Автоматическое получение и продление сертификатов (Let's Encrypt и др.) средствами самого сервера (модуль `acme`).
*   **Динамическая загрузка:** Поддержка переменных в директивах `ssl_certificate` и `ssl_certificate_key` (Angie 1.3.0+), что позволяет загружать сертификаты «на лету» на основе имени хоста.
*   **Кэширование сертификатов:** Директива `ssl_certificate_cache` (Angie 1.4.0+) ускоряет работу при использовании переменных в путях к сертификатам.
*   **Нативный HTTP/3 (QUIC):** Реализация встроена в ядро и не требует сборки внешних модулей или использования экспериментальных веток.
*   **Автоматизация тикетов сессий:** Ротация ключей `ssl_session_tickets` происходит автоматически между всеми рабочими процессами без необходимости внешних скриптов.
*   **Переменные в SSL-директивах:** Директивы `ssl_crl` и `ssl_ocsp` поддерживают переменные, позволяя менять списки отзыва и параметры проверки без `reload`.
*   **Kernel TLS (kTLS):** Перенос операций шифрования в ядро ОС (Linux 5.10+, OpenSSL 3.0+).
*   **QUIC eBPF:** Поддержка `quic_bpf` для стабильного HTTP/3 при `reload` без разрывов соединений.

### Архитектура TLS в Angie

Angie наследует событийно-ориентированную многопроцессную архитектуру (master и worker процессы). TLS-операции выполняются в контексте воркеров, что позволяет эффективно использовать многопроцессорность (SMP) иNUMA-узлы.

**Жизненный цикл TLS-соединения:**
1. Клиент инициирует TCP-соединение (или UDP для QUIC).
2. Angie принимает соединение на `listen 443 ssl` (или `listen 443 quic`).
3. Выполняется TLS-рукопожатие (ClientHello/ServerHello).
4. При использовании ACME — проверяется актуальность сертификата, при необходимости запускается обновление.
5. Устанавливается сессионный ключ (с поддержкой 0-RTT для TLS 1.3).
6. Данные передаются с шифрованием (в user-space или через kTLS).

## Практические сценарии

### Сценарий 1: Настройка HTTP/3 (QUIC)

Для работы HTTP/3 необходимо открыть порт по протоколу UDP и анонсировать поддержку через заголовок `Alt-Svc`.

```nginx
server {
    # Порт 443 для TCP (HTTP/1.1, HTTP/2) и UDP (HTTP/3)
    listen 443 ssl;
    listen 443 quic reuseport;

    server_name example.com;

    ssl_certificate     /etc/angie/ssl/cert.crt;
    ssl_certificate_key /etc/angie/ssl/cert.key;

    # Анонс поддержки HTTP/3 для клиентов
    add_header Alt-Svc 'h3=":443"; ma=86400';

    # Оптимизация: использование GSO (Generic Segmentation Offload) для QUIC
    quic_gso on;

    # Защита от UDP-спуфинга
    quic_retry on;

    # Стабилизация соединений при reload
    quic_bpf on;
}
```
→ Подробнее: **[Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../Nginx/Performance/nginx_http_versions.md)**

### Сценарий 2: Динамические сертификаты и кэширование

Используется в инфраструктурах с тысячами доменов, чтобы не описывать каждый `server` блок отдельно.

```nginx
http {
    # Настройка кэша для динамических сертификатов (Angie 1.4.0+)
    # Хранит до 1000 сертификатов в памяти, очистка через 10 минут простоя
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 443 ssl;
        server_name *.example.com;

        # Загрузка сертификата по имени хоста (Angie 1.3.0+)
        ssl_certificate     /etc/angie/ssl/$ssl_server_name.crt;
        ssl_certificate_key /etc/angie/ssl/$ssl_server_name.key;
    }
}
```

### Сценарий 3: Автоматизация через ACME (Quick Start)

Встроенный клиент для Let's Encrypt. Исключает необходимость в Certbot.

```nginx
http {
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    acme_client letsencrypt {
        directory "https://acme-v02.api.letsencrypt.org/directory";
    }

    server {
        listen 443 ssl;
        server_name app.example.com;

        # Использование ACME-сертификатов
        acme letsencrypt;
        ssl_certificate     $acme_cert_letsencrypt;
        ssl_certificate_key $acme_cert_key_letsencrypt;
    }
}
```
→ Подробнее: **[Модуль ACME в Angie: полная конфигурация](./angie_acme_module.md)**

### Сценарий 4: Двухстековые сертификаты (RSA + ECDSA)

Обеспечивает совместимость со старыми клиентами (RSA) и высокую скорость для новых (ECDSA).

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    # RSA
    ssl_certificate     /etc/angie/ssl/example.com.rsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.rsa.key;

    # ECDSA (приоритет в современных браузерах)
    ssl_certificate     /etc/angie/ssl/example.com.ecdsa.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.ecdsa.key;

    ssl_protocols TLSv1.2 TLSv1.3;
}
```

### Сценарий 5: Оптимизация через Kernel TLS (kTLS)

Снижает нагрузку на CPU за счет переноса операций шифрования в ядро ОС. Требует OpenSSL 3.0+ и поддержки в ядре (`modprobe tls`).

```nginx
http {
    # Включение kTLS через конфигурацию OpenSSL
    ssl_conf_command Options +KTLS;

    server {
        listen 443 ssl;
        sendfile on; # kTLS работает в связке с sendfile

        ssl_certificate     /etc/angie/ssl/cert.crt;
        ssl_certificate_key /etc/angie/ssl/cert.key;
    }
}
```

### Сценарий 6: Оптимизация производительности TLS и HTTP/2/3

Три ключевых рычага на клиентской стороне соединения: параметры DH, переиспользование сессий и протокольные возможности (0-RTT/HTTP-версии).

#### ssl_dhparam — параметры Диффи-Хеллмана

Для классических (не ECDHE) cipher suite требуется общий параметр DH. Сгенерируйте один раз (реюзабельный рекорд):

```bash
# 2048 бит достаточно (4096 — выше совместимость на старых клиентах, но медленнее handshake)
openssl dhparam -out /etc/angie/ssl/dhparam.pem 2048
# → Generating DH parameters, 2048 bit long safe prime, ... done
```

```nginx
server {
    listen 443 ssl;
    ssl_dhparam /etc/angie/ssl/dhparam.pem;
}
```

#### Переиспользование сессий TLS

Ускоряет повторный handshake за счёт кэша сессий и session tickets:

```nginx
server {
    listen 443 ssl http2;

    ssl_session_cache shared:SSL:16m;        # ~16k сессий; минимум 1m на ~1k RPS handshake
    ssl_session_timeout 1d;
    ssl_session_tickets on;                  # RFC 5077 — без серверной памяти
    ssl_session_ticket_key /etc/angie/ssl/ticket.key;  # один ключ на кластер (для 100% reuse)
}
```

Для кластеров без общих ticket-ключей resume через серверный кэш не работает между нодами — генерируйте и развозите общий `ticket.key` (параметры `ssl_session_ticket_key` первого и второго поколения).

#### 0-RTT Early Data (TLS 1.3) в Angie

Angie поддерживает TLS 1.3 Early Data для HTTP и stream-модулей:

```nginx
server {
    listen 443 ssl http2;
    ssl_early_data on;

    # Защита от replay: ограничить тело и время при валидации
    limit_req_zone $ssl_server_name zone=early:10m rate=10r/s;

    location / {
        # Запросы с Early Data передаются как есть; приложение должно быть
        # идемпотентно или принимать повторные (replay-безопасность)
        proxy_set_header X-Early-Data $ssl_early_data;
    }
}
```

**Предупреждение:** 0-RTT-данные уязвимы к replay. Включайте только если приложение идемпотентно обрабатывает повторы (типично — GET/предзагрузка), иначе злоумышленник может повторить запрос.

#### Общая конфигурация TLS-плюс HTTP-протоколов

```nginx
server {
    listen 443 ssl http2 reuseport;
    listen 443 quic reuseport;
    http3 on;

    keepalive_timeout 65s;
    keepalive_requests 1000;
}
```

Рекомендации: `http2_max_concurrent_streams` (для входящих потоков), для HTTP/3 — `quic_gso on`/`quic_retry on` (защита от UDP-спуфинга). Общий рецепт оптимизации веб-производительности — [TLS-оптимизация (Concepts)](../Concepts/web_performance/tls_optimization.md) и [HTTP/2 и HTTP/3 (Concepts)](../Concepts/web_performance/http2_http3.md).

#### Проверка

```bash
# Параметры DH на реальном сервере
openssl s_client -connect example.com:443 -cipher 'DHE-RSA-AES256-SHA' -tlsextdebug < /dev/null 2>&1 | grep 'DH'
# Для ECDHE: openssl s_client -connect example.com:443 < /dev/null | head

# 0-RTT раннее данные (curl 8.x)
curl --early-data /tmp/file --include https://example.com/
```

## Операции и команды

### Проверка конфигурации

```bash
# Проверка синтаксиса
sudo angie -t
# → syntax is ok

# Проверка конфигурации с тестовым loaded сертификатами
sudo angie -T
# → показывает загруженные конфиги и сертификаты
```

### Применение изменений

```bash
# Перезагрузка конфигурации (zero downtime)
sudo angie -s reload

# Перезапуск worker процессов
sudo angie -s reopen

# Остановка сервера
sudo angie -s stop

# Принудительная остановка
sudo angie -s quit
```

### Диагностика TLS-соединений

```bash
# Тестирование handshake и цепочки сертификатов
openssl s_client -connect example.com:443 -servername example.com -showcerts
# → показывает полную цепочку и используемый cipher

# Проверка конкретного cipher
openssl s_client -connect example.com:443 -cipher ECDHE-ECDSA-AES256-GCM-SHA384

# Проверка поддержки TLS 1.3
openssl s_client -connect example.com:443 -tls1_3

# Экспорт сертификата в PEM
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -outform PEM > server.pem

# Проверка срока действия сертификата
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates
# → notBefore=...
# → notAfter=...
```

### Управление ACME

```bash
# Проверка статуса ACME через API
curl -s http://127.0.0.1/api/v1/http/acme/ | jq .

# Принудительное обновление сертификата (удаление файлов + reload)
sudo rm -f /var/lib/angie/acme/letsencrypt/*
sudo angie -s reload

# Просмотр логов ACME
sudo tail -f /var/log/angie/error.log | grep -i acme
# → [acme] certificate obtained for example.com
# → [acme] certificate renewed for example.com
```

### Мониторинг TLS через API

```bash
# Получение статистики по SSL-соединениям
curl -s http://127.0.0.1/api/v1/http/ssl/ | jq .

# Проверка поддерживаемых протоколов и шифров
curl -s http://127.0.0.1/api/v1/http/ssl/ciphers | jq .

# Статус OCSP Stapling
curl -s http://127.0.0.1/api/v1/http/ssl/ocsp/ | jq .
```

## Устранение неисправностей

### Ошибки handshake

**Симптом:** `SSL_do_handshake() failed (SSL: error:14094410:SSL routines:ssl3_read_bytes:sslv3 alert handshake failure)`

**Причины и решения:**
1. **Несовместимость cipher suites:**
   ```bash
   # Диагностика поддерживаемых шифров клиентом
   openssl s_client -connect example.com:443 -cipher ALL
   # Проверка конфигурации Angie
   sudo angie -T | grep ssl_ciphers
   ```
2. **Устаревший TLS 1.0/1.1:** Angie по умолчанию использует TLS 1.2/1.3. Проверьте `ssl_protocols`.
3. **Проблемы с SNI:** Убедитесь что `server_name` совпадает с `ssl_certificate` или используются переменные.

### Проблемы с сертификатами

**Симптом:** `certificate verify failed (SSL: error:14090086:SSL routines:ssl3_get_server_certificate:certificate verify failed)`

**Диагностика:**
```bash
# Проверка цепочки сертификатов
openssl s_client -connect example.com:443 -servername example.com -showcerts -CAfile /etc/angie/ssl/ca.crt

# Проверка срока действия
echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates

# Проверка формата (должен быть PEM)
file /etc/angie/ssl/cert.crt
# → cert.crt: PEM certificate
```

**Частые причины:**
- Сертификат и ключ не соответствуют друг другу.
- Отсутствует промежуточный сертификат (full chain).
- Неправильные права доступа: `600` для ключа, `644` для сертификата.
- `ssl_certificate_cache` кэширует старый невалидный сертификат (сброс через `sudo angie -s stop && sudo rm -rf /var/cache/angie/ssl/*`).

### Ошибки ACME

**Симптом:** `[acme] challenge failed for example.com`

**Диагностика:**
```bash
# Проверка доступности директории ACME
curl -I https://acme-v02.api.letsencrypt.org/directory
# → HTTP/2 200

# Проверка DNS
dig +short example.com
dig +short _acme-challenge.example.com

# Проверка порта 80 (HTTP-01)
sudo ss -tlnp | grep :80
curl -s http://example.com/.well-known/acme-challenge/test
```

**Решения:**
- Для HTTP-01: убедитесь что порт 80 доступен из интернета.
- Для DNS-01: проверьте delegation `_acme-challenge` на NS сервер Angie.
- Rate limits: используйте staging окружение для тестов (`directory https://acme-staging-v02.api.letsencrypt.org/directory`).

### Проблемы с HTTP/3 и QUIC

**Симптом:** Клиенты не подключаются по HTTP/3, ошибки в логах `quic` или `http3`

**Диагностика:**
```bash
# Проверка доступности UDP порта
sudo ss -u lnp | grep :443
# → UNCONN 0 0 *:quic *:* (правильно)

# Проверка логов QUIC
sudo journalctl -u angie -f | grep -i quic
# → [quic] connection established

# Тестирование curl с HTTP/3
curl --http3-only https://example.com -I
# → HTTP/3 200
```

**Решения:**
- Убедитесь что `quic_retry on` включен (защита от UDP-спуфинга).
- Проверьте firewall: `sudo nft list ruleset | grep 443 udp`.
- Для стабильности добавьте `quic_bpf on` (Angie 1.12+).
- Отключите GSO если есть проблемы с фрагментацией: `quic_gso off`.

### Проблемы с kTLS

**Симптом:** `ktls: error:1408A0C1:SSL routines:ssl3_get_client_hello:no shared cipher`

**Диагностика:**
```bash
# Проверка поддержки kTLS в ядре
ls /proc/sys/net/core/tls_enabled
# → 1 (включено)

# Проверка загруженных TLS версий
sudo sysctl net.core.tls_enabled
# → net.core.tls_enabled = 1

# Проверка OpenSSL
openssl list -providers
# → base (правило по умолчанию)
```

**Решения:**
- Убедитесь что используется OpenSSL 3.0+: `openssl version`.
- Проверьте `ssl_conf_command Options +KTLS;` в конфигурации.
- Для отладки временно отключите kTLS и проверьте performance diff.

### Логирование SSL-ключей

Для анализа зашифрованного трафика Angie поддерживает запись SSL-ключей сессий:

```nginx
http {
    ssl_keylog_file /var/log/angie/sslkeys.log;
}
```

**Безопасность:** Файл содержит секретные ключи сессий. Права доступа: `600`, доступ только для `root` и `angie`.

## Лучшие практики

### Безопасность

1. **Протоколы:**
   ```nginx
   ssl_protocols TLSv1.2 TLSv1.3;
   ```
   Отключите TLS 1.0/1.1 — они устарели и небезопасны.

2. **Шифры:**
   ```nginx
   ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
   ssl_conf_command Ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256;
   ssl_conf_command Options +KTLS;
   ```
   → Смотрите: **[Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)**

3. **HSTS:**
   ```nginx
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
   ```
   Включите `preload` только после тестирования и регистрации в [hstspreload.org](https://hstspreload.org).

4. **OCSP Stapling:**
   ```nginx
   ssl_stapling on;
   ssl_stapling_verify on;
   resolver 1.1.1.1 8.8.8.8 valid=300s;
   ```
   Снижает задержку проверки статуса сертификата и защищает приватность.

5. **mTLS для внутренних сервисов:**
   Используйте взаимную аутентификацию для защиты API и внутренних endpoints.
   → Смотрите: **[mTLS в Angie](./angie_client_cert_auth.md)**

### Производительность

1. **kTLS для статики:**
   ```nginx
   sendfile on;
   tcp_nopush on;
   ssl_conf_command Options +KTLS;
   ```
   Прирост до 40% при отдаче статики.

2. **Кэширование сертификатов:**
   ```nginx
   ssl_certificate_cache max=2000 inactive=30m;
   ```
   Обязательно для динамических хостов.

3. **Сессии TLS:**
   ```nginx
   ssl_session_cache shared:SSL:10m;
   ssl_session_timeout 1d;
   ssl_session_tickets off; # или on для автоматической ротации
   ```

4. **QUIC оптимизации:**
   ```nginx
   quic_gso on;
   quic_bpf on;
   http3_max_concurrent_streams 128;
   ```

### Управление сертификатами

1. **Используйте встроенный ACME** вместо Certbot или внешних скриптов.
2. **Мониторинг сроков действия:**
   ```bash
   # Скрипт для мониторинга (cron)
   curl -s http://127.0.0.1/api/v1/http/acme/ | jq '.certs[] | {domain: .domain, expires: .expires}' > /tmp/acme_status.txt
   ```
3. **Резервное копирование:**
   ```bash
   # Ежедневное копирование ACME данных
   sudo tar -czf /backup/angie-acme-$(date +%Y%m%d).tar.gz /var/lib/angie/acme/
   ```
4. **Staging окружение:** Используйте Let's Encrypt staging для тестов, чтобы не получить rate limit.

### Логирование

```nginx
log_format tls_detail '$remote_addr - $remote_user [$time_local] '
                     '"$request" $status $body_bytes_sent '
                     'ssl_protocol=$ssl_protocol ssl_cipher=$ssl_cipher '
                     'ssl_curve=$ssl_curve session_reused=$ssl_session_reused';

access_log /var/log/angie/tls_access.log tls_detail;
```

## Дополнительная информация

### Мониторинг TLS

Angie предоставляет расширенные переменные для мониторинга состояния соединений, которые можно использовать в `log_format`:
*   `$ssl_protocol` — используемый протокол (например, TLSv1.3).
*   `$ssl_cipher` — используемый шифр.
*   `$ssl_curve` — выбранная эллиптическая кривая.
*   `$ssl_session_reused` — статус повторного использования сессии (`r` — reused, `.` — new).
*   `$ssl_server_name` — имя сервера, запрошенное через SNI.
*   `$ssl_early_data` — статус 0-RTT данных (`1` — использованы, `.` — нет).
*   `$ssl_keylog_file` — путь к файлу с ключами сессий (если включен).

### Рекомендации по безопасности

Для проверки качества настройки TLS рекомендуется использовать внешние сканеры (SSL Labs) или утилиту `testssl.sh`. На 2026 год стандартом является отказ от TLS 1.0/1.1 и использование только TLS 1.2 и 1.3.

```bash
# Быстрая проверка утилитой testssl.sh
testssl.sh --fast example.com

# Проверка на уязвимости
openssl s_client -connect example.com:443 -servername example.com -tlsextdebug 2>/dev/null | grep -i "renegotiation\|compression\|fallback"
```

### Откат изменений

При проблемах с TLS конфигурацией:
1. Сохраните рабочий конфиг: `sudo cp /etc/angie/angie.conf /etc/angie/angie.conf.bak`.
2. Восстановите предыдущую версию: `sudo cp /etc/angie/angie.conf.bak /etc/angie/angie.conf`.
3. Проверьте конфигурацию: `sudo angie -t`.
4. Примените: `sudo angie -s reload`.

## См. также

*   **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — базовые принципы, ECH и PQC.
*   **[Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)** — усиление защиты, cipher suites, HSTS.
*   **[Виртуальные хосты TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — базовая настройка listen 443.
*   **[Диагностика и совместимость TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — типичные ошибки handshake.
*   **[Диагностика SSL/TLS сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка цепочек и форматов.
*   **[Взаимная аутентификация (mTLS) в Angie](./angie_client_cert_auth.md)**
*   **[Модуль ACME в Angie](./angie_acme_module.md)**
*   **[DNS over HTTPS (DoH) в Angie](./angie_doh_module.md)**
*   **[Диагностика DoS-защиты в Angie](./High_Load/dos_protection.md)** — QUIC и HTTP/3 flood защита.
*   **[Конфигурация HTTP/2 и HTTP/3 (Nginx и Angie)](../Nginx/Performance/nginx_http_versions.md)** — встроенная поддержка HTTP/2, QUIC и 0-RTT.
*   **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — security-заголовки, CORS, защита от request smuggling.
