# Docker: Очистка и GC-стратегии (prune, retention, registry GC)

**Актуально для:** Docker 24.x–29.x

## Определения

- **docker system prune** — удаление неиспользуемых ресурсов: остановленных контейнеров, dangling-образов, неиспользуемых сетей и кэша сборки BuildKit (включая cache mounts `RUN --mount=type=cache`).
- **Prune filters** — фильтры (`until=`, `label=`), ограничивающие удаление по времени создания объекта или его меткам. Ключевой инструмент безопасности: без фильтров prune деструктивен.
- **docker image prune -a** — удаление **всех** образов, не привязанных ни к одному контейнеру (не только dangling). Опасная операция: удаляет тегированные образы, но оставляет образы, на которые ссылается хотя бы один контейнер — включая остановленные.
- **Anonymous vs named volumes** — anonymous-тома создаются автоматически при `docker run -v /path` без имени; named — явно через `docker volume create`. С Docker 23.0 (API 1.42) `volume prune` и `system prune --volumes` по умолчанию удаляют **только anonymous**-тома.
- **Registry GC** — сборка мусора в реестре (Harbor, distribution) для удаления неиспользуемых blobs и манифестов.
- **Retention policy** — политика хранения: сколько тегов/дней хранить в реестре (lifecycle policies в Harbor). Retention только **помечает** артефакты неиспользуемыми; физическое удаление — GC.

## Предварительные требования

- **Docker Engine** 24.x–29.x (текущая стабильная линейка — 29.8.x).
- **Доступ к Docker socket**: `/var/run/docker.sock` или `DOCKER_HOST`.
- **Для registry GC**: доступ к реестру (Harbor UI/API или `registry garbage-collect`).
- **Утилиты хоста**: `df`, `du` для контроля результата; `jq` для API Harbor.

## Базовые концепции

### 1. Что удаляет каждая команда

| Команда | Удаляет | Безопасность |
| :--- | :--- | :--- |
| `docker system prune` | Остановленные контейнеры, dangling-образы, неиспользуемые сети, кэш сборки BuildKit | Умеренная |
| `docker system prune -a` | + все образы без контейнеров (включая тегированные) | Высокий риск |
| `docker system prune --volumes` | + неиспользуемые **anonymous**-тома (Docker 23+/API 1.42+) | Высокий риск (данные!) |
| `docker container prune` | Все остановленные контейнеры | Умеренная |
| `docker image prune` | Dangling-образы | Безопасная |
| `docker image prune -a` | Все образы, не привязанные ни к одному контейнеру | Высокий риск |
| `docker volume prune` | Неиспользуемые **anonymous**-тома (по умолчанию) | Средний риск |
| `docker volume prune -a` | + неиспользуемые **named**-тома | Высокий риск (данные!) |
| `docker builder prune` | Неиспользуемый кэш сборки (dangling-записи) | Безопасная |
| `docker builder prune -a` | Весь неиспользуемый кэш сборки | Безопасная |
| `docker network prune` | Неиспользуемые сети (кроме системных `bridge`, `host`, `none`) | Безопасная |

> `docker system prune -a --volumes` **не удаляет named-тома** — для этого нужен отдельный `docker volume prune -a`.

### 2. Что НЕ удаляет prune

Даже `docker system prune -a --volumes` не удаляет:

- **Работающие контейнеры** и их writable layer.
- **Образы, на которые ссылается хотя бы один контейнер** — включая остановленные (сначала `docker container prune`, потом `docker image prune -a`).
- **Named-тома** (только `docker volume prune -a`).
- **Системные сети** `bridge`, `host`, `none` — никогда.
- **Данные bind mounts** — они на хосте, вне `/var/lib/docker`.
- **Логи контейнеров** (`json-file`) — растут независимо от prune; ограничивайте `max-size`/`max-file` ([ротация логов](../Docker_logs/docker_log_rotation.md)).

### 3. Фильтры

```bash
# Удалить ресурсы, СОЗДАННЫЕ более 24 часов назад (не "не использовавшиеся"!)
docker system prune --filter "until=24h"

# По метке
docker system prune --filter "label=env=dev"

# Комбинация: разные ключи — AND (оба условия должны выполняться)
docker image prune -a --filter "until=168h" --filter "label=env=dev"

# Отрицание: образы БЕЗ метки env
docker image prune --filter "label!=env"

# Одинаковые ключи — OR (env=dev ИЛИ env=test)
docker image prune --filter "label=env=dev" --filter "label=env=test"
```

**Семантика `until`** — время **создания** объекта, а не время последнего использования. Форматы: Go-duration (`10m`, `1h30m`, `24h`), Unix-timestamp (секунды), RFC3339, `2006-01-02T15:04:05`, `2006-01-02`. Без указания часового пояса используется локальная зона демона.

**Поддержка фильтров по командам:**

| Команда | `until` | `label` | Примечание |
| :--- | :--- | :--- | :--- |
| `docker system prune` | + | + | `until` — для контейнеров, образов и сетей; **не для томов** |
| `docker container prune` | + | + | |
| `docker image prune` | + | + | |
| `docker network prune` | + | + | системные сети не удаляются никогда |
| `docker volume prune` | — | + | только `label`; по умолчанию — anonymous-тома |
| `docker builder prune` | + | — | дополнительно `--keep-storage <размер>` |

> **Ловушка:** `docker system prune --volumes --filter "until=24h"` ограничивает по возрасту контейнеры, образы и сети, но **anonymous-тома удаляются все неиспользуемые** — endpoint volumes не поддерживает `until`.

**Прогноз удаления:** положительные `label`-фильтры можно предпросмотреть через `docker image ls --filter "label=env=dev"`. Отрицательные (`label!=`) через `docker image ls` не проверяются — промпт подтверждения всегда предупреждает об удалении всех dangling-образов, даже когда заданы фильтры.

### 4. Принципы безопасности

- **Всегда используйте фильтры** в production — `until=` ограничивает удаление объектами старше заданного возраста создания.
- **`-a` и `--volumes`** — только при явной необходимости; они удаляют данные.
- **Тома не удаляются** обычным `docker system prune` — только с `--volumes` (anonymous) или `docker volume prune -a` (все).
- **Prune идемпотентен** — повторный запуск безопасен.
- **Перед деструктивными операциями** — `docker system df -v` и `docker volume ls`; образы для rollback держите в реестре, а не только на хосте.

## Практические сценарии

### Сценарий 1: Ежедневная очистка dev-среды (cron)

```bash
# /etc/cron.d/docker-cleanup
# Каждый день в 03:00: остановленные контейнеры, dangling-образы и
# неиспользуемые сети, созданные более 24 часов назад, + кэш сборки
0 3 * * * root /usr/bin/docker system prune --filter "until=24h" -f >> /var/log/docker-prune.log 2>&1

# Еженедельно: очистка кэша сборки, созданного более 7 дней назад
0 4 * * 0 root /usr/bin/docker builder prune --filter "until=168h" -f >> /var/log/docker-prune.log 2>&1
```

### Сценарий 2: Очистка CI-раннера после каждого job

```bash
#!/bin/bash
# post-job cleanup для self-hosted runner
set -euo pipefail

# Удалить контейнеры и образы, созданные этим job (по метке)
docker system prune -f --filter "label=ci.job.id=${JOB_ID}"

# Очистить кэш сборки, созданный более часа назад
docker builder prune -f --filter "until=1h"

# Удалить все неиспользуемые образы, созданные более 24 часов назад
docker image prune -a -f --filter "until=24h"
```

### Сценарий 3: Очистка с фильтрами (until=24h)

```bash
# Что будет удалено (проверка без удаления)
docker system df -v

# Прогноз по label-фильтру (положительные фильтры)
docker image ls --filter "label=env=dev"

# Безопасная очистка: только ресурсы, созданные более 24 часов назад
docker system prune --filter "until=24h" -f
# → Deleted Containers:
# → f44f9b81948b3919590d5f79a680d8378f1139b41952e219830a33027c80c867
# → Deleted Networks:
# → network1
# → Deleted Images:
# → untagged: hello-world@sha256:f3b3b28a45160805bb16542c9531888519430e9e6d6ffc09d72261b0d26ff74f
# → Total reclaimed space: 1.84kB

# Проверка результата
docker system df
# → RECLAIMABLE уменьшился
```

### Сценарий 4: Garbage Collection в Harbor

Полное руководство (расписание, workers, квоты, webhooks) — в [Harbor: работа с реестром](../Docker_registries/Harbor/usage.md), сценарий 10.

```bash
# DRY RUN — Harbor покажет, что будет удалено, без фактического удаления
curl -sk -u "admin:$PASS" -X POST -H "Content-Type: application/json" \
  -d '{"dry_run": true}' "https://harbor.corp.local/api/v2.0/system/gc"
# → 201 Created

# Реальный GC (delete_untagged разрешает удаление артефактов без тегов)
curl -sk -u "admin:$PASS" -X POST -H "Content-Type: application/json" \
  -d '{"delete_untagged": false}' "https://harbor.corp.local/api/v2.0/system/gc"

# История задач GC
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/system/gc" | \
  jq '.[] | {id, status, job_status}'
```

Особенности Harbor GC:

- Работает **без остановки** Harbor; UI: **Administration → Clean Up → Garbage Collection** (сначала DRY RUN).
- Артефакты, загруженные за последние **2 часа**, не удаляются — защита от удаления образов, которые ещё скачиваются.
- Расписание: None / Hourly / Daily / Weekly / Custom (cron); параметр **Workers** задаёт параллелизм.
- Остановка GC **не восстанавливает** уже удалённые артефакты.

### Сценарий 5: Systemd timer вместо cron

```ini
# /etc/systemd/system/docker-prune.service
[Unit]
Description=Docker prune (resources older than 24h)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker system prune --filter "until=24h" -f
```

```ini
# /etc/systemd/system/docker-prune.timer
[Unit]
Description=Run docker-prune daily at 03:00

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now docker-prune.timer
systemctl list-timers | grep docker-prune
# → docker-prune.timer  n/a  n/a  Mon 2026-10-05 03:00:00  12h left
```

### Сценарий 6: Retention policy в реестре

Retention **помечает** артефакты неиспользуемыми по правилам (число тегов, возраст, фильтры); место на диске освобождается только после GC. API и шаблоны правил (`latestPushedK`, `pushDaysAgo`, `alwaysRetain`) — в [Harbor: работа с реестром](../Docker_registries/Harbor/usage.md), сценарий 8.

```bash
# Пример политики: хранить последние 10 тегов в проекте, запуск Daily
# UI: Administration → Project → <project> → Retention
# API: POST /api/v2.0/retentions (тело — правила ниже), выполнение —
# POST /api/v2.0/retentions/{id}/executions с {"dry_run": true} для проверки
# {
#   "scope": "project",
#   "rules": [{
#     "n": 10,
#     "unit": "count",
#     "tag_selectors": [{"kind": "doublestar", "pattern": "**"}],
#     "schedule": "Daily"
#   }]
# }
```

### Сценарий 7: Garbage Collection в distribution (docker registry)

Детали (конфиг `delete.enabled`, read-only mode, флаги) — в [Реестры](../docker_registries.md), раздел «Устранение неполадок».

```bash
# 1. Включить удаление в config.yml: delete.enabled: true
# 2. Перевести реестр в read-only: storage.maintenance.readonly.enabled: true
# 3. Прогноз (с удалением untagged-манифестов):
registry garbage-collect --dry-run --delete-untagged /etc/distribution/config.yml
# 4. Реальный GC:
registry garbage-collect --delete-untagged /etc/distribution/config.yml
```

> Удаление манифестов через API лишь помечает их; blobs на диске остаются до GC.

### Сценарий 8: Мониторинг reclaimable (SRE)

Метрик размеров образов в Docker Engine нет (эндпоинт `metrics-addr` экспортирует только состояния контейнеров) — для алертов используйте filesystem-метрики node_exporter на `/var/lib/docker` и периодический снимок `docker system df`. Пороги алертов — в [Анализ использования диска](./disk_usage_analysis.md).

```bash
# /etc/cron.hourly/docker-disk-check — раннее предупреждение о заполнении диска
#!/bin/bash
# Порог 80% для раздела Docker; алерт + снимок docker system df для диагностики
USE=$(df -h /var/lib/docker | awk 'NR==2 {gsub("%", "", $5); print $5}')
if [ "$USE" -gt 80 ]; then
  {
    echo "$(date -Is) WARNING: /var/lib/docker usage ${USE}%"
    docker system df
  } >> /var/log/docker-disk.log
fi
```

### Сценарий 9: Лимит кэша сборки на CI-раннере

```bash
# Держать кэш BuildKit в пределах 10 ГБ (удаляет старые записи сверх лимита)
docker builder prune -f --keep-storage 10GB

# buildx (Docker 28.0+): очистка по объёму через фильтры
# reserved-space, max-used-space, min-free-space, keep-bytes
# (формат значений — см. docker buildx prune --help)
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Prune удалил нужный образ** | `docker image prune -a` без фильтров | Восстановите из реестра (`docker pull`); используйте `--filter "until="` |
| **Prune не освобождает место** | Логи контейнеров или тома не в prune | Проверьте `docker system df -v`; логи — `max-size`/`max-file`; тома — `docker volume prune` |
| **`docker volume prune` не удаляет named-тома** | С Docker 23.0 (API 1.42) по умолчанию удаляются только anonymous-тома | `docker volume prune -a` для всех неиспользуемых томов; проверьте `docker volume ls` |
| **`--filter "until="` не ограничивает тома** | Endpoint volumes не поддерживает фильтр `until` | При `docker system prune --volumes --filter "until=24h"` anonymous-тома удаляются независимо от возраста создания |
| **`docker image prune -a` не удаляет образ** | Образ ссылается остановленным контейнером | Сначала `docker container prune` (или `docker rm`), затем `docker image prune -a` |
| **`docker volume prune` удалил данные** | Том не использовался контейнером | Восстановление только из бэкапа; всегда проверяйте `docker volume ls` перед prune |
| **Build cache не очищается** | Кэш используется текущими сборками | `docker builder prune -a` (все кэши); проверьте `docker builder du` |
| **Registry GC не освобождает место** | Blobs всё ещё на них ссылаются (теги/манифесты) | Удалите теги перед GC; Harbor GC удаляет только unreferenced blobs |
| **Reclaimable не совпадает с `df -h` после prune** | containerd image store: учёт unpacked image data (до 29.6.0) | Обновитесь до 29.6.0+; проверяйте `df -h /var/lib/containerd` |

## Валидация результатов

```bash
# До очистки
docker system df
# → TYPE                TOTAL               ACTIVE              SIZE                RECLAIMABLE
# → Images              12                  3                   4.5GB               3.2GB (71%)
# → Containers          8                   2                   120MB               100MB (83%)
# → Local Volumes       5                   2                   8.5GB               6.1GB (71%)
# → Build Cache         45                  0                   2.3GB               2.3GB

# Очистка
docker system prune --filter "until=24h" -f

# После очистки
docker system df
# → Images              8                   3                   1.3GB               0.2GB (15%)

# Проверка, что работающие контейнеры не пострадали
docker ps
# → (все контейнеры на месте)

# Проверка диска
df -h /var/lib/docker
# → Use% снизился
```

## Граничные случаи

### Production: никогда без фильтров

`docker system prune -a --volumes` в production без `until=` фильтра удалит все неиспользуемые образы и все неиспользуемые anonymous-тома — включая данные для rollback. Всегда используйте `--filter "until=<N>h"` (помните: `until` ограничивает по времени **создания**, не по времени последнего использования, и не распространяется на тома).

### Тома и данные

- Обычный `docker system prune` не удаляет тома вообще.
- `--volumes` удаляет только неиспользуемые **anonymous**-тома (Docker 23.0+/API 1.42+).
- Именованные (named) неиспользуемые тома удаляет только `docker volume prune -a`.
- Перед удалением проверьте: `docker volume ls` + `docker ps -a --filter volume=<name>`.

### BuildKit cache mounts

`--mount=type=cache` в Dockerfile использует отдельный кэш BuildKit. `docker system prune` очищает его **всегда** (включая cache mounts, даже без `-a`); `docker builder prune` — по dangling-записям, с `-a` — весь неиспользуемый кэш. `docker image prune` кэш сборки не затрагивает вообще.

### Self-hosted runners

На CI-раннерах с ограниченным диском настройте очистку после каждого job (Сценарий 2) и мониторинг `df -h` с алертом на > 80% (Сценарий 8).

### Ноды Kubernetes

На нодах Kubernetes не используйте `docker system prune` по cron: за очистку образов отвечает **kubelet** (image GC при заполнении `imagefs`: `imageGCHighThresholdPercent` 85% и `imageGCLowThresholdPercent` 80% по умолчанию — см. [kubelet](../../Kubernetes/Concepts/kubelet.md)). Prune `-a` на ноде удалит образы, не привязанные к текущим контейнерам, — включая образы для ещё не запланированных подов, что вызовет повторные pull и нагрузку на реестр. На нодах с containerd Docker CLI вообще отсутствует.

### Containerd image store (Docker 29.x)

В режиме containerd image store (включён по умолчанию в Docker 29) слои хранятся в `/var/lib/containerd/`; `docker system df` и prune учитывают их. Исправления, влияющие на prune: 29.4.1 — `docker image prune --filter label!=key=value` больше не пропускает образы без метки; 29.6.0 — `docker system prune` корректно считает reclaimed space для unpacked image data. Если reclaimable после prune не совпадает с `df -h`, проверьте версию Engine.

### Rootless Docker

Данные в `$HOME/.local/share/docker/`. Prune работает аналогично, но cron/systemd-timer должны запускаться от пользователя rootless-режима (systemd `--user`), а не от root.

## Лучшие практики

1. **Фильтры обязательны** в production: `--filter "until=24h"` минимум (по времени создания).
2. **Разделяйте dev и production**: в dev — агрессивный prune по cron; в production — только dangling + build cache.
3. **Мониторьте reclaimable**: алерт при Reclaimable > 50% от SIZE (пороги — в [disk_usage_analysis.md](./disk_usage_analysis.md)).
4. **Registry GC**: Harbor — ежедневный GC + retention policy ([usage](../Docker_registries/Harbor/usage.md)); distribution — `registry garbage-collect` по cron с предварительным read-only ([docker_registries.md](../docker_registries.md)).
5. **Логи**: `max-size`/`max-file` в log-opt — иначе логи заполнят диск раньше, чем prune поможет ([ротация](../Docker_logs/docker_log_rotation.md)).
6. **Тестируйте восстановление** после prune — убедитесь, что rollback-образы доступны из реестра ([бэкап и восстановление](./docker_backup_restore.md)).
7. **Named-тома** prune не трогает — бэкапьте их отдельно.
8. **На K8s-нодах** — kubelet image GC, а не cron-prune.

## Дополнительная информация

### Связанные документы

- **[Анализ использования диска](./disk_usage_analysis.md)** — `docker system df`, reclaimable, диагностика, пороги алертов.
- **[Драйвер хранения OverlayFS](./docker_overlayfs.md)** — слои и whiteout, влияющие на занятое место.
- **[Тома (Volumes)](./docker_volumes.md)** — данные, которые `prune --volumes` может удалить.
- **[Резервное копирование](./docker_backup_restore.md)** — восстановление после ошибочного prune.
- **[Ротация логов](../Docker_logs/docker_log_rotation.md)** — ограничение роста `*-json.log`.
- **[Справочник команд Docker](../docker_commands.md)** — краткая справка по prune.
- **[Harbor: работа с реестром](../Docker_registries/Harbor/usage.md)** — GC, retention, квоты проектов.
- **[Реестры](../docker_registries.md)** — GC в distribution, сравнение реестров.
- **[kubelet](../../Kubernetes/Concepts/kubelet.md)** — пороги image GC на нодах Kubernetes.
