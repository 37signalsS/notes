# Глобальные параметры TLS в Nginx

## Определения

**Глобальные параметры TLS** — директивы, задаваемые в блоке `http` файла `nginx.conf`, которые применяются ко всем виртуальным хостам (`server`) по умолчанию. Централизация настроек на этом уровне обеспечивает единообразную политику безопасности, упрощает аудит и снижает риск человеческой ошибки при добавлении новых сайтов.

**Область видимости директивы (Scope)** — уровень конфигурации, на котором директива может быть объявлена:
- **`http`** (глобальный): применяется ко всем `server` и `location`. Примеры: `ssl_protocols`, `ssl_ciphers`, `ssl_session_cache`, `ssl_ecdh_curve`, `ssl_stapling`, `ssl_conf_command`.
- **`server`** (уровень хоста): переопределяет глобальные значения для конкретного домена. Примеры: `ssl_certificate`, `ssl_certificate_key`, `ssl_early_data`.
- **`main`** (ядро): параметры процесса (`worker_processes`, `error_log`), не связанные напрямую с TLS.

**Разделяемая зона памяти (`shared:NAME:SIZE`)** — участок shared memory между worker процессами Nginx. Используется для кэширования сессий (`ssl_session_cache`) и ответов OCSP (`ssl_ocsp_cache`). Размер задается в мегабайтах (m) или гигабайтах (g).

**Perfect Forward Secrecy (PFS)** — свойство, при котором компрометация долгосрочного приватного ключа сервера не позволяет расшифровать прошлые сессии. В Nginx обеспечивается использованием эфемерных алгоритмов обмена ключами (ECDHE). Теория и сравнение с RSA: **[Протокол TLS — системный обзор](../../../../Networking/Protocols/tls.md)**.

**OCSP Stapling** — оптимизация проверки статуса сертификата, при которой Nginx сам запрашивает ответ от CA и передает его клиенту во время рукопожатия. Ускоряет соединение и защищает приватность, исключая прямой запрос клиента к OCSP-responder. Подробнее о протоколе OCSP: **[PKI — инфраструктура открытых ключей](../../../../Security/Concepts/pki_overview.md)**.

**kTLS (Kernel TLS)** — перенос операций симметричного шифрования (AES-GCM, ChaCha20-Poly1305) из user-space в ядро Linux (Kernel 5.10+). Позволяет использовать `sendfile()` без копирования данных между пользовательским пространством и ядром (zero-copy). Прирост производительности при отдаче статики — до 40 %. Требует включения в OpenSSL через `ssl_conf_command Options +KTLS` или автоматического определения при сборке.

**Hybrid PQC (Post-Quantum Cryptography)** — гибридный обмен ключами, сочетающий классическую эллиптическую криптографию (X25519) и постквантовые алгоритмы (ML-KEM-768, formerly Kyber). Защищает от атак «harvest now, decrypt later». В OpenSSL 3.5+ и 4.0 гибридные схемы включены по умолчанию.

## Основные концепции

### Иерархия конфигурации TLS в Nginx

TLS-параметры в Nginx наследуются сверху вниз. Понимание порядка наследования критично для управления глобальными настройками:

1. **Блок `main`** — параметры процесса, не связанные с TLS напрямую.
2. **Блок `http`** — глобальные политики по умолчанию. Применяются ко всем `server`, если не переопределены.
3. **Блок `server`** — переопределяет глобальные параметры для конкретного домена (сертификаты, `ssl_early_data`, `ssl_ech_file`).
4. **Блок `location`** — может переопределять `ssl_verify_client` в потоковых контекстах.

**Правило:** чем ближе директива к клиенту (ниже по иерархии), тем выше ее приоритет. Глобальные параметры являются базовой линией hardening; локальные могут только ослабить политику, но не усилить её относительно глобальных.

### Модель рабочих процессов и shared memory

Nginx использует многопроцессную модель: master-процесс управляет worker-процессами, каждый из которых обрабатывает соединения независимо. Без разделяемой памяти worker'ы не могли бы обмениваться состояниями TLS-сессий.

```
┌─────────────────────────────────────┐
│           master процесс            │
│  ┌───────┬───────┬───────┬───────┐ │
│  │ wrk 1 │ wrk 2 │ wrk 3 │ wrk 4 │ │
│  └───┬───┴───┬───┴───┬───┴───┬───┘ │
│      │       │       │       │     │
│      └───────┴───────┴───────┘     │
│         shared:SSL:10m (кэш)       │
└─────────────────────────────────────┘
```

**Важно для SRE:** размер shared memory задается один раз при старте Nginx. Изменение `ssl_session_cache` требует перезапуска master-процесса (`nginx -s reload`).

### Требования к окружению (2026)

Для использования всех глобальных директив, описанных в этом документе, необходимы соответствующие версии компонентов:

- **Nginx 1.30+ (Stable)** или **1.29+ (Mainline)**: поддержка TLS 1.3, нативный ECH, QUIC.
- **OpenSSL 3.0+**: базовый минимум для TLS 1.3 и kTLS.
- **OpenSSL 3.5 LTS+**: поддержка **ML-KEM-768** (Kyber) в гибридных схемах по умолчанию.
- **OpenSSL 4.0+**: необходима для нативной поддержки **ECH** (Encrypted Client Hello).
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

### Директивы управления сессиями

#### `ssl_session_cache`

Создает разделяемую зону памяти между worker процессами для хранения параметров возобновления TLS-сессий (Session ID, Session Ticket).

**Синтаксис:** `ssl_session_cache shared:NAME:SIZE | off;`

**Расчет памяти (2026):**
- `shared:SSL:10m` — ~40 000 сессий. Достаточно для большинства production-серверов.
- `shared:SSL:20m` — ~80 000 сессий (высоконагруженные порталы).
- `shared:SSL:50m` — ~200 000 сессий (CDN-edge, API-gateway).

**Таймаут:** `ssl_session_timeout` определяет, сколько секунд сессия остается валидной в кэше. Рекомендуемое значение `1d` (86400 секунд) балансирует между производительностью и памятью.

#### `ssl_session_tickets`

Реализует механизм Session Tickets (RFC 5077), при котором состояние сессии сохраняется на стороне клиента в зашифрованном виде. Устраняет необходимость в разделяемом кэше на сервере, но требует автоматической ротации ключей для сохранения PFS.

**Рекомендация:** использовать `off` в глобальном блоке, так как без автоматической ротации ключей (Nginx 1.23.2+ внутри worker'ов) билеты нарушают PFS. Кэш `ssl_session_cache` обеспечивает Comparable-производительность с контролируемым временем жизни.

**Если требуется Session Tickets:**
```nginx
# Включение с автоматической ротацией (Nginx 1.23.2+)
ssl_session_tickets on;
# Время ротации ключей (по умолчанию 6 часов)
ssl_session_ticket_lifetime 6h;
```

### Директивы протоколов и шифрования

#### `ssl_protocols`

Определяет версии TLS, разрешенные для Negotiation.

**Стандарт 2026:**
```nginx
ssl_protocols TLSv1.2 TLSv1.3;
```

**Запрещено:** TLS 1.0 и TLS 1.1 — отключены согласно RFC 8996. В Nginx 1.30+ поддержка этих протоколов может быть удалена на уровне сборки.

#### `ssl_ciphers`

Список алгоритмов шифрования для TLS 1.2. В TLS 1.3 наборы шифров (Ciphersuites) фиксированы и управляются библиотекой OpenSSL; директива `ssl_ciphers` на них не влияет.

**Рекомендация (Mozilla Modern):**
```nginx
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
            'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
            'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
```

#### `ssl_prefer_server_ciphers`

Определяет порядок выбора шифра при согласовании.
- **`off` (рекомендуется, 2026):** клиент выбирает наиболее производительный шифр (например, ChaCha20 на мобильных устройствах без AES-NI). Снижает нагрузку на CPU клиента и экономит заряд батареи.
- **`on`:** сервер принудительно выбирает первый шифр из списка. Требуется только для совместимости с устаревшими клиентами.

#### `ssl_ecdh_curve`

Задает список эллиптических кривых и гибридных схем для ECDHE.

**Стандарт 2026 (OpenSSL 3.5+):**
```nginx
ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
```

Объяснение приоритета:
1. `X25519MLKEM768` — гибридная постквантовая схема (X25519 + ML-KEM-768). Используется, если клиент поддерживает.
2. `X25519` — классическая эллиптическая кривая, быстрая и безопасная.
3. `prime256v1` (P-256) — fallback для совместимости.
4. `secp384r1` (P-384) — для сертификатов ECDSA P-384.

### Директива `ssl_conf_command`

Позволяет передавать низкоуровневые параметры напрямую в OpenSSL (требует OpenSSL 1.1.1+). Используется для функций, не имеющих собственной директивы Nginx.

```nginx
# Управление Ciphersuites TLS 1.3 (если не устраивают дефолтные)
ssl_conf_command Ciphersuites TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256;

# Принудительная приоритизация ChaCha20 (нестандартный сценарий)
ssl_conf_command Options PrioritizeChaCha;

# Включение kTLS на уровне библиотеки
ssl_conf_command Options +KTLS;

# Включение ECH (требует OpenSSL 4.0+)
ssl_conf_command EchConfig /etc/nginx/ech/example.com.config;
```

### Директива `ssl_reject_handshake`

Обрывает TLS-рукопожатие на стадии ServerHello, не отправляя сертификат. Используется для `default_server` для предотвращения утечки доменных имен сканерам.

```nginx
server {
    listen 443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}
```

**Примечание:** директива доступна в блоке `server`, но её конфигурация является частью глобальной политики защиты default server.

### Директива `ssl_stapling` (OCSP Stapling)

Включает отправку ответа OCSP клиенту во время рукопожатия.

**Глобальная конфигурация (обязательны все три строки):**
```nginx
ssl_stapling on;
ssl_stapling_verify on;
resolver 1.1.1.1 8.8.8.8 valid=300s;
resolver_timeout 5s;
```

**Почему `resolver` обязателен:** Nginx должен асинхронно запросить ответ OCSP от CA. Без DNS-резолвера stapling не работает.

**Проверка:**
```bash
openssl s_client -connect domain.com:443 -status 2>&1 | grep "OCSP Response Status"
# → OCSP Response Status: successful (0x0)
```

### Директива `ssl_early_data` (0-RTT)

Разрешает клиентам отправлять данные первого запроса вместе с ClientHello (TLS 1.3 0-RTT). **Включается на уровне `server` или `location`**, но является частью глобальной политики безопасности.

**Риск:** уязвимость к Replay-атакам (повтор транзакций).

**Защита:** на бэкенде должен проверяться заголовок `Early-Data`:
```nginx
proxy_set_header Early-Data $ssl_early_data;
```

## Практические сценарии

### Эталонная глобальная конфигурация (nginx.conf)

```nginx
http {
    # --- Протоколы и шифры ---
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers off;

    # --- Сессии (TLS 1.2 кэш, TLS 1.3 билеты выключены для PFS) ---
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # --- Обмен ключами (Hybrid PQC) ---
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;

    # --- OCSP Stapling (глобальный резолвер) ---
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # --- kTLS (ускоряет отдачу статики) ---
    ssl_buffer_size 4k;
    ssl_conf_command Options +KTLS;

    # --- Сокрытие версии сервера ---
    server_tokens off;

    # --- Default server (защита от сканирования) ---
    server {
        listen 443 ssl default_server;
        server_name _;
        ssl_reject_handshake on;
    }

    # --- Остальные server блоки наследуют параметры выше ---
}
```

### Валидация и применение конфигурации

```bash
# Проверка синтаксиса (обязательно перед reload)
sudo nginx -t

# Graceful reload без разрыва соединений
sudo systemctl reload nginx

# Проверка активных слушающих портов
sudo ss -tlpn | grep ':443'

# Проверка TLS 1.3 и шифра
openssl s_client -connect domain.com:443 -servername domain.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful
```

### Логирование TLS для аудита

Глобальный формат лога позволяет анализировать распределение версий TLS, шифров и кривых:

```nginx
log_format tls_audit '$remote_addr [$time_local] "$request" '
                     'proto:$ssl_protocol cipher:$ssl_cipher '
                     'curve:$ssl_curves reused:$ssl_session_reused '
                     'ech:$ssl_ech_status';

http {
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

### Диагностика глобальных параметров

```bash
# Проверка версии OpenSSL и доступных шифров
openssl version -a

# Список поддерживаемых TLS 1.3 Ciphersuites
openssl list -tls1.3-cipher-algorithms

# Проверка поддержки гибридных кривых (ML-KEM)
openssl ecparam -list_curves | grep -i mlkem
# → X25519MLKEM768

# Проверка поддержки kTLS в ядре
ls /proc/sys/net/ipv4/tcp_ulp
# → tls

# Проверка работы OCSP Stapling
openssl s_client -connect domain.com:443 -status 2>&1 | grep "OCSP Response Status"
# → OCSP Response Status: successful (0x0)

# Проверка сессий в разделяемой зоне
nginx -T 2>/dev/null | grep -A1 "ssl_session_cache"
# → ssl_session_cache shared:SSL:10m;
# → ssl_session_timeout 1d;
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

### Типичные ошибки глобальных параметров

| Ошибка в логе / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `SSL: error:14094410:SSL routines:sslv3 alert handshake failure` | Клиент не поддерживает ни один из шифров в `ssl_ciphers`. | Добавьте AES-GCM или ChaCha20 для совместимости. Проверьте: `openssl ciphers -v`. |
| `no shared cipher` | Пустая или некорректная строка `ssl_ciphers`. | Проверьте синтаксис и кавычки в `nginx.conf`. Выполните `nginx -t`. |
| `OCSP response: no response sent` | Отсутствует `resolver` или OCSP-responder недоступен. | Добавьте `resolver` в глобальный блок `http`. Проверьте доступность порта 80/443 на CA. |
| `ssl_stapling: no data` | Сертификат не содержит AIA (Authority Information Access). | Проверьте: `openssl x509 -in cert.pem -noout -text | grep -A1 "Authority Information Access"`. |
| `shared zone "SSL" too small` | `ssl_session_cache` переполнен. | Увеличьте SIZE (например, `shared:SSL:20m`). Выполните `nginx -s reload`. |
| `kTLS not available` | Ядро < 5.10 или OpenSSL собран без kTLS. | Обновите ядро или пересоберите OpenSSL с `enable-ktls`. |
| `ECH decryption failed` | Отсутствует `ssl_ech_file` или DNS-записи HTTPS/SVCB не настроены. | Настройте ECH на уровне `server` и добавьте DNS-записи. |
| `early data rejected` | Бэкенд не обрабатывает `Early-Data` заголовок. | Добавьте `proxy_set_header Early-Data $ssl_early_data;` или отключите `ssl_early_data`. |

### Проверка конфигурации после изменений

```bash
# 1. Проверка синтаксиса
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации
systemctl reload nginx

# 3. Внешняя проверка
openssl s_client -connect domain.com:443 -servername domain.com -alpn h2 -status

# 4. Проверка kTLS (если включен)
ss -tnp | grep :443 | grep ESTAB | head -5
# В выводе `ss` нет прямого индикатора kTLS; используйте:
nstat -s TlsExtRecvTls13 -s TlsExtRecvTls12
```

## Рекомендации и лучшие практики

### Чеклист безопасности глобальных параметров (2026)

- [ ] **Протоколы:** `ssl_protocols TLSv1.2 TLSv1.3;` — TLS 1.0/1.1 отключены.
- [ ] **Шифры:** Только AEAD (AES-GCM, ChaCha20-Poly1305). Отсутствуют 3DES, RC4, DES.
- [ ] **PFS:** Включены ECDHE-шифры с гибридными кривыми (`ssl_ecdh_curve X25519MLKEM768:X25519:...`).
- [ ] **Сессии:** `ssl_session_cache shared:SSL:10m;` настроен с учетом нагрузки.
- [ ] **Билеты сессий:** `ssl_session_tickets off;` (или настроена автоматическая ротация).
- [ ] **OCSP Stapling:** Включен на глобальном уровне с `resolver` и `resolver_timeout`.
- [ ] **kTLS:** `ssl_conf_command Options +KTLS;` для ядер >= 5.10.
- [ ] **Default Server:** `ssl_reject_handshake on;` для защиты от сканирования SNI.
- [ ] **Версия сервера:** `server_tokens off;` скрывает версию Nginx.
- [ ] **Права доступа:** Ключи `600`, сертификаты `644`, директория `/etc/nginx/ssl/` — `750 root:www-data`.
- [ ] **Мониторинг:** Настроен audit-лог с `$ssl_cipher`, `$ssl_protocol`, `$ssl_curves`.
- [ ] **Сертификаты:** Настроен автоматический renewal (Certbot/systemd timer) за 30 дней до истечения.

### Процедуры операционной поддержки

**Ротация глобальных параметров:**
1. Измените `nginx.conf` в блоке `http`.
2. Выполните `nginx -t`.
3. Выполните `systemctl reload nginx`.
4. Проверьте журнал: `journalctl -u nginx --since "1 minute ago"`.
5. Проверьте audit-лог: `tail -100 /var/log/nginx/tls_audit.log`.

**Масштабирование кэша сессий:**
- При увеличении трафика мониторьте процент попаданий в кэш через `$ssl_session_reused` в access_log.
- При попадании < 80 % увеличьте `ssl_session_cache` (например, с `10m` до `20m`).
- При переполнении зоны в логе появится `shared zone "SSL" too small` — немедленно увеличьте размер.

**Откат изменений:**
```bash
# Если reload вызвал проблемы, выполните откат
git checkout /etc/nginx/nginx.conf  # или восстановите из бэкапа
systemctl reload nginx
```

**Резервное копирование:**
```bash
# Бэкап конфигурации
tar czf /backup/nginx-conf-$(date +%F).tar.gz /etc/nginx/

# Бэкап сертификатов (если не используются Let's Encrypt)
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Производительность

| Параметр | Влияние | Рекомендация |
| :--- | :--- | :--- |
| `ssl_session_cache shared:SSL:10m` | Снижает нагрузку на CPU на 30-50 % за счет возобновления | Обязателен для production |
| `ssl_buffer_size 4k` | Ускоряет передачу первого пакета (особенно с 0-RTT) | Рекомендуется |
| `ssl_prefer_server_ciphers off` | Позволяет клиенту выбрать ChaCha20 (экономия CPU на мобильных) | Обязателен в 2026 |
| `kTLS` (`ssl_conf_command Options +KTLS`) | Zero-copy шифрование, прирост до 40 % на статике | Включайте на high-load серверах |
| `ssl_session_tickets off` | Исключает необходимость в ротации ключей, обеспечивает стабильный PFS | Рекомендуется |
| `ssl_early_data on` | Снижает TTFB на 1-RTT | Только при обработке `Early-Data` на бэкенде |

### Совместимость клиентов (Baseline 2026)

| Категория | Поддержка | Рекомендация |
| :--- | :--- | :--- |
| **Современные (Chrome 125+, FF 125+)** | TLS 1.3, HTTP/3, ECH, Hybrid PQC | Полная поддержка всех функций. |
| **Apple (iOS 18+, macOS 15+)** | TLS 1.3, HTTP/3, Hybrid PQC | ECH при наличии DNS HTTPS-записей. |
| **Legacy Android (8.0 - 11.0)** | TLS 1.2 / 1.3 | Требуют ECDHE-AES-GCM шифров. |
| **Инфраструктурные (Java 11, Go 1.22+)** | TLS 1.3 | Поддерживают современный TLS, ECH может отсутствовать. |

**Важно:** TLS 1.0 и 1.1 полностью выведены из эксплуатации. В Nginx 1.30+ поддержка этих протоколов может быть удалена на уровне сборки.

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура, жизненный цикл соединения, kTLS, ECH и PQC.
*   **[Конфигурация виртуальных хостов TLS](./nginx_tls_virtual_host_config.md)** — настройка `server`-блоков, ECH, 0-RTT и QUIC.
*   **[Диагностика TLS/SSL в Nginx](./nginx_tls_troubleshooting_and_compatibility.md)** — отладка ошибок рукопожатия и матрица совместимости.
