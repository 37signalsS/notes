# Настройка промежуточного CA (Intermediate CA)

> Общие определения PKI (ключ, CSR, X.509, CRL, OCSP) — в [обзоре PKI](../../../../Concepts/pki_overview.md). Архитектура двухуровневого CA — в [обзоре](./overview.md).

## Definitions

**Intermediate CA (промежуточный CA)** — рабочий CA, подписанный Root CA. Выполняет повседневные операции: выпуск, отзыв, перевыпуск сертификатов конечных сущностей (серверов, клиентов). Его ключ хранится онлайн, но в защищённом месте (Vault, CI/CD-система с MFA). Подробнее — в [обзоре двухуровневого CA](./overview.md#definitions).

**pathlen:0** — ограничение `basicConstraints`, запрещающее Intermediate CA подписывать другие CA. Промежуточный CA может выпускать только конечные (leaf) сертификаты, что предотвращает несанкционированное расширение цепочки доверия.

**ca-chain.crt** — файл цепочки сертификатов, объединяющий `intermediate.crt + root-ca/ca.crt`. Используется TLS-серверами для отправки полной цепочки клиентам и для верификации. Подробности формата — в [обзоре PKI](../../../../Concepts/pki_overview.md#цепочка-доверия-chain-of-trust).

## Basic Concepts

### Роль Intermediate CA в двухуровневой архитектуре

Intermediate CA — рабочее звено PKI. В отличие от Root CA, который хранится офлайн (air-gapped), промежуточный CA доступен для автоматизированных процессов:

| Характеристика | Root CA | Intermediate CA |
|---|---|---|
| Частота использования | Один раз (подпись Intermediate CA) | Ежедневно (выпуск, отзыв сертификатов) |
| Хранение ключа | Офлайн (air-gapped, HSM) | Онлайн (Vault, CI/CD, защищённый хост) |
| Подписывает | Только Intermediate CA | Конечные сертификаты (серверы, клиенты) |
| pathlen | `pathlen:1` (допускает 1 уровень промежуточных) | `pathlen:0` (только leaf-сертификаты) |
| Компрометация | Катастрофическая — вся PKI под угрозой | Локальная — отзывается intermediate.crt, Root CA остаётся доверенным |

### Конфигурационный файл (openssl.cnf)

Файл `intermediate-ca/openssl.cnf` определяет политики, расширения и пути для всех операций Intermediate CA. В отличие от [Root CA](./root_ca_setup.md), политика более мягкая (`policy_loose`): не требует совпадения полей с Root CA, только наличия Common Name. Это позволяет выпускать сертификаты для разных команд и проектов.

### Цепочка доверия и ca-chain.crt

TLS-клиенты проверяют цепочку от серверного сертификата до корневого CA. Сервер должен отправлять **полную цепочку**: `сертификат сервиса → intermediate.crt → root-ca.crt`. Файл `ca-chain.crt` объединяет промежуточный и корневой сертификаты и используется:

- В директиве `ssl_client_certificate` Nginx для проверки клиентских сертификатов ([mTLS](../../../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md))
- Для верификации: `openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt`

## Practical Scenarios

### 1. Подготовка структуры директорий

```bash
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber
```

| Директория/файл | Назначение |
|---|---|
| `db/index.txt` | База данных выпущенных сертификатов (обновляется при каждом `openssl ca`) |
| `db/serial` | Счётчик серийных номеров (hex, инкрементируется автоматически) |
| `db/crlnumber` | Счётчик номеров CRL |
| `certs/` | Архив выпущенных сертификатов (копии) |
| `crl/` | Списки отзыва (crl.pem) |
| `csr/` | Входящие запросы на подпись (CSR) |

### 2. Создание конфигурационного файла

```ini
# intermediate-ca/openssl.cnf

[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt         # База данных выпущенных сертификатов
new_certs_dir   = $dir/certs                # Архив выпущенных сертификатов
crl_dir         = $dir/crl                  # Директория для CRL

certificate     = $dir/intermediate.crt     # Сертификат Intermediate CA
serial          = $dir/db/serial            # Счётчик серийных номеров
crlnumber       = $dir/db/crlnumber         # Счётчик номеров CRL
crl             = $dir/crl/crl.pem          # Файл CRL
private_key     = $dir/intermediate.key     # Приватный ключ Intermediate CA

default_md      = sha512
default_days    = 365                       # Срок действия сертификата сервиса (1 год)
policy          = policy_loose              # Политика для конечных сертификатов

# Политика Intermediate CA — мягкая, не требует совпадения с Root CA.
# Только Common Name обязателен.
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

# Расширения X.509 v3 для сертификата Intermediate CA
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
# CA:true — это всё ещё CA, но pathlen:0 запрещает подписывать другие CA.
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign

# Расширения для конечных сертификатов (сервисы, пользователи)
[ v3_server_cert ]
basicConstraints       = CA:FALSE
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
extendedKeyUsage       = serverAuth, clientAuth
subjectAltName         = @alt_names
crlDistributionPoints  = URI:http://pki.my-corp.com/intermediate.crl

[ alt_names ]
DNS.1 = my-service.local
```

**Ключевые расширения:**

- `basicConstraints = critical, CA:true, pathlen:0` — разрешает подписывать сертификаты, но **запрещает** создавать дочерние CA
- `keyUsage = critical, keyCertSign, cRLSign` — только подпись сертификатов и CRL
- `extendedKeyUsage = serverAuth, clientAuth` (в `v3_server_cert`) — аутентификация сервера и клиента
- `crlDistributionPoints` — URL для автоматической проверки отзыва

### 3. Создание ключа и CSR для Intermediate CA

```bash
cd intermediate-ca

openssl req -new \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout intermediate.key \
    -out csr/intermediate.csr

cd ..
```

- `-nodes` — не шифровать ключ паролем (допустимо, если ключ хранится в Vault/HSM; для файлового хранения уберите флаг и используйте `-passout pass:PASSWORD`)
- `-sha512` — алгоритм хеширования (SHA-512, текущий стандарт)

### 4. Подпись CSR Intermediate CA с помощью Root CA

Этот шаг требует временного извлечения ключа Root CA из офлайн-хранилища.

```bash
# Временное извлечение root-ca/ca.key (выполняется на air-gapped системе)
cd root-ca

openssl ca -config openssl.cnf \
    -in ../intermediate-ca/csr/intermediate.csr \
    -out ../intermediate-ca/intermediate.crt \
    -extensions v3_intermediate_ca

cd ..

# Снова убрать root-ca/ca.key в офлайн-хранилище!
```

Расширение `v3_intermediate_ca` берётся из конфигурации Root CA (`root-ca/openssl.cnf`). Убедитесь, что секция `[v3_intermediate_ca]` с `pathlen:0` определена в Root CA конфиге ([Root CA Setup](./root_ca_setup.md)).

### 5. Создание цепочки сертификатов (ca-chain.crt)

```bash
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt
```

Файл `ca-chain.crt` используется:

- Nginx: `ssl_client_certificate /path/to/ca-chain.crt` — проверка клиентских сертификатов (mTLS)
- Диагностика: `openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt`
- Серверы: объединяется с сертификатом сервиса для отправки полной цепочки клиентам

## Additional Information

### Безопасность ключа Intermediate CA

Ключ Intermediate CA — критичный актив. Рекомендации:

- Хранить в Vault (Transit/Key-Value engine) или на выделенном хосте с MFA
- Ограничить доступ: только CI/CD-система или администратор PKI
- Регулярная ротация: перевыпуск промежуточного CA с новым ключом (старый — в CRL)
- Мониторинг: алерт на любое обращение к `intermediate.key`

### Связанные темы

Пошаговые инструкции по смежным операциям: [создание Root CA](./root_ca_setup.md) (предыдущий шаг), [выпуск и отзыв сертификатов сервисов](./service_certificate_management.md), [утилиты и диагностика](./common_utilities.md). Общие сведения об архитектуре — в [обзоре двухуровневого CA](./overview.md). Теория иерархии доверия, CRL, OCSP — в [обзоре PKI](../../../../Concepts/pki_overview.md). Практический пример с `ca-chain.crt` — [mTLS в Nginx](../../../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md). Альтернативный подход для тестовых сред — [настройка одноуровневого CA](../single_tier/ca_setup.md).
