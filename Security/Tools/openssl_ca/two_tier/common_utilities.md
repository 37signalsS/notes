# Утилиты и диагностика двухуровневого CA

## Определения

Базовые понятия PKI (Public Key Infrastructure, Инфраструктура открытых ключей), такие как **CSR (Certificate Signing Request)**, **CRL (Certificate Revocation List)** и **Цепочка доверия (Chain of Trust)**, подробно описаны в **[обзоре PKI](../../../../Concepts/pki_overview.md)**.

**OpenSSL 3.0+** — актуальная версия инструментария с поддержкой провайдеров и улучшенной безопасностью. В двухуровневых схемах OpenSSL 3.x требует строгого соблюдения иерархии при верификации.

**ca-chain.crt (Bundle)** — PEM-файл, содержащий сертификат Intermediate CA и Root CA. Необходим для корректной верификации цепочки `сервис → Intermediate → Root`.

## Базовые концепции

### Категории диагностических команд

Все команды OpenSSL для работы с сертификатами разделяются на:

- **Просмотр** — извлечение метаданных (команды `x509`, `req`, `crl`).
- **Верификация** — проверка криптографического соответствия и подписей (команды `verify`, `-modulus`, `pubkey`).
- **Подключение** — имитация клиента для тестирования TLS-конфигураций (команда `s_client`).

### Контекст двухуровневого CA

Ключевое отличие от **[одноуровневого CA](../../single_tier/common_utilities.md)** заключается в необходимости использования полной цепочки `ca-chain.crt`.

| Операция | Одноуровневый CA | Двухуровневый CA |
|:---|:---|:---|
| Доверенный корень | `ca.crt` | `ca-chain.crt` (Intermediate + Root) |
| Верификация сервиса | `-CAfile ca.crt` | `-CAfile ca-chain.crt` |
| Путь к CRL | `ca/crl.pem` | `intermediate-ca/db/crl.pem` |
| Проверка SNI | Рекомендуется | **Обязательна** (для TLS 1.3) |

## Практические сценарии

### Просмотр содержимого сертификата

```bash
openssl x509 -in my-service.crt -noout -text
```

Обратите внимание на поле `Authority Key Identifier (AKI)` — оно должно совпадать с `Subject Key Identifier (SKI)` промежуточного CA.

### Просмотр содержимого запроса CSR

```bash
openssl req -in my-service.csr -noout -text
```

Используется для проверки расширений SAN и корректности DN перед отправкой запроса на подпись в Intermediate CA.

### Проверка соответствия ключа и сертификата

Для предотвращения ошибок при запуске TLS-серверов необходимо убедиться, что файлы составляют рабочую пару.

#### Сценарий А: RSA-ключи
Сравниваются хеши модулей.

```bash
openssl rsa -noout -modulus -in service.key | openssl sha256
openssl x509 -noout -modulus -in service.crt | openssl sha256
```

#### Сценарий Б: ECDSA/Ed25519 (2026)
Сравниваются хеши публичных ключей (DER-формат).

```bash
# Извлечение из приватного ключа
openssl pkey -in service.key -pubout -outform DER | openssl sha256
# Извлечение из сертификата
openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
```

### Просмотр списка отозванных сертификатов CRL

```bash
openssl crl -in intermediate-ca/db/crl.pem -noout -text
```

В двухуровневой схеме вы всегда проверяете CRL, выпущенный **промежуточным** CA, так как именно он подписывал конечные сертификаты.

### Диагностика TLS-сервера (s_client)

```bash
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null
```

**Анализ вывода:**
- `Verification: OK` — цепочка доверена.
- `Verification error: unable to get local issuer certificate` — сервер не отдает промежуточный сертификат (нужно использовать `fullchain.crt`).

### Верификация цепочки доверия

Проверка конечного сертификата относительно полной цепочки CA:

```bash
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
```

Проверка самого промежуточного CA относительно корня:

```bash
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
```

## Дополнительная информация

### Связанные темы

- **[Управление сертификатами сервисов](./service_certificate_management.md)** — жизненный цикл и отзыв.
- **[Диагностика SSL/TLS сертификатов](../../ssl_certificate_diagnostics.md)** — решение проблем с цепочками.
- **[Обзор PKI](../../../../Concepts/pki_overview.md)** — теория и стандарты.
- **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — формирование файла `ca-chain.crt`.
