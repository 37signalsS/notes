# Создание Промежуточного CA (Intermediate CA)

Этот CA будет использоваться для повседневных задач по выпуску сертификатов для сервисов и пользователей. Его ключ хранится онлайн, но в защищенном месте (например, в Vault или с правами доступа только для CI/CD системы).

**2.4. Структура директорий Intermediate CA**

```bash
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber
```

**2.5. Конфигурационный файл Intermediate CA (`intermediate-ca/openssl.cnf`)**

```ini
# intermediate-ca/openssl.cnf

[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt         # База данных выданных сертификатов
new_certs_dir   = $dir/certs                # Архив выданных сертификатов
crl_dir         = $dir/crl                  # Директория для CRL

certificate     = $dir/intermediate.crt     # Сертификат самого Intermediate CA
serial          = $dir/db/serial            # Счетчик серийных номеров
crlnumber       = $dir/db/crlnumber         # Счетчик номеров CRL
crl             = $dir/crl/crl.pem          # Файл CRL
private_key     = $dir/intermediate.key     # Приватный ключ Intermediate CA

default_md      = sha512
default_days    = 365                       # Срок действия сертификата для сервиса (1 год)
policy          = policy_loose              # Политика для конечных сертификатов

# Политика для Intermediate CA может быть более мягкой.
# Она не требует совпадения полей с самим CA, только наличия Common Name.
# Это позволяет выпускать сертификаты для разных команд или проектов.
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
x509_extensions     = v3_intermediate_ca # Ссылка на расширения по умолчанию
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
O  = My Private Corp
CN = My Private Corp Intermediate CA

# Расширения X.509 v3 для промежуточного CA
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
# critical, CA:true — это все еще CA.
# pathlen:0 — критически важное ограничение! Запрещает этому CA
# подписывать другие CA. Он может выпускать только конечные сертификаты.
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign

# Расширения для конечных сертификатов (сервисы, пользователи)
# Будут использоваться при подписи запросов от сервисов.
[ v3_server_cert ]
basicConstraints       = CA:FALSE
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
extendedKeyUsage       = serverAuth, clientAuth
# Ссылка на секцию с альтернативными именами (SAN)
# ЗАПОЛНЯЕТСЯ ПЕРЕД ВЫДАЧЕЙ СЕРТИФИКАТА
subjectAltName         = @alt_names
# Ссылка на точку распространения CRL
crlDistributionPoints  = URI:http://pki.my-corp.com/intermediate.crl

[ alt_names ]
DNS.1 = my-service.local
```
*`pathlen:0`* запрещает этому CA подписывать другие CA.

**2.6. Создание ключа и CSR для Intermediate CA**

```bash
cd intermediate-ca

# Создаем ключ и CSR
openssl req -new 
    -config openssl.cnf 
    -newkey rsa:4096 -sha512 -nodes 
    -keyout intermediate.key 
    -out csr/intermediate.csr

cd ..
```

**2.7. Подпись CSR Intermediate CA с помощью Root CA**

```bash
# Возвращаем ключ Root CA из офлайн-хранилища (если убирали)
cd root-ca

# Подписываем запрос
openssl ca -config openssl.cnf -in ../intermediate-ca/csr/intermediate.csr 
    -out ../intermediate-ca/intermediate.crt -extensions v3_intermediate_ca

cd ..
# Снова убираем ключ Root CA в безопасное место!
```

**2.8. Создание цепочки сертификатов**

Для корректной работы TLS-клиентов (браузеров, утилит) сервер должен отправлять не только свой сертификат, но и сертификат промежуточного CA, который его подписал. Это позволяет клиенту построить полную цепочку доверия до корневого сертификата, который у него уже есть в хранилище.

```bash
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt
```
- **`ca-chain.crt`**: Этот файл будет использоваться в директиве `ssl_client_certificate` в Nginx для проверки клиентских сертификатов, а также может быть объединен с сертификатом сервера для отправки клиентам.
