# Установка PostgreSQL на Ubuntu (24.04 / 22.04)

## Определения

**PGDG (PostgreSQL Global Development Group) Repository** — официальный репозиторий сообщества PostgreSQL (`apt.postgresql.org`). Он предоставляет самые свежие мажорные и минорные версии СУБД, а также дополнительные расширения и утилиты, которые часто отсутствуют или устарели в стандартных репозиториях Ubuntu.

**GPG-ключ (GNU Privacy Guard)** — криптографический инструмент для проверки подлинности пакетов. Использование GPG гарантирует, что устанавливаемое ПО получено именно от разработчиков PostgreSQL и не было подменено.

**PostgreSQL Server vs Client:**
*   **Server (`postgresql-<version>`)**: Основной процесс СУБД, управляющий данными, памятью и соединениями.
*   **Client (`postgresql-client-<version>`)**: Набор утилит для взаимодействия с сервером (`psql`, `pg_dump`, `pg_restore`). Может быть установлен отдельно для удаленного управления.

**Локаль (Locale)** — набор параметров, определяющих языковые и региональные настройки (кодировка, правила сортировки, формат дат). Для корректной работы с кириллицей в PostgreSQL критически важна поддержка `ru_RU.UTF-8`.

## Базовые концепции

### Выбор источника установки
1.  **Стандартный репозиторий Ubuntu:** Стабильно, протестировано Canonical, но версии обычно отстают на 1-2 года. Подходит для простых систем с минимальными требованиями.
2.  **Репозиторий PGDG (Рекомендуется):** Позволяет использовать **PostgreSQL 18** (текущий стандарт 2026 года) и будущую версию 19. Обеспечивает доступ к новейшим функциям, таким как асинхронный ввод-вывод (AIO) и улучшенный механизм VACUUM.

### Архитектурные особенности при установке
PostgreSQL использует модель **«процесс на соединение»**. При установке создается основной управляющий процесс (Postmaster), который при каждом новом подключении порождает дочерний процесс. Это требует правильной настройки лимитов ОС (файл `/etc/security/limits.conf`) при высокой нагрузке.

По умолчанию данные хранятся в `/var/lib/postgresql/<version>/main`, а конфигурация — в `/etc/postgresql/<version>/main/`.

## Предварительные требования
*   Сервер под управлением Ubuntu 24.04 LTS (Noble) или 22.04 LTS (Jammy).
*   Пользователь с правами `sudo`.
*   Свободное дисковое пространство (минимум 1 ГБ для бинарных файлов и системных баз).
*   Настроенный брандмауэр. См. **[Настройка UFW](../../../Linux/Networking/Settings/tools/ufw.md)**.

## Практические сценарии

### Шаг 1: Добавление официального репозитория PGDG

Для установки **PostgreSQL 18** необходимо подключить официальный источник.

1.  Установите утилиты для работы с репозиториями:
    ```bash
    sudo apt update && sudo apt install -y curl gnupg2 lsb-release
    ```
2.  Добавьте GPG-ключ:
    ```bash
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg
    ```
3.  Создайте файл конфигурации репозитория:
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
    ```

### Шаг 2: Установка PostgreSQL 18

1.  Обновите индекс пакетов:
    ```bash
    sudo apt update
    ```
2.  Установите сервер, клиент и дополнительные расширения (`contrib`):
    ```bash
    sudo apt install -y postgresql-18 postgresql-contrib-18
    ```
3.  Запустите сервис и добавьте в автозагрузку:
    ```bash
    sudo systemctl enable --now postgresql
    ```

### Шаг 3: Валидация установки

Убедитесь, что СУБД работает корректно.

1.  **Проверка статуса сервиса:**
    ```bash
    sudo systemctl status postgresql
    # Ожидаемый вывод: Active: active (running)
    ```
2.  **Проверка готовности к подключениям:**
    ```bash
    pg_isready
    # Ожидаемый вывод: /var/run/postgresql:5432 - accepting connections
    ```
3.  **Проверка версии через psql:**
    ```bash
    psql --version
    # Ожидаемый вывод: psql (PostgreSQL) 18.x
    ```

### Шаг 4: Первоначальная настройка и локализация

1.  **Генерация локали:** Для работы с русским языком выполните:
    ```bash
    sudo locale-gen ru_RU.UTF-8
    sudo update-locale
    ```
2.  **Настройка пароля суперпользователя:** По умолчанию системный пользователь `postgres` не имеет пароля в БД. Установите его:
    ```bash
    sudo -u postgres psql -c "\password postgres"
    ```
3.  **Проверка кодировки:** Зайдите в консоль и проверьте настройки:
    ```sql
    SHOW server_encoding; -- Должно быть UTF8
    SHOW lc_ctype;       -- Должно быть ru_RU.UTF-8 (или en_US.UTF-8)
    ```

### Шаг 5: Базовая конфигурация сети и безопасности

По умолчанию PostgreSQL слушает только `localhost` (127.0.0.1).

1.  **Разрешение удаленных подключений:** Отредактируйте `postgresql.conf`:
    ```bash
    # Путь для PG 18: /etc/postgresql/18/main/postgresql.conf
    sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" /etc/postgresql/18/main/postgresql.conf
    ```
2.  **Настройка прав доступа:** Добавьте разрешение для вашей сети в `pg_hba.conf`:
    ```bash
    # Пример: разрешить доступ по паролю (scram-sha-256) для сети 192.168.1.0/24
    echo "host all all 192.168.1.0/24 scram-sha-256" | sudo tee -a /etc/postgresql/18/main/pg_hba.conf
    ```
3.  **Применение настроек:**
    ```bash
    sudo systemctl restart postgresql
    ```
4.  **Брандмауэр:** Откройте порт 5432:
    ```bash
    sudo ufw allow 5432/tcp
    ```

### Шаг 6: Тюнинг для мониторинга

Включите `pg_stat_statements` для анализа медленных запросов.

1.  Измените параметры загрузки библиотек:
    ```bash
    sudo -u postgres psql -c "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';"
    ```
2.  Перезапустите СУБД и создайте расширение:
    ```bash
    sudo systemctl restart postgresql
    sudo -u postgres psql -d postgres -c "CREATE EXTENSION pg_stat_statements;"
    ```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Peer authentication failed` | Попытка входа под пользователем, имя которого не совпадает с системным. | Используйте `sudo -u postgres psql` или измените `peer` на `scram-sha-256` в `pg_hba.conf`. |
| `Connection refused` (5432) | Сервис не запущен или `listen_addresses` не настроен. | Проверьте `systemctl status` и файл `postgresql.conf`. |
| `UTF-8` ошибки в логах | Отсутствие сгенерированной локали в ОС. | Выполните `sudo locale-gen ru_RU.UTF-8`. |
| Порт 5432 уже занят | Запущена другая версия PostgreSQL. | См. раздел "Пограничные случаи" ниже. |

## Пограничные случаи и ограничения

### Несколько версий на одном хосте
Ubuntu поддерживает параллельную установку версий (например, 16 и 18).
*   Каждая версия получает свой порт (5432, 5433 и т.д.).
*   Список установленных кластеров: `pg_lsclusters`.
*   Управление конкретным кластером: `pg_ctlcluster 18 main start`.

### Установка специфической версии
Если требуется версия 17 вместо 18:
```bash
sudo apt install postgresql-17 postgresql-client-17
```

## Дополнительная информация

### Пост-инсталяционный чек-лист
- [x] Проверен статус `systemctl status postgresql`.
- [x] Выполнена команда `pg_isready`.
- [x] Установлен пароль для роли `postgres`.
- [x] Настроены `listen_addresses` и `pg_hba.conf` (при необходимости).
- [x] Включено расширение `pg_stat_statements`.
- [x] Настроен ротационный лог в `postgresql.conf` (рекомендуется).

### Связанные документы
- **[Управление ролями и правами](./role_management.md)** — создание пользователей и БД.
- **[Работа через консоль (psql)](./console_basics.md)** — основы использования клиента.
- **[Оптимизация производительности](./performance_tuning.md)** — тюнинг параметров для PG 18.
- **[Безопасная установка СУБД](../../installation_security.md)** — SSL, шифрование и закалка.
