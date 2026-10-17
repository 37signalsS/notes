# Анализ audit логов Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Audit Device (Устройство аудита)** — компонент Vault, записывающий все API-запросы и ответы. Поддерживает три типа: `file` (запись в файл), `syslog` (отправка в syslog), `socket` (TCP/UDP или Unix socket). Audit device гарантирует запись в хотя бы одно устройство — если все устройства недоступны, Vault отказывает в обслуживании запроса.

**Audit Log** — неизменяемый JSON-журнал всех операций Vault, содержащий хэшированные запросы и ответы. Позволяет отслеживать активность без раскрытия секретов. Каждая запись содержит `type` (`request`/`response`), `time` (ISO 8601), `auth`, `request`, `response`.

**HMAC Hashing** — хэширование чувствительных значений с использованием keyed hash (HMAC-SHA256) с солью. По умолчанию Vault хэширует все строковые значения в audit логах. `client_token`, `client_token_accessor`, `accessor` хэшируются, если `hmac_accessor=true` (поведение по умолчанию).

**Elide List Responses** — опция `elide_list_responses=true`, которая заменяет `keys` и `key_info` в LIST-ответах количеством объектов вместо полного списка. Снижает объём логов для больших ответов.

**Request Correlation** — связь запроса и ответа через `request.id`, который присутствует в обеих audit записях (`type: request` и `type: response`).

**Audit Log Entry Schema** — строго определённая схема JSON-объектов audit логов (см. [Auditing schema](https://developer.hashicorp.com/vault/docs/audit/schema)). Включает `auth`, `request`, `response`, `forwarded_from`, `time`, `type` объекты с фиксированными атрибутами.

**Forensic Analysis** — процесс расследования инцидентов на основе audit логов: поиск аномалий, трассировка цепочки доступа по Request ID, определение радиуса поражения.

**SIEM (Security Information and Event Management)** — платформа для централизованного сбора, анализа и корреляции событий безопасности (Splunk, ELK/Elasticsearch, Grafana Loki).

**Log Forwarding** — процесс отправки audit логов во внешнюю систему (SIEM, лог-агрегатор) для долговременного хранения и анализа.

**Log Rotation** — процесс вращения лог-файлов для предотвращения переполнения диска. Для file audit device используется logrotate с отправкой сигнала `SIGHUP` Vault'у для переоткрытия файла.

**Log Retention** — политика хранения audit логов. Compliance требует хранения не менее 1 года (PCI DSS, GDPR).

**Audit Log Metrics** — телеметрические метрики audit device: `vault.audit.log_request_failure`, `vault.audit.log_response_failure`, `vault.audit.{DEVICE}.log_request`, `vault.audit.{DEVICE}.log_response`.

## Архитектура и принцип работы

### Архитектура audit device

Vault отправляет каждую audit запись **во все включённые audit устройства** и гарантирует запись в **хотя бы одно**. Если все устройства недоступны — Vault отказывает в обслуживании запроса. Это делает audit device критически важным компонентом.

```text
[Request] → [Vault Core] → [Response]
                ↓
        ┌───────┴────────────────┐
        │  Audit Device 1       │
        │  (file)               │
        └───────────────────────┘
        ┌───────┴────────────────┐
        │  Audit Device 2       │
        │  (syslog/socket)      │
        └───────────────────────┘
```

### Различие: Audit Logs vs. Server Logs

| Тип | Что логирует | Куда пишет | Цель |
|-----|-------------|-----------|------|
| **Audit logs** | Все API-запросы и ответы (детали, хэши) | File/Syslog/Socket | Безопасность, compliance, forensic |
| **Server logs** | Ошибки процесса, предупреждения конфигурации, startup/shutdown | stdout/stderr | Операционная поддержка |

### Схема audit записи

Каждая audit запись — это JSON-объект с фиксированной схемой:

```json
{
  "type": "request",
  "time": "2025-06-04T20:02:46.117181Z",
  "auth": {
    "client_token": "hmac-sha256:c39c69748f0894cb4cd0333c779e72343ba45af287649d0fbcc37e9b079abe5d",
    "accessor": "hmac-sha256:3348fe9b24b078f97d747363dda2d55bb0445e90b512e9f68f48d289fed798b3",
    "display_name": "userpass-alice",
    "policies": ["default"],
    "policy_results": { "allowed": true, "granting_policies": [...] }
  },
  "request": {
    "id": "79cc9b26-488f-eabf-2a97-303ed3bef0d6",
    "operation": "read",
    "path": "auth/token/lookup-self",
    "remote_address": "127.0.0.1",
    "remote_port": 64199,
    "mount_accessor": "auth_token_d43d387d",
    "mount_type": "token",
    "data": { ... }
  },
  "forwarded_from": "",
  "error": ""
}
```

Полный схема audit записи определена в [Auditing schema](https://developer.hashicorp.com/vault/docs/audit/schema). Response-записи включают дополнительный объект `response` с `data`, `warnings`, `secret` (lease info), `wrap_info`.

### Хэширование чувствительных данных

По умолчанию Vault применяет HMAC-SHA256 с солью к строковым значениям в audit логах. Неприменяется к:

- Целочисленным и булевым значениям
- `request_uri`, `id`, `operation`, `path` (метаданные запроса)
- `mount_running_version`, `remote_address`, `remote_port`

Для вычисления хэша любого значения используется API `/sys/audit-hash`:

```bash
vault write sys/audit-hash/file input="my-secret-value"
# → Keys      Value
#   sum      hmac-sha256:abc123...
```

### Исключения из аудита

Vault **не аудитирует** следующие эндпоинты (ни запросы, ни ответы):

```
sys/init, sys/seal-status, sys/seal, sys/step-down, sys/unseal,
sys/leader, sys/health, sys/rekey/init, sys/rekey/update,
sys/rekey/verify, sys/rekey-recovery-key/init,
sys/rekey-recovery-key/update, sys/rekey-recovery-key/verify,
sys/storage/raft/bootstrap, sys/storage/raft/join,
sys/internal/ui/feature-flags
```

Кроме того, не аудитируются (при unauthenticated доступе):

```
sys/metrics, sys/pprof/*, sys/in-flight-req
```

Это означает, что операции инициализации, посадки, здоровья и Raft-бутстринга не попадают в audit логи.

## Настройка и развертывание

### Prerequisites

- Vault 1.16+ (для Enterprise-only фич: `exclude`, `filter`, `fallback`)
- Минимум 2 audit устройства на кластер
- Выделенный том/партиция для file audit device (иначе другие процессы могут заполнить диск)
- Сетевая доступность для syslog/socket (TCP-рекомендуется из-за размера аудит-записей)

### Сценарий 1: Настройка audit devices

#### Файловый audit device

```bash
# Включение файлового audit device с рекомендуемыми опциями
vault audit enable file \
  file_path=/var/log/vault/vault_audit.log \
  elide_list_responses=true \
  hmac_accessor=false \
  log_raw=false

# Проверка включённых устройств
vault audit list
# → Path      Type     Description
#   file/     file     file audit log
#   syslog/   syslog   syslog audit
```

Параметры конфигурации:

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|-------------|----------|
| `file_path` | string | (required) | Путь к файлу. Специальные значения: `stdout`, `discard` |
| `mode` | string | `"0600"` | Режим файла (octal, как chmod). `"0000"` — не изменять |
| `log_raw` | bool | `false` | Логировать raw значения без хэширования |
| `elide_list_responses` | bool | `false` | Заменять `keys` на количество объектов в LIST-ответах |
| `hmac_accessor` | bool | `true` | Хэшировать accessor токена |
| `prefix` | string | `""` | Префикс перед каждой строкой лога |

> **Важно:** `SIGHUP` сигнал заставляет file audit device закрыть и заново открыть файл — используется для log rotation.

#### Log rotation для file audit device

```bash
# /etc/logrotate.d/vault-audit
/var/log/vault/vault_audit.log {
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
    create 0640 vault vault
    sharedscripts
    postrotate
        # SIGHUP заставляет Vault переоткрыть файл
        kill -HUP $(cat /var/run/vault.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

#### Syslog audit device

```bash
# Включение syslog audit device
vault audit enable syslog tag="vault" facility="AUTH"

# Повышение размера буфера (Linux socket)
# sysctl -w net.core.wmem_default=262144
```

**Ограничения syslog:**
- Только Unix-системы
- Без TCP-конфигурации может возникнуть `message too long` для больших записей
- Рекомендуется TCP listener для передачи больших аудит-записей

#### Socket audit device

```bash
# TCP socket
vault audit enable socket address="tcp://127.0.0.1:5000" mode="tcp"

# Unix socket (более надёжный)
vault audit enable socket address="unix:///var/run/vault/audit.sock" mode="unix"
```

### Сценарий 2: Интеграция с SIEM и лог-агрегаторами

#### Filebeat → Elasticsearch / OpenSearch

```yaml
# /etc/filebeat/filebeat.yml
filebeat.inputs:
- type: log
  paths:
    - /var/log/vault/vault_audit.log
  json.keys_under_root: true
  json.add_error_key: true
  fields:
    service: vault
    log_type: audit

output.elasticsearch:
  hosts: ["elasticsearch.example.com:9200"]
  index: "vault-audit-%{+yyyy.MM.dd}"
```

#### Splunk Universal Forwarder

```ini
# /opt/splunkforwarder/etc/apps/splunk-uf-config/local/inputs.conf
[monitor:///var/log/vault/vault_audit.log]
sourcetype = vault:audit
index = security
```

#### Grafana Loki + Promtail

```yaml
# /etc/vault/policies/promtail-vault.yml
scrape_configs:
- job_name: vault
  static_configs:
  - targets:
      - localhost
    labels:
      job: vault
      __path__: /var/log/vault/vault_audit.log
```

#### journald (Kubernetes)

```bash
# file_path=stdout + префикс для разделения
vault audit enable file file_path=stdout prefix="AUDIT:"
```

### Сценарий 3: Анализ audit логов с jq

#### Поиск конкретных операций

```bash
# Все операции чтения секретов
jq 'select(.type=="request" and (.request.path | startswith("secret/data/")))' /var/log/vault/vault_audit.log

# Все операции аутентификации
jq 'select(.type=="request" and (.request.path | startswith("auth/")))' /var/log/vault/vault_audit.log

# Все ошибки 403 Forbidden
jq 'select(.type=="response" and .response.status_code == 403)' /var/log/vault/vault_audit.log

# Все запросы определённого токена (через accessor)
jq 'select(.auth.accessor == "hmac-sha256:abc...")' /var/log/vault/vault_audit.log

# Ротация секретов (database static role/rotate-root)
jq 'select(.type=="request" and (.request.path | startswith("database/rotate")))' /var/log/vault/vault_audit.log
```

#### Корреляция request/response через Request ID

```bash
# Поиск response для конкретного request
jq -r '.request.id' /var/log/vault/vault_audit.log | head -1 | xargs -I{} \
  jq --arg id "{}" 'select(.type=="response" and .request.id == $id)' /var/log/vault/vault_audit.log
```

#### Поиск аномалий (brute-force detection)

```bash
# Всплеск ошибок аутентификации
jq -r 'select(.type=="response" and (.request.path | startswith("auth/")) and .response.status_code != 200) | .time' \
  /var/log/vault/vault_audit.log | \
  cut -d'T' -st | cut -d':' -f1-2 | sort | uniq -c | sort -rn | head -20

# Подозрительные IP-адреса (избыточно активные)
jq -r '.request.remote_address' /var/log/vault/vault_audit.log | \
  sort | uniq -c | sort -rn | head -20

# Root token creation / usage
jq 'select(.type=="request" and (.request.path == "auth/token/create" or .request.path == "auth/token/root"))' /var/log/vault/vault_audit.log
```

### Сценарий 4: Централизованная retention и backup

#### Log rotation с долговременным архивом

```bash
# logrotate с архивом на 2 года
/var/log/vault/vault_audit.log {
    rotate 730
    daily
    compress
    delaycompress
    create 0640 vault vault
    postrotate
        kill -HUP $(cat /var/run/vault.pid 2>/dev/null) 2>/dev/null || true
    endscript
}

# Offsite backup (rsync к NAS/rsync-серверу)
# /etc/cron.daily/vault-audit-backup
0 3 * * * root find /var/log/vault/archive -name "*.gz" -mtime +90 -delete && \
    rsync -av --remove-source-files /var/log/vault/archive/ backup-server:/vault-audit/
```

#### Compliance retention policy (syslog → SIEM)

Для SOC2, PCI DSS compliance требуется хранение audit логов минимум:

| Стандарт | Минимальный срок хранения |
|----------|--------------------------|
| SOC2 | 90 дней (логи), 365 дней (архивы) |
| PCI DSS | 1 год (логи), 3 месяца быстрый доступ |
| GDPR | 3 года (в зависимости от цели обработки) |
| ISO 27001 | 1 год (минимум) |

### Сценарий 5: Инкрементальный аудит и alerting (SRE)

```bash
# Мониторинг через telemetry metrics
# vault.hcl конфигурация telemetry
telemetry {
  disable_hostname = false
  enable_hostname_as_label = true
  prometheus_retention_time = "96h"
  statsd_address = "127.0.0.1:8125"
}

# Мониторинг audit device health (Prometheus)
# vault.audit.log_request_failure
rate(vault_audit_log_request_failure[5m]) > 0

# vault.audit.log_response_failure
rate(vault_audit_log_response_failure[5m]) > 0

# vault.audit.sink.failure (device-specific)
rate(vault_audit_sink_failure{device="file"}[5m]) > 0
```

#### Alert правила (Prometheus AlertManager)

```yaml
groups:
- name: vault-audit
  rules:
  - alert: VaultAuditLogFailure
    expr: rate(vault_audit_log_request_failure[5m]) > 0 or rate(vault_audit_log_response_failure[5m]) > 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Vault audit log failure detected"
      description: "Audit device failed to log {{ $value }} requests in 5m"

  - alert: VaultAuditDiskSpaceLow
    expr: (node_filesystem_avail_bytes{mountpoint="/var/log/vault"} / node_filesystem_size_bytes{mountpoint="/var/log/vault"}) < 0.1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Vault audit log disk space low"
      description: "Audit log volume below 10% of total disk space"
```

### Сценарий 6: Расследование инцидента

#### Пример: Подозрение на компрометацию токена

**Шаг 1: Определение времени инцидента**

```bash
# Первое подозрительное событие (403 Forbidden)
jq -r 'select(.type=="response" and .response.status_code == 403) | .time' /var/log/vault/vault_audit.log | head -1
# → 2026-09-24T12:15:00Z
```

**Шаг 2: Трассировка токена**

```bash
# Все операции с токеном (correlate по accessor)
jq 'select(.auth.accessor == "hmac-sha256:abc123...") | .time, .request.path, .response.status_code' /var/log/vault/vault_audit.log
```

**Шаг 3: Определение радиуса поражения**

```bash
# Какие секреты были доступны
jq -r 'select(.auth.accessor == "hmac-sha256:abc123...") | .request.path' /var/log/vault/vault_audit.log | sort | uniq
# → secret/data/myapp/config
# → secret/data/myapp/db
# → secret/data/myapp/api-key
```

**Шаг 4: Поиск источника компрометации**

```bash
# IP-адреса с которых выполнялись запросы
jq -r 'select(.auth.accessor == "hmac-sha256:abc123...") | .request.remote_address' /var/log/vault/vault_audit.log | sort | uniq -c
# → 3 10.0.1.99
```

**Шаг 5: Действия**

1. Отозвать токен: `vault token revoke -mode=orphan <accessor>`
2. Ротация всех секретов, к которым был доступ (см. [Ротация секретов](./secret_rotation.md))
3. Проверить, не были ли секреты выведены в логи приложения

### Сценарий 7: Compliance и отчётность

#### Отчёт по доступу к секретам

```bash
# Все чтения секретов за период
jq -r --arg start "2026-09-24T00:00:00Z" --arg end "2026-09-25T00:00:00Z" \
  'select(.type=="request" and (.request.path | startswith("secret/data/")) and (.time >= $start and .time <= $end)) | [.time, .auth.accessor, .request.path] | @csv' \
  /var/log/vault/vault_audit.log > secret_access_report.csv
```

#### SOC2 / PCI DSS отчёты

```bash
# Все операции записи (аудит изменений)
jq -r 'select(.type=="request" and (.request.operation == "create" or .request.operation == "update" or .request.operation == "delete")) | [.time, .auth.accessor, .request.path, .request.operation] | @csv' /var/log/vault/vault_audit.log > write_operations.csv

# Все операции аутентификации
jq -r 'select(.type=="request" and (.request.path | startswith("auth/"))) | [.time, .request.path, .response.status_code // "N/A"] | @csv' /var/log/vault/vault_audit.log > auth_operations.csv
```

### Сценарий 8: ACL для audit device (devops)

```hcl
# Политика администрирования audit devices
# Полный доступ к управлению audit device
path "sys/audit" {
  capabilities = ["sudo", "read"]
}

path "sys/audit-enable" {
  capabilities = ["sudo"]
}

path "sys/audit-disable" {
  capabilities = ["sudo"]
}

path "sys/audit-hash/*" {
  capabilities = ["update"]
}

path "sys/config/auditing*" {
  capabilities = ["sudo", "read", "update"]
}

# Только чтение для SRE (мониторинг)
path "sys/audit" {
  capabilities = ["read"]
}
```

```bash
# Применение политики
vault policy write audit-admin audit-admin.hcl

# Назначение политики на токен
vault token create -policy=audit-admin -format=json
```

## Операции и команды

### CLI команды audit device

| Команда | Описание | Пример |
|----------|----------|--------|
| `vault audit enable file ...` | Включить file audit device | `vault audit enable file file_path=/var/log/vault/audit.log` |
| `vault audit enable syslog ...` | Включить syslog audit device | `vault audit enable syslog tag="vault" facility="AUTH"` |
| `vault audit enable socket ...` | Включить socket audit device | `vault audit enable socket address="tcp://127.0.0.1:5000" mode="tcp"` |
| `vault audit disable <path>` | Отключить audit device | `vault audit disable file/` |
| `vault audit list` | Список включённых устройств | `vault audit list` |
| `vault write sys/audit-hash/<path> input=<value>` | HMAC hash значения | `vault write sys/audit-hash/file input="secret"` |
| `vault read sys/config/auditing` | Конфиг аудита | `vault read sys/config/auditing` |

### API эндпоинты audit device

| Метод | Путь | Описание | Требования |
|-------|------|----------|------------|
| `GET` | `/sys/audit` | List enabled audit devices | `sudo` |
| `POST` | `/sys/audit/:path` | Enable audit device | `sudo` |
| `DELETE` | `/sys/audit/:path` | Disable audit device | `sudo` |
| `POST` | `/sys/audit-hash/:path` | HMAC hash value | — |
| `GET` | `/sys/config/auditing` | Audit configuration | `sudo` |
| `PUT` | `/sys/config/auditing` | Update audit configuration | `sudo` |
| `GET` | `/sys/raw/sys/audit/:path` | Raw read audit mount config (debug) | root |

### Параметры конфигурации audit device

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|-------------|----------|
| `elide_list_responses` | bool | `false` | Заменять `keys` на count в LIST ответах |
| `hmac_accessor` | bool | `true` | Хэшировать accessor токена |
| `log_raw` | bool | `false` | Логировать raw значения без хэша |
| `prefix` | string | `""` | Префикс перед строкой лога |
| `format` | string | `"json"` | Формат вывода: `"json"` или `"jsonx"` (XML) |
| `file_path` | string | (required) | Путь к файлу (file device) |
| `mode` | string | `"0600"` | Режим файла (octal) |
| `tag` | string | `"vault"` | Syslog tag |
| `facility` | string | `"AUTH"` | Syslog facility |
| `address` | string | (required) | Socket address (socket device) |

### Telemetry метрики audit

| Метрика | Тип | Описание |
|---------|-----|----------|
| `vault.audit.log_request_failure` | counter | Количество request failures across all devices |
| `vault.audit.log_response_failure` | counter | Количество response failures across all devices |
| `vault.audit.log_request` | summary | Время выполнения всех request audit operations (ms) |
| `vault.audit.log_response` | summary | Время выполнения всех response audit operations (ms) |
| `vault.audit.sink.success` | counter | Количество успешных записей в audit device |
| `vault.audit.sink.failure` | counter | Количество ошибок записи в audit device |
| `vault.audit.{DEVICE}.log_request` | summary | Время request для конкретного устройства |
| `vault.audit.{DEVICE}.log_response` | summary | Время response для конкретного устройства |
| `vault.audit.fallback.success` | counter (ENT) | Записи в fallback устройство |
| `vault.audit.fallback.miss` | counter (ENT) | Записей, отфильтрованных до fallback |

### Исключенные эндпоинты

Vault **не аудитирует** следующие эндпоинты:

```
sys/init, sys/seal-status, sys/seal, sys/step-down, sys/unseal,
sys/leader, sys/health, sys/rekey/init, sys/rekey/update,
sys/rekey/verify, sys/rekey-recovery-key/init,
sys/rekey-recovery-key/update, sys/rekey-recovery-key/verify,
sys/storage/raft/bootstrap, sys/storage/raft/join,
sys/internal/ui/feature-flags
```

Дополнительно не аудитируются при unauthenticated доступе:

```
sys/metrics, sys/pprof/*, sys/in-flight-req
```

## Устранение неполадок

| Ошибка | Причина | Решение |
|---------|---------|---------|
| `no audit backend succeeded in logging` | Все audit устройства недоступны | Проверить доступность file/syslog/socket; включить резервное устройство; проверить permissions на файл и path |
| `message too long` в syslog | UDP пакет превышает размер | Использовать TCP syslog listener; или file device + syslog forwarder |
| `permission denied` при записи в файл | Недостаточно прав на file_path | `chown vault:vault /var/log/vault/audit.log`; `chmod 0640`; проверить `mode` параметр |
| `audit log disk full` | Диск заполнен audit логами | Настроить logrotate; выделить dedicated volume; включить compress + delaycompress |
| `hash mismatch` при audit-hash | Использован неверный audit device path | `vault write sys/audit-hash/<actual_path> input=value` — путь должен совпадать с audit device mount path |
| `elide_list_responses has no effect` | Параметр задан после enable | Пересоздить audit device: `vault audit disable <path>` → `vault audit enable ... elide_list_responses=true` |
| `audit device not receiving logs` | Vault не может писать в device | Проверить `vault audit list`; логи Vault (`[ERROR] audit: backend failed to log response`) |
| `HMAC verification failed` | Изменена salt или device | После `sys/audit-hash` с новым device salt — старые хэши не совпадают; использовать accessor для корреляции |
| `duplicate audit entries` | 2+ audit devices пишут одно и то же | Это by design (гарантии записи); dedup по `.request.id` в SIEM |
| `request forwarded_from non-empty` | Performance standby forwarding | Ожидаемое поведение для HA; коррелировать через `forwarded_from` + `request.id` |
| `unknown field "exclude"` (Community Edition) | Параметр `exclude` Enterprise-only | Использовать Enterprise, либо фильтровать на уровне SIEM |
| `unknown field "filter"` (Community Edition) | Параметр `filter` Enterprise-only | Использовать Enterprise, либо фильтровать на уровне SIEM |

## Лучшие практики

1. **Минимум два audit device:** Включите `file` + `syslog` (или `socket`) на каждом кластере. Vault гарантирует запись в хотя бы одно — если одно выходит из строя, второе продолжит писать.
2. **Выделенный том для file device:** Используйте отдельный volume/partition для `/var/log/vault/`. Иначе системные логи или другие процессы могут переполнить диск и вывести Vault из строя.
3. **Log rotation с SIGHUP:** Настройте `logrotate` с `postrotate`/`kill -HUP` для file device. Без SIGHUP Vault продолжит писать в удалённый файл.
4. **`elide_list_responses=true`:** Включите для уменьшения объёма LIST-ответов (особенно для `sys/leases/lookup/*`).
5. **`hmac_accessor=false`:** Отключите хэширование accessor — accessor нужен для `vault token revoke` и correlation в incident response.
6. **TCP для syslog:** Используйте TCP listener для syslog, чтобы избежать `message too long` при больших аудит-записях.
7. **SIEM forwarding:** Всегда отправляйте audit логи во внешнюю SIEM-систему. File device — только для локального резервного копирования.
8. **Retention policy:** Минимум 1 год для compliance (SOC2, PCI DSS, GDPR). Архивируйте на 2+ года.
9. **Monitoring:** Алерт на `vault.audit.log_request_failure > 0` и `vault.audit.log_response_failure > 0`. Это критически важные сигналы.
10. **Exclude/filter (Enterprise):** Используйте `exclude` для удаления `request.data` из audit записей (не хранить секреты в логах, даже в hashed виде).
11. **Audit log backup:** Offsite backup audit логов через rsync/s3-compatible storage с проверкой целостности.
12. **Корреляция через Request ID:** Всегда используйте `.request.id` для связи request/response записей, а не timestamp.
13. **Access control:** Ограничьте доступ к audit логам — только SRE/Security команда. Используйте `chmod 0640`, SELinux/AppArmor.
14. **Kubernetes:** Используйте `file_path=stdout` с префиксом для разделения audit и server logs в stdout.
15. **Regular testing:** Тестируйте конфигурацию audit device в non-production окружении с benchmark под нагрузкой.

## Ограничения и известные проблемы

- **Performance overhead:** Audit device добавляет latency на каждую операцию. Измеряйте через `vault.audit.log_request` / `vault.audit.log_response` метрики.
- **Disk space:** Audit логи растут линейно с запросами. Используйте `elide_list_responses=true` и настраивайте log rotation.
- **UDP syslog limit:** UDP пакеты могут быть обрезаны для больших аудит-записей. Используйте TCP или file device.
- **No audit for exempted endpoints:** `sys/health`, `sys/seal-status`, `sys/init`, `sys/storage/raft/*` и др. не логируются. Это безопасно по design, но означает пробел в visibility для этих операций.
- **Hash immutability:** После отключения audit device salt перестаёт работать. `vault write sys/audit-hash` требует включённого device с тем же путём.
- **Enterprise-only features:** `exclude`, `filter`, `fallback` доступны только в Enterprise.
- **Log duplication:** 2+ устройства пишут дубликаты. Dedup по `.request.id` в SIEM.
- **Kubernetes stdout:** При `file_path=stdout` логи смешиваются с server logs. Используйте `prefix` для разделения.
- **No filtering in Community Edition:** Нет возможности selectively исключить поля из audit записей в Community Edition.
- **Non-string values not hashed:** Целые числа и булевы значения не хэшируются по умолчанию — убедитесь, что sensitive integer fields (например, user IDs) не попадают в `data`.
- **Response data:** По умолчанию response data хэшируется. Отключение через `log_raw=true` выводит секреты в plaintext — Никогда не используйте в production.
- **Audit log size:** Запись одного запроса + ответа = 2 audit записи. При высокой нагрузке это удваивает объём логов по сравнению с простым request logging.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Ключевые концепции Vault](../concepts.md)** — audit devices, токены, Identity Store.
*   **[Авторизация и политики ACL](../authorization.md)** — управление доступом к audit endpoints.
*   **[Ротация секретов](./secret_rotation.md)** — связь audit с ротацией секретов.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему audit важен.
*   [Audit logging overview (Vault docs)](https://developer.hashicorp.com/vault/docs/audit)
*   [Auditing schema (audit entry JSON schema)](https://developer.hashicorp.com/vault/docs/audit/schema)
*   [File audit device](https://developer.hashicorp.com/vault/docs/audit/file)
*   [Syslog audit device](https://developer.hashicorp.com/vault/docs/audit/syslog)
*   [Socket audit device](https://developer.hashicorp.com/vault/docs/audit/socket)
*   [Audit best practices](https://developer.hashicorp.com/vault/docs/audit/best-practices)
*   [/sys/audit API](https://developer.hashicorp.com/vault/api-docs/system/audit)
*   [/sys/audit-hash API](https://developer.hashicorp.com/vault/api-docs/system/audit-hash)
*   [/sys/config/auditing API](https://developer.hashicorp.com/vault/api-docs/system/config-auditing)
*   [Audit telemetry metrics](https://developer.hashicorp.com/vault/docs/internals/telemetry/metrics/audit)