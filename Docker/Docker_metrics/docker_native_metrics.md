# Нативные метрики Docker

## Определения

**Нативные метрики Docker** — встроенные механизмы Docker Engine для сбора и отображения статистики потребления ресурсов контейнерами и самим демоном. Они позволяют проводить оперативную диагностику производительности (CPU, память, I/O, сеть) без использования внешних систем мониторинга.

## Основные концепции

### Источник данных: cgroups

Docker полагается на механизм ядра Linux **[cgroups (Control Groups)](../../Linux/Core/cgroups.md)** для изоляции и учета ресурсов. Демон Docker считывает данные из псевдофайловой системы `cgroupfs` и агрегирует их для пользователя.

#### Cgroups v1 (Устаревающий стандарт)
Метрики разделены по отдельным иерархиям контроллеров:
- **Память:** `/sys/fs/cgroup/memory/docker/<container_id>/memory.stat`
- **CPU:** `/sys/fs/cgroup/cpu/docker/<container_id>/cpuacct.stat`
- **I/O:** `/sys/fs/cgroup/blkio/docker/<container_id>/blkio.throttle.io_service_bytes`

#### Cgroups v2 (Современный стандарт)
Используется единая унифицированная иерархия. Пути зависят от используемого драйвера (`cgroupfs` или `systemd`):
- **Общий путь (cgroupfs):** `/sys/fs/cgroup/docker/<container_id>/`
- **Общий путь (systemd):** `/sys/fs/cgroup/system.slice/docker-<container_id>.scope/`

**Ключевые файлы метрик v2:**
- `memory.current`: Текущее потребление памяти (включая кеш).
- `memory.events`: Счетчик событий (low, high, max, oom, oom_kill). Позволяет подтвердить факт OOM без чтения `dmesg`.
- `cpu.stat`: Статистика использования CPU, включая `nr_throttled` и `throttled_usec`.
- `io.stat`: Статистика ввода-вывода (rbytes, wbytes, riops, wiops).
- `cpu.pressure`, `memory.pressure`, `io.pressure`: **[PSI (Pressure Stall Information)](../../Linux/Core/kernel/psi.md)** — показывают процент времени задержки из-за нехватки ресурса.

### Сетевые метрики
Docker собирает статистику сети напрямую из виртуальных интерфейсов внутри сетевого пространства имен (network namespace) контейнера. Метрики включают входящий/исходящий трафик (Rx/Tx) и ошибки. При использовании `network: host` нативные метрики сети контейнера будут идентичны метрикам хоста.

### Docker API
Все нативные инструменты (stats, df) работают через Docker Engine API. Вызов эндпоинта `/containers/<id>/stats` возвращает подробный JSON-объект с сырыми данными. 
*Примечание:* Постоянный опрос `/stats` для большого количества контейнеров (>100) может создавать заметную нагрузку на Docker-демон.

## Практические сценарии

### Мониторинг в реальном времени: docker stats

Команда `docker stats` выводит динамический поток данных о потреблении ресурсов.

**Примеры использования:**

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

### Диагностика троттлинга (Throttling)

Если контейнер работает медленно, необходимо проверить, не ограничивает ли его ядро из-за превышения лимитов.

1. **CPU Throttling:**
Проверьте файл `cpu.stat` внутри cgroup контейнера.
```bash
cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/cpu.stat | grep throttled
# → nr_throttled 50      # Количество периодов, когда CPU был ограничен
# → throttled_usec 1000  # Суммарное время ограничения в микросекундах
```

2. **I/O Throttling:**
Для cgroup v2 статистика видна в `io.stat`. Если значения `riops`/`wiops` стабильно держатся на уровне установленных в `docker run --device-write-iops`, значит, достигнут предел.
Подробнее: **[Сценарии диагностики I/O](../../Linux/Diagnostics/Performance/DiskIO/troubleshooting_scenarios.md)**.

### Мониторинг событий: docker events

Позволяет отслеживать жизненный цикл контейнеров и критические ошибки в реальном времени.

```bash
# Отслеживание OOM событий и завершения контейнеров
docker events --filter 'event=oom' --filter 'event=die'
# → 2024-05-20T... container oom a1b2c3... (image=nginx, name=web_app)
```

### Анализ дискового пространства: docker system df

Команда оценивает использование места на диске объектами Docker.

```bash
docker system df -v
```

*   **RECLAIMABLE**: Объем, который можно освободить.
    *   **Images**: "Dangling" образы (без тегов и зависимых контейнеров).
    *   **Containers**: Остановленные контейнеры.
    *   **Local Volumes**: Тома, не подключенные ни к одному запущенному или остановленному контейнеру.

## Дополнительная информация

Нативные метрики идеальны для ручной отладки, но для промышленной эксплуатации следует использовать внешние коллекторы.

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — использование встроенного экспортера (`daemon.json`).
- **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)** — стандарт для глубокого сбора метрик контейнеров (включая детали cgroup).
- **[cAdvisor: развертывание и сбор метрик](./docker_cadvisor_deployment.md)** — деплой cAdvisor, конфигурация сбора и интеграция с Prometheus.
- **[Vector](../../Vector/vector_overview.md)** — высокопроизводительный агент для сбора и маршрутизации метрик.
- **[Контрольные группы (cgroups)](../../Linux/Core/cgroups.md)** — теоретическая база механизмов ограничения ресурсов.
- **[Pressure Stall Information (PSI)](../../Linux/Core/kernel/psi.md)** — глубокая диагностика задержек на уровне ядра.

**Глубокое изучение:**
- **[Resource Tuning](../../Kubernetes/Base/Deployment/deployment_manifest.md)** — оптимизация CPU/memory limits. В Docker: `docker stats` для мониторинга, `docker update` для изменения limits без перезапуска, `nr_throttled` в `cpu.stat` для диагностики дросселирования.
- **[Container Profiling](../../Concepts/continuous_profiling.md)** — профилирование CPU/memory в runtime. В Docker: `pyroscope` как sidecar, `perf` через `--pid=host`, eBPF-based profiling через Parca.
