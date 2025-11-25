# Ansible Galaxy

Ansible Galaxy - это официальный репозиторий для поиска, повторного использования и обмена контентом Ansible, таким как роли и коллекции.

## Роли и Коллекции

-   **Роль**: Набор задач и связанных с ними файлов (переменные, обработчики, шаблоны) для автоматизации настройки конкретного приложения или компонента системы. Например, роль для установки и базовой настройки PostgreSQL.
-   **Коллекция**: Более крупная структура, которая может включать в себя несколько ролей, плагинов, модулей и документации. Коллекции обычно объединяют контент для работы с целой экосистемой, например, все необходимое для управления PostgreSQL (установка, создание баз данных, управление пользователями).

## Использование `ansible-galaxy`

`ansible-galaxy` — это утилита командной строки для взаимодействия с Ansible Galaxy и управления ролями и коллекциями.

### Установка ролей и коллекций

-   Установить роль:
    ```bash
    ansible-galaxy install <namespace>.<role_name>
    ```

-   Установить коллекцию:
    ```bash
    ansible-galaxy collection install <namespace>.<collection_name>
    ```

-   Обновить коллекцию:
    ```bash
    ansible-galaxy collection install <namespace>.<collection_name> --upgrade
    ```

### Просмотр установленных компонентов

-   Показать список установленных ролей:
    ```bash
    ansible-galaxy list
    # Старый вариант: ansible-galaxy role list
    ```

-   Показать список установленных коллекций:
    ```bash
    ansible-galaxy collection list
    ```

### Инициализация новой роли

Вы можете создать структуру каталогов для новой роли с помощью команды `init`:

```bash
ansible-galaxy role init my_new_role
```

Это создаст директорию `my_new_role` со стандартной структурой подкаталогов (`tasks`, `handlers`, `defaults`, `vars`, `meta`, `templates`, `files`).

## Файл зависимостей `requirements.yml`

Для автоматической установки нескольких ролей и коллекций используется файл `requirements.yml`. Это позволяет управлять зависимостями проекта в одном месте.

### Пример `requirements.yml`

```yaml
# roles/requirements.yml
roles:
  # Установка роли из Ansible Galaxy
  - src: geerlingguy.postgresql

  # Установка роли из репозитория Git
  - name: green.mongodb
    src: https://github.com/UnderGreen/ansible-role-mongodb

# collections/requirements.yml
collections:
  - name: community.postgresql
    version: 1.4.0
```

### Установка из файла

-   Установить роли:
    ```bash
    ansible-galaxy install -r roles/requirements.yml
    ```

-   Установить коллекции:
    ```bash
    ansible-galaxy collection install -r collections/requirements.yml
    ```

### Пути установки

По умолчанию, `ansible-galaxy` устанавливает контент в домашнюю директорию пользователя (`~/.ansible/`). Пути установки можно настроить в `ansible.cfg`.
