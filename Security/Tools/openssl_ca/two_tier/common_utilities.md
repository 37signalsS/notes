# Утилиты и диагностика двухуровневого CA

## Определения

**PKI (Public Key Infrastructure, Инфраструктура открытых ключей)** — совокупность технологий, стандартов, политик и процедур, необходимых для создания, управления, распределения, использования, хранения и отзыва цифровых сертификатов. Основная цель — обеспечить доверенную среду для обмена данными и идентификации субъектов через асимметричную криптографию.

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты для подтверждения подлинности открытых ключей.

**Root CA (Корневой центр сертификации)** — вершина иерархии доверия. Самоподписанный сертификат с расширением `CA:true`, используемый исключительно для подписи промежуточных центров сертификации. Его приватный ключ является наиболее критичным активом и должен находиться в максимально изолированной среде.

**Intermediate CA (Промежуточный центр сертификации)** — подчинённый удостоверяющий центр, сертификат которого подписан корневым CA. В двухуровневой архитектуре он является единственным узлом, выпускающим конечные сертификаты. Его безопасность обеспечивается через ограничение `pathlen:0` в расширении Basic Constraints.

**ca-chain.crt (Bundle)** — PEM-файл, объединяющий сертификат Intermediate CA и Root CA. TLS-серверы обязаны отдавать полную цепочку клиентам, так как клиенты доверяют только корневому якорю и не знают о промежуточном звене.

**HSM (Hardware Security Module, Аппаратный модуль безопасности)** — специализированное устройство для генерации и безопасного хранения криптографических ключей, обеспечивающее защиту от физического и логического извлечения. Рекомендуется для хранения корневого ключа в production-средах.

**TPM (Trusted Platform Module)** — аппаратный модуль безопасности, интегрированный в материнскую плату. Поддерживает хранение ключей и криптографические операции. Может использоваться для защиты ключей Intermediate CA.

**OpenSSL 3.0+** — версия инструментария, в которой архитектура перешла на использование провайдеров (Default, FIPS, Legacy), были депрецированы устаревшие параметры конфигурации (например, `RANDFILE`), и внедрена поддержка гибридных схем и постквантовой криптографии.

**mTLS (Mutual TLS, Взаимный TLS)** — стандарт безопасности для взаимодействия микросервисов, требующий обязательной аутентификации как сервера, так и клиента с помощью сертификатов. В двухуровневой схеме mTLS реализуется через промежуточные CA.

**CRL (Certificate Revocation List)** — список серийных номеров отозванных сертификатов, подписанный CA. Клиенты проверяют сертификаты по этому списку для подтверждения, что они не были отозваны.

**OCSP (Online Certificate Status Protocol)** — протокол проверки статуса конкретного сертификата в реальном времени. Снижает нагрузку по сравнению с CRL, но требует доступности OCSP-responder.

**Shamir's Secret Sharing** — схема разделения секрета на части, при которой для восстановления исходного секрета необходимо наличие минимального количества частей (порогового значения). Применяется для разделения парольной фразы Root CA между доверенными администраторами.

> Базовые понятия (ключ, CSR (Certificate Signing Request), X.509, цепочка доверия, CRL, OCSP, расширения X.509, алгоритмы 2026, PQC) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Об архитектуре двухуровневого CA и сравнении с одноуровневой см. **[обзор двухуровневого CA](./overview.md)**.

## Базовые концепции

### Категории диагностических команд

Все команды OpenSSL для работы с сертификатами разделяются на:

- **Просмотр** — извлечение метаданных (команды `x509`, `req`, `crl`).
- **Верификация** — проверка криптографического соответствия и подписей (команды `verify`, `-modulus`, `pubkey`).
- **Подключение** — имитация клиента для тестирования TLS-конфигураций (команда `s_client`).

### Контекст двухуровневого CA

Ключевое отличие от **[одноуровневого CA](../../openssl_ca/single_tier/common_utilities.md)** заключается в необходимости использования полной цепочки `ca-chain.crt`.

| Операция | Одноуровневый CA | Двухуровневый CA |
|:---|:---|:---|
| Доверенный корень | `ca.crt` | `ca-chain.crt` (Intermediate + Root) |
| Верификация сервиса | `-CAfile ca.crt` | `-CAfile ca-chain.crt` |
| Путь к CRL | `ca/crl.pem` | `intermediate-ca/db/crl.pem` |
| Проверка SNI | Рекомендуется | **Обязательна** (для TLS 1.3) |

### Архитектурные особенности верификации

В двухуровневой схеме верификация проходит два уровня:
1. Конечный сертификат → проверяется подписью Intermediate CA.
2. Intermediate CA → проверяется подписью Root CA.

Клиент доверяет сертификату сервиса только если может проследить цепочку до корневого CA, который присутствует в его доверенном хранилище. При использовании `openssl verify` в двухуровневой схеме требуется передавать полную цепочку через `-CAfile ca-chain.crt`, а не только корневой сертификат.

### OpenSSL 3.0+ и провайдеры

OpenSSL 3.x использует модульную архитектуру провайдеров:
- **Default** — основной провайдер с современными алгоритмами.
- **Legacy** — для устаревших алгоритмов (например, SHA-1).
- **FIPS** — для соответствия FIPS 140-2/3.

При диагностике всегда проверяйте активные провайдеры:
```bash
openssl list -providers
```

Если команда выдает ошибку `unsupported algorithm`, возможно, требуется явно указать провайдер Legacy или обновить конфигурацию `openssl.cnf`.

## Предварительные требования

### Аппаратные и программные требования

- **ОС:** Linux (Debian/Ubuntu, RHEL/CentOS/Fedora, Alpine) или macOS. Инструкции tested на Linux x86_64.
- **OpenSSL:** версия 3.0.0 или выше. Проверка: `openssl version -a`.
- **Права:** доступ пользователя с возможностью чтения файлов CA (`intermediate-ca/ca-chain.crt`, `root-ca/ca.crt`, `intermediate-ca/intermediate.key`). Для установки сертификатов в системные хранилища требуются права `root` или `sudo`.
- **Дисплей:** для операций с парольной фразой (если ключ CA шифруется) требуется терминал с поддержкой ввода пароля.

### Проверка окружения

```bash
# Проверка версии OpenSSL
openssl version -a
# → OpenSSL 3.0.x ...

# Проверка доступных провайдеров (OpenSSL 3.0+)
openssl list -providers
# → Providers:
# →  ... (default provider)
# →  ... (legacy provider, при необходимости)
```

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y openssl libssl-dev

# RHEL/CentOS/Fedora
sudo dnf install -y openssl openssl-devel

# Alpine
sudo apk add openssl openssl-dev
```

## Практические сценарии

### Просмотр содержимого сертификата

```bash
openssl x509 -in my-service.crt -noout -text
```

Обратите внимание на поле `Authority Key Identifier (AKI)` — оно должно совпадать с `Subject Key Identifier (SKI)` промежуточного CA.

#### Полезные флаги для целенаправленного просмотра

```bash
# Только Subject и Issuer
openssl x509 -in my-service.crt -noout -subject -issuer
# → subject=CN = my-service.local, O = Dev, C = RU
# → issuer=CN = My Private Intermediate CA, O = Dev, C = RU

# Только сроки действия
openssl x509 -in my-service.crt -noout -dates
# → notBefore=Jan  1 00:00:00 2025 GMT
# → notAfter=Jan  1 00:00:00 2026 GMT

# Серийный номер
openssl x509 -in my-service.crt -noout -serial
# → serial=0A1B2C3D4E5F6A7B8C9D

# Отпечаток (fingerprint) для сверки
openssl x509 -in my-service.crt -noout -fingerprint -sha256
# → SHA256 Fingerprint=AB:CD:EF:...

# Хеш subject (используется в lookup)
openssl x509 -in my-service.crt -noout -hash
# → 0a1b2c3d
```

### Просмотр содержимого запроса CSR

```bash
openssl req -in my-service.csr -noout -text
```

Используется для проверки расширений SAN и корректности DN перед отправкой запроса на подпись в Intermediate CA.

```bash
# Только Subject и открытый ключ
openssl req -in my-service.csr -noout -subject -pubkey
```

### Проверка соответствия ключа и сертификата

Для предотвращения ошибок при запуске TLS-серверов необходимо убедиться, что файлы составляют рабочую пару.

#### Сценарий А: RSA-ключи
Сравниваются хеши модулей.

```bash
openssl rsa -noout -modulus -in service.key | openssl sha256
openssl x509 -noout -modulus -in service.crt | openssl sha256
```

#### Сценарий Б: ECDSA/Ed25519 (2026)
Сравниваются хеши публичных ключей (DER-формат).

```bash
# Извлечение из приватного ключа
openssl pkey -in service.key -pubout -outform DER | openssl sha256
# Извлечение из сертификата
openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
```

### Просмотр списка отозванных сертификатов CRL

```bash
openssl crl -in intermediate-ca/db/crl.pem -noout -text
```

В двухуровневой схеме вы всегда проверяете CRL, выпущенный **промежуточным** CA, так как именно он подписывал конечные сертификаты.

```bash
# Поиск конкретного серийного номера в CRL
openssl crl -in intermediate-ca/db/crl.pem -noout -text | grep -A 1 "Serial Number:"
```

### Диагностика TLS-сервера (s_client)

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null
```

**Анализ вывода:**
- `Verification: OK` — цепочка доверена.
- `Verification error: unable to get local issuer certificate` — сервер не отдает промежуточный сертификат (нужно использовать `fullchain.crt`).

#### Критические флаги s_client

- `-servername` — **Обязателен** для современных серверов (SNI). Без него сервер может отдать дефолтный (неверный) сертификат.
- `-CAfile intermediate-ca/ca-chain.crt` — позволяет проверить доверие, используя ваш локальный Bundle.
- `-tls1_3` (или `-tls1_2`) — форсирование версии протокола для проверки совместимости.
- `-status` — проверка OCSP Stapling (отправляет запрос статуса сертификата).
- `-brief` — краткий режим вывода, упрощающий парсинг (OpenSSL 3.0+).

#### Краткий вывод и проверка статуса верификации

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local -brief </dev/null
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → Verify return code: 0 (ok)
```

| Показатель | Ожидаемое значение | Смысл |
|:---|:---|:---|
| `Verify return code: 0 (ok)` | OK | Цепочка доверена |
| `Verify return code: 21` | `unable to verify the first certificate` | Сервер не отдает промежуточный CA |
| `Verify return code: 20` | `unable to get local issuer certificate` | В хранилище клиента нет корневого CA |
| `Handshake failure` | — | Нет общих шифров или протоколов |

#### Проверка OCSP Stapling

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local -status </dev/null | grep -A 5 "OCSP response"
# → OCSP Response Data:
# →     OCSP Response Status: successful (0x0)
```

### Проверка поддерживаемых версий TLS

```bash
# Проверка TLS 1.3 (рекомендуется в 2026)
openssl s_client -connect my-service.local:443 -servername my-service.local -tls1_3 </dev/null

# Проверка TLS 1.2 (для совместимости с устаревшими клиентами)
openssl s_client -connect my-service.local:443 -servername my-service.local -tls1_2 </dev/null>
```

### Верификация mTLS

Для проверки взаимной аутентификации используйте флаги `-cert` и `-key`:

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local \
    -CAfile intermediate-ca/ca-chain.crt -cert client.crt -key client.key </dev/null
```

Если клиентский сертификат подписан вашим Intermediate CA, handshake завершится успешно. В противном случае OpenSSL завершит соединение с ошибкой.

### Верификация цепочки доверия

Проверка конечного сертификата относительно полной цепочки CA:

```bash
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
```

Проверка самого промежуточного CA относительно корня:

```bash
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
```

### Верификация корневого CA (самоподписанный)

```bash
# Корневой сертификат должен проходить самоподпись
openssl verify -CAfile root-ca/ca.crt root-ca/ca.crt
# → ca.crt: OK

# Проверка соответствия ключа и корневого сертификата
openssl x509 -noout -modulus -in root-ca/ca.crt | openssl sha256
openssl rsa -noout -modulus -in root-ca/ca.key | openssl sha256
# Хеши должны совпасть
```

### Проверка расширений сертификата

```bash
# Просмотр всех расширений (Basic Constraints, Key Usage, EKU, SAN, AKI/SKI)
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 3 "Basic Constraints"
# → basicConstraints = critical, CA:true, pathlen:0

# Проверка только Subject Alternative Name
openssl x509 -in my-service.crt -noout -text | grep -A 1 "Subject Alternative Name"
# → DNS:service.local, DNS:www.service.local, IP:10.0.5.10
```

### Извлечение информации из цепочки сертификатов

```bash
# Анализ цепочки, передаваемой сервером
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null | grep -E "s:|i:"
# → s:/CN=my-service.local
# → i:/CN=My Private Intermediate CA, O = Dev, C = RU
# → i:/CN=My Private Root CA, O = Dev, C = RU
```

## Типичные ошибки и диагностика

### Ошибка: `unable to load certificate` / `certificate verify failed`

**Причина:** Путь к `ca.crt` или `ca.key` указан неверно, файлы повреждены или у процесса нет прав на чтение.

**Диагностика:**
```bash
# Проверка доступности файлов
ls -la intermediate-ca/ca-chain.crt root-ca/ca.crt intermediate-ca/intermediate.key

# Проверка читаемости
file intermediate-ca/ca-chain.crt root-ca/ca.crt
openssl x509 -in root-ca/ca.crt -noout -text
```

### Ошибка: `Verify return code: 20 (unable to get local issuer certificate)`

**Причина:** Корневой или промежуточный CA не установлен в доверенное хранилище операционной системы или не передан через `-CAfile`.

**Решение:**
```bash
# Для проверки вручную
openssl s_client -connect my-service.local:443 -servername my-service.local -CAfile intermediate-ca/ca-chain.crt </dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)

# Установка корня в ОС
# Debian/Ubuntu
sudo cp root-ca/ca.crt /usr/local/share/ca-certificates/internal-ca.crt
sudo update-ca-certificates

# RHEL/CentOS/Fedora
sudo cp root-ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### Ошибка: `Verify return code: 21 (unable to verify the first certificate)`

**Причина:** Сервер передает только leaf-сертификат без промежуточного CA. В двухуровневой архитектуре это означает, что сервер настроен некорректно.

**Диагностика:**
```bash
# Просмотр цепочки, передаваемой сервером
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null | grep -E "s:|i:"
# → s:/CN=my-service.local
# → i:/CN=My Private Intermediate CA, O = Dev, C = RU
```

**Решение:** Установите `fullchain.pem` (leaf + intermediate) в конфигурации TLS-сервера.

### Ошибка: `signature routines::unsupported algorithm`

**Причина:** Алгоритм хеширования, указанный в `-sha384`, не поддерживается провайдером OpenSSL 3.0+.

**Решение:** используйте `-sha256` или явно укажите провайдер Legacy:
```bash
openssl x509 -req -in service.csr -CA intermediate-ca/intermediate.crt -CAkey intermediate-ca/intermediate.key -CAcreateserial \
    -out service.crt -days 90 -sha256 -provider legacy
```

### Ошибка: `Error loading extension` / `invalid extension`

**Причина:** Синтаксис `subjectAltName` в `-extfile` указан неверно (отсутствуют `DNS:` или `IP:`, некорректные пробелы).

**Решение:** проверьте синтаксис:
```bash
# Корректный формат
subjectAltName=DNS:service.local,DNS:www.service.local,IP:10.0.0.5

# Некорректные примеры:
# subjectAltName=service.local           ← нет префикса DNS:
# subjectAltName=DNS:service.local IP:10.0.0.5  ← запятая вместо пробела
```

### Ошибка: `serial file already exists` / `trying to commit certificate twice`

**Причина:** Файл `.srl` с серийным номером уже существует, и OpenSSL не может его прочитать или записать.

**Решение:**
```bash
# Проверка содержимого
cat intermediate-ca/db/crlnumber

# Переинициализация (если нет конфликта с другими сертификатами)
echo "1000" > intermediate-ca/db/crlnumber
```

### Ошибка: `No value for key` / `unable to find key`

**Причина:** Флаг `-CAkey` указан, но ключ зашифрован парольной фразой, и OpenSSL не может его прочитать в неинтерактивном режиме.

**Решение:** либо вводите парольную фразу при запросе, либо используйте незашифрованный ключ для тестовых сред.

### Ошибка: `pathlen constraint violated`

**Причина:** Промежуточный CA пытается подписать другой CA, но в его сертификате установлено ограничение `pathlen:0`.

**Решение:** Используйте промежуточный CA только для подписи конечных сертификатов (серверов, клиентов), а не для создания подчиненных CA.

## Рекомендации и лучшие практики

### Предварительная проверка перед деплоем

Всегда выполняйте комплексную проверку перед установкой сертификата в production:

```bash
# 1. Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256
# Хеши должны совпасть

# 2. Проверка цепочки доверия (через Bundle)
openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt
# → service.crt: OK

# 3. Проверка срока действия
openssl x509 -in service.crt -noout -dates

# 4. Проверка SAN (обязательно для современных браузеров)
openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"
# → DNS:service.local, DNS:www.service.local, IP:10.0.5.10

# 5. Проверка AKI/SKI соответствия Intermediate CA
openssl x509 -in service.crt -noout -text | grep -A 1 "Authority Key Identifier"
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 1 "Subject Key Identifier"
# Значения должны совпадать
```

### Безопасность при работе с утилитами

- **Никогда не передавайте приватный ключ CA по сети.** Все операции с `intermediate.key` и `root-ca/ca.key` выполняйте на машине, где хранится CA.
- **Храните `service.key` с правами `600`.** Утечка приватного ключа сервиса позволяет impersonate-атаки.
- **Проверяйте `issuer` перед установкой:** убедитесь, что сертификат выпущен именно вашим Intermediate CA, а не публичным центром.
- **Используйте `-CAfile` явно:** не полагайтесь на системное хранилище CA в скриптах — указывайте корень явно.

### Автоматизация в CI/CD

Для встраивания диагностики в пайплайны используйте неинтерактивные флаги:

```bash
# Неинтерактивная проверка
if openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt | grep -q "OK"; then
    echo "Certificate is valid"
else
    echo "Certificate verification failed"
    exit 1
fi

# Проверка срока действия (если осталось меньше 30 дней — fail)
openssl x509 -in service.crt -noout -checkend 2592000 || echo "CRITICAL: Certificate expires soon"
```

## Ограничения и крайние случаи

- **OpenSSL 3.0+ провайдеры:** некоторые устаревшие алгоритмы (SHA-1, MD5) требуют явного включения провайдера Legacy. Без этого команды `verify` и `x509` завершатся ошибкой.
- **Совместимость оболочек:** команды с `<(printf ...)` требуют Bash. В Alpine Linux, Ubuntu/Debian (где `/bin/sh` → dash) используйте явный вызов Bash или временные файлы.
- **Энтропия в виртуальных средах:** генерация ключей на ВМ без аппаратного RNG может блокироваться. Используйте `haveged` или подключение к `/dev/random` через virtio-rng.
- **Сервисы с жесткими требованиями к совместимости:** некоторые устаревшие системы (например, старые Java-приложения до версии 8) могут требовать RSA-ключей и специфических расширений.
- **Регуляторные требования:** в финансовой и медицинской отраслях может требоваться использование сертифицированных средств криптозащиты (СКЗИ) с поддержкой ГОСТ.
- **Ограничение `pathlen`:** после установки `pathlen:0` в Intermediate CA невозможно создать подчиненный CA без перевыпуска Intermediate.

## Очистка и откат изменений

### Удаление временных файлов диагностики

```bash
# Удаление временных сертификатов и ключей
rm -f service.crt service.key service.csr service.srl

# Удаление установленных корневых сертификатов из доверенных хранилищ ОС
# Debian/Ubuntu
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo update-ca-trust

# Windows Server
certutil -delstore "Root" "CN=My Private Root CA"
certutil -delstore "CA" "CN=My Private Intermediate CA"
```

### Откат тестового окружения

Если сертификат был установлен в приложение (Nginx, Apache, Java Keystore), выполните откат в обратном порядке:

1. Удалите сертификат из конфигурации сервиса.
2. Перезапустите сервис.
3. Удалите корневой сертификат из доверенного хранилища ОС/контейнера.
4. Удалите файлы CA и сгенерированные ключи.

### Отзыв всех сертификатов (экстренный сценарий)

```bash
cd intermediate-ca

# Отзыв всех сертификатов через скрипт (формальный метод)
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done

# Генерация нового CRL
openssl ca -config openssl.cnf -gencrl -out db/crl.pem

# Распространение нового CRL на все сервисы
```

### Очистка тестовой среды

```bash
# Удаление тестовых сертификатов и ключей
rm -f service.crt service.key service.csr

# Очистка кэша OpenSSL
rm -rf ~/.openssl/
```

## Мониторинг и оповещение

### Проверка срока действия удаленных сертификатов

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

EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
            date -d "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 0 ]; then
  echo "CRITICAL: $HOST сертификат истёк $(( -DAYS_LEFT )) дней назад"
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: $HOST сертификат истекает через $DAYS_LEFT дней"
else
  echo "OK: $HOST сертификат действителен ещё $DAYS_LEFT дней"
fi
```

### Проверка срока действия Intermediate CA

```bash
#!/usr/bin/env bash
# Проверка срока действия Intermediate CA
CA_CRT="intermediate-ca/intermediate.crt"
DAYS_WARN="${1:-365}"
DAYS_CRIT="${2:-30}"

EXP_DATE=$(openssl x509 -in "$CA_CRT" -noout -enddate 2>/dev/null \
  | cut -d= -f2)

if [ -z "$EXP_DATE" ]; then
  echo "FAIL: Не удалось прочитать сертификат $CA_CRT"
  exit 1
fi

EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
            date -d "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 0 ]; then
  echo "CRITICAL: Intermediate CA истёк $(( -DAYS_LEFT )) дней назад"
  exit 2
elif [ "$DAYS_LEFT" -lt "$DAYS_CRIT" ]; then
  echo "CRITICAL: Intermediate CA истекает через $DAYS_LEFT дней"
  exit 2
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: Intermediate CA истекает через $DAYS_LEFT дней"
  exit 1
else
  echo "OK: Intermediate CA действителен ещё $DAYS_LEFT дней"
fi
```

**Интеграция с мониторингом:**
- Добавьте скрипт в cron для ежедневной проверки.
- Настройте оповещение в Slack/Telegram/PagerDuty при достижении критического порога.
- Для enterprise-сред интегрируйте с Prometheus Blackbox Exporter, указав `server_name`, соответствующий внутреннему домену (см. **[обзор PKI](../../../Concepts/pki_overview.md)**).

## Best Practices

- **Приватные ключи всегда offline:** Root CA ключ никогда не должен находиться на машине с сетевым доступом. Intermediate CA ключ — только в защищенном сегменте.
- **HSM/TPM для корневых ключей:** использование аппаратных модулей исключает возможность извлечения ключа.
- **Права доступа:** `ca.key` и `intermediate.key` должны иметь права `600` и принадлежать выделенному пользователю (например, `ca`).
- **Резервное копирование:** зашифрованные копии ключей хранятся отдельно от сертификатов, с использованием отдельного пароля или шифрования GPG.
- **Аудит:** ведение журнала всех операций подписи через `index.txt` и отправка событий в SIEM.
- **Ротация по расписанию:** ротация Intermediate CA каждые 3–5 лет, конечных сертификатов — по мере приближения срока действия.
- **CRL Distribution Points:** всегда указывайте доступные URL для CRL в расширениях сертификата.
- **Тестовый выпуск:** перед использованием в production выпускайте тестовый сертификат и проверяйте его через `openssl verify`.
- **Документация:** поддерживайте актуальную схему инфраструктуры и список ответственных администраторов.

## Дополнительная информация

### Карта документации двухуровневого CA

| Документ | Содержание |
|:---|:---|
| [overview.md](./overview.md) | Архитектура, сравнение с одноуровневым CA, общие концепции. |
| [root_ca_setup.md](./root_ca_setup.md) | Настройка корневого узла, конфигурация и безопасность офлайн-ключа. |
| [intermediate_ca_setup.md](./intermediate_ca_setup.md) | Создание промежуточного узла, работа с `ca-chain.crt` и HSM. |
| [service_certificate_management.md](./service_certificate_management.md) | Жизненный цикл сервисных сертификатов: выпуск, SAN, отзыв. |
| [common_utilities.md](./common_utilities.md) | Диагностика цепочек доверия, извлечение метаданных, отладка TLS. |

### Связанные темы

- **[Обзор PKI](../../../Concepts/pki_overview.md)** — фундаментальная теория инфраструктуры открытых ключей, алгоритмы 2026, PQC, расширения X.509.
- **[Обзор двухуровневого CA](./overview.md)** — архитектура, алгоритмы, хранилище ключей, порядок развёртывания, сценарии использования.
- **[Алгоритм диагностики](./troubleshooting_flowchart.md)** — decision-tree для поиска проблем с сертификатами.
- **[Диагностика SSL-сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — методы поиска ошибок в цепочках доверия.
- **[Certificate Automation](../../../../Ansible/ansible_certificate_management.md)** — автоматизация выдачи и ротации через Ansible.
- **[Утилиты и диагностика одноуровневого CA](../../openssl_ca/single_tier/common_utilities.md)** — сравнение подходов и команды для простой архитектуры.
