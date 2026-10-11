# Установка PostgreSQL на RHEL / Rocky Linux / AlmaLinux (PGDG)

**Актуально для:** RHEL / Rocky Linux / AlmaLinux 8–10, PGDG (PostgreSQL Global Development Group) repository, PostgreSQL 16–18

## Определения

*   **PGDG** — официальный репозиторий пакетов PostgreSQL для Red Hat family (RHEL, Rocky Linux, AlmaLinux, Fedora): все поддерживаемые мажорные версии, обновления на протяжении всего жизненного цикла.
*   **Module (dnf module)** — механизм RHEL 8/9 для выбора версии из дистрибутивного репозитория; для установки PGDG-версий модуль `postgresql` нужно отключить.
*   **Versioned packages** — пакеты с номером мажорной версии: `postgresql18-server`, `postgresql18-contrib`; сервис `postgresql-18`; initdb через `/usr/pgsql-18/bin/postgresql-18-setup initdb`.
*   **`postgresql-setup`** — скрипт инициализации кластера (`--initdb`) и управления сервисом в Red Hat family.
*   **Peer authentication** — дефолтная локальная аутентификация: ОС-пользователь `postgres` = роль `postgres` (`sudo -u postgres psql`).

## Базовые концепции

### Почему PGDG, а не дистрибутивный репозиторий

Каждая платформа «снапшотит» одну версию PostgreSQL на весь срок жизни платформы:

| Платформа | Встроенная версия |
| :--- | :--- |
| RHEL / Rocky / AlmaLinux 10 | 16 |
| RHEL / Rocky / AlmaLinux 9 | 16, 15, 13 (через modules) |
| RHEL / Rocky / AlmaLinux 8 | 15, 13, 12, 10, 9.6 (через modules) |
| Fedora 43/44 | 18 |

PGDG поддерживает последние два минорных релиза RHEL и производных и предоставляет **все** поддерживаемые мажорные версии одновременно — критично для production, где версия выбирается по поддержке и фичам, а не по возрасту ОС.

### Структура пакетов PGDG

| Пакет | Содержимое |
| :--- | :--- |
| `postgresql18-client` | Библиотеки и клиентские бинарники (`psql`, `pg_dump`) |
| `postgresql18-server` | Сервер (`postgres`, `pg_upgrade`, `pg_basebackup`) |
| `postgresql18-contrib` | Дополнительные модули (`pgcrypto`, `pg_trgm`, `amcheck` и др.) |
| `postgresql18-devel` | Заголовки и библиотеки для C-разработки |

Пути: `PGDATA` — `/var/lib/pgsql/18/data/`, конфиги — `/var/lib/pgsql/18/data/` (или `/etc/pgsql/18/` для включаемых файлов), логи — `journalctl -u postgresql-18` (или `/var/log/postgresql/` при настройке).

## Предпосылки

| Требование | Значение |
| :--- | :--- |
| Дистрибутив | RHEL / Rocky Linux / AlmaLinux 8, 9, 10
| Архитектура | x86_64, aarch64 (ARM); i386 не поддерживается PGDG
| Права пользователя | `sudo` или root для `dnf install` и `systemctl`
| SELinux | Включён (Enforcing или Permissive); контекст `postgresql_db_t` для PGDATA
| Брандмауэр (firewalld) | Открытый порт 5432 (или выбранный) для нужных subnet
| Минимальные ресурсы | 2 CPU, 4 ГБ RAM, 20 ГБ свободного диска под PGDATA
| Время | NTP синхронизирован (`timedatectl status` → `synchronized: yes`)
| Репозитории | PGDG repo (добавляется в процессе установки)
| Сеть | DNS разрешает `download.postgresql.org` и `yum.postgresql.org`
| Совместимость | Отключить системный модуль `postgresql`: `sudo dnf -qy module disable postgresql`

Перед установкой убедиться, что на хосте нет уже запущенного PostgreSQL (иначе конфликт порта 5432):

```bash
sudo systemctl status postgresql.service 2>/dev/null || true
ss -tlnp | grep 5432
```

## Практические сценарии

### Сценарий: Установка PostgreSQL 18 на Rocky Linux 9

```bash
# 1. Подключить PGDG-репозиторий
sudo dnf install -y \
  https://download.postgresql.org/pub/repos/yum/reporpms/EL-$(rpm -E %{rhel})-x86_64/pgdg-redhat-repo-latest.noarch.rpm

# 2. Отключить встроенный модуль (иначе конфликт пакетов)
sudo dnf -qy module disable postgresql

# 3. Установить сервер
sudo dnf install -y postgresql18-server postgresql18-contrib

# 4. Инициализировать кластер
sudo /usr/pgsql-18/bin/postgresql-18-setup initdb
# → Initializing database ... OK

# 5. Включить и запустить сервис
sudo systemctl enable --now postgresql-18
sudo systemctl status postgresql-18
# → active (running)
```

URL репозитория генерируется на [странице загрузки](https://www.postgresql.org/download/linux/redhat/) под конкретную платформу — при нестандартной минорной версии RHEL скопируйте команду оттуда.

### Сценарий: Первичная настройка

```bash
# Локальное подключение (peer auth)
sudo -u postgres psql
# → psql (18.x)

# Пароль суперпользователя и доступ по TCP
sudo -u postgres psql -c "ALTER USER postgres PASSWORD '***';"

# /var/lib/pgsql/18/data/postgresql.conf
listen_addresses = '*'          # или конкретный IP
port = 5432

# /var/lib/pgsql/18/data/pg_hba.conf — SCRAM-SHA-256 вместо trust/peer для TCP
host    all             all             10.0.0.0/24         scram-sha-256

sudo systemctl reload postgresql-18
```

MD5-аутентификация объявлена deprecated в PG 18 — используйте `scram-sha-256`.

### Сценарий: Обновление minor-версии

```bash
sudo dnf update postgresql18-server
sudo systemctl restart postgresql-18
# → мажорная версия не меняется, PGDATA не затрагивается
```

### Сценарий: Мажорное обновление (17 → 18)

In-place через `pg_upgrade` — полная процедура в [Обновлении между мажорными версиями](./pg_upgrade.md):

```bash
sudo dnf install -y postgresql18-server postgresql18-contrib
sudo systemctl stop postgresql-17
sudo /usr/pgsql-18/bin/initdb -D /var/lib/pgsql/18/data --data-checksums
sudo /usr/pgsql-18/bin/pg_upgrade \
  --old-bindir=/usr/pgsql-17/bin --new-bindir=/usr/pgsql-18/bin \
  --old-datadir=/var/lib/pgsql/17/data --new-datadir=/var/lib/pgsql/18/data \
  --clone --jobs=8
```

Альтернатива без простоя — логическая репликация на новый кластер ([Миграция без простоя](./zero_downtime_migration.md)).

### Сценарий: Установка расширений

```bash
# contrib-модули
sudo dnf install -y postgresql18-contrib
sudo -u postgres psql -d mydb -c "CREATE EXTENSION pgcrypto;"

# Расширения из PGDG (pg_stat_statements входит в server; pg_partman, pg_repack — отдельные пакеты)
sudo dnf install -y pgdg18-pg_partman pgdg18-pg_repack
```

Trusted-расширения (`pgcrypto`, `pg_trgm`, `citext` и др.) ставит любой пользователь с `CREATE`; остальные (`pg_stat_statements`, `amcheck`, `pg_repack`) — суперпользователь.

### Сценарий: Удаление

```bash
sudo systemctl stop postgresql-18
sudo dnf remove -y postgresql18-server postgresql18-contrib
sudo rm -rf /var/lib/pgsql/18
# PGDG-репозиторий: sudo dnf remove -y pgdg-redhat-repo
```

## Валидация и проверка

### Проверка статуса сервиса

```bash
sudo systemctl status postgresql-18
# → active (running)

sudo systemctl is-enabled postgresql-18
# → enabled
```

### Проверка подключения и версии

```bash
sudo -u postgres psql -c "SELECT version();"
# → PostgreSQL 18.x on x86_64-pc-linux-gnu, compiled by ...

sudo -u postgres psql -c "SHOW data_directory;"
# → /var/lib/pgsql/18/data

sudo -u postgres psql -c "SHOW listen_addresses;"
# → *
```

### Проверка аутентификации

```bash
# Локальное подключение (peer auth) — без пароля
sudo -u postgres psql -c "SELECT current_user;"
# → postgres

# TCP-подключение с проверкой метода аутентификации
# с другого хоста из 10.0.0.0/24:
psql -h <host_ip> -U postgres -c "SELECT 1;"
# → 1 (требует ввод пароля — SCRAM-SHA-256)
```

### Проверка контекстов SELinux

```bash
ls -Z /var/lib/pgsql/18/data
# → system_u:object_r:postgresql_db_t:s0 ... data/
```

Если контекст неверный:

```bash
sudo restorecon -R -v /var/lib/pgsql/18/data
```

### Автоматизированная проверка установки

```bash
# Полный набор проверок в один вызов
sudo -u postgres pg_isready -h localhost -p 5432
# → /var/run/postgresql:5432 - accepting connections
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Конфликт пакетов при установке | Включён модуль `postgresql` | `sudo dnf -qy module disable postgresql` |
| `Address already in use` на 5432 | Другой кластер/сервис слушает порт | `ss -tlnp \| grep 5432`; остановить конфликтующий сервис или сменить `port` |
| `FATAL: role "root" does not exist` | Запуск `psql` без `-u postgres` | `sudo -u postgres psql` |
| `permission denied` на `PGDATA` | SELinux или права | `ls -Z /var/lib/pgsql/18/data`; контекст `postgresql_db_t`; не отключать SELinux — настроить контекст |
| `pg_upgrade: checksums mismatch` | Разный `--data-checksums` | Инициализировать оба кластера с `--data-checksums` |
| Сервис не стартует после `dnf update` | Не перезапущен после обновления бинарников | `sudo systemctl restart postgresql-18` |

## Лучшие практики

1.  **Всегда PGDG** для production — дистрибутивная версия фиксирована на всю жизнь платформы.
2.  **Versioned пакеты** — `postgresql18-server`, а не `postgresql-server`: несколько мажорных версий могут сосуществовать на одном хосте.
3.  **`--data-checksums` при initdb** — защита от битых страниц (в PG 18 дефолт; в 17 — указать явно).
4.  **SCRAM-SHA-256** для TCP-подключений; MD5 deprecated в PG 18.
5.  **`systemctl enable`** — автозапуск не включается автоматически (политика Red Hat family).
6.  **SELinux не отключать** — настраивать контексты (`postgresql_db_t`).
7.  **Мажорные апгрейды — по процедуре** `pg_upgrade` с тестом на клоне.
8.  **Очистка перед удалением**: перед `dnf remove` сделать backup PGDATA, если данные нужны; очистить firewall правила `postgresql-18` и SELinux контексты.

## Дополнительная информация

*   [Установка на Ubuntu](./installation_ubuntu.md) — Debian/Ubuntu-аналог
*   [Обновление между мажорными версиями](./pg_upgrade.md) — процедура `pg_upgrade`
*   [PostgreSQL в Docker](./docker_deployment.md) — контейнерный вариант
*   [Роли и базы данных](./role_management.md) — первичная настройка прав
*   [Безопасность и шифрование](../Concepts/security_and_encryption.md) — `pg_hba.conf`, TLS
*   [Официальная страница загрузки: Linux (Red Hat family)](https://www.postgresql.org/download/linux/redhat/)
*   [Официальная документация PGDG](https://wiki.postgresql.org/wiki/YUM_Installation)
