# SSL/TLS Termination: паттерны и production-сценарии

## Определения

**SSL/TLS Termination (Offloading)** — процесс завершения (расшифровки) TLS-соединения на балансировщике/проксии, после чего трафик пересылается на бэкенд в открытом виде (HTTP) или с новым TLS-соединением. Позволяет централизованно управлять сертификатами, снижает CPU-нагрузку на бэкендах и упрощает отладку.

**Edge Termination** — TLS завершается на внешнем балансировщике (CDN, cloud LB, HAProxy перед DMZ). Клиент ↔ Edge = TLS, Edge ↔ Backend = HTTP.

**Re-encryption (Dual TLS)** — Edge завершает TLS, расшифровывает, затем заново шифрует трафик перед отправкой на бэкенд. Клиент ↔ Edge = TLS, Edge ↔ Backend = TLS.

**Passthrough (TLS Passthrough)** — TLS не завершается на прокси. Трафик пробрасывается напрямую бэкенду. Бэкенд сам терминирует TLS.

**mTLS (Mutual TLS)** — двухсторонняя аутентификация: и клиент, и сервер представляют сертификаты. Используется для service-to-service шифрования.

## Теоретический блок

### Архитектурные паттерны

```
Паттерн 1: Edge Termination (самый распространённый)
┌────────┐     TLS      ┌─────────┐    HTTP     ┌─────────┐
│ Client │ ──────────── │ HAProxy │ ────────── │ Backend │
└────────┘              │ / Nginx │             └─────────┘
                        └─────────┘

Паттерн 2: Re-encryption (high security)
┌────────┐     TLS      ┌─────────┐    TLS     ┌─────────┐
│ Client │ ──────────── │ HAProxy │ ────────── │ Backend │
└────────┘              │ / Nginx │  (новый)   └─────────┘
                        └─────────┘

Паттерн 3: Passthrough (backend терминирует)
┌────────┐     TLS      ┌─────────┐    TLS     ┌─────────┐
│ Client │ ──────────── │ HAProxy │ ────────── │ Backend │
└────────┘              │(L4 only)│  (свой     └─────────┘
                        └─────────┘  сертификат)

Паттерн 4: SPA (Single Page Application)
┌────────┐     TLS      ┌─────────┐  ┌─────────┐
│ Client │ ──────────── │   CDN   │  │ Backend │
└────────┘              │(Edge TLS)│  │ (HTTP)  │
                        └─────────┘  └─────────┘
```

### Выбор паттерна

| Паттерн | Когда использовать | Безопасность | CPU-нагрузка на бэкенде |
|:---|:---|:---|:---|
| **Edge Termination** | Public-facing сервисы, CDN | Средняя ( plaintext внутри) | Минимальная |
| **Re-encryption** | PCI DSS,金融服务, healthcare | Высокая (шифрование end-to-end) | Высокая (двойной TLS) |
| **Passthrough** | Бэкенд с собственными сертификатами, gRPC | Высокая | Максимальная |
| **mTLS** | Service mesh, microservices | Максимальная | Высокая |

### Сертификаты: management at scale

| Подход | Инструмент | Сценарий |
|:---|:---|:---|
| **Ручное управление** | OpenSSL | Мало серверов, внутренние сервисы |
| **ACME (Let's Encrypt)** | certbot, acme.sh | Public HTTPS, автоматическое обновление |
| **Внутренний CA** |step-ca, HashiCorp Vault | Внутренние сервисы, mTLS |
| **Service mesh** | Istio, Linkerd | Kubernetes, service-to-service mTLS |

### Ключевые концепции

**SNI (Server Name Indication)** — расширение TLS, позволяющее серверу выбрать правильный сертификат до завершения handshake. Критично для хостинга нескольких доменов на одном IP.

**OCSP Stapling** — сервер.periodически запрашивает статус сертификата у CA и "стаплит" (приклеивает) ответ к TLS handshake. Клиенту не нужно обращаться к OCSP-серверу, что ускоряет соединение и защищает от блокировки OCSP.

**Certificate Pinning** — привязка клиента к конкретному сертификату/CA. Защита от compromised CA. Рискованно: при утечке ключа нужен немедленный revocation.

**HSTS (HTTP Strict Transport Security)** — сервер отправляет заголовок `Strict-Transport-Security`, заставляя браузер использовать только HTTPS в будущем.

## Практические сценарии

### HAProxy: Edge Termination

```haproxy
global
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets
    tune.ssl.default-dh-param 2048

frontend https_edge
    bind *:443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
    bind *:80
    mode http

    # Redirect HTTP → HTTPS
    http-request redirect scheme https unless { ssl_fc }

    # HSTS (1 год)
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"

    # Передача реального IP
    option forwardfor

    default_backend web_servers

backend web_servers
    mode http
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200

    server web01 10.0.0.1:8080 check
    server web02 10.0.0.2:8080 check
```

**Валидация:**
```bash
# Проверка TLS-версии и шифров
echo | openssl s_client -connect localhost:443 -servername example.com 2>/dev/null | grep -E "Protocol|Cipher"

# Проверка HTTP→HTTPS redirect
curl -I http://localhost/  # → 301 Moved Permanently, Location: https://localhost/
```

### HAProxy: Re-encryption (Backend TLS)

```haproxy
frontend https_edge
    bind *:443 ssl crt /etc/haproxy/certs/site.pem
    mode http
    default_backend web_servers_encrypted

backend web_servers_encrypted
    mode http
    balance roundrobin

    # Шифрование трафика к бэкендам
    server web01 10.0.0.1:8443 ssl verify none
    server web02 10.0.0.2:8443 ssl verify none
```

**С verifies (mTLS к бэкенду):**
```haproxy
backend web_servers_mtls
    mode http
    balance roundrobin

    # Клиентский сертификат для mTLS к бэкенду
    server web01 10.0.0.1:8443 ssl verify required ca-file /etc/haproxy/ca/backend-ca.crt
    server web02 10.0.0.2:8443 ssl verify required ca-file /etc/haproxy/ca/backend-ca.crt
```

### HAProxy: TLS Passthrough

```haproxy
frontend https_passthrough
    bind *:443
    mode tcp

    # SNI-based routing
    tcp-request inspect-delay 5s
    tcp-request content accept if { req_ssl_hello_type 1 }

    # Выбор бэкенда по SNI
    use_backend api_servers if { req_ssl_sni -i api.example.com }
    default_backend web_servers

backend api_servers
    mode tcp
    server api01 10.0.0.10:443 check

backend web_servers
    mode tcp
    server web01 10.0.0.1:443 check
```

### Nginx: SSL Termination

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    # TLS Hardening
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_session_tickets off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 1.1.1.1 valid=300s;
    resolver_timeout 5s;

    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

### Nginx: TLS Passthrough (stream module)

```nginx
stream {
    upstream backend_tls {
        server 10.0.0.1:443;
    }

    server {
        listen 443;
        proxy_pass backend_tls;
        proxy_protocol on;
    }
}
```

### Автоматическое обновление сертификатов (certbot + HAProxy)

```bash
# Установка certbot
apt install certbot

# Получение сертификата
certbot certonly --standalone -d example.com -d www.example.com

# Объединение для HAProxy (fullchain + privkey)
cat /etc/letsencrypt/live/example.com/fullchain.pem \
    /etc/letsencrypt/live/example.com/privkey.pem \
    > /etc/haproxy/certs/site.pem

# Автообновление (cron или systemd timer)
# /etc/cron.d/certbot-renew
0 3 * * * root certbot renew --deploy-hook "cat /etc/letsencrypt/live/example.com/fullchain.pem /etc/letsencrypt/live/example.com/privkey.pem > /etc/haproxy/certs/site.pem && systemctl reload haproxy"
```

### Внутренний CA для mTLS (step-ca)

```bash
# Установка step-ca
wget https://dl.smallstep.com/gh-release/cli/docs_ca-install/v0.27.5/step-ca_linux_0.27.5_amd64.tar.gz
tar xzf step-ca_linux_0.27.5_amd64.tar.gz
sudo mv step-ca_*/bin/step-ca /usr/local/bin/

# Инициализация CA
step ca init --name "Internal CA" --dns localhost --address :8443

# Выпуск сертификата для сервера
step ca certificate "api.internal" api.crt api.key --ca-url https://localhost:8443 --root ~/.step/certs/root_ca.crt

# Выпуск клиентского сертификата
step ca certificate "user1" user1.crt user1.key --ca-url https://localhost:8443 --root ~/.step/certs/root_ca.crt
```

## Диагностика и устранение неполадок

### Типичные проблемы

| Проблема | Симптом | Диагностика | Решение |
|:---|:---|:---|:---|
| **Certificate mismatch** | Браузер показывает warning | `openssl s_client -connect host:443` — проверка SAN | Добавить домен в SAN сертификата |
| **Protocol mismatch** | Client не может подключиться | `openssl s_client -connect host:443 -tls1_2` | Включить поддержку нужной версии TLS |
| **OCSP Stapling не работает** | Задержка при handshake | `openssl s_client -connect host:443 -status` | Проверить DNS для OCSP responder |
| **Expired certificate** | 502/SSL error | `echo | openssl s_client -connect host:443 2>/dev/null | grep "After"` | Обновить сертификат |
| **SNI routing fails** | Правильный бэкенд не выбран | `openssl s_client -connect host:443 -servername example.com` | Проверить `tcp-request content accept if { req_ssl_hello_type 1 }` |
| **TLS overhead** | Высокий latency | `openssl s_client -connect host:443` — проверка cipher | Включить TLS 1.3 (быстрее handshake) |

### Полезные команды

```bash
# Проверка сертификата
openssl x509 -in /etc/ssl/certs/site.pem -noout -dates -subject -issuer

# Проверка цепочки сертификатов
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/site.pem

# Проверка TLS-подключения
openssl s_client -connect example.com:443 -servername example.com

# Проверка OCSP
openssl s_client -connect example.com:443 -status

# Проверка HSTS
curl -I https://example.com/ | grep -i strict

# Проверка cipher suites
nmap --script ssl-enum-ciphers -p 443 example.com
```

## Дополнительная информация

### Best Practices

1. **Включайте TLS 1.3:** Быстрее handshake, лучшие шифры, меньше roundtrips.
2. **OCSP Stapling:** Ускоряет соединение для клиентов.
3. **HSTS с `includeSubDomains`:** Защита от downgrade-атак.
4. **Автоматическое обновление:** certbot + cron/systemd timer.
5. **Внутренние сертификаты:** Используйте step-ca или Vault для внутренних сервисов.
6. **SNI для multi-domain:** Один IP, несколько сертификатов.
7. **Не храните приватные ключи в коде:** Используйте Vault, Let's Encrypt, или облачные KMS.

### См. также

- **[TLS: Теория](./tls.md)** — протокол, handshake, cipher suites
- **[HTTPS с certbot](../../WebServers/Concepts/https_with_certbot.md)** — автоматизация Let's Encrypt
- **[OpenSSL CA](./openssl_ca/)** — внутренний CA
- **[HTTP TLS Hardening](./HTTP/http_tls_hardening.md)** — профили шифрования
- **[HAProxy: Production Patterns](../../WebServers/haproxy_overview.md)** — stick tables, health checks, Runtime API
