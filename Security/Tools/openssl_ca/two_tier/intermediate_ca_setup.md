# Настройка промежуточного центра сертификации

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты.

**Intermediate CA (Промежуточный центр сертификации)** — подчиненный удостоверяющий центр, подписанный корневым CA. Используется для повседневного выпуска конечных сертификатов (серверов, пользователей), что позволяет держать корневой ключ в безопасности.

**ca-chain.crt (Цепочка сертификатов)** — комбинированный файл, содержащий сертификат промежуточного CA и корневой сертификат. Необходим для корректной проверки цепочки доверия клиентами.

**pathlen (Path Length Constraint, Ограничение длины пути)** — параметр расширения Basic Constraints стандарта X.509, определяющий количество уровней подчиненных CA.

> Базовые понятия PKI (Public Key Infrastructure, Инфраструктура открытых ключей), такие как **CSR (Certificate Signing Request, Запрос на подпись сертификата)**, **CRL (Certificate Revocation List, Список отзыва сертификатов)** и **OCSP (Online Certificate Status Protocol, Протокол онлайн-проверки статуса сертификата)**, подробно описаны в **[обзоре PKI](../../../../Concepts/pki_overview.md)**.

## Базовые концепции

### Роль в двухуровневой архитектуре

Промежуточный CA является основным операционным узлом инфраструктуры. В то время как Root CA (Корневой CA) хранится в изолированной среде (air-gapped), промежуточный узел доступен для автоматизированных процессов выпуска сертификатов.

Подробное сравнение уровней и архитектурные схемы приведены в **[обзоре двухуровневого CA](./overview.md)**.

### Файл цепочки доверия

Современные TLS-клиенты (браузеры, API-клиенты) требуют предоставления полной цепочки сертификатов от сервера. Файл `ca-chain.crt` объединяет промежуточный и корневой сертификаты в одном PEM-контейнере. Это критично для:

- Настройки веб-серверов (например, Nginx).
- Реализации **mTLS (Mutual TLS, Взаимный TLS)** для аутентификации клиентов.
- Проведения диагностики утилитами OpenSSL.

## Практические сценарии

### 1. Подготовка структуры директорий

```bash
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber
```

Назначение ключевых файлов базы данных (`index.txt`, `serial`) описано в **[обзоре одноуровневого CA](../single_tier/overview.md#формальный-метод-создание-структуры-ca)**.

### 2. Создание конфигурационного файла openssl.cnf

Файл `intermediate-ca/openssl.cnf` определяет политики и расширения для работы промежуточного CA.

```ini
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt
new_certs_dir   = $dir/certs
crl_dir         = $dir/crl

certificate     = $dir/intermediate.crt
serial          = $dir/db/serial
crlnumber       = $dir/db/crlnumber
crl             = $dir/crl/crl.pem
private_key     = $dir/intermediate.key

default_md      = sha512
default_days    = 365
policy          = policy_loose

# Мягкая политика: требует только наличия Common Name (CN)
[ policy_loose ]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[ req ]
default_bits        = 4096
distinguished_name  = req_distinguished_name
x509_extensions     = v3_intermediate_ca
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
O  = My Private Corp
CN = My Private Corp Intermediate CA

# Расширения для самого Intermediate CA
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign

# Расширения для сертификатов сервисов
[ v3_server_cert ]
basicConstraints       = CA:FALSE
keyUsage               = digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName         = @alt_names
```

**Особенности конфигурации:**

- `pathlen:0`: запрещает промежуточному CA подписывать другие CA (только leaf-сертификаты).
- `policy_loose`: позволяет выпускать сертификаты с произвольными данными в полях организации.

### 3. Генерация ключа и запроса CSR

```bash
cd intermediate-ca

# Создание ключа и запроса
openssl req -new \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout intermediate.key \
    -out csr/intermediate.csr

cd ..
```

### 4. Подпись промежуточного CA корневым ключом

Операция выполняется на стороне **[Root CA](./root_ca_setup.md)**, обычно в изолированной среде.

```bash
cd root-ca

# Подпись с использованием расширения v3_intermediate_ca из конфига Root CA
openssl ca -config openssl.cnf \
    -in ../intermediate-ca/csr/intermediate.csr \
    -out ../intermediate-ca/intermediate.crt \
    -extensions v3_intermediate_ca

cd ..
```

### 5. Формирование ca-chain.crt

```bash
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt
```

## Дополнительная информация

### Безопасность

Несмотря на то что ключ Intermediate CA хранится онлайн, он должен быть защищен:

- Использованием **HSM (Hardware Security Module, Аппаратный модуль безопасности)** или HashiCorp Vault.
- Ограничением доступа на уровне ОС и сетевых политик.
- Применением **MFA (Multi-Factor Authentication, Многофакторная аутентификация)** для административного доступа.

### Связанные темы

- **[Настройка Root CA](./root_ca_setup.md)** — подготовка корневого узла доверия.
- **[Управление сертификатами сервисов](./service_certificate_management.md)** — выпуск и отзыв сертификатов через Intermediate CA.
- **[Утилиты и диагностика](./common_utilities.md)** — проверка цепочек доверия и верификация.
