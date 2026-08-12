# Node Exporter

## Определения

**Node Exporter** — это стандартный инструмент мониторинга для сбора аппаратных и операционных метрик (ОС на базе ядра Linux/Unix). Он предоставляет сотни системных показателей, отражающих состояние ресурсов: процессора, памяти, дисковых подсистем, сетевых интерфейсов, а также специфических модулей ядра.

*   **Порт по умолчанию:** `9100`
*   **Актуальная версия (2026):** `v1.12.1`
*   **Репозиторий:** [prometheus/node_exporter](https://github.com/prometheus/node_exporter)
*   **Инструкция по установке:** [node_exporter_installation.md](../installation/node_exporter_installation.md)

**См. также:** [Обзор экспортеров](./overview.md), [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

## Основные концепции

### Источники данных: procfs и sysfs

Node Exporter не является активным агентом, который опрашивает ядро через системные вызовы. Вместо этого он читает и парсит данные из виртуальных файловых систем Linux, которые ядро обновляет автоматически. Это обеспечивает высокую производительность и минимальный оверхед:

*   **`/proc`**: Статистика запущенных процессов, памяти (`meminfo`), планировщика CPU (`stat`) и аппаратных прерываний (`interrupts`).
*   **`/sys`**: Данные об аппаратных устройствах (диски, сетевые карты), драйверах, `cgroups` и термодатчиках.

Подробнее о механизмах: [виртуальная файловая система /proc](../../Linux/FileSystems/virtual_fs_proc.md) и [/sys](../../Linux/FileSystems/virtual_fs_sys.md).

### Поддержка cgroup v2

В современных дистрибутивах Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+) Node Exporter полноценно поддерживает **cgroup v2**. Метрики собираются через интерфейсы `/sys/fs/cgroup`. Это критично для корректного мониторинга ресурсов в контейнеризированных средах и системах с `systemd`, так как v2 использует единую иерархию управления ресурсами.

### Архитектура коллекторов

Архитектура Node Exporter основана на независимых модулях — **коллекторах** (collectors). Каждый коллектор можно включить или выключить независимо через флаги запуска.

*   **Включены по умолчанию:** Базовые системные ресурсы (`cpu`, `meminfo`, `diskstats`, `netdev`, `filesystem`, `mdadm`, `loadavg`, `uname`).
*   **Отключены по умолчанию:** Специфичные или ресурсоемкие метрики (`systemd`, `processes`, `logind`, `nfs`, `zfs`, `ntp`).
*   **Новые коллекторы (v1.10+):**
    *   `nvmesubsystem` — детальный мониторинг NVMe накопителей.
    *   `mountstats` — детальная статистика NFS-монтирований.
    *   `dmmultipath` — состояние Device Mapper Multipath.

## Практические сценарии

### Управление коллекторами при запуске

Для оптимизации нагрузки и уменьшения кардинальности (cardinality) в TSDB Prometheus, рекомендуется отключать ненужные коллекторы и явно включать требуемые.

```bash
# Пример запуска с отключением неиспользуемых и включением дополнительных коллекторов
./node_exporter \
  --no-collector.wifi \
  --no-collector.zfs \
  --collector.systemd \
  --collector.processes \
  --collector.textfile.directory="/var/lib/node_exporter/textfile_reports"
```

### Безопасность: TLS и Аутентификация

Node Exporter поддерживает встроенную защиту через конфигурационный файл `web-config.yml`. Это позволяет реализовать аутентификацию и шифрование без необходимости устанавливать Nginx в качестве reverse-proxy.

**Пример `web-config.yml`:**
```yaml
tls_server_config:
  cert_file: /etc/node_exporter/tls.crt
  key_file: /etc/node_exporter/tls.key
  # Рекомендуется для Zero Trust архитектур (mTLS):
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/node_exporter/ca.crt

basic_auth_users:
  # Хеш пароля генерируется через htpasswd (алгоритм bcrypt)
  admin: "$2b$12$..." 
```

**Запуск с защитой:**
```bash
./node_exporter --web.config.file=web-config.yml
```

## Детальное описание метрик и PromQL

### 1. Процессор (CPU)

Метрики CPU представлены в секундах, потраченных в различных режимах. Для анализа всегда используется функция `rate()`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_cpu_seconds_total` | Counter | Суммарное время CPU в разных режимах (`idle`, `system`, `user`, `iowait`, `steal`). |
| `node_load1` / `node_load5` / `node_load15` | Gauge | Средняя нагрузка системы (Load Average) за 1, 5 и 15 минут. |
| `node_procs_running` | Gauge | Количество процессов в состоянии "Running" (из `/proc/stat`). |
| `node_context_switches_total` | Counter | Количество переключений контекста ядром. |

**Примеры PromQL:**
*   **Загрузка CPU в % (среднее по всем ядрам для конкретного инстанса):**
    ```promql
    100 - (avg by(instance) (rate(node_cpu_seconds_total{instance="[инстанс]", mode="idle"}[5m])) * 100)
    ```
*   **Средняя нагрузка (Load Average) относительно количества ядер:**
    ```promql
    node_load1{instance="[инстанс]"} / count(node_cpu_seconds_total{instance="[инстанс]", mode="idle"})
    ```

### 2. Память (RAM)

В отличие от многих инструментов мониторинга, Node Exporter предоставляет "сырые" неагрегированные данные напрямую из `/proc/meminfo`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_memory_MemTotal_bytes` | Gauge | Общий объем физической памяти. |
| `node_memory_MemAvailable_bytes` | Gauge | **Доступная память.** Учитывает кэши, которые могут быть быстро освобождены ОС при нехватке RAM. |
| `node_memory_MemFree_bytes` | Gauge | Полностью свободная (неиспользуемая) память. Не используйте для алертинга! |
| `node_memory_Cached_bytes` / `node_memory_Buffers_bytes` | Gauge | Память под кэш страниц и дисковые буферы ядра. |
| `node_memory_SwapTotal_bytes` / `node_memory_SwapFree_bytes` | Gauge | Статистика пространства подкачки (Swap). |

**Примеры PromQL:**
*   **Использование оперативной памяти в %:**
    ```promql
    (1 - (node_memory_MemAvailable_bytes{instance="[инстанс]"} / node_memory_MemTotal_bytes{instance="[инстанс]"})) * 100
    ```
*   **Использование Swap в %:**
    ```promql
    (1 - (node_memory_SwapFree_bytes{instance="[инстанс]"} / node_memory_SwapTotal_bytes{instance="[инстанс]"})) * 100
    ```

### 3. Дисковая подсистема (Disk & Filesystem)

Важно различать метрики файловой системы (логический уровень использования места) и дисковой статистики (физический/блочный уровень I/O).

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_filesystem_size_bytes` | Gauge | Общий размер файловой системы. |
| `node_filesystem_avail_bytes` | Gauge | Свободное место, доступное для обычного (не root) пользователя. |
| `node_filesystem_files_free` | Gauge | Количество свободных **inodes** (критично для систем с множеством мелких файлов). |
| `node_disk_io_time_seconds_total` | Counter | Время, в течение которого диск был занят обслуживанием I/O (Disk Utilization). |
| `node_disk_read_bytes_total` / `node_disk_written_bytes_total` | Counter | Суммарный объем прочитанных/записанных данных на блочное устройство. |

**Примеры PromQL:**
*   **Свободное место на корневом разделе в %:**
    ```promql
    (node_filesystem_avail_bytes{instance="[инстанс]", mountpoint="/"} / node_filesystem_size_bytes{instance="[инстанс]", mountpoint="/"}) * 100
    ```
*   **Утилизация конкретного физического диска (например, sda) в %:**
    ```promql
    rate(node_disk_io_time_seconds_total{instance="[инстанс]", device="sda"}[5m]) * 100
    ```
*   **Скорость записи на диск (байт/сек):**
    ```promql
    rate(node_disk_written_bytes_total{instance="[инстанс]", device="sda"}[5m])
    ```

### 4. Сетевые метрики (Network)

Статистика снимается с каждого сетевого интерфейса. При визуализации часто требуется фильтровать виртуальные интерфейсы (например, `veth*`, `docker0`).

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_network_receive_bytes_total` | Counter | Входящий трафик (получено байт). |
| `node_network_transmit_bytes_total` | Counter | Исходящий трафик (отправлено байт). |
| `node_network_receive_errs_total` | Counter | Суммарное количество ошибок на уровне интерфейса при приеме. |
| `node_network_up` | Gauge | Статус интерфейса (1 = Up, 0 = Down). |

**Примеры PromQL:**
*   **Входящая скорость на интерфейсе eth0 (Мбит/сек):**
    ```promql
    rate(node_network_receive_bytes_total{instance="[инстанс]", device="eth0"}[5m]) * 8 / 1024 / 1024
    ```

## Алертинг (Alerting Rules)

### Рекомендуемые правила (Best Practices)

```yaml
groups:
- name: NodeExporterAlerts
  rules:
  # Инстанс недоступен
  - alert: HostDown
    expr: up{job="node-exporter"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Инстанс {{ $labels.instance }} недоступен"
      description: "Node Exporter не отвечает на HTTP запросы скрейпинга более 5 минут."

  # Критическое заполнение диска (осталось менее 10%)
  - alert: HostOutOfDiskSpace
    expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Критически мало места на диске ({{ $labels.instance }})"
      description: "Свободно менее 10% на разделе {{ $labels.mountpoint }}."

  # Высокая нагрузка CPU (LA превышает кол-во ядер в 1.5 раза)
  - alert: HostHighLoad
    expr: node_load1 > count(node_cpu_seconds_total{mode="idle"}) * 1.5
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Высокая нагрузка на сервер {{ $labels.instance }}"
      description: "Load Average (1m) стабильно выше количества доступных ядер более 10 минут."

  # Закончились inodes
  - alert: HostOutOfInodes
    expr: node_filesystem_files_free{mountpoint="/"} / node_filesystem_files{mountpoint="/"} * 100 < 5
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Заканчиваются inodes на файловой системе {{ $labels.instance }}"
```

## Дополнительная информация

### Расширяемость коллекторов

*   **[Textfile Collector](./extensibility/textfile_collector.md)** — основной механизм для интеграции кастомных скриптов (bash, python) и вывода сторонних утилит без написания отдельного экспортера.
*   **[SMART Monitoring](./smart_monitoring.md)** — мониторинг здоровья и износа дисков.

### См. также

*   [Установка Node Exporter](../installation/node_exporter_installation.md) — systemd, Docker, бинарный запуск.
*   [Метрики cAdvisor](./cadvisor.md) — детализированный мониторинг ресурсов внутри контейнеров.
*   [Мониторинг Docker](../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с Prometheus.
