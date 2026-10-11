**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

# Устранение неполадок безопасности MariaDB

## Определения

**Инцидент безопасности (Security Incident)** — событие, при котором нарушена конфиденциальность, целостность или доступность данных или инстанса MariaDB. Требует фиксации, анализа и реагирования по runbook.

**Forensic-анализ (Forensic Analysis)** — процесс сбора, сохранения и анализа доказательств (логов, binlog, артефактов файловой системы) для установления причины инцидента и восстановления состояния системы.

**Эшелонированная защита (Defense-in-Depth)** — стратегия многоуровневой защиты, при которой провал одного механизма компенсируется другими уровнями. В MariaDB: сеть → аутентификация → авторизация → аудит → шифрование.

**Принцип наименьших привилегий (PoLP)** — предоставление пользователям только тех прав, которые минимально необходимы. В MariaDB реализуется через RBAC, гранулярные `GRANT`/`REVOKE` и отсутствие `SUPER` у приложений.

**Целостность доказательств (Evidence Integrity)** — гарантия того, что логи, бэкапы и артефакты не были изменены, удалены или подделаны после инцидента. Требует хранения на неизменяемых носителях или в SIEM.

## Быстрый справочник: симптом → файл

Используйте эту таблицу для быстрой навигации к детальному troubleshooting в специализированных файлах.

| Симптом / Категория | Файл | Раздел |
| :--- | :--- | :--- |
| `Access denied` при входе, блокировка аккаунта | [Аутентификация](authentication.md) | Типичные ошибки |
| `ERROR 1819: Password policy violated` | [Аутентификация](authentication.md) | Типичные ошибки |
| `max_password_errors` не срабатывает | [Аутентификация](authentication.md) | Типичные ошибки |
| PAM / LDAP-аутентификация не работает | [Аутентификация](authentication.md) | Типичные ошибки |
| `caching_sha2_password` не установлен | [Аутентификация](authentication.md) | Типичные ошибки |
| `ERROR 2026: SSL connection error` | [SSL/TLS](ssl-tls.md) | Типичные ошибки |
| `require_secure_transport` блокирует приложение | [SSL/TLS](ssl-tls.md) | Типичные ошибки |
| CRL не обновляется | [SSL/TLS](ssl-tls.md) | Типичные ошибки |
| Сервис не запускается после hardening | [Начальная закалка](hardening.md) | Типичные ошибки |
| `skip-show-database` блокирует приложение | [Начальная закалка](hardening.md) | Типичные ошибки |
| `root` не может войти после смены плагина | [Начальная закалка](hardening.md) | Типичные ошибки |
| `Access denied` после `GRANT` | [Ролевая модель (RBAC)](rbac.md) | Troubleshooting |
| `ERROR 1396` / `ERROR 3510` | [Ролевая модель (RBAC)](rbac.md) | Troubleshooting |
| Потеря прав после перезапуска | [Ролевая модель (RBAC)](rbac.md) | Troubleshooting |
| Аудит-лог пустой, плагин не загружается | [Аудит](audit.md) | Troubleshooting |
| Производительность аудита | [Аудит](audit.md) | Troubleshooting |
| `Unable to decrypt tablespace` при старте | [Шифрование данных (TDE)](tde.md) | Типичные ошибки |
| KEK / DEK недоступны | [Шифрование данных (TDE)](tde.md) | Типичные ошибки |
| `Could not find target log file` | [Бинарное логирование](binary-logging.md) | Типичные ошибки |
| `mariadb-binlog` не расшифровывает binlog | [Бинарное логирование](binary-logging.md) | Типичные ошибки |
| `binlog` заполняет диск | [Бинарное логирование](binary-logging.md) | Типичные ошибки |
| `Error 1236: master has purged binary logs` | [Бинарное логирование](binary-logging.md) | Типичные ошибки |
| Ошибки репликации, `Error 1032`, `Error 1060` | [Диагностика репликации](../replication/troubleshooting.md) | Глубокий анализ |
| SST failed, кластер развалился | [Отказоустойчивость](../high_availability.md) | Типичные ошибки |
| Сетевой доступ заблокирован, `ERROR 2003` | [Сетевая безопасность](network-security.md) | Настройка файрвола |

## Общий диагностический workflow

### Шаг 1: Определение поверхности атаки и scope

Перед глубоким анализом ответьте на три вопроса:
1. **Что сломалось?** — сервис недоступен, данные изменены, пароль скомпрометирован, логи отсутствуют?
2. **Кто затронут?** — один пользователь, приложение, весь инстанс?
3. **Когда началось?** — время первого подозрительного события, время обнаружения?

Соберите контекст:
```bash
# Текущее время сервера (проверка расхождения с клиентом)
date
timedatectl status

# Список активных соединений
sudo ss -tnp | grep 3306

# Кто подключался в последнее время
sudo journalctl -u mariadb --since "1 hour ago" | grep -i "connect\|access denied\|error"

# Статус сервиса
sudo systemctl status mariadb
```

### Шаг 2: Проверка состояния сервиса и ресурсов

```bash
# Процесс MariaDB работает?
sudo systemctl status mariadb
# → active (running) / failed / inactive

# Использование диска (binlog может заполнить всё пространство)
df -h
du -sh /var/lib/mysql /var/log/mysql

# Использование памяти и swap
free -h
ps aux --sort=-%mem | head -10

# Очередь процессов MariaDB
top -H -p $(pidof mysqld)
```

### Шаг 3: Быстрая проверка безопасности инстанса

```sql
-- Пользователи с удалённым доступом и SUPER
SELECT User, Host, Super_priv, File_priv, Process_priv
FROM mysql.user
WHERE Host NOT IN ('localhost', '127.0.0.1', '::1')
   OR Super_priv = 'Y'
   OR File_priv = 'Y';

-- Анонимные пользователи
SELECT User, Host FROM mysql.user WHERE User = '';

-- Тестовая БД
SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = 'test';

-- Плагины аутентификации
SELECT User, Host, plugin FROM mysql.user;

-- Активные роли по умолчанию
SELECT User, Host, Default_role FROM mysql.user;

-- Глобальные привилегии пользователя
SELECT * FROM information_schema.USER_PRIVILEGES;

-- GTID-позиция (для forensic)
SELECT @@gtid_binlog_pos, @@gtid_slave_pos;

-- Статус бинарного логирования
SHOW MASTER STATUS;
SHOW BINARY LOGS;
```

### Шаг 4: Анализ логов

```bash
# Error log — первичный источник проблем
sudo journalctl -u mariadb --since "2 hours ago" --no-pager | tail -200

# Или legacy-путь
sudo tail -200 /var/log/mysql/error.log

# Аудит-лог (если включен)
sudo tail -200 /var/log/mysql/audit.log | grep -i "error\|denied\|fail"

# Slow query log (проверка аномалий)
sudo tail -100 /var/log/mysql/slow.log

# Бинарные логи (последние события)
mariadb-binlog --read-from-remote-server \
  --start-datetime="$(date -u -d '2 hours ago' '+%Y-%m-%d %H:%M:%S')" \
  --stop-datetime="$(date -u '+%Y-%m-%d %H:%M:%S')" \
  --base64-output=DECODE-ROWS -v \
  /var/log/mysql/mariadb-bin.000001 2>/dev/null | grep -E "DROP|DELETE|GRANT|CREATE USER|ALTER USER"
```

## Типовые cross-cutting ошибки

### Ошибка: сервис не запускается после изменения параметров безопасности

**Симптом:** `sudo systemctl status mariadb` → `failed`, в логах `Permission denied` или `unknown variable`.

**Причины и решения:**

1. **Опечатка в `my.cnf`** — неверное имя переменной или синтаксис.
   ```bash
   # Проверка синтаксиса
   sudo mariadb --help --verbose | grep -i "<parameter>"
   # Или dry-run через mysqld
   sudo mysqld --validate-config
   ```

2. **Права на файлы сертификатов/ключей** — MariaDB не может прочитать TLS-файлы или ключи TDE.
   ```bash
   # Права на сертификаты
   ls -la /etc/mysql/ssl/
   # → 600, владелец mysql:mysql

   # Права на ключи TDE
   ls -la /etc/mysql/encryption/
   # → 750 на каталог, 600 на ключи
   ```

3. **Несуществующий каталог для binlog** — указан путь, который не создан.
   ```bash
   sudo mkdir -p /var/log/mysql
   sudo chown mysql:mysql /var/log/mysql
   sudo chmod 750 /var/log/mysql
   ```

### Ошибка: `local-infile` блокирует приложение, но отключение не помогает

**Симптом:** Приложение падает с ошибкой загрузки данных, но `SHOW VARIABLES LIKE 'local_infile'` показывает `OFF`.

**Решение:**
1. Проверьте, не переопределяет ли параметр в другом файле `my.cnf` (иерархия: `/etc/mysql/my.cnf` → `/etc/mysql/mariadb.conf.d/` → `/etc/mysql/conf.d/`).
   ```bash
   sudo grep -r "local-infile" /etc/mysql/
   ```
2. Проверьте, не передаёт ли клиент флаг `--local-infile` принудительно.
3. Для legacy-приложений используйте `LOAD DATA INFILE` вместо `LOAD DATA LOCAL INFILE` (требует файл на сервере).

### Ошибка: `skip-name-resolve` тормозит подключения

**Симптом:** После включения `skip-name-resolve = 1` подключения занимают 5-10 секунд.

**Причина:** В `mysql.user` хранятся хосты в виде DNS-имен (`%.example.com`), а не IP. При `skip-name-resolve = 1` MariaDB не может разрешить их.

**Решение:**
```sql
-- Найдите записи с DNS-именами
SELECT User, Host FROM mysql.user WHERE Host NOT LIKE '1.2.3.4' AND Host NOT LIKE '10.%' AND Host NOT LIKE '192.168.%';

-- Замените на IP или CIDR
UPDATE mysql.user SET Host = '10.0.5.%' WHERE User = 'app_svc' AND Host = 'app.example.com';
FLUSH PRIVILEGES;
```

### Ошибка: пароль пользователя истёк, но приложение не падает сразу

**Симптом:** Приложение работает, но в логах MariaDB появляется `Password expired`.

**Причина:** `default_password_lifetime` установлен, но приложение кэширует соединения в пуле. При обновлении пароля приложение продолжает использовать устаревшее соединение.

**Решение:**
1. Найдите все соединения приложения:
   ```sql
   SELECT id, USER, HOST, db, TIME
   FROM information_schema.PROCESSLIST
   WHERE USER = 'app_svc';
   ```
2. Убейте устаревшие соединения:
   ```sql
   KILL <id>;
   ```
3. Настройте `wait_timeout` для автоматического закрытия неактивных соединений:
   ```ini
   [mariadb]
   wait_timeout = 600
   interactive_timeout = 600
   ```

### Ошибка: `log_warnings` слишком низкий — не видно ошибок аутентификации

**Симптом:** В error log нет записей о `Access denied`, но `server_audit` их фиксирует.

**Причина:** `log_warnings = 0` или `1` — слишком минимум. Для отладки аутентификации используйте `= 2` или выше (по умолчанию `2`).

**Решение:**
```ini
[mariadb]
log_warnings = 2
```

**Важно:** Не повышайте `log_warnings` выше 2 на production permanently — уровни 3+ создают большой объём логов (InnoDB DDL progress, killed connections) и могут раскрывать внутренние детали.

## Диагностика уровня хоста (OS-level)

### Проверка целостности файлов и прав

```bash
# Каталог datadir
sudo ls -la /var/lib/mysql/
# → Владелец mysql:mysql, права 750 на каталоги, 660 на файлы

# Каталог binlog
sudo ls -la /var/log/mysql/
# → audit.log должен быть 600, владелец mysql:mysql

# Сертификаты TLS
sudo ls -la /etc/mysql/ssl/
# → 600, владелец mysql:mysql

# Ключи TDE
sudo ls -la /etc/mysql/encryption/
# → 750 на каталог, 600 на keyfile.key

# Проверка, что нет чужих файлов в datadir
sudo find /var/lib/mysql -user mysql -group mysql -perm 660
```

### Проверка процессов и портов

```bash
# Процесс MariaDB
ps aux | grep mysqld
# → должен запускаться от имени mysql, не root

# Открытые порты
sudo ss -tnlp | grep 3306
# → должен слушать только на 127.0.0.1 или внутреннем интерфейсе

# Проверка, что нет посторонних процессов, подключающихся к MariaDB
sudo lsof -i :3306
```

### Проверка journalctl / systemd

```bash
# Последние 200 строк логов MariaDB
sudo journalctl -u mariadb --since "24 hours ago" --no-pager | tail -200

# Ошибки загрузки плагинов
sudo journalctl -u mariadb --since "24 hours ago" | grep -i "plugin\|audit\|tls\|error"

# Проверка, что сервис запускается автоматически
sudo systemctl is-enabled mariadb
# → enabled
```

### Проверка файрвола и сети

```bash
# UFW (Debian/Ubuntu)
sudo ufw status verbose

# firewalld (RHEL/CentOS)
sudo firewall-cmd --list-all

# iptables
sudo iptables -L -n | grep 3306

# Проверка, что порт 3306 не открыт на 0.0.0.0
sudo ss -tnlp | grep 3306
# → 0.0.0.0:3306 = плохо, 127.0.0.1:3306 = хорошо (если нет сетевого доступа)
```

## Workflow реагирования на инцидент безопасности

### Фаза 1: Сдерживание (Containment)

1. **Изолируйте инстанс при необходимости.** Если обнаружена активная компрометация:
   ```bash
   # Блокировка всех входящих подключений (кроме вашего)
   sudo iptables -A INPUT -p tcp --dport 3306 -s <your_ip> -j ACCEPT
   sudo iptables -A INPUT -p tcp --dport 3306 -j DROP

   # Или через UFW
   sudo ufw deny 3306/tcp
   ```

2. **Сохраните текущее состояние.** Не перезапускайте сервер до сбора доказательств:
   ```bash
   # Снимок процессов
   sudo ps aux > /tmp/incident_processes.txt

   # Снимок открытых соединений
   sudo ss -tnp > /tmp/incident_connections.txt

   # Копия error log (моментальный снимок)
   sudo cp /var/log/mysql/error.log /tmp/incident_error.log

   # Копия audit log
   sudo cp /var/log/mysql/audit.log /tmp/incident_audit.log
   ```

3. **Не удаляйте логи.** Даже если они кажутся пустыми — отсутствие логов само по себе является инцидентом.

### Фаза 2: Анализ (Analysis)

1. **Определите вектор атаки.** Ответьте на вопросы:
   - Откуда было подключение? (`information_schema.PROCESSLIST` → `Host`)
   - Какие SQL-команды выполнялись? (`audit.log` или `mariadb-binlog`)
   - Какие данные были затронуты? (`mariadb-binlog` с `--base64-output=DECODE-ROWS`)
   - Какие учётные записи были скомпрометированы? (`mysql.user` → `password_last_changed`)

2. **Проверьте целостность системы.**
   ```bash
   # Проверка, что нет неизвестных файлов в datadir
   sudo find /var/lib/mysql -type f -newer /var/log/mysql/error.log

   # Проверка, что нет неизвестных пользователей
   SELECT User, Host, plugin FROM mysql.user WHERE User NOT IN ('root', 'mysql.sys', 'mysql.session');

   # Проверка crontab на наличие подозрительных задач
   sudo crontab -l
   sudo ls -la /etc/cron.d/
   ```

3. **Коррелируйте события по времени.** Используйте GTID для точного временного отслеживания:
   ```sql
   -- Найдите транзакции за период подозрения
   SELECT *, ExtractTimestamp(header) AS ts
   FROM mysql.gtid_event
   WHERE ts BETWEEN '2026-08-20 14:00:00' AND '2026-08-20 15:00:00';

   -- Или через mariadb-binlog
   mariadb-binlog --start-datetime="2026-08-20 14:00:00" \
                  --stop-datetime="2026-08-20 15:00:00" \
                  --base64-output=DECODE-ROWS -v \
                  /var/log/mysql/mariadb-bin.000003 | grep -E "DROP|DELETE|GRANT"
   ```

### Фаза 3: Устранение (Remediation)

1. **Смените все скомпрометированные пароли.** Начните с root, затем сервисные аккаунты:
   ```sql
   ALTER USER 'root'@'localhost' IDENTIFIED BY '<new_strong_password>';
   ALTER USER 'app_svc'@'10.0.5.%' IDENTIFIED BY '<new_password>';
   ```

2. **Отзовите компрометированные привилегии.** Проверьте, не создал ли злоумышленник новых пользователей или не выдал ли себе `SUPER`:
   ```sql
   SELECT User, Host, Super_priv FROM mysql.user WHERE Super_priv = 'Y';
   -- Удалите неизвестных пользователей
   DROP USER 'suspicious'@'unknown_host';
   ```

3. **Восстановите данные из бэкапа**, если данные были изменены/удалены. Используйте PITR с GTID для точного восстановления. Подробнее: **[Резервное копирование и восстановление](../backup_and_recovery.md)**.

4. **Обновите все пароли и ключи.** Если злоумышленник получил доступ к файловой системе — смените KEK для TDE и перезапустите `file_key_management`.

### Фаза 4: Восстановление (Recovery)

1. **Верните сервис в рабочее состояние.** Только после полного анализа и устранения причины.
2. **Настройте мониторинг на повторение.** Добавьте алерты на:
   - Неудачные входы (`Access denied` в error log)
   - Изменения в `mysql.user` (через `server_audit`)
   - Необычный объём `DELETE`/`DROP` (через `mariadb-binlog`)
    - Изменение `server_audit_logging` или `log_warnings`

3. **Сохраните доказательства.** Архивируйте логи, бэкапы и вывод диагностических команд в неизменяемое хранилище.

## Диагностика прав и файловой системы

### Проверка прав на критические файлы

```bash
# Права на datadir
sudo find /var/lib/mysql -type d -exec stat -c "%a %U:%G %n" {} \;
# → 750 mysql:mysql на каталоги

# Права на binlog
sudo find /var/log/mysql -type f -exec stat -c "%a %U:%G %n" {} \;
# → 660 mysql:mysql на файлы

# Проверка, что нет файлов с правами 777 или чужим владельцем
sudo find /var/lib/mysql -perm /777 -o -user root -o -group root
```

### Проверка, что сервер не запущен от root

```bash
ps aux | grep mysqld
# → mysql    1234  0.5  3.2  123456  23456 ?  Ssl  12:00   0:05 /usr/sbin/mysqld

# Если процесс запущен от root — это критическая уязвимость
```

### Проверка на наличие подозрительных файлов

```bash
# Недавно изменённые файлы в datadir
sudo find /var/lib/mysql -type f -mtime -1

# Исполняемые файлы в datadir (не должны быть)
sudo find /var/lib/mysql -type f -executable

# Символические ссылки (должны быть отключены)
sudo find /var/lib/mysql -type l
```

## Аудит безопасности инстанса

### Быстрый SQL-аудит

```sql
-- Пользователи с удалённым доступом
SELECT User, Host, plugin FROM mysql.user WHERE Host NOT IN ('localhost', '127.0.0.1', '::1');

-- Анонимные пользователи
SELECT User, Host FROM mysql.user WHERE User = '';

-- Пользователи с SUPER
SELECT User, Host, Super_priv FROM mysql.user WHERE Super_priv = 'Y';

-- Глобальные привилегии (всё кроме root)
SELECT Grantee, Table_type, Privilege_type
FROM information_schema.USER_PRIVILEGES
WHERE Grantee NOT LIKE "'root'%";

-- Роли без членов (неиспользуемые)
SELECT * FROM mysql.role_edges WHERE TO_USER IS NULL;

-- Пользователи без пароля
SELECT User, Host, authentication_string FROM mysql.user WHERE authentication_string IS NULL OR authentication_string = '';

-- Политика паролей
SHOW VARIABLES LIKE 'validate_password%';
SHOW VARIABLES LIKE 'default_password_lifetime';

-- TLS статус
SHOW VARIABLES LIKE 'have_ssl';
SHOW VARIABLES LIKE 'require_secure_transport';

-- Аудит статус
SHOW PLUGINS LIKE 'server_audit';
SHOW VARIABLES LIKE 'server_audit%';

-- Шифрование
SHOW VARIABLES LIKE 'innodb_encrypt%';
SHOW VARIABLES LIKE 'encrypt_binlog';
SHOW VARIABLES LIKE 'encrypt_tmp_disk_tables';

-- Опасные параметры
SHOW VARIABLES LIKE 'local_infile';
SHOW VARIABLES LIKE 'skip_show_database';
SHOW VARIABLES LIKE 'log_warnings';
```

### Проверка поверхности атаки

```sql
-- Запрещённые функции (если используется sql_mode)
SELECT * FROM information_schema.ROUTINES
WHERE ROUTINE_TYPE = 'FUNCTION'
  AND ROUTINE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema');

    -- Представления, раскрывающие чувствительные данные
    SELECT TABLE_SCHEMA, TABLE_NAME, VIEW_DEFINITION
    FROM information_schema.VIEWS
    WHERE VIEW_DEFINITION LIKE '%password%'
       OR VIEW_DEFINITION LIKE '%secret%'
       OR VIEW_DEFINITION LIKE '%credit%';

-- Триггеры на чувствительных таблицах
SELECT TRIGGER_SCHEMA, TRIGGER_NAME, EVENT_MANIPULATION, ACTION_STATEMENT
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema');
```

## Метрики инцидентов и postmortem

### Метрики безопасности (Security Metrics)

Отслеживайте метрики для оценки эффективности защиты и скорости реагирования:

| Метрика | Как измерить | Целевое значение |
| :--- | :--- | :--- |
| MTTD (Mean Time To Detect) | время от события до обнаружения (по audit.log/SIEM) | < 1 часа для критичных |
| MTTR (Mean Time To Respond) | время от обнаружения до сдерживания | < 4 часов |
| Количество `Access denied`/час | `grep "Access denied" error.log \| wc -l` | baseline ± 2σ |
| Доля инстансов с аудитом | `server_audit_logging = ON` | 100% |
| Доля инстансов с TLS | `require_secure_transport = ON` | 100% |
| Просроченные TLS-сертификаты | мониторинг `notAfter` | 0 |
| Неиспользуемые привилегированные аккаунты | аудит `mysql.user` | 0 |

### Postmortem (разбор инцидента)

После каждого инцидента безопасности создавайте postmortem:

**Структура postmortem:**

1. **Резюме** — что произошло, затронутые данные/системы, длительность.
2. **Timeline** — хронология с точными временными метками (NTP-синхронизированными).
3. **Вектор атаки** — как проникли (слабый пароль, уязвимость, инсайдер, misconfiguration).
4. **Влияние** — какие данные скомпрометированы/изменены/удалены (по binlog/audit.log).
5. **Обнаружение** — как выявили (алерт, ручная проверка, внешний сигнал); почему не раньше.
6. **Сдерживание** — действия по изоляции.
7. **Устранение** — что исправлено (пароли, привилегии, конфигурация).
8. **Корневая причина (Root Cause)** — почему защита не сработала.
9. **Preventive measures** — конкретные действия с владельцами и сроками.
10. **Уроки** — что изменилось в процессах/мониторинге.

**Шаблон:**

```markdown
# Postmortem: <краткое название инцидента>

**Дата:** YYYY-MM-DD
**Серьёзность:** P1/P2/P3
**Статус:** Open/Closed

## Timeline
- YYYY-MM-DD HH:MM — первое подозрительное событие (источник: audit.log)
- YYYY-MM-DD HH:MM — обнаружение
- YYYY-MM-DD HH:MM — сдерживание
- YYYY-MM-DD HH:MM — восстановление

## Вектор атаки
...

## Корневая причина
...

## Preventive measures
- [ ] Действие 1 — владелец, срок
- [ ] Действие 2 — владелец, срок
```

**Хранение:** postmortem храните в системе отслеживания (Jira, GitLab) с доступом для команды безопасности; не в общих каналах.

### NTP для forensic-расследований

Корректная реконструкция инцидента требует синхронизированных часов на всех узлах (СУБД, SIEM, файрвол, приложения).

**Проверка синхронизации:**

```bash
# Текущий статус синхронизации
chronyc tracking
# → System time : 0.000000001 seconds fast of NTP time
# → Leap status   : Normal

# Источники времени
chronyc sources -v
# → ^* ntp.example.com  ...

# Дрейф часов
chronyc sourcestats
```

**Требования для forensic:**
- Все узлы кластера, SIEM и файрвол синхронизированы с одним NTP-пулом.
- Дрейф > 1 секунды — алерт.
- Фиксируйте часовой пояс (`timedatectl`) — временные метки в логах локальны.
- При расследовании сверяйте время событий из разных источников (audit.log, binlog, OS-логи) с учётом NTP-дрейфа.

Подробнее о настройке NTP: [Аудит — синхронизация времени](audit.md#синхронизация-времени-ntp-для-корреляции).

## Лучшие практики (SRE / Sysadmin)

1. **Один источник истины для troubleshooting.** Не дублируйте ошибки в нескольких файлах. Используйте этот файл как навигатор, детали — в специализированных файлах.
2. **Сохраняйте доказательства в неизменяемом хранилище.** Архивируйте audit.log и error.log в SIEM или WORM-хранилище до начала remediation.
3. **Не перезапускайте сервер до сбора доказательств.** Перезапуск сбрасывает `information_schema.PROCESSLIST` и временные данные.
4. **Используйте GTID для forensic.** GTID позволяет точно отследить, какие транзакции были выполнены, даже при ротации binlog.
5. **Мониторьте `server_audit_logging`.** Если аудит выключен — это критический инцидент ИБ. Добавьте алерт.
6. **Тестируйте восстановление на staging.** Регулярно проверяйте, что вы можете восстановить данные из последнего бэкапа + binlog.
7. **Документируйте инциденты.** Создавайте postmortem с описанием: вектор атаки, Timeline, remediations, preventive measures.
8. **Автоматизируйте рутинные проверки.** Настройте скрипты, которые ежедневно проверяют:
   - Отсутствие анонимных пользователей
   - Отсутствие `root@%`
   - `require_secure_transport = ON`
   - `server_audit_logging = ON`
   - `encrypt_binlog = ON`
   - `binlog_format = ROW`
9. **Используйте отдельный раздел для логов.** Выделите отдельный раздел/точку монтирования для `/var/log/mysql/`. Это предотвращает заполнение корневого раздела при атаке DoS через логи.
10. **Ротация ключей.** KEK для TDE ротируйте ежеквартально и внепланово при подозрении на компрометацию.

## Дополнительная информация

### Ссылки на специализированные troubleshooting-файлы

- **[Аутентификация](authentication.md)** — `Access denied`, `ERROR 1819`, PAM, `caching_sha2_password`, `max_password_errors`.
- **[SSL/TLS](ssl-tls.md)** — `ERROR 2026`, сертификаты, mTLS, CRL.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation`, root после смены плагина, `skip-show-database`.
- **[Ролевая модель (RBAC)](rbac.md)** — `Access denied` после `GRANT`, `ERROR 1396`, `ERROR 3510`, потери прав.
- **[Аудит](audit.md)** — пустые аудит-логи, производительность `server_audit`.
- **[Шифрование данных (TDE)](tde.md)** — `Unable to decrypt tablespace`, KEK/DEK.
- **[Бинарное логирование](binary-logging.md)** — binlog ошибки, `mariadb-binlog`, `Error 1236`, диск заполнен.
- **[Диагностика репликации](../replication/troubleshooting.md)** — `Error 1032`, `Error 1060`, GTID, лаг.
- **[Отказоустойчивость](../high_availability.md)** — `SST failed`, Galera, Split-Brain.

### Смежные темы

- **[Обзор безопасности](index.md)** — модель безопасности, Defense-in-Depth.
- **[Сетевая безопасность](network-security.md)** — файрвол, `bind-address`, DoS-защита.
- **[Резервное копирование и восстановление](../backup_and_recovery.md)** — PITR, бэкапы, восстановление после инцидента.
- **[Конфигурация MariaDB](../configuration.md)** — `my.cnf`, иерархия загрузки, `sql_mode`.
- **[Мониторинг MariaDB](../monitoring.md)** — алерты, Performance Schema, SRE-метрики.
- **[Безопасная установка СУБД](../../installation_security.md)** — общие принципы закалки.

### Внешние ресурсы

- [MariaDB Security Guide](https://mariadb.com/docs/server/security/)
- [MariaDB Audit Plugin](https://mariadb.com/docs/server/security/audit-logs/server-side)
- [MariaDB Error Codes](https://mariadb.com/docs/server/errors/)
- [CIS MariaDB Benchmark](https://www.cisecurity.org/benchmark/mariadb)
