# Диагностика SSL/TLS сертификатов

**Актуально для:** OpenSSL 3.x–4.x

## Определения

Базовые понятия PKI (X.509, SAN, AKI/SKI, CN) подробно описаны в **[обзоре PKI](../Concepts/pki_overview.md#определения)**. Здесь перечислены только понятия, специфичные для диагностики.

**TLS (Transport Layer Security)** — криптографический протокол, обеспечивающий безопасную связь между клиентом и сервером. Заменяет SSL (устаревшая версия).

**Chain of Trust (Цепочка доверия)** — последовательность сертификатов от конечного (серверного) узла до доверенного корневого центра (Root CA). Клиент проверяет подпись на каждом уровне; если хотя бы одно звено невалидно, доверие ко всей цепочке теряется.

**Incomplete chain** — ситуация, когда сервер не передаёт промежуточные сертификаты (Intermediate CA). Это приводит к ошибкам верификации у клиентов, чьё локальное хранилище не содержит этих промежуточных звеньев.

**Server Name Indication (SNI)** — расширение TLS, позволяющее клиенту передавать имя хоста (домен) в начале рукопожатия. Это необходимо для корректного выбора сертификата на серверах с несколькими виртуальными хостами на одном IP.

**OCSP Stapling** — механизм, при котором сервер сам запрашивает статус валидности своего сертификата у CA и «прикрепляет» подписанный ответ к handshake. Это ускоряет проверку для клиента и повышает его приватность.

**Trust Store (CA-хранилище)** — системный набор доверенных корневых и промежуточных сертификатов (например, `/etc/ssl/certs` в Linux).

**Mutual TLS (mTLS)** — режим взаимной аутентификации, при котором и клиент, и сервер предъявляют друг другу сертификаты. Используется для внутренних API, сервис-меш и Zero Trust архитектур.

**Certificate Transparency (CT)** — публичный реестр логов issuance сертификатов. Браузеры требуют наличия записей SCT (Signed Certificate Timestamp) для сертификатов, выданных публичными CA.

**CRL (Certificate Revocation List)** — подписанный список отозванных серийных номеров. Клиент проверяет наличие сертификата в CRL перед установкой доверия.

## Как это работает

### TLS-рукопожатие и проверка цепочки доверия

При установке TLS-соединения клиент выполняет следующую последовательность проверок:

1. **Server Hello + Certificate:** сервер отправляет свой сертификат и (опционально) промежуточные сертификаты.
2. **Chain building:** клиент строит цепочку от leaf-сертификата до корневого CA, используя поля `Authority Key Identifier` (AKI) в сертификате и `Subject Key Identifier` (SKI) у издателя.
3. **Signature verification:** каждая подпись в цепочке проверяется с использованием публичного ключа соответствующего издателя.
4. **Hostname verification:** проверяется, что `Subject` или `Subject Alternative Name` (SAN) сертификата совпадают с запрошенным хостом.
5. **Validity period:** проверяется, что текущее время попадает в диапазон `notBefore`–`notAfter`.
6. **Revocation check:** клиент запрашивает статус сертификата через OCSP (или CRL), если это включено.
7. **Trust anchor:** конечный корневой CA должен присутствовать в trust store клиента.

Если любой этап fails, OpenSSL выводит `Verify return code: <N> (<description>)`. Коды 0 означают успех; все остальные — ошибки.

### Архитектура сертификата X.509 v3

```
Leaf Certificate (server.crt)
    │
    ├── Subject: CN=example.com, SAN=DNS:example.com, DNS:www.example.com
    ├── Issuer:  CN=Intermediate CA
    ├── Validity: notBefore=Jan 1, notAfter=Apr 9
    ├── AKI ←→ SKI Intermediate CA
    └── Public Key: (ECDSA/RSA/Ed25519...)
    │
Intermediate CA Certificate (intermediate.pem)
    │
    ├── Subject: CN=Intermediate CA
    ├── Issuer:  CN=Root CA
    └── AKI ←→ SKI Root CA
    │
Root CA Certificate (root.pem)  ← в trust store
    ├── Subject = Issuer (self-signed)
    └── Trusted anchor
```

## Практические сценарии

### Сценарий 1: Проверка срока действия сертификата

При проверке удалённого сервера обязательно используйте флаг `-servername`, чтобы избежать получения дефолтного сертификата.

```bash
# Проверка удалённого сервера
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# notAfter=May 14 18:57:50 2026 GMT

# Проверка локального файла
openssl x509 -in server.crt -noout -enddate

# Вывод всех дат сразу
openssl x509 -in server.crt -noout -dates -subject -issuer
```

**Быстрая проверка с `-checkend`:**
```bash
# Вернёт код 0, если сертификат действителен ещё более N секунд
openssl x509 -in server.crt -noout -checkend 0 && echo "valid" || echo "expired"
openssl x509 -in server.crt -noout -checkend 86400 # проверка на 24 часа вперёд
```

**Важно:** Неверное системное время (рассинхронизация NTP) на стороне клиента или сервера часто является причиной ложных ошибок «Certificate Expired».

### Сценарий 2: Пакетная проверка сертификатов для списка хостов

```bash
# Перебирает хосты и выводит notAfter для сортировки по ближайшей просрочке
for h in $(cat hosts.txt); do
  echo -n "$h "
  echo | openssl s_client -connect "$h:443" -servername "$h" 2>/dev/null | \
    openssl x509 -noout -enddate
done | sort -t= -k2

# → example.com=May 14 18:57:50 2026 GMT
# → service.local=Jan 23 09:00:00 2026 GMT
```

### Сценарий 3: Верификация цепочки и типичные ошибки

Команда для быстрой проверки статуса верификации:

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null | grep Verification
```

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Verification: OK` | Ошибок не обнаружено. | Действие не требуется. |
| `unable to verify the first certificate` | Сервер не отдает промежуточные сертификаты. | Настроить `fullchain.crt` на сервере. |
| `unable to get local issuer certificate` | В хранилище клиента нет корневого CA. | Обновить `ca-certificates` или добавить CA вручную. |
| `Certificate expired` | Срок действия сертификата истек. | Перевыпустить сертификат. |
| `Self-signed certificate` | Сертификат подписан самим собой. | Использовать публичный CA или добавить его в доверенные. |
| `Hostname mismatch` | CN или SAN не совпадают с доменом. | Выпустить сертификат с корректным SAN. |

### Сценарий 4: Проверка соответствия ключа и сертификата

Перед установкой необходимо убедиться, что приватный ключ соответствует публичному ключу в сертификате.

**Универсальный метод (работает для RSA, ECDSA, Ed25519):**
```bash
# Извлечение публичного ключа из приватного ключа (OpenSSL 3.x+)
openssl pkey -in server.key -pubout -outform DER | openssl sha256
# Извлечение публичного ключа из сертификата
openssl x509 -in server.crt -pubkey -noout -outform DER | openssl sha256
# Хеши должны совпадать
```

**Для RSA (сравнение модуля) — устаревший метод:**
```bash
# openssl rsa устарел начиная с OpenSSL 3.0; используйте openssl pkey выше
openssl rsa -noout -modulus -in server.key | openssl sha256
openssl x509 -noout -modulus -in server.crt | openssl sha256
```

### Сценарий 5: Анализ CSR и отпечатков

```bash
# Проверка содержимого запроса перед отправкой в CA
openssl req -in server.csr -noout -text

# Получение отпечатка (Fingerprint) для сверки (например, в логах CT)
openssl x509 -in server.crt -noout -fingerprint -sha256

# Только Subject и Issuer
openssl x509 -in server.crt -noout -subject -issuer

# Только сроки действия
openssl x509 -in server.crt -noout -dates

# Серийный номер
openssl x509 -in server.crt -noout -serial

# Хеш subject (используется в lookup)
openssl x509 -in server.crt -noout -hash
```

### Сценарий 6: Управление системным trust store

```bash
# Debian/Ubuntu: добавление корневого CA
sudo cp custom-root.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates

# RHEL/CentOS/Fedora
sudo cp custom-root.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Проверка установленного CA
openssl verify -CApath /etc/ssl/certs custom-root.crt
# custom-root.crt: OK
```

### Сценарий 7: Исправление «Incomplete chain» в Nginx

Ошибка означает, что клиент не может построить путь к корню. Чаще всего в `ssl_certificate` указан только файл самого сертификата без Intermediate CA.

**Неправильно:**
```nginx
ssl_certificate /path/example.com.crt; # Только Leaf-сертификат
```

**Правильно:**
```nginx
ssl_certificate /path/fullchain.pem;   # Leaf + Intermediate(s)
```
Подробнее о форматах цепочек см. в **[обзоре PKI](../Concepts/pki_overview.md#форматы-файлов-и-стандарты)**.

### Сценарий 8: Ручная установка промежуточного и корневого сертификатов

Если системное CA-хранилище слишком старое, цепочку нужно восстановить вручную.

**Шаг 1: Получение ссылки на Intermediate CA из AIA:**
```bash
openssl s_client -connect target-site.ru:443 -servername target-site.ru </dev/null | \
  openssl x509 -noout -text | grep "CA Issuers"
# CA Issuers - URI:https://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt
```

**Шаг 2: Скачивание и конвертация (если формат DER):**
```bash
wget https://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt -O intermediate.crt
openssl x509 -inform DER -in intermediate.crt -out intermediate.pem
```

**Шаг 3: Определение издателя для поиска корневого CA:**
```bash
openssl x509 -in intermediate.pem -noout -issuer
# issuer=OU = GlobalSign Root CA - R3, O = GlobalSign, CN = GlobalSign
```

**Шаг 4: Скачивание корня (с официального сайта CA):**
```bash
wget https://secure.globalsign.net/cacert/Root-R3.crt -O root.crt
openssl x509 -inform DER -in root.crt -out root.pem
```

**Шаг 5: Проверка связки:**
```bash
openssl verify -CAfile root.pem intermediate.pem
# intermediate.pem: OK
```

**Шаг 6: Установка в систему (Debian/Ubuntu):**
```bash
sudo cp root.pem /usr/local/share/ca-certificates/custom-root.crt
sudo cp intermediate.pem /usr/local/share/ca-certificates/custom-inter.crt
sudo update-ca-certificates --fresh
```

**Шаг 7: Финальная проверка:**
```bash
openssl s_client -connect target-site.ru:443 -servername target-site.ru </dev/null | grep Verification
# Verification: OK
```

### Сценарий 9: Диагностика OCSP Stapling

Чтобы проверить, передаёт ли сервер статус отзыва в процессе рукопожатия:

```bash
openssl s_client -connect example.com:443 -servername example.com -status 2>/dev/null | grep -A 5 "OCSP response"
# OCSP response: 
# ======================================
# OCSP Response Data:
#     OCSP Response Status: successful (0x0)
#     Response Type: Basic OCSP Response
```

**Расширенная диагностика OCSP Stapling:**

```bash
# Проверка с таймаутом и детальным выводом
openssl s_client -connect example.com:443 -servername example.com -status -tlsextdebug 2>&1 | \
  grep -E "OCSP|Verify|no response sent"

# Если OCSP Stapling не работает:
# 1. Проверить DNS-резолвинг сервера (может не достучаться до OCSP responder)
# 2. Проверить firewall (firewall может блокировать исходящие запросы к OCSP responder)
# 3. Проверить наличие AIA в сертификате
openssl x509 -in server.crt -noout -text | grep -A 2 "Authority Information Access"

# Ручная проверка OCSP responder (прямой запрос)
openssl ocsp -issuer intermediate.pem -cert server.crt \
  -url http://ocsp.digicert.com -CAfile root.pem -resp_text
```

### Сценарий 10: Проверка поддержки версий TLS

```bash
# Проверка TLS 1.3 (рекомендуется)
openssl s_client -connect example.com:443 -servername example.com -tls1_3

# Проверка TLS 1.2 (для совместимости с устаревшими клиентами)
openssl s_client -connect example.com:443 -servername example.com -tls1_2

# Перечисление всех поддерживаемых шифров через nmap
nmap --script ssl-enum-ciphers -p 443 example.com
```

### Сценарий 11: Проверка HSTS и заголовков безопасности

```bash
curl -I https://example.com | grep -i "Strict-Transport-Security"
# Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

### Сценарий 12: Диагностика mTLS (взаимная аутентификация)

Для проверки, что сервер действительно требует клиентский сертификат и корректно его валидирует:

```bash
# Без клиентского сертификата (должен вернуть handshake failure или certificate required)
openssl s_client -connect api.example.com:443 -servername api.example.com -CAfile ca.crt </dev/null 2>&1 | grep -E "handshake|alert|Verify"

# С клиентским сертификатом (должен вернуть OK)
openssl s_client -connect api.example.com:443 -servername api.example.com \
  -CAfile ca.crt -cert client.crt -key client.key </dev/null 2>&1 | grep "Verify return code"
# Verify return code: 0 (ok)

# Проверка, что сервер запросил клиентский сертификат
openssl s_client -connect api.example.com:443 -servername api.example.com -CAfile ca.crt </dev/null 2>&1 | grep "Verify return code"
# Verify return code: 21 (unable to verify the first certificate) — если клиентский не предоставлен
```

### Сценарий 13: Глубокая диагностика cipher suites и ALPN

```bash
# Быстрое перечисление поддерживаемых cipher suites (требует nmap)
nmap --script ssl-enum-ciphers -p 443 example.com

# Проверка конкретного cipher suite через openssl
openssl s_client -connect example.com:443 -servername example.com -cipher 'ECDHE+AESGCM:ECDHE+CHACHA20' -brief </dev/null

# Проверка ALPN (необходим для HTTP/2)
openssl s_client -connect example.com:443 -servername example.com -alpn h2,http/1.1 </dev/null 2>&1 | grep "ALPN"
# ALPN protocol: h2
```

### Сценарий 14: Проверка отзыва через CRL

```bash
# Получение CRL Distribution Points из сертификата
openssl x509 -in server.crt -noout -text | grep -A 4 "CRL Distribution"

# Проверка статуса отзыва (требует OpenSSL 1.1.1+)
openssl verify -crl_check -CAfile ca-chain.crt -untrusted intermediate.crt server.crt
# server.crt: OK (CRL проверен)
```

### Сценарий 15: Проверка записей Certificate Transparency (CT)

```bash
# Получение отпечатка сертификата и проверка в CT-логах
fingerprint=$(openssl x509 -in server.crt -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')

# Проверка через crt.sh (curl)
curl -s "https://crt.sh/?q=${fingerprint}&output=json" | jq length

# Если возвращается 0 — сертификат не найден в публичных CT-логах
# (потенциальная проблема для браузеров, требующих CT)
```

### Сценарий 16: Устранение неполадок mTLS в Nginx

```bash
# Проверка, что Nginx запрашивает клиентский сертификат
openssl s_client -connect api.example.com:443 -servername api.example.com -CAfile ca.crt </dev/null 2>&1 | grep "Verify return code"
# Ожидается: Verify return code: 21 (unable to verify the first certificate) — клиент не предоставил сертификат

# Проверка, что доверенный CA указан в конфигурации
nginx -T 2>/dev/null | grep -A 2 "ssl_client_certificate"

# Ожидаемый вывод:
# ssl_client_certificate /etc/nginx/ca/ca-chain.crt;
# ssl_verify_client on;
```

### Сценарий 17: Пакетная проверка сертификатов в инфраструктуре

Для SRE/Sysadmin практик часто требуется массовая проверка сроков действия сертификатов на множестве сервисов.

```bash
#!/usr/bin/env bash
# check_certs.sh — пакетная проверка сертификатов
# Требуется GNU date (Linux). На macOS/BSD замените на Python-парсер.
set -euo pipefail

HOSTS=(
  "web1.example.com:443"
  "web2.example.com:443"
  "api.example.com:443"
  "mail.example.com:993"
)

DAYS_WARN=30

for host in "${HOSTS[@]}"; do
  expiry=$(echo | openssl s_client -connect "$host" -servername "${host%%:*}" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null \
    | cut -d= -f2)

  if [ -z "$expiry" ]; then
    echo "[FAIL] $host — не удалось получить сертификат"
    continue
  fi

  expire_epoch=$(date -d "$expiry" +%s)
  now_epoch=$(date +%s)
  days_left=$(( (expire_epoch - now_epoch) / 86400 ))

  if [ "$days_left" -lt 0 ]; then
    echo "[EXPIRED] $host — истёк $days_left дней назад ($expiry)"
  elif [ "$days_left" -lt "$DAYS_WARN" ]; then
    echo "[WARN]  $host — истекает через $days_left дней ($expiry)"
  else
    echo "[OK]    $host — действителен ещё $days_left дней ($expiry)"
  fi
done
```

### Сценарий 18: Мониторинг сертификатов через systemd / cron

Для production инфраструктуры используйте systemd-таймеры или cron для регулярной проверки:

```bash
# /etc/cron.d/cert-check
0 6 * * * root /usr/local/bin/check_certs.sh >> /var/log/cert-check.log 2>&1

# Или через systemd timer (/etc/systemd/system/cert-check.service)
[Unit]
Description=Certificate expiry check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check_certs.sh
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/cert-check.timer
[Unit]
Description=Daily certificate expiry check

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target

# systemd-реализация
sudo systemctl enable --now cert-check.timer
```

### Сценарий 19: Проверка сертификатов Kubernetes секретов

```bash
# Извлечение сертификата из Kubernetes Secret
kubectl get secret tls-secret -n default -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/tls.crt

# Проверка срока действия
openssl x509 -in /tmp/tls.crt -noout -dates -subject -issuer

# Проверка цепочки (если есть CA)
kubectl get secret ca-secret -n default -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/ca.crt
openssl verify -CAfile /tmp/ca.crt /tmp/tls.crt
```

### Сценарий 20: Валидация сертификатов в контейнерах

```bash
# Запуск openssl в контейнере (если на хосте нет)
docker run --rm -v "/path/to/cert.pem:/tmp/cert.pem" alpine/openssl \
  x509 -in /tmp/cert.pem -noout -text

# Проверка сертификата, смонтированного в контейнер
docker run --rm -v /etc/ssl/certs:/etc/ssl/certs alpine/openssl \
  s_client -connect example.com:443 -servername example.com -showcerts </dev/null

# Podman (без --rm, используйте --name для последующего удаления)
podman run --rm -v /tmp/tls.crt:/tmp/tls.crt alpine/openssl \
  x509 -in /tmp/tls.crt -noout -dates
```

### Сценарий 21: Падение SSL/TLS-соединений при смене времени

**Симптом:** HTTPS-сессии обрываются или завершаются ошибкой handshake, хотя сертификаты валидны и сервер доступен.

**Причины:**
- **Расхождение системных часов** — TLS строго проверяет временные метки `notBefore`/`notAfter`. Если часы сервера или клиента сильно отстают или опережают реальное время, сертификат может считаться просроченным или ещё не действительным.
- **Неправильно настроенный NTP** — без синхронизации часы расходятся, и handshake завершается с ошибкой.
- **Expired сертификаты** — просроченные сертификаты дополнительно усугубляют проблему, особенно на новых соединениях.

```bash
# Проверка системного времени
date
timedatectl status

# Проверка синхронизации NTP
chronyc tracking
# Или для systemd-timesyncd:
timedatectl show-timesync --all

# Проверка статуса NTP на сетевых устройствах
show ntp status

# Проверка логов NTP
journalctl -u chronyd --since "1 hour ago"

# Анализ TLS handshake
openssl s_client -connect <host>:443 -debug -msg

# Синхронизация времени
sudo chronyc makestep  # немедленная синхронизация
# или
sudo systemctl restart chronyd
```

**Решение:**
1. Проверьте синхронизацию времени: `timedatectl status` или `chronyc tracking`.
2. Если NTP не активен — включите и запустите службу: `systemctl enable --now chronyd` или `systemctl enable --now ntpd`.
3. Принудительно синхронизируйте время: `chronyc makestep` или `ntpd -gq`.
4. Проверьте сертификат на просрочку: `openssl x509 -in server.crt -noout -dates`.
5. Убедитесь, что на клиенте и сервере установлен одинаковый часовой пояс и NTP-источник.

### Сценарий 22: Диагностика TLS через testssl.sh

Для комплексной проверки используйте `testssl.sh`:

```bash
# Быстрая проверка (рекомендуется в production)
testssl.sh --fast https://example.com

# Полная проверка (долго, но детально)
testssl.sh https://example.com

# Только проверка сертификата и цепочки
testssl.sh -e -E https://example.com
```

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `openssl x509 -in cert.pem -noout -text` | Полный просмотр метаданных (SAN, AKI/SKI, Key Usage) | `openssl x509 -in server.crt -noout -text` |
| `openssl s_client -connect host:port -showcerts` | Вывод всех сертификатов, передаваемых сервером | `... -servername example.com </dev/null` |
| `openssl verify -CAfile ca-bundle.crt -untrusted intermediate.crt server.crt` | Верификация локальных файлов цепочки | `openssl verify -CAfile root.pem intermediate.pem` |
| `openssl s_client -connect host:port -brief` | Компактная сводка handshake (TLS 1.3+, OpenSSL 3.0+) | `... -servername example.com </dev/null` |
| `openssl s_client -starttls smtp -connect host:25` | Проверка STARTTLS для SMTP/POP3/IMAP | `openssl s_client -starttls smtp -connect mail:25` |
| `openssl x509 -in cert.pem -noout -checkend <seconds>` | Проверка, не истечёт ли сертификат через N секунд | `openssl x509 -in cert.pem -noout -checkend 86400` |
| `openssl pkey -in key.pem -pubout -outform DER \| openssl sha256` | Извлечение публичного ключа и хеширование | Для проверки key/cert match |
| `openssl x509 -in cert.pem -noout -fingerprint -sha256` | Отпечаток для сверки с CT-логами | `openssl x509 -in cert.pem -noout -fingerprint -sha256` |
| `openssl crl -in crl.pem -noout -text` | Просмотр CRL для проверки отзыва | `openssl crl -in ca/crl.pem -noout -text` |
| `openssl ocsp -issuer intermediate.pem -cert server.crt -url <OCSP_URL> -CAfile root.pem -resp_text` | Прямая проверка OCSP | `openssl ocsp -issuer int.pem -cert srv.crt -url http://ocsp.example.com` |
| `openssl verify -crl_check -CAfile ca.pem cert.pem` | Проверка с учётом CRL | `openssl verify -crl_check -CAfile ca.pem cert.pem` |
| `openssl s_client -connect host:port -status` | Проверка OCSP Stapling | `... -servername example.com </dev/null` |

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Verify return code: 21` (unable to verify) | Неполная цепочка или неизвестный CA | `openssl s_client -showcerts` — проверка количества сертификатов | Добавить промежуточный CA в `ssl_certificate` |
| `Verify return code: 10` (certificate expired) | Истёк срок действия | `openssl x509 -noout -enddate` | Перевыпустить сертификат |
| `certificate has expired or is not yet valid` | Расхождение часов (clock skew) или просроченный сертифект | `timedatectl status`, `date`, `openssl s_client -connect host:443` | Синхронизировать NTP (`chronyc makestep`), проверить `notBefore`/`notAfter` |
| `Verify return code: 18` (self-signed) | Самоподписанный сертификат | `openssl x509 -noout -issuer -subject` | Добавить CA в trust store или использовать публичный CA |
| `Verify return code: 62` (hostname mismatch) | SAN/CN не совпадают с доменом | `openssl x509 -noout -text \| grep -E "DNS:|Subject"` | Выпустить сертификат с корректным SAN |
| `handshake failure` | Несовпадение cipher suites или TLS версии | `openssl s_client -connect host:port -msg -debug` | Обновить конфигурацию шифров/версий на сервере |
| `Verify return code: 0 (ok)` (но сертификат просрочен) | Сертификат не прошёл проверку `notAfter` из-за неверного времени | `date`, `openssl x509 -noout -checkend 0` | Синхронизировать часы через NTP |
| OCSP response: no response sent | OCSP Stapling не настроен | `openssl s_client -status` | Настроить `ssl_stapling` в Nginx/Apache |
| `certificate revoked` | Сертификат отозван | `openssl verify -crl_check -CAfile ca-chain.crt cert.pem` | Прекратить использование сертификата, выпустить новый |
| `tlsv1 alert unknown ca` (mTLS) | Клиентский сертификат подписан неизвестным CA | `openssl s_client -cert client.crt -key client.key` | Добавить клиентский CA в `ssl_client_certificate` на сервере |
| `no shared cipher` | Клиент и сервер не имеют общих шифров | `openssl ciphers -v 'ALL:COMPLEMENTOFALL'` на обоих концах | Согласовать наборы шифров или версии TLS |
| `sops: no key found` | (если используется SOPS для управления ключами) | Проверить `SOPS_AGE_KEY_FILE` или `--age` флаг | Указать путь к key-файлу |

## Лучшие практики

### Предварительная проверка перед деплоем

Всегда выполняйте комплексную проверку перед установкой сертификата в production:

```bash
# 1. Проверка соответствия ключа и сертификата
openssl pkey -in service.key -pubout -outform DER | openssl sha256
openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
# Хеши должны совпасть

# 2. Проверка цепочки доверия
openssl verify -CAfile ca/ca.crt service.crt
# → service.crt: OK

# 3. Проверка срока действия
openssl x509 -in service.crt -noout -dates

# 4. Проверка SAN (обязательно для современных браузеров)
openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"
# → DNS:service.local, DNS:www.service.local, IP:10.0.0.5
```

### Безопасность при работе с утилитами

- **Никогда не передавайте приватный ключ CA по сети.** Все операции с `ca.key` выполняйте на машине, где хранится CA.
- **Храните `service.key` с правами `600`.** Утечка приватного ключа сервиса позволяет impersonation-атаки.
- **Проверяйте `issuer` перед установкой:** убедитесь, что сертификат выпущен именно вашим CA, а не публичным центром.
- **Используйте `-CAfile` явно:** не полагайтесь на системное хранилище CA в скриптах — указывайте корень явно.
- **Не используйте `-k` (insecure) в curl** для проверки сертификатов в production.

### Автоматизация в CI/CD

Для встраивания диагностики в пайплайны используйте неинтерактивные флаги:

```bash
# Неинтерактивная проверка цепочки
if openssl verify -CAfile ca/ca.crt service.crt | grep -q "OK"; then
    echo "Certificate chain is valid"
else
    echo "Certificate verification failed"
    exit 1
fi

# Проверка срока действия (если осталось меньше 30 дней — fail)
openssl x509 -in service.crt -noout -checkend 2592000 || {
    echo "CRITICAL: Certificate expires within 30 days"
    exit 1
}
```

## Очистка и ротация

### Удаление временных файлов диагностики

```bash
# Удаление временных сертификатов и ключей
rm -f service.crt service.key service.csr service.srl /tmp/tls.crt /tmp/ca.crt

# Удаление установленных корневых сертификатов из доверенных хранилищ ОС
# Debian/Ubuntu
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo update-ca-trust

# Очистка кэша сертификатов в контейнерах
docker system prune -a  # удаляет неиспользуемые образы с возможными сертификатами
```

### Откат тестового окружения

Если сертификат был установлен в приложение (Nginx, Apache, Java Keystore), выполните откат в обратном порядке:

1. Удалите сертификат из конфигурации сервиса.
2. Перезапустите сервис.
3. Удалите корневой сертификат из доверенного хранилища ОС/контейнера.
4. Удалите файлы CA и сгенерированные ключи.

### Ротация сертификатов

```bash
# 1. Генерация нового ключа и CSR
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out new.key
openssl req -new -key new.key -out new.csr -subj "/CN=example.com"

# 2. Подпись нового сертификата (если используется локальный CA)
openssl x509 -req -in new.csr -CA ca/ca.crt -CAkey ca/ca.key \
  -CAcreateserial -out new.crt -days 365 -sha256 \
  -extfile <(printf "subjectAltName=DNS:example.com,DNS:www.example.com")

# 3. Проверка нового сертификата
openssl verify -CAfile ca/ca.crt new.crt
openssl x509 -in new.crt -noout -dates

# 4. Замена в production (с health check)
# cp new.crt /etc/nginx/ssl/example.com.crt
# cp new.key /etc/nginx/ssl/example.com.key
# nginx -t && systemctl reload nginx
```

### Аварийная проверка подписи (MAC)

Если есть подозрение на компрометацию приватного ключа, проверьте целостность сертификата. Для сертификатов без CRL/OCSP используйте следующий подход:

```bash
# Проверка, что сертификат не был изменён после выпуска
# (это не защита от компрометации, а проверка целостности файла)
openssl x509 -in server.crt -noout -fingerprint -sha256
# Сравните с известным хорошим значением

# Аварийная проверка цепочки после подозрения на компрометацию
openssl verify -verbose -CAfile ca-bundle.crt server.crt
# Любая ошибка верификации требует немедленного анализа
```

Автоматизация ротации в k8s-окружениях — через **[cert-manager](../../Kubernetes/ToolsUtilities/cert_manager/installation.md)** или **[Certbot](https://certbot.eff.org/)** с Let's Encrypt.

## Дополнительная информация

### Сторонние инструменты

- **[SSL Labs Server Test](https://www.ssllabs.com/ssltest/)** — глубокий онлайн-анализ (оценка A+, проверка Chain Issues).
- **[testssl.sh](https://testssl.sh/)** — CLI-утилита для проверки любых портов на уязвимости и настройки TLS.
- **[Certigo](https://github.com/square/certigo)** — современный инструмент на Go для дампа и валидации сертификатов.
- **[ssllabs-scan](https://github.com/ssllabs/ssllabs-scan/)** — CLI для запуска SSL Labs проверок из вашей инфраструктуры.
- **[crt.sh](https://crt.sh/)** — поиск сертификатов в публичных CT-логах (для проверки issuance).

### Автоматизация через Ansible

Для встраивания диагностики в инфраструктуру как кода:

```yaml
---
- name: Check certificate expiry on remote hosts
  hosts: webservers
  tasks:
    - name: Fail if certificate expires within 30 days
      ansible.builtin.command: >
        echo | openssl s_client -connect {{ inventory_hostname }}:443
        -servername {{ inventory_hostname }} 2>/dev/null
        | openssl x509 -noout -checkend 2592000
      changed_when: false
      register: cert_check
      failed_when: cert_check.rc != 0
```

### Связанные темы

- **[PKI обзор](../Concepts/pki_overview.md)** — иерархия доверия, стандарты и форматы файлов.
- **[TLS Protocol](../../Networking/Protocols/tls.md)** — теория рукопожатия и шифрования.
- **[Nginx TLS Troubleshooting](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — специфика отладки в Nginx.
- **[Управление сертификатами CA (single-tier)](./openssl_ca/single_tier/service_certificate_management.md)** — формальный метод выпуска и отзова сертификатов.
- **[GPG и OpenPGP](../../Linux/Security/Tools/gpg_and_openpgp.md)** — PGP-шифрование (альтернатива PEM-сертификатам).