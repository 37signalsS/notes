# Consul Replicate

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x  
**Версия Consul Replicate:** v0.4.0 (стабильный релиз); master-ветка содержит более новые нестабильные изменения

## Определения

**Consul Replicate** — внешний демон (отдельный бинарный файл) для асинхронной репликации KV-префиксов между дата-центрами Consul в Open Source версии. Поскольку Consul OSS не имеет встроенной мульти-DC репликации KV и ACL, Replicate заполняет этот пробел, периодически синхронизируя выбранные префиксы и политики между кластерами.

**Blocking Queries** — механизм длительного опроса Consul HTTP API, при котором клиент отправляет запрос с индексом (`?index=X`), и Consul удерживает соединение до появления изменений или истечения таймаута. Consul Replicate использует blocking queries для эффективного обнаружения изменений в KV без постоянного轮询.

**ModifyIndex** — монотонно возрастающий индекс, присваиваемый каждой записи KV при изменении. Consul Replicate сравнивает ModifyIndex source и destination для предотвращения циклической репликации и определения необходимости обновления.

**Prefix** — префикс KV-пути (например, `config/app`), который реплицируется из source DC в destination DC. Поддерживается опциональное переименование destination prefix через синтаксис `source@datacenter:destination`.

**Quiescence Timers** (`wait {}`) — механизм подавления частой репликации при "flapping" (частом изменении) данных. Определяет минимальное и максимальное время ожидания перед выполнением репликации после обнаружения изменений.

**Status Dir** — путь в Consul KV (`service/consul-replicate/statuses` по умолчанию), где Replicate хранит метаданные о последней репликации (ModifyIndex, лидер, timestamp) для отслеживания состояния между перезапусками.

**ACL Replication Token** — токен (`acl.tokens.replication`), используемый в Consul Enterprise для автоматической репликации ACL между дата-центрами. В Consul OSS для репликации ACL используется Consul Replicate.

**Circular Replication** — нежелательный сценарий, при котором репликация из DC1 в DC2 и обратно из DC2 в DC1 создает бесконечный цикл обновлений. Предотвращается через уникальные префиксы и проверку ModifyIndex.

## Основные концепции

### Архитектура

Consul Replicate работает как демон, который:
1. Подключается к local Consul agent (рекомендуется) или напрямую к серверу.
2. Для каждого `prefix {}` запускает отдельный watcher, использующий blocking queries для отслеживания изменений в source DC.
3. При обнаружении изменений (сравнение ModifyIndex) реплицирует KV-записи в destination DC через HTTP API.
4. Хранит состояние репликации в `status_dir` для resume после перезапуска.
5. Предотвращает циклическую репликацию через проверку local datacenter vs source datacenter.

```
┌──────────────┐          ┌──────────────────┐          ┌──────────────┐
│   DC1 (Source)│◄─────────│ Consul Replicate │─────────►│ DC2 (Destination)│
│               │  watch   │                  │  PUT     │               │
│ KV: config/   │  block   │ - Watcher        │  KV API  │ KV: config/    │
│               │  query   │ - Runner         │          │               │
│               │          │ - ModifyIndex    │          │               │
│               │          │   comparison     │          │               │
└──────────────┘          └──────────────────┘          └──────────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ Status Dir       │
                          │ KV: service/     │
                          │ consul-replicate │
                          │ /statuses        │
                          └──────────────────┘
```

### Реплицируемые сущности

| Сущность | Поддержка | Ограничения |
| :--- | :--- | :--- |
| **KV Store** | Да | Только указанные префиксы; асинхронная репликация (best effort) |
| **ACL Policies** | Да | Только политики; токены не реплицируются |
| **ACL Roles** | Да | Связанные политики реплицируются вместе с ролью |
| **Service Catalog** | Нет | Сервисы регистрируются локально в каждом ДЦ |
| **Intentions** | Нет | Требуется ручное создание или terraform в каждом ДЦ |
| **Prepared Queries** | Нет | Требуется ручная настройка |

### Сравнительная таблица: Consul Replicate vs Альтернативы

| Критерий | Consul Replicate (OSS) | WAN Federation (Enterprise) | Cluster Peering (1.14+) | Snapshots + Import |
| :--- | :--- | :--- | :--- | :--- |
| **Архитектура** | External daemon | Built-in | Built-in | Periodic export/import |
| **Тип репликации** | KV prefix only | Все данные (KV, ACL, intentions, config) | Exported services + intentions | Full snapshot |
| **Версия Consul** | Любая | Enterprise only | 1.14.1+ | Любая |
| **Согласованность** | Асинхронная, best effort | Синхронная через Raft | mTLS encrypted, async | Атомарная точка во времени |
| **Задержка репликации** | Seconds to minutes | Sub-second | Seconds | Manual / scheduled |
| **Multi-DC** | Да (любое количество) | Да (primary/secondary) | Да (peer-to-peer) | N/A (backup, не replication) |
| **Enterprise required** | Нет | Да | Нет (1.14+) | Нет |
| **Изоляция отказов** | Partial (DC2 имеет stale данные) | Full (shared Raft) | Full (изолированные кластеры) | N/A |
| **Сложность настройки** | Средняя | Высокая | Средняя | Низкая |
| **Автоматизация** | Полная (демон) | Полная | Полная | Partial (требуется cron/script) |

### Механизм репликации

#### Blocking Queries и ModifyIndex

Consul Replicate использует Consul blocking query API с параметром `?index=MODIFY_INDEX`. Когда Consul возвращает данные, он включает X-Consul-Index заголовок. Replicate сохраняет этот индекс и использует его в следующем запросе. Consul удерживает соединение до:
- Появления изменений (X-Consul-Index увеличивается)
- Истечения `?wait` таймаута
- Возврата текущего значения немедленно, если индекс устарел (`max_stale`)

#### Quiescence Timers

При обнаружении изменений Replicate ждет от `wait.min` до `wait.max` перед выполнением репликации. Если за это время появляются новые изменения, таймер сбрасывается. Это снижает количество репликаций при "flapping" данных.

#### State Tracking

Replicate хранит состояние в `status_dir` (по умолчанию `service/consul-replicate/statuses` в Consul KV). Для каждого префикса хранится:
- Last ModifyIndex
- Source datacenter
- Last replication timestamp
- Leader information

Это позволяет Replicate корректно resume после перезапуска без полной пересинхронизации.

### Производительность и ограничения

#### Blocking Query Overhead

При изменении одного ключа под watching prefix Consul возвращает **все** ключи под этим prefix (не только измененный). Это означает, что при высокой частоте изменений под большим prefix Replicate может генерировать значительный трафик.

**Митигация:** Запускайте несколько экземпляров Replicate, каждый отвечает за узкий prefix (например, `/env/prod/db` и `/env/prod/cache` вместо одного `/env/prod`).

#### Асинхронность

Replicate предоставляет **best effort** репликацию. После записи в source DC нет гарантии, что данные уже реплицированы в destination. Для strong consistency используйте WAN Federation (Enterprise) или Cluster Peering.

#### Размер KV values

Consul API имеет лимит на размер значения (по умолчанию 512 КиБ, настраивается через `kv_max_value_size`). Replicate передает значения через HTTP API; значения больше лимита отклоняются API.

## Практические сценарии

### Сценарий 1: Установка и базовая конфигурация

#### Загрузка и установка

```bash
# Скачивание стабильного релиза
curl -o consul-replicate.zip https://releases.hashicorp.com/consul-replicate/0.4.0/consul-replicate_0.4.0_linux_amd64.zip
unzip consul-replicate.zip
chmod +x consul-replicate
sudo mv consul-replicate /usr/local/bin/

# Проверка установки
consul-replicate --version
# → consul-replicate v0.4.0

# Проверка справки
consul-replicate -h
# → Usage: consul-replicate [options]
```

#### Базовая конфигурация

```hcl
# /etc/consul.d/replicate.hcl

# Подключение к local Consul agent
consul {
  address = "127.0.0.1:8500"
  
  # ACL token (опционально, если ACL отключены)
  token = "${CONSUL_REPLICATE_TOKEN}"
}

# Реплицируемый префикс: source@datacenter → destination
prefix {
  source      = "config"
  datacenter  = "dc1"
  destination = "config"
}

# Исключения
exclude {
  source = "config/local/"
}

# Quiescence timers
wait {
  min = "5s"
  max = "10s"
}

# Логирование
log_level = "warn"

# Status directory
status_dir = "service/consul-replicate/statuses"
```

#### Проверка работоспособности

```bash
# Запуск в foreground с debug логированием
consul-replicate -config=/etc/consul.d/replicate.hcl -log-level=debug
# → [INFO] (cli) received config from Watcher
# → [INFO] (cli) invoking Runner
# → [INFO] (prefix) starting poll

# Проверка статуса
consul-replicate -config=/etc/consul.d/replicate.hcl status
# → Replication status: [dc1: healthy]

# Валидация KV в destination DC
consul kv get config/app/db_url -datacenter=dc2
# → значение совпадает с dc1
```

### Сценарий 2: Production deployment с ACL и TLS

#### ACL политики

**На source DC (dc1):**
```hcl
# /tmp/replicate-read.hcl
# Политика для чтения KV prefix
key_prefix "config/" {
  policy = "read"
}

# Чтение replication status
key_prefix "service/consul-replicate/" {
  policy = "read"
}

# Чтение метрик (опционально)
service "consul-replicate" {
  policy = "read"
}
```

```bash
# Создание политики
consul acl policy create \
  -name "replicate-read" \
  -rules @/tmp/replicate-read.hcl \
  -token "${MGMT_TOKEN}" \
  -datacenter=dc1

# Создание токена
consul acl token create \
  -description "Replicate read token for dc1→dc2" \
  -policy-name "replicate-read" \
  -token "${MGMT_TOKEN}" \
  -datacenter=dc1
# → SecretID: <TOKEN_DC1>
```

**На destination DC (dc2):**
```hcl
# /tmp/replicate-write.hcl
# Политика для записи KV prefix
key_prefix "config/" {
  policy = "write"
}

# Запись replication status
key_prefix "service/consul-replicate/" {
  policy = "write"
}
```

```bash
# Создание политики
consul acl policy create \
  -name "replicate-write" \
  -rules @/tmp/replicate-write.hcl \
  -token "${MGMT_TOKEN}" \
  -datacenter=dc2

# Создание токена
consul acl token create \
  -description "Replicate write token for dc1→dc2" \
  -policy-name "replicate-write" \
  -token "${MGMT_TOKEN}" \
  -datacenter=dc2
# → SecretID: <TOKEN_DC2>
```

#### Конфигурация с ACL

```hcl
# /etc/consul.d/replicate.hcl
consul {
  address = "127.0.0.1:8500"
  token   = "${CONSUL_REPLICATE_TOKEN_DC2}"
  
  # Retry behavior
  retry {
    enabled    = true
    attempts   = 12
    backoff    = "250ms"
    max_backoff = "1m"
  }
  
  # TLS (опционально)
  ssl {
    enabled     = true
    verify      = true
    cert        = "/etc/consul.d/certs/client.pem"
    key         = "/etc/consul.d/certs/client-key.pem"
    ca_cert     = "/etc/consul.d/certs/ca.pem"
    server_name = "dc1-server.consul"
  }
}

prefix {
  source      = "config"
  datacenter  = "dc1"
  destination = "config"
}

exclude {
  source = "config/local/"
}

wait {
  min = "5s"
  max = "10s"
}

log_level   = "warn"
status_dir  = "service/consul-replicate/statuses"
pid_file    = "/var/run/consul-replicate/pid"
```

### Сценарий 3: Multi-prefix replication (нагрузочное разделение)

```hcl
# /etc/consul.d/replicate.hcl
consul {
  address = "127.0.0.1:8500"
  token   = "${CONSUL_TOKEN}"
}

# Префикс 1: config базы данных
prefix {
  source      = "config/db"
  datacenter  = "dc1"
  destination = "config/db"
}

# Префикс 2: config кэша
prefix {
  source      = "config/cache"
  datacenter  = "dc1"
  destination = "config/cache"
}

# Префикс 3: feature flags (с переименованием)
prefix {
  source      = "feature-flags"
  datacenter  = "dc1"
  destination = "flags"
}

exclude {
  source = "config/db/local-dev"
}

wait {
  min = "5s"
  max = "10s"
}

log_level  = "warn"
status_dir = "service/consul-replicate/statuses"
```

При запуске Replicate автоматически создаст отдельные watcher'ы для каждого prefix, что позволяет распределить нагрузку и снизить влияние blocking query overhead.

### Сценарий 4: Systemd unit (production)

```ini
# /etc/systemd/system/consul-replicate.service
[Unit]
Description=Consul Cross-DC KV Replication Daemon
Documentation=https://github.com/hashicorp/consul-replicate
After=network.target consul.service
Requires=consul.service

[Service]
Type=simple
User=consul
Group=consul

EnvironmentFile=/etc/consul.d/replicate.env
ExecStart=/usr/local/bin/consul-replicate \
  -config=/etc/consul.d/replicate.hcl \
  -log-level=warn

Restart=on-failure
RestartSec=10

LimitNOFILE=65536
TimeoutStopSec=30
KillMode=process

# Security hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable consul-replicate
sudo systemctl start consul-replicate

# Проверка статуса
sudo systemctl status consul-replicate
# → active (running)

# Просмотр логов
journalctl -u consul-replicate -f
# → [INFO] (prefix) starting poll
```

### Сценарий 5: Docker deployment

```dockerfile
# Dockerfile
FROM hashicorp/consul:1.22

RUN curl -o /usr/local/bin/consul-replicate \
  https://releases.hashicorp.com/consul-replicate/0.4.0/consul-replicate_0.4.0_linux_amd64.zip \
  && chmod +x /usr/local/bin/consul-replicate

COPY replicate.hcl /etc/consul.d/replicate.hcl

ENTRYPOINT ["consul-replicate"]
CMD ["-config", "/etc/consul.d/replicate.hcl"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  consul-replicate:
    build: .
    container_name: consul-replicate
    restart: unless-stopped
    environment:
      - CONSUL_HTTP_ADDR=consul.dc1:8500
      - CONSUL_TOKEN=${CONSUL_REPLICATE_TOKEN}
    volumes:
      - ./replicate.hcl:/etc/consul.d/replicate.hcl:ro
    depends_on:
      - consul
    networks:
      - consul-net
    healthcheck:
      test: ["CMD", "consul-replicate", "status"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Сценарий 6: Bi-directional replication (осторожно!)

```hcl
# /etc/consul.d/replicate-dc1-to-dc2.hcl
consul {
  address = "127.0.0.1:8500"
  token   = "${TOKEN_DC2}"
}

prefix {
  source      = "shared"
  datacenter  = "dc1"
  destination = "shared"
}

exclude {
  source = "shared/dc1-only/"
}
```

```hcl
# /etc/consul.d/replicate-dc2-to-dc1.hcl
consul {
  address = "127.0.0.1:8500"
  token   = "${TOKEN_DC1}"
}

prefix {
  source      = "shared"
  datacenter  = "dc2"
  destination = "shared"
}

exclude {
  source = "shared/dc2-only/"
}
```

**Предупреждение:** При bi-directional replication убедитесь, что:
- Каждый кластер имеет уникальный prefix для исключения (`dc1-only/`, `dc2-only/`)
- ModifyIndex предотвращает циклические обновления
- Мониторинг настроен на detection конфликтов

### Сценарий 7: Миграция с Consul Replicate на Cluster Peering

```bash
# Этап 1: Инвентаризация текущей репликации
consul-replicate -config=replicate.hcl status
# → dc1: healthy, prefix: config/

# Сохранение списка префиксов
consul-replicate -config=replicate.hcl status -format=json | jq '.prefixes'

# Этап 2: Создание снапшота (для fallback)
consul snapshot save /tmp/pre-migration-$(date +%Y%m%d).snap

# Этап 3: Настройка Cluster Peering
# (согласно consul_wan_vs_peering.md)

# Этап 4: Тестирование peered services
consul catalog services -peer=cluster-b

# Этап 5: Постепенное отключение Replicate
# Уменьшите частоту polling:
# wait { min = "1h" max = "2h" }

# После подтверждения стабильности Peering:
sudo systemctl stop consul-replicate
sudo systemctl disable consul-replicate

# Этап 6: Cleanup
rm /etc/consul.d/replicate.hcl
```

## Операции и команды

### Валидация состояния репликации

```bash
# 1. Проверка статуса Replicate
consul-replicate -config=replicate.hcl status
# → [INFO] Replication status: [dc1: healthy]

# 2. Проверка статуса в KV (status_dir)
consul kv get service/consul-replicate/statuses/config -datacenter=dc2
# → {"ModifyIndex": 12345, "Source": "dc1", "Timestamp": "2026-01-15T10:30:00Z"}

# 3. Проверка ModifyIndex prefix
consul kv get -index config/app/key1 -datacenter=dc1
# → X-Consul-Index: 12345

consul kv get -index config/app/key1 -datacenter=dc2
# → X-Consul-Index: 12345 (должен совпадать)

# 4. Проверка исключений
consul kv get config/local/secret -datacenter=dc2
# → Error! Key not found (правильно, исключен)

# 5. Проверка логов на ошибки
journalctl -u consul-replicate --since "1 hour ago" | grep -iE "error|fail|denied"
# → (пусто, если нет ошибок)

# 6. Проверка process health
ps aux | grep consul-replicate
# → consul 12345  0.5  1.2  123456  23456 ?  Ssl  10:30   0:05 consul-replicate

# 7. Проверка open file descriptors
sudo lsof -p $(pgrep consul-replicate) | wc -l
# → 12 (должен быть Reasonable, не растет бесконечно)

# 8. Проверка network connectivity до Consul
nc -zv 127.0.0.1 8500
# → Connection succeeded
```

### Мониторинг

```bash
# Debug логирование (временное, для диагностики)
sudo systemctl edit consul-replicate
# → [Service]
# → Environment="CONSUL_REPLICATE_LOG_LEVEL=debug"

sudo systemctl restart consul-replicate
journalctl -u consul-replicate -f | grep -E "prefix|error|fail"

# Мониторинг метрик (через KV status_dir)
consul kv get -recurse service/consul-replicate/statuses -datacenter=dc2
# → все префиксы с last ModifyIndex

# Проверка утечек памяти (долгоживущий процесс)
ps -p $(pgrep consul-replicate) -o rss,vsz,etime
# → RSS: 45MB, VSZ: 120MB, Elapsed: 3 days
```

### Диагностика сети и connectivity

```bash
# Проверка доступности Consul API
curl -s http://127.0.0.1:8500/v1/kv/config/app/db_url
# → [{"Key":"config/app/db_url","Value":"..."}]

# Проверка blocking query
curl -s "http://127.0.0.1:8500/v1/kv/config/app/db_url?index=12345&wait=5s"
# → X-Consul-Index: 12345 (если нет изменений)
# → X-Consul-Index: 12346 (если есть изменения)

# Проверка ACL (если включены)
curl -s -H "X-Consul-Token: ${TOKEN}" http://127.0.0.1:8500/v1/kv/config/app/db_url
# → данные или 403 Forbidden

# Проверка TLS
openssl s_client -connect dc1-server.consul:8501 -servername dc1-server.consul
# → сертификат валиден, handshake успешен
```

### Обновление конфигурации без перезапуска

```bash
# Replicate поддерживает SIGHUP для перезагрузки конфигурации
sudo kill -SIGHUP $(pgrep consul-replicate)
# → [INFO] Reloading configuration

# Проверка нового статуса
consul-replicate -config=replicate.hcl status
```

## Устранение неполадок

### Данные не реплицируются

- **Причина:** Ошибки ACL на source или destination.
  - **Диагностика:** `journalctl -u consul-replicate | grep -i "permission denied\|acl\|403"`
  - **Решение:** Убедитесь, что токен имеет права `key_prefix "config/" { policy = "read" }` на source и `key_prefix "config/" { policy = "write" }` на destination.
- **Причина:** Неправильный `datacenter` в `prefix {}` блоке.
  - **Диагностика:** `consul kv get config/app/key -datacenter=dc1` (проверьте source).
  - **Решение:** Укажите правильное имя DC в `datacenter = "dc1"`.
- **Причина:** ModifyIndex destination выше, чем source (уже актуально).
  - **Диагностика:** `consul kv get -index config/app/key -datacenter=dc2` → индекс совпадает.
  - **Решение:** Это нормальное поведение; Replicate пропустит обновление.

### Высокое потребление CPU/памяти

- **Причина:** Большой prefix с высокой частотой изменений (blocking query возвращает все ключи).
  - **Диагностика:** `ps aux | grep consul-replicate` → CPU > 50%.
  - **Решение:** Разделите prefix на несколько более мелких; запустите несколько экземпляров Replicate.
- **Причина:** `max_stale` слишком велик, causing stale reads.
  - **Решение:** Установите `max_stale = "0"` или уменьшите значение.

### Циклическая репликация (бесконечные обновления)

- **Причина:** Bi-directional replication без исключений или с перекрывающимися prefix.
  - **Диагностика:** Логи показывают постоянные PUT в оба направления.
  - **Решение:** Используйте `exclude {}` для уникальных prefix каждого ДЦ; убедитесь, что destination prefix не является source для обратной репликации.

### Replicate не запускается / сразу падает

- **Причина:** Некорректный формат конфигурации.
  - **Диагностика:** `consul-replicate -config=replicate.hcl` → ошибка парсинга.
  - **Решение:** Проверьте синтаксис HCL; убедитесь, что `consul {}` блок корректен.
- **Причина:** Недоступен Consul agent.
  - **Диагностика:** `curl http://127.0.0.1:8500/v1/status/leader` → connection refused.
  - **Решение:** Запустите Consul agent или укажите правильный `address`.

### Конфликты версий Consul

- **Ограничение:** Consul Replicate совместим с большинством версий Consul API, но тестируется с текущей LTS.
- **Решение:** Используйте Consul Replicate v0.4.0 с Consul 1.19+; при использовании новых Consul версий проверяйте compatibility в release notes.

## Лучшие практики

- **Local agent:** Всегда подключайтесь к local Consul agent (`127.0.0.1:8500`), а не напрямую к серверу. Agent мультиплексирует соединения и снижает нагрузку на серверы.
- **Least Privilege:** Используйте отдельные токены для source (read) и destination (write). Никогда не используйте management-токен.
- **Exclude prefix:** Всегда исключайте локальные и чувствительные prefix (`config/local/`, `config/secrets/`) из репликации.
- **Multi-prefix:** При большом количестве KV (>1000 ключей) под одним prefix разделите на несколько `prefix {}` блоков для снижения blocking query overhead.
- **Quiescence timers:** Настраивайте `wait.min` и `wait.max` в зависимости от частоты изменений. Для статических конфигураций `min = "1m"`; для динамических `min = "5s"`.
- **Status dir:** Используйте отдельный `status_dir` в Consul KV с ACL, ограничивающими доступ.
- **Monitoring:** Настройте алерты на ошибки репликации, high CPU/memory, и stale ModifyIndex.
- **TLS:** Используйте TLS для соединения между Replicate и Consul, особенно при cross-DC репликации через WAN.
- **Migrate to Peering:** Для новых развертываний используйте Cluster Peering вместо Consul Replicate. Replicate является legacy инструментом для OSS сред, где Peering невозможен.
- **Avoid master-master:** Bi-directional replication возможен, но сложен в отладке. Предпочитайте single-source-of-truth с одним source DC.
- **Version pinning:** Используйте конкретную версию Consul Replicate (v0.4.0) и проверяйте release notes перед обновлением.

## Граничные случаи

- **Circular replication:** При bi-directional replication убедитесь, что у каждого ДЦ есть уникальные исключенные prefix, иначе ModifyIndex не предотвратит цикл при перекрывающихся destination prefix.
- **Large KV values:** Значения больше 512 КиБ (по умолчанию) вызывают ошибки API. Увеличьте `kv_max_value_size` на destination или разбейте большие значения на части.
- **ACL replication limitations:** Токены не реплицируются автоматически; их нужно создавать отдельно в каждом ДЦ через `consul acl token create`. Используйте Vault для централизованной выдачи токенов.
- **Intentions:** Не реплицируются автоматически; требуется terraform или `consul intention create` в каждом ДЦ.
- **Prepared Queries:** Не реплицируются; используйте Consul Service Catalog или Service Mesh для service discovery.
- **Enterprise → OSS:** При переходе с Enterprise на OSS ACL replication перестает работать; используйте Consul Replicate для миграции ACL policies.
- **Network partitions:** При разделении сети Replicate продолжает пытаться подключиться (exponential backoff). При восстановлении сети репликация resume автоматически.
- **Stale reads:** При `max_stale > 0` Replicate может читать устаревшие данные от follower. Убедитесь, что `max_stale` соответствует вашим требованиям к согласованности.
- **Consul agent restart:** При перезапуске local Consul agent Replicate переподключится автоматически (retry with exponential backoff). Состояние репликации сохраняется в `status_dir`.
- **KV size limit:** При приближении к лимиту размера KV (зависит от Raft log size) репликация может замедлиться. Мониторьте размер кластера и используйте TTL для старых ключей.

## Дополнительная информация

- **[Consul Replicate GitHub](https://github.com/hashicorp/consul-replicate)** — исходный код, release notes, инструкции по сборке.
- **[Consul Replicate Configuration README](https://github.com/hashicorp/consul-replicate/blob/master/README.md)** — полная документация по конфигурации.
- **[Consul Multi-Datacenter Overview](./consul_architecture.md)** — архитектурные принципы multi-DC.
- **[Consul KV Store](./consul_kv_store.md)** — ограничения KV, multi-DC стратегии.
- **[Consul ACL](./consul_acl.md)** — управление доступом, replication tokens.
- **[Consul Consensus](./consul_consensus.md)** — Raft-репликация, WAL, FSM, Autopilot.
- **[Consul Upgrade и Migration](./consul_upgrade_migration.md)** — upgrade процедуры для multi-DC кластеров.
- **[Consul WAN Federation против Cluster Peering](./consul_wan_vs_peering.md)** — сравнение подходов к multi-DC, рекомендации по миграции.
- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — snapshot-бэкапы, восстановление кластера.
- **[Consul Backup Verification](./consul_backup_verification.md)** — методика проверки целостности снапшотов.
- **[Consul CLI Reference](./consul_cli_reference.md)** — справочник CLI команд для KV и ACL.
- **[Consul Tools Documentation](https://developer.hashicorp.com/consul/docs/integrate/consul-tools)** — официальная документация по инструментам Consul, включая Replicate.
- **[Consul Releases](https://releases.hashicorp.com/consul-replicate/)** — все версии Consul Replicate.
