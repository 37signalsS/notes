# Алгоритм диагностики проблем с сертификатами

**Актуально для:** OpenSSL 3.0+

## Определения

**Root CA (Корневой центр сертификации)** — верхний узел иерархии PKI. Самоподписанный сертификат с `basicConstraints = CA:TRUE`, используемый исключительно для подписи Intermediate CA. Его приватный ключ хранится в офлайне (air-gapped) и является наиболее критичным активом инфраструктуры.

**Intermediate CA (Промежуточный центр сертификации)** — подчинённый Root CA, сертификат которого подписан корневым. В двухуровневой архитектуре отвечает за выпуск всех конечных сертификатов. Изоляция Root CA ограничивает ущерб при компрометации: достаточно отозвать Intermediate, а не перевыпускать всю PKI.

**Leaf certificate (Конечный сертификат)** — сертификат конечного субъекта (веб-сервер, клиент, сервис), подписанный Intermediate CA. В цепочке доверия находится на самом нижнем уровне (depth 0).

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая и подписывающая сертификаты в рамках PKI.

**ca-chain.crt (Bundle)** — PEM-файл, содержащий сертификаты Intermediate CA и Root CA в строгом порядке: сначала Intermediate, затем Root. TLS-серверы обязаны передавать этот bundle клиентам для построения полной цепочки доверия.

**Chain of Trust (Цепочка доверия)** — последовательность сертификатов от конечного (leaf) до корневого (Root CA), позволяющая клиенту верифицировать подлинность серверного сертификата. В двухуровневой архитектуре цепочка: leaf → Intermediate CA → Root CA.

**SNI (Server Name Indication)** — расширение протокола TLS, позволяющее клиенту указать имя сервера на этапе handshake. Это позволяет отдавать разные сертификаты для разных доменов на одном IP-адресе.

**OCSP Stapling** — механизм, при котором TLS-сервер сам запрашивает статус отзова сертификата у OCSP-респондента и отдаёт его клиенту «встык» (staple), снижая латентность и защищая приватность клиента.

**CRL (Certificate Revocation List, Список отозванных сертификатов)** — список серийных номеров отозванных сертификатов, подписанный CA. Клиенты проверяют сертификаты по этому списку для подтверждения их актуальности.

**CSR (Certificate Signing Request, Запрос на подпись сертификата)** — структура X.509, содержащая публичный ключ и DN субъекта, подписанная закрытым ключом. Используется для запроса сертификата к CA.

**mTLS (Mutual TLS, Взаимный TLS)** — механизм взаимной аутентификации, требующий наличия сертификатов как у сервера, так и у клиента. В двухуровневой схеме mTLS реализуется через промежуточные CA.

**Basic Constraints** — расширение X.509, определяющее, является ли субъект CA (`CA:TRUE/FALSE`), и ограничение длины пути (`pathlen`). Для Intermediate CA: `CA:TRUE, pathlen:0`; для leaf: `CA:FALSE`.

**OpenSSL 3.0+** — криптографический тулсет с модульной архитектурой провайдеров (Default, Legacy, FIPS). Команда `openssl rsa` находится в maintenance mode — используйте `openssl pkey`. Команда `pkcs7` устарела (deprecated), но функционирует. Полная поддержка NIST PQC (ML-KEM/ML-DSA/SLH-DSA) доступна, начиная с OpenSSL 3.5.

> Базовые понятия PKI (X.509, CSR, алгоритмы 2026, PQC, расширения) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Архитектура двухуровневого CA — в **[обзоре двухуровневого CA](./overview.md)**. Полный набор диагностических команд OpenSSL и справочник по кодам verify return code — в **[Утилиты и диагностика](./common_utilities.md)**.

## Базовые концепции

### Методология диагностики

Диагностика проблем с сертификатами в двухуровневой архитектуре строится по принципу «снизу вверх» (Bottom-Up): сначала проверяется сам сертификат, затем цепочка доверия, далее — сетевое подключение и конфигурация сервера.

**Ключевой принцип:** в двухуровневой схеме 90% ошибок связаны с неполной цепочкой сертификатов (отсутствует Intermediate CA в `ca-chain.crt`) или неверным порядком сертификатов в bundle.

### Категории ошибок

| Категория | Типичные симптомы | Частота в production |
|:---|:---|:---|
| **Цепочка доверия** | `unable to verify the first certificate`, `unable to get local issuer certificate` | Очень высокая |
| **Срок действия** | `certificate has expired`, `certificate is not yet valid` | Высокая |
| **Отзов сертификата** | `certificate has been revoked` | Средняя |
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
│     ├─ code: 19 (self signed certificate in chain) → в цепочке самоподписанный промежуточный
│     │  └─ Решение: проверить порядок в ca-chain.crt (intermediate сверху, root снизу)
│     └─ code: 11 (certificate has been revoked) → сертификат отозван
│        └─ Решение: проверить CRL/OCSP, перевыпустить сертификат
│
├─ Шаг 4: Проверка порядка в bundle
│  └─ openssl crl2pkcs7 -nocrl -certfile ca-chain.crt | openssl pkcs7 -print_certs -noout | grep "subject="
│     ├─ Первый: Intermediate CA, Второй: Root CA → порядок верный
│     └─ Порядок нарушён → пересобрать ca-chain.crt
│     Примечание: команда `pkcs7` устарела в OpenSSL 3.0+ (выдаёт warning, но работает)
│
└─ Шаг 5: Проверка соответствия ключа и сертификата
   └─ # Универсальный метод для RSA, ECDSA, Ed25519 (OpenSSL 3.x):
      openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
      openssl pkey -in service.key -pubout -outform DER | openssl sha256
      ├─ Хеши совпадают → ключ соответствует сертификату
      └─ Хеши различаются → перевыпустить пару ключ-сертификат
```

### Алгоритм 2: Ошибка `unable to get local issuer certificate` (code: 20)

Эта ошибка означает, что клиент не может найти颁发итель (issuer) для проверяемого сертификата.

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

# Windows Server
certutil -addstore -f "Root" root-ca\ca.crt

# Docker-контейнер (Debian/Ubuntu/Alpine-based)
# В Dockerfile:
COPY root-ca/ca.crt /usr/local/share/ca-certificates/my-private-ca.crt
RUN update-ca-certificates
# Или в runtime:
docker run -v /path/to/ca.crt:/usr/local/share/ca-certificates/ca.crt:ro my-service \
    sh -c "cp /usr/local/share/ca-certificates/ca.crt /usr/local/share/ca-certificates/ && update-ca-certificates"

# Приложения с собственным trust store:
export SSL_CERT_FILE=/path/to/ca-chain.crt   # Go, curl, Python
```

### Алгоритм 3: Ошибка `unable to verify the first certificate` (code: 21)

Эта ошибка означает, что сервер отправляет только leaf-сертификат без промежуточного CA.

**Быстрая проверка:**

```bash
# Посмотреть, какие сертификаты отдаёт сервер
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null 2>&1 | grep -c "BEGIN CERTIFICATE"
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

# date -j -f (BSD/macOS) пробуется первым, fallback на date -d (GNU/Linux)
EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
            date -d "$EXP_DATE" +%s 2>/dev/null)
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

Этот скрипт работает как на Linux (GNU `date`), так и на macOS/BSD (`date -j -f`) — порядок пробует BSD-синтаксис в первую очередь с fallback на GNU. Для SRE: добавьте в cron для ежедневной проверки, настройте алёртинг в Slack/Telegram/PagerDuty при достижении критического порога. Интеграция с Prometheus Blackbox Exporter поддерживает проверку `server_name` для внутренних доменов — см. [обзор PKI](../../../Concepts/pki_overview.md).

### Алгоритм 5: Диагностика mTLS

```bash
# 1. Проверка, запрашивает ли сервер клиентский сертификат
openssl s_client -connect my-service.local:443 -servername my-service.local </dev/null 2>&1 | grep "Acceptable client certificate CA names"
# → Если строка присутствует — сервер запрашивает клиентский сертификат

# 2. Проверка, что сервер доверяет вашему Intermediate CA
openssl s_client -connect my-service.local:443 -servername my-service.local </dev/null 2>&1 | grep -A 10 "Acceptable client certificate CA names"
# → В списке должен присутствовать ваш Intermediate CA

# 3. Тест mTLS с клиентским сертификатом
openssl s_client -connect my-service.local:443 -servername my-service.local \
    -cert client.crt -key client.key \
    -CAfile intermediate-ca/ca-chain.crt </dev/null 2>&1 | grep "Verify return code"
# → Verify return code: 0 (ok) — mTLS работает

# 4. Если ошибка — проверить, подписан ли клиентский сертификат тем же CA
openssl x509 -in client.crt -noout -issuer
# → issuer=CN = My Private Intermediate CA (должен совпадать с issuer серверного сертификата)

# 5. Проверка отзова клиентского сертификата (CRL)
openssl verify -crl_check -CAfile root-ca/ca.crt -untrusted intermediate-ca/intermediate.crt client.crt
# → client.crt: OK (если не отозван)
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

### Алгоритм 7: Проверка отзова сертификата (CRL / OCSP)

В двухуровневой схеме сертификат может быть отозван. Диагностика включает проверку CRL и OCSP.

```bash
# 1. Проверка наличия CDP (CRL Distribution Point) и AIA (Authority Information Access) в сертификате
openssl x509 -in service.crt -noout -text | grep -A 1 "CRL Distribution Point"
openssl x509 -in service.crt -noout -text | grep -A 1 "Authority Information Access"
# → Если секция отсутствует — CRL/OCSP не будут работать

# 2. Скачивание и проверка CRL
CRL_URL=$(openssl x509 -in service.crt -noout -text \
  | grep -A 1 "CRL Distribution Point" | tail -1 | tr -d ' ')
# → http://crl.example.local/intermediate-ca.crl
wget -O crl.pem "$CRL_URL"
openssl crl -in crl.pem -noout -text | grep <serial_number_сертификата>
# → Если серийный номер найден — сертификат отозван

# 3. Проверка через openssl verify с CRL
openssl verify -crl_check -CAfile root-ca/ca.crt \
    -untrusted intermediate-ca/intermediate.crt \
    -CRLfile crl.pem service.crt
# → service.crt: OK (если не отозван)
# → service.crt: REASON=DEEPENING (если сертификат или его предок отозваны)

# 4. Проверка OCSP статуса в реальном времени
OCSP_URL=$(openssl x509 -in service.crt -noout -text \
  | grep -A 1 "OCSP - URI:" | tail -1 | tr -d ' ')
openssl ocsp -issuer intermediate-ca/intermediate.crt -cert service.crt \
    -url "$OCSP_URL" -CAfile root-ca/ca.crt -resp_text
# → Cert Status: good (сертификат актуален)
# → Cert Status: revoked (сертификат отозван)

# 5. Проверка OCSP Stapling на сервере (s_client -status)
openssl s_client -connect my-service.local:443 -servername my-service.local -status </dev/null 2>&1 | grep -A 5 "OCSP response"
# → OCSP Response Data: (stapling работает)
# → No OCSP response sent (stapling не настроен)
```

Подробная настройка OCSP-респондера и CRL Distribution Points — в **[ocsp_responder.md](../ocsp_responder.md)** и **[crl_distribution_points.md](../crl_distribution_points.md)**.

## Типичные ошибки и решения

### Таблица быстрого поиска

| Ошибка | Код | Вероятная причина | Решение |
|:---|:---|:---|:---|
| `unable to get local issuer certificate` | 20 | Root CA отсутствует в trust store | Установить `ca.crt` в хранилище ОС |
| `unable to verify the first certificate` | 21 | Сервер не отдаёт Intermediate CA | Настроить `fullchain.pem` |
| `certificate has expired` | 10 | Сертификат просрочен | Перевыпустить сертификат |
| `certificate is not yet valid` | 12 | Системные часы сбиты или сертификат ещё не активен | Проверить NTP, дождаться `notBefore` |
| `certificate has been revoked` | 11 | Сертификат отозван | Проверить CRL/OCSP, перевыпустить |
| `self signed certificate in chain` | 19 | Самоподписанный Intermediate или иной порядок в bundle | Проверить порядок в `ca-chain.crt`, перевыпустить Intermediate |
| `certificate signature failure` | 23 | Повреждён сертификат или неверный ключ | Перевыпустить, проверить целостность файла |
| `signature routines::unsupported algorithm` | — | Алгоритм не поддерживается провайдером OpenSSL 3.0+ | Использовать `-sha256` или `-provider legacy` |
| `depth 0 self signed` | 18 | Клиент видит только leaf без chain | Передать `-CAfile ca-chain.crt` |
| `pathlen constraint violated` | 26 | Intermediate CA пытается подписать CA, но у него `pathlen:0` | Использовать Intermediate только для сервисных сертификатов |
| `handshake failure` | — | Нет общих шифров/протоколов | Проверить `ssl_protocols` и `ssl_ciphers` |
| `wrong version number` | — | Сервер не использует TLS (или неверный порт) | Проверить `listen 443 ssl` |
| `no protocols available` | — | OpenSSL не поддерживает запрошенный протокол | Обновить OpenSSL или изменить `-tls1_3` флаг |

### Частые ошибки при настройке в Nginx

```nginx
# НЕПРАВИЛЬНО: только leaf-сертификат
ssl_certificate     /etc/nginx/ssl/service.crt;

# ПРАВИЛЬНО: fullchain (leaf + intermediate)
ssl_certificate     /etc/nginx/ssl/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/service.key;

# НЕПРАВИЛЬНО: нет SSL на порту 443
listen 443;

# ПРАВИЛЬНО: SSL включён
listen 443 ssl;

# НЕПРАВИЛЬНО: не указаны протоколы
# (OpenSSL 3.x по умолчанию может включить legacy)

# ПРАВИЛЬНО: явное указание протоколов
ssl_protocols TLSv1.2 TLSv1.3;

# OCSP Stapling (рекомендуется для production)
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/nginx/ssl/fullchain.pem;
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

### Частые ошибки при настройке в HAProxy

```haproxy
# НЕПРАВИЛЬНО: только leaf-сертификат
# crt /etc/ssl/private/service.pem

# ПРАВИЛЬНО: объединить leaf и intermediate в один файл
# cat service.crt intermediate-ca/intermediate.crt > /etc/haproxy/certs/fullchain.pem
bind *:443 ssl crt /etc/haproxy/certs/fullchain.pem
```

## Сценарии: быстрая диагностика

### Сценарий 1: «Браузер отклоняет сертификат для внутреннего сервиса»

```bash
# 1. Проверка через curl (исключает кэш браузера)
curl -v https://my-service.local/ 2>&1 | grep -E "SSL|certificate|issuer|expire"

# 2. Проверка через openssl
openssl s_client -connect my-service.local:443 -servername my-service.local </dev/null 2>&1 | grep -E "Verify|expire|subject|issuer"

# 3. Если "unable to get local issuer" — установить Root CA (см. Алгоритм 2)
# 4. Если "unable to verify the first" — добавить Intermediate CA на сервер (см. Алгоритм 3)
```

### Сценарий 2: «Сервис не запускается, ругается на сертификат»

```bash
# 1. Проверка, что ключ и сертификат соответствуют
openssl x509 -in /etc/ssl/service.crt -pubkey -noout -outform DER | openssl sha256
openssl pkey -in /etc/ssl/service.key -pubout -outform DER | openssl sha256
# → Хеши должны совпадать

# 2. Проверка прав доступа
ls -la /etc/ssl/service.key
# → -rw------- 1 root root ... (permissions 600)

# 3. Проверка, что ключ не зашифрован (для автоматического запуска)
openssl pkey -in /etc/ssl/service.key -check -noout 2>&1
# → Если запрашивает пароль — ключ зашифрован, что может блокировать автозапуск
# → openssl pkey заменяет устаревшую openssl rsa (maintenance mode в OpenSSL 3.0+)
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

# Node.js
# Указать CA через переменную окружения
export NODE_EXTRA_CA_CERTS=/etc/ssl/ca-chain.crt

# Docker (контейнер должен иметь установленный Root CA)
# COPY root-ca/ca.crt /usr/local/share/ca-certificates/ca.crt && update-ca-certificates
```

### Сценарий 4: «Сертификат отозван, но клиенту это не явно сообщается»

```bash
# 1. Проверка статуса через CRL
openssl verify -crl_check -CAfile root-ca/ca.crt \
    -untrusted intermediate-ca/intermediate.crt \
    -CRLfile intermediate-ca/crl/crl.pem service.crt
# → service.crt: OK (если не отозван)
# → service.crt: REASON=DEEPENING (если отозван)

# 2. Проверка статуса через OCSP
OCSP_URL=$(openssl x509 -in service.crt -noout -text \
  | grep -A 1 "OCSP - URI:" | tail -1 | tr -d ' ')
openssl ocsp -issuer intermediate-ca/intermediate.crt -cert service.crt \
    -url "$OCSP_URL" -CAfile root-ca/ca.crt
# → Cert Status: good
# → Cert Status: revoked
```

## Рекомендации и лучшие практики

### Предварительная проверка перед деплоем

Перед установкой сертификата в production выполните комплексную проверку:

```bash
# 1. Срок действия (не истечёт ли в течение 30 дней)
openssl x509 -in service.crt -noout -checkend 2592000 || echo "WARN: < 30 дней"

# 2. SAN
openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"

# 3. Цепочка доверия
openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt

# 4. Соответствие ключа и сертификата (универсальный метод для RSA/ECDSA/Ed25519)
openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
openssl pkey -in service.key -pubout -outform DER | openssl sha256
# → Хеши должны совпадать

# 5. Расширения (для leaf и Intermediate)
openssl x509 -in service.crt -noout -text | grep -A 3 "Basic Constraints"
# → basicConstraints = CA:FALSE (для leaf)
# → basicConstraints = CA:TRUE, pathlen:0 (для Intermediate)

# 6. AKI/SKI соответствие Intermediate CA
openssl x509 -in service.crt -noout -text | grep -A 1 "Authority Key Identifier"
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 1 "Subject Key Identifier"
# → Значение AKI leaf должно совпадать со SKI Intermediate CA
```

Полный чек-лист и безопасная работа с ключами — в **[Утилиты и диагностика](./common_utilities.md#рекомендации-и-лучшие-практики)**.

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

# Проверка 4: соответствие ключа и сертификата
CERT_HASH=$(openssl x509 -in "$SERVICE_CRT" -pubkey -noout -outform DER | openssl sha256)
# KEY_HASH требует пути к ключу; если ключ недоступен, пропустить эту проверку
# KEY_HASH=$(openssl pkey -in "${2:-service.key}" -pubout -outform DER | openssl sha256)
# [ "$CERT_HASH" = "$KEY_HASH" ] || { echo "FAIL: ключ не соответствует сертификату"; exit 1; }

echo "OK: все проверки пройдены"
```

Для Ansible-автоматизации см. **[Диагностика SSL/TLS сертификатов](../../ssl_certificate_diagnostics.md#автоматизация-через-ansible)** — плейбуки для проверки срока действия и цепочки на удалённых хостах.

## Ограничения и крайние случаи

- **Самоподписанные (self-signed) сертификаты:** OpenSSL всегда помечает их как `self signed`. Для тестовых сред используйте ваш внутренний CA, а не self-signed.
- **Wildcard-сертификаты:** покрывают только один уровень поддоменов (`*.service.local` покрывает `api.service.local`, но не `a.api.service.local`).
- **Легаси-клиенты:** некоторые старые Java-приложения (до Java 8) не поддерживают SAN и требуют RSA-ключей. В этом случае потребуется отдельный сертификат.
- **clock skew:** если часы на клиенте или сервере сильно отклонены, проверка `notBefore`/`notAfter` может завершиться ошибкой. Убедитесь, что NTP работает на обоих узлах:
  ```bash
  timedatectl status
  chronyc sources -v    # Linux
  ntpq -p               # альтернатива
  ```
- **OCSP Stapling не настроен:** сервер не отдаёт OCSP-ответ клиенту. Добавьте `ssl_stapling on;` и `ssl_stapling_verify on;` в конфигурацию TLS-сервера (см. [Nginx TLS](../../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)).
- **CRL Distribution Point недоступен:** клиент не может скачать CRL для проверки отзова. Проверьте доступность HTTP-сервера, DNS-резолв и firewall (см. [crl_distribution_points.md](../crl_distribution_points.md)).
- **OpenSSL 3.0+ Legacy provider:** устаревшие алгоритмы (SHA-1, MD5, RSA PKCS#1 v1.5) требуют явного включения провайдера Legacy:
  ```bash
  openssl list -providers                          # проверка загруженных провайдеров
  openssl verify -provider legacy -CAfile ca-chain.crt service.crt  # принудительное подключение
  ```
- **Процесс не может прочитать ключ:** сервис запущен от имени пользователя без прав на чтение файла ключа. Проверьте права:
  ```bash
  ls -la /etc/ssl/service.key
  # → -rw------- 1 root root ... (permissions 600)
  stat -c '%U %G %a' /etc/ssl/service.key          # Linux
  stat -f '%u:%g %Lp' /etc/ssl/service.key          # macOS
  ```
- **Пересечение с SNI:** при подключении по IP-адресу вместо имени сервера TLS-сервер может вернуть дефолтный сертификат. Всегда используйте `-servername`:
  ```bash
  openssl s_client -connect my-server.example.com:443 -servername my-server.example.com
  ```

## Очистка и откат изменений

### Удаление временных сертификатов и ключей диагностики

```bash
# Удаление временных файлов, созданных во время диагностики
rm -f service.crt service.key service.csr service.srl
rm -f crl.pem ca-chain.crt
rm -f /tmp/bundle_*.pem
```

### Удаление установленных корневых сертификатов из доверенных хранилищ

```bash
# Debian/Ubuntu
sudo rm /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo rm /etc/pki/ca-trust/source/anchors/my-private-ca.crt
sudo update-ca-trust

# Alpine
sudo rm /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates

# macOS
sudo security remove-trusted-cert -d root-ca/ca.crt

# Windows Server
certutil -delstore "Root" "CN=My Private Root CA"
certutil -delstore "CA" "CN=My Private Intermediate CA"

# Java Keystore
keytool -delete -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit \
    -alias my-private-ca

# Docker-контейнеры
# Пересоберите образ без COPY root-ca/ca.crt
# или удалите сертификат вручную:
docker run my-service rm /usr/local/share/ca-certificates/ca.crt
```

### Откат изменений в TLS-серверах

Если сертификат был изменён на тестовый в процессе диагностики:

1. Восстановите оригинальные файлы сертификата и ключа из резервной копии.
2. Проверьте соответствие ключа и сертификата: `openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256` должно совпадать с `openssl pkey -in service.key -pubout -outform DER | openssl sha256`.
3. Проверьте цепочку: `openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt`.
4. Перезагрузите сервис:
   ```bash
   sudo systemctl reload nginx    # или: sudo nginx -s reload
   sudo systemctl reload apache2  # или: sudo apachectl graceful
   sudo systemctl reload haproxy
   ```
5. Проверьте, что сервер отдаёт 2 сертификата (leaf + intermediate):
   ```bash
   openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null 2>&1 | grep -c "BEGIN CERTIFICATE"
   # → 2 (leaf + intermediate)
   ```

Полный набор инструкций по очистке и резервному копированию — в **[Утилиты и диагностика](./common_utilities.md#очистка-и-откат-изменений)**.

## Дополнительная информация

### Связанные темы

- **[Утилиты и диагностика](./common_utilities.md)** — полный набор диагностических команд OpenSSL, коды verify return code, таблица ошибок.
- **[Управление сертификатами сервисов](./service_certificate_management.md)** — выпуск, ротация и отзыв сертификатов.
- **[Диагностика SSL-сертификатов](../../ssl_certificate_diagnostics.md)** — расширенные методы поиска ошибок, TLS-диагностика, Ansible-автоматизация.
- **[OCSP Responder](../ocsp_responder.md)** — настройка OCSP-резолвера для проверки статуса сертификатов в реальном времени.
- **[CRL Distribution Points](../crl_distribution_points.md)** — настройка HTTP-сервера для распространения CRL.
- **[Обзор PKI](../../../Concepts/pki_overview.md)** — фундаментальная теория PKI, алгоритмы 2026, PQC, расширения X.509.
- **[Обзор двухуровневого CA](./overview.md)** — архитектура, структура каталогов, развёртывание.
- **[TLS-протокол](../../../../Networking/Protocols/tls.md)** — теория TLS, cipher suites, handshake, forward secrecy.
- **[Nginx: диагностика TLS](../../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — отладка TLS-handshake в Nginx.
