# TLS Optimization

## Definitions

**TLS Optimization** — совокупность практик по сокращению времени установки безопасного соединения (handshake RTT), снижению вычислительной нагрузки на сервер и повышению безопасности TLS-сессий. Без оптимизации handshake может занимать до 4 RTT, что критично для мобильных пользователей.

**Ключевые цели:**

- Минимизация RTT при handshake (TLS 1.3 → 1-RTT, 0-RTT resumption)
- Снижение CPU-нагрузки (ECDHE вместо RSA-ключей, session resumption)
- Сохранение или повышение безопасности (PFS, HSTS, современные шифры)

## Basic Concepts

### TLS Versions

Использовать **TLS 1.2** и **TLS 1.3**. TLS 1.3 сокращает handshake до 1-RTT и поддерживает 0-RTT для повторных подключений. Устаревшие версии (SSLv3, TLS 1.0, TLS 1.1) — уязвимы (POODLE, BEAST) и должны быть отключены.

Подробнее о handshake и различиях версий: **[Протокол TLS](../../../Networking/Protocols/tls.md#процесс-рукопожатия-tls-handshake)**.

### Cipher Suites и Perfect Forward Secrecy

Приоритет — шифры с **ECDHE**, обеспечивающие [PFS](../../../Networking/Protocols/tls.md#perfect-forward-secrecy-pfs): каждая сессия использует уникальный эфемерный ключ, компрометация приватного ключа сервера не позволяет расшифровать прошлый трафик.

Рекомендуемые шифры для TLS 1.2: `ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384`. Актуальную конфигурацию генерирует [Mozilla TLS Configurator](https://ssl-config.mozilla.org/).

Для TLS 1.3 набор шифров стандартизирован (`TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`) и не требует ручной настройки.

### Certificates: ECDSA vs RSA

[ECDSA-сертификаты](../../../Security/Concepts/pki_overview.md) обеспечивают меньший размер и более быстрое рукопожатие. Nginx поддерживает параллельное использование: ECDSA для современных клиентов, RSA — для обратной совместимости. Практика: **[Виртуальные хосты с ECDSA + RSA](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md#использование-ec-и-rsa-сертификатов)**.

### Session Resumption

Механизмы избежания полного handshake при повторных подключениях:

| Механизм | Версия | Принцип |
| :--- | :--- | :--- |
| Session IDs | TLS 1.2 | Кэш на сервере |
| Session Tickets | TLS 1.2 | Зашифрованные параметры на клиенте |
| PSK (Pre-Shared Key) | TLS 1.3 | Тикет для 1-RTT возобновления |
| 0-RTT Early Data | TLS 1.3 | Данные в первом пакете (риск replay-атак) |

Подробнее: **[Протокол TLS](../../../Networking/Protocols/tls.md#возобновление-сессии-session-resumption)**. Конфигурация в Nginx: [кэш сессий и билеты](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md#кэширование-сессий-tls-оптимизация-производительности), [0-RTT](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md#включает-0-rtt-для-tls-13-ssl_early_data).

### HSTS (HTTP Strict Transport Security)

Заголовок `Strict-Transport-Security` обязывает браузеры всегда использовать HTTPS, предотвращая атаки понижения версии протокола.

> **Внимание:** HSTS — жёсткий кэш. Включать только после уверенной настройки HTTPS. Начинайте с малого `max-age` для тестирования. Флаг `preload` требует регистрации в [HSTS Preload List](https://hstspreload.org/). Конфигурация: [HSTS в виртуальных хостах](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md#базовая-конфигурация-https).

### OCSP Stapling

Сервер сам получает подписанный OCSP-ответ от CA и прикрепляет его к handshake. Избавляет клиента от отдельного запроса, ускоряя соединение. Подробнее: **[PKI — отзыв сертификатов](../../../Security/Concepts/pki_overview.md#механизмы-отзыва-сертификатов)**. Конфигурация в Nginx: [OCSP Stapling](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md#ocsp-stapling-ssl_stapling-ssl_stapling_verify-resolver).

### Kernel TLS (kTLS)

Перенос шифрования TLS из userspace (OpenSSL) в ядро. Даёт ~30% прирост для HTTP/1.1 при отдаче больших файлов, **несовместим с HTTP/2** (деградация 2-4×).

SSoT по kTLS: **[Оптимизация Nginx](../../../WebServers/Nginx/Performance/nginx_performance_tuning.md#kernel-tls-ktls)**.

## Practical Scenarios

### Сценарий 1: Полная TLS-конфигурация Nginx

Глобальные параметры (протоколы, шифры, кэш сессий, OCSP) — **[Глобальные параметры TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)**. Виртуальный хост (сертификаты, HSTS, HTTP→HTTPS редирект) — **[TLS в виртуальных хостах](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)**. Обзор концептов — **[Оптимальная настройка TLS/SSL](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

### Сценарий 2: High-Load оптимизация

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| `ssl_session_cache` | `shared:SSL:50m` | ~200 000 сессий |
| `keepalive_timeout` | `120s` | Меньше новых handshake |
| `keepalive_requests` | `10000` | Больше запросов на соединение |
| `ssl_buffer_size` | `8k` | Улучшает TTFB для динамического контента |

Параметры кэширования сессий описаны в [Глобальных параметрах TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md#кэширование-сессий-tls-оптимизация-производительности), `keepalive` и `ssl_buffer_size` — в том же файле.

### Сценарий 3: HTTP/2 и HTTP/3 (QUIC)

HTTP/2 и HTTP/3 сокращают количество RTT за счёт мультиплексирования. HTTP/3 объединяет QUIC + TLS 1.3, обеспечивая 1-RTT (0-RTT для повторных подключений). Подробнее: **[HTTP/2 и HTTP/3](./http2_http3.md)**, [Конфигурация HTTP в Nginx](../../../WebServers/Nginx/Performance/nginx_http_versions.md).

## Additional Information

### Tools

[SSL Labs Server Test](https://www.ssllabs.com/ssltest/) — оценка безопасности TLS-конфигурации. [Mozilla TLS Configurator](https://ssl-config.mozilla.org/) — генератор актуальной конфигурации. [SSL Certificate Diagnostics](../../../Security/Tools/ssl_certificate_diagnostics.md) — диагностика цепочки сертификатов.

### Связанные темы

Обзор производительности — [overview.md](./overview.md). Протокол TLS — [Протокол TLS](../../../Networking/Protocols/tls.md). Компрессия — [server_compression.md](./server_compression.md). Кэширование — [caching.md](./caching.md). Лучшие практики — [best_practices.md](./best_practices.md).
