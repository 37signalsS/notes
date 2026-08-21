# Neo4j: Обслуживание и эксплуатация

## Управление памятью

Neo4j критично зависит от правильной настройки памяти:
1.  **OS Page Cache:** Должен быть достаточным для хранения файлов магазина (`.db`) в памяти. Если Page Cache < размера БД, производительность упадет из-за Disk I/O.
2.  **JVM Heap:** Используется для управления транзакциями, планов выполнения и кэша запросов. Рекомендуется от 8 до 32 ГБ (не больше, чтобы избежать долгих пауз GC).

**Эвристика распределения RAM (16 ГБ):**
| Ресурс | Значение | Назначение |
| :--- | :--- | :--- |
| Heap | 4-8 ГБ | Транзакции, планы, кэш запросов |
| Page Cache | 8-10 ГБ | Хранение store-файлов в памяти |
| ОС/прочее | 2-4 ГБ | Системные процессы |

**Конфигурация (`neo4j.conf`):**
```conf
server.memory.heap.initial_size=4G
server.memory.heap.max_size=8G
server.memory.pagecache.size=10G
```

## Бэкап и восстановление

### Online-бэкап (Enterprise Edition)

```bash
# Создание онлайн-бэкапа
neo4j-admin database backup neo4j --to-path=/backups/$(date +%F)

# Восстановление из бэкапа
neo4j-admin database restore --from-path=/backups/2026-08-20/neo4j-2026-08-20T12-00-00.backup --database=neo4j --force

# Cron-задача для ежедневного бэкапа (crontab)
0 2 * * * /usr/bin/neo4j-admin database backup neo4j --to-path=/backups/$(date +\%F) >> /var/log/neo4j-backup.log 2>&1
```

### Offline-бэкап

```bash
sudo systemctl stop neo4j
cp -r /var/lib/neo4j/data/databases/neo4j /backups/neo4j-offline-$(date +%F)
sudo systemctl start neo4j
```

### Docker: Бэкап через volume

```bash
# Экспорт данных из volume
docker run --rm -v neo4j_data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/neo4j-backup-$(date +%F).tar.gz /data

# Восстановление
docker run --rm -v neo4j_data:/data -v $(pwd):/backup \
  ubuntu tar xzf /backup/neo4j-backup-2026-08-20.tar.gz -C /
```

## Диагностика

### Логи

- **query.log** — основной источник тяжёлых запросов (требуется `dbms.logs.query.enabled=true`).
- **debug.log** — общая информация о работе сервера.
- **security.log** — аудит аутентификации и авторизации.

```bash
# Мониторинг логов в реальном времени
tail -f /var/log/neo4j/debug.log

# Поиск тяжёлых запросов
grep "completed in" /var/log/neo4j/query.log | sort -t' ' -k3 -rn | head -20

# Проверка размера базы
du -sh /var/lib/neo4j/data/databases/neo4j/
```

### Метрики и мониторинг

Интеграция с Prometheus через `/metrics` эндпоинт.

**Важнейшие метрики:**
| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `neo4j_page_cache_hit_ratio` | Доля попаданий в Page Cache | < 98% |
| `neo4j_transaction_active` | Количество активных транзакций | > 100 |
| `neo4j_jvm_memory_used_bytes` | Использование JVM Heap | > 85% от max |
| `neo4j_dbms_indexes_size` | Размер индексов | Мониторинг роста |
| `neo4j_server_threads_waiting` | Потоки в ожидании | > 50 |

## Диагностика и устранение неисправностей

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **OutOfMemoryError** | Процесс завершается, нет ответа | Heap слишком мал для нагрузки | Увеличьте `server.memory.heap.max_size`. Проверьте PLAN для тяжёлых запросов. |
| **Очень медленные запросы** | Высокий DbHits в PROFILE | Отсутствует индекс, сканирование графа | Создайте индекс на свойства в WHERE. Указывайте направление связей. |
| **Timeout транзакции** | `Transaction rolled back` | Долгая транзакция, contention | Уменьшите размер батча. Используйте `CALL { } IN TRANSACTIONS`. |
| **Данные не видны** | `MATCH (n) RETURN n` пусто | Данные в другой базе | Проверьте `SHOW DATABASES` и `USE database_name`. |
| **Connection Refused** | Bolt/HTTP недоступен | Сервис не запущен, порт занят | `sudo systemctl status neo4j`, проверьте `netstat -tlnp | grep 7687`. |
| **Page Cache Hit Ratio < 95%** | Медленные чтения | Page Cache < размера данных | Увеличьте `server.memory.pagecache.size`. |

### Производительность: чек-лист

- [ ] Все свойства в WHERE имеют индексы
- [ ] Направление связей указано везде, где известно
- [ ] Используются параметры (`$param`) вместо хардкода
- [ ] `PROFILE` показывает DbHits < 1000 для типичных запросов
- [ ] Page Cache Hit Ratio > 98%
- [ ] Heap Usage стабилен (нет роста до 100%)
- [ ] Бэкапы проверены на восстановление

## См. также
- **[Установка и настройка](./installation_and_setup.md)** — развёртывание Neo4j.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, WAL, store files.
- **[Безопасность](./security.md)** — RBAC, TLS.
- **[Бэкап и восстановление](../Concepts/backups.md)** — общая теория резервного копирования.
