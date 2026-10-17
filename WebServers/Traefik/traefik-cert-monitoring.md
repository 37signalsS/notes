# Мониторинг сертификатов Traefik: expiration, ACME, proactive alerts

**Актуально для:** Traefik 3.x / 2.11+ / Prometheus Blackbox Exporter 0.25+ / Node Exporter 1.8+

## Определения

**Certificate Expiration Monitoring** — проактивный непрерывный контроль срока действия TLS-сертификатов с формированием ступенчатых предупреждений (warning/critical) задолго до наступления даты `notAfter`.

**ACME (Automated Certificate Management Environment)** — стандартизированный протокол (RFC 8555) для автоматического заказа, валидации и выпуска TLS-сертификатов центрами сертификации (Let's Encrypt, ZeroSSL).

**ACME Storage (`acme.json`)** — локальный файл Traefik в формате JSON с правами `0600`, используемый встроенным клиентом `lego` для хранения приватных ключей учетных записей, метаданных заказов и выпущенных сертификатов (в кодировке Base64).

**Prometheus Blackbox Exporter** — официальный инструмент синтетического мониторинга Prometheus, выполняющий внешнее TLS-рукопожатие с целевым хостом и вычисляющий метрику Unix-времени истечения ближайшего сертификата в цепочке (`probe_ssl_earliest_cert_expiry`).

**Textfile Collector** — режим работы `prometheus-node-exporter`, считывающий сгенерированные внешними скриптами `.prom`-файлы из локальной директории для экспорта пользовательских метрик хоста.

**Certificate Transparency (CT) Log** — публичный защищенный от перезаписи реестр (append-only log), в который центры сертификации обязаны вносить все выпущенные публичные сертификаты для аудита и обнаружения несанкционированного выпуска.

**OCSP Stapling** — механизм, при котором web-сервер при TLS-рукопожатии отдает клиенту подписанный центром сертификации ответ о статусе валидности сертификата, снижая нагрузку на OCSP-респондеры CA и ускоряя установление соединения.

---

## Архитектура и базовые концепции

### Встроенный ACME-клиент Traefik и его ограничения

Traefik содержит встроенный ACME-клиент на базе библиотеки `lego`. Процесс управления сертификатами в standalone-инсталляциях выглядит следующим образом:

```text
[ Let's Encrypt CA ] ◄──(1. HTTP-01 / TLS-ALPN-01 / DNS-01)──► [ Traefik Data Plane ]
        │                                                               │
(2. Выдача X.509)                                               (3. Запись сертификата)
        ▼                                                               ▼
[ In-Memory Cert Cache ] ───────────────────────────────► [ /var/lib/traefik/acme.json ]
        ▲                                                               │
        │                                                               │ (Чтение cron/timer)
[ Внешний TLS-клиент ] ◄──(4. Синтетический опрос 443)──► [ Blackbox Exporter / Script ]
                                                                        │
                                                                        ▼
                                                         [ Prometheus / Alertmanager ]
```

1. **Жизненный цикл:** При старте или поступлении нового роутера Traefik запрашивает сертификат у CA. При успешном прохождении challenge сертификат и закрытый ключ кодируются в Base64 и сохраняются в `acme.json`, а также помещаются в in-memory кэш TLS.
2. **Окно автоматического продления:** По умолчанию Traefik инициирует процедуру продления (renewal) сертификата ровно за **30 дней** до истечения срока его действия (для 90-дневных сертификатов Let's Encrypt).
3. **Критическое ограничение Traefik OSS:** Traefik Open Source **не экспортирует нативные метрики истечения TLS-сертификатов** в эндпоинт `/metrics`. Встроенные метрики Traefik покрывают запросы, задержки, открытые соединения и статус перезагрузки конфигурации, но не мониторят даты окончания действия сертификатов.
4. **Архитектурный риск единой точки отказа:** Если процесс Traefik завис, поврежден файл `acme.json`, исчерпан лимит запросов к CA (rate limit) или сетевой экран блокирует валидационный порт 80/443, сертификаты перестанут продлеваться без генерации стандартных алертов на стороне самого прокси.

### Двухконтурная стратегия мониторинга SRE

Для исключения сбоев на production-окружениях применяется комбинированная двухуровневая модель:

| Контур | Уровень мониторинга | Инструмент | Контролируемый артефакт | Преимущества |
| :--- | :--- | :--- | :--- | :--- |
| **Blackbox (внешний)** | Сетевой (L7/TLS) | Prometheus Blackbox Exporter (`probe_ssl_earliest_cert_expiry`) | Реальный сертификат, отдаваемый клиенту на 443 порту | Проверяет полную цепочку: DNS, SNI, файрвол, Traefik TLS termination, промежуточные CA |
| **Whitebox (внутренний)** | Файловая система / Хост | Node Exporter Textfile Collector (`traefik_certificate_expiration_timestamp_seconds`) | Содержимое `acme.json` (локальные приватные ключи и сертификаты) | Выявляет непродленные сертификаты в хранилище даже при отсутствии входящего трафика или для внутренних SAN |
| **Логирование событий** | Системный лог Traefik | Vector / Promtail / journalctl | События `level=error msg="Error renewing certificate"` | Мгновенный сигнал об ошибках валидации до того, как истечет 30-дневное окно |

### Внутренний формат хранилища `acme.json`

Файл `acme.json` содержит иерархический JSON по имени настроенных резолверов (например, `letsencrypt`):

```json
{
  "letsencrypt": {
    "Account": {
      "Email": "admin@example.com",
      "Registration": {
        "body": {
          "status": "valid",
          "contact": ["mailto:admin@example.com"]
        },
        "uri": "https://acme-v02.api.letsencrypt.org/acme/acct/12345678"
      },
      "PrivateKey": "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...",
      "KeyType": "4096"
    },
    "Certificates": [
      {
        "domain": {
          "main": "example.com",
          "sans": ["app.example.com", "api.example.com"]
        },
        "certificate": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCg==",
        "key": "LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQo=",
        "Store": "default"
      }
    ]
  }
}
```

> [!IMPORTANT]
> Поле `certificate` в `acme.json` содержит цепочку сертификатов в кодировке **Base64**. Файл не содержит готового поля `notAfter` в формате открытого текста. Для извлечения срока действия требуется декодирование Base64 с последующим синтаксическим анализом X.509 структуры утилитой `openssl`.

---

## Практические сценарии

### Сценарий 1: Синтетический мониторинг внешних эндпоинтов через Prometheus Blackbox Exporter

Это основной метод SRE для непрерывной верификации отдачи TLS-сертификатов конечным пользователям.

#### 1. Конфигурация модуля в `/etc/prometheus/blackbox.yml`

```yaml
modules:
  http_2xx_tls:
    prober: http
    timeout: 10s
    http:
      method: GET
      valid_status_codes: [200, 301, 302, 401, 403, 404]
      preferred_ip_protocol: ip4
      tls_config:
        insecure_skip_verify: false
      headers:
        User-Agent: "Prometheus-Blackbox-Exporter"
```

#### 2. Конфигурация Scrape Job в `/etc/prometheus/prometheus.yml`

```yaml
scrape_configs:
  - job_name: 'blackbox-traefik-endpoints'
    metrics_path: /probe
    params:
      module: [http_2xx_tls]
    static_configs:
      - targets:
          - https://example.com
          - https://app.example.com
          - https://api.example.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115 # адрес Prometheus Blackbox Exporter
```

#### 3. Правила алертинга в `/etc/prometheus/rules/traefik_cert_alerts.yml`

```yaml
groups:
  - name: traefik.certificates.blackbox
    rules:
      - alert: TraefikSSLCertificateExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) < 86400 * 30
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "TLS-сертификат для {{ $labels.instance }} истекает менее чем через 30 дней"
          description: "Сертификат на хосте {{ $labels.instance }} истекает через {{ $value | humanizeDuration }}. Traefik должен был начать автопродление."

      - alert: TraefikSSLCertificateExpiringCritical
        expr: (probe_ssl_earliest_cert_expiry - time()) < 86400 * 7
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "КРИТИЧЕСКИЙ СРОК: TLS-сертификат для {{ $labels.instance }} истекает менее чем через 7 дней"
          description: "До истечения сертификата на {{ $labels.instance }} осталось {{ $value | humanizeDuration }}. Автопродление не сработало, требуется ручное вмешательство."

      - alert: TraefikSSLCertificateExpired
        expr: (probe_ssl_earliest_cert_expiry - time()) <= 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "TLS-сертификат для {{ $labels.instance }} ИСТЕК"
          description: "Сертификат на хосте {{ $labels.instance }} просрочен. Клиенты получают ошибку безопасности SSL."
```

---

### Сценарий 2: Whitebox-мониторинг локального `acme.json` через Textfile Collector

Поскольку Traefik не отдает метрики срока действия сертификатов из своего хранилища, на хосте с Traefik настраивается системный парсер, генерирующий метрики для Node Exporter.

#### 1. Скрипт парсера `/usr/local/bin/traefik-cert-exporter.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

ACME_FILE="/var/lib/traefik/acme.json"
TEXTFILE_DIR="/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE="${TEXTFILE_DIR}/traefik_certs.prom"
TEMP_FILE="${OUTPUT_FILE}.$$"

if [ ! -r "$ACME_FILE" ]; then
  echo "ОШИБКА: Файл $ACME_FILE не существует или недоступен для чтения" >&2
  exit 1
fi

mkdir -p "$TEXTFILE_DIR"

cat << 'EOF' > "$TEMP_FILE"
# HELP traefik_certificate_expiration_timestamp_seconds Expiration timestamp of TLS certificates in Traefik acme.json in seconds since unix epoch
# TYPE traefik_certificate_expiration_timestamp_seconds gauge
EOF

# Извлечение резолвера, основного домена, SAN и закодированного сертификата
jq -r 'to_entries[] | .key as $res | .value.Certificates[]? | "\($res) \(.domain.main) \((.domain.sans // []) | join(",")) \(.certificate)"' "$ACME_FILE" 2>/dev/null | while read -r resolver main_domain sans cert_b64; do
  [ -z "$cert_b64" ] && continue

  # Декодирование X.509 и получение даты окончания
  not_after=$(echo "$cert_b64" | base64 -d 2>/dev/null | openssl x509 -enddate -noout 2>/dev/null | cut -d= -f2 || true)
  
  if [ -n "$not_after" ]; then
    expiry_epoch=$(date -d "$not_after" +%s 2>/dev/null || true)
    if [ -n "$expiry_epoch" ]; then
      echo "traefik_certificate_expiration_timestamp_seconds{resolver=\"${resolver}\",domain=\"${main_domain}\",sans=\"${sans}\"} ${expiry_epoch}" >> "$TEMP_FILE"
    fi
  fi
done

mv -f "$TEMP_FILE" "$OUTPUT_FILE"
chmod 644 "$OUTPUT_FILE"
```

Сделать скрипт исполняемым:
```bash
sudo chmod 750 /usr/local/bin/traefik-cert-exporter.sh
```

#### 2. Юнит systemd `/etc/systemd/system/traefik-cert-exporter.service`

```ini
[Unit]
Description=Traefik acme.json Certificate Expiration Exporter
After=network.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/traefik-cert-exporter.sh
```

#### 3. Таймер systemd `/etc/systemd/system/traefik-cert-exporter.timer`

```ini
[Unit]
Description=Run Traefik Certificate Exporter every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Активация таймера:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now traefik-cert-exporter.timer
sudo systemctl start traefik-cert-exporter.service
# Проверка сгенерированного файла:
cat /var/lib/node_exporter/textfile_collector/traefik_certs.prom
# → traefik_certificate_expiration_timestamp_seconds{resolver="letsencrypt",domain="example.com",sans="app.example.com"} 1782419000
```

#### 4. Правила алертинга для метрик Textfile Collector

```yaml
groups:
  - name: traefik.certificates.storage
    rules:
      - alert: TraefikStorageCertificateExpiringWarning
        expr: (traefik_certificate_expiration_timestamp_seconds - time()) < 86400 * 30
        for: 2h
        labels:
          severity: warning
        annotations:
          summary: "Сертификат для {{ $labels.domain }} в acme.json истекает менее чем через 30 дней"
          description: "Сертификат резолвера {{ $labels.resolver }} для домена {{ $labels.domain }} истекает через {{ $value | humanizeDuration }}."

      - alert: TraefikStorageCertificateExpiringCritical
        expr: (traefik_certificate_expiration_timestamp_seconds - time()) < 86400 * 7
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "Критический срок действия сертификата {{ $labels.domain }} в хранилище"
          description: "Сертификат {{ $labels.domain }} истекает через {{ $value | humanizeDuration }}. Процесс продления Traefik не сработал."
```

---

### Сценарий 3: Мониторинг ошибок ACME в системных логах Traefik

Если Traefik не может продлить сертификат из-за ошибки сети или проверки challenge, ошибки сразу появляются в журнале Traefik.

#### Настройка структурированных логов в `traefik.yml`

```yaml
log:
  level: INFO       # для отладки ACME временно переключается в DEBUG
  format: json      # json предпочтителен для централизованного сбора

accessLog:
  filePath: /var/log/traefik/access.log
  format: json
```

#### Парсинг логов через Promtail / Vector или поиск через systemd

Ключевые сигнатуры ошибок в логах Traefik:
- `cannot obtain certificate`
- `acme: error: 429` (превышение rate limit)
- `Error renewing certificate from LE`
- `acme: Could not find solver for challenge`
- `error: one or more domains had a problem`

Пример правила для Loki / Vector / Log-мониторинга:

```yaml
- alert: TraefikACMERenewalFailure
  expr: |
    increase({unit="traefik.service"} |= "Error renewing certificate" [1h]) > 0
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Сбой автоматического продления сертификата в Traefik"
    description: "В логах Traefik зафиксированы ошибки обновления сертификатов ACME."
```

---

### Сценарий 4: Предотвращение исчерпания ACME Rate Limits через Staging CA

Одной из главных причин непродления сертификатов является попадание под лимиты Let's Encrypt:
- **Лимит на выпуск:** 50 сертификатов на зарегистрированный домен (Registered Domain) в неделю.
- **Лимит на дубликаты:** 5 идентичных сертификатов в неделю.
- **Лимит на сбои (Failed Validation):** 5 ошибок валидации на аккаунт/хост в час.

#### Конфигурация Staging-резолвера для предварительной отладки

```yaml
# /etc/traefik/traefik.yml
certificatesResolvers:
  le-staging:
    acme:
      email: admin@example.com
      storage: /var/lib/traefik/acme-staging.json
      caServer: https://acme-staging-v02.api.letsencrypt.org/directory
      httpChallenge:
        entryPoint: web

  le-prod:
    acme:
      email: admin@example.com
      storage: /var/lib/traefik/acme.json
      caServer: https://acme-v02.api.letsencrypt.org/directory
      httpChallenge:
        entryPoint: web
```

Порядок безопасного ввода в эксплуатацию:
1. Назначить роутеру резолвер `le-staging`.
2. Убедиться, что выдан временный недоверенный сертификат `Fake LE Intermediate X1`, а в логах Traefik отсутствуют ошибки challenge.
3. Переключить роутер на резолвер `le-prod`.

---

### Сценарий 5: Мониторинг в кластерной среде Kubernetes (cert-manager + Traefik)

В High Availability инсталляциях на bare-metal встроенный клиент Traefik `acme.json` не поддерживает распределенные блокировки между несколькими репликами. Поэтому управление сертификатами делегируется `cert-manager`, а Traefik монтирует готовые `Secret` (подробнее см. [Автоматический TLS с cert-manager и Traefik IngressRoute](./traefik-cert-manager-ingressroute-tls.md)).

В такой архитектуре метрики собираются напрямую с контроллера `cert-manager`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-traefik-alerts
  namespace: cert-manager
spec:
  groups:
  - name: cert-manager.rules
    rules:
    - alert: CertManagerCertExpirySoon
      expr: |
        (certmanager_certificate_expiration_timestamp_seconds - time()) < (30 * 86400)
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Сертификат cert-manager {{ $labels.name }} истекает через 30 дней"
        description: "Сертификат {{ $labels.name }} в namespace {{ $labels.namespace }} истекает через {{ $value | humanizeDuration }}."

    - alert: CertManagerCertRenewalFailed
      expr: |
        certmanager_certificate_ready_status{condition="False"} == 1
      for: 30m
      labels:
        severity: critical
      annotations:
        summary: "Сбой выпуска или готовности сертификата cert-manager"
        description: "Сертификат {{ $labels.name }} в namespace {{ $labels.namespace }} находится в состоянии Ready=False."
```

---

### Сценарий 6: Маршрутизация уведомлений в Alertmanager

Конфигурация Alertmanager (`/etc/alertmanager/alertmanager.yml`) для многоуровневого оповещения:

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
  receiver: 'sysadmin-chat'
  routes:
    - match:
        severity: critical
      receiver: 'pager-oncall'
      repeat_interval: 2h
    - match:
        severity: warning
      receiver: 'sysadmin-chat'
      repeat_interval: 24h

receivers:
  - name: 'sysadmin-chat'
    webhook_configs:
      - url: 'http://alert-gateway.local:8080/alerts/telegram'
        send_resolved: true

  - name: 'pager-oncall'
    webhook_configs:
      - url: 'http://alert-gateway.local:8080/alerts/critical-pager'
        send_resolved: true
```

---

## Операции и команды

### 1. Извлечение и аудит всех сертификатов из `acme.json`

Вывести список всех доменов, SAN и точных дат окончания действия сертификатов:

```bash
sudo jq -r 'to_entries[] | .key as $res | .value.Certificates[]? | 
  "Резолвер: \($res) | Домен: \(.domain.main) | SANs: \((.domain.sans // []) | join(", "))\n" + 
  ("Срок действия: " + (.certificate | @base64d | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)) + "\n---"' \
  /var/lib/traefik/acme.json
# → Резолвер: letsencrypt | Домен: example.com | SANs: app.example.com, api.example.com
# → Срок действия: Nov 24 14:22:10 2026 GMT
# → ---
```

### 2. Проверка активного сертификата на сетевом сокете

Проверка сертификата, который Traefik отдает в текущий момент на 443 порту:

```bash
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -dates -subject -issuer
# → notBefore=Aug 26 14:22:10 2026 GMT
# → notAfter=Nov 24 14:22:10 2026 GMT
# → subject=CN = app.example.com
# → issuer=C = US, O = Let's Encrypt, CN = R3
```

Проверка поддержки и статуса OCSP Stapling:

```bash
echo | openssl s_client -connect app.example.com:443 -servername app.example.com -status 2>/dev/null | grep -A 17 "OCSP response"
# → OCSP Response Status: successful (0x0)
# → Cert Status: good
```

### 3. Проверка прав и целостности файла `acme.json`

```bash
# Проверка прав (должно быть строго 0600)
stat -c "%a %U:%G" /var/lib/traefik/acme.json
# → 600 traefik:traefik

# Исправление прав при ошибке:
sudo chown traefik:traefik /var/lib/traefik/acme.json
sudo chmod 600 /var/lib/traefik/acme.json

# Проверка синтаксической валидности JSON:
jq empty /var/lib/traefik/acme.json && echo "JSON OK" || echo "JSON CORRUPTED"
# → JSON OK
```

### 4. Мониторинг системных логов ACME

```bash
# Для systemd bare-metal сервиса:
journalctl -u traefik -f --grep "acme|lego|certificate"

# Для Docker Compose инсталляции:
docker compose -f /opt/traefik/docker-compose.yml logs -f traefik | grep -iE "acme|certificate|lego"
```

---

## Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Traefik не стартует или игнорирует ACME** | Некорректные права на `acme.json` (отличные от `0600`) | `stat -c "%a" /var/lib/traefik/acme.json` возвращает `644` или `755`. В логе: `permissions ... are too open, it should be 0600` | Выполнить `sudo chmod 600 /var/lib/traefik/acme.json` и `sudo chown traefik:traefik`. |
| **Сертификат не продлевается за 30 дней** | Заблокирован входящий трафик на 80 порт (HTTP-01) или фаервол фильтрует ACME | `curl -I http://domain/.well-known/acme-challenge/test`. В логе: `Cannot obtain certificate ... connection refused / timeout` | Открыть порт 80 TCP в iptables/nftables. Проверить маршрутизацию `entryPoint: web`. |
| **Ошибка 429 Too Many Requests (Rate Limit)** | Превышен лимит запросов Let's Encrypt (50 сертификатов в неделю или 5 сбоев в час) | В логе: `acme: error: 429: urn:ietf:params:acme:error:rateLimited` | Временно переключить `caServer` на staging. Дождаться сброса лимита скользящего окна (до 7 дней). |
| **`acme.json` пуст или перезаписан (`{}`)** | Запуск нескольких реплик Traefik с общим файлом или сбой диска | `jq . /var/lib/traefik/acme.json`. Отсутствуют ключи резолверов | Восстановить `acme.json` из резервной копии. В HA-окружениях перейти на cert-manager или DNS-01. |
| **Браузер выдает `SEC_ERROR_UNKNOWN_ISSUER`** | Traefik отдает дефолтный самоподписанный сертификат (TRAEFIK DEFAULT CERT) | `openssl s_client -connect host:443` показывает `issuer=CN = TRAEFIK DEFAULT CERT` | Сертификат еще не выпущен или роутер не привязан к TLS-резолверу (`tls.certresolver=letsencrypt`). |
| **Сбой TLS-ALPN-01 challenge** | Перед Traefik стоит промежуточный L7 прокси/балансировщик, терминальный по HTTPS | Проверка протокола ALPN: `openssl s_client -alpn acme-tls/1` | Использовать HTTP-01 challenge или пробросить чистый TCP (L4 SNI passthrough) до Traefik. |
| **Ошибки валидации даты (`clock skew`)** | Рассинхронизация системного времени на сервере | `timedatectl status` показывает `NTP service: inactive` или `System clock synchronized: no` | Настроить и запустить службу синхронизации времени: `sudo systemctl enable --now chrony` или `systemd-timesyncd`. |

---

## Лучшие практики (Best Practices)

1. **Обязательный двухконтурный контроль:** Не полагайтесь на то, что Traefik автоматически продлит все сертификаты. Всегда комбинируйте внешний мониторинг (Prometheus Blackbox Exporter) и внутренний аудит хранилища (Textfile Collector).
2. **Ступенчатые пороги алертинга:**
   - **30 дней (`Warning`):** Момент, когда Traefik начинает фоновые попытки продления. Предупреждение инженерам о начале окна продления.
   - **7 дней (`Critical`):** Признак блокирующей проблемы (ошибка сети, rate limit, битый challenge). Требует немедленного вмешательства до выключения продакшена.
3. **Бекап файла `acme.json`:** Организуйте регулярное атомарное резервное копирование `acme.json` (например, `cp -a /var/lib/traefik/acme.json /var/backups/traefik/acme.json.$(date +%F)`). Утрата файла при сотнях доменов приведет к мгновенной блокировке по лимитам Let's Encrypt при попытке перевыпуска.
4. **Запрет совместного использования `acme.json` (Shared Storage):** Никогда не монтируйте один и тот же файл `acme.json` через NFS/CIFS в несколько экземпляров Traefik OSS. Это приводит к гонкам записи и безвозвратному повреждению базы ключей.
5. **Изоляция Staging-окружения:** Все эксперименты с маршрутами, доменами и конфигурацией challenge проводите исключительно на `https://acme-staging-v02.api.letsencrypt.org/directory`.
6. **Контроль прав доступа:** Регулярно валидируйте маску доступа к `acme.json`. Файл содержит незашифрованные закрытые ключи RSA/ECDSA; права `0600` и владелец `traefik` должны быть зафиксированы в скриптах деплоя.

---

## Дополнительные материалы

- [Traefik: Наблюдаемость, метрики и логи](./traefik-observability.md) — конфигурация Prometheus-метрик запросов, latency и access-логов.
- [Автоматический TLS с cert-manager и Traefik IngressRoute](./traefik-cert-manager-ingressroute-tls.md) — архитектура выпуска сертификатов в Kubernetes без `acme.json`.
- [Traefik: Отказоустойчивость и Disaster Recovery](./traefik-disaster-recovery.md) — регламенты резервного копирования и восстановления `acme.json`.
- [Traefik: Архитектура высокой доступности (HA)](./traefik-high-availability.md) — решения для кластеров высокой доступности.
- [Blackbox Exporter: Метрики и алертинг](../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md) — детальное описание синтетических проверок `probe_ssl_earliest_cert_expiry`.
- [Предотвращение истечения SSL-сертификатов](../../Kubernetes/Operations/ssl_expiration_prevention.md) — общесистемный подход к ротации сертификатов в инфраструктуре.
