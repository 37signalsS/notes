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

Подробное описание конфигурации модулей (HTTP, TCP, ICMP, DNS, gRPC) находится в SSoT: [Конфигурация модулей Blackbox Exporter](../../Exporters/blackbox/blackbox_exporter_modules_configuration.md).

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

> **См. также:** [Prometheus configuration](../../../Databases/MariaDB/configuration.md).

## 4. Примеры проверок

| Проверка | Команда |
| :--- | :--- |
| **HTTP эндпоинт** | `curl "http://localhost:9115/probe?target=https://example.com&module=http_2xx"` |
| **TCP порт** | `curl "http://localhost:9115/probe?target=db.example.com:5432&module=tcp_connect"` |
| **DNS** | `curl "http://localhost:9115/probe?target=example.com&module=dns_check"` |
| **gRPC (v0.28.0+)** | `curl "http://localhost:9115/probe?target=grpc.example.com:443&module=grpc_check"` |
| **HTTP/3 (v0.28.0+)** | `curl "http://localhost:9115/probe?target=https://example.com&module=http3_check"` |

**Связанные темы:** [Основные концепции](./blackbox_exporter_concepts.md), [Дополнительные темы](./blackbox_exporter_advanced.md), [Конфигурация модулей](../../Exporters/blackbox/blackbox_exporter_modules_configuration.md), [Prometheus configuration](../../../Databases/MariaDB/configuration.md).
