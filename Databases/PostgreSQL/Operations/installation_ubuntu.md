# Установка PostgreSQL на Ubuntu (24.04 / 22.04)

## Определения

**APT-репозиторий (Advanced Package Tool Repository)** — хранилище пакетов программного обеспечения. Использование официального репозитория PostgreSQL (`apt.postgresql.org`) позволяет получать самые свежие версии СУБД (например, PostgreSQL 17), которые отсутствуют в стандартных репозиториях Ubuntu.

**Кодировка (Encoding)** — способ представления символов. Стандартом для PostgreSQL является `UTF-8`. Неправильная настройка кодировки и локали при установке может привести к ошибкам сортировки и отображения кириллицы.

## Предварительные требования
*   Сервер под управлением Ubuntu 24.04 LTS (Noble Numbat) или 22.04 LTS (Jammy Jellyfish).
*   Пользователь с правами `sudo`.
*   Настроенный брандмауэр (рекомендуется). См. **[Настройка UFW](../../../Linux/Networking/Settings/tools/ufw.md)**.

## Практические сценарии

### Шаг 1: Добавление официального репозитория PostgreSQL

Для получения актуальной мажорной версии (на данный момент — **PostgreSQL 17**) рекомендуется использовать официальный репозиторий.

1.  Установите необходимые вспомогательные пакеты:
    ```bash
    sudo apt update && sudo apt install -y curl gnupg2 lsb-release
    ```
2.  Добавьте GPG-ключ репозитория:
    ```bash
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg
    ```
3.  Добавьте сам репозиторий в список источников:
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
    ```

### Шаг 2: Установка PostgreSQL

1.  Обновите индекс пакетов после добавления нового репозитория:
    ```bash
    sudo apt update
    ```
2.  Установите PostgreSQL (версия 17 по умолчанию из официального репозитория) и дополнительные компоненты:
    ```bash
    sudo apt install -y postgresql-17 postgresql-contrib-17
    ```
3.  Убедитесь, что сервис запущен и включен в автозагрузку:
    ```bash
    sudo systemctl enable --now postgresql
    sudo systemctl status postgresql
    ```

### Шаг 3: Настройка локали и кодировки (Proactive)

Для корректной работы с русским языком убедитесь, что в системе сгенерированы нужные локали.

1.  Проверьте текущие локали:
    ```bash
    locale -a | grep -iE 'ru_RU|en_US'
    ```
2.  Если нужной локали нет, сгенерируйте её:
    ```bash
    sudo locale-gen ru_RU.UTF-8
    sudo update-locale
    ```

### Шаг 4: Первоначальная настройка и мониторинг

После установки рекомендуется включить расширение для анализа производительности запросов.

1.  Добавьте `pg_stat_statements` в файл конфигурации:
    ```bash
    sudo -u postgres psql -c "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';"
    ```
2.  Перезапустите сервис для применения настроек:
    ```bash
    sudo systemctl restart postgresql
    ```
3.  Включите расширение внутри базы данных:
    ```sql
    -- В консоли psql
    CREATE EXTENSION pg_stat_statements;
    ```
    Подробнее об оптимизации: **[Оптимизация производительности PostgreSQL](./performance_tuning.md)**.

### Шаг 5: Безопасность (Hardening)

1.  **Настройка доступа (UFW):** По умолчанию PostgreSQL слушает только `localhost`. Если требуется удаленный доступ, разрешите его только для конкретных IP:
    ```bash
    sudo ufw allow from 192.168.1.100 to any port 5432 proto tcp
    ```
2.  **Пароль суперпользователя:** Установите надежный пароль для системного пользователя `postgres` внутри БД:
    ```bash
    sudo -u postgres psql -c "\password postgres"
    ```
3.  **Закалка системы:** Изучите полный чек-лист безопасности: **[Безопасная установка СУБД](../../installation_security.md)**.

### Шаг 6: Удаление PostgreSQL (при необходимости)

Если требуется полностью удалить конкретную версию (например, 17) и очистить данные:

1.  Остановите сервис и удалите пакеты:
    ```bash
    sudo systemctl stop postgresql
    sudo apt-get --purge remove postgresql-17 postgresql-client-17 postgresql-common
    ```
2.  Удалите остаточные файлы и данные (ВНИМАНИЕ: это безвозвратно удалит все базы данных):
    ```bash
    sudo rm -rf /etc/postgresql/
    sudo rm -rf /var/lib/postgresql/
    sudo userdel -r postgres
    ```

## Дополнительная информация

### Пост-инсталяционный чек-лист
- [ ] Проверен статус сервиса (`systemctl status`).
- [ ] Установлен пароль для роли `postgres`.
- [ ] Включен `pg_stat_statements`.
- [ ] Настроен брандмауэр (`ufw`).
- [ ] Проверена кодировка (`SHOW server_encoding;`).

### Связанные документы
- **[Управление ролями и правами](./role_management.md)** — создание пользователей и БД.
- **[Оптимизация производительности](./performance_tuning.md)** — тюнинг `postgresql.conf`.
- **[Работа через консоль (psql)](./console_basics.md)** — основы использования клиента.
- **[Безопасная установка и закалка СУБД](../../installation_security.md)** — расширенные настройки безопасности.
