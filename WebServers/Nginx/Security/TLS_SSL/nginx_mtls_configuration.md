# Настройка Mutual TLS (mTLS) в Nginx и Angie

**Надёжность:** 10 (SSoT + Официальная документация Nginx 1.26 / Angie 1.12 + RFC 8446)
**Свежесть:** Июль 2026 (Актуально для Nginx 1.26+, Angie 1.12+)

## Определения

**Mutual TLS (mTLS)** — механизм взаимной аутентификации на транспортном уровне (L4/L7). В отличие от стандартного TLS, где только клиент проверяет подлинность сервера, mTLS требует от клиента также предъявить валидный сертификат, подписанный доверенным центром сертификации (CA).

Теоретические основы и процесс рукопожатия описаны в системном документе: **[mTLS в протоколе TLS](../../../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)**.

## Основные концепции

### Предварительные требования

Для реализации mTLS необходима действующая инфраструктура PKI:
1.  **Центр сертификации (CA)**: Root и/или Intermediate CA для подписи клиентских ключей. Инструкции по созданию: **[Двухуровневый CA на OpenSSL](../../../../Security/Tools/openssl_ca/two_tier/overview.md)**.
2.  **Файл цепочки CA**: Объединяет все доверенные CA в одном PEM-файле для проверки клиентов на стороне Nginx.
3.  **Клиентские сертификаты**: Выпущенные для каждого пользователя, устройства или микросервиса.

### Ключевые директивы конфигурации

| Директива | Описание | Примечание |
| :--- | :--- | :--- |
| `ssl_client_certificate` | Путь к файлу с доверенными сертификатами CA. | Список этих CA отправляется клиенту. |
| `ssl_verify_client` | Режимы: `on` (строго), `optional` (запрос без разрыва), `off`. | `optional_no_ca` — для проверки в приложении. |
| `ssl_verify_depth` | Глубина проверки цепочки сертификатов. | Минимум 2 для Intermediate CA. |
| `ssl_crl` | Путь к списку отозванных сертификатов (CRL). | В **Angie** поддерживает переменные. |
| `ssl_ocsp` | (Nginx 1.19+) Проверка статуса сертификата клиента онлайн. | Заменяет или дополняет CRL. |
| `ssl_certificate_cache` | (**Angie**) Кэширование сертификатов в памяти. | Ускоряет работу при динамических путях. |

### Переменные mTLS для логики и бэкендов

| Переменная | Описание |
| :--- | :--- |
| `$ssl_client_verify` | Статус проверки: `SUCCESS`, `FAILED:reason` или `NONE`. |
| `$ssl_client_s_dn` | Полная строка Subject DN из сертификата клиента. |
| `$ssl_client_s_dn_cn` | Common Name (CN) — например, имя пользователя или ID сервиса. |
| `$ssl_client_serial` | Серийный номер сертификата (важно для аудита). |
| `$ssl_client_v_remain` | (**Angie**) Дней до истечения срока действия сертификата. |

## Практические сценарии

### 1. Базовая настройка (Production)

Используется для защиты критических API. Рекомендуется использовать **ECDSA** ключи для повышения производительности mTLS-рукопожатий.

```nginx
server {
    listen 443 ssl;
    server_name api.secure-service.com;

    # Сертификат самого сервера (полная цепочка)
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/nginx/ssl/trusted_clients_ca.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2; # Клиент -> Intermediate -> Root

    location / {
        proxy_pass http://internal_app;
    }
}
```

### 2. Динамическая проверка отзыва (OCSP)

В 2026 году OCSP является стандартом, так как позволяет мгновенно блокировать доступ без обновления файлов CRL на диске.

```nginx
server {
    # ... базовые настройки TLS ...

    ssl_verify_client on;
    ssl_ocsp          on; # Включаем онлайн-проверку клиентов
    
    # Резолвер необходим для связи с OCSP-респондерами
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # Кэширование статусов для снижения нагрузки на CA
    ssl_ocsp_cache shared:CLIENT_OCSP:10m;
}
```

### 3. Передача метаданных сертификата в бэкенд

Позволяет приложению выполнять авторизацию на основе данных из сертификата (например, роль пользователя в CN).

```nginx
location /api/v1/ {
    # Передаем статус и идентификатор клиента
    proxy_set_header X-mTLS-Status  $ssl_client_verify;
    proxy_set_header X-mTLS-User    $ssl_client_s_dn_cn;
    proxy_set_header X-mTLS-Serial  $ssl_client_serial;

    proxy_pass http://api_backend;
}
```

### 4. Решение конфликта mTLS и Health Checks (Docker Swarm / K8s)

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

## Диагностика и устранение неисправностей

### Ошибка «400 Bad Request (No required SSL certificate was sent)»

Самая распространенная проблема. Причины:

1.  **Браузер не предлагает сертификат**:
    - Nginx отправляет клиенту список доверенных CA. Если сертификат клиента подписан Intermediate CA, которого нет в `ssl_client_certificate`, браузер скроет этот сертификат.
    - **Решение**: Объедините Root и все Intermediate CA в один файл `ssl_client_certificate`.
2.  **TLS 1.3 и Middleboxes**:
    - В TLS 1.3 запрос сертификата зашифрован. Прокси-фильтры могут его не видеть и блокировать.
    - **Решение**: Протестируйте с `ssl_protocols TLSv1.2;`.
3.  **Неполная цепочка на стороне клиента**:
    - Если клиент (например, мобильное приложение) не отправляет Intermediate CA, а на сервере только Root CA.
    - **Решение**: Используйте `ssl_trusted_certificate` для указания всей цепочки доверия для OCSP/Handshake.

### Тестирование через curl

```bash
# Проверка с явным указанием сертификата и ключа
curl -v --cert client.crt --key client.key --cacert ca.crt https://api.example.com

# Проверка через --resolve (без правки /etc/hosts)
curl -v --resolve api.example.com:443:127.0.0.1 \
     --cert client.pem --key key.pem \
     https://api.example.com/
```

## Дополнительная информация

### См. также

*   **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — базовые принципы и ECH.
*   **[Диагностика SSL/TLS сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка цепочек.
*   **[mTLS в Angie](../../../Angie/angie_client_cert_auth.md)** — специфика динамических переменных и модуля Stream.
*   **[Создание защищённого репозитория](../../Scenarios/secure_apt_repository_guide.md)** — практический кейс применения mTLS.
