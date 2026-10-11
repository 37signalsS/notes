# Установка PostgreSQL на Ubuntu (26.04 / 24.04 / 22.04)

**Актуально для:** PostgreSQL 18 / Ubuntu 26.04 LTS (Resolute), 24.04 LTS (Noble), 22.04 LTS (Jammy)

## Определения

**PGDG (PostgreSQL Global Development Group) Repository** — официальный репозиторий сообщества PostgreSQL (`apt.postgresql.org`). Содержит все поддерживаемые мажорные версии (14–18), бета-версию 19 и расширения (PostGIS, языки PL, отладчики), которые отсутствуют или устарели в стандартных репозиториях Ubuntu. Версии пакетов PGDG выше, чем у Ubuntu (например, `18.6-1.pgdg24.04+1` против `18+290ubuntu1`), поэтому apt выбирает их автоматически.

**postgresql-common** — пакет инфраструктуры Debian/Ubuntu для PostgreSQL. Реализует модель «кластеров» и предоставляет утилиты `pg_ctlcluster`, `pg_lsclusters`, `pg_createcluster`, `pg_dropcluster`, а также скрипт подключения репозитория `apt.postgresql.org.sh`.

**Кластер (Debian/Ubuntu)** — именованный экземпляр СУБД, управляемый через `postgresql-common`. Каждый кластер привязан к паре «версия — имя» (по умолчанию `<version>-main`) и имеет собственные каталоги данных, конфигурации и лог-файл. PostgreSQL использует модель «процесс на соединение»: postmaster порождает дочерний процесс для каждого подключения — при высокой нагрузке настраивайте лимиты ОС (`/etc/security/limits.conf`).

**GPG-ключ (GNU Privacy Guard)** — криптографическая подпись пакетов PGDG. Fingerprint ключа репозитория: `B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8`. Проверка подписи гарантирует, что ПО получено от разработчиков PostgreSQL и не подменено.

**PostgreSQL Server vs Client:**
*   **Server (`postgresql-<version>`)**: основной процесс СУБД, управляющий данными, памятью и соединениями.
*   **Client (`postgresql-client-<version>`)**: утилиты взаимодействия с сервером (`psql`, `pg_dump`, `pg_restore`). Может быть установлен отдельно на административной машине.

**Локаль (Locale)** — языковые и региональные параметры (кодировка, правила сортировки, формат дат). Для работы с кириллицей критична `ru_RU.UTF-8`. `lc_collate` и `lc_ctype` фиксируются при создании кластера и не меняются без dump/restore.

## Базовые концепции

### Выбор источника установки

| Источник | Версия по умолчанию | Когда использовать |
| :--- | :--- | :--- |
| Репозиторий Ubuntu (`apt install postgresql`) | jammy → 14, noble → 16, resolute → 18 | Согласование с Canonical, стабильность, тестирование на LTS-версии |
| PGDG (рекомендуется) | любая поддерживаемая: 14–18 | Нужна конкретная или новейшая мажорная версия, расширения из PGDG, единый источник для разных релизов Ubuntu |

Ubuntu «замораживает» одну версию PostgreSQL на весь срок жизни релиза и обновляет только минорные версии. PGDG интегрируется с системным package manager и предоставляет обновления на весь срок поддержки мажорной версии.

### Архитектура пакетов Debian/Ubuntu

*   Конфигурация: `/etc/postgresql/<version>/<cluster>/` (`postgresql.conf`, `pg_hba.conf`, `pg_ident.conf`, `start.conf`).
*   Данные: `/var/lib/postgresql/<version>/<cluster>`.
*   Логи: `/var/log/postgresql/postgresql-<version>-<cluster>.log` (ротация — средствами `postgresql-common`/logrotate).
*   Systemd: `postgresql` — umbrella-сервис всех кластеров; `postgresql@<version>-<cluster>` (например, `postgresql@18-main`) — сервис конкретного кластера.
*   Автозагрузка кластера управляется файлом `/etc/postgresql/<version>/<cluster>/start.conf` (`auto`/`manual`/`disabled`), а не только `systemctl enable`.

## Предпосылки

*   Ubuntu 26.04 LTS (Resolute), 24.04 LTS (Noble) или 22.04 LTS (Jammy); архитектуры amd64, arm64 и ppc64el (последние две — только для LTS-релизов).
*   Пользователь с правами `sudo`; свободное место — минимум 1 ГБ под пакеты и системные БД (данные растут отдельно).
*   Настроенный брандмауэр. См. **[Настройка UFW](../../../Linux/Networking/Settings/tools/ufw.md)**.
*   Проверка релиза: `lsb_release -a` → `Release: 24.04`, `Codename: noble` (или `grep VERSION_CODENAME /etc/os-release`).

## Практические сценарии

### Шаг 1: Подключение репозитория PGDG

**Автоматический способ (рекомендуется):**
```bash
sudo apt update && sudo apt install -y postgresql-common ca-certificates
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
```
Скрипт импортирует ключ и создаёт конфигурацию источника автоматически.

**Ручной способ (формат DEB822):**

1. Импорт ключа:
    ```bash
    sudo install -d /usr/share/postgresql-common/pgdg
    sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
    ```
2. Создание источника (код релиза берётся из `/etc/os-release`):
    ```bash
    . /etc/os-release
    sudo tee /etc/apt/sources.list.d/pgdg.sources <<EOF
    Types: deb
    URIs: https://apt.postgresql.org/pub/repos/apt
    Suites: $VERSION_CODENAME-pgdg
    Architectures: $(dpkg --print-architecture)
    Components: main
    Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
    EOF
    ```
3. Проверка, что пакет будет взят из PGDG:
    ```bash
    sudo apt update
    apt-cache policy postgresql-18
    # → postgresql-18:
    # →   Installed: (none)
    # →   Candidate: 18.6-1.pgdg24.04+1   ← репозиторий noble-pgdg
    ```

### Шаг 2: Установка сервера

1. Установка сервера, клиента и contrib-модулей:
    ```bash
    sudo apt install -y postgresql-18 postgresql-client-18 postgresql-contrib-18
    ```
    `postgresql-contrib-18` — мета-пакет дополнительных модулей; отдельные расширения ставятся пакетами `postgresql-18-<модуль>` (например, `postgresql-18-pldebugger`). Локальная документация — `postgresql-doc-18`, заголовки для разработки — `libpq-dev` / `postgresql-server-dev-18`.
2. Сервис запускается автоматически при установке; автозагрузка:
    ```bash
    sudo systemctl enable --now postgresql
    ```
3. Установка другой версии (например, 17):
    ```bash
    sudo apt install -y postgresql-17 postgresql-client-17
    ```

### Шаг 3: Валидация установки

```bash
sudo systemctl status postgresql@18-main
# → Active: active (running) ...
pg_isready
# → /var/run/postgresql:5432 - accepting connections
pg_lsclusters
# → Ver Cluster Port Status  Owner    Data directory               Log file
# → 18  main    5432 online  postgres /var/lib/postgresql/18/main /var/log/postgresql/postgresql-18-main.log
psql --version
# → psql (PostgreSQL) 18.6
sudo -u postgres psql -Atc "SELECT version();"
# → PostgreSQL 18.6 (Ubuntu 18.6-1.pgdg24.04+1) on x86_64-pc-linux-gnu, compiled by gcc ...
```
Полный справочник по утилитам кластера — [Инструменты управления](./management_tools.md) (SSoT).

### Шаг 4: Локаль и первоначальная настройка

1. Генерация локали ОС (для кириллицы):
    ```bash
    sudo locale-gen ru_RU.UTF-8 && sudo update-locale
    ```
2. Локаль кластера задаётся при создании. Если при установке применилась системная локаль по умолчанию, пересоздайте кластер:
    ```bash
    sudo pg_dropcluster --stop 18 main
    sudo pg_createcluster 18 main --locale=ru_RU.UTF-8
    sudo pg_ctlcluster 18 main start
    ```
3. Пароль суперпользователя (системный пользователь `postgres` не имеет пароля в БД):
    ```bash
    sudo -u postgres psql -c "\password postgres"
    ```
4. Проверка кодировки:
    ```sql
    SHOW server_encoding; -- → UTF8
    SHOW lc_collate;      -- → ru_RU.UTF-8
    SHOW lc_ctype;        -- → ru_RU.UTF-8
    ```

### Шаг 5: Сеть и доступ

По умолчанию PostgreSQL слушает только `localhost` (127.0.0.1).

1. Удалённые подключения — `listen_addresses` (контекст `postmaster`, требуется restart):
    ```bash
    sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/18/main/postgresql.conf
    sudo pg_ctlcluster 18 main restart
    ```
    Лучшая практика: указывайте конкретный IP интерфейса вместо `*`.
2. Правила аутентификации — `pg_hba.conf` (применяется reload'ом, restart не нужен):
    ```bash
    echo "host all all 192.168.1.0/24 scram-sha-256" | sudo tee -a /etc/postgresql/18/main/pg_hba.conf
    sudo pg_ctlcluster 18 main reload
    ```
    Модели аутентификации и роли: [Управление ролями](./role_management.md); SSL и закалка: [Безопасная установка СУБД](../../installation_security.md).
3. Брандмауэр — открывайте порт только для нужных подсетей:
    ```bash
    sudo ufw allow from 192.168.1.0/24 to any port 5432 proto tcp
    ```

### Шаг 6: Мониторинг через pg_stat_statements

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';"
sudo pg_ctlcluster 18 main restart
sudo -u postgres psql -d postgres -c "CREATE EXTENSION pg_stat_statements;"
```
Важно: `ALTER SYSTEM` перезаписывает значение целиком — если `shared_preload_libraries` уже содержит библиотеки, допишите `pg_stat_statements` к ним через запятую. Теория и настройка мониторинга: [Наблюдаемость](./observability.md), [Тюнинг](./performance_tuning.md) (SSoT).

## Мониторинг

*   Логи кластера: `/var/log/postgresql/postgresql-18-main.log` и `journalctl -u postgresql@18-main -f`.
*   Состояние всех кластеров: `pg_lsclusters` (статус `online`/`down`).
*   Готовность к подключениям: `pg_isready -h 127.0.0.1 -p 5432`.
*   Метрики СУБД (`pg_stat_activity`, `pg_stat_database`): см. [Наблюдаемость](./observability.md) (SSoT).

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Peer authentication failed` | Логин не совпадает с системным пользователем | `sudo -u postgres psql` или смена `peer` на `scram-sha-256` в `pg_hba.conf` + `pg_ctlcluster 18 main reload` |
| `Connection refused` (5432) | Сервис не запущен или `listen_addresses` не настроен | `pg_lsclusters`; `pg_ctlcluster 18 main start`; проверка `postgresql.conf` |
| `E: Unable to locate package postgresql-18` | Не выполнен `apt update` или неверный код релиза в `pgdg.sources` | `sudo apt update`; проверьте, что `Suites:` соответствует `$VERSION_CODENAME-pgdg` |
| `W: GPG error ... NO_PUBKEY` | Ключ репозитория не импортирован | Повторите шаг 1; проверьте fingerprint `B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8` |
| Изменения `pg_hba.conf` не применяются | Файл сохранён, но не перечитан | `sudo pg_ctlcluster 18 main reload` |
| Ошибки локали / `UTF-8` в логах | Локаль не сгенерирована в ОС | `sudo locale-gen ru_RU.UTF-8` |
| Порт 5432 уже занят | Запущен другой кластер | `pg_lsclusters`; `pg_ctlcluster 18 main stop` или смена порта в конфигурации |
| В логе `pg_stat_statements already loaded` | Дубликат имени в `shared_preload_libraries` | Уберите повторяющееся имя библиотеки |

## Пограничные случаи и ограничения

### Несколько версий на одном хосте
Ubuntu/Debian позволяют параллельную установку (например, 16 и 18):
*   Каждая версия получает свой порт (5432, 5433 и т.д.).
*   Управление конкретным кластером: `pg_ctlcluster 18 main start|stop|restart|reload`.
*   Подключение к конкретной версии: `psql -p 5433`.
*   Миграция между мажорными версиями: `pg_upgradecluster` или dump/restore — см. [Миграция без простоя](./zero_downtime_migration.md).

### Устаревшие релизы Ubuntu
Ubuntu 20.04 (focal) достигла EOL, пакеты для неё перенесены на `apt-archive.postgresql.org`. Для salvaging старых установок в PGDG доступны версии PostgreSQL начиная с 8.2.

## Лучшие практикы

*   Устанавливайте ПО только из PGDG или официальных репозиториев Ubuntu; при ручной настройке проверяйте fingerprint ключа.
*   Для production выбирайте LTS-релиз Ubuntu и обновляйте минорные версии через `apt upgrade`, не меняя мажорную версию без плана.
*   Не редактируйте файлы в `/usr/share/postgresql/` (upstream-дефолты) — настройки живут в `/etc/postgresql/` или в `postgresql.auto.conf` через `ALTER SYSTEM`.
*   Ограничивайте `pg_hba.conf` конкретными подсетями, а не `0.0.0.0/0`; по умолчанию используйте `scram-sha-256`.
*   Один кластер — один порт; автозагрузку кластера управляйте через `start.conf`.

## Очистка и откат

```bash
# Удаление кластера вместе с данными:
sudo pg_dropcluster --stop 18 main
# Удаление пакетов (конфигурации удаляются, каталог данных остаётся):
sudo apt remove --purge postgresql-18 postgresql-client-18 postgresql-contrib-18
# Отключение репозитория PGDG:
sudo rm -f /etc/apt/sources.list.d/pgdg.sources
sudo rm -rf /usr/share/postgresql-common/pgdg
sudo apt update
```

## Дополнительная информация

### Пост-инсталяционный чек-лист
- [x] `pg_lsclusters` показывает кластер в статусе `online`.
- [x] `pg_isready` отвечает `accepting connections`.
- [x] Установлен пароль роли `postgres`.
- [x] Локаль кластера соответствует требованиям (`SHOW lc_collate`).
- [x] Настроены `listen_addresses` и `pg_hba.conf` (при необходимости).
- [x] Включён `pg_stat_statements` (при необходимости).
- [x] Брандмауэр ограничен подсетью приложений.

### Связанные документы
- [Установка на RHEL / Rocky / AlmaLinux](./installation_rhel.md) — PGDG-репозиторий для Red Hat family.
- [Управление ролями и правами](./role_management.md) — создание пользователей и БД.
- [Работа через консоль (psql)](./console_basics.md) — основы использования клиента.
- [Инструменты управления](./management_tools.md) — `pg_lsclusters`, `pg_ctlcluster` и другие утилиты.
- [Наблюдаемость](./observability.md) — метрики и `pg_stat_statements`.
- [Тюнинг производительности](./performance_tuning.md) — параметры конфигурации.
- [Миграция без простоя](./zero_downtime_migration.md) — `pg_upgrade` и логический dump/restore.
- [Безопасная установка СУБД](../../installation_security.md) — SSL, шифрование и закалка.
- [Официальная страница загрузки](https://www.postgresql.org/download/linux/ubuntu/) — пакеты и поддерживаемые релизы.
