# Нативные метрики Docker

**Актуально для:** Docker Engine 20.10+

## Определения

**Нативные метрики Docker** — встроенные механизмы Docker Engine для сбора и отображения статистики потребления ресурсов контейнерами и самим демоном. Они позволяют проводить оперативную диагностику производительности (CPU, память, I/O, сеть) без использования внешних систем мониторинга.

**Docker Engine Metrics (порт 9323)** — встроенный экспортер метрик демона в формате Prometheus. Экспортирует стандартный Prometheus-реестр демона: метрики самого демона (`engine_daemon_`), сборки (`builder_*`), логирования (`logger_*`), Swarm (`swarm_*`) и Go-runtime (`go_*`, `process_*`): информацию о движке, состояния контейнеров, health-check'и, таймеры операций. Per-container метрики не предоставляет — для них нужен cAdvisor.

**PSI (Pressure Stall Information)** — метрики ядра Linux, показывающие процент времени, в течение которого задачи не могли получить доступ к CPU, памяти или диску из-за нехватки ресурса. Доступны через файлы `cpu.pressure`, `memory.pressure`, `io.pressure` в cgroup v2.

## Основные концепции

### Источник данных: cgroups

Docker полагается на механизм ядра Linux **[cgroups (Control Groups)](../../Linux/Core/cgroups.md)** для изоляции и учета ресурсов. Демон Docker считывает данные из псевдофайловой системы `cgroupfs` или через systemd и агрегирует их для пользователя.

#### Cgroups v1 (Устаревающий стандарт)

Метрики разделены по отдельным иерархиям контроллеров:
- **Память:** `/sys/fs/cgroup/memory/docker/<container_id>/memory.stat`
- **CPU:** `/sys/fs/cgroup/cpu/docker/<container_id>/cpuacct.stat`
- **I/O:** `/sys/fs/cgroup/blkio/docker/<container_id>/blkio.throttle.io_service_bytes`

#### Cgroups v2 (Современный стандарт)

Используется единая унифицированная иерархия. Пути зависят от используемого драйвера (`cgroupfs` или `systemd`):
- **Общий путь (cgroupfs):** `/sys/fs/cgroup/docker/<container_id>/`
- **Общий путь (systemd):** `/sys/fs/cgroup/system.slice/docker-<container_id>.scope/`

Docker поддерживает cgroup v2 начиная с версии 20.10. Для работы требуется:
- containerd: v1.4 или выше
- runc: v1.0.0-rc91 или выше
- Ядро Linux: v4.15 или выше (v5.2+ рекомендуется)

**Ключевые файлы метрик v2:**
- `memory.current`: Текущее потребление памяти (включая кеш).
- `memory.events`: Счетчик событий (low, high, max, oom, oom_kill). Позволяет подтвердить факт OOM без чтения `dmesg`.
- `cpu.stat`: Статистика использования CPU, включая `nr_throttled` и `throttled_usec`.
- `io.stat`: Статистика ввода-вывода (rbytes, wbytes, riops, wiops).
- `cpu.pressure`, `memory.pressure`, `io.pressure`: **[PSI (Pressure Stall Information)](../../Linux/Core/kernel/psi.md)** — показывают процент времени задержки из-за нехватки ресурса.

### Учет памяти: CLI против API

Docker CLI и API возвращают разные значения потребления памяти:

- **CLI (`docker stats`):** вычитает кеш из общего потребления. На cgroup v1 используется `total_inactive_file` из `memory.stat`. На cgroup v2 используется `inactive_file`. Это значение приблизительно соответствует working set и более полезно для алертинга, так как отражает память, которую контейнер может отдать под pressure.
- **API (`/containers/<id>/stats`):** возвращает сырые значения `memory.usage` и `stats` без вычитания кеша. Клиенты должны применить ту же логику самостоятельно, если нужен working set.

Различие важно при интеграции с внешними системами мониторинга. cAdvisor и `containerd/CRI` используют ту же логику вычитания кеша, что и Docker CLI.

### Сетевые метрики

Docker собирает статистику сети напрямую из виртуальных интерфейсов внутри сетевого пространства имен (network namespace) контейнера. Метрики включают входящий/исходящий трафик (Rx/Tx) и ошибки. При использовании `network: host` нативные метрики сети контейнера будут идентичны метрикам хоста.

**Потери и ошибки пакетов:** `docker stats` показывает только объём трафика (поле `NetIO`). Для диагностики потерь и ошибок читайте счётчики интерфейса напрямую:

```bash
# Счётчики veth-интерфейса контейнера (errors, dropped, overrun)
ip -s link show <veth_name>
# → RX: bytes  packets  errors  dropped  overrun  mcast
# → TX: bytes  packets  errors  dropped  carrier  collsns
```

Постоянный рост `dropped` на veth указывает на переполнение буфера между хостом и контейнером — типично при всплесках трафика или малом `txqueuelen`.

**Conntrack (отслеживание соединений):** каждое соединение контейнера занимает запись в таблице conntrack хоста. Исчерпание таблицы (`nf_conntrack: table full`) приводит к дропу новых соединений всех контейнеров хоста:

```bash
# Текущая загрузка таблицы conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 262144 (count) / 262144 (max) — таблица заполнена, новые соединения дропаются

# Статистика дропов conntrack
conntrack -S | grep drop
```

Алерт: `nf_conntrack_count / nf_conntrack_max > 0.8`. Увеличение таблицы: `sysctl -w net.netfilter.nf_conntrack_max=524288` (и в `/etc/sysctl.conf` для persistency).

### Docker API

Все нативные инструменты (`stats`, `df`) работают через Docker Engine API. Вызов эндпоинта `/containers/<id>/stats` возвращает подробный JSON-объект с сырыми данными: `cpu_stats` (включая `cpu_usage.percpu_usage`, `system_cpu_usage`, `throttling_data`), `memory_stats` (`usage`, `stats` с разбивкой по типам памяти), `networks` (Rx/Tx по интерфейсам), `blkio_stats`, `pids_stats`.

*Примечание:* Постоянный опрос `/stats` для большого количества контейнеров (>100) может создавать заметную нагрузку на Docker-демон. Параметр `stream=false` возвращает однократный снимок и закрывает соединение — используйте его для периодического сбора вместо постоянного streaming.

## Предварительные требования

- **Docker Engine:** 20.10 или выше (рекомендуется 24.0+)
- **Ядро Linux:** cgroup v2 требует ядро v4.15+ (v5.2+ рекомендуется)
- **Права доступа:** для просмотра cgroup-файлов требуется root или членство в группе `docker`
- **Среда:** Linux (нативные метрики на Windows/macOS ограничены Docker Desktop и не предоставляют доступа к cgroups)

## Практические сценарии

### Мониторинг в реальном времени: docker stats

Команда `docker stats` выводит динамический поток данных о потреблении ресурсов.

```bash
# Базовый мониторинг всех запущенных контейнеров
docker stats

# Однократный вывод (удобно для скриптов)
docker stats --no-stream

# Вывод в формате JSON
docker stats --no-stream --format json
```

**Расширенное форматирование:**
Позволяет извлекать конкретные числовые значения для парсинга.

```bash
# Вывод CPU, памяти и лимита в удобном виде
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
# → NAME       CPU %     MEM USAGE / LIMIT
# → web_app    0.15%     120MiB / 2GiB
```

Доступные поля для шаблона:
- `.Name` — имя контейнера
- `.ID` — короткий ID контейнера
- `.CPUPerc` — процент использования CPU
- `.MemUsage` — использование памяти / лимит
- `.MemPerc` — процент использования памяти
- `.NetIO` — сетевой ввод/вывод
- `.BlockIO` — блочный ввод/вывод
- `.PIDs` — количество процессов

### Включение встроенного экспортера Prometheus

Docker Engine имеет встроенный эндпоинт метрик в формате Prometheus. Начиная с Docker 20.10, параметр `metrics-addr` не требует включения `experimental`.

**Настройка (`/etc/docker/daemon.json`):**

```json
{
  "metrics-addr": "127.0.0.1:9323"
}
```

*   `metrics-addr`: адрес прослушивания. Для безопасности используйте `127.0.0.1` или закрытую сеть.

**Перезапуск и проверка:**
```bash
sudo systemctl restart docker
curl -s http://localhost:9323/metrics | grep engine_daemon
# → HELP engine_daemon_engine_info ...
# → TYPE engine_daemon_engine_info gauge
```

*Примечание:* В более старых конфигурациях может встречаться `"experimental": true`. Начиная с Docker 20.10, `metrics-addr` работает без этого флага.

### Диагностика троттлинга (Throttling)

Если контейнер работает медленно, необходимо проверить, не ограничивает ли его ядро из-за превышения лимитов.

1. **CPU Throttling:**
Проверьте файл `cpu.stat` внутри cgroup контейнера.
```bash
cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/cpu.stat | grep throttled
# → nr_throttled 50      # Количество периодов, когда CPU был ограничен
# → throttled_usec 1000  # Суммарное время ограничения в микросекундах
```

Высокое значение `nr_throttled` при низком среднем CPU% указывает на то, что контейнеру не хватает квоты CPU, и он сталкивается с задержками в часы пик.

2. **I/O Throttling:**
Для cgroup v2 статистика видна в `io.stat`. Если значения `riops`/`wiops` стабильно держатся на уровне установленных в `docker run --device-write-iops`, значит, достигнут предел.
Подробнее: **[Сценарии диагностики I/O](../../Linux/Diagnostics/Performance/DiskIO/troubleshooting_scenarios.md)**.

### PSI-метрики: PromQL и алерты

PSI-файлы (`cpu.pressure`, `memory.pressure`, `io.pressure`) доступны в cgroup v2 при ядре 4.20+ с `CONFIG_PSI=y` (некоторые дистрибутивы выключают PSI по умолчанию — включается параметром `psi=1` в командной строке ядра). Формат строки: `some avg10=0.50 avg60=0.20 avg300=0.10 total=123456789` — `some` (доля времени, когда хотя бы одна задача ждала) и `full` (все задачи ждали); `avg10/60/300` — проценты за 10с/1м/5м, `total` — суммарное время в микросекундах.

В Prometheus PSI экспортируется как счётчики времени ожидания: node_exporter — `node_pressure_{cpu,memory,io}_waiting_seconds_total` (хост), cAdvisor — `container_pressure_{cpu,memory,io}_waiting_seconds_total` (контейнер, требуется cgroup v2). Так как это counters, доля времени простоя за окно считается через `rate()`:

```promql
# Доля времени, когда задачи ждали CPU, за последние 5 минут (хост)
rate(node_pressure_cpu_waiting_seconds_total[5m])

# Доля времени ожидания памяти контейнером (cAdvisor)
rate(container_pressure_memory_waiting_seconds_total{container_name!=""}[5m])

# Алерт: memory pressure — задачи ждали память >10% времени за 5 минут
rate(node_pressure_memory_waiting_seconds_total[5m]) > 0.1

# Алерт: IO congestion (диск — bottleneck)
rate(node_pressure_io_waiting_seconds_total[5m]) > 0.1
```

**Интерпретация:** PSI > 5–10% на окне 5 минут — ресурс является bottleneck; утилизация при этом может быть невысокой (например, память занята кешем, но `some`-доля растёт из-за reclaim). PSI ловит деградацию раньше, чем utilization-метрики. Для контейнеров без cgroup v2 PSI недоступны — используйте `nr_throttled` (CPU) и `memory.events` (память).

### Rootless Docker

В rootless-режиме демон и контейнеры работают от непривилегированного пользователя внутри user namespace. Особенности мониторинга:

- **Конфигурация:** `daemon.json` расположен в `~/.config/docker/daemon.json` (не в `/etc/docker/daemon.json`). Параметр `metrics-addr` задаётся там же.
- **Управление:** демон — systemd user-сервис (`systemctl --user start docker`), сокет `/run/user/<uid>/docker.sock` (`DOCKER_HOST=unix:///run/user/1000/docker.sock`).
- **cgroups:** иерархия cgroups отличается от rootful. Для прямого чтения метрик уточняйте путь контейнера через `/proc/<pid>/cgroup` или `docker inspect --format '{{.Id}}'`.
- **`docker stats`:** работает штатно, но лимиты памяти отражают user-slice, а не хост.
- **PSI:** доступны только при cgroup v2 и ядре с `CONFIG_PSI`; чтение `pressure`-файлов может быть ограничено правами.
- **Требования:** `newuidmap`/`newgidmap` (пакет `uidmap`), `/etc/subuid` и `/etc/subgid` с ≥65536 подчинённых UID/GID.

**Scrape-конфиг Prometheus для rootless-демона** (сокет лежит в user namespace, поэтому Prometheus должен работать от того же пользователя или иметь доступ к `/run/user/<uid>`):

```yaml
scrape_configs:
  - job_name: 'docker-engine-rootless'
    static_configs:
      - targets: ['rootless-host:9323']  # metrics-addr из ~/.config/docker/daemon.json
```

```bash
# Проверка доступности сокета с хоста мониторинга
DOCKER_HOST=unix:///run/user/1000/docker.sock docker ps
# → список контейнеров rootless-демона
```

Подробнее: [Rootless mode](https://docs.docker.com/engine/security/rootless/).

### Мониторинг событий: docker events

Позволяет отслеживать жизненный цикл контейнеров и критические ошибки в реальном времени.

```bash
# Отслеживание OOM событий и завершения контейнеров
docker events --filter 'event=oom' --filter 'event=die'
# → 2024-05-20T... container oom a1b2c3... (image=nginx, name=web_app)
```

**Интеграция с Alertmanager (webhook):** поток событий можно преобразовывать в алерты скриптом — полезно, когда Prometheus/cAdvisor не развёрнуты:

```bash
#!/bin/sh
# /usr/local/bin/docker-events-to-webhook.sh
docker events --filter 'event=oom' --filter 'event=die' --format '{{.Time}} {{.Type}} {{.Action}} {{.Actor.Attributes.name}}' |
while read ts type action name; do
  curl -s -X POST http://alertmanager:9093/api/v2/alerts \
    -H 'Content-Type: application/json' \
    -d "[{\"labels\":{\"alertname\":\"DockerContainer${action}\",\"container\":\"$name\",\"severity\":\"warning\"},\"annotations\":{\"summary\":\"Container $name: $action at $ts\"}}"
done
```

*Примечание:* буфер событий демона ограничен — для исторического окна используйте `--since`. Для production-алертинга на OOM надёжнее метрика cAdvisor `container_oom_events_total` (см. [Деплой cAdvisor](./docker_cadvisor_deployment.md)).

### Анализ дискового пространства: docker system df

Команда оценивает использование места на диске объектами Docker.

```bash
docker system df -v
```

- **RECLAIMABLE**: Объем, который можно освободить.
  - **Images**: "Dangling" образы (без тегов и зависимых контейнеров).
  - **Containers**: Остановленные контейнеры.
  - **Local Volumes**: Тома, не подключенные ни к одному запущенному или остановленному контейнеру.

*Примечание:* `docker system df` показывает использование места объектами Docker, но не отслеживает заполнение файловой системы хоста. Для алертов на заполнение диска (пороги SRE: `/var/lib/docker` >80%, IUse% >80%, Reclaimable >50%) и диагностики overlay2/overlayfs используйте **[Анализ использования диска](../Docker_fs/disk_usage_analysis.md)**.

### Сбор метрик без Prometheus

Для хостов без Prometheus или для быстрого аудита используйте периодический сбор через cron:

```bash
# Скрипт /usr/local/bin/docker-metrics-snapshot.sh
#!/bin/sh
docker stats --no-stream --format json >> /var/log/docker-stats.jsonl
```

```bash
# Каждую минуту — /etc/cron.d/docker-stats
* * * * * root /usr/local/bin/docker-metrics-snapshot.sh
```

Формат JSONL позволяет потом анализировать историю через `jq`:
```bash
jq -s 'group_by(.Name) | map({name: .[0].Name, max_cpu: (map(.CPUPerc | rtrimstr("%") | tonumber) | max)})' /var/log/docker-stats.jsonl
```

Ограничения: нет алертов в реальном времени, растёт файл лога (настройте ротацию через logrotate). Для production-алертинга используйте Prometheus или Docker Engine Metrics (порт 9323).

### Прямой опрос Docker Engine API

Для кастомных коллекторов и быстрого аудита — опрос эндпоинта `/containers/<id>/stats` напрямую через curl:

```bash
# Однократный снимок (stream=false — соединение закрывается после ответа)
curl -s --unix-socket /var/run/docker.sock \
  http://localhost/containers/my_app/stats?stream=false | jq '.cpu_stats, .memory_stats'

# Структура ответа (ключевые поля)
# → cpu_stats: { cpu_usage: { total_usage, percpu_usage }, system_cpu_usage,
# →              throttling_data: { periods, throttled_periods, throttled_time } }
# → memory_stats: { usage, limit, stats: { inactive_file, total_inactive_file, ... } }
# → networks: { eth0: { rx_bytes, tx_bytes, rx_dropped, tx_errors } }
# → pids_stats: { current }

# Список ID контейнеров для пакетного опроса
docker ps -q | while read id; do
  curl -s --unix-socket /var/run/docker.sock \
    "http://localhost/containers/$id/stats?stream=false" | jq -c '{id, cpu: .cpu_stats.cpu_usage.total_usage}'
done
```

**Параметры:**
- `stream=false` — однократный снимок (для скриптов и cron); без параметра — бесконечный поток
- `--unix-socket` — доступ через Unix socket (без TCP-порта API)
- `throttling_data` в ответе — то же, что `nr_throttled`/`throttled_usec` в `cpu.stat` cgroup

**Ограничения:** опрос >100 контейнеров нагружает демон — для массового сбора используйте cAdvisor. Сырой `memory_stats.usage` не вычитает кеш — для working set вычитайте `memory_stats.stats.inactive_file` (v2) самостоятельно.

### Просмотр метрик cgroups напрямую

Для глубокой диагностики можно читать файлы cgroups напрямую:

```bash
# Определение cgroup контейнера
CONTAINER_ID=$(docker inspect --format '{{.Id}}' my_container)

# Память (cgroup v2, systemd driver)
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.current
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.events

# CPU (cgroup v2, systemd driver)
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/cpu.stat

# I/O (cgroup v2, systemd driver)
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/io.stat

# PIDs
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/pids.current
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/pids.max

# Проверка версии cgroups
stat -f /sys/fs/cgroup | head -5
# → cgroup2fs (v2) или tmpfs (v1)
```

### Валидация сбоя OOM

```bash
# Проверка счетчика OOM событий
cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/memory.events | grep oom_kill
# → oom_kill 1

# Проверка кода завершения контейнера
docker inspect --format='{{.State.ExitCode}}' <container_name>
# → 137 (128 + 9 = SIGKILL, типично для OOM)

# Журналы ядра
dmesg | tail -20 | grep -i "oom\|killed"
```

### Мониторинг Windows-контейнеров

cAdvisor требует cgroups ядра Linux — на Windows-хостах он не предоставляет доступа к cgroups. Что доступно:

- **`docker stats`** — работает штатно (данные через Docker Engine API).
- **Docker Engine Metrics (9323)** — работает, `metrics-addr` задаётся в Docker Desktop: Settings → Docker Engine.
- **Метрики хоста Windows** — собираются отдельным Windows-экспортёром Prometheus (не cAdvisor/Node Exporter).
- **Docker Desktop (Mac/Windows)** — метрики доступны внутри VM (Hyper-V/WSL2); для анализа на хосте используйте `docker run --privileged -v /:/host alpine ...` с монтированием хостовой ФС VM.

### eBPF-диагностика контейнеров

Для глубокой диагностики производительности (аналоги `top`, `trace`, `sockettrace` на уровне контейнеров) без инструментации приложения — Inspektor Gadget. Работает с контейнерами Docker независимо от Kubernetes (обогащает данные метаданными контейнера автоматически):

```bash
# Установка ig (Linux)
IG_VERSION=$(curl -s https://api.github.com/repos/inspektor-gadget/inspektor-gadget/releases/latest | jq -r .tag_name)
curl -sL https://github.com/inspektor-gadget/inspektor-gadget/releases/download/${IG_VERSION}/ig-linux-amd64-${IG_VERSION}.tar.gz | sudo tar -C /usr/local/bin -xzf - ig

# Топ файловой активности (аналог top по I/O)
sudo ig run top_file:latest

# Трассировка открытия файлов
sudo ig run trace_open:latest

# Трассировка exec (запуск процессов)
sudo ig run trace_exec:latest

# Снапшот сокетов (TCP/UDP)
sudo ig run snapshot_socket:latest

# Запуск в контейнере (без установки на хост)
docker run -ti --rm --privileged -v /:/host --pid=host ghcr.io/inspektor-gadget/ig:latest run trace_open:latest
```

Требования: ядро 4.15+ (рекомендуется 5.x), root или CAP_BPF/CAP_PERFMON. В Kubernetes запускается как DaemonSet (`kubectl gadget deploy`). Подробнее: [Runtime Monitoring](../Docker_security/runtime_monitoring.md) (eBPF-security: Falco, Tetragon) и [Observability in Containers](../../Concepts/Observability_and_Monitoring/observability_in_containers.md). Альтернативы для хоста: `bpftrace`, `perf` (см. [Диагностика производительности контейнеров](../../Linux/Diagnostics/Performance/container_performance_diagnostics.md)).

### Чем мониторить Docker: сравнение подходов

| Инструмент | Что собирает | Модель | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **`docker stats`** | CPU/RAM/NetIO/BlkIO/PIDs | CLI-снимок | Ручная диагностика, cron-аудит |
| **Engine Metrics (9323)** | Состояния контейнеров, health-check'и, таймеры операций | Prometheus pull | Мониторинг здоровья демона |
| **cAdvisor (8080)** | Per-container CPU/RAM/NetIO/Disk I/O/PSI/OOM | Prometheus pull | Стандарт production-мониторинга |
| **Node Exporter (9100)** | Метрики хоста (диски, сеть, ОС) | Prometheus pull | Всегда, вместе с cAdvisor |
| **OTel dockerstats receiver** | CPU/memory/network/blkio контейнеров | OTLP push/pull | OTel-стек вместо Prometheus (alpha) |
| **OTel hostmetrics receiver** | CPU/disk/load/filesystem/memory/network хоста | OTLP | OTel-стек, замена Node Exporter |
| **Netdata** | Хост + контейнеры, секундная гранулярность | Собственный агент + Prometheus-совместимый эндпоинт | Real-time диагностика без настройки дашбордов |
| **Glances** | Хост (TUI/WebUI) | TUI/`-w` WebUI | Быстрый взгляд с хоста, не для алертинга |
| **Collectd/Graphite** | Хост | Push в Whisper | Legacy-стек (мигрируйте на Prometheus/OTel) |

**Рекомендация для production:** cAdvisor + Node Exporter → Prometheus → Grafana; Engine Metrics 9323 — дополнительно для здоровья демона. Netdata — как быстрый диагностический слой. Glances/Collectd — не для алертинга.

### Мониторинг CI-раннеров

CI-раннеры с Docker (GitLab Runner, Jenkins agents, GitHub Actions self-hosted) имеют специфику: сборки оставляют stopped-контейнеры, dangling-образы и растущий build cache.

```bash
# Снимок состояния раннера (по cron, например каждые 5 минут)
docker system df --format json >> /var/log/runner-df.jsonl

# Алерт: reclaimable > 50% от занятого места
docker system df --format '{{.Reclaimable}}'
```

**Практики:**
- `builder.gc` в `daemon.json` — автоочистка build cache BuildKit.
- `docker system prune -f` по cron (вне окон сборок) или `docker builder prune --filter until=24h`.
- Алерт на скорость заполнения `/var/lib/docker` (>80%) и на рост `docker system df` между проверками.
- Метрики сборки (длительность, cache hit rate) — через метрики самого CI-сервера, а не Docker.

## Диагностика и устранение неполадок

### docker stats показывает неожиданно высокое использование памяти

- **Причина:** На cgroup v2 `docker stats` CLI вычитает `inactive_file` из `memory.current`, тогда как API возвращает сырое значение `memory.usage`. Внешние коллекторы, не применяющие эту логику, могут показывать завышенные цифры.
- **Решение:** Используйте `docker stats` для быстрой оценки, но для алертинга через Prometheus полагайтесь на cAdvisor, который применяет ту же логику, что и CLI.

### CPU throttling при низком среднем CPU%

- **Причина:** `docker stats` показывает усредненное значение. Троттлинг происходит в моменты пика и не виден в среднем.
- **Диагностика:**
  ```bash
  cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/cpu.stat
  # → nr_throttled 1500
  # → throttled_usec 2500000
  ```
- **Решение:** Увеличить CPU лимит (`--cpus`), уменьшить `--cpu-quota`, или пересмотреть нагрузку.

### Нет доступа к /sys/fs/cgroup

- **Причина:** Недостаточно прав или неверный путь cgroup.
- **Решение:** Запустите команду от root или добавьте пользователя в группу `docker`. Проверьте монтирование cgroup: `mount | grep cgroup`.

### docker events не показывает события

- **Причина:** Буфер событий имеет ограниченный размер и старые события могут быть удалены.
- **Решение:** Используйте флаг `--since` для ограничения временного окна:
  ```bash
  docker events --since 2024-01-01T00:00:00Z
  ```

### Высокая нагрузка на демон при опросе /stats

- **Причина:** Постоянный опрос `/containers/<id>/stats` для большого количества контейнеров (>100) создает нагрузку.
- **Решение:** Увеличьте интервал опроса, используйте фильтры по labels, или перейдите на cAdvisor для массового сбора метрик.

### memory.events не показывает oom_kill, но контейнер упал

- **Причина:** Контейнер был убит глобальным OOM killer хоста, а не через cgroup limit.
- **Диагностика:** Проверьте `dmesg` и системные логи. Без установленного `memory.max` контейнер не имеет отдельного предела, и глобальный OOM killer выбирает жертву по OOM score.
- **Решение:** Установите `--memory` (или `mem_limit` в Compose) для каждого контейнера, чтобы ограничения применялись на уровне cgroup.

## Лучшие практики

- **Используйте cgroup v2** на новых хостах. Он обеспечивает единую иерархию, PSI метрики и более предсказуемое поведение.
- **Не полагайтесь только на `docker stats`** в production. Он не хранит историю и не подходит для алертинга. Используйте **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)** или **[Docker Engine Metrics](./docker_prometheus_integration.md)** для долгосрочного мониторинга.
- **Мониторьте `nr_throttled` и `throttled_usec`** вместо среднего CPU% для диагностики производительности. Среднее значение за минуту может скрывать периодические троттлы, влияющие на p99 латентность.
- **Используйте `memory.events` → `oom_kill`** для подтверждения OOM без `dmesg`. Это единственный источник, где факт kill записан durable на хосте.
- **Мониторьте PSI метрики** (`cpu.pressure`, `memory.pressure`, `io.pressure`). Они показывают процент времени задержки, а не просто utilisation, что позволяет выявлять bottleneck раньше.
- **Для массового сбора метрик** (>100 контейнеров на хост) используйте cAdvisor вместо постоянного опроса Docker API.
- **Настройте лимиты ресурсов** для каждого контейнера. Без лимитов `memory.max` неактивен, `docker stats` показывает лимит хоста, и глобальный OOM killer может убить не тот контейнер, который вызвал нехватку памяти.
- **Используйте `docker system df`** регулярно для контроля дискового пространства, особенно на CI раннерах и хостах с большим количеством ephemeral контейнеров.
- **На CI-раннерах** мониторьте не только диск, но и скорость заполнения: сборки оставляют stopped контейнеры и dangling образы. Настройте автоочистку (`builder.gc` в `daemon.json`, регулярный `docker system prune -f`) и алерт на рост `docker system df` между проверками. Подробнее: сценарий «Мониторинг CI-раннеров» выше.

## Дополнительная информация

Нативные метрики идеальны для ручной отладки, но для промышленной эксплуатации следует использовать внешние коллекторы.

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — встроенный экспортер метрик демона (порт 9323).
- **[cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md)** — стандарт для глубокого сбора метрик контейнеров (включая детали cgroup).
- **[cAdvisor: развертывание и сбор метрик](./docker_cadvisor_deployment.md)** — деплой cAdvisor, конфигурация сбора и интеграция с Prometheus.
- **[Grafana для Docker-метрик](./docker_grafana_dashboards.md)** — дашборды, провиженинг, алерты, корреляция метрик с логами.
- **[Docker метрики: вопросы на собеседованиях](./docker_metrics_interview_qa.md)** — краткие ответы на типичные вопросы SRE-собеседований.
- **[OpenTelemetry: Collector в не-Kubernetes средах](../../OpenTelemetry/collector_without_kubernetes.md)** — OTel Collector на bare-metal и в Docker Compose (dockerstats/hostmetrics receivers).
- **[Vector](../../Vector/vector_overview.md)** — высокопроизводительный агент для сбора и маршрутизации метрик.
- **[Контрольные группы (cgroups)](../../Linux/Core/cgroups.md)** — теоретическая база механизмов ограничения ресурсов.
- **[Pressure Stall Information (PSI)](../../Linux/Core/kernel/psi.md)** — глубокая диагностика задержек на уровне ядра.

**Глубокое изучение:**
- **[Resource Tuning](../../Kubernetes/Base/Deployment/deployment_manifest.md)** — оптимизация CPU/memory limits. В Docker: `docker stats` для мониторинга, `docker update` для изменения limits без перезапуска, `nr_throttled` в `cpu.stat` для диагностики дросселирования.
- **[Container Profiling](../../Concepts/continuous_profiling.md)** — профилирование CPU/memory в runtime. В Docker: `pyroscope` как sidecar, `perf` через `--pid=host`, eBPF-based profiling через Parca.
- **[Inspektor Gadget](https://www.inspektor-gadget.io/)** — eBPF-gadget'ы для диагностики контейнеров (сценарий «eBPF-диагностика контейнеров» выше). Дополняет eBPF-security инструменты (Falco, Tetragon) из **[Runtime Monitoring](../Docker_security/runtime_monitoring.md)** профилированием производительности.
