# Node Exporter

## Определения

**Node Exporter** — экспортер для сбора метрик с хост-машины на базе Linux. Предоставляет детальную информацию о состоянии ресурсов: загрузку CPU (Central Processing Unit — центральный процессор), использование памяти, дисковое I/O (Input/Output — ввод-вывод), сетевую активность и другие системные показатели.

* **Порт по умолчанию:** `9100`
* **Репозиторий:** [prometheus/node_exporter](https://github.com/prometheus/node_exporter)
* **Установка:** подробно описана в [инструкции по установке](../installation/node_exporter_installation.md)

## Основные концепции

### Источник данных

`node_exporter` не обращается напрямую к ядру. Он читает и парсит файлы из виртуальных файловых систем Linux:

* `/proc` — информация о процессах, памяти, CPU
* `/sys` — информация об устройствах, драйверах, подсистемах ядра

Например, для получения информации о памяти он читает `/proc/meminfo`, для статистики CPU — `/proc/stat`. Подробнее: [виртуальная файловая система /proc](../../Linux/FileSystems/virtual_fs_proc.md) и [/sys](../../Linux/FileSystems/virtual_fs_sys.md).

### Совместимость с ОС

Node Exporter предназначен исключительно для ОС (операционных систем) на базе Linux. Для мониторинга Windows-систем используется [windows_exporter](https://github.com/prometheus-community/windows_exporter).

### Архитектура коллекторов

Node Exporter состоит из множества **коллекторов** — модулей, каждый из которых отвечает за сбор определённого типа метрик. Коллекторы можно включать или выключать через флаги запуска.

* **Включены по умолчанию:** базовые системные метрики (CPU, память, диск, сеть).
* **Отключены по умолчанию:** специфичные метрики (например, `systemd`, `processes`, `logind`).

## Практические сценарии

### Настройка запуска

Подробные инструкции по запуску через systemd и Docker приведены в [руководстве по установке](../installation/node_exporter_installation.md).

### Ключи запуска

| Ключ | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--web.listen-address` | `":9100"` | Адрес и порт для прослушивания (IP — Internet Protocol) |
| `--web.telemetry-path` | `"/metrics"` | URI (Uniform Resource Identifier) для экспозиции метрик |
| `--log.level` | `"info"` | Уровень логирования (`debug`, `info`, `warn`, `error`) |
| `--collector.textfile.directory` | — | Директория для [Textfile Collector](./extensibility/textfile_collector.md) |
| `--collector.disable-defaults` | `false` | Отключить все коллекторы, включённые по умолчанию |

### Управление коллекторами

```bash
# Отключить конкретный коллектор
--no-collector.<name>

# Включить коллектор (например, если он отключен по умолчанию)
--collector.<name>

# Пример: игнорировать монтированные точки виртуальных файловых систем
--collector.filesystem.ignored-mount-points="^/(sys|proc|dev|host|etc)($|/)"
```

### Основные метрики

#### CPU

```bash
node_cpu_seconds_total{cpu="0",mode="idle"}    # Время CPU в режиме бездействия
node_cpu_seconds_total{cpu="0",mode="system"}  # Время CPU в режиме ядра
node_cpu_seconds_total{cpu="0",mode="user"}    # Время CPU в пользовательском режиме
node_load1                                     # Средняя нагрузка за 1 минуту
node_load5                                     # Средняя нагрузка за 5 минут
node_load15                                    # Средняя нагрузка за 15 минут
```

**Пример PromQL:** загрузка CPU в процентах (%)

```promql
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

#### Память (RAM)

```bash
node_memory_MemTotal_bytes         # Общий объём RAM (Random Access Memory)
node_memory_MemFree_bytes          # Свободная память
node_memory_MemAvailable_bytes     # Доступная память (с учётом кэшей)
node_memory_Buffers_bytes          # Буферы ядра
node_memory_Cached_bytes           # Кэш страниц
node_memory_SwapTotal_bytes        # Общий объём swap (подкачки)
node_memory_SwapFree_bytes         # Свободный swap
```

**Пример PromQL:** использование памяти в %

```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

#### Диск и файловая система

```bash
node_filesystem_size_bytes{mountpoint="/"}      # Общий размер файловой системы
node_filesystem_free_bytes{mountpoint="/"}      # Свободное место
node_filesystem_avail_bytes{mountpoint="/"}     # Доступное место для обычных пользователей
node_filesystem_read_bytes_total{device="sda"}  # Прочитано байт
node_filesystem_written_bytes_total{device="sda"} # Записано байт
node_disk_read_bytes_total{device="sda"}        # Прочитано байт с физического диска
node_disk_written_bytes_total{device="sda"}     # Записано байт на физический диск
node_disk_io_time_seconds_total{device="sda"}   # Общее время выполнения операций ввода-вывода
```

**Пример PromQL:** использование диска в %

```promql
(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100
```

#### Сеть

```bash
node_network_receive_bytes_total{device="eth0"}   # Получено байт
node_network_transmit_bytes_total{device="eth0"}  # Отправлено байт
node_network_receive_drop_total{device="eth0"}    # Отброшено входящих пакетов
node_network_transmit_drop_total{device="eth0"}   # Отброшено исходящих пакетов
node_network_up{device="eth0"}                    # Статус интерфейса (1 = активен)
```

**Пример PromQL:** входящий трафик в байт/сек

```promql
rate(node_network_receive_bytes_total{device="eth0"}[5m])
```

#### Системные показатели

```bash
node_boot_time_seconds          # Время последней загрузки системы
node_time_seconds               # Текущее системное время
node_procs_running              # Количество процессов в состоянии выполнения
node_procs_blocked              # Количество процессов, ожидающих ввода-вывода
node_context_switches_total     # Общее количество переключений контекста
node_interrupts_total           # Общее количество прерываний
node_vmstat_pgmajfault          # Количество критических ошибок страниц (major page faults)
```

### Алертинг (Alerting)

**Node Exporter недоступен:**

```yaml
- alert: NodeExporterDown
  expr: up{job="node_exporter"} == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Node Exporter недоступен на {{ $labels.instance }}"
    description: "Экспортер не отвечает более 5 минут"
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
    description: "Загрузка процессора превышает 80% более 10 минут"
```

**Критический уровень свободного места:**

```yaml
- alert: NodeDiskSpaceLow
  expr: (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100 > 90
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Заканчивается место на диске {{ $labels.instance }}"
    description: "Использовано более 90% дискового пространства на корневом разделе"
```

### Интеграция с Prometheus

Конфигурация сбора метрик (scrape config) в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
        labels:
          instance: 'web-server-01'
          environment: 'production'
```

Для автоматического обнаружения экспортеров рекомендуется использовать [Service Discovery](../service_discovery_and_relabeling.md).

### Безопасность

* **Минимальные привилегии:** хотя для некоторых метрик (например, `smart`) нужен `root`, старайтесь запускать экспортёр от выделенного пользователя.
* **Сетевой доступ:** ограничивайте доступ к порту 9100 на уровне файрвола (iptables/ufw) только для IP-адресов Prometheus-серверов.
* **Шифрование:** Node Exporter поддерживает TLS (Transport Layer Security) и базовую аутентификацию. Также можно использовать reverse proxy (Nginx/Apache).

## Дополнительная информация

### Расширяемость

* **[Textfile Collector](./extensibility/textfile_collector.md)** — сбор произвольных метрик через текстовые файлы.
* **[Написание своих экспортеров](./extensibility/custom_exporters.md)** — создание кастомных решений на языке Go.

### Связанные темы

* [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md)
* [Мониторинг производительности Linux](../../Linux/Diagnostics/Performance/atop.md)
* [Лейблы и кардинальность](../concepts/labels_and_cardinality.md)
