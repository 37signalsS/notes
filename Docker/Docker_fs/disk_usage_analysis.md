# Docker: Анализ использования дискового пространства (docker system df)

**Актуально для:** Docker 24.x–29.x

## Определения

- **docker system df** — команда, показывающая сводку использования диска Docker: образы (Images), контейнеры (Containers), локальные тома (Local Volumes), кэш сборки (Build Cache). Опции: `-v`/`--verbose` (детализация) и `--format` (шаблоны Go, `table`, `json`, `raw`).
- **docker system df -v** — детализированный вывод в четырёх секциях: `Images space usage:`, `Containers space usage:`, `Local Volumes space usage:` и `Build cache usage: <итого>` — по каждому образу, контейнеру, тому и записи кэша BuildKit.
- **SIZE (образ)** — virtual size образа: сумма `SHARED SIZE` (данные, общие с другими образами) и `UNIQUE SIZE` (данные, принадлежащие только этому образу).
- **SIZE (контейнер)** — размер writable layer контейнера. Логи `json-file` в него **не входят** (см. «Что НЕ показывает»).
- **ACTIVE** — объекты, задействованные контейнерами: для Images и Local Volumes — используемые любыми контейнерами (включая остановленные); для Containers — работающие контейнеры.
- **Reclaimable** — объём диска, который можно освободить через prune: для Images — образы без контейнеров (dangling и неиспользуемые); для Containers — остановленные контейнеры; для Local Volumes — неиспользуемые anonymous-тома (Docker 23+/API 1.42+); для Build Cache — записи кэша, помеченные reclaimable.
- **Dangling image** — образ без тега (`<none>:<none>`), обычно промежуточный или оставшийся после пересборки.
- **Build cache** — кэш BuildKit, хранящийся отдельно от образов и учитываемый в `docker system df` как отдельная категория. Детальный анализ — `docker buildx du` (команды `docker builder du` не существует).

## Предварительные требования

- **Docker Engine** 24.x–29.x.
- **Доступ к Docker socket**: `/var/run/docker.sock` или `DOCKER_HOST`.
- **Docker Buildx** — для анализа кэша сборки (`docker buildx du`).
- **Утилиты хоста**: `df`, `du`, `find`, `sort` для анализа файловой системы.

## Базовые концепции

### 1. Где хранятся данные Docker

| Путь | Содержимое | Примечание |
| :--- | :--- | :--- |
| `/var/lib/docker/overlay2/` | Слои образов и writable layer | Классический режим (overlay2) |
| `/var/lib/docker/volumes/` | Именованные тома | Данные томов |
| `/var/lib/docker/containers/` | Логи контейнеров (`*-json.log`), конфиги | json-file driver растёт без ограничений |
| `/var/lib/containerd/` | Слои в containerd snapshotter | Docker 29.0+ (containerd image store) |
| `$HOME/.local/share/docker/` | Все данные Docker | Rootless-режим |

### 2. Сводка vs детализация

```bash
# Сводка
docker system df
# → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# → Images          12        3         4.5GB     3.2GB (71%)
# → Containers      8         2         120MB     100MB (83%)
# → Local Volumes   5         2         8.5GB     6.1GB (71%)
# → Build Cache     45        0         2.3GB     2.3GB

# Детализация
docker system df -v
# → Images space usage:
# → REPOSITORY   TAG      IMAGE ID   CREATED        SIZE    SHARED SIZE   UNIQUE SIZE   CONTAINERS
# → my-app       1.0      a1b2c3d4   2 hours ago    245MB   0B            245MB         2
# → <none>       <none>   e4f5a6b7   3 hours ago    11MB    11MB          0B            0
#
# → Containers space usage:
# → CONTAINER ID   IMAGE        COMMAND   LOCAL VOLUMES   SIZE    CREATED          STATUS                     NAMES
# → 4a7f7eebae0f   my-app:1.0   "sh"      1               12MB    16 minutes ago   Exited (0) 5 minutes ago   hopeful_yalow
#
# → Local Volumes space usage:
# → NAME        LINKS   SIZE
# → pg-data     1       6.2GB
# → redis-cache 0       1.8GB
#
# → Build cache usage: 2.3GB
# → CACHE ID   CACHE TYPE   SIZE    CREATED        LAST USED      USAGE COUNT   SHARED
# → x8k2m...   regular      512MB   2 hours ago    30 minutes ago 3             false
```

- **SIZE** — общий объём категории.
- **RECLAIMABLE** — сколько можно освободить через prune (в скобках — процент от SIZE категории; для Build Cache процент не показывается).
- **ACTIVE** — для Images и Local Volumes считаются объекты, на которые ссылаются контейнеры, включая остановленные (поэтому `docker image prune` без `-a` не удаляет образ остановленного контейнера); для Containers — только работающие.
- **Сети не показываются**, потому что не занимают место на диске (примечание из официальной документации).

### 3. Что НЕ показывает docker system df

- **Логи контейнеров (`json-file` driver)** — SIZE контейнера в `docker system df -v` — это только writable layer (в исходниках moby: `GetContainerLayerSize`); файлы `*-json.log` из `/var/lib/docker/containers/<id>/` в него не входят. Растущие логи — типичная причина «диск заполнен, а df показывает мало» (анализ — Сценарий 4).
- **Bind mounts** — данные на хосте, не в `/var/lib/docker`.
- **Docker Desktop (Mac/Windows)** — данные внутри VM; `docker system df` показывает размеры внутри VM (CLI уже обращается к демону в VM).
- **Rootless Docker** — данные в `$HOME/.local/share/docker/`.
- **Разница с `du`** — `docker system df` считает только отслеживаемые объекты; `du -sh /var/lib/docker` показывает физическое место на диске. Разница = логи, осиротевшие слои без образных записей и накладные расходы ФС (Сценарий 8).

## Практические сценарии

### Сценарий 1: Быстрая сводка

```bash
docker system df
# → TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
# → Images          12        3         4.5GB     3.2GB (71%)
# → Containers      8         2         120MB     100MB (83%)
# → Local Volumes   5         2         8.5GB     6.1GB (71%)
# → Build Cache     45        0         2.3GB     2.3GB

# Машиночитаемый вывод для скриптов (ключ-значение по каждой категории)
docker system df --format raw
# → type: Images
# → total: 12
# → active: 3
# → size: 4.5GB
# → reclaimable: 3.2GB (71%)
# → (затем аналогичные блоки для Containers, Local Volumes, Build Cache)

# JSON-объекты по каждой категории
docker system df --format json

# Произвольный шаблон Go (поля: .Type .TotalCount .Active .Size .Reclaimable)
docker system df --format "{{.Type}}: {{.Size}} (reclaimable {{.Reclaimable}})"
# → Images: 4.5GB (reclaimable 3.2GB (71%))
```

### Сценарий 2: Детальный анализ — что занимает место

```bash
# Образы с размерами (секция "Images space usage:")
docker system df -v | grep -A 100 "Images space usage"
# → REPOSITORY   TAG   IMAGE ID   CREATED   SIZE   SHARED SIZE   UNIQUE SIZE   CONTAINERS
# → my-app       1.0   a1b2c3d4   2h ago    245MB  0B            245MB         2

# Контейнеры с размерами writable layer (секция "Containers space usage:")
docker system df -v | grep -A 100 "Containers space usage"

# Тома с размерами (секция "Local Volumes space usage:")
docker system df -v | grep -A 100 "Local Volumes space usage"
# → NAME          LINKS   SIZE
# → pg-data       1       6.2GB
# → redis-cache   0       1.8GB

# Кэш сборки: детализация через buildx (docker builder du не существует)
docker buildx du
# → ID                                RECLAIMABLE    SIZE          LAST ACCESSED
# → 12wgll9os87pazzft8lt0yztp*        true           1.704GB       13 days ago
# → iupsv3it5ubh92aweb7c1wojc*        true           1.297GB       36 minutes ago
# → Shared:        115.5MB
# → Private:       10.25GB
# → Reclaimable:   10.36GB
# → Total:         10.36GB
```

Особенности `docker buildx du`:

- `*` рядом с ID — запись mutable (размер может измениться или запись перейдёт к другой сборке); `*` рядом с SIZE — хранилище разделяется с другим ресурсом (обычно образом); при prune такой записи удаляется только метадата, слои остаются.
- `RECLAIMABLE: false` — запись используется компонентом builder и не будет удалена даже `docker buildx prune --all`.
- Опции: `--filter` (те же фильтры, что у `buildx prune`), `--format` (Go-шаблоны, `json`, `pretty`), `--verbose` (синоним `--format=pretty`), `--builder <name>` (анализ конкретного builder'а).

### Сценарий 3: Поиск крупных томов на хосте

```bash
# Размер каждого тома на файловой системе
du -sh /var/lib/docker/volumes/*/ | sort -rh | head -10
# → 6.2G    /var/lib/docker/volumes/pg-data/_data
# → 1.8G    /var/lib/docker/volumes/redis-cache/_data

# Крупнейшие директории внутри тома
du -sh /var/lib/docker/volumes/pg-data/_data/*/ | sort -rh | head -5
```

### Сценарий 4: Анализ логов контейнеров

Логи `json-file` не входят в SIZE контейнера в `docker system df` (Сценарий 2), поэтому анализируются отдельно:

```bash
# Размер логов каждого контейнера
find /var/lib/docker/containers -name "*-json.log" -exec du -sh {} \; | sort -rh
# → 2.1G    /var/lib/docker/containers/abc123/abc123-json.log

# Контейнер с самым большим логом
for f in /var/lib/docker/containers/*/*-json.log; do
  echo "$(du -sh "$f" | cut -f1) $(basename $(dirname "$f"))"
done | sort -rh | head -5
```

### Сценарий 5: Диагностика inode exhaustion

```bash
# Проверка inodes
df -i /var/lib/docker
# → Filesystem     Inodes  IUsed  IFree IUse% Mounted on
# → /dev/sda1      655360  655360 0     100%  /var/lib/docker

# Поиск директорий с миллионами файлов
for d in /var/lib/docker/overlay2/*/diff; do
  echo "$(find "$d" -type f 2>/dev/null | wc -l) $d"
done | sort -rn | head -5
```

### Сценарий 6: Мониторинг через метрики Docker daemon

```bash
# Включение метрик в daemon.json
# {
#   "metrics-addr": "127.0.0.1:9323"
# }

# Получение метрик демона (пространство engine_daemon_)
curl -s localhost:9323/metrics | grep engine_daemon
# → engine_daemon_engine_info{version="29.8.2",...}
# → engine_daemon_container_states_containers{state="running"} 12

# Размеры объектов Docker — только через CLI (в метриках демона нет)
docker system df
# → TYPE     TOTAL  ACTIVE  SIZE   RECLAIMABLE
# → Images   12     3       4.5GB  3.2GB (71%)
```

*Примечание:* эндпоинт 9323 экспортирует только метрики демона (`engine_daemon_`): состояния контейнеров, health-check'и, таймеры операций. Метрик размеров образов/контейнеров (`docker_images_size_bytes` и т.п.) в Docker Engine **нет** — для алертов на место используйте `docker system df` по cron или textfile collector Node Exporter (Сценарий 7). Подробнее: [Справочник метрик Docker Engine](../Docker_metrics/docker_engine_metrics_reference.md).

### Сценарий 7: Скриптинг и алерты через --format (SRE)

`docker system df --format raw` выдаёт целые числа в полях `total` и `active` — их можно выгружать в Prometheus через textfile collector Node Exporter:

```bash
#!/bin/sh
# Снимок docker system df для textfile collector node_exporter
# Размещать в каталоге textfile collector (например, /var/lib/node_exporter/textfile_collector/)
OUT=/var/lib/node_exporter/textfile_collector/docker_df.prom
{
  docker system df --format raw | awk '
    /^type:/     {type=$2}
    /^total:/    {printf "docker_df_total{type=\"%s\"} %s\n", type, $2}
    /^active:/   {printf "docker_df_active{type=\"%s\"} %s\n", type, $2}
  '
} > "$OUT"
# → docker_df_total{type="Images"} 12
# → docker_df_active{type="Images"} 3
# → docker_df_total{type="Containers"} 8
# → ...
```

*Примечание:* поля `size` и `reclaimable` в raw-выводе — человекочитаемые строки (`4.5GB`), не числа; для байтовых значений используйте `docker system df --format json` и парсите JSON. Пороги алертов — в [Лучшие практики](#лучшие-практики).

### Сценарий 8: Сверка docker system df с du (поиск «потерянного» места)

```bash
# Сумма SIZE по категориям vs физическое место
docker system df
du -sh /var/lib/docker
# → docker system df: Images 4.5GB + Containers 120MB + Volumes 8.5GB + Cache 2.3GB ≈ 15.4GB
# → du -sh /var/lib/docker: 22GB
# → Разница ≈ 6.6GB: логи контейнеров, осиротевшие слои без образных записей, накладные расходы overlay2

# Что именно занимает место вне объектов Docker
du -sh /var/lib/docker/*/ | sort -rh
# → 9.1G    /var/lib/docker/overlay2
# → 6.2G    /var/lib/docker/volumes
# → 3.4G    /var/lib/docker/containers     ← в основном логи
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`docker system df` показывает мало, а диск заполнен** | Логи контейнеров (не входят в SIZE), bind mounts, `/var/lib/containerd` | Проверьте `du -sh /var/lib/docker/*`, `df -h`, логи (Сценарий 4) |
| **`du -sh /var/lib/docker` больше, чем сумма SIZE в df** | Логи, осиротевшие слои без образных записей, накладные расходы ФС | Сверка по Сценарию 8; очистка по [Очистка и GC-стратегии](./cleanup_gc_strategies.md) |
| **RECLAIMABLE большой, но prune не помогает** | Образы/тома используются остановленными контейнерами | Удалите остановленные контейнеры (`docker container prune`) |
| **Inodes исчерпаны (IUse% 100%)** | Миллионы мелких файлов в слоях или логах | Очистите неиспользуемые ресурсы; пересоздайте ФС с большим лимитом inodes |
| **Build Cache растёт бесконтрольно** | CI-раннер с частыми сборками | `docker builder prune --filter until=24h` по cron; лимит `--keep-storage` |
| **Docker 29+: место занято, но df показывает мало** | Данные в `/var/lib/containerd` (containerd snapshotter) | Проверьте `df -h /var/lib/containerd` |
| **`docker buildx du` показывает меньше, чем Build Cache в df** | Разные builder'ы: `buildx du` считает выбранный builder (`--builder`) | Сравнивайте с `docker buildx du --builder <name>` |

## Валидация результатов

```bash
# После очистки — сверка reclaimable
docker system df
# → Images: 4.5GB → 1.3GB (после docker image prune -a)

# Проверка, что диск освободился
df -h /var/lib/docker
# → /dev/sda1  100G   45G   55G  45% /var/lib/docker

# Проверка inodes
df -i /var/lib/docker
# → IUse% < 80%

# Сверка с физическим местом (разница должна быть только логи и накладные расходы)
du -sh /var/lib/docker
```

## Граничные случаи

### Containerd snapshotter (Docker 29.0+)

В режиме containerd image store слои хранятся в `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/` и могут дублироваться (сжатые в content store + распакованные в snapshotter). `docker system df` учитывает их, но для полной картины проверяйте `df -h /var/lib/containerd`.

### Docker Desktop (Mac/Windows)

Данные хранятся внутри VM, а не в `/var/lib/docker` хоста:

- **Mac** — VM на базе Apple Virtualization framework (в старых версиях HyperKit); диск VM — sparse-файл `Docker.raw`. `docker system df` показывает размеры внутри VM — это основной инструмент анализа; для оценки места на хосте смотрите размер файла диска VM в настройках Docker Desktop.
- **Windows (WSL 2)** — Docker Desktop работает в собственной WSL2-дистрибутиве `docker-desktop`; данные по умолчанию в `C:\Users\[USERNAME]\AppData\Local\Docker\wsl` (расположение меняется в Settings → Resources → Advanced). Анализ: `wsl -d docker-desktop du -sh /var/lib/docker` или `docker system df`.

### Rootless Docker

Данные в `$HOME/.local/share/docker/`. Анализ: `du -sh ~/.local/share/docker/*`. Логи — в `$XDG_RUNTIME_DIR/docker/containers/` (обычно `~/.local/share/docker/containers/`).

## Лучшие практики

- **Регулярный снимок**: `docker system df` по cron/systemd-timer (например, раз в сутки) с сохранением вывода — позволяет отслеживать тренд роста Reclaimable до заполнения диска.
- **Ограничивайте рост логов**: `log-opt max-size`/`max-file` для `json-file` или драйвер `local` (Docker Desktop 4.94+ по умолчанию использует `local` для новых Linux-контейнеров — с автоматической ротацией). Подробнее: [Ротация логов](../Docker_logs/docker_log_rotation.md).
- **Лимит кэша сборки** на CI-раннерах: `docker builder prune --keep-storage=5GB` (см. [Очистка и GC-стратегии](./cleanup_gc_strategies.md)).
- **Отдельный раздел или квоты** для `/var/lib/docker` — защита от DoS через переполнение диска логами или образами (см. [Усиление демона](../Docker_security/host_daemon_hardening.md)).
- **Перед деструктивными операциями** — снимок `docker system df -v` и `docker volume ls`; образы для rollback держите в реестре, а не только на хосте.

### Пороги для алертов (SRE)

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| Использование `/var/lib/docker` | > 80% | Предупреждение; > 90% — критический |
| IUse% (inodes) | > 80% | Предупреждение; риск отказа overlay2 |
| Reclaimable (Images) | > 50% от SIZE | Запланировать `docker image prune` |
| Размер `*-json.log` | > 1 ГБ | Настроить `max-size`/`max-file` в log-opt |
| Build Cache | > 5 ГБ | `docker builder prune` |

## Дополнительная информация

### Связанные документы

- **[Драйвер хранения OverlayFS](./docker_overlayfs.md)** — структура слоёв и writable layer, занимающих место.
- **[Анализ и управление слоями образа](./images/layer_management.md)** — дедупликация слоёв, dangling-слои, `docker system df` vs `du`.
- **[Тома (Volumes)](./docker_volumes.md)** — персистентные данные, занимающие место.
- **[Ротация логов](../Docker_logs/docker_log_rotation.md)** — ограничение роста `*-json.log`.
- **[Очистка и GC-стратегии](./cleanup_gc_strategies.md)** — освобождение reclaimable-пространства.
- **[Нативные метрики Docker](../Docker_metrics/docker_native_metrics.md)** — Prometheus-метрики демона (порт 9323).
- **[Справочник метрик Docker Engine](../Docker_metrics/docker_engine_metrics_reference.md)** — полный перечень метрик `engine_daemon_`.
