# Аудит в MariaDB: server_audit plugin

Плагин аудита фиксирует действия пользователей («кто, когда и что сделал»), что является обязательным условием для соответствия стандартам безопасности (PCI-DSS, HIPAA, GDPR).

## Включение и блокировка удаления (`my.cnf`)

Для предотвращения отключения аудита злоумышленником необходимо использовать флаг `FORCE_PLUS_PERMANENT`.

```ini
[mariadb]
# Загрузка плагина и блокировка его выгрузки в рантайме
plugin_load_add = server_audit
server_audit = FORCE_PLUS_PERMANENT

# Активация логирования
server_audit_logging = ON
# События: CONNECT (вход/выход), QUERY (текст запросов), TABLE (доступ к объектам)
server_audit_events = CONNECT,QUERY,TABLE,QUERY_DDL
```

## Тюнинг и фильтрация (SRE-практики)

Для минимизации влияния на производительность (особенно при `QUERY`) и уменьшения объема логов:

```ini
# Исключение технических пользователей (мониторинг, репликация) для снижения шума
server_audit_excl_users = 'zabbix,repl_user,maxscale'

# Использование Syslog для безопасной передачи в SIEM (Splunk/ELK)
# Это гарантирует неизменность логов даже при компрометации локальной ОС
server_audit_output_type = SYSLOG
server_audit_syslog_facility = LOG_LOCAL6
server_audit_syslog_priority = LOG_INFO

# Если используется вывод в файл (FILE), настройте агрессивную ротацию
server_audit_file_path = /var/log/mysql/audit.log
server_audit_file_rotate_size = 1G
server_audit_file_rotations = 30
```

## Верификация работы аудита

```sql
-- Проверка, что плагин загружен
SELECT PLUGIN_NAME, PLUGIN_STATUS
FROM information_schema.PLUGINS
WHERE PLUGIN_NAME = 'server_audit';
-- → server_audit | ACTIVE

-- Проверка текущих настроек аудита
SHOW VARIABLES LIKE 'server_audit%';
-- → server_audit_logging = ON
-- → server_audit_events = CONNECT,QUERY,TABLE,QUERY_DDL
-- → server_audit_output_type = SYSLOG
```

## SRE-рекомендации по эксплуатации

1. **Производительность:** Логирование `QUERY` может снизить пропускную способность записи на 10-15%. В высоконагруженных системах рассмотрите логирование только `TABLE` и `QUERY_DDL` для контроля доступа к данным при меньших затратах ресурсов.
2. **Мониторинг:** Настройте алерты в Zabbix/Prometheus на изменение переменной `server_audit_logging`. Если аудит выключен — это критический инцидент ИБ.
3. **Безопасность логов:** При использовании `FILE` установите права `600` на директорию логов и убедитесь, что владелец — пользователь `mysql`. Никогда не храните аудит-логи в `datadir`.
4. **Асинхронность:** В MariaDB запись аудита синхронна. Для минимизации задержек клиентов используйте выделенный быстрый диск (NVMe) для системных логов.

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Бинарное логирование](binary-logging.md)** — дополнительный уровень логирования для forensic.
- **[Дополнительные параметры](additional-parameters.md)** — `log_error_verbosity` и другие параметры логирования.
- **[Troubleshooting](troubleshooting.md)** — диагностика пустых аудит-логов.
