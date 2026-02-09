# Создание Корневого CA (Root CA)

Это "Бог" вашей PKI-инфраструктуры. Его ключ — самый ценный актив. Все операции с ним должны выполняться на изолированной (air-gapped) системе.

**2.1. Структура директорий Root CA**

```bash
# Создаем изолированное окружение для Root CA
mkdir -p root-ca/db/{newcerts,crl}
touch root-ca/db/index.txt
echo "1000" > root-ca/db/serial
```
- `db/`: База данных для отслеживания выданных сертификатов (в нашем случае — только промежуточных).
- `newcerts/`: Архив выданных сертификатов.

**2.2. Конфигурационный файл Root CA (`root-ca/openssl.cnf`)**

```ini
# root-ca/openssl.cnf

[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt         # База данных сертификатов
new_certs_dir   = $dir/newcerts             # Архив выданных сертификатов

certificate     = $dir/ca.crt               # Сертификат самого Root CA
serial          = $dir/db/serial            # Файл с серийными номерами
private_key     = $dir/ca.key               # Приватный ключ Root CA

default_md      = sha512                    # Алгоритм хеширования
default_days    = 3650                      # Срок действия по умолчанию (10 лет)
policy          = policy_strict             # Политика проверки полей CSR

# Политика для Root CA должна быть строгой.
# Она требует, чтобы страна, регион и организация в CSR
# промежуточного CA совпадали с данными Root CA.
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
x509_extensions     = v3_ca # Секция с расширениями для Root CA
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
O  = My Private Corp
CN = My Private Corp Root CA

# Расширения X.509 v3 для корневого сертификата
[ v3_ca ]
# Идентификатор ключа субъекта. Уникальный отпечаток открытого ключа сертификата.
# Позволяет клиентам однозначно идентифицировать сертификат.
subjectKeyIdentifier   = hash

# Идентификатор ключа издателя. Ссылка на subjectKeyIdentifier сертификата,
# которым подписан данный. Для самоподписанного Root CA указывает на самого себя.
authorityKeyIdentifier = keyid:always,issuer

# Основные ограничения. `critical` означает, что приложение обязано это расширение понять.
# CA:true — этот сертификат может подписывать другие сертификаты.
# pathlen:1 — глубина цепочки под этим CA. Означает, что под этим Root CA
# может быть только один уровень промежуточных CA (Intermediate CA).
# Промежуточный CA, подписанный этим Root, должен будет иметь pathlen:0.
basicConstraints       = critical, CA:true, pathlen:1

# Назначение ключа.
# keyCertSign, cRLSign — обязательные расширения для CA, разрешают
# подписывать сертификаты и списки отзыва (CRL).
keyUsage               = critical, keyCertSign, cRLSign
```

**2.3. Создание ключа и сертификата Root CA**

```bash
cd root-ca

# Создаем приватный ключ (ca.key) и самоподписанный сертификат (ca.crt)
# ВАЖНО: В production-среде уберите флаг -nodes. OpenSSL запросит пароль
# для шифрования приватного ключа. Этот пароль — ключ ко всему.
openssl req -new -x509 
    -config openssl.cnf 
    -newkey rsa:4096 -sha512 -nodes 
    -keyout ca.key 
    -out ca.crt 
    -days 3650

cd ..
```
> **Безопасность!** После этого шага приватный ключ `root-ca/ca.key` (и пароль от него) следует перенести на защищенный, отключенный от сети носитель (например, зашифрованную USB-флешку) и удалить с диска. Он понадобится только для подписи новых промежуточных CA или генерации CRL для них.
