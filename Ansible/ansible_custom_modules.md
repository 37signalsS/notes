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
    *   **Разработка:** подробнее см. **[Разработка Action-плагинов](./ansible-action-plugins.md)** и **[Разработка Callback-плагинов](./ansible-callback-plugins.md)**.

### Жизненный цикл выполнения модуля

1.  **Сборка**: Ansible (на Control Node) находит код модуля, извлекает зависимости из `module_utils` и упаковывает всё в один zip-файл (модуль становится автономным).
2.  **Передача**: Файл копируется на целевой узел во временную директорию (по умолчанию `~/.ansible/tmp/`).
3.  **Исполнение**: Ansible запускает Python-интерпретатор на удаленном узле, распаковывает архив и выполняет код.
4.  **Возврат**: Модуль возвращает JSON-структуру в stdout, которую перехватывает Control Node.
5.  **Очистка**: Временные файлы удаляются (если не включен режим отладки).

### Системные требования и Python

*   **Контрольный узел:** требует актуальную версию Python (3.9+ для последних версий Ansible).
*   **Управляемый узел:**
    *   Для **Ansible 2.17+** требуется минимум **Python 3.7**.
    *   Если Python отсутствует или версия слишком старая, можно использовать модули на Bash или PowerShell (для Windows).
*   **Универсальность:** Код модуля должен быть совместим с различными минорными версиями Python, если планируется поддержка старых дистрибутивов ОС.

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

### Использование AnsibleModule

Класс `AnsibleModule` из `ansible.module_utils.basic` — это основной инструмент разработчика. Он автоматизирует валидацию входных данных и формирование ответа.

#### Валидация аргументов (`argument_spec`)

Позволяет декларативно описать ожидаемые параметры:
*   `type`: тип данных (`str`, `int`, `bool`, `list`, `dict`, `float`, `path`).
*   `required`: обязательность параметра.
*   `choices`: список допустимых значений.
*   `default`: значение по умолчанию.
*   `no_log`: маскировка чувствительных данных в логах.

#### Сложные ограничения

Ansible позволяет настраивать зависимости между аргументами:
*   `mutually_exclusive`: список параметров, которые нельзя использовать одновременно.
*   `required_if`: параметр X обязателен, если параметр Y имеет значение Z.
*   `required_one_of`: хотя бы один параметр из списка должен быть указан.
*   `required_together`: параметры, которые должны указываться только парой/группой.

#### Принципы разработки (Best Practices)

*   **Идемпотентность:** модуль должен проверять текущее состояние и вносить изменения только при необходимости.
*   **Поддержка `check_mode`:** обязательная реализация `supports_check_mode=True` для безопасного тестирования (dry run).
*   **Поддержка `diff`:** вывод разницы между текущим и желаемым состоянием (`supports_diff=True`). Критично для текстовых конфигураций.
*   **Возвращаемые значения:** всегда возвращайте `changed` (boolean) и, при необходимости, детали изменений в JSON-формате.
*   **Документация:** наличие блоков `DOCUMENTATION`, `EXAMPLES` и `RETURN` внутри Python-файла обязательно для работы `ansible-doc`.
*   **Обработка ошибок:** используйте `module.fail_json(msg="...")` для аварийной остановки с понятным описанием причины.

## Практические сценарии

### Пример: Создание модуля `clickhouse_user` с поддержкой `diff`

Ниже представлен пример модуля для управления пользователями в ClickHouse. В данной версии реализована поддержка `check_mode` и `diff`, что позволяет видеть планируемые изменения.

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
        description: Пользователь для аутентификации в ClickHouse (обычно default).
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
- name: Создать пользователя ClickHouse с паролем
  clickhouse_user:
    login_user: default
    login_password: "{{ ch_admin_password }}"
    user: readonly_user
    password: "secure_password"
    state: present

- name: Удалить пользователя
  clickhouse_user:
    login_user: default
    login_password: "{{ ch_admin_password }}"
    user: old_user
    state: absent
'''

RETURN = r'''
queries:
    description: Список выполненных SQL-запросов.
    type: list
    returned: always
    sample: ["CREATE USER readonly_user IDENTIFIED BY 'password'"]
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

    if not HAS_CH_DRIVER:
        module.fail_json(msg="Библиотека 'clickhouse-driver' не найдена. Установите её через pip.")

    user = module.params['user']
    state = module.params['state']
    
    # Структура для поддержки режима diff
    result = {
        'changed': False, 
        'queries': [],
        'diff': {'before': '', 'after': ''}
    }

    try:
        client = CHClient(
            host='localhost',
            user=module.params['login_user'],
            password=module.params['login_password']
        )
        client.execute('SELECT 1')
    except Exception as e:
        module.fail_json(msg=f"Ошибка подключения к ClickHouse: {str(e)}")

    # Проверка существования пользователя
    user_exists = client.execute(
        "SELECT count() FROM system.users WHERE name = %(user)s",
        {'user': user}
    )[0][0] > 0

    # Определение необходимых действий
    if state == 'present' and not user_exists:
        password = module.params.get('password')
        if not password:
            module.fail_json(msg="Пароль обязателен при создании пользователя.")
        
        query = f"CREATE USER {user} IDENTIFIED BY '***'"
        result['changed'] = True
        result['diff']['before'] = f"User '{user}' does not exist"
        result['diff']['after'] = f"CREATE USER {user}"
        
        if not module.check_mode:
            real_query = "CREATE USER %(user)s IDENTIFIED BY %(password)s"
            client.execute(real_query, {'user': user, 'password': password})
            result['queries'].append(query)

    elif state == 'absent' and user_exists:
        query = f"DROP USER {user}"
        result['changed'] = True
        result['diff']['before'] = f"User '{user}' exists"
        result['diff']['after'] = f"DROP USER {user}"
        
        if not module.check_mode:
            client.execute(query)
            result['queries'].append(query)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Тестирование и отладка

Для профессиональной разработки и валидации контента в составе коллекций используется инструмент **[ansible-test](./ansible-test.md)**. Он позволяет запускать:
*   **Sanity-тесты** (статический анализ).
*   **Unit-тесты** (модульное тестирование логики).
*   **Integration-тесты** (проверка в изолированных Docker-контейнерах).
*   **Анализ покрытия кода** (Coverage).

Подробные сценарии запуска и настройки описаны в основном разделе: **[Тестирование через ansible-test](./ansible-test.md)**.

#### Ручная отладка через `ANSIBLE_KEEP_REMOTE_FILES`
    Если модуль падает с невнятной ошибкой, установите переменную окружения `ANSIBLE_KEEP_REMOTE_FILES=1`. Ansible не удалит временный файл на удаленном узле. Вы сможете зайти на хост и запустить его вручную:
    ```bash
    python3 ~/.ansible/tmp/ansible-tmp-.../AnsiballZ_clickhouse_user.py explode
    cd debug_dir
    python3 ansible_module_clickhouse_user.py args.json
    ```

## Дополнительная информация

### Использование module_utils

Если логика (например, клиент для API или парсер конфигураций) используется в нескольких модулях, её необходимо вынести в `module_utils`. Это сокращает дублирование кода и упрощает тестирование.

#### Стандартные библиотеки Ansible

Ansible предоставляет богатый набор готовых утилит в `ansible.module_utils`:
*   `urls`: Безопасная работа с HTTP/HTTPS запросами (обертка над `urllib`), поддержка прокси и сертификатов.
*   `common.text.converters`: Преобразование типов данных (например, `to_bytes`, `to_text`, `to_native`).
*   `json`: Работа с JSON с учетом особенностей Python 2/3.
*   `basic.AnsibleModule`: Базовый класс для всех модулей.

#### Пример выноса логики в коллекции

1.  **Создание библиотеки** (`plugins/module_utils/api_client.py`):
    ```python
    def get_api_status(url):
        # Логика запроса
        return {"status": "ok"}
    ```

2.  **Импорт в модуле** (`plugins/modules/my_module.py`):
    ```python
    from ansible_collections.my_ns.my_col.plugins.module_utils.api_client import get_api_status
    ```

#### Запуск внешних команд (`run_command`)

Для модулей, которые являются обертками над CLI-утилитами, используйте встроенный метод `module.run_command`. Он безопаснее `subprocess.run`, так как корректно обрабатывает окружение и логирование.

```python
rc, stdout, stderr = module.run_command(["/usr/bin/clickhouse-client", "--query", "SELECT 1"])
if rc != 0:
    module.fail_json(msg="Ошибка выполнения команды", stdout=stdout, stderr=stderr)
```

### Смотрите также

*   [Обзор модулей Ansible](./Modules/ansible_modules_overview.md) — базовые принципы работы.
*   [Ансбиль — роли и коллекции](./ansible_roles.md) — структура и распространение контента.
*   [Официальный Module Development Guide](https://docs.ansible.com/ansible/latest/dev_guide/developing_modules_general.html) (EN).
