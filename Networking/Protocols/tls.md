# Протокол TLS (Transport Layer Security)

## Определения

**TLS (Transport Layer Security)** — криптографический протокол, обеспечивающий защищённую передачу данных между узлами в сети. Предшественник — устаревший протокол **SSL (Secure Sockets Layer)**.

TLS гарантирует три ключевых аспекта безопасности:

1. **Конфиденциальность (Confidentiality):** данные шифруются и недоступны для чтения третьими лицами.
2. **Целостность (Integrity):** данные защищены от модификации при передаче (через механизм MAC или AEAD-шифры).
3. **Аутентификация (Authentication):** подтверждение подлинности сервера (и опционально клиента), предотвращение атак типа Man-in-the-Middle.

### Ключевые компоненты

* **Центр сертификации (CA — Certificate Authority):** доверенная организация (например, Let's Encrypt), выпускающая и подписывающая цифровые сертификаты. Инфраструктура **PKI (Public Key Infrastructure — инфраструктура открытых ключей)**: **[Инфраструктура открытых ключей (PKI)](../../Security/Concepts/pki_overview.md)**.
* **TLS/SSL-сертификат (X.509):** цифровой документ, связывающий доменное имя (или IP-адрес) с открытым ключом сервера. Сертификат содержит публичный ключ сервера и подтверждает его принадлежность владельцу через подпись доверенного CA.
* **TLS-сертификаты для IP-адресов:** начиная с 15 января 2026 года, Let's Encrypt поддерживает выпуск доверенных сертификатов для «чистых» IPv4-адресов через профиль **shortlived**. Это позволяет защищать трафик микросервисов, API и IoT-устройств без необходимости регистрации доменных имен. Срок действия таких сертификатов ограничен 6 днями.
* **Набор шифров (Cipher Suite):** комбинация криптографических алгоритмов для защиты сессии. Включает алгоритмы обмена ключами, аутентификации, симметричного шифрования и хеширования (например, `TLS_AES_128_GCM_SHA256`).
* **SNI (Server Name Indication):** расширение TLS, позволяющее клиенту указать имя хоста в начале рукопожатия. Это позволяет размещать несколько HTTPS виртуальных хостов на одном IP-адресе. SNI передается открытым текстом в ClientHello.
* **ECH (Encrypted Client Hello):** современное расширение (RFC 9460), шифрующее всё сообщение ClientHello, включая SNI. Решает проблему приватности, скрывая имя целевого сервера от провайдера.
* **OCSP Stapling (RFC 6066):** механизм оптимизации, при котором сервер сам запрашивает статус валидности своего сертификата у CA и «прикрепляет» подписанный ответ к TLS-рукопожатию. Это избавляет клиента от необходимости делать отдельный запрос к CA, ускоряя загрузку и повышая приватность.
* **Wildcard-сертификат:** сертификат для защиты основного домена и неограниченного количества поддоменов первого уровня (например, `*.example.com`). Не защищает поддомены более глубоких уровней (например, `test.api.example.com`).

### Цепочка сертификатов (Certificate Chain)

Для successful TLS-валидации клиент должен проследить путь доверия от серверного сертификата до доверенного корневого CA.

**Структура цепочки:**

```
Root CA (корневой) — уже есть в доверенном хранилище ОС/браузера
  └── Intermediate CA (промежуточный)
        └── Server Certificate (сертификат вашего домена)
```

* **Root CA:** самоподписанный сертификат, является корнем доверия. Не передаётся по сети — уже входит в доверенное хранилище клиента.
* **Intermediate CA:** используется для подписи серверных сертификатов. Позволяет хранить Root CA в безопасности (offline) и выпускать сертификаты через промежуточный уровень.
* **Server Certificate (Leaf):** непосредственный сертификат для домена/IP, подписанный Intermediate CA.

**Формат fullchain.pem:**
При настройке веб-сервера (Nginx, Apache) серверный сертификат и промежуточные CA объединяются в один файл. Порядок критичен:
1. Сертификат домена (leaf).
2. Промежуточные сертификаты (один или несколько).

**Проверка цепочки:**
```bash
# Просмотр цепочки сертификата
openssl s_client -connect example.com:443 -showcerts

# Проверка цепочки локального файла
openssl verify -CAfile ca.crt -untrusted intermediate.crt server.crt
# → server.crt: OK
```

### Отзыв сертификатов (Revocation)

CA может отозвать сертификат до истечения срока действия (например, при компрометации приватного ключа).

#### CRL (Certificate Revocation List)

Список отозванных сертификатов, публикуемый CA. Содержит серийные номера аннулированных сертификатов.

* **Недостаток:** список может быть большим; клиент должен загружать весь список.
* **Использование:** проверка вручную или на промежуточных серверах.

```bash
# Скачать CRL и проверить сертификат
curl -s http://crl.example.com/ca.crl -o ca.crl
openssl crl -in ca.crl -noout -text | grep -A1 "Serial Number"
```

#### OCSP (Online Certificate Status Protocol)

Протокол онлайн-проверки статуса сертификата (RFC 6960). Клиент запрашивает статус конкретного сертификата у CA.

* **Преимущество:** быстрая проверка одного сертификата без загрузки всего CRL.
* **Недостаток:** задержка на запрос к CA; проблемы с приватностью (CA узнаёт, какой сайт проверяется).

#### OCSP Stapling (RFC 6066)

Оптимизация OCSP: сервер самостоятельно запрашивает подписанный ответ OCSP и «прикрепляет» его к TLS-рукопожатию (stapling). Клиент не обращается к CA напрямую.

```bash
# Проверка OCSP stapling на сервере
openssl s_client -connect example.com:443 -status | grep "OCSP Response Status"
# → OCSP Response Status: successful
```

#### CT (Certificate Transparency)

Система публичного аудита выпуска сертификатов (RFC 6962). Каждый выпущенный сертификат должен быть зарегистрирован в публичном CT-логе.

* **Цель:** обнаружение ошибочно выпущенных или вредоносных сертификатов.
* **Требование:** с 2018 года браузеры Chrome требуют CT-подпись для доверенных сертификатов.
* **Проверка:** `openssl s_client -connect example.com:443 | grep "SCT"`.

#### DANE (DNS-based Authentication of Named Entities)

Механизм привязки TLS-сертификатов к DNS-записям через DNSSEC (RFC 6698). Позволяет указать, какой CA или сертификат является доверенным для конкретного домена.

* **Запись TLSA:** содержит отпечаток сертификата или CA в DNS.
* **Преимущество:** защита от подмены DNS и нелегитимных CA.
* **Применение:** DMARC, DANE для SMTP (защита почты).

## Основные концепции

### Гибридное шифрование

TLS комбинирует два типа шифрования:

* **Асимметричное шифрование (RSA, ECC):** используется на этапе **рукопожатия (Handshake)** для аутентификации сервера и безопасного обмена сессионным ключом.
* **Симметричное шифрование (AES, ChaCha20):** используется для шифрования основного потока данных после рукопожатия. Оно значительно быстрее асимметричного, что критично для производительности.

#### Сравнение TLS 1.2 и TLS 1.3 (RFC 8446)

TLS 1.3 — это радикальный редизайн, направленный на упрощение и безопасность.

| Характеристика | TLS 1.2 | TLS 1.3 |
| :--- | :--- | :--- |
| **Задержка (Handshake)** | 2-RTT | 1-RTT |
| **Возобновление** | Session ID / Tickets | PSK (Pre-Shared Key) |
| **PFS** | Опционально (DHE/ECDHE) | **Обязательно** для всех шифров |
| **Подпись сертификата** | Статическая | Всегда через `CertificateVerify` |
| **Защита ClientHello** | SNI открыт | Поддержка ECH (Encrypted Client Hello) |

**Удаленные (запрещенные) алгоритмы в TLS 1.3:**
- Симметричные шифры в режиме CBC (защита от Lucky13/POODLE).
- Хеширование SHA-1 и MD5.
- Обмен ключами RSA (теперь только для аутентификации).
- Статический Диффи-Хеллман.
- Экспортные (слабые) шифры.

#### Шифры TLS 1.3

TLS 1.3 определяет пять обязательных наборов шифров (все AEAD):

| Cipher Suite | Ключ (бит) | AEAD | Хеш | Описание |
| :--- | :--- | :--- | :--- | :--- |
| `TLS_AES_128_GCM_SHA256` | 128 | AES-GCM | SHA-256 | Базовый, широкая поддержка |
| `TLS_AES_256_GCM_SHA384` | 256 | AES-GCM | SHA-384 | Максимальная защита AES |
| `TLS_CHACHA20_POLY1305_SHA256` | 256 | ChaCha20 | SHA-256 | Оптимален для мобильных (без AES-NI) |
| `TLS_AES_128_CCM_SHA256` | 128 | AES-CCM | SHA-256 | IoT, ограниченные устройства |
| `TLS_AES_128_CCM_8_SHA256` | 128 | AES-CCM-8 | SHA-256 | Облегчённый (8-байтный TAG) |

**Группы обмена ключами (Key Exchange Groups) в TLS 1.3:**

| Группа | Описание | Рекомендация |
| :--- | :--- | :--- |
| `x25519` | Curve25519, быстрая и безопасная | Рекомендуется по умолчанию |
| `secp256r1` (P-256) | NIST P-256, широкая поддержка | Стандарт для enterprise |
| `secp384r1` (P-384) | NIST P-384, повышенная безопасность | Для высоких требований |
| `x25519_kyber768` | Гибридный: X25519 + ML-KEM (Kyber) | Постквантовая устойчивость |

#### Механизм выработки общего ключа (3 случайных числа)

Для создания итогового симметричного ключа сессии в TLS 1.2 обе стороны используют три компонента:

1. **Client Random:** случайное число от клиента (передается открыто в ClientHello).
2. **Server Random:** случайное число от сервера (передается открыто в ServerHello).
3. **Pre-master Secret:** случайное число, генерируемое клиентом и зашифрованное публичным ключом сервера (в режиме RSA) или выработанное через Диффи-Хеллмана.

В **TLS 1.3** процесс упрощен: клиент сразу отправляет `key_share` (свои эфемерные ключи) в первом пакете, что исключает один раунд обмена.

#### Механизм Диффи–Хеллмана (Diffie–Hellman) и ECDHE

Алгоритм Диффи–Хеллмана позволяет двум сторонам безопасно выработать общий секрет по открытому каналу.

**Принцип работы:**
1. Обе стороны генерируют пары **эфемерных** (временных) ключей.
2. Стороны обмениваются публичными частями ключей.
3. Каждая сторона комбинирует свой приватный ключ с публичным ключом другой стороны.
4. Результат — одинаковый общий секрет, никогда не передававшийся по сети напрямую.

В современном TLS используется **ECDHE (Elliptic Curve Diffie–Hellman Ephemeral)** — версия на основе эллиптических кривых. Эфемерность ключей обеспечивает свойство **Perfect Forward Secrecy (PFS)**: компрометация долгосрочного ключа сервера не позволяет расшифровать прошлые сессии.

### Процесс рукопожатия (SSL/TLS Handshake)

Количество раундов обмена данными (RTT — Round-Trip Time) зависит от версии протокола.

#### Упрощённый TLS 1.2 Handshake (2-RTT)

Классический процесс, требующий двух полных раундов обмена данными до начала передачи полезной нагрузки.

1. **ClientHello:** клиент отправляет список поддерживаемых версий протокола, наборов шифров, SNI и `client_random`.
2. **ServerHello + Certificate:** сервер выбирает параметры, отправляет свой сертификат и `server_random`.
3. **Проверка и обмен ключами:** клиент проверяет сертификат. Стороны используют асимметричное шифрование (или ECDHE) для выработки **premaster secret**.
4. **Finished:** на основе `client_random`, `server_random` и `premaster secret` вычисляется сессионный ключ. Стороны обмениваются зашифрованными сообщениями `Finished` для подтверждения.

#### Упрощённый TLS 1.3 Handshake (1-RTT)

Современный стандарт, сокращающий задержку до одного раунда.

1. **ClientHello:** клиент сразу отправляет параметры для обмена ключами (key share), предполагая алгоритмы сервера, а также `client_random`.
2. **ServerHello + Certificate + Finished:** сервер выбирает шифр, отправляет сертификат, свои параметры ключа (`server_key_share`) и сообщение `Finished` в одном пакете. Сертификат используется только для аутентификации (подпись), шифрование трафика всегда идет через PFS-ключи.
3. **Finished:** клиент проверяет сертификат, вычисляет сессионный ключ и отправляет своё сообщение `Finished`. После этого начинается передача зашифрованных данных.

### Механизмы оптимизации и безопасности

* **Возобновление сессии (Session Resumption):**
  * **TLS 1.2:** Session IDs (хранение на сервере) или Session Tickets (зашифрованный тикет у клиента).
  * **TLS 1.3:** **PSK (Pre-Shared Key)** — сервер выдаёт тикет для быстрого возобновления сессии (1-RTT).
* **0-RTT (Zero Round-Trip Time):** функция TLS 1.3, позволяющая клиенту отправлять зашифрованные данные уже в первом пакете при повторном подключении. Создаёт риски **атак повторного воспроизведения (replay attacks)**, поэтому должна использоваться только для идемпотентных запросов (GET).
* **ALPN (Application-Layer Protocol Negotiation):** расширение TLS для согласования протокола прикладного уровня (например, `h2` для HTTP/2) в рамках рукопожатия.
* **HSTS (HTTP Strict Transport Security):** заголовок, заставляющий браузер всегда использовать HTTPS для данного домена, предотвращая попытки даунгрейда до HTTP (SSL Stripping).
* **kTLS (Kernel TLS):** перенос операций шифрования симметричным ключом в ядро ОС. Это позволяет использовать механизм `sendfile` (Zero-copy), значительно повышая производительность при отдаче статических файлов.

### DTLS (Datagram Transport Layer Security)

**DTLS (RFC 6347 / RFC 9147)** — версия протокола TLS, предназначенная для работы поверх **UDP** (ненадёжных транспортных протоколов).

**Особенности и отличия:**
- **Решение проблемы потери пакетов:** В отличие от TLS, который полагается на TCP, DTLS реализует собственные механизмы повторной передачи (retransmission) и таймеров.
- **Предотвращение петель:** Включает механизм `Cookie` в Hello-сообщениях для защиты от DoS-атак с подменой IP.
- **Применение:** [WebRTC](../Concepts/webrtc.md), VPN (Cisco AnyConnect, OpenConnect), IoT (CoAP).
- **DTLS 1.3:** Соответствует TLS 1.3, минимизируя задержки и исключая слабые шифры.

## Практические сценарии

### Сценарий 1: Защита веб-сервера (HTTPS)

1. Получение сертификата (например, через **[Certbot и Let's Encrypt](../../WebServers/Concepts/https_with_certbot.md)**).
2. Настройка веб-сервера (Nginx/Angie) для использования сертификата и TLS 1.3.
3. Сервер выполняет TLS-терминацию и передает трафик приложению. Подробнее: **[Оптимальная настройка TLS/SSL в Nginx](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**.

### Сценарий 2: Взаимная аутентификация (mTLS)

Обеспечивает проверку подлинности не только сервера, но и клиента. Используется в микросервисных архитектурах и для доступа к критическим API.
* Сервер запрашивает и проверяет сертификат клиента, подписанный доверенным CA.
* Пример реализации: **[Аутентификация по клиентским сертификатам в Nginx](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)**.

### Сценарий 3: Базовая конфигурация TLS на сервере

#### Nginx / Angie

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate     /etc/ssl/certs/fullchain.pem;   # leaf + intermediates
    ssl_certificate_key /etc/ssl/private/privkey.pem;

    # TLS 1.3 приоритет
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers on;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/chain.pem;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    # Session optimization
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;  # для PFS

    # HSTS
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
}
```

#### HAProxy

```haproxy
frontend https-in
    bind *:443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
    http-request redirect scheme https unless { ssl_fc }

    # Минимальный TLS 1.2, приоритет TLS 1.3
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets

    # HSTS
    http-response set-header Strict-Transport-Security "max-age=63072000; includeSubDomains"

    # OCSP Stapling (требует crt с ca-file)
    bind *:443 ssl crt /etc/haproxy/certs/example.pem ca-file /etc/haproxy/certs/chain.pem

backend app-servers
    server app1 10.0.0.1:8080 check
```

#### OpenSSL: самоподписанный сертификат для тестов

```bash
# Генерация ключа и сертификата (ECDSA, P-256)
openssl ecparam -genkey -name prime256v1 -out privkey.pem
openssl req -new -x509 -key privkey.pem -out cert.pem -days 365 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Test/CN=test.local"

# Для доверия в браузере: импортируйте cert.pem в доверенное хранилище ОС
```

#### OpenSSL: запрос на подпись сертификата (CSR)

```bash
# Генерация ключа и CSR
openssl req -new -newkey rsa:2048 -nodes -keyout server.key -out server.csr \
  -subj "/C=RU/ST=Moscow/O=MyOrg/CN=example.com"

# Просмотр CSR
openssl req -in server.csr -noout -text

# Подпись CSR вашим CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -sha256
```

### Сценарий 4: Устранение ошибок

* **«Certificate Expired»:** срок действия истек. Решение: обновление сертификата.
* **«Cipher Mismatch»:** клиент и сервер не имеют общих шифров. Решение: обновить конфигурацию шифров на сервере или обновить клиент.
* **«Certificate not trusted»:** самоподписанный сертификат или отсутствует промежуточный CA в цепочке. Решение: использовать `fullchain.pem`.
* **«ERR_CERT_DATE_INVALID»:** сертификат ещё не действителен или просрочен. Проверьте системные часы сервера и клиента.
* **«SSL handshake failure»:** несовпадение поддерживаемых версий/шифров. Решение: проверьте `ssl_protocols` и `ssl_ciphers` на сервере.
* **Диагностика:** **[SSL Certificate Diagnostics](../../Security/Tools/ssl_certificate_diagnostics.md)**.

**Инструменты командной строки:**
```bash
# Проверка поддержки версий TLS и сертификата
openssl s_client -connect example.com:443 -tls1_3

# Проверка SNI (Server Name Indication)
openssl s_client -connect IP_ADDRESS:443 -servername example.com

# Декодирование локального сертификата
openssl x509 -in cert.pem -text -noout

# Проверка даты истечения сертификата
openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Jan  1 00:00:00 2026 GMT
# → notAfter=Dec 31 23:59:59 2026 GMT

# Проверка цепочки сертификатов
openssl s_client -connect example.com:443 -showcerts

# Проверка OCSP stapling
openssl s_client -connect example.com:443 -status

# Проверка поддерживаемых шифров (перебор)
for cipher in $(openssl ciphers 'ALL:COMPLEMENTOFALL' | tr ':' ' '); do
  result=$(openssl s_client -connect example.com:443 -cipher "$cipher" 2>&1)
  if echo "$result" | grep -q "Cipher is"; then
    echo "Supported: $cipher"
  fi
done

# Быстрая проверка с помощью nmap
nmap --script ssl-enum-ciphers -p 443 example.com
```

### Безопасность TLS: векторы атак и стандарты 2026

1. **Базовый уровень 2026:**
   - **TLS 1.3** — приоритет №1.
   - **TLS 1.2** — допустим только с шифрами ECDHE и режима AEAD (AES-GCM, ChaCha20-Poly1305).
   - **Запрещено:** TLS 1.0, 1.1 и все CBC-шифры.
2. **Постквантовая устойчивость (Post-Quantum Cryptography — PQC):**
   - В 2025-2026 годах внедряются гибридные схемы обмена ключами (например, `X25519 + ML-KEM`).
   - Защищает записанный сегодня трафик от расшифровки будущими квантовыми компьютерами (Harvest Now, Decrypt Later).
   - OpenSSL 3.5+ и 4.0 поддерживают ML-KEM (Kyber) по умолчанию.
3. **Анализ трафика:** при отсутствии ECH провайдер видит домен (SNI). При отсутствии PFS кража ключа сервера позволяет расшифровать весь записанный трафик.
4. **Методы анализа:** для отладки используют `SSLKEYLOGFILE`, MITM-прокси или ядерную отладку. См. подробнее: **[Методы расшифровки TLS-трафика](../ServicesAndTools/Wireshark/tls_decryption_methods.md)**.
5. **Известные атаки и уязвимости:**

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **POODLE** | Эксплуатация CBC в SSL 3.0 | Отключение SSL 3.0 и CBC |
| **BEAST** | Атака на CBC в TLS 1.0 | Переход на TLS 1.2+ или GCM |
| **Heartbleed** | Утечка памяти OpenSSL (CVE-2014-0160) | Обновление OpenSSL |
| **ROBOT** | Блеф RSA-ключей | Отключение RSA key exchange |
| **CRIME/BREACH** | Сжатие раскрывает секреты | Отключение сжатия |
| **Lucky13** | Timing-атака на CBC | Использование AEAD-шифров |
| **Downgrade Attack** | Принудительный переход на слабую версию | TLS_FALLBACK_SCSV |
| **Replay (0-RTT)** | Повторное воспроизведение Early Data | Только идемпотентные запросы |

### Типичные ошибки и их диагностика

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Сертификат не доверен | Самоподписанный или отсутствует intermediate CA | `openssl s_client -showcerts` | Использовать `fullchain.pem` |
| «Cipher mismatch» | Сервер не поддерживает шифры клиента | `openssl ciphers -v` / `nmap --script ssl-enum-ciphers` | Обновить `ssl_ciphers` на сервере |
| «Handshake failure» | Несовпадение версий TLS | `openssl s_client -tls1_3` | Проверить `ssl_protocols` |
| Медленная загрузка | Отсутствие OCSP stapling / session cache | `openssl s_client -status` | Включить `ssl_stapling on` |
| SNI не работает | Клиент не отправляет SNI | `openssl s_client -servername host` | Проверить поддержку SNI клиентом |
| Сертификат просрочен | Истёк `notAfter` | `openssl x509 -noout -dates` | Обновить сертификат |
| Ошибка цепочки | Порядок сертификатов неверен | `openssl verify -CAfile ca.pem` | Пересобрать `fullchain.pem` в правильном порядке |

## Дополнительная информация

* **Порт по умолчанию:** 443/TCP (HTTPS).
* **Инструменты:** [SSL Labs Server Test](https://www.ssllabs.com/ssltest/) для глубокого аудита.

### RFC-спецификации

| RFC | Описание |
| :--- | :--- |
| [RFC 8446](https://datatracker.ietf.org/doc/html/rfc8446) | TLS 1.3 — основная спецификация |
| [RFC 5246](https://datatracker.ietf.org/doc/html/rfc5246) | TLS 1.2 |
| [RFC 6066](https://datatracker.ietf.org/doc/html/rfc6066) | Расширения TLS (SNI, OCSP Stapling) |
| [RFC 6347](https://datatracker.ietf.org/doc/html/rfc6347) | DTLS 1.2 |
| [RFC 9147](https://datatracker.ietf.org/doc/html/rfc9147) | DTLS 1.3 |
| [RFC 6960](https://datatracker.ietf.org/doc/html/rfc6960) | OCSP |
| [RFC 6962](https://datatracker.ietf.org/doc/html/rfc6962) | Certificate Transparency |
| [RFC 6698](https://datatracker.ietf.org/doc/html/rfc6698) | DANE |
| [RFC 8092](https://datatracker.ietf.org/doc/html/rfc8092) | TLS Cipher Suites (IANA Registry) |
| [RFC 9460](https://datatracker.ietf.org/doc/html/rfc9460) | ECH (Encrypted Client Hello) |

### Связанные документы

* **[Инфраструктура открытых ключей (PKI)](../../Security/Concepts/pki_overview.md)** — иерархия CA и управление сертификатами.
* **[Методы расшифровки TLS-трафика](../ServicesAndTools/Wireshark/tls_decryption_methods.md)** — руководство по анализу.
* **[Оптимизация HTTP-протоколов](HTTP/http_protocols_optimization.md)** — влияние TLS на задержки.
* **[Обзор TLS/SSL в Nginx](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — практическая настройка Nginx.
* **[mTLS в Nginx](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)** — взаимная аутентификация.
* **[TLS и mTLS в Kubernetes](../../Kubernetes/Security/tls_and_mtls_in_kubernetes.md)** — управление сертификатами в кластере.
