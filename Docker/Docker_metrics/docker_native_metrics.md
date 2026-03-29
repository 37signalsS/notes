# Нативные метрики Docker

## Определения

**Нативные метрики Docker** — встроенные средства для оценки потребления ресурсов контейнерами. Предоставляют базовую статистику без установки внешних инструментов мониторинга. Подходят для оперативной диагностики.

## Основные концепции

### Источник данных: cgroups

Ключевой источник данных — механизм ядра Linux **[контрольные группы (cgroups)](../../Linux/Core/cgroups.md)**. Docker использует `cgroups` для изоляции, ограничения ресурсов и сбора статистики потребления.

Сырые метрики доступны в псевдофайловой системе `cgroupfs`:

- **Память:** `/sys/fs/cgroup/memory/docker/<container_long_id>/memory.stat`
- **CPU:** `/sys/fs/cgroup/cpu/docker/<container_long_id>/cpuacct.stat`
- **I/O:** `/sys/fs/cgroup/blkio/docker/<container_long_id>/blkio.throttle.io_service_bytes`

Эти файлы читает Docker daemon для формирования вывода `docker stats`.

## Практические сценарии

### Динамическая статистика: `docker stats`

Команда `docker stats` предоставляет обновляемый в реальном времени обзор производительности всех запущенных контейнеров.

**Команды:**

- `docker stats` — статистика по CPU, памяти, сети и I/O для всех контейнеров
- `docker stats <id_контейнера>` — статистика для указанного контейнера
- `docker stats --no-stream` — однократный снимок статистики

**Вывод `docker stats`:**

- `CONTAINER ID`, `NAME` — идентификатор и имя контейнера
- `CPU %` — процент использования CPU хоста
- `MEM USAGE / LIMIT` — использованная память и общий лимит
- `MEM %` — процент использования памяти
- `NET I/O` — объем данных, полученных и отправленных по сети
- `BLOCK I/O` — объем данных, прочитанных и записанных на диск
- `PIDS` — количество процессов внутри контейнера

### Анализ использования диска: `docker system df`

```bash
docker system df
```

Пример вывода:

```
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          10        5         1.5GB     1.2GB (79%)
Containers      8         3         500MB     450MB (90%)
Local Volumes   4         2         300MB     150MB (50%)
Build Cache     0         0         0B        0B
```

`RECLAIMABLE` — объем, который можно освободить удалением неиспользуемых объектов (остановленные контейнеры, "висячие" образы).

## Дополнительная информация

`docker stats` и `docker system df` полезны для быстрой диагностики. Для производственного мониторинга рекомендуются специализированные решения для долгосрочного сбора, агрегации и анализа метрик с настройкой оповещений.

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — экспорт метрик Docker в формате Prometheus
- **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)** — сбор метрик напрямую из `cgroups`
- **[Vector](../../Vector/vector_overview.md)**, **[Filebeat](../../ELK_Stack/filebeat_overview.md)** — сбор и отправка метрик в Prometheus, ClickHouse, Elasticsearch
