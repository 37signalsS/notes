# TLS: продвинутые темы для веб-серверов

## Определения

**TLS False Start** — оптимизация TLS 1.2+/1.3, при которой клиент отправляет application-данные уже после `ClientKeyExchange`, не дожидаясь завершения рукопожатия. Экономит 1 RTT при повторном подключении. Зависит от поддержки клиентом и совместимости cipher suites.

**TLS Session Resumption** — механизм ускорения повторного TLS-рукопожатия. Два варианта: Session ID (сервер держит кэш сессий в памяти) и Session Ticket (клиент хранит тикет, сервер расшифровывает). В TLS 1.3 используется только Session Ticket.

**TLS 1.3 0-RTT** — возможность клиента отправить application-данные уже в первом UDP/TCP-пакете при повторном подключении (Early Data). Только для идемпотентных запросов; риск replay-атаки.

**TLS Session Ticket Rotation** — автоматическая замена ключей для шифрования Session Tickets. Необходима, чтобы компрометация одного ключа не раскрывала все прошлые сессии.

## Практические сценарии

### Сценарий 1: Полная TLS-конфигурация Nginx с продвинутыми опциями

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers on;

    # Session resumption
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets on;
    ssl_session_ticket_key /etc/nginx/ssl/ticket.key;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    location / {
        limit_except GET HEAD POST OPTIONS { deny all; }
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Валидация:**
- `openssl s_client -connect api.example.com:443 -servername api.example.com -reconnect 2>&1 | grep "Reused"` — сессия повторно использована.
- `curl -v --tls-max 1.3 --tls13-ciphers TLS_AES_256_GCM_SHA384 https://api.example.com/` — handshake 1-RTT.
- `curl -v --tls13-ciphers TLS_AES_256_GCM_SHA384 --http0.9 https://api.example.com/` — 0-RTT Early Data.

### Сценарий 2: Ротация Session Ticket ключей

```bash
#!/bin/bash
# /etc/cron.daily/nginx-ticket-rotation
NEW_TICKET=$(openssl rand 48)
cp /etc/nginx/ssl/ticket.key /etc/nginx/ssl/ticket.key.bak
echo "$NEW_TICKET" > /etc/nginx/ssl/ticket.key
chown root:root /etc/nginx/ssl/ticket.key
chmod 600 /etc/nginx/ssl/ticket.key
systemctl reload nginx

# Хранить 2 ключа: текущий и предыдущий
# Nginx расшифровывает тикеты, зашифрованные любым из двух ключей
```

**Валидация:**
- `ls -l /etc/nginx/ssl/ticket.key*` — присутствует текущий и бэкап.
- `journalctl -u nginx --since '1 hour ago' | grep -i ticket` — ошибок ротации нет.

### Сценарий 3: Диагностика Session Resumption

```bash
# Проверка кэша сессий
echo | openssl s_client -connect api.example.com:443 -servername api.example.com -reconnect 2>&1 | grep -E "Reused|Session-ID|Session ticket"

# Проверка Session Ticket
openssl rand 48 | base64 > /tmp/ticket.key
openssl enc -aes-256-cbc -d -in ticket.bin -out ticket.dec -pass file:/tmp/ticket.key

# Wireshark: фильтр `tls.handshake.type == 2` (ServerHello) и `tls.handshake.type == 11` (Session Ticket)
```

**Валидация:**
- При втором подключении `Reused` должен быть `Yes`.
- При отсутствии кэша `Reused: No, Session-ID: None`.

## Лучшие практики

1. **TLS False Start:** включайте только если все клиенты поддерживают ECDHE и extended master secret. Для продакшена с разнородными клиентами лучше TLS 1.3 с 0-RTT.
2. **Session Cache:** настройте `ssl_session_cache shared:SSL:10m` для ~40k сессий. Для высоконагруженных сервисов увеличьте до `20m`.
3. **Session Tickets:** включите `ssl_session_tickets on;` и ротируйте ключи ежедневно. Храните 2 ключа для плавного перехода.
4. **0-RTT:** включайте только для идемпотентных методов (GET, HEAD). Никогда для POST/PUT/DELETE.
5. **Replay Protection:** мониторьте дублирующиеся 0-RTT запросы. Используйте nonce или idempotency-key на приложении.
6. **Аппаратное ускорение:** убедитесь, что сервер поддерживает AES-NI/AVX-512 для ECDHE/AES-GCM.

## Граничные случаи и ограничения

1. **TLS False Start несовместим с某些 cipher suites:** требуется ECDHE + AES-GCM/ChaCha20. RC4, DES, 3DES не поддерживаются.
2. **Session Tickets уязвимы к replay:** если злоумышленник перехватит тикет, он может повторить запрос. Ограничьте 0-RTT идемпотентными методами.
3. **Кэш сессий ограничен памятью:** `ssl_session_cache` хранит сессии в shared memory. При превышении лимита старые сессии удаляются.
4. **TLS 1.3 0-RTT требует QUIC/TCP:** работает только на UDP (QUIC) или TCP с TLS 1.3.
5. **Nginx не поддерживает 0-RTT для POST:** TLS 1.3 0-RTT в Nginx/Angie работает только для GET/HEAD.

## Дополнительная информация

- **[TLS-шифрование и сертификаты для HTTP](../../Networking/Protocols/HTTP/http_tls_hardening.md)** — OCSP stapling, cipher suites, session resumption.
- **[Оптимизация производительности HTTP](../../Networking/Protocols/HTTP/http_protocols_optimization.md)** — TLS 1.3, 0-RTT, kTLS.
- **[Эволюция HTTP и HTTPS](../../Networking/Protocols/HTTP/http_versions.md)** — TLS session tickets across versions.
