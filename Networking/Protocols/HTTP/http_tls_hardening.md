# TLS-шифрование и сертификаты для HTTP

## Определения

**TLS Termination (SSL Termination)** — процесс расшифровки HTTPS-трафика на прокси/балансировщике. Прокси принимает TLS-соединение от клиента, расшифровывает его и передаёт HTTP-трафик бэкенду по HTTP или TLS.

**End-to-End Encryption (E2EE)** — TLS-соединение от клиента до бэкенда без расшифровки на прокси. Прокси видит только cipher text (или SNI). Используется для критичных данных.

**Cipher Suite** — набор алгоритмов шифрования для TLS-рукопожатия: ключеобмен, шифрование, аутентификация, MAC. Пример: `TLS_AES_256_GCM_SHA384`.

**OCSP Stapling** — механизм, при котором сервер периодически запрашивает статус сертификата (OCSP) у CA и «прикрепляет» (staples) ответ к TLS-рукопожатию. Убирает необходимость клиенту обращаться к CA напрямую.

**Certificate Rotation** — автоматическое обновление истекающих сертификатов. Используется Let's Encrypt (ACME) или внутренние CA.

**SNI (Server Name Indication)** — расширение TLS, позволяющее клиенту указать домен во время handshake. Необходим для shared hosting (несколько доменов на одном IP).

**ECH (Encrypted Client Hello)** — расширение TLS 1.3, шифрующее SNI и другие параметры Client Hello для защиты от пассивного наблюдения.

## Основные концепции

### TLS-рукопожатие

| Версия | RTT для полного handshake | Ключевые особенности |
| :--- | :--- | :--- |
| **TLS 1.0/1.1** | 2 RTT + TCP | Устарели; уязвимы (POODLE, BEAST) |
| **TLS 1.2** | 2 RTT + TCP | Поддержка ECDHE, GCM; широко распространён |
| **TLS 1.3** | 1 RTT + TCP | Упрощённый handshake; только AEAD cipher suites; 0-RTT |
| **TLS 1.3 + 0-RTT** | 0 RTT (Early Data) | Только для идемпотентных запросов; риск replay |

### Cipher suites: рекомендации 2026

```nginx
# Nginx: только TLS 1.3
ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256;
ssl_protocols TLSv1.3;

# Nginx: TLS 1.2 + TLS 1.3 (совместимость)
ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256';
ssl_protocols TLSv1.2 TLSv1.3;
```

| Cipher Suite | Тип | Рекомендация |
| :--- | :--- | :--- |
| `TLS_AES_256_GCM_SHA384` | TLS 1.3 AEAD | Рекомендуется |
| `TLS_CHACHA20_POLY1305_SHA256` | TLS 1.3 AEAD | Для мобильных/слабых CPU |
| `TLS_AES_128_GCM_SHA256` | TLS 1.3 AEAD | Для низкоресурсных устройств |
| `ECDHE-ECDSA-AES256-GCM-SHA384` | TLS 1.2 PFS | Рекомендуется для совместимости |
| `ECDHE-RSA-AES256-GCM-SHA384` | TLS 1.2 PFS | Рекомендуется для совместимости |
| `AES256-GCM-SHA384` | TLS 1.2 legacy | Не использовать (нет PFS) |
| `DES-CBC3-SHA` | TLS 1.0 legacy | Устарел, уязвим |

### OCSP Stapling (прикрепление OCSP)

```nginx
# Включение OCSP stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 1.1.1.1 valid=300s;
resolver_timeout 5s;
```

### Certificate Rotation с certbot

```bash
# Получение сертификата Let's Encrypt
certbot certonly --nginx -d api.example.com --agree-tos --email admin@example.com

# Автоматическое обновление (cron/systemd timer)
certbot renew --dry-run

# Hook для reload Nginx после обновления
cat > /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh << 'EOF'
#!/bin/bash
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
```

### Real IP и X-Forwarded-For

```nginx
# В http{} блоке
real_ip_header X-Forwarded-For;
set_real_ip_from 10.0.0.0/8;     # Внутренняя сеть
set_real_ip_from 172.16.0.0/12;  # Docker
set_real_ip_from 192.168.0.0/16; # Локальная сеть
real_ip_recursive on;
```

## Практические сценарии

### Сценарий 1: Полная конфигурация TLS в Nginx

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256';
    ssl_prefer_server_ciphers on;

    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_session_tickets off;

    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 1.1.1.1 valid=300s;
    resolver_timeout 5s;

    ssl_ecdh_curve X25519:secp384r1;
}
```

**Валидация:**
- `openssl s_client -connect api.example.com:443 -servername api.example.com -brief` — `Protocol  : TLSv1.3`, `Cipher    : TLS_AES_256_GCM_SHA384`.
- `openssl s_client -connect api.example.com:443 -status -servername api.example.com` — `OCSP Response Status: successful`.
- [SSL Labs Test](https://www.ssllabs.com/ssltest/) — `A+` rating.

### Сценарий 2: HSTS + HTTPS redirect

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name api.example.com;

    # Редирект на HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    # HSTS — принудительный HTTPS на 1 год
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- `curl -I http://api.example.com/` — `HTTP/1.1 301 Moved Permanently`, `Location: https://api.example.com/`.
- `curl -I https://api.example.com/` — `strict-transport-security: max-age=31536000`.

### Сценарий 3: End-to-End TLS (TLS passthrough)

Шифрование от клиента до бэкенда через HAProxy:

```haproxy
frontend https-in
    bind *:443 ssl crt /etc/haproxy/certs/api.example.com.pem alpn h2,http/1.1
    default_backend api_servers

backend api_servers
    balance roundrobin
    server app1 10.0.1.10:8443 ssl verify none
    server app2 10.0.1.11:8443 ssl verify none
```

**Валидация:**
- `curl -v https://haproxy/api/` — TLS handshake между клиентом и HAProxy, затем между HAProxy и бэкендом.
- `tcpdump -i any port 8443 -A` — трафик между HAProxy и бэкендом зашифрован.

### Сценарий 4: Mutual TLS (mTLS)

Клиент должен предоставить сертификат:

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_client_certificate /etc/nginx/client-ca.pem;
    ssl_verify_client on;
    ssl_verify_depth 2;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';

    location / {
        proxy_set_header X-Client-Cert $ssl_client_verify;
        proxy_set_header X-Client-Subject $ssl_client_s_dn;
        proxy_pass http://api_backend;
    }
}
```

**Валидация:**
- `curl --cert client.pem --key client-key.pem https://api.example.com/` — `200 OK`.
- `curl https://api.example.com/` — `400 No required SSL certificate was sent`.

### Сценарий 5: Certificate rotation с Ansible

```yaml
- name: Renew Let's Encrypt certificates
  hosts: webservers
  tasks:
    - name: Run certbot renew
      command: certbot renew --quiet --deploy-hook "systemctl reload nginx"
      register: certbot_result

    - name: Show result
      debug:
        var: certbot_result.stdout_lines
```

**Валидация:**
- `ansible-playbook renew-certs.yml` — сертификаты обновлены, Nginx перезагружен.
- Проверка срока действия: `echo | openssl s_client -connect api.example.com:443 2>/dev/null | openssl x509 -noout -dates`.

### Сценарий 6: TLS-аудит через testssl.sh

```bash
# Полный аудит
testssl.sh https://api.example.com

# Только уязвимости
testssl.sh --fast https://api.example.com

# Проверка specific vulnerabilities
testssl.sh -p -S -P -c -h -H https://api.example.com
```

**Валидация:**
- Вывод testssl.sh: `Protocol Support: TLS 1.2, TLS 1.3` (TLS 1.0/1.1 отсутствуют).
- `Vulnerabilities: None` (для уязвимостей Heartbleed, POODLE, Logjam).
- `Cipher Strength: High`.

### Сценарий 7: Zero-downtime cert rotation

Без простоев при обновлении сертификатов:

```nginx
# /etc/nginx/nginx.conf
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    # Используем переменные для путей сертификатов
    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;
}
```

```bash
# 1. Получение нового сертификата
certbot certonly --nginx -d api.example.com

# 2. Проверка нового сертификата
echo | openssl s_client -connect api.example.com:443 -servername api.example.com 2>/dev/null | openssl x509 -noout -dates

# 3. Graceful reload
nginx -t && nginx -s reload
```

**Валидация:**
- Во время reload: соединения не разрываются (`ss -tn state established '( dport = :443 )'` — количество стабильно).
- Новые соединения используют новый сертификат, старые — завершаются с старым (Graceful).

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Сертификат истёк** | `NET::ERR_CERT_EXPIRED` в браузере | `openssl s_client -connect host:443` — `Verify return code: 10` | Обновить через certbot; настроить автоматический renew |
| **Несоответствие SNI** | Сервер возвращает wrong certificate | `openssl s_client -connect host:443 -servername correct.domain` | Проверить `server_name` в Nginx и путь к сертификату |
| **Нет OCSP stapling** | Браузер проверяет сертификат через CA напрямую | `openssl s_client -connect host:443 -status` — `OCSP Response Data: no response sent` | Включить `ssl_stapling on;` и `resolver` |
| **Устаревшие cipher suites** | testssl.sh показывает `DES-CBC3-SHA` | `openssl s_client -connect host:443 -cipher 'DES-CBC3-SHA'` | Обновить `ssl_ciphers`; удалить устаревшие suites |
| **TLS 1.0/1.1 включены** | Поддержка небезопасных версий | `nmap --script ssl-enum-ciphers -p 443 host` | `ssl_protocols TLSv1.2 TLSv1.3` |
| **Сертификат и CN/SAN не совпадают** | `NET::ERR_CERT_COMMON_NAME_INVALID` | `openssl s_client -connect host:443` — `Subject: CN=wrong` | Добавить SAN в сертификат (certbot `-d` для каждого домена) |
| **Цепочка сертификатов неполная** | Промежуточный сертификат отсутствует | `openssl s_client -connect host:443 -showcerts` | Использовать `fullchain.pem`, а не `cert.pem` |
| **Session tickets off** | Повторные handshakes при каждом запросе | `openssl s_client -connect host:443` — нет `Session Ticket` | Включить `ssl_session_tickets on` или `ssl_session_cache` |
| **mTLS handshake failed** | `400 Bad Request` при предоставлении клиентского сертификата | `openssl s_client -connect host:443 -cert client.pem -key client-key.pem` | Проверить `ssl_client_certificate`, `ssl_verify_client`, `ssl_verify_depth` |
| **ECDH curve mismatch** | Нет общих кривых для ECDHE | `openssl s_client -connect host:443 -curves X25519` | Добавить `ssl_ecdh_curve X25519:secp384r1` |

## Лучшие практики

1. **TLS 1.3 обязательно:** `ssl_protocols TLSv1.2 TLSv1.3;`. TLS 1.0/1.1 — устарели (RFC 8996).
2. **Только AEAD cipher suites:** GCM, CHACHA20-POLY1305. Никаких CBC-режимов.
3. **PFS (Perfect Forward Secrecy):** ECDHE для всех соединений. Без ECDHE компрометация приватного ключа расшифровывает весь архив трафика.
4. **OCSP stapling:** `ssl_stapling on; ssl_stapling_verify on; resolver ...;`. Снижает latency и защищает приватность.
5. **Session cache вместо tickets:** `ssl_session_cache shared:SSL:10m; ssl_session_timeout 10m;`. Tickets требуют дополнительной защиты.
6. **`ssl_prefer_server_ciphers on;`:** Сервер выбирает cipher suite, а не клиент. Клиенты могут предлагать слабые suites.
7. **ECDH curve `X25519`:** `ssl_ecdh_curve X25519:secp384r1;`. X25519 быстрее и безопаснее secp384r1 на слабых CPU.
8. **`ssl_session_tickets off;`:** Session tickets шифруются статическим ключом; при компрометации ключа расшифровываются все старые сессии.
9. **HSTS с `preload`:** `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`. Подключение к preload list на hstspreload.org.
10. **Автоматический renew certbot:** `certbot renew --deploy-hook "systemctl reload nginx"`. Проверяйте cron/timer.
11. **`ssl_verify_client` для mTLS:** Только для критичных API. Используйте `ssl_verify_depth 2` с промежуточными CA.
12. **testssl.sh в CI/CD:** Запускайте аудит TLS при каждом деплое. `testssl.sh --fast https://api.example.com`.

## Граничные случаи и ограничения

1. **TLS 1.3 0-RTT и replay:** 0-RTT данные не защищены от replay. Не используйте для `POST`, `PUT`, `DELETE`. Только `GET`, `HEAD`, `OPTIONS`.
2. **ECDHE и CPU:** ECDHE на слабых CPU (IoT, embedded) может потреблять больше ресурсов, чем RSA. Используйте `X25519` для минимизации.
3. **OCSP stapling и latency:** OCSP запрос к CA добавляет задержку при первом handshake. Кэшируйте ответ (`ssl_stapling`).
4. **Сертификаты с elliptic curves:** EC-сертификаты меньше по размеру, но не поддерживаются старыми ОС (Windows XP). Используйте RSA для совместимости.
5. **mTLS и horizontal scaling:** При добавлении нового бэкенда нужно установить клиентский сертификат. Используйте shared storage (Kubernetes Secret, HashiCorp Vault).
6. **SNI и privacy:** Без ECH SNI виден провайдеру и балансировщику. ECH (RFC 9460) шифрует SNI, но поддержка ещё ограничена.
7. **`ssl_session_cache` и память:** `shared:SSL:10m` хранит ~40 000 сессий. Увеличьте при высокой нагрузке.
8. **TLS termination и latency:** TLS termination на прокси добавляет ~0.5–2ms. End-to-end TLS добавляет ~1–3ms на прокси + бэкенд handshake.
9. **Wildcard сертификаты:** `*.example.com` не покрывает `sub.sub.example.com`. Используйте SAN-сертификаты (Subject Alternative Name).
10. **certbot и rate limits:** Let's Encrypt ограничивает 50 сертификатов на домен в неделю. Используйте `--expand` для добавления SAN.

## Дополнительная информация

### Завершение TLS: termination vs end-to-end

| Стратегия | Плюсы | Минусы | Когда использовать |
| :--- | :--- | :--- | :--- |
| **TLS termination на прокси** | Низкая latency; простой routing; WAF на прокси | Прокси видит plaintext; бэкенд уязвим внутри сети | Большинство продакшенов |
| **End-to-End TLS** | Полная защита данных; бэкенд верифицирует клиента | Сложнее routing; выше latency; бэкенд должен управлять сертификатами | Финансовые API, healthcare |

### X-Forwarded-* заголовки

| Заголовок | Значение | Пример |
| :--- | :--- | :--- |
| `X-Forwarded-For` | Цепочка IP: клиент, прокси1, прокси2 | `203.0.113.1, 10.0.0.1, 192.168.1.1` |
| `X-Forwarded-Proto` | Протокол клиента | `https` |
| `X-Forwarded-Host` | Оригинальный Host заголовок | `api.example.com` |
| `X-Forwarded-Port` | Порт клиента | `443` |
| `X-Real-IP` | IP клиента (первый прокси) | `203.0.113.1` |

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — TLS termination в Nginx/HAProxy.
- **[Наблюдаемость HTTP-сервисов](./http_monitoring_observability.md)** — мониторинг сертификатов (Prometheus blackbox exporter).
- **[Коды ответа HTTP](./http_status_codes.md)** — `426 Upgrade Required` для TLS.
- **[Эволюция HTTP](./http_versions.md)** — TLS 1.3, ECH, 0-RTT.
- **[Конфигурация Nginx](../../../WebServers/Nginx/Core/nginx_overview.md)** — модуль `ngx_http_ssl_module`.
