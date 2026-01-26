# Управление центром сертификации (CA) на OpenSSL: подробное руководство

Это руководство поможет вам создать и управлять собственным центром сертификации (CA) с помощью OpenSSL. Такой CA необходим для выпуска доверенных SSL/TLS-сертификатов для внутренних сервисов, разработки, тестирования и реализации взаимной аутентификации (mTLS).

Мы рассмотрим два подхода:
1.  **Формальный метод**: создание полноценной структуры CA с базой данных сертификатов. Рекомендуется для управления множеством сертификатов в организации.
2.  **Быстрый метод**: упрощенный выпуск сертификата для быстрых тестов и разовых задач.

## Основные понятия и форматы файлов

*   `.key`: Приватный (закрытый) ключ. **Храните его в строжайшем секрете.** Используется для подписи данных и расшифровки.
*   `.csr` (Certificate Signing Request): Запрос на подпись сертификата. Содержит открытый ключ и информацию о владельце (домен, организация). Отправляется в CA для получения сертификата.
*   `.crt` или `.cer`: Подписанный сертификат (X.509). Содержит открытый ключ, информацию о владельце и цифровую подпись CA, которая подтверждает его подлинность.
*   `.pem` (Privacy-Enhanced Mail): Текстовый формат-контейнер, кодированный в Base64. Может содержать ключ, сертификат, цепочку сертификатов или всё сразу. Легко определить по заголовкам `-----BEGIN...-----` и `-----END...-----`.

## Формальный метод: Создание полноценного CA

Этот метод включает создание иерархической структуры и базы данных для отслеживания выпущенных сертификатов.

### 1.1. Структура директорий CA

Создадим изолированное окружение для нашего CA.

```bash
# Основная директория
mkdir ca

# Вложенная структура для базы данных и сертификатов
mkdir -p ca/db/{newcerts,crl}
touch ca/db/index.txt   # База данных выданных сертификатов
echo "1000" > ca/db/serial # Начальный серийный номер в hex
echo "1000" > ca/db/crlnumber # Начальный номер для CRL
```
- `db/index.txt`: Текстовая база данных, где хранится информация о каждом подписанном сертификате.
- `db/serial`: Файл с серийным номером для следующего сертификата.
- `db/newcerts/`: Директория, куда будут складываться копии всех выданных сертификатов.
- `crl/`: Директория для хранения списков отзыва сертификатов (CRL).

### 1.2. Конфигурационный файл openssl.cnf

Создадим файл `ca/openssl.cnf`, который будет содержать все настройки нашего CA. Это упростит все последующие команды.

```ini
# ca/openssl.cnf

[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .                         # Корневая директория CA
certs           = $dir/certs                # Не используется, но должно быть
crl_dir         = $dir/crl                  # Директория для CRL
database        = $dir/db/index.txt         # Путь к базе данных сертификатов
new_certs_dir   = $dir/db/newcerts          # Куда сохранять новые сертификаты

certificate     = $dir/ca.crt               # Корневой сертификат CA
serial          = $dir/db/serial            # Файл с серийным номером
crlnumber       = $dir/db/crlnumber         # Файл с номером CRL
crl             = $dir/crl.pem              # Текущий CRL (создается позже)
private_key     = $dir/ca.key               # Приватный ключ CA
RANDFILE        = $dir/db/.rand             # Файл со случайными данными

default_md      = sha512                    # Алгоритм хеширования по умолчанию
default_days    = 365                       # Срок действия сертификата по умолчанию (1 год)
preserve        = no                        # Поля в CSR должны совпадать с полями CA
policy          = policy_match              # Политика проверки полей

# Политика, требующая совпадения страны, региона и организации
# с данными корневого CA.
[ policy_match ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

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
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign

# Расширения для сертификатов клиентов/серверов (конечных сущностей)
[ v3_req ]
basicConstraints       = CA:FALSE
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
# Назначение: аутентификация сервера и/или клиента
extendedKeyUsage       = serverAuth, clientAuth
```

### 1.3. Создание корневого ключа и сертификата CA

Корневой сертификат — это основа доверия всей системы. Мы создаем его и подписываем собственным ключом (самоподписанный).

```bash
cd ca

# Создаем приватный ключ (ca.key) и самоподписанный сертификат (ca.crt)
openssl req -new -x509 \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650 # Срок действия 10 лет

# Вернемся в родительскую директорию
cd ..
```
- `-x509`: Создать самоподписанный сертификат вместо запроса (CSR).
- `-newkey rsa:4096`: Сгенерировать новый 4096-битный RSA-ключ.
- `-nodes`: (No DES) Не шифровать приватный ключ паролем. **В production ключ обязательно нужно защитить паролем!**
- `-config`: Использовать наш конфигурационный файл. Поля из секции `[req_distinguished_name]` будут подставлены автоматически.

### 1.4. Выпуск сертификата для клиента или сервера

Процесс состоит из двух этапов:
1.  Клиент создает приватный ключ и запрос на подпись (CSR).
2.  CA проверяет и подписывает CSR, выпуская сертификат.

**Шаг 1: Создание ключа и CSR на стороне клиента**

```bash
# Создаем приватный ключ для нашего сервиса
openssl genrsa -out my-service.key 4096

# Создаем CSR, используя ключ
# Важно: CN (Common Name) должно быть уникальным, например, доменное имя FQDN
openssl req -new -key my-service.key -out my-service.csr \
  -subj "/C=RU/ST=Moscow/O=My Private Org/OU=Service/CN=my-service.local"
```

**Шаг 2: Подпись CSR с помощью CA**

```bash
cd ca

# Команда для подписи запроса
openssl ca -config openssl.cnf -in ../my-service.csr -out ../my-service.crt \
  -extensions v3_req -notext

cd ..
```
- `openssl ca`: Команда для управления CA.
- `-in ../my-service.csr`: Входящий запрос на подпись.
- `-out ../my-service.crt`: Имя файла для подписанного сертификата.
- `-extensions v3_req`: Применить расширения из секции `[v3_req]`, указывая, что это сертификат для конечного пользователя/сервиса, а не для другого CA.

После выполнения этой команды в файле `ca/db/index.txt` появится новая строка, а `ca/db/serial` обновится.

---

## Глава 2. Жизненный цикл сертификата

### 2.1. Проверка цепочки доверия

Убедимся, что выданный сертификат действителен и подписан нашим CA.

```bash
openssl verify -CAfile ca/ca.crt my-service.crt
```
Ожидаемый вывод: `my-service.crt: OK`. Это означает, что подпись сертификата `my-service.crt` соответствует открытому ключу из `ca.crt`.

### 2.2. Добавление корневого сертификата в системное хранилище

Чтобы браузеры и утилиты (curl, wget) доверяли нашим сертификатам, корневой сертификат `ca.crt` нужно добавить в системное хранилище.

**Для Debian/Ubuntu:**
```bash
sudo cp ca/ca.crt /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates
```

**Для RHEL/CentOS/Fedora:**
```bash
sudo cp ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### 2.3. Отзыв скомпрометированного сертификата

Если приватный ключ сертификата был украден или сертификат больше не нужен, его необходимо отозвать. Эта функция доступна только при использовании **формального метода**.

**Шаг 1: Отзыв сертификата**

```bash
cd ca

# Указываем путь к сертификату, который нужно отозвать
openssl ca -config openssl.cnf -revoke ../my-service.crt
```
В базе `db/index.txt` статус сертификата изменится с `V` (valid) на `R` (revoked).

**Шаг 2: Генерация списка отозванных сертификатов (CRL)**

```bash
# Создаем/обновляем файл crl.pem
openssl ca -config openssl.cnf -gencrl -out crl.pem

cd ..
```
Файл `ca/crl.pem` теперь содержит серийный номер отозванного сертификата. Веб-серверы и другие службы можно настроить на проверку этого списка.

---

## Глава 3. Быстрый метод: выпуск сертификата для тестов

Этот метод не требует ведения базы данных и подходит для быстрых задач. Подпись выполняется напрямую с помощью корневого сертификата и ключа.

```bash
# 1. Создаем ключ и CSR для тестового сайта
openssl req -new -newkey rsa:2048 -nodes \
            -keyout test.key -out test.csr \
            -subj "/C=RU/ST=Test/L=Test/O=Test/CN=test.local"

# 2. Подписываем CSR, используя корневой CA
openssl x509 -req -in test.csr \
    -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial \
    -out test.crt -days 90 -sha256
```
- `-CAcreateserial`: Создает файл `ca.srl` (если его нет), который хранит последний использованный серийный номер. Это упрощенная замена `db/serial`.
- **Недостаток**: этот метод не позволяет вести полноценный учёт и отзывать сертификаты.

---

## Приложение A: Практический пример — mTLS в Nginx

Настроим Nginx так, чтобы он требовал от клиентов валидный сертификат, подписанный нашим CA.

```nginx
server {
    listen 443 ssl;
    server_name my-service.local;

    ssl_certificate         /path/to/my-service.crt;
    ssl_certificate_key     /path/to/my-service.key;

    # --- Клиентская аутентификация ---

    # 1. Корневой сертификат для проверки клиентов
    ssl_client_certificate  /path/to/ca/ca.crt;

    # 2. Файл со списком отозванных сертификатов
    ssl_crl                 /path/to/ca/crl.pem;

    # 3. Включить проверку клиента (on) или запрашивать, но не требовать (optional)
    ssl_verify_client       on;

    location / {
        # Переменная $ssl_client_s_dn содержит DN (Distinguished Name) клиента
        # Например: /C=RU/ST=Moscow/O=My Private Org/OU=IT Department/CN=user1
        # Можно использовать для авторизации
        if ($ssl_verify_result != "SUCCESS") {
            return 403;
        }
        proxy_pass http://backend;
    }
}
```

---

## Приложение B: Полезные команды для проверки

**Просмотреть содержимое сертификата:**
```bash
openssl x509 -in my-service.crt -noout -text
```

**Просмотреть содержимое CSR:**
```bash
openssl req -in my-service.csr -noout -text
```

**Проверить соответствие ключа и сертификата:**
(Хеши модулей должны совпадать)
```bash
openssl rsa -noout -modulus -in my-service.key | openssl md5
openssl x509 -noout -modulus -in my-service.crt | openssl md5
```

**Просмотреть содержимое CRL:**
```bash
openssl crl -in ca/crl.pem -noout -text
```
