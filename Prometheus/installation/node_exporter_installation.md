# Установка Node Exporter

## Определения

**Node Exporter** — экспортер для сбора метрик с аппаратного и программного обеспечения хостовой системы на базе Linux.

> **Основное руководство:** [Node Exporter](../Exporters/node_exporter.md) — описания метрик, коллекторов, алертов и настройки безопасности.

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.11.0` (2026-04-04) |
| **Репозиторий** | [prometheus/node_exporter](https://github.com/prometheus/node_exporter) |
| **Порт по умолчанию** | `9100` |

### Архитектура сбора

Node Exporter работает по pull-модели (сбор данных сервером):

1. Экспортер собирает метрики через виртуальные файловые системы `/proc` и `/sys`.
2. Предоставляет данные по протоколу HTTP (HyperText Transfer Protocol) на порту 9100.
3. Prometheus опрашивает эндпоинт `/metrics`.
4. Данные сохраняются в TSDB (Time Series Database).

> **См. также:** [TSDB](../concepts/tsdb.md), [Источник данных](../Exporters/node_exporter.md#источник-данных).

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Загрузка и размещение:**

```bash
NODE_EXPORTER_VERSION="1.11.0"
cd /tmp
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
```

**2. Создание systemd-сервиса** (`/etc/systemd/system/node_exporter.service`):

```bash
cat <<EOF | sudo tee /etc/systemd/system/node_exporter.service
[Unit]
Description=Prometheus Node Exporter
Documentation=https://github.com/prometheus/node_exporter
After=network-online.target

[Service]
Restart=always
User=root
ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

**3. Управление службой:**

```bash
sudo systemctl daemon-reload
sudo systemctl start node_exporter
sudo systemctl enable node_exporter

# Проверка доступности метрик
curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics
# Ожидаемый ответ: 200

# Текущий статус
sudo systemctl status node_exporter
```

### Установка через Docker

Для полноценного мониторинга хоста из контейнера необходимо пробросить системные директории:

```yaml
services:
  node_exporter:
    image: prom/node-exporter:v1.11.0
    container_name: node_exporter
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    restart: unless-stopped
```

> **Примечание:** В некоторых случаях для корректного сбора метрик сети и процессов могут потребоваться флаги `--pid=host` и `--net=host`.

### Установка через менеджер пакетов (APT)

```bash
sudo apt update
sudo apt install prometheus-node-exporter
sudo systemctl start prometheus-node-exporter
sudo systemctl enable prometheus-node-exporter
```

*Примечание:* Версия в официальных репозиториях часто отстаёт от актуальной в GitHub.

## Дополнительная информация

### Настройка Prometheus

Добавьте цель для сбора в секцию `scrape_configs` файла `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
```

### Связанные темы

- [Node Exporter (SSoT)](../Exporters/node_exporter.md) — полное руководство по метрикам и алертам.
- [Exporters overview](../Exporters/overview.md) — обзор других экспортеров.
- [Configuration](../configuration.md) — настройка сбора данных в Prometheus.
