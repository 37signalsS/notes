# Диагностика SSL/TLS сертификатов

## Определения

**Цепочка доверия (Chain of Trust)** — последовательность сертификатов от конечного (серверного) узла до доверенного корневого центра (Root CA). Клиент проверяет подпись на каждом уровне; если хотя бы одно звено невалидно, доверие ко всей цепочке теряется.

**Incomplete chain** — ситуация, когда сервер не передаёт промежуточные сертификаты (Intermediate CA). Это приводит к ошибкам верификации у клиентов, чьё локальное хранилище не содержит этих промежуточных звеньев.

**Server Name Indication (SNI)** — расширение TLS, позволяющее клиенту передавать имя хоста (домен) в начале рукопожатия. Это необходимо для корректного выбора сертификата на серверах с несколькими виртуальными хостами на одном IP.

**OCSP Stapling** — механизм, при котором сервер сам запрашивает статус валидности своего сертификата у CA и «прикрепляет» подписанный ответ к handshake. Это ускоряет проверку для клиента и повышает его приватность.

**CA-хранилище (Trust Store)** — системный набор доверенных корневых и промежуточных сертификатов (например, `/etc/ssl/certs` в Linux).

**Mutual TLS (mTLS)** — режим взаимной аутентификации, при котором и клиент, и сервер предъявляют друг другу сертификаты. Используется для внутренних API, сервис-меш и Zero Trust архитектур.

**Certificate Transparency (CT)** — публичный реестр логов issuance сертификатов. Браузеры требуют наличия записей SCT (Signed Certificate Timestamp) для сертификатов, выданных публичными CA.

**CRL (Certificate Revocation List)** — подписанный список отозванных серийных номеров. Клиент проверяет наличие сертификата в CRL перед установкой доверия.

## Основные концепции

### Проверка срока действия сертификата

При проверке удаленного сервера обязательно используйте флаг `-servername`, чтобы избежать получения дефолтного сертификата сервера вместо целевого.

```bash
# Проверка удалённого сервера
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# notAfter=May 14 18:57:50 2026 GMT

# Проверка локального файла
openssl x509 -in server.crt -noout -enddate
```

**Важно:** Неверное системное время (рассинхронизация NTP) на стороне клиента или сервера часто является причиной ложных ошибок «Certificate Expired».

### Верификация цепочки и типичные ошибки

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

### Проверка соответствия ключа и сертификата

Перед установкой необходимо убедиться, что приватный ключ соответствует публичному ключу в сертификате.

**Для RSA (сравнение хешей модулей):**
```bash
openssl rsa -noout -modulus -in server.key | openssl sha256
openssl x509 -noout -modulus -in server.crt | openssl sha256
```

**Для ECDSA/Ed25519 (сравнение публичных ключей):**
```bash
# Извлечение из ключа
openssl pkey -in server.key -pubout -outform DER | openssl sha256
# Извлечение из сертификата
openssl x509 -in server.crt -pubkey -noout -outform DER | openssl sha256
```

### Анализ CSR и отпечатков

```bash
# Проверка содержимого запроса перед отправкой в CA
openssl req -in server.csr -noout -text

# Получение отпечатка (Fingerprint) для сверки (например, в логах CT)
openssl x509 -in server.crt -noout -fingerprint -sha256
```

### Управление системным trust store (Debian/Ubuntu/RHEL)

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

### Проверка соответствия приватного ключа и сертификата (md5/sha256)

```bash
# Быстрая проверка через md5
openssl rsa -noout -modulus -in server.key | openssl md5
openssl x509 -noout -modulus -in server.crt | openssl md5

# Для ECDSA ключей
openssl ec -noout -text -in server.key | grep "pub:" -A 5
openssl x509 -noout -text -in server.crt | grep "Subject Public Key:" -A 5
```

### Расширенная проверка SNI и виртуальных хостов

Для серверов с множеством доменов на одном IP недостаточно проверить только IP-адрес. Нужно явно указывать `-servername`:

```bash
# Проверка конкретного домена на общем IP
openssl s_client -connect 203.0.113.10:443 -servername app1.example.com </dev/null 2>&1 | grep "subject="

# Проверка альтернативного домена (должен вернуть другой сертификат)
openssl s_client -connect 203.0.113.10:443 -servername app2.example.com </dev/null 2>&1 | grep "subject="
```

## Практические сценарии

### Сценарий 1: Исправление «Incomplete chain» в Nginx

Ошибка означает, что клиент не может построить путь к корню. Чаще всего в `ssl_certificate` указан только файл самого сертификата без Intermediate CA.

**Неправильно:**
```nginx
ssl_certificate /path/example.com.crt; # Только Leaf-сертификат
```

**Правильно:**
```nginx
ssl_certificate /path/fullchain.pem;   # Leaf + Intermediate(s)
```
Подробнее о форматах цепочек см. в **[PKI Overview](../Concepts/pki_overview.md#форматы-файлов-и-стандарты)**.

### Сценарий 2: Ручная установка промежуточного и корневого сертификатов

Если системное CA-хранилище слишком старое, цепочку нужно восстановить вручную.

**Шаг 1: Получение ссылки на Intermediate CA из AIA:**
```bash
openssl s_client -connect target-site.ru:443 -servername target-site.ru </dev/null | \
  openssl x509 -noout -text | grep "CA Issuers"
# CA Issuers - URI:http://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt
```

**Шаг 2: Скачивание и конвертация (если формат DER):**
```bash
wget http://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt -O intermediate.crt
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

### Сценарий 3: Диагностика OCSP Stapling

Чтобы проверить, передает ли сервер статус отзыва в процессе рукопожатия:

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
# 2. Проверить firewall (UDP/443 часто блокируют)
# 3. Проверить наличие AIA в сертификате
openssl x509 -in server.crt -noout -text | grep -A 2 "Authority Information Access"

# Ручная проверка OCSP responder (прямой запрос)
openssl ocsp -issuer intermediate.pem -cert server.crt \
  -url http://ocsp.digicert.com -CAfile root.pem -resp_text
```

### Сценарий 4: Проверка поддержки версий TLS

В 2026 году рекомендуется использовать TLS 1.3.

```bash
# Проверка поддержки TLS 1.3
openssl s_client -connect example.com:443 -servername example.com -tls1_3

# Проверка TLS 1.2 (для совместимости)
openssl s_client -connect example.com:443 -servername example.com -tls1_2

# Перечисление всех поддерживаемых версий через nmap
nmap --script ssl-enum-ciphers -p 443 example.com
```

### Сценарий 5: Проверка HSTS и заголовков безопасности

```bash
curl -I https://example.com | grep -i "Strict-Transport-Security"
# Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

### Сценарий 6: Диагностика mTLS (взаимная аутентификация)

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

### Сценарий 7: Пакетная проверка сертификатов в инфраструктуре

Для SRE/Sysadmin практики часто требуется массовая проверка сроков действия сертификатов на множестве сервисов.

```bash
#!/usr/bin/env bash
# check_certs.sh — пакетная проверка сертификатов
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

### Сценарий 8: Мониторинг сертификатов через systemd / cron

Для production инфраструктуры используйте systemd-таймеры или cron для регулярной проверки:

```bash
# /etc/cron.d/cert-check
0 6 * * * root /usr/local/bin/check_certs.sh >> /var/log/cert-check.log 2>&1

# Или через systemd timer (/etc/systemd/system/cert-check.timer)
[Unit]
Description=Daily certificate expiry check

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

### Сценарий 9: Deep inspection — перечисление cipher suites и протоколов

```bash
# Быстрое перечисление поддерживаемых cipher suites (требует nmap)
nmap --script ssl-enum-ciphers -p 443 example.com

# Проверка конкретного cipher suite через openssl
openssl s_client -connect example.com:443 -servername example.com -cipher 'ECDHE+AESGCM:ECDHE+CHACHA20' -brief </dev/null

# Проверка ALPN (необходим для HTTP/2)
openssl s_client -connect example.com:443 -servername example.com -alpn h2,http/1.1 </dev/null 2>&1 | grep "ALPN"
# ALPN protocol: h2
```

### Сценарий 10: Проверка отзыва через CRL

```bash
# Получение CRL из сертификата
openssl x509 -in server.crt -noout -text | grep -A 4 "CRL Distribution"

# Проверка статуса отзыва (требует openssl 1.1.1+)
openssl verify -crl_check -CAfile ca-chain.crt -untrusted intermediate.crt server.crt
# server.crt: OK (CRL проверен)
```

### Сценарий 11: Проверка записей Certificate Transparency (CT)

```bash
# Получение отпечатка сертификата и проверка в CT-логах
fingerprint=$(openssl x509 -in server.crt -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')

# Проверка через crt.sh (curl)
curl -s "https://crt.sh/?q=${fingerprint}&output=json" | jq length

# Если возвращается 0 — сертификат не найден в публичных CT-логах (потенциальная проблема для браузеров)
```

### Сценарий 12: Устранение неполадок mTLS в Nginx

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

### Сценарий 13: Диагностика TLS через testssl.sh

Для комплексной проверки используйте `testssl.sh`:

```bash
# Быстрая проверка (рекомендуется в production)
testssl.sh --fast https://example.com

# Полная проверка (долго, но детально)
testssl.sh https://example.com

# Только проверка сертификата и цепочки
testssl.sh -e -E https://example.com
```

### Сценарий 14: Проверка сертификатов Kubernetes секретов

```bash
# Извлечение сертификата из Kubernetes Secret
kubectl get secret tls-secret -n default -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/tls.crt

# Проверка срока действия
openssl x509 -in /tmp/tls.crt -noout -dates -subject -issuer

# Проверка цепочки (если есть CA)
kubectl get secret ca-secret -n default -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/ca.crt
openssl verify -CAfile /tmp/ca.crt /tmp/tls.crt
```

### Сценарий 15: Валидация сертификатов в контейнерах

```bash
# Запуск openssl в контейнере (если на хосте нет)
docker run --rm -v /etc/ssl/certs:/etc/ssl/certs alpine/openssl s_client -connect example.com:443 -servername example.com </dev/null

# Проверка сертификата, смонтированного в контейнер
docker run --rm -v /path/to/cert.pem:/tmp/cert.pem alpine/openssl \
  x509 -in /tmp/cert.pem -noout -text -noout
```

## Дополнительная информация

### Полезные команды OpenSSL

- `openssl x509 -in cert.pem -noout -text` — полный просмотр метаданных (SAN, AKI/SKI, Key Usage).
- `openssl s_client -connect host:port -showcerts` — вывод всех сертификатов, передаваемых сервером (анализ бандла).
- `openssl verify -CAfile ca-bundle.crt -untrusted intermediate.crt server.crt` — верификация локальных файлов цепочки.
- `openssl s_client -connect host:port -brief` — компактная сводка handshake (TLS 1.3+, OpenSSL 1.1.1+).
- `openssl s_client -connect host:port -debug -msg` — пошаговая отладка handshake (для глубокой диагностики).
- `openssl x509 -in cert.pem -noout -fingerprint -sha256` — отпечаток для сверки с CT-логами.
- `openssl crl -in crl.pem -noout -text` — просмотр CRL для проверки отзыва.
- `openssl ocsp -issuer intermediate.pem -cert server.crt -url <OCSP_URL> -CAfile root.pem` — прямая проверка OCSP.
- `openssl verify -crl_check -CAfile ca.pem cert.pem` — проверка с учётом CRL.

### Сторонние инструменты

- **[SSL Labs Server Test](https://www.ssllabs.com/ssltest/)** — глубокий онлайн-анализ (оценка A+, проверка Chain Issues).
- **[testssl.sh](https://testssl.sh/)** — CLI-утилита для проверки любых портов на уязвимости и настройки TLS.
- **[Certigo](https://github.com/square/certigo)** — современный инструмент на Go для дампа и валидации сертификатов.
- **[ssllabs-scan](https://github.com/ssllabs/ssllabs-scan/)** — CLI для запуска SSL Labs проверок из вашей инфраструктуры.
- **[crtsh](https://crt.sh/)** — поиск сертификатов в публичных CT-логах (для проверки issuance).

### Устранение неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Verify return code: 21` (unable to verify) | Неполная цепочка или неизвестный CA | `openssl s_client -showcerts` — проверка количества сертификатов | Добавить промежуточный CA в `ssl_certificate` |
| `Verify return code: 10` (certificate expired) | Истёк срок действия | `openssl x509 -enddate` | Перевыпустить сертификат |
| `Verify return code: 18` (self-signed) | Самоподписанный сертификат | `openssl x509 -noout -issuer -subject` | Добавить CA в trust store или использовать публичный CA |
| `Verify return code: 62` (hostname mismatch) | SAN/CN не совпадают с доменом | `openssl x509 -noout -text | grep -E "DNS:|Subject"` | Выпустить сертификат с корректным SAN |
| `handshake failure` | Несовпадение cipher suites или TLS версии | `openssl s_client -connect host:port -msg -debug` | Обновить конфигурацию шифров/версий на сервере |
| OCSP response: no response sent | OCSP Stapling не настроен | `openssl s_client -status` | Настроить `ssl_stapling` в Nginx/Angie |
| `certificate revoked` | Сертификат отозван | `openssl verify -crl_check` | Прекратить использование сертификата |
| `tlsv1 alert unknown ca` (mTLS) | Клиентский сертификат подписан неизвестным CA | `openssl s_client -cert client.crt -key client.key` | Добавить клиентский CA в `ssl_client_certificate` |

### Автоматизация через Ansible

```yaml
- name: Check certificate expiry on remote hosts
  hosts: webservers
  tasks:
    - name: Get certificate expiry date
      command: >
        echo | openssl s_client -connect {{ inventory_hostname }}:443
        -servername {{ inventory_hostname }} 2>/dev/null
        | openssl x509 -noout -enddate
      register: cert_expiry
      changed_when: false

    - name: Fail if certificate expires within 30 days
      fail:
        msg: "Certificate on {{ inventory_hostname }} expires soon!"
      when: >
        (cert_expiry.stdout | regex_search('notAfter=(.*) GMT', '\\1') | 
         to_datetime('%b %d %H:%M:%S %Y %Z')).timestamp() < 
        (ansible_date_time.iso8601 | to_datetime('%Y-%m-%dT%H:%M:%SZ')).timestamp() + 2592000
```

### Связанные темы

- **[PKI Overview](../Concepts/pki_overview.md)** — иерархия доверия и стандарты.
- **[TLS Protocol](../../Networking/Protocols/tls.md)** — теория рукопожатия и шифрования.
- **[Nginx TLS Troubleshooting](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — специфика отладки в Nginx.
- **[Certificate Automation](../../Ansible/ansible_certificate_management.md)** — автоматизация выдачи и ротации через Ansible.
- **[Утилиты и диагностика OpenSSL CA](./openssl_ca/single_tier/common_utilities.md)** — расширенные команды для проверки TLS-серверов.
