# Алгоритм диагностики проблем с сертификатами

## Определения

**Цепочка доверия (Chain of Trust)** — последовательность сертификатов от конечного (leaf) до корневого (Root CA), позволяющая клиенту верифицировать подлинность серверного сертификата. В двухуровневой архитектуре цепочка: leaf → Intermediate CA → Root CA.

**SNI (Server Name Indication)** — расширение протокола TLS, позволяющее клиенту указать имя сервера на этапе handshake. Это позволяет отдавать разные сертификаты для разных доменов на одном IP-адресе.

**OCSP Stapling** — механизм, при котором TLS-сервер сам запрашивает статус отзыва сертификата у OCSP-резпондента и отдаёт его клиенту «встык» (staple), снижая латентность и защищая приватность клиента.

**CRL (Certificate Revocation List)** — список серийных номеров отозванных сертификатов, подписанный CA. Проверяется клиентами для подтверждения актуальности сертификата.

> Базовые понятия PKI описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Архитектура двухуровневого CA — в **[обзоре двухуровневого CA](./overview.md)**.

## Базовые концепции

### Методология диагностики

Диагностика проблем с сертификатами в двухуровневой архитектуре строится по принципу «снизу вверх» (Bottom-Up): сначала проверяется сам сертификат, затем цепочка доверия, далее — сетевое подключение и конфигурация сервера.

**Ключевой принцип:** в двухуровневой схеме 90% ошибок связаны с неполной цепочкой сертификатов (отсутствует Intermediate CA в `ca-chain.crt`) или неверным порядком сертификатов в bundle.

### Категории ошибок

| Категория | Типичные симптомы | Частота в production |
|:---|:---|:---|
| **Цепочка доверия** | `unable to verify the first certificate`, `unable to get local issuer certificate` | Очень высокая |
| **Срок действия** | `certificate has expired`, `certificate is not yet valid` | Высокая |
| **SAN / DN** | `SSL: CERTIFICATE_VERIFY_FAILED`, браузер отклоняет сертификат | Средняя |
| **Совместимость алгоритмов** | `handshake failure`, `no suitable cipher suites` | Низкая (чаще при legacy) |
| **Сетевые проблемы** | `connection refused`, `timeout`, `SSL_connect: Connection reset` | Средняя |
| **Ключ и сертификат** | Сертификат отклоняется, ключ не подходит | Низкая |

## Практические сценарии

### Алгоритм 1: Клиент отклоняет сертификат (Общий flowchart)

```
Сертификат отклоняется клиентом
│
├─ Шаг 1: Проверка срока действия
│  └─ openssl x509 -in service.crt -noout -checkend 0
│     ├─ ОК → срок не истёк, переходим к шагу 2
│     └─ ОШИБКА → сертификат просрочен или ещё не действителен
│        ├─ Просрочен → перевыпустить сертификат
│        └─ Ещё не действителен → проверить clock sync (NTP)
│
├─ Шаг 2: Проверка SAN
│  └─ openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"
│     ├─ SAN присутствует и совпадает с именем сервера → переходим к шагу 3
│     └─ SAN отсутствует или не совпадает → перевыпустить с корректным SAN
│
├─ Шаг 3: Проверка цепочки (самый частый случай)
│  └─ openssl s_client -connect host:443 -servername host </dev/null 2>&1 | grep "Verify return code"
│     ├─ "Verify return code: 0 (ok)" → проблема не в цепочке
│     ├─ code: 20 (unable to get local issuer) → Root CA отсутствует в trust store клиента
│     │  └─ Решение: установить ca.crt в хранилище ОС/контейнера
│     ├─ code: 21 (unable to verify the first certificate) → сервер не отдаёт Intermediate CA
│     │  └─ Решение: настроить fullchain (leaf + intermediate)
│     └─ code: 19 (self signed certificate in chain) → в цепочке самоподписанный промежуточный
│        └─ Решение: проверить порядок в ca-chain.crt (intermediate сверху, root снизу)
│
├─ Шаг 4: Проверка порядка в bundle
│  └─ openssl crl2pkcs7 -nocrl -certfile ca-chain.crt | pkcs7 -print_certs -noout | grep "subject="
│     ├─ Первый: Intermediate CA, Второй: Root CA → порядок верный
│     └─ Порядок нарушён → пересобрать ca-chain.crt
│
└─ Шаг 5: Проверка соответствия ключа и сертификата
   └─ openssl x509 -noout -modulus -in service.crt | openssl sha256
      openssl rsa -noout -modulus -in service.key | openssl sha256
      ├─ Хеши совпадают → ключ соответствует сертификату
      └─ Хеши различаются → перевыпустить пару ключ-сертификат
```

### Алгоритм 2: Ошибка `unable to get local issuer certificate` (code: 20)

Эта ошибка означает, что клиент не может найти颁发者 (issuer) для проверяемого сертификата.

**Диагностика:**

```bash
# 1. Определить issuer сертификата
openssl x509 -in service.crt -noout -issuer
# → issuer=CN = My Private Intermediate CA, O = My Corp, C = RU

# 2. Проверить, отдаёт ли сервер промежуточный сертификат
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null 2>&1 | grep -E "s:|i:"
# → s:/CN=my-service.local
# → i:/CN=My Private Intermediate CA
# → i:/CN=My Private Root CA

# 3. Если сервер отдаёт только leaf — проблема в конфигурации сервера
# 4. Если Intermediate отдаётся — проблема в trust store клиента
```

**Решения:**

| Ситуация | Решение |
|:---|:---|
| Сервер отдаёт только leaf-сертификат | Настроить `ssl_certificate /path/to/fullchain.pem` (leaf + intermediate) |
| Intermediate отдаётся, но Root отсутствует в trust store | Установить `ca.crt` в системное хранилище или передать через `-CAfile` |
| Неверный порядок в bundle | Пересобрать `ca-chain.crt`: сначала intermediate, потом root |

**Установка Root CA в доверенные хранилища:**

```bash
# Debian/Ubuntu
sudo cp root-ca/ca.crt /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates

# RHEL/CentOS/Fedora
sudo cp root-ca/ca.crt /etc/pki/ca-trust/source/anchors/my-private-ca.crt
sudo update-ca-trust

# Alpine
sudo cp root-ca/ca.crt /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates

# macOS
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root-ca/ca.crt
```

### Алгоритм 3: Ошибка `unable to verify the first certificate` (code: 21)

Эта ошибка означает, что сервер отправляет только leaf-сертификат без промежуточного CA.

**Быстрая проверка:**

```bash
# Посмотреть, какие сертификаты отдаёт сервер
openssl s_client -connect my-service.local:443 -showcerts </dev/null 2>&1 | grep -c "BEGIN CERTIFICATE"
# → 1 (только leaf — ошибка)
# → 2 или больше (leaf + intermediate — норма)
```

**Решение для разных серверов:**

```nginx
# Nginx: указать fullchain (leaf + intermediate)
ssl_certificate     /etc/nginx/ssl/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/service.key;
```

```apache
# Apache: указать полную цепочку
SSLCertificateFile      /etc/ssl/certs/service.crt
SSLCertificateKeyFile   /etc/ssl/private/service.key
SSLCertificateChainFile /etc/ssl/certs/ca-chain.crt
```

```haproxy
# HAProxy: объединить leaf и intermediate в один файл
# cat service.crt intermediate-ca/intermediate.crt > /etc/haproxy/certs/fullchain.pem
bind *:443 ssl crt /etc/haproxy/certs/fullchain.pem
```

### Алгоритм 4: Проверка срока действия удалённого сертификата

```bash
#!/usr/bin/env bash
HOST="$1"
PORT="${2:-443}"
DAYS_WARN="${3:-30}"

EXP_DATE=$(echo | openssl s_client -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null \
  | cut -d= -f2)

if [ -z "$EXP_DATE" ]; then
  echo "FAIL: $HOST не отвечает или не предоставляет сертификат"
  exit 1
fi

EXP_EPOCH=$(date -d "$EXP_DATE" +%s 2>/dev/null || date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 0 ]; then
  echo "CRITICAL: $HOST сертификат просрочен на $(( -DAYS_LEFT )) дней"
  exit 2
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: $HOST сертификат истекает через $DAYS_LEFT дней"
  exit 1
else
  echo "OK: $HOST сертификат действителен ещё $DAYS_LEFT дней"
  exit 0
fi
```

### Алгоритм 5: Диагностика mTLS

```bash
# 1. Проверка, запрашивает ли сервер клиентский сертификат
openssl s_client -connect my-service.local:443 -servername my-service.local </dev/null 2>&1 | grep "Acceptable client certificate CA names"
# → Если строка присутствует — сервер запрашивает клиентский сертификат

# 2. Тест mTLS с клиентским сертификатом
openssl s_client -connect my-service.local:443 -servername my-service.local \
    -cert client.crt -key client.key \
    -CAfile intermediate-ca/ca-chain.crt </dev/null 2>&1 | grep "Verify return code"
# → Verify return code: 0 (ok) — mTLS работает

# 3. Если ошибка — проверить, подписан ли клиентский сертификат тем же CA
openssl x509 -in client.crt -noout -issuer
# → issuer=CN = My Private Intermediate CA (должен совпадать с issuer серверного сертификата)
```

### Алгоритм 6: Диагностика TLS-хэндшэйка

```bash
# Полный вывод TLS-хэндшэйка для анализа
openssl s_client -connect my-service.local:443 -servername my-service.local -tlsextdebug </dev/null 2>&1

# Проверка поддерживаемых версий TLS
# TLS 1.3
openssl s_client -connect my-service.local:443 -tls1_3 </dev/null 2>&1 | head -5
# → Protocol  : TLSv1.3 (если поддерживается)

# TLS 1.2
openssl s_client -connect my-service.local:443 -tls1_2 </dev/null 2>&1 | head -5
# → Protocol  : TLSv1.2 (если поддерживается)

# Проверка шифрового набора
openssl s_client -connect my-service.local:443 </dev/null 2>&1 | grep "Cipher    :"
# → Cipher    : TLS_AES_256_GCM_SHA384 (TLS 1.3)
# → Cipher    : ECDHE-RSA-AES256-GCM-SHA384 (TLS 1.2)
```

## Типичные ошибки и решения

### Таблица быстрого поиска

| Ошибка | Код | Вероятная причина | Решение |
|:---|:---|:---|:---|
| `unable to get local issuer certificate` | 20 | Root CA отсутствует в trust store | Установить `ca.crt` в хранилище ОС |
| `unable to verify the first certificate` | 21 | Сервер не отдаёт Intermediate CA | Настроить `fullchain.pem` |
| `certificate has expired` | 10 | Сертификат просрочен | Перевыпустить сертификат |
| `certificate is not yet valid` | 12 | Системные часы сбиты или сертификат ещё не активен | Проверить NTP, дождаться `notBefore` |
| `self signed certificate in chain` | 19 | Неверный порядок в bundle или самоподписанный intermediate | Проверить `ca-chain.crt`, перевыпуск intermediate |
| `certificate signature failure` | 7 | Повреждён сертификат или неверный ключ | Перевыпустить, проверить целостность файла |
| `depth 0 self signed` | 18 | Клиент видит только leaf без chain | Передать `-CAfile ca-chain.crt` |
| `handshake failure` | — | Нет общих шифров/протоколов | Проверить `ssl_protocols` и `ssl_ciphers` |
| `wrong version number` | — | Сервер не использует TLS (или неверный порт) | Проверить `listen 443 ssl` |
| `no protocols available` | — | OpenSSL не поддерживает запрошенный протокол | Обновить OpenSSL или изменить `-tls1_3` флаг |

### Частые ошибки при настройке в Nginx

```nginx
# НЕПРАВИЛЬНО: только leaf-сертификат
ssl_certificate     /etc/nginx/ssl/service.crt;

# ПРАВИЛЬНО: fullchain (leaf + intermediate)
ssl_certificate     /etc/nginx/ssl/fullchain.pem;

# НЕПРАВИЛЬНО: нет SSL на порту 443
listen 443;

# ПРАВИЛЬНО: SSL включён
listen 443 ssl;

# НЕПРАВИЛЬНО: не указаны протоколы
# (OpenSSL 3.x по умолчанию может включить legacy)

# ПРАВИЛЬНО: явное указание протоколов
ssl_protocols TLSv1.2 TLSv1.3;
```

### Частые ошибки при настройке в Apache

```apache
# НЕПРАВИЛЬНО: chain указан отдельно, но не объединён с leaf
SSLCertificateFile      /etc/ssl/certs/service.crt
SSLCertificateChainFile /etc/ssl/certs/ca-chain.crt
# Это работает, но многие клиенты предпочитают fullchain

# ПРАВИЛЬНО для совместимости: полная цепочка в SSLCertificateFile
SSLCertificateFile      /etc/ssl/certs/fullchain.pem
SSLCertificateKeyFile   /etc/ssl/private/service.key
```

## Сценарии: быстрая диагностика

### Сценарий 1: «Браузер отклоняет сертификат для внутреннего сервиса»

```bash
# 1. Проверка через curl (исключает кэш браузера)
curl -v https://my-service.local/ 2>&1 | grep -E "SSL|certificate|issuer|expire"

# 2. Проверка через openssl
openssl s_client -connect my-service.local:443 -servername my-service.local </dev/null 2>&1 | grep -E "Verify|expire|subject|issuer"

# 3. Если "unable to get local issuer" — установить Root CA
# 4. Если "unable to verify the first" — добавить Intermediate CA на сервер
```

### Сценарий 2: «Сервис не запускается, ругается на сертификат»

```bash
# 1. Проверка, что ключ и сертификат соответствуют
openssl x509 -noout -modulus -in /etc/ssl/service.crt | openssl sha256
openssl rsa -noout -modulus -in /etc/ssl/service.key | openssl sha256
# → Хеши должны совпадать

# 2. Проверка прав доступа
ls -la /etc/ssl/service.key
# → -rw------- 1 root root ... (permissions 600)

# 3. Проверка, что intermediate ключ не зашифрован (для автоматического запуска)
openssl rsa -in /etc/ssl/service.key -check -noout 2>&1
# → Если запрашивает пароль — ключ зашифрован, что может блокировать автозапуск
```

### Сценарий 3: «curl работает, но приложение не работает»

```bash
# Приложение может использовать собственное хранилище CA
# Java
keytool -list -cacerts -storepass changeit | grep my-ca

# Python requests
python3 -c "import ssl; print(ssl.get_default_verify_paths())"

# Go
# Указать CA через переменную окружения
export SSL_CERT_FILE=/etc/ssl/ca-chain.crt
```

## Рекомендации и лучшие практики

### Предварительная проверка перед деплоем

```bash
# Чек-лист (копипастable):
# 1. Срок действия
openssl x509 -in service.crt -noout -checkend 2592000 || echo "WARN: < 30 дней"

# 2. SAN
openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"

# 3. Цепочка
openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt

# 4. Соответствие ключа
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256

# 5. Расширения (для leaf)
openssl x509 -in service.crt -noout -text | grep -A 3 "Basic Constraints"
# → basicConstraints = CA:FALSE (для leaf)
# → basicConstraints = CA:TRUE, pathlen:0 (для Intermediate)
```

### Автоматизация проверки в CI/CD

```bash
#!/bin/bash
set -euo pipefail

SERVICE_CRT="${1:?Укажите путь к сертификату}"
CA_CHAIN="${2:-intermediate-ca/ca-chain.crt}"
MIN_DAYS="${3:-30}"

# Проверка 1: срок действия
if ! openssl x509 -in "$SERVICE_CRT" -noout -checkend $((MIN_DAYS * 86400)); then
    echo "FAIL: сертификат истекает менее чем через $MIN_DAYS дней"
    exit 1
fi

# Проверка 2: цепочка
if ! openssl verify -CAfile "$CA_CHAIN" "$SERVICE_CRT" | grep -q "OK"; then
    echo "FAIL: ошибка верификации цепочки"
    exit 1
fi

# Проверка 3: SAN
if ! openssl x509 -in "$SERVICE_CRT" -noout -text | grep -q "Subject Alternative Name"; then
    echo "FAIL: отсутствует SAN"
    exit 1
fi

echo "OK: все проверки пройдены"
```

## Ограничения и крайние случаи

- **Самоподписанные (self-signed) сертификаты:** OpenSSL всегда помечает их как `self signed`. Для тестовых сред используйте ваш внутренний CA, а не self-signed.
- **Wildcard-сертификаты:** покрывают только один уровень поддоменов (`*.service.local` покрывает `api.service.local`, но не `a.api.service.local`).
- **Легаси-клиенты:** некоторые старые Java-приложения (до Java 8) не поддерживают SAN и требуют RSA-ключей. В этом случае потребуется отдельный сертификат.
- **clock skew:** если часы на клиенте или сервере сильно отклонены, проверка `notBefore`/`notAfter` может завершиться ошибкой. Убедитесь, что NTP работает на обоих узлах.

## Дополнительная информация

### Связанные темы

- **[Утилиты и диагностика](./common_utilities.md)** — полный набор диагностических команд OpenSSL.
- **[Управление сертификатами сервисов](./service_certificate_management.md)** — выпуск, ротация и отзыв сертификатов.
- **[Диагностика SSL-сертификатов](../../ssl_certificate_diagnostics.md)** — расширенные методы поиска ошибок.
- **[TLS-протокол](../../../Networking/Protocols/tls.md)** — теория TLS, cipher suites, handshake.
- **[Nginx TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — диагностика TLS в Nginx.
