# Конфигурация HTTP/2 и HTTP/3 в Nginx и Angie

## Определения

**HTTP/2 (Hypertext Transfer Protocol Version 2)** — вторая мажорная версия протокола HTTP (RFC 9113), разработанная для повышения производительности за счет мультиплексирования запросов и сжатия заголовков (HPACK) поверх TCP. Подробнее об эволюции протокола см. в [Истории версий HTTP](../../../Networking/Protocols/HTTP/http_versions.md).

**HTTP/3 (Hypertext Transfer Protocol Version 3)** — третья мажорная версия протокола (RFC 9114), использующая транспортный протокол QUIC вместо TCP для устранения проблемы блокировки начала очереди (Head-of-Line blocking) на транспортном уровне.

**QUIC (Quick UDP Internet Connections)** — транспортный протокол (RFC 9000) на базе UDP, объединяющий мультиплексирование потоков, контроль перегрузок и встроенное TLS 1.3 шифрование. Фундамент для HTTP/3.

**HPACK (Header Compression for HTTP/2)** — алгоритм сжатия заголовков для HTTP/2, использующий статический и динамический словари для уменьшения накладных расходов на повторяющиеся заголовки.

**QPACK (Header Compression for HTTP/3)** — алгоритм сжатия заголовков для HTTP/3, адаптированный для работы с независимыми потоками QUIC без блокировки.

**ALPN (Application-Layer Protocol Negotiation)** — расширение TLS, позволяющее клиенту и серверу согласовать используемый протокол прикладного уровня (h2, h3) непосредственно в процессе TLS-рукопожатия.

**Head-of-Line (HOL) Blocking** — задержка обработки данных из-за потери или медленной обработки первого пакета в очереди. В HTTP/2 сохраняется на уровне TCP, в HTTP/3 полностью устранена благодаря независимым потокам QUIC.

**0-RTT (Zero Round Trip Time)** — режим повторного соединения в QUIC, при котором клиент может отправлять данные в первом же пакете, не дожидаясь завершения TLS-handshake. Экономит один RTT, но создает риск replay-атак.

**Alt-Svc (Alternative Services)** — HTTP-заголовок ответа, информирующий клиент о доступных альтернативных протоколах или конечных точках (например, поддержка HTTP/3 на том же хосте).

## Основные концепции

### Архитектура обработки HTTP/2 и HTTP/3 в Nginx

Nginx обрабатывает HTTP/2 и HTTP/3 через отдельные модули, интегрированные в конвейер обработки запросов:

1. **ngx_http_v2_module** — встроен в ядро начиная с Nginx 1.25.1. Обрабатывает бинарные фреймы HTTP/2, управляет потоками (streams), реализует HPACK-сжатие заголовков и Flow Control.
2. **ngx_http_v3_module** — начиная с Nginx 1.30+ является стабильным и доступен в официальных сборках. В Angie доступен нативно с версии 1.11+. Реализует QUIC-транспорт, QPACK и управление потоками поверх UDP.
3. **ngx_http_ssl_module** — обеспечивает TLS- Handshake для HTTP/2 (через TCP) и интегрированное шифрование для HTTP/3 (QUIC).

**Принцип работы конвейера:**
- Nginx получает соединение на порт 443 (TCP для HTTP/1.1/HTTP/2, UDP для HTTP/3).
- При использовании ALPN клиент и сервер согласовывают протокол в процессе TLS-рукопожатия.
- Для HTTP/2 Nginx принимает бинарные фреймы, декодирует заголовки через HPACK и передает запрос в соответствующий обработчик (статический файл, прокси, FastCGI).
- Для HTTP/3 Nginx управляет QUIC-соединениями, обрабатывает независимые потоки и передает декодированные запросы обработчикам.
- Ответ проходит через конвейер фильтров и отправляется клиенту с учетом специфики протокола (например, Server Push для HTTP/2, 0-RTT для HTTP/3).

### Решение проблемы Head-of-Line Blocking

| Версия | Уровень блокировки | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **HTTP/1.1** | Уровень соединения | Последовательная обработка запросов | Keep-Alive, Pipeline (непригоден) |
| **HTTP/2** | Уровень TCP-пакета | Потеря одного пакета блокирует все потоки в соединении | Мультиплексирование, но TCP HoL остается |
| **HTTP/3 (QUIC)** | Устранена | Независимые потоки на уровне QUIC | Потеря пакета затрагивает только один поток |

### Поддерживаемые версии и модули (2026)

Для современных дистрибутивов минимально рекомендуемые версии:

*   **HTTP/2:**
    *   **Nginx 1.25.1+** (модуль `ngx_http_v2_module` встроен).
    *   **Angie** — любая версия с поддержкой HTTP/2.
    *   **OpenSSL 1.1.1+** (рекомендуется 3.0+ для ALPN).
*   **HTTP/3 (QUIC):**
    *   **Nginx 1.30+** (стабильная нативная поддержка через `ngx_http_v3_module`).
    *   **Angie 1.11+** (нативная поддержка HTTP/3).
    *   **OpenSSL 3.2+**, BoringSSL или QuicTLS.
    *   **Ядро Linux 5.7+** — необходимо для `quic_bpf` и `quic_gso`.
    *   **UDP 443** — порт должен быть открыт в firewall, включая промежуточные балансировщики.

**Важно:** Браузеры не поддерживают HTTP/2 без шифрования (h2c возможен только для внутренних соединений). HTTP/3 требует UDP-порт 443 и поддержки QUIC на всех промежуточных устройствах.

## Практические сценарии

### Предварительные требования

*   **Сертификаты TLS:** Действующий сертификат (ECDSA или RSA) и приватный ключ. Для HTTP/3 обязателен TLS 1.3.
*   **OpenSSL:** Версия 3.0+ для ALPN, 3.2+ для HTTP/3.
*   **Firewall/NAT:** UDP порт 443 открыт и транслируется корректно. Для HTTP/3 необходимо, чтобы промежуточные балансировщики поддерживали QUIC или передавали UDP-трафик.
*   **Ядро Linux:** 5.7+ для `quic_bpf` (сохранение сессий при reload), 5.10+ для оптимальной производительности.
*   **Пакеты:** Для Nginx из официальных репозиториев HTTP/3 может отсутствовать и требоваться сборка из исходного кода с включенным модулем `ngx_http_v3_module`. В Angie HTTP/3 доступен нативно.

### Настройка HTTP/2

В современных версиях Nginx и Angie поддержка HTTP/2 включается через директиву `http2` в блоке `listen`.

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    ssl_certificate /etc/nginx/ssl/site.crt;
    ssl_certificate_key /etc/nginx/ssl/site.key;

    # Рекомендуемые TLS-настройки для HTTP/2
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Отключить Server Push (устарел). Используйте 103 Early Hints.
    http2_push off;

    # Опционально: увеличение лимитов для защиты от HTTP/2 Flood
    # http2_max_requests 1000;
    # http2_max_concurrent_streams 128;
}
```

**Проверка:**
```bash
# Проверка заголовков и ALPN
openssl s_client -connect example.com:443 -alpn h2 -servername example.com -brief
# → ALPN protocol: h2

# Проверка через curl (если собран с HTTP/2 поддержкой)
curl --http2 -I https://example.com
# → HTTP/2 200
```

### Настройка HTTP/3 (QUIC)

Требует активации UDP-прослушивания и рекламы протокола через `Alt-Svc`.

```nginx
# В контексте main (опционально, для производительности)
# quic_bpf on;       # Требует Linux 5.7+
# quic_gso on;       # Generic Segmentation Offload

# http {
#     ... общие настройки ...
# }

server {
    # 1. TCP-слушатель для HTTP/1.1 и HTTP/2
    listen 443 ssl;
    
    # 2. UDP-слушатель для HTTP/3 (reuseport обязателен для балансировки)
    listen 443 quic reuseport;
    
    # 3. Активация HTTP/3
    http3 on;

    # 4. Реклама протокола (Alt-Svc)
    # Браузер запомнит поддержку h3 на 24 часа (ma=86400)
    add_header Alt-Svc 'h3=":443"; ma=86400' always;

    # 5. Защита от UDP-амплификации
    quic_retry on;

    # 6. Ускорение повторных соединений (0-RTT)
    # ВНИМАНИЕ: ssl_early_data делает сервер уязвимым к replay-атакам.
    # Используйте только если приложение защищено на уровне логики (Idempotency Key).
    ssl_early_data on;

    # TLS-настройки (подробнее в nginx_tls_ssl_overview.md)
    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.3;
}
```

**Проверка:**
```bash
# Проверка UDP-порта
ss -ulpn | grep :443
# → UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))

# Проверка HTTP/3 через curl (требуется curl с поддержкой h3)
curl --http3 -I https://example.com
# → HTTP/3 200

# Проверка ALPN для QUIC
openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief
# → ALPN protocol: h3
```

### Работа с бэкендами (Upstream)

*   **gRPC через HTTP/2:** Стандартный Nginx поддерживает проксирование gRPC.
    ```nginx
    location /grpc.service {
        grpc_pass grpc://backend_grpc;
    }
    ```
*   **Upstream HTTP/3 (Angie):** Angie позволяет взаимодействовать с бэкендами по HTTP/3, обеспечивая минимальные задержки внутри инфраструктуры.
    ```nginx
    location /api/ {
        proxy_http_version 3;
        proxy_pass https://backend_cluster;
    }
    ```

## Операции и команды

### Валидация конфигурации

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `nginx -t` | Проверка синтаксиса конфигурации | `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok` |
| `nginx -V 2>&1 \| grep -o 'http_v2_module'` | Проверка модуля HTTP/2 | `http_v2_module` |
| `nginx -V 2>&1 \| grep -o 'http_v3_module'` | Проверка модуля HTTP/3 | `http_v3_module` (отсутствует, если не собран) |
| `nginx -V 2>&1 \| grep -o 'built with OpenSSL [0-9.]\+'` | Версия OpenSSL | `built with OpenSSL 3.2.1` |

### Диагностика соединений

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ss -tnp \| grep :443` | TCP-соединения (HTTP/1.1, HTTP/2) | `LISTEN 0 128 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=6))` |
| `ss -ulpn \| grep :443` | UDP-соединения (HTTP/3, QUIC) | `UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))` |
| `openssl s_client -connect example.com:443 -alpn h2 -servername example.com -brief` | Проверка ALPN для HTTP/2 | `ALPN protocol: h2` |
| `openssl s_client -connect example.com:443 -alpn h3 -servername example.com -brief` | Проверка ALPN для HTTP/3 | `ALPN protocol: h3` |
| `curl --http2 -I https://example.com` | Проверка HTTP/2 | `HTTP/2 200` |
| `curl --http3 -I https://example.com` | Проверка HTTP/3 | `HTTP/3 200` |
| `curl -I -H "Alt-Used: example.com:443" https://example.com` | Проверка Alt-Svc заголовка | `Alt-Svc: h3=":443"; ma=86400` |

### Нагрузочное тестирование

```bash
# wrk с поддержкой HTTP/2
wrk -t4 -c100 -d30s -H "Accept-Encoding: gzip" https://example.com

# hey с поддержкой HTTP/3 (если собран с libcurl h3)
hey -n 1000 -c 100 --http3 https://example.com
```

### Логирование

```nginx
# Добавление полей HTTP-версии в access_log
log_format main_ext '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'alpn=$ssl_alpn protocol=$server_protocol';
```

## Устранение неполадок

### HTTP/2 не активируется

**Симптомы:** `curl -I` возвращает `HTTP/1.1 200`, хотя в конфигурации указано `http2 on`. `nginx -t` проходит успешно.

**Причины и решения:**
1.  **Клиент не поддерживает ALPN:** Проверить через `openssl s_client -connect example.com:443 -alpn h2 -servername example.com`. Если ALPN не согласуется, проверить настройки `ssl_protocols` и версию OpenSSL.
2.  **Устаревший Nginx:** Версия ниже 1.25.1 не имеет встроенного модуля HTTP/2. Обновить до 1.30+.
3.  **Конфликт модулей:** Убедиться, что `ngx_http_v2_module` загружен (встроен по умолчанию в современных сборках).

### HTTP/3 недоступен

**Симптомы:** `curl --http3` возвращает ошибку, `ss -ulpn` не показывает UDP-порт 443.

**Причины и решения:**
1.  **Модуль не собран:** Проверить `nginx -V 2>&1 | grep -o 'http_v3_module'`. Если модуль отсутствует, пересобрать Nginx с `--with-http_v3_module` или использовать Angie 1.11+.
2.  **UDP порт закрыт:** Проверить firewall (`iptables -L -n`, `nft list ruleset`) и NAT-трансляцию на балансировщике.
3.  **Отсутствует reuseport:** Для балансировки несколькими воркерами директиву `listen 443 quic reuseport;` необходимо добавлять в каждый `server` блок, использующий HTTP/3.
4.  **Ядро слишком старое:** Для `quic_bpf` требуется Linux 5.7+. Обновить ядро или отключить `quic_bpf on;`.

### Проблемы с ALPN

**Симптомы:** Клиент не получает ожидаемый протокол, соединение падает на TLS-handshake.

**Причины и решения:**
1.  **Устаревший OpenSSL:** Для ALPN требуется OpenSSL 1.1.1+. Обновить до 3.0+.
2.  **Неверный порядок ALPN:** В `ssl_conf` проверьте директиву `alpn`. Nginx управляет ALPN автоматически при использовании `listen 443 ssl http2;` и `listen 443 quic reuseport;`.
3.  **Прокси-серверы:** Промежуточные прокси (HAProxy, балансировщики) могут не поддерживать ALPN для QUIC. Проверить документацию оборудования.

### Ошибка 421 Misdirected Request

**Симптомы:** Клиент получает `421 Misdirected Request` при использовании HTTP/2 или HTTP/3.

**Причина:** Запрос направлен на сервер, который не настроен для обслуживания этого SNI/домена. Возникает при connection coalescing (объединении соединений для разных доменов на одном IP).

**Решение:**
1.  Убедиться, что для каждого `server_name` существует отдельный `server` блок с соответствующим сертификатом.
2.  Проверить, что `ssl_certificate` и `ssl_certificate_key` настроены корректно для каждого домена.
3.  Для внутренних соединений (h2c) убедиться, что `server_name` совпадает с заголовком `Host`.

### HTTP/2 Bomb / Flood

**Симптомы:** Высокая нагрузка на CPU, исчерпание памяти, отказ в обслуживании при атаке мелкими запросами с множеством потоков HTTP/2.

**Решение:**
1.  Установить лимиты на уровне `server` или `http`:
    ```nginx
    http2_max_requests 1000;
    http2_max_concurrent_streams 128;
    ```
2.  Использовать `limit_req` и `limit_conn` для ограничения частоты запросов.
3.  Настроить таймауты:
    ```nginx
    client_header_timeout 10s;
    client_body_timeout 10s;
    ```

### Проблемы с 0-RTT и replay-атаками

**Симптомы:** Повторная обработка одного и того же запроса (например, повторное создание заказа) после включения `ssl_early_data on;`.

**Решение:**
1.  Включить 0-RTT только для идемпотентных операций (GET, HEAD, OPTIONS).
2.  На уровне приложения проверять `Idempotency-Key` или `Early-Data` заголовок (`$ssl_early_data` в Nginx).
3.  Отключить `ssl_early_data on;` для эндпоинтов с побочными эффектами (POST, PUT, DELETE).

### MTU и фрагментация UDP

**Симптомы:** Нестабильная работа HTTP/3, потери пакетов, высокий jitter.

**Решение:**
1.  Убедиться, что MTU на всех интерфейсах не ниже 1280 байт (QUIC требует).
2.  Проверить, что промежуточные сети не фрагментируют UDP-пакеты ниже 1252 байт (с учетом заголовков QUIC/TLS).
3.  Использовать PMTUD (Path MTU Discovery), который встроен в QUIC.

## Лучшие практики

### Выбор протокола

| Сценарий | Рекомендация |
| :--- | :--- |
| **Публичные сайты** | HTTP/2 + HTTP/3 (QUIC) с fallback на HTTP/1.1 |
| **Внутренние API** | HTTP/2 (h2c) без шифрования, если сеть доверенная |
| **Высоконагруженные API** | HTTP/3 (QUIC) для снижения HOL-блокировки |
| **gRPC-сервисы** | HTTP/2 через `grpc_pass` |
| **Статика с CDN** | HTTP/2 или HTTP/3 на Edge, HTTP/1.1 на Origin (если CDN не поддерживает HTTP/3) |

### Безопасность

*   **Всегда использовать TLS:** Браузеры не поддерживают HTTP/2 без шифрования. Для HTTP/3 TLS 1.3 обязателен.
*   **Отключить 0-RTT для чувствительных эндпоинтов:** Использовать `ssl_early_data off;` в `location` для платежей, авторизации и других операций с побочными эффектами.
*   **Защита от UDP-флуда:** Включать `quic_retry on;` для защиты от амплификации.
*   **Лимиты HTTP/2:** Устанавливать `http2_max_requests` и `http2_max_concurrent_streams` для защиты от HTTP/2 Bomb.
*   **Сертификаты:** Использовать ECDSA для производительности и безопасности. ECDSA в 2026 году является предпочтительным стандартом.

### Производительность

*   **reuseport:** Обязательно для HTTP/3 при использовании нескольких воркеров. Позволяет ядру распределять UDP-соединения между процессами.
*   **tcp_nopush и tcp_nodelay:** Включать в конфигурации для оптимизации отправки фреймов:
    ```nginx
    tcp_nopush on;
    tcp_nodelay on;
    ```
*   **QUIC оптимизации:** Для детальной настройки `quic_bpf`, `quic_gso` и параметров ядра см. [Тюнинг производительности Nginx](nginx_performance_tuning.md).
*   **Кэширование:** Использовать `proxy_cache` для снижения нагрузки на бэкенды. HTTP/3 с 0-RTT ускоряет повторные запросы для кэшированного контента.

### Совместимость

*   **Alt-Svc:** Всегда добавлять заголовок `Alt-Svc` для информирования клиентов о поддержке HTTP/3. Использовать флаг `always` для наследования в дочерних `location`.
*   **Graceful reload:** Nginx поддерживает Graceful Reload для HTTP/2. Для HTTP/3 Graceful Reload требует ядро 5.7+ с `quic_bpf on;` для сохранения активных сессий.
*   **h2c (HTTP/2 без шифрования):** Использовать только для доверенных внутренних соединений. Включать через `listen 80 http2;` или `listen 8080 http2;` с `grpc_pass`/`proxy_pass`.

## Дополнительная информация

### Связанные темы

*   [Эволюция протокола HTTP](../../../Networking/Protocols/HTTP/http_versions.md) — детали спецификаций, HPACK, QPACK.
*   [Оптимизация TLS в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md) — настройка шифров, ALPN, сертификаты для HTTP/2 и HTTP/3.
*   [Тюнинг производительности Nginx](nginx_performance_tuning.md) — системные аспекты оптимизации, включая QUIC-оптимизации (`quic_bpf`, `quic_gso`).

### Диагностика и мониторинг

*   **Статистика:** В Nginx Plus доступна расширенная статистика HTTP/2 и HTTP/3. В Open Source используйте `stub_status` или VTS для базовых метрик.
*   **Логирование:** Добавляйте `$server_protocol` и `$ssl_alpn` в `log_format` для анализа распределения трафика по протоколам.
*   **Wireshark/tcpdump:** Для глубокой диагностики QUIC используйте фильтр `udp port 443` и декодер QUIC в Wireshark 3.0+.
