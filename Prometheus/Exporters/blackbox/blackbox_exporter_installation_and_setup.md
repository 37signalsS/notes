# Blackbox Exporter — Установка и настройка

## 1. Запуск blackbox_exporter

### Systemd

```bash
# Скачать последнюю версию
BLACKBOX_EXPORTER_VERSION="0.28.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Создать директорию для конфигурации
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/

# Создать systemd-сервис
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
ExecStart=/usr/local/bin/blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml
ExecReload=/bin/kill -HUP \$MAINPID

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter
```

### Docker

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

---

## 2. Настройка Prometheus

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
      # Копируем адрес цели в параметр __param_target
      - source_labels: [__address__]
        target_label: __param_target
      # Копируем __param_target в лейбл instance
      - source_labels: [__param_target]
        target_label: instance
      # Подменяем адрес на адрес blackbox_exporter
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

Подробнее о relabeling см. в [service_discovery_and_relabeling.md](../../service_discovery_and_relabeling.md).

---

## 3. Проверка работы

**Проверка URL в браузере:**

```bash
# HTTP-проверка
curl "localhost:9115/probe?module=http_2xx&target=http://prometheus.io"

# ICMP ping
curl "localhost:9115/probe?module=icmp_ping&target=google.com"

# DNS-проверка
curl "localhost:9115/probe?module=dns_google&target=8.8.8.8"

# TCP-проверка
curl "localhost:9115/probe?module=tcp_ssh&target=127.0.0.1:22"
```

---

## 4. Связанные документы

- **[Обзор и концепции](./blackbox_exporter_overview.md)** — базовые определения
- **[Конфигурация модулей](./blackbox_exporter_modules_configuration.md)** — HTTP, TCP, ICMP, DNS, gRPC модули
- **[Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)** — метрики и правила оповещений
- **[Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)**
