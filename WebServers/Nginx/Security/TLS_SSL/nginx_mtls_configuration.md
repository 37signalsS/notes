# Настройка Mutual TLS (mTLS) в Nginx

## Определения

**Mutual TLS (mTLS)** — механизм взаимной аутентификации, при котором и сервер, и клиент проверяют сертификаты друг друга. В Nginx это позволяет ограничить доступ к ресурсам, разрешая подключения только тем клиентам, которые предъявляют валидный сертификат, подписанный доверенным центром сертификации (CA).

Теоретические основы взаимной аутентификации описаны в системном SSoT: **[mTLS в протоколе TLS](../../../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)**.

## Базовые понятия

### Предварительные требования

Для реализации mTLS на стороне Nginx необходимо подготовить:

1. **Инфраструктуру PKI:** действующий [центр сертификации (CA)](../../../../Security/Tools/openssl_ca/single_tier/overview.md).
2. **Сертификат сервера:** подписанный вашим CA.
3. **Сертификаты клиентов:** выданные и подписанные тем же (или доверенным промежуточным) CA для каждого клиента.

### Основные директивы

| Директива | Описание |
|:----------|:---------|
| `ssl_client_certificate` | Путь к файлу с доверенными сертификатами CA для проверки клиентов. |
| `ssl_verify_client` | Включает проверку клиента (`on`, `off`, `optional`, `optional_no_ca`). |
| `ssl_crl` | Путь к списку отозванных сертификатов (CRL). |
| `ssl_verify_depth` | Глубина проверки цепочки сертификатов (по умолчанию 1). |

**Режимы `ssl_verify_client`:**

* `on`: Проверка обязательна. При отсутствии валидного сертификата соединение разрывается.
* `optional`: Сертификат запрашивается, но соединение устанавливается даже при его отсутствии (статус проверки доступен в переменной).
* `optional_no_ca`: Сертификат запрашивается, но не проверяется по цепочке CA (используется для передачи проверки приложению).

### Переменные mTLS

Nginx предоставляет данные о сертификате клиента через встроенные переменные:

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Результат проверки (`SUCCESS`, `FAILED:reason`, `NONE`). |
| `$ssl_client_s_dn` | Строка Subject DN сертификата клиента. |
| `$ssl_client_s_dn_cn` | Common Name (CN) из сертификата клиента. |
| `$ssl_client_serial` | Серийный номер сертификата. |
| `$ssl_client_i_dn` | Строка Issuer DN (кто выдал сертификат). |

## Практические сценарии

### Сценарий 1: Базовая конфигурация (Single CA)

Используется, когда все сертификаты подписаны одним корневым центром.

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Настройка mTLS
    ssl_client_certificate /etc/nginx/ssl/ca.crt;
    ssl_verify_client      on;

    location / {
        proxy_pass http://backend;
    }
}
```

### Сценарий 2: Использование промежуточного CA (Intermediate CA)

Рекомендуемый подход для рабочих сред. Требует увеличения глубины проверки.

```nginx
server {
    listen 443 ssl;
    server_name secure.example.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # Цепочка промежуточного и корневого CA
    ssl_client_certificate /etc/nginx/ssl/ca-chain.crt;
    ssl_verify_client      on;
    
    # Глубина 2: Клиент -> Intermediate -> Root
    ssl_verify_depth       2;

    location / {
        proxy_pass http://backend;
    }
}
```

### Сценарий 3: Передача данных сертификата в бэкенд

Позволяет приложению выполнять авторизацию на основе данных из сертификата.

```nginx
location / {
    proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
    proxy_set_header X-SSL-Client-DN     $ssl_client_s_dn;
    proxy_set_header X-SSL-Client-CN     $ssl_client_s_dn_cn;
    
    proxy_pass http://upstream_server;
}
```

### Сценарий 4: Исключение healthcheck из mTLS (Docker Swarm)

При `ssl_verify_client on;` nginx разрывает соединения без клиентского сертификата. Swarm healthcheck (`CMD curl http://localhost/health`) не может предъявить сертификат — проверка будет всегда падать.

**Решение:** добавить HTTP-сервер (порт 80) с `server_name localhost` и location `/health`, доступный без TLS и mTLS. HTTPS-сервер остаётся полностью защищённым.

```nginx
server {
    listen 80;
    server_name {{ nginx_domain }} localhost;

    location /health {
        return 200 "healthy\n";
        access_log off;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name {{ nginx_domain }};

    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;
    ssl_client_certificate /etc/nginx/ssl/ca.crt;
    ssl_verify_client      on;

    location / {
        proxy_pass http://app:8080;
    }
}
```

`healthcheck` в `docker-compose.yml` использует HTTP к localhost — сертификат не требуется:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost/health"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 30s
```

**Важно:** убедитесь, что контейнер curl доступен внутри образа (nginx:alpine его содержит; для дистрибутивов без curl замените на `wget -q -O /dev/null http://localhost/health`).

### Тестирование через curl

Для проверки mTLS необходимо передать клиентский сертификат и ключ.

```bash
# 1. Успешное подключение (стандартное)
curl -v --cert client.crt --key client.key --cacert ca.crt https://api.example.com

# 2. Отладка локального сервиса (без правки /etc/hosts)
# Опция --resolve позволяет сопоставить домен с IP вручную
curl -v -k --resolve bookstack.local:443:192.168.77.11 \
    --cert my_browser.crt \
    --key my_browser.key \
    https://bookstack.local/

# 3. Проверка без сертификата (ожидается 400 Bad Request или закрытие соединения)
curl -v https://api.example.com
```

## Дополнительная информация

### См. также

* [Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)
* [Инфраструктура открытых ключей (PKI)](../../../../Security/Concepts/pki_overview.md)
* [Двухуровневый CA (Intermediate CA)](../../../../Security/Tools/openssl_ca/two_tier/overview.md)
