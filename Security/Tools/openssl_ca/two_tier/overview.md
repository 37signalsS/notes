# Обзор двухуровневого центра сертификации (CA) на OpenSSL

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты для подтверждения подлинности открытых ключей.

**Двухуровневый CA** — стандартная архитектура PKI для производственных сред, состоящая из корневого узла (Root) и одного или нескольких подчиненных (Intermediate) узлов. Эта схема обеспечивает максимальную защиту наиболее критичного «якоря доверия» при сохранении операционной гибкости.

**Root CA (Корневой CA)** и **Intermediate CA (Промежуточный CA)** — ключевые элементы иерархии. Их определения, а также понятия **Цепочки доверия (Chain of Trust)**, **CSR (Certificate Signing Request)** и механизмов отзыва (**CRL**, **OCSP**) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**.

**OpenSSL 3.0+** — современная версия криптографического тулсета, в которой реализована модульная архитектура провайдеров (Default, Legacy, FIPS) и депрецированы устаревшие параметры (например, `RANDFILE`).

**mTLS (Mutual TLS)** — механизм взаимной аутентификации, требующий наличия сертификатов как у сервера, так и у клиента. В двухуровневой схеме mTLS реализуется через промежуточные CA.

## Базовые концепции

### Архитектура двухуровневого CA (2-Tier)

Рекомендованная схема для производственных сред (2026+) предполагает жесткое разделение обязанностей и криптографическую изоляцию уровней:

```
Root CA (самоподписанный, ОФЛАЙН, срок 10–20 лет, RSA-4096 или ECDSA P-384)
    └── Intermediate CA (подписан Root CA, ОНЛАЙН, срок 3–5 лет, ECDSA P-384/Ed25519)
            ├── Сертификаты сервисов (TLS Server Auth)
            └── Сертификаты пользователей/клиентов (TLS Client Auth)
```

**Изоляция Root CA (Air-Gapping):**
Приватный ключ корневого узла (`ca.key`) является наиболее ценным активом. После выпуска промежуточного CA он должен храниться на физически отсоединенном носителе (air-gapped) или в аппаратном модуле **HSM (Hardware Security Module)**. Доступ к нему осуществляется только для выпуска новых Intermediate CA или ротации всей PKI.

**Операционный уровень (Intermediate):**
Все повседневные запросы обрабатываются промежуточным CA. В 2026 году стандартом является интеграция Intermediate CA с системами управления секретами, такими как **HashiCorp Vault**, что позволяет автоматизировать выпуск сертификатов без прямого доступа человека к приватному ключу.

### Сравнение с одноуровневым CA

| Критерий | Одноуровневый CA | Двухуровневый CA |
| :--- | :--- | :--- |
| **Безопасность** | Низкая — корень всегда «горячий» (онлайн) | Высокая — Root CA полностью изолирован |
| **Сложность** | Минимальная | Средняя — требует двух конфигов и цепочек |
| **Риск компрометации** | Полная перенастройка всей инфраструктуры | Локализован уровнем Intermediate (отзыв узла) |
| **Производительность** | Высокая (короткая цепочка) | Чуть ниже (проверка цепочки до корня) |
| **Применение** | Dev, POC, локальные тесты | Production, Enterprise, мТLS в локальных сетях |

Подробности об упрощенном подходе см. в **[обзоре одноуровневого CA](../single_tier/overview.md)**.

### Компоненты и структура

Для корректной работы требуется разделение конфигураций и баз данных для каждого уровня.

**Файл ca-chain.crt (Bundle):**
Критически важный компонент, объединяющий сертификат промежуточного CA и корневой сертификат. TLS-серверы обязаны отдавать полную цепочку клиентам, так как клиенты (браузеры, ОС) доверяют только Root CA и не знают о промежуточном звене.

**Ключевые расширения X.509 (OpenSSL 3.x):**
- **`pathlen:0`** — устанавливается в Intermediate CA, запрещая ему создавать подчиненные CA (предотвращает неконтролируемое разрастание иерархии).
- **`basicConstraints = critical, CA:true`** — обязательный атрибут для всех уровней CA.
- **`subjectAltName (SAN)`** — единственный валидный способ указания доменов в 2026 году.

### Алгоритмы и стойкость (2026)

В двухуровневой схеме для разных уровней допустимы разные алгоритмы в зависимости от совместимости и производительности:

- **Root CA:** RSA-4096 (максимальная совместимость) или ECDSA P-384 (современный стандарт). Срок действия — 10–20 лет.
- **Intermediate CA:** ECDSA P-384 или Ed25519. Срок действия — 3–5 лет.
- **Конечные сертификаты:** ECDSA P-256/P-384 или Ed25519 для внутренних сервисов.

### Хранилище ключей и доступ

- **Root CA:** хранение на air-gapped хосте или в HSM/TPM. Парольная фраза (passphrase) для `ca.key` обязательна и хранится отдельно от ключа.
- **Intermediate CA:** хранение в защищенном сегменте сети (no public access), с ограничением доступа к файлу `intermediate.key` только через выделенного пользователя (например, `ca`).

### Энтропия и генерация ключей

При генерации ключей на серверах без аппаратного RNG (например, виртуальных машинах) может не хватать энтропии. Для OpenSSL 3.x используйте провайдеры и указание устройства:

```bash
# Проверка доступного энтропийного пула (Linux)
cat /proc/sys/kernel/random/entropy_avail

# При нехватке энтропии используйте haveged или rng-tools
# Debian/Ubuntu
sudo apt-get install haveged
sudo systemctl enable --now haveged
```

## Предварительные требования

### Железо и ОС

- **Root CA:** выделенный air-gapped хост (физический ноутбук/сервер без сетевых интерфейсов или с отключенными) или HSM с поддержкой PKCS#11/KMIP. Операционная система загружается с Read-Only носителя (Live USB) для предотвращения компрометации после использования.
- **Intermediate CA:** выделенный сервер (bare-metal или ВМ) в защищенном сегменте сети, без выхода в интернет. Минимум 2 CPU, 4 GB RAM, 20 GB SSD.
- **Клиенты/серверы:** любая ОС с OpenSSL 3.0+ и возможностью обновления доверенного хранилища.

### Программное обеспечение

- **OpenSSL 3.0+** с включенными провайдерами Default и FIPS (при необходимости).
- **HSM firmware/software** (если используется аппаратный модуль): PKCS#11 библиотека от производителя.
- **Система резервного копирования** для носителей с ключами (зашифрованные бэкапы).
- **Аудит:** доступ к системному журналированию (`journalctl` или `/var/log/syslog`).

### Требования к оператору

- Парольная фраза Root CA должна быть разделена по схеме Shamir (минимум 2 из 3) между доверенными администраторами.
- Учетные записи с доступом к Intermediate CA должны быть защищены MFA.
- Журнал операций (`index.txt`) должен периодически реплицироваться на SIEM-сервер.

## Практические сценарии

### Порядок развёртывания инфраструктуры

Создание полноценной PKI выполняется строго последовательно:

1. **[Создание Root CA](./root_ca_setup.md)** — подготовка конфигурации, самоподпись корня и уход в офлайн.
2. **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — генерация CSR промежуточного узла и подпись его корневым ключом.
3. **[Управление сертификатами сервисов](./service_certificate_management.md)** — операционная работа: выпуск, ротация и отзыв.
4. **[Утилиты и диагностика](./common_utilities.md)** — верификация цепочек доверия и отладка TLS.

### Высокоуровневая последовательность команд (обзор)

На этапе планирования полезно видеть полную картину операций:

```bash
# ====== Root CA (air-gapped) ======
mkdir -p root-ca/{db,newcerts,crl}
touch root-ca/db/index.txt
echo "1000" > root-ca/db/serial
echo "1000" > root-ca/db/crlnumber

# Генерация Root CA (ECDSA P-384)
openssl req -new -x509 -config root-ca/openssl.cnf \
    -newkey ec:<(openssl ecparam -name secp384r1) -sha512 \
    -keyout root-ca/ca.key -out root-ca/ca.crt -days 7300

# Подпись Intermediate CA (внесение CSR с air-gapped машины)
openssl ca -config root-ca/openssl.cnf \
    -extensions v3_intermediate_ca \
    -days 3650 -notext -md sha512 \
    -in intermediate-ca/csr/intermediate.csr \
    -out intermediate-ca/intermediate.crt

# ====== Intermediate CA (online) ======
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber

# Формирование Bundle
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt

# Верификация
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
# → intermediate.crt: OK
```

### Сценарии использования

- **Внутренние API и веб-сервисы:** аутентификация серверов и клиентов внутри локальной сети.
- **VPN (OpenVPN/WireGuard):** аутентификация удаленных пользователей и узлов.
- **Управление конфигурациями (Ansible, SaltStack):** подпись артефактов и аутентификация агентов.
- **Почтовые системы:** подпись и шифрование почты через S/MIME.
- **Аутентификация в K8s:** замена стандартного CA кластера на корпоративный Intermediate CA для повышения безопасности.

### Интеграция с системами управления секретами

Для production-сред рекомендуется использование **HashiCorp Vault** (PKI Secrets Engine) или **step-ca** в качестве замены прямого доступа к утилите `openssl ca`:

- **Vault PKI:** динамическая выдача сертификатов с TTL от 1 часа до 24 часов, автоматическая ротация, хранение ключа в HSM.
- **step-ca:** легковесное решение с поддержкой ACME и SSH-сертификатов для гибридных сред.

## Верификация на архитектурном уровне

После развертывания CA необходимо проверить целостность всей иерархии:

```bash
# 1. Верификация самоподписанного корня (должен доверять сам себе)
openssl verify -CAfile root-ca/ca.crt root-ca/ca.crt
# → ca.crt: OK

# 2. Верификация Intermediate относительно корня
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
# → intermediate.crt: OK

# 3. Верификация тестового сервисного сертификата через Bundle
openssl verify -CAfile intermediate-ca/ca-chain.crt my-service.crt
# → my-service.crt: OK

# 4. Проверка соответствия ключа и сертификата (ECDSA/Ed25519)
openssl pkey -in my-service.key -pubout -outform DER | openssl sha256
openssl x509 -in my-service.crt -pubkey -noout -outform DER | openssl sha256
# Хеши должны совпадать

# 5. Проверка расширений (pathlen, basicConstraints)
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 3 "Basic Constraints"
# → basicConstraints = critical, CA:true, pathlen:0
```

## Типичные ошибки проектирования

1. **Хранение `ca.key` на промежуточном узле или в репозитории** — корневой ключ должен быть только на air-gapped хосте или в HSM. Исправление: вынести ключ, отозвать и перевыпустить Intermediate CA.
2. **Отсутствие `pathlen:0` в Intermediate CA** — позволяет создавать бесконтрольную иерархию подчиненных CA. Исправление: перевыпуск Intermediate CA с правильными расширениями.
3. **Использование CN вместо SAN** — современные браузеры и сервисы отклоняют сертификаты без SAN. Исправление: перевыпуск с корректным `subjectAltName`.
4. **Сервер отдает только сертификат без Bundle** — клиент не может построить цепочку. Исправление: настроить TLS-сервер на отдачу `fullchain.pem` (или `ca-chain.crt` + сертификат).
5. **Использование устаревших алгоритмов (SHA-1, RSA-1024)** — снижает стойкость всей инфраструктуры. Исправление: переход на SHA-256/512 и RSA-3072/4096 или ECDSA P-384.
6. **Отсутствие CRL или OCSP** — при компрометации сертификата клиенты не смогут проверить его отзыв. Исправление: настроить CRL Distribution Points и/или OCSP responder.
7. **Недостаточная защита Intermediate CA** — доступ к ключу через insecure-канал или хранение в unprotected директории. Исправление: изоляция сети, права `600`, HSM/Vault.
8. **Отсутствие резервного копирования ключей** — потеря `ca.key` равносильна компрометации. Исправление: зашифрованные копии на независимых носителях.

## Ограничения и крайние случаи

- **Число сертификатов:** для сред с более чем 1000 конечными узлами рекомендуется создание нескольких Intermediate CA с разными политиками для распределения нагрузки.
- **Ротация Intermediate CA:** требует повторного подписания корневым CA и обновления `ca-chain.crt` на всех серверах. Планируйте окно обслуживания.
- **Совместимость с legacy-системами:** некоторые старые Java-приложения (до Java 8) и hardware appliances требуют RSA-ключей и специфических расширений (Key Usage без `keyAgreement`).
- **Регуляторные требования:** в финансовой и медицинской отраслях может требоваться использование сертифицированных средств криптозащиты (СКЗИ) с поддержкой ГОСТ (см. [ГОСТ-криптография](../../../Security/Tools/gost_cryptography.md)).
- **Ограничение `pathlen`:** после установки `pathlen:0` в Intermediate CA невозможно создать подчиненный CA без перевыпуска Intermediate.
- **Энтропия в виртуальных средах:** генерация ключей на ВМ без аппаратного RNG может блокироваться. Используйте `haveged` или подключение к `/dev/random` через virtio-rng.

## Несколько Intermediate CA — масштабирование и сегментация

Для инфраструктур с более чем 1000 конечными сертификатами или необходимостью сегментации рекомендуется создание нескольких Intermediate CA.

### Когда нужно несколько Intermediate CA

| Сценарий | Причина |
| :--- | :--- |
| >1000 нод | Распределение нагрузки, ускорение CRL/OCSP |
| Разные среды (Dev/QA/Prod) | Изоляция: компрометация Dev не влияет на Prod |
| Разные команды/бизнес-единицы | Автономное управление, делегирование подписи |
| Разные алгоритмы | Legacy (RSA) + Modern (ECDSA) на разных Intermediate |
| Регуляторные требования | Разные compliance-требования для разных сегментов |

### Архитектура с несколькими Intermediate CA

```text
                    ┌──────────────┐
                    │   Root CA    │
                    │  (offline)   │
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼───────┐ ┌──────▼───────┐ ┌──────▼───────┐
   │ Intermediate │ │ Intermediate │ │ Intermediate │
   │  CA (Prod)   │ │  CA (Dev)    │ │  CA (Legacy) │
   │  ECDSA P-384 │ │  ECDSA P-256 │ │  RSA-4096    │
   │  pathlen:0   │ │  pathlen:0   │ │  pathlen:0   │
   └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
          │                │                │
   ┌──────┼──────┐         │                │
   │      │      │         │                │
 Сервисы  API  DB       Dev-сервисы      Legacy-системы
```

### openssl.cnf для Root CA с несколькими Intermediate

```ini
# В секции [policy_loose] — гибкая политика для всех Intermediate
[policy_loose]
countryName            = optional
stateOrProvinceName    = optional
organizationName       = optional
organizationalUnitName = optional
commonName             = supplied
emailAddress           = optional

# Расширения для Prod Intermediate
[v3_intermediate_prod]
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always, issuer
crlDistributionPoints = URI:http://crl-prod.internal/ca-prod.crl

# Расширения для Dev Intermediate
[v3_intermediate_dev]
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always, issuer

# Расширения для Legacy Intermediate
[v3_intermediate_legacy]
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always, issuer
```

### Порядок действий

```bash
# 1. Генерация ключей для каждого Intermediate
openssl genpkey -algorithm ec -pkeyopt ec_paramgen_curve:P-384 \
  -out intermediate-prod.key
openssl genpkey -algorithm ec -pkeyopt ec_paramgen_curve:P-256 \
  -out intermediate-dev.key
openssl genpkey -algorithm rsa -pkeyopt rsa_keygen_bits:4096 \
  -out intermediate-legacy.key

# 2. Создание CSR для каждого Intermediate
openssl req -new -key intermediate-prod.key \
  -subj "/C=RU/O=MyOrg/OU=Production/CN=Intermediate CA - Prod" \
  -out intermediate-prod.csr

# 3. Подпись каждого Intermediate разными расширениями
openssl ca -config openssl.cnf \
  -extensions v3_intermediate_prod \
  -in intermediate-prod.csr \
  -out intermediate-prod.crt \
  -days 1825

openssl ca -config openssl.cnf \
  -extensions v3_intermediate_dev \
  -in intermediate-dev.csr \
  -out intermediate-dev.crt \
  -days 1825

# 4. Формирование Bundle для каждого Intermediate
cat intermediate-prod.crt root.crt > bundle-prod.crt
cat intermediate-dev.crt root.crt > bundle-dev.crt
cat intermediate-legacy.crt root.crt > bundle-legacy.crt

# 5. Верификация
openssl verify -CAfile root.crt -untrusted intermediate-prod.crt leaf-prod.crt
# → leaf-prod.crt: OK
```

### Управление несколькими Intermediate

| Аспект | Рекомендация |
| :--- | :--- |
| Именование | `<org>-<env>-<algo>-ca.crt` (напр., `myorg-prod-ecdsa-ca.crt`) |
| Директории | Отдельная директория для каждого Intermediate |
| CRL | Отдельный CRL-файл для каждого Intermediate |
| OCSP | Один OCSP-резолвер может обслуживать все Intermediate |
| Мониторинг | Отдельные алерты на срок жизни каждого Intermediate |
| Backup | Отдельный backup для каждого ключа Intermediate CA |

### Пример структуры директорий

```
/opt/ca/
├── root/
│   ├── root.key
│   ├── root.crt
│   └── openssl.cnf
├── intermediate-prod/
│   ├── intermediate.key
│   ├── intermediate.crt
│   ├── ca-chain.crt
│   ├── db/
│   │   ├── index.txt
│   │   └── serial
│   └── openssl.cnf
├── intermediate-dev/
│   ├── intermediate.key
│   ├── intermediate.crt
│   ├── ca-chain.crt
│   ├── db/
│   └── openssl.cnf
└── intermediate-legacy/
    ├── intermediate.key
    ├── intermediate.crt
    ├── ca-chain.crt
    ├── db/
    └── openssl.cnf
```

## Жизненный цикл эксплуатации

### 1. Развертывание и инициализация

- Подготовка air-gapped хоста для Root CA.
- Генерация ключа и самоподписанного сертификата с расширением `CA:true`.
- Выпуск Intermediate CA и формирование `ca-chain.crt`.
- Установка корневого сертификата во все доверенные хранилища целевых ОС.

### 2. Эксплуатация

- Прием CSR от сервисов через защищенный канал (SCP, VPN, Jump-host).
- Проверка SAN и политик перед подписью.
- Ведение журнала выпусков в `intermediate-ca/db/index.txt` и аудит через SIEM.
- Плановая ротация сертификатов за 10–20% до истечения срока.
- Генерация CRL каждые 24–48 часов или при каждом отзыве.

### 3. Ротация и обновление

- **Ротация Intermediate CA:** каждые 3–5 лет. Требует повторного подписания корневым CA и обновления Bundle.
- **Ротация корневого CA:** каждые 10–20 лет. Требует полной перевыпуск всей цепочки.
- **Аварийная ротация:** при потере или компрометации ключа Intermediate CA — выпуск нового Intermediate, отзыв старого, обновление клиентов.

### 4. Аварийное реагирование

- Отзыв скомпрометированных сертификатов через `openssl ca -revoke`.
- Генерация и распространение обновленного CRL.
- При компрометации Intermediate ключа — выпуск нового Intermediate, распространение нового Bundle.
- При компрометации корневого ключа — полная перевыпуск инфраструктуры.

### 5. Деактивация и архивация

- Удаление корневого и промежуточных сертификатов из доверенных хранилищ всех клиентов.
- Архивирование или безопасное уничтожение ключей в соответствии с политикой данных организации.
- Сохранение `index.txt` и `serial` для аудита.

## Очистка и откат изменений

### Удаление CA и всех сертификатов

```bash
# Полное удаление директории Intermediate CA (необратимо!)
rm -rf intermediate-ca/

# Удаление установленных корневых сертификатов из доверенных хранилищ ОС
# Debian/Ubuntu
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo update-ca-trust

# Windows Server
certutil -delstore "Root" "CN=My Private Root CA"
```

### Отзыв всех сертификатов (экстренный сценарий)

```bash
cd intermediate-ca

# Отзыв всех сертификатов через скрипт (аккуратно!)
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done

# Генерация нового CRL
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

# Распространение нового CRL на все сервисы
```

### Очистка тестовой среды

```bash
# Удаление тестовых сертификатов и ключей
rm -f my-service.crt my-service.key my-service.csr

# Очистка кэша OpenSSL
rm -rf ~/.openssl/
```

## Аварийное восстановление (Disaster Recovery)

### Сценарий 1: Потеря Intermediate CA

1. Подготовить новую машину для Intermediate CA.
2. Скопировать `root-ca/ca.crt` и `root-ca/ca.key` с air-gapped хоста (или использовать HSM).
3. Выпустить новый Intermediate CA и новый Bundle.
4. Отозвать старый Intermediate CA через корневой ключ.
5. Обновить `ca-chain.crt` на всех серверах.

### Сценарий 2: Потеря Root CA

1. Восстановить `ca.key` и `ca.crt` из зашифрованного бэкапа.
2. Если восстановление невозможно — требуется полная перевыпуск всей PKI.
3. Выпустить новый Root CA и новый Intermediate CA.
4. Отозвать все старые сертификаты.
5. Распространить новый Root CA через все доверенные хранилища.

### Сценарий 3: Компрометация ключа

1. Немедленно отозвать скомпрометированный сертификат.
2. Сгенерировать новый CRL и обеспечить его доступность.
3. Выпустить новый ключ и сертификат.
4. Обновить все сервисы, использующие старый сертификат.

## Мониторинг и оповещение

### Проверка срока действия удаленных сертификатов

```bash
#!/usr/bin/env bash
HOST="$1"
PORT="${2:-443}"
DAYS_WARN="${3:-30}"

EXP_DATE=$(echo | openssl s_client -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null \
  | cut -d= -f2)

if [ -z "$EXP_DATE" ]; then
  echo "FAIL: $HOST не отвечает или не предоставляет сертификат"
  exit 1
fi

EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
            date -d "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 0 ]; then
  echo "CRITICAL: $HOST сертификат истёк $(( -DAYS_LEFT )) дней назад"
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: $HOST сертификат истекает через $DAYS_LEFT дней"
else
  echo "OK: $HOST сертификат действителен ещё $DAYS_LEFT дней"
fi
```

### Мониторинг истечения корневого и промежуточного CA

```bash
#!/usr/bin/env bash
# Проверка срока действия Root и Intermediate CA
for crt in root-ca/ca.crt intermediate-ca/intermediate.crt; do
    EXP_DATE=$(openssl x509 -in "$crt" -noout -enddate | cut -d= -f2)
    EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
                date -d "$EXP_DATE" +%s)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))
    echo "$crt: $DAYS_LEFT дней осталось"
done
```

### Интеграция с Prometheus Blackbox Exporter

Базовый модуль для проверки TLS и алерты подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Для мониторинга истечения именно корневого и промежуточного CA используйте локальные скрипты (см. выше) или blackbox exporter с указанием `server_name`, соответствующего внутреннему домену.

## Best Practices

- **Приватные ключи всегда offline:** Root CA ключ никогда не должен находиться на машине с сетевым доступом. Intermediate CA ключ — только в защищенном сегменте.
- **HSM/TPM для корневых ключей:** использование аппаратных модулей исключает возможность извлечения ключа.
- **Права доступа:** `ca.key` и `intermediate.key` должны иметь права `600` и принадлежать выделенному пользователю (например, `ca`).
- **Резервное копирование:** зашифрованные копии ключей хранятся отдельно от сертификатов, с использованием отдельного пароля или шифрования GPG.
- **Аудит:** ведение журнала всех операций подписи через `index.txt` и отправка событий в SIEM.
- **Ротация по расписанию:** ротация Intermediate CA каждые 3–5 лет, конечных сертификатов — по мере приближения срока действия.
- **CRL Distribution Points:** всегда указывайте доступные URL для CRL в расширениях сертификата.
- **Тестовый выпуск:** перед использованием в production выпускайте тестовый сертификат и проверяйте его через `openssl verify`.
- **Документация:** поддерживайте актуальную схему инфраструктуры и список ответственных администраторов.

## Дополнительная информация

### Карта документации двухуровневого CA

| Документ | Содержание |
| :--- | :--- |
| [root_ca_setup.md](./root_ca_setup.md) | Настройка корневого узла, конфигурация и безопасность офлайн-ключа. |
| [intermediate_ca_setup.md](./intermediate_ca_setup.md) | Создание промежуточного узла, работа с `ca-chain.crt` и HSM. |
| [service_certificate_management.md](./service_certificate_management.md) | Жизненный цикл сервисных сертификатов: выпуск, SAN, отзыв. |
| [common_utilities.md](./common_utilities.md) | Диагностика цепочек доверия, извлечение метаданных, отладка TLS. |
| [troubleshooting_flowchart.md](./troubleshooting_flowchart.md) | Алгоритм диагностики проблем с сертификатами (decision-tree). |
| [siem_integration.md](./siem_integration.md) | Интеграция логов CA с SIEM: аудит, syslog, auditd, алертинг. |
| [ocsp_responder.md](../ocsp_responder.md) | Настройка OCSP-резолвера для проверки статуса сертификатов в реальном времени. |
| [crl_distribution_points.md](../crl_distribution_points.md) | Настройка HTTP-сервера для распространения CRL. |

### Связанные темы

#### PKI и сертификаты

- **[Обзор PKI](../../../Concepts/pki_overview.md)** — фундаментальная теория инфраструктуры открытых ключей, алгоритмы 2026, PQC, расширения X.509.
- **[Обзор одноуровневого CA](../single_tier/overview.md)** — архитектурные отличия и сценарии для разработки.
- **[Диагностика SSL-сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — методы поиска ошибок в цепочках доверия.
- **[Certificate Pinning](../../../Concepts/certificate_pinning.md)** — привязка клиентов к сертификатам/ключам, защита от MITM.
- **[Certificate Transparency](../../../Concepts/certificate_transparency.md)** — публичное логирование сертификатов, CT-мониторинг.
- **[Key Escrow Policy](../../../Concepts/key_escrow_policy.md)** — политика хранения копий ключей, Shamir's Secret Sharing.
- **[ГОСТ-криптография](../../../Security/Tools/gost_cryptography.md)** — реализация ГОСТ-алгоритмов в OpenSSL, CryptoPro, Кузнечик.

#### TLS-конфигурация и харденинг

- **[TLS-протокол](../../../Networking/Protocols/tls.md)** — теория TLS, cipher suites, AEAD, forward secrecy, handshake.
- **[Nginx: глобальные параметры TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)** — шифры, протоколы, HSTS, сессии.
- **[Nginx: диагностика TLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — отладка TLS-handshake.
- **[Nginx: mTLS](../../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)** — взаимная аутентификация в Nginx.
- **[Оптимизация TLS](../../../WebServers/Concepts/web_performance/tls_optimization.md)** — бенчмарки, AES-GCM vs ChaCha20, 0-RTT, session tickets.

#### Автоматизация и управление сертификатами

- **[Ansible: автоматизация сертификатов](../../../../Ansible/ansible_certificate_management.md)** — плейбуки выпуска, ротации и распространения.
- **[cert-manager (Kubernetes)](../../../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)** — CRDs, Issuer/ClusterIssuer, ACME.
- **[Let's Encrypt + certbot](../../../../WebServers/Concepts/https_with_certbot.md)** — автоматический выпуск публичных сертификатов.
- **[acme.sh](../../../../WebServers/Concepts/acme_sh.md)** — lightweight ACME-клиент.

#### Секреты и HSM

- **[HashiCorp Vault](../../../../Vault/overview.md)** — PKI Secrets Engine, SSH CA, управление секретами.
- **[Vault PKI + cert-manager](../../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/vault_integration.md)** — интеграция Vault с Kubernetes.
- **[Step-CA](../../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/step_ca_integration.md)** — легковесный внутренний CA с ACME.

#### Мониторинг

- **[Blackbox Exporter](../../../../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — мониторинг TLS и сертификатов через Prometheus.
- **[Blackbox Exporter: метрики и алертинг](../../../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md)** — `probe_ssl_earliest_cert_expiry`, alerting rules.

#### Service Mesh и mTLS

- **[Istio: безопасность](../../../../Service_Mesh/istio-security-policies.md)** — SPIFFE, PeerAuthentication, AuthorizationPolicy.
- **[TLS/mTLS в Kubernetes](../../../../Kubernetes/Security/tls_and_mtls_in_kubernetes.md)** — CA-модель, CSR workflow, Kubelet TLS bootstrap.
- **[mkcert](../../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/scenarios.md)** — локальный CA для dev-окружений.

#### SSH-сертификаты

- **[SSH-сертификаты](../../../../Linux/Security/ssh/server/ssh_certificate_authentication.md)** — SSH CA, жизненный цикл, Vault SSH CA.
- **[SSH-сертификаты в CI/CD](../../../../Linux/Security/ssh/ssh_cicd_integration.md)** — ephemeral-сертификаты для пайплайнов.
