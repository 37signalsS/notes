# Управление сертификатами сервисов (одноуровневый CA)

## Определения

**CSR (Certificate Signing Request)** — запрос на подпись сертификата. Содержит открытый ключ и DN-информацию владельца. Генерируется на стороне сервиса и передаётся администратору CA.

**SAN (Subject Alternative Name)** — расширение X.509, позволяющее указать несколько доменных имён и IP-адресов в одном сертификате. Обязательно для современных браузеров ([RFC 2818](https://datatracker.ietf.org/doc/html/rfc2818)).

**CRL (Certificate Revocation List)** — список отозванных сертификатов. Подробности механизма — в [обзоре PKI](../../../Concepts/pki_overview.md#механизмы-отзыва-сертификатов).

## Базовые концепции

### Жизненный цикл сертификата сервиса

```
Генерация ключа → Создание CSR → Передача CA → Подпись с SAN → Установка → Мониторинг → Перевыпуск/Отзыв
```

Ключевые принципы:

- **Разделение ролей:** клиент генерирует ключ и CSR, администратор CA подписывает и контролирует SAN
- **Контроль SAN:** CA определяет, какие домены/IP будут в сертификате, независимо от запроса клиента
- **Формальный метод:** все операции фиксируются в `db/index.txt`, поддерживается отзыв и CRL

### Архитектурные ограничения

В одноуровневой архитектуре корневой CA выполняет все функции одним ключом. Это означает:

- Компрометация выпускающего ключа = компрометация корневого доверия
- Для production настоятельно рекомендуется [двухуровневая архитектура](../two_tier/overview.md)

## Практические сценарии

### Выпуск сертификата с SAN

#### Шаг 1: Создание ключа и CSR на стороне клиента

Клиент генерирует приватный ключ и CSR с базовой DN-информацией. Расширения на этом этапе не требуются.

```bash
# Создаём приватный ключ для сервиса
openssl genrsa -out my-service.key 4096

# Создаём CSR. CN важен для идентификации запроса.
openssl req -new -key my-service.key -out my-service.csr \
    -subj "/C=RU/ST=Moscow/O=My Private Org/OU=Service/CN=my-service.local"
```

Файл `my-service.csr` передаётся администратору CA.

#### Шаг 2: Редактирование `openssl.cnf` и подпись CSR

Администратор CA редактирует `ca/openssl.cnf` и вписывает правильные DNS-имена и IP-адреса в секцию `[alt_names]`:

```ini
# ca/openssl.cnf -> [alt_names]
[alt_names]
DNS.1 = my-service.local
DNS.2 = my-app.local
IP.1  = 192.168.10.20
```

После этого подписывает запрос:

```bash
cd ca

# Подпись запроса с применением расширений v3_req
openssl ca -config openssl.cnf -in ../my-service.csr -out ../my-service.crt \
    -extensions v3_req -notext

cd ..
```

- `-extensions v3_req` — применить расширения из секции `[v3_req]`. Поскольку в ней указано `subjectAltName = @alt_names`, OpenSSL автоматически добавит все имена из `[alt_names]`.
- `-notext` — не выводить текстовое описание сертификата в stdout (ускоряет процесс).

После выполнения в `ca/db/index.txt` появится новая запись, а `ca/db/serial` обновится. Проверить SAN:

```bash
openssl x509 -in my-service.crt -noout -text | grep -A1 "Subject Alternative Name"
```

### Проверка цепочки доверия

```bash
openssl verify -CAfile ca/ca.crt my-service.crt
```

Ожидаемый вывод: `my-service.crt: OK`. Подпись сертификата соответствует открытому ключу из `ca.crt`.

Подробнее о диагностике: [утилиты и диагностика](./common_utilities.md).

### Установка корневого сертификата в системное хранилище

Чтобы браузеры и утилиты (curl, wget) доверяли выпущенным сертификатам, корневой сертификат `ca/ca.crt` нужно установить в доверенное хранилище клиентских машин.

**Debian/Ubuntu:**

```bash
sudo cp ca/ca.crt /usr/local/share/ca-certificates/my-private-ca.crt
sudo update-ca-certificates
```

**RHEL/CentOS/Fedora:**

```bash
sudo cp ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

> **Примечание о браузерах:** Chrome, Edge, Opera используют системное хранилище. Firefox по умолчанию использует собственное хранилище — для него может потребоваться ручной импорт `ca.crt` через настройки безопасности.

### Отзыв скомпрометированного сертификата

Доступен только при **формальном методе**. Если приватный ключ сертификата скомпрометирован или сертификат больше не нужен — его необходимо отозвать.

#### Шаг 1: Отзыв сертификата

```bash
cd ca

openssl ca -config openssl.cnf -revoke ../my-service.crt

cd ..
```

В `db/index.txt` статус изменится с `V` (valid) на `R` (revoked).

#### Шаг 2: Генерация CRL

```bash
cd ca

openssl ca -config openssl.cnf -gencrl -out crl.pem

cd ..
```

Файл `ca/crl.pem` содержит серийный номер отозванного сертификата. Веб-серверы настраиваются на проверку этого списка. Подробности механизма CRL/OCSP — в [обзоре PKI](../../../Concepts/pki_overview.md#механизмы-отзыва-сертификатов).

## Дополнительная информация

### Сравнение с двухуровневой архитектурой

| Операция | Одноуровневый CA | Двухуровневый CA |
| :--- | :--- | :--- |
| Подпись CSR | `ca/openssl.cnf` | `intermediate-ca/openssl.cnf` |
| Проверка цепочки | `-CAfile ca/ca.crt` | `-CAfile intermediate-ca/ca-chain.crt` |
| Установка в систему | `ca/ca.crt` | `root-ca/ca.crt` |
| Отзыв | `ca/` | `intermediate-ca/` |

Аналогичные операции для двухуровневой архитектуры описаны в [управлении сертификатами (двухуровневый)](../two_tier/service_certificate_management.md). Введение в одноуровневый CA — в [обзоре](./overview.md), настройка CA — в [ca_setup.md](./ca_setup.md), утилиты диагностики — в [common_utilities.md](./common_utilities.md). Упрощённый выпуск без базы данных — [быстрый метод](./quick_method.md). Теория PKI, CRL и OCSP — в [обзоре PKI](../../../Concepts/pki_overview.md).
