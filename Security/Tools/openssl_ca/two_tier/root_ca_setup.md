# Root CA Setup

## Definitions

**Root CA (корневой центр сертификации)** — вершина иерархии доверия PKI. Самоподписанный сертификат с `CA:true`, используется исключительно для подписи промежуточных CA (Intermediate). После выпуска промежуточных сертификатов приватный ключ Root CA хранится на изолированной (air-gapped) системе.

**Air-gapped система** — компьютер или среда, физически отключённая от сетей общего пользования. Применяется для защиты ключей Root CA от удалённых атак.

> Базовые понятия PKI (ключ, CSR, X.509, цепочка доверия, CRL/OCSP) — в [обзоре PKI](../../../../Concepts/pki_overview.md).

## Basic Concepts

### Назначение Root CA

Root CA — вершина доверия в PKI-инфраструктуре. Его приватный ключ — наиболее ценный актив. Архитектура двухуровневого CA предполагает, что Root CA:

- Подписывает **только** сертификаты промежуточных CA (Intermediate CA)
- Хранится офлайн между редкими операциями (выпуск нового промежуточного CA, генерация CRL)
- Имеет длительный срок действия — 10–25 лет

### Структура директорий

```text
root-ca/
├── openssl.cnf          # Конфигурация OpenSSL для Root CA
├── ca.key               # Приватный ключ Root CA (убирается в офлайн)
├── ca.crt               # Самоподписанный сертификат Root CA
└── db/
    ├── index.txt        # База данных выданных сертификатов
    ├── serial           # Счётчик серийных номеров
    ├── newcerts/        # Архив выданных сертификатов
    └── crl/             # Списки отзыва (CRL)
```

| Путь | Назначение |
|---|---|
| `openssl.cnf` | Конфигурация Root CA: пути, политики, расширения |
| `ca.key` | Приватный ключ RSA 4096 бит (переносится в офлайн) |
| `ca.crt` | Самоподписанный X.509-сертификат (публичный, распространяется клиентам) |
| `db/index.txt` | База данных подписанных сертификатов (обновляется при подписи Intermediate CA) |
| `db/serial` | Счётчик серийных номеров (hex, инкрементируется автоматически) |
| `db/newcerts/` | Копии подписанных сертификатов с именами `<serial>.pem` |
| `db/crl/` | Списки отзыва (CRL) для отзыва Intermediate CA |

### Конфигурация OpenSSL

Ключевые секции `openssl.cnf` для Root CA:

| Секция | Назначение |
|---|---|
| `[ca]` / `[CA_default]` | Основные параметры CA: пути к ключам, БД, политика |
| `[policy_strict]` | Политика валидации CSR промежуточных CA — требует совпадения `C`, `ST`, `O` с Root CA |
| `[req]` / `[req_distinguished_name]` | Параметры запроса на создание сертификата (DN-поля) |
| `[v3_ca]` | Расширения X.509 v3 для корневого сертификата |
| `[v3_intermediate_ca]` | Расширения для подписи Intermediate CA — `pathlen:0` |

### Критичные расширения X.509 v3

#### Для корневого сертификата (`[v3_ca]`)

| Расширение | Значение | Обоснование |
|---|---|---|
| `basicConstraints` | `critical, CA:true, pathlen:1` | `pathlen:1` допускает ровно один уровень промежуточных CA под Root |
| `keyUsage` | `critical, keyCertSign, cRLSign` | Разрешает только подписание сертификатов и CRL, но не TLS/клиентских данных |
| `subjectKeyIdentifier` | `hash` | Уникальный отпечаток открытого ключа |
| `authorityKeyIdentifier` | `keyid:always,issuer` | Для самоподписанного Root CA указывает на самого себя |

#### Для сертификата Intermediate CA (`[v3_intermediate_ca]`)

| Расширение | Значение | Обоснование |
|---|---|---|
| `basicConstraints` | `critical, CA:true, pathlen:0` | Запрещает Intermediate CA подписывать другие CA |
| `keyUsage` | `critical, keyCertSign, cRLSign` | Только подпись сертификатов и CRL |

## Practical Scenarios

### 1. Создание структуры директорий

```bash
mkdir -p root-ca/db/{newcerts,crl}
touch root-ca/db/index.txt
echo "1000" > root-ca/db/serial
```

### 2. Конфигурационный файл `root-ca/openssl.cnf`

```ini
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt
new_certs_dir   = $dir/db/newcerts

certificate     = $dir/ca.crt
serial          = $dir/db/serial
private_key     = $dir/ca.key

default_md      = sha512
default_days    = 3650
policy          = policy_strict

# Строгая политика: поля C, ST, O в CSR промежуточного CA
# должны совпадать с Root CA
[ policy_strict ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[ req ]
default_bits        = 4096
distinguished_name  = req_distinguished_name
x509_extensions     = v3_ca
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
O  = My Private Corp
CN = My Private Corp Root CA

# Расширения X.509 v3 для корневого сертификата
[ v3_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:1
keyUsage               = critical, keyCertSign, cRLSign

# Расширения для подписи Intermediate CA
# Добавляются в тот же файл root-ca/openssl.cnf
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign
```

### 3. Генерация ключа и самоподписанного сертификата

```bash
cd root-ca

openssl req -new -x509 \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650

cd ..
```

| Флаг | Назначение |
|---|---|
| `-new -x509` | Создание самоподписанного X.509-сертификата |
| `-newkey rsa:4096` | Генерация нового RSA-ключа 4096 бит |
| `-sha512` | Алгоритм хеширования подписи |
| `-nodes` | Без шифрования приватного ключа |
| `-days 3650` | Срок действия — 10 лет |

> **Безопасность:** В production-среде уберите флаг `-nodes` — OpenSSL запросит пароль для шифрования ключа (`-passout pass:PASSWORD` или интерактивно). Пароль защищает приватный ключ Root CA. Для тестов `-nodes` допустим.

### 4. Подпись Intermediate CA

После создания CSR промежуточным CA ([Intermediate CA Setup](./intermediate_ca_setup.md)), подпись выполняется на air-gapped системе:

```bash
cd root-ca

openssl ca -config openssl.cnf \
    -extensions v3_intermediate_ca \
    -days 1825 \
    -notext \
    -in ../intermediate-ca/csr/intermediate.csr \
    -out ../intermediate-ca/intermediate.crt

cd ..
```

| Флаг | Назначение |
|---|---|
| `-extensions v3_intermediate_ca` | Применяет расширения из секции `[v3_intermediate_ca]` |
| `-days 1825` | Срок действия Intermediate CA — 5 лет |
| `-notext` | Не добавлять текстовое представление сертификата в выходной файл |
| `-in` | Путь к CSR промежуточного CA |
| `-out` | Путь к подписанному сертификату Intermediate CA |

### 5. Защита приватного ключа

После подписи Intermediate CA:

1. Проверить отпечаток `ca.key`: `openssl rsa -in ca.key -noout -modulus | sha512sum`
2. Скопировать `ca.key` на зашифрованный офлайн-носитель (HSM, зашифрованная USB-флешка)
3. Убедиться в корректности копии (сравнить отпечатки)
4. Удалить `ca.key` с рабочей системы: `shred -uvz ca.key`
5. Ключ извлекается из офлайн-хранилища **только** для:
   - Подписи нового Intermediate CA
   - Генерации CRL для отзыва скомпрометированного Intermediate CA

## Additional Information

Проверка созданного сертификата:

```bash
# Проверка структуры и содержимого
openssl x509 -in root-ca/ca.crt -noout -text

# Проверка что сертификат самоподписанный
openssl verify -CAfile root-ca/ca.crt root-ca/ca.crt

# Проверка basicConstraints
openssl x509 -in root-ca/ca.crt -noout -text | grep -A1 "Basic Constraints"
```

Архитектура двухуровневого CA — в [обзоре](./overview.md). Настройка Intermediate CA, подписанного Root CA — в [Intermediate CA Setup](./intermediate_ca_setup.md). Теория иерархии доверия, CRL, OCSP — в [обзоре PKI](../../../../Concepts/pki_overview.md).
