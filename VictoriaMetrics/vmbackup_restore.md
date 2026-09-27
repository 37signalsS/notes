# vmbackup / vmrestore: резервное копирование и восстановление

## Определения

**vmbackup** — утилита VictoriaMetrics для инкрементального резервного копирования данных метрик и логов в объектное хранилище (S3, GCS, Azure Blob Storage) или локальную файловую систему без остановки сервиса.

**vmrestore** — утилита для восстановления данных из бэкапа обратно в `-storageDataPath`. Требует остановленного сервиса VictoriaMetrics.

**Snapshot (снапшот)** — консистентная точка-застывшая копия данных, создаваемая самим VictoriaMetrics по HTTP-запросу `/snapshot/create`. vmbackup копирует снапшот, а не живой каталог данных, поэтому не нарушает работу сервиса.

## Базовые концепции

### Поток резервного копирования

```
victoria-metrics (vmsingle/vmstorage)
        │
        ▼
 POST /snapshot/create   →  возвращает имя снапшота (temp-каталог)
        │
        ▼
 vmbackup -storageDataPath=... -snapshot.createURL=... -dst=...
        │
        ▼  сравнивает с предыдущим бэкапом (инкремент)
 объектное хранилище / локальный fs
```

- Снапшот создаётся мгновенно (имена вида `20260922T123456.789`), данные копируются из него без блокировки записи.
- **Инкрементальность автоматическая:** vmbackup загружает только изменившиеся блоки по сравнению с последним бэкапом в `-dst`.
- Снапшот после копирования можно удалить (`DELETE /snapshot/<name>`), иначе он накапливается в `-storageDataPath/snapshots`.

### Поддерживаемые назначения `-dst`

| Префикс | Назначение |
| :--- | :--- |
| `s3://bucket/path` | AWS S3 (требует `-s3.endpoint`, `-s3.accessKeyID`, `-s3.secretAccessKey`) |
| `gs://bucket/path` | Google Cloud Storage |
| `azblob://container/path` | Azure Blob Storage |
| `fs:///path/to/backup` | Локальная ФС или смонтированный NFS |
| `s3://...cистем123` + `-customS3Endpoint` | MinIO, Ceph, Yandex Object Storage и пр. |

### Восстановление (vmrestore)

```bash
# 1) Остановить victoria-metrics
systemctl stop victoria-metrics

# 2) Восстановить данные в пустой каталог
vmrestore -storageDataPath=/victoria-metrics-data \
  -src=s3://my-backups/victoria-metrics
# → последний бэкап (инкремент + базовый) применится автоматически

# 3) Запустить сервис с тем же -storageDataPath
systemctl start victoria-metrics
```

Ключевые флаги: `-src` (источник, тот же формат, что `-dst`), `-storageDataPath` (куда распаковать), `-dst` для vmbackup, `-snapshot.createURL` (у vmsingle — `http://localhost:8428/snapshot/create`, у VictoriaLogs — `http://localhost:9428/snapshot/create`), `-origin` — server-side copy в пределах одного объекта (например, для быстрого переключения между ветками бэкапов).

## Практические сценарии

### 1. Еженощный бэкап в S3 (systemd timer)

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP="s3://backups/victoria-metrics/prod"
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst="$BACKUP" \
  -s3.endpoint=s3.amazonaws.com \
  -s3.accessKeyID=AKIA... \
  -s3.secretAccessKey=$S3_SECRET
```

Снапшот копируется, VM продолжает писать. Первый запуск — полный бэкап; последующие — только дельта.

### 2. Локальное резервирование на отдельный диск (без облака)

```bash
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst=fs:///mnt/backup/victoria-metrics
```

### 3. Cluster: бэкап всех vmstorage

Каждый `vmstorage` бэкапится отдельно (данные не реплицируются между нодами):

```bash
for i in 0 1 2; do
  vmbackup \
    -storageDataPath=/var/lib/vmstorage-$i \
    -snapshot.createURL=http://vmstorage-$i:8482/snapshot/create \
    -dst=s3://backups/victoria-cluster/$i
done
```

Восстановление кластера — поузловое через vmrestore на каждый `-storageDataPath`, затем запуск всех компонентов в том же составе.

### 4. Автоматическая проверка бэкапа и тест восстановления

Бэкап без теста восстановления — «магическая резервная копия». Регулярно (не реже раза в месяц) прогоняйте тест в CI/cron:

```bash
#!/usr/bin/env bash
set -euo pipefail
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# 1) Восстановить последний бэкап в изолированный каталог
vmrestore -storageDataPath="$TMP" -src=s3://backups/victoria-metrics/latest

# 2) Запустить теневой инстанс на отдельном порту
victoria-metrics -storageDataPath="$TMP" -httpListenAddr=:8499 -retentionPeriod=1d &
sleep 10

# 3) Проверить health и наличие данных
curl -sf http://localhost:8499/health
curl -sf 'http://localhost:8499/api/v1/query?query=up' | grep -q 'UP' || exit 1

# 4) (по желанию) статистика: число серий/партиций
curl -sf 'http://localhost:8499/api/v1/status/tsdb' | jq -r '.data.totalSeries'

kill %1; wait %1 2>/dev/null || true
echo "OK: бэкап восстанавливается"
```

- Теневой инстанс можно не поднимать каждый раз: достаточно `vmrestore` + проверка каталога + `fetch /health` на холодной ноде;
- Включайте тест в CI (после vmbackupmanager/cron) с рассылкой результата в чат;
- Периодически проверяйте **retention бэкапов**: старые копии не должны «съесть» объектное хранилище (для этого — `vmbackupmanager` или cron-чистка).

## Валидация установки

```bash
# Создание снапшота вручную
curl -s http://localhost:8428/snapshot/create | jq .
# → {"status":"ok","snapshot":"20260922T123456.789"}

# Список снапшотов
curl -s http://localhost:8428/snapshot/list | jq .

# Удаление неиспользуемого снапшота
curl -s -XDELETE http://localhost:8428/snapshot/20260922T123456.789 | jq .

# После восстановления: данные на месте
ls -la /victoria-metrics-data/ | head
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| vmbackup ошибка авторизации S3 | Неверные ключи/регион/эндпоинт | Проверить `-s3.endpoint` (для MinIO указать кастомный), права bucket |
| «snapshot not found» | Снапшот удалён раньше, чем vmbackup его скопировал | Не удалять снапшоты руками раньше времени; настроить удаление старых снапшотов |
| Восстановление из «инкремента» даёт неполные данные | Распаковано не всё дерево бэкапов | vmrestore сам собирает инкремент; не удаляйте более ранние бэкапы из `-src` |
| VM не стартует после vmrestore | Занят каталог/неверный `-storageDataPath` | Остановить сервис до vmrestore; запускать строго с тем же путём |
| Много снапшотов накапливается | Нет чистки | Настроить `vmbackupmanager` (Enterprise) или CRON-удаление старых `/snapshot` |

## Рекомендации по эксплуатации

- **Делайте бэкап перед major-апгрейдом:** vmbackup инкрементален, но восстановление требует останова сервиса — планируйте окно.
- Храните бэкапы в отдельном регионе/zonе от продового кластера.
- Тестируйте восстановление регулярно (восстановление в отдельный каталог + запуск на «дренажном» экземпляре).
- Следите за снапшотами в `-storageDataPath/snapshots` — удаляйте после успешного vmbackup.
- Для retention бэкапов (хранить N дней) используйте Enterprise **vmbackupmanager**, а не кастомные скрипты.

## Ограничения и особые случаи

- vmrestore требует остановленного сервиса; для кластера — останавливать каждый vmstorage по очереди или все сразу, в зависимости от приемлемого RTO.
- Для VictoriaLogs/метрик снапшот создаётся по тому же механизму (`/snapshot/create` на порту 9428/8428), но бэкап логов обычно ведётся через тот же vmbackup (`-snapshot.createURL=http://localhost:9428/snapshot/create`).
- Shared-Nothing: никогда не монтируйте NFS/CIFS как `-storageDataPath` — только для `fs://`-бэкапов.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты и часто используемые флаги;
- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — бэкап логов;
- [Kubernetes: VictoriaLogs + operator](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — helm/cronjob-схема бэкапа;
- [DR: аварийное восстановление](./disaster_recovery.md) — сценарии потери нод/кластера, RPO/RTO;
- [HTTP API: снапшоты](./http_api_reference.md) — `/snapshot/create`, `/snapshot/list`.