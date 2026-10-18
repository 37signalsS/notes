# Backup и восстановление SaltStack

**Актуально для:** Salt 3008.x

## Определения

- **PKI Backup**: Резервное копирование ключей PKI (`/etc/salt/pki/`) для восстановления аутентификации миньонов.
- **file_roots Backup**: Резервное копирование файлового сервера Salt (`/srv/salt/`) со всеми SLS-файлами, формулами и конфигурациями.
- **pillar_roots Backup**: Резервное копирование Pillar данных (`/srv/pillar/`) со всеми секретами и конфигурациями.
- **Job Cache Backup**: Резервное копирование истории заданий (PostgreSQL, Redis, Elasticsearch).
- **Master Config Backup**: Резервное копирование конфигурации мастера (`/etc/salt/master` и `master.d/`).
- **Disaster Recovery (DR)**: Процесс восстановления Salt infrastructure после катастрофы (потеря мастера, повреждение данных).
- **Backup Verification**: Проверка целостности и восстанавливаемости резервных копий.
- **Retention Policy**: Политика хранения резервных копий (количество копий, сроки хранения).

---

## Основные концепции

### Что бэкапить

| Компонент | Путь | Важность | Частота |
|:---|:---|:---|:---|
| **PKI Keys** | `/etc/salt/pki/master/` | Критично | Ежедневно |
| **Master Config** | `/etc/salt/master`, `/etc/salt/master.d/` | Высокая | Ежедневно |
| **file_roots** | `/srv/salt/` | Высокая | Ежедневно |
| **pillar_roots** | `/srv/pillar/` | Критично | Ежедневно |
| **Job Cache** | PostgreSQL/Redis | Средняя | Ежедневно |
| **GitFS Cache** | `/var/cache/salt/master/gitfs/` | Средняя | Еженедельно |
| **Roster** | `/etc/salt/roster` | Средняя | Ежедневно |

### Стратегии бэкапа

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **Full Backup** | Полная копия всех данных | Ежедневно/Еженедельно |
| **Incremental** | Только изменения с последнего бэкапа | Ежедневно |
| **Differential** | Все изменения с последнего full | Ежедневно |

---

## Предпосылки и требования

Перед настройкой резервного копирования SaltStack убедитесь в следующем:

| Требование | Детали |
|:---|:---|
| **Привилегии** | Root или sudo-доступ на Salt Master для чтения `/etc/salt/pki/` и `/srv/salt/` |
| **Дисковое пространство** | PKI: ~10 МБ, file_roots: зависит от формул (рекомендуется 100+ МБ), pillar_roots: 1–10 МБ, job cache: зависит от объёма истории |
| **Клиент PostgreSQL** | Для бэкапа job cache: `postgresql-client` или `pg_dump` в PATH |
| **Доступ к PostgreSQL** | Пользователь `salt` с паролем или через trust-аутентификацию; pg_dump должен иметь права на чтение базы `salt` |
| **Каталог резервных копий** | `/backup/salt/` с правами записи для root; рекомендуется отдельный диск/том |
| **Шифрование** | Для бэкапов pillar_roots с секретами используйте GPG (`gpg-zip`) или шифруйте на этапе передачи в хранилище |
| **Cron или аналог** | Планировщик для автоматического выполнения скриптов (cron, systemd timers) |
| **Сеть** | Доступ к PostgreSQL на `localhost:5432` или удалённому хосту (для распределённого job cache) |

---

## Практические сценарии

### 1. Бэкап PKI

```bash
#!/bin/bash
# /usr/local/bin/salt_backup_pki.sh

BACKUP_DIR="/backup/salt/pki"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/pki_${DATE}.tar.gz"

mkdir -p "$BACKUP_DIR"

# Бэкап ключей мастера
tar -czf "$BACKUP_FILE" \
    /etc/salt/pki/master/ \
    /etc/salt/pki/minion/ \
    2>/dev/null

# Проверка размера
ls -lh "$BACKUP_FILE"
# → /backup/salt/pki/pki_20260921_020000.tar.gz  12M

# Очистка старых бэкапов (старше 30 дней)
find "$BACKUP_DIR" -name "pki_*.tar.gz" -mtime +30 -delete

# Верификация архива
tar -tzf "$BACKUP_FILE" >/dev/null 2>&1 || echo "WARNING: backup archive corrupted"
```

**Cron:**

```bash
# Ежедневно в 2:00
0 2 * * * /usr/local/bin/salt_backup_pki.sh >> /var/log/salt_backup.log 2>&1
```

### 2. Бэкап file_roots и pillar_roots

```bash
#!/bin/bash
# /usr/local/bin/salt_backup_roots.sh

BACKUP_DIR="/backup/salt/roots"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Бэкап file_roots
tar -czf "${BACKUP_DIR}/file_roots_${DATE}.tar.gz" \
    /srv/salt/ \
    --exclude='*.pyc' \
    --exclude='__pycache__'

# Бэкап pillar_roots
tar -czf "${BACKUP_DIR}/pillar_roots_${DATE}.tar.gz" \
    /srv/pillar/

# Проверка
ls -lh ${BACKUP_DIR}/*_${DATE}.tar.gz
# → /backup/salt/roots/file_roots_20260921_020000.tar.gz  45M
# → /backup/salt/roots/pillar_roots_20260921_020000.tar.gz  2M

# Верификация архивов
tar -tzf ${BACKUP_DIR}/file_roots_${DATE}.tar.gz >/dev/null 2>&1 || echo "WARNING: file_roots archive corrupted"
tar -tzf ${BACKUP_DIR}/pillar_roots_${DATE}.tar.gz >/dev/null 2>&1 || echo "WARNING: pillar_roots archive corrupted"

# Шифрование бэкапа pillar (содержит секреты)
# gpg-zip --encrypt --recipient admin@example.com ${BACKUP_DIR}/pillar_roots_${DATE}.tar.gz
```

### 3. Бэкап конфигурации мастера

```bash
#!/bin/bash
# /usr/local/bin/salt_backup_config.sh

BACKUP_DIR="/backup/salt/config"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Бэкап конфигурации
tar -czf "${BACKUP_DIR}/master_config_${DATE}.tar.gz" \
    /etc/salt/master \
    /etc/salt/master.d/ \
    /etc/salt/minion \
    /etc/salt/minion.d/ \
    2>/dev/null

# Бэкап systemd units
tar -czf "${BACKUP_DIR}/systemd_${DATE}.tar.gz" \
    /etc/systemd/system/salt-*.service \
    2>/dev/null

# Верификация
tar -tzf "${BACKUP_DIR}/master_config_${DATE}.tar.gz" >/dev/null 2>&1 || echo "WARNING: config archive corrupted"
```

### 4. Бэкап Job Cache (PostgreSQL)

```bash
#!/bin/bash
# /usr/local/bin/salt_backup_jobcache.sh

BACKUP_DIR="/backup/salt/jobcache"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Дамп PostgreSQL
pg_dump -U salt -h localhost salt > "${BACKUP_DIR}/jobcache_${DATE}.sql"

# Сжатие
gzip "${BACKUP_DIR}/jobcache_${DATE}.sql"

# Проверка
ls -lh "${BACKUP_DIR}/jobcache_${DATE}.sql.gz"

# Верификация дампа
gunzip -t "${BACKUP_DIR}/jobcache_${DATE}.sql.gz" 2>/dev/null || echo "WARNING: job cache backup corrupted"
```

### 5. Восстановление PKI

```bash
#!/bin/bash
# /usr/local/bin/salt_restore_pki.sh

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file.tar.gz>"
    exit 1
fi

# Остановка сервисов
systemctl stop salt-master
systemctl stop salt-minion

# Восстановление
tar -xzf "$BACKUP_FILE" -C /

# Проверка
ls -la /etc/salt/pki/master/
# → master.pem
# → master.pub
# → master_sign.pem
# → master_sign.pub

# Запуск сервисов
systemctl start salt-master
systemctl start salt-minion

# Приём ключей миньонов (если ключи были потеряны)
salt-key -A --yes

# Проверка
salt '*' test.ping | head -5

# Валидация ключей
ls -la /etc/salt/pki/master/
# → master.pem
# → master.pub
# → master_sign.pem
# → master_sign.pub
# → миньоны/ — каталог с ключами принятых миньонов

# Проверка подключения миньонов
salt '*' test.ping
# → minion1:
#     ----------
#     minion1: True
#   minion2:
#     ----------
#     minion2: True
```

### 6. Восстановление file_roots

```bash
#!/bin/bash
# /usr/local/bin/salt_restore_roots.sh

BACKUP_FILE="$1"
TARGET="$2"  # file_roots или pillar_roots

if [ -z "$BACKUP_FILE" ] || [ -z "$TARGET" ]; then
    echo "Usage: $0 <backup_file.tar.gz> <file_roots|pillar_roots>"
    exit 1
fi

case "$TARGET" in
    file_roots)
        DEST="/srv/salt"
        ;;
    pillar_roots)
        DEST="/srv/pillar"
        ;;
    *)
        echo "Invalid target: $TARGET"
        exit 1
        ;;
esac

# Бэкап текущего состояния
tar -czf "${DEST}_before_restore_$(date +%Y%m%d).tar.gz" "$DEST"

# Восстановление
tar -xzf "$BACKUP_FILE" -C /

# Проверка
ls -la "$DEST"

# Очистка кэша файлового сервера
salt-run fileserver.clear_cache
salt-run fileserver.clear_file_cache

# Обновление файлового сервера
salt-run fileserver.update

# Проверка
ls -la "$DEST"

# Валидация: проверка компиляции highstate
salt '*' state.show_highstate test=True | head -20
```

### 7. Автоматический бэкап с версионированием

```bash
#!/bin/bash
# /usr/local/bin/salt_full_backup.sh
set -euo pipefail

BACKUP_BASE="/backup/salt"
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/salt_backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting full Salt backup"

# Создание каталога
mkdir -p "${BACKUP_BASE}/${DATE}"

# Бэкап PKI
log "Backing up PKI"
tar -czf "${BACKUP_BASE}/${DATE}/pki.tar.gz" /etc/salt/pki/ 2>/dev/null

# Бэкап конфигурации
log "Backing up config"
tar -czf "${BACKUP_BASE}/${DATE}/config.tar.gz" \
    /etc/salt/master /etc/salt/master.d/ 2>/dev/null

# Бэкап file_roots
log "Backing up file_roots"
tar -czf "${BACKUP_BASE}/${DATE}/file_roots.tar.gz" /srv/salt/ 2>/dev/null

# Бэкап pillar_roots
log "Backing up pillar_roots"
tar -czf "${BACKUP_BASE}/${DATE}/pillar_roots.tar.gz" /srv/pillar/ 2>/dev/null

# Бэкап Job Cache
log "Backing up job cache"
pg_dump -U salt -h localhost salt | gzip > "${BACKUP_BASE}/${DATE}/jobcache.sql.gz"

# Проверка размеров
log "Backup sizes:"
ls -lh "${BACKUP_BASE}/${DATE}/"

# Очистка старых бэкапов (старше 7 дней)
find "$BACKUP_BASE" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;

log "Full backup completed"

# Верификация архивов
log "Verifying archives"
for archive in pki config file_roots pillar_roots; do
    tar -tzf "${BACKUP_BASE}/${DATE}/${archive}.tar.gz" >/dev/null 2>&1 || {
        echo "ERROR: ${archive}.tar.gz is corrupted" >&2
        exit 1
    }
done
gunzip -t "${BACKUP_BASE}/${DATE}/jobcache.sql.gz" 2>/dev/null || {
    echo "ERROR: jobcache.sql.gz is corrupted" >&2
    exit 1
}
log "All archives verified"
```

### 8. План восстановления

План восстановления Salt Master после катастрофы. Бэкапы создаются скриптами из сценариев 1–7.

**Сценарий 1: Потеря конфигурации мастера**

1. Остановить salt-master: `systemctl stop salt-master`
2. Восстановить конфигурацию: `tar -xzf <config_backup.tar.gz> -C /`
3. Запустить salt-master: `systemctl start salt-master`
4. Проверить подключение: `salt '*' test.ping`

**Сценарий 2: Потеря PKI**

1. Остановить salt-master и salt-minion: `systemctl stop salt-master && systemctl stop salt-minion`
2. Восстановить PKI: `tar -xzf <pki_backup.tar.gz> -C /`
3. Запустить salt-master: `systemctl start salt-master`
4. Запустить salt-minion: `systemctl start salt-minion`
5. Принять ключи миньонов: `salt-key -A --yes`
6. Проверить ключи: `salt-key -L`

**Сценарий 3: Потеря file_roots или pillar_roots**

1. Восстановить файлы: `tar -xzf <roots_backup.tar.gz> -C /`
2. Очистить кэш файлового сервера: `salt-run fileserver.clear_cache && salt-run fileserver.clear_file_cache`
3. Обновить файловый сервер: `salt-run fileserver.update`
4. Проверить highstate: `salt '*' state.show_highstate test=True`

**Сценарий 4: Полная потеря мастера**

1. Установить новый salt-master (соответствующей версии)
2. Восстановить PKI (сценарий 2)
3. Восстановить конфигурацию (сценарий 1)
4. Восстановить file_roots и pillar_roots (сценарий 3)
5. Восстановить Job Cache из PostgreSQL-дампа (сценарий 4)
6. Запустить salt-master: `systemctl start salt-master`
7. Принять ключи миньонов: `salt-key -A --yes`
8. Проверить подключение миньонов: `salt '*' test.ping`

---

## Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Бэкап не создается` | Нет прав на запись | Проверить права на `/backup/salt/` |
| `Восстановленный PKI не работает` | Миньоны не подключаются | Принять ключи через `salt-key -A --yes` |
| `file_roots не обновляется` | Кэш не очищен | `salt-run fileserver.clear_cache && salt-run fileserver.clear_file_cache` |
| `Pillar не компилируется` | Ошибка в восстановленных файлах | Проверить YAML-синтаксис |
| `Job Cache поврежден` | Ошибка PostgreSQL | Восстановить из дампа |
| `Бэкап слишком большой` | Исключить *.pyc, __pycache__ | `--exclude='*.pyc'` |
| `pg_dump: команда не найдена` | PostgreSQL клиент не установлен | Установить `postgresql-client` |
| `tar: архив повреждён` | Ошибка записи во время бэкапа | Верифицировать архив (`tar -tzf`) и создать новый |
| `salt-run: команда не найдена` | salt-master не запущен | `systemctl start salt-master` |
| `Миньоны не reconnect после restore PKI` | Ключи миньонов не приняты | `salt-key -L` → `salt-key -A --yes` |

## Ограничения и edge cases

1. **Backup на том же диске**: Если `/backup/salt/` находится на том же диске, что и `/etc/salt/` и `/srv/salt/`, бэкап не защищает от сбоя диска. Используйте сетевое хранилище (NFS, CIFS) или внешние носители.

2. **Потеря minion keys**: При восстановлении только master keys (`/etc/salt/pki/master/`), миньоны автоматически переподключатся, но их ключи окажутся в статусе `unaccepted`. Требуется ручной `salt-key -A`.

3. **PostgreSQL под нагрузкой**: `pg_dump` делает снимок на момент запуска, но при интенсивной записи job cache может получиться неполный дамп. Используйте `--lock-wait-timeout=30` или останавливайте запись job cache на время бэкапа.

4. **GitFS cache**: Кэш GitFS (`/var/cache/salt/master/gitfs/`) содержит блокировки файлов. Бэкап в активное время может привести к inconsistентному состоянию. Лучше бэкапить GitFS-источники (remotes) напрямую.

5. **Размер pillar_roots**: Если pillar содержит большие данные (например, встраиваемые сертификаты), бэкап может занять значительное место. Шифруйте и сжимайте (`--exclude='*.pem'`) если сертификаты хранятся отдельно.

6. **Время простоя при restore**: Восстановление PKI требует остановки salt-master. Для минимизации простоя используйте репликацию master (Standby Master) или планируйте окно обслуживания.

7. **File server cache после restore**: После восстановления file_roots обязательно очищайте кэш (`salt-run fileserver.clear_cache`). Иначе миньоны получат устаревшие версии SLS-файлов.

## Лучшие практики

1. **Автоматизация**: Автоматические бэкапы через cron или systemd timers.
2. **Регулярность**: Ежедневные бэкапы PKI и pillar_roots. Еженедельные — полные бэкапы all-in-one.
3. **Версионирование**: Хранить несколько последних бэкапов (7 дней для PKI, 30 дней для configs).
4. **Проверка**: Регулярно тестировать восстановление на стенде (не в проде).
5. **Шифрование**: Шифровать бэкапы pillar_roots (содержит секреты) через GPG.
6. **Хранение**: Внеузловое хранение бэкапов (NFS, S3-совместимое, отдельный сервер).
7. **Документация**: Описать процедуру восстановления, включая порядок действий и контакты ответственных.
8. **Мониторинг**: Алертинг на проблемы бэкапа — проверка наличия файлов, их размера и целостности (`tar -tzf`).
9. **Ротация ключей**: Периодически ротацию minion keys для сокращения blast radius при компрометации.
10. **DR-тестинг**: Проводить tabletop-совещания и периодические DR-тесты (раз в квартал).

### Дополнительная информация

| Версия Salt | Особенности backup |
|:---|:---|
| 3006 LTS | Стандартная структура файлов |
| 3007 STS | Улучшенный job cache |
| 3008 LTS | Безопасное хранение ключей (masterless-режим) |

### См. также

- [Архитектура SaltStack](Architecture.md) — backup section
- [Безопасность SaltStack](Security_Approaches.md) — PKI security
- [Мониторинг Salt](Salt_Monitoring.md) — monitoring backup health
