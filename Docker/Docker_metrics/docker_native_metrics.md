# Нативные метрики Docker

## Определения

**Нативные метрики Docker** — встроенные механизмы Docker Engine для сбора и отображения статистики потребления ресурсов контейнерами и самим демоном. Они позволяют проводить оперативную диагностику производительности (CPU, память, I/O, сеть) без использования внешних систем мониторинга.

## Основные концепции

### Источник данных: cgroups

Docker полагается на механизм ядра Linux **[cgroups (Control Groups)](../../Linux/Core/cgroups.md)** для изоляции и учета ресурсов. Демон Docker считывает данные из псевдофайловой системы `cgroupfs` и агрегирует их для пользователя.

Структура путей зависит от версии cgroups, используемой в операционной системе:

#### Cgroups v1 (Устаревающий стандарт)
Метрики разделены по отдельным иерархиям контроллеров:
- **Память:** `/sys/fs/cgroup/memory/docker/<container_id>/memory.stat`
- **CPU:** `/sys/fs/cgroup/cpu/docker/<container_id>/cpuacct.stat`
- **I/O:** `/sys/fs/cgroup/blkio/docker/<container_id>/blkio.throttle.io_service_bytes`

#### Cgroups v2 (Современный стандарт)
Используется единая унифицированная иерархия. Пути зависят от используемого драйвера (`cgroupfs` или `systemd`):
- **Общий путь (cgroupfs):** `/sys/fs/cgroup/docker/<container_id>/`
- **Общий путь (systemd):** `/sys/fs/cgroup/system.slice/docker-<container_id>.scope/`
- **Файлы метрик:** `memory.current` (текущая память), `cpu.stat` (статистика CPU), `io.stat` (статистика ввода-вывода).

### Docker API
Все нативные инструменты (stats, df) работают через Docker Engine API. Вызов эндпоинта `/containers/<id>/stats` возвращает подробный JSON-объект с сырыми данными, которые затем форматируются CLI-клиентом.

## Практические сценарии

### Мониторинг в реальном времени: docker stats

Команда `docker stats` (или её полный эквивалент `docker container stats`) выводит динамический поток данных о потреблении ресурсов.

**Примеры использования:**

```bash
# Базовый мониторинг всех запущенных контейнеров
docker stats

# Вывод статистики для конкретных контейнеров
docker stats nginx_proxy db_main

# Однократный вывод (удобно для скриптов)
docker stats --no-stream
# → CONTAINER ID   NAME          CPU %     MEM USAGE / LIMIT     MEM %     NET I/O          BLOCK I/O   PIDS
# → a1b2c3d4e5f6   web_app       0.15%     120MiB / 2GiB         5.86%     1.2kB / 0B       0B / 0B     8
```

**Расширенное форматирование:**
Использование флага `--format` позволяет выводить данные в кастомном виде или в JSON для последующей обработки.

```bash
# Вывод только имени и процента CPU в виде таблицы
docker stats --format "table {{.Name}}\t{{.CPUPerc}}"

# Вывод в формате JSON (одна строка на контейнер)
docker stats --no-stream --format json
# → {"BlockIO":"0B / 0B","CPUPerc":"0.00%","Container":"a1b2c3...","ID":"a1b2c3...","MemPerc":"0.50%",...}
```

### Анализ дискового пространства: docker system df

Команда позволяет оценить, сколько места занимают образы, контейнеры, тома и кеш сборки.

```bash
# Общая сводка
docker system df
# → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# → Images          15        6         2.4GB     1.1GB (45%)
# → Containers      10        2         150MB     100MB (66%)
# → Local Volumes   5         3         1.2GB     500MB (41%)
# → Build Cache     22        0         4.5GB     4.5GB

# Подробный вывод по каждому объекту
docker system df -v
```

*   **RECLAIMABLE** — объем данных, которые будут удалены при выполнении команд очистки (`docker image prune`, `docker container prune` и т.д.).

### Проверка конфигурации ресурсов: docker inspect

Хотя `inspect` не является инструментом сбора метрик, он критически важен для сопоставления текущего потребления с установленными лимитами.

```bash
# Проверка лимитов памяти и CPU для контейнера
docker inspect <id> --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
# → 536870912 1000000000  # (512MB и 1 CPU в нано-единицах)
```

## Дополнительная информация

Нативные метрики идеальны для ручной отладки, но для промышленной эксплуатации (Production) следует использовать внешние коллекторы, которые умеют хранить историю и строить графики.

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — использование встроенного в Docker экспортера.
- **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)** — стандарт де-факто для глубокого сбора метрик контейнеров.
- **[Vector](../../Vector/vector_overview.md)** — высокопроизводительный агент для сбора и маршрутизации метрик.
- **[Cgroups (Контрольные группы)](../../Linux/Core/cgroups.md)** — теоретическая база механизмов ограничения ресурсов.
