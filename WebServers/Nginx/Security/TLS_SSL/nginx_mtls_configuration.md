# Настройка Mutual TLS (mTLS) в Nginx и Angie

## Определения

**Mutual TLS (mTLS)** — механизм взаимной аутентификации на транспортном уровне (L4/L7). В отличие от стандартного TLS, где только клиент проверяет подлинность сервера, mTLS требует от клиента также предъявить валидный сертификат, подписанный доверенным центром сертификации (CA). Это обеспечивает высший уровень безопасности для межсервисного взаимодействия (M2M), критических API и административных панелей.

Теоретические основы и процесс рукопожатия описаны в системном документе: **[mTLS в протоколе TLS](../../../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)**.

## Основные концепции

### Предварительные требования

Для реализации mTLS необходима действующая инфраструктура PKI:
1.  **Центр сертификации (CA)**: Root и/или Intermediate CA для подписи клиентских ключей. Инструкции по созданию: **[Двухуровневый CA на OpenSSL](../../../../Security/Tools/openssl_ca/two_tier/overview.md)**.
2.  **Файл цепочки CA**: Объединяет все доверенные CA в одном PEM-файле для проверки клиентов на стороне Nginx.
3.  **Клиентские сертификаты**: Выпущенные для каждого пользователя, устройства или микросервиса. В 2026 году рекомендуется использовать **ECDSA** (P-256/P-384) для повышения производительности mTLS-рукопожатий.

### Ключевые директивы конфигурации

| Директива | Описание | Примечание |
| :--- | :--- | :--- |
| `ssl_client_certificate` | Путь к файлу с доверенными сертификатами CA. | Список этих CA отправляется клиенту в CertificateRequest. |
| `ssl_verify_client` | Режимы: `on` (строго), `optional` (запрос без разрыва), `off`. | `optional_no_ca` — для проверки логикой приложения. |
| `ssl_verify_depth` | Глубина проверки цепочки сертификатов. | Минимум 2, если используются Intermediate CA. |
| `ssl_crl` | Путь к списку отозванных сертификатов (CRL). | В **Angie** поддерживает переменные для динамического обновления. |
| `ssl_ocsp` | Проверка статуса сертификата клиента онлайн (OCSP). | Стандарт 2026 года для мгновенного отзыва доступа. |
| `ssl_certificate_cache` | (**Angie**) Кэширование сертификатов в памяти. | Радикально ускоряет работу при использовании динамических путей. |

### Переменные mTLS для логики и бэкендов

| Переменная | Описание |
| :--- | :--- |
| `$ssl_client_verify` | Статус проверки: `SUCCESS`, `FAILED:reason` или `NONE`. |
| `$ssl_client_s_dn` | Полная строка Subject DN из сертификата клиента. |
| `$ssl_client_s_dn_cn` | Common Name (CN) — например, имя пользователя или ID сервиса. |
| `$ssl_client_serial` | Серийный номер сертификата (важно для аудита и блокировок). |
| `$ssl_client_v_remain` | (**Angie**) Количество дней до истечения срока действия сертификата. |

## Практические сценарии

### 1. Базовая настройка HTTP API (Production)

Используется для защиты критических сервисов. Настройка TLS 1.3 обязательна для обеспечения приватности mTLS-рукопожатия (CertificateRequest шифруется). В Nginx 1.30+ обеспечивается нативная поддержка всех современных расширений.

```nginx
server {
    listen 443 ssl;
    http2  on;
    server_name api.secure-service.com;

    # Сертификат сервера
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/nginx/ssl/trusted_clients_ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    location / {
        proxy_pass http://internal_app;
        # Передача метаданных в бэкенд
        proxy_set_header X-mTLS-Status  $ssl_client_verify;
        proxy_set_header X-mTLS-User    $ssl_client_s_dn_cn;
        proxy_set_header X-mTLS-Serial  $ssl_client_serial;
    }
}
```

### 2. mTLS в модуле Stream (L4)

Применяется для защиты соединений с базами данных (PostgreSQL, MySQL, Redis) или шифрования произвольного TCP/UDP трафика.

```nginx
stream {
    server {
        listen 5432 ssl; # Порт для PostgreSQL с mTLS
        
        ssl_certificate         /etc/nginx/ssl/db_proxy.crt;
        ssl_certificate_key     /etc/nginx/ssl/db_proxy.key;
        
        ssl_client_certificate  /etc/nginx/ssl/db_clients_ca.crt;
        ssl_verify_client       on;
        
        proxy_pass postgres_backend;
    }
}
```

### 3. Динамическая проверка отзыва через OCSP

В 2026 году OCSP является стандартом, так как позволяет мгновенно блокировать доступ без обновления файлов CRL на диске.

```nginx
server {
    # ... базовые настройки TLS ...

    ssl_verify_client on;
    ssl_ocsp          on; 
    
    # Резолвер необходим для связи с OCSP-респондерами CA
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # Кэширование статусов для снижения нагрузки на CA
    ssl_ocsp_cache shared:CLIENT_OCSP:20m;
}
```

### 4. Решение конфликта mTLS и Health Checks (Docker/K8s)

При `ssl_verify_client on;` локальные проверки (например, `curl` внутри контейнера) падают, так как не имеют сертификата.

**Решение**: Выделение отдельного виртуального хоста для проверок без mTLS.

```nginx
# Внутренний порт для Health Checks (Localhost only)
server {
    listen 8080;
    server_name localhost;

    location /health {
        access_log off;
        return 200 "healthy\n";
    }
}

# Внешний HTTPS порт с mTLS
server {
    listen 443 ssl;
    # ... mTLS конфигурация ...
}
```

### 5. Динамические CRL и кэш в Angie

В **Angie** можно изменять пути к спискам отзыва через переменные, что позволяет обновлять их без `reload`.

```nginx
http {
    # Кэш для ускорения проверки сертификатов
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        set $client_crl_path "/etc/angie/ssl/current_revocations.crl";
        ssl_crl $client_crl_path; # Angie перечитает файл при изменении пути
        # ...
    }
}
```

### 6. Постквантовая криптография (PQC) в mTLS

В 2026 году при использовании **OpenSSL 3.5 LTS+** mTLS-соединения могут использовать гибридные алгоритмы (например, `X25519MLKEM768`).
- **Нюанс**: PQC-сертификаты (ML-DSA) имеют значительно больший размер, что может вызвать фрагментацию пакетов в процессе рукопожатия.
- **Рекомендация**: Используйте **ECDSA** для клиентских сертификатов до массового внедрения квантово-устойчивых PKI.

## Диагностика и устранение неисправностей

### Ошибка «400 Bad Request (No required SSL certificate was sent)»

Самая распространенная проблема. Причины:

1.  **Браузер не предлагает сертификат**:
    - Nginx отправляет клиенту список имен доверенных CA. Если сертификат клиента подписан Intermediate CA, которого нет в `ssl_client_certificate`, браузер скроет этот сертификат.
    - **Решение**: Объедините Root и все Intermediate CA в один файл `ssl_client_certificate`.
2.  **TLS 1.3 и Middleboxes**:
    - В TLS 1.3 запрос `CertificateRequest` зашифрован. Прокси-фильтры могут его не видеть и блокировать соединение.
    - **Решение**: Протестируйте с `ssl_protocols TLSv1.2;` для исключения проблем с сетевым оборудованием.
3.  **Неполная цепочка на стороне клиента**:
    - Если клиент не отправляет Intermediate CA, а на сервере только Root.
    - **Решение**: Используйте `ssl_trusted_certificate` для указания всей цепочки доверия для OCSP и корректного завершения Handshake.
4.  **Key Usage**: Сертификат клиента должен иметь расширение `Client Authentication` (OID `1.3.6.1.5.5.7.3.2`).

### Тестирование через CLI

```bash
# Проверка с явным указанием сертификата и ключа
curl -v --cert client.crt --key client.key --cacert ca.crt https://api.example.com

# Проверка через s_client с отладкой и SNI
openssl s_client -connect api.example.com:443 -cert client.crt -key client.key -CAfile ca.crt -servername api.example.com
```

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — базовые принципы, ECH и PQC.
*   **[Диагностика SSL/TLS сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка цепочек и форматов.
*   **[mTLS в Angie](../../../Angie/angie_client_cert_auth.md)** — специфика динамических переменных и модуля Stream.
*   **[Создание защищённого репозитория](../../Scenarios/secure_apt_repository_guide.md)** — практический кейс применения mTLS.
