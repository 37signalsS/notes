# Ansible — разработка собственных модулей

## Определения

- **Пользовательский модуль Ansible (Custom Module)** — это автономный сценарий (обычно на Python), расширяющий стандартную функциональность Ansible. Модули позволяют инкапсулировать сложную логику, обеспечивать идемпотентность и автоматизировать специфические задачи, для которых не подходят встроенные инструменты.
- **Module Utils** — общие Python-библиотеки (`plugins/module_utils/`), вынесенные из модулей для переиспользования. Содержат вспомогательные функции (клиенты API, парсеры, вспомогательные классы), которые используются несколькими модулями одновременно. Подробнее: [Использование module_utils](#использование-module_utils).
- **Check Mode (Dry Run)** — режим проверки, при котором модуль анализирует необходимые изменения, но не применяет их. Реализуется через `supports_check_mode=True` в `AnsibleModule`. Позволяет безопасно тестировать плейбуки командой `ansible-playbook --check`.
- **Diff Mode** — режим отображения разницы между текущим и желаемым состоянием. Реализуется через `supports_diff=True`. Выводит unified diff для текстовых файлов, что критично для audit--trейлов и review изменений.
- **FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.module_name` (например, `community.general.docker_image`). Использование FQCN обязательно для модулей в коллекциях и предотвращает конфликты имен.
- **AnsibleModule** — базовый класс из `ansible.module_utils.basic`, предоставляющий разработчику валидацию аргументов, обработку ошибок, поддержку check_mode/diff и формирование JSON-ответа. Все пользовательские модули создаются на его основе.

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
*   `elements`: тип элементов списка (для `type: list`).
*   `options`: вложенные аргументы (для `type: dict`).

#### Сложные ограничения

Ansible позволяет настраивать зависимости между аргументами:
*   `mutually_exclusive`: список параметров, которые нельзя использовать одновременно.
*   `required_if`: параметр X обязателен, если параметр Y имеет значение Z.
*   `required_one_of`: хотя бы один параметр из списка должен быть указан.
*   `required_together`: параметры, которые должны указываться только парой/группой.

#### Возврат результатов

Два основных метода завершения модуля:
*   `module.exit_json(**result)` — успешное завершение. Принимает любые ключи (обычно `changed`, `msg`, пользовательские данные).
*   `module.fail_json(msg="...")` — аварийная остановка с описанием ошибки. Обязательно передавать `msg`.

#### Принципы разработки (Best Practices)

*   **Идемпотентность:** модуль должен проверять текущее состояние и вносить изменения только при необходимости.
*   **Поддержка `check_mode`:** обязательная реализация `supports_check_mode=True` для безопасного тестирования (dry run).
*   **Поддержка `diff`:** вывод разницы между текущим и желаемым состоянием (`supports_diff=True`). Критично для текстовых конфигураций.
*   **Возвращаемые значения:** всегда возвращайте `changed` (boolean) и, при необходимости, детали изменений в JSON-формате.
*   **Документация:** наличие блоков `DOCUMENTATION`, `EXAMPLES` и `RETURN` внутри Python-файла обязательно для работы `ansible-doc`.
*   **Обработка ошибок:** используйте `module.fail_json(msg="...")` для аварийной остановки с понятным описанием причины.
*   **Логирование:** не используйте `print()` — для вывода информации в консоль Ansible используйте `module.exit_json()` с ключом `msg` или пользовательскими ключами.

### Переменные окружения для отладки

| Переменная | Назначение |
| :--- | :--- |
| `ANSIBLE_KEEP_REMOTE_FILES=1` | Сохраняет временные файлы на Managed Node (не удаляет после выполнения) |
| `ANSIBLE_DEBUG=1` | Включает расширенное логирование ядра Ansible |
| `ANSIBLE_VERBOSITY=3` | Увеличивает детализацию вывода (`-vvv`) |
| `PYTHONPATH=/path/to/modules` | Добавляет путь к пользовательским модулям |

## Предварительные требования

### Для разработки модулей

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| Python | 3.7 | 3.11+ |
| ansible-core | 2.14 | 2.17+ |
| pytest | 7.0 | 8.0+ |
| Docker / Podman | 20.0 | 24.0+ (для интеграционных тестов) |
| ansible-lint | 6.0 | 24.0+ (проверка стиля) |

### Проверка окружения

```bash
# Проверка версий
python3 --version       # → Python 3.11.x
ansible --version       # → ansible-core 2.17.x
pytest --version        # → pytest 8.x.x
docker --version        # → Docker version 24.x

# Проверка доступных модулей
ansible-doc -l | grep custom
```

### Структура директорий для модуля

**Вариант 1: Локальный модуль (простой)**
```text
my_project/
├── inventory.yml
├── site.yml
└── library/              # ← Сюда помещаются модули
    └── my_module.py
```

**Вариант 2: Модуль в роли**
```text
my_role/
├── tasks/
├── library/              # Модули доступны только внутри роли
│   └── my_module.py
└── module_utils/         # Общий код для модулей роли
    └── helpers.py
```

**Вариант 3: Модуль в коллекции (рекомендуется)**
```text
ansible_collections/my_namespace/my_collection/
├── galaxy.yml
├── plugins/
│   ├── modules/
│   │   └── my_module.py
│   └── module_utils/
│       └── helpers.py
└── tests/
    ├── sanity/
    ├── unit/
    └── integration/
        └── targets/
            └── my_module/
```

## Практические сценарии

### Пример 1: Минималистичный модуль «Hello World»

Создайте файл `library/hello_world.py`:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r'''
---
module: hello_world
short_description: Простой модуль для демонстрации
version_added: "1.0.0"
description:
    - Выводит приветствие и информацию о системе.
    - Полезен для проверки работы пользовательских модулей.
options:
    name:
        description: Имя пользователя для приветствия.
        required: false
        type: str
        default: "World"
author:
    - DevOps Team
'''

EXAMPLES = r'''
- name: Вывести приветствие
  hello_world:
    name: "Ansible"
  register: greeting

- name: Показать результат
  ansible.builtin.debug:
    var: greeting
'''

RETURN = r'''
msg:
    description: Текст приветствия.
    type: str
    returned: always
    sample: "Hello, Ansible!"
system_info:
    description: Информация о системе.
    type: dict
    returned: always
    sample: {"hostname": "web1.example.com", "python": "3.11.0"}
'''

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', default='World'),
        ),
        supports_check_mode=True
    )

    name = module.params['name']

    # Сбор информации о системе
    import socket
    import sys
    system_info = {
        'hostname': socket.gethostname(),
        'python': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

    result = {
        'changed': False,
        'msg': f"Hello, {name}!",
        'system_info': system_info,
    }

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

**Запуск и проверка:**

```bash
# Запуск плейбука
ansible-playbook -i "localhost," -c local site.yml
# → TASK [Вывести приветствие] ***************************************************
# → ok: [localhost] => {
#     "msg": "Hello, Ansible!",
#     "system_info": {
#         "hostname": "web1.example.com",
#         "python": "3.11.0"
#     }
# }

# Проверка документации модуля
ansible-doc ./library/hello_world.py
# → > HELLO_WORLD    (/path/to/library/hello_world.py)
# →   Выводит приветствие и информацию о системе.
```

### Пример 2: Модуль с внешними зависимостями (requests)

Для модулей, использующих сторонние библиотеки (например, `requests`), необходима проверка доступности перед работой:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

DOCUMENTATION = r'''
---
module: http_check
short_description: Проверка доступности HTTP-эндпоинта
version_added: "1.0.0"
description:
    - Проверяет, что HTTP-эндпоинт доступен и возвращает ожидаемый статус-код.
options:
    url:
        description: URL для проверки.
        required: true
        type: str
    expected_status:
        description: Ожидаемый HTTP-код ответа.
        type: int
        default: 200
    timeout:
        description: Таймаут ожидания ответа (секунды).
        type: int
        default: 10
author:
    - DevOps Team
'''

EXAMPLES = r'''
- name: Проверить доступность API
  http_check:
    url: "https://api.example.com/health"
    expected_status: 200
    timeout: 5
  register: health_check

- name: Показать статус
  ansible.builtin.debug:
    msg: "HTTP {{ health_check.status_code }} (ожидался {{ health_check.expected_status }})"
'''

RETURN = r'''
status_code:
    description: Полученный HTTP-код ответа.
    type: int
    returned: always
    sample: 200
elapsed:
    description: Время ответа в секундах.
    type: float
    returned: always
    sample: 0.342
'''

def main():
    module = AnsibleModule(
        argument_spec=dict(
            url=dict(type='str', required=True),
            expected_status=dict(type='int', default=200),
            timeout=dict(type='int', default=10),
        ),
        supports_check_mode=True
    )

    if not HAS_REQUESTS:
        module.fail_json(msg="Библиотека 'requests' не найдена. Установите: pip install requests")

    url = module.params['url']
    expected_status = module.params['expected_status']
    timeout = module.params['timeout']

    try:
        response = requests.get(url, timeout=timeout)
        status_code = response.status_code
        elapsed = response.elapsed.total_seconds()
    except requests.exceptions.RequestException as e:
        module.fail_json(msg=f"Ошибка запроса к {url}: {str(e)}")

    result = {
        'changed': False,
        'status_code': status_code,
        'expected_status': expected_status,
        'elapsed': elapsed,
        'msg': f"HTTP {status_code} (ожидался {expected_status})",
    }

    if status_code != expected_status:
        module.fail_json(msg=f"Неверный статус-код: получен {status_code}, ожидался {expected_status}", **result)

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Пример 3: CLI-обертка с `run_command`

Для модулей, которые являются обертками над существующими CLI-утилитами, используйте `module.run_command`:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r'''
---
module: docker_image_info
short_description: Получение информации об Docker-образе
version_added: "1.0.0"
description:
    - Возвращает размер и количество слоёв Docker-образа через docker inspect.
options:
    image:
        description: Имя Docker-образа (например, nginx:latest).
        required: true
        type: str
author:
    - DevOps Team
'''

EXAMPLES = r'''
- name: Получить информацию об образе
  docker_image_info:
    image: "nginx:latest"
  register: image_info

- name: Показать размер образа
  ansible.builtin.debug:
    msg: "Размер: {{ image_info.size_mb }} MB, Слоёв: {{ image_info.layers }}"
'''

RETURN = r'''
size_mb:
    description: Размер образа в мегабайтах.
    type: float
    returned: always
    sample: 187.5
layers:
    description: Количество слоёв в образе.
    type: int
    returned: always
    sample: 6
'''

def main():
    module = AnsibleModule(
        argument_spec=dict(
            image=dict(type='str', required=True),
        ),
        supports_check_mode=True
    )

    image = module.params['image']

    # Проверка наличия docker
    rc, stdout, stderr = module.run_command(["docker", "--version"])
    if rc != 0:
        module.fail_json(msg="Docker не найден. Установите Docker.")

    # Получение информации об образе
    rc, stdout, stderr = module.run_command(
        ["docker", "inspect", "--format", "{{.Size}} {{len .RootFS.Layers}}", image]
    )

    if rc != 0:
        module.fail_json(msg=f"Ошибка получения информации об образе: {stderr}")

    try:
        parts = stdout.strip().split()
        size_bytes = int(parts[0])
        layers = int(parts[1])
        size_mb = round(size_bytes / (1024 * 1024), 2)
    except (IndexError, ValueError) as e:
        module.fail_json(msg=f"Ошибка парсинга вывода docker inspect: {str(e)}")

    module.exit_json(
        changed=False,
        size_mb=size_mb,
        layers=layers,
        image=image,
    )

if __name__ == '__main__':
    main()
```

### Пример 4: Модуль с `check_mode`, `diff` и сложной логикой

Полноценный пример с поддержкой всех режимов:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import json
from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r'''
---
module: config_file
short_description: Управление конфигурационным файлом
version_added: "1.0.0"
description:
    - Создает или обновляет конфигурационный файл с поддержкой check_mode и diff.
options:
    path:
        description: Путь к конфигурационному файлу.
        required: true
        type: path
    settings:
        description: Словарь настроек для записи в файл.
        type: dict
    owner:
        description: Владелец файла.
        type: str
    mode:
        description: Права доступа к файлу (в формате octal).
        type: str
        default: '0644'
author:
    - DevOps Team
'''

EXAMPLES = r'''
- name: Создать конфигурационный файл
  config_file:
    path: /etc/myapp/config.json
    settings:
      debug: true
      port: 8080
      log_level: info
    owner: root
    mode: '0644'
  register: config_result

- name: Показать изменения
  ansible.builtin.debug:
    var: config_result.diff
'''

RETURN = r'''
diff:
    description: Разница между текущим и новым содержимым файла.
    type: dict
    returned: always
    sample: {"before": "...", "after": "..."}
backup_file:
    description: Путь к резервной копии (если файл существовал).
    type: str
    returned: when changed
    sample: /etc/myapp/config.json.bak
'''

def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type='path', required=True),
            settings=dict(type='dict', required=True),
            owner=dict(type='str', default='root'),
            mode=dict(type='str', default='0644'),
        ),
        supports_check_mode=True,
        supports_diff=True,
    )

    path = module.params['path']
    settings = module.params['settings']
    owner = module.params['owner']
    mode = module.params['mode']

    result = {
        'changed': False,
        'diff': {'before': '', 'after': ''},
    }

    # Чтение текущего файла
    current_content = None
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                current_content = f.read()
        except IOError as e:
            module.fail_json(msg=f"Ошибка чтения файла {path}: {str(e)}")

    # Формирование нового содержимого
    new_content = json.dumps(settings, indent=4, sort_keys=True) + "\n"

    # Сравнение
    if current_content == new_content:
        module.exit_json(**result)

    result['changed'] = True

    # Diff
    if current_content:
        result['diff']['before'] = current_content
    else:
        result['diff']['before'] = "(file does not exist)"
    result['diff']['after'] = new_content

    # Backup
    if current_content and os.path.exists(path):
        backup_path = path + ".bak"
        if not module.check_mode:
            try:
                with open(backup_path, 'w') as f:
                    f.write(current_content)
            except IOError as e:
                module.fail_json(msg=f"Ошибка создания бэкапа: {str(e)}")
        result['backup_file'] = backup_path

    # Запись
    if not module.check_mode:
        try:
            with open(path, 'w') as f:
                f.write(new_content)
            # Установка прав
            os.chmod(path, int(mode, 8))
        except IOError as e:
            module.fail_json(msg=f"Ошибка записи файла {path}: {str(e)}")

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Пример 5: Unit-тест модуля (pytest)

Для тестирования логики модуля без запуска Ansible используйте `pytest`:

```python
# tests/unit/test_hello_world.py
import pytest
import sys
import os

# Добавляем путь к модулю
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'library'))

from hello_world import main as hello_main
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes


def setup_module(args):
    """Хелпер для настройки модуля в тестах."""
    if not hasattr(basic, '_original_exit_json'):
        basic._original_exit_json = basic.AnsibleModule.exit_json
    if not hasattr(basic, '_original_fail_json'):
        basic._original_fail_json = basic.AnsibleModule.fail_json

    basic.AnsibleModule.exit_json = lambda self, **kwargs: (_ for _ in ()).throw(SystemExit(0, kwargs))
    basic.AnsibleModule.fail_json = lambda self, **kwargs: (_ for _ in ()).throw(SystemExit(1, kwargs))

    return args


def test_hello_world_default():
    """Тест модуля с параметрами по умолчанию."""
    args = {
        'ANSIBLE_MODULE_ARGS': {
            'name': {'type': 'str', 'default': 'World'},
        }
    }

    with pytest.raises(SystemExit) as exc_info:
        sys.argv = ['test_module']
        basic.ANSIBLE_MODULE_ARGS = args
        hello_main()

    result = exc_info.value.args[1]
    assert result['changed'] is False
    assert result['msg'] == "Hello, World!"
    assert 'system_info' in result
    assert 'hostname' in result['system_info']


def test_hello_world_custom_name():
    """Тест модуля с кастомным именем."""
    args = {
        'ANSIBLE_MODULE_ARGS': {
            'name': {'type': 'str', 'default': 'World'},
        }
    }

    with pytest.raises(SystemExit) as exc_info:
        basic.ANSIBLE_MODULE_ARGS = args
        hello_main()

    result = exc_info.value.args[1]
    assert "Hello, World!" in result['msg']
```

**Запуск тестов:**

```bash
# Установка pytest
pip install pytest

# Запуск тестов
pytest tests/unit/test_hello_world.py -v
# → test_hello_world_default PASSED
# → test_hello_world_custom_name PASSED
# → 2 passed in 0.05s
```

### Пример 6: Интеграционный тест через ansible-test

Для тестирования модуля в коллекции:

```yaml
# tests/integration/targets/my_module/tasks/main.yml
---
- name: Тест модуля hello_world
  block:
    - name: Вызов модуля
      my_namespace.my_collection.hello_world:
        name: "TestUser"
      register: result

    - name: Проверка результата
      ansible.builtin.assert:
        that:
          - result.changed == false
          - result.msg == "Hello, TestUser!"
          - result.system_info.hostname is defined

    - name: Проверка без параметров
      my_namespace.my_collection.hello_world:
      register: result_default

    - name: Проверка значения по умолчанию
      ansible.builtin.assert:
        that:
          - result_default.msg == "Hello, World!"
```

**Запуск:**

```bash
# Из корня коллекции
ansible-test integration my_module -v
# → ██ Integration: my_namespace.my_collection.my_module
# → Задачи выполнены: ok=3  changed=0  unreachable=0  failed=0
```

### Пример 7: Модуль с валидацией и `mutually_exclusive`

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r'''
---
module: service_manager
short_description: Управление сервисом (systemd/init)
version_added: "1.0.0"
description:
    - Запускает, останавливает или перезапускает системный сервис.
options:
    name:
        description: Имя сервиса.
        required: true
        type: str
    state:
        description: Желаемое состояние.
        choices: [ started, stopped, restarted, reloaded ]
        type: str
        required: true
    enabled:
        description: Автозапуск при загрузке.
        type: bool
        default: false
author:
    - DevOps Team
'''

EXAMPLES = r'''
- name: Запустить и включить nginx
  service_manager:
    name: nginx
    state: started
    enabled: true
'''

RETURN = r'''
state:
    description: Текущее состояние сервиса.
    type: str
    returned: always
'''

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', required=True, choices=['started', 'stopped', 'restarted', 'reloaded']),
            enabled=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']
    state = module.params['state']
    enabled = module.params['enabled']

    # Проверка наличия systemctl
    rc, stdout, stderr = module.run_command(["systemctl", "is-active", name])
    current_state = stdout.strip()

    result = {'changed': False, 'name': name, 'state': current_state}

    # Определение необходимых действий
    if state == 'started' and current_state != 'active':
        result['changed'] = True
        if not module.check_mode:
            rc, stdout, stderr = module.run_command(["systemctl", "start", name])
            if rc != 0:
                module.fail_json(msg=f"Ошибка запуска {name}: {stderr}")

    elif state == 'stopped' and current_state == 'active':
        result['changed'] = True
        if not module.check_mode:
            rc, stdout, stderr = module.run_command(["systemctl", "stop", name])
            if rc != 0:
                module.fail_json(msg=f"Ошибка остановки {name}: {stderr}")

    elif state in ('restarted', 'reloaded'):
        result['changed'] = True
        if not module.check_mode:
            cmd = "restart" if state == 'restart' else "reload"
            rc, stdout, stderr = module.run_command(["systemctl", cmd, name])
            if rc != 0:
                module.fail_json(msg=f"Ошибка {state} {name}: {stderr}")

    # Управление автозапуском
    rc, stdout, stderr = module.run_command(["systemctl", "is-enabled", name])
    is_enabled = stdout.strip() == 'enabled'

    if enabled and not is_enabled:
        result['changed'] = True
        if not module.check_mode:
            module.run_command(["systemctl", "enable", name])
    elif not enabled and is_enabled:
        result['changed'] = True
        if not module.check_mode:
            module.run_command(["systemctl", "disable", name])

    # Обновление текущего состояния
    rc, stdout, stderr = module.run_command(["systemctl", "is-active", name])
    result['state'] = stdout.strip()

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

## Типичные ошибки и их решение (Troubleshooting)

### 1. «Module import error» — ошибка импорта модуля

**Симптом:** `Failed to import the required Python library`.

**Диагностика:**
```bash
# Проверка Python на Managed Node
ansible all -m command -a "python3 --version"
```

**Решение:** Убедитесь, что Python 3.7+ установлен на Managed Node. Дляbootstrap используйте `ansible.builtin.raw`.

### 2. «Module failure» — падение модуля с невнятной ошибкой

**Симптом:** Модуль падает без понятного описания.

**Решение:**
```bash
# Сохранение временных файлов на Managed Node
ANSIBLE_KEEP_REMOTE_FILES=1 ansible-playbook site.yml

# Подключение к Managed Node и запуск модуля вручную
ssh managed_node
python3 ~/.ansible/tmp/ansible-tmp-.../AnsiballZ_my_module.py explode
cd debug_dir
python3 ansible_module_my_module.py args.json
```

### 3. «Check mode не работает» — модуль применяет изменения в check_mode

**Симптом:** `ansible-playbook --check` применяет реальные изменения.

**Причина:** В `AnsibleModule` не указан `supports_check_mode=True` или отсутствует проверка `module.check_mode`.

**Решение:**
```python
module = AnsibleModule(
    argument_spec=argument_spec,
    supports_check_mode=True  # ← Обязательно
)

if not module.check_mode:
    # Реальное изменение
    do_something()
```

### 4. «Argument validation error» — невалидные аргументы

**Симптом:** `Unsupported parameters: (unknown)`.

**Диагностика:** Проверьте `argument_spec` — все параметры, передаваемые в модуль, должны быть объявлены.

### 5. «JSON decode error» — невалидный JSON в ответе

**Симптом:** Модуль завершается, но Ansible не может распарсить ответ.

**Причина:** В stdout модуля попадает мусор (print, логи, traceback).

**Решение:** Убедитесь, что в модуле нет `print()`. Используйте `module.exit_json()` и `module.fail_json()`.

### 6. «Permission denied» при записи файлов

**Симптом:** Модуль не может записать файл на Managed Node.

**Решение:** Добавьте `become: true` в задачу или используйте `module.run_command` с `sudo`.

## Дополнительная информация

### Использование module_utils

Если логика (например, клиент для API или парсер конфигураций) используется в нескольких модулях, её необходимо вынести в `module_utils`. Это сокращает дублирование кода и упрощает тестирование.

#### Стандартные библиотеки Ansible

Ansible предоставляет богатый набор готовых утилит в `ansible.module_utils`:
*   `urls`: Безопасная работа с HTTP/HTTPS запросами (обертка над `urllib`), поддержка прокси и сертификатов.
*   `common.text.converters`: Преобразование типов данных (например, `to_bytes`, `to_text`, `to_native`).
*   `json`: Работа с JSON с учетом особенностей Python 2/3.
*   `basic.AnsibleModule`: Базовый класс для всех модулей.
*   `six`: Совместимость Python 2/3 (используйте только при необходимости поддержки legacy-систем).

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

### Контрольный список перед публикацией модуля

- [ ] Модуль использует FQCN (полное имя коллекции)
- [ ] Реализован `supports_check_mode=True`
- [ ] Модуль идемпотентен (не ломается при повторном запуске)
- [ ] Заполнены блоки `DOCUMENTATION`, `EXAMPLES`, `RETURN`
- [ ] Нет `print()` — используется `module.exit_json()` / `module.fail_json()`
- [ ] Внешние зависимости проверены через try/except с `HAS_*`
- [ ] Модуль не логирует пароли (`no_log: true` для чувствительных параметров)
- [ ] Пройдены sanity-тесты (`ansible-test sanity`)
- [ ] Написаны unit-тесты (`pytest`)
- [ ] Написаны integration-тесты (`ansible-test integration`)

### Смотрите также

- [Тестирование через ansible-test](./ansible-test.md) — полное руководство по тестированию модулей и плагинов.
- [Разработка Action-плагинов](./ansible-action-plugins.md) — расширение логики выполнения на Control Node.
- [Разработка Callback-плагинов](./ansible-callback-plugins.md) — перехват событий и интеграция с внешними системами.
