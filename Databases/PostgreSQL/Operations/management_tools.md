# Инструменты управления PostgreSQL

## pgAdmin 4
pgAdmin — самое популярное графическое средство администрирования PostgreSQL.

### Установка
*   **Windows / macOS:** Скачайте инсталлятор с [официального сайта pgAdmin](https://www.pgadmin.org/download/).
*   **Ubuntu/Debian:**
    ```bash
    curl -fsS https://www.pgadmin.org/static/packages_pgadmin_org.pub | sudo gpg --dearmor -o /usr/share/keyrings/packages-pgadmin-org.gpg
    sudo sh -c 'echo "deb [signed-by=/usr/share/keyrings/packages-pgadmin-org.gpg] https://ftp.postgresql.org/pub/pgadmin/pgadmin4/apt/$(lsb_release -cs) pgadmin4 main" > /etc/apt/sources.list.d/pgadmin4.list && apt update'
    sudo apt install pgadmin4
    ```

### Управление ролями в pgAdmin
1.  Подключитесь к серверу.
2.  В дереве объектов раскройте раздел **Login/Group Roles**.
3.  Нажмите правой кнопкой → **Create** → **Login/Group Role**.
4.  Вкладки настройки:
    *   **General:** Имя роли (пользователя) и комментарий.
    *   **Definition:** Пароль и срок его действия.
    *   **Privileges:** Права на вход (`Login?`), создание БД, суперпользователь и др.
    *   **Membership:** Добавление пользователя в группы (например, `pg_monitor` или созданные вами группы).
    *   **SQL:** Предварительный просмотр генерируемых SQL-команд.

## phpPgAdmin
Легковесный веб-интерфейс, доступный в репозиториях Ubuntu.

### Установка и настройка
1.  Установите пакет:
    ```bash
    sudo apt install phppgadmin
    ```
2.  Настройка доступа в Apache (`/etc/apache2/conf-available/phppgadmin.conf`):
    Закомментируйте `Require local` и добавьте `Allow From all` для внешнего доступа.
3.  Перезагрузите веб-сервер:
    ```bash
    sudo systemctl restart apache2
    ```

## Другие инструменты
*   **DBeaver**: Универсальный клиент для работы с множеством СУБД. Поддерживает визуальное управление пользователями.
*   **DataGrip**: Профессиональная IDE от JetBrains для работы с SQL.

### См. также
*   [Управление ролями и правами](./role_management.md)
*   [Установка PostgreSQL на Ubuntu](./installation_ubuntu.md)
