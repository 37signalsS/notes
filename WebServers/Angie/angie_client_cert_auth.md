# Взаимная аутентификация клиентов (mTLS) в Angie

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — механизм безопасности, при котором не только клиент проверяет подлинность сервера, но и сервер проверяет подлинность клиента с помощью его TLS-сертификата. 

**Angie** расширяет классический mTLS Nginx, добавляя поддержку динамических переменных в путях к сертификатам и CRL, нативный модуль ACME для автоматизации выпуска сертификатов в модуле Stream, а также Certificates API для управления цепочками доверия в runtime.

## Основные концепции

mTLS обеспечивает высший уровень безопасности, ограничивая доступ только владельцами валидных сертификатов. В 2026 году, в связи с ограничениями публичных CA (Let's Encrypt и др.) на выпуск сертификатов с расширением Client Auth, mTLS практически полностью перешел на использование **Private CA** (HashiCorp Vault, Easy-RSA) и современные алгоритмы подписи (**ECDSA P-384**).

### Ключевые директивы

| Директива | Описание | Особенности Angie |
|:----------|:---------|:------------------|
| `ssl_client_certificate` | Путь к сертификату CA для проверки клиента. | Список этих CA отправляется клиенту в CertificateRequest. |
| `ssl_verify_client` | Режимы: `on`, `off`, `optional`, `optional_no_ca`. | Базовый переключатель режима проверки. |
| `ssl_crl` | Путь к списку отозванных сертификатов (CRL). | **Поддерживает переменные**, что позволяет обновлять CRL без `reload`. |
| `ssl_verify_depth` | Глубина проверки цепочки (минимум 2 для Intermediate CA). | Стандартная проверка иерархии. |
| `ssl_certificate_cache` | Кэширование сертификатов при использовании переменных. | Радикально ускоряет работу при динамических путях. |
| `ssl_ocsp` | Проверка статуса сертификата клиента онлайн. | Стандарт 2026 года для мгновенного отзыва доступа. |

### Переменные клиентского сертификата (Angie 1.12+)

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Результат проверки (`SUCCESS`, `FAILED:reason`, `NONE`). |
| `$ssl_client_s_dn` | Distinguished Name (DN) субъекта. |
| `$ssl_client_i_dn` | Distinguished Name (DN) издателя (CA). |
| `$ssl_client_s_dn_cn` | Common Name (CN) из DN субъекта. |
| `$ssl_client_serial` | Серийный номер сертификата. |
| `$ssl_client_v_remain` | Количество дней до истечения срока действия. |
| `$ssl_client_v_start` | Дата начала действия сертификата. |
| `$ssl_client_v_end` | Дата окончания действия сертификата. |
| `$ssl_client_sigalg` | Алгоритм подписи (например, `sha384WithRSAEncryption`). |
| `$ssl_client_raw_cert` | Полный текст сертификата в формате PEM. |

## Практические сценарии

### Сценарий 1: Настройка PKI с использованием Easy-RSA

Easy-RSA остается эталонным инструментом для быстрого развертывания внутреннего центра сертификации.

#### 1. Инициализация PKI

```bash
sudo apt update && sudo apt install easy-rsa
mkdir ~/easy-rsa-ca
cd ~/easy-rsa-ca
ln -s /usr/share/easy-rsa/* .
./easyrsa init-pki
```

#### 2. Создание Центра Сертификации (CA)

```bash
# Создание CA без пароля для автоматизации (в 2026 рекомендуется ECDSA)
./easyrsa build-ca nopass
```

#### 3. Генерация сертификатов

```bash
# Сертификат сервера
./easyrsa build-server-full server nopass

# Сертификат клиента
./easyrsa build-client-full client nopass

# Список отозванных сертификатов (CRL)
./easyrsa gen-crl
```

#### 4. Конфигурация виртуального хоста в Angie

```nginx
server {
    listen 443 ssl;
    server_name your.domain.com;

    ssl_certificate /etc/angie/ssl/server.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/angie/ssl/ca.crt;
    ssl_crl /etc/angie/ssl/crl.pem;
    ssl_verify_client on;
    ssl_verify_depth 2;

    location / {
        add_header X-SSL-Client-Verify $ssl_client_verify;
        add_header X-SSL-Client-S-DN $ssl_client_s_dn;
        proxy_pass http://backend;
    }
}
```

### Сценарий 2: mTLS в модуле Stream (L4) с ACME (Angie 1.10+)

Защита TCP/UDP трафика (например, PostgreSQL) с автоматизацией сертификатов.

```nginx
stream {
    # Использование встроенного ACME для внутреннего PKI
    acme_client pki_internal {
        server https://vault.internal/v1/pki/acme/directory;
        contact mailto:admin@internal.local;
    }

    server {
        listen 5432 ssl;
        
        ssl_certificate     acme:pki_internal;
        ssl_certificate_key acme:pki_internal;

        # Конфигурация mTLS
        ssl_verify_client on;
        ssl_trusted_certificate /etc/angie/ssl/ca.crt;
        
        # TLS 1.3 Early Data для производительности
        ssl_early_data on;

        proxy_pass pg_cluster;
    }
}
```

### Сценарий 3: Динамическое обновление CRL и кэширование

В Angie использование переменных в `ssl_crl` позволяет мгновенно блокировать доступ без `reload`.

```nginx
http {
    # Кэш для ускорения работы с динамическими путями
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 443 ssl;
        set $dynamic_crl "/etc/angie/ssl/crl.pem";
        
        ssl_client_certificate /etc/angie/ssl/ca.crt;
        ssl_crl $dynamic_crl;
        ssl_verify_client on;
        
        location / {
            # Проверка срока действия в логах
            access_log /var/log/angie/mtls_access.log combined if=$ssl_client_verify;
        }
    }
}
```

### Сценарий 4: Управление через Certificates API (Angie 1.12+)

Позволяет обновлять цепочки доверия программно.

```bash
# Пример обновления сертификата через API
curl -X POST -H "Content-Type: application/json" \
  --data '{"certificate": "/etc/angie/ssl/new_ca.crt"}' \
  http://127.0.0.1/api/v1/http/certificates/mtls_zone
```

## Диагностика и тестирование

### Тестирование с curl

```bash
# С сертификатом (успех)
curl https://your.domain.com --insecure \
  --cert client.crt \
  --key client.key \
  --cacert ca.crt
```

### Отладка через s_client

```bash
openssl s_client -connect your.domain.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt -debug
```

### Распространенные ошибки

1.  **400 Bad Request (No required SSL certificate was sent):**
    *   Клиент не отправил сертификат. Проверьте, что Root CA клиента добавлен в `ssl_client_certificate`.
2.  **Handshake failure (Unknown CA):**
    *   Сервер не доверяет издателю клиентского сертификата. Убедитесь в корректности цепочки.

## Дополнительная информация

### См. также

- [Настройка mTLS в Nginx (общие принципы)](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)
- [Настройка TLS в Angie (базовая конфигурация)](./angie_tls_setup.md)
- [Обзор возможностей Angie](./angie_overview.md)
- [Автоматизация PKI с HashiCorp Vault](../../Vault/guides/pki_secrets_engine.md)
