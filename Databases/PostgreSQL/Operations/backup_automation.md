# Автоматизация резервного копирования PostgreSQL

## Использование Shell-скриптов и Cron

Для регулярного создания логических копий удобно использовать скрипты, которые не только создают дамп, но и управляют ротацией (удалением старых файлов).

### Пример скрипта для pg_dump
Создайте файл `/etc/scripts/pg_backup.sh`:
```bash
#!/bin/bash

# Настройки
BACKUP_DIR="/mnt/backups/postgresql"
DB_USER="dbadmin"
DATABASE="mydb"
# Пароль можно задать через переменную окружения (небезопасно) 
# или использовать ~/.pgpass
export PGPASSWORD="your_password"

# Дата для имени файла
DATE=$(date "+%Y-%m-%d")

# Создание дампа и сжатие
pg_dump -U $DB_USER $DATABASE | gzip > $BACKUP_DIR/pgsql_$DATE.sql.gz

# Ротация: удаление файлов старше 60 дней, 
# исключая бэкапы за 15-е число месяца (для долгого хранения)
find $BACKUP_DIR \( -name "*.sql.gz" -a ! -name "*-15.sql.gz" \) -ctime +60 -delete

# Очистка переменной
unset PGPASSWORD
```

### Настройка расписания в Crontab
```bash
# Выполнять ежедневно в 03:00 ночи
0 3 * * * /bin/bash /etc/scripts/pg_backup.sh
```

## Использование WAL-G для резервного копирования в S3

**WAL-G** позволяет автоматизировать процесс физического копирования и архивации WAL-логов в S3-совместимые хранилища.

### 1. Установка
```bash
curl -L "https://github.com/wal-g/wal-g/releases/download/v2.0.1/wal-g-pg-ubuntu-20.04-amd64.tar.gz" -o wal-g.tar.gz
tar -xzf wal-g.tar.gz
sudo mv wal-g /usr/local/bin/
```

### 2. Конфигурация (~/postgres/.walg.json)
```json
 {
     "WALG_S3_PREFIX": "s3://my-backup-bucket",
     "AWS_ENDPOINT": "https://s3.example.com",
     "AWS_ACCESS_KEY_ID": "key_id",
     "AWS_SECRET_ACCESS_KEY": "secret_key",
     "WALG_COMPRESSION_METHOD": "brotli",
     "PGDATA": "/var/lib/postgresql/14/main",
     "PGHOST": "/var/run/postgresql/.s.PGSQL.5432"
 }
```

### 3. Настройка PostgreSQL (postgresql.conf)
```conf
wal_level = replica
archive_mode = on
archive_command = '/usr/local/bin/wal-g wal-push %p'
archive_timeout = 60
restore_command = '/usr/local/bin/wal-g wal-fetch %f %p'
```

### 4. Создание базового бэкапа
```bash
sudo -u postgres wal-g backup-push /var/lib/postgresql/14/main
```

### См. также
*   [Теория бэкапов](../Concepts/backup_and_recovery.md)
*   [Управление ролями и БД](./role_management.md)
