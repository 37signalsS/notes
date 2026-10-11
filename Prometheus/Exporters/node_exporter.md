# Node Exporter

## Определения

**Node Exporter** — это стандартный инструмент мониторинга для сбора аппаратных и операционных метрик (ОС на базе ядра Linux/Unix). Он предоставляет сотни системных показателей, отражающих состояние ресурсов: процессора, памяти, дисковых подсистем, сетевых интерфейсов, а также специфических модулей ядра.

*   **Порт по умолчанию:** `9100`
*   **Актуальная версия (2026):** `v1.12.1`
*   **Репозиторий:** [prometheus/node_exporter](https://github.com/prometheus/node_exporter)
*   **Инструкция по установке:** [node_exporter_installation.md](../installation/node_exporter_installation.md)

**См. также:** [Обзор экспортеров](./overview.md), [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

## Предварительные требования

*   **ОС:** Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+, Rocky Linux 9+), BSD или macOS. Для Linux требуется systemd или cron для периодических задач.
*   **Архитектура:** amd64, arm64, armv7, ppc64le, s390x.
*   **Права доступа:**
    *   Для доступа к метрикам ядра (`diskstats`, `hwmon`, `edac`) рекомендуется запуск от `root`.
    *   При запуске от непривилегированного пользователя добавьте его в группы `disk`, `hwmon`, `adm`.
*   **Файловые системы:** Метрики файловых систем собираются из `/proc/mounts` и `/proc/self/mountinfo`. Для корректной работы в контейнерах требуется монтирование `/proc` и `/sys` хоста.
*   **Сеть:** Порт `9100` должен быть доступен для Prometheus-сервера. При использовании TLS/basic auth убедитесь, что конфигурационный файл `web-config.yml` корректно сформирован.
*   **Ресурсы:** Рекомендуемые лимиты — не более 150m CPU и 128Mi RAM на инстанс. При включении тяжелых коллекторов (`zfs`, `nfs`, `nfsd`) может потребоваться увеличение до 300m CPU.

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
*   **Важные коллекторы (v1.8+):**
    *   `pressure` — Pressure Stall Information (PSI) для CPU, памяти и I/O. Позволяет измерять реальное время простоя процессов из-за нехватки ресурсов.
    *   `softnet` — статистика обработки сетевых прерываний ядром (`netdev`-коллектор собирает только интерфейсные счетчики, `softnet` — внутреннюю обработку).
    *   `ksmd` — демон `kswapd` (Kernel Swap Daemon), отслеживающий активность подкачки.

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

### Мониторинг systemd-сервисов

Включите коллектор `systemd` для получения статусов юнитов без дополнительных скриптов. Это особенно полезно для отслеживания критичных сервисов (`sshd`, `cron`, `networkd`).

```bash
./node_exporter \
  --collector.systemd
```

**Пример PromQL:**
```promql
# Сервис перешел в failed состояние
node_systemd_unit_state{state="failed"} == 1

# Сервис постоянно перезапускается (более 3 раз за 5 минут)
increase(node_systemd_unit_state{state="activating"}[5m]) > 3
```

### Мониторинг NTP и времени

Коллектор `ntp` (отключен по умолчанию) предоставляет метрики отклонения времени от NTP-серверов. В системах с chrony или systemd-timesyncd это критично для корректной работы кластеров и логов.

```bash
./node_exporter \
  --collector.ntp
```

**Пример PromQL:**
```promql
# Отклонение времени более 0.1 секунды
abs(node_timex_offset_seconds) > 0.1

# Синхронизация не установлена
node_timex_sync_status == 0
```

### Мониторинг аппаратных сенсоров (hwmon/thermal)

Коллекторы `hwmon` и `thermal` автоматически собирают данные о температуре, вольтаже, скорости вращения вентиляторов и мощности с чипов на материнской плате (coretemp, nct6798 и др.).

```bash
./node_exporter \
  --collector.hwmon \
  --collector.thermal
```

**Пример PromQL:**
```promql
# Температура CPU выше 75°C в течение 5 минут
node_hwmon_temp_celsius{sensor="coretemp"} > 75

# Вентилятор остановился
node_hwmon_fan_rpm == 0
```

### Производительность и управление кардинальностью

При развертывании на тысячах серверов важно контролировать количество уникальных временных рядов (cardinality). Каждый высококардинальный лейбл (например, `device` с уникальными именами дисков) умножает объем данных во всех агрегациях.

**Рекомендации:**
*   Используйте `metric_relabel_configs` для удаления лишних лейблов на стороне Prometheus.
*   Ограничьте `filesystem` коллектор через `--collector.filesystem.mount-points-exclude`, чтобы не собирать метрики с виртуальных ФС.
*   Устанавливайте `scrape_interval` не менее 15 секунд для Node Exporter.
*   Для высоконагруженных систем используйте `--collector.netdev.ignored-devices` для исключения виртуальных интерфейсов.

**Пример конфигурации Prometheus:**
```yaml
scrape_configs:
  - job_name: 'node-exporter'
    scrape_interval: 30s
    static_configs:
      - targets: ['server1:9100', 'server2:9100']
    metric_relabel_configs:
      # Удаляем лейбл device для снижения кардинальности
      - source_labels: [__name__]
        regex: 'node_disk_.*'
        target_label: device
        action: 'drop'
```

### Валидация установки

После развертывания проверьте корректность работы экспортера:

```bash
# 1. Проверка доступности эндпоинта
curl -s http://localhost:9100/metrics | head -20

# 2. Проверка наличия ключевых метрик
curl -s http://localhost:9100/metrics | grep -E 'node_cpu_seconds_total|node_memory_MemTotal_bytes|node_filesystem_size_bytes'

# 3. Проверка статуса systemd-сервиса
systemctl status node_exporter

# 4. Проверка коллекторов через флаг --web.enable-lifecycle
curl -s http://localhost:9100/metrics | grep -E '^# HELP node_'
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
| `node_intr_total` | Counter | Общее количество аппаратных прерываний. |
| `node_softnet_total` | Counter | Суммарное количество обработанных пакетов сетевым стеком ядра. |

**Примеры PromQL:**
*   **Загрузка CPU в % (среднее по всем ядрам для конкретного инстанса):**
    ```promql
    100 - (avg by(instance) (rate(node_cpu_seconds_total{instance="[инстанс]", mode="idle"}[5m])) * 100)
    ```
*   **Средняя нагрузка (Load Average) относительно количества ядер:**
    ```promql
    node_load1{instance="[инстанс]"} / count(node_cpu_seconds_total{instance="[инстанс]", mode="idle"})
    ```
*   **Количество переключений контекста в секунду:**
    ```promql
    rate(node_context_switches_total[5m])
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
| `node_memory_Active_bytes` / `node_memory_Inactive_bytes` | Gauge | Активная/неактивная память (полезно для диагностики page cache). |

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
| `node_filesystem_files` | Gauge | Общее количество inodes. |
| `node_filesystem_files_free` | Gauge | Количество свободных **inodes** (критично для систем с множеством мелких файлов). |
| `node_filesystem_readonly` | Gauge | Файловая система смонтирована только для чтения (1 = да). |
| `node_disk_io_time_seconds_total` | Counter | Время, в течение которого диск был занят обслуживанием I/O (Disk Utilization). |
| `node_disk_read_bytes_total` / `node_disk_written_bytes_total` | Counter | Суммарный объем прочитанных/записанных данных на блочное устройство. |
| `node_disk_read_time_seconds_total` / `node_disk_write_time_seconds_total` | Counter | Суммарное время чтения/записи. |
| `node_disk_io_time_weighted_seconds_total` | Counter | Взвешенное время I/Os — интеграл числа операций в очереди по времени (сумма `N·(N+1)/2`). Делится на `node_disk_io_time_seconds_total` даёт среднюю глубину очереди, а на число операций — среднее время ожидания в очереди (await). |

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
*   **Использование inodes на всех ФС (кроме tmpfs и overlay):**
    ```promql
    100 - (avg by(instance, mountpoint) (node_filesystem_files_free{fstype!~"tmpfs|overlay"} / node_filesystem_files{fstype!~"tmpfs|overlay"})) * 100
    ```

### 4. Сетевые метрики (Network)

Статистика снимается с каждого сетевого интерфейса. При визуализации часто требуется фильтровать виртуальные интерфейсы (например, `veth*`, `docker0`).

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_network_receive_bytes_total` | Counter | Входящий трафик (получено байт). |
| `node_network_transmit_bytes_total` | Counter | Исходящий трафик (отправлено байт). |
| `node_network_receive_errs_total` / `node_network_transmit_errs_total` | Counter | Суммарное количество ошибок на уровне интерфейса при приёме/передаче. |
| `node_network_up` | Gauge | Статус интерфейса (1 = Up, 0 = Down). |
| `node_network_speed_bytes` | Gauge | Скорость интерфейса в байтах/сек (из `/sys/class/net/*/speed`). |
| `node_network_receive_drop_total` / `node_network_transmit_drop_total` | Counter | Отброшенные пакеты при приёме/передаче. |

**Примеры PromQL:**
*   **Входящая скорость на интерфейсе eth0 (Мбит/сек):**
    ```promql
    rate(node_network_receive_bytes_total{instance="[инстанс]", device="eth0"}[5m]) * 8 / 1024 / 1024
    ```
*   **Утилизация сетевого интерфейса в %:**
    ```promql
    rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8 / node_network_speed_bytes{device="eth0"} * 100
    ```

### 5. Процессы (Processes)

Коллектор `processes` (отключен по умолчанию) собирает агрегированную статистику по запущенным процессам.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_procs_running` | Gauge | Процессы в состоянии "Running" или "Runnable". |
| `node_procs_blocked` | Gauge | Процессы, заблокированные на завершение I/O. |
| `node_processes` | Gauge | Общее количество дескрипторов процессов (pid_max). |

**Примеры PromQL:**
*   **Отношение заблокированных процессов к общему количеству:**
    ```promql
    node_procs_blocked / node_processes
    ```

### 6. Systemd

Коллектор `systemd` (отключен по умолчанию) экспортирует статусы юнитов systemd. Позволяет отслеживать failed, activating, inactive состояния без внешних скриптов.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_systemd_unit_state` | Gauge | Состояние юнита (1 = текущее состояние, 0 = нет). Лейбл `state`: `active`, `failed`, `inactive`, `activating`. |

**Примеры PromQL:**
*   **Сервисы в failed состоянии:**
    ```promql
    node_systemd_unit_state{state="failed"} == 1
    ```
*   **Сервисы, которые перезапускаются чаще 3 раз за 5 минут:**
    ```promql
    increase(node_systemd_unit_state{state="activating"}[5m]) > 3
    ```

### 7. Время и NTP

Node Exporter собирает метрики синхронизации времени через системные вызовы `adjtimex`/`ntp_adjtime`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_boot_time_seconds` | Gauge | Время загрузки системы (Unix timestamp). |
| `node_timex_offset_seconds` | Gauge | Текущее отклонение системных часов от эталона (NTP). |
| `node_timex_sync_status` | Gauge | Статус синхронизации (1 = синхронизировано, 0 = нет). |
| `node_timex_maxerror_seconds` | Gauge | Максимальная ошибка времени (Error threshold). |
| `node_ntp_sanity` | Gauge | Результат sanity-проверки NTP (1 = OK, 0 = FAIL). |

**Примеры PromQL:**
*   **Обнаружение перезагрузки сервера:**
    ```promql
    changes(node_boot_time_seconds[5m]) > 0
    ```
*   **Расхождение времени более 1 секунды:**
    ```promql
    abs(node_timex_offset_seconds) > 1
    ```

### 8. Давление и Stall (Pressure Stall Information — PSI)

Коллектор `pressure` (включен по умолчанию с v1.8.0) предоставляет метрики PSI, которые измеряют, сколько времени процессы простаивали в очереди из-за нехватки ресурсов. В отличие от утилизации (utilisation), PSI показывает реальное влияние на рабочую нагрузку.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_pressure_cpu_waiting_seconds_total` | Counter | Время, когда процессы ожидали CPU. |
| `node_pressure_memory_waiting_seconds_total` | Counter | Время, когда процессы ожидали памяти (OOM, kswapd). |
| `node_pressure_io_waiting_seconds_total` | Counter | Время, когда процессы ожидали I/O. |
| `node_pressure_cpu_waiting_seconds` | Gauge | Текущее накопленное время ожидания CPU. |

**Примеры PromQL:**
*   **Давление на память (полное, более 5% времени):**
    ```promql
    rate(node_pressure_memory_waiting_seconds_total{state="full"}[5m]) > 0.05
    ```
*   **Давление на I/O (частичное, более 10%):**
    ```promql
    rate(node_pressure_io_waiting_seconds_total{state="some"}[5m]) > 0.1
    ```

### 9. Аппаратные сенсоры (hwmon/thermal)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `node_hwmon_temp_celsius` | Gauge | Температура датчиков (coretemp, nct6798 и др.). |
| `node_hwmon_fan_rpm` | Gauge | Скорость вращения вентиляторов. |
| `node_hwmon_in_volts` | Gauge | Напряжение на линии питания. |
| `node_hwmon_power_watts` | Gauge | Потребляемая мощность (если поддерживается датчиком). |
| `node_thermal_zone_temp` | Gauge | Температура thermal zone ядра. |

**Примеры PromQL:**
*   **Температура CPU выше 75°C в течение 5 минут:**
    ```promql
    node_hwmon_temp_celsius{sensor="coretemp"} > 75
    ```
*   **Скорость изменения температуры более 0.5 градуса/сек (перегрев):**
    ```promql
    deriv(node_hwmon_temp_celsius{sensor="coretemp"}[5m]) > 0.5
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

  # NTP-расхождение
  - alert: HostNTPDesync
    expr: abs(node_timex_offset_seconds) > 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Расхождение времени на {{ $labels.instance }}"
      description: "Отклонение от NTP-сервера составляет {{ $value }} секунд."

  # Давление на память (PSI)
  - alert: HostMemoryPressure
    expr: rate(node_pressure_memory_waiting_seconds_total{state="full"}[5m]) > 0.05
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Давление на память ({{ $labels.instance }})"
      description: "Процессы простаивали более 5% времени из-за нехватки памяти."

  # Перегрев CPU
  - alert: HostCPUTemperatureHigh
    expr: node_hwmon_temp_celsius{sensor="coretemp"} > 75
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокая температура CPU ({{ $labels.instance }})"
      description: "Температура ядра {{ $value }}°C."

  # Остановился вентилятор
  - alert: HostFanFailed
    expr: node_hwmon_fan_rpm == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Вентилятор не вращается ({{ $labels.instance }})"
      description: "Датчик {{ $labels.sensor }} показывает 0 RPM."

  # Failed systemd-сервис
  - alert: HostSystemdServiceFailed
    expr: node_systemd_unit_state{state="failed"} == 1
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Сервис {{ $labels.unit }} в состоянии failed"
      description: "Systemd-юнит {{ $labels.unit }} на {{ $labels.instance }} завершился с ошибкой."

  # Частые перезапуски сервиса
  - alert: HostSystemdServiceRestarting
    expr: increase(node_systemd_unit_state{state="activating"}[5m]) > 3
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Сервис {{ $labels.unit }} перезапускается"
      description: "Юнит {{ $labels.unit }} активировался более 3 раз за 5 минут."
```

## Типичные ошибки и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` при чтении `/proc` или `/sys` | Запуск от непривилегированного пользователя | Запустите от `root` или добавьте пользователя в группы `disk`, `hwmon`. |
| Метрики файловой системы пустые | Отсутствует монтирование `/` или `--path.rootfs` указан неверно | Проверьте монтирование хостовых директорий в контейнере. |
| Высокая нагрузка на CPU | Слишком много активных коллекторов (`zfs`, `nfs`, `nfsd`) | Отключите неиспользуемые коллекторы через `--no-collector.<name>`. |
| `node_disk_*` метрики отсутствуют для диска | Диск не имеет личного блочного устройства (например, LUN на multipath) | Проверьте `dmmultipath` коллектор или имена устройств через `lsblk`. |
| Метрики не обновляются | `node_exporter` упал или завис | Проверьте `systemctl status node_exporter`, логи `journalctl -u node_exporter`. |
| Высокая кардинальность в TSDB | Лейблы с уникальными значениями (например, `device` для каждого LUN) | Используйте `metric_relabel_configs` для удаления лишних лейблов. |
| `stale` метрики | Экспортер перезапустился без graceful shutdown | Добавьте `KillSignal=SIGTERM` и `TimeoutStopSec=10` в systemd-юнит. |

## Лучшие практики

*   **Запуск от root:** Для доступа ко всем метрикам ядра (`diskstats`, `hwmon`) рекомендуется запускать Node Exporter от `root` или через `sudo`. При невозможности используйте capabilities (`CAP_SYS_ADMIN`, `CAP_SYS_RAWIO`).
*   **Systemd hardening:** Используйте стандартные директивы hardening в unit-файле (`NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, `PrivateTmp`).
*   **Scrape interval:** Устанавливайте `scrape_interval` не менее 15 секунд. Для инфраструктурного мониторинга рекомендуется 30 секунд, чтобы избежать избыточной нагрузки на ядро при чтении `/proc`.
*   **Фильтрация метрик:** Вместо отключения коллекторов полностью, можно использовать `collect[]` в URL скрейпинга или `metric_relabel_configs` для selective сбора.
*   **Мониторинг мониторинга:** Настройте алерт на `up{job="node-exporter"} == 0` и на `exporter_scrape_duration_seconds` (если Prometheus собирает метрики экспортера).
*   **Разделение ответственности:** Не объединяйте в одном экспортере метрики, которые имеют разные owners. Для кастомных метрик используйте [Textfile Collector](./extensibility/textfile_collector.md).

## Граничные случаи и особенности

*   **Атомарность `mv`:** Textfile Collector ожидает, что `.prom` файлы обновляются атомарно (через `mv` на ту же ФС). Если скрипт пишет напрямую в целевой файл, при скрапинге может попасться полузаписанный файл.
*   **Stale-маркеры:** При удалении метрики из `.prom` файла, `node_exporter` по умолчанию не отправляет stale-маркер. Для корректного исчезновения временного ряда добавьте метрику с тем же именем и значением `NaN`.
*   **Нативные гистограммы:** Текстовый формат экспозиции (`.prom`) не поддерживает нативные гистограммы (exponential buckets). Для их использования требуется бинарный формат Protobuf или OTLP.
*   **Кодировка:** Метрики в `.prom` файлах должны быть в кодировке UTF-8 без BOM. Любые символы вне ASCII в `HELP` или лейблах должны быть валидированы через `promtool check metrics`.
*   **Виртуальные ФС в контейнерах:** При запуске в Docker без монтирования `/proc` и `/sys` хоста, экспортер будет собирать метрики самого контейнера, а не хоста. Обязательно используйте `--path.procfs=/host/proc`, `--path.sysfs=/host/sys`.
*   **Ограничения `/proc`:** Некоторые метрики (например, `interrupts`, `softnet`) могут потреблять значительные ресурсы при чтении на системах с тысячами прерываний. Используйте фильтры или отключайте коллекторы, если не нужны.
*   **Переименование интерфейсов:** В современных дистрибутивах используется predictable network interface names (`enp0s3`, `ens192` вместо `eth0`). Убедитесь, что ваши алерты и дашборды используют правильные имена интерфейсов.

## Дополнительная информация

### Расширяемость коллекторов

*   **[Textfile Collector](./extensibility/textfile_collector.md)** — основной механизм для интеграции кастомных скриптов (bash, python) и вывода сторонних утилит без написания отдельного экспортера.
*   **[SMART Monitoring](../../Linux/Diagnostics/Hardware/smartctl/smartctl_exporter.md)** — мониторинг здоровья и износа дисков.

### См. также

*   [Установка Node Exporter](../installation/node_exporter_installation.md) — systemd, Docker, бинарный запуск.
*   [Метрики cAdvisor](./cadvisor.md) — детализированный мониторинг ресурсов внутри контейнеров.
*   [Мониторинг Docker](../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с Prometheus.
