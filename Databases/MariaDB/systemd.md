# MariaDB под systemd: юнит, лимиты и тюнинг

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

## Определения

*   **`mariadb.service`** — systemd-юнит MariaDB Server. Тип: `Type=notify` (сервер уведомляет systemd о готовности через `sd_notify`). Исполняемый: `/usr/bin/mariadbd` (через `mariadbd-safe` wrapper на старых системах).
*   **`mariadb@.service`** — шаблон-юнит для запуска нескольких инстансов MariaDB на одном хосте (multi-instance). Каждый инстанс использует свой `my.cnf` и datadir.
*   **`LimitNOFILE`** — лимит открытых файловых дескрипторов для процесса. Критичен для MariaDB: каждая таблица, соединение и временный файл потребляет дескриптор. По умолчанию часто 1024 — недостаточно для production.
*   **`LimitCORE`** — лимит core dump. Для диагностики crash — `unlimited`.
*   **`TasksMax`** — лимит потоков (threads) в cgroup. Для Thread Pool требует `infinity` или высокое значение.
*   **`PrivateTmp`** — изоляция `/tmp`. Для MariaDB обычно `false` (временные таблицы и загрузки используют общий `tmpdir`).
*   **`ProtectSystem` / `ProtectHome`** — sandbox-опции systemd. Для MariaDB `ProtectSystem=full` (datadir доступен на запись через `ReadWritePaths`).
*   **`NoNewPrivileges`** — запрет получения новых привилегий через `execve`.
*   **Socket Activation** — механизм systemd, при котором MariaDB запускается при первом подключении к сокету. Параметр `bind-address` игнорируется; привязка выполняется через systemd.

## Основные концепты

### Структура юнита

Типичный `/lib/systemd/system/mariadb.service` (MariaDB 11.4/12.3):

```ini
[Unit]
Description=MariaDB 11.4.7 database server
Documentation=man:mariadbd(8) https://mariadb.com/kb/en/
After=network.target
After=time-sync.target

[Install]
WantedBy=multi-user.target
Alias=mysql.service

[Service]
Type=notify
User=mysql
Group=mysql
ExecStart=/usr/bin/mariadbd $MYSQLD_OPTS $_WSREP_NEW_CLUSTER
ExecStartPost=/usr/bin/mariadb-check-upgrade
ExecStop=/usr/bin/mariadb-admin shutdown
Restart=on-abort
RestartSec=5s
TimeoutStartSec=300
TimeoutStopSec=600
LimitNOFILE=10000
LimitCORE=unlimit
TasksMax=infinity
PrivateTmp=false
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_SETGID CAP_SETUID CAP_CHOWN CAP_FOWNER CAP_SETFCAP CAP_IPC_LOCK CAP_SYS_RESOURCE
```

### Ключевые лимиты

| Лимит | По умолчанию | Рекомендация production | Назначение |
| :--- | :--- | :--- | :--- |
| `LimitNOFILE` | 1024 (или 5000) | 10000–65535 | Файловые дескрипторы (таблицы, соединения, временные файлы) |
| `LimitCORE` | 0 | `unlimited` (для диагностики) | Core dump при crash |
| `TasksMax` | 4915 (systemd default) | `infinity` | Лимит потоков (Thread Pool, Galera) |
| `LimitMEMLOCK` | 65536 | `unlimited` (при `innodb_buffer_pool_lock`) | Заблокированная память |

**Расчёт `LimitNOFILE`:**
```bash
# Формула: max_connections + table_open_cache * 2 + 1000 (запас)
# Пример: max_connections=2000, table_open_cache=8000
# Минимум: 2000 + 16000 + 1000 = 19000 → рекомендуется 65535
```

### Multi-instance (mariadb@.service)

Для запуска нескольких инстансов на одном хосте:

```bash
# 1. Создать datadir для инстанса
sudo mkdir -p /var/lib/mysql3307
sudo chown mysql:mysql /var/lib/mysql3307
sudo mysql_install_db --datadir=/var/lib/mysql3307 --user=mysql

# 2. Создать конфиг инстанса
# /etc/mysql/mariadb.conf.d/99-instance-3307.cnf
[mariadb@3307]
port = 3307
datadir = /var/lib/mysql3307
socket = /run/mysqld/mysqld3307.sock
log_error = /var/log/mysql/mariadb3307.log
pid_file = /run/mysqld/mariadb3307.pid

# 3. Запустить инстанс
sudo systemctl start mariadb@3307
sudo systemctl enable mariadb@3307

# 4. Проверить
sudo systemctl status mariadb@3307
mariadb -S /run/mysqld/mysqld3307.sock -u root -p
```

Каждый инстанс получает свой override: `systemctl edit mariadb@3307`.

## Предварительные требования (Prerequisites)

- **systemd версии 232+** (поддержка `TasksMax`, `Delegate=yes`)
- **Пользователь `mysql`** и группа `mysql` существуют
- **Директории** `/var/lib/mysql`, `/var/log/mysql`, `/run/mysqld` с правами `mysql:mysql`
- **MariaDB 10.11+** (10.6 EOL июль 2026, не рекомендуется для новых развёртываний)

## Операции и команды (Operations and Commands)

### Просмотр и управление юнитом

```bash
# Статус сервиса
systemctl status mariadb

# Все свойства юнита
systemctl show mariadb.service

# Текущие лимиты процесса (runtime)
cat /proc/$(pgrep -x mariadbd)/limits

# Количество открытых дескрипторов
ls /proc/$(pgrep -x mariadbd)/fd | wc -l

# cgroup лимиты
cat /sys/fs/cgroup/system.slice/mariadb.service/tasks.max
cat /sys/fs/cgroup/system.slice/mariadb.service/pids.max
```

### Изменение лимитов (override)

```bash
# Создать override (редактор откроется автоматически)
sudo systemctl edit mariadb.service

# Содержимое override-файла
[Service]
LimitNOFILE=65535
LimitCORE=unlimited
TasksMax=infinity
LimitMEMLOCK=unlimited
TimeoutStopSec=600
```

```bash
# Применить
sudo systemctl daemon-reload
sudo systemctl restart mariadb

# Проверить применение
systemctl show mariadb.service -p LimitNOFILE -p LimitCORE -p TasksMax -p LimitMEMLOCK -p TimeoutStopSec
# → LimitNOFILE=65535
# → LimitCORE=18446744073709551615
# → TasksMax=18446744073709551615
# → LimitMEMLOCK=18446744073709551615
# → TimeoutStopSec=10min
```

### Настройка переменных окружения

```bash
# Через override
sudo systemctl edit mariadb.service
[Service]
Environment=MYSQLD_OPTS="--skip-name-resolve --performance-schema-consumer-thread-instances=ON"

# Или через environment-файл (Debian/Ubuntu)
# /etc/default/mariadb
MYSQLD_OPTS="--skip-name-resolve"

# RHEL/CentOS
# /etc/sysconfig/mariadb
MYSQLD_OPTS="--skip-name-resolve"
```

### Socket Activation

```bash
# 1. Отключить стандартный юнит
sudo systemctl disable --now mariadb.service

# 2. Включить socket
sudo systemctl enable --now mariadb.socket

# mariadb.socket (обычно в /lib/systemd/system/mariadb.socket):
[Unit]
Description=MariaDB Socket

[Socket]
ListenStream=/run/mysqld/mysqld.sock
ListenStream=3306
Accept=no

[Install]
WantedBy=sockets.target

# 3. Проверить: процесс должен отсутствовать до подключения
ss -tlnp | grep 3306
# → LISTEN 0 80 *:3306 *:* users:(("systemd",pid=1,fd=...))
# подключение:
mysql -u root -p
# → процесс mariadbd запущен
```

### Валидация конфигурации

```bash
# Проверка синтаксиса юнита
systemd-analyze verify /lib/systemd/system/mariadb.service

# Валидация MariaDB конфигурации
mariadbd --validate-config
# → ошибок нет, вывод пуст

# Полный тест запуска
sudo -u mysql mariadbd --verbose --help 2>&1 | head -30
```

### Отладка и диагностика

```bash
# Логи загрузки (текущая загрузка)
journalctl -u mariadb -b

# Последние 100 строк
journalctl -u mariadb -n 100 --no-pager

# Фильтр по приоритету
journalctl -u mariadb -p err
journalctl -u mariadb -p warning

# Follow mode
journalctl -u mariadb -f

# Запуск в foreground (для отладки конфига)
sudo systemctl stop mariadb
sudo -u mysql /usr/bin/mariadbd --console

# Проверка зависимостей
systemctl list-dependencies mariadb.service
systemctl list-dependencies mariadb.service --reverse
```

### Управление перезапуском

```bash
# Graceful shutdown (ожидает завершения транзакций)
sudo systemctl stop mariadb

# Force stop (через TimeoutStopSec)
sudo systemctl kill -s SIGKILL mariadb

# Restart с reload конфигурации
sudo systemctl reload mariadb  # только если поддерживается
sudo systemctl restart mariadb

# После обновления пакета
sudo systemctl daemon-reload
sudo systemctl restart mariadb
mariadb-upgrade
```

## Устранение неполадок (Troubleshooting)

### 1. «Too many open files»

*   **Причина:** `LimitNOFILE` ниже, чем требуется (`max_connections` + `table_open_cache` * 2 + запас).
*   **Диагностика:**
    ```bash
    cat /proc/$(pgrep -x mariadbd)/limits | grep "Max open files"
    ls /proc/$(pgrep -x mariadbd)/fd | wc -l
    journalctl -u mariadb | grep -i "too many open files"
    ```
*   **Решение:** увеличьте `LimitNOFILE` через `systemctl edit mariadb.service` (см. Operations).
*   **Профилактика:** мониторьте `Open_files` / `Open_table_definitions` в `SHOW GLOBAL STATUS`.

### 2. Сервис не запускается после обновления

*   **Причина:** не выполнен `mariadb-upgrade`, несовместимость конфигурации, удалённый параметр в `my.cnf` (`innodb_buffer_pool_instances`, `big_tables`, `storage_engine`, `sql_big_tables`).
*   **Диагностика:**
    ```bash
    journalctl -u mariadb -b | grep -i -e error -e fail
    mariadbd --validate-config
    ```
*   **Решение:** выполните `mariadb-upgrade`; проверьте `my.cnf` на удалённые/устаревшие параметры.
*   **Важно:** после MariaDB 12.0 удалены `big_tables`, `sql_big_tables`, `innodb_buffer_pool_instances` — их наличие блокирует старт.

### 3. Thread Pool не работает / ошибки создания потоков

*   **Причина:** `TasksMax` systemd ограничивает количество потоков.
*   **Диагностика:**
    ```bash
    systemctl show mariadb.service -p TasksMax
    journalctl -u mariadb | grep -i "thread\|pthread"
    ```
*   **Решение:** установите `TasksMax=infinity` в override.

### 4. Сервис зависает при остановке (timeout)

*   **Причина:** долгие транзакции, блокировки, большой `innodb_buffer_pool` с `innodb_buffer_pool_dump_at_shutdown=ON`.
*   **Диагностика:**
    ```bash
    journalctl -u mariadb -b | tail -50
    # Ищите "Shutdown complete" или таймаут
    ```
*   **Решение:**
    - увеличьте `TimeoutStopSec=600` (или больше) в override
    - проверьте долгие транзакции перед остановкой: `SHOW ENGINE INNODB STATUS\G`
    - рассмотрите `innodb_buffer_pool_dump_at_shutdown=OFF` для быстрой остановки

### 5. Ошибка доступа к datadir / Permission denied

*   **Причина:** неверные права на `/var/lib/mysql`, SELinux/AppArmor блокирует доступ, `ProtectSystem=full` без `ReadWritePaths`.
*   **Диагностика:**
    ```bash
    ls -la /var/lib/mysql
    journalctl -u mariadb -b | grep -i -e permission -e selinux -e apparmor
    ```
*   **Решение:**
    - `chown -R mysql:mysql /var/lib/mysql /var/log/mysql /run/mysqld`
    - для SELinux: `restorecon -Rv /var/lib/mysql`
    - при `ProtectSystem=full` добавьте в override:
      ```ini
      [Service]
      ReadWritePaths=/var/lib/mysql /var/log/mysql /run/mysqld /tmp
      ```

### 6. Core dump не создаётся при краше

*   **Причина:** `LimitCORE=0` или `fs.suid_dumpable=0`, отсутствует `/var/lib/systemd/coredump`.
*   **Диагностика:**
    ```bash
    cat /proc/$(pgrep -x mariadbd)/limits | grep "Max core file size"
    sysctl fs.suid_dumpable
    coredumpctl list | head
    ```
*   **Решение:**
    - override: `LimitCORE=unlimited`
    - `sysctl -w fs.suid_dumpable=1` (или в `/etc/sysctl.d/99-mariadb.conf`)
    - убедитесь, что `systemd-coredump` установлен и активен

### 7. Socket Activation не работает

*   **Причина:** конфликт с `mariadb.service`, неверный путь сокета в `mariadb.socket`, `bind-address` в `my.cnf` переопределяет.
*   **Диагностика:**
    ```bash
    systemctl status mariadb.socket
    systemctl status mariadb.service
    ss -tlnp | grep 3306
    cat /etc/systemd/system/mariadb.socket
    ```
*   **Решение:**
    - `systemctl disable --now mariadb.service`
    - `systemctl enable --now mariadb.socket`
    - удалите `bind-address` из `my.cnf` (игнорируется при socket activation)

## Лучшие практики (Best Practices)

1.  **`LimitNOFILE` ≥ 10000** для production (расчёт: `max_connections` + `table_open_cache` * 2 + 1000).
2.  **Используйте `systemctl edit`** для override — не редактируйте `/lib/systemd/system/` напрямую (перезаписывается при обновлении пакета).
3.  **`daemon-reload` после любых изменений** override-файлов.
4.  **`mariadb-upgrade` после обновления пакета** — обязательно, до перезапуска приложения.
5.  **Мониторьте дескрипторы:** `ls /proc/$(pgrep -x mariadbd)/fd | wc -l` vs `LimitNOFILE` (alert при >80%).
6.  **`TasksMax=infinity`** при использовании Thread Pool или Galera.
7.  **`TimeoutStopSec=600`** для баз с большим буферным пулом (>50GB) или включенным дампом пула.
8.  **Hardening через override** (не через редактирование unit-файла):
    ```ini
    [Service]
    ProtectSystem=full
    ProtectHome=true
    NoNewPrivileges=yes
    PrivateTmp=true
    ProtectKernelTunables=yes
    ProtectKernelModules=yes
    ProtectControlGroups=yes
    RestrictRealtime=yes
    RestrictSUIDSGID=yes
    LockPersonality=yes
    MemoryDenyWriteExecute=yes
    ```
9.  **Multi-instance** через `mariadb@.service` для изоляции нагрузок на одном хосте — каждый с отдельным override.
10. **Логи в journald** — не дублируйте `log_error` в файл, если используете systemd (см. **[Управление логами](log_management.md)**).
11. **Проверяйте `@@global.sql_mode` и лимиты** после каждого рестарта — расхождения обнаруживаются в инциденте.

## Дополнительная информация

### См. также

- **[Конфигурация](configuration.md)** — `my.cnf`, системные переменные.
- **[Установка и настройка](installation_and_setup.md)** — установка пакетов, hardening скрипт.
- **[Безопасность: Начальная закалка](security/hardening.md)** — systemd hardening drop-in.
- **[Безопасность: Сетевая безопасность](security/network-security.md)** — socket activation, bind-address.
- **[Управление памятью](memory_management.md)** — лимиты памяти, `LimitMEMLOCK`.
- **[Мониторинг](monitoring.md)** — метрики экспортера, `LimitNOFILE` для экспортера.
- **[Управление логами](log_management.md)** — journald, ротация, `sql_errlog`.
- **[Zero-Downtime Upgrade](Operations/zero_downtime_upgrade.md)** — systemd при rolling upgrade.

### Внешние ресурсы

- [MariaDB systemd](https://mariadb.com/kb/en/systemd/)
- [MariaDB Multi-Instance](https://mariadb.com/kb/en/multi-instance/)
- [systemd.exec (limits)](https://www.freedesktop.org/software/systemd/man/systemd.exec.html)
- [systemd.service](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [mariadbd](https://mariadb.com/kb/en/mariadbd/)