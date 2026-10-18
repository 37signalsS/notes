# Интеграция логов CA с SIEM

**Актуально для:** OpenSSL 3.0+ (PKI 2026; Linux: rsyslog/syslog-ng, auditd, Filebeat/Fluentd)

## Определения

**SIEM (Security Information and Event Management)** — система сбора, нормализации и анализа событий безопасности в реальном времени. Собирает логи из разных источников, коррелирует их и генерирует алерты при обнаружении подозрительной активности.

**CEF (Common Event Format)** — формат логов от ArcSight (Micro Focus), стандарт для SIEM-систем. Содержит_vendor, product, version, signature ID, severity и расширения (key=value).

**LEEF (Log Event Enhanced Format)** — формат логов от IBM QRadar, альтернатива CEF.

**Audit Trail (Аудиторский след)** — последовательность событий, документирующая все операции с сертификатами: выпуск, ротация, отзыв, изменение конфигурации CA.

**index.txt** — текстовая база данных OpenSSL CA, содержащая записи о всех выпущенных и отозванных сертификатах. Формат колонок: `статус дата_истечения дата_отзыва serial placeholder DN`.

> Базовые концепции PKI описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**. Архитектура двухуровневого CA — в **[обзоре двухуровневого CA](./overview.md)**.

## Базовые концепции

### Зачем логировать операции CA

В production-среде каждый оператор, имеющий доступ к Intermediate CA, теоретически может выпустить сертификат для любого домена. Логирование обеспечивает:

1. **Детерминность:** каждый выпуск сертификата документирован с указанием оператора, времени и целевого DN.
2. **Обнаружение инцидентов:** немедленное уведомление при попытке выпуска сертификата для несанкционированного домена или при отзыве сертификата.
3. **Соответствие аудиту:** для регуляторных требований (PCI DSS, ISO 27001, ГОСТ) необходим аудит всех операций с криптографическими ключами.
4. **Forensic analysis:** при компрометации ключа позволяет восстановить хронологию событий.

### Источники событий в двухуровневом CA

| Источник | Что логировать | Формат |
|:---|:---|:---|
| **index.txt** | Выпуск, отзыв, истечение сертификатов | Текст OpenSSL (V/R/E + serial + DN) |
| **Обёртки скриптов (logger)** | Оператор, время, результат подписи | Syslog (RFC 3164/5424) |
| **OpenSSL stderr** | Ошибки при подписи, невалидные CSR | Текст |
| **Файловая система** | Права доступа к `ca.key`, время модификации | inotify / auditd |
| **HSM** | Операции с аппаратным модулем | PKCS#11 audit log |

### Формат записей в index.txt

```
# Статус  Дата_истечения  Дата_отзова  Serial  placeholder  DN
V    260101120000Z           0A1B2C3D    unknown /C=RU/ST=Moscow/O=Org/CN=service.local
R    260101120000Z    250315120000Z 0A1B2C3D    unknown /C=RU/ST=Moscow/O=Org/CN=revoked.local
```

- **V** (Valid) — сертификат действителен
- **R** (Revoked) — сертификат отозван
- **E** (Expired) — сертификат истёк

### Критические события для алертинга

| Событие | Severity | Описание |
|:---|:---|:---|
| `CA_KEY_ACCESS` | Critical | Доступ к `ca.key` или `intermediate.key` |
| `SIGN_SUCCESS` | Info | Успешная подпись сертификата |
| `SIGN_FAILURE` | Warning | Ошибка при подписи (невалид CSR, неверные расширения) |
| `REVOKE` | Critical | Отзыв сертификата |
| `CRL_GENERATED` | Info | Генерация нового CRL |
| `CA_ROTATION` | Critical | Ротация Intermediate CA |
| `POLICY_VIOLATION` | Critical | Попытка нарушения политики (например, подписание CA-сертификата через intermediate) |
| `UNAUTHORIZED_ACCESS` | Critical | Попытка доступа к файлам CA без authorized пользователя |

## Предварительные требования

### Программное обеспечение

- **rsyslog** или **syslog-ng** — сбор логов на промежуточном CA
- **auditd** — аудит файловой системы (Linux audit subsystem)
- **Filebeat** или **Fluentd** — форвардинг логов в SIEM
- **curl** или **logger** — отправка событий

### Доступ к SIEM

- Адрес SIEM-сервера (IP:порт)
- Протокол: TCP/UDP 514 (syslog), TCP 5044 (Beats), HTTP(S) (webhook)
- API-ключ или сертификат аутентификации

## Практические сценарии

### 1. Логирование через обёртку над openssl ca

OpenSSL не пишет в syslog напрямую. Используйте скрипт-обёртку:

```bash
#!/bin/bash
# /opt/scripts/sign_with_audit.sh
set -euo pipefail

CA_DIR="/opt/pki/intermediate-ca"
LOG_TAG="openssl-ca"
OPERATOR="${SUDO_USER:-$(whoami)}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log_event() {
    local severity="$1"
    local message="$2"
    logger -t "$LOG_TAG" "severity=$severity $message operator=$OPERATOR timestamp=$TIMESTAMP"
}

CSR="${1:?Укажите путь к CSR}"
OUTPUT="${2:?Укажите путь для выходного сертификата}"
DAYS="${3:-365}"
SAN_DNS="${4:-}"
SAN_IP="${5:-}"

# Лог начала операции
log_event "INFO" "START_SIGN csr=$CSR output=$OUTPUT days=$DAYS san_dns=$SAN_DNS san_ip=$SAN_IP"

# Создание временного конфига с SAN (если указан)
TEMP_CNF=""
if [ -n "$SAN_DNS" ] || [ -n "$SAN_IP" ]; then
    TEMP_CNF=$(mktemp /tmp/v3_ext_XXXXXX.cnf)
    cat > "$TEMP_CNF" <<EOF
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
    EXT_ARGS="-extfile $TEMP_CNF -extensions v3_server_cert"
else
    EXT_ARGS="-extensions v3_server_cert"
fi

# Выполнение подписи
cd "$CA_DIR"
if openssl ca -config openssl.cnf -in "$CSR" -out "$OUTPUT" \
    $EXT_ARGS -days "$DAYS" -md sha512 -notext -batch 2>&1; then
    SERIAL=$(openssl x509 -in "$OUTPUT" -noout -serial | cut -d= -f2)
    SUBJECT=$(openssl x509 -in "$OUTPUT" -noout -subject | sed 's/^subject=//')
    log_event "INFO" "SIGN_SUCCESS serial=$SERIAL subject=$SUBJECT output=$OUTPUT"
    echo "OK: $OUTPUT (serial=$SERIAL)"
else
    log_event "ERROR" "SIGN_FAILURE csr=$CSR reason=openssl_ca_error"
    echo "FAIL: ошибка подписи" >&2
    [ -n "$TEMP_CNF" ] && rm -f "$TEMP_CNF"
    exit 1
fi

# Очистка
[ -n "$TEMP_CNF" ] && rm -f "$TEMP_CNF"
```

Ожидаемый результат — событие в syslog и на экран:

```text
# → OK: /certs/service.local.crt (serial=0A1B2C3D...)
# → syslog: severity=info event=SIGN_SUCCESS serial=0A1B2C3D subject=/C=RU/.../CN=service.local output=/certs/service.local.crt operator=root timestamp=2026-...
```

### 2. Логирование отзыва сертификатов

```bash
#!/bin/bash
# /opt/scripts/revoke_with_audit.sh
set -euo pipefail

CA_DIR="/opt/pki/intermediate-ca"
LOG_TAG="openssl-ca"
OPERATOR="${SUDO_USER:-$(whoami)}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log_event() {
    logger -t "$LOG_TAG" "severity=$1 $2 operator=$OPERATOR timestamp=$TIMESTAMP"
}

CERT="${1:?Укажите путь к сертификату для отзыва}"
REASON="${2:-unspecified}"

# Проверка сертификата перед отзывом
SERIAL=$(openssl x509 -in "$CERT" -noout -serial | cut -d= -f2)
SUBJECT=$(openssl x509 -in "$CERT" -noout -subject | sed 's/^subject=//')

log_event "CRITICAL" "REVOKE_ATTEMPT serial=$SERIAL subject=$SUBJECT reason=$REASON cert=$CERT"

cd "$CA_DIR"
if openssl ca -config openssl.cnf -revoke "$CERT" -crl_reason "$REASON" 2>&1; then
    log_event "CRITICAL" "REVOKE_SUCCESS serial=$SERIAL reason=$REASON"
    # Генерация нового CRL
    openssl ca -config openssl.cnf -gencrl -out crl/crl.pem 2>&1
    log_event "INFO" "CRL_GENERATED new_crl=crl/crl.pem"
    echo "OK: сертификат $SERIAL отозван, CRL обновлён"
else
    log_event "ERROR" "REVOKE_FAILURE serial=$SERIAL reason=openssl_ca_error"
    echo "FAIL: ошибка отзыва" >&2
    exit 1
fi
```

### 3. Аудит файловой системы через auditd

Настройте аудит доступа к критическим файлам CA:

```bash
# /etc/audit/rules.d/pki-audit.rules

# Аудит доступа к приватному ключу Root CA
-w /opt/pki/root-ca/ca.key -p rwxa -k pki-root-key

# Аудит доступа к приватному ключу Intermediate CA
-w /opt/pki/intermediate-ca/intermediate.key -p rwxa -k pki-intermediate-key

# Аудит модификации index.txt (базы данных сертификатов)
-w /opt/pki/intermediate-ca/db/index.txt -p wa -k pki-index

# Аудит модификации конфигурации
-w /opt/pki/intermediate-ca/openssl.cnf -p wa -k pki-config

# Аудит CRL
-w /opt/pki/intermediate-ca/crl/ -p wa -k pki-crl
```

Применение правил:

```bash
# Загрузка правил
sudo augenrules --load

# Проверка активных правил
sudo auditctl -l | grep pki

# Просмотр аудит-событий
sudo ausearch -k pki-root-key --start today
sudo ausearch -k pki-intermediate-key --start today
sudo ausearch -k pki-index --start today
```

### 4. Форвардинг логов через rsyslog

#### Конфигурация rsyslog на промежуточном CA

```bash
# /etc/rsyslog.d/50-pki-ca.conf

# Шаблон для syslog-полей PKI (SIEM разбирает key=value на стороне приёмщика)
template(name="PKI_CEF" type="string"
    string="<%pri%>%timestamp:::date-rfc3339% %hostname% %syslogtag% %msg%")

# Отправка логов openssl-ca в SIEM
if $programname == 'openssl-ca' then {
    action(type="omfwd"
           target="siem.example.com"
           port="514"
           protocol="tcp"
           template="PKI_CEF"
           queue.type="LinkedList"
           queue.filename="pki_forward"
           queue.maxDiskSpace="1g"
           queue.saveOnShutdown="on"
           action.resumeRetryCount="-1")
    stop
}

# Локальное сохранение (бэкап)
if $programname == 'openssl-ca' then {
    action(type="omfile" file="/var/log/pki-ca.log" template="PKI_CEF")
}
```

#### Конфигурация rsyslog на Root CA (air-gapped)

На Root CA логи хранятся локально и копируются вручную:

```bash
# /etc/rsyslog.d/50-pki-root.conf

template(name="PKI_Root" type="string"
    string="%timestamp:::date-rfc3339% %hostname% %syslogtag% %msg%\n")

if $programname == 'openssl-ca' then {
    action(type="omfile" file="/var/log/pki-root-ca.log" template="PKI_Root"
           fileCreateMode="0600" dirCreateMode="0700")
}
```

### 5. Парсинг index.txt для SIEM

Скрипт для конвертации `index.txt` в структурированные события:

```bash
#!/bin/bash
# /opt/scripts/parse_index_to_syslog.sh
# Конвертирует index.txt в syslog-события для SIEM

INDEX_FILE="${1:-/opt/pki/intermediate-ca/db/index.txt}"
LOG_TAG="openssl-index"

while IFS= read -r line; do
    STATUS=$(echo "$line" | awk '{print $1}')
    EXPIRY=$(echo "$line" | awk '{print $2}')
    SERIAL=$(echo "$line" | awk '{print $4}')
    DN=$(echo "$line" | awk '{for(i=6;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ $//')

    case "$STATUS" in
        V) EVENT="CERT_VALID" ;;
        R) EVENT="CERT_REVOKED" ;;
        E) EVENT="CERT_EXPIRED" ;;
        *) EVENT="CERT_UNKNOWN" ;;
    esac

    logger -t "$LOG_TAG" "severity=info event=$EVENT serial=$SERIAL expiry=$EXPIRY dn=\"$DN\""
done < "$INDEX_FILE"
```

### 6. Пример алертинга в Prometheus (SIEM-интеграция)

```yaml
# prometheus-rules/pki-alerts.yml
groups:
  - name: pki_ca_alerts
    rules:
      # Отзыв сертификата — критический алерт
      - alert: CertificateRevoked
        expr: |
          increase(openssl_ca_revoke_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Отзыв сертификата"
          description: "Выполнен отзыв сертификата. Проверьте SIEM для деталей."

      # Ключевое событие: доступ к ca.key
      - alert: CAKeyAccessed
        expr: |
          increase(auditd_pki_root_key_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Доступ к корневому ключу CA"
          description: "Зафиксирован доступ к ca.key. Проверьте, authorized ли оператор."

      # Попытка нарушения политики
      - alert: CAPolicyViolation
        expr: |
          increase(openssl_ca_policy_violation_total[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Нарушение политики CA"
          description: "Попытка подписи сертификата с нарушением политики."
```

### 7. Проверка работоспособности интеграции

После настройки убедитесь, что события CA достигают SIEM и вызывают алерты:

```bash
# 1. Тестовое syslog-сообщение (имитирует событие CA)
logger -t openssl-ca "severity=info test_event=integration_check timestamp=$(date -u +%FT%TZ)"

# 2. Проверка локального rsyslog перед отправкой
sudo journalctl -u rsyslog -f --since "1 min ago" | grep openssl-ca
# → ожидается строка с test_event=integration_check

# 3. Проверка транспорта до SIEM (замените host:port)
sudo tcpdump -ni any port 514 | grep -i test_event
# → пакет UDP/TCP 514 с тестовым сообщением

# 4. Проверка аудита доступа к ключу
sudo bash -c 'cat /opt/pki/intermediate-ca/intermediate.key >/dev/null'
sudo ausearch -k pki-intermediate-key --start recent
# → событие типа PROCTITLE/PATH с именем файла ключа

# 5. Проверка, что алерт сработал в Prometheus
curl -s "http://prometheus:9090/api/v1/alerts" | grep -i certificate_revoked
# → активный алерт при on_error_rate > 0
```

Ожидаемый результат — каждое тестовое событие появляется в соответствующем модуле SIEM в течение 1–5 секунд.

## Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Логи не поступают в SIEM | rsyslog не запущен или неверный адрес назначения | Проверить `systemctl status rsyslog`, тестировать `logger -t openssl-ca test` |
| index.txt повреждён | Предыдущий `openssl ca` завершился аварийно | Восстановить из резервной копии или пересоздать (осторожно!) |
| auditd не фиксирует события | Правила не загружены или SELinux блокирует | Проверить `auditctl -l`, посмотреть `ausearch -m AVC` |
| Дублирование событий | Один источник логируется и в syslog, и в файл | Убрать дублирующий action в rsyslog.conf |
| Высокий объём логов | Логирование каждого `index.txt` lookup | Фильтровать по severity, логировать только write-операции |

## Рекомендации и лучшие практики

- **Минимальный набор для production:** логирование через обёртку (sign_with_audit.sh) + auditd для `ca.key` и `intermediate.key` + rsyslog forwarding в SIEM.
- **Не логируйте парольные фразы:** никогда не включайте passphrase в логи.
- **Раздельные каналы:** Root CA (air-gapped) хранит логи локально, Intermediate CA — форвардит в SIEM.
- **Регулярная ротация логов:** настройте logrotate для `/var/log/pki-ca.log`.
- **Корреляция событий:** настройте правила корреляции в SIEM для обнаружения аномалий (например, серия неудачных попыток подписи).
- **Бэкап index.txt:** регулярно копируйте `index.txt` и `serial` в защищённое хранилище.

## Дополнительная информация

### Связанные темы

- **[Настройка Root CA](./root_ca_setup.md)** — аудит операций корневого CA.
- **[Настройка Intermediate CA](./intermediate_ca_setup.md)** — логирование операций промежуточного CA.
- **[Обзор двухуровневого CA](./overview.md)** — жизненный цикл и аварийное реагирование.
- **[Логирование и аудит (single tier)](../single_tier/formats_and_advanced_config.md)** — пример syslog-обёртки для одноуровневого CA.
- **[Audit и compliance](../../../audit_and_compliance_overview.md)** — общие принципы аудита.
