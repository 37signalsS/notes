# Конфигурация Alertmanager для Docker Compose

## Определения

**Alertmanager в Docker Stack** — это специализированный компонент системы мониторинга, развёрнутый в виде изолированного контейнера, предназначенный для обработки алертов от Prometheus. Он отвечает за дедупликацию, группировку и доставку уведомлений в конечные каналы (Email, Telegram, Slack и др.).

**Персистентность (Persistence)** — механизм сохранения состояния Alertmanager (тишины/silences, данные о разосланных уведомлениях) при перезапуске или пересоздании контейнеров с использованием именованных Docker Volumes.

**Alertmanager Pipeline** — последовательная конвейерная обработка алертов: дедупликация (удаление дублей от HA-пар Prometheus), группировка по общим меткам, применение правил подавления (inhibition), фильтрация через mute timings, маршрутизация по дереву `route` и финальная доставка через `receivers`.

**Inhibition Rules** — декларативные правила, при которых алерт одного типа автоматически подавляет алерт другого типа (например, `ClusterDown` подавляет `InstanceDown` для всех сервисов на недоступном кластере).

**Mute Timings** — плановые временные окна, во время которых подавление уведомлений применяется автоматически (например, ночные смены, плановые окна обслуживания).

**Gossip Cluster** — mesh-сеть между репликами Alertmanager на базе gossip-протокола (порт `9094`), обеспечивающая синхронизацию silences, дедупликацию и кворум для HA-режима.

**Self-monitoring** — сбор и алертинг на метрики самого Alertmanager (`alertmanager_notifications_failed_total`, `alertmanager_notification_latency_seconds`, `alertmanager_cluster_members`, `up`).

> **См. также:** [Alertmanager — полная конфигурация](../../alertmanager.md), [Конфигурация Docker Compose](./docker-compose_config.md).

## Основные концепции

### Структура монтирования (Volumes)

Для корректной работы Alertmanager в Docker необходимо обеспечить доступ к конфигурации, шаблонам и хранилищу данных.

| Ресурс | Хост-путь | Контейнер-путь | Режим | Описание |
|---|---|---|---|---|
| Конфигурация | `./alertmanager/config.yml` | `/etc/alertmanager/config.yml` | `ro` | Основной файл настроек |
| Шаблоны | `./alertmanager/templates/` | `/etc/alertmanager/templates/` | `ro` | Кастомные шаблоны сообщений |
| Хранилище | `alertmanager_data` (volume) | `/alertmanager` | `rw` | База данных silences и состояний |
| TLS-сертификаты (HA) | `./alertmanager/certs/` | `/etc/alertmanager/certs/` | `ro` | Сертификаты для gossip-трафика |

### Связь с Prometheus (API v2)

В Docker Compose сервисы взаимодействуют через внутреннюю сеть по DNS-именам. В Prometheus v3 поддержка Alertmanager API v1 удалена. В файле `prometheus.yml` (см. [prometheus_config.md](./prometheus_config.md)) необходимо указывать:

```yaml
alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Особенности Docker-развёртывания

1.  **Интерполяция переменных:** С версии v0.27+ Alertmanager поддерживает флаг `--config.expand-env`, позволяющий использовать конструкции `${VAR}` в `config.yml`.
2.  **Hot Reload:** Конфигурацию можно применить без рестарта контейнера через HTTP POST на `/etc/alertmanager/-/reload` (требуется флаг `--web.enable-lifecycle`).
3.  **Персистентность:** Без использования именованного тома (volume) все созданные в UI «тишины» (silences) будут удалены при обновлении образа.
4.  **Права доступа:** Контейнер работает под пользователем с UID 65534. При использовании bind mounts для данных необходимо выполнить `chown -R 65534:65534 ./alertmanager_data`.
5.  **Gossip-порт 9094:** В HA-режиме между репликами идёт mesh-трафик на TCP/9094. В Docker Compose порт должен быть открыт внутри bridge-сети; привязка к `127.0.0.1:9094` отключит кластеризацию.
6.  **DNS и адвертайзинг:** В Docker Compose имена сервисов разрешаются через встроенный DNS. Для корректного gossip используйте имена сервисов (`alertmanager-node-1`, `alertmanager-node-2`) в `--cluster.advertise-address` и `--cluster.peer`.

### Сетевые порты и изоляция

| Порт | Протокол | Назначение | Рекомендация по открытию |
|---|---|---|---|
| `9093` | TCP | HTTP API, Web UI, Prometheus scrape | Только для доверенных сервисов (Prometheus, reverse proxy) |
| `9094` | TCP | Gossip mesh (HA-кластер) | Только между репликами Alertmanager; никогда наружу |

Рекомендации по изоляции:
- Используйте выделенную Docker bridge-сеть (`monitoring-net`) для стека.
- Не привязывайте `9093` к `0.0.0.0` в production — используйте `127.0.0.1:9093:9093` или внешний reverse proxy с Basic Auth/TLS.
- Для Swarm mode используйте сеть с опцией `attachable: false` и разворачивайте Alertmanager в изолированном segment.
- Рассмотрите использование `network_mode: bridge` с явно заданной `ipam` subnet для сегментации.

### Ключевые флаги запуска

| Флаг | Значение по умолчанию | Описание |
|---|---|---|
| `--config.file` | `/etc/alertmanager/config.yml` | Путь к конфигурационному файлу |
| `--storage.path` | `/alertmanager` | Путь к персистентному хранилищу silences |
| `--web.listen-address` | `:9093` | Адрес и порт для HTTP API |
| `--web.external-url` | — | Публичный URL для ссылок в уведомлениях |
| `--cluster.listen-address` | `0.0.0.0:9094` | Адрес для gossip-протокола (пусто = отключить HA) |
| `--cluster.advertise-address` | — | Адрес для анонса другим узлам; в Docker — имя сервиса |
| `--cluster.peer` | — | Список пиров для mesh; можно указывать несколько раз |
| `--cluster.tls-config.cert-file` | — | Сертификат для TLS gossip-трафика |
| `--cluster.tls-config.key-file` | — | Приватный ключ для TLS gossip-трафика |
| `--cluster.tls-config.ca-file` | — | CA для верификации пиров |
| `--data.retention` | `120h` | Время хранения silences и алертов |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`) |
| `--config.expand-env` | `false` | Интерполяция переменных окружения в `config.yml` |
| `--web.enable-lifecycle` | `false` | Включение `/-/reload` и `/-/healthy` |
| `--web.enable-api` | `true` | Включение HTTP API v2 |

## Практические сценарии

### Конфигурация с секретами, шаблонами, inhibition и mute timings (`alertmanager/config.yml`)

Пример использования переменных окружения для безопасной передачи токенов с полной маршрутизацией.

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: '${SMTP_SMARTHOST}'
  smtp_from: '${SMTP_FROM}'
  smtp_auth_username: '${SMTP_USER}'
  smtp_auth_password: '${SMTP_PASS}'
  pagerduty_url: '${PAGERDUTY_URL}'
  opsgenie_api_key: '${OPSGENIE_API_KEY}'
  telegram_api_url: 'https://api.telegram.org'
  wechat_url: '${WECHAT_URL}'

templates:
  - '/etc/alertmanager/templates/*.tmpl'

route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'cluster', 'service', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  continue: false
  routes:
    - receiver: 'critical-notifications'
      matchers:
        - severity="critical"
      continue: true
      group_wait: 10s
      group_interval: 1m
      repeat_interval: 1h

    - receiver: 'slack-notifications'
      matchers:
        - severity="warning"
      continue: false

    - receiver: 'webhook-audit'
      matchers:
        - alertname=~"NodeDown|InstanceDown"
      continue: false

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: '~|warning'
    equal: ['alertname', 'cluster']

  - source_match:
      alertname: 'ClusterDown'
    target_match_re:
      alertname: 'InstanceDown|NodeDown'
    equal: ['cluster']

mute_time_intervals:
  maintenance_window:
    time_intervals:
      - time_range:
          start_time: '02:00'
          end_time: '06:00'
      - weekdays: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
  weekend:
    time_intervals:
      - weekdays: ['saturday', 'sunday']
      - time_range:
          start_time: '00:00'
          end_time: '23:59'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'admin-team@example.com'
        send_resolved: true
        require_tls: true
        tls_config:
          ca_file: '/etc/alertmanager/certs/ca.crt'
          insecure_skip_verify: false

  - name: 'critical-notifications'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_SERVICE_KEY}'
        send_resolved: true
        description: '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
        severity: critical
        client: 'Alertmanager'
        client_url: '{{ .ExternalURL }}'

  - name: 'critical-notifications'
    opsgenie_configs:
      - api_key: '${OPSGENIE_API_KEY}'
        send_resolved: true
        description: '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
        source: 'prometheus-alertmanager'
        priority: P1

  - name: 'slack-notifications'
    slack_configs:
      - api_url: '${SLACK_API_URL}'
        channel: '#monitoring-alerts'
        send_resolved: true
        title: '{{ .Status | toUpper }}: {{ .GroupLabels.alertname }}'
        text: >-
          {{ range .Alerts }}
            *Alert:* {{ .Labels.alertname }}
            *Severity:* {{ .Labels.severity }}
            *Summary:* {{ .Annotations.summary }}
            *Runbook:* {{ .Annotations.runbook_url }}
          {{ end }}
        color: >-
          {{ if eq .Status "firing" }}danger{{ else }}good{{ end }}

  - name: 'telegram-notifications'
    telegram_configs:
      - bot_token: '${TELEGRAM_BOT_TOKEN}'
        chat_id: '${TELEGRAM_CHAT_ID}'
        send_resolved: true
        message: |-
          *{{ .Status | toUpper }}*: {{ .GroupLabels.alertname }}
          {{ range .Alerts }}
          *Instance:* {{ .Labels.instance }}
          *Severity:* {{ .Labels.severity }}
          *Summary:* {{ .Annotations.summary }}
          {{ end }}

  - name: 'webhook-audit'
    webhook_configs:
      - url: '${WEBHOOK_AUDIT_URL}'
        send_resolved: true
        http_config:
          tls_config:
            ca_file: '/etc/alertmanager/certs/ca.crt'
            insecure_skip_verify: false
          basic_auth:
            username: '${WEBHOOK_USER}'
            password: '${WEBHOOK_PASS}'
        max_alerts: 10
        timeout: 5s
```

### Секция Alertmanager в `compose.yml`

Production-ready конфигурация с полным security hardening, healthchecks и ограничением ресурсов.

```yaml
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: monitoring-alertmanager
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
      - seccomp:default
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--config.expand-env'
      - '--web.enable-lifecycle'
      - '--log.level=info'
    env_file: .env
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml:ro
      - ./alertmanager/templates/:/etc/alertmanager/templates/:ro
      - ./alertmanager/certs/:/etc/alertmanager/certs/:ro
      - alertmanager_data:/alertmanager
    ports:
      - "127.0.0.1:9093:9093"
      - "127.0.0.1:9094:9094"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 128M
    networks:
      - monitoring-net

volumes:
  alertmanager_data:
    driver: local
```

### Standalone Compose для Alertmanager

Минимальный файл `compose.yml` для запуска только Alertmanager без полного стека:

```yaml
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--web.listen-address=:9093'
      - '--cluster.listen-address=:9094'
    volumes:
      - ./config.yml:/etc/alertmanager/config.yml:ro
      - ./templates/:/etc/alertmanager/templates/:ro
      - alertmanager_data:/alertmanager
    ports:
      - "127.0.0.1:9093:9093"
      - "127.0.0.1:9094:9094"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - monitoring-net

volumes:
  alertmanager_data:

networks:
  monitoring-net:
    driver: bridge
```

Запуск: `docker compose up -d`. Проверка: `docker compose ps alertmanager`.

### HA-кластер в Docker Compose с Gossip TLS

Для обеспечения высокой доступности узлы Alertmanager должны обмениваться данными через gossip-протокол (порт `9094`). Минимальный рекомендуемый размер кластера — 3 узла (кворум).

**Генерация сертификатов для gossip:**

```bash
# 1. CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt \
  -subj "/CN=alertmanager-ca"

# 2. Сертификаты для каждого узла
for node in alertmanager-node-1 alertmanager-node-2 alertmanager-node-3; do
  openssl genrsa -out ${node}.key 2048
  openssl req -new -key ${node}.key -out ${node}.csr \
    -subj "/CN=${node}"
  cat > ${node}.ext <<EOF
basicConstraints = critical,CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = DNS:${node}
EOF
  openssl x509 -req -in ${node}.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out ${node}.crt -days 365 -sha256 -extfile ${node}.ext
done

mkdir -p alertmanager/certs
mv *.crt *.key *.csr *.ext alertmanager/certs/
chmod 600 alertmanager/certs/*.key
```

**Полный `compose.yml` для HA-кластера:**

```yaml
services:
  alertmanager-node-1:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager-node-1
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.advertise-address=alertmanager-node-1:9094'
      - '--cluster.peer=alertmanager-node-2:9094'
      - '--cluster.peer=alertmanager-node-3:9094'
      - '--cluster.tls-config.cert-file=/etc/alertmanager/certs/alertmanager-node-1.crt'
      - '--cluster.tls-config.key-file=/etc/alertmanager/certs/alertmanager-node-1.key'
      - '--cluster.tls-config.ca-file=/etc/alertmanager/certs/ca.crt'
      - '--config.expand-env'
      - '--web.enable-lifecycle'
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml:ro
      - ./alertmanager/templates/:/etc/alertmanager/templates/:ro
      - ./alertmanager/certs/:/etc/alertmanager/certs/:ro
      - alertmanager_data_1:/alertmanager
    ports:
      - "127.0.0.1:9093:9093"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - monitoring-net

  alertmanager-node-2:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager-node-2
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.advertise-address=alertmanager-node-2:9094'
      - '--cluster.peer=alertmanager-node-1:9094'
      - '--cluster.peer=alertmanager-node-3:9094'
      - '--cluster.tls-config.cert-file=/etc/alertmanager/certs/alertmanager-node-2.crt'
      - '--cluster.tls-config.key-file=/etc/alertmanager/certs/alertmanager-node-2.key'
      - '--cluster.tls-config.ca-file=/etc/alertmanager/certs/ca.crt'
      - '--config.expand-env'
      - '--web.enable-lifecycle'
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml:ro
      - ./alertmanager/templates/:/etc/alertmanager/templates/:ro
      - ./alertmanager/certs/:/etc/alertmanager/certs/:ro
      - alertmanager_data_2:/alertmanager
    ports:
      - "127.0.0.1:9095:9093"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - monitoring-net

  alertmanager-node-3:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager-node-3
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
      - '--cluster.advertise-address=alertmanager-node-3:9094'
      - '--cluster.peer=alertmanager-node-1:9094'
      - '--cluster.peer=alertmanager-node-2:9094'
      - '--cluster.tls-config.cert-file=/etc/alertmanager/certs/alertmanager-node-3.crt'
      - '--cluster.tls-config.key-file=/etc/alertmanager/certs/alertmanager-node-3.key'
      - '--cluster.tls-config.ca-file=/etc/alertmanager/certs/ca.crt'
      - '--config.expand-env'
      - '--web.enable-lifecycle'
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml:ro
      - ./alertmanager/templates/:/etc/alertmanager/templates/:ro
      - ./alertmanager/certs/:/etc/alertmanager/certs/:ro
      - alertmanager_data_3:/alertmanager
    ports:
      - "127.0.0.1:9096:9093"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - monitoring-net

volumes:
  alertmanager_data_1:
  alertmanager_data_2:
  alertmanager_data_3:

networks:
  monitoring-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

В Prometheus `prometheus.yml` укажите все три инстанса:

```yaml
alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets:
            - 'alertmanager-node-1:9093'
            - 'alertmanager-node-2:9093'
            - 'alertmanager-node-3:9093'
```

Проверка кластерного статуса:

```bash
docker exec alertmanager-node-1 amtool cluster show
# → NODE         PEER        STATE
# → node-1       node-2      Ready
# → node-1       node-3      Ready
```

### Диагностика через amtool

Утилита `amtool` предустановлена в образе и позволяет управлять алертингом из терминала.

```bash
# Валидация синтаксиса конфигурации
docker exec alertmanager amtool check-config /etc/alertmanager/config.yml

# Просмотр активных оповещений
docker exec alertmanager amtool alert --alertmanager.url=http://localhost:9093

# Просмотр дерева маршрутизации
docker exec alertmanager amtool config routes show --config.file=/etc/alertmanager/config.yml

# Создание тишины (silence) для подавления шума
docker exec alertmanager amtool silence add alertname=NodeDown duration=1h comment="Scheduled maintenance"

# Просмотр активных тишин
docker exec alertmanager amtool silence

# Отмена тишины по ID
docker exec alertmanager amtool silence expire 12345-abcde...

# Проверка статуса кластера (HA)
docker exec alertmanager-node-1 amtool cluster show --alertmanager.url=http://localhost:9093

# Проверка статуса API
curl -s http://localhost:9093/-/healthy
```

### Валидация состояния

Комплексная проверка работоспособности Alertmanager в Docker:

```bash
# 1. Health endpoint
curl -s http://localhost:9093/-/healthy
# → OK

# 2. Readiness endpoint (запущены ли все receivers)
curl -s http://localhost:9093/-/ready
# → OK

# 3. Build info и версия
curl -s http://localhost:9093/api/v2/status/buildinfo | jq .version
# → "0.33.1"

# 4. Активные алерты
curl -s http://localhost:9093/api/v2/alerts | jq length
# → 0

# 5. Активные silences (проверка персистентности)
curl -s http://localhost:9093/api/v2/silences | jq length
# → 5

# 6. Метрики self-monitoring
curl -s http://localhost:9093/metrics | grep alertmanager_notifications_failed_total
# → alertmanager_notifications_failed_total{receiver="...",integration="...", ...} 0

# 7. Проверка конфигурации без запуска
docker run --rm -v ./alertmanager:/etc/alertmanager:ro prom/alertmanager:v0.33.1 \
  amtool check-config /etc/alertmanager/config.yml
# → SUCCESS

# 8. DNS-разрешение имён пиров (HA)
docker exec alertmanager-node-1 nslookup alertmanager-node-2
# → Non-authoritative answer: Name: alertmanager-node-2 Address: 172.28.0.3

# 9. Проверка открытых портов внутри контейнера
docker exec alertmanager netstat -tlnp
# → tcp        0      0 0.0.0.0:9093            0.0.0.0:*               LISTEN     1/alertmanager
# → tcp        0      0 0.0.0.0:9094            0.0.0.0:*               LISTEN     1/alertmanager
```

### Zero-downtime обновление и перезагрузка

Обновление конфигурации без потери алертов:

```bash
# 1. Валидация нового конфига
docker exec alertmanager amtool check-config /etc/alertmanager/config.yml

# 2. Reload через API (не рестарт контейнера)
curl -X POST http://localhost:9093/-/reload
# → {}

# 3. Проверка, что конфиг подхвачен
docker exec alertmanager amtool config routes show --alertmanager.url=http://localhost:9093

# Альтернатива: пересоздание контейнера (для обновления образа)
docker compose pull
docker compose up -d --no-deps --force-recreate alertmanager
docker compose ps alertmanager
```

Обновление образа в HA-кластере (rolling update):

```bash
# Обновляем узлы по одному, чтобы не потерять кворум
for node in alertmanager-node-1 alertmanager-node-2 alertmanager-node-3; do
  docker compose pull
  docker compose up -d --no-deps --force-recreate ${node}
  sleep 10
  docker exec ${node} amtool cluster show --alertmanager.url=http://localhost:9093
done
```

### Резервное копирование и восстановление

Бэкап конфигурации и состояния:

```bash
# Экспорт конфигурации
cp ./alertmanager/config.yml ./backups/alertmanager-config-$(date +%Y%m%d).yml

# Экспорт silences через API
curl -s http://localhost:9093/api/v2/silences > ./backups/alertmanager-silences-$(date +%Y%m%d).json

# Бэкап тома alertmanager_data
docker compose stop alertmanager
docker run --rm \
  -v alertmanager_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/alertmanager-data-$(date +%Y%m%d).tar.gz -C /data ./
docker compose start alertmanager
```

Восстановление:

```bash
# Остановка сервиса
docker compose stop alertmanager

# Удаление текущих данных
docker compose rm -f alertmanager
docker volume rm alertmanager_data
docker volume create alertmanager_data

# Восстановление из снапшота
docker run --rm \
  -v alertmanager_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/alertmanager-data-20260917.tar.gz -C /data

# Восстановление конфигурации
cp ./backups/alertmanager-config-20260917.yml ./alertmanager/config.yml

# Запуск
docker compose up -d alertmanager

# Проверка silences
curl -s http://localhost:9093/api/v2/silences | jq length
```

### Самонаблюдение Alertmanager

Добавьте в Prometheus алерты на состояние самого Alertmanager:

```yaml
groups:
  - name: alertmanager_self_monitoring
    rules:
      - alert: AlertmanagerDown
        expr: up{job="alertmanager"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Alertmanager {{ $labels.instance }} недоступен"
          runbook_url: "https://wiki.example.com/runbooks/alertmanager-down"

      - alert: AlertmanagerNotificationsFailing
        expr: rate(alertmanager_notifications_failed_total[5m]) > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Ошибки доставки уведомлений в {{ $labels.receiver }}"
          runbook_url: "https://wiki.example.com/runbooks/notification-failing"

      - alert: AlertmanagerClusterNotReady
        expr: alertmanager_cluster_members != 3
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Gossip-кластер Alertmanager не готов ({{ $value }} из 3 узлов)"
          runbook_url: "https://wiki.example.com/runbooks/am-cluster"

      - alert: AlertmanagerNotificationLatencyHigh
        expr: histogram_quantile(0.99, sum(rate(alertmanager_notification_latency_seconds_bucket[5m])) by (le)) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка доставки уведомлений (>30s)"
```

### Масштабирование и отказоустойчивость

**Standalone Compose (без Swarm):**

```bash
# Масштабирование Alertmanager до 3 реплик с shared gossip
docker compose up -d --scale alertmanager=3
```

> **Важно:** При масштабировании через `docker compose up --scale` каждый контейнер получает уникальное имя, но `--cluster.peer` нужно указывать явно или использовать headless service для DNS-обнаружения.

**Docker Swarm mode:**

```yaml
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    deploy:
      replicas: 3
      placement:
        constraints:
          - node.role == manager
      update_config:
        parallelism: 1
        delay: 10s
        order: start-first
      restart_policy:
        condition: on-failure
    networks:
      - monitoring-net
```

Для Swarm используйте `mode: global` для привязки одной реплики к каждому узлу, или `replicated` с явным указанием `replicas`.

**Рекомендации:**
- Минимум 3 реплики для HA (гарантирует кворум при потере одного узла).
- Максимальный практический размер кластера — ~16 узлов (при большем размере gossip overhead возрастает).
- Используйте одинаковые версии Alertmanager во всех узлах кластера.
- Хранилище silences должно быть персистентным для каждого узла.

### Восстановление после сбоя хоста

При перезагрузке хоста контейнеры запускаются в порядке, определяемом `depends_on` и `restart_policy`. Для Alertmanager:

```yaml
restart: unless-stopped

# Ожидание готовности Prometheus (если в одном compose)
depends_on:
  prometheus:
    condition: service_healthy
```

После восстановления хоста проверьте:

```bash
# Все контейнеры подняты?
docker compose ps

# Кластер gossip сформирован?
docker exec alertmanager-node-1 amtool cluster show

# Silences на месте?
curl -s http://localhost:9093/api/v2/silences | jq length

# Доставка работает?
curl -s http://localhost:9093/-/healthy
```

## Устранение неполадок в Docker

| Проблема | Причина | Решение |
|---|---|---|
| **Silences сбрасываются** | Не примонтирован volume `/alertmanager` | Проверьте секцию `volumes` в `compose.yml`. |
| **Переменные не подставляются** | Отсутствует флаг `--config.expand-env` | Добавьте флаг в команду запуска сервиса. |
| **Узлы HA не видят друг друга** | Неверный `advertise-address` или порт 9094 закрыт | Убедитесь, что узлы используют имена сервисов Docker Compose для связи и порт открыт внутри сети. |
| **Permission denied на данных** | Несоответствие прав UID | Выполните `chown -R 65534:65534 ./alertmanager_data`. |
| **Gossip-кластер не образуется** | Порт 9094 заблокирован или разные версии AM | Проверьте `docker exec alertmanager-node-1 amtool cluster show`; откройте порт в сетевой политике. |
| **Дублирующиеся уведомления** | Неправильная HA-конфигурация или отсутствие gossip | Проверьте `cluster.listen-address`, `cluster.peer` и открытый порт 9094. |
| **Config reload не работает** | Отсутствует `--web.enable-lifecycle` | Добавьте флаг в команду запуска и перезапустите контейнер. |
| **`/-/reload` возвращает 404** | Флаг `--web.enable-lifecycle` не активен | Проверьте запущенный процесс: `docker exec alertmanager ps aux`. |
| **Alerts не доставляются в Slack/Telegram** | Неверный URL, токен, или чат/канал недоступен | Проверьте `alertmanager_notifications_failed_total` и логи контейнера. |
| **Inhibition не работает** | Неправильные `equal` или `source_match`/`target_match` | Проверьте, что алерты содержат нужные метки и severity. |
| **Mute timing не применяется** | Неверный формат `time_range` или часовой пояс | Alertmanager использует UTC; проверьте `time_range` и `weekdays`. |
| **High memory usage** | Слишком много активных silences или алертов | Ограничьте retention (`--data.retention=48h`) и добавьте purge cron. |
| **SMTP доставка падает** | TLS handshake failed, спам-фильтр, неверный from | Проверьте `require_tls`, сертификаты и SPF/DKIM для домена. |
| **Webhook таймаут** | Целевой сервис недоступен или медленный | Увеличьте `timeout` в `webhook_configs` и проверьте сетевую доступность. |

## Рекомендации SRE

1.  **Actionable Alerts:** Каждый алерт должен иметь аннотацию `runbook_url`. Если на алерт нельзя отреагировать действием — это не алерт, а шум.
2.  **Symptom-based Alerting:** Алертите на симптомы (ошибки, задержки), а не на причины.
3.  **NoData — это алерт:** Всегда настраивайте алерты на отсутствие данных (`absent()`) от критических систем.
4.  **Группировка:** Используйте `group_by` на `cluster` или `service`, чтобы видеть масштаб проблемы, а не отдельные инстансы.
5.  **Мета-мониторинг:** Добавьте алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0` — «тихий» сбой доставки остаётся незамеченным без мониторинга самого алертинга.
6.  **Дедупликация:** В HA-режиме всегда включайте gossip (порт 9094), иначе при рестарте одного из Prometheus вы получите дубли уведомлений.
7.  **Inhibition:** Используйте inhibition для подавления зависимых алертов, но регулярно пересматривайте правила, чтобы не замаскировать проблему.
8.  **Mute Timings vs Silences:** Используйте Mute Timings для плановых окон (ночные смены), а Silences — для инцидентов и работ. Удаляйте временные Silences после инцидентов.
9.  **Бэкап silences:** Регулярно экспортируйте silences через API (`curl -s http://localhost:9093/api/v2/silences > backup.json`) перед массовыми изменениями.
10. **Безопасность:** Никогда не открывайте порт 9093 наружу без reverse proxy с Basic Auth/TLS. Портом 9094 вообще не должен быть доступен с хоста.

## Дополнительная информация

### Связанные темы

* [Alertmanager — архитектура и API](../../alertmanager.md) — детальный разбор маршрутизации и группировки.
* [Конфигурация Docker Compose](./docker-compose_config.md) — production-ready compose для локального стека.
* [Конфигурация Prometheus](./prometheus_config.md) — настройка отправки алертов.
* [Мониторинг Docker Engine](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.