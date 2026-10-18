# Настройка промежуточного центра сертификации

## Определения

**CA (Certificate Authority, Центр сертификации)** — доверенная сущность, выпускающая цифровые сертификаты для подтверждения подлинности открытых ключей.

**Intermediate CA (Промежуточный центр сертификации)** — подчиненный удостоверяющий центр, сертификат которого подписан корневым CA. В двухуровневой архитектуре он является единственным узлом, выпускающим конечные сертификаты. Его безопасность обеспечивается через ограничение `pathlen:0` в расширении Basic Constraints.

**ca-chain.crt (Цепочка сертификатов, Bundle)** — PEM-файл, содержащий сертификаты всех уровней от Intermediate до Root (в порядке убывания иерархии). Необходим для того, чтобы клиенты могли построить путь доверия до корневого якоря.

**pathlen (Path Length Constraint)** — параметр расширения Basic Constraints стандарта X.509. Значение `0` в сертификате Intermediate CA означает, что он может выпускать только конечные сертификаты (leaf), но не может подписывать другие CA. Это критически важное ограничение: если злоумышленник компрометирует ключ Intermediate CA, он не сможет создать подчиненный CA и выдать доверенный сертификат для другого домена — только для конечных узлов, что сужает поверхность атаки.

**OpenSSL 3.0+** — версия тулсета, в которой архитектура перешла на использование провайдеров (Default, FIPS, Legacy). Параметр конфигурации `RANDFILE` не нужен с OpenSSL 1.1.1 (улучшенный CSPRNG): сохраняется лишь для обратной совместимости, а энтропия берётся из ОС. Поддержаны гибридные схемы и постквантовая криптография (PQC).

> Базовые понятия PKI (ключ, CSR (Certificate Signing Request), X.509, цепочка доверия, CRL, OCSP, расширения X.509, алгоритмы 2026, PQC) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Об архитектуре двухуровневого CA и сравнении с одноуровневой см. **[обзор двухуровневого CA](./overview.md)**.

## Предварительные требования

### Железо и операционная система

- **CPU:** x86_64 или ARM64 с поддержкой AES-NI (для аппаратного ускорения RSA/ECDSA операций).
- **RAM:** минимально 512 МБ, рекомендуется 2 ГБ и выше для генерации ключей RSA-4096.
- **Диск:** 1 ГБ свободного пространства для хранения сертификатов, CRL, базы данных и логов.
- **ОС:** Linux (Debian 12+, RHEL 9+, Ubuntu 22.04+), FreeBSD 13+, macOS 13+ (только для разработки, не для production).

### Программное обеспечение

- **OpenSSL 3.0.x или 3.1.x** — проверить: `openssl version -a`
  ```bash
  # → OpenSSL 3.0.2 15 Mar 2022
  ```
  OpenSSL 1.1.1 несовместим с новой системой провайдеров и отсутствием поддержки некоторых алгоритмов 2026.
- **Coreutils:** `mkdir`, `touch`, `echo`, `cat`, `chmod`, `chown` (стандартный набор GNU/Linux).
- **Cron или systemd-timer** — для автоматической генерации CRL и проверки срока действия.
- **jq** (опционально) — для парсинга JSON при интеграции с HashiCorp Vault.
- **curl** или **wget** — для загрузки CRL/OCSP ответов на удаленные серверы.

### Проверка окружения

```bash
# Проверка версии OpenSSL
openssl version -a

# Проверка доступных провайдеров (OpenSSL 3.0+)
openssl list -providers

# Проверка аппаратного ускорения AES
openssl speed -evp aes-256-gcm

# Проверка энтропии (важно для генерации ключей)
cat /proc/sys/kernel/random/entropy_avail
# → значение > 1000 желательно для headless-серверов
```

Если энтропия недостаточна, установите `haveged` или `rng-tools`:
```bash
# Debian/Ubuntu
apt-get install -y haveged
systemctl enable --now haveged

# RHEL/CentOS/Fedora
dnf install -y haveged
systemctl enable --now haveged
```

### Разделение ответственности

Intermediate CA работает на **онлайн-узле** с доступом к сети. В двухуровневой схеме:
- **Root CA** — air-gapped хост, используется только для подписи CSR Intermediate CA.
- **Intermediate CA** — production-узел, отвечает за выпуск конечных сертификатов, CRL, OCSP Stapling.

См. архитектурный обзор в **[обзоре двухуровневого CA](./overview.md)**.

## Базовые концепции

### Роль в двухуровневой архитектуре

Промежуточный CA выполняет роль «операционного офиса» PKI. В то время как Root CA (Корневой CA) хранится в изолированной среде (air-gapped), промежуточный узел доступен для автоматизированных процессов.

**Преимущества использования Intermediate CA:**
- **Безопасность корня:** Корневой ключ остается офлайн. В случае компрометации промежуточного ключа отзывается только он, а корневое доверие сохраняется.
- **Масштабируемость:** Можно создать несколько Intermediate CA для разных департаментов или регионов с разными политиками.
- **Автоматизация:** Промежуточный CA можно интегрировать с HashiCorp Vault или cert-manager (только on-prem, не cloud-native managed services).

### Расширения X.509 для Intermediate CA

Каждое расширение в секции `[ v3_intermediate_ca ]` имеет строгое назначение:

| Расширение | Значение | Назначение |
|:---|:---|:---|
| `basicConstraints` | `critical, CA:true, pathlen:0` | Обозначает, что этот сертификат принадлежит CA, и запрещает создание подчиненных CA. Критическое — клиенты обязаны проверять это расширение. |
| `keyUsage` | `critical, digitalSignature, keyCertSign, cRLSign` | Разрешает использование ключа для подписи сертификатов и CRL. `digitalSignature` обязателен для TLS-серверов, `keyCertSign` и `cRLSign` — для операций CA. |
| `subjectKeyIdentifier` | `hash` | Уникальный хеш открытого ключа. Используется клиентами для быстрого сопоставления сертификатов в цепочке. |
| `authorityKeyIdentifier` | `keyid:always,issuer` | Ссылка на открытый ключ издателя (Root CA). Позволяет клиенту верифицировать, что Intermediate CA действительно подписан корневым. |

### Файл цепочки доверия

Современные браузеры и TLS-клиенты требуют предоставления полной цепочки. Без файла `ca-chain.crt` сервер отправит только свой сертификат, и клиент выдаст ошибку `Incomplete Chain` или `Unknown CA`, так как он не знает о промежуточном звене.

Правильный порядок в `ca-chain.crt`:
```
intermediate-ca/intermediate.crt
root-ca/ca.crt
```
Клиент читает файл сверху вниз, проверяя каждый сертификат по цепочке.

## Практические сценарии

### 1. Подготовка структуры директорий

```bash
mkdir -p intermediate-ca/{db,certs,crl,csr}
touch intermediate-ca/db/index.txt
echo "1000" > intermediate-ca/db/serial
echo "1000" > intermediate-ca/db/crlnumber

# Ограничение прав: только владелец может читать/писать
chmod 700 intermediate-ca
chmod 600 intermediate-ca/db/*
```

**Валидация:**
```bash
ls -la intermediate-ca/
# → db/  certs/  crl/  csr/
ls -la intermediate-ca/db/
# → index.txt  serial  crlnumber
```

### 2. Создание конфигурационного файла openssl.cnf

Файл `intermediate-ca/openssl.cnf` определяет политику выпуска операционного узла. В отличие от Root CA, политика здесь мягче (`policy_loose`), так как Intermediate CA обслуживает множество сервисов с разными DN.

```ini
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = .
database        = $dir/db/index.txt
new_certs_dir   = $dir/certs
serial          = $dir/db/serial
crlnumber       = $dir/db/crlnumber
certificate     = $dir/intermediate.crt
private_key     = $dir/intermediate.key

default_md      = sha512
default_days    = 365
policy          = policy_loose
copy_extensions = copy

# Мягкая политика для конечных сервисов
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
x509_extensions     = v3_intermediate_ca
prompt              = no

[ req_distinguished_name ]
C  = RU
ST = Moscow
O  = My Private Corp
CN = My Private Intermediate CA

# Расширения для самого Intermediate CA (при подписи корнем)
[ v3_intermediate_ca ]
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints       = critical, CA:true, pathlen:0
keyUsage               = critical, digitalSignature, keyCertSign, cRLSign

# Расширения для сертификатов сервисов (serverAuth)
[ v3_server_cert ]
basicConstraints       = CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName         = @alt_names

# Шаблон SAN для сервисов (переопределяется при выпуске)
[ alt_names ]
DNS.1 = my-service.local
IP.1  = 10.0.0.10
```

**Пояснения к ключевым параметрам:**
- `copy_extensions = copy` — позволяет сервисным сертификатам наследовать расширения из CSR (включая SAN). Без этого параметра OpenSSL игнорирует расширения, запрошенные в CSR.
- `default_days = 365` — срок действия сервисных сертификатов по умолчанию. Рекомендуется ≤ 90 дней для production с автоматической ротацией.
- `policy_loose` — не требует обязательного указания `countryName`, `stateOrProvinceName` и т.д. в CSR. Только `commonName` обязателен.
- `v3_server_cert` — секция используется при выпуске сервисных сертификатов через `openssl ca -extensions v3_server_cert`.

**Валидация синтаксиса:**
```bash
openssl genpkey -algorithm RSA -out /tmp/test.pem -pkeyopt rsa_keygen_bits:2048 2>&1
# → (без ошибок)

# Проверка, что openssl.cnf читается корректно
openssl req -config intermediate-ca/openssl.cnf -noenc -new -key /tmp/test.pem -out /tmp/test.csr 2>&1
# → (без ошибок)
```

### 3. Генерация ключа и запроса (CSR)

#### Вариант А: RSA-4096

```bash
openssl req -new -config intermediate-ca/openssl.cnf \
    -newkey rsa:4096 -sha512 -nodes \
    -keyout intermediate-ca/intermediate.key \
    -out intermediate-ca/csr/intermediate.csr
```

#### Вариант Б: ECDSA P-384 (Рекомендуется в 2026)

```bash
openssl req -new -config intermediate-ca/openssl.cnf \
    -newkey ec:<(openssl ecparam -name secp384r1 -genkey -noout) \
    -sha512 -nodes \
    -keyout intermediate-ca/intermediate.key \
    -out intermediate-ca/csr/intermediate.csr
```

**Валидация:**
```bash
# Проверка параметров ключа
openssl ecparam -in intermediate-ca/intermediate.key -text -noout 2>/dev/null || \
openssl rsa -in intermediate-ca/intermediate.key -text -noout
# → для ECDSA: ASN1 OID: secp384r1
# → для RSA: Private-Key: (4096 bit)

# Проверка CSR
openssl req -in intermediate-ca/csr/intermediate.csr -noout -text
# → subject=/CN=My Private Intermediate CA/O=My Private Corp/C=RU
# → No attributes (or extensions) present in CSR
```

**Безопасность ключа:**
```bash
chmod 600 intermediate-ca/intermediate.key
# Рекомендуется: переместить ключ на HSM или TPM, если оборудование доступно.
```

### 4. Подпись промежуточного CA в Root-узле

Операция выполняется на стороне **[Root CA](./root_ca_setup.md)** (офлайн-система). Подробные шаги смотрите в разделе «Подпись Intermediate CA» в `root_ca_setup.md`. Здесь описан сам процесс для полноты картины:

```bash
# На air-gapped хосте Root CA
cd root-ca

# Проверка CSR перед подписью
openssl req -in ../intermediate-ca/csr/intermediate.csr -noout -text

# Подпись с расширениями Intermediate CA (1825 дней ≈ 5 лет — ротация 3–5 лет)
openssl ca -config openssl.cnf \
    -extensions v3_intermediate_ca \
    -days 1825 -notext -md sha512 \
    -in ../intermediate-ca/csr/intermediate.csr \
    -out ../intermediate-ca/intermediate.crt

cd ..
```

**Валидация на стороне Root CA:**
```bash
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
# → intermediate.crt: OK
```

### 5. Формирование цепочки и верификация

После получения подписанного сертификата необходимо создать Bundle и проверить его.

```bash
# Создание цепочки (Intermediate + Root)
cat intermediate-ca/intermediate.crt root-ca/ca.crt > intermediate-ca/ca-chain.crt

# Верификация промежуточного сертификата относительно корня
openssl verify -CAfile root-ca/ca.crt intermediate-ca/intermediate.crt
# → intermediate.crt: OK

# Проверка расширения Basic Constraints
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 3 "Basic Constraints"
# → X509v3 Basic Constraints:
# →     critical
# →     CA:TRUE, pathlen:0

# Проверка Subject Key Identifier
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 1 "Subject Key Identifier"
# → X509v3 Subject Key Identifier:
# →     hash:AB:CD:EF:...

# Проверка Authority Key Identifier
openssl x509 -in intermediate-ca/intermediate.crt -noout -text | grep -A 1 "Authority Key Identifier"
# → X509v3 Authority Key Identifier:
# →     keyid:12:34:56:...,issuer
```

### 6. Настройка CRL и OCSP (опционально, рекомендуется)

Intermediate CA должен уметь отзывать скомпрометированные сертификаты и предоставлять актуальный CRL клиентам.

```bash
cd intermediate-ca

# Генерация первого CRL
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

# Проверка CRL
openssl crl -in crl/crl.pem -noout -text
# → Signature Algorithm: sha512WithRSAEncryption
# → Last Update: ...
# → Next Update: ...

# Публикация CRL (скопировать в web-accessible директорию)
cp crl/crl.pem /var/www/html/pki/crl.pem
```

Для автоматической генерации CRL добавьте в `crontab`:
```bash
# Каждый день в 02:00
0 2 * * * cd /opt/pki/intermediate-ca && /usr/bin/openssl ca -config openssl.cnf -gencrl -out crl/crl.pem && /usr/bin/openssl crl -in crl/crl.pem -noout -nextupdate > /dev/null
```

### 7. Автоматизация выпуска сертификатов (CI/CD)

Для автоматизации в Jenkins, GitLab CI или аналогичных систем используйте неинтерактивный режим:

```bash
#!/bin/bash
set -euo pipefail

INTERMEDIATE_DIR="/opt/pki/intermediate-ca"
CSR_PATH="${1:-/tmp/service.csr}"
CERT_OUT="${2:-/tmp/service.crt}"
DAYS="${3:-365}"
SAN_DNS="${4:-my-service.local}"
SAN_IP="${5:-10.0.0.10}"

# Создание временного конфига с SAN
cat > /tmp/v3_server_tmp.cnf <<EOF
[v3_server_cert]
basicConstraints       = CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName         = @alt_names

[alt_names]
DNS.1 = ${SAN_DNS}
IP.1  = ${SAN_IP}
EOF

# Подпись сертификата
openssl ca -config "${INTERMEDIATE_DIR}/openssl.cnf" \
    -extensions v3_server_cert \
    -extfile /tmp/v3_server_tmp.cnf \
    -days "${DAYS}" -md sha512 -notext \
    -in "${CSR_PATH}" \
    -out "${CERT_OUT}"

# Очистка
rm -f /tmp/v3_server_tmp.cnf

echo "OK: ${CERT_OUT}"
```

**Валидация:**
```bash
chmod +x sign_service_cert.sh
./sign_service_cert.sh /tmp/service.csr /tmp/service.crt 90 myservice.local 192.168.1.10
# → OK: /tmp/service.crt
openssl verify -CAfile intermediate-ca/ca-chain.crt /tmp/service.crt
# → /tmp/service.crt: OK
```

## Дополнительная информация

### Безопасность операционного узла

Так как ключ Intermediate CA доступен онлайн, он требует повышенных мер защиты:
- **Хранение ключа:** Приватный ключ `intermediate.key` должен иметь права `600` и принадлежать dedicated-пользователю (например, `pkiuser`).
- **Сетевая изоляция:** доступ к порту управления CA (если используется веб-интерфейс) только через VPN или внутренние Jump-хосты.
- **Аудит:** все операции выпуска и отзыва логируются. Включите `-log` в `openssl.cnf` или перенаправьте stderr в SIEM.
- **Резервное копирование:** резервная копия `intermediate.key` и `intermediate.crt` хранится в зашифрованном хранилище (например, LUKS, VeraCrypt) на отдельном носителе.
- **Мониторинг `index.txt`:** аудит всех выпущенных сертификатов через системы логирования.

### Ротация Intermediate CA

Срок действия Intermediate CA — 3–5 лет. Процедура ротации:

1. Подготовить новый CSR на новом Intermediate CA (параллельно с действующим).
2. Подписать новый CSR корневым CA.
3. Сформировать новый `ca-chain.crt`.
4. Выпустить новые сервисные сертификаты через новый Intermediate CA.
5. Распространить новый `ca-chain.crt` во все доверенные хранилища.
6. Отозвать старый Intermediate CA.
7. Сгенерировать новый CRL.

Подробности см. в **[обзоре двухуровневого CA](./overview.md)**.

### Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `unable to load certificate` | Путь к `certificate` в `openssl.cnf` неверный или файл отсутствует | Проверьте `certificate = $dir/intermediate.crt` и наличие файла |
| `database lock error` | Предыдущий `openssl ca` завершился аварийно, оставив блокировку | Удалите `db/index.txt.attr` или `db/index.txt.lock` |
| `error loading extension section` | Имя секции в `-extensions` не совпадает с `[ section_name ]` в `.cnf` | Проверьте точное соответствие имен секций |
| `TXT_DB error` | Некорректный формат `db/index.txt` (пробелы, спецсимволы в DN) | Отредактируйте `db/index.txt` вручную или пересоздайте |
| `pathlen constraint violated` | Промежуточный CA пытается подписать другой CA, но `pathlen:0` | Убедитесь, что подписываются только конечные сертификаты |
| `certificate verify failed` | `ca-chain.crt` неполный или `root-ca/ca.crt` не добавлен в trust store | Проверьте порядок сертификатов в `ca-chain.crt` |
| `unsupported algorithm` | OpenSSL 3.0+ требует явного указания провайдера для MD5/SHA1 | Используйте `default_md = sha512`, избегайте MD5/SHA1 |

### Ограничения и крайние случаи

- **OpenSSL 3.0+ провайдеры:** При использовании FIPS-режима убедитесь, что провайдер загружен: `openssl list -providers`. Если алгоритм не поддерживается, OpenSSL завершит операцию с ошибкой `unsupported algorithm`.
- **Энтропия:** На headless-серверах без датчика энтропии генерация ключей может блокироваться. Установите `haveged` или используйте `/dev/urandom` с предварительным заполнением.
- **Legacy-системы:** OpenSSL 1.1.1 и ниже не поддерживают `pathlen:0` корректно в некоторых сборках. Используйте 3.0+.
- **pathlen:** После установки `pathlen:0` в Intermediate CA невозможно создать подчиненный CA без перевыпуска Intermediate. Это необратимое ограничение.
- **Регуляторика:** В финансовом и медицинском секторах может требоваться использование сертифицированных криптографических средств (СКЗИ). OpenSSL из стандартных репозиториев не является сертифицированным.

### Очистка и откат

Если требуется полностью удалить Intermediate CA и начать заново:

```bash
# Остановка всех сервисов, использующих сертификаты Intermediate CA
systemctl stop nginx apache2 haproxy

# Отзыв всех выпущенных сертификатов (опционально)
cd intermediate-ca
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

# Удаление директории Intermediate CA
rm -rf intermediate-ca

# Удаление сертификата Intermediate CA из доверенных хранилищ клиентов
# (выполняется на каждом клиенте отдельно)
```

### Мониторинг и оповещение

Скрипт для Nagios/Zabbix/Prometheus Node Exporter:

```bash
#!/bin/bash
set -euo pipefail

INTERMEDIATE_CRT="/opt/pki/intermediate-ca/intermediate.crt"
WARN_DAYS=30
CRIT_DAYS=7

if [[ ! -f "$INTERMEDIATE_CRT" ]]; then
    echo "CRITICAL: Intermediate CA certificate not found"
    exit 2
fi

DAYS_LEFT=$(openssl x509 -in "$INTERMEDIATE_CRT" -noout -enddate 2>/dev/null \
    | cut -d= -f2 \
    | date -f - +%s 2>/dev/null \
    | awk -v now=$(date +%s) 'BEGIN{print int(($1-now)/86400)}')

if [[ -z "$DAYS_LEFT" ]] || [[ "$DAYS_LEFT" -lt 0 ]]; then
    echo "CRITICAL: Intermediate CA expired or invalid"
    exit 2
elif [[ "$DAYS_LEFT" -le "$CRIT_DAYS" ]]; then
    echo "CRITICAL: Intermediate CA истекает через $DAYS_LEFT дней"
    exit 2
elif [[ "$DAYS_LEFT" -le "$WARN_DAYS" ]]; then
    echo "WARNING: Intermediate CA истекает через $DAYS_LEFT дней"
    exit 1
else
    echo "OK: Intermediate CA действителен ещё $DAYS_LEFT дней"
    exit 0
fi
```

### Best Practices

- **Приватные ключи всегда offline:** Root CA ключ никогда не должен находиться на машине с сетевым доступом. Intermediate CA ключ — только в защищенном сегменте.
- **Ротация по расписанию:** ротация Intermediate CA каждые 3–5 лет, конечных сертификатов — по мере приближения срока действия (рекомендуется ≤ 90 дней).
- **Алгоритмы:** используйте ECDSA P-384 или RSA-4096 с SHA-512. Избегайте SHA-1 и MD5 — они депрецированы и не проходят проверку в современных браузерах.
- **Резервное копирование:** храните зашифрованные копии `intermediate.key` и `intermediate.crt` на внешних носителях.
- **Аудит:** ведите журнал всех выпущенных и отозванных сертификатов.
- **Мониторинг:** автоматически проверяйте срок действия Intermediate CA и CRL.
- **CRL Distribution Points:** добавьте расширение `crlDistributionPoints` в `v3_server_cert` для автоматического распространения CRL.
- **OCSP:** для production-сред настройте OCSP responder на Intermediate CA узле — это снижает нагрузку и ускоряет проверку статуса сертификатов.

### Связанные темы

- **[Настройка Root CA](./root_ca_setup.md)** — подготовка фундамента доверия, подпись Intermediate CA.
- **[Управление сертификатами сервисов](./service_certificate_management.md)** — выпуск конечных сертификатов через Intermediate CA.
- **[Утилиты и диагностика](./common_utilities.md)** — проверка цепочек `ca-chain.crt`, диагностика ошибок.
- **[Алгоритм диагностики](./troubleshooting_flowchart.md)** — decision-tree для поиска проблем с сертификатами.
- **[Интеграция с SIEM](./siem_integration.md)** — аудит операций CA, syslog, auditd, алертинг.
- **[CRL Distribution Points](../crl_distribution_points.md)** — настройка HTTP-сервера для распространения CRL.
- **[OCSP Responder](../ocsp_responder.md)** — настройка OCSP-резолвера для проверки статуса сертификатов в реальном времени.
- **[Обзор двухуровневого CA](./overview.md)** — архитектура, алгоритмы, хранилище ключей, порядок развёртывания.
