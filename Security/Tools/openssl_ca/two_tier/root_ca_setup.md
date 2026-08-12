# Настройка Root CA

## Определения

**PKI (Public Key Infrastructure, Инфраструктура открытых ключей)** — совокупность технологий и политик для управления цифровыми сертификатами.

**Root CA (Корневой центр сертификации)** — вершина иерархии доверия. Самоподписанный сертификат с расширением `CA:true`, используемый исключительно для подписи промежуточных центров сертификации.

**Air-gapped система** — компьютер или среда, физически изолированная от любых сетей (Ethernet, Wi-Fi, Bluetooth). Применяется для защиты приватных ключей от удалённых атак.

**HSM (Hardware Security Module, Аппаратный модуль безопасности)** — специализированное устройство для генерации и безопасного хранения криптографических ключей, обеспечивающее защиту от физического и логического извлечения.

**OpenSSL 3.0+** — версия инструментария, в которой депрецирован параметр `RANDFILE` и внедрена система провайдеров.

> Базовые понятия (ключ, **CSR (Certificate Signing Request)**, X.509, цепочка доверия, CRL) подробно описаны в **[обзоре PKI](../../../../Concepts/pki_overview.md)**.

## Базовые концепции

### Назначение и безопасность

В двухуровневой архитектуре Root CA является наиболее критичным компонентом. Его единственная задача — выпуск и отзыв сертификатов Intermediate CA.

**Золотые правила безопасности Root CA:**
- **Офлайн-хранение:** приватный ключ должен находиться на air-gapped системе. Операционная система должна загружаться с Read-Only носителя (например, Live USB с отключенной записью).
- **Минимальный доступ:** ключ извлекается только для редких операций (выпуск нового промежуточного CA или генерация списка отзыва).
- **Физическая защита:** носители с ключами должны храниться в сейфах с ограниченным доступом.
- **Долговечность:** срок действия корня обычно составляет 20–25 лет (RSA-4096) или 15–20 лет (ECDSA P-384).

Сравнение одноуровневой и двухуровневой архитектур приведено в **[обзоре двухуровневого CA](./overview.md)**.

### Структура директорий

```text
root-ca/
├── openssl.cnf          # Конфигурация для Root-уровня
├── ca.key               # Приватный ключ Root CA
├── ca.crt               # Корневой сертификат
└── db/
    ├── index.txt        # База данных выданных Intermediate CA
    ├── serial           # Счётчик серийных номеров (hex)
    ├── newcerts/        # Архив выданных сертификатов
    └── crl/             # Списки отзыва (CRL)
```

## Практические сценарии

### 1. Подготовка конфигурации openssl.cnf

Файл настроек для Root CA должен быть максимально строгим.

```ini
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt
new_certs_dir   = $dir/db/newcerts
serial          = $dir/db/serial
certificate     = $dir/ca.crt
private_key     = $dir/ca.key
default_md      = sha512
default_days    = 3650
policy          = policy_strict

[ policy_strict ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied

[ req ]
default_bits        = 4096
distinguished_name  = req_distinguished_name
x509_extensions     = v3_ca
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
L  = Moscow
O  = My Private Corp
CN = My Private Root CA

# Расширения для самого Root CA
[ v3_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign

# Расширения для подписи Intermediate CA
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, digitalSignature, cRLSign, keyCertSign
```

### 2. Генерация корневого узла

#### Сценарий А: Классический RSA-4096 (Рекомендуется для корня)
```bash
openssl req -new -x509 -config openssl.cnf \
    -newkey rsa:4096 -sha512 \
    -keyout ca.key -out ca.crt -days 7300
```

#### Сценарий Б: Современный ECDSA P-384
```bash
openssl req -new -x509 -config openssl.cnf \
    -newkey ec:<(openssl ecparam -name secp384r1) -sha512 \
    -keyout ca.key -out ca.crt -days 7300
```

> **Важно:** Система запросит пароль (passphrase). Для Root CA пароль должен быть максимально сложным и храниться отдельно от ключа (например, разделен по схеме Шамира между несколькими доверенными лицами).

### 3. Подпись Intermediate CA

Операция выполняется при получении CSR от промежуточного узла:

```bash
openssl ca -config openssl.cnf \
    -extensions v3_intermediate_ca \
    -days 3650 -notext -md sha512 \
    -in intermediate.csr -out intermediate.crt
```

### 4. Вывод в офлайн и защита

1.  **Резервное копирование:** Сохраните `ca.key` и `ca.crt` на 2-3 USB-накопителях разных производителей.
2.  **Верификация:** Проверьте контрольную сумму ключа: `sha512sum ca.key`.
3.  **Уничтожение:** Если использовалась временная ОС, выполните `shred -u ca.key`.
4.  **Безопасное хранение:** Носители должны находиться в запечатанных конвертах в банковской ячейке или сейфе.

## Дополнительная информация

### Верификация результата

```bash
# Просмотр расширений (CA:TRUE и pathlen)
openssl x509 -in ca.crt -noout -text | grep -A 1 "Basic Constraints"

# Проверка подписи самого себя
openssl verify -CAfile ca.crt ca.crt
```

### Связанные темы

- **[Обзор двухуровневого CA](./overview.md)** — архитектура и сравнение.
- **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — следующий этап (онлайн-узел).
- **[Обзор PKI](../../../../Concepts/pki_overview.md)** — теоретическая база.
