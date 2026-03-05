# Blackbox Exporter: Установка и настройка

## 1. Установка из бинарных файлов (Linux)

### 1.1. Загрузка и установка

```bash
BLACKBOX_EXPORTER_VERSION="0.28.0"
cd /tmp
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/
```

### 1.2. Настройка каталогов и конфигурации

```bash
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
chown -R nobody:nobody /etc/blackbox_exporter
```

### 1.3. Создание файла с опциями запуска

`/etc/sysconfig/blackbox_exporter`:

```bash
cat <<EOF > /etc/sysconfig/blackbox_exporter
OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml \
--web.listen-address=:9115 \
--log.level=info"
EOF
```

### 1.4. Создание systemd-сервиса

`/etc/systemd/system/blackbox_exporter.service`:

```bash
cat <<EOF > /etc/systemd/system/blackbox_exporter.service
[Unit]
Description=Prometheus Blackbox Exporter
Documentation=https://github.com/prometheus/blackbox_exporter
After=network-online.target

[Service]
Restart=always
User=nobody
Group=nobody
EnvironmentFile=/etc/sysconfig/blackbox_exporter
ExecStart=/usr/local/bin/blackbox_exporter \$OPTIONS
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
EOF
```

### 1.5. Запуск и проверка

```bash
systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9115
# Ожидаемый ответ: 200
```

## 2. Конфигурация модулей

**Базовый `/etc/blackbox_exporter/blackbox.yml`:**

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200, 201, 202, 204]
      method: GET
      follow_redirects: true
      preferred_ip_protocol: "ip4"

  http_post_2xx:
    prober: http
    timeout: 5s
    http:
      method: POST
      valid_status_codes: [200, 201, 204]

  tcp_connect:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: "ip4"

  icmp_check:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
      payload_size: 56

  dns_check:
    prober: dns
    timeout: 5s
    dns:
      preferred_ip_protocol: "ip4"
      query_name: "example.com"
      query_type: "A"
      valid_rcodes: [NOERROR]

  grpc_check:
    prober: grpc
    timeout: 5s
    grpc:
      preferred_ip_protocol: "ip4"
      tls: true

  http3_check:
    prober: http
    timeout: 5s
    http:
      preferred_ip_protocol: "ip4"
      http3: true  # Новая возможность v0.28.0
```

## 3. Интеграция с Prometheus

**Добавьте в `prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - https://example.com
          - https://api.example.com/health
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9115

  - job_name: 'blackbox-tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
          - db.example.com:5432
          - redis.example.com:6379
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9115

  - job_name: 'blackbox-icmp'
    metrics_path: /probe
    params:
      module: [icmp_check]
    static_configs:
      - targets:
          - 8.8.8.8
          - 1.1.1.1
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9115
```

> **См. также:** [Prometheus configuration](../configuration.md).

## 4. Примеры проверок

| Проверка | Команда |
| :--- | :--- |
| **HTTP эндпоинт** | `curl "http://localhost:9115/probe?target=https://example.com&module=http_2xx"` |
| **TCP порт** | `curl "http://localhost:9115/probe?target=db.example.com:5432&module=tcp_connect"` |
| **DNS** | `curl "http://localhost:9115/probe?target=example.com&module=dns_check"` |
| **gRPC (v0.28.0+)** | `curl "http://localhost:9115/probe?target=grpc.example.com:443&module=grpc_check"` |
| **HTTP/3 (v0.28.0+)** | `curl "http://localhost:9115/probe?target=https://example.com&module=http3_check"` |

## Связанные документы

- **[Основные концепции](./blackbox_exporter_concepts.md)** — определения и возможности
- **[Дополнительные темы](./blackbox_exporter_advanced.md)** — безопасность, Docker, troubleshooting
- **[Prometheus configuration](../configuration.md)** — настройка Prometheus
