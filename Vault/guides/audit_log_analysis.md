# Анализ audit логов Vault

## Определения

**Audit Device** — компонент Vault, записывающий все запросы и ответы в лог. Поддерживаются форматы: `file`, `syslog`, `socket`.

**Audit Log** — неизменяемый журнал всех операций Vault, содержащий хэшированные значения запросов и ответов. Позволяет отслеживать активность без раскрытия секретов.

**SIEM (Security Information and Event Management)** — платформа для централизованного сбора, анализа и корреляции событий безопасности. Vault audit logs могут интегрироваться с SIEM для compliance и расследования инцидентов.

**Forensic Analysis** — процесс расследования инцидентов безопасности на основе audit логов. Включает поиск аномалий, трассировку цепочки доступа и определение радиуса поражения.

**Log Hash** — хэш чувствительных данных в audit логах. Vault хэширует секретные значения с солью, поэтому даже при компрометации логов секреты не раскрываются.

**Request ID** — уникальный идентификатор запроса, генерируемый Vault. Используется для трассировки запроса через цепочку сервисов.

## Основные концепции

### Формат audit лога

Каждая запись audit лога содержит:

```json
{
  "type": "request",
  "time": "2026-09-24T12:00:00Z",
  "auth": {
    "client_token": "hvs.CAESI...",
    "accessor": "a_1b2c...",
    "policies": ["default", "app-policy"]
  },
  "request": {
    "id": "1a2b3c4d-5678-90ab-cdef-1234567890ab",
    "method": "POST",
    "path": "secret/data/myapp/config",
    "data": {
      "password": "hash:abc123..."
    },
    "headers": {
      "X-Vault-Token": "hvs.CAESI..."
    }
  },
  "response": {
    "status_code": 200,
    "data": {
      "data": {
        "password": "hash:def456..."
      }
    }
  }
}
```

### Типы audit записей

| Тип | Описание |
| :--- | :--- |
| `request` | Входящий запрос (метод, путь, параметры, заголовки) |
| `response` | Ответ Vault (статус, данные) |
| `error` | Ошибки валидации, аутентификации, авторизации |

### Хэширование чувствительных данных

Vault хэширует чувствительные значения в audit логах:

- `password` → `hash:abc123...`
- `secret_id` → `hash:def456...`
- `client_token` → хэш с солью

Это позволяет отслеживать операции без раскрытия plaintext.

## Практические сценарии

### Сценарий 1: Настройка audit devices

#### Файловый audit device

```bash
# Включение файлового audit device
vault audit enable file file_path=/var/log/vault/audit.log log_raw=true

# Проверка
vault audit list
# → Path     Type    Description
# → file/    file    file audit log
```

Параметры:
- `file_path` — путь к файлу лога
- `log_raw` — логировать raw запросы/ответы (включая хэши)
- `mode` — режим записи (`0640` по умолчанию)

#### Syslog audit device

```bash
# Включение syslog audit device
vault audit enable syslog tag="vault-audit" facility="AUTH"
```

Параметры:
- `tag` — тег для идентификации в syslog
- `facility` — syslog facility (`AUTH`, `AUTHPRIV`, `LOCAL0`-`LOCAL7`)

#### Socket audit device

```bash
# Включение socket audit device
vault audit enable socket address="tcp://127.0.0.1:5000" mode="tcp"
```

### Сценарий 2: Анализ audit логов

#### Поиск конкретных операций

```bash
# Все операции чтения секретов
jq 'select(.request.path | startswith("secret/data"))' /var/log/vault/audit.log

# Все операции аутентификации
jq 'select(.request.path | startswith("auth/"))' /var/log/vault/audit.log

# Все ошибки 403 Forbidden
jq 'select(.response.status_code == 403)' /var/log/vault/audit.log

# Все операции конкретного токена
jq 'select(.auth.client_token == "hvs.CAESI...")' /var/log/vault/audit.log

# Все операции за последний час
jq 'select(.time > "2026-09-24T11:00:00Z")' /var/log/vault/audit.log
```

#### Поиск аномалий

```bash
# Всплеск ошибок аутентификации (возможен brute-force)
jq -r 'select(.request.path == "auth/approle/login" and .response.status_code != 200) | .time' /var/log/vault/audit.log | sort | uniq -c | sort -rn | head -20

# Запросы с необычными IP
jq -r 'select(.request.headers["X-Forwarded-For"] // "unknown" | contains("10.0.1.99")) | .time, .request.path' /var/log/vault/audit.log

# Попытки доступа к root-путям
jq 'select(.request.path | startswith("sys/"))' /var/log/vault/audit.log
```

### Сценарий 3: Интеграция с SIEM

#### Elasticsearch / OpenSearch

```bash
# Отправка audit логов в Elasticsearch через Filebeat
# filebeat.yml
filebeat.inputs:
- type: log
  paths:
    - /var/log/vault/audit.log
  json.keys_under_root: true
  json.add_error_key: true

output.elasticsearch:
  hosts: ["elasticsearch.example.com:9200"]
  index: "vault-audit-%{+yyyy.MM.dd}"
```

#### Splunk

```bash
# Отправка audit логов в Splunk через syslog
vault audit enable syslog tag="vault-audit" facility="AUTH"

# Настройка Splunk Universal Forwarder
# outputs.conf
[tcpout:splunk-indexer]
server = splunk.example.com:9997

# inputs.conf
[monitor:///var/log/vault/audit.log]
sourcetype = vault:audit
```

#### Grafana Loki

```bash
# Отправка audit логов в Loki через Promtail
# promtail-config.yml
scrape_configs:
- job_name: vault
  static_configs:
  - targets:
      - localhost
    labels:
      job: vault
      __path__: /var/log/vault/audit.log
```

### Сценарий 4: Расследование инцидента

#### Пример: Подозрение на компрометацию токена

**Шаг 1: Определение времени инцидента**

```bash
# Найти первое подозрительное событие
jq -r 'select(.response.status_code == 403) | .time' /var/log/vault/audit.log | head -1
# → 2026-09-24T12:15:00Z
```

**Шаг 2: Трассировка токена**

```bash
# Все операции с токеном
jq 'select(.auth.client_token == "hvs.CAESI...")' /var/log/vault/audit.log | jq -r '.time, .request.path, .response.status_code'
```

**Шаг 3: Определение радиуса поражения**

```bash
# Какие секреты были доступны
jq 'select(.auth.client_token == "hvs.CAESI...") | .request.path' /var/log/vault/audit.log | sort | uniq
# → secret/data/myapp/config
# → secret/data/myapp/db
# → secret/data/myapp/api-key
```

**Шаг 4: Поиск источника компрометации**

```bash
# IP-адреса, с которых выполнялись запросы
jq -r 'select(.auth.client_token == "hvs.CAESI...") | .request.headers["X-Forwarded-For"] // .request.remote_addr' /var/log/vault/audit.log | sort | uniq -c
# → 3 10.0.1.99
```

**Шаг 5: Действия**

1. Отозвать скомпрометированный токен: `vault token revoke <accessor>`
2. Ротация всех секретов, к которым был доступ
3. Проверить, не были ли секреты выведены в логи приложения

### Сценарий 5: Compliance и отчетность

#### Отчет по доступу к секретам

```bash
# Все чтения секретов за последние 30 дней
jq -r 'select(.request.path | startswith("secret/data") and .request.method == "GET") | [.time, .auth.client_token, .request.path] | @csv' /var/log/vault/audit.log > secret_access_report.csv

# Уникальные пользователи, читавшие секреты
jq -r 'select(.request.path | startswith("secret/data")) | .auth.policies[]' /var/log/vault/audit.log | sort | uniq -c
```

#### SOC2 / PCI DSS отчеты

```bash
# Все операции записи (аудит изменений)
jq -r 'select(.request.method == "POST" or .request.method == "PUT" or .request.method == "DELETE") | [.time, .auth.client_token, .request.path, .response.status_code] | @csv' /var/log/vault/audit.log > write_operations.csv

# Все операции аутентификации
jq -r 'select(.request.path | startswith("auth/")) | [.time, .request.path, .response.status_code] | @csv' /var/log/vault/audit.log > auth_operations.csv
```

## Лучшие практики

1. **Минимум два audit device:** Файловый + syslog для отказоустойчивости.
2. **Защита audit логов:** Ограничьте доступ к файлам audit логов (`chmod 640`, `vault:vault`).
3. **Ротация логов:** Настройте ротацию audit логов (`logrotate` или системd journald).
4. **SIEM интеграция:** Централизуйте логи в SIEM для compliance и расследования инцидентов.
5. **Анализ аномалий:** Регулярно анализируйте audit логи на подозрительную активность.
6. **Хранилище:** Храните audit логи не менее 1 года (требование compliance).

## Ограничения и известные проблемы

- **Производительность:** Audit device добавляет overhead на каждую операцию. В high-load средах используйте syslog или socket для снижения задержки.
- **Диск:** Audit логи могут быстро заполнять диск. Настройте ротацию и мониторинг свободного места.
- **Только запросы:** Audit логируют только запросы к Vault API. Не логируют операции внутри плагинов (например, вызовы БД).
- **Хэши:** Хэши чувствительных данных нельзя дехэшировать. Для расследования используйте correlation по Request ID.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и аудит.
*   **[Основные концепции Vault](../concepts.md)** — audit devices.
*   **[Установка Vault](../guides/vault_installation.md)** — настройка audit.
*   [Официальная документация по аудиту](https://developer.hashicorp.com/vault/docs/enterprise/audit)
