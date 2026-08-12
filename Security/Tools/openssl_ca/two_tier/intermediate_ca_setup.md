# Настройка промежуточного центра сертификации

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты для подтверждения подлинности открытых ключей.

**Intermediate CA (Промежуточный центр сертификации)** — подчиненный удостоверяющий центр, сертификат которого подписан корневым CA. В двухуровневой архитектуре он является единственным узлом, выпускающим конечные сертификаты.

**ca-chain.crt (Цепочка сертификатов, Bundle)** — PEM-файл, содержащий сертификаты всех уровней от Intermediate до Root (в порядке убывания иерархии). Необходим для того, чтобы клиенты могли построить путь доверия до корневого якоря.

**pathlen (Path Length Constraint)** — параметр расширения Basic Constraints стандарта X.509. Значение `0` в сертификате Intermediate CA означает, что он может выпускать только конечные сертификаты (leaf), но не может подписывать другие CA.

**OpenSSL 3.0+** — версия тулсета, в которой депрецирован параметр `RANDFILE` и введена система провайдеров.

> Базовые понятия PKI (CSR, CRL, OCSP) подробно описаны в **[обзоре PKI](../../../../Concepts/pki_overview.md)**.

## Базовые концепции

### Роль в двухуровневой архитектуре

Промежуточный CA выполняет роль «операционного офиса» PKI. В то время как Root CA (Корневой CA) хранится в изолированной среде (air-gapped), промежуточный узел доступен для автоматизированных процессов.

**Преимущества использования Intermediate CA:**
- **Безопасность корня:** Корневой ключ остается офлайн. В случае компрометации промежуточного ключа, отзывается только он, а корневое доверие сохраняется.
- **Масштабируемость:** Можно создать несколько Intermediate CA для разных департаментов или регионов с разными политиками.
- **Автоматизация:** Промежуточный CA можно интегрировать с HashiCorp Vault или Kubernetes (cert-manager).

### Файл цепочки доверия

Современные браузеры и TLS-клиенты требуют предоставления полной цепочки. Без файла `ca-chain.crt` сервер отправит только свой сертификат, и клиент выдаст ошибку `Incomplete Chain` или `Unknown CA`, так как он не знает о промежуточном звене.

## Практические сценарии

### 1. Подготовка структуры директорий

```bash
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber
```

### 2. Создание конфигурационного файла openssl.cnf

Файл `intermediate-ca/openssl.cnf` определяет правила работы операционного узла.

```ini
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt
new_certs_dir   = $dir/certs
serial          = $dir/db/serial
crlnumber       = $dir/db/crlnumber
certificate     = $dir/intermediate.crt
private_key     = $dir/intermediate.key
RANDFILE        = $dir/db/.rand             # Игнорируется в OpenSSL 3.0+

default_md      = sha512
default_days    = 365
policy          = policy_loose

# Мягкая политика для конечных сервисов
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
CN = My Private Intermediate CA

# Расширения для самого Intermediate CA (при подписи корнем)
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, digitalSignature, keyCertSign, cRLSign

# Расширения для сертификатов сервисов (serverAuth)
[ v3_server_cert ]
basicConstraints       = CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName         = @alt_names
```

### 3. Генерация ключа и запроса (CSR)

#### Вариант А: RSA-4096
```bash
openssl req -new -config intermediate-ca/openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout intermediate-ca/intermediate.key \
    -out intermediate-ca/csr/intermediate.csr
```

#### Вариант Б: ECDSA P-384 (Рекомендуется в 2026)
```bash
openssl req -new -config intermediate-ca/openssl.cnf \
    -newkey ec:<(openssl ecparam -name secp384r1) -sha512 -nodes \
    -keyout intermediate-ca/intermediate.key \
    -out intermediate-ca/csr/intermediate.csr
```

### 4. Подпись промежуточного CA в Root-узле

Операция выполняется на стороне **[Root CA](./root_ca_setup.md)** (офлайн-система):

```bash
cd root-ca

openssl ca -config openssl.cnf \
    -extensions v3_intermediate_ca \
    -days 3650 -notext -md sha512 \
    -in ../intermediate-ca/csr/intermediate.csr \
    -out ../intermediate-ca/intermediate.crt

cd ..
```

### 5. Формирование цепочки и верификация

После получения подписанного сертификата необходимо создать Bundle и проверить его.

```bash
# Создание цепочки (Intermediate + Root)
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt

# Верификация промежуточного сертификата относительно корня
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
# → intermediate.crt: OK
```

## Дополнительная информация

### Безопасность операционного узла

Так как ключ Intermediate CA доступен онлайн, он требует повышенных мер защиты:
- **HashiCorp Vault:** использование движка PKI для хранения ключа и динамического выпуска.
- **Сетевая изоляция:** доступ к порту управления CA только через VPN или внутренние Jump-хосты.
- **Мониторинг `index.txt`:** аудит всех выпущенных сертификатов через системы логирования.

### Связанные темы

- **[Настройка Root CA](./root_ca_setup.md)** — подготовка фундамента доверия.
- **[Управление сертификатами сервисов](./service_certificate_management.md)** — выпуск конечных сертификатов через Intermediate CA.
- **[Утилиты и диагностика](./common_utilities.md)** — проверка цепочек `ca-chain.crt`.
