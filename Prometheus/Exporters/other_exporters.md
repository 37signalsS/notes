# Другие экспортеры Prometheus: Полный каталог

## Определения

**Другие экспортеры** — систематизированный перечень агентов и встроенных механизмов мониторинга для различных технологических стеков. Они преобразуют метрики целевых систем (баз данных, веб-серверов, очередей, сетевого оборудования) в формат Prometheus.

В современных реалиях 2026 года подходы к сбору метрик делятся на три типа:
1.  **Внешние экспортеры (Standalone/Sidecar):** Отдельные процессы для систем без встроенной поддержки (MySQL, PostgreSQL, Linux).
2.  **Нативный экспорт (Native Support):** Встроенные эндпоинты `/metrics` в самом ПО. Это предпочтительный метод, не требующий дополнительных агентов (RabbitMQ, Angie, Traefik).
3.  **Универсальные коллекторы:** Использование [OpenTelemetry Collector](../../OpenTelemetry/opentelemetry_overview.md) как единого шлюза для трансляции логов и метрик.

**См. также:** [Обзор экспортеров](./overview.md), [Принципы работы экспортера](./overview.md#принцип-работы-экспортера).

## Предварительные требования

*   **ОС:** Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+, Rocky Linux 9+), BSD или macOS. Для Linux требуется systemd или cron для периодических задач.
*   **Архитектура:** amd64, arm64, armv7, ppc64le, s390x — большинство экспортеров имеют кросс-платформенные бинарники.
*   **Права доступа:**
    *   Для доступа к метрикам ядра (`diskstats`, `hwmon`, `edac`) рекомендуется запуск от `root`.
    *   При запуске от непривилегированного пользователя добавьте его в группы `disk`, `hwmon`, `adm`.
*   **Файловые системы:** Метрики файловых систем собираются из `/proc/mounts` и `/proc/self/mountinfo`. Для корректной работы в контейнерах требуется монтирование `/proc` и `/sys` хоста.
*   **Сеть:** Порт экспортера должен быть доступен для Prometheus-сервера. При использовании TLS/basic auth убедитесь, что конфигурационный файл `web-config.yml` корректно сформирован.
*   **Ресурсы:** Рекомендуемые лимиты — не более 150m CPU и 128Mi RAM на инстанс. При включении тяжелых коллекторов может потребоваться увеличение до 300m CPU.

## Основные концепции

### Категоризация

Каталог разбит по типам целевых систем. Для каждой системы указаны:
*   Рекомендуемый инструмент скрапинга.
*   Тип (нативный или внешний).
*   Стандартный порт (важно для настройки `scrape_configs` и Service Discovery).
*   Ссылка на профильную SSoT-статью в базе знаний (если применимо).

### Паттерны развертывания

Выбор паттерна зависит от инфраструктуры и требований к изоляции:

| Паттерн | Сценарий | Примеры |
| :--- | :--- | :--- |
| **Standalone binary + systemd** | Базовые машины, bare-metal, VM | `node_exporter`, `mysqld_exporter`, `blackbox_exporter` |
| **Sidecar** | Боковой контейнер рядом с основным приложением | `postgres_exporter` в StatefulSet, `redis_exporter` рядом с Redis |
| **DaemonSet** | Один экземпляр на узел кластера | `node_exporter`, `snmp_exporter` |
| **Deployment (single/multi)** | Централизованный сбор с множества целей | `blackbox_exporter`, `snmp_exporter` (multi-target) |

---


## Практические сценарии: Каталог экспортеров

### 1. Базы данных (Databases)

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **mysqld_exporter** | MySQL/MariaDB. Требует пользователя с `GRANT PROCESS`, `REPLICATION CLIENT`, `SHOW DATABASES`, `SHOW VIEW`. | Внешний | 9104 | **[MySQL](../../Databases/MySQL/overview.md)** |
| **postgres_exporter** | PostgreSQL. Анализ таблиц `pg_stat_*`, `pg_locks`, `pg_replication_slot`. | Внешний | 9187 | **[PostgreSQL](../../Databases/PostgreSQL/overview.md)** |
| **redis_exporter** | Redis. Поддерживает сбор по нескольким URI, кластеры, sentinel. ACL (Redis 6+). | Внешний | 9121 | **[Redis Exporter](./redis_exporter.md)** |
| **mongodb_exporter** | MongoDB. Метрики через `serverStatus`, `replSetGetStatus`. | Внешний | 9216 | **[MongoDB](../../Databases/MongoDB/mongodb.md)** |
| **elasticsearch_exporter** | Elasticsearch. Состояние кластера, индексов, shards, nodes. | Внешний | 9114 | **[Elasticsearch](../../ELK_Stack/Elasticsearch/elasticsearch_overview.md)** |
| **consul_exporter** | Consul. Health Checks, лидерство, KV, service catalog. | Внешний | 9107 | **[Consul](../../Consul/consul_overview.md)** |
| **clickhouse_exporter** | ClickHouse. Метрики системы, merges, parts, replication. | Внешний | 9116 | **[ClickHouse](../../Databases/ClickHouse/clickhouse.md)** |

### 2. Веб-серверы и L7 Прокси

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **Angie (нативно)** | Встроенный модуль `prometheus_zone`. Нативный экспорт без внешних зависимостей. | Нативный | 80/443 | **[Angie](../../WebServers/Angie/angie_overview.md)** |
| **Traefik (нативно)** | Мониторинг Gateway API, Ingress, middlewares, routers. Автоматическое обнаружение через Provider (Docker, K8s). | Нативный | 8080 | **[Traefik](../../WebServers/Traefik/traefik_overview.md)** |
| **nginx-prometheus-exporter** | Nginx OSS. Парсит страницу `stub_status`. | Внешний | 9113 | **[Nginx](../../WebServers/Nginx/Core/nginx_overview.md)** |
| **apache_exporter** | Apache HTTPD. Парсит `/server-status` (mod_status). | Внешний | 9117 | **[Apache](../../WebServers/Apache/apache_overview.md)** |
| **haproxy_exporter** | HAProxy. В v2.0+ нативный экспорт через `promo-metrics` сервис. Метрики: бэкенды, серверы, фронтенды, соединения. | Нативный (v2.0+) | 9101 | **[HAProxy](../../WebServers/haproxy_overview.md)** |
| **envoy-exporter** | Envoy Proxy (Service Mesh). Метрики кластера, listeners, clusters. | Внешний | 9102 | **[Envoy](../../Service_Mesh/service_mesh_concepts.md)** |

### 3. Брокеры сообщений (Message Brokers)

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **RabbitMQ (нативно)** | Плагин `rabbitmq_prometheus` (включен в v3.8+). | Нативный | 15692 | **[RabbitMQ](../../Kafka/rabbitmq_vs_kafka.md)** |
| **kafka_exporter** | Kafka. Задержки консьюмеров (lag), партиции, группы, брокеры. | Внешний | 9308 | **[Kafka](../../Kafka/kafka_for_monitoring.md)** |

### 4. Аппаратное обеспечение и СХД

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **node_exporter** | Мониторинг Linux (CPU, RAM, disks, network, systemd). | Внешний | 9100 | **[Node Exporter](./node_exporter.md)** |
| **cAdvisor** | Мониторинг контейнеров (Docker/K8s). cAdvisor собирает метрики через cgroups. | Внешний | 8080 | **[cAdvisor](./cadvisor.md)** |
| **ceph_exporter** | Мониторинг Ceph кластера и OSD. | Внешний | 9128 | — |
| **ipmi_exporter** | Мониторинг BMC, кулеров, питания серверов. Три паттерна: remote, local, proxy. | Внешний | 9290 | **[IPMI Exporter](./ipmi_exporter.md)** |
| **snmp_exporter** | Опрос коммутаторов, ИБП (Multi-Target паттерн). | Внешний | 9116 | — |

### 5. Специализированные и "Blackbox" инструменты

| Экспортер | Описание | Тип | Порт | Ссылка на SSoT |
| :--- | :--- | :--- | :--- | :--- |
| **blackbox_exporter** | Проверка доступности (HTTP, TCP, DNS, ICMP, gRPC). | Внешний | 9115 | **[Blackbox Exporter](./blackbox/blackbox_exporter_overview.md)** |
| **process_exporter** | Детальный мониторинг по конкретным именам процессов. | Внешний | 9256 | — |
| **json_exporter** | Парсинг произвольных JSON API ответов в метрики. | Внешний | 9117 | — |
| **sql_exporter** | Периодическое выполнение кастомных SQL-запросов. | Внешний | 9116 | — |
| **mtail** | Извлечение метрик из логов через regex. Демон, читающий файлы логов. | Внешний | 9116 | **[Log-based Exporters](./log_based_exporters.md)** |
| **grok_exporter** | Парсинг логов через Grok-паттерны (аналог Logstash). | Внешний | 9144 | **[Log-based Exporters](./log_based_exporters.md)** |

---


## Практические сценарии развертывания

### Systemd (bare-metal/VMs)

Стандартный способ развертывания на физических серверах и виртуальных машинах. Создайте файл `/etc/systemd/system/<exporter>.service`:

```ini
[Unit]
Description=Prometheus Exporter
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/<exporter> \
  --config.file=/etc/<exporter>/config.yml \
  --web.listen-address=0.0.0.0:9100
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now <exporter>
sudo systemctl status <exporter>
journalctl -u <exporter> -f
```

### Docker Compose

Изоляция и быстрое развертывание. Пример для нескольких экспортеров:

```yaml
version: "3.8"
services:
  mysqld-exporter:
    image: prom/mysqld-exporter:v0.15.1
    container_name: mysqld-exporter
    restart: unless-stopped
    ports:
      - "9104:9104"
    environment:
      DATA_SOURCE_NAME: "exporter:${MYSQL_EXPORTER_PASSWORD}@(db-host:3306)/"
    networks:
      - monitoring

  redis-exporter:
    image: oliver006/redis_exporter:v1.55.0
    container_name: redis-exporter
    restart: unless-stopped
    ports:
      - "9121:9121"
    environment:
      REDIS_ADDR: "redis://redis-host:6379"
    networks:
      - monitoring

  blackbox-exporter:
    image: prom/blackbox-exporter:v0.25.0
    container_name: blackbox-exporter
    restart: unless-stopped
    ports:
      - "9115:9115"
    volumes:
      - ./blackbox.yml:/config/blackbox.yml:ro
    command:
      - '--config.file=/config/blackbox.yml'
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

```bash
# Запуск
docker compose up -d

# Проверка логов
docker logs -f mysqld-exporter
docker logs -f blackbox-exporter

# Проверка эндпоинта
curl -s http://localhost:9104/metrics | head -20
```

### Kubernetes (ServiceMonitor)

Рекомендуемый метод для управления в K8s через kube-prometheus-stack или Prometheus Operator:

```yaml
# ServiceMonitor для баз данных
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: redis-exporter
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: redis
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

```yaml
# Deployment с exporter sidecar
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16
          ports:
            - containerPort: 5432
        - name: postgres-exporter
          image: prometheuscommunity/postgres-exporter:v0.15.0
          ports:
            - containerPort: 9187
          env:
            - name: DATA_SOURCE_NAME
              value: "exporter:$(POSTGRES_EXPORTER_PASSWORD)@(127.0.0.1:5432)/"
            - name: POSTGRES_EXPORTER_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: exporter-password
```

---


## Общие конфигурации Prometheus

### Статическая конфигурация

Для фиксированного набора целей:

```yaml
scrape_configs:
  - job_name: 'mysql'
    static_configs:
      - targets: ['db-host-01:9104', 'db-host-02:9104']
    scrape_interval: 30s
    scrape_timeout: 10s

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-01:9121']
    scrape_interval: 15s

  - job_name: 'nginx'
    static_configs:
      - targets: ['nginx-01:9113', 'nginx-02:9113']
```

### Service Discovery (Kubernetes)

Автоматический поиск экспортеров в кластере:

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        regex: (.+)
        replacement: $1
        target_label: __metrics_path__
      - source_labels: [__address__]
        action: replace
        regex: (.+):\d+
        replacement: $1:9100
        target_label: __address__
```

### File Service Discovery

Для динамических целей из файлов:

```yaml
scrape_configs:
  - job_name: 'dynamic-targets'
    file_sd_configs:
      - files:
          - /etc/prometheus/targets/*.json
          - /etc/prometheus/targets/*.yml
        refresh_interval: 5m
```

### Безопасность: TLS и Basic Auth

Защита эндпоинта экспортера:

```yaml
# web-config.yml для экспортера
basic_auth_users:
  prometheus: "$2y$12$..." # htpasswd hash

tls_server_config:
  cert_file: /etc/exporter/certs/server.crt
  key_file: /etc/exporter/certs/server.key
  client_ca_file: /etc/exporter/certs/ca.crt
  client_auth_type: "RequireAndVerifyClientCert"

# В systemd-юните
ExecStart=/usr/local/bin/<exporter> \
  --web.config.file=/etc/<exporter>/web-config.yml \
  --web.listen-address=0.0.0.0:9100
```

```yaml
# Prometheus scrape config с TLS и basic auth
scrape_configs:
  - job_name: 'secure-exporter'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      cert_file: /etc/prometheus/certs/client.crt
      key_file: /etc/prometheus/certs/client.key
      insecure_skip_verify: false
    basic_auth:
      username: prometheus
      password: "${EXPORTER_PASSWORD}"
    static_configs:
      - targets: ['exporter-host:9100']
```

---


## Типичные ошибки и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `up == 0` | Экспортер не запущен или порт закрыт | `ss -tlnp \| grep <port>`, `systemctl status <exporter>` | Запустить экспортер, проверить firewall |
| `connection refused` | Ошибка в DSN или адресе цели | Проверить логи экспортера, доступность БД/сервиса | Исправить DSN, проверить сетевую связность |
| `401 Unauthorized` | Неверные креды или отсутствует `Authorization` | Проверить `basic_auth_users` в `web-config.yml` | Обновить пароль, перегенерировать htpasswd |
| `SSL handshake failure` | Неверный сертификат или несовпадение CA | `openssl s_client -connect host:port` | Обновить сертификаты, проверить `ca_file` |
| `scrape timeout` | Большая кардинальность или медленная БД | `curl -w "%{time_total}" <exporter>/metrics` | Уменьшить `scrape_timeout`, оптимизировать запросы |
| `metric not found` | Неправильный `metrics_path` или экспортер не поддерживает путь | `curl <exporter>/metrics \| grep <metric>` | Указать корректный путь, проверить версию экспортера |
| `rate limit / 429` | Слишком частый скрапинг | Проверить логи Prometheus и экспортера | Увеличить `scrape_interval`, настроить лимиты на стороне цели |
| `high memory usage` | Утечка памяти или слишком большой `--collector.*` | `top`, `ps aux --sort=-%mem` | Обновить экспортер, отключить тяжелые коллекторы |

### Диагностические команды

```bash
# Проверка доступности эндпоинта
curl -v http://localhost:9100/metrics

# Проверка открытого порта
ss -tlnp | grep 9100
# → LISTEN 0 4096 0.0.0.0:9100

# Проверка статуса systemd
systemctl status <exporter>
journalctl -u <exporter> -f

# Проверка TLS-сертификата
openssl s_client -connect exporter-host:9100 -servername exporter-host

# Проверка метрик в реальном времени
curl -s http://localhost:9100/metrics | grep -E "^(up|scrape)"
```

---


## Лучшие практики

*   **Scrape intervals:** Используйте 15-30s для критичных метрик, 60-120s для статических систем. Чем выше частота, тем больше нагрузка на цель и Prometheus.
*   **Resource limits:** Ограничьте CPU (150-300m) и RAM (128-256Mi) на инстанс экспортера. Для тяжелых коллекторов (`zfs`, `nfs`, `nfsd`) может потребоваться больше.
*   **Cardinality control:** Избегайте метрик с высокой кардинальностью (например, `labels` с уникальными значениями на каждый запрос). Используйте `relabel_configs` для обрезки лишних лейблов.
*   **Auth и TLS:** Всегда используйте TLS и basic auth в production. Никогда не экспонируйте порты экспортеров в публичную сеть без защиты.
*   **Redundancy:** Развертывайте экземпляры на каждом хосте (DaemonSet) для критичных метрик. Используйте балансировку для скрапинга.
*   **Version pinning:** Фиксируйте версии экспортеров в systemd unit files, Docker Compose и Helm values. Обновляйте через CI/CD с тестированием.
*   **Monitoring the monitor:** Добавьте `up{job="<exporter>"}` и `scrape_duration_seconds` в алерты. Мониторьте сам экспортер.
*   **Avoid duplicate metrics:** При использовании нативного экспорта и внешнего экспортера одновременно настройте `metric_relabel_configs` для удаления дубликатов.

---


## Валидация установки

После развертывания проверьте:

```bash
# 1. Endpoint доступен
curl -s http://localhost:9100/metrics | head -5
# → # HELP node_cpu_seconds_total ...
# → # TYPE node_cpu_seconds_total counter

# 2. Формат корректный
curl -s http://localhost:9100/metrics | grep -E "^(# TYPE|# HELP)"
# → Должны присутствовать HELP и TYPE для каждой метрики

# 3. Метрики обновляются
curl -s http://localhost:9100/metrics | grep "node_time_seconds"
# → node_time_seconds 1234567890.123

# 4. Prometheus видит цели
curl -s http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="<exporter>")'
# → {"job":"<exporter>","health":"up",...}

# 5. Scrape работает
curl -s http://prometheus:9090/api/v1/query?query=up{job="<exporter>"}
# → up должен быть равен 1

# 6. Длительность скрапинга в норме
curl -s http://prometheus:9090/api/v1/query?query=scrape_duration_seconds{job="<exporter>"}
# → Значение должно быть < scrape_timeout
```

```bash
# Полная проверка через promtool
promtool check metrics http://localhost:9100/metrics
# → SUCCESS: X metric families found

# Проверка конфигурации Prometheus
promtool check config prometheus.yml
# → SUCCESS: prometheus.yml is valid
```

---


## Дополнительная информация

### Поиск и расширяемость

Если требуемой системы нет в каталоге:
1.  **Реестр сообщества:** Проверьте официальный список поддерживаемых портов и экспортеров на [Prometheus.io](https://prometheus.io/docs/instrumenting/exporters/).
2.  **Скрипты:** Для простых разовых проверок используйте bash-скрипты в связке с [Textfile Collector](./extensibility/textfile_collector.md).
3.  **Собственная разработка:** Архитектурные паттерны создания агентов на Go описаны в статье [Создание собственных экспортеров](./extensibility/custom_exporters.md).

### См. также

*   [Обзор экспортеров](./overview.md) — принцип работы, безопасность (TLS/Auth), кардинальность.
*   [Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — автоматизация сбора метрик с большого количества агентов.
*   [Redis Exporter](./redis_exporter.md) — практический гайд по Redis.
*   [IPMI/BMC Exporter](./ipmi_exporter.md) — мониторинг аппаратного обеспечения серверов.
*   [Log-based Exporters](./log_based_exporters.md) — mtail и grok_exporter для извлечения метрик из логов.
