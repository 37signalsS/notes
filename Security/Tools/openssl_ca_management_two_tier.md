# Управление двухуровневым центром сертификации (CA) на OpenSSL

> **Примечание:** Это руководство описывает создание **двухуровневого** центра сертификации (Root CA + Intermediate CA), что является рекомендуемой практикой для производственных сред. Для более простых задач доступно [руководство по созданию одноуровневого CA](./openssl_ca_management.md).

Это руководство поможет вам создать и управлять собственным двухуровневым центром сертификации (CA) с помощью OpenSSL. Такой CA необходим для выпуска доверенных SSL/TLS-сертификатов для внутренних сервисов, разработки, тестирования и реализации взаимной аутентификации (mTLS).

**Почему двухуровневая архитектура?**

Использование промежуточного CA (Intermediate CA) — это стандарт безопасности.
1.  **Безопасность**: Приватный ключ корневого CA (Root CA) используется только один раз для подписи промежуточного CA, после чего его можно перенести в безопасное офлайн-хранилище. Это минимизирует риск компрометации самого важного ключа.
2.  **Гибкость**: Повседневные операции по выпуску и отзыву сертификатов выполняются с помощью промежуточного CA. Если его ключ скомпрометирован, можно отозвать только его, не затрагивая всю инфраструктуру доверия.

## Глава 1. Основы PKI и OpenSSL

### 1.1. Основные понятия
*   **Приватный ключ (`.key`)**: Секретный ключ, используемый для создания цифровых подписей и расшифровки данных. **Его компрометация равносильна компрометации удостоверяемого им лица.**
*   **Запрос на подпись сертификата (`.csr`)**: Файл, содержащий открытый ключ и идентифицирующую информацию (домен, организацию). Отправляется в CA для получения сертификата.
*   **Сертификат (`.crt`, `.cer`)**: Цифровое удостоверение, подписанное CA. Связывает открытый ключ с конкретным субъектом (сервером, пользователем).
*   **Цепочка доверия (Chain of Trust)**: Иерархическая последовательность сертификатов, от конечного сертификата до доверенного корневого. Например: `Root CA -> Intermediate CA -> a_service.crt`. Клиент может проверить подлинность сертификата сервиса, если доверяет корневому CA.

### 1.2. Форматы файлов
*   `.pem` (Privacy-Enhanced Mail): Текстовый формат-контейнер, кодированный в Base64. Может содержать ключ, сертификат, цепочку сертификатов или всё сразу. Наиболее распространенный формат, используемый, например, в Nginx. Легко определить по заголовкам `-----BEGIN...-----` и `-----END...-----`.
*   `.der`: Бинарный формат сертификата или ключа. Часто используется в Java и Windows-средах.
*   `.p12` / `.pfx` (PKCS#12): Бинарный формат-архив, защищенный паролем. Может содержать приватный ключ, сертификат и цепочку сертификатов в одном файле. Удобен для безопасной передачи и импорта в Windows, Java KeyStore и браузеры.

---

## Глава 2. Формальный метод: Создание двухуровневого CA

### Часть 1: Создание Корневого CA (Root CA)

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
openssl req -new -x509 \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -days 3650

cd ..
```
> **Безопасность!** После этого шага приватный ключ `root-ca/ca.key` (и пароль от него) следует перенести на защищенный, отключенный от сети носитель (например, зашифрованную USB-флешку) и удалить с диска. Он понадобится только для подписи новых промежуточных CA или генерации CRL для них.

### Часть 2: Создание Промежуточного CA (Intermediate CA)

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
openssl req -new \
    -config openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout intermediate.key \
    -out csr/intermediate.csr

cd ..
```

**2.7. Подпись CSR Intermediate CA с помощью Root CA**

```bash
# Возвращаем ключ Root CA из офлайн-хранилища (если убирали)
cd root-ca

# Подписываем запрос
openssl ca -config openssl.cnf -in ../intermediate-ca/csr/intermediate.csr \
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

### Часть 3: Выпуск сертификата для сервиса (с поддержкой SAN)

Это централизованный и наиболее правильный подход. Заявитель (клиент) создает простой запрос, а администратор Intermediate CA определяет, какие доменные имена (SAN) будут включены в сертификат.

**2.9. Создание ключа и простого CSR на стороне клиента**

Клиент генерирует приватный ключ и CSR, указывая только основную информацию (DN). Никаких расширений на этом этапе не требуется.

```bash
# 1. Создаем приватный ключ для нашего сервиса
openssl genrsa -out my-service.key 4096

# 2. Создаем простой CSR. CN важен для идентификации запроса.
openssl req -new -key my-service.key -out my-service.csr \
  -subj "/C=RU/ST=Moscow/O=My Private Corp/OU=WebApp/CN=my-service.local"
```
Далее файл `my-service.csr` передается администратору Intermediate CA.

**2.10. Подпись CSR с помощью Intermediate CA**

Администратор Intermediate CA перед подписью должен отредактировать файл `intermediate-ca/openssl.cnf` и вписать правильные DNS-имена и/или IP-адреса в секцию `[alt_names]`.

```ini
# intermediate-ca/openssl.cnf -> [alt_names]
[alt_names]
DNS.1 = my-service.local
DNS.2 = my-app.local
IP.1 = 192.168.10.20
```

После этого администратор подписывает запрос, используя профиль `v3_server_cert`:

```bash
cd intermediate-ca

# Подписываем запрос
openssl ca -config openssl.cnf -in ../my-service.csr -out ../my-service.crt \
  -extensions v3_server_cert -notext

cd ..
```
- `-extensions v3_server_cert`: Эта опция указывает OpenSSL применить расширения из секции `[v3_server_cert]` конфигурационного файла. Поскольку в этой секции есть строка `subjectAltName = @alt_names`, OpenSSL автоматически добавит в сертификат все имена из секции `[alt_names]`.

Теперь у вас есть `my-service.crt`, `my-service.key` и `intermediate-ca/ca-chain.crt` для настройки вашего веб-сервера.

---

## Глава 3. Жизненный цикл сертификата

### 3.1. Проверка цепочки доверия

```bash
# Проверяем, что сертификат сервиса доверен цепочке
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
```
Ожидаемый вывод: `my-service.crt: OK`.

### 3.2. Добавление корневого сертификата в системное хранилище

Чтобы вся система доверяла вашему CA, нужно добавить в нее **только корневой сертификат `root-ca/ca.crt`**.

**Для Debian/Ubuntu:**
```bash
sudo cp root-ca/ca.crt /usr/local/share/ca-certificates/my-private-corp-root.crt
sudo update-ca-certificates
```
**Для RHEL/CentOS/Fedora:**
```bash
sudo cp root-ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### 3.3. Отзыв скомпрометированного сертификата

Если ключ `my-service.key` был скомпрометирован, сертификат нужно отозвать. Это делается с помощью Intermediate CA.

```bash
cd intermediate-ca

# 1. Отзыв сертификата
openssl ca -config openssl.cnf -revoke ../my-service.crt

# 2. Генерация списка отзыва (CRL)
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

cd ..
```
> **Как клиенты узнают об отзыве?**
> В конфигурации `intermediate-ca/openssl.cnf` мы добавили строку `crlDistributionPoints = URI:http://pki.my-corp.com/intermediate.crl`. Это расширение записывается в каждый выданный сертификат. Когда клиент проверяет сертификат, он видит этот URL, скачивает по нему CRL и проверяет, не отозван ли проверяемый сертификат.
> **Ваша задача** — разместить сгенерированный файл `crl/crl.pem` по этому публично доступному URL (например, на обычном веб-сервере) и регулярно его обновлять.

---

## Глава 4. Быстрый метод для тестов (одноуровневый CA)

Для быстрых тестов можно обойтись без промежуточного CA, подписывая сертификаты напрямую корневым. **Этот метод не рекомендуется для production, так как он подвергает риску ключ Root CA.**

```bash
# Используем наш Root CA из первой части
# 1. Создаем ключ и CSR для тестового сайта
openssl req -new -newkey rsa:2048 -nodes \
            -keyout test.key -out test.csr \
            -subj "/CN=test.local"

# 2. Подписываем CSR напрямую корневым CA
# Для добавления SAN потребуется опция -extfile с описанием расширений.
openssl x509 -req -in test.csr \
    -CA root-ca/ca.crt -CAkey root-ca/ca.key -CAcreateserial \
    -out test.crt -days 90
```
- `-CAcreateserial`: Создает файл `root-ca.srl` (если его нет) для отслеживания серийных номеров.
- **Недостаток**: этот метод не позволяет вести полноценный учёт и отзывать сертификаты через CRL и подвергает риску ключ корневого CA.

---

## Приложение A: Пример — mTLS в Nginx

Подробное описание и практический пример настройки mTLS в Nginx можно найти в разделе [Аутентификация по клиентским SSL-сертификатам (mTLS)](../../WebServers/Nginx/Security/nginx_tls_ssl_configuration.md#аутентификация-по-клиентским-ssl-сертификатам-mtls)

---

## Приложение B: Полезные команды

- **Просмотреть содержимое сертификата:**
  `openssl x509 -in my-service.crt -noout -text`
- **Просмотреть содержимое CSR:**
  `openssl req -in my-service.csr -noout -text`
- **Просмотреть содержимое CRL:**
  `openssl crl -in intermediate-ca/crl/crl.pem -noout -text`
- **Проверить соответствие ключа и сертификата:** (хеши модулей должны совпадать)
  ```bash
  openssl rsa -noout -modulus -in my-service.key | openssl md5
  openssl x509 -noout -modulus -in my-service.crt | openssl md5
  ```
- **Подключиться к TLS-серверу и показать его сертификат:**
  `openssl s_client -connect my-service.local:443 -showcerts < /dev/null`
- **Проверить цепочку доверия для файла fullchain:**
  `openssl verify -CAfile root-ca/ca.crt my-service.fullchain.crt`
