# Node Exporter

## Overview

**Node Exporter** — экспортер для сбора метрик с хост-машины на базе Linux. Предоставляет детальную ресурсную мониторинговую информацию: загрузку CPU, использование памяти, дисковое I/O, сетевую активность и другие системные метрики.

* **Порт по умолчанию:** `9100`
* **Репозиторий:** [prometheus/node_exporter](https://github.com/prometheus/node_exporter)
* **Установка:** [installation/node_exporter_installation.md](../installation/node_exporter_installation.md)

## Basic Concepts

### Data Source

`node_exporter` не обращается напрямую к ядру. Он читает и парсит файлы из виртуальных файловых систем Linux:

* `/proc` — информация о процессах, памяти, CPU
* `/sys` — информация об устройствах, драйверах, подсистемах ядра

Например, для получения информации о памяти он читает `/proc/meminfo`, для статистики CPU — `/proc/stat`.

### OS Compatibility

`node_exporter` предназначен исключительно для операционных систем на базе Linux. Для мониторинга Windows-систем используется [wmi_exporter](https://github.com/prometheus-community/windows_exporter).

### Архитектура коллекторов

Node Exporter состоит из множества **коллекторов** — модулей, каждый из которых отвечает за сбор определённого типа метрик. Коллекторы можно включать/выключать через флаги `--collector.<name>`.

## Практические сценарии

### Запуск node_exporter

**Systemd (рекомендуется для production):**

```bash
# Скачать последнюю версию
NODE_EXPORTER_VERSION="1.11.0"
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/

# Создать systemd-сервис
cat <<EOF > /etc/systemd/system/node_exporter.service
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

systemctl daemon-reload
systemctl start node_exporter
systemctl enable node_exporter
```

**Docker:**

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

### Ключи запуска

| Ключ | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--web.listen-address` | `":9100"` | Адрес и порт для прослушивания |
| `--web.telemetry-path` | `"/metrics"` | URI для экспозиции метрик |
| `--log.level` | `"info"` | Уровень логирования (`debug`, `info`, `warn`, `error`) |
| `--log.format` | `"logfmt"` | Формат логов (`logfmt`, `json`) |
| `--collector.textfile.directory` | — | Директория для [Textfile Collector](./extensibility/textfile_collector.md) |
| `--collector.disable-defaults` | `false` | Отключить все коллекторы по умолчанию |

### Включение/отключение коллекторов

```bash
# Отключить конкретный коллектор
--no-collector.<name>

# Включить коллектор (если отключены по умолчанию через --collector.disable-defaults)
--collector.<name>

# Пример: игнорировать монтированные точки виртуальных ФС
--collector.filesystem.ignored-mount-points="^/(sys|proc|dev|host|etc)($|/)"
```

### Основные метрики

#### CPU

```
node_cpu_seconds_total{cpu="0",mode="idle"}    # Время CPU в режиме idle
node_cpu_seconds_total{cpu="0",mode="system"}  # Время CPU в режиме kernel
node_cpu_seconds_total{cpu="0",mode="user"}    # Время CPU в режиме user
node_load1                                     # Загрузка CPU за 1 минуту
node_load5                                     # Загрузка CPU за 5 минут
node_load15                                    # Загрузка CPU за 15 минут
```

**Пример PromQL:** загрузка CPU в %

```promql
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

#### Память

```
node_memory_MemTotal_bytes         # Общий объём памяти
node_memory_MemFree_bytes          # Свободная память
node_memory_MemAvailable_bytes     # Доступная память (с учётом кэшей)
node_memory_Buffers_bytes          # Буферы ядра
node_memory_Cached_bytes           # Кэш страниц
node_memory_SwapTotal_bytes        # Общий объём swap
node_memory_SwapFree_bytes         # Свободный swap
```

**Пример PromQL:** использование памяти в %

```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

#### Диск и файловая система

```
node_filesystem_size_bytes{mountpoint="/"}      # Общий размер ФС
node_filesystem_free_bytes{mountpoint="/"}      # Свободное место
node_filesystem_avail_bytes{mountpoint="/"}     # Доступное место для non-root
node_filesystem_read_bytes_total{device="sda"}  # Прочитано байт
node_filesystem_written_bytes_total{device="sda"} # Записано байт
node_disk_read_bytes_total{device="sda"}        # Прочитано байт с диска
node_disk_written_bytes_total{device="sda"}     # Записано байт на диск
node_disk_io_time_seconds_total{device="sda"}   # Время I/O операций
```

**Пример PromQL:** использование диска в %

```promql
(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100
```

#### Сеть

```
node_network_receive_bytes_total{device="eth0"}   # Получено байт
node_network_transmit_bytes_total{device="eth0"}  # Отправлено байт
node_network_receive_drop_total{device="eth0"}    # Получено пакетов с ошибками
node_network_transmit_drop_total{device="eth0"}   # Отправлено пакетов с ошибками
node_network_up{device="eth0"}                    # Статус интерфейса (1=up)
```

**Пример PromQL:** входящий трафик в байт/сек

```promql
rate(node_network_receive_bytes_total{device="eth0"}[5m])
```

#### Прочие метрики

```
node_boot_time_seconds          # Время загрузки системы
node_time_seconds               # Текущее время системы
node_procs_running              # Количество запущенных процессов
node_procs_blocked              # Количество заблокированных процессов
node_context_switches_total     # Количество переключений контекста
node_interrupts_total           # Количество прерываний
node_vmstat_pgmajfault          # Количество major page faults
```

### Алертинг

**Node Exporter недоступен:**

```yaml
- alert: NodeExporterDown
  expr: up{job="node_exporter"} == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Node Exporter недоступен на {{ $labels.instance }}"
    description: "Node Exporter не отвечает более 5 минут"
```

**Высокая загрузка CPU:**

```yaml
- alert: NodeHighCPU
  expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Высокая загрузка CPU на {{ $labels.instance }}"
    description: "Загрузка CPU превышает 80% более 10 минут"
```

**Мало места на диске:**

```yaml
- alert: NodeDiskSpaceLow
  expr: (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100 > 85
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Мало места на диске {{ $labels.instance }}"
    description: "Использовано более 85% дискового пространства"
```

### Интеграция с Prometheus

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

> **См. также:** [Configuration](../configuration.md).

### Безопасность

**Ограничение сетевого доступа:**

```bash
# Разрешить доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9100
ufw allow from 192.168.1.0/24 to any port 9100
```

**TLS через reverse proxy (Nginx):**

```nginx
server {
    listen 443 ssl;
    server_name node-exporter.example.com;

    ssl_certificate /etc/ssl/certs/node-exporter.crt;
    ssl_certificate_key /etc/ssl/private/node-exporter.key;

    location / {
        proxy_pass http://localhost:9100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Рекомендации:**

- Для сбора всех метрик `node_exporter` рекомендуется запускать от `root`
- Ограничивайте доступ к порту 9100 на уровне файрвола
- Используйте TLS через reverse proxy для передачи метрик по незащищённым сетям
- Отключайте неиспользуемые коллекторы для уменьшения кардинальности метрик

> **См. также:** [Лейблы и кардинальность](../concepts/labels_and_cardinality.md).

## Дополнительная информация

### Расширяемость

* **[Textfile Collector](./extensibility/textfile_collector.md)** — механизм для сбора произвольных метрик через внешние скрипты
* **[Написание своих экспортеров](./extensibility/custom_exporters.md)** — руководство по созданию кастомных экспортеров

### Связанные темы

* [Виртуальная файловая система /proc](../../Linux/FileSystems/virtual_fs_proc.md)
* [Виртуальная файловая система /sys](../../Linux/FileSystems/virtual_fs_sys.md)
* [Мониторинг производительности Linux](../../Linux/Diagnostics/Performance/atop.md)
* [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md) — связка с cAdvisor

### Официальные ресурсы

* [GitHub Repository](https://github.com/prometheus/node_exporter)
* [Official Documentation](https://prometheus.io/docs/guides/node-exporter/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
