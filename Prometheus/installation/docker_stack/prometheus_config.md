# Конфигурация Prometheus для Docker Compose

## Определения

**Конфигурация Prometheus в Docker Stack** — это совокупность файлов (`prometheus.yml`, `web-config.yml`, файлы правил), монтируемых в контейнер для управления сбором, обработкой и безопасностью метрик. В среде Docker Compose конфигурация адаптируется для работы с внутренним DNS, монтируемыми томами, переменными окружения и CLI-флагами, переопределяющими параметры, которые в обычном развёртывании задаются в `prometheus.yml`.

> **См. также:** [Конфигурация Prometheus](../../configuration.md) — общая структура `prometheus.yml`, CLI-флаги, retention, remote read/write, Agent Mode, OTLP.

## Основные концепции

### Пути и монтирование конфигурации

Для корректной работы Prometheus v3 в Docker рекомендуется использовать раздельное монтирование для конфигурации и данных. В дополнение к базовым путям,В производственной среде применяются `tmpfs` для чувствительных временных данных и политики `read_only` для минимизации поверхности атаки контейнера.

| Ресурс | Хост-путь | Контейнер-путь | Описание |
|---|---|---|---|
| Основной конфиг | `./prometheus/prometheus.yml` | `/etc/prometheus/prometheus.yml` | Основные scrape-цели и глобальные настройки |
| Файлы правил | `./prometheus/rules/*.yml` | `/etc/prometheus/rules/` | Recording и Alerting rules |
| Безопасность | `./prometheus/web-config.yml` | `/etc/prometheus/web-config.yml` | TLS и Basic Auth (опционально) |
| Хранилище (TSDB) | `prometheus_data` (volume) | `/prometheus` | База данных метрик |
| Временные данные (tmpfs) | — | `/tmp` | WAL буферы, временные файлы утилит |
| Секреты (Docker secret) | secret | `/run/secrets/` | Креды для remote_write, OAuth2, credentialsFile |

**Рекомендации по монтированию:**
- Конфигурационные файлы монтируются с флагом `:ro` для предотвращения случайной модификации из контейнера.
- Том `prometheus_data` должен иметь явно заданного владельца `UID=65534` (`nobody`), так как официальный образ Prometheus запускается от непривилегированного пользователя.
- Директория с правилами (`rules/`) должна существовать на хосте до первого запуска; иначе Docker создаст её от `root`, и Prometheus не сможет прочитать файлы.

### Структура prometheus.yml (Docker-специфика)

Полное описание всех секций `prometheus.yml` приведено в [Конфигурация Prometheus](../../configuration.md). В Docker Compose важно разграничить, что задаётся в YAML-конфиге, а что — через CLI-флаги в `compose.yml`, потому что переопределение CLI-флагами имеет более высокий приоритет.

| Параметр | Где задаётся в Docker | Приоритет |
|---|---|---|
| `scrape_interval`, `evaluation_interval` | `prometheus.yml` (`global`) или CLI | CLI > YAML |
| `retention.time`, `retention.size` | Только CLI (`--storage.tsdb.*`) | — |
| `web.config.file` | Только CLI | — |
| `web.enable-lifecycle` | Только CLI | — |
| `storage.tsdb.wal-compression` | Только CLI | — |
| `external_labels` | `prometheus.yml` | — |

**Важно:** CLI-флаги, задаваемые в `command:` или `args:` compose-сервиса, переопределяют одноимённые параметры в `prometheus.yml`. Это используется для управления retention и включения hot reload без изменения файла конфигурации.

### Docker DNS и scrape-цели

В Docker Compose сервисы, находящиеся в одной сети, доступны друг другу по именам, объявленным в `compose.yml`. Prometheus разрешает эти имена через встроенный Docker DNS.

| Сервис | Имя в scrape_config | Порт |
|---|---|---|
| Prometheus (self) | `localhost` | 9090 |
| Node Exporter | `node-exporter` | 9100 |
| Alertmanager | `alertmanager` | 9093 |
| cAdvisor | `cadvisor` | 8080 |

**Особенности работы с сетью:**
- **`localhost`**: Всегда указывает на сам контейнер Prometheus. Не используется для обращения к другим сервисам Compose.
- **`host.docker.internal`**: Используется для обращения к сервисам, запущенным напрямую на хост-машине (требует `extra_hosts` в `compose.yml` или `network_mode: host`).
- **Сетевая изоляция**: Если экспортёр находится в другой сети Docker, он будет недоступен без явного добавления Prometheus в эту сеть через `networks:` в сервисе.
- **Headless-сервисы**: Для сервисов с `mode: global` в Swarm или `deploy.replicas > 1` в Compose v3.8+ Docker DNS возвращает все экземпляры. Prometheus автоматически опрашивает каждый IP.
- **DNS кэширование**: Docker кэширует DNS-записи на время TTL (по умолчанию 60с). При изменении `compose.yml` (например, добавлении нового сервиса) кэш не обновляется мгновенно. Используйте `docker compose up -d --force-recreate` или подождите TTL.

### external_labels

`external_labels` добавляют статические метки ко **всем** метрикам, отправляемым через Remote Write или Federation. Это позволяет различать данные от разных инстансов Prometheus в централизованном хранилище.

```yaml
global:
  external_labels:
    origin: 'docker-stack'
    cluster: '${CLUSTER_NAME:-production}'
    region: 'eu-west-1'
```

**Ограничения и правила:**
- Не используйте `external_labels` для идентификации отдельных таргетов; для этого применяйте `relabel_configs`.
- Изменение `external_labels` без перезапуска может привести к дублированию рядов в Remote Write-хранилище, потому что старые и новые метки будут считаться разными временными рядами.
- Имена меток из `external_labels` зарезервированы; не создавайте метки с такими же именами в recording rules или relabeling, иначе произойдёт конфликт.
- В Federation на Master-сервере `external_labels` Leaf-инстансов используются для маршрутизации; убедитесь, что они уникальны в пределах одного Master.

### Параметры scrape

Каждый `job` в `scrape_configs` поддерживает параметры, управляющие частотой, объёмом и форматом сбора данных. В Prometheus v3 появилась поддержка нативных гистограмм и расширенные лимиты.

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    scrape_interval: 15s          # Как часто опрашивать таргет
    scrape_timeout: 10s           # Таймаут одного запроса (должен быть < scrape_interval)
    metrics_path: '/metrics'      # Путь эндпоинта метрик
    scheme: 'http'                # http или https
    honor_labels: true            # Доверять меткам от экспортера (не перезаписывать)
    honor_timestamps: true        # Использовать timestamp из экспортера
    scrape_native_histograms: true # Включить сбор нативных гистограмм (v3)

    # Лимиты кардинальности
    sample_limit: 100000          # Максимум samples с одного таргета за scrape
    target_limit: 100             # Максимум таргетов в job
    label_limit: 40               # Максимум лейблов на одну метрику
    body_size_limit: 15MB         # Максимальный размер ответа /metrics

    static_configs:
      - targets: ['node-exporter:9100']
```

**Рекомендации:**
- `scrape_timeout` должен быть минимум на 2–3 секунды меньше `scrape_interval`, чтобы дать запас на сетевые задержки.
- `body_size_limit: 0` отключает ограничение; в production всегда задавайте значение, чтобы защититься от утечек памяти при аномально больших ответах.
- `honor_labels: false` (по умолчанию) заставляет Prometheus перезаписывать метки `job` и `instance` своими значениями. Используйте `true` для Pushgateway и кастомных экспортеров, где важно сохранить оригинальные метки.

### Динамическое обнаружение (Docker SD)

Вместо статического перечисления `targets` можно использовать `docker_sd_config`. Это позволяет Prometheus автоматически находить все запущенные контейнеры, соответствующие заданным критериям.

**Требование:** Контейнер Prometheus должен иметь доступ к Docker Socket:
```yaml
# compose.yml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

**Конфигурация в `prometheus.yml`:**
```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_config:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      # Собирать метрики только с контейнеров с меткой 'prometheus_scrape=true'
      - source_labels: [__meta_docker_container_label_prometheus_scrape]
        regex: true
        action: keep
      # Исключить сам Prometheus из списка целей
      - source_labels: [__meta_docker_container_name]
        regex: .*prometheus.*
        action: drop
      # Использовать имя сервиса Compose как инстанс
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: container_service
      # Использовать IP контейнера как адрес для скрейпинга
      - source_labels: [__meta_docker_container_network_ip]
        regex: .+
        replacement: ${1}
        target_label: __address__
      - source_labels: [__meta_docker_container_network_ip]
        regex: ^$
        replacement: localhost
        target_label: __address__
      # Удалить служебные метки Docker
      - action: labeldrop
        regex: __meta_.+
```

**Фильтры по Docker SD:**
- `__meta_docker_container_label_<имя_метки>` — фильтрация по label контейнера.
- `__meta_docker_container_state_running` — только запущенные контейнеры (`true`).
- `__meta_docker_network_name` — фильтр по имени сети Docker.

### Exemplars

Exemplars — это отдельные точки данных внутри гистограммы, показывающие конкретный trace ID или пример запроса, который попал в корзину. В Prometheus v3 поддержка exemplars включена по умолчанию при использовании нативных гистограмм.

```yaml
scrape_configs:
  - job_name: 'service-with-traces'
    scrape_native_histograms: true
    exemplars:
      max_exemplars: 100000  # Лимит exemplars на одну метрику
    static_configs:
      - targets: ['app:8080']
```

**Ограничения:**
- Exemplars хранятся в отдельном блоке Head в TSDB и потребляют дополнительную память. При высокой кардинальности снизьте `max_exemplars` или используйте `metric_relabel_configs` для удаления ненужных exemplars.
- При Remote Write exemplars отправляются только если бэкенд поддерживает protobuf и флаг `send_exemplars: true` (см. раздел Remote Write).

### Readiness и Liveness probes

В Docker Compose для Prometheus рекомендуется настроить два типа probes, чтобы оркестратор корректно отслеживал состояние сервиса:

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.13.1
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    # readiness_probe и liveness_probe задаются только в Swarm/Kubernetes;
    # в Compose v3.9+ используйте profiles или внешние оркестраторы.
```

**Эндпоинты для мониторинга:**
- `/-/healthy` — возвращает 200, если TSDB и конфигурация загружены корректно.
- `/-/ready` — возвращает 200, если Prometheus готов принимать запросы (все scrape targets обнаружены и синхронизированы).
- `/-/config` — возвращает текущий конфиг (может содержать секреты, если заданы в YAML; см. раздел Безопасность).

## Практические сценарии

### Базовая конфигурация (Prometheus v3)

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    origin: 'docker-stack'

rule_files:
  - "/etc/prometheus/rules/*.yml"

alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets: ['alertmanager:9093']

scrape_configs:
  - job_name: 'prometheus'
    scrape_native_histograms: true
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

### Production-ready конфигурация

Полный пример production-ready `prometheus.yml` с учётом ограничений кардинальности, защиты от флуда и оптимальных интервалов для Docker-среды:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    origin: 'docker-stack'
    cluster: '${CLUSTER_NAME:-production}'

# Ограничения глобальных запросов (защита от тяжелых PromQL)
query:
  max_concurrency: 20
  max_samples: 50000000
  timeout: 2m

# Включение нативных гистограмм по умолчанию
storage:
  tsdb:
    wal-compression: true

rule_files:
  - "/etc/prometheus/rules/*.yml"

alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets: ['alertmanager:9093']
      timeout: 10s

scrape_configs:
  - job_name: 'prometheus'
    scrape_interval: 15s
    scrape_native_histograms: true
    static_configs:
      - targets: ['localhost:9090']
    relabel_configs:
      - source_labels: [__address__]
        replacement: localhost:9090
        target_label: __address__

  - job_name: 'node-exporter'
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets: ['node-exporter:9100']
    relabel_configs:
      - source_labels: [__address__]
        replacement: node-exporter:9100
        target_label: __address__

  - job_name: 'cadvisor'
    scrape_interval: 20s
    scrape_timeout: 15s
    static_configs:
      - targets: ['cadvisor:8080']
    relabel_configs:
      - source_labels: [__address__]
        replacement: cadvisor:8080
        target_label: __address__

remote_write:
  - url: "http://remote-storage:8428/api/v1/write"
    name: 'primary-backend'
    send_exemplars: true
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
      max_backoff: 1s
      min_backoff: 100ms
      retry_on_http_429: true
    timeout: 30s
```

### Docker Compose: сервис Prometheus

Минимальный фрагмент `compose.yml` для сервиса Prometheus с учётом безопасности, ресурсов и мониторинга состояния:

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: prometheus
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
      - seccomp:default
    cap_drop:
      - ALL
    tmpfs:
      - /tmp:noexec,nosuid,size=1g
    read_only: true
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/rules:/etc/prometheus/rules:ro
      - ./prometheus/web-config.yml:/etc/prometheus/web-config.yml:ro
      - prometheus_data:/prometheus
      - /etc/localtime:/etc/localtime:ro
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
      - '--storage.tsdb.retention.size=50GB'
      - '--storage.tsdb.wal-compression'
      - '--web.enable-lifecycle'
      - '--web.config.file=/etc/prometheus/web-config.yml'
      - '--auto-gomemlimit'
      - '--auto-gomaxprocs'
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    depends_on:
      node-exporter:
        condition: service_healthy
      alertmanager:
        condition: service_healthy
    networks:
      - monitoring
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G

volumes:
  prometheus_data:

networks:
  monitoring:
    driver: bridge
```

**Пояснения к параметрам:**
- `user: "65534:65534"` — запуск от непривилегированного пользователя (встроенный в образ).
- `read_only: true` + `tmpfs` — запрет записи в корневую ФС контейнера; WAL и временные файлы размещаются в tmpfs.
- `cap_drop: [ALL]` — отзыв всех Linux capabilities; повышение привилегий заблокировано.
- `security_opt.no-new-privileges:true` — запрет на повышение привилегий через setuid/setgid.
- `depends_on.condition` — ожидание готовности зависимых сервисов перед стартом Prometheus (требует healthcheck в зависимых сервисах).

### Настройка Remote Write

Remote Write позволяет экспортировать метрики в долгосрочные хранилища (VictoriaMetrics, Grafana Mimir, Thanos Receive, ClickHouse). В Prometheus v3 конфигурация поддерживает несколько бэкендов одновременно.

```yaml
remote_write:
  - url: "http://vmstorage:8428/api/v1/write"
    name: 'victoriametrics'
    send_exemplars: true
    timeout: 30s
    headers:
      X-Scope-OrgID: 'monitoring'
    basic_auth:
      username: "prometheus"
      password: "${REMOTE_PASSWORD}"
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      cert_file: /etc/prometheus/certs/client.crt
      key_file: /etc/prometheus/certs/client.key
      insecure_skip_verify: false
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
      max_backoff: 1s
      min_backoff: 100ms
      retry_on_http_429: true
      capacity: 10000

  - url: "https://mimir.corp.local/api/v1/push"
    name: 'mimir'
    authorization:
      type: Bearer
      credentials: '/run/secrets/mimir-token'
    oauth2:
      client_id: 'prometheus'
      client_secret_file: '/run/secrets/oauth2-client-secret'
      token_url: 'https://keycloak.corp.local/realms/monitoring/protocol/openid-connect/token'
      scopes: ['read', 'write']
    queue_config:
      max_samples_per_send: 500
      batch_send_deadline: 10s
      max_backoff: 5s
      min_backoff: 500ms
      retry_on_http_429: true
      capacity: 50000
```

**Аутентификация и авторизация:**
- `basic_auth` — базовая аутентификация. Избегайте хранения паролей в YAML; используйте переменные окружения (в Compose) или `credentialsFile`.
- `authorization` — заголовок `Authorization` произвольного типа (Bearer, Basic, Digest). Рекомендуется для токенов.
- `oauth2` — автоматическое получение токена по OAuth2. Подходит для корпоративных Identity Provider (Keycloak, Dex).
- `tls_config` — настройка mTLS и проверки сертификатов. `insecure_skip_verify: false` — обязательно в production.
- `credentialsFile` (v3) — путь к файлу с секретом (пароль, токен). Prometheus перечитывает файл при hot reload, что упрощает ротацию секретов без перезапуска контейнера.

**Queue Config параметры:**
- `max_samples_per_send` — количество samples в одном HTTP-запросе. Слишком большое значение увеличивает латентность и риск потери данных при обрыве; слишком маленькое — нагрузку на сеть и бэкенд.
- `batch_send_deadline` — максимальное время ожидания накопления батча. Если за это время не набралось `max_samples_per_send`, отправка происходит принудительно.
- `max_backoff` / `min_backoff` — экспоненциальный backoff при ошибках сети.
- `retry_on_http_429` — повторная отправка при получении `429 Too Many Requests`. Включите, если бэкенд применяет rate limiting.
- `capacity` — размер внутренней очереди в памяти. При заполнении очереди Prometheus начинает дропить старые samples.

### Безопасность Web UI (Basic Auth + TLS)

Для защиты веб-интерфейса Prometheus в Docker используется файл `web-config.yml`, монтируемый в контейнер.

**1. Создайте хэш пароля:**
```bash
docker run --rm httpd:alpine htpasswd -nbB admin 'StrongPassword123' | cut -d: -f2
# → $2y$12$...
```

**2. Файл `prometheus/web-config.yml`:**
```yaml
basic_auth_users:
  admin: "$2y$12$..." # bcrypt хэш

tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
  client_auth_type: RequireAndVerifyClientCert # mTLS (опционально)
  client_ca_file: /etc/prometheus/certs/ca.crt
```

**3. В `compose.yml` добавьте флаг запуска:**
```yaml
services:
  prometheus:
    command:
      - '--web.config.file=/etc/prometheus/web-config.yml'
    volumes:
      - ./prometheus/certs:/etc/prometheus/certs:ro
```

**Важно:**
- В Prometheus v3 секреты можно вынести из YAML в отдельные файлы с помощью `credentialsFile` (например, `basic_auth_password: credentialsFile("/run/secrets/prom-password")`).
- Никогда не указывайте секреты напрямую в `prometheus.yml`. Используйте `credentialsFile` или переменные окружения, передаваемые через Docker secrets.
- TLS 1.0 и 1.1 не поддерживаются Prometheus v3. Используйте сертификаты с ГОСТ/совместимостью TLS 1.2+.
- Basic Auth без TLS передаёт пароли в base64, что эквивалентно открытому тексту. Всегда используйте TLS при Basic Auth.

### Hot Reload

Обновление параметров `prometheus.yml` (кроме CLI-флагов) возможно без перезапуска процесса.

**Предварительное требование:** Флаг `--web.enable-lifecycle` должен быть задан в `command:` сервиса.

**Способы reload:**
```bash
# Через HTTP API (внутри сети Docker):
curl -X POST http://prometheus:9090/-/reload
# → Если успешно, вернётся пустой ответ с HTTP 200

# Через host-машину (с учётом проброса порта):
curl -X POST http://localhost:9090/-/reload -u admin:pass
```

**Что происходит при reload:**
1. Prometheus парсит новый `prometheus.yml`.
2. Проверяет синтаксис; при ошибке возвращает 400 и оставляет старую конфигурацию активной.
3. При успехе обновляет scrape targets, rules и alerting без остановки сбора метрик.

**Ограничения:**
- CLI-флаги (retention, `--web.listen-address`, `--query.max-concurrency`) **нельзя** изменить через reload. Требуется перезапуск контейнера.
- Изменения в `web-config.yml` (Basic Auth, TLS) также требуют перезапуска.
- Reload во время записи в Remote Write может привести к временному дропу samples; это нормально, queue восстановится автоматически.
- После reload проверьте успешность: `curl -u admin:pass http://localhost:9090/api/v1/status/config | jq '.status'` или метрика `prometheus_config_last_reload_successful`.

### Валидация и проверка

Перед reload или развёртыванием выполните валидацию:

```bash
# Проверка синтаксиса конфигурации (Server Mode)
docker exec prometheus promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: prometheus.yml is valid

# Проверка файлов правил
docker exec prometheus promtool check rules /etc/prometheus/rules/*.yml

# Проверка TSDB на ошибки
docker exec prometheus promtool tsdb analyze /prometheus

# Проверка статуса конфигурации через API
curl -u admin:pass http://localhost:9090/api/v1/status/config | jq '.status'
# → "success"

# Проверка времени последнего reload
curl -u admin:pass http://localhost:9090/api/v1/query?query=prometheus_config_last_reload_success_timestamp_seconds

# Проверка здоровья
curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/healthy
# → 200

# Проверка готовности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/ready
# → 200

# Просмотр всех targets
curl -u admin:pass http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
```

### Диагностика типичных проблем

| Проблема | Причина | Проверка | Решение |
|---|---|---|---|
| `config reload failed` | Ошибка в `prometheus.yml` или правах | `docker logs prometheus 2>&1 | grep -i reload` | Проверить YAML-синтаксис, права на файлы (`chmod 644`), выполнить `promtool check config` |
| Targets в `DOWN` | Ошибка DNS, неверный порт, фаервол | `docker exec prometheus nslookup node-exporter`; `curl -v http://node-exporter:9100/metrics` | Проверить сеть Docker (`docker network inspect monitoring`), healthcheck зависимых сервисов |
| `scrape timeout` | Большая кардинальность, медленный экспортер | `curl -w "%{time_total}" http://node-exporter:9100/metrics` | Увеличить `scrape_timeout`, оптимизировать экспортер, добавить `sample_limit` |
| `sample limit exceeded` | Превышен `sample_limit` в job | Метрика `prometheus_target_scrapes_exceeded_sample_limit_total` | Увеличить `sample_limit` или добавить `metric_relabel_configs` для удаления не нужных метрик |
| `OOMKilled` | Недостаток памяти, отсутствует `--auto-gomemlimit` | `docker inspect prometheus --format='{{.State.OOMKilled}}'` | Увеличить `deploy.resources.limits.memory`, добавить флаг `--auto-gomemlimit` |
| `secret leaked in /-/config` | Секреты указаны в `prometheus.yml` | `curl -u admin:pass http://localhost:9090/api/v1/status/config` | Перенести секреты в `credentialsFile` или env vars |
| `hot reload не работает` | Флаг `--web.enable-lifecycle` отсутствует | `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:9090/-/reload` | Добавить флаг в `command:` и перезапустить контейнер |
| `retention не применяется` | Параметр задан в `prometheus.yml`, а не в CLI | `docker inspect prometheus --format='{{.Config.Cmd}}'` | Переместить `--storage.tsdb.retention.time` в `command:` compose-сервиса |

### Резервное копирование и восстановление

Резервное копирование конфигурации:

```bash
# Создание снапшота TSDB (требует остановки записи или использования sidecar)
docker exec prometheus promtool tsdb snapshot /prometheus
# → Создаст директорию в /prometheus/snapshots/YYYYmmddHHMMSS

# Копирование снапшота на хост
docker cp prometheus:/prometheus/snapshots/<timestamp> ./backups/prometheus-snapshot

# Резервное копирование конфигурационных файлов
tar czf prometheus-config-backup.tar.gz ./prometheus/prometheus.yml ./prometheus/rules ./prometheus/web-config.yml
```

Восстановление:

```bash
# Остановка Prometheus
docker compose stop prometheus

# Восстановление конфигов
tar xzf prometheus-config-backup.tar.gz -C ./prometheus/

# Запуск с новой директорией данных (или восстановление снапшота)
docker compose up -d prometheus
```

**Важно:** При восстановлении снапшота убедитесь, что версия Prometheus совпадает с версией, на которой создавался снапшот. TSDB формат не гарантирует обратную совместимость между мажорными версиями.

### Обновление и откат

Обновление образа Prometheus в Docker Compose:

```bash
# Обновление образа с проверкой конфигурации
docker compose pull prometheus
docker compose up -d --no-deps prometheus

# Проверка работоспособности
docker exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker exec prometheus wget -qO- http://localhost:9090/-/healthy
```

Откат на предыдущую версию:

```bash
# Откат образа
docker compose pull prometheus:v3.12.0
docker compose up -d --no-deps prometheus

# Если данные несовместимы, запустите с новой директорией и восстанавливайте снапшот
docker compose down prometheus
docker volume rm monitoring_prometheus_data
docker compose up -d prometheus
```

### Очистка данных и конфигурации

Удаление устаревших данных и логов:

```bash
# Очистка WAL и временных файлов (внутри контейнера)
docker exec prometheus find /prometheus/wal -type f -mtime +7 -delete

# Удаление старых снапшотов
docker exec prometheus find /prometheus/snapshots -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;

# Очистка неиспользуемых образов и volumes
docker system prune -a --volumes
```

**Предупреждение:** Удаление файлов WAL вручную может привести к corruption TSDB. Используйте `promtool tsdb analyze` для диагностики перед очисткой.

## Дополнительная информация

### Проверка и обслуживание в Docker

| Задача | Команда |
|---|---|
| **Валидация конфига** | `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml` |
| **Валидация правил** | `docker exec prometheus promtool check rules /etc/prometheus/rules/*.yml` |
| **Hot Reload** | `curl -X POST http://prometheus:9090/-/reload` (требует `--web.enable-lifecycle`) |
| **Статус конфигурации** | `curl -u admin:pass http://localhost:9090/api/v1/status/config \| jq` |
| **Статус reload** | `curl -u admin:pass http://localhost:9090/api/v1/query?query=prometheus_config_last_reload_successful` |
| **Просмотр целей** | `curl -u admin:pass http://localhost:9090/api/v1/targets` |
| **Здоровье** | `curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/healthy` |
| **Готовность** | `curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/ready` |
| **Анализ TSDB** | `docker exec prometheus promtool tsdb analyze /prometheus` |
| **Создание снапшота** | `docker exec prometheus promtool tsdb snapshot /prometheus` |

### Оптимизация ресурсов (v3)

Флаги для предотвращения OOM Killer в контейнерах с жёсткими лимитами:
- **`--auto-gomemlimit`**: Автоматическая настройка предела памяти Go на основе лимитов контейнера. В v3 включён по умолчанию. При необходимости задайте явно: `--auto-gomemlimit=0.9` (90% от лимита контейнера).
- **`--auto-gomaxprocs`**: Синхронизация количества потоков Go с выделенными CPU-ресурсами. В v3 включён по умолчанию.

**Рекомендации по лимитам для Docker:**
- Минимум: `2 CPU`, `4GB` RAM (при retention 7d, < 100 targets).
- Production: `4 CPU`, `8GB` RAM (при retention 30d, < 1000 targets).
- Высоконагруженные: `8 CPU`, `16GB` RAM + отдельный том NVMe для TSDB.

### Ограничения и граничные случаи

- **Hot Reload и WAL**: При reload Prometheus переоткрывает файлы конфигурации, но не останавливает запись в WAL. Это безопасно, но при изменении `external_labels` возможны дубликаты рядов в Remote Write до следующего compaction.
- **Docker DNS кэш**: При массовом обновлении контейнеров DNS-кэш Docker может возвращать устаревшие IP. Используйте `docker compose up --force-recreate` или подождите TTL.
- **Volume permissions**: Если том `prometheus_data` создан от `root`, Prometheus не сможет писать в него. Проверьте: `docker exec prometheus ls -la /prometheus` (владелец должен быть UID 65534).
- **Retention в Compose**: Параметры `--storage.tsdb.retention.time` и `--storage.tsdb.retention.size` задаются только через CLI. Если они заданы одновременно, удаление происходит по первому наступившему условию.
- **Secrets в Docker Swarm**: В Swarm-режиме используйте `secrets:` вместо `environment:` для передачи кредов. В Compose (standalone) можно монтировать файлы через `volumes:` с правами `:ro`.
- **Read-only контейнер**: При `read_only: true` убедитесь, что все пути (кроме `/prometheus` и `/tmp`) доступны для записи через `tmpfs` или том. В противном случае Prometheus упадёт с ошибкой `permission denied`.

### Связанные темы

* [Конфигурация Prometheus](../../configuration.md) — детальный разбор всех секций `prometheus.yml`.
* [Docker Compose конфигурация](./docker-compose_config.md) — полный `compose.yml` для всего стека, healthcheck, security options, логирование.
* [Docker Compose Alertmanager](./docker_compose_alertmanager_config.md) — настройка уведомлений.
* [Удалённые хосты](./remote_hosts_monitoring.md) — мониторинг внешних нод через Node Exporter.
* [Безопасность Prometheus](../../security.md) — общий обзор защиты, TLS, Basic Auth, секреты.
* [Federation](../../scaling/federation.md) — иерархический сбор метрик между инстансами Prometheus.
