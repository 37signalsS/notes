# Vector: Безопасность и харднинг

**Актуально для:** Vector 0.58.0

## Определения

- **TLS (Transport Layer Security)** — криптографический протокол для шифрования канала связи. Vector поддерживает TLS для HTTP-совместимых sinks (Elasticsearch, OpenSearch, Loki, HTTP).
- **mTLS (Mutual TLS)** — взаимная аутентификация, при которой клиент и сервер одновременно подтверждают подлинность друг друга по сертификатам.
- **Secret Management** — централизованное хранение секретов (пароли, API-ключи, сертификаты) вне конфигурации Vector.
- **Template Confinement (v0.57+)** — механизм предотвращения injection атак через шаблоны маршрутизации (`{{ field }}`).
- **Systemd hardening** — ограничение привилегий сервиса через директивы systemd (`NoNewPrivileges`, `ProtectSystem`, `PrivateDevices` и др.).

## Безопасность TLS и аутентификация

### TLS для sinks

Vector поддерживает TLS для всех HTTP-совместимых sinks. Настройка TLS включается на уровне sink через блок `tls.*`:

```toml
[sinks.loki_secure]
type = "loki"
inputs = ["normalize"]
endpoint = "https://loki.internal:3100"

[sinks.loki_secure.tls]
ca_file = "/etc/vector/certs/loki-ca.crt"     # CA для проверки сервера
cert_file = "/etc/vector/certs/vector.crt"     # клиентский сертиикат (mTLS)
key_file = "/etc/vector/certs/vector.key"      # приватный ключ
verify_certificate = true                      # проверять цепочку сертификата
verify_hostname = true                         # проверять CN/SAN сервера
```

**Основные параметры:**

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `ca_file` / `ca_path` | — | PEM-файл или директория с CA-сертификатами |
| `cert_file` | — | PEM-файл клиентского сертификата (для mTLS) |
| `key_file` | — | PEM-файл приватного ключа |
| `verify_certificate` | `true` | Проверять сертификат сервера по CA |
| `verify_hostname` | `true` | Проверять CN/SAN сервера |
| `alpns` | — | ALPN-протоколы для HTTP/2 (например, `["h2"]` для Loki |

### Аутентификация для sinks

#### HTTP Basic Auth

```toml
[sinks.loki_basic]
type = "loki"
inputs = ["normalize"]
endpoint = "https://loki.internal:3100"

[sinks.loki_basic.auth]
strategy = "basic"
user = "vector"
password = "${LOKI_PASSWORD}"  # переменная окружения (см. ниже)
```

#### Bearer Token (OAuth2 / API Key)

```toml
[sinks.loki_apikey]
type = "loki"
inputs = ["normalize"]
endpoint = "https://loki.internal:3100"

[sinks.loki_apikey.auth]
strategy = "bearer_token"
token = "${LOKI_API_KEY}"
```

#### Kafka SASL

```toml
[sources.kafka_in]
type = "kafka"
bootstrap_servers = "kafka-01:9093,kafka-02:9093,kafka-03:9093"
topics = ["app-logs"]
group_id = "vector-aggregator-v1"

[sources.kafka_in.sasl]
mechanism = "PLAIN"
username = "vector"
password = "${KAFKA_SASL_PASSWORD}"

[sources.kafka_in.tls]
ca_file = "/etc/vector/certs/kafka-ca.crt"
cert_file = "/etc/vector/certs/vector.crt"
key_file = "/etc/vector/certs/vector.key"
```

#### Elasticsearch/OpenSearch API Key

```toml
[sinks.elasticsearch_secure]
type = "elasticsearch"
inputs = ["normalize"]
endpoints = ["https://os.example.com:9200"]
index = "logs-%Y.%m.%d"

[sinks.elasticsearch_secure.auth]
strategy = "bearer_token"
token = "${ES_API_KEY}"

[sinks.elasticsearch_secure.tls]
ca_file = "/etc/vector/certs/es-ca.crt"
verify_certificate = true
```

### Управление секретами

#### Переменные окружения (v0.57+)

Начиная с v0.57, интерполяция `${VAR}` в конфигурации **отключена по умолчанию** и требует явного флага:

```bash
vector --config /etc/vector/vector.yaml --dangerously-allow-env-var-interpolation
```

Или через переменную окружения:

```bash
export VECTOR_DANGEROUSLY_ALLOW_ENV_VAR_INTERPOLATION=true
```

**Рекомендуется:** использовать secret-провайдеры или переменные с префиксом вместо прямой интерполяции.

#### Secret-провайдеры (v0.58+)

Vector поддерживает `secrets` секцию для централизованного управления секретами через Vault, AWS KMS, GCP и др.:

```toml
[secrets.loki_password]
provider = "vault"
path = "secret/data/vector/loki"
key = "password"

[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "https://loki.internal:3100"

[sinks.loki.auth]
strategy = "basic"
user = "vector"
password = "${loki_password}"  # ссылка на secret
```

#### Kubernetes Secrets

Для K8s рекомендуется монтировать секреты как файлы и ссылаться на них:

```yaml
# Kubernetes Secret
apiVersion: v1
kind: Secret
metadata:
  name: vector-secrets
type: Opaque
stringData:
  loki-password: "s3cr3t"
  kafka-sasl-password: "k4fka-s3cr3t"
---
# Kubernetes Deployment
env:
  - name: VECTOR_SECRETS_LOKI_PASSWORD_FILE
    value: /etc/vector/secrets/loki-password
volumeMounts:
  - name: secrets
    mountPath: /etc/vector/secrets
    readOnly: true
volumes:
  - name: secrets
    secret:
      secretName: vector-secrets
```

### Template Confinement (v0.57+)

Sinks, принимающие `{{ field }}` в путях и заголовках (HTTP-заголовки, имена таблиц/стримов), требуют **буквального префикса**. Это предотвращает path traversal и injection атаки:

```toml
# Безопасно: буквальный префикс
[sinks.loki]
labels.service = "myapp"
labels.env = "{{ env }}"  # env должен быть известен на этапе компиляции

# Небезопасно: динамический путь без префикса — отклоняется на старте
# stream = "{{ user_input }}"  # ERROR: rejected
```

Опт-out (только для доверенных данных):

```toml
[sinks.loki]
dangerously_allow_unconfined_template_resolution = true
```

HTTP-family шаблоны не могут содержать `?` или `#` — это дополнительная защита от path traversal.

## Systemd Hardening

Для production-развёртывания Vector на bare-metal или ВМ рекомендуется использовать жёсткую изоляцию systemd. Шаблон основан на паттерне из [Neo4j operations](../Databases/Neo4j/operations.md):

```ini
# /etc/systemd/system/vector.service.d/hardening.conf
[Service]
# Безопасность (аналогично Neo4j/operations.md)
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictNamespaces=true

# Только чтение файловой системы, разрешённая запись только в data_dir
ReadWritePaths=/var/lib/vector /var/log/vector

# Ограничения ресурсов
LimitNOFILE=1048576
MemoryMax=4G
CPUQuota=200%

# Дополнительные ограничения
AmbientCapabilities=
CapabilityBoundingSet=
```

```bash
# Применение настроек
sudo systemctl daemon-reload
sudo systemctl restart vector
```

**Важно:** `ProtectSystem=strict` делает все файлы только для чтения, кроме путей в `ReadWritePaths`. Без `ReadWritePaths=/var/lib/vector` Vector не сможет писать disk buffer.

**Ограничения по типу роли:**

| Роль | CPUQuota | MemoryMax | LimitNOFILE | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| Agent (на хосте) | 100% | 1G | 65536 | Сбор с одного хоста |
| Aggregator | 400% | 8G | 262144 | Централизованная обработка |

Проверка:

```bash
# Проверка настроек systemd для сервиса
systemctl show vector -p NoNewPrivileges,ProtectSystem,MemoryMax,CPUQuota
# → NoNewPrivileges=true
# → ProtectSystem=strict
# → MemoryMax=4294967296
# → CPUQuota=2000000
```

### Проверка TLS-соединения до sink

```bash
# Проверка доступности и TLS для sink
openssl s_client -connect loki.internal:3100 -CAfile /etc/vector/certs/loki-ca.crt
# → Verify return code: 0 (ok)

# Проверка имени сервера (hostname verification)
curl --cacert /etc/vector/certs/loki-ca.crt --cert /etc/vector/certs/vector.crt --key /etc/vector/certs/vector.key https://loki.internal:3100/ready
# → {"ready": true}
```

## Операции и команды

### Проверка конфигурации безопасности

```bash
# Validate конфигурации с deny-warnings (перевод предупреждений в ошибки)
vector validate --config /etc/vector/vector.yaml --deny-warnings
# → Config is valid

# Проверка на отсутствие уязвимых шаблонов
vector validate --config /etc/vector/vector.yaml 2>&1 | grep -i "confinement\|unconfined"
```

### Аудит секретов в конфигурации

```bash
# Поиск открытых секретов в конфигах (пароли в plaintext)
grep -r "password\s*=\s*\"" /etc/vector/
# → Лучше использовать переменные окружения или secret provider

# Проверка прав на секретные файлы
ls -la /etc/vector/certs/
# → -rw-r----- root:vector  vector.key  # только owner и group
```

## Устранение неполадок

### TLS handshake failure

**Симптом:** `connection error: TLS handshake failed` в логах Vector.

**Диагностика:**

1.  Проверить цепочку сертификата:
    ```bash
    openssl verify -CAfile /etc/vector/certs/ca.crt /etc/vector/certs/vector.crt
    # → vector.crt: OK
    ```
2.  Проверить соединение вручную:
    ```bash
    openssl s_client -connect loki.internal:3100 -CAfile /etc/vector/certs/loki-ca.crt -cert /etc/vector/certs/vector.crt -key /etc/vector/certs/vector.key
    ```
3.  Проверить SAN/CN сервера:
    ```bash
    openssl x509 -in /etc/vector/certs/loki-ca.crt -text -noout | grep "Subject Alternative Name"
    ```

### Ошибка аутентификации sink

**Симптом:** `401 Unauthorized` или `403 Forbidden` в метриках `sink_request_failed`.

**Решение:**

1.  Проверить переменные окружения для секретов:
    ```bash
    systemctl show vector -p Environment
    ```
2.  Проверить, что `--dangerously-allow-env-var-interpolation` включён, если используется `${VAR}`.
3.  Для Kafka проверить SASL-креды:
    ```bash
    # Тестовое подключение к Kafka с SASL
    # Используйте kafka-console-producer.sh или kcat для проверки
    ```

### Template confinement ошибка

**Симптом:** `error: template confinement` или `dangerously_allow_unconfined_template_resolution required`.

**Решение:** Добавьте буквальный префикс для динамических значений шаблонов, либо включите `--dangerously-allow-unconfined-template-resolution` только для доверенных источников.

## Лучшие практики

1.  **TLS везде:** для всех sink, взаимодействующих с внешними системами (Elasticsearch, Loki, Kafka, OpenSearch). Исключение: `console` sink для локальной отладки.
2.  **mTLS для критичных каналов:** используйте клиентские сертификаты для аутентификации Vector на стороне sink (особенно для Kafka, Elasticsearch).
3.  **Секреты вне конфигурации:** никогда не храните пароли и API-ключи в plaintext в конфиг-файлах. Используйте secret-провайдеры (Vault), Kubernetes Secrets (монтированные как файлы) или переменные окружения.
4.  **Systemd hardening:** всегда применяйте `NoNewPrivileges=true`, `ProtectSystem=strict`, `PrivateTmp=true` для production-развёртываний.
5.  **Template confinement:** не отключайте `dangerously_allow_unconfined_template_resolution` в production. Используйте буквальные префиксы для динамических шаблонов.
6.  **LimitNOFILE:** для high-throughput пайплайнов увеличьте до 262144 (агрегатор) или 65536 (агент). Vector использует дескрипторы для каждого sink соединения.
7.  **Health endpoint:** держите `api.enabled = false` в production. Включайте только для `vector top`/`vector tap` с временным доступом через SSH tunnel.

## Дополнительная информация

- **Общая безопасность Vector:** [Vector Overview — Безопасность и харднинг](./vector_overview.md#безопасность-и-харднинг)
- **Systemd hardening pattern:** [Neo4j Operations — Жёсткая изоляция службы](../Databases/Neo4j/operations.md)
- **TLS общая теория:** [Протокол TLS](../Networking/Protocols/tls.md), [mTLS в Nginx](../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)
- **Reliability patterns:** [Паттерны надёжности](../CI-CD/Core_Concepts/reliability_patterns.md) — retry, circuit breaker, bulkhead
- **Мета-мониторинг:** [Meta-monitoring — Сценарий 5: Vector + Loki](../Concepts/Observability_and_Monitoring/meta-monitoring.md)
- **Официальная документация:** [Vector Security](https://vector.dev/docs/administration/security/)