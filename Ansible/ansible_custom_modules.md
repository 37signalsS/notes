# Ansible: Создание пользовательских модулей на Python

## Определения

Пользовательские модули Ansible — это Python-скрипты, которые расширяют функциональность Ansible, позволяя автоматизировать специфические задачи, для которых нет встроенных модулей. Они позволяют инкапсулировать сложную логику, обеспечивать идемпотентность и предоставлять декларативный интерфейс для управления ресурсами.

## 1. Теория: Модули vs. Плагины

*   **Модуль (Module):**
    *   **Где исполняется:** На **удаленном хосте**, которым вы управляете.
    *   **Назначение:** Выполняет конкретную задачу по управлению состоянием ресурса (например, установка пакета, создание пользователя, управление службой). Вся основная работа в `tasks` плейбука выполняется модулями.

*   **Плагин (Plugin):**
    *   **Где исполняется:** На **контрольном узле** (машине, где запущен `ansible-playbook`).
    *   **Назначение:** Расширяет ядро Ansible. Примеры:
        *   **Action плагины:** Логика, которая выполняется *перед* вызовом модуля на удаленном хосте.
        *   **Connection плагины:** Определяют, как подключаться к хостам (ssh, winrm, docker).
        *   **Inventory плагины:** Динамически формируют список хостов.
        *   **Callback плагины:** Влияют на вывод Ansible в консоль.

**Процесс взаимодействия:**
1.  Ansible на **контрольном узле** парсит плейбук.
2.  **Action плагин** подготавливает аргументы и передает их в виде **JSON** на удаленный хост.
3.  **Модуль** исполняется на **удаленном хосте**, принимает JSON, выполняет работу.
4.  Модуль возвращает результат своей работы обратно в виде **JSON**.
5.  Action плагин получает JSON, интерпретирует его и выводит результат в консоль.

---

## 3. Практика: Создание модуля `clickhouse_user`

**Цель:** Создать модуль, который может создавать и удалять пользователей в базе данных ClickHouse.

### Шаг 1: Настройка окружения для разработки

1.  **Клонировать репозиторий Ansible:**
    ```bash
    git clone https://github.com/ansible/ansible.git
    cd ansible
    ```

2.  **Создать и активировать виртуальное окружение:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Установить зависимости Ansible:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Настроить среду для разработки:**
    Запустите специальный скрипт, который сделает Ansible доступным из вашего окружения.
    ```bash
    source hacking/env-setup
    ```

### Шаг 2: Создание файла модуля

Модули Ansible располагаются в директории `lib/ansible/modules/`. Создадим наш модуль.

```bash
touch lib/ansible/modules/clickhouse_user.py
```

### Шаг 3: Структура и скелет модуля

Каждый модуль Ansible — это Python-скрипт со специальной структурой.

```python
#!/usr/bin/python

from ansible.module_utils.basic import AnsibleModule

# 1. Секция документации (ОЧЕНЬ ВАЖНО)
DOCUMENTATION = r'''
---
module: clickhouse_user
short_description: Manages users in ClickHouse.
version_added: "1.0.0"
description:
    - Create, update, or delete users in a ClickHouse database.
options:
    login_user:
        description: The user to authenticate with.
        required: true
        type: str
    login_password:
        description: The password for the login_user.
        required: true
        type: str
        no_log: true
    user:
        description: The name of the user to manage.
        required: true
        type: str
    password:
        description: The password for the managed user.
        required: false
        type: str
        no_log: true
    state:
        description: The desired state of the user.
        choices: [ present, absent ]
        default: present
        type: str
author:
    - Your Name
'''

# 2. Примеры использования
EXAMPLES = r'''
# Create a user
- name: Create 'new_user'
  clickhouse_user:
    login_user: default
    login_password: ""
    user: new_user
    password: "secure_password"
    state: present

# Delete a user
- name: Delete 'new_user'
  clickhouse_user:
    login_user: default
    login_password: ""
    user: new_user
    state: absent
'''

# 3. Секция возвращаемых значений
RETURN = r'''
queries:
    description: A list of mutating queries that were executed.
    type: list
    returned: always
    sample: ['CREATE USER new_user IDENTIFIED BY password']
'''

def main():
    # 4. Определение аргументов модуля
    argument_spec = {
        "login_user": {"type": "str", "required": True},
        "login_password": {"type": "str", "required": True, "no_log": True},
        "user": {"type": "str", "required": True},
        "password": {"type": "str", "no_log": True},
        "state": {"type": "str", "default": "present", "choices": ['present', 'absent']},
    }

    # 5. Создание объекта модуля
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )
    
    # 6. Основная логика
    # ... (будет реализована ниже)

    # 7. Возврат результата
    result = {'changed': False, 'queries': []}
    
    if module.check_mode:
        module.exit_json(**result)

    # ... логика ...

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Шаг 4: Реализация логики

#### Обработка внешней зависимости

Нашему модулю для работы с ClickHouse понадобится библиотека `clickhouse-driver`. Модуль не должен устанавливать ее сам, но должен вежливо сообщить пользователю, если она отсутствует.

```python
# Поместить в начало файла
try:
    from clickhouse_driver import Client as CHClient
except ImportError:
    CHClient = None

def main():
    # ...
    module = AnsibleModule(...)

    if CHClient is None:
        module.fail_json(msg="The 'clickhouse-driver' Python library is required. Please install it with 'pip install clickhouse-driver'.")
    
    # ... остальная логика
```

#### Основная логика в `main`

```python
def main():
    # ... (спецификация аргументов и создание модуля) ...
    
    # Получение параметров
    user_to_manage = module.params['user']
    state = module.params['state']

    # Логика подключения к БД
    try:
        client = CHClient(
            host='localhost', 
            user=module.params['login_user'], 
            password=module.params['login_password']
        )
    except Exception as e:
        module.fail_json(msg=f"Failed to connect to ClickHouse: {e}")

    # Проверка существования пользователя (идемпотентность)
    user_exists = client.execute(
        "SELECT count() FROM system.users WHERE name = %(user)s",
        {'user': user_to_manage}
    )[0][0] > 0

    result = {'changed': False, 'queries': []}

    if module.check_mode:
        # В check_mode мы только предсказываем изменения
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
                module.fail_json(msg="Password is required when state=present")
            
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
```

### Шаг 5: Тестирование модуля

Тестирование модулей Ansible — это в первую очередь **интеграционное тестирование**. Вам понадобится реальное окружение.

1.  **Подготовить среду:** Запустить Docker-контейнер с ClickHouse и `sshd`.
2.  **Создать инвентарь:**
    ```ini
    # inventory.ini
    [clickhouse]
    ch_server ansible_host=172.17.0.2 ansible_user=root ansible_ssh_pass=password
    ```
3.  **Создать плейбук для теста:**
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
4.  **Запустить плейбук:**
    ```bash
    ansible-playbook -i inventory.ini test_module.yml
    ```

