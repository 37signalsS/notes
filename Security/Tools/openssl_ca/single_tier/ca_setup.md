# Настройка одноуровневого CA

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты.

**Одноуровневый CA** — упрощенная архитектура центра сертификации, в которой корневой CA напрямую подписывает сертификаты конечных сущностей (серверов, клиентов). Не рекомендуется для производственных сред из-за риска компрометации корневого ключа.

**Конфигурационный файл (openssl.cnf)** — центральный файл настроек CA, определяющий политики, расширения, пути к базам данных и параметры генерации сертификатов.

**CSR (Certificate Signing Request, Запрос на подпись сертификата)** — файл, содержащий информацию о субъекте и открытый ключ, который отправляется в CA для выпуска сертификата.

**Самоподписанный сертификат** — сертификат CA, подписанный собственным приватным ключом. Является корневым якорем доверия для всей иерархии.

**X.509** — стандарт ITU-T для инфраструктуры открытых ключей (PKI), определяющий формат сертификатов открытых ключей.

**OpenSSL 3.0+** — актуальная версия криптографического тулсета, в которой внедрена архитектура провайдеров (Default, FIPS, Legacy). Параметр `RANDFILE` не нужен с OpenSSL 1.1.1 и сохраняется лишь для обратной совместимости. Все инструкции ниже ориентированы на эту версию.

**mTLS (Mutual TLS, Взаимный TLS)** — режим аутентификации, при котором и сервер, и клиент предъявляют сертификаты, подписанные доверенным CA.

## Базовые концепции

### Особенности одноуровневой архитектуры

В одноуровневой схеме корневой CA (Root CA) напрямую выпускает сертификаты для конечных узлов. Это упрощает управление, но снижает безопасность, так как компрометация единственного ключа требует полной перенастройки инфраструктуры доверия.

Подробное сравнение с двухуровневой схемой и области применения описаны в **[обзоре архитектуры](./overview.md#назначение-одноуровневого-ca)**.

### Совместимость версий

Инструкции ориентированы на **OpenSSL 3.0+**. В этой версии произошли важные изменения:
- Параметр `RANDFILE` в конфигурации признан устаревшим (депрекация) и игнорируется, так как OpenSSL теперь использует системные генераторы случайных чисел напрямую.
- По умолчанию включены современные алгоритмы хеширования (SHA-2).
- Улучшена поддержка алгоритмов на эллиптических кривых (ECDSA) и Ed25519.

### Подготовка структуры

Работа с CA по формальному методу требует наличия базы данных и специфической иерархии папок для учёта выданных и отозванных сертификатов.

Инструкции по созданию директорий и назначение файлов базы данных (`index.txt`, `serial`) приведены в **[обзоре одноуровневого CA](./overview.md#формальный-метод-создание-структуры-ca)**.

## Практические сценарии

### Предварительные требования

#### Аппаратные и программные требования

- **ОС:** Linux (Debian/Ubuntu, RHEL/CentOS/Fedora, Alpine) или macOS. Инструкции tested на Linux x86_64.
- **OpenSSL:** версия 3.0.0 или выше. Проверка: `openssl version -a`.
- **Права:** доступ пользователя с возможностью выполнения `sudo` для установки системных сертификатов и создания файлов в защищенных директориях.
- **Дисплей:** для операций с парольной фразой (если ключ шифруется) требуется терминал с поддержкой ввода пароля.

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

### Создание конфигурационного файла openssl.cnf

Файл `ca/openssl.cnf` содержит все настройки CA. Это упрощает последующие команды подписи и управления.

```ini
# ca/openssl.cnf

[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
certs           = $dir/certs                # Не используется, но должно быть
crl_dir         = $dir/crl                  # Директория для CRL
database        = $dir/db/index.txt         # Путь к базе данных сертификатов
new_certs_dir   = $dir/db/newcerts          # Куда сохранять новые сертификаты

certificate     = $dir/ca.crt               # Корневой сертификат CA
serial          = $dir/db/serial            # Файл с серийным номером
crlnumber       = $dir/db/crlnumber         # Файл с номером CRL
crl             = $dir/crl.pem              # Текущий CRL (создается позже)
private_key     = $dir/ca.key               # Приватный ключ CA

# RANDFILE      = $dir/db/.rand             # УСТАРЕЛО в OpenSSL 3.0+ (можно удалить)

default_md      = sha512                    # Алгоритм хеширования по умолчанию
default_days    = 365                       # Срок действия сертификата по умолчанию (1 год)
preserve        = no                        # Поля в CSR должны совпадать с полями CA
policy          = policy_match              # Политика проверки полей
unique_subject  = no                        # Разрешить несколько сертификатов с одинаковым CN
copy_extensions = copy                      # Копировать расширения из CSR в подписываемый сертификат
default_crl_days= 30                        # Срок действия CRL по умолчанию (30 дней)

# Политика, требующая совпадения страны, региона и организации
# с данными корневого CA.
[ policy_match ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

# Объяснение политики:
# match    - поле в CSR должно в точности совпадать со значением в сертификате CA.
#            Это строгая политика, гарантирующая, что все сертификаты,
#            например, принадлежат одной организации и стране.
# supplied - поле должно присутствовать в CSR. Его значение может быть любым.
#            Используется для уникальных имен, таких как Common Name.
# optional - поле может отсутствовать в CSR. Если оно есть, его значение не проверяется.

[ req ]
default_bits        = 4096                  # Длина ключа RSA по умолчанию
default_md          = sha512                # Алгоритм хеширования
distinguished_name  = req_distinguished_name
x509_extensions     = v3_ca                 # Расширения для корневого CA
prompt              = no                    # Не задавать вопросы при создании CSR

[ req_distinguished_name ]
C  = RU
ST = Moscow
L  = Moscow
O  = My Private Org
OU = IT Department
CN = My Private Root CA

# Расширения для корневого сертификата (v3_ca)
[ v3_ca ]
# Идентификатор ключа субъекта (Subject Key Identifier, SKI)
# Генерирует уникальный хэш открытого ключа самого сертификата.
# Позволяет отличать разные сертификаты, выданные одному и тому же лицу.
subjectKeyIdentifier   = hash

# Идентификатор ключа центра сертификации (Authority Key Identifier, AKI)
# Копирует SKI из сертификата CA, который подписывает данный сертификат.
# Это позволяет построить цепочку доверия: AKI дочернего сертификата
# должен совпадать с SKI родительского. `keyid:always` гарантирует
# его наличие, `issuer` добавляет имя и серийный номер CA.
authorityKeyIdentifier = keyid:always,issuer

# Основные ограничения (Basic Constraints)
# `critical` означает, что это расширение должно быть понято и обработано.
# `CA:true` — это то, что делает сертификат сертификатом CA. Он может подписывать другие.
basicConstraints       = critical, CA:true

# Использование ключа (Key Usage)
# Определяет, для каких криптографических операций может быть использован этот ключ.
# `digitalSignature`: проверка подписей (кроме сертификатов и CRL)
# `cRLSign`: подпись списков отзыва (CRL)
# `keyCertSign`: подпись других сертификатов
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign

# Расширения для сертификатов клиентов/серверов (конечных сущностей)
[ v3_req ]
# `CA:FALSE` означает, что этот сертификат не может подписывать другие.
basicConstraints       = CA:FALSE
# `nonRepudiation`: для неотрекаемости
# `digitalSignature`: для цифровой подписи
# `keyEncipherment`: для шифрования ключей (например, в TLS handshake)
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
# Назначение: аутентификация сервера и/или клиента
extendedKeyUsage       = serverAuth, clientAuth
# Указываем, что альтернативные имена субъекта (SAN) нужно брать из секции [alt_names]
subjectAltName         = @alt_names

# Секция для альтернативных имен субъекта (SAN)
# --- ВАЖНО ---
# Современные браузеры (Chrome >= 58, Firefox >= 48) и стандарты (RFC 2818)
# требуют, чтобы доменные имена и IP-адреса находились в расширении
# Subject Alternative Name (SAN). Поле Common Name (CN) считается устаревшим
# для этой цели и игнорируется, если присутствует SAN.
#
# ЭТУ СЕКЦИЮ НУЖНО РЕДАКТИРОВАТЬ ПЕРЕД ВЫПУСКОМ КАЖДОГО СЕРТИФИКАТА.
[alt_names]
DNS.1 = my-service.local
DNS.2 = www.my-service.local
IP.1  = 192.168.1.10
```

#### Пояснение к новым параметрам

- `unique_subject = no`: разрешает выпускать несколько сертификатов с одинаковым CN. По умолчанию OpenSSL требует уникальности CN, что неудобно в гетерогенных средах.
- `copy_extensions = copy`: копирует расширения из CSR в выпускаемый сертификат. Позволяет передавать SAN через CSR, не меняя конфиг CA каждый раз. Для production рекомендуется значение `copy` или `copyall`.
- `default_crl_days = 30`: срок действия CRL. По истечении этого срока клиенты, проверяющие отзыв, считают CRL недействительным.

### Создание корневого ключа и сертификата CA

Корневой сертификат — это основа доверия всей системы. Он создается и подписывается собственным ключом (самоподписанный).

> **О безопасности ключа CA**
> Флаг `-nodes` (no DES) отключает шифрование приватного ключа паролем. Это удобно для тестов, но **абсолютно недопустимо в производственной среде**. Компрометация приватного ключа корневого CA означает компрометацию всей инфраструктуры доверия. В реальности ключ корневого CA должен:
>
> 1. Быть защищен сложной парольной фразой (passphrase).
> 2. Храниться на физически изолированном носителе (air-gapped-система, аппаратный модуль безопасности HSM — Hardware Security Module), который никогда не подключается к сети.
>
> Для production-сред настоятельно рекомендуется [двухуровневая архитектура](../two_tier/overview.md), где корневой ключ Root CA генерируется один раз и немедленно убирается в офлайн.

#### Вариант 1: Использование RSA (классический метод)

Подходит для максимальной совместимости со старыми системами.

```bash
cd ca

# Создаем приватный ключ (ca.key) и самоподписанный сертификат (ca.crt)
openssl req -new -x509 \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650

# Вернемся в родительскую директорию
cd ..
```

- `-x509`: Создать самоподписанный сертификат вместо запроса (CSR).
- `-newkey rsa:4096`: Сгенерировать новый 4096-битный RSA-ключ.
- `-nodes`: (No DES) Не шифровать приватный ключ паролем.
- `-config`: Использовать наш конфигурационный файл. Поля из секции `[req_distinguished_name]` будут подставлены автоматически.
- `-days 3650`: Срок действия сертификата — 10 лет.

#### Вариант 2: Использование ECDSA (современный метод, рекомендуемый в 2026)

Алгоритмы на эллиптических кривых обеспечивают тот же уровень безопасности при гораздо меньшей длине ключа, что ускоряет TLS-handshake.

```bash
cd ca

# Генерация ключа и сертификата на кривой P-384
openssl req -new -x509 \
    -config openssl.cnf \
    -newkey ec:<(openssl ecparam -name secp384r1) \
    -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650

cd ..
```

- `-newkey ec:<(...)`: Генерация ключа на базе эллиптических кривых (параметры `secp384r1` эквивалентны по стойкости RSA 7680 бит).

#### Вариант 3: Использование Ed25519 (современный метод, максимальная производительность)

Алгоритм Ed25519 обеспечивает высокую скорость подписи и верификации, а также компактные ключи и сертификаты. Подходит для новых инфраструктур, где не требуется совместимость с устаревшими RSA-системами.

```bash
cd ca

# Генерация ключа и сертификата Ed25519
openssl req -new -x509 \
    -config openssl.cnf \
    -newkey ed25519 \
    -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650

cd ..
```

> **Примечание:** Ed25519 не поддерживает произвольную длину ключа и алгоритмы хеширования SHA-512 по умолчанию. В OpenSSL 3.0+ поддержка Ed25519 встроена в провайдер Default.

### Права доступа и безопасность хранения

После генерации ключей необходимо установить корректные права доступа:

```bash
# Приватный ключ CA — только для владельца, без чтения для группы и остальных
chmod 600 ca/ca.key

# Сертификат CA — можно сделать читаемым для всех
chmod 644 ca/ca.crt

# Директория CA — доступ только владельцу
chmod 700 ca

# База данных — доступ только владельцу
chmod 700 ca/db
chmod 600 ca/db/index.txt
chmod 600 ca/db/serial
chmod 600 ca/db/crlnumber
```

> **Важно:** Приватный ключ `ca.key` никогда не должен быть доступен для чтения другими пользователями или группами. В Linux-системах проверяйте права командой `ls -la ca/ca.key`.

### Верификация созданного сертификата

После генерации крайне важно убедиться, что сертификат содержит правильные расширения (особенно `CA:true`).

```bash
# Просмотр содержимого сертификата в текстовом виде
openssl x509 -in ca/ca.crt -text -noout

# Проверка, является ли сертификат самоподписанным и валидным
openssl verify -CAfile ca/ca.crt ca/ca.crt
# → ca/ca.crt: OK

# Проверка соответствия ключа и сертификата (RSA)
openssl x509 -noout -modulus -in ca/ca.crt | openssl sha256
openssl rsa -noout -modulus -in ca/ca.key | openssl sha256
# Хеши должны совпасть

# Проверка соответствия ключа и сертификата (ECDSA/Ed25519)
openssl x509 -in ca/ca.crt -pubkey -noout -outform DER | openssl sha256
openssl pkey -in ca/ca.key -pubout -outform DER | openssl sha256
# Хеши должны совпасть
```

В выводе `openssl x509` обратите внимание на:
- `X509v3 Basic Constraints: critical`: `CA:TRUE`
- `X509v3 Key Usage: critical`: `Digital Signature, Certificate Sign, CRL Sign`

### Резервное копирование и восстановление

Создание резервной копии корневого CA является критически важной операцией. Без актуального бэкапа компрометация или потеря ключа приводит к полной потере доверия всей инфраструктуры.

#### Создание резервной копии

```bash
# Создание защищенного архива с корневым CA
tar czf ca-backup-$(date +%Y%m%d).tar.gz ca/ca.key ca/ca.crt ca/db/

# Опционально: шифрование архива парольной фразой
gpg --symmetric --cipher-algo AES256 ca-backup-$(date +%Y%m%d).tar.gz
```

#### Восстановление из резервной копии

```bash
# Распаковка архива
tar xzf ca-backup-20260918.tar.gz -C /restore/path/

# Если архив был зашифрован
gpg --decrypt ca-backup-20260918.tar.gz.gpg | tar xzf - -C /restore/path/
```

> **Важно:** Храните резервные копии на физически изолированных носителях (USB-диски, ленты) и в защищенных местах (сейф, банковская ячейка). Никогда не храните бэкапы на тех же серверах, где работает CA.

### Автоматизация и переменные окружения

При интеграции CA в скрипты и CI/CD пайплайны удобно использовать переменные окружения вместо хардкода путей.

```bash
# Переменные окружения для OpenSSL
export OPENSSL_CONF=/path/to/ca/openssl.cnf
export CA_DIR=/path/to/ca
export CA_CERT=$CA_DIR/ca.crt
export CA_KEY=$CA_DIR/ca.key
export CA_DB=$CA_DIR/db/index.txt
export CA_SERIAL=$CA_DIR/db/serial

# Использование в командах
openssl x509 -in $CA_CERT -noout -text
```

> **Примечание:** Переменная `OPENSSL_CONF` позволяет переопределить путь к конфигурационному файлу globally для всех вызовов `openssl` в текущей сессии. Это удобно для тестирования, но в production лучше явно указывать `-config` для предотвращения случайного использования неверного конфига.

### Типичные ошибки и диагностика

#### Ошибка: `database locked`

**Причина:** Другой процесс (например, параллельный вызов `openssl ca`) удерживает блокировку на файле `index.txt`.

**Решение:**
```bash
# Проверка блокировок
ls -la ca/db/index.txt.*

# Удаление устаревших блокировок (только если нет запущенных процессов openssl ca)
rm -f ca/db/index.txt.lock
```

> **Важно:** Никогда не удаляйте файлы блокировок во время активной работы с CA. Это может привести к повреждению базы данных.

#### Ошибка: `failed to update database` / `trying to commit certificate twice`

**Причина:** Попытка подписать сертификат с серийным номером, который уже присутствует в базе. Проверьте `ca/db/serial` и `ca/db/index.txt`.

**Решение:**
```bash
# Проверка серийных номеров
cat ca/db/serial
grep "SERIAL_NUMBER" ca/db/index.txt
```

#### Ошибка: `unable to load certificate` / `certificate verify failed`

**Причина:** Сертификат не подписан нужным CA, поврежден или истек срок действия.

**Диагностика:**
```bash
# Проверка подписи
openssl verify -CAfile ca/ca.crt service.crt

# Проверка срока действия
openssl x509 -in service.crt -noout -dates

# Проверка цепочки с промежуточным звеном (если есть)
openssl verify -CAfile ca/ca.crt -untrusted intermediate.crt service.crt
```

#### Ошибка: `no serial number set` / `problem with the serial number`

**Причина:** Файл `db/serial` пуст или имеет неверный формат (должен быть hex-число).

**Решение:**
```bash
# Переинициализация серийного номера
echo "1000" > ca/db/serial
```

### Ограничения и крайние случаи

#### Ограничение одноуровневой архитектуры

- **Точка отказа:** Компрометация корневого ключа требует отзыва и перевыпуска всех сертификатов в инфраструктуре.
- **Масштабируемость:** Высокая нагрузка на корневой ключ при большом количестве конечных сертификатов. Для сред с >100 узлов рекомендуется переход на двухуровневую архитектуру.
- **Отсутствие делегирования:** Все подписи выполняются корневым ключом, что требует его постоянной доступности онлайн.

#### Сценарии с нестандартными DN

OpenSSL по умолчанию ожидает определенный набор полей DN. При работе с унаследованными системами могут потребоваться нестандартные атрибуты (например, `businessCategory`, `jurisdictionCountryName`). В этом случае расширьте секции `[req_distinguished_name]` и политики в `openssl.cnf`.

#### Сетевая изоляция и доступ к CA

Если CA находится в изолированном сегменте сети, доступ к нему для подписи сертификатов должен обеспечиваться через:
- **VPN-туннели** между сегментами.
- **Jump-хосты (bastion hosts)** с ограниченным доступом.
- **Офлайн-подпись:** генерация CSR на целевом сервере, передача CSR администратору CA по защищенному каналу, возврат подписанного сертификата.

### Очистка и откат изменений

#### Удаление CA и всех сертификатов

```bash
# Полное удаление директории CA (необратимо!)
rm -rf ca/

# Удаление установленных корневых сертификатов из доверенных хранилищ ОС
# Debian/Ubuntu
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo update-ca-trust
```

#### Отзыв всех сертификатов (экстренный сценарий)

```bash
# Переход в директорию CA
cd ca

# Отзыв всех сертификатов через скрипт (аккуратно!)
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done

# Генерация нового CRL
openssl ca -config openssl.cnf -gencrl -out crl.pem

# Распространение нового CRL на все сервисы
```

### Верификация и интеграция с сервисами

После создания CA и выпуска сертификатов необходимо убедиться, что инфраструктура корректно их воспринимает.

#### Проверка в операционной системе

```bash
# Debian/Ubuntu — проверка наличия в хранилище
grep -i "My Private Root CA" /usr/local/share/ca-certificates/internal-ca.crt

# RHEL/CentOS/Fedora
trust list | grep "My Private Root CA"

# macOS — проверка связки ключей (Keychain)
security find-certificate -c "My Private Root CA" /System/Library/Keychains/SystemRootCertificates.keychain
```

#### Проверка TLS-соединения

```bash
# Проверка handshake с использованием внутреннего CA
openssl s_client -connect my-service.local:443 -servername my-service.local -CAfile ca/ca.crt </dev/null

# Ожидаемый результат: Verify return code: 0 (ok)
```

#### Проверка mTLS

```bash
# Сервер запрашивает клиентский сертификат, клиент предъявляет свой
openssl s_client -connect my-service.local:443 -servername my-service.local \
    -CAfile ca/ca.crt -cert client.crt -key client.key </dev/null
```

### Чеклист тестирования CA перед production

Перед использованием CA в production выполните полную проверку:

```bash
#!/bin/bash
# ca-selftest.sh — проверка целостности одноуровневого CA
CA_DIR="${1:-.}"
ERRORS=0

echo "=== Self-test CA: $CA_DIR ==="

# 1. Корневой CA проходит самоподпись
echo -n "[1] Самоподпись корневого CA: "
if openssl verify -CAfile "$CA_DIR/ca.crt" "$CA_DIR/ca.crt" | grep -q "OK"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 2. CA:TRUE в корневом сертификате
echo -n "[2] CA:TRUE в корневом: "
if openssl x509 -in "$CA_DIR/ca.crt" -noout -text | grep -q "CA:TRUE"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 3. keyCertSign в Key Usage
echo -n "[3] keyCertSign в Key Usage: "
if openssl x509 -in "$CA_DIR/ca.crt" -noout -text | grep -A1 "Key Usage" | grep -q "Certificate Sign"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 4. Ключ соответствует сертификату (RSA)
echo -n "[4] Ключ соответствует сертификату: "
HASH1=$(openssl x509 -noout -modulus -in "$CA_DIR/ca.crt" 2>/dev/null | openssl sha256)
HASH2=$(openssl rsa -noout -modulus -in "$CA_DIR/ca.key" 2>/dev/null | openssl sha256)
if [ "$HASH1" = "$HASH2" ] && [ -n "$HASH1" ]; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 5. Файлы базы данных
echo -n "[5] index.txt: "
[ -f "$CA_DIR/db/index.txt" ] && echo "OK" || { echo "FAIL"; ERRORS=$((ERRORS+1)); }

echo -n "[6] serial: "
[ -s "$CA_DIR/db/serial" ] && echo "OK ($(cat "$CA_DIR/db/serial"))" || { echo "FAIL"; ERRORS=$((ERRORS+1)); }

# 7. Права на ca.key
echo -n "[7] Права на ca.key: "
PERMS=$(stat -c %a "$CA_DIR/ca.key" 2>/dev/null || stat -f %Lp "$CA_DIR/ca.key" 2>/dev/null)
if [ "$PERMS" = "600" ]; then
    echo "OK"
else
    echo "WARN: $PERMS (ожидается 600)"
fi

# 8. Тестовый выпуск и верификация
echo -n "[8] Тестовый выпуск сертификата: "
TEMP_DIR=$(mktemp -d)
openssl genrsa -out "$TEMP_DIR/test.key" 2048 2>/dev/null
openssl req -new -key "$TEMP_DIR/test.key" -out "$TEMP_DIR/test.csr" \
    -subj "/CN=self-test.local" 2>/dev/null

cd "$CA_DIR"
if openssl ca -config openssl.cnf -in "$TEMP_DIR/test.csr" -out "$TEMP_DIR/test.crt" \
    -extensions v3_req -notext -batch 2>/dev/null; then
    echo "OK"
    echo -n "[9] Верификация тестового: "
    if openssl verify -CAfile "$CA_DIR/ca.crt" "$TEMP_DIR/test.crt" | grep -q "OK"; then
        echo "OK"
    else
        echo "FAIL"; ERRORS=$((ERRORS+1))
    fi
else
    echo "FAIL (подпись)"; ERRORS=$((ERRORS+1))
fi

rm -rf "$TEMP_DIR"
echo "=== Результат: $ERRORS ошибок ==="
exit $ERRORS
```

Запуск:

```bash
chmod +x ca-selftest.sh
./ca-selftest.sh /path/to/ca
# → === Self-test CA: /path/to/ca ===
# → [1] Самоподпись корневого CA: OK
# → ...
# → === Результат: 0 ошибок ===
```

### Расширения сертификатов

Файл конфигурации содержит две ключевые секции расширений:

- `[v3_ca]` — для корневого сертификата CA. Содержит `CA:true`, `keyCertSign`, `cRLSign`.
- `[v3_req]` — для сертификатов конечных сущностей. Содержит `CA:FALSE`, `serverAuth`, `clientAuth`.

Теория расширений X.509 и механизмы отзыва — в [обзоре PKI (Public Key Infrastructure, Инфраструктура открытых ключей)](../../../Concepts/pki_overview.md).

### Следующие шаги

После создания CA:

1. [Выпуск сертификатов сервисов](./service_certificate_management.md) — подпись CSR, SAN, отзыв, CRL
2. [Управление сертификатами](./common_utilities.md) — проверка, диагностика, mTLS
3. [Быстрый метод выпуска](./quick_method.md) — упрощенная подпись без базы данных

### Связанные темы

- [Обзор одноуровневого CA](./overview.md) — структура директорий, подготовка
- [Двухуровневая архитектура CA](../two_tier/overview.md) — рекомендуемый подход для production
- [Конвертация форматов](./formats_and_advanced_config.md) — PEM/DER/PKCS#12, продвинутый openssl.cnf
- [Обзор PKI](../../../Concepts/pki_overview.md) — теория иерархии доверия, жизненный цикл сертификатов
