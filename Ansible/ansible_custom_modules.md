# Разработка собственных модулей Ansible

## Определения

**Пользовательский модуль Ansible** — Python-скрипт, расширяющий стандартную функциональность Ansible. Позволяет инкапсулировать сложную логику, обеспечивать идемпотентность и автоматизировать специфические задачи без использования встроенных модулей.

## Основные концепции

### Модули против плагинов

**Модуль (Module):**

- **Место исполнения:** выполняется на **удаленном хосте**.
- **Назначение:** управление состоянием ресурса (установка пакета, создание пользователя).

**Плагин (Plugin):**

- **Место исполнения:** выполняется на **контрольном узле**.
- **Назначение:** расширение ядра Ansible (плагины инвентаря, подключения, вывода).

### Процесс взаимодействия

1. Ansible на контрольном узле парсит плейбук.
2. Action-плагин подготавливает аргументы в формате JSON (JavaScript Object Notation) и передает их на удаленный хост.
3. Модуль исполняется на удаленном хосте, выполняя поставленную задачу.
4. Модуль возвращает результат в формате JSON.
5. Action-плагин интерпретирует результат и выводит его пользователю.

### Размещение модулей

Ansible ищет модули в следующих местах:

- Директория `library/` рядом с плейбуком.
- Внутри роли: `roles/<role_name>/library/`.
- В путях, указанных в переменной окружения `ANSIBLE_LIBRARY` или в конфигурационном файле `ansible.cfg`.

### Лучшие практики разработки

- **Идемпотентность:** модуль не должен вносить изменения, если система уже находится в целевом состоянии.
- **Поддержка `check_mode`:** возможность запуска модуля без внесения реальных изменений для проверки (dry run).
- **Минимальные зависимости:** старайтесь использовать стандартную библиотеку Python или широко распространенные пакеты.
- **Документация:** наличие обязательных секций `DOCUMENTATION`, `EXAMPLES` и `RETURN`.
- **Безопасность:** использование `no_log: true` для параметров, содержащих чувствительные данные (пароли, токены).

## Практические сценарии

### Пример: Создание модуля `clickhouse_user`

**Цель:** создать модуль для декларативного управления пользователями в базе данных ClickHouse.

#### Код модуля

Каждый модуль Ansible представляет собой Python-скрипт со специальной структурой.

```python
#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.module_utils.basic import AnsibleModule

try:
    from clickhouse_driver import Client as CHClient
except ImportError:
    CHClient = None

DOCUMENTATION = r'''
---
module: clickhouse_user
short_description: Управляет пользователями в ClickHouse.
version_added: "1.0.0"
description:
    - Создает, обновляет или удаляет пользователей в базе данных ClickHouse.
options:
    login_user:
        description: Пользователь для аутентификации в ClickHouse.
        required: true
        type: str
    login_password:
        description: Пароль для пользователя, используемого для аутентификации.
        required: true
        type: str
        no_log: true
    user:
        description: Имя управляемого пользователя.
        required: true
        type: str
    password:
        description: Пароль для управляемого пользователя.
        required: false
        type: str
        no_log: true
    state:
        description: Желаемое состояние пользователя.
        choices: [ present, absent ]
        default: present
        type: str
author:
    - Имя Автора (@github_nickname)
'''

EXAMPLES = r'''
# Создание пользователя
- name: Создать пользователя 'new_user'
  clickhouse_user:
    login_user: default
    login_password: ""
    user: new_user
    password: "secure_password"
    state: present

# Удаление пользователя
- name: Удалить пользователя 'new_user'
  clickhouse_user:
    login_user: default
    login_password: ""
    user: new_user
    state: absent
'''

RETURN = r'''
queries:
    description: Список выполненных изменяющих запросов.
    type: list
    returned: always
    sample: ['CREATE USER new_user IDENTIFIED BY password']
'''

def main():
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

    if CHClient is None:
        module.fail_json(msg="Требуется Python-библиотека 'clickhouse-driver'. Пожалуйста, установите ее с помощью 'pip install clickhouse-driver'.")

    user_to_manage = module.params['user']
    state = module.params['state']
    
    result = {'changed': False, 'queries': []}

    try:
        client = CHClient(
            host='localhost', 
            user=module.params['login_user'], 
            password=module.params['login_password']
        )
        # Проверка доступности сервера
        client.execute('SELECT 1')
    except Exception as e:
        module.fail_json(msg=f"Не удалось подключиться к ClickHouse: {e}")

    # Проверка существования пользователя (идемпотентность)
    user_exists = client.execute(
        "SELECT count() FROM system.users WHERE name = %(user)s",
        {'user': user_to_manage}
    )[0][0] > 0

    if module.check_mode:
        if state == 'present' and not user_exists:
            result['changed'] = True
        elif state == 'absent' and user_exists:
            result['changed'] = True
        module.exit_json(**result)

    # Применение изменений
    if state == 'present':
        if not user_exists:
            password = module.params.get('password')
            if not password:
                module.fail_json(msg="Пароль обязателен при state=present")

            query = "CREATE USER %(user)s IDENTIFIED BY %(password)s"
            params = {'user': user_to_manage, 'password': password}
            client.execute(query, params)

            result['changed'] = True
            result['queries'].append(query % params)

    elif state == 'absent':
        if user_exists:
            query = "DROP USER %(user)s"
            params = {'user': user_to_manage}
            client.execute(query, params)

            result['changed'] = True
            result['queries'].append(query % params)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

#### Тестирование модуля

Тестирование является интеграционным и требует развернутого окружения (например, контейнера с ClickHouse).

1. **Создать инвентарь:**

    ```ini
    # inventory.ini
    [clickhouse]
    ch_server ansible_host=172.17.0.2 ansible_user=root ansible_ssh_pass=password
    ```

2. **Создать плейбук для теста:**

    ```yaml
    # test_module.yml
    - name: Test ClickHouse Module
      hosts: clickhouse
      become: true

      tasks:
        - name: Install clickhouse-driver
          ansible.builtin.pip:
            name: clickhouse-driver
            state: present
        
        - name: Create user 'testuser'
          clickhouse_user:
            login_user: default
            login_password: ""
            user: testuser
            password: "test_password"
            state: present
          register: create_result

        - name: Print create result
          ansible.builtin.debug:
            var: create_result
    ```

3. **Запустить плейбук:**

    ```bash
    ansible-playbook -i inventory.ini test_module.yml
    # → PLAY [Test ClickHouse Module] ... ok=2 changed=1 unreachable=0 failed=0
    ```

## Дополнительная информация

- [Официальная документация по разработке модулей](https://docs.ansible.com/ansible/latest/dev_guide/developing_modules_general.html)
- [Обзор модулей Ansible](./Modules/ansible_modules_overview.md)
- [Сборка образов с Buildah](./ansible_buildah_image_building.md)
