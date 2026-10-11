# Docker метрики: Вопросы на собеседованиях

**Актуально для:** Docker Engine 20.10–29.8.x (`image_actions` — с 28.0, `health_check_start_duration` — с 23.0, `host_info_functions` — с 20.10, остальные метрики демона — с 18.09); ответы верифицированы по исходникам moby и документации Docker

## Определения

**Задачи этого файла** — краткие, точные ответы на типичные вопросы DevOps/SRE-собеседований по метрикам Docker. Каждый ответ содержит ключевой факт и, где нужно, команду для проверки. Теория и практика — в смежных файлах (ссылки в конце).

## Базовые концепции

### Источники метрик

**Q: Чем `docker stats` отличается от cAdvisor и Docker Engine Metrics (порт 9323)?**
A: `docker stats` — CLI-снимок через API `/containers/<id>/stats`: текущий момент, без истории, для ручной диагностики. cAdvisor (порт 8080) — агент на хосте, per-container метрики CPU/RAM/Network/Disk I/O из cgroups, экспорт в Prometheus. Engine Metrics (9323, `metrics-addr` в `daemon.json`) — встроенный экспортер демона, только пространство `engine_daemon_`: состояния контейнеров, health-check'и, таймеры операций. Per-container метрики он **не** предоставляет. В production используют cAdvisor + Engine Metrics вместе.

**Q: Что экспортирует порт 9323 и чего на нём нет?**
A: Есть: `engine_daemon_engine_info` (версия, graphdriver, ОС), `engine_daemon_engine_cpus_cpus`/`engine_daemon_engine_memory_bytes`, `engine_daemon_container_states_containers{state}` (с 18.09), `engine_daemon_container_actions_seconds_{bucket,sum,count}{action}`, `engine_daemon_health_checks{,_failed}_total`, `engine_daemon_image_actions_seconds_{bucket,sum,count}` (28.0+), `engine_daemon_events{,_subscribers}_total` (с 18.09), `builder_builds_{triggered,failed}_total{reason}`, `logger_log_*_failed_total`, `swarm_*` (при Swarm), `go_*`/`process_*`. Имена формируются по правилу `<name>_<unit>` библиотеки docker/go-metrics — поэтому с суффиксами `_total`, `_bytes`, `_containers`. Нет: per-container CPU/RAM/NetIO (только cAdvisor), метрики BuildKit-даемона и containerd (собственные эндпоинты), OOM-события в реальном времени (`docker events --filter event=oom` или cAdvisor `container_oom_events_total`).

**Q: Почему `docker stats` не подходит для алертинга в production?**
A: Нет истории (только снимок), усреднение скрывает пики троттлинга, а постоянный опрос `/stats` для >100 контейнеров создаёт заметную нагрузку на демон. Для алертинга — cAdvisor или Engine Metrics в Prometheus.

**Q: Что такое `housekeeping_interval` cAdvisor?**
A: Интервал сбора метрических снимков (по умолчанию 1s). На хостах с >100 контейнерами увеличивают до 10–15s — иначе сам cAdvisor становится источником нагрузки на CPU.

### Память

**Q: Что такое working set и почему `docker stats` вычитает кеш?**
A: CLI вычитает `inactive_file` (cgroup v2) или `total_inactive_file` (v1) из `memory.current` — получает working set: память, которую контейнер может отдать под pressure. Это значение учитывает OOM Killer и использует cAdvisor. API `/containers/<id>/stats` возвращает сырой `memory.usage` без вычитания — внешние коллекторы должны применять ту же логику самостоятельно.

**Q: Как подтвердить OOM kill контейнера?**
A: Три источника: (1) `memory.events` → `oom_kill` в cgroup v2 — durable-счётчик, не требует `dmesg`; (2) `docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' <c>` → `137 true` (137 = 128+9, SIGKILL); (3) `dmesg | grep -i oom`. cAdvisor фиксирует OOM только при смонтированном `/dev/kmsg`.

**Q: Как понять, кто убил контейнер — cgroup-лимит или глобальный OOM killer хоста?**
A: `oom_kill > 0` в `memory.events` → сработал лимит cgroup контейнера. `oom_kill = 0`, но ExitCode 137 и `OOMKilled true` → глобальный OOM killer хоста выбрал жертву по OOM score. Причина второго случая: контейнеру не задан `--memory`, поэтому cgroup-лимит неактивен. Лечение: задать `--memory` каждому контейнеру.

### CPU

**Q: Как обнаружить CPU throttling и почему `nr_throttled` важнее среднего CPU%?**
A: В `cpu.stat` cgroup v2: `nr_throttled` (число периодов ограничения) и `throttled_usec` (суммарное время). `docker stats` показывает усреднённый процент — пики троттлинга скрыты. Высокое `nr_throttled` при низком среднем CPU% означает нехватку квоты в пиках и деградацию p99-латентности. В cAdvisor: `rate(container_cpu_cfs_throttled_seconds_total[5m]) / rate(container_cpu_usage_seconds_total[5m]) > 0.25` — сигнал.

**Q: Что такое PSI и зачем он нужен?**
A: Pressure Stall Information — метрики ядра (`cpu.pressure`, `memory.pressure`, `io.pressure` в cgroup v2), показывающие процент времени, в течение которого задачи ждали доступа к ресурсу. Требуется ядро с `CONFIG_PSI`. Позволяет выявлять bottleneck раньше, чем utilisation-метрики.

### cgroups

**Q: Чем cgroup v1 отличается от v2 в части метрик?**
A: v1: отдельные иерархии контроллеров (`/sys/fs/cgroup/memory/docker/<id>/memory.stat`, `/sys/fs/cgroup/cpu/docker/<id>/cpuacct.stat`). v2: единая иерархия (`/sys/fs/cgroup/system.slice/docker-<id>.scope/` для systemd-драйвера), появляются `memory.events` и PSI. Docker поддерживает v2 с 20.10 (ядро 4.15+, containerd 1.4+, runc 1.0.0-rc91+). Проверка: `stat -f /sys/fs/cgroup` → `cgroup2fs` (v2) или `tmpfs` (v1).

### Prometheus и сбор

**Q: Как снизить кардинальность Docker-метрик в Prometheus?**
A: `metric_relabel_configs`: drop метрик с пустым `container_name`, drop инфраструктурных сетей (`bridge|host|none|container`), keep только нужных метрик (`container_(cpu|memory|network|blkio)_.*`). Снижает объём TSDB на 40–60%. Дополнительно у cAdvisor: `--docker_only=true` и `--disable_metrics=advtcp,udp,sched,hugetlb`.

**Q: Когда `docker_sd_config`, а когда `static_configs`?**
A: `static_configs` — фиксированное число хостов (типично для Engine Metrics 9323). `docker_sd_config` — динамическое обнаружение контейнеров через Docker socket (требует доступа к `/var/run/docker.sock`; фильтр по лейблу `prometheus_scrape=true`). В Swarm — `dockerswarm_sd_config` с ролями `nodes`/`services`/`tasks`/`networks`. В Prometheus 3.x порт не угадывается автоматически — указывайте его явно в `__address__`.

**Q: Как оценить объём метрик для Docker-хоста (capacity planning)?**
A: cAdvisor генерирует порядка 50–100 серий на контейнер (зависит от включённых подсистем). Формулы Prometheus: `Disk (GB) = active_series × bytes_per_sample × samples_per_day × retention_days / 10^9`; `RAM (MB) = 2000 + active_series × 8`. Пример: 200 контейнеров × 80 серий = 16K серий → ~13 ГБ диска при `scrape_interval: 15s` и retention 15d. Полные формулы: [Capacity Planning для Prometheus](../../Prometheus/installation/capacity_planning.md).

**Q: Какие метрики собирает OTel dockerstats receiver?**
A: `container.cpu.usage.total`, `container.cpu.utilization`, `container.memory.*`, `container.network.io.*`, `container.blkio.*` — через API `/containers/<id>/stats` (Docker API 1.25+). Настройки: `endpoint: unix:///var/run/docker.sock`, `collection_interval: 10s`, `container_labels_to_metric_labels` для обогащения лейблами. Альтернатива cAdvisor в OTel-стеке; стабильность метрик — alpha.

### Эксплуатация

**Q: Как мониторить Docker без Prometheus?**
A: cron + `docker stats --no-stream --format json >> /var/log/docker-stats.jsonl` (с logrotate), анализ истории через `jq`. Ограничения: нет алертов в реальном времени, растёт лог. Для демона — встроенный экспортер 9323.

**Q: Как диагностировать исчерпание таблицы conntrack?**
A: `cat /proc/sys/net/netfilter/nf_conntrack_count` и `nf_conntrack_max`. Алерт при отношении >0.8. Симптом: дроп новых соединений **всех** контейнеров хоста, в `dmesg`: `nf_conntrack: table full, dropping packet`. Лечение: `sysctl -w net.netfilter.nf_conntrack_max=524288` + запись в `/etc/sysctl.conf`.

**Q: Что такое `docker events` и как его использовать в мониторинге?**
A: Поток событий жизненного цикла контейнеров (`oom`, `die`, `start`, `stop`). `docker events --filter 'event=oom' --filter 'event=die'`. Буфер событий ограничен — для исторического окна используйте `--since`. Для алертинга — скрипт с отправкой в webhook/Alertmanager или метрика cAdvisor `container_oom_events_total`.

**Q: Особенности мониторинга rootless Docker?**
A: `daemon.json` в `~/.config/docker/daemon.json`; демон — systemd user-сервис (`systemctl --user`); сокет `/run/user/<uid>/docker.sock` (`DOCKER_HOST=unix:///run/user/1000/docker.sock`); пути cgroups отличаются от rootful — уточняйте через `/proc/<pid>/cgroup`; PSI доступны только при cgroup v2 и ядре с `CONFIG_PSI`.

**Q: Что доступно из метрик в Windows-контейнерах?**
A: cgroups в Windows нет — cAdvisor не предоставляет доступа к cgroups хоста на Windows/macOS. Работают `docker stats` (через API) и Engine Metrics 9323. Метрики хоста Windows собираются отдельным Windows-экспортёром, а не cAdvisor.

**Q: Как мониторить CI-раннеры с Docker?**
A: `docker system df -v` по cron + алерт на рост reclaimable и на скорость заполнения `/var/lib/docker` (>80%); `builder.gc` в `daemon.json`; регулярный `docker system prune` по cron. Сборки оставляют stopped-контейнеры и dangling-образы — место растёт быстрее, чем на обычных хостах.

## Дополнительная информация

### Ссылки на смежные темы

* **[Нативные метрики Docker](./docker_native_metrics.md)** — `docker stats`, PSI, чтение cgroups, диагностика троттлинга.
* **[Справочник метрик Docker Engine](./docker_engine_metrics_reference.md)** — полный перечень метрик порта 9323 с версиями.
* **[Деплой cAdvisor](./docker_cadvisor_deployment.md)** — per-container метрики, `docker_only`, `housekeeping_interval`.
* **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — `docker_sd_config`, `metric_relabel_configs`, кардинальность.
* **[Grafana для Docker-метрик](./docker_grafana_dashboards.md)** — дашборды, провиженинг, алерты, корреляция с логами.
* **[cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md)** — SSoT: метрики, PromQL, дашборды, правила алертинга.
* **[Capacity Planning для Prometheus](../../Prometheus/installation/capacity_planning.md)** — формулы RAM/Disk/CPU.
* **[Docker daemon.json — полный референс](../docker_daemon_config.md)** — `metrics-addr`, `log-opts`, `builder.gc`.
* **[Docker логирование: вопросы на собеседованиях](../Docker_logs/docker_logging_interview_qa.md)** — смежная тема: лог-драйверы и диагностика.
