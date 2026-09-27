# Конвертация форматов и продвинутая конфигурация одноуровневого CA

## Определения

**PEM (Privacy Enhanced Mail)** — текстовый формат хранения сертификатов и ключей, основанный на Base64-кодировании бинарных данных с заголовками (`-----BEGIN CERTIFICATE-----`). Стандартный формат в Linux и OpenSSL.

**DER (Distinguished Encoding Rules)** — бинарный формат сертификатов X.509. Используется в Windows (CryptoAPI), Java KeyStore и ASN.1-системах. Не содержит текстовых заголовков.

**PKCS#12 (PFX, .p12/.pfx)** — защищённый контейнер для хранения пары «ключ + сертификат + цепочка CA» в одном файле. Шифруется паролем. Используется в Windows (IIS, Certificate Store), Java KeyStore и при импорте/экспорте сертификатов.

**PKCS#7/CMS (.p7b)** — формат для хранения цепочки сертификатов (без приватного ключа). Используется Windows-системами для передачи цепочки доверия.

**policy_anything** — гибкая политика OpenSSL, в которой все поля DN (Distinguished Name) могут быть любыми (не требуют совпадения с CA). Подходит для внутренних CA, где гибкость важнее строгой иерархии.

**copy_extensions** — параметр `openssl.cnf`, определяющий, как OpenSSL обрабатывает расширения из CSR при подписи. Значение `copy` копирует расширения, `copyall` копирует все (включая критические), `none` (по умолчанию) игнорирует.

**CRL Extensions** — расширения, добавляемые в список отзыва (CRL): `Authority Key Identifier`, `Number of Revoked Certificates`, `Signature Algorithm`. Определяют формат и подпись CRL.

**index.txt** — текстовая база данных CA, содержащая записи о каждом выпущенном сертификате. Формат: статус (V/R/E), дата истечения, серийный номер, DN, файл сертификата, дата выдачи.

## Базовые концепции

### Форматы файлов и сценарии использования

| Формат | Расширения | Где используется | Особенности |
| :--- | :--- | :--- | :--- |
| **PEM** | `.pem`, `.crt`, `.key`, `.csr` | Linux, Nginx, Apache, OpenSSL, Let's Encrypt | Текстовый, читаемый, стандарт для консоли |
| **DER** | `.der`, `.cer` | Windows (CryptoAPI), Java, ASN.1 | Бинарный, компактный, без Base64 |
| **PKCS#12** | `.p12`, `.pfx` | Windows (IIS), Java KeyStore, мобильные | Контейнер «ключ + сертификат», зашифрован |
| **PKCS#7** | `.p7b`, `.spc` | Windows Certificate Store, IE | Только сертификаты (без ключа) |

### Когда какой формат нужен

- **Linux + Nginx/Apache:** PEM (`.crt` + `.key` раздельно или `fullchain.pem`)
- **Java (Elasticsearch, Kafka, Tomcat):** PKCS#12 или JKS (через keytool)
- **Windows (IIS, PowerShell):** PKCS#12 (`.pfx`) или DER (`.cer`)
- **Windows Trust Store:** DER или PKCS#7 для цепочки
- **curl/wget с mTLS:** PEM или PKCS#12 (через `--cert-type P12`)

### Формат index.txt (база данных CA)

Файл `db/index.txt` содержит по одной строке на каждый выпущенный сертификат:

```
V    260101120000Z    0A1B2C3D    unknown    /C=RU/ST=Moscow/O=Org/CN=service.local
R    250601120000Z    4E5F6A7B    unknown    250601120000Z    /C=RU/ST=Moscow/O=Org/CN=revoked.local
E    241201120000Z    1A2B3C4D    unknown    /C=RU/ST=Moscow/O=Org/CN=expired.local
```

Столбцы:
1. **Статус:** `V` (Valid), `R` (Revoked), `E` (Expired)
2. **Дата истечения:** формат `YYMMDDHHMMSSZ` (UTC)
3. **Серийный номер:** hex
4. **Флаг:** `unknown` (стандартное значение)
5. **DN (Distinguished Name)**
6. **Для отозванных:** дата отзыва + причина

## Практические сценарии

### Предварительные требования

- OpenSSL 3.0+ установлен и доступен из PATH
- Директория CA настроена по инструкции в [Настройка CA](./ca_setup.md)

### Конвертация форматов сертификатов

#### PEM → DER (бинарный X.509)

```bash
openssl x509 -in service.crt -outform DER -out service.der
# → service.der создан (бинарный, без текстовых заголовков)
```

#### DER → PEM

```bash
openssl x509 -in service.der -inform DER -out service.crt
# → service.crt создан (текстовый PEM)
```

#### PEM → PKCS#12 (PFX) для Windows/Java

```bash
# Минимальный контейнер (только сертификат + ключ)
openssl pkcs12 -export -out service.p12 \
    -in service.crt -inkey service.key \
    -name "service.local"

# С цепочкой CA (рекомендуется)
openssl pkcs12 -export -out service.p12 \
    -in service.crt -inkey service.key \
    -certfile ca/ca.crt \
    -name "service.local" \
    -passout pass:changeit
```

- `-export`: режим экспорта (создание .p12)
- `-name`: friendly name сертификата (отображается в Windows Certificate Store)
- `-certfile`: добавить корневой/промежуточный CA в контейнер
- `-passout pass:...`: пароль для шифрования (в production используйте ввод пароля)

#### PKCS#12 → PEM (извлечение сертификата и ключа)

```bash
# Извлечение только сертификата
openssl pkcs12 -in service.p12 -clcerts -nokeys -out service.crt

# Извлечение только приватного ключа (без шифрования)
openssl pkcs12 -in service.p12 -nocerts -nodes -out service.key

# Полное извлечение в один PEM-файл
openssl pkcs12 -in service.p12 -out service.pem -nodes
```

#### PKCS#7/CMS → PEM

```bash
openssl pkcs7 -in chain.p7b -print_certs -out chain.pem
# → Разделяет цепочку на отдельные PEM-сертификаты
```

#### Объединение ключа и сертификата в один PEM (для某些-сервисов)

```bash
cat service.crt service.key > service-combined.pem
# Используется某些-сервисами (например,某些-SDK, некоторые LB)
```

### Продвинутые секции openssl.cnf

#### Политика policy_anything (гибкая)

В отличие от `policy_match` (требует совпадения полей с CA), `policy_anything` разрешает произвольные значения DN:

```ini
[ policy_anything ]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional
```

- `supplied`: поле обязательно должно присутствовать в CSR
- `optional`: поле может отсутствовать; если присутствует — не проверяется
- `match`: поле должно совпадать с CA (только в `policy_match`)

Использование: измените `policy = policy_match` на `policy = policy_anything` в секции `[CA_default]`, если нужно выпускать сертификаты для разных организаций/стран.

#### Разница между copy и copyall

```ini
# copy — копирует некритичные расширения из CSR
copy_extensions = copy

# copyall — копирует ВСЕ расширения (включая критичные)
copy_extensions = copyall
```

> **Важно:** `copyall` позволяет CSR-у задать `basicConstraints = CA:TRUE`, что является критической уязвимостью. Используйте `copy` для безопасного копирования SAN. Полный контроль — через секцию расширений в конфиге (`-extensions`).

#### CRL Extensions (расширения списка отзыва)

Для генерации CRL с расширениями добавьте в `openssl.cnf`:

```ini
[ crl_ext ]
# Идентификатор ключа CA, подписывающего CRL
authorityKeyIdentifier = keyid:always,issuer
```

Генерация CRL с расширениями:

```bash
cd ca
openssl ca -config openssl.cnf -gencrl -out crl.pem \
    -extensions crl_ext
```

#### Формат и назначение crlnumber

Файл `db/crlnumber` хранит порядковый номер текущего CRL:

```bash
cat ca/db/crlnumber
# → 1000
```

При каждой генерации CRL номер инкрементируется. Это позволяет клиентам определить, является ли скачанный CRL актуальным.

### Автоматизация ротации сертификатов

#### Скрипт проверки срока действия и автоматической переподписи

```bash
#!/bin/bash
# cert-renew.sh — проверка сертификатов и уведомление/автоматическая ротация

CA_DIR="/opt/ca"
CERT_DIR="/etc/nginx/ssl"
WARN_DAYS=30
AUTO_RENEW=false  # Установить true для автоматической переподписи

for crt in "$CERT_DIR"/*.crt; do
    [ -f "$crt" ] || continue

    # Проверка: истекает ли сертификат в ближайшие N дней
    if ! openssl x509 -in "$crt" -noout -checkend $((WARN_DAYS * 86400)) 2>/dev/null; then
        SUBJECT=$(openssl x509 -in "$crt" -noout -subject -nameopt multiline | grep commonName | awk '{print $3}')
        EXPIRY=$(openssl x509 -in "$crt" -noout -enddate | cut -d= -f2)

        echo "WARNING: $crt ($SUBJECT) истекает: $EXPIRY"

        if [ "$AUTO_RENEW" = true ]; then
            KEY="${crt%.crt}.key"
            CSR="${crt%.crt}.csr"

            # Генерация нового ключа и CSR
            openssl genrsa -out "$KEY" 4096 2>/dev/null
            openssl req -new -key "$KEY" -out "$CSR" \
                -subj "$(openssl x509 -in "$crt" -noout -subject | sed 's/^subject=//')" 2>/dev/null

            # Подпись новым сертификатом
            cd "$CA_DIR"
            openssl ca -config openssl.cnf -in "$CSR" -out "${crt}.new" \
                -extensions v3_req -notext -batch 2>/dev/null

            if [ $? -eq 0 ]; then
                mv "${crt}.new" "$crt"
                echo "RENEWED: $crt"
                # Уведомление сервиса (nginx reload)
                systemctl reload nginx
            else
                echo "ERROR: Failed to renew $crt"
                rm -f "${crt}.new"
            fi

            rm -f "$CSR"
        fi
    fi
done
```

#### Cron-задача для ежедневной проверки

```bash
# Добавить в crontab root
0 3 * * * /opt/scripts/cert-renew.sh >> /var/log/cert-renewal.log 2>&1
```

#### Массовая ротация через Ansible (краткая идея)

```yaml
- name: Rotate expiring certificates
  hosts: web_servers
  tasks:
    - name: Check certificate expiry
      shell: openssl x509 -in /etc/nginx/ssl/{{ item }}.crt -noout -checkend 2592000
      register: cert_check
      failed_when: false
      loop: "{{ managed_certificates }}"

    - name: Generate new CSR
      when: cert_check.rc != 0
      shell: |
        openssl genrsa -out /etc/nginx/ssl/{{ item }}.key 4096
        openssl req -new -key /etc/nginx/ssl/{{ item }}.key \
          -out /tmp/{{ item }}.csr -subj "/CN={{ item }}"
      loop: "{{ managed_certificates }}"

    # Подпись выполняется на хосте CA (отдельный play)
```

### Чеклист тестирования CA перед production

```bash
#!/bin/bash
# ca-selftest.sh — проверка целостности одноуровневого CA

CA_DIR="${1:-.}"
ERRORS=0

echo "=== Self-test CA: $CA_DIR ==="

# 1. Проверка корневого сертификата
echo -n "[1] Корневой CA: "
if openssl verify -CAfile "$CA_DIR/ca.crt" "$CA_DIR/ca.crt" | grep -q "OK"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 2. Проверка CA:true в корневом
echo -n "[2] CA:TRUE в корневом: "
if openssl x509 -in "$CA_DIR/ca.crt" -noout -text | grep -q "CA:TRUE"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 3. Проверка keyCertSign в Key Usage
echo -n "[3] keyCertSign в Key Usage: "
if openssl x509 -in "$CA_DIR/ca.crt" -noout -text | grep -A1 "Key Usage" | grep -q "Certificate Sign"; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 4. Проверка соответствия ключа и сертификата
echo -n "[4] Ключ соответствует сертификату (RSA): "
HASH1=$(openssl x509 -noout -modulus -in "$CA_DIR/ca.crt" 2>/dev/null | openssl sha256)
HASH2=$(openssl rsa -noout -modulus -in "$CA_DIR/ca.key" 2>/dev/null | openssl sha256)
if [ "$HASH1" = "$HASH2" ] && [ -n "$HASH1" ]; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 5. Проверка базы данных
echo -n "[5] index.txt существует: "
if [ -f "$CA_DIR/db/index.txt" ]; then
    echo "OK"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

echo -n "[6] serial существует и не пуст: "
if [ -s "$CA_DIR/db/serial" ]; then
    echo "OK ($(cat "$CA_DIR/db/serial"))"
else
    echo "FAIL"; ERRORS=$((ERRORS+1))
fi

# 7. Проверка прав доступа
echo -n "[7] Права на ca.key (600): "
PERMS=$(stat -c %a "$CA_DIR/ca.key" 2>/dev/null || stat -f %Lp "$CA_DIR/ca.key" 2>/dev/null)
if [ "$PERMS" = "600" ]; then
    echo "OK"
else
    echo "WARN: $PERMS (ожидается 600)"
fi

# 8. Тестовый выпуск сертификата
echo -n "[8] Тестовый выпуск сертификата: "
TEMP_DIR=$(mktemp -d)
openssl genrsa -out "$TEMP_DIR/test.key" 2048 2>/dev/null
openssl req -new -key "$TEMP_DIR/test.key" -out "$TEMP_DIR/test.csr" \
    -subj "/CN=self-test.local" 2>/dev/null

cd "$CA_DIR"
if openssl ca -config openssl.cnf -in "$TEMP_DIR/test.csr" -out "$TEMP_DIR/test.crt" \
    -extensions v3_req -notext -batch 2>/dev/null; then
    echo "OK"
    # Верификация выпущенного сертификата
    echo -n "[9] Верификация тестового сертификата: "
    if openssl verify -CAfile "$CA_DIR/ca.crt" "$TEMP_DIR/test.crt" | grep -q "OK"; then
        echo "OK"
    else
        echo "FAIL"; ERRORS=$((ERRORS+1))
    fi
else
    echo "FAIL (подпись)"; ERRORS=$((ERRORS+1))
fi

# Очистка
rm -rf "$TEMP_DIR"

echo "=== Результат: $ERRORS ошибок ==="
exit $ERRORS
```

### Параллельная подпись с flock

При автоматизации (Ansible, CI/CD) параллельные вызовы `openssl ca` могут вызвать блокировку `index.txt`. Решение — обёртка с `flock`:

```bash
# sign_cert.sh — подпись с блокировкой (безопасна для параллельных вызовов)
#!/bin/bash
set -euo pipefail

CA_DIR="/opt/ca"
LOCK_FILE="$CA_DIR/db/index.lock"
CSR_FILE="$1"
OUTPUT_FILE="$2"

(
    flock -n 200 || { echo "ERROR: CA is busy, try later"; exit 1; }

    cd "$CA_DIR"
    openssl ca -config openssl.cnf \
        -in "$CSR_FILE" -out "$OUTPUT_FILE" \
        -extensions v3_req -notext -batch

) 200>"$LOCK_FILE"
```

Использование в Ansible:

```yaml
- name: Sign certificate (with lock)
  ansible.builtin.command: >
    /opt/scripts/sign_cert.sh
    {{ item.csr_path }}
    {{ item.cert_path }}
  loop: "{{ certificate_requests }}"
  throttle: 1  # Ограничение: 1 операция за раз
```

### Логирование и аудит операций CA

#### Встроенный аудит через index.txt

`index.txt` уже содержит журнал всех операций (выпуск, отзыв). Для расширенного аудита:

```bash
# Просмотр всех выпущенных сертификатов
awk '$1 == "V" {print $3, $5}' ca/db/index.txt
# → 0A1B2C3D /C=RU/ST=Moscow/O=Org/CN=service.local

# Просмотр отозванных
awk '$1 == "R" {print $3, $6}' ca/db/index.txt
# → 4E5F6A7B /C=RU/ST=Moscow/O=Org/CN=revoked.local

# Статистика
echo "Выдано: $(grep -c "^V" ca/db/index.txt)"
echo "Отозвано: $(grep -c "^R" ca/db/index.txt)"
echo "Истекло: $(grep -c "^E" ca/db/index.txt)"
```

#### Перенаправление логов OpenSSL в syslog

OpenSSL не пишет в syslog напрямую, но можно обернуть вызов:

```bash
# sign_with_audit.sh
#!/bin/bash
CA_DIR="/opt/ca"
LOG_TAG="openssl-ca"

log_event() {
    logger -t "$LOG_TAG" "$1"
}

CSR="$1"
OUTPUT="$2"
OPERATOR=$(whoami)

log_event "START_SIGN operator=$OPERATOR csr=$CSR"

cd "$CA_DIR"
if openssl ca -config openssl.cnf -in "$CSR" -out "$OUTPUT" \
    -extensions v3_req -notext -batch 2>&1; then
    SERIAL=$(openssl x509 -in "$OUTPUT" -noout -serial | cut -d= -f2)
    log_event "SUCCESS_SIGN serial=$SERIAL output=$OUTPUT operator=$OPERATOR"
else
    log_event "FAIL_SIGN csr=$CSR operator=$OPERATOR"
    exit 1
fi
```

Просмотр логов:

```bash
journalctl -t openssl-ca --since "1 hour ago"
# → START_SIGN operator=root csr=/tmp/service.csr
# → SUCCESS_SIGN serial=0A1B2C3D output=/tmp/service.crt operator=root
```

### Интеграция с Nginx (пример конфига)

После выпуска сертификата через ваш одноуровневый CA, настройте Nginx:

```nginx
# /etc/nginx/conf.d/service.local.conf

server {
    listen 443 ssl http2;
    server_name service.local;

    ssl_certificate     /etc/nginx/ssl/service.crt;   # Leaf-сертификат
    ssl_certificate_key /etc/nginx/ssl/service.key;   # Приватный ключ

    # Корневой CA для проверки клиентских сертификатов (mTLS)
    # ssl_client_certificate /etc/nginx/ssl/ca.crt;
    # ssl_verify_client on;

    # Hardened TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # OCSP Stapling (для публичных CA; для внутреннего CA не применимо)
    # ssl_stapling on;
    # ssl_stapling_verify on;
    # ssl_trusted_certificate /etc/nginx/ssl/ca.crt;
    # resolver 8.8.8.8 8.8.4.4 valid=300s;

    # CRL для проверки отозванных сертификатов (mTLS)
    # ssl_crl /etc/nginx/ssl/crl.pem;

    location / {
        proxy_pass http://backend;
    }
}

# Редирект HTTP → HTTPS
server {
    listen 80;
    server_name service.local;
    return 301 https://$host$request_uri;
}
```

#### Проверка конфигурации

```bash
# Синтаксис
nginx -t

# Проверка TLS через s_client
openssl s_client -connect service.local:443 -servername service.local \
    -CAfile /etc/nginx/ssl/ca.crt </dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)
```

### Wildcard-сертификаты через одноуровневый CA

Wildcard-сертификаты (`*.example.com`) выпускаются аналогично обычным, но SAN должен содержать wildcard:

```ini
[alt_names]
DNS.1 = *.service.local
DNS.2 = service.local        # Корневой домен (wildcard его не покрывает)
IP.1  = 10.0.5.10
```

Подпись:

```bash
cd ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_req -notext -batch
```

Проверка:

```bash
openssl x509 -in service.crt -noout -text | grep -A 2 "Subject Alternative Name"
# → X509v3 Subject Alternative Name:
# →     DNS:*.service.local, DNS:service.local, IP Address:10.0.5.10
```

> **Ограничение wildcard:** покрывает только ОДИН уровень поддоменов:
> - `api.service.local` — доверяет (да)
> - `v2.api.service.local` — НЕ доверяет (нет)
> - `service.local` — НЕ доверяет (нет, нужен отдельный SAN)
>
> Для глубоких поддоменов перечисляйте их явно в SAN или выпускайте несколько сертификатов.

## Типичные ошибки и диагностика

### Ошибка: `unable to load private key` при импорте PKCS#12

**Причина:** Неверный пароль или повреждённый файл .p12.

**Диагностика:**
```bash
# Проверка содержимого PKCS#12
openssl pkcs12 -in service.p12 -info -nokeys
# Ввод пароля → отображение сертификатов
```

### Ошибка: `copy_extensions` не копирует SAN

**Причина:** Расширения SAN не были указаны в CSR или OpenSSL игнорирует их.

**Решение:** Убедитесь, что:
1. В CSR есть расширение SAN (через `-extfile` или OpenSSL config)
2. В `openssl.cnf` установлено `copy_extensions = copy` или `copyall`
3. При подписи через `openssl ca` НЕ указана `-extensions` секция (она перезапишет CSR)

### Ошибка: `database is locked` при параллельной подписи

**Причина:** Два процесса одновременно пытаются записать в `index.txt`.

**Решение:** Используйте `flock` (см. раздел «Параллельная подпись»).

## Рекомендации и лучшие практики

- **PKCS#12:** всегда указывайте `-certfile ca.crt` при экспорте — это включает цепочку доверия в контейнер
- **Пароли:** в production не используйте `-passout pass:...` в командах (попадают в историю shell). Используйте переменные окружения или ввод пароля
- **policy_anything:** используйте для внутренних CA, где гибкость DN важнее строгой иерархии
- **copy_extensions:** для безопасности используйте `copy` (не `copyall`) и контролируйте расширения через секции `[v3_req]`
- **Wildcard:** всегда добавляйте корневой домен в SAN отдельно
- **Flock:** обязателен при автоматизации (Ansible, CI/CD, cron) для предотвращения гонки данных

## Очистка и откат изменений

```bash
# Удаление тестовых файлов конвертации
rm -f service.p12 service.der service-combined.pem

# Удаление тестовых сертификатов, созданных self-test
rm -rf /tmp/self-test-*
```

## Дополнительная информация

### Связанные темы

- [Настройка CA](./ca_setup.md) — создание корневой инфраструктуры
- [Управление сертификатами](./service_certificate_management.md) — выпуск и отзыв
- [Утилиты и диагностика](./common_utilities.md) — проверка и отладка
- [Обзор PKI](../../../Concepts/pki_overview.md) — теория сертификатов
- [Диагностика SSL/TLS](../../ssl_certificate_diagnostics.md) — решение ошибок
- [TLS Hardening](../../../Networking/Protocols/HTTP/http_tls_hardening.md) — профили шифрования
