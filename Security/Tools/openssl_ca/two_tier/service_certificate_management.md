# Service Certificate Management

## Definitions

**Сертификат сервиса (service certificate)** — X.509-сертификат, выдаваемый для конкретного сервиса (веб-сервер, API, база данных). Подписывается Intermediate CA, содержит SAN (Subject Alternative Names) с DNS-именами и/или IP-адресами сервиса.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата, создаётся владельцем сервиса и передаётся администратору CA.

**SAN (Subject Alternative Name)** — расширение X.509 v3, позволяющее указать несколько DNS-имён и IP-адресов для одного сертификата. Критично для корректной проверки TLS-соединений.

> Базовые понятия (CSR, X.509, SAN, CRL, цепочка доверия) — в [обзоре PKI](../../../../Concepts/pki_overview.md).

## Basic Concepts

### Принципы выпуска сертификатов

В двухуровневой архитектуре Root CA не участвует в выпуске сертификатов сервисов — это задача Intermediate CA:

| Этап | Ответственный | Где выполняется |
|---|---|---|---|
| Генерация ключа + CSR | Владелец сервиса | Рабочая станция/сервер |
| Валидация CSR, SAN | Администратор Intermediate CA | Система Intermediate CA |
| Подпись, выдача сертификата | Intermediate CA | Система Intermediate CA |
| Установка на сервис | Владелец сервиса | Целевой сервер |

### Разделение ролей

Ключевой принцип: **приватный ключ сервиса никогда не покидает сервер, на котором будет использоваться сертификат**. CSR передаётся администратору CA, который подписывает его и возвращает готовый `.crt`.

### Проверка и доверие

- **Цепочка доверия** — `сервис → Intermediate CA → Root CA`. Верификация выполняется через файл `ca-chain.crt`, содержащий оба CA-сертификата.
- **Установка доверия в ОС** — в системное хранилище добавляется только `root-ca/ca.crt`. После этого все сертификаты, подписанные данной PKI, считаются доверенными.

### Отзыв сертификатов

При компрометации ключа или изменении доменных имён сертификат отзывается через Intermediate CA. Механизм — CRL (Certificate Revocation List), публикуемый по URL из расширения `crlDistributionPoints`. Подробности механизма — в [обзоре PKI](../../../../Concepts/pki_overview.md#механизмы-отзыва-сертификатов).

## Practical Scenarios

### 1. Генерация CSR на стороне клиента

Владелец сервиса создаёт ключ и CSR, указывая базовую DN-информацию:

```bash
openssl genrsa -out my-service.key 4096

openssl req -new -key my-service.key -out my-service.csr \
    -subj "/C=RU/ST=Moscow/O=My Private Corp/OU=WebApp/CN=my-service.local"
```

Файл `my-service.csr` передаётся администратору Intermediate CA.

### 2. Подготовка SAN в конфигурации Intermediate CA

Администратор редактирует `intermediate-ca/openssl.cnf` и указывает допустимые имена в секции `[alt_names]`:

```ini
[alt_names]
DNS.1 = my-service.local
DNS.2 = my-app.local
IP.1  = 192.168.10.20
```

Секция `[v3_server_cert]` уже определена в конфигурации Intermediate CA ([настройка Intermediate CA](./intermediate_ca_setup.md#2-создание-конфигурационного-файла)). Она включает `subjectAltName = @alt_names`, `basicConstraints = CA:FALSE`, `keyUsage` и `extendedKeyUsage = serverAuth`. При необходимости добавьте новые домены в `[alt_names]` и используйте существующую секцию расширений.

### 3. Подпись CSR и выдача сертификата

```bash
cd intermediate-ca

openssl ca -config openssl.cnf \
    -in ../my-service.csr \
    -out ../my-service.crt \
    -extensions v3_server_cert \
    -notext

cd ..
```

Результат: `my-service.crt`, `my-service.key`, `intermediate-ca/ca-chain.crt` — готовы к настройке TLS на сервере.

### 4. Проверка цепочки доверия

```bash
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
```

Ожидаемый вывод: `my-service.crt: OK`.

### 5. Установка корневого сертификата в системное хранилище

Для Debian/Ubuntu:

```bash
sudo cp root-ca/ca.crt /usr/local/share/ca-certificates/my-private-corp-root.crt
sudo update-ca-certificates
```

Для RHEL/CentOS/Fedora:

```bash
sudo cp root-ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### 6. Отзыв скомпрометированного сертификата

```bash
cd intermediate-ca

# Отзыв
openssl ca -config openssl.cnf -revoke ../my-service.crt

# Генерация CRL
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

cd ..
```

CRL-файл `crl/crl.pem` необходимо опубликовать по URL из `crlDistributionPoints` (например, на веб-сервере по `http://pki.my-corp.com/intermediate.crl`) и регулярно обновлять.

### 7. Быстрый метод для тестов (без Intermediate CA)

> ⚠️ **Не для production** — подвергает риску ключ Root CA, не поддерживает учёт и отзыв через CRL. Используйте только для локальных тестов.

Для полноценного выпуска сертификатов в двухуровневой архитектуре см. [быстрый метод без Intermediate CA](../single_tier/quick_method.md).

## Additional Information

- Архитектура двухуровневого CA — в [обзоре](./overview.md)
- Настройка Intermediate CA, включая секции `[v3_server_cert]` и `[alt_names]` — в [настройке Intermediate CA](./intermediate_ca_setup.md)
- Генерация Root CA (air-gapped) — в [создании Root CA](./root_ca_setup.md)
- Диагностика сертификатов, CSR, CRL — в [утилитах двухуровневого CA](./common_utilities.md)
- Быстрый метод для тестов (без базы данных) — в [quick_method.md](../single_tier/quick_method.md)
- Теория PKI, механизмы отзыва — в [обзоре PKI](../../../../Concepts/pki_overview.md)
