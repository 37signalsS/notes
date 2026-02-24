# Настройка CA (одноуровневый)

#### Конфигурационный файл openssl.cnf

Создадим файл `ca/openssl.cnf`, который будет содержать все настройки нашего CA. Это упростит все последующие команды.

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

#### Создание корневого ключа и сертификата CA

Корневой сертификат — это основа доверия всей системы. Мы создаем его и подписываем собственным ключом (самоподписанный).

> **О безопасности ключа CA**
> Флаг `-nodes` (no DES) отключает шифрование приватного ключа паролем. Это удобно для тестов, но **абсолютно недопустимо в производственной среде**. Компрометация приватного ключа корневого CA означает компрометацию всей инфраструктуры доверия. В реальности ключ корневого CA должен:
>
> 1. Быть защищен сложным паролем.
> 2. Храниться на физически изолированном носителе (Air-gapped-система, аппаратный модуль безопасности HSM), который никогда не подключается к сети.

```bash
cd ca

# Создаем приватный ключ (ca.key) и самоподписанный сертификат (ca.crt)
openssl req -new -x509 
    -config openssl.cnf 
    -newkey rsa:4096 -sha512 -nodes 
    -keyout ca.key 
    -out ca.crt 
    -days 3650 # Срок действия 10 лет

# Вернемся в родительскую директорию
cd ..
```

- `-x509`: Создать самоподписанный сертификат вместо запроса (CSR).
- `-newkey rsa:4096`: Сгенерировать новый 4096-битный RSA-ключ.
- `-nodes`: (No DES) Не шифровать приватный ключ паролем.
- `-config`: Использовать наш конфигурационный файл. Поля из секции `[req_distinguished_name]` будут подставлены автоматически.
