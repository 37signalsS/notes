# Ansible — разработка собственных модулей

## Определения

**Пользовательский модуль Ansible (Custom Module)** — это автономный сценарий (обычно на Python), расширяющий стандартную функциональность Ansible. Модули позволяют инкапсулировать сложную логику, обеспечивать идемпотентность и автоматизировать специфические задачи, для которых не подходят встроенные инструменты.

## Основные концепции

### Модуль (Module) против Плагина (Plugin)

*   **Модуль (Module):**
    *   **Место исполнения:** выполняется на **удаленном узле (Managed Node)**.
    *   **Назначение:** управление состоянием ресурса (установка пакета, конфигурация БД).
*   **Плагин (Plugin):**
    *   **Место исполнения:** выполняется на **узле управления (Control Node)**.
    *   **Назначение:** расширение логики ядра Ansible (Inventory, Connection, Callback, Lookup).

### Современный стандарт: Коллекции

Начиная с версии 2.10, предпочтительным способом разработки и распространения модулей являются **Коллекции**.
*   **Путь размещения:** `plugins/modules/` внутри структуры коллекции.
*   **FQCN:** использование полного имени `namespace.collection.module_name` предотвращает конфликты.
*   **Общие библиотеки:** логика, общая для нескольких модулей, выносится в `plugins/module_utils/`.

### Поиск модулей Ansible

Ansible ищет модули в следующих местах (в порядке приоритета):
1.  Директория `library/` в корне текущего плейбука.
2.  Внутри роли: `roles/<role_name>/library/`.
3.  В установленных коллекциях.
4.  Пути из переменной `ANSIBLE_LIBRARY` или параметра `library` в `ansible.cfg`.

### Лучшие практики разработки

*   **Идемпотентность:** модуль должен проверять текущее состояние и вносить изменения только при необходимости.
*   **Поддержка `check_mode`:** обязательная реализация `supports_check_mode=True` для безопасного тестирования (dry run).
*   **Возвращаемые значения:** всегда возвращайте `changed` (boolean) и, при необходимости, детали изменений в JSON-формате.
*   **Документация:** наличие блоков `DOCUMENTATION`, `EXAMPLES` и `RETURN` внутри Python-файла обязательно для работы `ansible-doc`.
*   **Безопасность:** используйте параметр `no_log: true` в `argument_spec` для защиты паролей и токенов в логах.

## Практические сценарии

### Пример: Создание модуля `clickhouse_user`

Ниже представлен пример модуля для управления пользователями в ClickHouse с использованием современной структуры.

#### Код модуля (clickhouse_user.py)

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

# Попытка импорта внешних зависимостей
try:
    from clickhouse_driver import Client as CHClient
    HAS_CH_DRIVER = True
except ImportError:
    HAS_CH_DRIVER = False

DOCUMENTATION = r'''
---
module: clickhouse_user
short_description: Управляет пользователями в ClickHouse
version_added: "1.0.0"
description:
    - Создает, обновляет или удаляет пользователей в базе данных ClickHouse.
options:
    login_user:
        description: Пользователь для аутентификации в ClickHouse.
        required: true
        type: str
    login_password:
        description: Пароль для аутентификации.
        required: true
        type: str
        no_log: true
    user:
        description: Имя управляемого пользователя.
        required: true
        type: str
    password:
        description: Пароль для нового пользователя.
        required: false
        type: str
        no_log: true
    state:
        description: Желаемое состояние пользователя.
        choices: [ present, absent ]
        default: present
        type: str
author:
    - DevOps Team (@company)
'''

EXAMPLES = r'''
- name: Создать пользователя ClickHouse
  clickhouse_user:
    login_user: default
    login_password: "admin_password"
    user: readonly_user
    password: "secure_password"
    state: present
'''

RETURN = r'''
queries:
    description: Список выполненных SQL-запросов.
    type: list
    returned: always
    sample: ["CREATE USER readonly_user IDENTIFIED BY 'password'"]
'''

def main():
    # Определение спецификации аргументов
    argument_spec = {
        "login_user": {"type": "str", "required": True},
        "login_password": {"type": "str", "required": True, "no_log": True},
        "user": {"type": "str", "required": True},
        "password": {"type": "str", "no_log": True},
        "state": {"type": "str", "default": "present", "choices": ['present', 'absent']},
    }

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )

    # Проверка зависимостей
    if not HAS_CH_DRIVER:
        module.fail_json(msg="Библиотека 'clickhouse-driver' не найдена. Установите её через pip.")

    user = module.params['user']
    state = module.params['state']
    result = {'changed': False, 'queries': []}

    try:
        client = CHClient(
            host='localhost',
            user=module.params['login_user'],
            password=module.params['login_password']
        )
        # Проверка подключения
        client.execute('SELECT 1')
    except Exception as e:
        module.fail_json(msg=f"Ошибка подключения к ClickHouse: {str(e)}")

    # Идемпотентность: проверка существования
    user_exists = client.execute(
        "SELECT count() FROM system.users WHERE name = %(user)s",
        {'user': user}
    )[0][0] > 0

    # Обработка Check Mode
    if module.check_mode:
        if (state == 'present' and not user_exists) or (state == 'absent' and user_exists):
            result['changed'] = True
        module.exit_json(**result)

    # Основная логика
    if state == 'present' and not user_exists:
        password = module.params.get('password')
        if not password:
            module.fail_json(msg="Пароль обязателен при создании пользователя.")
        
        query = "CREATE USER %(user)s IDENTIFIED BY %(password)s"
        client.execute(query, {'user': user, 'password': password})
        result['changed'] = True
        result['queries'].append(f"CREATE USER {user} ...")

    elif state == 'absent' and user_exists:
        query = f"DROP USER {user}"
        client.execute(query)
        result['changed'] = True
        result['queries'].append(query)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Тестирование и отладка

Для профессиональной разработки рекомендуется использовать встроенную утилиту `ansible-test`, которая поставляется вместе с `ansible-core`.

1.  **Sanity-тесты (статический анализ):**
    Проверяют код на соответствие стандартам (PEP8, структура документации, корректность импортов).
    ```bash
    ansible-test sanity plugins/modules/clickhouse_user.py
    # → Running sanity test 'pep8'
    # → plugins/modules/clickhouse_user.py: ... (SUCCESS)
    ```

2.  **Локальное тестирование логики (Unit-тесты):**
    Запуск модульных тестов, расположенных в директории `tests/unit/`.
    ```bash
    ansible-test units --python 3.10 plugins/modules/clickhouse_user.py
    # → =======================================================================
    # → plugins/modules/clickhouse_user.py: 12 tests, 0 failures, 0 errors
    ```

3.  **Изолированное тестирование в OCI-контейнерах:**
    Позволяет запускать интеграционные (`integration`) или модульные (`units`) тесты в чистом окружении на базе различных ОС без засорения локальной машины.
    ```bash
    # Запуск тестов внутри контейнера Ubuntu
    ansible-test units --docker ubuntu2204 plugins/modules/clickhouse_user.py
    # → Provisioning ubuntu2204 docker container...
    # → ... tests passed
    ```

4.  **Отладка через `ansible-playbook`:**
    Создайте плейбук и запустите его с флагом `-vvv`. Ansible сохранит временный скомпилированный Python-файл модуля на удаленном хосте в директории `~/.ansible/tmp/`, что позволит выполнить его вручную и изучить стек вызовов при ошибке.

## Дополнительная информация

### Использование module_utils

Если ваша логика (например, клиент для API) используется в нескольких модулях, вынесите её в отдельный файл:
*   Путь: `plugins/module_utils/my_api_client.py`
*   Импорт в модуле: `from ansible_collections.my_namespace.my_collection.plugins.module_utils.my_api_client import MyClient`

### Смотрите также

*   [Обзор модулей Ansible](./Modules/ansible_modules_overview.md) — базовые принципы работы.
*   [Ансбиль — роли и коллекции](./ansible_roles.md) — структура и распространение контента.
*   [Официальный Module Development Guide](https://docs.ansible.com/ansible/latest/dev_guide/developing_modules_general.html) (EN).
