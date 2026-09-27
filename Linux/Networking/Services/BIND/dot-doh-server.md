# BIND: DNS over TLS (DoT) и DNS over HTTPS (DoH) — серверная часть

---

## Определения

**DNS over TLS (DoT, RFC 7858)** — шифрование DNS-трафика через TLS на выделенном порту 853. Сервер BIND принимает зашифрованные запросы от клиентов, обеспечивая конфиденциальность и целостность данных. В отличие от клиентской настройки (systemd-resolved), здесь BIND выступает как TLS-сервер.

**DNS over HTTPS (DoH, RFC 8484)** — инкапсуляция DNS в HTTPS-трафик на порту 443. Клиенты отправляют DNS-запросы как HTTP POST/GET-запросы, что маскирует DNS-трафик под обычный веб-трафик. Поддерживается BIND 9.18+.

**TLS-сертификат** — криптографический документ, подтверждающий Ownership сервера. Для DoT/DoH требуется действующий сертификат (Let's Encrypt, коммерческий CA или самоподписанный для внутренних нужд).

**HTTP/2** — протокол второго поколения HTTP, используемый DoH для мультиплексирования DNS-запросов в одном TLS-соединении. BIND поддерживает HTTP/2 для DoH.

---

## Базовые концепции

### Когда использовать DoT/DoH на сервере

| Сценарий | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Корпоративный резолвер** | DoT + DoH | Шифрование DNS для всех сотрудников, защита от прослушивания |
| **Публичный рекурсивный резолвер** | DoH (приоритет) | Маскировка под HTTPS, устойчивость к блокировке порта 853 |
| **Авторитативный сервер** | DoT (для трансферов) | Шифрование AXFR/IXFR между серверами (XoT, RFC 9103) |
| **IoT/Embedded устройства** | DoT | Простота реализации на клиентах, минимальный оверхед |
| **Региональные фильтры** | DoH | Обход блокировок порта 853 провайдерами |

### Версионная совместимость

| Функция | Минимальная версия BIND | Примечание |
| :--- | :--- | :--- |
| DoT (сервер) | 9.16.0 | Базовая поддержка TLS |
| DoH (сервер) | 9.18.0 | Требуется HTTP/2 библиотека (nghttp2) |
| DoH (клиент) | 9.18.0 | `tls-key-directory` для клиентских TLS-соединений |
| XoT (zone transfer over TLS) | 9.18.0 | RFC 9103 |
| HTTP/2 для DoH | 9.18.0 | По умолчанию, если собран с nghttp2 |
| TLS 1.3 | 9.18.0 | Рекомендуется для максимальной безопасности |

### Архитектура DoT/DoH сервера

```text
                    ┌─────────────────────────────────┐
                    │          BIND 9.18+              │
                    │                                  │
  DoT (TCP:853) ──>│  named                          │
  DoH (TCP:443) ──>│    ├── TLS termination          │
  DNS (UDP:53)  ──>│    ├── DNS protocol handler      │
                    │    ├── Zone storage              │
                    │    └── rndc control               │
                    └─────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Zone files /     │
                    │   rndc.key         │
                    └───────────────────┘
```

### Порядок TLS-соединения

1. Клиент устанавливает TCP-соединение с сервером на порт 853 (DoT) или 443 (DoH)
2. TLS-хэндшейк (TLS 1.2/1.3) — сервер предоставляет сертификат, клиент проверяет
3. После установки TLS-канала клиент отправляет DNS-запрос внутри TLS
4. Сервер обрабатывает запрос и возвращает зашифрованный ответ
5. Клиент может повторно использовать TLS-соединение (session resumption)

---

## Практические сценарии

### Предусловия

```bash
# Проверка версии BIND (требуется 9.18+)
named -v
# → BIND 9.18.28-0ubuntu0.22.04.1-Ubuntu (Extended Support Version)

# Установка необходимых пакетов (Debian/Ubuntu)
sudo apt install bind9 bind9utils ssl-cert

# Проверка наличия TLS-библиотек
named -V 2>&1 | grep -i "tls\|ssl\|http"
# → --with-openssl --with-httpd-jsonc
```

### 1. Получение TLS-сертификата

#### Вариант A: Let's Encrypt (рекомендуется для публичных серверов)

```bash
# Установка certbot
sudo apt install certbot

# Остановка nginx/apache占用 порт 80
sudo systemctl stop nginx apache2

# Получение сертификата
sudo certbot certonly --standalone -d dns.example.com \
  --agree-tos --email admin@example.com

# Сертификаты будут в:
# /etc/letsencrypt/live/dns.example.com/fullchain.pem
# /etc/letsencrypt/live/dns.example.com/privkey.pem

# Автоматическое обновление (cron)
echo "0 3 * * * certbot renew --quiet --deploy-hook 'rndc reconfig'" | sudo tee /etc/cron.d/certbot-renew
```

#### Вариант B: Самоподписанный сертификат (для внутренних серверов)

```bash
# Генерация CA и серверного сертификата
sudo mkdir -p /etc/bind/tls && cd /etc/bind/tls

# Создание CA (один раз)
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
  -subj "/CN=DNS CA/O=Internal"

# Создание серверного сертификата
openssl genrsa -out dns-server.key 2048
openssl req -new -key dns-server.key -out dns-server.csr \
  -subj "/CN=dns.example.com/O=Internal"
openssl x509 -req -in dns-server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out dns-server.crt -days 3650

# Права доступа
sudo chown bind:bind /etc/bind/tls/dns-server.key
sudo chmod 640 /etc/bind/tls/dns-server.key
```

#### Вариант C:欻集成 с Vault PKI (для enterprise-сред)

```bash
# Через Vault PKI Secrets Engine
vault write pki/issue/dns-server \
  common_name="dns.example.com" \
  ttl=8760h

# Результат:
# certificate → /etc/bind/tls/dns-server.crt
# private_key → /etc/bind/tls/dns-server.key
# issuing_ca → /etc/bind/tls/ca.crt
```

### 2. Настройка DoT (DNS over TLS) в BIND

**Конфигурация `/etc/bind/named.conf.local`:**

```conf
tls tls-certificate {
    key-file "/etc/bind/tls/dns-server.key";
    cert-file "/etc/bind/tls/dns-server.crt";
    dhparam-file "/etc/bind/tls/dhparam.pem";
    ciphers "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384";
    protocols { TLSv1.2; TLSv1.3; };
    session-tickets no;     # Отключение session tickets для perfect forward secrecy
    prefer-server-ciphers yes;
};

options {
    listen-on port 53 { any; };
    listen-on port 853 { any; };           # DoT
    listen-on tls port 853 { any; };       # TLS-терминация на порту 853

    tls tls-certificate;

    # Остальные опции...
    recursion yes;
    allow-query { any; };
};
```

**Генерация DH-параметров (рекомендуется):**

```bash
# Генерация dhparam.pem (может занять 1-5 минут)
openssl dhparam -out /etc/bind/tls/dhparam.pem 2048
sudo chown bind:bind /etc/bind/tls/dhparam.pem
```

**Валидация:**

```bash
# Проверка конфигурации
sudo named-checkconf
# → no errors

# Перезапуск
sudo systemctl restart named

# Проверка прослушивания
sudo ss -tlnp | grep -E ':(53|853)\b'
# → LISTEN  0  128  0.0.0.0:53   0.0.0.0:*  users:(("named",...))
# → LISTEN  0  128  0.0.0.0:853  0.0.0.0:*  users:(("named",...))

# Тест DoT-подключения
kdig @dns.example.com +tls example.com A +short
# → 192.0.2.1

# Тест через openssl
openssl s_client -connect dns.example.com:853 -brief 2>&1 | head -5
# → TLSv1.3 ... OK
```

### 3. Настройка DoH (DNS over HTTPS) в BIND

**Предусловия:**

```bash
# Проверка поддержки DoH
named -V 2>&1 | grep -i http
# → --with-httpd-jsonc  (должен присутствовать)

# Установка nghttp2 (если требуется)
sudo apt install libnghttp2-dev
```

**Конфигурация `/etc/bind/named.conf.local`:**

```conf
http http-service {
    endpoints { "/dns-query"; };
    allow { any; };

    # TLS-сертификат (тот же, что и для DoT)
    tls tls-certificate;

    # HTTP/2 настройки
    max-clients 1000;
    http2-max-concurrent-streams 100;
    listen-on tls port 443 { any; };

    # Принудительный HTTP/2 (без fallback на HTTP/1.1)
    http2 no;
};

options {
    listen-on port 53 { any; };
    listen-on port 853 { any; };
    listen-on tls port 853 { any; };
    listen-on tls port 443 { any; };    # DoH

    tls tls-certificate;
    http http-service;

    recursion yes;
    allow-query { any; };
};
```

**Валидация:**

```bash
# Проверка конфигурации
sudo named-checkconf
# → no errors

# Перезапуск
sudo systemctl restart named

# Проверка прослушивания
sudo ss -tlnp | grep -E ':(53|853|443)\b'

# Тест DoH (POST-запрос)
curl -H 'accept: application/dns-message' \
     --data-binary @/dev/stdin \
     https://dns.example.com/dns-query <<EOF
$(python3 -c "
import struct, base64
# DNS query: example.com A
q = b'\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01'
print(base64.b64encode(q).decode())
")
EOF

# Тест через kdig (BIND-утилита)
kdig @https://dns.example.com/dns-query example.com A +short
# → 192.0.2.1

# Тест через dig (BIND 9.18+)
dig @https://dns.example.com/dns-query example.com A +short
# → 192.0.2.1
```

### 4. Настройка XoT (Zone Transfer over TLS)

**На Master-сервере:**

```conf
tls tls-certificate {
    key-file "/etc/bind/tls/dns-server.key";
    cert-file "/etc/bind/dns-server.crt";
    protocols { TLSv1.2; TLSv1.3; };
};

zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    allow-transfer { key "transfer-key"; };
    transfer-source tls 192.168.1.1;     # Источник для XoT
};
```

**На Slave-сервере:**

```conf
tls tls-certificate {
    key-file "/etc/bind/tls/dns-server.key";
    cert-file "/etc/bind/tls/dns-server.crt";
};

zone "example.com" {
    type slave;
    file "/var/lib/bind/db.example.com";
    masters {
        192.168.1.1 key "transfer-key";
    };
    allow-transfer { none; };
    masterfile-format text;
};
```

**Валидация XoT:**

```bash
# Проверка трансфера через TLS
dig @192.168.1.1 example.com AXFR -k /etc/bind/transfer.key
# → Данные зоны (зашифрованы при передаче)

# Проверка через tcpdump
sudo tcpdump -i eth0 port 853 -nn
# → Должны видеть TLS handshake + DNS данные
```

### 5. Firewall rules для DoT/DoH

```bash
# iptables
sudo iptables -A INPUT -p tcp --dport 53 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 53 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 853 -j ACCEPT    # DoT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT    # DoH

# nftables
sudo nft add rule inet filter input tcp dport {53, 853, 443} accept
sudo nft add rule inet filter input udp dport 53 accept

# ufw
sudo ufw allow 53/tcp
sudo ufw allow 53/udp
sudo ufw allow 853/tcp
sudo ufw allow 443/tcp
```

### 6. Мониторинг DoT/DoH соединений

```bash
# Проверка активных TLS-соединений
sudo ss -tnp | grep -E ':(853|443)\b' | wc -l
# → 42 (активных соединения)

# Мониторинг через rndc
sudo rndc status | grep -A5 "network"
# → TCP requests: 1523
# → IPv4 interfaces: ...

# Проверка через statistics channel
curl -s http://127.0.0.1:8080/stats/json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('DNS over TLS connections:', data.get('nsstat', {}).get('TLSHandshakes', 'N/A'))
print('DNS over HTTPS connections:', data.get('nsstat', {}).get('HTTPSRequests', 'N/A'))
"

# Мониторинг через Prometheus (см. logging-and-monitoring.md)
```

---

## Типичные ошибки и их решение

### DoT: клиент не может подключиться

**Симптом:** `kdig @dns.example.com +tls example.com` возвращает timeout.

**Причины:**
1. Порт 853 закрыт файрволом
2. Сертификат недействителен или просрочен
3. Имя в сертификате не совпадает с именем сервера

**Решение:**

```bash
# 1. Проверка порта
sudo ss -tlnp | grep 853
# → Должен слушать

# 2. Проверка сертификата
openssl x509 -in /etc/bind/tls/dns-server.crt -noout -dates -subject
# → notBefore=... notAfter=...  (должен быть действителен)

# 3. Проверка CN/SAN
openssl x509 -in /etc/bind/tls/dns-server.crt -noout -text | grep -A1 "Subject Alternative"
# → DNS:dns.example.com (должен совпадать)

# 4. Проверка логов BIND
journalctl -u named -n 50 | grep -i "tls\|error\|ssl"
```

### DoH: HTTP/2 не работает

**Симптом:** DoH-запросы возвращают HTTP 501 или пустой ответ.

**Причина:** BIND собран без поддержки HTTP/2 (отсутствует `nghttp2`).

**Решение:**

```bash
# Проверка поддержки HTTP/2
named -V 2>&1 | grep -i http
# → Если нет --with-httpd-jsonc — нужно пересобрать

# Для Ubuntu/Debian
sudo apt install libnghttp2-dev
sudo apt source bind9
cd bind9-*
./configure --with-httpd-jsonc --with-openssl
make && sudo make install
```

### TLS: handshake failure

**Симптом:** `openssl s_client` возвращает `handshake failure`.

**Причина:** Несовпадение cipher suites между клиентом и сервером.

**Решение:**

```conf
// Указать более широкий набор шифров
tls tls-certificate {
    ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384";
    protocols { TLSv1.2; TLSv1.3; };
};
```

### DoH: сертификат Let's Encrypt истек

**Симптом:** Клиенты получают ошибку `certificate verify failed`.

**Решение:**

```bash
# Проверка срока действия
sudo certbot certificates

# Принудительное обновление
sudo certbot renew --force-renewal

# Проверка
curl -I https://dns.example.com/dns-query 2>&1 | grep -i "expire"
```

---

## Лучшие практики

*   **Используйте TLS 1.3** — более быстрый хэндшейк, лучшая безопасность. TLS 1.2 допустим для совместимости со старыми клиентами.
*   **Не используйте self-signed сертификаты** в продакшене — клиенты не смогут проверить подлинность сервера. Используйте Let's Encrypt или внутренний CA.
*   **Настройте OCSP Stapling** для ускорения проверки сертификатов клиентами.
*   **Разделяйте порты** — DoT на 853, DoH на 443, классический DNS на 53. Не смешивайте.
*   **Мониторьте количество TLS-соединений** через statistics channel или Prometheus. Резкий рост может указывать на DDoS.
*   **Настройте rate-limiting** для DoT/DoH — те же RRL-механизмы, что и для классического DNS.
*   **Используйте XoT** (zone transfer over TLS) для шифрования трансферов зон между серверами.
*   **Регулярно обновляйте сертификаты** — настройте автоматическое обновление через certbot + cron.

---

## Дополнительная информация

### Ключевые RFC

*   **RFC 7858:** DNS over TLS (DoT).
*   **RFC 8484:** DNS over HTTPS (DoH).
*   **RFC 9103:** DNS Zone Transfer over TLS (XoT).
*   **RFC 9250:** DNS over QUIC (DoQ) — альтернатива DoT/DoH.
*   **RFC 8467:** Padding for DNS over TLS.

### Связанные разделы

*   [Безопасность DNS](../../../Networking/Protocols/DNS/dns_security.md) — DoT/DoH клиентская настройка, DNSSEC.
*   [BIND: Обзор](./overview.md) — архитектура и роли серверов.
*   [BIND: Slave сервер](./slave_server_configuration.md) — XoT для трансферов зон.
*   [BIND: Мониторинг](./logging-and-monitoring.md) — метрики DoT/DoH соединений.
*   [Диагностика DNS](../../../Linux/Diagnostics/Networking/dns/overview.md) — инструменты `dig`, `kdig`.
