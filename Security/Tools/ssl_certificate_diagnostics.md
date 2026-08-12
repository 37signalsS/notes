# Диагностика SSL/TLS сертификатов

## Определения

**Цепочка доверия (Chain of Trust)** — последовательность сертификатов от конечного (серверного) узла до доверенного корневого центра (Root CA). Клиент проверяет подпись на каждом уровне; если хотя бы одно звено невалидно, доверие ко всей цепочке теряется.

**Incomplete chain** — ситуация, когда сервер не передаёт промежуточные сертификаты (Intermediate CA). Это приводит к ошибкам верификации у клиентов, чьё локальное хранилище не содержит этих промежуточных звеньев.

**Server Name Indication (SNI)** — расширение TLS, позволяющее клиенту передавать имя хоста (домен) в начале рукопожатия. Это необходимо для корректного выбора сертификата на серверах с несколькими виртуальными хостами на одном IP.

**OCSP Stapling** — механизм, при котором сервер сам запрашивает статус валидности своего сертификата у CA и «прикрепляет» подписанный ответ к handshake. Это ускоряет проверку для клиента и повышает его приватность.

**CA-хранилище (Trust Store)** — системный набор доверенных корневых и промежуточных сертификатов (например, `/etc/ssl/certs` в Linux).

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
Подробнее о форматах цепочек см. в **[PKI Overview](../../Concepts/pki_overview.md#форматы-файлов-и-стандарты)**.

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

### Сценарий 4: Проверка поддержки версий TLS

В 2026 году рекомендуется использовать TLS 1.3.

```bash
# Проверка поддержки TLS 1.3
openssl s_client -connect example.com:443 -servername example.com -tls1_3

# Проверка TLS 1.2 (для совместимости)
openssl s_client -connect example.com:443 -servername example.com -tls1_2
```

### Сценарий 5: Проверка HSTS и заголовков безопасности

```bash
curl -I https://example.com | grep -i "Strict-Transport-Security"
# Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

## Дополнительная информация

### Полезные команды OpenSSL

- `openssl x509 -in cert.pem -noout -text` — полный просмотр метаданных (SAN, AKI/SKI, Key Usage).
- `openssl s_client -connect host:port -showcerts` — вывод всех сертификатов, передаваемых сервером (анализ бандла).
- `openssl verify -CAfile ca-bundle.crt -untrusted intermediate.crt server.crt` — верификация локальных файлов цепочки.

### Сторонние инструменты

- **[SSL Labs Server Test](https://www.ssllabs.com/ssltest/)** — глубокий онлайн-анализ (оценка A+, проверка Chain Issues).
- **[testssl.sh](https://testssl.sh/)** — CLI-утилита для проверки любых портов на уязвимости и настройки TLS.
- **[Certigo](https://github.com/square/certigo)** — современный инструмент на Go для дампа и валидации сертификатов.

### Связанные темы

- **[PKI Overview](../../Concepts/pki_overview.md)** — иерархия доверия и стандарты.
- **[TLS Protocol](../../../Networking/Protocols/tls.md)** — теория рукопожатия и шифрования.
- **[Nginx TLS Troubleshooting](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — специфика отладки в Nginx.
