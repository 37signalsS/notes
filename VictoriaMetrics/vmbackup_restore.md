# vmbackup / vmrestore: резервное копирование и восстановление

**Актуально для:** VictoriaMetrics (vmbackup/vmrestore/vmbackupmanager) v1.154.0

## 1. Определения

**vmbackup** — утилита VictoriaMetrics для инкрементального резервного копирования данных метрик (victoria-metrics, vmstorage) и логов (VictoriaLogs) в объектное хранилище (S3, GCS, Azure Blob Storage) или локальную файловую систему без остановки сервиса. Создаёт мгновенный snapshot через HTTP API и копирует его содержимое в назначение, сравнивая с предыдущим бэкапом и загружая только изменившиеся блоки.

**vmrestore** — утилита для восстановления данных из бэкапа, созданного vmbackup или vmbackupmanager, обратно в `-storageDataPath`. Требует остановленного сервиса VictoriaMetrics (vmsingle или vmstorage). Поддерживает прерывание и возобновление с того же места.

**Snapshot (снапшот)** — консистентная точка-застывшая копия данных, создаваемая VictoriaMetrics по HTTP-запросу `POST /snapshot/create`. Снапшот создаётся мгновенно (имена вида `20260922T123456.789`), данные копируются из него без блокировки записи. После успешного копирования снапшот удаляется автоматически.

**vmbackupmanager** — утилита Enterprise для автоматизации регламентного резервного копирования (hourly/daily/weekly/monthly) и retention-политики. Управляется через CLI или HTTP API на порту `:8300`.

## 2. Базовые концепции и архитектура

### Поток резервного копирования

```
victoria-metrics (vmsingle / vmstorage / VictoriaLogs)
        │
        ▼
POST /snapshot/create  →  возвращает имя снапшота (temp-каталог)
        │
        ▼
vmbackup -storageDataPath=... -snapshot.createURL=... -dst=...
        │
        ▼  сравнивает с предыдущим бэкапом (инкремент)
объектное хранилище / локальный fs
        │
        ▼
удаление снапшота (автоматически после успешного копирования)
```

- Снапшот создаётся мгновенно, данные копируются из него без блокировки записи.
- **Инкрементальность автоматическая:** vmbackup загружает только изменившиеся файлы по сравнению с `-dst`. Если `-dst` уже содержит данные предыдущего бэкапа — загружаются только новые/изменённые файлы.
- Снапшот после копирования удаляется автоматически vmbackup. Если vmbackup прерван — снапшот остаётся в `-storageDataPath/snapshots/` и должен быть удалён вручную.
- Если `-dst` уже содержит данные — vmbackup синхронизирует (удаляет файлы, которых нет в снапшоте, загружает новые), как `rsync --delete`.

### Типы бэкапов

| Тип | Когда используется | Характеристика |
| :--- | :--- | :--- |
| **Full backup** | Первичный/разовый бэкап | Все файлы из снапшота копируются в `-dst`. |
| **Incremental backup** | Ежедневный/повторный | Только изменённые/новые файлы копируются. Автоматически при повторном запуске в тот же `-dst`. |
| **Smart backup** | Регламентный график | Комбинация full + incremental. Hourly бэкапы в `/latest/`, ежедневные — в `YYYYMMDD/` и т.д. |
| **Server-side copy** | Ускорение full backup | `-origin=gs://bucket/existing -dst=gs://bucket/new` — данные копируются внутри объектного хранилища без скачивания. |

### Поддерживаемые назначения `-dst` / `-src`

| Префикс | Назначение |
| :--- | :--- |
| `s3://bucket/path` | AWS S3 (credentials через `-credsFilePath`, env vars или IAM роли) |
| `gs://bucket/path` | Google Cloud Storage (credentials через `-credsFilePath` или env vars) |
| `azblob://container/path` | Azure Blob Storage (credentials через env vars `AZURE_STORAGE_ACCOUNT_NAME` + `AZURE_STORAGE_ACCOUNT_KEY`) |
| `fs:///path/to/backup` | Локальная ФС или смонтированный NFS/диск |
| `s3://...` + `-customS3Endpoint` | MinIO, Ceph, Yandex Object Storage, DigitalOcean Spaces и пр. |

### Алгоритм работы vmbackup

1. Создаёт instant snapshot через `-snapshot.createURL`.
2. Собирает информацию о файлах в снапшоте, в `-dst` и в `-origin` (если указан).
3. Удаляет из `-dst` файлы, которых нет в снапшоте (обычно мелкие файлы, объединённые в более крупные).
4. Определяет файлы из снапшота, которых нет в `-dst` (новые и объединённые файлы).
5. Копирует существующие в `-origin` файлы через server-side copy (без скачивания).
6. Загружает оставшиеся файлы из снапшота в `-dst`.
7. Удаляет созданный снапшот.

Файлы разбиваются на чанки размером **1 GiB** — это баланс между количеством файлов и объёмом повторной передачи при ошибках.

### Восстановление (vmrestore)

```bash
# 1) Остановить victoria-metrics
systemctl stop victoria-metrics

# 2) Восстановить данные в пустой (или тот же) каталог
vmrestore -storageDataPath=/var/lib/victoria-metrics \
  -src=s3://my-backups/victoria-metrics
# → последний бэкап (инкремент + базовый) применяется автоматически

# 3) Запустить сервис с тем же -storageDataPath
systemctl start victoria-metrics
```

Ключевые флаги:
- `-src` — источник (тот же формат, что `-dst` для vmbackup): `s3://`, `gs://`, `azblob://`, `fs://`
- `-storageDataPath` — куда восстанавливать данные
- `-skipBackupCompleteCheck` (v1.139.0+) — пропустить проверку файла `backup complete` в `-src`, полезно для восстановления из старых бэкапов
- `-concurrency` — число параллельных воркеров (по умолчанию 10)
- `-maxBytesPerSecond` — ограничение скорости загрузки (0 = без ограничения)

`-storageDataPath` может быть не пустым — содержимое синхронизируется с `-src` (как `rsync --delete`).

## 3. Требования к окружению

### Права доступа

- vmbackup требует **чтения** каталога `-storageDataPath` и права на создание снапсотов через API VictoriaMetrics.
- vmrestore требует **записи** в `-storageDataPath` и доступа к `-src`.
- VictoriaMetrics должен быть **остановлен** до начала vmrestore (иначе возможно повреждение данных).
- vmbackup не требует остановки сервиса — данные копируются из снапсота.

### Хранилище

- `-dst` для vmbackup не должен совпадать с `-storageDataPath` (vmbackup это проверяет и отказывается).
- Для `fs://` бэкапов — целевой диск должен иметь достаточно места. vmbackup сравнивает с `-dst` и удаляет лишние файлы.
- Для S3-совместимых хранилищ важно: `-s3ForcePathStyle=true` (по умолчанию) для MinIO и подобных.

### Сеть

- Доступ к API VictoriaMetrics на порту `8428` (single-node) или `8482` (vmstorage в cluster).
- Доступ к объектному хранилищу (обход файрволов, VPC-маршруты к S3/GCS/Azure).

## 4. Практические сценарии

### 1. Еженочный бэкап в S3 (systemd timer + credentials file)

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP="s3://backups/victoria-metrics/prod"
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst="$BACKUP/latest" \
  -credsFilePath=/etc/victoriametrics/s3-creds \
  -concurrency=8 \
  -maxBytesPerSecond=100MB
```

Файл `/etc/victoriametrics/s3-creds` в формате AWS credentials:
```ini
[default]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
```

Первый запуск — full backup; последующие — только дельта (инкремент).

### 2. Smart backup (hourly + daily) в S3

```bash
# Ежечасно — инкремент в /latest/
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst=s3://backups/vm/latest

# Ежедневно — server-side copy из /latest/ в /YYYYMMDD/
vmbackup \
  -origin=s3://backups/vm/latest \
  -dst=s3://backups/vm/$(date +%Y%m%d)
```

Допускается восстановление из любого дневного слота или последнего hourly.

### 3. Локальный бэкап на отдельный диск (без облака)

```bash
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst=fs:///mnt/backup/victoria-metrics
```

### 4. Бэкап в S3 с кастомным эндпоинтом (MinIO)

```bash
vmbackup \
  -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst=s3://victoriametrics-backups/prod \
  -customS3Endpoint=http://minio.local:9000 \
  -s3ForcePathStyle=true
# → для учёта MinIO: endpoint через -customS3Endpoint, а не -s3.endpoint
```

### 5. Cluster: поузловый бэкап всех vmstorage

Каждый `vmstorage` бэкапится отдельно — данные не реплицируются между нодами (replication обеспечиваетfault tolerance, а не резервное копирование):

```bash
for i in 0 1 2; do
  vmbackup \
    -storageDataPath=/var/lib/vmstorage-$i \
    -snapshot.createURL=http://vmstorage-$i:8482/snapshot/create \
    -dst=s3://backups/victoria-cluster/$i/latest
done
```

Восстановление кластера — поузловое через vmrestore на каждый `-storageDataPath`, затем запуск всех компонентов в том же составе.

### 6. Автоматическая проверка бэкапа и тест восстановления

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

### 7. VictoriaLogs: бэкап и восстановление

```bash
# Бэкап (single-node VictoriaLogs на порту 9428)
vmbackup \
  -storageDataPath=/var/lib/victoria-logs \
  -snapshot.createURL=http://localhost:9428/snapshot/create \
  -dst=s3://backups/victoria-logs/latest

# Восстановление
vmrestore \
  -storageDataPath=/var/lib/victoria-logs \
  -src=s3://backups/victoria-logs/latest
```

## 5. Операции и команды

### vmbackup — ключевые флаги

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `-storageDataPath` | Путь к данным VM (vmsingle/vmstorage/VictoriaLogs) | — |
| `-snapshot.createURL` | URL создания снапсота (`http://host:8428/snapshot/create`) | — |
| `-dst` | Куда сохранять бэкап (`s3://`, `gs://`, `azblob://`, `fs://`) | — |
| `-origin` | Source для server-side copy (ускоряет full backup) | пусто |
| `-credsFilePath` | Путь к файлу credentials (AWS/GCS формат) | — |
| `-customS3Endpoint` | Кастомный S3 эндпоинт (MinIO, Ceph) | пусто |
| `-s3ForcePathStyle` | Использовать path-style для S3 | `true` |
| `-concurrency` | Число параллельных воркеров загрузки | 10 |
| `-maxBytesPerSecond` | Ограничение скорости | 0 (без лимита) |
| `-filestream.disableFadvise` | Отключить fadvise() при чтении больших файлов | `false` |
| `-skipBackupCompleteCheck` | Пропустить проверку `backup complete` в `-src` | `false` |
| `-deleteAllObjectVersions` | Удалить все версии объектов при cleanup | `false` |
| `-s3SSEKMSKeyId` | SSE KMS Key ID для S3 | пусто |
| `-s3SkipTaggingDirective` | Пропустить x-amz-tagging-directive при копировании | `false` |
| `-s3StorageClass` | Storage Class для объектов в S3 | пусто |
| `-s3TLSInsecureSkipVerify` | Пропустить TLS-проверку для S3 эндпоинта | `false` |

### vmrestore — ключевые флаги

| Флаг | Описание | По умолчанию |
| :--- | :--- | :--- |
| `-src` | Источник бэкапа (`s3://`, `gs://`, `azblob://`, `fs://`) | — |
| `-storageDataPath` | Куда восстанавливать данные | `victoria-metrics-data` |
| `-credsFilePath` | Путь к файлу credentials | — |
| `-customS3Endpoint` | Кастомный S3 эндпоинт | пусто |
| `-concurrency` | Число параллельных воркеров | 10 |
| `-maxBytesPerSecond` | Ограничение скорости загрузки | 0 |
| `-skipBackupCompleteCheck` | Пропустить проверку `backup complete` | `false` |
| `-deleteAllObjectVersions` | Удалить все версии объектов | `false` |
| `-s3ForcePathStyle` | Path-style для S3 | `true` |

### vmbackupmanager — CLI команды

```
vmbackupmanager backup            # управление бэкапами
vmbackupmanager backup list       # список бэкапов в хранилище
vmbackupmanager backup lock       # заблокировать бэкап от удаления
vmbackupmanager backup unlock     # разблокировать бэкап
vmbackupmanager restore           # восстановление по restore mark
vmbackupmanager restore create    # создать restore mark
vmbackupmanager restore get       # получить restore mark
vmbackupmanager restore delete    # удалить restore mark
```

### API vmbackupmanager (порт :8300)

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| POST | `/api/v1/backups` | Создать бэкап |
| GET | `/api/v1/backups` | Список бэкапов |
| PUT | `/api/v1/backups/<name>` | Обновить атрибут `locked` |
| POST | `/api/v1/restore` | Установить restore mark |
| GET | `/api/v1/restore` | Получить restore mark |
| DELETE | `/api/v1/restore` | Удалить restore mark |

## 6. Валидация установки

### Создание снапсота вручную

```bash
# Создать снапсот (мгновенно, без остановки)
curl -s http://localhost:8428/snapshot/create | jq .
# → {"status":"ok","snapshot":"20260922T123456.789"}

# Список снапсотов
curl -s http://localhost:8428/snapshot/list | jq .

# Удаление неиспользуемого снапсота
curl -s -XDELETE http://localhost:8428/snapshot/20260922T123456.789 | jq .
```

### Проверка восстановления

```bash
# 1) Восстановить в временный каталог
TMP=$(mktemp -d)
vmrestore -storageDataPath="$TMP" -src=s3://backups/victoria-metrics/latest

# 2) Запустить теневой инстанс
victoria-metrics -storageDataPath="$TMP" -httpListenAddr=:8499 -retentionPeriod=1d &
sleep 10

# 3) Проверить health и данные
curl -sf http://localhost:8499/health
curl -sf 'http://localhost:8499/api/v1/query?query=count(up)' | jq .

# 4) Очистка
kill %1; rm -rf "$TMP"
```

### Мониторинг vmbackupmanager

`vmbackupmanager` экспортирует метрики на `:8300/metrics`. Ключевые метрики:

| Метрика | Описание |
| :--- | :--- |
| `vm_backup_last_success_at{type="daily"}` | Unix timestamp последнего успешного бэкапа (v1.149.0+). `0` если ошибка. |
| `vm_backup_last_run_failed{type="daily"}` | `1` если последняя задача бэкапа заверилась ошибкой |
| `vm_backup_errors_total{type="daily"}` | Общее число ошибок бэкапа этого типа |

## 7. Безопасность

### Управление credentials

- **AWS S3:** используйте `-credsFilePath` с файлом `~/.aws/credentials` или IAM роли (для EC2/ECS). Не передавайте ключи в командной строке — они попадут в `ps` и историю bash.
- **GCS:** `-credsFilePath` с service account JSON или `GOOGLE_APPLICATION_CREDENTIALS` env var.
- **Azure:** env vars `AZURE_STORAGE_ACCOUNT_NAME` и `AZURE_STORAGE_ACCOUNT_KEY`.
- **Kubernetes:** используйте Secrets для хранения credentials и inject через env vars или volume mount.

### Права доступа к хранилищу

- vmbackup требует прав на: `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`, `s3:DeleteObject` для S3.
- Для server-side copy (`-origin`): дополнительно `s3:GetObject` и `s3:PutObject` на целевой bucket.
- vmrestore требует прав на чтение (`s3:GetObject`, `s3:ListBucket`) и запись в `-storageDataPath`.

### Защита endpoint

- `/snapshot/create` не должен быть доступен из интернета — используйте [vmauth](./vmauth_overview.md) или обратный прокси для защиты (см. [security.md](./security.md)).

## 8. Процедура обновления и откат

### Обновление vmbackup/vmrestore

Утилиты поставляются в том же релиозе, что и VictoriaMetrics. Скачивают с [releases page](https://github.com/VictoriaMetrics/VictoriaMetrics/releases):

```bash
VL_VERSION="v1.154.0"
wget "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VL_VERSION}/vmutils-linux-amd64-${VL_VERSION}.tar.gz"
tar xzf vmutils-linux-amd64-${VL_VERSION}.tar.gz
sudo cp vmbackup vmrestore vmbackupmanager /usr/local/bin/
```

### Обновление VictoriaMetrics перед бэкапом

Перед major-апгрейдом обязательно создавайте снапсот. vmbackup инкрементален, но восстановление требует остановки сервиса — планируйте окно:

```bash
# 1. Снапсот
curl -s http://localhost:8428/snapshot/create | jq -r '.status'

# 2. Бэкап
vmbackup -storageDataPath=/var/lib/victoria-metrics \
  -snapshot.createURL=http://localhost:8428/snapshot/create \
  -dst=s3://backups/vm/prod/$(date +%Y%m%d) \
  -credsFilePath=/etc/victoriametrics/s3-creds

# 3. Очистка снапсота (если vmbackup не удалил автоматически)
curl -s -XDELETE http://localhost:8428/snapshot/20240125... | jq .
```

## 9. Отладка и устранение неисполнимостей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| vmbackup ошибка авторизации S3 | Неверные креды/регион/эндпоинт | Использовать `-credsFilePath`, проверить `-customS3Endpoint` для MinIO |
| «snapshot not found» | Снапсот удалён до копирования | Не удалять снапсоты вручную раньше времени; настроить авто-удаление |
| Восстановление даёт неполные данные | Не вся цепочка бэкапов в `-src` | vmrestore собирает инкремент сам; не удаляйте ранние бэкапы из `-src` |
| VM не стартует после vmrestore | Каталог занят/неверный `-storageDataPath` | Остановить сервис до vmrestore; запускать строго с тем же путём |
| Много снапсотов накапливается | Нет чистки после прерванного vmbackup | Вручную удалить старые снапсоты из `snapshots/` |
| Бэкап медленный | Мало воркеров | Увеличить `-concurrency` |
| vmbackup «съедает» всю сеть/CPU | Нет лимитов | `-maxBytesPerSecond`, `-concurrency`, `-filestream.disableFadvise` |
| vmbackupmanager не бэкапит | `-snapshot.createURL` неверный/нет прав | Проверить доступ к snapshot-эндпоинту |
| Восстановление из старого бэкапа без `backup complete` | Файл отсутствует в старом бэкапе | Добавить `-skipBackupCompleteCheck` |
| Данные исчезли после restore | vmrestore на не пустой каталог с конфликтом | Всегда используйте чистый или синхронизируемый каталог |

### Отладка скорости

```bash
# Проверить, какие файлы vmbackup загружает в данный момент
strace -p $(pidof vmbackup) -e trace=open,sendto -f 2>&1 | head

# Профилирование через pprof (если включено)
curl -s http://localhost:8421/debug/pprof/profile?seconds=10 -o cpu.prof
```

## 10. Рекомендации по эксплуатации

### План резервного копирования

- **Full backup** — раз в неделю/месяц (через `-origin` от последнего daily).
- **Incremental/hourly** — каждые 1–24 часа в `/latest/`.
- **Daily/weekly/monthly** — server-side copy из `/latest/` в датированную папку.
- **Retention** — хранить не менее 2 недель daily + 1 месяц weekly + 3–6 месяцев monthly (настраивается через vmbackupmanager или lifecycle rules в S3).

### Лучшие практики

- Делайте бэкап перед major-апгрейдом: инкрементальный, но восстановление требует останова.
- Храните бэкапы в отдельном регионе/zone от продового кластера.
- Тестируйте восстановление регулярно (восстановление в отдельный каталог + запуск на «дренажном» экземпляре).
- Следите за снапсотами в `-storageDataPath/snapshots` — удаляйте после успешного vmbackup.
- Ограничьте скорость (`-maxBytesPerSecond`) во время пиковой нагрузки.
- Используйте `-filestream.disableFadvise` при большом числе CPU и замедлении vmbackup.
- Для retention бэкапов (хранить N дней) используйте Enterprise **vmbackupmanager** или S3 lifecycle rules.
- Не включайте versioning в S3 для `/latest/` — файлы сохраняются с оригинальными timestamps и могут быть удалены правилами lifecycle до необходимого срока.
- Для защиты от случайного удаления используйте `vmbackupmanager backup lock <name>` или S3 Object Lock.

### Очистка окружения

```bash
# Удалить старые снапсоты (если vmbackup не удалил их)
for snap in $(curl -s http://localhost:8428/snapshot/list | jq -r '.snapshots[].name'); do
  curl -s -XDELETE "http://localhost:8428/snapshot/$snap" | jq .
done

# Очистить временный каталог после теста restore
rm -rf "$(mktemp -d)"
```

## 11. Ограничения и особые случаи

- **vmrestore требует остановленного сервиса.** Для минимизации простоя используйте `-replicationFactor≥2` и горячий standby.
- **Shared-Nothing:** в cluster-режиме каждый `vmstorage` бэкапится независимо. Никогда не монтируйте NFS/CIFS как `-storageDataPath` — только для `fs://`-бэкапов на отдельном диске.
- **Смешанные backup/restore:** бэкапы из single-node нельзя восстановить в cluster и наоборот — формат данных несовместим.
- **Downsampled данные (Enterprise):** не «раскручиваются» обратно в полную гранулярность после restore.
- **S3 Glacier/S3 Deep Archive:** server-side copy может быть медленным и дорогим — проверяйте документацию провайдера.
- **Для VictoriaLogs:** снапсот создаётся на порту `9428`, бэкап/восстановление через тот же vmbackup/vmrestore с `-snapshot.createURL=http://localhost:9428/snapshot/create`.

## 12. Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты, порты, флаги;
- [VictoriaMetrics Enterprise: расширенные функции](./enterprise_features.md) — vmbackupmanager, downsampling, retention filters;
- [HTTP API: снапсоты](./http_api_reference.md) — `/snapshot/create`, `/snapshot/list`, `/snapshot/delete`, `/snapshot/delete_all`;
- [DR: аварийное восстановление](./disaster_recovery.md) — сценарии потери нод/кластера, RPO/RTO;
- [Операции с кластером](./cluster_operations.md) — управление vmstorage, replication;
- [vmagent: сбор метрик](./vmagent_overview.md) — для настройки scrape перед бэкапом;
- [Подключение VM к облаку (credentials)](https://docs.victoriametrics.com/guides/connecting-vm-components-to-cloud-storage/) — GGS, S3, Azure, Kubernetes Secrets, IAM роли.
