# Управление сертификатами сервисов

## Практические сценарии

### Выпуск сертификата для сервиса (с поддержкой SAN)

Это централизованный и наиболее правильный подход. Заявитель (клиент) создает простой запрос, а администратор Intermediate CA определяет, какие доменные имена (SAN) будут включены в сертификат.

**Создание ключа и простого CSR на стороне клиента**

Клиент генерирует приватный ключ и CSR, указывая только основную информацию (DN). Никаких расширений на этом этапе не требуется.

```bash
# 1. Создаем приватный ключ для нашего сервиса
openssl genrsa -out my-service.key 4096

# 2. Создаем простой CSR. CN важен для идентификации запроса.
openssl req -new -key my-service.key -out my-service.csr 
  -subj "/C=RU/ST=Moscow/O=My Private Corp/OU=WebApp/CN=my-service.local"
```
Далее файл `my-service.csr` передается администратору Intermediate CA.

**Подпись CSR с помощью Intermediate CA**

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
openssl ca -config openssl.cnf -in ../my-service.csr -out ../my-service.crt 
  -extensions v3_server_cert -notext

cd ..
```
- `-extensions v3_server_cert`: Эта опция указывает OpenSSL применить расширения из секции `[v3_server_cert]` конфигурационного файла. Поскольку в этой секции есть строка `subjectAltName = @alt_names`, OpenSSL автоматически добавит в сертификат все имена из секции `[alt_names]`.

Теперь у вас есть `my-service.crt`, `my-service.key` и `intermediate-ca/ca-chain.crt` для настройки вашего веб-сервера.

### Жизненный цикл сертификата

#### Проверка цепочки доверия

```bash
# Проверяем, что сертификат сервиса доверен цепочке
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
```
Ожидаемый вывод: `my-service.crt: OK`.

#### Добавление корневого сертификата в системное хранилище

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

#### Отзыв скомпрометированного сертификата

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

### Быстрый метод для тестов (одноуровневый CA)

Для быстрых тестов можно обойтись без промежуточного CA, подписывая сертификаты напрямую корневым. **Этот метод не рекомендуется для production, так как он подвергает риску ключ Root CA.**

```bash
# Используем наш Root CA из первой части
# 1. Создаем ключ и CSR для тестового сайта
openssl req -new -newkey rsa:2048 -nodes 
            -keyout test.key -out test.csr 
            -subj "/CN=test.local"

# 2. Подписываем CSR напрямую корневым CA
# Для добавления SAN потребуется опция -extfile с описанием расширений.
openssl x509 -req -in test.csr 
    -CA root-ca/ca.crt -CAkey root-ca/ca.key -CAcreateserial 
    -out test.crt -days 90
```
- `-CAcreateserial`: Создает файл `root-ca.srl` (если его нет) для отслеживания серийных номеров.
- **Недостаток**: этот метод не позволяет вести полноценный учёт и отзывать сертификаты через CRL и подвергает риску ключ корневого CA.
