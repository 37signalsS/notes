# Установка Node Exporter

## Определения

**Node Exporter** — экспортер для сбора метрик с аппаратного и программного обеспечения хостовой системы на базе Linux.

> **Полное руководство:** [Node Exporter](../Exporters/node_exporter.md) — основное описание, метрики, коллекторы, алерты, безопасность.

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.11.0` (2026-04-04) |
| **Репозиторий** | [prometheus/node_exporter](https://github.com/prometheus/node_exporter) |
| **Порт по умолчанию** | `9100` |

### Архитектура

Node Exporter работает по pull-модели:

1. Экспортер собирает метрики с хоста через `/proc` и `/sys`
2. Предоставляет их по HTTP на порту 9100
3. Prometheus опрашивает эндпоинт `/metrics`
4. Метрики сохраняются в TSDB

> **См. также:** [TSDB](../concepts/tsdb.md), [Источник данных](../Exporters/node_exporter.md#источник-данных).

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Загрузка и установка:**

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

**3. Запуск и проверка:**

```bash
sudo systemctl daemon-reload
sudo systemctl start node_exporter
sudo systemctl enable node_exporter

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics
# Ожидаемый ответ: 200

# Проверка статуса
sudo systemctl status node_exporter
```

### Установка через Docker

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
      - '--web.listen-address=:9100'
    restart: unless-stopped
```

> **Примечание:** Требуются `--pid=host` и `--net=host` для полного доступа к хост-метрикам. Подробности — [Запуск node_exporter](../Exporters/node_exporter.md#запуск-node_exporter).

### Установка через APT (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install prometheus-node-exporter
sudo systemctl start prometheus-node-exporter
sudo systemctl enable prometheus-node-exporter
```

> **Примечание:** Версия в репозиториях может отставать от актуальной. Проверьте: `prometheus-node-exporter --version`.

## Интеграция с Prometheus

**Добавьте в `prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
        labels:
          instance: 'my-server'
          environment: 'production'
```

**Для нескольких хостов:**

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets:
          - 'server1.example.com:9100'
          - 'server2.example.com:9100'
          - 'server3.example.com:9100'
```

> **См. также:** [Configuration](../configuration.md), [Интеграция с Prometheus](../Exporters/node_exporter.md#интеграция-с-prometheus).

## Дополнительная информация

### Коллекторы

Node Exporter использует коллекторы для сбора метрик по категориям.

**Включённые по умолчанию:** `cpu`, `diskstats`, `filesystem`, `loadavg`, `meminfo`, `netdev`, `stat`, `time`

**Полный список:**

```bash
node_exporter --help | grep collector
```

**Пример включения опциональных:**

```bash
--collector.systemd --collector.processes --collector.logind
```

> **Полное описание:** [Коллекторы и метрики](../Exporters/node_exporter.md#архитектура-коллекторов).

### Безопасность

- Для сбора всех метрик рекомендуется запускать от `root`
- Ограничивайте доступ к порту 9100 на уровне файрвола
- Используйте TLS через reverse proxy для незащищённых сетей

> **Подробности:** [Безопасность](../Exporters/node_exporter.md#безопасность).

### Связанные темы

* [Node Exporter (SSoT)](../Exporters/node_exporter.md) — полное руководство
* [Exporters overview](../Exporters/overview.md) — обзор экспортёров
* [Prometheus Server installation](./prometheus_server_installation.md)
* [Configuration](../configuration.md) — настройка Prometheus
