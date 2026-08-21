# Percona XtraBackup — физические бэкапы MySQL

`Percona XtraBackup` — промышленный стандарт для создания «горячих» физических бэкапов InnoDB. Позволяет копировать файлы данных без остановки сервера и блокировок записи. Финальный релиз ветки 8.0 — **8.0.35-36** (июнь 2026).

> **Версионная совместимость:** XtraBackup 8.0.35-xx совместим со всеми версиями MySQL 8.0.x. Для MySQL 5.7 required ветка XtraBackup 2.4. Версии инструмента и сервера должны совпадать по major.minor. Подробности — в **[обзоре инструментов](./overview.md#версии-mysql-и-инструментов)**.

## Установка

```bash
# Debian/Ubuntu
sudo apt-get install percona-xtrabackup-80

# RHEL/CentOS
sudo yum install percona-xtrabackup-80

# Проверка версии
xtrabackup --version
# → xtrabackup version 8.0.35-36 based on MySQL server 8.0.xx
```

## Полный физический бэкап

### Базовый полный бэкап

```bash
xtrabackup --backup \
  --target-dir=/backups/full_$(date +%F) \
  --user=backup_user \
  --password='StrongPassword!2024'
# → ... completed OK!
```

### Бэкап с ограничением нагрузки (throttle)

```bash
# Ограничение I/O: 100 страниц/сек (16 КБ каждый ≈ 1.6 МБ/с)
xtrabackup --backup \
  --target-dir=/backups/full_$(date +%F) \
  --user=backup_user --password='StrongPassword!2024' \
  --throttle=100
```

### Стриминг через SSH (без промежуточного файла)

```bash
xtrabackup --backup --stream=xbstream \
  --user=backup_user --password='StrongPassword!2024' | \
ssh user@remote_host "mkdir -p /data/backups/full_$(date +%F) && \
  xbstream -x -C /data/backups/full_$(date +%F)"
```

> **Преимущество:** Данные не записываются на локальный диск сервера бэкапа. Идеально при нехватке места.

### Бэкап со сжатием (Zstd)

```bash
xtrabackup --backup \
  --compress --compress-threads=4 --compress-zstd-level=3 \
  --target-dir=/backups/full_zstd_$(date +%F) \
  --user=backup_user --password='StrongPassword!2024'

# Восстановление сжатого бэкапа: распаковка перед --prepare
xtrabackup --decompress --target-dir=/backups/full_zstd_$(date +%F)
xtrabackup --prepare --target-dir=/backups/full_zstd_$(date +%F)
```

**Параметры сжатия:**
- `--compress-threads` — количество потоков сжатия. Оптимально: `(CPU ядра / 2)`.
- `--compress-zstd-level` — уровень сжатия Zstd (0–19). Уровень 3 — баланс скорость/размер. Уровень 15+ — максимальное сжатие, но медленно.
- `--compress` без указания алгоритма использует `quicklz` (устаревший). Всегда указывайте `--compress-zstd-level` для Zstd.

## Инкрементальный бэкап

Минимизирует объём передаваемых данных, копируя только изменённые страницы InnoDB между LSN.

### Создание инкрементального бэкапа

```bash
# 1. Базовый полный бэкап (Base)
xtrabackup --backup --target-dir=/backups/base \
  --user=backup_user --password='StrongPassword!2024'

# 2. Инкремент 1 (на основе Base)
xtrabackup --backup --target-dir=/backups/inc1 \
  --incremental-basedir=/backups/base \
  --user=backup_user --password='StrongPassword!2024'

# 3. Инкремент 2 (на основе Inc1 — цепочка)
xtrabackup --backup --target-dir=/backups/inc2 \
  --incremental-basedir=/backups/inc1 \
  --user=backup_user --password='StrongPassword!2024'
```

> **Принцип:** Каждый инкрементальный бэкап содержит только страницы, изменённые с момента предыдущего. `--incremental-basedir` указывает на ПОСЛЕДНИЙ успешный бэкап (полный или инкрементальный).

### Восстановление из полного + инкрементальных бэкапов

```bash
# 1. Подготовка базового бэкапа (apply log only — без отката redo)
xtrabackup --prepare --apply-log-only --target-dir=/backups/base

# 2. Применение первого инкремента
xtrabackup --prepare --apply-log-only --target-dir=/backups/base \
  --incremental-dir=/backups/inc1

# 3. Применение второго инкремента (последний — БЕЗ --apply-log-only)
xtrabackup --prepare --target-dir=/backups/base \
  --incremental-dir=/backups/inc2

# 4. Копирование данных в каталог MySQL
systemctl stop mysql
rm -rf /var/lib/mysql/*
xtrabackup --copy-back --target-dir=/backups/base \
  --datadir=/var/lib/mysql
chown -R mysql:mysql /var/lib/mysql
systemctl start mysql
```

> **Важно:** Последний шаг `--prepare` выполняется **без** флага `--apply-log-only`. Это позволяет InnoDB выполнить финальный откат незавершённых транзакций (Rollback), обеспечивая консистентность.

> **Восстановление инкрементов:** Инкременты применяются строго последовательно: Base → Inc1 → Inc2. Пропуск шага приведёт к ошибке LSN mismatch.

## Восстановление конкретной таблицы из физического бэкапа

Позволяет избежать полного восстановления терабайтной БД ради одной таблицы.

```bash
# 1. Подготовка бэкапа с экспортом метаданных
xtrabackup --prepare --export --target-dir=/backups/base

# 2. На целевом сервере (может быть другим инстансом):
# Удалите данные таблицы и отсоедините tablespace
mysql> ALTER TABLE mydb.mytable DISCARD TABLESPACE;

# 3. Скопируйте файлы из бэкапа в каталог данных MySQL
cp /backups/base/mydb/mytable.ibd /var/lib/mysql/mydb/mytable.ibd
cp /backups/base/mydb/mytable.cfg /var/lib/mysql/mydb/mytable.cfg
chown mysql:mysql /var/lib/mysql/mydb/mytable.*

# 4. Подключите tablespace
mysql> ALTER TABLE mydb.mytable IMPORT TABLESPACE;
```

> **Ограничения:**
> - Таблица должна принадлежать движку InnoDB.
> - Для MyISAM потребуется полное восстановление или логический дамп с фильтрацией.
> - Целевой сервер должен иметь ту же major-версию MySQL, что и источник.
> - При использовании `INSTANT ADD/DROP COLUMN` (MySQL 8.0.12+) файл `.cfg` может не содержать актуальную схему — обновите MySQL до 8.0.29+.

## Проверка целостности бэкапа

Этап `--prepare` является фактической проверкой: если Redo Log не удаётся применить к данным, бэкап считается повреждённым.

```bash
# Проверка целостности (успешный prepare = бэкап валиден)
xtrabackup --prepare --target-dir=/backups/full_latest
# → ... completed OK!

# Если ошибка — бэкап повреждён, используйте другой
```

Подробнее о методах верификации — в **[Автоматизация и верификация](./automation.md#скрипт-верификации-бэкапа-smoke-test)**.

## Дополнительная информация

- **[Обзор инструментов бэкапа](./overview.md)** — сравнение методов, определения, бест-практики.
- **[Point-in-Time Recovery](./pitr.md)** — комбинация физического бэкапа + бинарные логи.
- **[Автоматизация](./automation.md)** — cron-скрипты для XtraBackup.
- **[Percona XtraBackup Documentation](https://docs.percona.com/percona-xtrabackup/8.0/index.html)**
