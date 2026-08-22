# Docker: Стратегия резервного копирования и восстановления

## Определения

- **docker save / docker load** — сериализация и десериализация образов Docker с полным сохранением всех слоёв, тегов, истории сборки и метаданных (ENV, CMD, ENTRYPOINT). `save` создаёт архив формата `tar` из одного или нескольких образов; `load` восстанавливает образы в локальное хранилище Docker. Это **рекомендуемый** метод для переноса и бэкапа образов, так как он сохраняет кэшируемые слои и позволяет эффективно восстанавливать инфраструктуру.

- **docker export / docker import** — операция «сплющивания» (flatten) файловой системы контейнера в архив с одним слоем. `export` создаёт плоский `tar` текущего состояния ФС конкретного контейнера, теряя всю информацию о слоях, истории сборки и метаданных. `import` создаёт **новый** однослойный образ на основе этого архива. Используется для создания «золотых образов» (golden images) или миграции данных, но **не рекомендуется** для полного бэкапа инфраструктуры из-за потери структуры слоёв.

- **Volume Backup (Бэкап тома)** — процесс архивирования данных именованного тома Docker через временный контейнер с монтированием тома в режиме `readonly` и привязкой целевой директории. Наиболее распространённый подход — использование Alpine-контейнера с утилитой `tar` для создания `tar.gz` архива. Этот метод позволяет бэкапить тома без остановки приложений, так как том монтируется как `readonly`.

- **Disaster Recovery (Аварийное восстановление)** — комплексный план и процедуры восстановления Docker-инфраструктуры после катастрофической ошибки (потеря сервера, повреждение диска, случайное удаление). Включает восстановление образов (из реестра или `docker load`), томов (из архивов), конфигурационных файлов (Compose, daemon.json), сетей и сертификатов. Эффективность DR-плана определяется RTO (Recovery Time Objective) и RPO (Recovery Point Objective).

- **Incremental Backup (Инкрементальный бэкап)** — стратегия резервного копирования, при которой архивируются только данные, изменившиеся с момента последнего бэкапа. В контексте Docker томов реализуется через сравнение контрольных сумм файлов или использование механизмов файловых систем (Btrfs snapshots, ZFS snapshots, LVM snapshots). Снижает объём хранилища и время бэкапа, но увеличивает сложность восстановления (требуется полный + инкрементальные архивы).

## Предварительные требования

- **Docker Engine**: версия 20.10+ (для стабильного `--mount` и корректной работы `docker save/load`). На Docker Desktop (Mac/Windows) тома хранятся внутри виртуальной машины; для бэкапа томов рекомендуется использовать Linux-хост или SSH-туннель к VM.
- **Дисковое пространство**: для полного бэкапа необходимо как минимум 2× объём бэкапируемых данных (архив + место для восстановления). Проверка: `docker system df`.
- **Утилиты хоста**: `tar`, `gzip` (или `zstd` для лучшего сжатия), `sha256sum` (для проверки целостности). Для шифрованных бэкапов — `gpg`. Для инкрементальных бэкапов — `rsync` или `rdiff-backup`.
- **Доступ к Docker Socket**: все операции бэкапа выполняются через Docker API (сокет `/var/run/docker.sock` или `DOCKER_HOST`). Отсутствие прав приведёт к `permission denied while trying to connect to the Docker daemon socket`.
- **Сетевой доступ**: для `docker push` в реестр или `docker save/load` через SSH-туннель. Для air-gapped сред — физический носитель (USB/внешний диск).

## Базовые концепции

### 1. Что нужно бэкапить в Docker-инфраструктуре

Полноценная стратегия резервного копирования должна охватывать все компоненты:

| Компонент | Метод бэкапа | Приоритет |
| :--- | :--- | :--- |
| **Тома (Volumes)** | `tar` через Alpine-контейнер | Критический |
| **Образы (Images)** | `docker save` или push в реестр | Высокий |
| **Compose-файлы** | Копирование на файловом уровне | Критический |
| **Daemon config** (`daemon.json`) | Копирование `/etc/docker/` | Средний |
| **Сети (Networks)** | Экспорт через `docker network inspect` | Средний |
| **Сертификаты TLS** | Копирование `/etc/docker/certs.d/` | Высокий |
| **Secrets** | Менеджер секретов (Vault, K8s Secrets) | Критический |
| **Bind mounts** | Копирование исходных директорий | Средний |

> **Критично:** Docker **не бэкапит** записываемый слой (writable layer) контейнера при `docker save`. Если данные хранятся только в контейнере (без тома), они будут потеряны. Всегда используйте тома для персистентных данных.

### 2. docker save/load vs docker export/import

| Критерий | `save` / `load` | `export` / `import` |
| :--- | :--- | :--- |
| **Объект** | Образ (Image) | Контейнер (Container) |
| **Слои** | Сохраняются все слои | Объединяются в один (Flatten) |
| **Метаданные** | Полностью (ENV, CMD, LABEL) | Теряются (требуется `--change`) |
| **Кэширование** | Сохраняется — повторная сборка быстрее | Теряется — все слои пересобираются |
| **Размер архива** | Больше (все слои) | Меньше (один слой) |
| **Назначение** | Перенос образов, DR-бэкап | Миграция ФС, golden images |

**Когда использовать `save/load`:**
- Бэкап и восстановление образов в DR-сценариях
- Перенос в air-gapped среды
- Сохранение образов перед обновлением Docker Engine

**Когда использовать `export/import`:**
- Создание компактных снимков файловой системы
- Миграция данных между кластерами
- Создание базовых образов без истории сборки

### 3. Стратегия бэкапа томов

Основной подход — запуск временного контейнера, который монтирует целевой том как `readonly` и создаёт tar-архив:

```
[Том Docker] -> [Alpine-контейнер (tar)] -> [tar.gz на хосте]
```

**Ключевые аспекты:**
- Том монтируется через `--mount type=volume,source=<name>,target=/data,readonly` — это гарантирует, что бэкап не модифицирует данные.
- Alpine-контейнер используется из-за минимального размера (~5 МБ) и наличия `tar`.
- Архив выводится через bind mount в директорию хоста.
- Для больших томов рекомендуется использовать `pigz` (параллельный gzip) или `zstd` вместо стандартного `gzip`.

**Инкрементальные бэкапы томов:**
Для реализации инкрементального бэкапа необходимо отслеживать изменения файлов. Подходы:
1. **Btrfs/ZFS snapshots**: если тома хранятся на Btrfs/ZFS, создавайте снимки перед бэкапом.
2. **LVM snapshots**: на блочном уровне через `lvcreate --snapshot`.
3. **Сравнение checksums**: сохранение `sha256sum` файлов и сравнение при следующем бэкапе.
4. **rsync --link-dest**: хардлинки для неизменённых файлов (экономия места).

### 4. Шифрование бэкапов

Для защиты конфиденциальных данных в бэкапах:

- **GPG (GNU Privacy Guard)**: симметричное шифрование через `gpg --symmetric --cipher-algo AES256`. Простой и надёжный метод.
- **LUKS**: шифрование на уровне блочного устройства (для зашифрованных томов — бэкап зашифрованного контейнера).
- **OpenSSL**: быстрое шифрование через `openssl enc -aes-256-cbc`.

**Рекомендация:** всегда шифруйте бэкапы, содержащие базы данных, логи или пользовательские данные. Ключи храните отдельно от бэкапов (в менеджере секретов или на внешнем носителе).

### 5. Перенос образов в air-gapped среды

В полностью изолированных сетях (без доступа к интернету) образы доставляются физическим путём:

```
[Интернет-машина] -> docker save -> [USB/диск] -> sha256sum -> [Целевой сервер] -> docker load
```

**Процедура:**
1. Сохранение образов: `docker save -o images.tar image1:tag1 image2:tag2`
2. Проверка целостности: `sha256sum images.tar > images.tar.sha256`
3. Физический перенос на носителе
4. Верификация на целевом сервере: `sha256sum -c images.tar.sha256`
5. Загрузка: `docker load -i images.tar`

Для multi-arch образов рекомендуется использовать `skopeo` или `buildx`, так как `docker save` сохраняет только текущую архитектуру.

### 6. Ретеншн и планирование бэкапов

**Стратегия ретеншна (3-2-1):**
- **3** копии данных (оригинал + 2 бэкапа)
- **2** разных типа носителей (локальный диск + облако/внешний диск)
- **1** копия вне сайта (offsite)

**Расписание (пример):**

| Тип | Частота | Хранение |
| :--- | :--- | :--- |
| Полный бэкап томов | Еженедельно | 4 недели |
| Инкрементальный | Ежедневно | 7 дней |
| Бэкап образов | При изменении | 30 дней |
| Compose-файлы | При изменении | бессрочно |

**Автоматизация через cron:**
```bash
# Ежедневный бэкап в 02:00
0 2 * * * /opt/scripts/docker-backup.sh >> /var/log/docker-backup.log 2>&1
```

## Практические сценарии

### Сценарий 1: Бэкап и восстановление тома (tar.gz через Alpine)

Создание и восстановление резервной копии именованного тома.

**Бэкап:**
```bash
# Бэкап тома my-app-data в файл backup.tar.gz
docker run --rm \
  --mount type=volume,source=my-app-data,target=/data,readonly \
  --mount type=bind,source=$(pwd)/backups,target=/backup \
  alpine \
  tar -czvf /backup/my-app-data-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .

# Проверка архива
ls -lh backups/my-app-data-*.tar.gz
# -> -rw-r--r-- 1 user user 156M Aug 22 02:00 backups/my-app-data-20260822-020000.tar.gz

# Проверка содержимого
tar -tzf backups/my-app-data-20260822-020000.tar.gz | head -5
# -> ./
# -> ./database/
# -> ./database/postgresql.conf
# -> ./database/pg_hba.conf
# -> ./database/base/
```

**Восстановление:**
```bash
# Создание нового тома для восстановления
docker volume create my-app-data-restored

# Восстановление из архива
docker run --rm \
  --mount type=bind,source=$(pwd)/backups/my-app-data-20260822-020000.tar.gz,target=/backup.tar.gz,readonly \
  --mount type=volume,source=my-app-data-restored,target=/data \
  alpine \
  sh -c "tar -xzvf /backup.tar.gz -C /data"

# Проверка восстановленных данных
docker run --rm \
  --mount type=volume,source=my-app-data-restored,target=/data,readonly \
  alpine ls /data/
# -> database/
# -> config/
```

### Сценарий 2: docker save/load для переноса образов

Сохранение и загрузка образов с полным сохранением слоёв и метаданных.

**Сохранение (на машине с интернетом):**
```bash
# Сохранение нескольких образов в один файл
docker save -o app-stack.tar my-app:1.0 postgres:16-alpine redis:7-alpine

# Сохранение сжатого архива (экономия места)
docker save my-app:1.0 | gzip > my-app-1.0.tar.gz

# Проверка размера
ls -lh app-stack.tar
# -> -rw------- 1 user user 1.2G Aug 22 10:00 app-stack.tar

# Проверка целостности
sha256sum app-stack.tar > app-stack.tar.sha256
```

**Загрузка (на целевом сервере):**
```bash
# Проверка суммы перед загрузкой
sha256sum -c app-stack.tar.sha256
# -> app-stack.tar: OK

# Загрузка из несжатого архива
docker load -i app-stack.tar
# -> Loaded image: my-app:1.0
# -> Loaded image: postgres:16-alpine
# -> Loaded image: redis:7-alpine

# Загрузка из сжатого архива
gunzip -c my-app-1.0.tar.gz | docker load
# -> Loaded image: my-app:1.0

# Подтверждение загрузки
docker images my-app
# -> REPOSITORY   TAG    IMAGE ID       CREATED        SIZE
# -> my-app       1.0    a1b2c3d4e5f6   3 days ago     245MB
```

### Сценарий 3: docker export/import для плоских снимков

Создание компактного однослойного образа из состояния контейнера.

**Создание снимка:**
```bash
# Запуск контейнера с данными
docker run -d --name my-database \
  -e POSTGRES_PASSWORD=secret \
  --mount type=volume,source=pg-data,target=/var/lib/postgresql/data \
  postgres:16-alpine

# Создание снимка файловой системы контейнера
docker export my-database | gzip > pg-database-snapshot.tar.gz

# Проверка размера (один слой vs полный образ)
ls -lh pg-database-snapshot.tar.gz
# -> -rw-r--r-- 1 user user 89M Aug 22 11:00 pg-database-snapshot.tar.gz
```

**Восстановление из снимка:**
```bash
# Импорт как новый образ
docker import \
  --change "ENV POSTGRES_PASSWORD=secret" \
  --change 'CMD ["postgres"]' \
  pg-database-snapshot.tar.gz my-pg-restored:latest

# Запуск восстановленного контейнера
docker run -d --name pg-restored \
  -e POSTGRES_PASSWORD=secret \
  my-pg-restored:latest
```

> **Важно:** при `import` теряются метаданные образа (ENV, CMD, ENTRYPOINT). Их необходимо задать заново через `--change`.

### Сценарий 4: Полный бэкап Compose-проекта

Бэкап всех компонентов Compose-проекта: тома, файлы конфигурации, образы.

**Скрипт бэкапа:**
```bash
#!/bin/bash
# full-backup.sh
set -euo pipefail

PROJECT_NAME="my-web-app"
BACKUP_DIR="/backup/${PROJECT_NAME}-$(date +%Y%m%d-%H%M%S)"
COMPOSE_DIR="/opt/${PROJECT_NAME}"

mkdir -p "${BACKUP_DIR}"/{volumes,images,config}

echo "=== Бэкап Compose-файлов ==="
cp "${COMPOSE_DIR}"/docker-compose.yml "${BACKUP_DIR}/config/"
cp -r "${COMPOSE_DIR}"/.env "${BACKUP_DIR}/config/" 2>/dev/null || true
cp -r "${COMPOSE_DIR}"/nginx/ "${BACKUP_DIR}/config/" 2>/dev/null || true

echo "=== Бэкап образов ==="
docker save -o "${BACKUP_DIR}/images/${PROJECT_NAME}.tar" \
  $(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" images -q | sort -u)

echo "=== Бэкап томов ==="
VOLUMES=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" volumes -q)
for VOL in $VOLUMES; do
  docker run --rm \
    --mount type=volume,source=${VOL},target=/data,readonly \
    --mount type=bind,source=${BACKUP_DIR}/volumes,target=/backup \
    alpine \
    tar -czf "/backup/${VOL}.tar.gz" -C /data .
  echo "  Том ${VOL} забэкаплен"
done

echo "=== Проверка целостности ==="
find "${BACKUP_DIR}" -name "*.tar.gz" -exec sha256sum {} \; > "${BACKUP_DIR}/checksums.sha256"

echo "=== Бэкап завершён: ${BACKUP_DIR} ==="
du -sh "${BACKUP_DIR}"
```

**Восстановление:**
```bash
#!/bin/bash
# full-restore.sh
set -euo pipefail

BACKUP_DIR="$1"
COMPOSE_DIR="/opt/my-web-app"

for img in "${BACKUP_DIR}"/images/*.tar; do
  docker load -i "${img}"
done

for vol_archive in "${BACKUP_DIR}"/volumes/*.tar.gz; do
  VOL_NAME=$(basename "${vol_archive}" .tar.gz)
  docker volume create "${VOL_NAME}"
  docker run --rm \
    --mount type=bind,source="${vol_archive}",target=/backup.tar.gz,readonly \
    --mount type=volume,source=${VOL_NAME},target=/data \
    alpine \
    sh -c "tar -xzf /backup.tar.gz -C /data"
done

cp -r "${BACKUP_DIR}/config/"* "${COMPOSE_DIR}/"

cd "${COMPOSE_DIR}" && docker compose up -d
```

### Сценарий 5: Шифрованный бэкап с GPG

Создание зашифрованного архива для защиты конфиденциальных данных.

**Создание зашифрованного бэкапа:**
```bash
# Бэкап тома с шифрованием через GPG
docker run --rm \
  --mount type=volume,source=prod-db-data,target=/data,readonly \
  --mount type=bind,source=$(pwd)/backups,target=/backup \
  alpine \
  tar -czf - -C /data . | \
  gpg --symmetric --cipher-algo AES256 \
    --passphrase-file /secure/passphrase.txt \
    -o backups/prod-db-$(date +%Y%m%d).tar.gz.gpg

# Проверка размера зашифрованного архива
ls -lh backups/prod-db-*.tar.gz.gpg
# -> -rw-r--r-- 1 user user 210M Aug 22 12:00 backups/prod-db-20260822.tar.gz.gpg

# Бэкап нескольких томов с шифрованием
for VOL in postgres-data redis-data minio-data; do
  docker run --rm \
    --mount type=volume,source=${VOL},target=/data,readonly \
    --mount type=bind,source=$(pwd)/backups,target=/backup \
    alpine \
    tar -czf - -C /data . | \
    gpg --symmetric --cipher-algo AES256 \
      --passphrase-file /secure/passphrase.txt \
      -o "backups/${VOL}-$(date +%Y%m%d).tar.gz.gpg"
done
```

**Расшифровка и восстановление:**
```bash
# Расшифровка архива
gpg --decrypt --batch --passphrase-file /secure/passphrase.txt \
  backups/prod-db-20260822.tar.gz.gpg > /tmp/prod-db.tar.gz

# Восстановление
docker volume create prod-db-restored
docker run --rm \
  --mount type=bind,source=/tmp/prod-db.tar.gz,target=/backup.tar.gz,readonly \
  --mount type=volume,source=prod-db-restored,target=/data \
  alpine \
  sh -c "tar -xzf /backup.tar.gz -C /data"

# Очистка временного файла
shred -u /tmp/prod-db.tar.gz
```

### Сценарий 6: Air-gapped перенос образов (save -> USB -> load)

Процедура доставки образов в полностью изолированную среду.

**На машине с интернетом:**
```bash
# 1. Сохранение всех необходимых образов
docker save \
  -o /mnt/usb/docker-images-$(date +%Y%m%d).tar \
  nginx:1.25-alpine \
  postgres:16-alpine \
  redis:7-alpine \
  my-app:2.1.0 \
  alpine:3.19

# 2. Проверка целостности
sha256sum /mnt/usb/docker-images-*.tar > /mnt/usb/docker-images.sha256

# 3. Извлечение USB
echo "Архив создан. Проверьте sha256sum и извлеките носитель."
cat /mnt/usb/docker-images.sha256
```

**На целевом сервере (air-gapped):**
```bash
# 1. Подключение USB и копирование
cp /mnt/usb/docker-images-20260822.tar /tmp/

# 2. Верификация целостности
sha256sum -c /mnt/usb/docker-images.sha256
# -> docker-images-20260822.tar: OK

# 3. Загрузка образов
docker load -i /tmp/docker-images-20260822.tar
# -> Loaded image: nginx:1.25-alpine
# -> Loaded image: postgres:16-alpine
# -> Loaded image: redis:7-alpine
# -> Loaded image: my-app:2.1.0
# -> Loaded image: alpine:3.19

# 4. Проверка
docker images
# -> REPOSITORY    TAG           IMAGE ID       CREATED        SIZE
# -> nginx         1.25-alpine   021283c8eb95   2 weeks ago    42MB
# -> postgres      16-alpine     7e83fb038a7c   1 week ago     235MB
# -> redis         7-alpine      4d1e0a438b2e   3 days ago     32MB
# -> my-app        2.1.0         a1b2c3d4e5f6   5 days ago     245MB
# -> alpine        3.19          123456789abc   1 month ago    7MB

# 5. Очистка
rm /tmp/docker-images-20260822.tar
```

### Сценарий 7: Автоматизированный скрипт бэкапа (cron + ротация)

Полностью автоматизированный скрипт с ротацией старых бэкапов.

```bash
#!/bin/bash
# /opt/scripts/docker-backup.sh
set -euo pipefail

# === Конфигурация ===
BACKUP_ROOT="/backup/docker"
LOG_FILE="/var/log/docker-backup.log"
RETENTION_DAYS=7
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${DATE}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

mkdir -p "${BACKUP_DIR}"

log "=== Начало бэкапа ==="

# === Бэкап всех именованных томов ===
VOLUMES=$(docker volume ls -q --filter "dangling=false")
TOTAL_VOLUMES=$(echo "${VOLUMES}" | wc -l | tr -d ' ')
log "Найдено томов: ${TOTAL_VOLUMES}"

COUNT=0
for VOL in ${VOLUMES}; do
  COUNT=$((COUNT + 1))
  log "  [${COUNT}/${TOTAL_VOLUMES}] Бэкап тома: ${VOL}"

  docker run --rm \
    --mount type=volume,source=${VOL},target=/data,readonly \
    --mount type=bind,source=${BACKUP_DIR},target=/backup \
    alpine \
    tar -czf "/backup/${VOL}.tar.gz" -C /data . 2>> "${LOG_FILE}"

  SIZE=$(ls -lh "${BACKUP_DIR}/${VOL}.tar.gz" | awk '{print $5}')
  log "    Размер: ${SIZE}"
done

# === Бэкап Compose-проектов ===
COMPOSE_PROJECTS=$(find /opt -name "docker-compose.yml" -o -name "docker-compose.yaml" 2>/dev/null || true)
for COMPOSE_FILE in ${COMPOSE_PROJECTS}; do
  PROJECT_DIR=$(dirname "${COMPOSE_FILE}")
  PROJECT_NAME=$(basename "${PROJECT_DIR}")
  log "  Бэкап Compose-проекта: ${PROJECT_NAME}"

  mkdir -p "${BACKUP_DIR}/compose/${PROJECT_NAME}"
  cp "${COMPOSE_FILE}" "${BACKUP_DIR}/compose/${PROJECT_NAME}/"
  cp "${PROJECT_DIR}/.env" "${BACKUP_DIR}/compose/${PROJECT_NAME}/" 2>/dev/null || true
done

# === Генерация контрольных сумм ===
log "Генерация checksums..."
find "${BACKUP_DIR}" -name "*.tar.gz" -exec sha256sum {} \; > "${BACKUP_DIR}/checksums.sha256"

# === Ротация старых бэкапов ===
log "Ротация бэкапов старше ${RETENTION_DAYS} дней..."
find "${BACKUP_ROOT}" -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \; 2>/dev/null || true

# === Итог ===
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | awk '{print $1}')
log "=== Бэкап завершён ==="
log "Директория: ${BACKUP_DIR}"
log "Общий размер: ${TOTAL_SIZE}"

DISK_USAGE=$(df -h "${BACKUP_ROOT}" | tail -1 | awk '{print $5}' | tr -d '%')
if [ "${DISK_USAGE}" -gt 85 ]; then
  log "ВНИМАНИЕ: Использование диска ${DISK_USAGE}%!"
fi
```

**Установка через cron:**
```bash
chmod +x /opt/scripts/docker-backup.sh

# Добавление в crontab (ежедневно в 02:00)
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/scripts/docker-backup.sh >> /var/log/docker-backup.log 2>&1") | crontab -

crontab -l
# -> 0 2 * * * /opt/scripts/docker-backup.sh >> /var/log/docker-backup.log 2>&1
```

### Сценарий 8: Верификация восстановления из бэкапа

Проверка корректности бэкапа перед реальным инцидентом.

```bash
#!/bin/bash
# /opt/scripts/verify-backup.sh
set -euo pipefail

BACKUP_DIR="$1"
VERIFY_DIR="/tmp/backup-verify-$$"
LOG_FILE="/var/log/backup-verify.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

mkdir -p "${VERIFY_DIR}"

log "=== Верификация бэкапа: ${BACKUP_DIR} ==="

# 1. Проверка checksums
log "Проверка контрольных сумм..."
if sha256sum -c "${BACKUP_DIR}/checksums.sha256" > /dev/null 2>&1; then
  log "  OK: все checksums совпадают"
else
  log "  ОШИБКА: контрольные суммы не совпадают!"
  exit 1
fi

# 2. Проверка архивов (целостность tar)
log "Проверка целостности tar-архивов..."
for ARCHIVE in "${BACKUP_DIR}"/*.tar.gz; do
  if tar -tzf "${ARCHIVE}" > /dev/null 2>&1; then
    log "  OK: $(basename ${ARCHIVE})"
  else
    log "  ОШИБКА: $(basename ${ARCHIVE}) — повреждён!"
    exit 1
  fi
done

# 3. Тестовое восстановление тома
for ARCHIVE in "${BACKUP_DIR}"/*.tar.gz; do
  VOL_NAME=$(basename "${ARCHIVE}" .tar.gz)
  TEST_VOL="verify-${VOL_NAME}-$$"

  docker volume create "${TEST_VOL}" > /dev/null
  docker run --rm \
    --mount type=bind,source="${ARCHIVE}",target=/backup.tar.gz,readonly \
    --mount type=volume,source=${TEST_VOL},target=/data \
    alpine \
    sh -c "tar -xzf /backup.tar.gz -C /data" 2>/dev/null

  FILE_COUNT=$(docker run --rm \
    --mount type=volume,source=${TEST_VOL},target=/data,readonly \
    alpine sh -c "find /data -type f | wc -l" | tr -d ' ')

  log "  OK: ${VOL_NAME} — файлов: ${FILE_COUNT}"

  docker volume rm "${TEST_VOL}" > /dev/null
done

log "=== Верификация завершена успешно ==="
rm -rf "${VERIFY_DIR}"
```

### Сценарий 9: Бэкап базы данных (PostgreSQL pg_dump в контейнере)

Специализированный бэкап PostgreSQL с использованием `pg_dump` внутри контейнера.

**Создание логического бэкапа:**
```bash
# Полный дамп базы данных
docker exec my-postgres \
  pg_dump -U postgres -d myapp \
  --format=custom \
  --compress=6 \
  --file=/tmp/myapp-$(date +%Y%m%d).dump

# Копирование дампа из контейнера
docker cp my-postgres:/tmp/myapp-20260822.dump ./backups/

# Бэкап всех баз данных
docker exec my-postgres \
  pg_dumpall -U postgres | gzip > ./backups/all-databases-$(date +%Y%m%d).sql.gz

# Бэкап с шифрованием
docker exec my-postgres \
  pg_dump -U postgres -d myapp --format=custom | \
  gpg --symmetric --cipher-algo AES256 \
    --passphrase-file /secure/pg-passphrase.txt \
    -o ./backups/myapp-$(date +%Y%m%d).dump.gpg
```

**Восстановление PostgreSQL:**
```bash
# Расшифровка (если зашифрован)
gpg --decrypt --batch --passphrase-file /secure/pg-passphrase.txt \
  ./backups/myapp-20260822.dump.gpg > /tmp/myapp.dump

# Восстановление из custom dump
docker exec -i my-postgres \
  pg_restore -U postgres -d myapp --clean --if-exists < /tmp/myapp.dump

# Восстановление из SQL dump
gunzip -c ./backups/all-databases-20260822.sql.gz | \
  docker exec -i my-postgres psql -U postgres

# Очистка
shred -u /tmp/myapp.dump
```

**Комбинированный бэкап (volume + pg_dump):**
```bash
#!/bin/bash
# postgres-full-backup.sh
set -euo pipefail

DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/backup/postgres/${DATE}"

mkdir -p "${BACKUP_DIR}"

# 1. Логический дамп (для восстановления на другую версию PostgreSQL)
docker exec my-postgres \
  pg_dump -U postgres --format=custom --compress=6 \
  --file=/tmp/pg-full-${DATE}.dump

docker cp my-postgres:/tmp/pg-full-${DATE}.dump "${BACKUP_DIR}/"

# 2. Физический бэкап тома (для быстрого восстановления на ту же версию)
docker run --rm \
  --mount type=volume,source=pg-data,target=/data,readonly \
  --mount type=bind,source=${BACKUP_DIR},target=/backup \
  alpine \
  tar -czf "/backup/pg-data-${DATE}.tar.gz" -C /data .

# 3. Контрольные суммы
sha256sum "${BACKUP_DIR}"/* > "${BACKUP_DIR}/checksums.sha256"

echo "Бэкап завершён: ${BACKUP_DIR}"
du -sh "${BACKUP_DIR}"
```

## Дополнительная информация

### Связанные документы

- **[Docker: Тома и персистентное хранение данных](./docker_volumes.md)** — типы монтирования, управление томами, mounts.
- **[Docker: Перенос и экспорт образов](./images/diagnostics_transfer.md)** — `docker save/load`, `docker export/import`, OCI Archive, air-gapped перенос.
- **[Docker: Шифрование томов](./volume_encryption.md)** — LUKS, fscrypt, облачное шифрование, управление ключами.
- **[Docker: Драйвер хранения OverlayFS](./docker_overlayfs.md)** — механизм CoW, записываемый слой, производительность.

### Что НЕ бэкапится автоматически

| Компонент | Причина | Решение |
| :--- | :--- | :--- |
| **Записываемый слой контейнера** | `docker save` работает с образами, не контейнерами | Используйте тома для всех персистентных данных |
| **Остановленные контейнеры** | Их конфигурация хранится в metadata Docker | Экспортируйте через `docker inspect` |
| **Сети Docker** | Настраиваются декларативно | Сохраняйте `docker network inspect` вывод |
| **Привилегии и capabilities** | Не отражены в образе | Документируйте в Compose-файле или скриптах |
| **Пользовательские bridge-сети** | Привязаны к хосту | Экспортируйте конфигурацию через API |

### Оценка размера бэкапа

```bash
# Размер всех томов
docker system df -v

# Размер отдельного тома
du -sh /var/lib/docker/volumes/<volume-name>/_data

# Размер образов (с учётом общих слоёв)
docker system df

# Размер архива тома (примерная оценка)
docker run --rm \
  --mount type=volume,source=<volume>,target=/data,readonly \
  alpine du -sh /data
```

**Формула оценки:**
```
Размер бэкапа = (Размер тома + Размер метаданных) x Коэффициент сжатия
Коэффициент сжатия gzip = ~0.3-0.7 (зависит от типа данных)
Коэффициент сжатия zstd = ~0.2-0.5 (лучше для текстовых данных)
```

> **Важно:** при бэкапе через `docker save` с учётом общих слоёв размер архива может быть значительно меньше суммарного размера образов. Docker автоматически дедуплицирует общие слои в tar-архиве.

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`permission denied while trying to connect to the Docker daemon socket`** | Текущий пользователь не в группе `docker` | `sudo usermod -aG docker $USER` или выполнение от `root` |
| **`Error: No such volume` при `docker run --mount`** | Опечатка в имени тома | Проверьте `docker volume ls` |
| **`tar: Error is not recoverable: exiting now`** | Архив повреждён или не полностью записан | Проверьте свободное место, повторите бэкап |
| **Бэкап весит больше ожидаемого** | Сжатие не применяется или данные плохо сжимаются | Используйте `zstd` вместо `gzip` для текстовых данных |
| **`docker load` не находит образ** | Архив повреждён или создан другим инструментом | Проверьте `tar -tzf` перед загрузкой |
| **`gpg: decryption failed: No secret key`** | Неверный ключ или passphrase | Проверьте ключевую непосредственность, попробуйте `--batch` |
| **Бэкап тома с open source БД повреждён** | БД писала данные во время бэкапа | Остановите БД или используйте `pg_dump` / `mysqldump` |
| **Скрипт cron не выполняется** | Нет прав на Docker socket | Запускайте скрипт от `root` или добавьте пользователя в группу `docker` |
| **Ротация удаляет все бэкапы** | Неправильный `find` с `-mtime` | Используйте `-maxdepth 1` для точечного удаления |

### Best Practices

1. **Всегда проверяйте целостность бэкапа** после создания (`sha256sum` + `tar -tzf`).
2. **Тестируйте восстановление** регулярно (минимум раз в квартал).
3. **Шифруйте бэкапы** с конфиденциальными данными (GPG, LUKS).
4. **Храните ключи шифрования отдельно** от бэкапов (в менеджере секретов или на внешнем носителе).
5. **Используйте именованные тома** вместо анонимных — их легче бэкапить и идентифицировать.
6. **Документируйте процедуру восстановления** — в критической ситуации не должно быть сюрпризов.
7. **Настраивайте мониторинг** свободного места для бэкапов.
8. **Используйте `pigz` или `zstd`** вместо `gzip` для ускорения сжатия больших томов.
9. **Разделяйте бэкапы данных и образов** — они имеют разную частоту изменения и разный приоритет.
10. **Храните Compose-файлы в git** для отслеживания изменений конфигурации.

