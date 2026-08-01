# Взаимная аутентификация клиентов (mTLS) в Angie

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — механизм безопасности, при котором не только клиент проверяет подлинность сервера, но и сервер проверяет подлинность клиента с помощью его TLS-сертификата. 

Angie расширяет классический mTLS Nginx, добавляя поддержку динамических переменных в путях к сертификатам и CRL, а также полноценную поддержку mTLS в модуле **Stream (L4)** для защиты не-HTTP трафика.

## Основные концепции

mTLS обеспечивает высокий уровень безопасности, ограничивая доступ только владельцами валидных сертификатов, выданных доверенным центром сертификации (Certificate Authority, CA). Это стандарт для защиты межсервисного взаимодействия в [микросервисных архитектурах](../../Concepts/monolith_vs_microservices.md) и высоконагруженных API.

### Предварительные требования

1. Центр сертификации (Root CA или Intermediate CA).
2. Сертификат сервера, подписанный CA.
3. Сертификат клиента, подписанный CA.
4. (Опционально) Список отозванных сертификатов (CRL) для блокировки скомпрометированных ключей.

### Ключевые директивы

| Директива | Описание |
|:----------|:---------|
| `ssl_client_certificate` | Путь к сертификату CA для проверки клиента. |
| `ssl_verify_client` | Режимы: `on`, `off`, `optional`, `optional_no_ca`. |
| `ssl_crl` | Путь к CRL. **В Angie поддерживает переменные**, что позволяет обновлять CRL без `reload`. |
| `ssl_verify_depth` | Глубина проверки цепочки (минимум 2 для Intermediate CA). |
| `ssl_certificate_cache` | (Angie-specific) Кэширование сертификатов при использовании переменных в путях. |

### Переменные клиентского сертификата

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Результат проверки (`SUCCESS`, `FAILED:reason`, `NONE`). |
| `$ssl_client_s_dn` | Distinguished Name (DN) субъекта. |
| `$ssl_client_i_dn` | Distinguished Name (DN) издателя (CA). |
| `$ssl_client_s_dn_cn` | Common Name (CN) из DN субъекта. |
| `$ssl_client_serial` | Серийный номер сертификата. |
| `$ssl_client_v_remain` | (Angie-specific) Количество дней до истечения срока действия сертификата. |
| `$ssl_client_raw_cert` | Полный текст сертификата в формате PEM (для передачи в `proxy_set_header`). |

## Практические сценарии

### Сценарий 1: Настройка PKI с использованием Easy-RSA

Easy-RSA — это удобная обертка над OpenSSL для управления собственной инфраструктурой открытых ключей (PKI).

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
# Создание CA без пароля для автоматизации
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

#### 4. Конфигурация Angie

Скопируйте файлы в `/etc/angie/ssl/` и настройте виртуальный хост:

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

    location / {
        add_header X-SSL-Client-Verify $ssl_client_verify;
        root /var/www/html;
    }
}
```

#### 5. Тестирование с curl

```bash
# С сертификатом (успех)
curl https://your.domain.com --insecure \
  --cert client.crt \
  --key client.key
```

### Сценарий 2: Использование промежуточного CA (Production)

В продуктивных средах рекомендуется использовать цепочку из корневого и промежуточного CA.

1. Подготовьте полную цепочку (`fullchain`) для сервера.
2. Установите `ssl_verify_depth 2`.

```nginx
server {
    listen 443 ssl;
    ssl_certificate /etc/angie/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    ssl_client_certificate /etc/angie/ssl/ca-chain.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;

    location / {
        proxy_pass http://backend;
        proxy_set_header X-Client-DN $ssl_client_s_dn;
    }
}
```

### Сценарий 3: mTLS в модуле Stream (L4)

Применяется для защиты соединений с базами данных (PostgreSQL, MySQL) или другими TCP-сервисами.

```nginx
stream {
    # Кэш для ускорения динамической загрузки сертификатов
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 5432 ssl; # Порт PostgreSQL с TLS
        
        ssl_certificate     /etc/angie/ssl/db-server.crt;
        ssl_certificate_key /etc/angie/ssl/db-server.key;

        # Конфигурация mTLS
        ssl_verify_client on;
        ssl_trusted_certificate /etc/angie/ssl/ca.crt;
        
        # Включение ускоренного рукопожатия TLS 1.3 (Angie-specific в Stream)
        ssl_early_data on;

        proxy_pass pg_cluster;
    }
}
```

### Сценарий 4: Динамическое обновление CRL без перезагрузки

В Angie использование переменных в `ssl_crl` заставляет сервер перечитывать файл при каждом новом соединении.

```nginx
http {
    # Путь к CRL может быть задан через переменную
    set $dynamic_crl "/etc/angie/ssl/crl.pem";

    server {
        listen 443 ssl;
        ssl_client_certificate /etc/angie/ssl/ca.crt;
        ssl_crl $dynamic_crl;
        ssl_verify_client on;
        
        # ... остальная конфигурация
    }
}
```
Это позволяет обновлять файл `crl.pem` на диске и немедленно блокировать отозванные сертификаты без выполнения `angie -s reload`.

## Дополнительная информация

### См. также

- [Настройка mTLS в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
- [Обзор возможностей Angie](./angie_overview.md)
