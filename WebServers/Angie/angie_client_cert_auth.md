# Взаимная аутентификация клиентов (mTLS) в Angie

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — механизм безопасности, при котором не только клиент проверяет подлинность сервера, но и сервер проверяет подлинность клиента с помощью его TLS-сертификата.

## Основные концепции

mTLS обеспечивает высокий уровень безопасности, ограничивая доступ только владельцами валидных сертификатов, выданных доверенным центром сертификации (Certificate Authority, CA). Это стандарт для защиты межсервисного взаимодействия в [микросервисных архитектурах](../../Concepts/monolith_vs_microservices.md).

Поскольку Angie полностью совместим с Nginx, механизмы и директивы настройки mTLS идентичны. Подробное описание теоретических основ и всех доступных директив приведено в [руководстве по mTLS в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md).

### Предварительные требования

1. Центр сертификации (Root CA или Intermediate CA).
2. Сертификат сервера, подписанный CA.
3. Сертификат клиента, подписанный CA.

### Ключевые директивы

| Директива | Описание |
|:----------|:---------|
| `ssl_client_certificate` | Путь к сертификату CA для проверки клиента. |
| `ssl_verify_client` | Режимы: `on`, `off`, `optional`, `optional_no_ca`. |
| `ssl_crl` | Путь к списку отозванных сертификатов. |
| `ssl_verify_depth` | Глубина проверки цепочки (минимум 2 для Intermediate CA). |

### Переменные клиентского сертификата

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Результат проверки (`SUCCESS`, `FAILED:reason`, `NONE`). |
| `$ssl_client_s_dn` | Distinguished Name (DN) субъекта. |
| `$ssl_client_s_dn_cn` | Common Name (CN) из DN субъекта. |
| `$ssl_client_serial` | Серийный номер сертификата. |

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

## Дополнительная информация

### См. также

- [Настройка mTLS в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md) — детальное описание директив и общей теории
- [Обзор Angie](./angie_overview.md) — базовые возможности веб-сервера
- [PKI Overview](../../Security/Concepts/pki_overview.md) — основы инфраструктуры открытых ключей
