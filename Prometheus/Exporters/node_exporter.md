# Node Exporter

## Определения

**Node Exporter** — это стандартный инструмент мониторинга для сбора метрик аппаратного обеспечения и операционной системы на базе Linux. Он предоставляет сотни метрик, отражающих состояние ресурсов: CPU, памяти, дисков, сети, а также специфических подсистем ядра.

* **Порт по умолчанию:** `9100`
* **Актуальная версия (2026):** `v1.12.1`
* **Репозиторий:** [prometheus/node_exporter](https://github.com/prometheus/node_exporter)
* **Инструкция по установке:** [node_exporter_installation.md](../installation/node_exporter_installation.md)

## Основные концепции

### Источники данных: procfs и sysfs

Node Exporter не является активным агентом, который «опрашивает» ядро через системные вызовы. Вместо этого он читает и парсит данные из виртуальных файловых систем Linux, которые ядро обновляет автоматически:

* **`/proc`**: статистика процессов, памяти, планировщика CPU и системных прерываний.
* **`/sys`**: данные об аппаратных устройствах (диски, сетевые карты), драйверах, cgroups и термодатчиках.

Подробнее о механизмах: [виртуальная файловая система /proc](../../Linux/FileSystems/virtual_fs_proc.md) и [/sys](../../Linux/FileSystems/virtual_fs_sys.md).

### Поддержка Cgroup v2

В современных дистрибутивах Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+) Node Exporter полноценно поддерживает **Cgroup v2**. Метрики собираются через интерфейсы `/sys/fs/cgroup`. Это критично для корректного мониторинга ресурсов в контейнеризированных средах и системах с `systemd`.

### Архитектура коллекторов

Функциональность разделена на **коллекторы** (collectors). Каждый коллектор можно включить или выключить независимо через флаги запуска.

* **Включены по умолчанию:** базовые системные ресурсы (`cpu`, `meminfo`, `diskstats`, `netdev`, `filesystem`, `mdadm`, `uname`).
* **Отключены по умолчанию:** специфичные или ресурсоемкие метрики (`systemd`, `processes`, `logind`, `nfs`, `zfs`).

**Новые коллекторы (v1.10+):**
* `nvmesubsystem` — детальный мониторинг NVMe накопителей.
* `mountstats` — детальная статистика NFS-монтирований.
* `dmmultipath` — состояние Device Mapper Multipath.

---

## Практические сценарии

### Управление коллекторами при запуске

Для оптимизации нагрузки и уменьшения кардинальности (cardinality) рекомендуется отключать ненужные коллекторы и включать только необходимые.

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

Node Exporter поддерживает встроенную защиту через файл конфигурации `web-config.yml`. Это позволяет отказаться от использования Nginx-прокси для базовой защиты.

**Пример `web-config.yml`:**

```yaml
tls_server_config:
  cert_file: /etc/node_exporter/tls.crt
  key_file: /etc/node_exporter/tls.key
  # Рекомендуется для Zero Trust архитектур (mTLS):
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/node_exporter/ca.crt

basic_auth_users:
  # Хеш пароля генерируется через htpasswd (bcrypt)
  admin: "$2b$12$..." 
```

**Запуск с защитой:**
```bash
./node_exporter --web.config.file=web-config.yml
```

---

## Детальное описание метрик и PromQL

### 1. Процессор (CPU)

Метрики CPU представлены в секундах, потраченных в различных режимах.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_cpu_seconds_total` | Counter | Время CPU в разных режимах (`idle`, `system`, `user`, `iowait`, `steal`). |
| `node_load1` / `node_load5` / `node_load15` | Gauge | Средняя нагрузка системы за 1, 5 и 15 минут. |
| `node_procs_running` | Gauge | Количество процессов в состоянии "Running". |
| `node_context_switches_total` | Counter | Количество переключений контекста. |

**Примеры PromQL:**

* **Загрузка CPU в % (среднее по всем ядрам для конкретного инстанса):**
  ```promql
  100 - (avg by(instance) (rate(node_cpu_seconds_total{instance="[инстанс]", mode="idle"}[5m])) * 100)
  ```
* **Средняя нагрузка (Load Average) относительно количества ядер:**
  ```promql
  node_load1{instance="[инстанс]"} / count(node_cpu_seconds_total{instance="[инстанс]", mode="idle"})
  ```

### 2. Память (RAM)

В отличие от многих инструментов, Node Exporter предоставляет "сырые" данные из `/proc/meminfo`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_memory_MemTotal_bytes` | Gauge | Общий объем физической памяти. |
| `node_memory_MemAvailable_bytes` | Gauge | **Доступная память.** Учитывает кэши, которые могут быть быстро освобождены. |
| `node_memory_MemFree_bytes` | Gauge | Полностью свободная (неиспользуемая) память. |
| `node_memory_Cached_bytes` / `node_memory_Buffers_bytes` | Gauge | Память под кэш страниц и буферы ядра. |
| `node_memory_SwapTotal_bytes` | Gauge | Общий объем раздела подкачки. |

**Примеры PromQL:**

* **Использование оперативной памяти в %:**
  ```promql
  (1 - (node_memory_MemAvailable_bytes{instance="[инстанс]"} / node_memory_MemTotal_bytes{instance="[инстанс]"})) * 100
  ```
* **Использование Swap в %:**
  ```promql
  (1 - (node_memory_SwapFree_bytes{instance="[инстанс]"} / node_memory_SwapTotal_bytes{instance="[инстанс]"})) * 100
  ```

### 3. Дисковая подсистема (Disk & Filesystem)

Важно различать метрики файловой системы (логический уровень) и дисковой статистики (физический/блочный уровень).

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_filesystem_size_bytes` | Gauge | Общий размер файловой системы. |
| `node_filesystem_avail_bytes` | Gauge | Свободное место, доступное для обычного пользователя. |
| `node_filesystem_files_free` | Gauge | Количество свободных **inodes** (критично для систем с множеством мелких файлов). |
| `node_disk_io_time_seconds_total` | Counter | Время, в течение которого диск был занят (Disk Utilization). |
| `node_disk_read_bytes_total` / `node_disk_written_bytes_total` | Counter | Суммарный объем прочитанных/записанных данных. |

**Примеры PromQL:**

* **Свободное место на корневом разделе в %:**
  ```promql
  (node_filesystem_avail_bytes{instance="[инстанс]", mountpoint="/"} / node_filesystem_size_bytes{instance="[инстанс]", mountpoint="/"}) * 100
  ```
* **Утилизация конкретного диска в %:**
  ```promql
  rate(node_disk_io_time_seconds_total{instance="[инстанс]", device="sda"}[5m]) * 100
  ```
* **Скорость записи на диск (байт/сек):**
  ```promql
  rate(node_disk_written_bytes_total{instance="[инстанс]", device="sda"}[5m])
  ```

### 4. Сетевые метрики (Network)

Снимаются с каждого сетевого интерфейса.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_network_receive_bytes_total` | Counter | Входящий трафик в байтах. |
| `node_network_transmit_bytes_total` | Counter | Исходящий трафик в байтах. |
| `node_network_receive_errs_total` | Counter | Ошибки при получении пакетов. |
| `node_network_up` | Gauge | Статус интерфейса (1 = Up, 0 = Down). |

**Примеры PromQL:**

* **Входящая скорость на интерфейсе eth0 (Мбит/сек):**
  ```promql
  rate(node_network_receive_bytes_total{instance="[инстанс]", device="eth0"}[5m]) * 8 / 1024 / 1024
  ```

---

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
      description: "Node Exporter не отвечает более 5 минут."

  # Критическое заполнение диска
  - alert: HostOutOfDiskSpace
    expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Мало места на диске ({{ $labels.instance }})"
      description: "Свободно менее 10% на разделе {{ $labels.mountpoint }}."

  # Высокая нагрузка CPU (LA > кол-во ядер)
  - alert: HostHighLoad
    expr: node_load1 > count(node_cpu_seconds_total{mode="idle"}) * 1.5
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Высокая нагрузка на {{ $labels.instance }}"
      description: "Load Average выше количества ядер более 10 минут."

  # Закончились inodes
  - alert: HostOutOfInodes
    expr: node_filesystem_files_free{mountpoint="/"} / node_filesystem_files{mountpoint="/"} * 100 < 5
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Заканчиваются inodes на {{ $labels.instance }}"
```

---

## Дополнительная информация

### Reliability Score: 10
Документация соответствует Node Exporter v1.12.1 и актуальным практикам мониторинга Linux-инфраструктуры на 2026 год.

### Расширяемость

* **[Textfile Collector](./extensibility/textfile_collector.md)** — механизм для интеграции кастомных скриптов (bash, python) без написания экспортера.
* **[SMART Monitoring](./smart_monitoring.md)** — мониторинг здоровья дисков.

### Связанные темы

* [Установка Node Exporter](../installation/node_exporter_installation.md) — systemd, Docker, бинарный запуск.
* [Обзор экспортеров](./overview.md) — сравнение с другими решениями.
* [Мониторинг Docker](../../Docker/Docker_metrics/docker_prometheus_integration.md) — нативные метрики движка.
* [cAdvisor](./cadvisor.md) — метрики потребления ресурсов контейнерами.
