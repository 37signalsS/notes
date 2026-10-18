# Управление сертификатами сервисов в двухуровневом CA

**Актуально для:** OpenSSL 3.0+

## Определения

**Сертификат сервиса (Service Certificate)** — цифровой документ стандарта X.509, используемый для идентификации узлов (веб-серверов, API, БД) и шифрования трафика. В двухуровневой иерархии подписывается исключительно **Intermediate CA**.

**CA (Certificate Authority)** — доверенная сторона в PKI. В данной модели корень (Root) изолирован, а промежуточный узел (Intermediate) является «выпускающим».

**OpenSSL 3.0+** — криптографический тулсет с модульной архитектурой провайдеров (Default, Legacy, FIPS). Команда `openssl rsa` находится в режиме поддержки (maintenance mode) — для универсальной проверки key/cert используйте `openssl pkey`/`openssl x509 -pubkey` (см. [Утилиты и диагностика](./common_utilities.md#проверка-соответствия-ключа-и-сертификата)). Полная поддержка NIST PQC (ML-KEM, ML-DSA, SLH-DSA) доступна, начиная с OpenSSL 3.5.

**mTLS (Mutual TLS)** — стандарт безопасности, требующий наличия сертификатов у обеих сторон соединения.

**DN (Distinguished Name, Отличительное имя)** — уникальная строка идентификации субъекта в формате X.500 (например, `/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local`).

**EKU (Extended Key Usage)** — расширение X.509, уточняющее назначение сертификата: `serverAuth` (аутентификация сервера), `clientAuth` (аутентификация клиента), `codeSigning` (подпись кода).

**Bundle / Fullchain** — PEM-файл, объединяющий сертификат сервиса и промежуточный CA. В двухуровневой схеме клиенту требуется `ca-chain.crt` (Intermediate + Root) для построения цепочки доверия.

> Базовые понятия (CSR, SAN, CRL, Цепочка доверия) подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**.

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

### Жизненный цикл сертификата сервиса

1. **Генерация ключа и CSR:** выполняется локально на целевом сервере. Приватный ключ **никогда** не покидает сервер.
2. **Передача запроса:** CSR отправляется администратору CA.
3. **Валидация и подпись:** администратор проверяет CSR, настраивает SAN и подписывает запрос через `openssl ca`.
4. **Установка:** сертификат (`.crt`) и корень (`ca-chain.crt`) устанавливаются в приложение/ОС.
5. **Ротация:** плановый перевыпуск за 30–60 дней до истечения срока действия.
6. **Отзыв:** немедленное аннулирование в базе CA при компрометации.

### Порядок в ca-chain.crt

В двухуровневой архитектуре файл `ca-chain.crt` (bundle) обязан содержать сертификаты в строгом порядке:

```
-----BEGIN CERTIFICATE-----
[Сертификат Intermediate CA]
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
[Сертификат Root CA]
-----END CERTIFICATE-----
```

Клиентские приложения (OpenSSL, curl, Java) проверяют цепочку снизу вверх: leaf → Intermediate → Root. Если порядок нарушен или отсутствует Intermediate, верификация завершается ошибкой `unable to verify the first certificate`.

### Ограничения двухуровневой архитектуры

- **`pathlen:0`:** Intermediate CA не может подписывать дочерние CA. Для создания подчинённого CA требуется перевыпуск Intermediate с другим `pathlen`.
- **Зависимость от Intermediate:** все сервисные сертификаты становятся недействительными при истечении или отзеве Intermediate CA.
- **Распространение bundle:** при ротации Intermediate CA требуется обновить `ca-chain.crt` на всех серверах и в доверенных хранилищах.

## Предварительные требования

### Аппаратные и программные требования

- **ОС:** Linux (Debian/Ubuntu, RHEL/CentOS/Fedora, Alpine) или macOS. Инструкции tested на Linux x86_64.
- **OpenSSL:** версия 3.0.0 или выше. Проверка: `openssl version -a`.
- **CA:** развернутый двухуровневый CA по инструкциям в **[Настройка Root CA](./root_ca_setup.md)** и **[Настройка Intermediate CA](./intermediate_ca_setup.md)**.
- **Права:** доступ пользователя с возможностью чтения файлов CA (`intermediate-ca/ca-chain.crt`, `intermediate-ca/intermediate.key`). Для установки сертификатов в системные хранилища требуются права `root` или `sudo`.
- **Дисплей:** для операций с парольной фразой (если ключ CA шифруется) требуется терминал с поддержкой ввода пароля.

### Проверка окружения

```bash
# Проверка версии OpenSSL
openssl version -a
# → OpenSSL 3.0.x ...

# Проверка доступных провайдеров (OpenSSL 3.0+)
openssl list -providers
# → Providers:
# →  ... (default provider)
# →  ... (legacy provider, при необходимости)
```

### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y openssl libssl-dev

# RHEL/CentOS/Fedora
sudo dnf install -y openssl openssl-devel

# Alpine
sudo apk add openssl openssl-dev
```

### Разделение ответственности

| Роль | Обязанности |
| :--- | :--- |
| **Владелец сервиса** | Генерация ключа, создание CSR, установка сертификата, мониторинг срока действия |
| **Администратор Intermediate CA** | Валидация CSR, настройка SAN, подпись, отзев, генерация CRL |
| **Администратор Root CA** | Подпись нового Intermediate CA, ротация корня (раз в 5–10 лет) |

## Практические сценарии

### 1. Генерация ключа и CSR на стороне сервиса

#### Вариант А: Классический RSA-4096
```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out service.key
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

#### Вариант Б: Современный ECDSA P-384 (Рекомендуется)
```bash
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 -out service.key
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

#### Вариант В: Ed25519 (максимальная производительность)
```bash
openssl genpkey -algorithm Ed25519 -out service.key
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

> **Важно:** Приватный ключ `service.key` должен храниться с правами `600` и никогда не покидать целевой сервер.

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

**Ожидаемый вывод:**
```
Using configuration from openssl.cnf
Check that the request matches the signature
Signature ok
The Subject's Distinguished Name is as follows
...
1 out of 1 certificate requests certified, commit? [y/n]: y
Write out database with 1 new entries
Data Base Updated
```

> **Примечание:** детальная настройка `openssl.cnf` и политик подписи описана в **[Настройка Intermediate CA](./intermediate_ca_setup.md)**. Диагностика проблем с подписью — в **[Утилиты и диагностика](./common_utilities.md)**.

### 3. Установка доверия (Root CA)

Чтобы приложения доверяли иерархии, необходимо установить сертификат **Root CA** в системные хранилища.

#### Операционные системы
- **Debian/Ubuntu/Angie:** `sudo cp root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`
- **RHEL/CentOS/Fedora:** `sudo cp root.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust`
- **Alpine:** `sudo cp root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`
- **macOS:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root.crt`
- **Windows Server:** `certutil -addstore "Root" root.crt`

#### Docker-контейнеры

При сборке образа добавьте сертификат в системное хранилище внутри Dockerfile:
```dockerfile
COPY root.crt /usr/local/share/ca-certificates/internal-ca.crt
RUN update-ca-certificates
```

#### Java (KeyStore/TrustStore)

Java использует собственное хранилище `cacerts`. Для добавления корня:
```bash
keytool -import -alias root-ca -file root.crt \
    -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit -noprompt
```

> **Важно:** приватные ключи сервисов также можно добавлять в Java Keystore через PKCS#12 (см. сценарий 7).

### 4. Верификация перед запуском

Всегда проверяйте соответствие ключа сертификату и целостность цепочки:

```bash
# Проверка пары: хеши публичных ключей должны совпасть (универсальный метод для RSA/ECDSA/Ed25519)
openssl pkey -in service.key -pubout -outform DER | openssl sha256
openssl x509 -in service.crt -pubkey -noout -outform DER | openssl sha256
# → Хеши должны совпадать

# Проверка цепочки доверия (через Bundle)
openssl verify -CAfile intermediate-ca/ca-chain.crt service.crt
# → service.crt: OK
```

> **Примечание:** полный набор диагностических команд (просмотр расширений, проверка SAN, тестирование через `s_client`, верификация mTLS) приведён в **[Утилиты и диагностика](./common_utilities.md)**.

### 5. Отзев скомпрометированного сертификата

```bash
cd intermediate-ca
openssl ca -config openssl.cnf -revoke ../service.crt
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem
```

После отзева убедитесь, что сервис перестаёт получать доступ к защищённым ресурсам, а новый CRL распространён на все серверы, которые его проверяют.

### 6. Выпуск клиентского сертификата для mTLS

Для взаимной аутентификации (mTLS) клиентский сертификат выпускается аналогично серверному, но с расширением `extendedKeyUsage = clientAuth`.

#### Шаг 1: Генерация ключа и CSR на стороне клиента

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out client.key
openssl req -new -key client.key -out client.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service-client"
```

#### Шаг 2: Подпись администратором Intermediate CA

В `intermediate-ca/openssl.cnf` используйте или создайте секцию `[v3_client]`:
```ini
[v3_client]
basicConstraints       = CA:FALSE
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
```

Выполните подпись:
```bash
cd intermediate-ca
openssl ca -config openssl.cnf -in ../client.csr -out ../client.crt \
    -extensions v3_client -notext
```

### 7. Конвертация форматов сертификатов

Разные сервисы и ОС требуют различных форматов хранилища сертификатов.

#### PEM → DER (бинарный X.509)
```bash
openssl x509 -in service.crt -outform DER -out service.der
```

#### DER → PEM
```bash
openssl x509 -in service.der -inform DER -out service.crt
```

#### PEM → PKCS#12 (PFX) для Windows/Java
```bash
openssl pkcs12 -export -out service.p12 \
    -in service.crt -inkey service.key \
    -certfile intermediate-ca/ca-chain.crt \
    -name "service.local"
```

#### PKCS#12 → PEM
```bash
openssl pkcs12 -in service.p12 -out service.pem \
    -nodes -clcerts
```

#### PEM → Java Keystore (JKS)
```bash
# pkcs12 → JKS
keytool -importkeystore -dest storepass changeit \
    -dest keypass changeit \
    -dest keystore service.jks \
    -srckeystore service.p12 -srcstoretype PKCS12 \
    -srcstorepass changeit -alias "service.local"
```

### 8. Обработка wildcard-сертификатов

Wildcard-сертификаты (`*.service.local`) выпускаются аналогично обычным, но SAN должен содержать как wildcard, так и конкретные имена:

```ini
[alt_names]
DNS.1 = *.service.local
DNS.2 = service.local
IP.1  = 10.0.5.10
```

> **Важно:** wildcard покрывает только один уровень поддоменов (`api.service.local` — да, `a.api.service.local` — нет). Для глубоких поддоменов перечисляйте их явно.

### 9. Ротация и продление сертификатов

Рекомендуется перевыпускать сертификат за 30–60 дней до истечения срока действия.

#### Шаг 1: Проверка срока действия
```bash
openssl x509 -in service.crt -noout -enddate
# → notAfter=Jan  1 00:00:00 2026 GMT

# Быстрая проверка (выход 0 = сертификат действителен ≥ 30 дней)
openssl x509 -in service.crt -noout -checkend 2592000
```

#### Шаг 2: Генерация нового ключа и CSR
```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out service.key
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Org/OU=IT/CN=service.local"
```

#### Шаг 3: Подпись новым сертификатом
```bash
cd intermediate-ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_server_cert -notext
```

#### Шаг 4: Graceful-замена в сервисе
1. Скопируйте новый сертификат в каталог сервиса.
2. Перезапустите сервис (systemd reload, nginx -s reload).
3. Удалите старый сертификат после подтверждения работоспособности.
4. Обновите `ca-chain.crt` в доверенных хранилищах, если он менялся.

### 10. Пакетная выдача сертификатов (CI/CD)

Для автоматизации в Jenkins, GitLab CI или аналогичных систем используйте неинтерактивный режим:

```bash
#!/bin/bash
set -euo pipefail

INTERMEDIATE_DIR="/opt/pki/intermediate-ca"
CSR_PATH="${1:?Укажите путь к CSR}"
CERT_OUT="${2:?Укажите путь для выходного сертификата}"
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
    -batch \
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

## Рекомендации и лучшие практики

### Планирование срока действия

- **Root CA:** 10–20 лет (редкая ротация, хранится offline).
- **Intermediate CA:** 3–5 лет (периодическая ротация для ограничения blast radius).
- **Сертификаты сервисов:** 90–365 дней (автоматическая ротация — предпочтительнее).
- **Client certificates для mTLS:** 30–90 дней (короткий срок для ограничения экспозиции).

### Управление ключами

- Приватные ключи сервисов всегда хранятся с правами `600` и принадлежат сервисному пользователю (не `root`, не `www-data`).
- Root CA ключ — строго offline (USB-HSM, Papertape backup), никогда не на сервере с сетевым доступом.
- Intermediate CA ключ — в защищённом сегменте, но доступен для операций подписи.

### Автоматизация ротации

Для массовой ротации используйте Ansible-плейбуки (см. **[Ansible certificate management](../../../../Ansible/ansible_certificate_management.md)**, если доступно):

```yaml
# Минимальный playbook для ротации сертификата
- hosts: webservers
  vars:
    cert_days_min: 30
  tasks:
    - name: Проверить срок действия сертификата
      shell: |
        echo | openssl s_client -connect "{{ inventory_hostname }}:443" 2>/dev/null \
          | openssl x509 -noout -checkend "{{ cert_days_min * 86400 }}"
      register: cert_check
      changed_when: false
      ignore_errors: true

    - name: Сообщить о необходимости ротации
      debug:
        msg: "Certificate on {{ inventory_hostname }} expires soon"
      when: cert_check.rc != 0
```

> **Примечание:** скрипты мониторинга для Nagios/Zabbix/Prometheus, а также полный чек-лист перед деплоем — в **[Утилиты и диагностика](./common_utilities.md)**.

## Ограничения и крайние случаи

- **Ротация Intermediate CA:** при смене Intermediate CA все ранее выписанные сертификаты остаются действительными до своего `notAfter`, но новые сертификаты будут подписаны другим издателем. Bundle (`ca-chain.crt`) на всех серверах должен быть обновлён для новых сертификатов.
- **Дублирование серийного номера:** OpenSSL использует `index.txt` для отслеживания выписанных сертификатов. Если серийный номер уже существует (например, после ручного редактирования), подпись завершится ошибкой `ERROR: ... already in DB`. Очищайте `index.txt` только при полной переинициализации CA.
- **Совпадение key и cert:** сертификат может визуально выглядеть корректно, но приватный ключ не соответствовать публичному. Всегда проверяйте пару через хеши публичных ключей (см. сценарий 4).
- **SAN без CN:** если в CSR нет расширения `subjectAltName`, OpenSSL 3.0+ не будет его автоматически добавлять из `CN`. Всегда указывайте SAN явно в `openssl.cnf`.
- **Граничные IP-адреса:** IP-адреса в SAN поддерживаются, но только IPv4 и IPv6 в стандартном виде. DNS-имена не должны содержать IP-адреса.
- **Срок действия Intermediate CA истек:** если Intermediate CA истёк, ни один сервисный сертификат на его основе больше не проходит верификацию, даже если сервисный сертификат ещё действителен.
- **Ограничение `pathlen`:** если Intermediate CA создан с `pathlen:0`, невозможно выпустить сертификат с `CA:TRUE` для вложенного CA — только конечные сертификаты (`CA:FALSE`).
- **Отзов сертификата и CRL:** если CRL-проверка включена на клиенте (`-crl_check`), отозванный сертификат будет отклоняться даже если CRL не распространён на всех серверах. Используйте стратегию "CRL first, then deploy cert".

## Очистка и откат изменений

### Удаление временных файлов

```bash
# Удаление временных сертификатов и ключей
rm -f service.key service.csr service.crt service.der service.pem service.p12 service.jks

# Очистка кэша OpenSSL и временных конфигов
rm -f /tmp/v3_server_tmp.cnf
rm -rf ~/.openssl/
```

### Отзев сертификата при компрометации

```bash
cd intermediate-ca
# Отзев сертификата с указанием причины
openssl ca -config openssl.cnf -revoke ../compromised.crt -crl_reason keyCompromise

# Регенерация CRL
openssl ca -config openssl.cnf -gencrl -out crl/crl.pem

# Распространение обновлённого CRL на все серверы
rsync -av crl/crl.pem ca-server:/opt/pki/crl/
rsync -av crl/crl.pem web-server:/etc/ssl/crl/
```

### Отзев клиентского сертификата (mTLS)

Для отзова клиентского сертификата используйте расширение `extendedKeyUsage = clientAuth`:

```bash
cd intermediate-ca
openssl ca -config openssl.cnf -revoke ../compromised_client.crt \
    -crl_reason keyCompromise -gencrl -out crl/crl.pem
```

### Удаление записи из index.txt (pre-deployment)

Если сертификат был выпущен, но не установлен, удалите запись из `index.txt`:

```bash
cd intermediate-ca
# Просмотр записей в БД CA
openssl ca -config openssl.cnf -list -serial <serial_number>

# Удаление записи (только для неустановленных сертификатов)
# В index.txt найдите строку с соответствующим серийным номером и удалите её
```

> **Важно:** если сертификат уже установлен на серверах, удаление из `index.txt` недостаточно — необходимо выполнить отзов через `openssl ca -revoke`.

### Откат изменений в CI/CD

При ошибке в пайплайне подписи всегда удаляйте временные артефакты:

```bash
# Очистка в CI/CD-скрипте (добавьте в finally/before_script)
rm -f /tmp/v3_server_tmp.cnf /tmp/service.crt /tmp/service.csr
```

> Полная инструкция по очистке trust store и CI/CD-автоматизации — в **[Утилиты и диагностика](./common_utilities.md#очистка-и-откат-изменений)** и **[Утилиты и диагностика](./common_utilities.md#автоматизация-в-cicd)**.

## Дополнительная информация

### Связанные темы
- **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — подготовка выпускующего узла.
- **[Утилиты и диагностика](./common_utilities.md)** — команды проверки и TLS-тесты.
- **[Алгоритм диагностики](./troubleshooting_flowchart.md)** — decision-tree для поиска проблем с сертификатами.
- **[Интеграция с SIEM](./siem_integration.md)** — аудит операций CA, syslog, auditd, алертинг.
- **[OCSP responder](../ocsp_responder.md)** — настройка OCSP-ответчика.
- **[CRL Distribution Points](../crl_distribution_points.md)** — настройка распределения CRL.
- **[Обзор двухуровневого CA](./overview.md)** — архитектурные принципы.
- **[Обзор PKI](../../../Concepts/pki_overview.md)** — теория X.509 и отзовов.
