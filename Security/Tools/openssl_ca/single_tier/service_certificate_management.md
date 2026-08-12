# Управление сертификатами сервисов в одноуровневом CA

## Определения

Базовые понятия PKI (Public Key Infrastructure, Инфраструктура открытых ключей), такие как **CSR (Certificate Signing Request, Запрос на подпись сертификата)**, **SAN (Subject Alternative Name, Альтернативное имя субъекта)** и **CRL (Certificate Revocation List, Список отзыва сертификатов)**, подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**.

В контексте управления сервисами:

- **DN (Distinguished Name, Отличительное имя)** — уникальная строка идентификации субъекта (например, `/C=RU/ST=Moscow/O=Org/CN=server.local`).
- **mTLS (Mutual TLS)** — механизм взаимной аутентификации, где сервис-клиент также обязан предъявить сертификат, подписанный доверенным CA.
- **Цепочка доверия (Chain of Trust)** — в одноуровневой схеме состоит из сертификата сервиса и корневого сертификата `ca.crt`.

## Базовые концепции

### Жизненный цикл сертификата сервиса

Процесс управления сертификатом по формальному методу включает следующие этапы:

1. **Генерация ключа и CSR:** выполняется локально на целевом сервере или в защищенном контуре.
2. **Передача запроса:** CSR отправляется администратору CA. Приватный ключ **никогда** не покидает сервер.
3. **Валидация и подпись:** администратор проверяет CSR, настраивает SAN (Subject Alternative Name) и подписывает запрос через `openssl ca`.
4. **Установка:** сертификат (`.crt`) и корень (`ca.crt`) устанавливаются в приложение/ОС.
5. **Ротация:** плановый перевыпуск до истечения срока действия (рекомендуется за 10–20% до конца срока).
6. **Отзыв:** немедленное аннулирование в базе CA при компрометации.

### Принципы безопасности

- **Минимальные привилегии:** доступ к приватному ключу сервиса должен иметь только пользователь, под которым запущен процесс (например, `www-data` или `nginx`).
- **Использование SAN:** современные системы (браузеры, Go-сервисы, браузеры с 2026 года) полностью игнорируют поле `Common Name (CN)`, если присутствует `Subject Alternative Name`. SAN является обязательным.
- **Алгоритмы 2026:** рекомендуется переход с RSA-4096 на **ECDSA (secp384r1)** для снижения нагрузки на CPU при TLS-handshake.

## Практические сценарии

### Выпуск сертификата (Key -> CSR -> CRT)

#### Шаг 1: Генерация на стороне сервиса

**Вариант А: Классический RSA (4096 бит)**
```bash
openssl genrsa -out service.key 4096
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service.local"
```

**Вариант Б: Современный ECDSA (P-384)**
```bash
openssl req -new -newkey ec:<(openssl ecparam -name secp384r1) -nodes \
    -keyout service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service.local"
```

#### Шаг 2: Подпись администратором CA

Администратор проверяет запрос и вносит DNS/IP в `ca/openssl.cnf` (секция `[alt_names]`):

```ini
[alt_names]
DNS.1 = service.local
DNS.2 = *.service.local
IP.1  = 10.0.0.50
```

Выполнение подписи:
```bash
cd ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_req -notext
```

### Установка корневого сертификата в доверенные хранилища

#### Операционные системы

**Linux (Debian/Ubuntu/Angie):**
```bash
sudo cp ca.crt /usr/local/share/ca-certificates/internal-ca.crt
sudo update-ca-certificates
```

**Linux (RHEL/CentOS/Fedora):**
```bash
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

#### Docker-контейнеры

При сборке образа добавьте сертификат в системное хранилище внутри Dockerfile:
```dockerfile
COPY ca.crt /usr/local/share/ca-certificates/internal-ca.crt
RUN update-ca-certificates
```

#### Java (KeyStore/TrustStore)

Java использует собственное хранилище `cacerts`. Для добавления корня:
```bash
keytool -import -alias internal-ca -file ca.crt \
    -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit -noprompt
```

### Отзыв и работа с CRL

Если ключ сервиса утерян, его нужно пометить как `Revoked` в базе CA и выпустить новый список отзыва.

```bash
cd ca

# 1. Отзыв (меняет статус в index.txt на 'R')
openssl ca -config openssl.cnf -revoke ../service.crt

# 2. Перегенерация CRL
openssl ca -config openssl.cnf -gencrl -out crl.pem
```

Для того чтобы отзыв работал, приложения должны быть настроены на проверку файла `crl.pem`. В Nginx это делается директивой `ssl_crl /etc/nginx/ssl/ca/crl.pem;`.

## Дополнительная информация

### Верификация перед деплоем

Всегда проверяйте валидность пары «ключ-сертификат» перед перезагрузкой сервиса:
```bash
# Проверка соответствия (хеши должны совпасть)
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256

# Проверка цепочки
openssl verify -CAfile ca.crt service.crt
```

### Связанные темы

- **[Обзор одноуровневого CA](./overview.md)** — архитектура и структура базы данных.
- **[Настройка CA и конфигурация openssl.cnf](./ca_setup.md)** — политики подписи и параметры `v3_req`.
- **[Утилиты и диагностика OpenSSL](./common_utilities.md)** — команды глубокой проверки сертификатов.
- **[Обзор PKI](../../../Concepts/pki_overview.md)** — теоретические основы иерархии доверия.
