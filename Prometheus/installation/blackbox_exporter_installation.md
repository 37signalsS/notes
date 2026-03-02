# Установка Blackbox Exporter

## Определения

**Blackbox Exporter** — экспортер для проверки доступности эндпоинтов по различным протоколам:
* HTTP/HTTPS — проверка веб-сервисов
* TCP — проверка сетевых сервисов
* ICMP — проверка доступности хостов (ping)
* DNS — проверка DNS-серверов
* gRPC — проверка gRPC-сервисов (v0.28.0+)
* HTTP/3 (QUIC) — проверка HTTP/3 (v0.28.0+)

> **См. также:** [Blackbox Exporter](../Exporters/blackbox_exporter.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `0.28.0` |
| **Дата выпуска** | Декабрь 2025 |
| **Репозиторий** | [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) |

### Новые возможности v0.28.0

* **HTTP/3 (QUIC) prober:** Проверка сервисов по протоколу HTTP/3
* **gRPC metadata:** Поддержка метаданных для gRPC проверок
* **Byte matching в TCP:** Проверка содержимого TCP-ответов
* **Автоматическая перезагрузка конфига:** При изменении конфигурации

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Загрузка и установка:**

```bash
BLACKBOX_EXPORTER_VERSION="0.28.0"
cd /tmp
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/
```

**2. Настройка каталогов и конфигурации:**

```bash
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
chown -R nobody:nobody /etc/blackbox_exporter
```

**3. Создание файла с опциями запуска** (`/etc/sysconfig/blackbox_exporter`):

```bash
cat <<EOF > /etc/sysconfig/blackbox_exporter
OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml \
--web.listen-address=:9115 \
--log.level=info"
EOF
```

**4. Создание systemd-сервиса** (`/etc/systemd/system/blackbox_exporter.service`):

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

**5. Запуск и проверка:**

```bash
systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9115
# Ожидаемый ответ: 200
```

### Конфигурация модулей

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

### Интеграция с Prometheus

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

### Примеры проверок

**Проверка HTTP эндпоинта:**

```bash
curl "http://localhost:9115/probe?target=https://example.com&module=http_2xx"
```

**Проверка TCP порта:**

```bash
curl "http://localhost:9115/probe?target=db.example.com:5432&module=tcp_connect"
```

**Проверка DNS:**

```bash
curl "http://localhost:9115/probe?target=example.com&module=dns_check"
```

**Проверка gRPC (v0.28.0+):**

```bash
curl "http://localhost:9115/probe?target=grpc.example.com:443&module=grpc_check"
```

**Проверка HTTP/3 (v0.28.0+):**

```bash
curl "http://localhost:9115/probe?target=https://example.com&module=http3_check"
```

## Дополнительная информация

### Рекомендации по безопасности

**1. Ограничение доступа:**

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9115
```

**2. TLS через reverse proxy:**

```nginx
server {
    listen 443 ssl;
    server_name blackbox.example.com;

    ssl_certificate /etc/ssl/certs/blackbox.crt;
    ssl_certificate_key /etc/ssl/private/blackbox.key;

    location / {
        proxy_pass http://localhost:9115;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Установка через Docker

```bash
docker run -d \
  --name blackbox-exporter \
  -p 9115:9115 \
  -v /etc/blackbox_exporter/blackbox.yml:/etc/blackbox_exporter/blackbox.yml \
  prom/blackbox-exporter:v0.28.0 \
  --config.file=/etc/blackbox_exporter/blackbox.yml
```

### Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `blackbox.yml` | Путь к конфигурации |
| `--web.listen-address` | `:9115` | Адрес для веб-интерфейса |
| `--log.level` | `info` | Уровень логирования |

### Устранение неполадок

**Blackbox Exporter не запускается:**

```bash
# Проверка логов
journalctl -u blackbox_exporter -f

# Проверка портов
ss -tnlp | grep 9115

# Проверка конфигурации
blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --dry-run
```

**Проверка не выполняется:**

* Проверьте доступность цели из сети
* Убедитесь, что таймаут достаточен
* Проверьте логи на ошибки

### Связанные темы

* [Blackbox Exporter](../Exporters/blackbox_exporter.md) — полное руководство
* [Prometheus Server](./prometheus_server_installation.md) — интеграция
* [Configuration](../configuration.md) — настройка Prometheus
* [Docker Stack](./docker_stack/remote_hosts_monitoring.md) — мониторинг удалённых хостов
