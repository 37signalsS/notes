# Управление собственным центром сертификации (CA) с помощью OpenSSL

Это руководство описывает, как создать и управлять простым центром сертификации для внутреннего использования, например, для аутентификации клиентов или сервисов.

## Основные понятия и форматы файлов

Прежде чем начать, разберемся с основными типами файлов, используемых в инфраструктуре открытых ключей (PKI).

*   `.key`: Файл, содержащий **приватный (закрытый) ключ**. Его необходимо хранить в секрете. OpenSSL работает с ключами для различных алгоритмов, например, RSA, DSA, EC.
*   `.csr` (Certificate Signing Request): Файл **запроса на подпись сертификата**. Он содержит информацию о том, для кого выпускается сертификат (например, доменное имя), а также **открытый ключ**. Этот файл отправляется в центр сертификации (CA) для подписи.
*   `.crt` или `.cer`: Файл, содержащий **подписанный сертификат** стандарта X.509. Он включает в себя открытый ключ, информацию о владельце, а также цифровую подпись центра сертификации.
*   `.pem` (Privacy-Enhanced Mail): Это не формат, а скорее контейнер, использующий кодировку Base64. Файлы `.pem` могут содержать практически всё: от приватных ключей и сертификатов до запросов на подпись. Их легко идентифицировать по заголовкам `-----BEGIN ...-----` и `-----END ...-----`.

## 1. Структура директорий и создание CA

Сначала создадим директорию для хранения всех файлов нашего CA. Этот метод рекомендуется для формализованного управления множеством сертификатов.

```bash
mkdir -p ca/db/newcerts
touch ca/db/index.txt
echo "01" > ca/db/serial
```

*   `ca/`: Корневая директория.
*   `ca/db/`: "База данных" CA.
*   `ca/db/index.txt`: Список всех подписанных сертификатов.
*   `ca/db/serial`: Следующий серийный номер для сертификата.
*   `ca/db/newcerts/`: Директория для хранения копий подписанных сертификатов.

## 2. Создание корневого ключа и сертификата CA

Теперь сгенерируем корневой приватный ключ и самоподписанный сертификат. Этот сертификат является "корнем доверия" для всех сертификатов, которые мы будем выпускать.

```bash
openssl req -x509 -newkey rsa:4096 -sha512 -nodes \
  -keyout ca/ca.key \
  -out ca/ca.crt \
  -days 3650 \
  -subj "/C=EE/ST=Tallinn/O=Rebrain/OU=IT/CN=root/emailAddress=campaign@rebrain.com"
```

*   `-x509`: Создать самоподписанный сертификат.
*   `-newkey rsa:4096`: Создать новый 4096-битный RSA ключ.
*   `-sha512`: Использовать SHA-512 для подписи.
*   `-nodes`: Не шифровать приватный ключ (для простоты; в production рекомендуется использовать пароль).
*   `-days 3650`: Срок действия сертификата (10 лет).
*   `-subj`: Информация о владельце сертификата.

## 3. Конфигурационный файл OpenSSL

Для удобства дальнейшей работы создадим конфигурационный файл `ca/openssl.cnf`. Он упростит команды для подписи и отзыва сертификатов.

```ini
#
# Конфигурационный файл OpenSSL для управления CA
#

[ ca ]
default_ca = CA_default

[ CA_default ]
    dir               = .          # Путь к директории CA
    certs             = $dir/certs
    crl_dir           = $dir/crl
    database          = $dir/db/index.txt
    new_certs_dir     = $dir/db/newcerts

    certificate       = $dir/ca.crt
    serial            = $dir/db/serial
    crlnumber         = $dir/db/crlnumber
    crl               = $dir/crl.pem
    private_key       = $dir/ca.key
    RANDFILE          = $dir/db/.rand

default_md        = sha512
default_days      = 365
preserve          = no
policy            = policy_strict # Используем policy_strict для более строгой проверки

[ policy_strict ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[ req ]
default_bits        = 4096
default_md          = sha512
distinguished_name  = req_distinguished_name
x509_extensions     = v3_ca

[ req_distinguished_name ]
countryName                     = Country Name (2 letter code)
stateOrProvinceName             = State or Province Name
localityName                    = Locality Name
0.organizationName              = Organization Name
organizationalUnitName          = Organizational Unit Name
commonName                      = Common Name
emailAddress                    = Email Address

[ v3_ca ]
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always,issuer
basicConstraints = critical,CA:true

[ v3_req ]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
extendedKeyUsage = clientAuth, serverAuth # Добавлено для явного указания назначения сертификата
```
*Обратите внимание, что пути в конфиге относительные (`.`). Команды `openssl ca` нужно будет выполнять из директории `ca/`.*

## 4. Выпуск сертификата (формальный метод)

Процесс состоит из двух шагов: создание запроса на подпись сертификата (CSR) и подпись этого запроса нашим CA с использованием его базы данных.

### 4.1. Создание приватного ключа и CSR

```bash
# Создание ключа
openssl genrsa -out client.key 4096

# Создание CSR
openssl req -new -key client.key -out client.csr \
  -subj "/C=EE/ST=Tallinn/O=Rebrain/OU=User/CN=client01"
```
*   `CN` (Common Name) — это ключевое поле, часто используемое для идентификации (например, доменное имя для сервера или логин пользователя для клиента).

### 4.2. Подпись CSR с помощью CA

Перейдем в директорию CA и подпишем запрос.

```bash
cd ca

openssl ca -config openssl.cnf -in ../client.csr -out ../client.crt \
  -extensions v3_req -notext
```
*   `-extensions v3_req`: Применяет секцию `v3_req` из конфига, указывая, что это не сертификат CA.
*   `-notext`: Не включать текстовое представление сертификата в итоговый файл.

После выполнения в `db/index.txt` появится запись о новом сертификате, а серийный номер в `db/serial` увеличится.

## 5. Выпуск сертификата (упрощенный метод)

Этот метод не требует ведения базы данных CA и подходит для быстрых тестов или разовых задач. Подпись выполняется напрямую с помощью корневого сертификата и ключа.

```bash
# 1. Создаем ключ и CSR для нашего сайта/сервиса
openssl req -new -newkey rsa:2048 -nodes \
            -keyout my-service.key -out my-service.csr \
            -subj "/C=RU/ST=Moscow/L=Moscow/O=MyOrg/CN=my-service.local"

# 2. Подписываем CSR с помощью корневого ключа (ca.key) и корневого сертификата (ca.crt)
openssl x509 -req -in my-service.csr \
    -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial \
    -out my-service.crt -days 365 -sha256
```
*   `openssl x509 -req`: Указывает, что мы работаем с CSR.
*   `-CAcreateserial`: Создает файл `.srl` рядом с CA-сертификатом для отслеживания серийных номеров (требуется при первом запуске).

## 6. Проверка цепочки сертификатов

Убедимся, что сертификат клиента действительно подписан нашим CA. Для этого используется команда `verify`.

```bash
# Для сертификата, выпущенного формальным методом
openssl verify -CAfile ca/ca.crt client.crt

# Для сертификата, выпущенного упрощенным методом
openssl verify -CAfile ca/ca.crt my-service.crt
```
Ожидаемый результат в обоих случаях: `client.crt: OK` или `my-service.crt: OK`.

## 7. Добавление корневого сертификата в доверенные системные

Чтобы браузеры и утилиты командной строки (curl, wget) доверяли нашим самоподписанным сертификатам, корневой сертификат CA (`ca.crt`) нужно добавить в системное хранилище доверенных сертификатов.

Для Debian/Ubuntu и производных:
```bash
# 1. Копируем сертификат в специальную директорию
sudo cp ca/ca.crt /usr/local/share/ca-certificates/my-ca.crt

# 2. Обновляем хранилище сертификатов
sudo update-ca-certificates
```
Система сообщит о добавлении 1 нового сертификата.

## 8. Отзыв сертификата

Если ключ сертификата был скомпрометирован или больше не должен быть действителен, его необходимо отозвать. **Эта операция возможна только при использовании формального метода с базой данных CA.**

```bash
cd ca

# Отзыв сертификата
# Можно указать причину отзыва (например, keyCompromise, cessationOfOperation)
# openssl ca -config openssl.cnf -revoke -crl_reason keyCompromise ../client.crt
openssl ca -config openssl.cnf -revoke ../client.crt

# Генерация списка отозванных сертификатов (CRL)
openssl ca -config openssl.cnf -gencrl -out crl.pem
```

Файл `crl.pem` (Certificate Revocation List) содержит серийные номера всех отозванных сертификатов. Сервисы (например, Nginx) могут использовать этот файл, чтобы отказывать в доступе клиентам с отозванными сертификатами.

Чтобы посмотреть содержимое CRL:
```bash
openssl crl -in ca/crl.pem -noout -text
```