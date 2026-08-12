# Управление сертификатами сервисов в двухуровневом CA

## Определения

**Сертификат сервиса (Service Certificate)** — цифровой документ стандарта X.509, используемый для идентификации узлов (веб-серверов, API, БД) и шифрования трафика. В двухуровневой иерархии подписывается исключительно **Intermediate CA**.

**CA (Certificate Authority)** — доверенная сторона в PKI. В данной модели корень (Root) изолирован, а промежуточный узел (Intermediate) является «выпускающим».

**OpenSSL 3.0+** — современная версия криптографического инструментария. В 2026 году рекомендуется использовать его архитектуру провайдеров для обеспечения соответствия стандартам безопасности.

**mTLS (Mutual TLS)** — стандарт безопасности, требующий наличия сертификатов у обеих сторон соединения.

> Базовые понятия (CSR, SAN, CRL, Цепочка доверия) подробно описаны в **[обзоре PKI](../../../../Concepts/pki_overview.md)**.

## Базовые концепции

### Принципы выпуска в двухуровневой модели

В отличие от одноуровневой схемы, **Root CA (Корневой CA)** полностью изолирован от процесса выдачи сертификатов сервисам. Эту роль выполняет **Intermediate CA (Промежуточный CA)**.

| Этап | Ответственный | Локация |
| :--- | :--- | :--- |
| Генерация ключа и CSR | Владелец сервиса | Целевой сервер / HSM |
| Валидация данных и SAN | Администратор Intermediate CA | Узел Intermediate CA |
| Подпись и выдача | Intermediate CA | Узел Intermediate CA |
| Установка и настройка | Владелец сервиса | Целевой сервер |

### Ключевые принципы безопасности

1. **Изоляция приватного ключа:** Ключ сервиса генерируется локально и **никогда** не передается администратору CA. Передается только публичный запрос (CSR).
2. **Обязательность SAN:** Поле `Common Name (CN)` считается устаревшим. Все современные системы (Go, Rust, браузеры 2026+) требуют наличия расширения `Subject Alternative Name`.
3. **Цепочка доверия (Bundle):** Сервер обязан отдавать клиенту «бандл», состоящий из собственного сертификата и сертификата Intermediate CA. Клиент доверяет корню (Root CA), который подписывал Intermediate.

## Практические сценарии

### 1. Генерация ключа и CSR на стороне сервиса

#### Вариант А: Классический RSA-4096
```bash
openssl genrsa -out service.key 4096
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

#### Вариант Б: Современный ECDSA P-384 (Рекомендуется)
```bash
openssl req -new -newkey ec:<(openssl ecparam -name secp384r1) -nodes \
    -keyout service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

### 2. Подпись и выдача сертификата

Администратор Intermediate CA проверяет CSR и вносит SAN в `openssl.cnf` (секция `[alt_names]`):

```ini
[alt_names]
DNS.1 = service.local
DNS.2 = *.service.local
IP.1  = 10.0.5.10
```

Выполнение подписи:
```bash
cd intermediate-ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_server_cert -notext
```

### 3. Установка доверия (Root CA)

Чтобы приложения доверяли иерархии, необходимо установить сертификат **Root CA** в системные хранилища.

#### Операционные системы
- **Debian/Ubuntu/Angie:** `sudo cp root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`
- **RHEL/CentOS/Fedora:** `sudo cp root.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust`

#### Docker и Java
- **Docker:** Используйте `COPY` и `RUN update-ca-certificates` в Dockerfile.
- **Java:** `keytool -import -alias root-ca -file root.crt -keystore $JAVA_HOME/lib/security/cacerts`

### 4. Верификация перед запуском

Всегда проверяйте соответствие ключа сертификату и целостность цепочки:

```bash
# Проверка пары (хеши должны совпасть)
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256

# Проверка цепочки доверия (через Bundle)
openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt
```

### 5. Отзыв скомпрометированного сертификата

```bash
cd intermediate-ca
openssl ca -config openssl.cnf -revoke ../service.crt
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem
```

## Дополнительная информация

### Автоматизация (2026)
Для масштабируемых систем рекомендуется интеграция с **HashiCorp Vault** (движок PKI) или **cert-manager** в Kubernetes, которые используют Intermediate CA для автоматической ротации.

### Связанные темы
- **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — подготовка выпускающего узла.
- **[Утилиты и диагностика](./common_utilities.md)** — команды проверки и TLS-тесты.
- **[Обзор двухуровневого CA](./overview.md)** — архитектурные принципы.
- **[Обзор PKI](../../../../Concepts/pki_overview.md)** — теория X.509 и отзывов.
