# Бэкап и восстановление

## Снапшоты (Snapshots)

```bash
# Создание снапшота для конкретной таблицы
nodetool snapshot my_app user_events -t backup_2026_01_15
# → Snapshot directory: /var/lib/cassandra/data/my_app/user_events-<uuid>/snapshots/backup_2026_01_15

# Список снапшотов
nodetool listsnapshots

# Восстановление из снапшота
# 1. Остановить узел
# 2. Скопировать файлы снапшота в директорию данных
# 3. Запустить Cassandra
nodetool clearsnapshot -t backup_2026_01_15  # удалить снапшот после восстановления
```

---

## Инкрементальный бэкап

```bash
# Скрипт бэкапа с rsync (ежедневный)
#!/bin/bash
SNAP_DIR="/backups/cassandra/$(date +%F)"
mkdir -p "$SNAP_DIR"

# Создание снапшота
nodetool snapshot my_app -t daily_backup_$(date +%F)

# Копирование снапшота на удаленный сервер
rsync -avz /var/lib/cassandra/data/my_app/*/snapshots/daily_backup_* \
    backup-server:"$SNAP_DIR/"

# Удаление локального снапшота после копирования
nodetool clearsnapshot -t daily_backup_$(date +%F)
```

---

## Восстановление на новом узле

```bash
# 1. Установить ту же версию Cassandra/ScyllaDB
# 2. Остановить сервис
systemctl stop cassandra

# 3. Удалить данные
rm -rf /var/lib/cassandra/data/*

# 4. Скопировать бэкапы
rsync -avz backup-server:/backups/cassandra/latest/ /var/lib/cassandra/data/

# 5. Запустить сервис
systemctl start cassandra

# 6. Запустить Repair для проверки согласованности
nodetool repair -pr my_app
```

---

## См. также
- **[Обслуживание и эксплуатация](./operations.md)** — Repair, Compaction.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — восстановление после сбоев.
- **[Мониторинг и observability](./monitoring.md)** — проверка состояния после restore.
