# Утилиты и диагностика одноуровневого CA

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты для подтверждения подлинности открытых ключей.

**Одноуровневый CA** — архитектура PKI, в которой один корневой CA напрямую подписывает сертификаты конечных сувисов (серверов, клиентов, пользователей) без промежуточных узлов.

**Цепочка доверия (Chain of Trust)** — в одноуровневой схеме состоит из двух звеньев: конечного сертификата сервиса и самоподписанного корневого сертификата CA (`ca.crt`). В отличие от двухуровневой архитектуры, здесь отсутствует промежуточное звено, что упрощает верификацию, но увеличивает риск при компрометации корня.

**CRL (Certificate Revocation List, Список отзыва сертификатов)** — подписанный CA файл, содержащий серийные номера аннулированных сертификатов. Позволяет клиентам отклонять compromised-сертификаты до истечения срока их действия.

**CSR (Certificate Signing Request, Запрос на подпись сертификата)** — файл, содержащий DN-информацию субъекта и открытый ключ, который отправляется в CA для выпуска подписанного сертификата.

**mTLS (Mutual TLS, Взаимный TLS)** — режим аутентификации, при котором и сервер, и клиент предъявляют сертификаты, подписанные доверенным CA.

**OpenSSL 3.0+** — актуальное поколение криптографического тулсета с архитектурой провайдеров (Default, Legacy, FIPS) и депрекацией устаревших параметров. Все примеры ниже протестированы на совместимость с OpenSSL 3.x.

Базовые понятия PKI (SAN, OCSP, AKI/SKI, Key Usage) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**.

## Базовые концепции

### Категории диагностических команд

Все команды OpenSSL для работы с сертификатами в одноуровневой архитектуре можно разделить на три функциональные группы:

- **Просмотр** — чтение содержимого и метаданных сертификатов, запросов CSR и списков CRL (команды `x509`, `req`, `crl`).
- **Верификация** — проверка криптографических подписей и соответствия пар «ключ — сертификат» (команды `verify`, `-modulus`, `pubkey`).
- **Подключение** — имитация клиента для проверки доступности и корректности настройки TLS-серверов (команда `s_client`).

### Архитектурные особенности одноуровневого CA

В одноуровневой схеме все операции верификации выполняются напрямую относительно корневого сертификата `ca/ca.crt`. Это отличает её от двухуровневых схем, где требуется использование промежуточных цепочек — подробнее см. **[утилиты двухуровневого CA](../two_tier/common_utilities.md)**.

| Операция | Одноуровневый CA | Двухуровневый CA |
| :--- | :--- | :--- |
| Доверенный корень | `ca.crt` | `ca-chain.crt` (Intermediate + Root) |
| Верификация сервиса | `-CAfile ca.crt` | `-CAfile ca-chain.crt` |
| Путь к CRL | `ca/crl.pem` | `intermediate-ca/db/crl.pem` |
| Аудит | Отсутствует (быстрый метод) | `index.txt` (формальный метод) |

### Безопасность и риски

**Ключевой риск — компрометация корневого ключа.** Поскольку корневой CA постоянно доступен онлайн для подписи новых сертификатов, его приватный ключ (`ca.key`) является единственной точой отказа. При утечке или потере этого ключа все выданные CA сертификаты становятся ненадежными и требуется полная перевыпуск инфраструктуры доверия.

**Меры смягчения:**
- Храните `ca.key` с правами `600` и в директории, доступной только для `root` или выделенного сервисного аккаунта.
- Используйте шифрование ключа парольной фразой (`-aes256` при генерации) в production-средах.
- Никогда не передавайте `ca.key` по сети. Все операции подписи выполняйте на машине, где хранится CA.
- Ведите журнал всех операций подписи через `index.txt` (формальный метод).

## Практические сценарии

### Предварительные требования

#### Аппаратные и программные требования

- **ОС:** Linux (Debian/Ubuntu, RHEL/CentOS/Fedora, Alpine) или macOS. Инструкции tested на Linux x86_64.
- **OpenSSL:** версия 3.0.0 или выше. Проверка: `openssl version -a`.
- **Права:** доступ пользователя с возможностью чтения файлов CA (`ca/ca.crt`, `ca/ca.key`). Для установки сертификатов в системные хранилища требуются права `root` или `sudo`.
- **Дисплей:** для операций с парольной фразой (если ключ CA шифруется) требуется терминал с поддержкой ввода пароля.

#### Проверка окружения

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

#### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y openssl libssl-dev

# RHEL/CentOS/Fedora
sudo dnf install -y openssl openssl-devel

# Alpine
sudo apk add openssl openssl-dev
```

### Просмотр содержимого сертификата

```bash
openssl x509 -in my-service.crt -noout -text
```

Команда выводит все значимые поля: Subject (Субъект), Issuer (Издатель), сроки действия, серийный номер, расширения (SAN, Key Usage, Basic Constraints, AKI/SKI).

#### Полезные флаги для целенаправленного просмотра

```bash
# Только Subject и Issuer
openssl x509 -in my-service.crt -noout -subject -issuer
# → subject=CN = my-service.local, O = Dev, C = RU
# → issuer=CN = My Private Root CA, O = Dev, C = RU

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

Позволяет проверить DN-информацию (Distinguished Name, Отличительное имя) и открытый ключ до момента подписи запроса администратором CA.

```bash
# Только Subject и открытый ключ
openssl req -in my-service.csr -noout -subject -pubkey
```

### Проверка соответствия ключа и сертификата

Для корректной работы TLS-сервера приватный ключ должен соответствовать открытому ключу в сертификате.

#### Сценарий А: Для RSA (сравнение модуля)

Используется хеширование модуля (`modulus`). Хеши должны быть идентичны.

```bash
openssl rsa -noout -modulus -in my-service.key | openssl sha256
openssl x509 -noout -modulus -in my-service.crt | openssl sha256
# Хеши должны совпасть
```

#### Сценарий Б: Для ECDSA/Ed25519 (сравнение публичного ключа)

Поскольку понятие «модуль» неприменимо к эллиптическим кривым, сравниваются хеши публичных ключей, извлеченных из обоих файлов.

```bash
# Извлечение публичного ключа из приватного
openssl pkey -in my-service.key -pubout -outform DER | openssl sha256
# Извлечение публичного ключа из сертификата
openssl x509 -in my-service.crt -pubkey -noout -outform DER | openssl sha256
# Хеши должны совпасть
```

### Верификация цепочки доверия

```bash
# Проверка подписи конечного сертификата относительно корневого CA
openssl verify -CAfile ca/ca.crt my-service.crt
# → my-service.crt: OK
```

Для формального метода с промежуточными сертификатами используйте `-untrusted`:

```bash
# Проверка с указанием промежуточного CA (если есть)
openssl verify -CAfile ca/ca.crt -untrusted intermediate.crt my-service.crt
# → my-service.crt: OK
```

В одноуровневой архитектуре промежуточного CA нет, поэтому достаточно только `-CAfile ca/ca.crt`.

### Просмотр списка отозванных сертификатов CRL

```bash
openssl crl -in ca/crl.pem -noout -text
```

Отображает серийные номера аннулированных сертификатов и дату генерации списка. Подробнее о процедуре отзыва — в **[управлении сертификатами](./service_certificate_management.md#отзыв-и-работа-с-crl)**.

```bash
# Поиск конкретного серийного номера в CRL
openssl crl -in ca/crl.pem -noout -text | grep -A 1 "Serial Number:"
```

### Проверка срока действия

```bash
# Текущие сроки действия
openssl x509 -in my-service.crt -noout -enddate
# → notAfter=Apr  9 12:00:00 2027 GMT

# Проверка, действителен ли сертификат в данный момент
openssl x509 -in my-service.crt -noout -checkend 86400
# Проверяет, не истечет ли сертификат в ближайшие 24 часа (86400 сек)
# → Certificate will expire
```

### Диагностика удаленного TLS-сервера

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null
```

**Критические флаги:**
- `-servername` — **Обязателен** для современных серверов (SNI). Без него сервер может отдать дефолтный (неверный) сертификат.
- `-CAfile ca/ca.crt` — позволяет проверить доверие, используя ваш локальный корень.
- `-tls1_3` (или `-tls1_2`) — форсирование версии протокола для проверки совместимости.
- `-status` — проверка OCSP Stapling (отправляет запрос статуса сертификата).
- `-brief` — краткий режим вывода, упрощающий парсинг (OpenSSL 3.0+).

#### Анализ вывода s_client

```bash
# Краткий вывод и проверка статуса верификации
openssl s_client -connect my-service.local:443 -servername my-service.local -brief </dev/null
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → Verify return code: 0 (ok)
```

| Показатель | Ожидаемое значение | Смысл |
| :--- | :--- | :--- |
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
openssl s_client -connect my-service.local:443 -servername my-service.local -tls1_2 </dev/null
```

### Верификация mTLS

Для проверки взаимной аутентификации используйте флаги `-cert` и `-key`:

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local \
    -CAfile ca/ca.crt -cert client.crt -key client.key </dev/null
```

Если клиентский сертификат подписан вашим CA, handshake завершится успешно. В противном случае OpenSSL завершит соединение с ошибкой.

### Верификация корневого CA (самоподписанный)

```bash
# Корневой сертификат должен проходить самоподпись
openssl verify -CAfile ca/ca.crt ca/ca.crt
# → ca/ca.crt: OK

# Проверка соответствия ключа и корневого сертификата
openssl x509 -noout -modulus -in ca/ca.crt | openssl sha256
openssl rsa -noout -modulus -in ca/ca.key | openssl sha256
# Хеши должны совпасть
```

## Типичные ошибки и диагностика

### Ошибка: `unable to load certificate` / `certificate verify failed`

**Причина:** Путь к `ca.crt` или `ca.key` указан неверно, файлы повреждены или у процесса нет прав на чтение.

**Диагностика:**
```bash
# Проверка доступности файлов
ls -la ca/ca.crt ca/ca.key

# Проверка читаемости
file ca/ca.crt ca/ca.key
openssl x509 -in ca/ca.crt -noout -text
```

### Ошибка: `Verify return code: 20 (unable to get local issuer certificate)`

**Причина:** Корневой CA не установлен в доверенное хранилище операционной системы или не передан через `-CAfile`.

**Решение:**
```bash
# Для проверки вручную
openssl s_client -connect my-service.local:443 -servername my-service.local -CAfile ca/ca.crt </dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)

# Установка корня в ОС
# Debian/Ubuntu
sudo cp ca/ca.crt /usr/local/share/ca-certificates/internal-ca.crt
sudo update-ca-certificates

# RHEL/CentOS/Fedora
sudo cp ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### Ошибка: `Verify return code: 21 (unable to verify the first certificate)`

**Причина:** Сервер передает только leaf-сертификат без промежуточного CA. В одноуровневой архитектуре это означает, что сервер настроен некорректно.

**Диагностика:**
```bash
# Просмотр цепочки, передаваемой сервером
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null | grep -E "s:|i:"
# → s:/CN=my-service.local
# → i:/CN=My Private Root CA
```

### Ошибка: `signature routines::unsupported algorithm`

**Причина:** Алгоритм хеширования, указанный в `-sha384`, не поддерживается провайдером OpenSSL 3.0+.

**Решение:** используйте `-sha256` или явно укажите провайдер Legacy:
```bash
openssl x509 -req -in service.csr -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial \
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
cat service.srl

# Переинициализация (если нет конфликта с другими сертификатами)
echo "1000" > service.srl
```

### Ошибка: `No value for key` / `unable to find key`

**Причина:** Флаг `-CAkey` указан, но ключ зашифрован парольной фразой, и OpenSSL не может его прочитать в неинтерактивном режиме.

**Решение:** либо вводите парольную фразу при запросе, либо используйте незашифрованный ключ для тестовых сред.

## Рекомендации и лучшие практики

### Предварительная проверка перед деплоем

Всегда выполняйте комплексную проверку перед установкой сертификата в production:

```bash
# 1. Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256
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
- **Храните `service.key` с правами `600`.** Утечка приватного ключа сервиса позволяет impersonate-атаки.
- **Проверяйте `issuer` перед установкой:** убедитесь, что сертификат выпущен именно вашим CA, а не публичным центром.
- **Используйте `-CAfile` явно:** не полагайтесь на системное хранилище CA в скриптах — указывайте корень явно.

### Автоматизация в CI/CD

Для встраивания диагностики в пайплайны используйте неинтерактивные флаги:

```bash
# Неинтерактивная проверка
if openssl verify -CAfile ca/ca.crt service.crt | grep -q "OK"; then
    echo "Certificate is valid"
else
    echo "Certificate verification failed"
    exit 1
fi

# Проверка срока действия (если осталось меньше 30 дней — fail)
openssl x509 -in service.crt -noout -checkend 2592000 || echo "CRITICAL: Certificate expires soon"
```

## Ограничения и крайние случаи

- **Отсутствие статусов сертификатов:** в одноуровневой архитектуре без формального метода (`openssl ca` с `index.txt`) нет возможности отслеживать статус (Valid/Revoked/Expired) без ручного сканирования CRL.
- **CRL в одноуровневой схеме:** CRL должен генерироваться вручную. В формальном методе это делается через `openssl ca -gencrl`. В быстром методе CRL может отсутствовать полностью.
- **Совместимость оболочек:** команды с `<(printf ...)` требуют Bash. В Alpine Linux, Ubuntu/Debian (где `/bin/sh` → dash) используйте явный вызов Bash или временные файлы.
- **Сервисы с жесткими требованиями к совместимости:** некоторые устаревшие системы (например, старые Java-приложения до версии 8) могут требовать RSA-ключей и специфических расширений.
- **Накладные расходы на проверку:** при росте числа сертификатов (>100) проверка целостности через `index.txt` становится предпочтительнее ручных команд.
- **Регуляторные требования:** в некоторых отраслях (финансы, медицина) требуется использование двухуровневой архитектуры и сертифицированных криптографических средств (СКЗИ).

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
```

### Откат тестового окружения

Если сертификат был установлен в приложение (Nginx, Apache, Java Keystore), выполните откат в обратном порядке:

1. Удалите сертификат из конфигурации сервиса.
2. Перезапустите сервис.
3. Удалите корневой сертификат из доверенного хранилища ОС/контейнера.
4. Удалите файлы CA и сгенерированные ключи.

### Отзыв всех сертификатов (экстренный сценарий)

```bash
cd ca

# Отзыв всех сертификатов через скрипт (формальный метод)
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done

# Генерация нового CRL
openssl ca -config openssl.cnf -gencrl -out crl.pem

# Распространение нового CRL на все сервисы
```

### Параллельная подпись с flock (безопасная автоматизация)

При параллельных вызовах `openssl ca` (Ansible, CI/CD, cron) возникает гонка за `index.txt`. Решение — обёртка с блокировкой `flock`:

```bash
#!/bin/bash
# sign-cert.sh — подпись сертификата с блокировкой (безопасна для параллельных вызовов)
set -euo pipefail

CA_DIR="/opt/ca"
LOCK_FILE="$CA_DIR/db/index.lock"
CSR_FILE="$1"
OUTPUT_FILE="$2"

(
    flock -n 200 || { echo "ERROR: CA is busy, try later"; exit 1; }

    cd "$CA_DIR"
    openssl ca -config openssl.cnf \
        -in "$CSR_FILE" -out "$OUTPUT_FILE" \
        -extensions v3_req -notext -batch

) 200>"$LOCK_FILE"
```

- `flock -n 200`: неблокирующая блокировка (файловый дескриптор 200). Если другой процесс удерживает блокировку — немедленный выход с ошибкой
- `200>"$LOCK_FILE"`: создание lock-файла и привязка к дескриптору

Использование в Ansible:

```yaml
- name: Sign certificate
  ansible.builtin.command: >
    /opt/scripts/sign_cert.sh
    {{ item.csr_path }}
    {{ item.cert_path }}
  loop: "{{ certificate_requests }}"
  throttle: 1
```

### Логирование и аудит операций CA

#### Статистика по index.txt

```bash
# Количество выпущенных/отозванных/истёкших сертификатов
echo "Выдано: $(grep -c "^V" ca/db/index.txt)"
echo "Отозвано: $(grep -c "^R" ca/db/index.txt)"
echo "Истекло: $(grep -c "^E" ca/db/index.txt)"

# Последние 5 выпущенных
grep "^V" ca/db/index.txt | tail -5
# → V  260101120000Z  0A1B2C3D  unknown  /C=RU/.../CN=service.local

# Отозванные с датой отзыва
grep "^R" ca/db/index.txt
# → R  250601120000Z  4E5F6A7B  unknown  250601120000Z  /C=RU/.../CN=revoked.local
```

#### Перенаправление логов OpenSSL в syslog

```bash
#!/bin/bash
# sign-with-audit.sh — подпись с аудитом в syslog
CA_DIR="/opt/ca"
LOG_TAG="openssl-ca"
CSR="$1"
OUTPUT="$2"
OPERATOR=$(whoami)

logger -t "$LOG_TAG" "START_SIGN operator=$OPERATOR csr=$CSR"

cd "$CA_DIR"
if openssl ca -config openssl.cnf -in "$CSR" -out "$OUTPUT" \
    -extensions v3_req -notext -batch 2>&1; then
    SERIAL=$(openssl x509 -in "$OUTPUT" -noout -serial | cut -d= -f2)
    logger -t "$LOG_TAG" "SUCCESS_SIGN serial=$SERIAL output=$OUTPUT operator=$OPERATOR"
else
    logger -t "$LOG_TAG" "FAIL_SIGN csr=$CSR operator=$OPERATOR"
    exit 1
fi
```

```bash
# Просмотр логов
journalctl -t openssl-ca --since "1 hour ago"
```

### Сравнение методов управления

| Характеристика | Быстрый метод | Формальный метод |
| :--- | :--- | :--- |
| **База данных** | Отсутствует | Обязательна (`index.txt`) |
| **Учёт статусов** | Нет | Да (Valid, Revoked, Expired) |
| **Поддержка CRL** | Нет | Да |
| **Сложность** | Низкая | Средняя |
| **Рекомендация** | Локальные тесты, Docker | Инфраструктурные сервисы, mTLS |

### Связанные темы

- [Обзор одноуровневого CA](./overview.md) — архитектурные подходы и сравнение.
- [Настройка CA](./ca_setup.md) — создание корневой инфраструктуры и `openssl.cnf`.
- [Управление сертификатами сервисов](./service_certificate_management.md) — формальный метод выпуска и отзыва сертификатов.
- [Конвертация форматов](./formats_and_advanced_config.md) — PEM/DER/PKCS#12, продвинутый openssl.cnf.
- [Диагностика SSL/TLS сертификатов](../../ssl_certificate_diagnostics.md) — решение типичных ошибок при настройке TLS.
