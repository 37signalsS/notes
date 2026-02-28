# Ansible: Создание пользовательских модулей

## Определения

**Пользовательские модули Ansible** — это Python-скрипты, расширяющие стандартную функциональность Ansible. Они позволяют инкапсулировать сложную логику, обеспечивать идемпотентность и автоматизировать специфические задачи, для которых нет встроенных модулей.

## Основные концепции

### Разница между модулями и плагинами

- **Модуль (Module):**
  - **Где исполняется:** На **удаленном хосте**, которым вы управляете.
  - **Назначение:** Выполняет конкретную задачу по управлению состоянием ресурса (например, установка пакета, создание пользователя).

- **Плагин (Plugin):**
  - **Где исполняется:** На **контрольном узле** (машине, где запущен `ansible-playbook`).
  - **Назначение:** Расширяет ядро Ansible (например, плагины для инвентаря, подключения, вывода).

### Процесс взаимодействия

1. Ansible на **контрольном узле** парсит плейбук.
2. **Action плагин** (если есть) подготавливает аргументы и передает их в виде JSON на удаленный хост.
3. **Модуль** исполняется на **удаленном хосте**, принимает JSON и выполняет работу.
4. Модуль возвращает результат своей работы обратно в виде JSON.
5. Action плагин получает JSON, интерпретирует его и выводит результат.

## Практические сценарии

### Пример: Создание модуля `clickhouse_user`

**Цель:** Создать модуль для декларативного управления пользователями в базе данных ClickHouse.

#### 1. Код модуля

Каждый модуль Ansible — это Python-скрипт со специальной структурой, включающей документацию (`DOCUMENTATION`), примеры (`EXAMPLES`) и возвращаемые значения (`RETURN`).

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
                module.fail_json(msg="Пароль является обязательным, когда state=present")
            
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

#### 2. Тестирование модуля

Тестирование является интеграционным и требует реального окружения.

1. **Подготовить среду:** Запустить Docker-контейнер с ClickHouse и `sshd`.
2. **Создать инвентарь:**

    ```ini
    # inventory.ini
    [clickhouse]
    ch_server ansible_host=172.17.0.2 ansible_user=root ansible_ssh_pass=password
    ```

3. **Создать плейбук для теста:**

    ```yaml
    # test_module.yml
    - name: Test ClickHouse Module
      hosts: clickhouse
      become: true

      tasks:
        # Сначала убедимся, что зависимость установлена на хосте
        - name: Install clickhouse-driver
          ansible.builtin.pip:
            name: clickhouse-driver
            state: present
        
        # Создание пользователя
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

        # Проверка идемпотентности (должно быть changed=false)
        - name: Create user 'testuser' again
          clickhouse_user:
            login_user: default
            login_password: ""
            user: testuser
            password: "test_password"
            state: present
          register: create_idempotent_result

        - name: Print create idempotent result
          ansible.builtin.debug:
            var: create_idempotent_result
            
        # Удаление пользователя
        - name: Delete user 'testuser'
          clickhouse_user:
            login_user: default
            login_password: ""
            user: testuser
            state: absent
          register: delete_result
          
        - name: Print delete result
          ansible.builtin.debug:
            var: delete_result
    ```

4. **Запустить плейбук:**

    ```bash
    ansible-playbook -i inventory.ini test_module.yml
    ```

## Дополнительная информация

### Размещение модулей

Пользовательские модули могут быть размещены в нескольких местах. Ansible автоматически ищет их в следующих каталогах (в порядке приоритета):

1. **В директории `library` рядом с плейбуком:**

    ```
    playbook.yml
    library/
        └── clickhouse_user.py
    ```

2. **В директории `library` внутри роли:**

    ```
    roles/
        └── my_role/
            └── library/
                └── my_module.py
    ```

3. **В системных директориях:** Пути, указанные в переменной окружения `ANSIBLE_LIBRARY` или в конфигурационном файле `ansible.cfg` (`library` = `/path/to/library`).

### Лучшие практики

- **Идемпотентность:** Модуль не должен вносить изменения, если система уже находится в желаемом состоянии.
- **Поддержка `check_mode`:** Модуль должен уметь предсказывать изменения без их реального выполнения.
- **Минимальные зависимости:** Старайтесь использовать стандартные библиотеки Python. Если сторонняя библиотека необходима, модуль должен проверять её наличие и выдавать понятную ошибку.
- **Четкая документация:** Секции `DOCUMENTATION`, `EXAMPLES` и `RETURN` обязательны. Они используются для генерации документации (`ansible-doc`) и помогают пользователям понять, как работает ваш модуль.
- **Безопасность:** Используйте `no_log=True` для чувствительных данных (пароли, ключи), чтобы они не попадали в логи.

## Дополнительная информация

- [Официальная документация по модулям](https://docs.ansible.com/ansible/latest/dev_guide/developing_modules_general.html): Полное руководство по разработке
- [Модули Ansible](Modules/ansible_modules_overview.md): Обзор встроенных модулей
- [Ansible-bender](ansible_buildah_image_building.md): Сборка контейнеров через Ansible
