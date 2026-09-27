# Backup и восстановление SaltStack

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

# Проверка
salt '*' test.ping | head -5
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
```

### 7. Автоматический бэкап с версионированием

```bash
#!/bin/bash
# /usr/local/bin/salt_full_backup.sh

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
```

### 8. Recovery Plan

```markdown
# Recovery Plan: Salt Master

## Сценарий 1: Потеря конфигурации
1. Остановить salt-master
2. Восстановить /etc/salt/master из бэкапа
3. Запустить salt-master
4. Проверить salt '*' test.ping

## Сценарий 2: Потеря PKI
1. Остановить salt-master и salt-minion
2. Восстановить /etc/salt/pki/ из бэкапа
3. Запустить salt-master
4. Запустить salt-minion
5. Проверить salt-key -L

## Сценарий 3: Потеря file_roots
1. Восстановить /srv/salt/ из бэкапа
2. salt-run fileserver.clear_cache
3. Проверить salt '*' state.show_highstate

## Сценарий 4: Полная потеря мастера
1. Установить новый salt-master
2. Восстановить PKI
3. Восстановить конфигурацию
4. Восстановить file_roots и pillar_roots
5. Восстановить Job Cache
6. Запустить salt-master
7. Принять ключи миньонов (salt-key -A)
8. Проверить salt '*' test.ping
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Бэкап не создается` | Нет прав на запись | Проверить права на `/backup/salt/` |
| `Восстановленный PKI не работает` | Миньоны не подключаются | Принять ключи через `salt-key -A` |
| `file_roots не обновляется` | Кэш не очищен | `salt-run fileserver.clear_cache` |
| `Pillar не компилируется` | Ошибка в восстановленных файлах | Проверить YAML-синтаксис |
| `Job Cache поврежден` | Ошибка PostgreSQL | Восстановить из дампа |
| `Бэкап слишком большой` | Исключить *.pyc, __pycache__ | `--exclude='*.pyc'` |

### Best practices

1. **Автоматизация**: Автоматические бэкапы через cron.
2. **Регулярность**: Ежедневные бэкапы PKI и pillar.
3. **Версионирование**: Хранить несколько последних бэкапов.
4. **Проверка**: Регулярно тестировать восстановление.
5. **Шифрование**: Шифровать бэкапы pillar (содержит секреты).
6. **Хранение**: Внеузловое хранение бэкапов.
7. **Документация**: Описать процедуру восстановления.
8. **Мониторинг**: Алертинг на проблемы бэкапа.

### Версии и совместимость

| Версия Salt | Особенности backup |
|:---|:---|
| 3006 LTS | Стандартная структура файлов |
| 3007 STS | Улучшенный job cache |
| 3008 LTS | Безопасное хранение ключей |

### См. также

- [Архитектура SaltStack](Architecture.md) — backup section
- [Безопасность SaltStack](Security_Approaches.md) — PKI security
- [Мониторинг Salt](Salt_Monitoring.md) — monitoring backup health
