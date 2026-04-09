# Blackbox Exporter — Установка и настройка

## Definitions

**Blackbox Exporter** — экспортер Prometheus для blackbox-мониторинга (проверка доступности эндпоинтов снаружи). Порт по умолчанию: `9115`. Текущая стабильная версия: `0.28.0`.

> **См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).

## Basic Concepts

### Способы установки

| Способ | Когда использовать |
| :--- | :--- |
| **Binary + systemd** | Bare-metal, VM, контроль версий |
| **Docker** | Контейнеризация, быстрое развёртывание |

### Структура конфигурации

Конфигурационный файл `blackbox.yml` содержит секцию `modules`. Каждый модуль описывает тип проверки (`prober`) и её параметры. Подробнее: [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).

### Ключевые параметры запуска

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `blackbox.yml` | Путь к конфигурации |
| `--web.listen-address` | `:9115` | Адрес для scraping |
| `--log.level` | `info` | Уровень логирования |
| `--config.enable-auto-reload` | `false` | Автоматическая перезагрузка при изменении конфига (v0.28.0+) |

## Practical Scenarios

### 1. Установка из бинарных файлов (systemd)

```bash
BLACKBOX_EXPORTER_VERSION="0.28.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Создание директории для конфигурации
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
chown -R nobody:nobody /etc/blackbox_exporter
```

**Файл опций** `/etc/sysconfig/blackbox_exporter`:

```bash
cat <<EOF > /etc/sysconfig/blackbox_exporter
OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml \
--web.listen-address=:9115 \
--log.level=info"
EOF
```

**Systemd-юнит** `/etc/systemd/system/blackbox_exporter.service`:

```ini
[Unit]
Description=Prometheus Blackbox Exporter
Documentation=https://github.com/prometheus/blackbox_exporter
After=network-online.target

[Service]
Restart=always
User=nobody
Group=nobody
EnvironmentFile=/etc/sysconfig/blackbox_exporter
ExecStart=/usr/local/bin/blackbox_exporter $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
```

**Запуск:**

```bash
systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter

# Проверка
curl -s -o /dev/null -w "%{http_code}" http://localhost:9115
# Ожидаемый ответ: 200
```

### 2. Установка через Docker

**Docker Compose:**

```yaml
services:
  blackbox_exporter:
    image: prom/blackbox-exporter:v0.28.0
    container_name: blackbox_exporter
    ports:
      - "9115:9115"
    volumes:
      - ./blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro
    command:
      - '--config.file=/etc/blackbox_exporter/blackbox.yml'
    restart: unless-stopped
```

**Docker CLI:**

```bash
docker run -d \
  --name blackbox-exporter \
  -p 9115:9115 \
  -v /etc/blackbox_exporter/blackbox.yml:/etc/blackbox_exporter/blackbox.yml \
  prom/blackbox-exporter:v0.28.0 \
  --config.file=/etc/blackbox_exporter/blackbox.yml
```

### 3. Настройка Prometheus

#### HTTP-проверки (один job)

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - "http://prometheus.io"
        - "https://google.com"
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

#### Раздельные job'ы для разных протоколов

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

Подробнее о relabeling: [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md).

### 4. Проверка работы

| Проверка | Команда |
| :--- | :--- |
| **HTTP эндпоинт** | `curl "http://localhost:9115/probe?target=https://example.com&module=http_2xx"` |
| **ICMP ping** | `curl "http://localhost:9115/probe?target=google.com&module=icmp_ping"` |
| **DNS** | `curl "http://localhost:9115/probe?target=8.8.8.8&module=dns_google"` |
| **TCP SSH** | `curl "http://localhost:9115/probe?target=127.0.0.1:22&module=tcp_ssh"` |
| **gRPC (v0.28.0+)** | `curl "http://localhost:9115/probe?target=grpc.example.com:443&module=grpc_health"` |

## Additional Information

### Рекомендации по безопасности

**Ограничение доступа через firewall:**

```bash
ufw allow from 10.0.0.0/8 to any port 9115
```

**TLS через reverse proxy (nginx):**

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

### Устранение неполадок

**Blackbox Exporter не запускается:**

```bash
# Проверка логов
journalctl -u blackbox_exporter -f

# Проверка портов
ss -tnlp | grep 9115

# Валидация конфигурации (если доступна опция)
blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --dry-run
```

**Проверка не выполняется:**
- Убедиться в доступности цели из сети blackbox_exporter
- Проверить достаточность таймаута
- Проверить логи на ошибки

### Связанные документы

- **[Обзор и концепции](./blackbox_exporter_overview.md)** — базовые определения, принцип работы
- **[Конфигурация модулей](./blackbox_exporter_modules_configuration.md)** — HTTP, TCP, ICMP, DNS, gRPC модули
- **[Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)** — метрики и правила оповещений
- **[Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)** — relabeling в Prometheus
