# Установка и настройка MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**MariaDB** — реляционная система управления базами данных (RDBMS) с открытым исходным кодом, развивающаяся как высокопроизводительный и функционально богатый форк MySQL. Управляется независимым **MariaDB Foundation**.

**LTS (Long Term Support)** — версии с долгосрочной поддержкой, обеспечивающие стабильность API и гарантированные обновления безопасности. Приоритетны для production-сред.

**GPG Key (GnuPG Key)** — криптографический ключ, используемый для проверки подлинности и целостности пакетов в репозиториях Linux. Начиная с 2025 года MariaDB использует новый ключ `mariadb-keyring-2025.gpg`, размещаемый в `/etc/apt/trusted.gpg.d/` (Debian/Ubuntu) или `/etc/pki/rpm-gpg/` (RHEL-семейство).

**Unix Socket (`unix_socket`)** — плагин аутентификации, позволяющий пользователям ОС подключаться к БД без пароля, если их системный UID совпадает с именем пользователя в базе (актуально для `root` через `sudo`). Установлен по умолчанию в MariaDB на Unix-системах. Подробнее о настройке и использовании см. в **[Аутентификация и политика паролей](security/authentication.md)**.

**`mariadb_repo_setup`** — официальный скрипт MariaDB Foundation для автоматической настройки репозитория пакетов. Поддерживает флаги `--mariadb-server-version`, `--os-type`, `--os-version`, `--skip-key-import`, `--skip-server`, `--skip-tools`. Начиная с 2026 года, скрипт по умолчанию использует Deb822-format (`mariadb.sources`) на Debian/Ubuntu и импортирует ключ в `/etc/apt/trusted.gpg.d/mariadb-keyring-2025.gpg`.

**`apt-key`** — устаревший механизм управления GPG-ключами в Debian/Ubuntu. Использование `apt-key` deprecated и удалено в Debian 13 / Ubuntu 25.04+. Рекомендуется размещение ключей в `/etc/apt/trusted.gpg.d/` с правами `644`.

**dirmgr** — пакет, требуемый для работы `apt-key adv --keyserver` на минимальных установках Debian/Ubuntu. При использовании современного подхода с ключом в `/etc/apt/trusted.gpg.d/` пакет `dirmgr` не требуется.

**Data Directory (`datadir`)** — каталог на диске, где MariaDB хранит файлы данных, индексов и логов. По умолчанию: `/var/lib/mysql` (RHEL/Debian) или `/var/db/mysql` (SLES). Должен находиться на отдельном разделе или массиве с достаточным запасом места.

**Socket Activation** — механизм systemd, при котором MariaDB запускается при первом подключении к сокету. При socket activation параметр `bind-address` игнорируется; привязка выполняется через systemd. Проверяйте `ss -tlnp | grep 3306` — в выводе должен быть `systemd`, а не `mysqld`. Подробнее см. **[MariaDB под systemd](systemd.md#socket-activation)**.

## Базовые концепции

### Жизненный цикл и выбор версии

Для продуктивных систем следует выбирать актуальные LTS-ветки. Использование Rolling релизов (например, 12.1, 12.2) в production не рекомендуется из-за короткого цикла поддержки.

| Версия | Статус | Поддержка до | Ключевые фичи |
| :--- | :--- | :--- | :--- |
| **12.3 LTS** | Рекомендуемая | Июнь 2029 | Атомарные логи InnoDB, 4x производительность binlog, `sql_mode=ORACLE` |
| **11.8 LTS** | Стабильная | Июнь 2028 | Оптимизации оптимизатора, `slave_domain_parallel_threads` |
| **11.4 LTS** | Зрелая | Июнь 2029 | `binlog_gtid_index` (default ON), улучшенная стабильность |
| **10.11 LTS** | Наследие | Февраль 2028 | Высокая стабильность, широкая поддержка ОС |

**Важно:** MariaDB 12.3 LTS требует отдельного пакета `mariadb-server-galera` для кластерных развертываний (в отличие от предыдущих версий, где Galera входил в зависимость `mariadb-server`). Подробнее см. в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**.

### Иерархия конфигурации MariaDB

MariaDB считывает конфигурационные файлы в жестко определенном порядке. Если параметр встречается в нескольких файлах, применяется значение из **последнего** считанного файла:

1.  **`/etc/my.cnf`**: Глобальные настройки системы.
2.  **`/etc/my.cnf.d/**` (RHEL/CentOS) или **`/etc/mysql/mariadb.conf.d/**` (Debian/Ubuntu): Модульные файлы.
    - *Важно:* Файлы считываются в алфавитном порядке. Файлы с префиксами `99-custom.cnf` переопределяют настройки из `50-server.cnf`.
3.  **`/etc/mysql/my.cnf`**: Дополнительный глобальный путь (зависит от дистрибутива).
4.  **`~/.my.cnf`**: Пользовательские настройки. Используются для хранения учетных данных (`[client] user=... password=...`) для автоматизации без ввода пароля.

**`MARIADB_GROUP_SUFFIX`:** Этот механизм позволяет одному файлу конфигурации обслуживать разные окружения. Если запустить сервер с переменной окружения `MARIADB_GROUP_SUFFIX=.prod`, он будет считывать секции `[mariadb]` И `[mariadb.prod]`. Это исключает дублирование общих настроек и позволяет переопределять только специфичные параметры.

### Архитектура установки

```
┌─────────────────────────────────────────────────────────────┐
│                     Слой 1: Репозиторий                     │
│              Официальный GPG-подписанный репозиторий         │
│  • mariadb_repo_setup (Deb822 / rpm --import)               │
│  • Ключ: mariadb-keyring-2025.gpg                           │
├─────────────────────────────────────────────────────────────┤
│                     Слой 2: Пакеты                          │
│  • mariadb-server (ядро)                                    │
│  • mariadb-client (CLI)                                     │
│  • galera-4 (опционально, для HA)                          │
│  • mariadb-plugin-server_audit (опционально)               │
├─────────────────────────────────────────────────────────────┤
│                     Слой 3: Данные                          │
│  • datadir (/var/lib/mysql)                                 │
│  • Логи (error, slow, binlog)                               │
│  • Сокет (/run/mysqld/mysqld.sock)                         │
├─────────────────────────────────────────────────────────────┤
│                     Слой 4: Закалка                         │
│  • mariadb-secure-installation (базовый уровень)           │
│  • my.cnf (конфигурационные параметры)                     │
│  • Файрвол хоста                                            │
│  • TLS (опционально)                                        │
│  • Аудит (опционально)                                      │
└─────────────────────────────────────────────────────────────┘
```

### Модель hardening

Эффективная закалка строится из нескольких независимых слоев. Провал одного слоя компенсируется наличием других:

1.  **Базовый уровень:** Скрипт `mariadb-secure-installation` — удаляет анонимных пользователей, тестовую БД, удалённый root-доступ. **Не изменяет** `my.cnf`, файрвол, права ОС или плагины.
2.  **Конфигурационный уровень:** `my.cnf` — параметры сервера, сетевые ограничения, TLS, аудит.
3.  **Сетевой уровень:** `bind-address`, файрвол (UFW/iptables/firewalld), mTLS.
4.  **Уровень ОС:** Права на файлы, systemd hardening, SELinux/AppArmor, sysctl.

Полное руководство по многоуровневой модели hardening см. в **[Безопасность MariaDB: обзор](security/index.md)**. Детальный разбор `mariadb-secure-installation` и OS-level hardening см. в **[Начальная закалка MariaDB](security/hardening.md)**.

## Предварительные требования

### Требования к оборудованию и ОС

| Компонент | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядер |
| **ОЗУ** | 2 ГБ | 8+ ГБ (зависит от рабочего набора данных) |
| **Диск** | 500 МБ + данные | SSD/NVMe (отдельный массив для `datadir`) |
| **Сеть** | 100 Мбит/с | 1 Гбит/с |
| **ОС** | Linux (RHEL 8+, Debian 11+, Ubuntu 20.04+) | Актуальный LTS-дистрибутив с поддержкой ядра 5.4+ |
| **Права** | `sudo` на целевом хосте | Отдельный пользователь `mysql` без shell (`/usr/sbin/nologin`) |

### Подготовка ОС

```bash
# Проверка прозрачных огромных страниц (THP)
cat /sys/kernel/mm/transparent_hugepage/enabled
# → рекомендуется: never

# Отключение THP (временно, до перезагрузки)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# Постоянное отключение THP
echo '[mariadb]
transparent_hugepage=never' | sudo tee /etc/systemd/system/mariadb.service.d/thp.conf
sudo systemctl daemon-reload

# Проверка vm.swappiness
sysctl vm.swappiness
# → рекомендуется: 1

# Проверка vm.overcommit_memory
sysctl vm.overcommit_memory
# → рекомендуется: 2

# Проверка лимитов файловых дескрипторов
ulimit -n
# → должно быть >= 65535 для production

# Проверка memlock
ulimit -l
# → рекомендуется: unlimited
```

**Валидация:**

```bash
# Проверка vm.swappiness
sysctl vm.swappiness
# → vm.swappiness = 1

# Проверка vm.overcommit_memory
sysctl vm.overcommit_memory
# → vm.overcommit_memory = 2

# Проверка открытых файловых дескрипторов для mysql
cat /proc/$(pidof mysqld)/limits | grep "open files"
# → Max open files 65535 65535 files

# Проверка memlock
cat /proc/$(pidof mysqld)/limits | grep "max locked memory"
# → max locked memory unlimited
```

### Подготовка каталогов и прав

```bash
# Создание каталога данных (если не существует)
sudo mkdir -p /var/lib/mysql
sudo chown mysql:mysql /var/lib/mysql
sudo chmod 700 /var/lib/mysql

# Создание каталога сокета
sudo mkdir -p /run/mysqld
sudo chown mysql:mysql /run/mysqld
sudo chmod 755 /run/mysqld

# Создание каталога логов
sudo mkdir -p /var/log/mysql
sudo chown mysql:mysql /var/log/mysql
```

**Валидация:**

```bash
# Проверка владельца каталога данных
ls -ld /var/lib/mysql
# → drwx------ mysql mysql /var/lib/mysql

# Проверка каталога сокета
ls -ld /run/mysqld/
# → drwxr-xr-x mysql mysql /run/mysqld/
```

## Практические сценарии

### Сценарий 1: Установка через официальный репозиторий (Debian / Ubuntu)

**Важно:** Начиная с Debian 13 (Trixie) и Ubuntu 25.04+, устаревший механизм `apt-key` заменен на размещение ключа в `/etc/apt/trusted.gpg.d/`. Скрипт `mariadb_repo_setup` автоматически обрабатывает это.

```bash
# 1. Установка curl (если не установлен)
sudo apt update
sudo apt install -y curl

# 2. Настройка репозитория и GPG-ключей
curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup | sudo bash -s -- --mariadb-server-version="mariadb-12.3"

# Скрипт автоматически:
# - Скачивает mariadb-keyring-2025.gpg в /etc/apt/trusted.gpg.d/
# - Создает файл репозитория (Deb822 format по умолчанию)
# - Выполняет apt-get update

# 3. Установка пакетов
sudo apt install -y mariadb-server mariadb-client
```

**Для RHEL 10 / Rocky Linux 10 / AlmaLinux 10** требуется `dirmgr` только если вы используете `apt-key adv --keyserver` для ручного импорта ключа. `mariadb_repo_setup` для RHEL использует `rpm --import` напрямую, `dirmgr` не требуется.

**Валидация:**

```bash
# Проверка версии
mariadb --version
# → mariadb  Ver 15.1 Distrib 12.3.x-MariaDB

# Проверка статуса сервиса
sudo systemctl status mariadb --no-pager
# → active (running)

# Проверка прослушивания портов
sudo ss -tlnp | grep 3306
# → LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mariadbd",pid=...,fd=...))

# Проверка аутентификации через unix_socket
sudo mariadb -u root -e "SELECT User, Host, Plugin FROM mysql.user WHERE User='root';"
# → root | localhost | unix_socket
```

### Сценарий 2: Установка в RHEL / Rocky Linux / AlmaLinux

```bash
# 1. Установка curl (если не установлен)
sudo dnf install -y curl

# 2. Настройка репозитория
curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup | sudo bash -s -- --mariadb-server-version="mariadb-12.3"

# Скрипт автоматически:
# - Создает /etc/yum.repos.d/mariadb.repo
# - Импортирует GPG-ключи через rpm --import
# - Сохраняет ключи в /etc/pki/rpm-gpg/

# 3. Установка через DNF
sudo dnf install -y MariaDB-server MariaDB-client

# 4. Запуск и включение автозапуска
sudo systemctl start mariadb
sudo systemctl enable mariadb
```

**Валидация:**

```bash
# Проверка версии
mariadb --version
# → mariadb  Ver 15.1 Distrib 12.3.x-MariaDB

# Проверка статуса сервиса
sudo systemctl status mariadb --no-pager
# → active (running)

# Проверка открытых портов
sudo ss -tlnp | grep 3306
# → LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mariadbd",pid=...,fd=...))
```

### Сценарий 3: Послеустановочная закалка безопасности (Hardening)

Скрипт `mariadb-secure-installation` устраняет стандартные уязвимости конфигурации "из коробки". Он **не изменяет** `my.cnf`, файрвол, права ОС или плагины аудита/шифрования.

```bash
sudo mariadb-secure-installation
```

**Рекомендуемые ответы для Production:**
- **Switch to unix_socket authentication? [Y/n]**: `Y`. Обеспечивает безопасность root-доступа через системные права.
- **Change the root password? [Y/n]**: `Y` (установите сложный пароль, даже если используете socket).
- **Remove anonymous users? [Y/n]**: `Y`.
- **Disallow root login remotely? [Y/n]**: `Y`.
- **Remove test database and access to it? [Y/n]**: `Y`.
- **Reload privilege tables now? [Y/n]**: `Y`.

**Важно:** После выполнения скрипта обязательно выполните OS-level hardening (права на файлы, systemd drop-in, SELinux/AppArmor). Детальный разбор см. в **[Начальная закалка MariaDB](security/hardening.md)**.

### Сценарий 4: Проверка корректности запуска и сетевой доступности

```bash
# Проверка статуса сервиса
sudo systemctl status mariadb --no-pager
# → active (running)

# Проверка прослушивания портов
sudo ss -tlnp | grep 3306
# → LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mariadbd",pid=...,fd=...))

# Проверка аутентификации через unix_socket
sudo mariadb -u root -e "SELECT User, Host, Plugin FROM mysql.user WHERE User='root';"
# → root | localhost | unix_socket
```

### Сценарий 5: Создание пользователя для приложения

Создайте отдельного пользователя с минимально необходимыми привилегиями. Никогда не используйте `root` для подключений приложений.

```sql
-- Создание пользователя с минимальными привилегиями
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON app_db.* TO 'app_svc'@'10.0.5.%';
FLUSH PRIVILEGES;
```

**Валидация:**

```bash
# Проверка подключения
mariadb -u app_svc -p -e "SHOW DATABASES;"
# → список БД

# Проверка прав
mariadb -u app_svc -p -e "SHOW GRANTS FOR CURRENT_USER();"
# → GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON app_db.* TO ...
```

### Сценарий 6: Начальная конфигурация my.cnf для production

После установки создайте базовый конфигурационный файл. Детальный тюнинг под конкретную нагрузку см. в **[Конфигурация MariaDB](configuration.md)**.

```ini
[mariadb]
# -- Пути --
datadir                 = /var/lib/mysql
socket                  = /run/mysqld/mysqld.sock
user                    = mysql

# -- Сеть --
bind-address            = 127.0.0.1
max_connections         = 500
max_allowed_packet      = 64M
skip-name-resolve       = 1

# -- Бинарный лог (обязательно для replication/PITR) --
log_bin                 = /var/log/mysql/mariadb-bin
binlog_format           = ROW
binlog_expire_logs_seconds = 2592000
binlog_gtid_index       = ON

# -- InnoDB --
innodb_buffer_pool_size = 4G
innodb_flush_method     = O_DIRECT
innodb_log_file_size    = 512M

# -- Логирование --
slow_query_log          = 1
long_query_time         = 0.5
log_warnings            = 2  # verbosity error log (0-9, default 2)
```

**Валидация:**

```sql
-- Проверка параметров
SHOW VARIABLES LIKE 'bind_address';
-- → bind_address = 127.0.0.1

SHOW VARIABLES LIKE 'max_connections';
-- → max_connections = 500

SHOW VARIABLES LIKE 'binlog_format';
-- → binlog_format = ROW

SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
-- → innodb_buffer_pool_size = 4294967296 (4G)
```

### Сценарий 7: Systemd hardening

Создайте drop-in для сервиса MariaDB для повышения изоляции:

```ini
# /etc/systemd/system/mariadb.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=yes
NoNewPrivileges=yes
PrivateTmp=yes
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart mariadb
```

**Валидация:**

```bash
# Проверка, что drop-in применен
systemctl show mariadb | grep -E "ProtectSystem|ProtectHome|PrivateTmp"
# → ProtectSystem=full
# → ProtectHome=yes
# → PrivateTmp=yes
```

### Сценарий 8: Обновление системных таблиц (mariadb-upgrade)

После мажорного обновления версии (например, 10.11 → 11.4) выполните обновление системных таблиц:

```bash
# Остановка сервиса
sudo systemctl stop mariadb

# Обновление пакетов
sudo apt update && sudo apt install mariadb-server mariadb-client

# Запуск
sudo systemctl start mariadb

# Обновление системных таблиц (обязательно для мажорных версий)
mariadb-upgrade --user=root --password

# Валидация
mariadb -e "SELECT VERSION();"
```

**Важно:** Для минорных обновлений (12.3.1 → 12.3.2) `mariadb-upgrade` обычно не требуется, если Changelog не содержит изменений в системных таблицах. В Galera Cluster запускайте только на одном узле; остальные обновятся через SST. Детали см. в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**.

### Сценарий 9: Проверка закалки после установки

```bash
# Статус сервиса
sudo systemctl status mariadb
# → active (running)

# Открытые порты
sudo ss -tlnp | grep 3306
# → LISTEN 0 80 127.0.0.1:3306 ...

# Отсутствие тестовой БД
mariadb -e "SHOW DATABASES;" | grep -w test
# → (пустой результат — хорошо)

# Отсутствие анонимных пользователей
mariadb -e "SELECT User, Host FROM mysql.user WHERE User = '';"
# → (пустой результат — хорошо)

# Проверка, что root доступен только локально
mariadb -e "SELECT User, Host FROM mysql.user WHERE User = 'root';"
# → root | localhost | unix_socket
```

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`The following signatures couldn't be verified`** | Устаревший GPG-ключ или блокировка трафика к серверам ключей. | `apt-key list` или проверка `/etc/apt/trusted.gpg.d/`. | Перезапустите `mariadb_repo_setup` или импортируйте ключ вручную. На Debian 13+ / Ubuntu 25.04+ используйте ключ в `/etc/apt/trusted.gpg.d/mariadb-keyring-2025.gpg`, `apt-key` deprecated. |
| **`Can't connect to local MySQL server through socket`** | Сервер не запущен или socket в нестандартном пути. | `sudo systemctl status mariadb`; `mysqladmin variables \| grep socket`. | Запустите сервер. Если socket нестандартный, укажите его: `sudo mariadb-secure-installation --socket=/path/to/socket`. |
| **`Access denied for user 'root'@'localhost'`** | Попытка входа без `sudo` при активном `unix_socket`. | `SELECT User, Host, Plugin FROM mysql.user WHERE User='root';`. | Всегда используйте `sudo mariadb` для локального root-доступа. Если требуется доступ без sudo, смените плагин на `ed25519` (см. **[Аутентификация](security/authentication.md)**). |
| **Сервер не запускается после `apt upgrade`** | Не выполнено `mariadb-upgrade` или удаленный параметр в `my.cnf`. | `journalctl -u mariadb \| grep -i error`; проверка `my.cnf` на удаленные параметры. | Выполните `mariadb-upgrade`. Удалите устаревшие параметры (`innodb_buffer_pool_instances`, `big_tables`, `storage_engine`). Параметр `query_cache_size` не удалён в MariaDB — он валиден, но выключен по умолчанию. |
| **`Permission denied` на datadir или socket** | Пользователь `mysql` не имеет прав на запись. | `ls -ld /var/lib/mysql`; `ls -ld /run/mysqld/`. | Установите владельца `mysql:mysql` и права `700` на `datadir`, `755` на каталог сокета. |
| **SELinux блокирует запуск** | Неправильные контексты SELinux на файлах данных или ключах. | `sudo ausearch -m avc -ts recent \| grep mariadb`. | Восстановите контексты: `restorecon -Rv /var/lib/mysql`. Для диагностики временно установите `permissive`. |
| **OOM Killer при установке** | Недостаточно ОЗУ для выполнения `mariadb-upgrade` или восстановления. | `dmesg \| grep -i oom`. | Увеличьте swap или добавьте ОЗУ. Для containerized окружения проверьте cgroup лимиты. |
| **`Too many connections` после установки** | `max_connections` исчерпан или приложение создает слишком много соединений. | `SHOW STATUS LIKE 'Threads_connected';`; `SHOW VARIABLES LIKE 'max_connections';`. | Увеличьте `max_connections` в `my.cnf` или настройте connection pooling на стороне приложения (ProxySQL/MaxScale). |

## Лучшие практики (Best Practices)

1.  **Стратегия 3-2-1-1-0:** 3 копии данных (1 production + 2 бэкапа), 2 разных носителя, 1 копия вне площадки, 1 immutable/air-gapped бэкап, 0 ошибок при проверке. Для MariaDB: локальный диск + NFS/сетевое хранилище + ленточная библиотека или удаленный сервер.
2.  **LTS-версии для production:** Используйте только LTS-версии (10.11, 11.4, 11.8, 12.3). Rolling релизы не предназначены для production из-за короткого цикла поддержки.
3.  **Официальный репозиторий:** Всегда используйте официальный репозиторий MariaDB Foundation, а не устаревшие пакеты из дистрибутива. Это гарантирует своевременные исправления безопасности.
4.  **Установка через `mariadb_repo_setup`:** Избегайте ручного редактирования `.list` файлов. Скрипт автоматически обрабатывает GPG-ключи, архитектуру и версию ОС.
5.  **GPG-ключи:** На Debian 13+ / Ubuntu 25.04+ используйте ключ в `/etc/apt/trusted.gpg.d/mariadb-keyring-2025.gpg`. Не используйте `apt-key` — он deprecated.
6.  **Базовая закалка обязательна:** После установки выполните `mariadb-secure-installation` и OS-level hardening. Без этого production-запуск недопустим.
7.  **unix_socket для root:** Никогда не открывайте root-доступ через сетевой интерфейс. Локальный root должен использовать `unix_socket`.
8.  **Принудительный TLS:** `require_secure_transport = ON` — не опционально для production. Детали см. в **[SSL/TLS](security/ssl-tls.md)**.
9.  **Системный пользователь:** Используйте отдельного пользователя `mysql` без логина в shell (`/usr/sbin/nologin`). Изолируйте `datadir` на отдельном разделе или LUN.
10. **Версионируйте конфигурацию:** `my.cnf` и скрипты hardening должны храниться в Git с аудитом изменений между окружениями.
11. **Тестируйте на staging:** Любые изменения конфигурации и hardening тестируйте на инстансе с идентичной ОС и версией MariaDB перед применением в production.
12. **Systemd hardening:** Используйте drop-in с `ProtectSystem=full`, `ProtectHome=yes`, `NoNewPrivileges=yes`, `PrivateTmp=yes` для изоляции сервиса.
13. **SELinux/AppArmor:** В production-средах используйте enforcing-режим. Настройте политики для разрешения MariaDB доступа только к необходимым директориям и портам.
14. **Ротация binlog:** Настройте `binlog_expire_logs_seconds` не менее, чем `максимальный_лаг_реплики + 1 день`. Без этого PITR-восстановление будет невозможным.
15. **Привилегии:** Пользователь приложения должен иметь только минимально необходимые привилегии (`SELECT, INSERT, UPDATE, DELETE, EXECUTE` на конкретные БД). Никаких прав `SUPER` или `FILE` для приложений.

## Особенности и ограничения (Edge Cases)

1.  **`apt-key` deprecated:** На Debian 13 (Trixie) и Ubuntu 25.04+ `apt-key` удален. Всегда используйте размещение ключей в `/etc/apt/trusted.gpg.d/` или `/etc/apt/keyrings/`.
2.  **Новый GPG-ключ 2025:** Начиная с 2025 года, MariaDB использует ключ `mariadb-keyring-2025.gpg`. Старые ключи в `trusted.gpg.d` должны быть удалены вручную после обновления `mariadb_repo_setup`.
3.  **RHEL 10 / Rocky 10 / Alma 10:** Для этих дистрибутивов требуется `dirmgr` только при ручном импорте ключа через `apt-key adv`. `mariadb_repo_setup` использует `rpm --import` напрямую, `dirmgr` не требуется.
4.  **Debian 13 (Trixie) и Ubuntu 25.04+:** Используют Deb822-format для репозиториев (`mariadb.sources`). Старый формат `.list` можно запросить через флаг `--list`.
5.  **CentOS 7 / Ubuntu 20.04:** Поддержка прекращена в 2025 году. `mariadb_repo_setup` больше не обслуживает эти дистрибутивы. Используйте RHEL 8+ / Ubuntu 22.04 LTS.
6.  **Socket Activation:** При использовании socket activation параметр `bind-address` игнорируется. Проверяйте `ss -tlnp | grep 3306` — в выводе должен быть `systemd`, а не `mysqld`. Подробнее см. **[MariaDB под systemd](systemd.md#socket-activation)**.
7.  **`mariadb-secure-installation` и OS:** Скрипт не изменяет `my.cnf`, файрвол, права ОС или плагины аудита/шифрования. Эти слои hardening выполняются отдельно.
8.  **`unix_socket` и sudo:** При активном `unix_socket` всегда используйте `sudo mariadb` для локального root-доступа. Если требуется доступ без sudo — смените плагин на `ed25519` (см. **[Аутентификация](security/authentication.md)**).
9.  **SELinux/AppArmor:** После восстановления из бэкапа или изменения путей файлов могут потребоваться перезагрузка контекстов SELinux (`restorecon -Rv /var/lib/mysql`) или перезагрузка AppArmor.
10. **`mariadb-upgrade` и права:** Утилита требует прав `SUPER` или `ALTER USER` на системных таблицах. В Galera Cluster запускайте только на одном узле; остальные обновятся через SST.
11. **`innodb_log_archive` (13.0+):** Начиная с MariaDB 13.0, доступен `innodb_log_archive=ON` для PITR без зависимости от binlog. Это экспериментальная функция, не используйте в production без тестирования.

## Дополнительная информация

### См. также

- **[Безопасность MariaDB: обзор](security/index.md)** — многоуровневая модель hardening.
- **[Начальная закалка MariaDB](security/hardening.md)** — `mariadb-secure-installation` и OS-level hardening.
- **[Аутентификация и политика паролей](security/authentication.md)** — плагины аутентификации, `validate_password`, PAM.
- **[Конфигурация MariaDB](configuration.md)** — глубокая настройка `my.cnf`, иерархия загрузки.
- **[Клиентские утилиты](client_utilities.md)** — переименование утилит (`mariadb-*`), `--defaults-extra-file`.
- **[Обслуживание MariaDB](maintenance.md)** — `mariadb-check`, `mariadb-admin`, `mariadb-upgrade`, окна обслуживания.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup` и `mariadb-dump`.
- **[Отказоустойчивость MariaDB](high_availability.md)** — Galera Cluster, Orchestrator, MaxScale.
- **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — стратегия обновления кластеров без остановки.
- **[Обзор MariaDB](overview.md)** — архитектура, версии, сравнение с MySQL.

### Внешние ресурсы

- [MariaDB Package Repository Setup and Usage](https://mariadb.com/docs/server/server-management/install-and-upgrade-mariadb/mariadb-package-repository-setup-and-usage)
- [MariaDB 12.3 LTS Release Notes](https://mariadb.com/docs/release-notes/community-server/12.3/)
- [MariaDB Server System Variables](https://mariadb.com/docs/server/server-system-variables/)
- [MariaDB Pluggable Authentication Overview](https://mariadb.com/docs/server/reference/plugins/authentication-plugins/pluggable-authentication-overview)
